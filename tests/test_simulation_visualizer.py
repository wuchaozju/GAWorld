import json
import os
import tempfile
import unittest

from gaworld.world.city_map import load_city_map
from gaworld.apps.visualizer import SimulationVisualizer, build_agent_step_payload, build_map_layout


class TestSimulationVisualizer(unittest.TestCase):
    def test_build_map_layout_includes_tiles_and_nodes(self):
        city_map = load_city_map("citymap.md")
        layout = build_map_layout(city_map)
        node_ids = {node["id"] for node in layout["nodes"]}
        self.assertIn("Central Block", node_ids)
        self.assertIn("Hangzhou Tech Labs", node_ids)
        self.assertIn("tile_map", layout)
        self.assertGreater(layout["tile_map"]["width"], 50)

    def test_visualizer_writes_frames_and_finalize_flag(self):
        city_map = load_city_map("citymap.md")
        agents = [
            {
                "id": 1,
                "name": "李泽宇",
                "locations": {"home": "Central Block", "workplace": "Hangzhou Tech Labs"},
                "state": {"stress": 0.4, "emotion": 0.6},
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            visualizer = SimulationVisualizer(tmpdir, city_map, agents, sim_meta={"sim_days": 1})
            step = build_agent_step_payload(
                agents[0],
                time_str="08:00",
                location="Transit to Hangzhou Tech Labs",
                resolved_location="Central Block",
                target_location="Hangzhou Tech Labs",
                scheduled_activity="通勤上班",
                activity="前往Hangzhou Tech Labs",
                action="乘坐bus移动",
                outcome="从【Central Block】前往【Hangzhou Tech Labs】",
                perception="早晨有点冷。",
                plan="先去上班。",
                reflection="路上还算顺利。",
                travel={"mode": "bus", "distance_km": 2.4, "minutes": 14, "progress": 0.4, "route": ["Central Block", "Hangzhou Tech Labs"], "status": "in_transit"},
            )
            visualizer.record_frame(
                day=1,
                time_str="08:00",
                day_context={"sim_date": "2026-03-10", "weekday_zh": "周二", "day_type_zh": "工作日"},
                env_context="无显著环境事件",
                env_events=[],
                agent_steps=[step],
                policy={},
            )
            visualizer.finalize()
            with open(os.path.join(tmpdir, "simulation_trace.json"), "r", encoding="utf-8") as f:
                payload = json.load(f)
            self.assertTrue(payload["meta"]["finished"])
            self.assertEqual(1, payload["meta"]["frame_count"])
            self.assertEqual("avatars/agent_1.svg", payload["agents"][0]["avatar_path"])
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "avatars", "agent_1.svg")))
            self.assertEqual("Hangzhou Tech Labs", payload["frames"][0]["agents"][0]["target_location"])
            self.assertEqual("avatars/agent_1.svg", payload["frames"][0]["agents"][0]["avatar_path"])
            self.assertEqual("bus", payload["frames"][0]["agents"][0]["travel"]["mode"])

            # The run is also archived under runs/<run_id>/ so the next run
            # does not bury it — that archive is what the replay page lists.
            archive = os.path.join(tmpdir, "runs", visualizer.run_id, "simulation_trace.json")
            self.assertTrue(os.path.exists(archive))
            with open(archive, "r", encoding="utf-8") as f:
                archived = json.load(f)
            self.assertTrue(archived["meta"]["finished"])
            self.assertEqual(1, archived["meta"]["frame_count"])
            self.assertEqual(visualizer.run_id, archived["meta"]["run_id"])

    def test_successive_runs_get_separate_archives(self):
        city_map = load_city_map("citymap.md")
        agents = [{"id": 1, "name": "李泽宇", "locations": {"home": "Central Block"}, "state": {}}]
        with tempfile.TemporaryDirectory() as tmpdir:
            first = SimulationVisualizer(tmpdir, city_map, agents)
            first.finalize()
            second = SimulationVisualizer(tmpdir, city_map, agents)
            second.finalize()
            self.assertNotEqual(first.run_id, second.run_id)
            self.assertEqual(
                2, len(os.listdir(os.path.join(tmpdir, "runs"))), "each run keeps its own archive"
            )


if __name__ == "__main__":
    unittest.main()
