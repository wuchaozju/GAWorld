"""Tests for the real (OpenStreetMap-derived) map mode.

The real-map loader must produce a ``city_map`` that is structurally identical
to the virtual one — so every downstream consumer (routing, travel plans,
spatial queries, the visualizer) works unchanged — but grounded on true
Hangzhou geography rather than a synthetic grid.
"""

import json
import os
import tempfile
import unittest

from gaworld.world.city_map import (
    build_visualization_payload,
    distance_between,
    load_real_city_map,
    real_city_map_text,
    serialize_city_map,
    shortest_path,
    travel_plan,
)

# A tiny but real slice of Hangzhou: a few landmarks with true WGS84 coords,
# one metro line, and a stretch of the Qiantang river.
LONGXIANGQIAO = (120.1657, 30.2497)   # 龙翔桥 (metro, city centre)
WULIN = (120.1618, 30.2790)           # 武林广场 (commercial hub)
EAST_STATION = (120.2130, 30.2907)    # 杭州东站 (rail/metro hub)
ZHEDA = (120.1250, 30.2637)           # 浙大玉泉 (university)
CBD = (120.2110, 30.2450)             # 钱江新城 (CBD)


def _fixture_bundle():
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": list(LONGXIANGQIAO)},
             "properties": {"name": "龙翔桥", "category": "transit", "kind": "hub"}},
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": list(WULIN)},
             "properties": {"name": "武林广场", "category": "commerce", "kind": "hub"}},
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": list(EAST_STATION)},
             "properties": {"name": "杭州东站", "category": "transit", "kind": "hub"}},
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": list(ZHEDA)},
             "properties": {"name": "浙大玉泉校区", "category": "education", "kind": "place"}},
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": list(CBD)},
             "properties": {"name": "钱江新城", "category": "commerce", "kind": "place"}},
            {"type": "Feature",
             "geometry": {"type": "LineString",
                          "coordinates": [list(WULIN), list(LONGXIANGQIAO), list(EAST_STATION)]},
             "properties": {"kind": "metro", "line": "1号线", "color": "#c04040",
                            "stops": ["武林广场", "龙翔桥", "杭州东站"]}},
            {"type": "Feature",
             "geometry": {"type": "LineString",
                          "coordinates": [[120.13, 30.22], [120.18, 30.235],
                                          [120.22, 30.245], [120.27, 30.26]]},
             "properties": {"kind": "river", "name": "钱塘江", "width_km": 1.1}},
        ],
    }


class TestRealCityMap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".geojson", delete=False, encoding="utf-8")
        json.dump(_fixture_bundle(), self.tmp, ensure_ascii=False)
        self.tmp.close()
        self.city_map = load_real_city_map(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_structure_parity_with_virtual_map(self):
        for key in ("nodes", "edges", "metro_lines", "river", "bridges",
                    "tile_map", "overlays", "bounds", "adjacency", "name_index"):
            self.assertIn(key, self.city_map, f"missing {key}")
        self.assertEqual(len(self.city_map["nodes"]), 5)
        self.assertGreaterEqual(len(self.city_map["edges"]), 4)
        self.assertEqual(self.city_map["meta"]["mode"], "real")

    def test_nodes_carry_true_coordinates(self):
        wulin = self.city_map["nodes"]["武林广场"]
        # Recomputed lat/lng must round-trip back to the real input coords.
        self.assertAlmostEqual(wulin["lat"], WULIN[1], places=2)
        self.assertAlmostEqual(wulin["lng"], WULIN[0], places=2)

    def test_distances_are_real_kilometres(self):
        # 龙翔桥 → 武林广场 is ~3.3 km straight-line in reality.
        d = distance_between(self.city_map, "龙翔桥", "武林广场")
        self.assertGreater(d, 2.5)
        self.assertLess(d, 4.0)
        # 龙翔桥 → 杭州东站 is farther (~6 km).
        self.assertGreater(distance_between(self.city_map, "龙翔桥", "杭州东站"), 4.0)

    def test_graph_is_routable(self):
        route = shortest_path(self.city_map, "浙大玉泉校区", "杭州东站")
        self.assertGreaterEqual(len(route), 2)
        self.assertEqual(route[0], "浙大玉泉校区")
        self.assertEqual(route[-1], "杭州东站")

    def test_travel_plan_works_on_real_map(self):
        agent = {"job": "算法工程师", "daily_life": "通勤上班"}
        plan = travel_plan(agent, self.city_map, "武林广场", "杭州东站", activity="通勤")
        self.assertGreater(plan["distance_km"], 0.1)
        self.assertIn(plan["mode"], {"walk", "bike", "e-bike", "bus", "metro", "car", "taxi"})
        self.assertGreaterEqual(len(plan["route"]), 2)

    def test_metro_line_and_river_loaded(self):
        self.assertEqual(len(self.city_map["metro_lines"]), 1)
        line = self.city_map["metro_lines"][0]
        self.assertEqual(line["name"], "1号线")
        self.assertIn("龙翔桥", line["stops"])
        self.assertEqual(self.city_map["river"]["name"], "钱塘江")

    def test_visualization_payload_and_summary(self):
        payload = build_visualization_payload(self.city_map)
        self.assertEqual(len(payload["nodes"]), 5)
        self.assertTrue(payload["geojson"]["features"])
        text = real_city_map_text(self.city_map)
        self.assertIn("龙翔桥", text)
        self.assertIn("地铁1号线", text)

    def test_serialize_roundtrip(self):
        data = serialize_city_map(self.city_map)
        self.assertIn("nodes", data)
        # Real nodes survive a JSON round-trip.
        self.assertEqual(len(data["nodes"]), 5)

    def test_missing_bundle_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_real_city_map("data/does_not_exist_real.geojson")


if __name__ == "__main__":
    unittest.main()
