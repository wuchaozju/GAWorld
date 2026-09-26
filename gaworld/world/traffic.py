"""Endogenous road congestion (P1).

The city map has carried a per-edge travel-time multiplier
(``set_edge_congestion`` / ``get_edge_congestion``) since the map layer was
written, and ``travel_plan`` already multiplies trip duration by
``_route_congestion``. Nothing ever *wrote* to it, so the read side was
exercised only in the free-flow case and the road network was congestion
free by construction.

This module closes that gap the same way ``local_physical`` closed the
node-occupancy gap: recompute a physical quantity from what the agents
actually did, write it back into the city map's runtime, and let the next
tick read it.

* ``accumulate_travel`` — add one completed/ongoing trip's PCU load to the
  edges of its route.
* ``apply_flows`` — turn a tick's accumulated edge flows into travel-time
  multipliers via the BPR link performance function, blended with the
  previous tick so congestion eases rather than snapping.

Design notes that are load-bearing:

* **One tick of lag is deliberate.** Flows collected during tick T are
  committed at the start of tick T+1. Reading and writing within one tick
  would make the agent iteration order decide who gets stuck in traffic,
  which destroys run-to-run determinism.
* **A trip counts on every tick it spans, and single-tick trips count too.**
  ``move_agent`` only marks an agent ``in_transit`` when the trip is longer
  than one step, so at the default 10-30 minute step most intra-town trips
  finish inside one tick. Counting only ``in_transit`` agents would miss
  nearly every vehicle and congestion would stay at zero.
* **BPR, not a hand-rolled curve.** ``t = t0 * (1 + alpha * (v/c)^beta)`` is
  the standard link performance function with published parameter ranges;
  ``beta = 4`` gives the "free until ~80% of capacity, then a cliff" shape
  without any extra thresholding.

All behaviour is gated by ``CONFIG["traffic"]["enabled"]`` at the call site
(``TrafficPlugin``); the functions here are pure except ``apply_flows``,
which only writes to ``city_map``.
"""

from __future__ import annotations

from typing import Any

from gaworld.world import city_map as _cm

# Rough capacity in passenger-car units per hour, per direction, by road
# class. The map keys congestion by an *undirected* edge (``_edge_key`` sorts
# its endpoints) and ``get_edge_congestion`` reads it the same way, so both
# directions necessarily share one multiplier; ``edge_capacity_pcu`` therefore
# compares the two-way flow against ``EDGE_DIRECTIONS`` times these values.
ROAD_TYPE_CAPACITY: dict[str, float] = {
    "arterial": 1800.0,
    "collector": 900.0,
    "local": 400.0,
    "road": 900.0,
}

# Passenger-car equivalents. Walking and metro do not use the road network;
# a bus occupies more road than a car (that it also carries more people is a
# separate question, handled — if ever — by a transit capacity layer).
MODE_PCU: dict[str, float] = {
    "car": 1.0,
    "taxi": 1.0,
    "bus": 2.0,
    "e-bike": 0.2,
    "bike": 0.2,
    "walk": 0.0,
    "metro": 0.0,
}

# Trip states that put a vehicle on the road during this tick.
ON_ROAD_STATUSES = frozenset({"arrived", "departed", "in_transit"})

# Both directions of a road share one congestion entry (see above).
EDGE_DIRECTIONS = 2

DEFAULT_ALPHA = 0.15
DEFAULT_BETA = 4.0
DEFAULT_DECAY = 0.5
DEFAULT_MAX_CONGESTION = 3.0

# Below this, an edge is free-flowing and is dropped from the runtime table
# so it does not grow without bound over a long run.
_PRUNE_EPS = 1e-3
# Guards ``ratio ** beta`` against absurd inputs; the result is clamped to
# ``max_congestion`` anyway.
_MAX_RATIO = 1e3


#: Two-wheelers are cheap, so ownership is high and only weakly graded by
#: income — the pivot sits well *below* the median and the curve is flat.
#: Anchor: China's e-bike stock passed 400 million in 2024 against a
#: population of ~1.41 billion (~0.28 per person, all ages). Ownership among
#: working-age commuters is higher than that population-wide figure, since
#: children and the very old hold almost none.
DEFAULT_TWO_WHEELER_PIVOT_MULTIPLE = 0.35
DEFAULT_TWO_WHEELER_SPREAD = 1.1
DEFAULT_CAR_PIVOT_MULTIPLE = 1.2
DEFAULT_CAR_SPREAD = 0.55
DEFAULT_DRIVING_AGE = 18


def assign_two_wheeler_ownership(
    agents,
    *,
    pivot_multiple: float = DEFAULT_TWO_WHEELER_PIVOT_MULTIPLE,
    spread: float = DEFAULT_TWO_WHEELER_SPREAD,
    riding_age: int = 16,
    rng=None,
) -> float:
    """Decide who has a bike or e-bike. Returns the resulting rate.

    The counterpart to car ownership, and the assumption the scored mode
    model exposed: every resident was treated as having a two-wheeler, so
    the cheapest and quickest option was always available to everyone and
    active travel came out at 98.5% of commutes. Cars were modelled; the
    thing most people actually ride was not.
    """
    return _assign_ownership(
        agents, "has_two_wheeler", pivot_multiple, spread, riding_age, rng)


def assign_car_ownership(
    agents,
    *,
    pivot_multiple: float = DEFAULT_CAR_PIVOT_MULTIPLE,
    spread: float = DEFAULT_CAR_SPREAD,
    driving_age: int = DEFAULT_DRIVING_AGE,
    rng=None,
) -> float:
    """Decide who has a car, from income. Returns the resulting rate.

    Mode choice had no ownership condition at all: a trip of 6-10 km with no
    metro access simply became a car trip, so the car share was whatever the
    geometry happened to produce and the transit share could not be compared
    against anything. Ownership rises with income on a logistic in log-income
    — the standard form — with the 50% point set at a multiple of *this
    town's* median, so the same parameters transfer to a richer or poorer
    population instead of being re-tuned per map.

    **Per agent, not per household** — a retired parent in a car-owning family
    is counted as car-less here. Households are derived at run time and the
    mode chooser cannot see them, so this is a deliberate simplification and
    a (c)-class assumption: the level it produces is not evidence, only its
    response to income is.
    """
    return _assign_ownership(
        agents, "has_car", pivot_multiple, spread, driving_age, rng)


def _assign_ownership(agents, field, pivot_multiple, spread, min_age, rng) -> float:
    """Logistic in log-income, with the 50% point at a multiple of the median."""
    import math
    import random as _random

    people = [a for a in (agents or []) if isinstance(a, dict)]
    incomes = sorted(_to_float(a.get("monthly_income")) for a in people)
    incomes = [x for x in incomes if x > 0]
    if not incomes:
        for agent in people:
            agent[field] = False
        return 0.0
    median = incomes[len(incomes) // 2]
    pivot = max(1.0, median * max(0.01, _to_float(pivot_multiple, 1.0)))
    width = max(0.01, _to_float(spread, 0.55))
    picker = rng or _random
    owners = 0
    for agent in people:
        income = _to_float(agent.get("monthly_income"))
        age = int(_to_float(agent.get("age"), min_age))
        if income <= 0 or age < min_age:
            agent[field] = False
            continue
        odds = (math.log(income) - math.log(pivot)) / width
        probability = 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, odds))))
        agent[field] = picker.random() < probability
        owners += bool(agent[field])
    return round(owners / len(people), 4) if people else 0.0


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip01(value: Any, default: float = 0.0) -> float:
    return max(0.0, min(1.0, _to_float(value, default)))


def travel_pcu(travel: dict[str, Any] | None, mode_pcu: dict[str, float] | None = None) -> float:
    """Road load of one trip, in passenger-car units (0.0 when off-road)."""
    if not isinstance(travel, dict):
        return 0.0
    if str(travel.get("status", "")) not in ON_ROAD_STATUSES:
        return 0.0
    route = travel.get("route")
    if not isinstance(route, (list, tuple)) or len(route) < 2:
        return 0.0
    table = mode_pcu if isinstance(mode_pcu, dict) else MODE_PCU
    return max(0.0, _to_float(table.get(str(travel.get("mode", "")), 0.0)))


def accumulate_travel(
    flows: dict[str, float],
    travel: dict[str, Any] | None,
    *,
    mode_pcu: dict[str, float] | None = None,
    agents_represent: float = 1.0,
) -> float:
    """Add one trip's load to every edge of its route. Returns the PCU added.

    ``agents_represent`` scales one simulated traveller up to the number of
    real travellers it stands for. It is a **modelling knob, not a
    demographic fact**: the simulated population is a sample, so without it
    ``v/c`` is ~0 and congestion never happens.
    """
    pcu = travel_pcu(travel, mode_pcu) * max(0.0, _to_float(agents_represent, 1.0))
    if pcu <= 0.0:
        return 0.0
    route = travel.get("route", [])  # type: ignore[union-attr]
    for a_name, b_name in zip(route, route[1:]):
        if not a_name or not b_name:
            continue
        key = _cm._edge_key(a_name, b_name)
        flows[key] = flows.get(key, 0.0) + pcu
    return pcu


def bpr_factor(
    flow: float,
    capacity: float,
    *,
    alpha: float = DEFAULT_ALPHA,
    beta: float = DEFAULT_BETA,
    max_congestion: float = DEFAULT_MAX_CONGESTION,
) -> float:
    """BPR link performance function, clamped to ``max_congestion``."""
    cap = max(1e-6, _to_float(capacity, 1.0))
    ratio = min(_MAX_RATIO, max(0.0, _to_float(flow)) / cap)
    factor = 1.0 + max(0.0, _to_float(alpha, DEFAULT_ALPHA)) * (
        ratio ** max(0.0, _to_float(beta, DEFAULT_BETA))
    )
    return min(max(1.0, _to_float(max_congestion, DEFAULT_MAX_CONGESTION)), factor)


def edge_road_type(city_map: Any, a: str, b: str) -> str:
    """Road class of the edge between two nodes (``"road"`` when unknown).

    Parallel edges are resolved first-match, matching ``_route_road_factor``
    — the two must not disagree about the same road.
    """
    if not isinstance(city_map, dict):
        return "road"
    node_a = _cm.node_by_name(city_map, a)
    node_b = _cm.node_by_name(city_map, b)
    if not node_a or not node_b:
        return "road"
    for edge in city_map.get("adjacency", {}).get(node_a["id"], []):
        if edge.get("node") == node_b["id"]:
            return str(edge.get("road_type") or "road")
    return "road"


def edge_capacity_pcu(
    city_map: Any,
    a: str,
    b: str,
    *,
    step_minutes: float,
    road_capacity: dict[str, float] | None = None,
) -> float:
    """Per-tick capacity of an edge, in PCU."""
    table = road_capacity if isinstance(road_capacity, dict) else ROAD_TYPE_CAPACITY
    fallback = _to_float(table.get("road"), ROAD_TYPE_CAPACITY["road"])
    per_hour = _to_float(table.get(edge_road_type(city_map, a, b)), fallback)
    minutes = max(1.0, _to_float(step_minutes, 30.0))
    return max(1e-6, per_hour * EDGE_DIRECTIONS * minutes / 60.0)


def _key_endpoints(edge_key: str) -> tuple[str, str]:
    parts = str(edge_key).split("||")
    return (parts[0], parts[1]) if len(parts) == 2 else ("", "")


def apply_flows(
    city_map: Any,
    flows: dict[str, float] | None,
    *,
    step_minutes: float,
    alpha: float = DEFAULT_ALPHA,
    beta: float = DEFAULT_BETA,
    decay: float = DEFAULT_DECAY,
    max_congestion: float = DEFAULT_MAX_CONGESTION,
    road_capacity: dict[str, float] | None = None,
) -> dict[str, float]:
    """Commit a tick's edge flows as travel-time multipliers on the map.

    Edges that carried no flow this tick relax back towards free flow at the
    same ``decay`` rate rather than snapping to 1.0, and are dropped once
    they are indistinguishable from it.
    """
    if not city_map:
        return {}
    runtime = _cm._runtime(city_map)
    previous = dict(runtime.get("edge_congestion", {}))
    flows = flows if isinstance(flows, dict) else {}
    weight = _clip01(decay, DEFAULT_DECAY)
    updated: dict[str, float] = {}
    for key in set(previous) | set(flows):
        a_name, b_name = _key_endpoints(key)
        capacity = edge_capacity_pcu(
            city_map, a_name, b_name,
            step_minutes=step_minutes, road_capacity=road_capacity,
        )
        raw = bpr_factor(
            flows.get(key, 0.0), capacity,
            alpha=alpha, beta=beta, max_congestion=max_congestion,
        )
        blended = weight * _to_float(previous.get(key), 1.0) + (1.0 - weight) * raw
        if blended > 1.0 + _PRUNE_EPS:
            updated[key] = round(blended, 4)
    runtime["edge_congestion"] = updated
    return updated


__all__ = [
    "EDGE_DIRECTIONS",
    "assign_car_ownership",
    "assign_two_wheeler_ownership",
    "MODE_PCU",
    "ON_ROAD_STATUSES",
    "ROAD_TYPE_CAPACITY",
    "accumulate_travel",
    "apply_flows",
    "bpr_factor",
    "edge_capacity_pcu",
    "edge_road_type",
    "travel_pcu",
]
