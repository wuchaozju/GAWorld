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
from datetime import UTC, datetime
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
        "agents": [{"id": agent_id, "name": _agent_label(agent_id, names)} for agent_id in sorted(agent_ids)],
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
    event_total = sum(len(frame.get("env_events") or []) for frame in frames if isinstance(frame, dict))

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


# ---------------------------------------------------------------------------
# Cross-world system summary
# ---------------------------------------------------------------------------


def _safe_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _dir_file_count(path: str) -> int:
    if not os.path.isdir(path):
        return 0
    try:
        return sum(1 for _ in os.listdir(path))
    except OSError:
        return 0


def _count_files(root: str, prefix: str = "") -> int:
    """Recursive file count under ``root`` whose basename starts with ``prefix``.

    ``prefix=""`` counts every file. ``os.scandir`` keeps it cheap on big trees.
    """
    if not os.path.isdir(root):
        return 0
    total = 0
    try:
        with os.scandir(root) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    if not prefix or entry.name.startswith(prefix):
                        total += 1
                elif entry.is_dir(follow_symlinks=False):
                    total += _count_files(entry.path, prefix)
    except OSError:
        return total
    return total


def _city_metrics(city_dir: str) -> dict[str, Any]:
    """Per-city artifact summary used by the cross-world panel.

    The dashboard never relies on a single sentinel file; every count reads its
    own artifact so a half-finished city (an aborted migration, a quarantined
    bundle) still appears in the panel instead of vanishing as "missing".
    """
    slug = os.path.basename(city_dir.rstrip("/"))
    state_csv = os.path.join(city_dir, "state", "agent_state_history.csv")
    agents: set[int] = set()
    for row in _read_csv(state_csv):
        aid = _i(row.get("agent_id"))
        if aid is not None:
            agents.add(aid)

    diary_dir = os.path.join(city_dir, "diaries")
    diary_count = 0
    if os.path.isdir(diary_dir):
        for entry in os.listdir(diary_dir):
            sub = os.path.join(diary_dir, entry)
            if os.path.isdir(sub):
                diary_count += sum(1 for f in os.listdir(sub) if f.endswith(".md"))

    life_events_path = os.path.join(city_dir, "life_events", "events.json")
    life_payload = _read_json(life_events_path, {}) or {}
    life_count = len(life_payload.get("events") or []) if isinstance(life_payload, dict) else 0

    intervention_rows = len(_read_csv(os.path.join(city_dir, "intervention", "intervention_metrics.csv")))

    manifest_dir = os.path.join(city_dir, "run_manifests")
    last_manifest = None
    if os.path.isdir(manifest_dir):
        manifests = sorted(
            (os.path.join(manifest_dir, n) for n in os.listdir(manifest_dir) if n.endswith(".json")),
            key=_safe_mtime,
            reverse=True,
        )
        if manifests:
            payload = _read_json(manifests[0], {}) or {}
            if isinstance(payload, dict):
                llm = payload.get("llm") or {}
                if not isinstance(llm, dict):
                    llm = {}
                git = payload.get("git") or {}
                if not isinstance(git, dict):
                    git = {}
                last_manifest = {
                    "filename": os.path.basename(manifests[0]),
                    "started_at": payload.get("started_at") or "",
                    "finished_at": payload.get("finished_at") or "",
                    "duration_s": _f(payload.get("duration_s"), 0.0),
                    "outcome": payload.get("outcome") or "",
                    "comparability_epoch": _i(payload.get("comparability_epoch")),
                    "llm_call_count": _i(llm.get("call_count")),
                    "llm_failure_count": _i(llm.get("failure_count")),
                    "llm_avg_latency_ms": _f(llm.get("avg_latency_ms"), 0.0),
                    "git_commit": git.get("commit") or "",
                    "git_dirty": bool(git.get("dirty")),
                }

    return {
        "slug": slug,
        "path": os.path.relpath(city_dir, os.path.dirname(city_dir) or "."),
        "agent_count": len(agents),
        "memory_exists": os.path.isdir(os.path.join(city_dir, "memory"))
        and any(name.startswith("agent_") for name in os.listdir(os.path.join(city_dir, "memory")) or []),
        "diary_count": diary_count,
        "life_events_count": life_count,
        "intervention_rows": intervention_rows,
        "last_run_manifest": last_manifest,
        "last_updated": _safe_mtime(city_dir),
    }


def _parallel_world_summary(study_dir: str) -> dict[str, Any]:
    """One ``parallel_worlds/study_*`` entry — worlds + causal verdict counts."""
    exp_payload = _read_json(os.path.join(study_dir, "experiment.json"), {}) or {}
    rep_payload = _read_json(os.path.join(study_dir, "report.json"), {}) or {}
    worlds_meta = []
    rep_worlds = (rep_payload.get("worlds") or []) if isinstance(rep_payload, dict) else []
    if isinstance(rep_worlds, list):
        for world in rep_worlds:
            if not isinstance(world, dict):
                continue
            worlds_meta.append(
                {
                    "id": world.get("id") or "",
                    "label": world.get("label") or "",
                    "role": world.get("role") or "",
                    "is_baseline": bool(world.get("is_baseline")),
                    "has_data": bool(world.get("has_data")),
                    "steps": _i(world.get("steps")) or 0,
                    "agents": _i(world.get("agents")) or 0,
                    "divergence_final": _f(world.get("divergence_final"), 0.0),
                    "divergence_peak": _f(world.get("divergence_peak"), 0.0),
                    "top_metric": world.get("top_metric") or "",
                    "top_delta": _f(world.get("top_delta"), 0.0),
                    "status": world.get("status") or "",
                    "error": world.get("error") or "",
                }
            )
    if not worlds_meta and isinstance(exp_payload, dict):
        for world in exp_payload.get("worlds") or []:
            if not isinstance(world, dict):
                continue
            worlds_meta.append(
                {
                    "id": world.get("id") or "",
                    "label": world.get("label") or "",
                    "role": world.get("role") or "",
                    "is_baseline": False,
                    "has_data": False,
                    "steps": 0,
                    "agents": 0,
                    "divergence_final": 0.0,
                    "divergence_peak": 0.0,
                    "top_metric": "",
                    "top_delta": 0.0,
                    "status": "",
                    "error": "",
                }
            )

    causal_summary = {}
    if isinstance(rep_payload, dict):
        causal = rep_payload.get("causal") or {}
        if isinstance(causal, dict):
            summary = causal.get("summary") or {}
            if isinstance(summary, dict):
                for key in ("robust", "below_noise", "unbalanced", "suggestive", "null", "insufficient"):
                    causal_summary[key] = _i(summary.get(key)) or 0

    causal_rows = 0
    try:
        with open(os.path.join(study_dir, "causal_effects.csv"), encoding="utf-8") as f:
            causal_rows = max(0, sum(1 for _ in f) - 1)
    except OSError:
        causal_rows = 0

    return {
        "study_id": os.path.basename(study_dir),
        "path": os.path.relpath(study_dir, os.path.dirname(study_dir) or "."),
        "name": (exp_payload.get("spec") or {}).get("name") or "" if isinstance(exp_payload, dict) else "",
        "seed": _i((exp_payload.get("spec") or {}).get("seed")) if isinstance(exp_payload, dict) else None,
        "created_at": (exp_payload.get("created_at") or "") if isinstance(exp_payload, dict) else "",
        "worlds": worlds_meta,
        "causal_summary": causal_summary,
        "comparability_epoch": _i(rep_payload.get("comparability_epoch"))
        if isinstance(rep_payload, dict)
        else None,
        "causal_effects_rows": causal_rows,
        "last_updated": _safe_mtime(study_dir),
    }


def _interview_summary(sess_dir: str) -> dict[str, Any]:
    session = _read_json(os.path.join(sess_dir, "session.json"), {}) or {}
    cities: set[str] = set()
    rounds: set[int] = set()
    questions_count = 0
    respondent_total = 0
    respondent_by_city: dict[str, int] = {}
    report_exists = os.path.exists(os.path.join(sess_dir, "report.md"))
    created_at = ""

    if isinstance(session, dict):
        created_at = session.get("created_at") or ""
        questions = session.get("questions") or []
        if isinstance(questions, list):
            questions_count = len(questions)
        for entry in (session.get("transcripts") or {}).values():
            if not isinstance(entry, dict):
                continue
            resp = entry.get("respondent") or {}
            if not isinstance(resp, dict):
                continue
            city = (resp.get("city") or resp.get("kind") or "").strip()
            if city:
                cities.add(city)
                respondent_by_city[city] = respondent_by_city.get(city, 0) + 1
            respondent_total += 1

    for entry in os.listdir(sess_dir) if os.path.isdir(sess_dir) else []:
        if entry.startswith("round-") and "-" in entry:
            head = entry[len("round-") :].split("-", 1)[0]
            num = _i(head)
            if num is not None:
                rounds.add(num)

    return {
        "id": os.path.basename(sess_dir),
        "title": (session.get("title") or "") if isinstance(session, dict) else "",
        "cities": sorted(cities),
        "rounds": sorted(rounds),
        "respondent_count": respondent_total,
        "respondent_by_city": respondent_by_city,
        "questions_count": questions_count,
        "report_exists": report_exists,
        "created_at": created_at,
        "last_updated": _safe_mtime(sess_dir),
    }


def _research_plan_summary(plan_path: str) -> dict[str, Any]:
    payload = _read_json(plan_path, {}) or {}
    feasibility = payload.get("feasibility") or {}
    return {
        "id": os.path.basename(plan_path).rsplit(".", 1)[0],
        "title": payload.get("title") or "",
        "kind": payload.get("kind") or "",
        "language": payload.get("language") or "",
        "feasibility_score": _i((feasibility.get("score")) if isinstance(feasibility, dict) else None),
        "feasibility_verdict": (feasibility.get("verdict") or "") if isinstance(feasibility, dict) else "",
        "research_questions_count": len(payload.get("research_questions") or []),
        "hypotheses_count": len(payload.get("hypotheses") or []),
        "capability_map_count": len(payload.get("capability_map") or []),
        "created_at": payload.get("created_at") or "",
        "last_updated": _safe_mtime(plan_path),
    }


def _research_study_summary(study_dir: str) -> dict[str, Any]:
    study = _read_json(os.path.join(study_dir, "study.json"), {}) or {}
    protocol = study.get("protocol") or {}
    if not isinstance(protocol, dict):
        protocol = {}
    validity = protocol.get("validity") if isinstance(protocol.get("validity"), dict) else {}
    seeds: list[int] = []
    raw_seeds = validity.get("seeds") if isinstance(validity, dict) else None
    if isinstance(raw_seeds, list):
        for item in raw_seeds:
            num = _i(item)
            if num is not None:
                seeds.append(num)
    return {
        "id": study.get("id") or os.path.basename(study_dir),
        "title": study.get("title") or "",
        "stage": study.get("stage") or "",
        "attempt": _i(study.get("attempt")) or 0,
        "sim_days": _i(protocol.get("sim_days")) or 0,
        "conditions_count": len(protocol.get("conditions") or []),
        "worlds_count": len(protocol.get("conditions") or []),
        "seeds": seeds,
        "placebo": bool(validity.get("placebo")) if isinstance(validity, dict) else False,
        "hypotheses_count": len(protocol.get("hypotheses") or []),
        "measures_count": len(protocol.get("measures") or []),
        "updated_at": study.get("updated_at") or "",
        "error": study.get("error") or "",
        "last_updated": _safe_mtime(study_dir),
    }


def _serious_game_summary(path: str) -> dict[str, Any]:
    payload = _read_json(path, {}) or {}
    spec = payload.get("spec") or {}
    if not isinstance(spec, dict):
        spec = {}
    return {
        "id": payload.get("id") or os.path.basename(path).rsplit(".", 1)[0],
        "description": payload.get("description") or "",
        "roles_count": len(spec.get("roles") or []),
        "indicators_count": len(spec.get("indicators") or []),
        "created_at": payload.get("created_at") or "",
        "last_updated": _safe_mtime(path),
    }


def _replication_summary(path: str) -> dict[str, Any]:
    payload = _read_json(path, {}) or {}
    spec = payload.get("spec") or {}
    if not isinstance(spec, dict):
        spec = {}
    return {
        "id": payload.get("id") or os.path.basename(path).rsplit(".", 1)[0],
        "title": payload.get("title") or "",
        "design": payload.get("design") or "",
        "city": payload.get("city") or "",
        "seed": _i(payload.get("seed")),
        "requested_sample": _i(payload.get("requested_sample")),
        "eligible": _i(payload.get("eligible")),
        "human_n": _i(spec.get("human_n")),
        "spec_kind": spec.get("kind") or "",
        "conditions_count": len(spec.get("conditions") or []),
        "items_count": len(spec.get("items") or []),
        "residents_count": len(payload.get("residents") or []),
        "last_updated": _safe_mtime(path),
    }


def _persona_summary(slug_dir: str) -> dict[str, Any]:
    payload = _read_json(os.path.join(slug_dir, "persona.json"), {}) or {}
    state = payload.get("state") or {}
    big5 = payload.get("big5") or {}
    return {
        "slug": os.path.basename(slug_dir),
        "subject": payload.get("subject") or "",
        "mode": payload.get("mode") or "",
        "confidence": payload.get("confidence") or "",
        "evidence_pages": _i(payload.get("evidence_pages")) or 0,
        "evidence_items": _i(payload.get("evidence_items")) or 0,
        "framework_error": payload.get("framework_error") or "",
        "state_keys_count": len(state) if isinstance(state, dict) else 0,
        "big5_filled": bool(big5) if isinstance(big5, dict) else False,
        "built_at": payload.get("built_at") or "",
        "last_updated": _safe_mtime(slug_dir),
    }


def _experiment_summary(exp_dir: str) -> dict[str, Any]:
    name = os.path.basename(exp_dir)
    spec = _read_json(os.path.join(exp_dir, "spec.json"), {}) or {}
    summary = _read_json(os.path.join(exp_dir, "summary.json"), {}) or {}
    return {
        "name": name,
        "arms": list(spec.get("arms") or []),
        "questions": list(spec.get("questions") or []),
        "total_cells": _i(spec.get("total_cells")) or 0,
        "n_rows": _i(summary.get("n_rows")) or 0,
        "provider": spec.get("provider") or "",
        "seed": _i(spec.get("seed")),
        "summary_arms": summary.get("arms") or {},
        "has_report": os.path.exists(os.path.join(exp_dir, "report.md")),
        "started_at": spec.get("started_at") or "",
        "last_updated": _safe_mtime(exp_dir),
    }


def _legco_summary(legco_dir: str) -> dict[str, Any]:
    members: list[dict[str, Any]] = []
    by_party: Counter[str] = Counter()
    by_constituency: Counter[str] = Counter()
    for entry in sorted(os.listdir(legco_dir)) if os.path.isdir(legco_dir) else []:
        if not entry.startswith("member-") or not entry.endswith(".json"):
            continue
        payload = _read_json(os.path.join(legco_dir, entry), {}) or {}
        if not isinstance(payload, dict):
            continue
        party = payload.get("party") or []
        party_label = ", ".join(party) if isinstance(party, list) and party else "—"
        constituency_type = (payload.get("constituency_type") or "—").strip() or "—"
        by_party[party_label] += 1
        by_constituency[constituency_type] += 1
        members.append(
            {
                "member_id": _i(payload.get("member_id")) or 0,
                "name": payload.get("name") or "",
                "constituency_type": constituency_type,
                "constituency": payload.get("constituency") or "",
                "title": payload.get("title") or "",
                "honour": payload.get("honour") or "",
                "qualification_count": len(payload.get("qualification") or []),
                "occupation": payload.get("occupation") or [],
                "party": party,
            }
        )
    members.sort(key=lambda m: m["member_id"])
    return {
        "members_count": len(members),
        "by_party": dict(by_party.most_common()),
        "by_constituency_type": dict(by_constituency.most_common()),
        "sample": members[:12],
        "last_updated": _safe_mtime(legco_dir),
    }


def _population_summary(pop_dir: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not os.path.isdir(pop_dir):
        return results
    for entry in sorted(os.listdir(pop_dir)):
        if not entry.endswith("_manifest.json"):
            continue
        path = os.path.join(pop_dir, entry)
        payload = _read_json(path, {}) or {}
        spec = payload.get("spec") or {}
        if not isinstance(spec, dict):
            spec = {}
        demography = spec.get("demography") or {}
        household = spec.get("household") or {}
        edu = spec.get("education_work") or {}
        if not isinstance(demography, dict):
            demography = {}
        if not isinstance(household, dict):
            household = {}
        if not isinstance(edu, dict):
            edu = {}
        name = entry[: -len("_manifest.json")]
        results.append(
            {
                "name": name,
                "size": _i(spec.get("size")) or 0,
                "seed": _i(spec.get("seed")),
                "preset": spec.get("preset") or "",
                "median_age": _f(demography.get("median_age"), 0.0),
                "share_under_18": _f(demography.get("share_under_18"), 0.0),
                "share_over_65": _f(demography.get("share_over_65"), 0.0),
                "sex_ratio_m_per_100f": _f(demography.get("sex_ratio_m_per_100f"), 0.0),
                "migrant_share": _f(demography.get("migrant_share"), 0.0),
                "household_mean_size": _f(household.get("mean_size"), 0.0),
                "tertiary_rate": _f(edu.get("tertiary_rate"), 0.0),
                "employment_rate": _f(edu.get("employment_rate"), 0.0),
                "spec_path": os.path.relpath(path, os.path.dirname(path) or "."),
                "last_updated": _safe_mtime(path),
            }
        )
    return results


def _info_source_summary(feed_path: str) -> dict[str, Any]:
    payload = _read_json(feed_path, {}) or {}
    last_fetch = payload.get("last_fetch") or {}
    if not isinstance(last_fetch, dict):
        last_fetch = {}
    sources = list(last_fetch.keys())
    latest = ""
    for value in last_fetch.values():
        text = str(value or "")
        if text > latest:
            latest = text
    return {"total_sources": len(sources), "sources": sources, "latest_fetch": latest}


def _quarantine_summary(q_root: str) -> list[dict[str, Any]]:
    """``output/_quarantine/<ts>/`` snapshots kept for forensic recovery.

    The dashboard treats these as forensic, not analytic, data. They are
    surfaced only so the operator notices if a spike of quarantined records
    means a recent run is unrecoverable.
    """
    out: list[dict[str, Any]] = []
    if not os.path.isdir(q_root):
        return out
    for entry in sorted(os.listdir(q_root)):
        snap_dir = os.path.join(q_root, entry)
        if not os.path.isdir(snap_dir):
            continue
        before = os.path.join(snap_dir, "records_before")
        fixture = os.path.join(snap_dir, "fixture_records")
        out.append(
            {
                "ts": entry,
                "path": os.path.relpath(snap_dir, os.path.dirname(snap_dir) or "."),
                "records_before_files": _count_files(before),
                "fixture_records_files": _count_files(fixture),
                "last_updated": _safe_mtime(snap_dir),
            }
        )
    return out


def _trackb_summary(output_root: str) -> list[dict[str, Any]]:
    """``output/trackb*`` debug trees the operator can purge when they grow.

    Excluded from KPI counts; only listed so the cleanup dialog can find them.
    """
    out: list[dict[str, Any]] = []
    if not os.path.isdir(output_root):
        return out
    for entry in sorted(os.listdir(output_root)):
        if not entry.startswith("trackb"):
            continue
        sub = os.path.join(output_root, entry)
        if not os.path.isdir(sub):
            continue
        out.append({"path": os.path.join(os.path.basename(output_root), entry), "files": _count_files(sub)})
    return out


def _kpis_from_payloads(
    cities: list[dict[str, Any]],
    parallel_worlds: list[dict[str, Any]],
    personas: list[dict[str, Any]],
    experiments: list[dict[str, Any]],
    interviews: list[dict[str, Any]],
    plans: list[dict[str, Any]],
    studies: list[dict[str, Any]],
    serious_games: list[dict[str, Any]],
    replications: list[dict[str, Any]],
    legco: dict[str, Any],
    population: list[dict[str, Any]],
    quarantine: list[dict[str, Any]],
    info_source: dict[str, Any],
    run_manifests: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "cities_count": len(cities),
        "cities_total_agents": sum(c["agent_count"] for c in cities),
        "cities_total_diaries": sum(c["diary_count"] for c in cities),
        "cities_total_life_events": sum(c["life_events_count"] for c in cities),
        "parallel_worlds_studies": len(parallel_worlds),
        "parallel_worlds_total_worlds": sum(len(p["worlds"]) for p in parallel_worlds),
        "parallel_worlds_causal_robust": sum(p["causal_summary"].get("robust", 0) for p in parallel_worlds),
        "personas_count": len(personas),
        "experiments_count": len(experiments),
        "experiments_total_cells": sum(e["total_cells"] for e in experiments),
        "experiments_total_rows": sum(e["n_rows"] for e in experiments),
        "interview_sessions": len(interviews),
        "interview_total_respondents": sum(i["respondent_count"] for i in interviews),
        "research_plans": len(plans),
        "research_studies": len(studies),
        "serious_games_count": len(serious_games),
        "replication_studies": len(replications),
        "legco_members": legco.get("members_count", 0),
        "quarantine_snapshots": len(quarantine),
        "population_towns": len(population),
        "run_manifests_total": len(run_manifests),
        "info_feed_sources": info_source.get("total_sources", 0),
        "info_feed_latest": info_source.get("latest_fetch", ""),
    }


def _build_health(
    *,
    current_world: dict[str, Any] | None,
    overview: dict[str, Any],
    cities: list[dict[str, Any]],
    parallel_worlds: list[dict[str, Any]],
    personas: list[dict[str, Any]],
    output_root: str,
) -> dict[str, Any]:
    """Cross-section sanity flags the operator can act on at a glance."""
    warnings: list[str] = []
    has_state = bool(overview.get("agent_count"))
    has_economy = bool(overview.get("agent_count"))
    has_trace = bool(overview.get("frame_count"))
    if not has_state:
        warnings.append("当前运行没有智能体状态历史 — 是不是刚刚 reset？")
    if not has_trace:
        warnings.append("当前运行没有可视化轨迹 — 仪表盘可能空")
    for city in cities:
        if not city["last_run_manifest"]:
            warnings.append(f"城市 {city['slug']} 没有 run_manifests/")
        elif city["last_run_manifest"].get("outcome") == "error":
            warnings.append(f"城市 {city['slug']} 最近一次运行失败")
    low_conf = [p["slug"] for p in personas if p["confidence"] not in ("high", "medium") and p["confidence"]]
    if low_conf:
        warnings.append(f"{len(low_conf)} 个人物画像置信度偏低（{', '.join(low_conf[:5])}…）")
    err_worlds = sum(
        1
        for study in parallel_worlds
        for world in study["worlds"]
        if world.get("status") == "error" or world.get("error")
    )
    if err_worlds:
        warnings.append(f"{err_worlds} 个平行世界以 error 状态完成")
    trackb_dirs = [
        name
        for name in (os.listdir(output_root) if os.path.isdir(output_root) else [])
        if name.startswith("trackb")
    ]
    if trackb_dirs:
        warnings.append(f"调试残留目录 {len(trackb_dirs)} 个（{', '.join(trackb_dirs[:5])}），可清理")
    return {
        "current_run_has_state": has_state,
        "current_run_has_economy": has_economy,
        "current_run_has_trace": has_trace,
        "warnings": warnings,
    }


def system_panel(
    *,
    output_root: str,
    current_world: dict[str, Any] | None,
    overview: dict[str, Any],
    agent_names: dict[int, str] | None = None,
) -> dict[str, Any]:
    """A whole-system snapshot: current world + every cross-world artifact tree.

    The dashboard reads this once and renders the top-of-page 综合面板 above the
    per-run sections. Each subsection degrades independently — a missing
    ``parallel_worlds/`` shows zero studies instead of failing the page.

    *output_root* is the resolved ``output/`` path (city-aware: ``output/cities/<slug>/``
    for the active city). ``current_world`` and ``overview`` are reused from
    the existing analytics reads so the panel never re-walks the active city.
    """
    cities_dir = os.path.join(output_root, "cities")
    cities: list[dict[str, Any]] = []
    if os.path.isdir(cities_dir):
        for entry in sorted(os.listdir(cities_dir)):
            sub = os.path.join(cities_dir, entry)
            if os.path.isdir(sub):
                cities.append(_city_metrics(sub))

    pw_root = os.path.join(output_root, "parallel_worlds")
    parallel_worlds: list[dict[str, Any]] = []
    if os.path.isdir(pw_root):
        for entry in sorted(os.listdir(pw_root)):
            sub = os.path.join(pw_root, entry)
            if os.path.isdir(sub):
                parallel_worlds.append(_parallel_world_summary(sub))

    interviews_dir = os.path.join(output_root, "interviews")
    interviews: list[dict[str, Any]] = []
    if os.path.isdir(interviews_dir):
        for entry in sorted(os.listdir(interviews_dir)):
            sub = os.path.join(interviews_dir, entry)
            if os.path.isdir(sub):
                interviews.append(_interview_summary(sub))

    research_root = os.path.join(output_root, "research")
    plans: list[dict[str, Any]] = []
    studies: list[dict[str, Any]] = []
    serious_games: list[dict[str, Any]] = []
    replications: list[dict[str, Any]] = []
    if os.path.isdir(research_root):
        for entry in sorted(os.listdir(research_root)):
            sub = os.path.join(research_root, entry)
            if os.path.isfile(sub) and entry.endswith(".json"):
                plans.append(_research_plan_summary(sub))
            elif os.path.isdir(sub) and entry == "studies":
                for study in sorted(os.listdir(sub)):
                    study_dir = os.path.join(sub, study)
                    if os.path.isdir(study_dir):
                        studies.append(_research_study_summary(study_dir))
            elif os.path.isdir(sub) and entry == "serious_games":
                for game in sorted(os.listdir(sub)):
                    if game.endswith(".json"):
                        serious_games.append(_serious_game_summary(os.path.join(sub, game)))
            elif os.path.isdir(sub) and entry == "replication":
                for rep in sorted(os.listdir(sub)):
                    if rep.endswith(".json"):
                        replications.append(_replication_summary(os.path.join(sub, rep)))

    personas_dir = os.path.join(output_root, "personas")
    personas: list[dict[str, Any]] = []
    if os.path.isdir(personas_dir):
        for entry in sorted(os.listdir(personas_dir)):
            sub = os.path.join(personas_dir, entry)
            if os.path.isdir(sub):
                personas.append(_persona_summary(sub))
    personas.sort(key=lambda p: p["last_updated"], reverse=True)

    experiments_dir = os.path.join(output_root, "experiments")
    experiments: list[dict[str, Any]] = []
    if os.path.isdir(experiments_dir):
        for entry in sorted(os.listdir(experiments_dir)):
            sub = os.path.join(experiments_dir, entry)
            if os.path.isdir(sub):
                experiments.append(_experiment_summary(sub))

    legco_dir = os.path.join(output_root, "legco")
    legco = (
        _legco_summary(legco_dir)
        if os.path.isdir(legco_dir)
        else {
            "members_count": 0,
            "by_party": {},
            "by_constituency_type": {},
            "sample": [],
            "last_updated": 0.0,
        }
    )

    population = _population_summary(os.path.join(output_root, "population"))

    info_source = _info_source_summary(os.path.join(output_root, "infosources", "feed.json"))

    quarantine = _quarantine_summary(os.path.join(output_root, "_quarantine"))
    trackb = _trackb_summary(output_root)

    run_manifests_dir = os.path.join(output_root, "run_manifests")
    run_manifests: list[dict[str, Any]] = []
    if os.path.isdir(run_manifests_dir):
        for entry in sorted(os.listdir(run_manifests_dir)):
            if not entry.endswith(".json"):
                continue
            run_manifests.append(
                {"filename": entry, "mtime": _safe_mtime(os.path.join(run_manifests_dir, entry))}
            )

    plans.sort(key=lambda p: p["last_updated"], reverse=True)
    studies.sort(key=lambda p: p["last_updated"], reverse=True)
    serious_games.sort(key=lambda p: p["last_updated"], reverse=True)
    replications.sort(key=lambda p: p["last_updated"], reverse=True)
    interviews.sort(key=lambda p: p["last_updated"], reverse=True)
    parallel_worlds.sort(key=lambda p: p["last_updated"], reverse=True)
    cities.sort(key=lambda p: p["last_updated"], reverse=True)
    experiments.sort(key=lambda p: p["last_updated"], reverse=True)

    kpis = _kpis_from_payloads(
        cities,
        parallel_worlds,
        personas,
        experiments,
        interviews,
        plans,
        studies,
        serious_games,
        replications,
        legco,
        population,
        quarantine,
        info_source,
        run_manifests,
    )

    health = _build_health(
        current_world=current_world,
        overview=overview,
        cities=cities,
        parallel_worlds=parallel_worlds,
        personas=personas,
        output_root=output_root,
    )

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "output_root": os.path.relpath(output_root, os.path.dirname(output_root) or ".") or ".",
        "current_world": current_world,
        "overview": overview,
        "kpis": kpis,
        "cities": cities,
        "parallel_worlds": parallel_worlds,
        "interviews": interviews,
        "research": {
            "plans": plans,
            "studies": studies,
            "serious_games": serious_games,
            "replications": replications,
        },
        "personas": personas[:50],
        "experiments": experiments,
        "legco": legco,
        "population": population,
        "info_sources": info_source,
        "quarantine": quarantine,
        "stale_debug_runs": trackb,
        "health": health,
    }
