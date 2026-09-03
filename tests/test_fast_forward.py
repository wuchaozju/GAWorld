"""Tests for the long-horizon fast-forward day compression.

Two layers:

* **Unit** — :mod:`gaworld.sim._fastforward` in isolation: JSON parse +
  delta clamping, whitelist enforcement, deterministic fallback, state
  application, and brief rendering. These need no heavy sim deps.
* **E2E smoke** — a 3-day fast-forward run of
  :func:`generative_city_sim.run_simulation` against the mock LLM,
  asserting the tick megaloop is bypassed (no ``planning`` /
  ``reflection`` / ``perception`` tasks), exactly one ``fast_forward_day``
  call per agent per day, and that per-day briefs + diaries are written.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest

import gaworld.sim._fastforward as ff
from tests.fixtures.mock_llm import install


# ---------------------------------------------------------------------------
# Unit — _fastforward module
# ---------------------------------------------------------------------------

class TestFastForwardUnit(unittest.TestCase):
    def _agent(self):
        return {
            "id": 1,
            "name": "李泽宇",
            "state": {
                "emotion": 0.58,
                "stress": 0.62,
                "econ_security": 0.5,
                "city_identity": 0.48,
            },
            "memory": ["昨天加班到很晚"],
            "social_neighbors": [2, 3],
            "goals": {},
        }

    def test_digest_parses_and_clamps(self):
        def llm(prompt, task=None, agent_id=None):
            self.assertEqual(task, "fast_forward_day")
            return json.dumps(
                {
                    "brief": "今天照常上班，晚上早回家，心情稍好。",
                    "memory": "和同事的闲聊让我放松了些",
                    # emotion over-cap → clamped to +0.15; stress → -0.15;
                    # 'bogus' key is not whitelisted → dropped.
                    "state_changes": {"emotion": 0.9, "stress": -0.5, "bogus": 1.0},
                    "goal_progress": [],
                    "social": [{"neighbor": 2, "signal": "positive"}],
                    "intentions": {"priorities": ["早点休息"]},
                },
                ensure_ascii=False,
            )

        d = ff.simulate_agent_day(
            self._agent(),
            day=5,
            day_desc="周三 工作日",
            base_schedule=[("07:00", "起床"), ("09:00", "工作")],
            goals_context="无",
            env_events=[{"title": "地铁延误"}],
            agents_by_id={2: {"name": "周婉清"}, 3: {"name": "王强"}},
            config={"long_run": {"enabled": True, "brief_llm": True,
                                 "max_state_delta": 0.15, "randomness": 0}},
            llm_fn=llm,
        )
        self.assertEqual(d["state_changes"], {"emotion": 0.15, "stress": -0.15})
        self.assertEqual(d["social"], [{"neighbor": 2, "signal": "positive"}])
        self.assertTrue(d["brief"])
        self.assertFalse(d["burst"])  # randomness=0 → never a burst

    def test_apply_state_changes_clamps_to_unit_interval(self):
        agent = self._agent()
        agent["state"]["stress"] = 0.95
        applied = ff.apply_state_changes(
            agent, {"emotion": 0.15, "stress": 0.15, "missing": 0.1}, max_delta=0.15
        )
        self.assertAlmostEqual(agent["state"]["emotion"], 0.73)
        self.assertAlmostEqual(agent["state"]["stress"], 1.0)  # clamped at 1.0
        self.assertNotIn("missing", applied)

    def test_fallback_when_no_llm(self):
        d = ff.simulate_agent_day(
            self._agent(),
            day=6,
            day_desc="周四",
            base_schedule=[("07:00", "起床")],
            config={"long_run": {"enabled": True}},
            llm_fn=None,
        )
        self.assertTrue(d["brief"])
        self.assertEqual(d["state_changes"], {})

    def test_fallback_on_unparseable_response(self):
        d = ff.simulate_agent_day(
            self._agent(),
            day=7,
            day_desc="周五",
            base_schedule=[("07:00", "起床")],
            config={"long_run": {"enabled": True, "brief_llm": True}},
            llm_fn=lambda *a, **k: "not json at all",
        )
        self.assertTrue(d["brief"])

    def test_render_day_brief_block(self):
        block = ff.render_day_brief_block(
            5, "周三 工作日", [("李泽宇", "平稳的一天"), ("周婉清", "忙碌")], world_line="地铁延误"
        )
        self.assertIn("Day 5 简报", block)
        self.assertIn("李泽宇", block)
        self.assertIn("地铁延误", block)

    def test_randomness_level_clamps(self):
        self.assertEqual(ff.randomness_level({"long_run": {"randomness": 5}}), 1.0)
        self.assertEqual(ff.randomness_level({"long_run": {"randomness": -1}}), 0.0)
        self.assertEqual(ff.randomness_level({"long_run": {"randomness": "x"}}), ff._DEFAULT_RANDOMNESS)

    def test_burst_injects_prompt_hint_and_flag(self):
        import random as _r
        prompts = []
        d = ff.simulate_agent_day(
            self._agent(),
            day=5,
            day_desc="周三",
            base_schedule=[("07:00", "起床")],
            config={"long_run": {"enabled": True, "brief_llm": True, "randomness": 1.0}},
            llm_fn=lambda p, **k: prompts.append(p) or json.dumps({"brief": "突发了一件事"}, ensure_ascii=False),
            rng=_r.Random(1),  # seeded: first random()=0.134 < 0.30 → burst fires at r=1
        )
        self.assertTrue(d["burst"])
        self.assertIn("突发", prompts[0])

    def test_no_burst_at_zero_randomness(self):
        import random as _r
        d = ff.simulate_agent_day(
            self._agent(),
            day=5,
            day_desc="周三",
            base_schedule=[("07:00", "起床")],
            config={"long_run": {"enabled": True, "brief_llm": True, "randomness": 0}},
            llm_fn=lambda p, **k: json.dumps({"brief": "平稳"}, ensure_ascii=False),
            rng=_r.Random(0),
        )
        self.assertFalse(d["burst"])

    def test_jitter_scales_with_randomness_and_is_noop_at_zero(self):
        import random as _r
        # Zero randomness → no jitter, no state change.
        agent = self._agent()
        before = dict(agent["state"])
        applied0 = ff.apply_random_jitter(agent, randomness=0, rng=_r.Random(1))
        self.assertEqual(applied0, {})
        self.assertEqual(agent["state"], before)
        # Positive randomness → bounded, non-empty perturbation on jitter keys.
        agent = self._agent()
        applied = ff.apply_random_jitter(agent, randomness=1.0, burst=False, rng=_r.Random(1))
        self.assertTrue(applied)
        for key, step in applied.items():
            self.assertIn(key, ff._JITTER_STATE_KEYS)
            self.assertLessEqual(abs(step), ff._JITTER_SCALE + 1e-9)  # amp = scale*r, r=1
            self.assertGreaterEqual(agent["state"][key], 0.0)
            self.assertLessEqual(agent["state"][key], 1.0)
        # Burst amplifies the amplitude envelope.
        agent = self._agent()
        burst_applied = ff.apply_random_jitter(agent, randomness=1.0, burst=True, rng=_r.Random(1))
        for step in burst_applied.values():
            self.assertLessEqual(abs(step), ff._JITTER_SCALE * ff._BURST_JITTER_MULT + 1e-9)


# ---------------------------------------------------------------------------
# E2E smoke — run_simulation in fast-forward mode
# ---------------------------------------------------------------------------

def _has_dep(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


_REQUIRED = ("networkx", "matplotlib", "matplotlib.pyplot")
_MISSING = [m for m in _REQUIRED if not _has_dep(m)]
_PY_OK = sys.version_info >= (3, 11)


@unittest.skipIf(_MISSING, f"missing runtime deps: {_MISSING}")
@unittest.skipUnless(_PY_OK, "requires Python 3.11+ (datetime.UTC)")
class TestFastForwardE2E(unittest.TestCase):
    """A 3-day, 2-agent fast-forward run against the mock LLM."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_src = os.path.join(repo_root, "data")
        data_dst = os.path.join(self.tmp.name, "data")
        if os.path.isdir(data_src):
            shutil.copytree(data_src, data_dst)
        original_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, original_cwd)

    def _patch_config(self) -> None:
        from gaworld.settings import CONFIG

        originals: dict[str, object] = {}
        for key in (
            "agent_ids", "sim_days", "stateful", "simulate_realtime",
            "seconds_per_day", "news", "human_realism", "intervention",
            "external_environment_service", "distributed", "visualization",
            "life_events", "external_rag", "long_run",
        ):
            if key in CONFIG:
                originals[key] = CONFIG[key]
        self.addCleanup(lambda: CONFIG.update(originals))

        CONFIG["agent_ids"] = [4, 5]
        CONFIG["sim_days"] = 3
        CONFIG["stateful"] = False
        CONFIG["simulate_realtime"] = False
        CONFIG["seconds_per_day"] = 1
        CONFIG["long_run"] = {"enabled": True, "brief_llm": True, "max_state_delta": 0.15}
        for key, sub in (("news", "enabled"), ("intervention", "enabled"),
                         ("external_environment_service", "enabled"),
                         ("distributed", "enabled"), ("visualization", "enabled"),
                         ("life_events", "enabled")):
            if isinstance(CONFIG.get(key), dict):
                CONFIG[key] = dict(CONFIG[key])
                CONFIG[key][sub] = False
        if isinstance(CONFIG.get("news"), dict):
            CONFIG["news"]["info_seek"] = dict(CONFIG["news"].get("info_seek", {}))
            CONFIG["news"]["info_seek"]["enabled"] = False
        if isinstance(CONFIG.get("external_rag"), dict):
            CONFIG["external_rag"] = dict(CONFIG["external_rag"])
            CONFIG["external_rag"]["bootstrap"] = dict(CONFIG["external_rag"].get("bootstrap", {}))
            CONFIG["external_rag"]["bootstrap"]["enabled"] = False

    def test_fast_forward_run(self) -> None:
        import generative_city_sim as sim

        self._patch_config()
        # Snapshot + restore the module-level constants we mutate so this
        # run does not leak `LONG_RUN_ENABLED=True` (or a short SIM_DAYS)
        # into later tests sharing the imported module.
        _globals = (
            "AGENT_IDS", "SIM_DAYS", "STATEFUL", "SIMULATE_REALTIME",
            "SECONDS_PER_DAY", "NEWS_ENABLED", "INTERVENTION_ENABLED",
            "HUMAN_REALISM_ENABLED", "VISUALIZATION_ENABLED",
            "LIFE_EVENTS_ENABLED", "LONG_RUN_ENABLED", "LONG_RUN_UNIT",
        )
        _saved = {name: getattr(sim, name) for name in _globals if hasattr(sim, name)}
        self.addCleanup(lambda: [setattr(sim, k, v) for k, v in _saved.items()])

        sim.AGENT_IDS = [4, 5]
        sim.SIM_DAYS = 3
        sim.STATEFUL = False
        sim.SIMULATE_REALTIME = False
        sim.SECONDS_PER_DAY = 1
        sim.NEWS_ENABLED = False
        sim.INTERVENTION_ENABLED = False
        sim.HUMAN_REALISM_ENABLED = False
        sim.VISUALIZATION_ENABLED = False
        sim.LIFE_EVENTS_ENABLED = False
        sim.LONG_RUN_ENABLED = True
        # Pin the step unit: this test is about *day*-granularity fast-forward,
        # and the unit otherwise comes from the developer's local
        # dashboard_config.json — a month there would silently turn this into a
        # period run and break the per-day assertions below.
        sim.LONG_RUN_UNIT = "day"

        with install() as mock:
            sim.run_simulation()

        seen = set(mock.tasks_seen())
        # The fast-forward digest ran...
        self.assertIn("fast_forward_day", seen)
        # ...and the intra-day tick pipeline did NOT (proves the megaloop
        # was skipped, not just made cheaper).
        self.assertFalse(
            seen & {"planning", "reflection", "perception"},
            f"tick-loop tasks should be absent in fast-forward mode: {seen}",
        )
        # One digest per agent per day.
        self.assertEqual(mock.call_count("fast_forward_day"), 2 * 3)

        # Per-agent logs carry the per-day fast-forward brief marker.
        log_dir = os.path.join(self.tmp.name, "output", "logs")
        for aid in (4, 5):
            with open(os.path.join(log_dir, f"agent_{aid}.log"), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("[FastForward Day", text)

        # A diary file per agent per day.
        for aid in (4, 5):
            for day in (1, 2, 3):
                path = os.path.join(
                    self.tmp.name, "output", "diaries", f"agent_{aid}", f"day_{day:03d}.md"
                )
                self.assertTrue(os.path.exists(path), f"missing diary {path}")


if __name__ == "__main__":
    unittest.main()
