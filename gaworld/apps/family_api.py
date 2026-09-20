"""Dashboard backend for the 家庭 card and the Agent Studio family editor.

A *delegate* module, following the ``population_api`` precedent: the family
tier is self-contained, and ``dashboard_server.py`` gains four lines of
forwarding rather than another branch of subsystem logic.

Two read paths, answering two different questions — the distinction matters
enough to state up front:

* :func:`overview` (the dashboard card) serves the **recorded** run:
  ``output/records/family.{summary,household,agent}.jsonl``. Re-deriving it
  on request would silently disagree with the run whenever the config had
  changed since it started, and a card that shows a *different* family than
  the one the agents are living in is worse than one showing the last
  recorded state.
* :func:`preview` (the Studio editor) deliberately re-derives, because the
  question there is the opposite one: *what will this agent's family be next
  time I press run, if I save this?* Editing blind and finding out a day
  later is the whole failure mode the editor exists to remove.

Path constants are read from ``dashboard_server`` at call time (not imported
at module load) so the existing tests' monkeypatching of output paths lands.
"""

from __future__ import annotations

import json
import os
from typing import Any

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.family")

#: Only the last row per table is ever meaningful for summary; households and
#: agents are keyed, so later rows win. A run left going for weeks should not
#: make this endpoint read a hundred megabytes.
_MAX_ROWS = 20000


def _records_dir() -> str:
    from gaworld.apps import dashboard_server as ds

    return str(getattr(ds, "RECORDS_DIR", os.path.join("output", "records")))


def _read_table(name: str) -> list[dict[str, Any]]:
    path = os.path.join(_records_dir(), f"{name}.jsonl")
    if not os.path.exists(path):
        return []
    rows: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                if len(rows) > _MAX_ROWS:
                    del rows[: len(rows) // 2]
    except OSError as exc:
        _LOG.warning("reading %s failed: %s", path, exc)
    return rows


def _dedupe(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Keep the last row per key — a re-run appends rather than truncating."""
    latest: dict[Any, dict[str, Any]] = {}
    for row in rows:
        if key in row:
            latest[row[key]] = row
    return list(latest.values())


def overview() -> dict[str, Any]:
    """Everything the card needs, in one request."""
    households = _dedupe(_read_table("family.household"), "id")
    agents = _dedupe(_read_table("family.agent"), "agent_id")
    summary_rows = _read_table("family.summary")
    summary = summary_rows[-1] if summary_rows else {}

    if not summary and agents:
        # A run that recorded agents but no summary (older output, or a
        # partially-written file) should still render rather than show
        # "no data".
        types: dict[str, int] = {}
        statuses: dict[str, int] = {}
        for row in agents:
            types[row.get("household_type", "?")] = types.get(row.get("household_type", "?"), 0) + 1
            statuses[row.get("marital_status", "?")] = (
                statuses.get(row.get("marital_status", "?"), 0) + 1
            )
        summary = {
            "agents": len(agents),
            "households": len(households),
            "household_types": types,
            "marital_statuses": statuses,
        }

    finance = _read_table("family.finance")
    spend = {}
    for row in finance:
        hid = row.get("household")
        if not hid:
            continue
        entry = spend.setdefault(hid, {"dependant_cost": 0.0, "partner_transfer": 0.0, "days": 0})
        entry["dependant_cost"] += float(row.get("dependant_cost", 0) or 0)
        entry["partner_transfer"] += float(row.get("partner_transfer", 0) or 0)
        entry["days"] += 1

    return {
        "available": bool(agents or households),
        "summary": summary,
        "households": sorted(households, key=lambda h: str(h.get("id", ""))),
        "agents": sorted(agents, key=lambda a: int(a.get("agent_id", 0) or 0)),
        "finance": spend,
    }


# ---------------------------------------------------------------------------
# Studio editor: preview + overrides
# ---------------------------------------------------------------------------


def _roster() -> list[dict[str, Any]]:
    """Minimal agent dicts for a preview assignment, read from the state CSV.

    ``assign_households`` only needs identity and residence; it does not need
    the city map, memories or state. Building the roster from the CSV keeps
    the preview cheap and keeps this module out of the simulator's import
    graph.
    """
    from gaworld.apps import dashboard_server as ds

    rows = ds._read_state_rows()[1]
    roster: list[dict[str, Any]] = []
    for row in rows:
        agent_id = ds._row_id(row)
        if agent_id is None:
            continue
        try:
            age = int(float(row.get("age") or 0))
        except (TypeError, ValueError):
            age = 0
        roster.append(
            {
                "id": agent_id,
                "name": str(row.get("name", "") or ""),
                "age": age,
                "gender": str(row.get("gender", "") or ""),
                "hukou": str(row.get("hukou", "") or ""),
                "residence": str(row.get("residence", "") or ""),
                "locations": {},
            }
        )
    return roster


def preview(agent_id: int | None = None) -> dict[str, Any]:
    """Assign households over the current roster + overrides, without a run."""
    from gaworld.family.assign import assign_households
    from gaworld.family.duties import daily_duties
    from gaworld.family.narrative import family_brief
    from gaworld.family.overrides import cross_check, load_overrides
    from gaworld.settings import CONFIG

    roster = _roster()
    overrides = load_overrides(CONFIG)
    assignment = assign_households(roster, CONFIG, overrides)
    by_name = {int(a["id"]): a for a in roster}

    rows = []
    for aid, record in sorted(assignment.by_agent.items()):
        agent = by_name.get(aid, {})
        rows.append(
            {
                "agent_id": aid,
                "name": agent.get("name", ""),
                "age": agent.get("age"),
                "gender": agent.get("gender", ""),
                "household_id": record.get("household_id", ""),
                "household_type": record.get("household_type", ""),
                "marital_status": record.get("marital_status", ""),
                "members": record.get("members", []),
                "brief": family_brief(record),
                "pinned": aid in overrides,
            }
        )

    payload: dict[str, Any] = {
        "summary": assignment.summary(),
        "agents": rows,
        "warnings": cross_check(overrides),
    }
    if agent_id is not None:
        selected = next((r for r in rows if r["agent_id"] == int(agent_id)), None)
        payload["selected"] = selected
        payload["override"] = overrides.get(int(agent_id), {})
        if selected:
            record = assignment.by_agent[int(agent_id)]
            payload["duties"] = {
                "weekday": daily_duties(record, day=2, is_weekend=False, config=CONFIG),
                "weekend": daily_duties(record, day=6, is_weekend=True, config=CONFIG),
            }
        # Candidate partners: everyone else in the roster. The editor shows
        # them all rather than pre-filtering by age gap — an operator pinning
        # a couple is overriding the demographics on purpose, and a dropdown
        # that hides the person they want reads as a bug.
        payload["candidates"] = [
            {
                "agent_id": a["id"],
                "name": a["name"],
                "age": a["age"],
                "gender": a["gender"],
                "residence": a["residence"],
            }
            for a in roster
            if int(a["id"]) != int(agent_id)
        ]
    return payload


def save_override(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    from gaworld.family.overrides import (
        OverrideError,
        load_overrides,
        normalize_override,
        save_overrides,
    )
    from gaworld.settings import CONFIG

    if not isinstance(payload, dict):
        return {"error": "请求体必须是一个对象"}, 400
    try:
        agent_id = int(payload.get("agent_id"))
    except (TypeError, ValueError):
        return {"error": "缺少 agent_id"}, 400

    overrides = load_overrides(CONFIG)
    if payload.get("clear"):
        overrides.pop(agent_id, None)
    else:
        try:
            record = normalize_override(payload.get("override") or {}, agent_id=agent_id)
        except OverrideError as exc:
            return {"error": str(exc)}, 400
        if record:
            overrides[agent_id] = record
        else:
            # Saving an empty edit means "stop pinning this agent" — the same
            # thing the 恢复自动生成 button does, so treat it that way rather
            # than persisting a record that pins nothing.
            overrides.pop(agent_id, None)

    try:
        path = save_overrides(overrides, CONFIG)
    except OSError as exc:
        return {"error": f"写入覆盖文件失败：{exc}"}, 500
    _LOG.info("family override saved for agent %s -> %s", agent_id, path)
    result = preview(agent_id)
    result["saved"] = True
    result["path"] = path
    return result, 200


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Route ``/api/family/*`` POSTs. Returns ``(payload, status)``."""
    if path in ("/api/family/override", "/api/family/override/"):
        return save_override(payload)
    return {"error": f"unknown family endpoint: {path}"}, 404


def handle_get(path: str, query: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Route ``/api/family/*`` GETs. Returns ``(payload, status)``."""
    if path in ("/api/family", "/api/family/", "/api/family/overview"):
        return overview(), 200
    if path in ("/api/family/preview", "/api/family/override"):
        raw = (query.get("agent_id") or [None])[0] if isinstance(query, dict) else None
        agent_id: int | None
        try:
            agent_id = int(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            return {"error": "agent_id must be an integer"}, 400
        try:
            return preview(agent_id), 200
        except Exception as exc:  # a preview must never take the panel down
            _LOG.warning("family preview failed: %s", exc)
            return {"error": f"预览失败：{exc}"}, 500
    if path == "/api/family/agent":
        raw = (query.get("agent_id") or [None])[0] if isinstance(query, dict) else None
        try:
            agent_id = int(raw)
        except (TypeError, ValueError):
            return {"error": "agent_id is required and must be an integer"}, 400
        rows = _dedupe(_read_table("family.agent"), "agent_id")
        for row in rows:
            if int(row.get("agent_id", -1)) == agent_id:
                return row, 200
        return {"error": f"no family record for agent {agent_id}"}, 404
    return {"error": f"unknown family endpoint: {path}"}, 404
