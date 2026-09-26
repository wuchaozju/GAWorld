"""HTTP handlers for the home-environment plugin's dashboard panel.

Two read-only endpoints:

- ``GET /api/home`` — list every agent that has a designed home. Useful for
  the analytics panel that wants to know how many homes have been seeded and
  what the room mix looks like.
- ``GET /api/home/<id>`` — full home design + the per-tick observation tail
  (last 200 rows) for one agent. Drives the dashboard's at-home panel.

The data lives in ``output/home/agent_<id>.json`` (one snapshot per agent,
written by :mod:`gaworld.world.home_plugin` once on seeding) and
``output/home/agent_<id>.jsonl`` (one row per tick the agent was actually
at home). This module only *reads*; the plugin owns the writes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.apps.home_api")


#: Cap the per-tick tail we ship to the dashboard. The plugin writes ~1 row
#: per tick; 200 rows is roughly 1 day at the default tick granularity.
OBSERVATION_TAIL = 200


def _output_root() -> Path:
    """Resolve ``output/home`` next to the repo root.

    Mirrors how ``dashboard_server.py`` resolves ``REPO_ROOT``: the config
    doesn't pin this directory, so the plugin's writer and this reader both
    default to ``<repo>/output/home``."""
    # ``dashboard_server`` puts REPO_ROOT three levels above its own file;
    # we are called from there, so use the same anchor.
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        if (ancestor / "dashboard_config.json").exists() or (ancestor / "gaworld").is_dir():
            return ancestor / "output" / "home"
    # Fallback: best-effort relative path.
    return Path(os.getcwd()) / "output" / "home"


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        _LOG.warning("home_api: read %s failed: %s", path, exc)
        return None
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError as exc:
        _LOG.warning("home_api: parse %s failed: %s", path, exc)
        return None


def _read_tail(path: Path, max_rows: int = OBSERVATION_TAIL) -> list[dict[str, Any]]:
    """Return up to ``max_rows`` trailing rows from a JSONL file."""
    if not path.exists():
        return []
    try:
        # Reading the whole file is fine here: a single agent's at-home
        # cadence tops out at ~rows-per-day, which stays well under 1 MB.
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _LOG.warning("home_api: tail read %s failed: %s", path, exc)
        return []
    rows: list[dict[str, Any]] = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            rows.append(json.loads(raw))
        except ValueError:
            continue
    if len(rows) > max_rows:
        rows = rows[-max_rows:]
    return rows


def _summary(home: dict[str, Any]) -> dict[str, Any]:
    """One-line summary for the list view."""
    rooms = home.get("rooms") or {}
    return {
        "home_id": home.get("home_id"),
        "home_node": home.get("home_node"),
        "rooms": list(rooms.keys()),
        "room_count": len(rooms),
        "ambiance_quality": home.get("ambiance_quality"),
        "vibe": home.get("vibe"),
    }


def handle_get(path: str, query: dict[str, list[str]] | None = None) -> tuple[Any, int]:
    """Dispatch one ``GET /api/home[/...]`` request."""
    parts = [p for p in path.split("/") if p]
    # /api/home
    if len(parts) == 2 and parts[0] == "api" and parts[1] == "home":
        return _list_homes(), 200
    # /api/home/<id>
    if len(parts) == 3 and parts[0] == "api" and parts[1] == "home":
        try:
            agent_id = int(parts[2])
        except ValueError:
            return {"error": "agent_id must be an integer"}, 400
        return _home_for(agent_id, query or {})
    return {"error": "not found"}, 404


def _list_homes() -> dict[str, Any]:
    root = _output_root()
    if not root.exists():
        return {"homes": [], "count": 0}
    homes: list[dict[str, Any]] = []
    for path in sorted(root.glob("agent_*.json")):
        data = _safe_read_json(path)
        if not data:
            continue
        try:
            agent_id = int(path.stem.split("_", 1)[1])
        except (IndexError, ValueError):
            continue
        summary = _summary(data)
        summary["agent_id"] = agent_id
        homes.append(summary)
    return {"homes": homes, "count": len(homes)}


def _home_for(agent_id: int, query: dict[str, list[str]]) -> tuple[dict[str, Any], int]:
    root = _output_root()
    design = _safe_read_json(root / f"agent_{agent_id}.json")
    if design is None:
        return {"error": f"agent {agent_id} has no home design yet"}, 404

    tail = _read_tail(root / f"agent_{agent_id}.jsonl")
    tail_count_raw = (query.get("tail") or query.get("tail_count") or [""])[0]
    try:
        tail_count = max(1, min(OBSERVATION_TAIL, int(tail_count_raw or OBSERVATION_TAIL)))
    except ValueError:
        tail_count = OBSERVATION_TAIL

    summary = _summary(design)
    return {
        "agent_id": agent_id,
        "summary": summary,
        "design": design,
        "observations": tail[-tail_count:],
        "observation_count": len(tail),
    }, 200


def parse_query(qs: str) -> dict[str, list[str]]:
    """Thin wrapper so callers can pass a raw querystring in tests."""
    return parse_qs(qs)
