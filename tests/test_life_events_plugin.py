"""Wiring tests for the LifeEventsPlugin (K3e migration).

Kernel-level: build the kernel, set up the plugin, emit the events it rides,
verify each consumer path (the life-events domain logic has its own suites).

1. ``on_time_tick`` drains due events into plugin state and mirrors them
   into the env timeline JSONL;
2. ``env.events.compose`` contributes the env-event form, exposes
   ``step["life_events"]``, and records into the daily log;
3. ``perception.compose`` contributes the "人生事件：…" context line;
4. ``state.effects`` applies (clipped) state deltas;
5. ghost injection on ``on_day_start`` honors the human_realism gate.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from collections import defaultdict
from unittest.mock import patch

from gaworld.events import life as life_impl
from gaworld.events.plugin import LifeEventsPlugin
from gaworld.kernel import build_kernel


class _AlwaysRng:
    @staticmethod
    def random():
        return 0.0  # always below the ghost dice threshold


class TestLifeEventsPlugin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self._cwd)
        self.config = {
            "life_events": {
                "event_dir": os.path.join(self.tmp.name, "life_events"),
                "events_file": "events.json",
            },
            "human_realism": {"enabled": False},
        }
        self.ctx = build_kernel(self.config, load_entry_points=False)
        self.ctx.llm = lambda prompt, **kw: ""
        self.plugin = LifeEventsPlugin()
        self.plugin.setup(self.ctx)
        self.timeline_path = os.path.join(self.tmp.name, "timeline.jsonl")

    def _queue_event(self, **overrides):
        payload = {
            "title": "老友来电",
            "description": "多年未见的朋友打来电话",
            "severity": 0.5,
            "impact_tags": ["relationship"],
            "state_effects": {"emotion": 0.2},
            "schedule_mode": "scheduled",
            "day": 1,
            "time": "08:30",
            "agent_ids": [7],
            "template_key": "ghost_event",
        }
        payload.update(overrides)
        return life_impl.add_life_event(payload, self.config)

    def _drain(self, day=1, time_str="08:30"):
        self.ctx.bus.emit(
            "on_time_tick",
            day=day,
            time_str=time_str,
            env_timeline_path=self.timeline_path,
            day_context={"sim_date": "2026-07-11"},
        )

    def test_tick_drain_and_timeline_mirror(self):
        self._queue_event()
        self._drain()
        due = self.ctx.plugin_state("life_events")["due"]
        self.assertEqual(len(due), 1)
        with open(self.timeline_path, encoding="utf-8") as fh:
            row = json.loads(fh.readline())
        self.assertEqual(row["scope"], "life_event")
        self.assertEqual(row["day"], 1)
        # Tick-scope contributions (visualizer merge) reflect the drain.
        tick_events = self.ctx.bus.collect("env.events.tick", day=1, time_str="08:30")
        self.assertEqual(len(tick_events), 1)
        self.assertTrue(tick_events[0]["life_event"])

    def test_agent_events_step_key_and_recording(self):
        self._queue_event()
        self._drain()
        agent = {"id": 7, "name": "丁"}
        step: dict = {}
        daily_logs = defaultdict(str)
        contributed = self.ctx.bus.collect(
            "env.events.compose",
            agent=agent, day=1, time_str="08:30", step=step, daily_logs=daily_logs,
        )
        self.assertEqual(len(contributed), 1)
        self.assertEqual(contributed[0]["type"], "life_event")
        self.assertEqual(len(step["life_events"]), 1)
        self.assertIn("[LifeEvent Day 1 08:30]", daily_logs[7])
        # Perception context line derives from the same events.
        sections = self.ctx.bus.collect(
            "perception.compose", agent=agent, day=1, time_str="08:30",
        )
        self.assertTrue(any(s.startswith("人生事件：") for s in sections))
        # Other agents see nothing.
        other_step: dict = {}
        other = self.ctx.bus.collect(
            "env.events.compose",
            agent={"id": 9, "name": "戊"}, day=1, time_str="08:30",
            step=other_step, daily_logs=defaultdict(str),
        )
        self.assertEqual(other, [])
        self.assertEqual(other_step["life_events"], [])

    def test_state_effects_applied_and_clipped(self):
        agent = {"id": 7, "state": {"emotion": 0.95, "stress": 0.5}}
        step = {"life_events": [{"state_effects": {"emotion": 0.2, "unknown_key": 1.0}}]}
        self.ctx.bus.emit("state.effects", agent=agent, step=step, day=1, time_str="08:30")
        self.assertEqual(agent["state"]["emotion"], 1.0)  # clipped
        self.assertNotIn("unknown_key", agent["state"])

    def test_ghost_injection_gated_by_human_realism(self):
        agents = [{"id": 7, "name": "丁"}]
        fake_ev = {
            "title": "旧同学的消息",
            "description": "一位旧同学发来近况",
            "severity": 0.5,
            "impact_tags": ["relationship", "off_screen"],
            "state_effects": {},
            "template_key": "ghost_event",
        }
        with patch.object(self.plugin, "_rng", _AlwaysRng), patch.object(
            self.plugin, "_generate_ghost_event", lambda *a, **kw: dict(fake_ev)
        ):
            # Gate closed: nothing queued.
            self.ctx.bus.emit("on_day_start", day=1, agents=agents)
            self.assertEqual(life_impl.list_life_events(self.config), [])
            # Gate open: one ghost event queued for the agent.
            self.config["human_realism"]["enabled"] = True
            self.ctx.bus.emit("on_day_start", day=1, agents=agents)
        events = life_impl.list_life_events(self.config)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["agent_ids"], [7])
        self.assertEqual(events[0]["created_by"], "social_network")


if __name__ == "__main__":
    unittest.main()
