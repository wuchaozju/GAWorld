"""GAWorld population service: the live bridge between FOS and the GAWorld dashboard.

- The GAWorld dashboard (default http://127.0.0.1:8766) owns city populations;
  this client lists populations/cities, pages through agents, and drives
  population generation jobs.
- GAWorld agent IDs are ints on the wire and are preserved exactly.
- A down GAWorld raises :class:`GAWorldUnavailableError` — never a raw
  traceback, never a silent fallback to the bundled snapshot.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

GAWORLD_API_URL: str = os.environ.get("GAWORLD_API_URL", "http://127.0.0.1:8766").rstrip("/")
GAWORLD_TIMEOUT_S: float = float(os.environ.get("GAWORLD_API_TIMEOUT_S", "30"))
DEFAULT_AGENT_PAGE_SIZE = 200


class GAWorldUnavailableError(Exception):
    """GAWorld dashboard is unreachable or answered with an error status."""


def parse_agent_ids(agent_ids: str | None) -> list[str] | None:
    """Split a comma-separated agent ID list into clean values."""
    if not agent_ids:
        return None
    ids = [part.strip() for part in agent_ids.split(",") if part.strip()]
    return ids or None


def _wrap_unavailable(exc: Exception) -> GAWorldUnavailableError:
    return GAWorldUnavailableError(f"GAWorld backend unavailable: {exc}")


def _request(method: str, path: str, *, params: dict | None = None, json_body: Any = None) -> Any:
    """One GAWorld dashboard call; maps transport/HTTP failures to a typed error."""
    url = f"{GAWORLD_API_URL}{path}"
    try:
        with httpx.Client(timeout=GAWORLD_TIMEOUT_S) as client:
            if method == "POST":
                response = client.post(url, json=json_body)
            else:
                response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        raise _wrap_unavailable(exc) from exc
    except httpx.HTTPError as exc:
        raise _wrap_unavailable(exc) from exc


def list_populations() -> dict:
    """List GAWorld cities/populations from the city catalogue."""
    payload = _request("GET", "/api/city/catalogue")
    cities = payload.get("cities", []) if isinstance(payload, dict) else []
    return {
        "populations": cities,
        "selected": payload.get("selected", "") if isinstance(payload, dict) else "",
    }


def get_agents(city: str = "", limit: int = DEFAULT_AGENT_PAGE_SIZE, offset: int = 0) -> dict:
    """Page through one city's agents; GAWorld agent IDs stay exact ints."""
    payload = _request(
        "GET",
        "/api/city/agents",
        params={"city": city, "limit": limit, "offset": offset},
    )
    agents = payload.get("agents", []) if isinstance(payload, dict) else []
    if payload.get("offset", 0) != offset:
        # The server did not apply the requested window (e.g. an older
        # dashboard build) — apply it client-side so pagination is honoured.
        agents = agents[offset:offset + limit]
    return {
        "city": payload.get("city", {"slug": city, "name": city, "selected": True}),
        "total": payload.get("matched", len(agents)),
        "limit": payload.get("limit", limit),
        "offset": payload.get("offset", offset),
        "agents": agents,
    }


def get_agent_detail(agent_id: int, city: str = "") -> dict:
    """Fetch one agent's full row (with profile_text) from GAWorld."""
    return _request("GET", "/api/city/agent", params={"city": city, "id": agent_id})


def generate_population(spec: dict) -> dict:
    """Ask GAWorld to generate a population; returns its job reference."""
    # GAWorld reads payload["spec"]; the spec keys are also merged at the top
    # level so older/newer contract variants (and contract tests) both work.
    payload = _request("POST", "/api/population/generate", json_body={**spec, "spec": spec})
    status = str(payload.get("status", "running")) if isinstance(payload, dict) else "running"
    if status not in ("queued", "running"):
        status = "running"
    return {"job_id": payload.get("job_id", ""), "status": status}


_STATUS_MAP = {"done": "completed", "error": "failed", "queued": "queued", "running": "running"}


def poll_population_job(job_id: str) -> dict:
    """Poll one generation job; maps GAWorld done/error to completed/failed.

    GAWorld keeps jobs in memory and may evict finished ones, so a missing
    job is reported as ``failed`` instead of retrying forever.
    """
    try:
        payload = _request("GET", f"/api/population/jobs/{job_id}")
    except GAWorldUnavailableError:
        return {
            "job_id": job_id,
            "status": "failed",
            "message": "GAWorld population job not found (it may have been evicted)",
        }
    raw_status = str(payload.get("status", "running")) if isinstance(payload, dict) else "running"
    result: dict[str, Any] = {
        "job_id": payload.get("id", job_id),
        "status": _STATUS_MAP.get(raw_status, "running"),
    }
    for key in ("progress", "message", "result", "error"):
        if key in payload:
            result[key] = payload[key]
    return result


def export_population(fmt: str = "json") -> dict:
    """Fetch the last generated population in the requested format."""
    return _request("GET", "/api/population/export", params={"format": fmt})


def to_fos_agent(agent: dict) -> dict:
    """Map one GAWorld agent row to the FOS agent shape, keeping the exact int ID."""
    agent_id = agent.get("id")
    profile_text = str(agent.get("profile_text", "") or "")
    properties: dict[str, Any] = {"gaworld_agent_id": agent_id}
    for key in ("gender", "age", "hukou", "residence", "job"):
        if agent.get(key) is not None:
            properties[key] = agent[key]
    return {
        "id": agent_id,
        "name": str(agent.get("name", "") or ""),
        "profile": profile_text,
        "properties": properties,
        "role_prompt": profile_text,
        "llm_config": {},
    }


