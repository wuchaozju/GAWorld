"""Offline place naming for coordinates outside the simulated map.

A real GPS fix is always worth recording, even when it falls far outside the
city the simulation models. To say something more useful than a pair of
decimals, this turns a coordinate into a human place name.

**Everything here is offline by design.** Reverse geocoding normally means
sending the user's exact position to a third-party service, which would break
the one privacy promise this feature makes — that location data goes only to
your own server. So naming is done against a small builtin table and the
city bundles already on disk, and never over the network.

The trade-off is precision: this answers at province granularity (plus any
city bundle you have built), not street level. That is the right resolution
for an "away" marker, and it is stated rather than hidden.
"""

from __future__ import annotations

import json
import math
import os


#: Province-level divisions keyed by their administrative centre. Nearest-
#: centre lookup is approximate and can pick the wrong side of a border; it is
#: used only for a coarse "away (somewhere)" label, never for simulation state.
REGION_CENTRES = (
    ("北京", 39.90, 116.41),
    ("天津", 39.34, 117.36),
    ("上海", 31.23, 121.47),
    ("重庆", 29.56, 106.55),
    ("河北", 38.04, 114.51),
    ("山西", 37.87, 112.55),
    ("辽宁", 41.80, 123.43),
    ("吉林", 43.82, 125.32),
    ("黑龙江", 45.80, 126.53),
    ("江苏", 32.06, 118.80),
    ("浙江", 30.27, 120.15),
    ("安徽", 31.82, 117.23),
    ("福建", 26.07, 119.30),
    ("江西", 28.68, 115.86),
    ("山东", 36.65, 117.12),
    ("河南", 34.75, 113.62),
    ("湖北", 30.59, 114.30),
    ("湖南", 28.23, 112.94),
    ("广东", 23.13, 113.26),
    ("海南", 20.04, 110.20),
    ("四川", 30.57, 104.07),
    ("贵州", 26.65, 106.63),
    ("云南", 25.04, 102.71),
    ("陕西", 34.34, 108.94),
    ("甘肃", 36.06, 103.83),
    ("青海", 36.62, 101.78),
    ("台湾", 25.03, 121.57),
    ("内蒙古", 40.84, 111.75),
    ("广西", 22.82, 108.32),
    ("西藏", 29.65, 91.14),
    ("宁夏", 38.49, 106.23),
    ("新疆", 43.83, 87.62),
    ("香港", 22.32, 114.17),
    ("澳门", 22.20, 113.54),
)

#: Beyond this, the nearest province centre is not a meaningful answer — the
#: user is most likely outside the country, and a confident wrong label is
#: worse than plain coordinates.
MAX_REGION_KM = 1500.0

DEFAULT_CITY_DIR = "data/cities"


def haversine_km(lat_a, lng_a, lat_b, lng_b):
    radius = 6371.0
    dlat = math.radians(float(lat_b) - float(lat_a))
    dlng = math.radians(float(lng_b) - float(lng_a))
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(float(lat_a)))
        * math.cos(math.radians(float(lat_b)))
        * math.sin(dlng / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def format_coords(lat, lng):
    lat_hemi = "N" if float(lat) >= 0 else "S"
    lng_hemi = "E" if float(lng) >= 0 else "W"
    return f"{abs(float(lat)):.2f}°{lat_hemi} {abs(float(lng)):.2f}°{lng_hemi}"


def load_city_places(city_dir=DEFAULT_CITY_DIR):
    """Read name + bbox from every city bundle already built on disk."""
    places = []
    try:
        slugs = os.listdir(city_dir)
    except OSError:
        return places
    for slug in slugs:
        path = os.path.join(city_dir, slug, "city.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                bundle = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        place = (bundle or {}).get("place") or {}
        try:
            entry = {
                "name": str(place.get("name") or bundle.get("name") or slug),
                "lat": float(place["lat"]),
                "lng": float(place["lng"]),
                "bbox": place.get("bbox"),
            }
        except (KeyError, TypeError, ValueError):
            continue
        places.append(entry)
    return places


def _in_bbox(lat, lng, bbox):
    try:
        south, west, north, east = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return False
    return south <= float(lat) <= north and west <= float(lng) <= east


def describe(lat, lng, city_places=None, max_region_km=MAX_REGION_KM):
    """Best-effort offline name for a coordinate.

    Resolution order, most specific first:

    1. inside a built city bundle's bbox — that city's own name;
    2. nearest province-level centre within ``max_region_km``;
    3. plain coordinates, when nothing credible applies.
    """
    if lat is None or lng is None:
        return ""
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return ""

    for place in city_places or []:
        if place.get("bbox") and _in_bbox(lat, lng, place["bbox"]):
            return place["name"]

    best_name = None
    best_km = math.inf
    for name, centre_lat, centre_lng in REGION_CENTRES:
        km = haversine_km(lat, lng, centre_lat, centre_lng)
        if km < best_km:
            best_name = name
            best_km = km

    if best_name is not None and best_km <= float(max_region_km):
        return best_name
    return format_coords(lat, lng)
