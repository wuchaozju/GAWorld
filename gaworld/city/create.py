"""Turn a place name into a complete city bundle on disk.

The pipeline is deliberately degradable — each stage has a fallback, because a
village nobody has mapped and a laptop with no network should both still give
you a city you can simulate:

    place name
      → geocode (Nominatim)            ── fails ──▶ synthetic place record
      → real map (Overpass/OSM)        ── fails ──▶ procedural map only
      → procedural map                 (always written: prompt context + fallback)
      → environment config
      → manifest
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

from gaworld.city import bundle as bundle_mod
from gaworld.city.bundle import CityBundle, city_root, new_manifest, slugify
from gaworld.city.environment import build_environment
from gaworld.city.geocode import GeocodeError, Place, geocode, offline_place
from gaworld.city.osm import OSMError, fetch_bundle
from gaworld.city.procedural import generate_citymap, seed_from_name
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.city.create")

#: Mean kilometres per degree of latitude — the same constant the map layer's
#: ``LAT_PER_KM`` encodes, kept here so the anchor maths is self-contained.
KM_PER_LAT_DEG = 111.0
#: Kilometres per degree of longitude at the equator.
KM_PER_LNG_DEG_EQUATOR = 111.32


class CityCreationError(RuntimeError):
    """Raised when a city could not be created at all."""


def projection_origin(place: Place) -> dict[str, float]:
    """The per-city projection anchor stored in the real-map bundle.

    Longitude degrees shrink as ``cos(latitude)``; the simulator's built-in
    constants are calibrated for Hangzhou (~30°N), so a city anywhere else needs
    its own scale or east–west distances come out wrong.
    """
    lng_km_per_deg = KM_PER_LNG_DEG_EQUATOR * math.cos(math.radians(place.lat))
    return {
        "lat": round(place.lat, 6),
        "lng": round(place.lng, 6),
        "lat_per_km": round(1.0 / KM_PER_LAT_DEG, 9),
        "lng_per_km": round(1.0 / max(1.0, lng_km_per_deg), 9),
    }


def resolve_place(
    name: str,
    *,
    offline: bool = False,
    scale: str | None = None,
    geocode_fn: Callable[..., Place] | None = None,
) -> Place:
    """Geocode *name*, degrading to a synthetic record when that is impossible."""
    if offline:
        place = offline_place(name, scale=scale or "medium")
    else:
        try:
            place = (geocode_fn or geocode)(name)
        except GeocodeError as exc:
            _LOG.warning("geocoding failed (%s); falling back to an offline place record", exc)
            place = offline_place(name, scale=scale or "medium")
    if scale and scale != place.scale:
        # An explicit --scale is the operator's call and overrides the guess.
        place = Place(**{**place.to_dict(), "bbox": place.bbox, "scale": scale})
    return place


def create_city(
    name: str,
    *,
    slug: str | None = None,
    scale: str | None = None,
    offline: bool = False,
    force: bool = False,
    root: Path | str | None = None,
    geocode_fn: Callable[..., Place] | None = None,
    overpass: Callable[[str, int], dict[str, Any]] | None = None,
    seed: int | None = None,
) -> CityBundle:
    """Create a city bundle for *name* and return it.

    Parameters
    ----------
    offline
        Skip both geocoding and the OSM fetch; build everything procedurally.
    force
        Overwrite an existing bundle with the same slug.
    overpass
        Injection point for the Overpass client (tests / custom mirrors).
    """
    label = str(name or "").strip()
    if not label:
        raise CityCreationError("a place name is required")

    city_slug = slugify(slug or label)
    directory = city_root(root) / city_slug
    # A directory without a manifest is the debris of a creation that was
    # interrupted (killed mid-fetch, disk full). It is not a city, so it should
    # not make the user reach for --force to try again.
    complete = (directory / bundle_mod.MANIFEST_NAME).exists()
    if directory.exists() and complete and not force:
        raise CityCreationError(
            f"city {city_slug!r} already exists at {directory}; pass force=True to overwrite"
        )

    place = resolve_place(label, offline=offline, scale=scale, geocode_fn=geocode_fn)
    map_seed = seed if seed is not None else seed_from_name(city_slug)

    directory.mkdir(parents=True, exist_ok=True)
    city = CityBundle(
        directory=directory,
        manifest=new_manifest(
            slug=city_slug,
            name=place.name or label,
            display_name=place.display_name or label,
            place=place.to_dict(),
            scale=place.scale,
        ),
    )

    # 1. Procedural map — always written. It doubles as the LLM prompt context
    #    and as the fallback if the real bundle is ever deleted.
    spec = generate_citymap(place.name or label, scale=place.scale, seed=map_seed)
    city.virtual_map_path.write_text(spec, encoding="utf-8")
    city.record("map.virtual", scale=place.scale, seed=map_seed)

    # 2. Real map — best effort, and only when the coordinates are real.
    #    A place that failed to geocode carries a *synthetic* bbox around the
    #    default anchor; fetching OSM for that would burn a slow round of
    #    Overpass retries on a region that has nothing to do with the request.
    origin = projection_origin(place)
    if not offline and place.source == "nominatim":
        try:
            geojson = fetch_bundle(
                place.bbox, city=place.name or label, origin=origin, overpass=overpass
            )
        except OSMError as exc:
            _LOG.warning("real map unavailable for %s (%s); using the procedural map", label, exc)
            city.record("map.real.skipped", reason=str(exc))
        else:
            city.real_map_path.write_text(
                json.dumps(geojson, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            node_count = sum(
                1 for f in geojson.get("features", []) if (f.get("geometry") or {}).get("type") == "Point"
            )
            city.manifest["map"] = {
                "mode": "real",
                "virtual": bundle_mod.VIRTUAL_MAP_NAME,
                "real": bundle_mod.REAL_MAP_NAME,
                "origin": origin,
                "nodes": node_count,
            }
            city.record("map.real", nodes=node_count, bbox=list(place.bbox))

    # 3. Environment.
    city.environment_path.write_text(
        json.dumps(build_environment(place, seed=map_seed), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    city.record("environment", climate=build_environment(place)["climate"])

    city.record("create", offline=offline, source=place.source)
    city.save()
    _LOG.info("created city %s at %s (map_mode=%s)", city_slug, directory, city.map_mode)
    return city


__all__ = ["CityCreationError", "create_city", "projection_origin", "resolve_place"]
