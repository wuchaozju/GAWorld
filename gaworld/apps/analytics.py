"""Read-only aggregation of simulation artifacts for the dashboard Analytics view.

Every reader here degrades to an empty payload when its artifact is missing or
malformed, so a half-finished (or never-started) run still renders a page
instead of a stack trace. Nothing in this module writes to disk.

Each reader takes the directory its artifacts live in rather than the repo
root, so the same code serves the live ``output/`` tree and any past run's tree
(a scenario run, an archived trace) — the caller decides which run to read.
"""

from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict
from typing import Any

# Per-series point cap. A 50-agent x 21-metric run over hundreds of ticks
# serializes to megabytes otherwise, and no chart can show that many points.
MAX_SERIES_POINTS = 400

# Ledger columns worth charting over time; the rest of the row is dropped.
LEDGER_SERIES_KEYS = (
    "income",
    "expense",
    "balance",
    "checking",
    "savings",
    "investment",
    "debt",
    "econ_security",
    "engel_coefficient",
)

WEALTH_SNAPSHOT_KEYS = (
    "balance",
    "checking",
    "savings",
    "investment",
    "housing_fund",
    "debt",
    "net_monthly_salary",
    "monthly_tax",
    "engel_coefficient",
    "savings_rate",
    "lifetime_income",
    "lifetime_expense",
    "wealth_drive",
    "hourly_income",
    "investment_return_ytd",
    "initial_assets_total",
)

# Habit keys are "period|context|activity"; these are the periods the behavior
# module emits, ordered for the heatmap axis.
HABIT_PERIODS = ("morning", "noon", "afternoon", "evening", "night")


def _read_json(path: str, default: Any = None) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _read_csv(path: str) -> list[dict[str, str]]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return [dict(row) for row in csv.DictReader(f)]
    except OSError:
        return []


def _f(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
        return default
    return round(number, 6)


def _i(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _downsample(series: list[Any], cap: int = MAX_SERIES_POINTS) -> list[Any]:
    """Evenly thin ``series`` to at most ``cap`` points, keeping the last one.

    The final value matters most (it is what the delta charts compare against),
    so it is appended explicitly rather than left to the stride.
    """
    if len(series) <= cap:
        return series
    stride = len(series) / float(cap - 1)
    picked = [series[int(i * stride)] for i in range(cap - 1)]
    picked.append(series[-1])
    return picked


def _stats(series: list[float]) -> dict[str, float]:
    clean = [v for v in series if v is not None]
    if not clean:
        return {}
    return {
        "first": clean[0],
        "last": clean[-1],
        "delta": round(clean[-1] - clean[0], 6),
        "min": min(clean),
        "max": max(clean),
        "mean": round(sum(clean) / len(clean), 6),
    }


def _agent_label(agent_id: int, names: dict[int, str] | None) -> str:
    name = (names or {}).get(agent_id)
    return name or f"Agent {agent_id}"


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def state_history(output_dir: str, names: dict[int, str] | None = None) -> dict[str, Any]:
    """Per-agent trajectories of the normalized [0,1] state variables."""
    rows = _read_csv(os.path.join(output_dir, "state", "agent_state_history.csv"))
    # metric -> agent_id -> step -> value
    buckets: dict[str, dict[int, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        metric = (row.get("metric") or "").strip()
        agent_id = _i(row.get("agent_id"))
        step = _i(row.get("step"))
        value = _f(row.get("value"))
        if not metric or agent_id is None or step is None or value is None:
            continue
        buckets[metric][agent_id][step] = value

    agent_ids: set[int] = set()
    series: dict[str, dict[str, list[float]]] = {}
    deltas: dict[str, dict[str, dict[str, float]]] = {}
    steps = 0
    for metric, per_agent in buckets.items():
        series[metric] = {}
        deltas[metric] = {}
        for agent_id, by_step in per_agent.items():
            ordered = [by_step[step] for step in sorted(by_step)]
            if not ordered:
                continue
            agent_ids.add(agent_id)
            steps = max(steps, len(ordered))
            series[metric][str(agent_id)] = _downsample(ordered)
            deltas[metric][str(agent_id)] = _stats(ordered)

    return {
        "available": bool(series),
        "metrics": sorted(series),
        "agents": [
            {"id": agent_id, "name": _agent_label(agent_id, names)}
            for agent_id in sorted(agent_ids)
        ],
        "steps": steps,
        "sampled": steps > MAX_SERIES_POINTS,
        "series": series,
        "deltas": deltas,
    }


def economy(output_dir: str, names: dict[int, str] | None = None) -> dict[str, Any]:
    """Daily ledger trajectories, final wealth snapshot and macro cycle state."""
    econ_dir = os.path.join(output_dir, "economy")
    ledger_rows = _read_csv(os.path.join(econ_dir, "daily_ledger.csv"))

    per_agent: dict[int, dict[str, list[Any]]] = {}
    macro_phase_by_day: dict[int, str] = {}
    for row in ledger_rows:
        agent_id = _i(row.get("agent_id"))
        day = _i(row.get("day"))
        if agent_id is None or day is None:
            continue
        entry = per_agent.setdefault(agent_id, {"days": [], **{key: [] for key in LEDGER_SERIES_KEYS}})
        entry["days"].append(day)
        for key in LEDGER_SERIES_KEYS:
            entry[key].append(_f(row.get(key)))
        phase = (row.get("macro_phase") or "").strip()
        if phase:
            macro_phase_by_day[day] = phase

    ledger = []
    for agent_id in sorted(per_agent):
        entry = per_agent[agent_id]
        order = sorted(range(len(entry["days"])), key=lambda i: entry["days"][i])
        ledger.append(
            {
                "id": agent_id,
                "name": _agent_label(agent_id, names),
                "days": _downsample([entry["days"][i] for i in order]),
                **{key: _downsample([entry[key][i] for i in order]) for key in LEDGER_SERIES_KEYS},
            }
        )

    wealth = []
    for row in _read_csv(os.path.join(econ_dir, "wealth_snapshot.csv")):
        agent_id = _i(row.get("agent_id"))
        if agent_id is None:
            continue
        wealth.append(
            {
                "id": agent_id,
                "name": _agent_label(agent_id, names),
                "portfolio_type": (row.get("portfolio_type") or "").strip(),
                **{key: _f(row.get(key), 0.0) for key in WEALTH_SNAPSHOT_KEYS},
            }
        )
    wealth.sort(key=lambda item: item.get("balance") or 0.0, reverse=True)

    audit = _read_csv(os.path.join(econ_dir, "conservation_audit.csv"))
    conservation = None
    if audit:
        last = audit[-1]
        conservation = {
            "day": _i(last.get("day")),
            "agents_total": _f(last.get("agents_total"), 0.0),
            "firms": _f(last.get("firms"), 0.0),
            "government": _f(last.get("government"), 0.0),
            "bank": _f(last.get("bank"), 0.0),
            "system_total": _f(last.get("system_total"), 0.0),
            "drift": _f(last.get("drift"), 0.0),
        }

    macro = _read_json(os.path.join(econ_dir, "macro_state.json"), {}) or {}
    return {
        "available": bool(ledger or wealth),
        "ledger": ledger,
        "series_keys": list(LEDGER_SERIES_KEYS),
        "wealth": wealth,
        "conservation": conservation,
        "sectors": _read_json(os.path.join(econ_dir, "sectors.json"), {}) or {},
        "macro": {
            "phase": macro.get("phase") or "",
            "phase_day_counter": macro.get("phase_day_counter"),
            "phase_duration": macro.get("phase_duration"),
            "inflation_rate": _f(macro.get("inflation_rate")),
            "unemployment_rate": _f(macro.get("unemployment_rate")),
            "cumulative_inflation": _f(macro.get("cumulative_inflation")),
            "industry_conditions": macro.get("industry_conditions") or {},
        },
        "macro_timeline": [
            {"day": day, "phase": macro_phase_by_day[day]} for day in sorted(macro_phase_by_day)
        ],
    }


def _relationship_files(memory_dir: str) -> list[tuple[int, str]]:
    if not os.path.isdir(memory_dir):
        return []
    found = []
    for filename in sorted(os.listdir(memory_dir)):
        if not (filename.startswith("agent_") and filename.endswith("_relationships.json")):
            continue
        owner = _i(filename[len("agent_") : -len("_relationships.json")])
        if owner is not None:
            found.append((owner, os.path.join(memory_dir, filename)))
    return found


def social(memory_dir: str, names: dict[int, str] | None = None) -> dict[str, Any]:
    """Relationship graph across every agent that has a persisted memory file.

    Agent-to-agent ties are keyed by the peer's numeric id and are reciprocal,
    so they collapse into a single undirected link; ``g_*`` ghost ties are
    private to their owner and stay as leaf nodes.
    """
    nodes: dict[str, dict[str, Any]] = {}
    links: dict[tuple[str, str], dict[str, Any]] = {}
    tier_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()

    owners = _relationship_files(memory_dir)
    for owner, _path in owners:
        nodes[str(owner)] = {
            "id": str(owner),
            "label": _agent_label(owner, names),
            "kind": "agent",
            "agent_id": owner,
            "role": "",
        }

    for owner, path in owners:
        payload = _read_json(path, {}) or {}
        if not isinstance(payload, dict):
            continue
        for key, item in payload.items():
            if not isinstance(item, dict):
                continue
            kind = item.get("kind") or "agent"
            profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
            peer_id = _i(key)
            if kind == "agent" and peer_id is not None:
                node_id = str(peer_id)
                nodes.setdefault(
                    node_id,
                    {
                        "id": node_id,
                        "label": profile.get("name") or _agent_label(peer_id, names),
                        "kind": "agent",
                        "agent_id": peer_id,
                        "role": item.get("role") or "",
                    },
                )
            else:
                node_id = f"{owner}:{key}"
                nodes[node_id] = {
                    "id": node_id,
                    "label": profile.get("name") or str(key),
                    "kind": "ghost",
                    "agent_id": None,
                    "role": item.get("role") or "",
                }
            tier_counts[item.get("dunbar_tier") or "unknown"] += 1
            role_counts[item.get("role") or "unknown"] += 1
            edge = tuple(sorted((str(owner), node_id)))
            existing = links.get(edge)
            record = {
                "source": edge[0],
                "target": edge[1],
                "closeness": _f(item.get("closeness"), 0.0),
                "trust": _f(item.get("trust"), 0.0),
                "obligation": _f(item.get("obligation"), 0.0),
                "friction": _f(item.get("friction"), 0.0),
                "tier": item.get("dunbar_tier") or "",
                "role": item.get("role") or "",
                "last_contact_day": _i(item.get("last_contact_day")),
            }
            if existing is None:
                links[edge] = record
            else:
                # Reciprocal agent ties: keep the stronger reading of each side.
                for field in ("closeness", "trust", "obligation"):
                    existing[field] = max(existing.get(field) or 0.0, record[field] or 0.0)

    ordered_links = sorted(links.values(), key=lambda item: item["closeness"] or 0.0, reverse=True)
    return {
        "available": bool(ordered_links),
        "nodes": list(nodes.values()),
        "links": ordered_links,
        "tier_counts": dict(tier_counts),
        "role_counts": dict(role_counts.most_common(12)),
    }


def behavior(memory_dir: str, names: dict[int, str] | None = None) -> dict[str, Any]:
    """Where agents went, how they travelled, and which habits they formed."""
    places: Counter[str] = Counter()
    modes: Counter[str] = Counter()
    contexts: Counter[str] = Counter()
    # period -> context -> summed habit strength
    heat: dict[str, Counter[str]] = defaultdict(Counter)
    habits: list[dict[str, Any]] = []
    schedule_hours: Counter[int] = Counter()
    per_agent: list[dict[str, Any]] = []

    if not os.path.isdir(memory_dir):
        return {
            "available": False,
            "places": [],
            "modes": [],
            "heatmap": {"periods": [], "contexts": [], "cells": []},
            "habits": [],
            "schedule_hours": [],
            "agents": [],
        }

    for filename in sorted(os.listdir(memory_dir)):
        if not (filename.startswith("agent_") and filename.endswith("_locations.json")):
            continue
        agent_id = _i(filename[len("agent_") : -len("_locations.json")])
        if agent_id is None:
            continue
        payload = _read_json(os.path.join(memory_dir, filename), {}) or {}
        frequent = payload.get("frequent_places")
        if isinstance(frequent, dict):
            for place, count in frequent.items():
                visits = _i(count) or 0
                if visits > 0:
                    places[str(place)] += visits
        preferred = payload.get("preferred_modes")
        if isinstance(preferred, dict):
            for mode, count in preferred.items():
                trips = _i(count) or 0
                if trips > 0:
                    modes[str(mode)] += trips
        per_agent.append(
            {
                "id": agent_id,
                "name": _agent_label(agent_id, names),
                "home": payload.get("home") or "",
                "workplace": payload.get("workplace") or "",
                "current": payload.get("current") or "",
                "transport_mode": payload.get("transport_mode") or "",
                "travel_distance_km": _f(payload.get("travel_distance_km"), 0.0),
                "daily_travel_cost": _f(payload.get("daily_travel_cost"), 0.0),
                "place_count": len(payload.get("frequent_places") or {}),
            }
        )

    for filename in sorted(os.listdir(memory_dir)):
        if filename.startswith("agent_") and filename.endswith("_habits.json"):
            agent_id = _i(filename[len("agent_") : -len("_habits.json")])
            payload = _read_json(os.path.join(memory_dir, filename), {}) or {}
            if not isinstance(payload, dict):
                continue
            for key, item in payload.items():
                if not isinstance(item, dict):
                    continue
                parts = str(key).split("|")
                period = parts[0] if parts else ""
                context = parts[1] if len(parts) > 1 else ""
                activity = parts[2] if len(parts) > 2 else ""
                strength = _f(item.get("strength"), 0.0) or 0.0
                if context:
                    contexts[context] += 1
                if period and context:
                    heat[period][context] += round(strength, 4)
                habits.append(
                    {
                        "agent_id": agent_id,
                        "name": _agent_label(agent_id, names) if agent_id is not None else "",
                        "period": period,
                        "context": context,
                        "activity": activity,
                        "strength": strength,
                        "action": item.get("preferred_action") or "",
                        "last_updated_day": _i(item.get("last_updated_day")),
                    }
                )
        elif filename.startswith("agent_") and filename.endswith("_schedule.json"):
            payload = _read_json(os.path.join(memory_dir, filename), []) or []
            if not isinstance(payload, list):
                continue
            for slot in payload:
                if not isinstance(slot, dict):
                    continue
                hour = _i(str(slot.get("time") or "").split(":")[0])
                if hour is not None and 0 <= hour < 24:
                    schedule_hours[hour] += 1

    periods = [p for p in HABIT_PERIODS if p in heat] + sorted(set(heat) - set(HABIT_PERIODS))
    context_axis = [context for context, _ in contexts.most_common(10)]
    cells = [
        {"period": period, "context": context, "value": round(heat[period].get(context, 0.0), 4)}
        for period in periods
        for context in context_axis
    ]
    habits.sort(key=lambda item: item["strength"], reverse=True)

    return {
        "available": bool(places or habits or modes),
        "places": [{"name": name, "visits": count} for name, count in places.most_common(20)],
        "modes": [{"mode": mode, "trips": count} for mode, count in modes.most_common()],
        "heatmap": {"periods": periods, "contexts": context_axis, "cells": cells},
        "habits": habits[:25],
        "schedule_hours": [{"hour": hour, "count": schedule_hours.get(hour, 0)} for hour in range(24)],
        "agents": per_agent,
    }


def events(visualization_dir: str) -> dict[str, Any]:
    """Environment / policy events per simulated day, from the replay trace."""
    trace = _read_json(os.path.join(visualization_dir, "simulation_trace.json"), {}) or {}
    frames = trace.get("frames") if isinstance(trace, dict) else None
    if not isinstance(frames, list):
        frames = []

    timeline: list[dict[str, Any]] = []
    type_counts: Counter[str] = Counter()
    impact_counts: Counter[str] = Counter()
    seen: set[str] = set()
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        entries = []
        for item in frame.get("env_events") or []:
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("id") or "")
            if event_id and event_id in seen:
                continue
            if event_id:
                seen.add(event_id)
            event_type = str(item.get("type") or "unknown")
            type_counts[event_type] += 1
            for tag in item.get("impact_tags") or []:
                impact_counts[str(tag)] += 1
            entries.append(
                {
                    "type": event_type,
                    "topic": str(item.get("topic") or ""),
                    "name": str(item.get("name") or ""),
                    "description": str(item.get("description") or ""),
                    "severity": _f(item.get("severity"), 0.0),
                    "scope": str(item.get("scope") or ""),
                    "impact_tags": [str(tag) for tag in (item.get("impact_tags") or [])],
                }
            )
        policy = frame.get("policy") if isinstance(frame.get("policy"), dict) else {}
        if not entries and not policy:
            continue
        timeline.append(
            {
                "index": _i(frame.get("index")),
                "day": _i(frame.get("day")),
                "date": str(frame.get("date") or ""),
                "weekday": str(frame.get("weekday") or ""),
                "day_type": str(frame.get("day_type") or ""),
                "events": entries,
                "policy": policy,
            }
        )

    meta = trace.get("meta") if isinstance(trace, dict) else {}
    return {
        "available": bool(timeline),
        "timeline": timeline,
        "type_counts": dict(type_counts),
        "impact_counts": dict(impact_counts.most_common(12)),
        "meta": meta if isinstance(meta, dict) else {},
    }


def overview(
    output_dir: str,
    memory_dir: str,
    visualization_dir: str,
    diary_dir: str,
    names: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Headline numbers for the KPI strip, cheap enough to poll."""
    history = state_history(output_dir, names)
    trace = _read_json(os.path.join(visualization_dir, "simulation_trace.json"), {}) or {}
    meta = trace.get("meta") if isinstance(trace, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    frames = trace.get("frames") if isinstance(trace, dict) else []
    frames = frames if isinstance(frames, list) else []

    days = [_i(frame.get("day")) for frame in frames if isinstance(frame, dict)]
    days = [day for day in days if day is not None]
    event_total = sum(
        len(frame.get("env_events") or []) for frame in frames if isinstance(frame, dict)
    )

    diary_count = 0
    if os.path.isdir(diary_dir):
        for entry in os.listdir(diary_dir):
            agent_dir = os.path.join(diary_dir, entry)
            if os.path.isdir(agent_dir):
                diary_count += len([f for f in os.listdir(agent_dir) if f.endswith(".md")])

    relationship_total = 0
    for _owner, path in _relationship_files(memory_dir):
        payload = _read_json(path, {}) or {}
        if isinstance(payload, dict):
            relationship_total += len(payload)

    # Mean start->end movement per metric, averaged across agents. This is the
    # single number that answers "did the run actually change anything?".
    movement = {}
    for metric, per_agent in history["deltas"].items():
        deltas = [stats["delta"] for stats in per_agent.values() if "delta" in stats]
        if deltas:
            movement[metric] = round(sum(deltas) / len(deltas), 4)
    top_movers = sorted(movement.items(), key=lambda kv: abs(kv[1]), reverse=True)[:6]

    return {
        "agent_count": len(history["agents"]),
        "metric_count": len(history["metrics"]),
        "step_count": history["steps"],
        "frame_count": len(frames),
        "day_span": {"first": min(days), "last": max(days)} if days else None,
        "event_total": event_total,
        "diary_count": diary_count,
        "relationship_total": relationship_total,
        "finished": bool(meta.get("finished")),
        "generated_at": meta.get("generated_at") or "",
        "last_updated": meta.get("last_updated") or "",
        "sim_meta": meta.get("sim_meta") or {},
        "top_movers": [{"metric": metric, "mean_delta": value} for metric, value in top_movers],
    }
