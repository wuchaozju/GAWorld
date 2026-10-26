import json
import os
import tempfile
import unittest

from gaworld.apps.visualizer import SimulationVisualizer, build_agent_step_payload, build_map_layout
from gaworld.world.city_map import load_city_map


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
                travel={
                    "mode": "bus",
                    "distance_km": 2.4,
                    "minutes": 14,
                    "progress": 0.4,
                    "route": ["Central Block", "Hangzhou Tech Labs"],
                    "status": "in_transit",
                },
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
            with open(os.path.join(tmpdir, "simulation_trace.json"), encoding="utf-8") as f:
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
            with open(archive, encoding="utf-8") as f:
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

    def test_start_positions_are_published_before_the_first_tick(self):
        """The map must show the residents before the first tick finishes.

        A tick costs one model call per resident, so the first *recorded*
        frame landed minutes into the run — until then the dashboard's map
        was an empty city. The start positions are known when the visualizer
        is built, so they are published right away.
        """
        city_map = load_city_map("citymap.md")
        agents = [
            {
                "id": 1,
                "name": "李泽宇",
                "locations": {"home": "Central Block", "current": "Central Block"},
                "state": {},
            },
            {
                "id": 2,
                "name": "周慕云",
                "locations": {
                    "home": "Airport Hotel",
                    "workplace": "Central Block",
                    "current": "Airport Hotel",
                },
                "state": {},
            },
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            SimulationVisualizer(tmpdir, city_map, agents, sim_meta={"sim_days": 1})
            with open(os.path.join(tmpdir, "latest_frame.json"), encoding="utf-8") as f:
                frame = json.load(f)["frame"]
            self.assertEqual("init", frame["phase"])
            self.assertEqual(0, frame["index"])
            self.assertEqual(2, len(frame["agents"]))
            self.assertEqual("Central Block", frame["agents"][0]["resolved_location"])
            self.assertEqual("Airport Hotel", frame["agents"][1]["resolved_location"])
            self.assertEqual("李泽宇", frame["agents"][0]["name"])
            # The preview is not a simulated moment: the archive keeps only
            # real frames.
            with open(os.path.join(tmpdir, "simulation_trace.json"), encoding="utf-8") as f:
                trace = json.load(f)
            self.assertEqual(0, len(trace["frames"]))

    def test_live_frame_fills_in_as_residents_report(self):
        """One resident finishing must be visible before the tick is over."""
        city_map = load_city_map("citymap.md")
        agents = [
            {
                "id": 1,
                "name": "李泽宇",
                "locations": {"home": "Central Block", "current": "Central Block"},
                "state": {},
            },
            {
                "id": 2,
                "name": "周慕云",
                "locations": {"home": "Airport Hotel", "current": "Airport Hotel"},
                "state": {},
            },
        ]

        def step(agent, **overrides):
            payload = {
                "time_str": "08:00",
                "location": "Central Block",
                "resolved_location": "Central Block",
                "target_location": "Central Block",
                "scheduled_activity": "通勤上班",
                "activity": "前往中央商务区",
                "action": "乘坐公交",
                "outcome": "",
                "perception": "",
                "plan": "",
                "reflection": "",
            }
            payload.update(overrides)
            return build_agent_step_payload(agent, **payload)

        with tempfile.TemporaryDirectory() as tmpdir:
            visualizer = SimulationVisualizer(tmpdir, city_map, agents, sim_meta={"sim_days": 1})
            # Publish every report straight away; the write interval only
            # matters for a cast that reports in bursts.
            visualizer.live_write_interval = 0

            def latest_frame():
                with open(os.path.join(tmpdir, "latest_frame.json"), encoding="utf-8") as f:
                    return json.load(f)["frame"]

            visualizer.note_agent_step(2, "08:00", step(agents[0], action="李泽宇在读报"), env_context="晴")
            frame = latest_frame()
            self.assertEqual("live", frame["phase"])
            self.assertEqual(0, frame["index"], "the live frame takes the slot the tick will")
            self.assertEqual(2, len(frame["agents"]), "the resident that has not reported keeps its place")
            self.assertEqual("李泽宇在读报", frame["agents"][0]["action"])
            self.assertEqual("Airport Hotel", frame["agents"][1]["resolved_location"])

            # The second resident reports: the frame is filled in, still live.
            visualizer.note_agent_step(
                2,
                "08:00",
                step(agents[1], resolved_location="Central Block", action="周慕云在开会"),
                env_context="晴",
            )
            frame = latest_frame()
            self.assertEqual(2, len(frame["agents"]))
            self.assertEqual("周慕云在开会", frame["agents"][1]["action"])

            # The tick ends: the recorded frame replaces the preview.
            visualizer.record_frame(
                day=2,
                time_str="08:00",
                day_context={"sim_date": "2026-03-10", "weekday_zh": "周二", "day_type_zh": "工作日"},
                env_context="晴",
                env_events=[],
                agent_steps=[step(agents[0], action="李泽宇在读报"), step(agents[1], action="周慕云在开会")],
                policy={},
            )
            frame = latest_frame()
            self.assertNotEqual("live", frame.get("phase"))
            self.assertEqual("2026-03-10", frame["date"])

            # The next tick opens the next slot and seeds it from the frame
            # that was just recorded.
            visualizer.note_agent_step(
                2,
                "09:00",
                step(agents[0], resolved_location="Airport Hotel", action="李泽宇在通勤"),
                env_context="晴",
            )
            frame = latest_frame()
            self.assertEqual(1, frame["index"])
            self.assertEqual("09:00", frame["time"])
            self.assertEqual("Airport Hotel", frame["agents"][0]["resolved_location"])


class TestHomeRoomInPayload(unittest.TestCase):
    """At home, the trace says which room the resident is in.

    The console's indoor mode draws the resident's own flat from it, so the
    frontend never has to re-derive the activity → room mapping.
    """

    def _payload(self, agent, **overrides):
        payload = {
            "time_str": "18:30",
            "location": "Central Block",
            "resolved_location": "Central Block",
            "target_location": "Central Block",
            "scheduled_activity": "晚饭",
            "activity": "晚饭",
            "action": "在餐桌前坐下",
            "outcome": "",
            "perception": "",
            "plan": "",
            "reflection": "",
        }
        payload.update(overrides)
        return build_agent_step_payload(agent, **payload)

    def test_home_room_is_written_when_the_resident_is_home(self):
        agent = {
            "id": 1,
            "name": "李泽宇",
            "locations": {"home": "Central Block", "current": "Central Block"},
            "state": {},
            "_home_observation": {
                "is_at_home": True,
                "current_room": {"key": "dining_room", "name": "餐厅"},
            },
        }
        payload = self._payload(agent)
        self.assertEqual("dining_room", payload["home_room"]["key"])
        self.assertEqual("餐厅", payload["home_room"]["name"])
        self.assertEqual("晚饭", payload["home_room"]["activity"])

    def test_no_home_room_outside_the_flat(self):
        agent = {
            "id": 1,
            "name": "李泽宇",
            "locations": {"home": "Central Block", "current": "工联CC"},
            "state": {},
            "_home_observation": {"is_at_home": False},
        }
        self.assertNotIn("home_room", self._payload(agent))

    def test_household_id_is_written_when_the_family_plugin_ran(self):
        agent = {
            "id": 1,
            "name": "李泽宇",
            "locations": {"home": "Central Block", "current": "Central Block"},
            "state": {},
            "ext": {"family": {"household_id": "H-7"}},
        }
        self.assertEqual("H-7", self._payload(agent)["household"])


if __name__ == "__main__":
    unittest.main()
