"""Tests for the P0 local physical perception layer.

Covers occupancy recomputation from agents, the per-agent physical
snapshot (crowding / opening hours / weather), and text rendering.
"""

import unittest

from gaworld.world import city_map as cm
from gaworld.world.local_physical import (
    crowding_label,
    local_physical_state,
    physical_state_text,
    update_occupancy_from_agents,
)


def _mini_map():
    """Two explicit nodes with known capacity and opening hours."""
    content = (
        "# City Map\n"
        "@node: Plaza | kind=hub | category=commerce | x=1.0 | y=1.0 | capacity=10 | open=9:00 | close=18:00\n"
        "@node: Home Block | kind=hub | category=residential | x=2.0 | y=2.0 | capacity=100\n"
        "@road: Plaza -> Home Block | type=arterial\n"
        "\n- City: Demo\n  - Hub: Plaza\n  - Hub: Home Block\n"
    )
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "m.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return cm.load_city_map(path)


class TestLocalPhysical(unittest.TestCase):
    def test_crowding_label_bands(self):
        self.assertEqual(crowding_label(0.95), "非常拥挤")
        self.assertEqual(crowding_label(0.7), "比较拥挤")
        self.assertEqual(crowding_label(0.4), "人不少")
        self.assertEqual(crowding_label(0.1), "比较空旷")

    def test_update_occupancy_counts_stationary_agents(self):
        city_map = _mini_map()
        agents = [
            {"id": 1, "locations": {"current": "Plaza"}},
            {"id": 2, "locations": {"current": "Plaza"}},
            {"id": 3, "locations": {"current": "Home Block"}},
            {"id": 4, "locations": {"current": "Plaza", "in_transit": True}},  # excluded
        ]
        counts = update_occupancy_from_agents(city_map, agents)
        self.assertEqual(counts["Plaza"], 2)
        self.assertEqual(counts["Home Block"], 1)
        self.assertEqual(cm.get_node_occupancy(city_map, "Plaza"), 2)
        cap = int(cm.node_by_name(city_map, "Plaza")["capacity"])
        self.assertAlmostEqual(cm.occupancy_ratio(city_map, "Plaza"), round(2 / cap, 3), places=3)

    def test_update_occupancy_clears_stale(self):
        city_map = _mini_map()
        update_occupancy_from_agents(city_map, [{"id": 1, "locations": {"current": "Plaza"}}])
        self.assertEqual(cm.get_node_occupancy(city_map, "Plaza"), 1)
        # Next tick nobody is at Plaza -> occupancy must reset to 0.
        update_occupancy_from_agents(city_map, [{"id": 1, "locations": {"current": "Home Block"}}])
        self.assertEqual(cm.get_node_occupancy(city_map, "Plaza"), 0)

    def test_snapshot_crowding_and_hours(self):
        city_map = _mini_map()
        cap = int(cm.node_by_name(city_map, "Plaza")["capacity"])
        # Fill to capacity at Plaza -> packed (ratio >= 0.9).
        agents = [{"id": i, "locations": {"current": "Plaza"}} for i in range(cap)]
        update_occupancy_from_agents(city_map, agents)
        snap = local_physical_state(city_map, agents[0], time_str="10:00", weather_state="小雨")
        self.assertEqual(snap["location"], "Plaza")
        self.assertEqual(snap["crowding"], "非常拥挤")
        self.assertTrue(snap["is_open"])  # 10:00 within 9-18
        self.assertEqual(snap["weather"], "小雨")

        # Before opening hours -> closed.
        snap_closed = local_physical_state(city_map, agents[0], time_str="07:00")
        self.assertFalse(snap_closed["is_open"])

    def test_snapshot_in_transit_is_empty_text(self):
        city_map = _mini_map()
        agent = {"id": 1, "locations": {"current": "Plaza", "in_transit": True}}
        snap = local_physical_state(city_map, agent, time_str="10:00")
        self.assertTrue(snap["in_transit"])
        self.assertEqual(physical_state_text(snap), "")

    def test_text_rendering(self):
        text = physical_state_text(
            {"location": "Plaza", "in_transit": False, "crowding": "非常拥挤",
             "is_open": False, "weather": "高温"}
        )
        self.assertIn("Plaza此刻非常拥挤", text)
        self.assertIn("不在营业时间", text)
        self.assertIn("高温", text)

    def test_unknown_location_degrades_gracefully(self):
        city_map = _mini_map()
        agent = {"id": 1, "locations": {"current": "Nowhere"}}
        snap = local_physical_state(city_map, agent, time_str="10:00")
        self.assertEqual(snap["occupancy_ratio"], 0.0)
        # is_open returns False for unknown nodes (city_map.is_open contract).
        self.assertIn("is_open", snap)

    def test_missing_map_is_safe(self):
        snap = local_physical_state(None, {"id": 1, "locations": {"current": "X"}}, time_str="10:00")
        self.assertEqual(snap["occupancy_ratio"], 0.0)
        self.assertEqual(update_occupancy_from_agents(None, []), {})


if __name__ == "__main__":
    unittest.main()
