"""LLM persona authoring/enrichment — the ``/api/persona-generate`` delegate.

Three things this endpoint does, none of which the existing panels do:

* **Author** a new resident from a structural seed (``scope="fast"`` keeps the
  zero-LLM templated path; the fast generator is never weakened, LLM authoring
  is strictly additive).
* **Enrich** existing residents with an LLM-authored narrative
  (``selected`` / ``focal_n`` / ``all``) — the structural facts in the state
  CSV are *locked*: the model is never asked for them and an answer that
  contradicts them is rejected before any write, visibly, per agent.
* **Provenance**: every enriched/generated resident is stamped with
  ``persona_source``, task, provider, timestamp and a hash of the structural
  snapshot it was authored against — both in the job record and in a sidecar
  JSON beside the world's seed.

Everything writes through :mod:`gaworld.apps.world_paths` and
:mod:`gaworld.apps.residents`, so a multi-user world edits its own copy.
Model calls go through the router only: ``call_llm(prompt,
task="persona_author", provider=…, agent_id=None)`` — ``agent_id`` stays
``None`` so per-agent routing can never shadow the task routing, and an
explicit ``provider`` from the UI beats task routing (``providers.py``
explicit-precedence). No silent fallback: a failed agent lands in the job
record's ``failed`` list with its error.

Enriched prose lands in the existing ``**…**：`` Markdown headings so
``agents_loader.parse_profile`` reads it unchanged — which is what carries it
into ``experiments/subjects`` → ``paradigms.build_prompt`` without touching
any experiment code. The provenance banner sits *outside* those headings.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import traceback
import uuid
from typing import Any

from gaworld.apps import residents, world_paths
from gaworld.llm.providers import call_llm
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.persona_generate")

#: job id → record. One table per delegate, matching ``persona_api``.
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 10

#: Same ceiling rationale as ``persona_api.DISTILL_MAX_TOKENS``: a reasoning
#: model charges its thinking block against the same budget, so the ceiling is
#: a property of the prompt, not of the deployment.
DISTILL_MAX_TOKENS = 16384

#: Structural facts are the synthesiser's / the operator's, never the model's.
#: They are *checked*, not requested: any key the model volunteers that
#: contradicts the seed/CSV row rejects the whole answer before any write.
STRUCTURAL_FIELDS = (
    "id",
    "name",
    "gender",
    "age",
    "hukou",
    "residence",
    "job",
    "employment",
    "income_monthly",
    "household",
    "city",
)

#: The only fields the model is asked to produce — all narrative, all
#: rendered into ``**…**：`` headings ``parse_profile`` already reads.
NARRATIVE_FIELDS = (
    "personality",
    "daily_life",
    "values",
    "motivations",
    "concerns",
    "social_context",
    "behavioral_tendencies",
    "voice",
)

#: Narrative field → the profile Markdown heading it renders into. Existing
#: corpus headings where there is one (``parse_profile`` reads these);
#: additional single-line headings for the surplus fields.
HEADING_FOR_FIELD = {
    "personality": "**性格与情绪特征**：",
    "daily_life": "**日常生活与生活习惯**：",
    "values": "**价值观与公共事务态度**：",
    "behavioral_tendencies": "**人格与行为倾向**：",
    "motivations": "**动机与追求**：",
    "concerns": "**担忧与顾虑**：",
    "social_context": "**社交情境**：",
    "voice": "**说话方式**：",
}

#: Honest labelling for anything a resident did not get from a human hand:
#: the fast generator's templated prose and the LLM's narrative alike carry
#: this banner, kept OUTSIDE the parsed headings so ``parse_profile`` output
#: is byte-identical with or without it.
BANNER_TEMPLATE = (
    "> 合成人口画像（Synthetic demographic profile）：结构字段来自人口合成器，"
    "叙述字段由 LLM 撰写（persona_author, {date}）。"
)

SCOPES = ("fast", "selected", "focal_n", "all")


# ---------------------------------------------------------------------------
# Job plumbing — the persona_api pattern
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
    from gaworld.accounts import ownership

    def runner() -> None:
        try:
            result = work(lambda p, m: _update_job(job_id, progress=p, message=m))
            _update_job(
                job_id,
                status="completed",
                progress=1.0,
                message="完成",
                result=result,
                finished_at=time.time(),
            )
        except Exception as exc:
            _LOG.exception("persona-generate job %s failed", job_id)
            _update_job(
                job_id,
                status="failed",
                message=str(exc),
                error={"type": type(exc).__name__, "detail": traceback.format_exc(limit=5)},
                finished_at=time.time(),
            )

    ownership.spawn(runner, name=f"persona-generate-{job_id}")


def job_status(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        if record is None:
            return None
        # NaN/Infinity would make JSON.parse drop the whole response.
        return json.loads(json.dumps(record, ensure_ascii=False), parse_constant=lambda _: None)


# ---------------------------------------------------------------------------
# Structural snapshot + the gate
# ---------------------------------------------------------------------------


def _structural_snapshot(agent_id: int) -> dict[str, Any]:
    """The facts a narrative must agree with: the CSV row plus what the
    profile's own headings state about job and income."""
    from gaworld.sim.agents_loader import parse_profile

    state = residents.agent_state(agent_id) or {}
    section = residents.agent_profile(agent_id) or {}
    parsed = parse_profile(section.get("text") or "") if section else {}
    return {
        "id": int(agent_id),
        "name": state.get("name") or "",
        "gender": state.get("gender") or "",
        "age": state.get("age"),
        "hukou": state.get("hukou") or "",
        "residence": state.get("residence") or "",
        "job": parsed.get("job") or "",
        "income_monthly": parsed.get("monthly_income"),
    }


def _normalized(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    text = str(value or "").strip()
    for token in ("元", "岁", "人"):
        text = text.rstrip(token)
    return text


def _structural_contradictions(output: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    """Fields the model volunteered that contradict the locked facts."""
    bad = []
    for key in STRUCTURAL_FIELDS:
        got = output.get(key)
        if got in (None, ""):
            continue  # the model was never asked; silence is compliance
        want = snapshot.get(key)
        if want in (None, ""):
            continue  # nothing locked to contradict
        if _normalized(want) != _normalized(got):
            bad.append(key)
    return bad


def _structural_hash(snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The LLM call and the narrative render
# ---------------------------------------------------------------------------


def _prompt(snapshot: dict[str, Any]) -> str:
    facts = "\n".join(
        f"- {key}：{snapshot[key]}"
        for key in ("name", "gender", "age", "hukou", "residence", "job")
        if snapshot.get(key) not in (None, "")
    )
    fields = "、".join(NARRATIVE_FIELDS)
    return (
        "你是人口仿真中的居民画像作者。下面是这位居民的结构性事实（不可更改，"
        "也不要在回答里复述它们）：\n"
        f"{facts}\n\n"
        f"请只依据这些事实，为这位居民撰写叙事画像。输出一个 JSON 对象，"
        f"只包含这些键：{fields}。每个值是一句到三句平实的中文叙述，"
        "要与上面的事实一致。不要输出 JSON 以外的任何内容。"
    )


def _clean_prose(value: Any) -> str:
    return " ".join(str(value or "").split())


def _apply_narrative(text: str, narrative: dict[str, Any]) -> str:
    """Rewrite the ``**…**：`` narrative headings in one profile section.

    Only the narrative lines move; the ``**基础信息**`` structural line and
    the state-variable lines are untouched, so ``parse_profile`` reads the
    same structural facts it did before. Missing headings are appended before
    the closing rule so a fresh resident gets a complete block.
    """
    lines = text.splitlines()
    for field in NARRATIVE_FIELDS:
        value = _clean_prose(narrative.get(field))
        if not value:
            continue
        heading = HEADING_FOR_FIELD[field]
        replacement = heading + value
        for index, line in enumerate(lines):
            if line.startswith(heading):
                lines[index] = replacement
                break
        else:
            insert_at = next((i for i, line in enumerate(lines) if line.strip() == "---"), len(lines))
            lines.insert(insert_at, replacement)
    return "\n".join(lines)


def _with_banner(text: str, provider: str | None) -> str:
    if "Synthetic demographic profile" in text:
        return text
    banner = BANNER_TEMPLATE.format(date=time.strftime("%Y-%m-%d"))
    if provider:
        banner = banner[:-1] + f"，provider={provider}）。"
    head, sep, rest = text.partition("\n")
    return head + ("\n" + banner + "\n" + rest if sep else "\n" + banner)


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------


def _enrich_one(agent_id: int, provider: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """One bounded attempt per agent. Returns ``(enriched, failure)`` —
    exactly one of the two. No templated fallback: whatever went wrong is
    reported on the agent, visibly.

    The bound is one attempt, not "retry until it works": a model answer that
    contradicts the locked structural facts is a rejection, and papering over
    it with a second sample is exactly the silent-fallback this endpoint
    forbids — the operator sees the failure and re-runs the failed ids.
    """
    snapshot = _structural_snapshot(agent_id)
    try:
        raw = call_llm(
            _prompt(snapshot),
            task="persona_author",
            provider=provider or None,
            agent_id=None,
            max_tokens=DISTILL_MAX_TOKENS,
        )
    except Exception as exc:
        return None, {"id": agent_id, "error": f"{type(exc).__name__}: {exc}"}

    from gaworld.persona.distill import parse_json_object

    try:
        output = parse_json_object(raw or "")
    except Exception as exc:
        return None, {"id": agent_id, "error": f"模型输出不是有效 JSON：{exc}"}

    if not isinstance(output, dict) or not output:
        return None, {"id": agent_id, "error": "模型输出为空或不是 JSON 对象"}

    bad = _structural_contradictions(output, snapshot)
    if bad:
        return None, {
            "id": agent_id,
            "error": f"模型输出与结构事实冲突，已拒绝写入：{'、'.join(bad)}",
        }

    narrative = {key: output[key] for key in NARRATIVE_FIELDS if output.get(key)}
    if not narrative:
        return None, {"id": agent_id, "error": "模型没有返回任何叙事字段"}

    section = residents.agent_profile(agent_id) or {}
    current = section.get("text")
    if current is None:
        return None, {"id": agent_id, "error": f"Profile {agent_id} not found"}
    updated = _with_banner(_apply_narrative(current, narrative), provider)
    residents.save_agent_profile(agent_id, updated)

    provenance = {
        "agent_id": agent_id,
        "persona_source": "llm_enriched",
        "task": "persona_author",
        "provider": provider or "",
        "model": "",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "scope": "",
        "structural_hash": _structural_hash(snapshot),
        "structural_fields": {k: snapshot.get(k) for k in ("name", "gender", "age", "hukou", "residence")},
        "labelling": "synthetic",
    }
    return {"id": agent_id, "fields": sorted(narrative), "provenance": provenance}, None


def _write_sidecar(agent_id: int, provenance: dict[str, Any]) -> None:
    """Provenance beside the world's seed, so it survives the job table's LRU."""
    try:
        base = os.path.dirname(world_paths.state_csv_path())
        directory = os.path.join(base, "personas", "derived")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"{agent_id}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(provenance, handle, ensure_ascii=False, indent=2)
    except OSError:
        _LOG.exception("provenance sidecar for agent %s could not be written", agent_id)


def _resolve_ids(payload: dict[str, Any]) -> list[int]:
    _fieldnames, rows = residents.read_state_rows()
    if not rows:
        raise ValueError("State CSV is missing or empty")
    all_ids = [residents.row_id(row) for row in rows]
    all_ids = [i for i in all_ids if i is not None]
    scope = payload.get("scope") or "fast"
    if scope == "selected":
        ids = payload.get("ids") or []
        wanted = {int(i) for i in ids}
        missing = wanted - set(all_ids)
        if missing:
            raise ValueError(f"找不到这些居民：{sorted(missing)}")
        return [int(i) for i in ids]
    if scope == "focal_n":
        n = int(payload.get("n") or 0)
        if n <= 0:
            raise ValueError("focal_n 需要一个正整数 n")
        return all_ids[:n]
    if scope == "all":
        return all_ids
    raise ValueError(f"未知 scope：{scope}")


def _enrich_run(scope: str, ids: list[int], provider: str | None, progress: Any) -> dict[str, Any]:
    from gaworld.accounts import ownership

    enriched: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    total = len(ids)
    for index, agent_id in enumerate(ids):
        progress(index / max(total, 1), f"正在丰富居民 {agent_id}（{index + 1}/{total}）…")
        ok, bad = _enrich_one(agent_id, provider)
        if ok:
            ok["provenance"]["scope"] = scope
            stamp = ownership.stamp()
            if stamp:
                ok["provenance"].update(stamp)
            enriched.append(ok)
            provenance.append(ok["provenance"])
            _write_sidecar(agent_id, ok["provenance"])
        else:
            failed.append(bad)
    progress(0.99, "写入完成，正在汇总…")
    result: dict[str, Any] = {
        "scope": scope,
        "enriched": enriched,
        "provenance": provenance,
        "failed": failed,
        "label": "Synthetic demographic profile",
    }
    return result


# ---------------------------------------------------------------------------
# Fast scope — the zero-LLM authoring path
# ---------------------------------------------------------------------------


def _fast_run(seed: dict[str, Any], provider: str | None, progress: Any) -> dict[str, Any]:
    """Create one resident from a structural seed, templated narrative only.

    The seed's structural facts go through ``residents.create_agent`` (the
    canonical creator); the narrative keeps the templated defaults. Honest
    labelling: the banner says exactly what this is — synthetic structural
    facts, template prose, no model involved.
    """
    seed = seed or {}
    body = {
        "name": seed.get("name"),
        "gender": seed.get("gender"),
        "age": seed.get("age"),
        "hukou": seed.get("hukou"),
        "residence": seed.get("residence"),
        "job": seed.get("job"),
    }
    body = {k: v for k, v in body.items() if v not in (None, "")}
    created = residents.create_agent(body)
    agent_id = created["id"]
    progress(0.6, f"居民 {agent_id} 已创建，正在写入画像标注…")
    section = residents.agent_profile(agent_id) or {}
    if section.get("text"):
        residents.save_agent_profile(agent_id, _with_banner(section["text"], provider))
    progress(0.99, "完成")
    from gaworld.accounts import ownership

    provenance = {
        "agent_id": agent_id,
        "persona_source": "demographic_template",
        "task": "",
        "provider": "",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "scope": "fast",
        "structural_hash": _structural_hash(_structural_snapshot(agent_id)),
        "structural_fields": {k: seed.get(k) for k in STRUCTURAL_FIELDS if k in seed},
        "labelling": "synthetic",
    }
    stamp = ownership.stamp()
    if stamp:
        provenance.update(stamp)
    _write_sidecar(agent_id, provenance)
    return {
        "scope": "fast",
        "agent_id": agent_id,
        "id": agent_id,
        "name": created["name"],
        "persona_source": "demographic_template",
        "label": "Synthetic demographic profile",
        "provenance": [provenance],
        "failed": [],
    }


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def start(payload: dict[str, Any]) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    scope = str(payload.get("scope") or "fast")
    if scope not in SCOPES:
        raise ValueError(f"未知 scope：{scope}（可选：{'、'.join(SCOPES)}）")
    provider = str(payload.get("provider") or "").strip() or None
    if scope == "fast":
        seed = payload.get("seed")
        if not isinstance(seed, dict) or not seed:
            raise ValueError("fast 需要一个 seed 对象（name/gender/age/…）")
        job_id = _new_job("persona-generate")
        _run_in_background(job_id, lambda progress: _fast_run(seed, provider, progress))
    else:
        ids = _resolve_ids(payload)
        if not ids:
            raise ValueError("没有可丰富居民")
        job_id = _new_job("persona-generate")
        _run_in_background(job_id, lambda progress: _enrich_run(scope, ids, provider, progress))
    return {"job_id": job_id, "status": "running", "scope": scope}


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    if path.startswith("/api/persona-generate/jobs/"):
        record = job_status(path.rsplit("/", 1)[-1])
        if record is None:
            return {"error": "Unknown job"}, 404
        return record, 200
    return {"error": "Unknown endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    try:
        if path == "/api/persona-generate":
            return start(payload), 202
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown endpoint"}, 404


__all__ = [
    "DISTILL_MAX_TOKENS",
    "handle_get",
    "handle_post",
    "job_status",
    "start",
]
