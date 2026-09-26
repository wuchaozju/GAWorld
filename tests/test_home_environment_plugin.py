"""Wiring tests for HomeEnvironmentPlugin (K3-style plugin contract).

The domain logic has its own suite (``test_home_environment.py``); pinned here
is the plugin wiring:

1. ``agents.built`` seeds each agent's home (procedural when ``llm_enrich`` is
   off, persisted to ``output/home`` so a stateful run reloads it next time);
2. ``perception.compose`` contributes the room + ambiance line when the agent
   is at their home node, and contributes nothing otherwise (off-site /
   in-transit / ``enabled=False``);
3. ``on_agent_post_step`` records one row per tick to ``agent_<id>.jsonl``;
4. disabled: nothing is contributed and the per-agent key resets.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gaworld.kernel import build_kernel
from gaworld.world.home_plugin import HomeEnvironmentPlugin


def _agent(agent_id=1, home="H1", income=12000, current=None):
    current = current if current is not None else home
    return {
        "id": agent_id,
        "name": f"a{agent_id}",
        "age": 30,
        "monthly_income": income,
        "locations": {"home": home, "current": current},
        "marital_status": "single",
    }


class _RecorderSpy:
    def __init__(self):
        self.records = []

    def record(self, *args, **kwargs):
        self.records.append((args, kwargs))


class _Sim:
    """Minimal stand-in for the simulator object the home plugin pokes at."""

    def __init__(self, output_root, weather="clear"):
        self.extras = {
            "env_system": type(
                "E", (), {"export_runtime_state": staticmethod(lambda: {"weather_state": weather})}
            )(),
        }
        self.recorder = _RecorderSpy()
        self.extras["recorder"] = self.recorder
        self.config = {"stateful": False}


class _Ctx:
    """Wrapper around build_kernel() that gives us a temporary output root."""

    def __init__(self, home_cfg: dict):
        self._tmp = tempfile.TemporaryDirectory()
        self.output_root = self._tmp.name
        self.ctx = build_kernel(
            {"home": home_cfg, "output_root": self.output_root},
            load_entry_points=False,
        )

    def sim(self, weather="clear"):
        sim = _Sim(output_root=self.output_root, weather=weather)
        sim.extras.update(self.ctx.extras)
        return sim

    def cleanup(self):
        self._tmp.cleanup()


class TestHomePluginSeeding(unittest.TestCase):
    def test_seeds_each_agent_with_a_home(self):
        c = _Ctx({"enabled": True, "seed": 42})
        try:
            plugin = HomeEnvironmentPlugin()
            plugin.setup(c.ctx)
            sim = c.sim()
            agents = [_agent(1, home="H1"), _agent(2, home="H2"), _agent(3, home="H3")]
            c.ctx.bus.emit("agents.built", sim=sim, agents=agents)
            for agent in agents:
                self.assertIn("_home", agent)
                self.assertEqual(agent["_home"]["home_node"], agent["locations"]["home"])
            saved = list(Path(c.output_root, "home").glob("agent_*.json"))
            self.assertEqual(len(saved), 3)
        finally:
            c.cleanup()

    def test_stateful_run_reloads_existing_home(self):
        c = _Ctx({"enabled": True, "seed": 42})
        try:
            sim = c.sim()
            agent = _agent()
            plugin1 = HomeEnvironmentPlugin()
            plugin1.setup(c.ctx)
            c.ctx.bus.emit("agents.built", sim=sim, agents=[agent])
            first_vibe = agent["_home"]["vibe"]
            agent.pop("_home")
            sim.config["stateful"] = True
            plugin2 = HomeEnvironmentPlugin()
            plugin2.setup(c.ctx)
            c.ctx.bus.emit("agents.built", sim=sim, agents=[agent])
            self.assertEqual(agent["_home"]["vibe"], first_vibe)
        finally:
            c.cleanup()

    def test_llm_enrich_calls_call_llm(self):
        c = _Ctx({"enabled": True, "seed": 42, "llm_enrich": True})
        try:
            plugin = HomeEnvironmentPlugin()
            plugin.setup(c.ctx)
            with patch(
                "gaworld.llm.providers.call_llm",
                return_value=json.dumps(
                    {
                        "living_room": {"furniture": ["Linen sofa"]},
                        "vibe": "warm minimal",
                    },
                    ensure_ascii=False,
                ),
            ) as mock_llm:
                sim = c.sim()
                agent = _agent()
                c.ctx.bus.emit("agents.built", sim=sim, agents=[agent])
            self.assertEqual(mock_llm.call_count, 1)
            self.assertEqual(agent["_home"]["vibe"], "warm minimal")
            self.assertIn("Linen sofa", agent["_home"]["rooms"]["living_room"]["furniture"])
        finally:
            c.cleanup()


class TestHomePluginPerception(unittest.TestCase):
    def test_at_home_contributes_room_and_ambiance(self):
        c = _Ctx({"enabled": True, "seed": 42, "inject_into_perception": True})
        try:
            plugin = HomeEnvironmentPlugin()
            plugin.setup(c.ctx)
            sim = c.sim()
            agent = _agent()
            c.ctx.bus.emit("agents.built", sim=sim, agents=[agent])
            snippets = c.ctx.bus.collect(
                "perception.compose",
                agent=agent,
                sim=sim,
                day=1,
                time_str="18:30",
                step={"scheduled_activity": "做饭", "activity": "做饭"},
            )
            self.assertEqual(len(snippets), 1)
            self.assertIn("厨房", snippets[0])
            self.assertIn("氛围", snippets[0])
            self.assertTrue(agent["_home_observation"]["is_at_home"])
            self.assertEqual(agent["_home_observation"]["current_room"]["key"], "kitchen")
        finally:
            c.cleanup()

    def test_out_of_home_contributes_nothing(self):
        c = _Ctx({"enabled": True, "seed": 42, "inject_into_perception": True})
        try:
            plugin = HomeEnvironmentPlugin()
            plugin.setup(c.ctx)
            sim = c.sim()
            agent = _agent(current="Office Tower")
            c.ctx.bus.emit("agents.built", sim=sim, agents=[agent])
            snippets = c.ctx.bus.collect(
                "perception.compose",
                agent=agent,
                sim=sim,
                day=1,
                time_str="10:00",
                step={"scheduled_activity": "工作", "activity": "工作"},
            )
            self.assertEqual(snippets, [])
            self.assertFalse(agent["_home_observation"]["is_at_home"])
        finally:
            c.cleanup()

    def test_in_transit_does_not_contribute(self):
        c = _Ctx({"enabled": True, "seed": 42})
        try:
            plugin = HomeEnvironmentPlugin()
            plugin.setup(c.ctx)
            sim = c.sim()
            agent = _agent()
            agent["locations"]["in_transit"] = True
            c.ctx.bus.emit("agents.built", sim=sim, agents=[agent])
            snippets = c.ctx.bus.collect(
                "perception.compose",
                agent=agent,
                sim=sim,
                day=1,
                time_str="10:00",
                step={"scheduled_activity": "回家", "activity": "回家"},
            )
            self.assertEqual(snippets, [])
        finally:
            c.cleanup()

    def test_inject_disabled_stores_snapshot_only(self):
        c = _Ctx({"enabled": True, "seed": 42, "inject_into_perception": False})
        try:
            plugin = HomeEnvironmentPlugin()
            plugin.setup(c.ctx)
            sim = c.sim()
            agent = _agent()
            c.ctx.bus.emit("agents.built", sim=sim, agents=[agent])
            snippets = c.ctx.bus.collect(
                "perception.compose",
                agent=agent,
                sim=sim,
                day=1,
                time_str="18:30",
                step={"scheduled_activity": "做饭", "activity": "做饭"},
            )
            self.assertEqual(snippets, [])
            self.assertTrue(agent["_home_observation"]["is_at_home"])
        finally:
            c.cleanup()


class TestHomePluginTick(unittest.TestCase):
    def test_on_post_step_appends_observation_row_when_at_home(self):
        c = _Ctx({"enabled": True, "seed": 42, "record_observations": True})
        try:
            plugin = HomeEnvironmentPlugin()
            plugin.setup(c.ctx)
            sim = c.sim()
            agent = _agent()
            c.ctx.bus.emit("agents.built", sim=sim, agents=[agent])
            agent["_home_observation"] = {
                "is_at_home": True,
                "home_node": "H1",
                "current_room": {"key": "living_room", "name": "客厅"},
                "ambiance": {"lighting": "自然光"},
                "vibe": "v",
            }
            c.ctx.bus.emit(
                "on_agent_post_step",
                sim=sim,
                agent=agent,
                day=1,
                time_str="10:00",
            )
            jsonl = Path(c.output_root) / "home" / "agent_1.jsonl"
            self.assertTrue(jsonl.exists())
            row = json.loads(jsonl.read_text(encoding="utf-8").strip())
            self.assertEqual(row["day"], 1)
            self.assertEqual(row["current_room"]["key"], "living_room")
            event_names = [args[0] for args, _ in sim.recorder.records]
            self.assertIn("home.observation", event_names)
        finally:
            c.cleanup()

    def test_on_post_step_skips_when_not_at_home(self):
        c = _Ctx({"enabled": True, "seed": 42, "record_observations": True})
        try:
            plugin = HomeEnvironmentPlugin()
            plugin.setup(c.ctx)
            sim = c.sim()
            agent = _agent()
            c.ctx.bus.emit("agents.built", sim=sim, agents=[agent])
            agent["_home_observation"] = {"is_at_home": False}
            c.ctx.bus.emit(
                "on_agent_post_step",
                sim=sim,
                agent=agent,
                day=1,
                time_str="10:00",
            )
            jsonl = Path(c.output_root) / "home" / "agent_1.jsonl"
            self.assertFalse(jsonl.exists())
        finally:
            c.cleanup()


class TestHomePluginDisabled(unittest.TestCase):
    def test_disabled_resets_agent_key_and_contributes_nothing(self):
        c = _Ctx({"enabled": False})
        try:
            plugin = HomeEnvironmentPlugin()
            plugin.setup(c.ctx)
            sim = c.sim()
            agent = {
                "id": 1,
                "locations": {"home": "H1", "current": "H1"},
                "_home_observation": {"stale": True},
            }
            snippets = c.ctx.bus.collect(
                "perception.compose",
                agent=agent,
                sim=sim,
                day=1,
                time_str="10:00",
                step={"scheduled_activity": "做饭"},
            )
            self.assertEqual(snippets, [])
            self.assertNotIn("_home_observation", agent)
        finally:
            c.cleanup()


if __name__ == "__main__":
    unittest.main()
