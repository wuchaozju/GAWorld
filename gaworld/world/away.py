"""Being out of town: the one definition of what "异地" means.

Two different things put an agent outside the mapped city:

* a **real** phone report whose GPS fix matched no map node (``gaworld.twin``);
* a **simulated** trip — business, family visit, holiday (``gaworld.travel``).

Both write the same marker into ``agent["locations"]["current"]``, because
every downstream reader of that field needs the same answer to "is this a
place on the map?". Deliberately *not* a node id: the agent genuinely is not
at one, and pretending otherwise would put a phantom body into node occupancy
and into the co-location loop.

Only the simulated kind carries an itinerary at ``agent["ext"]["travel"]``.
That asymmetry matters: a real position is decided by a real person, so
nothing here may "send them home". Ask :func:`trip_of` before acting.

The label is display text, never an identifier — never route from it. The
node to come back to lives in the itinerary (``home_node``); deriving it from
the label would go through ``city_map.shortest_path_with_distance``, which
answers ``([], 0.0)`` for an unknown origin and would make the journey home
free and instantaneous.
"""

from __future__ import annotations

from typing import Any

#: Marks a location that is real but outside the simulated city.
AWAY_PREFIX = "异地"


def away_label(place: str | None = None) -> str:
    """The ``current`` marker for someone out of town, named when we can."""
    name = str(place or "").strip()
    return AWAY_PREFIX + (f"（{name}）" if name else "")


def is_away_location(location: Any) -> bool:
    """True when this location string is the out-of-town marker."""
    return str(location or "").startswith(AWAY_PREFIX)


def is_away(agent: Any) -> bool:
    """True when the agent is outside the mapped city, for any reason."""
    if not isinstance(agent, dict):
        return False
    locations = agent.get("locations")
    if not isinstance(locations, dict):
        return False
    return is_away_location(locations.get("current"))


def trip_of(agent: Any) -> dict[str, Any]:
    """The simulated itinerary, or ``{}`` for a real (twin) away position."""
    if not isinstance(agent, dict):
        return {}
    trip = agent.get("ext", {}).get("travel") if isinstance(agent.get("ext"), dict) else None
    return trip if isinstance(trip, dict) else {}


def place_of(agent: Any) -> str:
    """Best-effort place name: the itinerary's, else parsed from the label."""
    trip = trip_of(agent)
    if trip.get("place"):
        return str(trip["place"])
    current = str((agent.get("locations") or {}).get("current", "")) if isinstance(agent, dict) else ""
    if is_away_location(current) and "（" in current:
        return current.split("（", 1)[1].rstrip("）")
    return ""


def home_node_of(agent: Any) -> str:
    """Where a trip returns to — the itinerary's anchor, else the agent's home.

    Never derived from the away label; see the module docstring.
    """
    trip = trip_of(agent)
    node = str(trip.get("home_node", "") or "")
    if node:
        return node
    locations = agent.get("locations", {}) if isinstance(agent, dict) else {}
    return str(locations.get("home", "") or "")
