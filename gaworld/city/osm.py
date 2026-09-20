"""Fetch a real map bundle for an arbitrary bounding box from OpenStreetMap.

The place-agnostic generalisation of ``scripts/dev/fetch_hangzhou_osm.py``:
same Overpass queries and same output schema (a GeoJSON ``FeatureCollection``
that :func:`gaworld.world.city_map.load_real_city_map` consumes), but the bbox,
the city name and the river all come from the caller instead of being hardcoded
to Hangzhou.

Bundles are deliberately COARSE — a few hundred landmark nodes, not every
building — to match the simulation's abstraction level: named districts,
transit stations and category anchors that agents route between.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Callable

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.city.osm")

# Rotate across public mirrors to survive rate-limiting (429) / timeouts (504).
# Ordered by observed reliability, NOT arbitrarily: the main instance is the one
# that actually answers from most networks, while the other two frequently hang
# until the socket timeout rather than refusing fast. A dead mirror in front
# costs DEFAULT_TIMEOUT on the very first query of every fetch, before
# ``_preferred_mirror`` has anything to stick to — which is the difference
# between a city in ~40s and one in ~4min that then falls back to procedural.
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
USER_AGENT = "GAWorld-sim/1.0 (research; https://github.com/wuchaozju/GAWorld)"

#: Socket timeout for one Overpass request. The server-side budget is declared
#: inside each query ("[out:json][timeout:120]"); this is the *client* giving up
#: on an unresponsive mirror, and it has to be short because a bundle needs ~9
#: queries and a firewalled mirror otherwise burns the full timeout on each one.
DEFAULT_TIMEOUT = 45

#: Wall-clock budget for a whole ``fetch_bundle``. Past this the fetch stops and
#: the caller falls back to a procedural map: "create a city" is interactive, and
#: waiting 20 minutes for a map is worse than getting a generated one.
DEFAULT_DEADLINE = 240.0

#: Last mirror that answered successfully. The public mirrors are frequently
#: blocked or overloaded one-at-a-time, so once one works we keep using it
#: instead of re-discovering the dead ones on every subsequent query.
_preferred_mirror: str | None = None

# category → (overpass selectors, kind, per-category cap).
# Each selector runs for both nodes and ways (way centroids via `out center`).
CATEGORY_QUERIES: dict[str, tuple[list[str], str, int]] = {
    "residential": (['node["place"~"suburb|neighbourhood|quarter|town|village|hamlet"]'], "hub", 55),
    # Mainline rail only here; subway stations are fetched in full (uncapped) by
    # fetch_subway_stations so every reconstructed metro stop exists as a node.
    "transit": (['node["railway"="station"]["station"!~"subway"]'], "hub", 20),
    "education": (
        ['node["amenity"~"university|college|school"]', 'way["amenity"~"university|college"]'],
        "place",
        22,
    ),
    "medical": (['node["amenity"="hospital"]', 'way["amenity"="hospital"]'], "place", 22),
    "commerce": (
        ['node["shop"="mall"]', 'way["shop"="mall"]', 'node["amenity"="marketplace"]'],
        "place",
        30,
    ),
    "leisure": (['way["leisure"="park"]["name"]', 'node["tourism"="attraction"]["name"]'], "place", 26),
    "government": (
        ['node["office"="government"]', 'node["amenity"="townhall"]', 'way["amenity"="townhall"]'],
        "place",
        12,
    ),
}

#: Name fragments that promote a transit node to an arterial-backbone anchor.
HUB_NAME_HINTS = ("站", "机场", "火车", "Station", "Airport", "Terminal", "Hbf", "Gare")

#: Below this many nodes a bundle is too thin to build a believable city from,
#: and the caller should fall back to a procedural map.
MIN_USABLE_NODES = 8


class OSMError(RuntimeError):
    """Raised when Overpass could not be reached or returned nothing usable."""


def _mirror_order() -> list[str]:
    """Mirrors to try, known-good one first."""
    if _preferred_mirror and _preferred_mirror in OVERPASS_URLS:
        return [_preferred_mirror] + [u for u in OVERPASS_URLS if u != _preferred_mirror]
    return list(OVERPASS_URLS)


def _request_once(url: str, data: bytes, timeout: int) -> dict[str, Any]:
    """One Overpass request, bounded by *timeout* in **wall-clock** seconds.

    ``urlopen``'s own timeout applies per socket operation, so a mirror that
    trickles the body back keeps resetting it and a single ``read()`` can run
    for many minutes — we have measured 13 against a nominal 45s. Running the
    request on a worker thread and refusing to wait past the budget is what
    actually bounds it. The abandoned thread is a daemon and its socket still
    carries the same timeout, so it dies on its own shortly after.
    """
    result: dict[str, Any] = {}

    def work() -> None:
        request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result["payload"] = json.loads(response.read().decode("utf-8"))

    # Deliberately NOT a `with` block: ThreadPoolExecutor.__exit__ calls
    # shutdown(wait=True), which would block on the very thread we are trying to
    # walk away from and reinstate the unbounded wait this function exists to
    # prevent.
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="overpass")
    future = pool.submit(work)
    try:
        future.result(timeout=timeout)
    except FuturesTimeout as exc:
        raise TimeoutError(f"no response within {timeout}s") from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return result.get("payload", {})


def _default_overpass(query: str, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    global _preferred_mirror

    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last_err: Exception | None = None
    mirrors = _mirror_order()
    # A timeout already shrunk to the caller's remaining budget means there is
    # no time for a second and third mirror; try only the best one.
    if timeout <= 10:
        mirrors = mirrors[:1]
    for index, url in enumerate(mirrors):
        try:
            payload = _request_once(url, data, timeout)
            # A rate-limited/overloaded mirror can return HTTP 200 with an empty
            # body and a "remark" instead of an error — treat that as retryable.
            if payload.get("remark") and not payload.get("elements"):
                raise ValueError(f"overpass remark: {payload['remark'].strip()}")
            _preferred_mirror = url
            return payload
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            OSError,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            last_err = exc
            if url == _preferred_mirror:
                _preferred_mirror = None  # it stopped working; re-discover
            _LOG.warning("overpass error via %s: %s", url, exc)
            # Back off only *between* mirrors, and only briefly: a bundle needs
            # ~9 queries, so a long sleep here is multiplied nine-fold.
            if index < len(mirrors) - 1:
                time.sleep(2)
    raise OSMError(f"Overpass failed on all {len(mirrors)} mirrors: {last_err}")


def _bbox_clause(bbox: tuple[float, float, float, float]) -> str:
    return f"({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]})"


def _element_lnglat(element: dict[str, Any]) -> tuple[Any, Any]:
    if element.get("type") == "node":
        return element.get("lon"), element.get("lat")
    center = element.get("center") or {}
    return center.get("lon"), center.get("lat")


def _name(element: dict[str, Any]) -> str:
    tags = element.get("tags") or {}
    return (tags.get("name:zh") or tags.get("name") or tags.get("name:en") or "").strip()


def fetch_category(
    category: str,
    selectors: list[str],
    kind: str,
    cap: int,
    bbox: tuple[float, float, float, float],
    overpass: Callable[[str, int], dict[str, Any]],
    timeout: int = 180,
) -> list[dict[str, Any]]:
    """De-duplicated (by name) node dicts for one category."""
    clause = _bbox_clause(bbox)
    body = "".join(f"{selector}{clause};" for selector in selectors)
    query = f"[out:json][timeout:120];({body});out center tags;"
    result = overpass(query, timeout)
    seen: set[str] = set()
    nodes: list[dict[str, Any]] = []
    for element in result.get("elements", []):
        name = _name(element)
        lng, lat = _element_lnglat(element)
        if not name or lng is None or lat is None or name in seen:
            continue
        seen.add(name)
        node_kind = kind
        if category == "transit" and any(hint in name for hint in HUB_NAME_HINTS):
            node_kind = "hub"  # rail/airport stations anchor the backbone
        nodes.append(
            {"name": name, "lng": float(lng), "lat": float(lat), "category": category, "kind": node_kind}
        )
        if len(nodes) >= cap:
            break
    return nodes


def fetch_subway_stations(
    bbox: tuple[float, float, float, float],
    overpass: Callable[[str, int], dict[str, Any]],
    timeout: int = 180,
) -> list[dict[str, Any]]:
    """All subway station nodes (uncapped), so no metro stop is ever missing."""
    query = f'[out:json][timeout:120];node["station"="subway"]{_bbox_clause(bbox)};out;'
    result = overpass(query, timeout)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for element in result.get("elements", []):
        name = _name(element)
        lng, lat = _element_lnglat(element)
        if not name or lng is None or name in seen:
            continue
        seen.add(name)
        out.append(
            {"name": name, "lng": float(lng), "lat": float(lat), "category": "transit", "kind": "place"}
        )
    return out


def _clean_line_name(tags: dict[str, Any], fallback: str) -> str:
    """'1号线：湘湖 -> 萧山国际机场' → '1号线'; keeps a stable per-line key."""
    raw = (tags.get("name:zh") or tags.get("name") or "").strip()
    for separator in ("：", ":", "→", "->"):
        if separator in raw:
            raw = raw.split(separator, 1)[0].strip()
            break
    if not raw:
        ref = (tags.get("ref:zh") or tags.get("ref") or "").strip()
        raw = f"{ref}号线" if ref.isdigit() else ref
    return raw or fallback


def fetch_metro_lines(
    bbox: tuple[float, float, float, float],
    stations: list[dict[str, Any]],
    overpass: Callable[[str, int], dict[str, Any]],
    timeout: int = 180,
) -> list[dict[str, Any]]:
    """Ordered metro lines from subway route relations.

    Non-fatal on failure — metro only enriches transport-mode choice, so a city
    without one is still perfectly playable.
    """
    # `out geom` (NOT `out tags geom` — the `tags` modifier suppresses members)
    # returns the relation's tags plus its ordered member nodes with coords.
    query = f'[out:json][timeout:180];relation["route"="subway"]{_bbox_clause(bbox)};out geom;'
    try:
        result = overpass(query, timeout)
    except (OSMError, RuntimeError) as exc:
        _LOG.warning("metro fetch failed: %s", exc)
        return []
    coords = [(n["name"], n["lng"], n["lat"]) for n in stations]

    def nearest(lng: Any, lat: Any) -> str | None:
        if lng is None or lat is None:
            return None
        best, best_dist = None, float("inf")
        for name, node_lng, node_lat in coords:
            dist = (node_lng - lng) ** 2 + (node_lat - lat) ** 2
            if dist < best_dist:
                best_dist, best = dist, name
        return best if best_dist < 1.3e-5 else None  # ~400m tolerance (deg^2)

    lines = []
    for index, relation in enumerate(result.get("elements", [])):
        tags = relation.get("tags") or {}
        name = _clean_line_name(tags, f"M{index + 1}")
        color = tags.get("colour") or "#8f5bd8"
        stops: list[str] = []
        for member in relation.get("members", []):
            if member.get("type") != "node":
                continue
            role = member.get("role") or ""
            if "stop" not in role and "platform" not in role:
                continue
            matched = nearest(member.get("lon"), member.get("lat"))
            if matched and (not stops or stops[-1] != matched):
                stops.append(matched)
        if len(stops) >= 2:
            lines.append({"name": name, "color": color, "stops": stops})
    # Merge the two directions of each line, keeping the longer sequence.
    merged: dict[str, dict[str, Any]] = {}
    for line in lines:
        current = merged.get(line["name"])
        if not current or len(line["stops"]) > len(current["stops"]):
            merged[line["name"]] = line
    return sorted(merged.values(), key=lambda line: line["name"])


def fetch_river(
    bbox: tuple[float, float, float, float],
    overpass: Callable[[str, int], dict[str, Any]],
    timeout: int = 180,
) -> dict[str, Any] | None:
    """The most prominent named river in the bbox, as a simplified polyline.

    Unlike the Hangzhou script this does not filter by river name — it takes
    whichever named waterway contributes the most geometry, which is the right
    heuristic for an arbitrary place.
    """
    query = f'[out:json][timeout:120];way["waterway"="river"]["name"]{_bbox_clause(bbox)};out geom;'
    try:
        result = overpass(query, timeout)
    except (OSMError, RuntimeError) as exc:
        _LOG.warning("river fetch failed: %s", exc)
        return None

    # Group segments by river name; the winner is the one with most points.
    by_name: dict[str, list[tuple[float, float]]] = {}
    for way in result.get("elements", []):
        tags = way.get("tags") or {}
        name = (tags.get("name:zh") or tags.get("name") or "").strip()
        if not name:
            continue
        points = by_name.setdefault(name, [])
        for geometry in way.get("geometry") or []:
            points.append((geometry["lon"], geometry["lat"]))
    if not by_name:
        return None
    name, points = max(by_name.items(), key=lambda item: len(item[1]))
    if len(points) < 2:
        return None
    # Simplify: keep ~24 evenly-spaced points, sorted west→east.
    points.sort(key=lambda point: point[0])
    step = max(1, len(points) // 24)
    return {"name": name, "lnglat": points[::step], "width_km": 0.8}


def build_feature_collection(
    nodes: list[dict[str, Any]],
    metro_lines: list[dict[str, Any]],
    river: dict[str, Any] | None,
    *,
    city: str,
    origin: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Assemble the GeoJSON bundle ``load_real_city_map`` reads.

    ``meta.origin`` carries the city's own projection anchor so the map layer
    can convert lat/lng to kilometres correctly at this latitude instead of
    reusing the simulator's historical Hangzhou constants.
    """
    features: list[dict[str, Any]] = []
    for node in nodes:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [node["lng"], node["lat"]]},
                "properties": {
                    "name": node["name"],
                    "category": node["category"],
                    "kind": node["kind"],
                },
            }
        )
    by_name = {node["name"]: node for node in nodes}
    for line in metro_lines:
        # Stop coords let the viewer draw the line even without node lookup.
        coords = [[by_name[s]["lng"], by_name[s]["lat"]] for s in line["stops"] if s in by_name]
        if len(coords) < 2:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "kind": "metro",
                    "line": line["name"],
                    "color": line["color"],
                    "stops": line["stops"],
                },
            }
        )
    if river:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lng, lat] for lng, lat in river["lnglat"]],
                },
                "properties": {
                    "kind": "river",
                    "name": river["name"],
                    "width_km": river["width_km"],
                },
            }
        )
    meta: dict[str, Any] = {"city": city, "source": "OpenStreetMap"}
    if origin:
        meta["origin"] = origin
    return {"type": "FeatureCollection", "meta": meta, "features": features}


def fetch_bundle(
    bbox: tuple[float, float, float, float],
    *,
    city: str,
    origin: dict[str, float] | None = None,
    overpass: Callable[[str, int], dict[str, Any]] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    pause: float | None = None,
    deadline: float | None = DEFAULT_DEADLINE,
) -> dict[str, Any]:
    """Fetch every layer for *bbox* and return the GeoJSON bundle.

    *overpass* is an injection point for tests and custom mirrors: a callable
    ``(query, timeout)`` returning parsed Overpass JSON.

    *pause* seconds are slept between category queries to stay polite to the
    public mirrors.  It defaults to 3s for the built-in client and to 0 for an
    injected one — the delay exists for those shared endpoints, and a caller
    supplying its own client owns its own rate-limiting.

    *deadline* bounds the whole fetch in wall-clock seconds; once it passes, the
    remaining optional layers are skipped so the caller gets *something* rather
    than an unbounded wait.  Pass ``None`` to disable.

    Raises :class:`OSMError` when the result is too thin to build a city from,
    so the caller can fall back to a procedural map.
    """
    base_client = overpass or _default_overpass
    if pause is None:
        pause = 0.0 if overpass is not None else 3.0
    started = time.monotonic()

    def out_of_time() -> bool:
        return deadline is not None and (time.monotonic() - started) > deadline

    def remaining() -> float:
        return float("inf") if deadline is None else deadline - (time.monotonic() - started)

    def client(query: str, request_timeout: int) -> dict[str, Any]:
        """Shrink each request's timeout to what is left of the budget.

        ``urlopen``'s timeout is per socket operation, so a mirror that trickles
        bytes can run far past it; capping the timeout by the remaining budget
        is what actually keeps the total bounded.
        """
        left = remaining()
        if left <= 0:
            raise OSMError("fetch deadline exceeded")
        return base_client(query, int(max(5, min(request_timeout, left))))

    all_nodes: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for category, (selectors, kind, cap) in CATEGORY_QUERIES.items():
        if out_of_time():
            _LOG.warning("deadline reached; skipping remaining categories from %r", category)
            break
        try:
            category_nodes = fetch_category(category, selectors, kind, cap, bbox, client, timeout)
        except (OSMError, RuntimeError) as exc:
            _LOG.warning("%s skipped: %s", category, exc)
            category_nodes = []
        for node in category_nodes:
            if node["name"] in seen_names:
                continue
            seen_names.add(node["name"])
            all_nodes.append(node)
        _LOG.info("  · %s: %d", category, len(category_nodes))
        if pause:
            time.sleep(pause)

    subway: list[dict[str, Any]] = []
    if not out_of_time():
        try:
            subway = fetch_subway_stations(bbox, client, timeout)
        except (OSMError, RuntimeError) as exc:
            _LOG.warning("subway stations skipped: %s", exc)
        for node in subway:
            if node["name"] in seen_names:
                continue
            seen_names.add(node["name"])
            all_nodes.append(node)
        if pause:
            time.sleep(pause)

    if len(all_nodes) < MIN_USABLE_NODES:
        raise OSMError(
            f"only {len(all_nodes)} usable OSM nodes in bbox {bbox} "
            f"(need {MIN_USABLE_NODES}) — too sparse for a real map"
        )

    # Metro and river only enrich the map, so they are the first things dropped
    # when the budget is gone.
    metro_lines: list[dict[str, Any]] = []
    river: dict[str, Any] | None = None
    if not out_of_time():
        metro_lines = fetch_metro_lines(
            bbox, subway or [n for n in all_nodes if n["category"] == "transit"], client, timeout
        )
    if not out_of_time():
        river = fetch_river(bbox, client, timeout)

    _LOG.info(
        "fetched %d nodes (%d hubs), %d metro lines, river=%s",
        len(all_nodes),
        sum(1 for n in all_nodes if n["kind"] == "hub"),
        len(metro_lines),
        "yes" if river else "no",
    )
    return build_feature_collection(all_nodes, metro_lines, river, city=city, origin=origin)


__all__ = [
    "CATEGORY_QUERIES",
    "MIN_USABLE_NODES",
    "OSMError",
    "build_feature_collection",
    "fetch_bundle",
    "fetch_category",
    "fetch_metro_lines",
    "fetch_river",
    "fetch_subway_stations",
]
