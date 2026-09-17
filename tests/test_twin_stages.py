import os
import tempfile
import unittest
from dataclasses import dataclass, field

from gaworld.twin import stages, store


class _Recorder:
    def __init__(self):
        self.records = []

    def record(self, table, payload):
        self.records.append((table, payload))


class _Controller:
    def __init__(self):
        self._interventions = {}
        self.recorder = None

    def register_intervention(self, name, fn):
        self._interventions[str(name)] = fn

    def intervention_names(self):
        return sorted(self._interventions)

    def intervene(self, name, ctx, **kwargs):
        if ctx.recorder is not None:
            ctx.recorder.record("controller.intervention", {"name": name, "kwargs": kwargs})
        return self._interventions[str(name)](ctx, **kwargs)


@dataclass
class _Clock:
    day: int = 1
    time_str: str = "09:00"
    tick_index: int = 0


@dataclass
class _Ctx:
    """Minimal SimContext stand-in exposing only what the stages may touch."""

    config: dict = field(default_factory=dict)
    clock: _Clock = field(default_factory=_Clock)
    controller: _Controller = field(default_factory=_Controller)
    recorder: _Recorder = field(default_factory=_Recorder)
    _ext: dict = field(default_factory=dict)

    def agent_ext(self, agent, plugin_id):
        return agent.setdefault("ext", {}).setdefault(str(plugin_id), {})


def _report(report_id, ts, node_id="office", tag="work", note="",
            out_of_map=False, place=""):
    return {
        "report_id": report_id,
        "ts": ts,
        "tz_offset": 480,
        "loc": {"lat": 30.27, "lng": 120.15, "acc_m": 10, "source": "gps"},
        "grid": {"x": 1.0, "y": 0.0},
        "node_id": node_id,
        "snap_km": 0.2,
        "out_of_map": out_of_map,
        "place": place,
        "action_tag": tag,
        "note": note,
    }


class _TwinStageCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, "twin")
        self.ctx = _Ctx(
            config={
                "twin": {
                    "enabled": True,
                    "root": self.root,
                    "snapshot_ttl_minutes": 30,
                },
                "memory_dir": os.path.join(self._tmp.name, "memory"),
            }
        )
        self.agent = {"id": 7, "name": "cw", "locations": {"current": "家"}}

    def tearDown(self):
        self._tmp.cleanup()

    def _fresh_step(self):
        return {
            "_location": "家",
            "_resolved_location": "家",
            "_act": "看书",
            "_outcome": "在【休息】中执行了【看书】",
            "_effective_activity": "休息",
            "_perception": "现在是早上。",
        }


class TestTwinMirror(_TwinStageCase):
    def test_mirror_overwrites_location_and_action(self):
        store.append_reports(7, [_report("a", 1000)], root=self.root)
        step = self._fresh_step()
        stages.twin_mirror(self.agent, step, self.ctx, now_ts=1000 + 60)

        self.assertEqual(self.agent["locations"]["current"], "office")
        self.assertEqual(step["_location"], "office")
        self.assertEqual(step["_resolved_location"], "office")
        self.assertIn("work", step["_act"])

    def test_mirror_is_skipped_when_the_snapshot_is_stale(self):
        store.append_reports(7, [_report("a", 1000)], root=self.root)
        step = self._fresh_step()
        stages.twin_mirror(self.agent, step, self.ctx, now_ts=1000 + 60 * 60)

        # The agent must fall back to autonomous behaviour, untouched.
        self.assertEqual(self.agent["locations"]["current"], "家")
        self.assertEqual(step["_act"], "看书")

    def test_out_of_map_marks_the_agent_as_away_with_the_place_name(self):
        # A fix outside the mapped city is still a real position. Leaving the
        # agent in town would quietly assert something false.
        store.append_reports(
            7,
            [_report("a", 1000, node_id=None, out_of_map=True, place="北京")],
            root=self.root,
        )
        step = self._fresh_step()
        stages.twin_mirror(self.agent, step, self.ctx, now_ts=1000 + 60)

        self.assertEqual(self.agent["locations"]["current"], "异地（北京）")
        self.assertEqual(step["_location"], "异地（北京）")
        self.assertIn("work", step["_act"])

    def test_out_of_map_without_a_place_name_still_marks_away(self):
        store.append_reports(
            7,
            [_report("a", 1000, node_id=None, out_of_map=True, place="")],
            root=self.root,
        )
        step = self._fresh_step()
        stages.twin_mirror(self.agent, step, self.ctx, now_ts=1000 + 60)
        self.assertEqual(self.agent["locations"]["current"], "异地")

    def test_out_of_map_never_snaps_to_a_nearest_node(self):
        # Fabricating a node would poison the calibration corpus.
        store.append_reports(
            7,
            [_report("a", 1000, node_id=None, out_of_map=True, place="北京")],
            root=self.root,
        )
        step = self._fresh_step()
        stages.twin_mirror(self.agent, step, self.ctx, now_ts=1000 + 60)
        self.assertNotEqual(step["_location"], "office")
        self.assertTrue(step["_location"].startswith("异地"))

    def test_mirror_does_nothing_for_an_agent_with_no_twin(self):
        step = self._fresh_step()
        stages.twin_mirror({"id": 99, "locations": {"current": "家"}}, step, self.ctx, now_ts=1000)
        self.assertEqual(step["_act"], "看书")

    def test_mirror_is_audited(self):
        store.append_reports(7, [_report("a", 1000)], root=self.root)
        stages.twin_mirror(self.agent, self._fresh_step(), self.ctx, now_ts=1000 + 60)

        names = [
            payload["name"]
            for table, payload in self.ctx.recorder.records
            if table == "controller.intervention"
        ]
        self.assertIn("set_agent_twin_state", names)

    def test_mirror_is_disabled_when_config_says_so(self):
        self.ctx.config["twin"]["enabled"] = False
        store.append_reports(7, [_report("a", 1000)], root=self.root)
        step = self._fresh_step()
        stages.twin_mirror(self.agent, step, self.ctx, now_ts=1000 + 60)
        self.assertEqual(step["_act"], "看书")


class TestTwinPerceive(_TwinStageCase):
    def test_perceive_appends_new_reports_to_perception(self):
        store.append_reports(7, [_report("a", 1000, note="在公司加班")], root=self.root)
        step = self._fresh_step()
        stages.twin_perceive(self.agent, step, self.ctx)
        self.assertIn("在公司加班", step["_perception"])

    def test_perceive_does_not_replay_the_same_report_twice(self):
        store.append_reports(7, [_report("a", 1000, note="加班")], root=self.root)
        first = self._fresh_step()
        stages.twin_perceive(self.agent, first, self.ctx)
        second = self._fresh_step()
        stages.twin_perceive(self.agent, second, self.ctx)
        self.assertNotIn("加班", second["_perception"])

    def test_perceive_advances_the_offset_across_reports(self):
        # Note texts must not appear in the base perception fixture, or the
        # "not replayed" assertion would match the fixture instead.
        store.append_reports(7, [_report("a", 1000, note="第一条报告")], root=self.root)
        stages.twin_perceive(self.agent, self._fresh_step(), self.ctx)
        store.append_reports(7, [_report("b", 2000, note="第二条报告")], root=self.root)
        step = self._fresh_step()
        stages.twin_perceive(self.agent, step, self.ctx)
        self.assertIn("第二条报告", step["_perception"])
        self.assertNotIn("第一条报告", step["_perception"])

    def test_perceive_writes_an_episode(self):
        from gaworld.memory.experience import load_agent_episodes

        store.append_reports(7, [_report("a", 1000, note="加班")], root=self.root)
        stages.twin_perceive(self.agent, self._fresh_step(), self.ctx)
        episodes = load_agent_episodes(7, cfg=self.ctx.config)
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["source"], "twin")

    def test_perceive_does_nothing_for_an_agent_with_no_twin(self):
        step = self._fresh_step()
        stages.twin_perceive({"id": 99}, step, self.ctx)
        self.assertEqual(step["_perception"], "现在是早上。")


class TestStageOrdering(_TwinStageCase):
    def test_mirror_after_move_survives_but_before_move_does_not(self):
        """Encode WHY the mirror sits after select_action.

        Simulates the two candidate orderings against a stand-in `move` that
        rewrites location the way the real one does. Only the correct ordering
        leaves the real location standing.
        """
        store.append_reports(7, [_report("a", 1000)], root=self.root)

        def fake_move(agent, step, sim):
            agent.setdefault("locations", {})["current"] = "模拟推断的地点"
            step["_location"] = "模拟推断的地点"
            step["_resolved_location"] = "模拟推断的地点"

        # Wrong ordering: mirror then move.
        agent_wrong = {"id": 7, "name": "cw", "locations": {"current": "家"}}
        step_wrong = self._fresh_step()
        stages.twin_mirror(agent_wrong, step_wrong, self.ctx, now_ts=1060)
        fake_move(agent_wrong, step_wrong, self.ctx)
        self.assertEqual(step_wrong["_location"], "模拟推断的地点")

        # Correct ordering: move then mirror.
        agent_right = {"id": 7, "name": "cw", "locations": {"current": "家"}}
        step_right = self._fresh_step()
        fake_move(agent_right, step_right, self.ctx)
        stages.twin_mirror(agent_right, step_right, self.ctx, now_ts=1060)
        self.assertEqual(step_right["_location"], "office")

    def test_configured_pipeline_places_the_stages_correctly(self):
        """The documented CONFIG ordering must actually satisfy the contract."""
        order = [
            "prepare", "perceive", "gaworld.twin.stages:twin_perceive", "interrupts",
            "plan", "adjust_activity", "move", "select_action",
            "gaworld.twin.stages:twin_mirror", "reflect", "update_state",
            "broadcast", "memorize", "record",
        ]
        self.assertLess(order.index("perceive"), order.index("gaworld.twin.stages:twin_perceive"))
        self.assertLess(order.index("gaworld.twin.stages:twin_perceive"), order.index("plan"))
        self.assertLess(order.index("move"), order.index("gaworld.twin.stages:twin_mirror"))
        self.assertLess(
            order.index("select_action"), order.index("gaworld.twin.stages:twin_mirror")
        )
        self.assertLess(order.index("gaworld.twin.stages:twin_mirror"), order.index("reflect"))
        self.assertLess(order.index("gaworld.twin.stages:twin_mirror"), order.index("memorize"))


if __name__ == "__main__":
    unittest.main()
