"""Refresh a city's real OSM bundle from Overpass.

Re-runs ``gaworld.city.osm.fetch_bundle`` for an existing city bundle and
overwrites its ``map.geojson``.  Use this when:

  - The OSM mirror was down on first fetch and you want to retry.
  - You want to add new categories (new POI selectors added in osm.py).
  - A city's population has grown enough that the existing bundle feels thin.

The script reads the city's bounding box from ``city.json`` so the user does
not have to retype it.

Usage:
  python3 scripts/dev/refresh_city_osm.py wuzhen
  python3 scripts/dev/refresh_city_osm.py wuzhen --dry-run
  python3 scripts/dev/refresh_city_osm.py wuzhen --offline   # skip fetch, just rewrite from local

Overwrites ``data/cities/<slug>/map.geojson`` only when --offline is NOT set.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from gaworld.city.osm import build_feature_collection, fetch_bundle  # noqa: E402
from gaworld.logging_setup import get_logger  # noqa: E402

_LOG = get_logger("gaworld.dev.refresh_city_osm")


def _load_bundle(slug: str) -> dict:
    bundle_path = ROOT / "data" / "cities" / slug / "city.json"
    if not bundle_path.exists():
        raise SystemExit(f"city bundle not found: {bundle_path}")
    return json.loads(bundle_path.read_text(encoding="utf-8"))


def _bundle_path(slug: str) -> Path:
    return ROOT / "data" / "cities" / slug / "map.geojson"


def refresh(slug: str, *, dry_run: bool = False) -> Path:
    bundle = _load_bundle(slug)
    place = bundle.get("place") or {}
    bbox = place.get("bbox")
    if not bbox:
        raise SystemExit(f"{slug} has no bbox in city.json — nothing to refresh")
    name = bundle.get("display_name") or bundle.get("name") or slug
    origin = (bundle.get("map") or {}).get("origin") or {
        "lat": place["lat"], "lng": place["lng"],
        "lat_per_km": 1.0 / 111.0, "lng_per_km": 1.0 / 96.0,
    }
    _LOG.info("refreshing %s (%s) bbox=%s", slug, name, bbox)
    nodes, metro, river = fetch_bundle(
        tuple(bbox), city=name, origin=origin,
    )
    geojson = build_feature_collection(
        nodes, metro, river, city=name, origin=origin,
    )
    geojson["meta"]["refreshed_at"] = (
        __import__("datetime").datetime.utcnow().isoformat() + "Z"
    )
    out = _bundle_path(slug)
    if dry_run:
        _LOG.info("DRY RUN — would write %d nodes / %d metro / river=%s to %s",
                  len(nodes), len(metro), river and river.get("name"), out)
        return out
    out.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")
    _LOG.info("wrote %d nodes / %d metro lines / river=%s → %s",
              len(nodes), len(metro), river and river.get("name"), out)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Refresh a city's OSM-derived map.geojson")
    p.add_argument("slug", help="city slug under data/cities/")
    p.add_argument("--dry-run", action="store_true", help="fetch but don't write")
    args = p.parse_args()
    refresh(args.slug, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())