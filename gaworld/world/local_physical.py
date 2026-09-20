"""Local physical environment perception (P0).

The city map already carries per-node physical state — occupancy vs.
capacity (``occupancy_ratio``) and opening hours (``is_open``) — but
nothing in the simulation loop ever populated occupancy or read these
back, so they were effectively dead code (see
``docs/physical_env_perception_analysis.md`` §3.1).

This module closes that gap with three pure, LLM-free helpers:

* ``update_occupancy_from_agents`` — recompute node occupancy each tick
  from where agents actually are.
* ``local_physical_state`` — a per-agent snapshot of the *current*
  location's physical condition (crowding, open/closed, local weather).
* ``physical_state_text`` — render that snapshot as a short Chinese
  fragment for injection into perception / decision context.

All behaviour is gated by ``CONFIG["local_physical"]["enabled"]`` at the
call sites; the functions themselves are side-effect-free except for
``update_occupancy_from_agents`` (which only writes to ``city_map``).
"""

from __future__ import annotations

from typing import Any

from gaworld.world import city_map as _cm

# Default thresholds; overridable via CONFIG["local_physical"].
_DEFAULT_BUSY_RATIO = 0.6
_DEFAULT_PACKED_RATIO = 0.9
_DEFAULT_ANOMALY_RATIO = 0.9
_DEFAULT_ANOMALY_JUMP = 0.25


def _prev_occupancy_ratio(city_map: Any, node_id: str) -> float:
    """Occupancy ratio recorded on the *previous* tick (0.0 if none)."""
    if not city_map or not node_id:
        return 0.0
    runtime = _cm._runtime(city_map)
    prev = runtime.get("node_occupancy_prev", {})
    count = int(prev.get(_cm._slug(node_id), 0))
    node = _cm.node_by_name(city_map, node_id)
    if not node:
        return 0.0
    cap = max(1, int(node.get("capacity", 1) or 1))
    return round(count / cap, 3)


def update_occupancy_from_agents(city_map: Any, agents: list[dict[str, Any]] | None) -> dict[str, int]:
    """Recompute node occupancy from agents' current locations.

    Counts each *stationary* (non-in-transit) agent at its current
    resolved location and writes the result back into the city map's
    runtime occupancy table. Stale nodes are cleared so occupancy always
    reflects the present tick.

    Returns the computed ``{location_name: count}`` map (handy for tests
    and for emergent-anomaly detection in later phases).
    """
    counts: dict[str, int] = {}
    if not city_map or not agents:
        # Still clear any stale occupancy so we never report phantom crowds.
        if city_map:
            _cm._runtime(city_map)["node_occupancy"] = {}
        return counts

    for agent in agents:
        locations = agent.get("locations") if isinstance(agent, dict) else None
        if not isinstance(locations, dict):
            continue
        if locations.get("in_transit"):
            continue
        current = locations.get("current") or locations.get("home")
        if not current:
            continue
        counts[current] = counts.get(current, 0) + 1

    runtime = _cm._runtime(city_map)
    # Remember last tick's occupancy so emergent crowd surges can be detected.
    runtime["node_occupancy_prev"] = dict(runtime.get("node_occupancy", {}))
    runtime["node_occupancy"] = {}
    for name, count in counts.items():
        _cm.set_node_occupancy(city_map, name, count)
    return counts


def crowding_label(ratio: float, busy_ratio: float = _DEFAULT_BUSY_RATIO,
                   packed_ratio: float = _DEFAULT_PACKED_RATIO) -> str:
    """Map an occupancy ratio to a coarse Chinese crowding label."""
    if ratio >= packed_ratio:
        return "非常拥挤"
    if ratio >= busy_ratio:
        return "比较拥挤"
    if ratio >= max(0.0, busy_ratio / 2.0):
        return "人不少"
    return "比较空旷"


def local_physical_state(
    city_map: Any,
    agent: dict[str, Any],
    time_str: str = "",
    weather_state: str = "",
    *,
    busy_ratio: float = _DEFAULT_BUSY_RATIO,
    packed_ratio: float = _DEFAULT_PACKED_RATIO,
    anomaly_ratio: float = _DEFAULT_ANOMALY_RATIO,
    anomaly_jump: float = _DEFAULT_ANOMALY_JUMP,
) -> dict[str, Any]:
    """Snapshot the physical condition of the agent's *current* location.

    Never raises: unknown locations or missing maps degrade gracefully to
    a benign, empty snapshot. Sets an emergent ``anomaly`` flag (P2) when
    the location is packed *and* occupancy jumped sharply vs. last tick.
    """
    locations = agent.get("locations") if isinstance(agent, dict) else None
    locations = locations if isinstance(locations, dict) else {}
    in_transit = bool(locations.get("in_transit"))
    location = locations.get("current") or locations.get("home") or ""

    state: dict[str, Any] = {
        "location": location,
        "in_transit": in_transit,
        "occupancy_ratio": 0.0,
        "crowding": "",
        "is_open": True,
        "weather": str(weather_state or ""),
        "anomaly": False,
        "anomaly_kind": "",
    }
    if not location or in_transit or not city_map:
        return state

    try:
        ratio = float(_cm.occupancy_ratio(city_map, location))
    except Exception:
        ratio = 0.0
    state["occupancy_ratio"] = ratio
    state["crowding"] = crowding_label(ratio, busy_ratio, packed_ratio)
    try:
        state["is_open"] = bool(_cm.is_open(city_map, location, time_str))
    except Exception:
        state["is_open"] = True

    prev_ratio = _prev_occupancy_ratio(city_map, location)
    if ratio >= anomaly_ratio and (ratio - prev_ratio) >= anomaly_jump:
        state["anomaly"] = True
        state["anomaly_kind"] = "crowd_surge"
    return state


def physical_state_text(state: dict[str, Any] | None) -> str:
    """Render a snapshot as a short Chinese fragment (empty when uninformative)."""
    if not isinstance(state, dict) or state.get("in_transit"):
        return ""
    location = str(state.get("location") or "").strip()
    if not location:
        return ""
    parts: list[str] = []
    if state.get("anomaly") and state.get("anomaly_kind") == "crowd_surge":
        parts.append(f"{location}人流骤增，明显不同寻常")
    crowding = str(state.get("crowding") or "").strip()
    if crowding and not state.get("anomaly"):
        parts.append(f"{location}此刻{crowding}")
    if state.get("is_open", True) is False:
        parts.append(f"{location}目前不在营业时间")
    weather = str(state.get("weather") or "").strip()
    if weather:
        parts.append(f"当地天气{weather}")
    return "；".join(parts)


__all__ = [
    "crowding_label",
    "local_physical_state",
    "physical_state_text",
    "update_occupancy_from_agents",
]
