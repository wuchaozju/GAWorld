"""Dashboard backend for 真人蒸馏 — Agent Studio's "build a resident from a
real person" panel.

A *delegate* module following the ``interview_api`` / ``city_api`` precedent:
``dashboard_server.py`` gains four lines of forwarding rather than another
subsystem's routes.

Distillation is a **job**, not a request handler: four live searches plus four
page fetches plus two model calls is 30-90 seconds, which no browser should sit
on. Start it, poll it, read the persona when it lands — the same pattern the
population and interview panels use.

Deployment is deliberately separate from distillation. Distilling writes only
into ``output/personas/``; deploying is what touches the seed CSV and the
profile Markdown that the simulator reads. The operator reviews the persona in
between, which is the whole point of the panel — this is a claim about a real
person, and nothing about it should land in a running world unreviewed.
"""

from __future__ import annotations

import csv
import json
import os
import threading
import time
import traceback
import uuid
from typing import Any

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.persona")

#: job id → record. One table per delegate, matching ``interview_api``.
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 10

#: One distillation at a time. Two concurrent runs would double the outbound
#: request rate against the same handful of search hosts, which is exactly what
#: ``io.http_guard`` exists to prevent.
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
            _LOG.exception("persona job %s failed", job_id)
            _update_job(
                job_id,
                status="error",
                message=str(exc),
                error={"type": type(exc).__name__, "detail": traceback.format_exc(limit=5)},
                finished_at=time.time(),
            )

    threading.Thread(target=runner, name=f"persona-{job_id}", daemon=True).start()


def job_status(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        if not record:
            return None
        # Matches interview_api: NaN/Infinity would make JSON.parse throw away
        # the whole response rather than just the offending key.
        return json.loads(json.dumps(record, ensure_ascii=False), parse_constant=lambda _: None)


# ---------------------------------------------------------------------------
# Distillation
# ---------------------------------------------------------------------------


#: The framework prompt asks for three mental models with quoted evidence plus
#: nine state seeds — three thousand characters of JSON before a reasoning
#: model's thinking block is counted. ``providers._build`` falls back to 512
#: when a configured provider omits ``max_tokens`` (which ``dashboard_config``'s
#: own MiniMax entry does), and every distillation then arrived truncated:
#: ``parse_json_object`` repaired what it could and the rest of the framework
#: was simply missing. Stated here rather than left to configuration because it
#: is a property of *these prompts*, not of the deployment.
#: Matched to ``settings.llm``'s own MiniMax default rather than trimmed to
#: what the answer needs: on a reasoning model the ``thinking`` block is
#: charged against the same budget, so a ceiling sized for the JSON alone is
#: spent before the text block starts and the caller receives "".
DISTILL_MAX_TOKENS = 16384


def _llm_fn(provider: str | None = None):
    from gaworld.llm.providers import call_llm

    def call(prompt: str) -> str:
        return call_llm(
            prompt,
            task="persona_distill",
            provider=provider or None,
            max_tokens=DISTILL_MAX_TOKENS,
        ) or ""

    return call


def _news_config() -> dict[str, Any]:
    from gaworld.apps import dashboard_server as ds

    return (ds.CONFIG.get("news", {}) or {}) if isinstance(getattr(ds, "CONFIG", None), dict) else {}


def _distill_now(subject: str, provider: str | None, progress: Any) -> dict[str, Any]:
    from gaworld.persona import distill as distill_mod
    from gaworld.persona import research as research_mod
    from gaworld.persona import store as store_mod

    with _RUN_LOCK:
        dossier = research_mod.research(
            subject,
            search_fn=research_mod.default_search_fn(_news_config()),
            fetch_fn=research_mod.default_fetch_fn(),
            wiki_fn=research_mod.default_wiki_fn(),
            progress=lambda f, m: progress(0.05 + 0.45 * f, m),
        )
        profile = distill_mod.distill(
            dossier,
            llm_fn=_llm_fn(provider),
            progress=lambda f, m: progress(0.5 + 0.45 * f, m),
        )
        store_mod.save(profile, dossier)
    return {"persona": profile.to_dict(), "slug": profile.slug}


def start_distill(payload: dict[str, Any]) -> dict[str, Any]:
    subject = str((payload or {}).get("subject") or "").strip()
    if not subject:
        raise ValueError("请填写姓名或网址")
    provider = str((payload or {}).get("provider") or "").strip() or None
    job_id = _new_job("distill")
    _run_in_background(job_id, lambda progress: _distill_now(subject, provider, progress))
    return {"job_id": job_id, "subject": subject}


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def personas() -> dict[str, Any]:
    from gaworld.persona import store as store_mod

    return {"personas": store_mod.list_personas()}


def detail(slug: str) -> dict[str, Any] | None:
    from gaworld.persona import store as store_mod

    profile = store_mod.load(slug)
    if profile is None:
        return None
    from gaworld.persona.render import profile_block, skill_markdown

    return {
        "persona": profile.to_dict(),
        "profile_block": profile_block(profile),
        "skill_markdown": skill_markdown(profile),
        "dir": str(store_mod.persona_dir(slug)),
    }


# ---------------------------------------------------------------------------
# Deployment — the only path here that writes into the simulated world
# ---------------------------------------------------------------------------


def _seed_big5(agent_id: int, name: str, values: dict[str, float]) -> bool:
    """Append this resident's OCEAN row to the Big Five seed CSV.

    ``dashboard_server._save_agent_big5`` only *edits* an existing row — the
    sampler writes them for the seeded population — so a resident created here
    has nowhere to be written to until this appends one. Returns False (rather
    than raising) when the file is absent: the Big Five plugin is optional, and
    a missing personality seed must not cost the operator the whole deployment.
    """
    from gaworld.apps import dashboard_server as ds

    fieldnames, rows = ds._read_big5_rows()
    if not fieldnames:
        return False
    row = {key: "" for key in fieldnames}
    row.update({"id": agent_id, "name": name, "source": "persona_distilled"})
    for dim in ds.BIG5_DIMENSIONS:
        if dim in fieldnames:
            row[dim] = f"{float(values.get(dim, 0.0)):.4f}"
    rows = [r for r in rows if ds._row_id(r) != int(agent_id)] + [row]
    tmp_path = ds.BIG5_CSV_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in rows:
            writer.writerow({key: item.get(key, "") for key in fieldnames})
    os.replace(tmp_path, ds.BIG5_CSV_PATH)
    return True


def deploy(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a resident from a stored persona.

    ``identity`` / ``state`` overrides are whatever the operator edited in the
    panel before pressing 部署 — the persona on disk stays as distilled, so a
    later reader can still see what the sources supported versus what a human
    decided.
    """
    from gaworld.apps import dashboard_server as ds
    from gaworld.persona import store as store_mod
    from gaworld.persona.distill import clamp_state
    from gaworld.persona.render import agent_payload, insert_block, profile_block

    slug = str((payload or {}).get("slug") or "").strip()
    profile = store_mod.load(slug)
    if profile is None:
        raise ValueError(f"找不到画像 {slug!r}")

    body = agent_payload(profile)
    overrides = (payload or {}).get("identity") or {}
    for key in ("name", "gender", "age", "hukou", "residence", "job", "personality",
                "daily_life", "values", "education_income", "social_network"):
        value = overrides.get(key)
        if value not in (None, ""):
            body[key] = value
    if (payload or {}).get("state"):
        body["state"] = clamp_state(payload["state"])

    created = ds._create_agent(body)
    agent_id = created["id"]

    block = profile_block(profile)
    if block:
        section = ds._agent_profile(agent_id) or {}
        ds._save_agent_profile(agent_id, insert_block(section.get("text") or "", block))

    big5_written = _seed_big5(agent_id, body["name"], profile.big5)

    profile.agent_id = agent_id
    store_mod.save(profile)
    _LOG.info("persona %s deployed as agent %s", slug, agent_id)
    return {
        "agent_id": agent_id,
        "name": created["name"],
        "slug": slug,
        "framework_written": bool(block),
        "big5_written": big5_written,
    }


def install_skill(payload: dict[str, Any]) -> dict[str, Any]:
    from gaworld.persona import store as store_mod

    slug = str((payload or {}).get("slug") or "").strip()
    if not slug:
        raise ValueError("缺少画像标识")
    return store_mod.install_skill(slug, overwrite=bool((payload or {}).get("overwrite")))


def delete(payload: dict[str, Any]) -> dict[str, Any]:
    from gaworld.persona import store as store_mod

    slug = str((payload or {}).get("slug") or "").strip()
    return {"deleted": store_mod.delete(slug), "slug": slug}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    try:
        if path == "/api/persona/list":
            return personas(), 200
        if path.startswith("/api/persona/jobs/"):
            record = job_status(path.rsplit("/", 1)[-1])
            if record is None:
                return {"error": "Unknown job"}, 404
            return record, 200
        if path.startswith("/api/persona/detail/"):
            found = detail(path.split("/", 4)[4])
            if found is None:
                return {"error": "Unknown persona"}, 404
            return found, 200
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown persona endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/persona/distill":
            return start_distill(payload), 202
        if path == "/api/persona/deploy":
            return deploy(payload), 200
        if path == "/api/persona/install-skill":
            return install_skill(payload), 200
        if path == "/api/persona/delete":
            return delete(payload), 200
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown persona endpoint"}, 404


__all__ = [
    "deploy",
    "detail",
    "handle_get",
    "handle_post",
    "install_skill",
    "job_status",
    "personas",
    "start_distill",
]
