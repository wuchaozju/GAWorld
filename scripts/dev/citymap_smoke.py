"""Smoke check + sample exports for the enhanced city_map.

Run from repo root:  python3 scripts/dev/citymap_smoke.py
Writes citymap.geojson and citymap_visualization.json next to data/.
"""
import json
import os

from gaworld.world.city_map import (
    build_visualization_payload,
    export_geojson,
    is_open,
    load_city_map,
    occupancy_ratio,
    set_edge_congestion,
    set_node_occupancy,
    travel_plan,
)

cm = load_city_map("citymap.md")
print(f"nodes={len(cm['nodes'])} edges={len(cm['edges'])} "
      f"metro={len(cm['metro_lines'])} bridges={len(cm['bridges'])} "
      f"interiors={len(cm.get('interiors', {}))}")

agent = {"job": "算法工程师"}
plan = travel_plan(agent, cm, "North Block", "Airport District", time_str="08:15")
print("\ntravel_plan North Block -> Airport District @08:15 (rush):")
for k in ("mode", "distance_km", "straight_distance_km", "network_distance_km",
          "travel_minutes", "travel_cost", "road_factor", "congestion", "rush_hour"):
    print(f"  {k:>20} = {plan[k]}")
print(f"  route = {' -> '.join(plan['route'])}")

# congestion effect
route = plan["route"]
for a, b in zip(route, route[1:]):
    set_edge_congestion(cm, a, b, 1.8)
jam = travel_plan(agent, cm, "North Block", "Airport District", time_str="08:15")
print(f"\n  with 1.8x congestion: {plan['travel_minutes']} -> {jam['travel_minutes']} min")

# opening hours + occupancy
print("\nopening hours / occupancy:")
print(f"  Financial District open @03:00? {is_open(cm, 'Financial District', '03:00')}")
print(f"  Financial District open @12:00? {is_open(cm, 'Financial District', '12:00')}")
set_node_occupancy(cm, "Financial District", 450)
print(f"  Financial District occupancy_ratio = {occupancy_ratio(cm, 'Financial District')}")

# exports
gj = export_geojson(cm)
payload = build_visualization_payload(cm)
print(f"\ngeojson features = {len(gj['features'])}")
ov = cm["overlays"]
print(f"overlays zone/density = {ov['width']}x{ov['height']}")
print("\nzone overlay (land-use Voronoi, top rows):")
for row in ov["zone"][:8]:
    print("  " + row)

out_dir = "data"
with open(os.path.join(out_dir, "citymap.geojson"), "w", encoding="utf-8") as f:
    json.dump(gj, f, ensure_ascii=False, indent=2)
with open(os.path.join(out_dir, "citymap_visualization.json"), "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
print("\nwrote data/citymap.geojson and data/citymap_visualization.json")
print("SMOKE_OK")
