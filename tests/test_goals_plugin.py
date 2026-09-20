"""Tests for gaworld.goals_plugin.GoalsPlugin."""

import os
import tempfile
import unittest
from unittest.mock import patch

from gaworld.goals_plugin import GoalsPlugin
from gaworld.kernel import build_kernel


def _make_ctx(goals_cfg, *, stateful=False):
    ctx = build_kernel(
        {
            "goals": goals_cfg,
            "stateful": stateful,
            "memory_dir": "output/memory",
        },
        load_entry_points=False,
    )
    ctx.llm = lambda prompt, **kw: ""
    return ctx


class TestGoalsPluginBootstrap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self._cwd)

    def test_disabled_seeds_empty_goals_and_skips_day_end(self):
        ctx = _make_ctx({"enabled": False})
        plugin = GoalsPlugin()
        plugin.setup(ctx)
        agents = [{"id": 1, "name": "甲"}]
        ctx.bus.emit("agents.built", agents=agents, config=ctx.config)
        self.assertEqual(agents[0]["goals"], {})

    def test_enabled_bootstrap_invokes_impl(self):
        ctx = _make_ctx({"enabled": True}, stateful=True)
        plugin = GoalsPlugin()
        plugin.setup(ctx)
        agents = [{"id": 1, "name": "甲"}]
        calls = {}

        def fake_bootstrap(agents_arg, *, llm, memory_dir, stateful, config, day):
            calls.update(agents=agents_arg, memory_dir=memory_dir,
                         stateful=stateful, day=day)
            for a in agents_arg:
                a["goals"] = {"short_term_goals": []}

        with patch("gaworld.goals.bootstrap_goals", fake_bootstrap), \
             patch("gaworld.goals.format_goals_context", lambda g, max_items=8: "无"):
            ctx.bus.emit("agents.built", agents=agents, config=ctx.config)

        self.assertIs(calls["agents"], agents)
        self.assertTrue(calls["stateful"])
        self.assertEqual(calls["day"], 0)


class TestGoalsPluginDayEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self._cwd)

    def _agent(self, last_review_day=0, needs_review=False):
        return {
            "id": 1, "name": "甲", "episodes": [],
            "goals": {
                "life_goals": [{"id": "lg1", "title": "安家", "domain": "family",
                                "description": "", "status": "active"}],
                "long_term_goals": [], "short_term_goals": [],
                "last_review_day": last_review_day,
                "needs_review": needs_review, "review_log": [],
            },
        }

    def test_weekly_review_fires_on_interval(self):
        ctx = _make_ctx({"enabled": True, "review_interval_days": 7})
        plugin = GoalsPlugin()
        plugin.setup(ctx)
        agent = self._agent(last_review_day=0)
        reviews = []

        with patch("gaworld.goals.run_goal_review",
                   lambda a, **kw: reviews.append(kw["trigger"]) or (a["goals"], "小结")), \
             patch.object(plugin, "_severe_event_today", lambda a, d: None):
            ctx.bus.emit("on_day_end", day=7, agents=[agent],
                         agents_by_id={1: agent}, config=ctx.config)
        self.assertEqual(reviews, ["weekly"])

    def test_no_review_before_interval(self):
        ctx = _make_ctx({"enabled": True, "review_interval_days": 7})
        plugin = GoalsPlugin()
        plugin.setup(ctx)
        agent = self._agent(last_review_day=3)
        reviews = []
        with patch("gaworld.goals.run_goal_review",
                   lambda a, **kw: reviews.append(1) or (a["goals"], "")), \
             patch.object(plugin, "_severe_event_today", lambda a, d: None):
            ctx.bus.emit("on_day_end", day=7, agents=[agent],
                         agents_by_id={1: agent}, config=ctx.config)
        self.assertEqual(reviews, [])

    def test_weekly_budget_defers_review(self):
        ctx = _make_ctx({"enabled": True, "review_interval_days": 7,
                         "max_reviews_per_day": 0})
        plugin = GoalsPlugin()
        plugin.setup(ctx)
        agent = self._agent(last_review_day=0)
        reviews = []
        with patch("gaworld.goals.run_goal_review",
                   lambda a, **kw: reviews.append(1) or (a["goals"], "")), \
             patch.object(plugin, "_severe_event_today", lambda a, d: None):
            ctx.bus.emit("on_day_end", day=7, agents=[agent],
                         agents_by_id={1: agent}, config=ctx.config)
        self.assertEqual(reviews, [])
        self.assertEqual(agent["goals"]["last_review_day"], 0)

    def test_severe_event_triggers_event_review_and_sets_flag(self):
        ctx = _make_ctx({"enabled": True, "review_interval_days": 7})
        plugin = GoalsPlugin()
        plugin.setup(ctx)
        agent = self._agent(last_review_day=6)  # weekly not due on day 7? 7-6<7 → yes
        triggers = []

        def fake_review(a, **kw):
            triggers.append((kw["trigger"], kw.get("trigger_event", {}).get("title")))
            a["goals"]["needs_review"] = False
            return a["goals"], "重估"

        with patch("gaworld.goals.run_goal_review", fake_review), \
             patch.object(plugin, "_severe_event_today",
                          lambda a, d: {"title": "失业", "severity": 0.9}):
            ctx.bus.emit("on_day_end", day=7, agents=[agent],
                         agents_by_id={1: agent}, config=ctx.config)
        self.assertEqual(triggers, [("event", "失业")])

    def test_needs_review_flag_retries_event_review(self):
        ctx = _make_ctx({"enabled": True, "review_interval_days": 30})
        plugin = GoalsPlugin()
        plugin.setup(ctx)
        agent = self._agent(last_review_day=0, needs_review=True)
        triggers = []
        with patch("gaworld.goals.run_goal_review",
                   lambda a, **kw: triggers.append(kw["trigger"]) or (a["goals"], "")), \
             patch.object(plugin, "_severe_event_today", lambda a, d: None):
            ctx.bus.emit("on_day_end", day=3, agents=[agent],
                         agents_by_id={1: agent}, config=ctx.config)
        self.assertEqual(triggers, ["event"])


class TestBuiltinRegistration(unittest.TestCase):
    def test_goals_plugin_in_builtin_list(self):
        from gaworld.plugins import builtin_plugins

        ids = [p.id for p in builtin_plugins()]
        self.assertIn("goals", ids)


if __name__ == "__main__":
    unittest.main()
