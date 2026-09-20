"""Structured spatial learning from anomalies (P4).

The analysis (``docs/physical_env_perception_analysis.md`` §4.3) noted that
anomaly experiences only influenced future behaviour *indirectly*, via
episode salience. This module adds an explicit, reusable preference: when
an agent repeatedly hits a *local* physical anomaly at a place (a venue
that's shut, a recurring crowd surge), it accumulates an avoidance score
for that place, which later biases location choice away from it.

Scope is deliberately narrow and honest: only **location-bound** anomalies
are learned here (city-wide macro anomalies like a storm are not a
property of any one place and would be mis-attributed). Pure, LLM-free,
and gated by ``CONFIG["spatial_preferences"]["enabled"]`` at call sites.
"""

from __future__ import annotations

import math
from typing import Any

DEFAULT_AVOID_THRESHOLD = 1.5
DEFAULT_HALF_LIFE_DAYS = 7.0


def _store(agent: dict[str, Any]) -> dict[str, Any]:
    prefs = agent.setdefault("env_preferences", {})
    if not isinstance(prefs, dict):
        prefs = {}
        agent["env_preferences"] = prefs
    prefs.setdefault("avoid", {})
    return prefs


def time_bucket(time_str: str) -> str:
    """Coarse part-of-day bucket for a ``HH:MM`` string."""
    try:
        hh = int(str(time_str).split(":")[0])
    except (ValueError, IndexError):
        return ""
    if 5 <= hh < 11:
        return "morning"
    if 11 <= hh < 14:
        return "noon"
    if 14 <= hh < 18:
        return "afternoon"
    if 18 <= hh < 23:
        return "evening"
    return "night"


def record_anomaly_experience(
    agent: dict[str, Any],
    *,
    location: str,
    day: int | None = None,
    weight: float = 1.0,
    reason: str = "",
    time_str: str = "",
) -> dict[str, Any] | None:
    """Accumulate an avoidance score for *location* after an anomaly there."""
    if not location:
        return None
    avoid = _store(agent)["avoid"]
    entry = avoid.setdefault(
        location,
        {"score": 0.0, "count": 0, "reasons": [], "last_day": day, "time_buckets": {}},
    )
    entry["score"] = round(float(entry["score"]) + float(weight), 4)
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["last_day"] = day if day is not None else entry.get("last_day")
    if reason and reason not in entry["reasons"]:
        entry["reasons"] = (entry["reasons"] + [reason])[-5:]
    bucket = time_bucket(time_str)
    if bucket:
        tb = entry["time_buckets"]
        tb[bucket] = round(float(tb.get(bucket, 0.0)) + float(weight), 4)
    return entry


def location_aversion(agent: dict[str, Any], location: str, time_str: str = "") -> float:
    """Current avoidance score for *location* (optionally time-bucket aware)."""
    if not location:
        return 0.0
    avoid = (agent.get("env_preferences") or {}).get("avoid", {}) if isinstance(agent, dict) else {}
    entry = avoid.get(location)
    if not isinstance(entry, dict):
        return 0.0
    score = float(entry.get("score", 0.0))
    bucket = time_bucket(time_str)
    if bucket and entry.get("time_buckets"):
        # Concentrated-in-this-bucket history weighs a little more.
        score += 0.5 * float(entry["time_buckets"].get(bucket, 0.0))
    return round(score, 4)


def decay_preferences(
    agent: dict[str, Any],
    current_day: int,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    prune_below: float = 0.05,
) -> None:
    """Exponentially decay avoidance scores by recency; prune the negligible."""
    avoid = (agent.get("env_preferences") or {}).get("avoid", {}) if isinstance(agent, dict) else {}
    if not avoid:
        return
    hl = max(0.1, float(half_life_days))
    dead: list[str] = []
    for location, entry in avoid.items():
        if not isinstance(entry, dict):
            dead.append(location)
            continue
        last_day = entry.get("last_day")
        if last_day is None:
            continue
        elapsed = max(0, int(current_day) - int(last_day))
        if elapsed <= 0:
            continue
        factor = math.pow(0.5, elapsed / hl)
        entry["score"] = round(float(entry.get("score", 0.0)) * factor, 4)
        if "time_buckets" in entry:
            entry["time_buckets"] = {
                k: round(v * factor, 4) for k, v in entry["time_buckets"].items()
            }
        if entry["score"] < prune_below:
            dead.append(location)
    for location in dead:
        avoid.pop(location, None)


def redirect_for_aversion(
    agent: dict[str, Any],
    city_map: Any,
    primary_location: str,
    time_str: str = "",
    *,
    threshold: float = DEFAULT_AVOID_THRESHOLD,
    top_k: int = 4,
) -> tuple[str, bool]:
    """If *primary_location* is sufficiently aversive, pick a same-category
    alternative the agent dislikes less.

    Returns ``(location, redirected)``. Falls back to the primary location
    whenever no better same-category alternative exists, so it is always
    safe to use the result directly.
    """
    if not primary_location or not city_map:
        return primary_location, False
    if location_aversion(agent, primary_location, time_str) < threshold:
        return primary_location, False

    # Local import to avoid a heavy module-load dependency cycle.
    from gaworld.world.city_map import infer_category, nearest_by_category, node_by_name

    # Prefer the node's stored category; fall back to name inference.
    node = node_by_name(city_map, primary_location)
    category = (node or {}).get("category") or infer_category(primary_location)
    try:
        candidates = nearest_by_category(city_map, primary_location, category, top_k=top_k)
    except Exception:
        return primary_location, False

    best = primary_location
    best_av = location_aversion(agent, primary_location, time_str)
    for nid, _dist in candidates or []:
        if nid == primary_location:
            continue
        av = location_aversion(agent, nid, time_str)
        if av < best_av:
            best, best_av = nid, av
    return (best, best != primary_location)


__all__ = [
    "DEFAULT_AVOID_THRESHOLD",
    "DEFAULT_HALF_LIFE_DAYS",
    "decay_preferences",
    "location_aversion",
    "record_anomaly_experience",
    "redirect_for_aversion",
    "time_bucket",
]
