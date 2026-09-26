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
parallel worlds experiments (a job, one study at a time), score the
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
import json
import threading
import time
import traceback
import uuid
from typing import Any

from gaworld.logging_setup import get_logger

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
            record.update(fields)


def _run_in_background(job_id: str, work: Any) -> None:
    def runner() -> None:
        try:
            result = work(lambda p, m: _update_job(job_id, progress=p, message=m))
            _update_job(
                job_id,
                status="done",
                progress=1.0,
                message="完成",
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
                finished_at=time.time(),
            )

    threading.Thread(target=runner, name=f"research-{job_id}", daemon=True).start()


def job_status(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        if not record:
            return None
        return json.loads(json.dumps(record, ensure_ascii=False), parse_constant=lambda _: None)


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
    from gaworld.research import measures, workbench
    from gaworld.research import study as study_mod
    from gaworld.research.protocol import DEFAULT_CALL_BUDGET

    catalogue = workbench.load_catalogue()
    _heal_all()
    return {
        "providers": _providers(),
        "catalogue": {"path": workbench.CATALOGUE_PATH, "chars": len(catalogue), "available": bool(catalogue)},
        "limits": {"material_chars": workbench.MAX_MATERIAL_CHARS, "call_budget": DEFAULT_CALL_BUDGET},
        "plans": workbench.list_plans(),
        "studies": study_mod.list_studies(),
        "measures": len(measures.registry()),
    }


def plans() -> dict[str, Any]:
    from gaworld.research import workbench

    return {"plans": workbench.list_plans()}


def plan_detail(plan_id: str) -> dict[str, Any] | None:
    from gaworld.research import workbench

    return workbench.load_plan(plan_id)


def export_markdown(plan_id: str) -> dict[str, Any]:
    """The downloadable document plus the filename the browser should use.

    JSON rather than a file response, as every other export in this dashboard
    is, so the frontend keeps one download path.
    """
    from gaworld.research import workbench

    plan = workbench.load_plan(plan_id)
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
        workbench.save_plan(plan)
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
    removed = workbench.delete_plan(plan_id)
    return {"deleted": removed, "plan_id": plan_id}


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
_ACTIVE_STUDY: dict[str, Any] = {
    "study_id": None,
    "job_id": None,
    "runner": None,
    "stop": None,
    "pause": None,
}
_ACTIVE_LOCK = threading.Lock()

#: What a study's record says after the process that was running it died.
INTERRUPTED_MESSAGE = "运行已中断（服务重启或进程退出）。重置后可以重新运行。"

_OVERRIDE_KEYS = ("seeds", "sim_days", "fast", "agent_ids", "max_parallel", "sim_provider")


def _repo_root() -> str:
    try:
        from gaworld.apps import dashboard_server as ds

        return str(ds.REPO_ROOT)
    except Exception:  # outside the dashboard the package root is the repo
        from gaworld.research import workbench

        return str(workbench.PROJECT_ROOT)


def _base_config() -> dict[str, Any]:
    """The config the worlds inherit — dashboard overrides included, like a
    hand-built parallel worlds experiment. Late-bound for the same reason
    ``parallel_worlds_api`` is: tests move the repo root."""
    try:
        from gaworld.apps import dashboard_server as ds

        config = ds._effective_config()
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
    return found


def _seed_runner(study: Any) -> Any:
    """The real seed runner. Module-level so tests can swap in a fake."""
    from gaworld.research import backends

    attempt = int(getattr(study, "attempt", 1) or 1)
    prefix = f"study_{study.id}" if attempt <= 1 else f"study_{study.id}_r{attempt}"
    return backends.default_seed_runner(
        repo_root=_repo_root(),
        base_config=_base_config(),
        experiment_prefix=prefix,
        active=_ACTIVE_STUDY,
    )


def _is_live(study_id: str) -> bool:
    """Is this study running *in this process*, right now?

    The only honest definition available: the job table and the stop handles
    do not survive a restart, so a record claiming otherwise is stale.
    """
    with _ACTIVE_LOCK:
        if _ACTIVE_STUDY.get("study_id") != study_id:
            return False
        job_id = _ACTIVE_STUDY.get("job_id")
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

    for item in study_mod.list_studies():
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
    return {"studies": study_mod.list_studies()}


def study_detail(study_id: str) -> dict[str, Any]:
    study = _heal_interrupted(_load_study(study_id))
    detail = study.to_dict()
    live = _is_live(study_id)
    with _ACTIVE_LOCK:
        pause = _ACTIVE_STUDY.get("pause")
        detail["active_job_id"] = _ACTIVE_STUDY.get("job_id") if live else None
    detail["live"] = live
    detail["paused"] = bool(live and pause is not None and pause.is_set())
    return detail


def export_study_report(study_id: str) -> dict[str, Any]:
    from gaworld.research.report import render_study_markdown

    study = _load_study(study_id)
    markdown = study.report_markdown or render_study_markdown(study.to_dict())
    safe = "".join(char if char.isalnum() or char in "-_（）()" else "_" for char in study.title)[:40]
    return {"filename": f"{safe or 'study'}-{study.id}.md", "markdown": markdown, "bytes": len(markdown.encode("utf-8"))}


def start_study(payload: dict[str, Any]) -> dict[str, Any]:
    """Compile a plan into a protocol in the background; autopilot may go on to run it."""
    from gaworld.research import workbench

    plan_id = str(payload.get("plan_id") or "").strip()
    plan = workbench.load_plan(plan_id)  # a malformed id raises ResearchError → 400
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
        study = study_mod.new_study(plan, protocol.to_dict(), check, provider=routed or provider, autopilot=autopilot)
        study_mod.save_study(study)
        result: dict[str, Any] = {"study_id": study.id, "title": study.title, "stage": study.stage, "preflight": check}
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


def update_study(study_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Cost and scope knobs, re-checked; only while nothing has been approved."""
    from gaworld.research import protocol as protocol_mod
    from gaworld.research import study as study_mod

    study = _load_study(study_id)
    if study.stage not in ("protocol", "error"):
        raise ValueError(f"研究已进入 {study.stage} 阶段，协议不能再改")
    protocol = protocol_mod.apply_overrides(protocol_mod.Protocol.from_dict(study.protocol), payload)
    study.preflight = protocol_mod.preflight(protocol, default_agents=_default_agents(_base_config()))
    study.protocol = protocol.to_dict()
    study.set_stage("protocol")
    study_mod.save_study(study)
    return {"study_id": study.id, "stage": study.stage, "preflight": study.preflight, "protocol": study.protocol}


def approve_study(study_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from gaworld.research import study as study_mod

    study = _load_study(study_id)
    if study.stage not in ("protocol", "error"):
        raise ValueError(f"研究处于 {study.stage} 阶段，不需要批准")
    if not (study.preflight or {}).get("ok") and not payload.get("force"):
        raise ValueError("跑前检查没有通过，先修正协议（或带 force 强行批准）")
    study.set_stage("approved")
    study_mod.save_study(study)
    result: dict[str, Any] = {"study_id": study.id, "stage": study.stage}
    if payload.get("run"):
        result["run_job_id"] = _launch_run(study.id)
    return result


def _launch_run(study_id: str) -> str:
    study = _load_study(study_id)
    if study.stage != "approved":
        raise ValueError(f"研究处于 {study.stage} 阶段，只有 approved 的研究能运行")
    with _ACTIVE_LOCK:
        active = _ACTIVE_STUDY.get("job_id")
        with _JOBS_LOCK:
            busy = bool(active and (_JOBS.get(active) or {}).get("status") == "running")
        if busy:
            raise StudyBusy(f"研究 {_ACTIVE_STUDY.get('study_id')} 正在运行，一次只能跑一项")
        job_id = _new_job("run")
        _ACTIVE_STUDY.update(
            study_id=study_id,
            job_id=job_id,
            runner=None,
            stop=threading.Event(),
            pause=threading.Event(),
        )
    _run_in_background(job_id, lambda report: _run_study(study_id, report))
    return job_id


def _run_study(study_id: str, report: Any) -> dict[str, Any]:
    from gaworld.research import backends
    from gaworld.research import study as study_mod
    from gaworld.research.evaluate import evaluate
    from gaworld.research.interpret import INTERPRET_MAX_TOKENS, interpret
    from gaworld.research.protocol import Protocol
    from gaworld.research.report import render_study_markdown
    from gaworld.research.workbench import ResearchError

    study = _load_study(study_id)
    protocol = Protocol.from_dict(study.protocol)
    stop = _ACTIVE_STUDY.get("stop") or threading.Event()
    pause = _ACTIVE_STUDY.get("pause")
    study.set_stage("running")
    study_mod.save_study(study)
    try:
        runs = backends.run_protocol(
            protocol,
            run_seed=_seed_runner(study),
            report=lambda p, m: report(p * 0.85, m),
            stop=stop,
            pause=pause,
            name=study.title,
        )
        study.runs = backends.slim_runs(runs)
        if stop.is_set():
            study.set_stage("error", error="已停止")
            study_mod.save_study(study)
            return {"study_id": study.id, "stage": study.stage}
        report(0.86, "正在判定假设…")
        study.evaluation = evaluate(protocol, runs)
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
        study.report_markdown = render_study_markdown(study.to_dict())
        study.set_stage("reported")
        study_mod.save_study(study)
        return {"study_id": study.id, "stage": study.stage, "summary": study.evaluation.get("summary")}
    except Exception as exc:
        study.set_stage("error", error=str(exc))
        study.report_markdown = render_study_markdown(study.to_dict())
        study_mod.save_study(study)
        raise
    finally:
        with _ACTIVE_LOCK:
            if _ACTIVE_STUDY.get("study_id") == study_id:
                _ACTIVE_STUDY.update(study_id=None, job_id=None, runner=None, stop=None, pause=None)


def stop_study(study_id: str) -> dict[str, Any]:
    """Stop a live run — or, if there is nothing to stop, tidy the record.

    The second half is what a study interrupted by a restart needs: the
    stage on disk still says ``running``, and only writing the truth to it
    lets the panel offer anything but a dead 停止 button.
    """
    study = _heal_interrupted(_load_study(study_id))
    if not _is_live(study_id):
        return {"study_id": study_id, "stopping": False, "stage": study.stage}
    with _ACTIVE_LOCK:
        stop = _ACTIVE_STUDY.get("stop")
        pause = _ACTIVE_STUDY.get("pause")
        runner = _ACTIVE_STUDY.get("runner")
    if stop is not None:
        stop.set()
    if pause is not None:
        pause.clear()  # a paused run must still be stoppable
    if runner is not None:
        runner.stop()
    return {"study_id": study_id, "stopping": True, "stage": study.stage}


def pause_study(study_id: str) -> dict[str, Any]:
    """Hold a live run: suspend the worlds in flight, queue the rest."""
    _load_study(study_id)
    if not _is_live(study_id):
        raise ValueError("研究没有在运行，无法暂停")
    with _ACTIVE_LOCK:
        pause = _ACTIVE_STUDY.get("pause")
        runner = _ACTIVE_STUDY.get("runner")
    if pause is None:
        raise ValueError("这次运行没有暂停句柄，只能停止")
    pause.set()
    suspended = runner.pause() if runner is not None else True
    result: dict[str, Any] = {"study_id": study_id, "paused": True}
    if not suspended:
        result["note"] = "这个平台不能挂起子进程，正在跑的世界会跑完，之后的世界会等待继续。"
    return result


def resume_study(study_id: str) -> dict[str, Any]:
    _load_study(study_id)
    if not _is_live(study_id):
        raise ValueError("研究没有在运行，无法继续")
    with _ACTIVE_LOCK:
        pause = _ACTIVE_STUDY.get("pause")
        runner = _ACTIVE_STUDY.get("runner")
    if pause is not None:
        pause.clear()
    if runner is not None:
        runner.resume()
    return {"study_id": study_id, "paused": False}


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
    if study.runs or study.evaluation:
        study.attempt = int(study.attempt or 1) + 1
    study.runs = []
    study.evaluation = {}
    study.interpretation = {}
    study.report_markdown = ""
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


def delete_study(study_id: str) -> dict[str, Any]:
    from gaworld.research import study as study_mod

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


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
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
            if not action:
                return study_detail(study_id), 200
    except StudyNotFound:
        return {"error": "Unknown study"}, 404
    except ValueError as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown research endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/research/analyze":
            return start_analysis(payload), 202
        if path == "/api/research/digest":
            return start_digest(payload), 202
        if path == "/api/research/extract":
            return extract_text(payload), 200
        if path == "/api/research/delete":
            return delete(payload), 200
        if path == "/api/research/studies":
            return start_study(payload), 202
        if path.startswith("/api/research/studies/"):
            study_id, action = _study_route(path)
            if action == "update":
                return update_study(study_id, payload), 200
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
    return {"error": "Unknown research endpoint"}, 404


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
