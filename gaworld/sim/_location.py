"""Agent location & movement helpers extracted from ``generative_city_sim.py``.

Scope of this module — the agent-dict-mutating subset of the legacy
``# Map & Location`` banner:

* Workplace / home inference via category-based spatial matching
* Initial location assignment (in-memory; persistence stays in legacy file)
* Commute memory bookkeeping
* Transit progress tracking
* The main ``move_agent`` dispatcher

Intentionally out of scope:

* ``init_agent_locations`` / ``persist_agent_locations_if_changed`` — they
  depend on ``STATEFUL`` and ``memory_store`` persistence and will move
  when the memory layer migrates.
* ``resolve_location`` — 180+ line dispatcher with many module-level
  config constants; needs its own dedicated extraction phase.
* ``_timeline_step_minutes`` — reads the module-level ``TIME_STEP_MINUTES``
  fallback; will move when the runtime context object is introduced.
"""

from __future__ import annotations

import random
from typing import Any

from gaworld.world.city_map import (
    all_locations as city_all_locations,
    job_to_workplace_categories,
    map_center_name,
    node_by_name,
    resolve_best_location,
    travel_plan as build_travel_plan,
)

from gaworld.settings import CONFIG
from gaworld.sim._utils import _minutes_to_time_str, _time_str_to_minutes

# Home / workplace assignment. "nearest" is the original behaviour, kept so a
# run can be compared against one made before this existed.
# 0 = no cap: consider every node of the right category inside the search
# radius. A fixed top-k cuts the pool at whatever distance the k-th nearest
# node happens to sit — measured on the default map, 8 of 20 residential
# blocks were never candidates because the cut landed at 3.06 km on a map
# 19 km across. The radius and the gravity weight are the real limits.
_NO_CAP = 10 ** 6
_DEFAULT_LOCATION_ASSIGNMENT = {
    "mode": "gravity",
    "workplace_candidates": 0,
    "home_candidates": 0,
    # Workplaces decay with distance *from home* — that is the real force
    # shortening commutes. Homes decay with distance from the city centre,
    # which is a much weaker preference and is not the same statement, so it
    # gets its own, gentler exponent. Sharing one value made two of twenty-one
    # residential blocks house 44% of the town purely because they sit 250m
    # from the centre.
    "distance_decay": 1.5,
    "home_distance_decay": 0.5,
}


def _candidate_cap(value: Any) -> int:
    try:
        cap = int(value)
    except (TypeError, ValueError):
        return _NO_CAP
    return cap if cap > 0 else _NO_CAP


def _assignment_cfg() -> dict[str, Any]:
    cfg = CONFIG.get("location_assignment", {})
    merged = dict(_DEFAULT_LOCATION_ASSIGNMENT)
    if isinstance(cfg, dict):
        merged.update({k: v for k, v in cfg.items() if k in merged})
    return merged


def _gravity_pick(city_map: Any, candidates: list, decay: float, rng=None) -> str:
    """Pick one candidate with probability proportional to size / distance^decay.

    Taking the *nearest* match instead sends everyone whose job maps to the
    same category into the same building. On the default map that put 56% of
    commuters at one node and left 89% of the road network carrying no
    traffic at all, which makes any spatial quantity measured on it
    meaningless. Weighting by a node's capacity is the standard gravity form:
    large employers draw more people, distant ones draw fewer.
    """
    weights = []
    for node_id, distance in candidates:
        node = node_by_name(city_map, node_id)
        size = float(node.get("capacity", 1) or 1) if node else 1.0
        span = (1.0 + max(0.0, float(distance))) ** max(0.0, float(decay))
        weights.append(max(1e-6, size / span))
    picker = rng or random
    threshold = picker.random() * sum(weights)
    cumulative = 0.0
    for (node_id, _distance), weight in zip(candidates, weights):
        cumulative += weight
        if cumulative >= threshold:
            return node_id
    return candidates[-1][0]

# ---------------------------------------------------------------------------
# Location lookup primitives.
# ---------------------------------------------------------------------------

def _pick_first_available(candidates: list[str], location_set: set[str]) -> str | None:
    for c in candidates:
        if c in location_set:
            return c
    return None


def _central_origin(city_map: Any, preferred: str = "Central Block") -> str:
    """A valid central origin node for spatial inference.

    Prefers the virtual map's ``Central Block``; on a real map (where that name
    is absent) falls back to the node nearest the geometric centre so home/work
    inference stays anchored instead of degenerating to a random node."""
    if node_by_name(city_map, preferred) is not None:
        return preferred
    return map_center_name(city_map) or preferred


def _infer_workplace(
    agent: dict[str, Any], city_map: Any, home_node: str | None = None
) -> str:
    """Infer the agent's workplace using category-based spatial matching.

    Uses the agent's job profile to determine workplace categories, then
    finds the nearest matching node from the city map.  Falls back to the
    legacy hardcoded lookup when the map-based search yields nothing.
    """
    location_set = set(city_all_locations(city_map))
    job_str = agent.get("job", "")
    categories = job_to_workplace_categories(job_str)

    # Also check profile blob for Chinese keywords → categories
    profile_blob = " ".join([
        job_str,
        agent.get("personality", ""),
        agent.get("daily_life", ""),
        agent.get("values", ""),
    ])
    if any(k in profile_blob for k in ["学生", "硕士", "博士", "学校", "上课", "老师", "教师", "教育"]):
        categories = list(dict.fromkeys(["education"] + categories))
    if any(k in profile_blob for k in ["医院", "医生", "护士", "医疗", "诊所"]):
        categories = list(dict.fromkeys(["medical"] + categories))
    if any(k in profile_blob for k in ["警察", "公安", "消防"]):
        categories = list(dict.fromkeys(["government"] + categories))

    if not categories:
        categories = ["commerce", "industry"]

    # Search from home or a central location
    origin = home_node or _central_origin(city_map)
    cfg = _assignment_cfg()
    candidates = resolve_best_location(
        city_map, origin, categories,
        top_k=_candidate_cap(cfg["workplace_candidates"]), max_radius_km=20.0,
    )
    if candidates:
        # Prefer candidates that really exist in the location set, but a slug
        # mismatch must not empty the pool.
        known = [pair for pair in candidates if pair[0] in location_set]
        pool = known or candidates
        if str(cfg["mode"]) == "gravity":
            return _gravity_pick(city_map, pool, cfg["distance_decay"])
        return pool[0][0]

    # Fallback: legacy hardcoded names
    return _pick_first_available(
        ["C-01 (Village Center)", "Riverside Night Market", "Market St"],
        location_set,
    )


def _infer_home(agent: dict[str, Any], city_map: Any) -> str:
    """Infer the agent's home using category-based spatial matching.

    Picks a residential node, preferring those near the city centre.
    Falls back to legacy hardcoded names then random selection.
    """
    location_set = set(city_all_locations(city_map))
    cfg = _assignment_cfg()
    residential = resolve_best_location(
        city_map, _central_origin(city_map), ["residential"],
        top_k=_candidate_cap(cfg["home_candidates"]), max_radius_km=30.0,
    )
    if residential:
        known = [pair for pair in residential if pair[0] in location_set]
        pool = known or residential
        if str(cfg["mode"]) == "gravity":
            # Same reasoning as the workplace side: a flat choice over the five
            # most central blocks packs the whole town into five addresses.
            return _gravity_pick(city_map, pool, cfg["home_distance_decay"])
        node_id, _ = random.choice(pool[:min(5, len(pool))])
        return node_id

    # Fallback
    candidates = ["Central Block", "North Block", "South Block"]
    home = _pick_first_available(candidates, location_set)
    if home:
        return home
    return random.choice(list(location_set)) if location_set else "Home"


# ---------------------------------------------------------------------------
# Agent location initialisation (in-memory; persistence stays in caller).
# ---------------------------------------------------------------------------

def assign_agent_locations(agent: dict[str, Any], city_map: Any) -> dict[str, Any]:
    home = _infer_home(agent, city_map)
    workplace = _infer_workplace(agent, city_map, home_node=home) or home
    return {
        "home": home,
        "workplace": workplace,
        "current": home,
        "destination": home,
        "in_transit": False,
        "transport_mode": "",
        "travel_minutes": 0,
        "travel_progress": 1.0,
        "travel_route": [home],
        "travel_congestion": 1.0,
        "travel_cost": 0.0,
        "rush_hour": False,
        "arrival_time": "",
        # Commute memory: tracks frequent places and preferred transport modes
        "frequent_places": {},      # {location_id: visit_count}
        "preferred_modes": {},      # {mode: use_count}
        "commute_route": {          # primary commute (home <-> work)
            "mode": "",
            "distance_km": 0.0,
            "avg_minutes": 0,
            "trip_count": 0,
        },
        "daily_travel_cost": 0.0,   # accumulated cost for the current day
    }


# ---------------------------------------------------------------------------
# Commute memory bookkeeping.
# ---------------------------------------------------------------------------

def _update_commute_memory(
    agent: dict[str, Any], destination: str, mode: str, travel_cost: float
) -> None:
    """Update the agent's commute memory after a completed trip."""
    locs = agent.get("locations", {})

    # Update frequent places
    freq = locs.setdefault("frequent_places", {})
    freq[destination] = freq.get(destination, 0) + 1

    # Update preferred modes
    modes = locs.setdefault("preferred_modes", {})
    if mode:
        modes[mode] = modes.get(mode, 0) + 1

    # Update daily travel cost
    locs["daily_travel_cost"] = locs.get("daily_travel_cost", 0.0) + travel_cost

    # Update commute route stats if this is a home<->work trip
    home = locs.get("home", "")
    work = locs.get("workplace", "")
    current = locs.get("current", "")
    is_commute = (
        (current == home and destination == work)
        or (current == work and destination == home)
    )
    if is_commute and mode:
        cr = locs.setdefault("commute_route", {})
        prev_count = cr.get("trip_count", 0)
        prev_avg = cr.get("avg_minutes", 0)
        new_mins = locs.get("travel_minutes", 0)
        cr["mode"] = mode
        cr["distance_km"] = locs.get("travel_distance_km", 0.0)
        cr["avg_minutes"] = round(
            (prev_avg * prev_count + new_mins) / (prev_count + 1), 1
        )
        cr["trip_count"] = prev_count + 1


# ---------------------------------------------------------------------------
# Transit progress tracking.
# ---------------------------------------------------------------------------

def _update_transit_progress(agent: dict[str, Any], current_minutes: int) -> bool:
    locations = agent.get("locations", {})
    if not locations.get("in_transit"):
        return False
    arrival_time = locations.get("arrival_time", "")
    arrival_minutes = _time_str_to_minutes(arrival_time)
    travel_minutes = max(1, int(locations.get("travel_minutes", 1) or 1))
    start_minutes = _time_str_to_minutes(locations.get("depart_time", ""))
    if start_minutes is None:
        start_minutes = current_minutes

    def _complete_transit() -> None:
        locations["in_transit"] = False
        dest = locations.get("destination", locations.get("current", ""))
        locations["current"] = dest
        locations["travel_progress"] = 1.0
        _update_commute_memory(
            agent,
            dest,
            locations.get("transport_mode", ""),
            float(locations.get("travel_cost", 0.0) or 0.0),
        )

    if arrival_minutes is None:
        _complete_transit()
        return True
    elapsed = current_minutes - start_minutes
    if elapsed < 0:
        elapsed += 24 * 60
    if current_minutes == arrival_minutes or elapsed >= travel_minutes:
        _complete_transit()
        return True
    locations["travel_progress"] = max(0.0, min(0.99, elapsed / float(travel_minutes)))
    return False


# ---------------------------------------------------------------------------
# Main movement dispatcher.
# ---------------------------------------------------------------------------

def move_agent(
    agent: dict[str, Any],
    desired_location: str,
    activity: str,
    time_str: str,
    step_minutes: int,
    city_map: Any,
) -> dict[str, Any]:
    locations = agent.setdefault("locations", {})
    current_minutes = _time_str_to_minutes(time_str)
    if current_minutes is None:
        current_minutes = 0
    just_arrived = _update_transit_progress(agent, current_minutes)
    if locations.get("in_transit"):
        return {
            "display_location": f"Transit to {locations.get('destination', '')}",
            "resolved_location": locations.get("current", locations.get("home", "Home")),
            "target_location": locations.get(
                "destination", locations.get("current", locations.get("home", "Home"))
            ),
            "travel": {
                "mode": locations.get("transport_mode", ""),
                "distance_km": float(locations.get("travel_distance_km", 0.0) or 0.0),
                "minutes": int(locations.get("travel_minutes", 0) or 0),
                "progress": float(locations.get("travel_progress", 0.0) or 0.0),
                "route": locations.get("travel_route", []),
                "congestion": float(locations.get("travel_congestion", 1.0) or 1.0),
                "status": "in_transit",
            },
            "just_arrived": just_arrived,
        }

    origin = locations.get("current", locations.get("home", "Home"))
    target = desired_location or origin
    if target == origin:
        locations["destination"] = target
        locations["travel_progress"] = 1.0
        locations["transport_mode"] = ""
        locations["travel_minutes"] = 0
        locations["travel_distance_km"] = 0.0
        locations["travel_route"] = [origin]
        locations["arrival_time"] = time_str
        locations["depart_time"] = time_str
        return {
            "display_location": origin,
            "resolved_location": origin,
            "target_location": target,
            "travel": {
                "mode": "",
                "distance_km": 0.0,
                "minutes": 0,
                "progress": 1.0,
                "route": [origin],
                "congestion": 1.0,
                "status": "stationary",
            },
            "just_arrived": False,
        }

    # Pass time_str for rush-hour detection; weather from environment if available
    _weather = agent.get("_env_weather", None)
    travel = build_travel_plan(
        agent, city_map, origin, target, activity=activity, time_str=time_str, weather=_weather
    )
    travel_minutes = max(1, int(travel.get("travel_minutes", 1) or 1))
    arrival_minutes = (current_minutes + travel_minutes) % (24 * 60)
    arrival_time = _minutes_to_time_str(arrival_minutes)
    travel_cost = float(travel.get("travel_cost", 0.0) or 0.0)
    is_rush = travel.get("rush_hour", False)
    locations["destination"] = target
    locations["transport_mode"] = travel.get("mode", "")
    locations["travel_minutes"] = travel_minutes
    locations["travel_distance_km"] = float(travel.get("distance_km", 0.0) or 0.0)
    locations["travel_cost"] = travel_cost
    locations["rush_hour"] = is_rush
    locations["travel_route"] = travel.get("route", [origin, target])
    locations["travel_congestion"] = float(travel.get("congestion", 1.0) or 1.0)
    locations["depart_time"] = time_str
    locations["arrival_time"] = arrival_time

    if travel_minutes <= max(1, int(step_minutes or 1)):
        locations["current"] = target
        locations["in_transit"] = False
        locations["travel_progress"] = 1.0
        _update_commute_memory(agent, target, travel.get("mode", ""), travel_cost)
        return {
            "display_location": target,
            "resolved_location": target,
            "target_location": target,
            "travel": {
                "mode": travel.get("mode", ""),
                "distance_km": float(travel.get("distance_km", 0.0) or 0.0),
                "minutes": travel_minutes,
                "progress": 1.0,
                "route": travel.get("route", [origin, target]),
                "cost": travel_cost,
                "rush_hour": is_rush,
                "congestion": float(travel.get("congestion", 1.0) or 1.0),
                "status": "arrived",
            },
            "just_arrived": True,
        }

    locations["in_transit"] = True
    locations["travel_progress"] = max(
        0.05, min(0.95, float(step_minutes) / float(travel_minutes))
    )
    return {
        "display_location": f"Transit to {target}",
        "resolved_location": origin,
        "target_location": target,
        "travel": {
            "mode": travel.get("mode", ""),
            "distance_km": float(travel.get("distance_km", 0.0) or 0.0),
            "minutes": travel_minutes,
            "progress": float(locations["travel_progress"]),
            "route": travel.get("route", [origin, target]),
            "cost": travel_cost,
            "rush_hour": is_rush,
            "congestion": float(travel.get("congestion", 1.0) or 1.0),
            "status": "departed",
        },
        "just_arrived": False,
    }


__all__ = [
    "_infer_home",
    "_infer_workplace",
    "_pick_first_available",
    "_update_commute_memory",
    "_update_transit_progress",
    "assign_agent_locations",
    "move_agent",
]
