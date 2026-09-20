import os
import tempfile
import unittest

from gaworld.world.city_map import (
    TERRAIN_LEGEND,
    build_visualization_payload,
    deserialize_city_map,
    distance_between,
    export_geojson,
    is_open,
    load_city_map,
    nearest_by_category,
    occupancy_ratio,
    path_distance_km,
    serialize_city_map,
    set_edge_congestion,
    set_node_occupancy,
    shortest_path,
    shortest_path_with_distance,
    travel_plan,
)
from scripts.generate_citymap import generate_citymap


class TestCityMapSystem(unittest.TestCase):
    def test_city_map_has_coordinates_edges_and_overlays(self):
        city_map = load_city_map("citymap.md")
        self.assertIn("nodes", city_map)
        self.assertIn("edges", city_map)
        self.assertIn("metro_lines", city_map)
        self.assertIn("river", city_map)
        self.assertGreater(len(city_map["nodes"]), 10)
        self.assertGreater(len(city_map["edges"]), 10)
        self.assertGreaterEqual(len(city_map["metro_lines"]), 1)
        central = city_map["nodes"]["Central Block"]
        self.assertIn("lat", central)
        self.assertIn("lng", central)

    def test_travel_plan_returns_distance_mode_and_route(self):
        city_map = load_city_map("citymap.md")
        agent = {"job": "算法工程师", "daily_life": "平时通勤上班"}
        plan = travel_plan(agent, city_map, "Central Block", "Hangzhou Tech Labs", activity="通勤上班")
        self.assertGreater(plan["distance_km"], 0.1)
        self.assertIn(plan["mode"], {"walk", "bike", "e-bike", "bus", "metro", "car", "taxi"})
        self.assertGreaterEqual(plan["travel_minutes"], 1)
        self.assertGreaterEqual(len(plan["route"]), 2)
        self.assertGreater(distance_between(city_map, "Central Block", "Hangzhou Tech Labs"), 0.1)
        self.assertGreaterEqual(len(shortest_path(city_map, "Central Block", "Hangzhou Tech Labs")), 2)

    def test_explicit_directives_are_parsed(self):
        content = """# City Map\n@river: Demo River | path=0.1,0.2;0.5,0.2;0.9,0.4 | width=0.05\n@node: Alpha Hub | kind=hub | category=commerce | x=3.0 | y=4.0\n@node: Beta Hub | kind=hub | category=transit | x=7.0 | y=4.0\n@road: Alpha Hub -> Beta Hub | type=arterial | bridge=true\n@metro: M9 | color=#ff5500 | stops=Alpha Hub>Beta Hub\n\n- City: Demo\n  - Hub: Alpha Hub\n    - Nearby: A Street\n  - Hub: Beta Hub\n    - Nearby: B Street\n"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "demo.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            city_map = load_city_map(path)
        self.assertEqual("commerce", city_map["nodes"]["Alpha Hub"]["category"])
        self.assertEqual("#ff5500", city_map["metro_lines"][0]["color"])
        self.assertTrue(any(edge.get("bridge") for edge in city_map["edges"]))

    def test_generator_outputs_new_directives(self):
        generated = generate_citymap("a medium city in east china", seed=7)
        self.assertIn("@river:", generated)
        self.assertIn("@node:", generated)
        self.assertIn("@road:", generated)

    # ------------------------------------------------------------------
    # Realistic routing
    # ------------------------------------------------------------------
    def test_travel_plan_uses_network_distance(self):
        city_map = load_city_map("citymap.md")
        agent = {"job": "算法工程师"}
        plan = travel_plan(agent, city_map, "North Block", "Airport District")
        # Network distance must be >= straight-line (triangle inequality) and
        # the reported distance_km is the network distance.
        self.assertGreaterEqual(
            plan["network_distance_km"] + 1e-6, plan["straight_distance_km"]
        )
        self.assertAlmostEqual(plan["distance_km"], plan["network_distance_km"], places=3)

    def test_route_and_distance_are_consistent(self):
        city_map = load_city_map("citymap.md")
        route, dist = shortest_path_with_distance(
            city_map, "North Block", "Airport District"
        )
        self.assertGreaterEqual(len(route), 2)
        self.assertEqual(route, shortest_path(city_map, "North Block", "Airport District"))
        # The summed road length of the route equals the Dijkstra distance.
        self.assertAlmostEqual(path_distance_km(city_map, route), dist, places=2)

    def test_congestion_increases_travel_time(self):
        city_map = load_city_map("citymap.md")
        agent = {"job": "算法工程师"}
        base = travel_plan(agent, city_map, "North Block", "Central Block")
        route = base["route"]
        for a, b in zip(route, route[1:]):
            set_edge_congestion(city_map, a, b, 2.0)
        jammed = travel_plan(agent, city_map, "North Block", "Central Block")
        self.assertGreater(jammed["travel_minutes"], base["travel_minutes"])

    # ------------------------------------------------------------------
    # Node enrichment & runtime state
    # ------------------------------------------------------------------
    def test_nodes_carry_landuse_and_style(self):
        city_map = load_city_map("citymap.md")
        fin = city_map["nodes"]["Financial District"]
        self.assertEqual(fin["category"], "commerce")
        self.assertGreater(fin["capacity"], 0)
        self.assertIn("color", fin["style"])
        self.assertTrue(0.0 <= fin["popularity"] <= 1.0)
        self.assertTrue(0.0 <= fin["density"] <= 1.0)

    def test_opening_hours_and_occupancy(self):
        city_map = load_city_map("citymap.md")
        # Commerce closes overnight; residential is always open.
        self.assertFalse(is_open(city_map, "Financial District", "03:00"))
        self.assertTrue(is_open(city_map, "Financial District", "12:00"))
        self.assertTrue(is_open(city_map, "North Block", "03:00"))
        cap = city_map["nodes"]["Financial District"]["capacity"]
        set_node_occupancy(city_map, "Financial District", cap // 2)
        self.assertAlmostEqual(occupancy_ratio(city_map, "Financial District"), 0.5, delta=0.05)

    def test_spatial_index_matches_bruteforce(self):
        city_map = load_city_map("citymap.md")
        indexed = nearest_by_category(city_map, "Central Block", "commerce", top_k=5)
        # Brute-force the same query and compare the ordered id lists.
        from gaworld.world.city_map import _euclidean_distance_km
        nodes = city_map["nodes"]
        origin = nodes["Central Block"]
        brute = sorted(
            (
                (nid, round(_euclidean_distance_km(origin, n), 3))
                for nid, n in nodes.items()
                if nid != origin["id"] and n.get("category") == "commerce"
            ),
            key=lambda x: (x[1], x[0]),
        )[:5]
        # Compare as (dist, id)-sorted sets to be robust to tie ordering.
        self.assertEqual(
            sorted((round(d, 3), i) for i, d in indexed),
            sorted((round(d, 3), i) for i, d in brute),
        )

    # ------------------------------------------------------------------
    # Visualization & serialization
    # ------------------------------------------------------------------
    def test_overlays_and_geojson_export(self):
        city_map = load_city_map("citymap.md")
        overlays = city_map["overlays"]
        self.assertEqual(len(overlays["zone"]), overlays["height"])
        self.assertEqual(len(overlays["zone"][0]), overlays["width"])
        gj = export_geojson(city_map)
        self.assertEqual(gj["type"], "FeatureCollection")
        kinds = {f["properties"].get("kind") for f in gj["features"]}
        self.assertIn("road", kinds)
        self.assertIn("metro", kinds)
        payload = build_visualization_payload(city_map)
        self.assertIn("geojson", payload)
        self.assertIn("terrain_legend", payload)

    def test_terrain_legend_covers_tile_symbols(self):
        city_map = load_city_map("citymap.md")
        used = set("".join(city_map["tile_map"]["terrain"]))
        self.assertTrue(used.issubset(set(TERRAIN_LEGEND.keys())))

    def test_serialize_roundtrip_preserves_routing(self):
        city_map = load_city_map("citymap.md")
        before = travel_plan({"job": "算法工程师"}, city_map, "North Block", "Airport District")
        restored = deserialize_city_map(serialize_city_map(city_map))
        self.assertEqual(len(restored["nodes"]), len(city_map["nodes"]))
        after = travel_plan({"job": "算法工程师"}, restored, "North Block", "Airport District")
        self.assertEqual(before["route"], after["route"])
        self.assertAlmostEqual(before["distance_km"], after["distance_km"], places=3)

    def test_building_interiors_parsed(self):
        city_map = load_city_map("citymap.md")
        interiors = city_map.get("interiors", {})
        self.assertIn("Building N-01", interiors)
        floors = interiors["Building N-01"]["floors"]
        self.assertTrue(any(fl["units"] for fl in floors))


if __name__ == "__main__":
    unittest.main()
