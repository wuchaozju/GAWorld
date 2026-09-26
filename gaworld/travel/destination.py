"""Where a trip goes, and what the journey costs.

Everything here is offline and reuses data already in the repo:

* the destination catalogue is the twin's province-centre table
  (``gaworld/twin/places.py``) — 34 Chinese place names with coordinates,
  offline by design and already in the repo;
* the origin is the city map's own geometric centre, whose nodes carry true
  ``lat``/``lng`` (procedural maps are anchored near Hangzhou, real-map
  bundles use the real thing);
* the distance is the twin's ``haversine_km``.

So a trip's length is a real distance between two real points, not a number
someone picked. The *fare and speed coefficients* below are not: they are
plausible-guess parameters (mechanism class (c) in the bench's provenance
table), and no conclusion may rest on their absolute level.
"""

from __future__ import annotations

import random
from typing import Any

from gaworld.twin.places import REGION_CENTRES, haversine_km
from gaworld.world.city_map import map_center_name, node_by_name

#: Nearer than this and it is a day trip inside the same region, not a
#: journey out of town — such destinations are dropped from the catalogue.
MIN_TRIP_KM = 120.0

#: Above this distance people fly rather than take the train.
AIR_THRESHOLD_KM = 1200.0

#: Effective door-to-door speeds, km/h. Rail is the service speed of a
#: Chinese high-speed line; air is cruise speed, with the ground time added
#: separately below because it does not scale with distance.
RAIL_SPEED_KMH = 250.0
AIR_SPEED_KMH = 700.0

#: Hours of check-in / security / airport transfer on each leg of a flight.
AIR_GROUND_HOURS = 2.0

#: Minimum one-way journey, hours. Even a short hop eats half a day.
MIN_LEG_HOURS = 2.0

DEFAULT_FARE_PER_KM = {"rail": 0.45, "air": 0.75}


def city_origin(city_map: Any) -> tuple[float, float] | None:
    """The mapped city's own coordinate, or ``None`` for an empty map."""
    if not isinstance(city_map, dict):
        return None
    centre = map_center_name(city_map)
    node = node_by_name(city_map, centre) if centre else None
    if not node:
        return None
    lat, lng = node.get("lat"), node.get("lng")
    if lat is None or lng is None:
        return None
    return float(lat), float(lng)


def catalogue(city_map: Any) -> list[tuple[str, float]]:
    """``(place, km)`` for every destination far enough to count as a trip.

    Sorted by name so the catalogue — and therefore any seeded draw from it —
    does not depend on the order of the source table.
    """
    origin = city_origin(city_map)
    if origin is None:
        return []
    lat, lng = origin
    out = [
        (name, round(haversine_km(lat, lng, c_lat, c_lng), 1))
        for name, c_lat, c_lng in REGION_CENTRES
    ]
    return sorted([(n, d) for n, d in out if d >= MIN_TRIP_KM], key=lambda e: e[0])


def distance_to(city_map: Any, place: str) -> float:
    """Distance to a named place, or ``0.0`` when it is not in the table."""
    origin = city_origin(city_map)
    if origin is None or not place:
        return 0.0
    lat, lng = origin
    for name, c_lat, c_lng in REGION_CENTRES:
        if name == str(place).strip():
            return round(haversine_km(lat, lng, c_lat, c_lng), 1)
    return 0.0


def match_place(text: Any) -> str:
    """The table entry named inside a free-text city string, else ``""``.

    Ghost profiles store a city the LLM wrote ("北京" / "北京市" / "浙江杭州"),
    so an exact lookup would miss most of them.
    """
    blob = str(text or "").strip()
    if not blob:
        return ""
    for name, _lat, _lng in REGION_CENTRES:
        if name in blob:
            return name
    return ""


def journey(distance_km: float, fare_per_km: dict[str, float] | None = None) -> dict[str, Any]:
    """One-way mode, hours and fare for a given distance."""
    km = max(0.0, float(distance_km))
    fares = dict(DEFAULT_FARE_PER_KM)
    if isinstance(fare_per_km, dict):
        fares.update({k: float(v) for k, v in fare_per_km.items()})
    if km > AIR_THRESHOLD_KM:
        mode = "air"
        hours = km / AIR_SPEED_KMH + AIR_GROUND_HOURS
    else:
        mode = "rail"
        hours = km / RAIL_SPEED_KMH
    return {
        "mode": mode,
        "hours": round(max(MIN_LEG_HOURS, hours), 2),
        "fare": round(km * fares.get(mode, DEFAULT_FARE_PER_KM[mode]), 2),
    }


def pick(
    city_map: Any,
    rng: random.Random,
    *,
    prefer: str = "",
    max_km: float | None = None,
) -> tuple[str, float]:
    """Choose a destination: ``prefer`` when it is usable, else a draw.

    The draw is inverse-distance weighted — people go to the next province far
    more often than across the country — and bounded by ``max_km`` so a
    two-day business trip cannot land 3000 km away.
    """
    places = catalogue(city_map)
    if not places:
        return "", 0.0
    wanted = match_place(prefer)
    if wanted:
        for name, km in places:
            if name == wanted and (max_km is None or km <= float(max_km)):
                return name, km
    pool = [(n, d) for n, d in places if max_km is None or d <= float(max_km)]
    if not pool:
        pool = [min(places, key=lambda e: e[1])]
    weights = [1.0 / max(1.0, d) for _n, d in pool]
    return rng.choices(pool, weights=weights, k=1)[0]
