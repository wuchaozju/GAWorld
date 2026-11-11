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

When the run never touched a resident there is no file to read — but a home
is a *procedural* design (seeded by agent id + income tier + ``home.seed``),
so the same resident always gets the same flat. In that case the endpoint
rebuilds the design from the city's roster and marks it ``source="preview"``:
the card shows the home the resident has, and says that it was computed
rather than simulated.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from gaworld.apps import world_paths
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.apps.home_api")


#: Cap the per-tick tail we ship to the dashboard. The plugin writes ~1 row
#: per tick; 200 rows is roughly 1 day at the default tick granularity.
OBSERVATION_TAIL = 200

#: The roster CSV is re-read only when the file changed (the dashboard writes
#: it when a resident is edited), so a preview costs one ``stat`` per request.
_ROSTER_CACHE: dict[str, Any] = {"path": "", "mtime": -1.0, "rows": []}


def _output_root() -> Path:
    """``<run root>/home``: where the home plugin of the active run writes.

    The plugin writes under ``output_root`` (``output`` by default, the world's
    or city's run root otherwise), so read the same key the dashboard's active
    world resolves, anchored at the dashboard's ``REPO_ROOT``."""

    root = str(world_paths.effective_config().get("output_root") or "output")
    return Path(world_paths.REPO_ROOT) / root / "home"


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


# ---------------------------------------------------------------------------
# Preview: the home of a resident the last run never touched.
# ---------------------------------------------------------------------------


def _roster_rows() -> list[dict[str, Any]]:
    """The running city's roster — the same CSV ``/api/agents`` reads."""
    path = world_paths.state_csv_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return []
    cache = _ROSTER_CACHE
    if cache["path"] == path and cache["mtime"] == mtime:
        return cache["rows"]
    rows: list[dict[str, Any]] = []
    try:
        with open(path, newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if isinstance(row, dict):
                    rows.append(row)
    except (OSError, csv.Error) as exc:
        _LOG.warning("home_api: roster read %s failed: %s", path, exc)
        return []
    _ROSTER_CACHE.update({"path": path, "mtime": mtime, "rows": rows})
    return rows


def _roster_row(agent_id: int) -> dict[str, Any] | None:
    for row in _roster_rows():
        try:
            if int(float(row.get("id"))) == int(agent_id):
                return row
        except (TypeError, ValueError):
            continue
    return None


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _residence_district(row: dict[str, Any]) -> str:
    """``Rotherhithe·联排住宅`` -> ``Rotherhithe``.

    A resident outside a run has no map node for their building yet; the
    district they live in is the honest label for their flat.
    """
    text = str(row.get("residence") or "").strip()
    if not text:
        return ""
    for sep in ("·", "・", " ", "，", ","):
        if sep in text:
            return text.split(sep)[0].strip()
    return text[:3]


def _preview_design(agent_id: int) -> dict[str, Any] | None:
    """The home this resident *would* have — computed, never simulated.

    The home plugin draws a flat procedurally: the draw is seeded by agent id
    and ``home.seed``, and the room set follows the income tier. So the flat
    this returns is the same one a run would produce for that resident (only
    the building label differs — a run resolves it to a map node).
    """
    if not (world_paths.effective_config().get("home") or {}).get("enabled", True):
        # The plugin is off: there are no homes in this world.
        return None
    row = _roster_row(agent_id)
    if not row:
        return None
    from gaworld.world import home_environment as he

    agent = {
        "id": int(agent_id),
        "name": str(row.get("name") or ""),
        "monthly_income": _to_float(row.get("monthly_income")),
        "locations": {"home": _residence_district(row)},
    }
    seed = (world_paths.effective_config().get("home") or {}).get("seed")
    return he.design_home(agent, seed=seed)


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
    return {"error": "Unknown endpoint"}, 404


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
    source = "run"
    if design is None:
        # No file from the last run: rebuild the flat the resident has.
        design = _preview_design(agent_id)
        source = "preview"
    if design is None:
        return {
            "error": f"agent {agent_id} has no home design yet",
            "reason": "no_home_design",
            "has_home": False,
        }, 404

    tail = _read_tail(root / f"agent_{agent_id}.jsonl")
    tail_count_raw = (query.get("tail") or query.get("tail_count") or [""])[0]
    try:
        tail_count = max(1, min(OBSERVATION_TAIL, int(tail_count_raw or OBSERVATION_TAIL)))
    except ValueError:
        tail_count = OBSERVATION_TAIL

    summary = _summary(design)
    return {
        "agent_id": agent_id,
        "has_home": True,
        # "run" — written by the plugin during a simulation.
        # "preview" — rebuilt from the roster (the resident never ran).
        "source": source,
        "summary": summary,
        "design": design,
        "observations": tail[-tail_count:],
        "observation_count": len(tail),
    }, 200


def parse_query(qs: str) -> dict[str, list[str]]:
    """Thin wrapper so callers can pass a raw querystring in tests."""
    return parse_qs(qs)
