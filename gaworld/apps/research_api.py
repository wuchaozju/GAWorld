"""Dashboard backend for 研究工作台 — the research workbench panel.

A *delegate* module following the ``interview_api`` precedent: the dashboard
server forwards everything under ``/api/research/`` here.

An analysis is a **job**, not a request handler. One plan is a single model
call, but it is a long one — the prompt carries the whole capability
catalogue plus up to a paper's worth of text, and the answer is a structured
document of several thousand tokens. On a local model that is minutes, which
no browser request should sit on. Start it, poll it, read the plan when it
lands — the same shape the interview and population panels use.

A **study** carries a plan the rest of the way: compile it into a
pre-registered protocol (a job), wait for approval, run its seeds as
parallel worlds experiments (an independent job per study), score the
predictions, ask the model to read the numbers, and write the report. The
stages live in :mod:`gaworld.research.study`; this module only moves a
study between them and keeps the handles to pause and stop a run.

Those handles are in memory, so they die with the process. A study found at
``running`` without a live job here was interrupted — a restart, a crash, a
Ctrl-C — and is marked as such on the next read rather than showing 运行中
forever; from there 停止 tidies the record and 重置 puts it back where it can
run again, under a fresh experiment id so the previous attempt survives.
"""

from __future__ import annotations

import base64
import copy
import json
import threading
import time
import traceback
import uuid
from functools import wraps
from pathlib import Path
from typing import Any

from gaworld.accounts import ownership
from gaworld.apps import world_paths
from gaworld.logging_setup import get_logger
from gaworld.research import workspaces
from gaworld.research.progress import RunTiming

_LOG = get_logger("gaworld.dashboard.research")

#: job id → record. One table per delegate, matching ``interview_api``.
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 10

#: Uploaded PDFs are decoded server-side; past this the file is a scanned
#: book, not a paper, and the text would be cut at ``MAX_MATERIAL_CHARS``
#: anyway.
MAX_UPLOAD_B64 = 30_000_000


# ---------------------------------------------------------------------------
# Job plumbing
# ---------------------------------------------------------------------------


def _new_job(kind: str) -> str:
    job_id = f"{kind}-{uuid.uuid4().hex[:8]}"
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "running",
            "progress": 0.0,
            "message": "启动中…",
            "started_at": time.time(),
            "finished_at": None,
            "result": None,
            "error": None,
            "paused": False,
            "stopping": False,
            "_timing": RunTiming(),
            "_events": [],
            **workspaces.stamp(),
        }
        finished = [
            (record["started_at"], key) for key, record in _JOBS.items() if record["status"] != "running"
        ]
        while len(_JOBS) > _MAX_JOBS and finished:
            finished.sort()
            _, oldest = finished.pop(0)
            _JOBS.pop(oldest, None)
    return job_id


def _update_job(job_id: str, **fields: Any) -> None:
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        if record is not None:
            event = None
            if fields.get("message") and fields["message"] != record.get("message"):
                event = {
                    "time": time.time(),
                    "message": fields["message"],
                    "progress": fields.get("progress", record.get("progress")),
                    "status": fields.get("status", record.get("status")),
                }
                record["_events"] = [*(record.get("_events") or []), event][-100:]
            event_path = fields.get("_event_log") or record.get("_event_log")
            if event_path and (event or "_event_log" in fields):
                Path(event_path).parent.mkdir(parents=True, exist_ok=True)
                pending = record.get("_events", []) if "_event_log" in fields else [event]
                with open(event_path, "a", encoding="utf-8") as handle:
                    for item in pending:
                        handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            # A control request may have captured its handle just before the
            # worker completed. Terminal records must stay terminal in the UI.
            if record["status"] != "running":
                for key in ("paused", "stopping"):
                    if key in fields:
                        fields[key] = False
            timing = record.get("_timing")
            if timing is not None:
                if "paused" in fields:
                    timing.set_paused(bool(fields["paused"]))
                if fields.get("status") in {"done", "stopped", "error"}:
                    timing.finish()
            if "progress" in fields:
                fields["progress"] = max(record.get("progress", 0.0), min(1.0, fields["progress"]))
            record.update(fields)


def _run_in_background(job_id: str, work: Any) -> None:
    def runner() -> None:
        try:
            from gaworld.llm.run_state import ledger_context

            with _JOBS_LOCK:
                ledger_path = str((_JOBS.get(job_id) or {}).get("_ledger_path") or "")
            with ledger_context(ledger_path):
                result = work(lambda p, m: _update_job(job_id, progress=p, message=m))
            stopped = bool(isinstance(result, dict) and result.get("stopped"))
            _update_job(
                job_id,
                status="stopped" if stopped else "done",
                **({} if stopped else {"progress": 1.0}),
                message="已停止" if stopped else "完成",
                paused=False,
                stopping=False,
                result=result,
                finished_at=time.time(),
            )
        except Exception as exc:
            _LOG.exception("research job %s failed", job_id)
            _update_job(
                job_id,
                status="error",
                message=str(exc),
                error={"type": type(exc).__name__, "detail": traceback.format_exc(limit=5)},
                paused=False,
                stopping=False,
                finished_at=time.time(),
            )

    ownership.spawn(runner, name=f"research-{job_id}")


def job_status(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        if not record or not workspaces.visible(record):
            return None
        snapshot = {key: value for key, value in record.items() if not key.startswith("_")}
        timing = record.get("_timing")
        if timing is not None:
            snapshot.update(timing.snapshot(float(record.get("progress") or 0)))
        if record.get("stopping"):
            snapshot["remaining_seconds"] = None
        ledger_path = record.get("_ledger_path")
    if ledger_path:
        from gaworld.llm.run_state import RunLedger

        snapshot["telemetry"] = RunLedger(str(ledger_path)).snapshot()
    with _ACTIVE_LOCK:
        active = _active(str(record.get("study_id") or ""))
        runner = active.get("runner") if active.get("job_id") == job_id else None
    if runner is not None:
        snapshot["worlds"] = runner.snapshot()["worlds"]
        snapshot["queued_seconds"] = sum(
            float(w.get("queued_seconds") or 0)
            + (
                max(0, time.time() - w["queued_at"])
                if w.get("waiting_for_slot") and w.get("queued_at")
                else 0
            )
            for w in snapshot["worlds"]
        )
    return json.loads(json.dumps(snapshot, ensure_ascii=False), parse_constant=lambda _: None)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _providers() -> list[dict[str, Any]]:
    """Configured LLM backends, so the panel's model picker is real.

    Mirrors ``interview_api._providers``: an unreadable registry degrades the
    picker to "按配置路由" rather than breaking the whole panel.
    """
    try:
        from gaworld.llm.providers import available_providers

        return list(available_providers())
    except Exception:
        _LOG.warning("could not read the LLM provider registry", exc_info=True)
        return []


def context() -> dict[str, Any]:
    """Everything the panel needs before its first render, in one request."""
    from gaworld import accounts
    from gaworld.accounts.context import USER
    from gaworld.research import measures, workbench
    from gaworld.research import study as study_mod
    from gaworld.research.protocol import DEFAULT_CALL_BUDGET

    catalogue = workbench.load_catalogue()
    user = USER.get() or {}
    _heal_all()
    return {
        "providers": _providers(),
        "catalogue": {
            "path": workbench.CATALOGUE_PATH,
            "chars": len(catalogue),
            "available": bool(catalogue),
        },
        "limits": {"material_chars": workbench.MAX_MATERIAL_CHARS, "call_budget": DEFAULT_CALL_BUDGET},
        "plans": workspaces.owned(workbench.list_plans()),
        # Only admins start studies, so only they see them.
        "studies": workspaces.owned(study_mod.list_studies()),
        "measures": len(measures.registry()),
        "workspace": {
            "mode": "multi_user" if user or accounts.enabled_store(_repo_root()) else "single_user",
            "owner": user.get("nickname") or "",
            "world_id": workspaces.stamp()["world_id"],
        },
    }


def plans() -> dict[str, Any]:
    from gaworld.research import workbench

    return {"plans": workspaces.owned(workbench.list_plans())}


def plan_detail(plan_id: str) -> dict[str, Any] | None:
    """The plan, or None when it does not exist or is someone else's."""
    from gaworld.research import workbench

    plan = workbench.load_plan(plan_id)
    return plan if workspaces.visible(plan) else None


def export_markdown(plan_id: str) -> dict[str, Any]:
    """The downloadable document plus the filename the browser should use.

    JSON rather than a file response, as every other export in this dashboard
    is, so the frontend keeps one download path.
    """
    from gaworld.research import workbench

    plan = plan_detail(plan_id)
    if plan is None:
        raise ValueError(f"找不到方案 {plan_id}")
    markdown = str(plan.get("markdown") or "")
    if not markdown:
        markdown = workbench.render_markdown(workbench.ResearchPlan.from_dict(plan))
    title = str(plan.get("title") or "研究方案").strip() or "研究方案"
    safe = "".join(char if char.isalnum() or char in "-_（）()" else "_" for char in title)[:40]
    return {
        "filename": f"{safe or 'research-plan'}-{plan_id}.md",
        "markdown": markdown,
        "bytes": len(markdown.encode("utf-8")),
    }


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def start_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate, then analyse in the background."""
    from gaworld.research import workbench

    # Validate before returning a job id: an empty textarea should come back
    # as a 400 the user can fix, not as a job that fails a second later.
    request = workbench.normalize_request(payload)
    job_id = _new_job("plan")

    def work(report: Any) -> dict[str, Any]:
        from gaworld.llm.providers import call_llm, resolve_provider

        provider = request["provider"] or None
        try:
            routed = resolve_provider(task="research", provider=provider)
        except Exception:  # an unknown name is reported by call_llm itself
            routed = request["provider"]
        report(0.1, f"正在用 {routed or '默认模型'} 分析…")

        def llm_fn(prompt: str) -> str:
            return call_llm(
                prompt,
                task="research",
                provider=provider,
                max_tokens=workbench.PLAN_MAX_TOKENS,
            )

        plan = workbench.analyze(request, llm_fn=llm_fn, provider=routed)
        report(0.9, "正在保存方案…")
        workbench.save_plan(plan, workspaces.stamp())
        return {"plan_id": plan.id, "title": plan.title, "feasibility": plan.feasibility}

    _run_in_background(job_id, work)
    return {"job_id": job_id, "kind": request["kind"], "truncated": request["truncated"]}


def start_digest(payload: dict[str, Any]) -> dict[str, Any]:
    """Step one for a paper: read it in the background, return the digest.

    The digest is not saved — it is the job's result, which the panel shows
    for editing and then sends back with ``/analyze``.
    """
    from gaworld.research import workbench

    request = workbench.normalize_request({**payload, "kind": "paper"})
    job_id = _new_job("digest")

    def work(report: Any) -> dict[str, Any]:
        from gaworld.llm.providers import call_llm

        provider = request["provider"] or None
        report(0.1, "正在解读论文…")
        return workbench.digest_paper(
            request,
            llm_fn=lambda prompt: call_llm(
                prompt, task="research", provider=provider, max_tokens=workbench.DIGEST_MAX_TOKENS
            ),
        )

    _run_in_background(job_id, work)
    return {"job_id": job_id, "truncated": request["truncated"]}


def extract_text(payload: dict[str, Any]) -> dict[str, Any]:
    """Text out of an uploaded paper, for the textarea.

    Plain text and Markdown are decoded as-is. PDF needs ``pypdf``, which is
    not a runtime dependency; without it the user is told to paste the text,
    which is what the field takes anyway.
    """
    name = str(payload.get("name") or "").strip()
    raw = str(payload.get("data") or "")
    if raw.startswith("data:"):
        raw = raw.partition(",")[2]
    if not raw:
        raise ValueError("没有收到文件内容")
    if len(raw) > MAX_UPLOAD_B64:
        raise ValueError("文件太大了，请粘贴论文正文或摘要")
    try:
        blob = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("文件内容不是有效的 base64") from exc

    lower = name.lower()
    if lower.endswith(".pdf") or blob[:5] == b"%PDF-":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("读取 PDF 需要安装 pypdf（pip install pypdf），或直接粘贴论文文本") from exc
        import io

        try:
            reader = PdfReader(io.BytesIO(blob))
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:  # a damaged PDF is a user-facing error
            raise ValueError(f"无法解析这个 PDF：{exc}") from exc
        text = "\n\n".join(page.strip() for page in pages if page.strip())
        if not text.strip():
            raise ValueError("这个 PDF 里没有可提取的文字（可能是扫描件），请粘贴文本")
        return {"text": text, "pages": len(pages), "name": name}

    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            return {"text": blob.decode(encoding), "pages": 1, "name": name}
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文件编码，请粘贴文本")


def delete(payload: dict[str, Any]) -> dict[str, Any]:
    from gaworld.research import workbench

    plan_id = str((payload or {}).get("plan_id") or "").strip()
    if plan_detail(plan_id) is None:
        return {"deleted": False, "plan_id": plan_id}
    removed = workbench.delete_plan(plan_id)
    return {"deleted": removed, "plan_id": plan_id}


def update_plan(plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from gaworld.research import workbench
    from gaworld.research.editing import plan_edit

    with _ACTIVE_LOCK:
        current = plan_detail(plan_id)
        if current is None:
            raise ValueError("找不到方案")
        data = plan_edit(current, payload.get("plan"))
        editable = workbench.ResearchPlan.from_dict(data)
        extra = {key: data[key] for key in ("owner_id", "owner", "world_id", "revisions") if key in data}
        workbench.save_plan(editable, extra)
    return plan_detail(plan_id) or {}


# ---------------------------------------------------------------------------
# Studies: plan → protocol → approve → run → evaluate → report
# ---------------------------------------------------------------------------


class StudyBusy(Exception):
    """Another study is running. One at a time, for the parallel panel's
    reason: a study is several full simulations, and two would thrash."""


class StudyNotFound(LookupError):
    """No study with that id — the caller answers 404."""


#: The one study allowed to run at a time, plus the handles that stop and
#: pause it. All of it is in memory, which is why a study found at
#: ``running`` without a live job here has been interrupted — see
#: :func:`_heal_interrupted`.
_ACTIVE_STUDIES: dict[str, dict[str, Any]] = {}
_ACTIVE_LOCK = threading.RLock()
# Redaction-only cache survives run completion, never serialized to artifacts.
_ATTEMPT_LOG_SECRETS: dict[tuple[str, int], list[str]] = {}


def _active(study_id: str) -> dict[str, Any]:
    return _ACTIVE_STUDIES.get(study_id, {})


def _mutation(function: Any) -> Any:
    @wraps(function)
    def locked(*args: Any, **kwargs: Any) -> Any:
        with _ACTIVE_LOCK:
            return function(*args, **kwargs)

    return locked


#: What a study's record says after the process that was running it died.
INTERRUPTED_MESSAGE = "运行已中断（服务重启或进程退出）。重置后可以重新运行。"

_OVERRIDE_KEYS = ("seeds", "sim_days", "fast", "agent_ids", "max_parallel", "sim_provider")


def _repo_root() -> str:
    try:
        return str(world_paths.REPO_ROOT)
    except Exception:  # outside the dashboard the package root is the repo
        from gaworld.research import workbench

        return str(workbench.PROJECT_ROOT)


def _base_config() -> dict[str, Any]:
    """The config the worlds inherit — dashboard overrides included, like a
    hand-built parallel worlds experiment. Late-bound for the same reason
    ``parallel_worlds_api`` is: tests move the repo root."""
    try:
        config = world_paths.effective_config()
        return config if isinstance(config, dict) else {}
    except Exception:
        _LOG.warning("could not read the effective config; worlds run on defaults", exc_info=True)
        return {}


def _default_agents(config: dict[str, Any]) -> int:
    ids = config.get("agent_ids")
    return len(ids) if isinstance(ids, list) and ids else 5


def _load_study(study_id: str) -> Any:
    from gaworld.research import study as study_mod

    found = study_mod.load_study(study_id)
    if found is None:
        raise StudyNotFound(study_id)
    if not workspaces.visible(found.to_dict()):
        raise StudyNotFound(study_id)
    world = world_paths.current_world() or {}
    if found.world_id and found.world_id != str(world.get("id") or ""):
        raise StudyNotFound(study_id)
    return found


def _attempt_dir(study: Any) -> Path:
    from gaworld.research.study import study_dir

    return study_dir(study.id) / f"attempt_{study.attempt}"


def _telemetry(study: Any) -> dict[str, Any]:
    from gaworld.llm.run_state import RunLedger

    path = _attempt_dir(study) / "providers.sqlite"
    if path.is_file():
        return RunLedger(str(path)).snapshot()
    from gaworld.research.telemetry import historical_snapshot

    return study.runtime.get("telemetry") or historical_snapshot(study, _repo_root())


def quick_study(study_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from gaworld.research import protocol as protocols
    from gaworld.research import study as store
    from gaworld.research.quick import original_sample, quick_protocol

    parent = _load_study(study_id)
    config = _base_config()
    source = protocols.Protocol.from_dict(copy.deepcopy(parent.protocol))
    current_sample = (payload or {}).get("use_current_sample") is True
    if current_sample:
        evidence = {}
        source.sample["agent_ids"] = list(config.get("agent_ids") or [])
        source.sample.pop("seed_identity", None)
    else:
        evidence = original_sample(parent, _repo_root())
    if evidence.get("agent_ids"):
        source.sample["agent_ids"] = evidence["agent_ids"]
    if evidence.get("seed_identity"):
        source.sample["seed_identity"] = evidence["seed_identity"]
    protocol, changes = quick_protocol(source, config, repo_root=_repo_root())
    changes["sample"]["before"] = parent.protocol.get("sample") or {}
    if current_sample:
        changes["sample_origin"] = {
            "before": "parent study sample not reused",
            "after": "current_city_independent_pilot",
        }
    check = protocols.preflight(protocol, default_agents=_default_agents(config))
    child = store.new_study(
        {"id": parent.plan_id, "language": parent.language},
        protocol.to_dict(),
        check,
        provider=parent.provider,
    )
    child.parent_study_id = parent.id
    child.protocol_changes = changes
    child.source_plan = parent.source_plan or plan_detail(parent.plan_id) or {}
    _stamp_study(child)
    store.save_study(child)
    return {"study_id": child.id, "stage": child.stage, "preflight": check, "protocol_changes": changes}


def _stamp_study(study: Any) -> None:
    for key, value in workspaces.stamp().items():
        setattr(study, key, value)
    study.world_id = str((world_paths.current_world() or {}).get("id") or "")


def check_study_provider(study_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from gaworld.research.provider_check import inspect_provider
    from gaworld.research.run_logs import configured_secrets, redact

    study = _load_study(study_id)
    config = _base_config()
    result = inspect_provider(
        config,
        str(payload.get("provider") or study.protocol.get("sim_provider") or ""),
        local=True,
        probe=payload.get("probe") is True,
    )
    # Probe errors can include server responses. Keep credentials out of UI.
    secrets = configured_secrets(config)

    def clean(value: Any) -> Any:
        if isinstance(value, str):
            return redact(value, secrets)
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return clean(result)


def study_logs(study_id: str, query: dict[str, Any]) -> dict[str, Any]:
    from gaworld.parallel.runner import load_manifest
    from gaworld.research.run_logs import configured_secrets, read_chunk, safe_path

    study = _load_study(study_id)
    active = _active(study_id)
    repo = Path(_repo_root())
    sources: list[dict[str, Any]] = [{"seed": None, "world": "", "kind": "events", "status": study.stage}]
    paths: dict[tuple[str, str, str], tuple[Path, Path]] = {
        ("", "", "events"): (_attempt_dir(study) / "events.log", _attempt_dir(study))
    }
    runs = list(study.runs)
    secrets = configured_secrets(_base_config())
    with _ACTIVE_LOCK:
        secrets.extend(_ATTEMPT_LOG_SECRETS.get((study.id, study.attempt), []))
        if active.get("study_id") == study.id:
            secrets.extend(configured_secrets(active.get("base_config") or {}))
        runner = active.get("runner") if active.get("study_id") == study.id else None
        if runner is not None:
            manifest = runner.manifest
            active_root = manifest.get("root")
            if active_root not in {r.get("root") for r in runs}:
                runs.append({"seed": manifest.get("spec", {}).get("seed"), "root": active_root})
    prefix = f"study_{study.id}" + (f"_r{study.attempt}" if study.attempt > 1 else "")
    for run in runs:
        seed = str(run.get("seed"))
        expected = repo / "output" / "parallel_worlds" / f"{prefix}_s{seed}"
        supplied = repo / str(run.get("root") or "")
        if supplied.absolute() != expected.absolute():
            continue
        safe_path(expected / "experiment.json", expected)
        manifest = load_manifest(str(repo), str(run["root"])) or {}
        for world, entry in (manifest.get("worlds") or {}).items():
            if not isinstance(entry, dict) or world not in {
                str(c.get("id")) for c in study.protocol.get("conditions", [])
            }:
                continue
            directory = expected / "worlds" / world
            safe_path(directory, expected)
            if (repo / str(entry.get("dir") or "")).absolute() != directory.absolute():
                continue
            for kind, filename in (("run", "run.log"), ("reset", "reset.log"), ("survey", "survey.log")):
                paths[(seed, world, kind)] = (directory / filename, directory)
                sources.append(
                    {
                        "seed": run.get("seed"),
                        "world": world,
                        "kind": kind,
                        "status": (manifest.get("world_status") or {}).get(
                            world, manifest.get("status", "prepared")
                        ),
                    }
                )

    def value(key: str, default: str = "") -> str:
        found = query.get(key, default)
        return str(found[0] if isinstance(found, list) and found else found)

    key = (value("seed"), value("world"), value("kind", "events"))
    if key not in paths:
        raise ValueError("找不到当前研究/尝试的日志来源")
    path, root = paths[key]
    chunk = read_chunk(
        path,
        root,
        offset=int(value("offset", "0")),
        file_id=value("file_id"),
        secrets=secrets,
        terminal=study.stage != "running",
    )
    return {
        **chunk,
        "sources": sources,
        "study_id": study.id,
        "attempt": study.attempt,
        "live": _is_live(study.id),
    }


def _seed_runner(study: Any) -> Any:
    """The real seed runner. Module-level so tests can swap in a fake."""
    from gaworld.research import backends

    active = _active(study.id)

    attempt = int(getattr(study, "attempt", 1) or 1)
    prefix = f"study_{study.id}" if attempt <= 1 else f"study_{study.id}_r{attempt}"
    return backends.default_seed_runner(
        repo_root=_repo_root(),
        base_config=active.get("base_config") or _base_config(),
        experiment_prefix=prefix,
        active=active,
    )


def _survey_runner(study: Any) -> Any:
    """The real post-run survey (composite studies). Module-level so tests
    can swap in a fake. Residents answer on the model they ran on."""
    from gaworld.research import backends

    active = _active(study.id)

    provider = str(study.runtime.get("actual_provider") or (study.protocol or {}).get("sim_provider") or "")
    return backends.default_survey_runner(
        repo_root=_repo_root(),
        provider=provider,
        stop=active.get("stop"),
        pause=active.get("pause"),
        ledger_path=str(active.get("ledger") or ""),
        provider_config=((active.get("base_config") or {}).get("llm") or {})
        .get("providers", {})
        .get(provider),
    )


def _is_live(study_id: str) -> bool:
    """Is this study running *in this process*, right now?

    The only honest definition available: the job table and the stop handles
    do not survive a restart, so a record claiming otherwise is stale.
    """
    with _ACTIVE_LOCK:
        active = _active(study_id)
        if active.get("study_id") != study_id:
            return False
        job_id = active.get("job_id")
    if not job_id:
        return False
    with _JOBS_LOCK:
        return (_JOBS.get(job_id) or {}).get("status") == "running"


def _heal_interrupted(study: Any) -> Any:
    """Move a study stuck at ``running`` with no live job to ``error``.

    Without this a dashboard restart leaves a study that shows 运行中 forever:
    *stop* has nothing to stop, *run* refuses because the stage is not
    ``approved``, and the panel offers no way out. Saying "interrupted" is
    both true and the thing that makes 停止 / 重置运行 work again.
    """
    from gaworld.research import study as study_mod

    if study.stage != "running" or _is_live(study.id):
        return study
    study.set_stage("error", error=INTERRUPTED_MESSAGE)
    study_mod.save_study(study)
    _LOG.info("study %s was left running by a dead process; marked interrupted", study.id)
    return study


def _heal_all() -> None:
    """Same, for every study on disk — the panel lists before it opens."""
    from gaworld.research import study as study_mod

    for item in workspaces.owned(study_mod.list_studies()):
        study_id = str(item.get("id") or "")
        if item.get("stage") != "running" or _is_live(study_id):
            continue
        found = study_mod.load_study(study_id)
        if found is not None:
            _heal_interrupted(found)


def _llm(provider: str, max_tokens: int) -> Any:
    from gaworld.llm.providers import call_llm

    def call(prompt: str) -> str:
        return call_llm(prompt, task="research", provider=provider or None, max_tokens=max_tokens)

    return call


def studies() -> dict[str, Any]:
    from gaworld.research import study as study_mod

    _heal_all()
    items = workspaces.owned(study_mod.list_studies())
    for item in items:
        item["live"] = _is_live(item["id"])
        pause = _active(item["id"]).get("pause")
        item["paused"] = bool(item["live"] and pause is not None and pause.is_set())
    return {"studies": items}


def study_detail(study_id: str) -> dict[str, Any]:
    study = _heal_interrupted(_load_study(study_id))
    active = _active(study_id)
    detail = study.to_dict()
    live = _is_live(study_id)
    with _ACTIVE_LOCK:
        pause = active.get("pause")
        stop = active.get("stop")
        detail["active_job_id"] = active.get("job_id") if live else None
    detail["live"] = live
    detail["paused"] = bool(live and pause is not None and pause.is_set())
    detail["stopping"] = bool(live and stop is not None and stop.is_set())
    job_id = detail["active_job_id"]
    if not job_id and study.stage not in {"approved", "protocol"}:
        with _JOBS_LOCK:
            matching = [job for job in _JOBS.values() if job.get("study_id") == study_id]
            job_id = max(matching, key=lambda job: job["started_at"])["id"] if matching else None
    detail["run_status"] = job_status(job_id) if job_id else None
    detail["runtime"]["telemetry"] = _telemetry(study)
    return detail


def export_study_report(study_id: str) -> dict[str, Any]:
    from gaworld.research.report import render_study_markdown

    study = _load_study(study_id)
    markdown = study.report_markdown or render_study_markdown(study.to_dict())
    safe = "".join(char if char.isalnum() or char in "-_（）()" else "_" for char in study.title)[:40]
    return {
        "filename": f"{safe or 'study'}-{study.id}.md",
        "markdown": markdown,
        "bytes": len(markdown.encode("utf-8")),
    }


def start_study(payload: dict[str, Any]) -> dict[str, Any]:
    """Compile a plan into a protocol in the background; autopilot may go on to run it."""
    from gaworld.research import workbench

    plan_id = str(payload.get("plan_id") or "").strip()
    plan = plan_detail(plan_id)  # authorized source, captured before the worker starts
    if plan is None:
        raise ValueError(f"找不到方案 {plan_id}")
    designs = plan.get("designs") or []
    if payload.get("design_index") is not None and designs:
        # Compile one of the alternatives instead of the recommended design.
        try:
            index = int(payload["design_index"])
        except (TypeError, ValueError) as exc:
            raise ValueError("design_index 必须是整数") from exc
        if not 0 <= index < len(designs):
            raise ValueError(f"方案只有 {len(designs)} 个实验设计，没有第 {index + 1} 个")
        plan = {**plan, "design": designs[index]}
    provider = str(payload.get("provider") or "").strip()[:64]
    autopilot = bool(payload.get("autopilot"))
    overrides = {key: payload[key] for key in _OVERRIDE_KEYS if key in payload}
    job_id = _new_job("study")

    def work(report: Any) -> dict[str, Any]:
        from gaworld.city.knowledge import _parse_json_object
        from gaworld.llm.providers import resolve_provider
        from gaworld.research import protocol as protocol_mod
        from gaworld.research import study as study_mod

        try:
            routed = resolve_provider(task="research", provider=provider or None)
        except Exception:  # an unknown name is reported by call_llm itself
            routed = provider
        report(0.1, f"正在用 {routed or '默认模型'} 编译预注册协议…")
        prompt = protocol_mod.build_compile_prompt(plan, language=str(plan.get("language") or "zh-CN"))
        try:
            raw = _llm(provider, protocol_mod.PROTOCOL_MAX_TOKENS)(prompt)
        except Exception as exc:  # surfaced to the user as-is
            raise workbench.ResearchError(f"模型调用失败：{exc}") from exc
        answer = _parse_json_object(raw)
        if not answer:
            raise workbench.ResearchError("模型没有返回可解析的 JSON 协议")
        protocol = protocol_mod.apply_overrides(protocol_mod.protocol_from_answer(answer, plan), overrides)
        report(0.7, "正在做跑前检查…")
        check = protocol_mod.preflight(protocol, default_agents=_default_agents(_base_config()))
        study = study_mod.new_study(
            plan, protocol.to_dict(), check, provider=routed or provider, autopilot=autopilot
        )
        _stamp_study(study)
        _update_job(job_id, study_id=study.id, _event_log=str(_attempt_dir(study) / "events.log"))
        study_mod.save_study(study)
        result: dict[str, Any] = {
            "study_id": study.id,
            "title": study.title,
            "stage": study.stage,
            "preflight": check,
        }
        # Autopilot skips the wait for a click, never the gate.
        if autopilot and check["ok"]:
            study.set_stage("approved")
            study_mod.save_study(study)
            result["stage"] = study.stage
            try:
                result["run_job_id"] = _launch_run(study.id)
            except StudyBusy as exc:
                result["note"] = str(exc)
        return result

    _run_in_background(job_id, work)
    return {"job_id": job_id, "plan_id": plan_id}


@_mutation
def update_study(study_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Cost and scope knobs, re-checked; only while nothing has been approved."""
    from gaworld.research import protocol as protocol_mod
    from gaworld.research import study as study_mod

    study = _load_study(study_id)
    if _is_live(study_id) or study.runs or study.runtime or study.evaluation:
        raise ValueError("已有运行结果，请复制并修订后重新批准")
    if study.stage not in ("protocol", "error") and not (study.stage == "approved" and "protocol" in payload):
        raise ValueError(f"研究已进入 {study.stage} 阶段，协议不能再改")
    previous = copy.deepcopy(study.protocol)
    if "protocol" in payload:
        from gaworld.research.editing import protocol_edit

        protocol = protocol_edit(previous, payload["protocol"])
    else:
        protocol = protocol_mod.apply_overrides(
            protocol_mod.Protocol.from_dict(copy.deepcopy(previous)), payload
        )
    from gaworld.research.quick import exclude_unused_measures

    removed_unused = (
        exclude_unused_measures(protocol) if payload.get("exclude_incompatible") is not True else []
    )
    if removed_unused:
        study.protocol_changes["excluded_unused_measures"] = list(
            dict.fromkeys([*study.protocol_changes.get("excluded_unused_measures", []), *removed_unused])
        )
    if payload.get("exclude_incompatible") is True:
        if not study.parent_study_id or protocol.purpose != "exploratory" or protocol.mode != "daily_brief":
            raise ValueError("只有待批准的快速探索子研究可以排除不兼容指标")
        from gaworld.research.survey import PREFIX
        from gaworld.sim._fastforward import LONG_RUN_STATE_KEYS

        allowed = set(LONG_RUN_STATE_KEYS) | {
            PREFIX + str(q.get("id")) for q in protocol.survey.get("questions", [])
        }
        removed = [m["id"] for m in protocol.measures if m.get("id") not in allowed]
        dropped = [h for h in protocol.hypotheses if h.get("measure") not in allowed]
        protocol.measures = [m for m in protocol.measures if m.get("id") in allowed]
        protocol.hypotheses = [h for h in protocol.hypotheses if h.get("measure") in allowed]
        study.protocol_changes["excluded_measures"] = removed
        study.protocol_changes["excluded_hypotheses"] = dropped
    study.preflight = protocol_mod.preflight(protocol, default_agents=_default_agents(_base_config()))
    study.protocol = protocol.to_dict()
    if study.protocol != previous:
        study.protocol_revisions.append(previous)
    study.title = protocol.title
    study.set_stage("protocol")
    study_mod.save_study(study)
    return {
        "study_id": study.id,
        "stage": study.stage,
        "preflight": study.preflight,
        "protocol": study.protocol,
    }


def revise_study(study_id: str) -> dict[str, Any]:
    from gaworld.research import protocol as protocols
    from gaworld.research import study as store

    parent = _load_study(study_id)
    protocol = protocols.Protocol.from_dict(parent.protocol)
    protocol.title += " · 修订"
    check = protocols.preflight(protocol, default_agents=_default_agents(_base_config()))
    child = store.new_study(
        {"id": parent.plan_id, "language": parent.language},
        protocol.to_dict(),
        check,
        provider=parent.provider,
    )
    child.parent_study_id = parent.id
    child.source_plan = parent.source_plan or plan_detail(parent.plan_id) or {}
    child.protocol_changes = {"revision_of": parent.id}
    _stamp_study(child)
    store.save_study(child)
    return {"study_id": child.id, "stage": child.stage}


@_mutation
def approve_study(study_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from gaworld.research import study as study_mod

    study = _load_study(study_id)
    if study.stage not in ("protocol", "error"):
        raise ValueError(f"研究处于 {study.stage} 阶段，不需要批准")
    from gaworld.research.protocol import Protocol, preflight

    config = _base_config()
    protocol = Protocol.from_dict(study.protocol)
    study.preflight = preflight(protocol, default_agents=_default_agents(config))
    study.protocol = protocol.to_dict()
    _check_runtime_compatibility(study, config)
    if not (study.preflight or {}).get("ok") and not payload.get("force"):
        raise ValueError("跑前检查没有通过，先修正协议（或带 force 强行批准）")
    study.set_stage("approved")
    study_mod.save_study(study)
    result: dict[str, Any] = {"study_id": study.id, "stage": study.stage}
    if payload.get("run"):
        result["run_job_id"] = _launch_run(study.id)
    return result


def _check_runtime_compatibility(study: Any, config: dict[str, Any]) -> dict[str, Any]:
    from gaworld.research.editing import validate_code_overrides
    from gaworld.research.protocol import Protocol
    from gaworld.research.quick import compatibility_errors, validate_sample

    protocol = Protocol.from_dict(study.protocol)
    for condition in protocol.conditions:
        patch = condition.get("config") or {}
        validate_code_overrides(patch)
        forbidden = set(patch) & {"city", "csv_path", "md_path", "map_path", "agent_ids", "llm", "long_run"}
        if forbidden:
            raise ValueError(f"研究条件不能替换共享人口、模型或运行引擎：{', '.join(sorted(forbidden))}")
    if protocol.mode == "daily_brief":
        errors = compatibility_errors(protocol, config)
        if errors:
            raise ValueError("；".join(errors))
    return validate_sample(protocol, config, _repo_root())


@_mutation
def _launch_run(study_id: str) -> str:
    from gaworld.research import study as study_mod

    study = _load_study(study_id)
    if study_id in _ACTIVE_STUDIES:
        raise ValueError("研究已有运行任务，不能重复启动")
    if study.stage != "approved":
        raise ValueError(f"研究处于 {study.stage} 阶段，只有 approved 的研究能运行")
    from gaworld.research.provider_check import inspect_provider

    config = _base_config()
    identity = _check_runtime_compatibility(study, config)
    from gaworld.research.protocol import Protocol, preflight

    refreshed = preflight(Protocol.from_dict(study.protocol), default_agents=_default_agents(config))
    if any("超过上限" in item for item in refreshed["errors"]):
        study.preflight = refreshed
        study.set_stage("protocol")
        study_mod.save_study(study)
        raise ValueError("；".join(refreshed["errors"]))
    study.preflight = refreshed
    check = inspect_provider(config, str(study.protocol.get("sim_provider") or ""), local=True)
    if check["status"] in {"unconfigured", "missing_key", "connection_failed", "model_missing"}:
        raise ValueError(f"仿真模型跑前检查失败：{check['status']} · {check['primary']}")
    directory = _attempt_dir(study)
    directory.mkdir(parents=True, exist_ok=True)
    from gaworld.research.runtime_inputs import freeze_inputs

    frozen_config, inputs = freeze_inputs(config, _repo_root(), directory)
    if identity.get("sha256") and inputs.get("csv_path", {}).get("sha256") != identity["sha256"]:
        raise ValueError("居民样本在运行启动期间发生改变，请重新检查协议")
    from gaworld.llm.run_state import RunLedger

    ledger = str(directory / "providers.sqlite")
    RunLedger(ledger).check()
    study.runtime = {
        "provider_check": check,
        "actual_provider": check["primary"],
        "actual_agent_ids": list(
            study.protocol.get("sample", {}).get("agent_ids") or config.get("agent_ids") or []
        ),
        "actual_city": identity["city"],
        "seed_identity": identity,
        "input_snapshots": inputs,
        "actual_model": ((config.get("llm") or {}).get("providers", {}).get(check["primary"]) or {}).get(
            "model"
        ),
        "started_at_epoch": time.time(),
    }
    with _ACTIVE_LOCK:
        fresh = _load_study(study_id)
        if fresh.stage != "approved":
            raise ValueError(f"研究处于 {fresh.stage} 阶段，只有 approved 的研究能运行")
        limits = config.get("research_workbench") or {}
        maximum = max(1, int(limits.get("max_concurrent_studies", 4)))
        per_user = max(1, int(limits.get("max_studies_per_user", 2)))
        from gaworld.accounts.context import USER

        user = USER.get()
        mine = sum(a.get("owner_id") == (user or {}).get("id") for a in _ACTIVE_STUDIES.values())
        if len(_ACTIVE_STUDIES) >= maximum or (user and user.get("role") != "admin" and mine >= per_user):
            raise StudyBusy("研究并发上限已达到，请等待或停止一项研究后再运行")
        from gaworld.research.run_logs import configured_secrets

        _ATTEMPT_LOG_SECRETS[(study.id, study.attempt)] = configured_secrets(frozen_config)
        job_id = _new_job("run")
        _update_job(job_id, study_id=study_id)
        _ACTIVE_STUDIES[study_id] = {
            "owner_id": study.owner_id,
            "study_id": study_id,
            "job_id": job_id,
            "runner": None,
            "stop": threading.Event(),
            "pause": threading.Event(),
            "ledger": ledger,
            "actual_provider": check["primary"],
            "base_config": frozen_config,
        }
        _update_job(job_id, _event_log=str(directory / "events.log"), _ledger_path=ledger)
        study.set_stage("running")
        study_mod.save_study(study)
    _run_in_background(job_id, lambda report: _run_study(study_id, report))
    return job_id


def _run_study(study_id: str, report: Any) -> dict[str, Any]:
    from gaworld.research import backends
    from gaworld.research import study as study_mod
    from gaworld.research.evaluate import evaluate, has_comparable_data
    from gaworld.research.interpret import INTERPRET_MAX_TOKENS, interpret
    from gaworld.research.protocol import Protocol
    from gaworld.research.report import render_study_markdown
    from gaworld.research.workbench import ResearchError

    study = _load_study(study_id)
    active = _active(study_id)
    protocol = Protocol.from_dict(study.protocol)
    stop = active.get("stop") or threading.Event()
    pause = active.get("pause")
    study.set_stage("running")
    study_mod.save_study(study)

    def checkpoint(*, check_provider: bool = True) -> None:
        backends._wait_while_paused(pause, stop, None, 0.0)
        if stop.is_set():
            raise _StudyStopped
        telemetry = _telemetry(study)
        if check_provider and telemetry.get("aborted"):
            raise ResearchError(str(telemetry.get("reason")))

    def prepared(manifest: dict[str, Any], seed: int) -> None:
        study.runs.append({"seed": seed, "root": manifest["root"], "id": manifest["id"], "status": "running"})
        study_mod.save_study(study)

    active["on_prepared"] = prepared

    try:
        runs = backends.run_protocol(
            protocol,
            run_seed=_seed_runner(study),
            run_survey=_survey_runner(study) if protocol.kind == "composite" else None,
            report=lambda p, m: report(p * 0.85, m),
            stop=stop,
            pause=pause,
            name=study.title,
        )
        study.runs = backends.slim_runs(runs)
        checkpoint()
        report(0.86, "正在判定假设…")
        study.evaluation = evaluate(protocol, runs)
        checkpoint()
        if not has_comparable_data(study.evaluation):
            raise ResearchError("运行失败：没有可用于判定假设的数据，请查看执行记录和运行日志。")
        study.set_stage("evaluated")
        study_mod.save_study(study)
        report(0.9, "正在解读结果…")
        # A failed reading is a missing section, not a failed study: the
        # verdicts are already on disk and the report renders without it.
        try:
            study.interpretation = interpret(
                protocol, study.evaluation, llm_fn=_llm(study.provider, INTERPRET_MAX_TOKENS)
            )
        except ResearchError as exc:
            study.interpretation = {"error": str(exc)}
        checkpoint(check_provider=False)
        study.set_stage("reported")
        study.report_markdown = render_study_markdown(study.to_dict())
        checkpoint(check_provider=False)
        study_mod.save_study(study)
        return {"study_id": study.id, "stage": study.stage, "summary": study.evaluation.get("summary")}
    except _StudyStopped:
        study.set_stage("error", error="已停止")
        study.report_markdown = ""
        study_mod.save_study(study)
        return {"study_id": study.id, "stage": study.stage, "stopped": True}
    except Exception as exc:
        study.set_stage("error", error=str(exc))
        study.report_markdown = render_study_markdown(study.to_dict())
        study_mod.save_study(study)
        raise
    finally:
        study.runtime["telemetry"] = _telemetry(study)
        study.runtime["queued_seconds"] = sum(float(run.get("queued_seconds") or 0) for run in study.runs)
        study.runtime["wall_seconds"] = max(
            0, time.time() - study.runtime.get("started_at_epoch", time.time())
        )
        job_id = active.get("job_id")
        if job_id:
            job = job_status(job_id) or {}
            study.runtime["elapsed_seconds"] = job.get("elapsed_seconds", 0)
            study.runtime["paused_seconds"] = job.get("paused_seconds", 0)
        if study.report_markdown:
            study.report_markdown = render_study_markdown(study.to_dict())
        study_mod.save_study(study)
        with _ACTIVE_LOCK:
            if _active(study_id) is active:
                _ACTIVE_STUDIES.pop(study_id, None)


class _StudyStopped(Exception):
    """Stop requested at a cooperative boundary."""


def stop_study(study_id: str) -> dict[str, Any]:
    """Stop a live run — or, if there is nothing to stop, tidy the record.

    The second half is what a study interrupted by a restart needs: the
    stage on disk still says ``running``, and only writing the truth to it
    lets the panel offer anything but a dead 停止 button.
    """
    study = _heal_interrupted(_load_study(study_id))
    active = _active(study_id)
    if not _is_live(study_id):
        return {"study_id": study_id, "stopping": False, "stage": study.stage}
    with _ACTIVE_LOCK:
        stop = active.get("stop")
        pause = active.get("pause")
        runner = active.get("runner")
        job_id = active.get("job_id")
    if stop is not None:
        stop.set()
    if pause is not None:
        pause.clear()  # a paused run must still be stoppable
    _update_job(job_id, stopping=True, paused=False)
    if runner is not None:
        ownership.spawn(runner.stop, name=f"stop-study-{study_id}")
    return {"study_id": study_id, "stopping": True, "stage": study.stage}


def pause_study(study_id: str) -> dict[str, Any]:
    """Hold a live run: suspend the worlds in flight, queue the rest."""
    _load_study(study_id)
    active = _active(study_id)
    if not _is_live(study_id):
        raise ValueError("研究没有在运行，无法暂停")
    with _ACTIVE_LOCK:
        pause = active.get("pause")
        runner = active.get("runner")
        stop = active.get("stop")
        job_id = active.get("job_id")
        if stop is not None and stop.is_set():
            raise ValueError("研究正在停止，无法暂停")
    if pause is None:
        raise ValueError("这次运行没有暂停句柄，只能停止")
    pause.set()
    _update_job(job_id, paused=True)
    suspended = runner.pause() if runner is not None else True
    result: dict[str, Any] = {"study_id": study_id, "paused": True}
    if not suspended:
        result["note"] = "这个平台不能挂起子进程，正在跑的世界会跑完，之后的世界会等待继续。"
    return result


def resume_study(study_id: str) -> dict[str, Any]:
    _load_study(study_id)
    active = _active(study_id)
    if not _is_live(study_id):
        raise ValueError("研究没有在运行，无法继续")
    with _ACTIVE_LOCK:
        pause = active.get("pause")
        runner = active.get("runner")
        stop = active.get("stop")
        job_id = active.get("job_id")
        if stop is not None and stop.is_set():
            raise ValueError("研究正在停止，无法继续")
    if pause is not None:
        pause.clear()
    _update_job(job_id, paused=False)
    if runner is not None:
        runner.resume()
    return {"study_id": study_id, "paused": False}


@_mutation
def reset_study(study_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Throw away what a run produced and put the study back where it can run.

    The parallel worlds trees stay on disk — they are ordinary experiments
    and the 平行世界 panel still opens them — and the next attempt writes its
    own tree, so a re-run never overwrites the evidence of the last one (or
    collides with world processes a dead dashboard left behind).
    """
    from gaworld.research import study as study_mod

    if _is_live(study_id):
        raise ValueError("研究正在运行，先停止再重置")
    study = _heal_interrupted(_load_study(study_id))
    if study.runs or study.evaluation or study.runtime:
        study.attempt = int(study.attempt or 1) + 1
    study.runs = []
    study.evaluation = {}
    study.interpretation = {}
    study.report_markdown = ""
    study.runtime = {}
    approved = bool((study.preflight or {}).get("ok"))
    study.set_stage("approved" if approved else "protocol")
    study_mod.save_study(study)
    result: dict[str, Any] = {"study_id": study.id, "stage": study.stage, "attempt": study.attempt}
    if payload.get("run"):
        if approved:
            result["run_job_id"] = _launch_run(study.id)
        else:
            result["note"] = "跑前检查没有通过，协议回到待批准，修正后再运行。"
    return result


@_mutation
def delete_study(study_id: str) -> dict[str, Any]:
    from gaworld.research import study as study_mod

    _load_study(study_id)
    if _is_live(study_id):
        raise ValueError("研究正在运行，先停止再删除")
    return {"deleted": study_mod.delete_study(study_id), "study_id": study_id}


def _study_route(path: str) -> tuple[str, str]:
    """``/api/research/studies/<id>[/<action>]`` → ``(id, action)``."""
    parts = path.strip("/").split("/")
    return (parts[3] if len(parts) > 3 else "", parts[4] if len(parts) > 4 else "")


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def _is_game_path(path: str) -> bool:
    return path == "/api/research/games" or path.startswith("/api/research/games/")


def _is_policy_path(path: str) -> bool:
    return path == "/api/research/policy" or path.startswith("/api/research/policy/")


def _is_replication_path(path: str) -> bool:
    return path == "/api/research/replication" or path.startswith("/api/research/replication/")


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    if _is_game_path(path):
        from gaworld.apps import serious_game_api

        return serious_game_api.handle_get(path, query)
    if _is_policy_path(path):
        from gaworld.apps import policy_sim_api

        return policy_sim_api.handle_get(path, query)
    if _is_replication_path(path):
        from gaworld.apps import replication_api

        return replication_api.handle_get(path, query)
    try:
        if path == "/api/research/context":
            return context(), 200
        if path == "/api/research/plans":
            return plans(), 200
        if path.startswith("/api/research/jobs/"):
            record = job_status(path.rsplit("/", 1)[-1])
            if record is None:
                return {"error": "Unknown job"}, 404
            return record, 200
        if path.startswith("/api/research/plans/") and path.endswith("/export"):
            plan_id = path.split("/")[4]
            return export_markdown(plan_id), 200
        if path.startswith("/api/research/plans/"):
            plan_id = path.split("/")[4]
            detail = plan_detail(plan_id)
            if detail is None:
                return {"error": "Unknown plan"}, 404
            return detail, 200
        if path == "/api/research/studies":
            return studies(), 200
        if path.startswith("/api/research/studies/"):
            study_id, action = _study_route(path)
            if action == "report":
                return export_study_report(study_id), 200
            if action == "logs":
                return study_logs(study_id, query or {}), 200
            if not action:
                return study_detail(study_id), 200
    except StudyNotFound:
        return {"error": "Unknown study"}, 404
    except ValueError as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    if _is_game_path(path):
        from gaworld.apps import serious_game_api

        return serious_game_api.handle_post(path, payload)
    if _is_policy_path(path):
        from gaworld.apps import policy_sim_api

        return policy_sim_api.handle_post(path, payload)
    if _is_replication_path(path):
        from gaworld.apps import replication_api

        return replication_api.handle_post(path, payload)
    try:
        if path == "/api/research/analyze":
            return start_analysis(payload), 202
        if path == "/api/research/digest":
            return start_digest(payload), 202
        if path == "/api/research/extract":
            return extract_text(payload), 200
        if path == "/api/research/delete":
            return delete(payload), 200
        if path.startswith("/api/research/plans/") and path.endswith("/update"):
            return update_plan(path.split("/")[4], payload), 200
        if path == "/api/research/studies":
            return start_study(payload), 202
        if path.startswith("/api/research/studies/"):
            study_id, action = _study_route(path)
            if action == "quick":
                return quick_study(study_id, payload), 200
            if action == "check-provider":
                return check_study_provider(study_id, payload), 200
            if action == "update":
                return update_study(study_id, payload), 200
            if action == "revise":
                return revise_study(study_id), 200
            if action == "approve":
                result = approve_study(study_id, payload)
                return result, (202 if "run_job_id" in result else 200)
            if action == "run":
                return {"study_id": study_id, "job_id": _launch_run(study_id)}, 202
            if action == "stop":
                return stop_study(study_id), 200
            if action == "pause":
                return pause_study(study_id), 200
            if action == "resume":
                return resume_study(study_id), 200
            if action == "reset":
                result = reset_study(study_id, payload)
                return result, (202 if "run_job_id" in result else 200)
            if action == "delete":
                return delete_study(study_id), 200
    except StudyNotFound:
        return {"error": "Unknown study"}, 404
    except StudyBusy as exc:
        return {"error": str(exc)}, 409
    except ValueError as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown endpoint"}, 404


__all__ = [
    "INTERRUPTED_MESSAGE",
    "StudyBusy",
    "StudyNotFound",
    "approve_study",
    "context",
    "delete",
    "delete_study",
    "export_markdown",
    "export_study_report",
    "extract_text",
    "handle_get",
    "handle_post",
    "job_status",
    "pause_study",
    "plan_detail",
    "plans",
    "reset_study",
    "resume_study",
    "start_analysis",
    "start_study",
    "stop_study",
    "studies",
    "study_detail",
    "update_study",
]
