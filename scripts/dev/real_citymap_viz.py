#!/usr/bin/env python3
"""Regenerate the CityMap viewer data from the real (OSM) Hangzhou map.

Mirrors scripts/dev/citymap_smoke.py but loads the real-map bundle, so the
Phaser viewer at site/citymap/ can render true Hangzhou geography.

    python3 scripts/dev/real_citymap_viz.py
    python3 scripts/dev/real_citymap_viz.py --bundle data/hangzhou_real.geojson
"""

import argparse
import json
import os
import sys

# Make the package importable when run as a plain script from anywhere.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from gaworld.world.city_map import (
    build_visualization_payload,
    export_geojson,
    load_real_city_map,
    real_city_map_text,
)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", default="data/hangzhou_real.geojson")
    ap.add_argument("--out-dir", default="data")
    args = ap.parse_args()

    cm = load_real_city_map(args.bundle)
    print(f"nodes={len(cm['nodes'])} edges={len(cm['edges'])} "
          f"metro={len(cm['metro_lines'])} bridges={len(cm['bridges'])}")
    print("\n" + real_city_map_text(cm))

    gj = export_geojson(cm)
    payload = build_visualization_payload(cm)
    os.makedirs(args.out_dir, exist_ok=True)
    # Distinct filenames so the virtual map's committed exports are left intact.
    geo_out = os.path.join(args.out_dir, "citymap_real.geojson")
    viz_out = os.path.join(args.out_dir, "citymap_real_visualization.json")
    with open(geo_out, "w", encoding="utf-8") as f:
        json.dump(gj, f, ensure_ascii=False, indent=2)
    with open(viz_out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\nwrote {geo_out} and {viz_out}")


if __name__ == "__main__":
    main()
