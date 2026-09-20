#!/usr/bin/env python3
"""Fetch a real Hangzhou map bundle from OpenStreetMap (Overpass API).

Builds the *offline* bundle consumed by ``map_mode="real"`` — a GeoJSON
``FeatureCollection`` (same schema as ``city_map.export_geojson`` plus a few
extra properties) that ``gaworld.world.city_map.load_real_city_map`` turns into
a full ``city_map``.  Run it once with network access; commit the output for
reproducible, offline simulation runs.

    python3 scripts/dev/fetch_hangzhou_osm.py            # → data/hangzhou_real.geojson
    python3 scripts/dev/fetch_hangzhou_osm.py -o out.geojson --bbox 30.14,119.98,30.40,120.35

The bundle is deliberately COARSE (a few hundred landmark nodes, not every
building) to match the simulation's abstraction level: named districts, transit
stations, and category anchors that agents route between.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Rotate across public mirrors to survive rate-limiting (429) / timeouts (504).
OVERPASS_URLS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
USER_AGENT = "GAWorld-sim/1.0 (research; https://github.com/wuchaozju/GAWorld)"

# Hangzhou urban core: (south, west, north, east).
DEFAULT_BBOX = (30.14, 119.98, 30.40, 120.35)

# category → (overpass selectors, kind, per-category cap).
# Each selector runs for both nodes and ways (way centroids via `out center`).
CATEGORY_QUERIES = {
    "residential": (['node["place"~"suburb|neighbourhood|quarter|town"]'], "hub", 55),
    # Mainline rail only here; subway stations are fetched in full (uncapped) by
    # fetch_subway_stations so every reconstructed metro stop exists as a node.
    "transit":     (['node["railway"="station"]["station"!~"subway"]'], "hub", 20),
    "education":   (['node["amenity"~"university|college"]',
                     'way["amenity"~"university|college"]'], "place", 22),
    "medical":     (['node["amenity"="hospital"]', 'way["amenity"="hospital"]'], "place", 22),
    "commerce":    (['node["shop"="mall"]', 'way["shop"="mall"]',
                     'node["amenity"="marketplace"]'], "place", 30),
    "leisure":     (['way["leisure"="park"]["name"]',
                     'node["tourism"="attraction"]["name"]'], "place", 26),
    "government":  (['node["office"="government"]', 'node["amenity"="townhall"]',
                     'way["amenity"="townhall"]'], "place", 12),
}

# Rail/airport hubs get promoted to arterial-backbone anchors (kind=hub).
HUB_NAME_HINTS = ("站", "机场", "东站", "城站", "南站", "西站", "火车")


def overpass(query, retries=4, timeout=180):
    """POST an Overpass QL query, returning parsed JSON.

    Rotates across mirror endpoints and backs off on transient errors (429 rate
    limit / 504 gateway timeout are common on the public instances)."""
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last_err = None
    for attempt in range(retries):
        url = OVERPASS_URLS[attempt % len(OVERPASS_URLS)]
        try:
            req = urllib.request.Request(
                url, data=data, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            # A rate-limited/overloaded mirror can return HTTP 200 with an empty
            # body and a "remark" instead of an error — treat that as retryable.
            if payload.get("remark") and not payload.get("elements"):
                raise ValueError(f"overpass remark: {payload['remark'].strip()}")
            return payload
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                json.JSONDecodeError, ValueError) as exc:
            last_err = exc
            wait = 8 * (attempt + 1)
            print(f"  ! overpass error ({exc}) via {url}; retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"Overpass failed after {retries} attempts: {last_err}")


def _bbox_clause(bbox):
    return f"({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]})"


def _element_lnglat(el):
    if el.get("type") == "node":
        return el.get("lon"), el.get("lat")
    center = el.get("center") or {}
    return center.get("lon"), center.get("lat")


def _name(el):
    tags = el.get("tags") or {}
    return (tags.get("name:zh") or tags.get("name") or tags.get("name:en") or "").strip()


def fetch_category(category, selectors, kind, cap, bbox):
    """Return a de-duplicated (by name) list of node dicts for one category."""
    bb = _bbox_clause(bbox)
    body = "".join(f"{sel}{bb};" for sel in selectors)
    query = f"[out:json][timeout:120];({body});out center tags;"
    result = overpass(query)
    seen, nodes = set(), []
    for el in result.get("elements", []):
        name = _name(el)
        lng, lat = _element_lnglat(el)
        if not name or lng is None or lat is None or name in seen:
            continue
        seen.add(name)
        node_kind = kind
        if category == "transit" and any(h in name for h in HUB_NAME_HINTS):
            node_kind = "hub"   # rail/airport stations anchor the backbone
        nodes.append({
            "name": name, "lng": float(lng), "lat": float(lat),
            "category": category, "kind": node_kind,
        })
        if len(nodes) >= cap:
            break
    print(f"  · {category}: {len(nodes)}")
    return nodes


def fetch_subway_stations(bbox):
    """All subway station nodes (uncapped), so no metro stop is ever missing."""
    bb = _bbox_clause(bbox)
    query = f"[out:json][timeout:120];node[\"station\"=\"subway\"]{bb};out;"
    result = overpass(query)
    seen, out = set(), []
    for el in result.get("elements", []):
        name = _name(el)
        lng, lat = _element_lnglat(el)
        if not name or lng is None or name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "lng": float(lng), "lat": float(lat),
                    "category": "transit", "kind": "place"})
    print(f"  · subway stations: {len(out)}")
    return out


def _clean_line_name(tags, fallback):
    """'1号线：湘湖 -> 萧山国际机场' → '1号线'; keeps a stable per-line key.

    Prefers the descriptive Chinese name (direction stripped) over a bare ``ref``
    number so lines read as '1号线' rather than '1'."""
    raw = (tags.get("name:zh") or tags.get("name") or "").strip()
    for sep in ("：", ":", "→", "->"):
        if sep in raw:
            raw = raw.split(sep, 1)[0].strip()
            break
    if not raw:
        ref = (tags.get("ref:zh") or tags.get("ref") or "").strip()
        raw = f"{ref}号线" if ref.isdigit() else ref
    return raw or fallback


def fetch_metro_lines(bbox, stations):
    """Ordered metro lines from subway route relations.

    Each relation's ordered stop members are snapped (by coordinate) to the
    nearest real station, giving a clean stop sequence.  The two directions of
    a line are merged, keeping the longest.  Non-fatal on failure — metro only
    enriches transport-mode choice."""
    bb = _bbox_clause(bbox)
    # `out geom` (NOT `out tags geom` — the `tags` modifier suppresses members)
    # returns the relation's tags plus its ordered member nodes with coords.
    query = f"[out:json][timeout:180];relation[\"route\"=\"subway\"]{bb};out geom;"
    try:
        result = overpass(query)
    except RuntimeError as exc:
        print(f"  ! metro fetch failed: {exc}", file=sys.stderr)
        return []
    coords = [(n["name"], n["lng"], n["lat"]) for n in stations]

    def nearest(lng, lat):
        if lng is None or lat is None:
            return None
        best, bd = None, float("inf")
        for nm, nlng, nlat in coords:
            d = (nlng - lng) ** 2 + (nlat - lat) ** 2
            if d < bd:
                bd, best = d, nm
        return best if bd < 1.3e-5 else None   # ~400m tolerance (deg^2)

    lines = []
    for i, rel in enumerate(result.get("elements", [])):
        tags = rel.get("tags") or {}
        name = _clean_line_name(tags, f"M{i + 1}")
        color = tags.get("colour") or "#8f5bd8"
        stops = []
        for m in rel.get("members", []):
            if m.get("type") != "node":
                continue
            role = m.get("role") or ""
            if "stop" not in role and "platform" not in role:
                continue
            nm = nearest(m.get("lon"), m.get("lat"))
            if nm and (not stops or stops[-1] != nm):
                stops.append(nm)
        if len(stops) >= 2:
            lines.append({"name": name, "color": color, "stops": stops})
    # Merge the two directions of each line, keeping the longer sequence.
    merged = {}
    for ln in lines:
        cur = merged.get(ln["name"])
        if not cur or len(ln["stops"]) > len(cur["stops"]):
            merged[ln["name"]] = ln
    out = sorted(merged.values(), key=lambda l: l["name"])
    print(f"  · metro lines: {len(out)} ({', '.join(l['name'] for l in out)})")
    return out


def fetch_river(bbox):
    """Fetch the Qiantang river as a simplified (lng, lat) polyline."""
    bb = _bbox_clause(bbox)
    query = (f"[out:json][timeout:120];way[\"waterway\"=\"river\"][\"name\"~\"钱塘\"]{bb};"
             "out geom;")
    try:
        result = overpass(query)
    except RuntimeError as exc:
        print(f"  ! river fetch failed: {exc}", file=sys.stderr)
        return None
    pts = []
    for way in result.get("elements", []):
        for g in way.get("geometry", []) or []:
            pts.append((g["lon"], g["lat"]))
    if len(pts) < 2:
        return None
    # Simplify: keep ~24 evenly-spaced points, sorted west→east.
    pts.sort(key=lambda p: p[0])
    step = max(1, len(pts) // 24)
    simplified = pts[::step]
    print(f"  · river points: {len(simplified)}")
    return {"name": "钱塘江", "lnglat": simplified, "width_km": 1.1}


def build_feature_collection(nodes, metro_lines, river):
    features = []
    for n in nodes:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [n["lng"], n["lat"]]},
            "properties": {"name": n["name"], "category": n["category"], "kind": n["kind"]},
        })
    for ln in metro_lines:
        # Stop coords let the viewer draw the line even without node lookup.
        by_name = {n["name"]: n for n in nodes}
        coords = [[by_name[s]["lng"], by_name[s]["lat"]] for s in ln["stops"] if s in by_name]
        if len(coords) < 2:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"kind": "metro", "line": ln["name"], "color": ln["color"],
                           "stops": ln["stops"]},
        })
    if river:
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[lng, lat] for lng, lat in river["lnglat"]]},
            "properties": {"kind": "river", "name": river["name"], "width_km": river["width_km"]},
        })
    return {"type": "FeatureCollection",
            "meta": {"city": "Hangzhou", "source": "OpenStreetMap"},
            "features": features}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default="data/hangzhou_real.geojson")
    ap.add_argument("--bbox", default=None,
                    help="south,west,north,east (default Hangzhou urban core)")
    args = ap.parse_args()
    bbox = tuple(float(x) for x in args.bbox.split(",")) if args.bbox else DEFAULT_BBOX

    print(f"Fetching Hangzhou OSM data for bbox {bbox} …")
    all_nodes, seen_names = [], set()
    for category, (selectors, kind, cap) in CATEGORY_QUERIES.items():
        try:
            cat_nodes = fetch_category(category, selectors, kind, cap, bbox)
        except RuntimeError as exc:
            print(f"  ! {category} skipped: {exc}", file=sys.stderr)
            cat_nodes = []
        for n in cat_nodes:
            if n["name"] in seen_names:
                continue
            seen_names.add(n["name"])
            all_nodes.append(n)
        time.sleep(3)  # be polite to the public mirrors

    # Full subway station set (uncapped) — added as nodes AND used to snap the
    # metro line stop sequences, so every reconstructed stop resolves to a node.
    try:
        subway = fetch_subway_stations(bbox)
    except RuntimeError as exc:
        print(f"  ! subway stations skipped: {exc}", file=sys.stderr)
        subway = []
    for n in subway:
        if n["name"] in seen_names:
            continue
        seen_names.add(n["name"])
        all_nodes.append(n)
    time.sleep(3)

    metro_lines = fetch_metro_lines(bbox, subway or
                                    [n for n in all_nodes if n["category"] == "transit"])
    river = fetch_river(bbox)

    fc = build_feature_collection(all_nodes, metro_lines, river)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, indent=1)
    hubs = sum(1 for n in all_nodes if n["kind"] == "hub")
    print(f"\n✓ wrote {args.output}: {len(all_nodes)} nodes ({hubs} hubs), "
          f"{len(metro_lines)} metro lines, river={'yes' if river else 'no'}")


if __name__ == "__main__":
    main()
