"""Wiring tests for the InterestsPlugin (K3d migration).

Kernel-level tests: build the kernel, set up the plugin, emit the events it
rides, and verify the wiring (domain logic has its own suites — see
test_interest_growth_dynamics et al.). Pinned here:

1. ``agents.built``: disabled → every agent seeded with ``{}`` (schema
   parity with the old inline else-branch); enabled → bootstrap invoked
   with the configured cache path / max_items / statefulness.
2. ``episode.compose``: growth keys filled on the episode, profile updated
   on the agent, persistence only when stateful.
3. ``on_day_end``: the plugin's pass runs at priority 10 — before
   config-registered (priority 0) day-end hooks like the economy's.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from gaworld.interests_plugin import InterestsPlugin
from gaworld.kernel import build_kernel


def _make_ctx(interests_cfg: dict, *, stateful: bool = False):
    ctx = build_kernel(
        {
            "interests": interests_cfg,
            "stateful": stateful,
            "memory_dir": "output/memory",
        },
        load_entry_points=False,
    )
    ctx.llm = lambda prompt, **kw: ""
    return ctx


class TestInterestsPlugin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self._cwd)

    def test_disabled_bootstrap_seeds_empty_profiles(self):
        ctx = _make_ctx({"enabled": False})
        plugin = InterestsPlugin()
        plugin.setup(ctx)
        agents = [{"id": 1, "name": "甲"}, {"id": 2, "name": "乙"}]
        ctx.bus.emit("agents.built", agents=agents, config=ctx.config)
        for agent in agents:
            self.assertEqual(agent["growth_profile"], {})

    def test_enabled_bootstrap_invokes_impl_with_config(self):
        ctx = _make_ctx(
            {"enabled": True, "max_items": 4, "cache_path": "output/custom.json"},
            stateful=True,
        )
        plugin = InterestsPlugin()
        plugin.setup(ctx)
        agents = [{"id": 1, "name": "甲"}]
        calls = {}

        def fake_bootstrap(
            agents_arg, *, cache_path, memory_dir, llm, max_items, stateful,
            city_hint="", city_signature="",
        ):
            calls.update(
                agents=agents_arg, cache_path=cache_path, memory_dir=memory_dir,
                max_items=max_items, stateful=stateful,
                city_hint=city_hint, city_signature=city_signature,
            )

        with patch("gaworld.interests.bootstrap_growth_profiles", fake_bootstrap), \
             patch("gaworld.interests.format_growth_context", lambda p, max_items=6: "无"):
            ctx.bus.emit("agents.built", agents=agents, config=ctx.config)

        self.assertIs(calls["agents"], agents)
        self.assertEqual(calls["cache_path"], "output/custom.json")
        self.assertEqual(calls["max_items"], 4)
        self.assertTrue(calls["stateful"])
        # No city selected in this context, so the city channel stays inert and
        # derivation is byte-identical to the pre-city-knowledge behaviour.
        self.assertEqual(calls["city_hint"], "")
        self.assertEqual(calls["city_signature"], "")

    def test_episode_compose_fills_growth_keys(self):
        ctx = _make_ctx({"enabled": True})
        plugin = InterestsPlugin()
        plugin.setup(ctx)
        agent = {"id": 7, "name": "丙", "growth_profile": {"items": []}}
        episode = {"growth_matches": [], "growth_progress": {}}
        progress = {"matches": ["阅读"], "minutes": 30, "level_changes": {}}
        saved = []

        with patch(
            "gaworld.interests.update_growth_from_episode",
            lambda profile, ep, step_minutes=None: ({"items": ["x"]}, progress),
        ), patch(
            "gaworld.interests.save_agent_growth_profile",
            lambda aid, profile, mem_dir: saved.append(aid),
        ):
            ctx.bus.emit(
                "episode.compose", agent=agent, episode=episode,
                step_minutes=30, day=1, time_str="10:00",
            )

        self.assertEqual(episode["growth_matches"], ["阅读"])
        self.assertEqual(episode["growth_progress"], progress)
        self.assertEqual(agent["growth_profile"], {"items": ["x"]})
        self.assertEqual(saved, [], "must not persist when stateful=False")

    def test_episode_compose_persists_when_stateful(self):
        ctx = _make_ctx({"enabled": True}, stateful=True)
        plugin = InterestsPlugin()
        plugin.setup(ctx)
        agent = {"id": 7, "growth_profile": {"items": []}}
        saved = []

        with patch(
            "gaworld.interests.update_growth_from_episode",
            lambda profile, ep, step_minutes=None: ({}, {"matches": []}),
        ), patch(
            "gaworld.interests.save_agent_growth_profile",
            lambda aid, profile, mem_dir: saved.append(aid),
        ):
            ctx.bus.emit(
                "episode.compose", agent=agent, episode={},
                step_minutes=30, day=1, time_str="10:00",
            )

        self.assertEqual(saved, [7])

    def test_day_end_runs_before_config_registered_hooks(self):
        ctx = _make_ctx({"enabled": True})
        order = []
        # Simulate the economy hook: config-registered → priority 0.
        ctx.bus.on("on_day_end", lambda hc: order.append("economy"))
        plugin = InterestsPlugin()
        plugin.setup(ctx)
        agent = {"id": 1, "name": "甲", "growth_profile": {"items": ["x"]}, "episodes": []}

        with patch(
            "gaworld.interests.apply_daily_growth_decay",
            lambda profile, day, config=None: (order.append("interests") or (profile, {})),
        ), patch(
            "gaworld.interests.evolve_growth_profile",
            lambda profile, day, **kw: (profile, {}),
        ):
            ctx.bus.emit(
                "on_day_end", day=1, agents=[agent], agents_by_id={1: agent},
            )

        self.assertEqual(order, ["interests", "economy"])


if __name__ == "__main__":
    unittest.main()
