"""Dashboard backend for 群体采访 — the group interview panel.

A *delegate* module following the ``population_api`` / ``city_api``
precedent: ``dashboard_server.py`` gains four lines of forwarding rather than
another subsystem's routes.

Routes are all under ``/api/interview/`` **with a trailing segment**, which
leaves the pre-existing single-agent ``POST /api/interview`` exactly as it
was. That endpoint shells out once per agent and answers synchronously; it is
the right shape for one resident and the wrong shape for eighty, but it is
also what Agent Studio's 采访 box calls, so it is left alone rather than
generalised underneath a live UI.

A round is a **job**, not a request handler: 80 respondents × 5 questions is
400 model calls, which no browser will wait for. Start it, poll it, read the
session when it lands — the same pattern the population and parallel-worlds
panels use.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from typing import Any

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.interview")

#: job id → record. One table per delegate, matching ``population_api``.
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 10

#: At most one round at a time. Two concurrent rounds on the same session
#: would interleave their appends to ``session.json`` and corrupt the
#: transcript; two on *different* sessions would fight over the same model
#: backend and make both slower than running them in turn.
_RUN_LOCK = threading.Lock()


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
            _LOG.exception("interview job %s failed", job_id)
            _update_job(
                job_id,
                status="error",
                message=str(exc),
                error={"type": type(exc).__name__, "detail": traceback.format_exc(limit=5)},
                finished_at=time.time(),
            )

    threading.Thread(target=runner, name=f"interview-{job_id}", daemon=True).start()


def job_status(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        if not record:
            return None
        # Matches population_api: NaN/Infinity would make JSON.parse throw
        # away the whole response rather than just the offending key.
        return json.loads(json.dumps(record, ensure_ascii=False), parse_constant=lambda _: None)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _query_list(query: dict[str, Any] | None, key: str) -> list[str]:
    """Read a repeatable or comma-joined query parameter.

    ``parse_qs`` gives every value as a list, and the panel sends
    ``cities=a&cities=b`` for multi-select but ``axes=age_band,hukou`` for the
    axis set — both shapes have to work or one of the two silently sends
    nothing.

    Empty segments are kept, not filtered: the default world's slug *is* the
    empty string, so ``?cities=`` means "just the default world" and must stay
    distinguishable from ``cities`` being absent, which means "every city".
    """
    raw = (query or {}).get(key)
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    out: list[str] = []
    for value in values:
        out.extend(part.strip() for part in str(value).split(","))
    return out


def _providers() -> list[dict[str, Any]]:
    """Configured LLM backends, so the panel's model picker is real.

    Mirrors ``population_api._providers``: an unreadable registry degrades
    the picker to "按配置路由" rather than breaking the whole panel.
    """
    try:
        from gaworld.llm.providers import available_providers

        return list(available_providers())
    except Exception:
        _LOG.warning("could not read the LLM provider registry", exc_info=True)
        return []


def roster(query: dict[str, Any] | None = None) -> dict[str, Any]:
    from gaworld.interview.roster import roster as build_roster

    cities = _query_list(query, "cities")
    axes = [axis for axis in _query_list(query, "axes") if axis]
    payload = build_roster(cities or None, axes=axes or None)
    # Shipped with the roster rather than as its own endpoint: the panel needs
    # both before its first render, and one request beats two.
    payload["providers"] = _providers()
    payload["axis_labels"] = {
        "age_band": "年龄段",
        "hukou": "户籍",
        "gender": "性别",
        "district": "片区",
        "city": "城市",
    }
    return payload


def sessions() -> dict[str, Any]:
    from gaworld.interview import store

    return {"sessions": store.list_sessions()}


def session_detail(session_id: str) -> dict[str, Any] | None:
    from gaworld.interview import store

    return store.load_session(session_id)


def export_markdown(session_id: str) -> dict[str, Any]:
    """The downloadable document, plus the filename the browser should use.

    Returned as JSON rather than as a file response because every other
    export in this dashboard does (Analytics' 导出结果 menu), so the frontend
    already has one download path instead of two.
    """
    from gaworld.interview import store

    session = store.load_session(session_id)
    if session is None:
        raise ValueError(f"找不到会话 {session_id}")
    markdown = store.load_report(session_id)
    if not markdown:
        # A session whose round is still running has no report yet; rendering
        # one here from a half-filled transcript would produce a document
        # that looks finished and is not.
        raise ValueError("这次采访还没有生成文档（可能仍在进行中）")
    title = str(session.get("title") or "群体采访").strip() or "群体采访"
    safe = "".join(char if char.isalnum() or char in "-_（）()" else "_" for char in title)[:40]
    return {
        "filename": f"{safe or 'interview'}-{session_id}.md",
        "markdown": markdown,
        "bytes": len(markdown.encode("utf-8")),
    }


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def plan(payload: dict[str, Any]) -> dict[str, Any]:
    from gaworld.interview.session import plan_round

    return plan_round(payload if isinstance(payload, dict) else {})


def start_round(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate, then run one round in the background."""
    from gaworld.interview.session import plan_round, run_round

    payload = payload if isinstance(payload, dict) else {}
    # Validate before returning a job id: a rejected question set should come
    # back as a 400 the user can fix, not as a job that fails a second later
    # in a log they never read.
    preview = plan_round(payload)

    job_id = _new_job("round")

    def work(report: Any) -> dict[str, Any]:
        if not _RUN_LOCK.acquire(blocking=False):
            raise RuntimeError("已有一次群体采访正在进行，请等它结束再开始下一次。")
        try:
            session = run_round(payload, report=lambda fraction, message: report(fraction, message))
        finally:
            _RUN_LOCK.release()
        return {
            "session_id": session.get("id"),
            "round": len(session.get("rounds") or []),
            "analysis": session.get("analysis") or {},
            "questions": session.get("questions") or [],
            "respondents": len(session.get("respondents") or []),
        }

    _run_in_background(job_id, work)
    return {"job_id": job_id, "plan": preview}


def delete(payload: dict[str, Any]) -> dict[str, Any]:
    from gaworld.interview import store

    session_id = str((payload or {}).get("session_id") or "").strip()
    removed = store.delete_session(session_id)
    return {"deleted": removed, "session_id": session_id}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    try:
        if path == "/api/interview/roster":
            return roster(query), 200
        if path == "/api/interview/sessions":
            return sessions(), 200
        if path.startswith("/api/interview/jobs/"):
            record = job_status(path.rsplit("/", 1)[-1])
            if record is None:
                return {"error": "Unknown job"}, 404
            return record, 200
        if path.startswith("/api/interview/sessions/") and path.endswith("/export"):
            session_id = path.split("/")[4]
            return export_markdown(session_id), 200
        if path.startswith("/api/interview/sessions/"):
            session_id = path.split("/")[4]
            detail = session_detail(session_id)
            if detail is None:
                return {"error": "Unknown session"}, 404
            return detail, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown interview endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    from gaworld.interview.schema import InterviewSpecError

    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/interview/plan":
            return plan(payload), 200
        if path == "/api/interview/run":
            return start_round(payload), 202
        if path == "/api/interview/delete":
            return delete(payload), 200
    except (InterviewSpecError, ValueError) as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown interview endpoint"}, 404


__all__ = [
    "export_markdown",
    "handle_get",
    "handle_post",
    "job_status",
    "plan",
    "roster",
    "session_detail",
    "sessions",
    "start_round",
]
