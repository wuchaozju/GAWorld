"""Turn a place name — or a description of one — into a city bundle on disk.

The pipeline is deliberately degradable — each stage has a fallback, because a
village nobody has mapped and a laptop with no network should both still give
you a city you can simulate:

    place name
      → geocode (Nominatim)            ── fails ──▶ synthetic place record
      → real map (Overpass/OSM)        ── fails ──▶ procedural map only
      → procedural map                 (always written: prompt context + fallback)
      → environment config
      → manifest

A city that does not exist takes the second route.  Nothing to geocode and
nothing to fetch, so the evidence is whatever the user supplied and an LLM does
the design work that Nominatim and Overpass do for a real place:

    description and/or sketch
      → imagine (LLM)                  ── fails ──▶ procedural map by name
      → climate and economy from the same pass
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
from gaworld.city.imagine import ImagineError, ImaginedCity, imagine_city
from gaworld.city.knowledge import CityProfile, build_from_map, build_from_web, map_category_counts
from gaworld.city.locale import build_locale
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


def default_search(query: str) -> list[dict[str, str]]:
    """Web search for the city layer, reusing the simulator's own engines."""
    from gaworld.settings import CONFIG
    from gaworld.sim._news import web_search

    _engine, results = web_search(query, config=(CONFIG.get("news", {}) or {}))
    return results


def default_llm(prompt: str) -> str:
    from gaworld.llm.providers import call_llm

    return call_llm(prompt, task="city_knowledge")


#: Output budget for one city design. A dozen districts with their places,
#: roads, industries and labour demand runs to ~3–4k tokens of JSON; the
#: providers' 512-token default cuts that off mid-object, and a truncated
#: design is indistinguishable from a model that answered badly.
DESIGN_MAX_TOKENS = 8000


def default_design_llm(prompt: str, *, images: list[dict[str, str]] | None = None) -> str:
    """The model call behind an imagined city. Separate task key from knowledge:
    designing a city wants a larger, image-capable model than summarising one."""
    from gaworld.llm.providers import call_llm

    return call_llm(prompt, task="city_design", images=images, max_tokens=DESIGN_MAX_TOKENS)


def sketch_requires_vision() -> None:
    """Raise unless the model a sketch would route to can actually see it.

    Checked before the call rather than after: a text-only backend handed an
    image part either 400s with the provider's own opaque message, or — worse —
    answers from the place name alone and returns a city that has nothing to do
    with the picture the user drew.
    """
    from gaworld.llm.providers import provider_supports_images

    if not provider_supports_images(task="city_design"):
        raise CityCreationError(
            "当前配置的模型不支持图片输入，无法按草图建城。"
            "请在「配置」面板把 city_design 指向一个多模态模型，或改用文字描述创建。"
        )


def build_knowledge(
    city: CityBundle,
    place: Place,
    *,
    offline: bool = False,
    search_fn: Callable[[str], list[dict[str, str]]] | None = None,
    llm_fn: Callable[[str], str] | None = None,
) -> CityProfile:
    """Research the city, degrading to map statistics then to a bare stub."""
    name = place.name or city.name
    if not offline:
        try:
            researched = build_from_web(
                name, search_fn=search_fn or default_search, llm_fn=llm_fn or default_llm
            )
        except Exception as exc:  # noqa: BLE001 - knowledge must never block creation
            _LOG.warning("city knowledge research failed for %s: %s", name, exc)
            researched = None
        if researched is not None:
            return researched

    counts: dict[str, int] = {}
    if city.real_map_path.exists():
        try:
            counts = map_category_counts(json.loads(city.real_map_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            counts = {}
    return build_from_map(name, counts)


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
    search_fn: Callable[[str], list[dict[str, str]]] | None = None,
    llm_fn: Callable[[str], str] | None = None,
    seed: int | None = None,
    description: str = "",
    images: list[dict[str, str]] | None = None,
    design_llm_fn: Callable[..., str] | None = None,
    locale_llm_fn: Callable[[str], str] | None = None,
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
    description, images
        Either one switches the city to the *imagined* route: the place is not
        looked up at all, and an LLM designs the map, climate and economy from
        what the user supplied.  ``images`` are ``{"media_type", "data"}``
        entries as :func:`gaworld.llm.providers.call_llm` takes them.
        ``offline`` is not consulted on this route — there is no network fetch
        in it to skip, only the model call the description exists to make.
    design_llm_fn
        Injection point for that model call (tests / a pinned model).
    locale_llm_fn
        Injection point for the locale research call (see
        :mod:`gaworld.city.locale`).
    """
    label = str(name or "").strip()
    if not label:
        raise CityCreationError("a place name is required")
    imagined_from = str(description or "").strip()
    is_imagined = bool(imagined_from or images)

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

    map_seed = seed if seed is not None else seed_from_name(city_slug)

    imagined: ImaginedCity | None = None
    if is_imagined:
        if images:
            sketch_requires_vision()
        try:
            imagined = imagine_city(
                label,
                description=imagined_from,
                images=images,
                scale=scale,
                seed=map_seed,
                llm_fn=design_llm_fn or default_design_llm,
            )
        except ImagineError as exc:
            # The name still gets a city out of the procedural generator — but
            # say so rather than handing back something that ignores the
            # description and looks like it honoured it.
            _LOG.warning("could not imagine %s (%s); falling back to the procedural map", label, exc)
            raise CityCreationError(f"{exc}。可改用真实地名创建，或稍后重试。") from exc

    if imagined is not None:
        # Nothing to geocode: the place is invented. The record is synthetic,
        # anchored at the latitude its climate implies so the environment layer
        # gives a described tropical island typhoons rather than Hangzhou drizzle.
        place = offline_place(label, scale=imagined.scale, lat=imagined.latitude)
        place = Place(**{**place.to_dict(), "bbox": place.bbox, "source": "imagined"})
    else:
        place = resolve_place(label, offline=offline, scale=scale, geocode_fn=geocode_fn)

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

    # 1. Virtual map — always written. It doubles as the LLM prompt context
    #    and as the fallback if the real bundle is ever deleted.
    if imagined is not None:
        city.virtual_map_path.write_text(imagined.spec, encoding="utf-8")
        city.manifest["imagined"] = {
            "source": imagined.source,
            "description": imagined_from,
            "summary": imagined.summary,
            "climate": imagined.climate,
        }
        city.record(
            "map.imagined",
            source=imagined.source,
            scale=imagined.scale,
            districts=len(imagined.districts),
        )
    else:
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

    # 3. Environment. An imagined city's own summary goes in as the note: it is
    #    the only place the volcano and the coral reef are written down, and
    #    without it the background prompt would describe a generic tropical town.
    environment = build_environment(
        place, seed=map_seed, note=imagined.summary if imagined else ""
    )
    city.environment_path.write_text(
        json.dumps(environment, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    city.record("environment", climate=environment["climate"])

    # 4. Knowledge base — what the city *is* economically. Best effort, and
    #    never fatal: a city with no industry profile still simulates fine, it
    #    just does not steer its residents' careers. An imagined city already
    #    has one from the design pass; searching the web for a place that does
    #    not exist would at best find nothing and at worst find a real homonym.
    if imagined is not None and imagined.profile is not None and not imagined.profile.is_empty:
        profile = imagined.profile
    else:
        profile = build_knowledge(
            city, place, offline=offline or is_imagined, search_fn=search_fn, llm_fn=llm_fn
        )
    city.knowledge_path.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    city.record(
        "knowledge",
        source=profile.source,
        industries=[i.name for i in profile.top_industries()],
    )

    # 5. Locale — what this city's residents are called, and how their housing
    #    and residency read. Skipped for an invented city, whose prompt would
    #    have no real administrative chain to reason from ("南城街道, 东莞市,
    #    广东省, 中国" is the whole point), and for an offline build, where the
    #    model call is as unavailable as the map fetch. Either way the city
    #    keeps the mainland default until someone runs
    #    ``python -m gaworld.city locale <city> --rebuild``.
    build_locale(city, place, offline=offline or is_imagined, llm_fn=locale_llm_fn)

    city.record("create", offline=offline, source=place.source, imagined=is_imagined)
    city.save()
    _LOG.info("created city %s at %s (map_mode=%s)", city_slug, directory, city.map_mode)
    return city


__all__ = ["CityCreationError", "create_city", "projection_origin", "resolve_place"]
