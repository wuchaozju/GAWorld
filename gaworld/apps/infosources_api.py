"""Read-only HTTP view of the information-source layer (``gaworld/infosources``).

Everything here is read from files the plugin already writes — the registry,
the feed cache and ``diets.json`` — plus the ``infosources.read`` record table,
so the endpoints work whether or not a run is in progress. Writing goes through
the kernel: ``POST /api/interventions/inject_info_item`` during a run.
"""

from __future__ import annotations

import json
import os
from typing import Any

from gaworld.infosources import feed as feed_impl
from gaworld.infosources import registry as registry_impl


def _ds():
    from gaworld.apps import dashboard_server

    return dashboard_server


def _cfg() -> dict[str, Any]:
    return dict(((_ds().CONFIG.get("news") or {}).get("sources")) or {})


def _repo(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(_ds().REPO_ROOT, path)


def _first(query: dict, key: str, default: str = "") -> str:
    values = query.get(key) or [default]
    return str(values[0]).strip()


def _int(query: dict, key: str, default: int) -> int:
    try:
        return max(1, int(_first(query, key, str(default))))
    except ValueError:
        return default


def _cache():
    return feed_impl.load(_repo(_cfg().get("feed_cache_path", "output/infosources/feed.json")))


def sources_payload() -> dict[str, Any]:
    sources = registry_impl.load_registry(
        _repo(_cfg().get("registry_path", registry_impl.DEFAULT_REGISTRY_PATH))
    )
    cache = _cache()
    counts = cache.counts()
    return {
        "sources": [
            {**s.to_dict(), "items": counts.get(s.id, 0), "last_fetch": cache.last_fetch.get(s.id, "")}
            for s in sources
        ]
    }


def feed_payload(query: dict) -> dict[str, Any]:
    cache = _cache()
    source_id = _first(query, "source_id")
    limit = _int(query, "limit", 20)
    if source_id:
        items = cache.items_for(source_id)
    else:
        items = cache.all_items()
    return {"source_id": source_id or None, "items": [i.to_dict() for i in items[:limit]]}


def diets_payload(query: dict) -> tuple[dict[str, Any], int]:
    path = _repo(os.path.join(_ds().CONFIG.get("output_root", "output"), "infosources", "diets.json"))
    try:
        with open(path, "r", encoding="utf-8") as f:
            diets = json.load(f)
    except (OSError, ValueError):
        diets = {}
    agent_id = _first(query, "agent_id")
    if agent_id:
        if agent_id not in diets:
            return {"error": f"no diet for agent {agent_id} (has a run built diets yet?)"}, 404
        return {"agent_id": agent_id, **diets[agent_id]}, 200
    return {"diets": diets}, 200


def reads_payload(query: dict) -> dict[str, Any]:
    """Recent ``infosources.read`` rows, newest first, filterable by item/source/agent."""
    path = os.path.join(_ds().RECORDS_DIR, "infosources.read.jsonl")
    want = {k: _first(query, k) for k in ("url", "source_id", "agent_id")}
    limit = _int(query, "limit", 100)
    rows: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if all(not v or str(row.get(k, "")) == v for k, v in want.items()):
                    rows.append(row)
    except OSError:
        pass
    rows.reverse()
    return {"total": len(rows), "reads": rows[:limit]}


def handle_get(path: str, query: dict) -> tuple[dict[str, Any], int]:
    route = path.rstrip("/")
    if route == "/api/infosources/sources":
        return sources_payload(), 200
    if route == "/api/infosources/feed":
        return feed_payload(query), 200
    if route == "/api/infosources/diets":
        return diets_payload(query)
    if route == "/api/infosources/reads":
        return reads_payload(query), 200
    return {"error": "Unknown endpoint"}, 404
