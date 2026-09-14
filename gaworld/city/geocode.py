"""Resolve a place name to coordinates, a bounding box and a rough scale.

Uses OpenStreetMap's Nominatim.  Everything here is best-effort: a village that
Nominatim has never heard of, or no network at all, must still yield a usable
city — so the caller gets a typed :class:`GeocodeError` and falls back to a
procedural map rather than failing the whole creation.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "GAWorld-sim/1.0 (research; https://github.com/wuchaozju/GAWorld)"
DEFAULT_TIMEOUT = 20

#: OSM ``place`` values mapped to the city scales the map generators understand.
#: Anything unrecognised falls through to a population-based guess.
PLACE_TYPE_SCALE = {
    "hamlet": "tiny",
    "isolated_dwelling": "tiny",
    "farm": "tiny",
    "village": "tiny",
    "neighbourhood": "small",
    "quarter": "small",
    "suburb": "small",
    "town": "small",
    "borough": "medium",
    "municipality": "medium",
    "city": "large",
    "county": "large",
    "state": "metro",
    "province": "metro",
    "region": "metro",
}

#: Population thresholds → scale. Shared with the procedural generator so a
#: place described only by its population still lands in the same buckets.
POPULATION_SCALE_BREAKS = (
    (2_000, "tiny"),
    (20_000, "small"),
    (200_000, "medium"),
    (1_000_000, "large"),
)
LARGEST_SCALE = "metro"

#: How wide a bbox to synthesise (in degrees of latitude) when Nominatim gives
#: none, keyed by scale. Longitude is widened by 1/cos(lat) at build time.
SCALE_BBOX_HALF_DEG = {
    "tiny": 0.015,
    "small": 0.035,
    "medium": 0.07,
    "large": 0.13,
    "metro": 0.22,
}


class GeocodeError(RuntimeError):
    """Raised when a place name could not be resolved to coordinates."""


@dataclass(frozen=True)
class Place:
    """A geocoded place, in the shape the rest of the city layer consumes."""

    query: str
    name: str
    display_name: str
    lat: float
    lng: float
    #: (south, west, north, east) — Overpass order, *not* Nominatim's.
    bbox: tuple[float, float, float, float]
    kind: str
    scale: str
    country: str = ""
    country_code: str = ""
    population: int | None = None
    source: str = "nominatim"
    osm_id: int | None = None
    osm_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bbox"] = list(self.bbox)
        return data


def scale_from_population(population: int | None) -> str | None:
    if population is None:
        return None
    for threshold, scale in POPULATION_SCALE_BREAKS:
        if population < threshold:
            return scale
    return LARGEST_SCALE


def _parse_population(extratags: dict[str, Any]) -> int | None:
    raw = (extratags or {}).get("population")
    if raw in (None, ""):
        return None
    try:
        # OSM population tags are sometimes "1 234 567" or "1,234,567".
        return int(float(str(raw).replace(",", "").replace(" ", "")))
    except (TypeError, ValueError):
        return None


def _nominatim_bbox(raw: Any) -> tuple[float, float, float, float] | None:
    """Nominatim's ``[minlat, maxlat, minlon, maxlon]`` → ``(s, w, n, e)``."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        min_lat, max_lat, min_lon, max_lon = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    return (min_lat, min_lon, max_lat, max_lon)


def synth_bbox(lat: float, lng: float, scale: str) -> tuple[float, float, float, float]:
    """A plausible bbox around a point when the geocoder supplies none."""
    import math

    half_lat = SCALE_BBOX_HALF_DEG.get(scale, SCALE_BBOX_HALF_DEG["medium"])
    # Longitude degrees shrink towards the poles; widen so the box stays roughly
    # square in kilometres.
    half_lng = half_lat / max(0.2, math.cos(math.radians(lat)))
    return (lat - half_lat, lng - half_lng, lat + half_lat, lng + half_lng)


def max_span_for(scale: str) -> float:
    """How wide (in degrees of latitude) a city of *scale* may be.

    Twice the synthesis half-width, so a bbox the geocoder supplies is allowed
    to be a bit generous but still has to describe a place of roughly the right
    size.  Without this a district-level match routinely swallows its
    neighbouring towns and agents end up with 70 km commutes.
    """
    return 2.0 * SCALE_BBOX_HALF_DEG.get(scale, SCALE_BBOX_HALF_DEG["medium"])


def clamp_bbox(
    bbox: tuple[float, float, float, float],
    lat: float,
    lng: float,
    max_span_deg: float = 0.6,
) -> tuple[float, float, float, float]:
    """Shrink an oversized administrative bbox around its centre.

    A province-level match can span several degrees; fetching OSM over that is
    slow, hits the Overpass caps and produces a map whose "city" is really a
    region.  Clamping keeps the fetch bounded and the map legible.
    """
    south, west, north, east = bbox
    if (north - south) <= max_span_deg and (east - west) <= max_span_deg:
        return bbox
    half = max_span_deg / 2.0
    return (lat - half, lng - half, lat + half, lng + half)


def _fetch(url: str, timeout: int) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def geocode(
    name: str,
    *,
    language: str = "zh-CN,zh,en",
    timeout: int = DEFAULT_TIMEOUT,
    fetch: Any = None,
) -> Place:
    """Resolve *name* to a :class:`Place`.

    *fetch* is an injection point for tests: any callable taking ``(url,
    timeout)`` and returning parsed JSON.
    """
    query = str(name or "").strip()
    if not query:
        raise GeocodeError("empty place name")

    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
            "extratags": 1,
            "accept-language": language,
        }
    )
    url = f"{NOMINATIM_URL}?{params}"
    fetcher = fetch or _fetch
    try:
        payload = fetcher(url, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        raise GeocodeError(f"geocoding {query!r} failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GeocodeError(f"geocoding {query!r} returned invalid JSON: {exc}") from exc

    if not isinstance(payload, list) or not payload:
        raise GeocodeError(f"no geocoding match for {query!r}")
    return place_from_nominatim(query, payload[0])


def place_from_nominatim(query: str, hit: dict[str, Any]) -> Place:
    """Convert one Nominatim result into a :class:`Place`."""
    try:
        lat = float(hit["lat"])
        lng = float(hit["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GeocodeError(f"geocoding {query!r} returned no coordinates") from exc

    address = hit.get("address") or {}
    extratags = hit.get("extratags") or {}
    population = _parse_population(extratags)
    kind = str(hit.get("addresstype") or hit.get("type") or "").strip()
    scale = PLACE_TYPE_SCALE.get(kind) or scale_from_population(population) or "medium"

    bbox = _nominatim_bbox(hit.get("boundingbox")) or synth_bbox(lat, lng, scale)
    bbox = clamp_bbox(bbox, lat, lng, max_span_for(scale))

    display = str(hit.get("display_name") or query)
    return Place(
        query=query,
        name=str(hit.get("name") or display.split(",")[0].strip() or query),
        display_name=display,
        lat=lat,
        lng=lng,
        bbox=bbox,
        kind=kind or "unknown",
        scale=scale,
        country=str(address.get("country") or ""),
        country_code=str(address.get("country_code") or "").lower(),
        population=population,
        source="nominatim",
        osm_id=int(hit["osm_id"]) if str(hit.get("osm_id", "")).isdigit() else None,
        osm_type=str(hit.get("osm_type") or ""),
    )


def offline_place(name: str, *, scale: str = "medium", lat: float = 30.2741, lng: float = 120.1551) -> Place:
    """A synthetic :class:`Place` for a name that could not be geocoded.

    Coordinates default to the simulator's historical Hangzhou anchor so an
    offline city still lands in the projection's well-conditioned range.
    """
    query = str(name or "").strip() or "Unnamed"
    return Place(
        query=query,
        name=query,
        display_name=query,
        lat=lat,
        lng=lng,
        bbox=synth_bbox(lat, lng, scale),
        kind="unknown",
        scale=scale,
        source="offline",
    )


__all__ = [
    "GeocodeError",
    "PLACE_TYPE_SCALE",
    "Place",
    "clamp_bbox",
    "geocode",
    "max_span_for",
    "offline_place",
    "place_from_nominatim",
    "scale_from_population",
    "synth_bbox",
]
