"""Regression: routine changes must survive the agent step (post-K2 fix).

The pre-K2 loop re-read ``step_ctx["activity"]`` unconditionally after
``maybe_adjust_activity``; since that key was seeded with the scheduled
activity at step start, the seeded value clobbered any LLM/dynamic
adjustment whenever no pre-step hook overrode it — silently disabling
routine changes on the mainline path (introduced by commit 3f7edba).

Two behaviors are pinned here:

1. an adjustment returned by ``maybe_adjust_activity`` reaches the final
   step (``activity`` / ``changed`` in the post-step payload);
2. a pre-step hook override (the economy income-seek contract) still wins
   over the adjustment.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.fixtures.mock_llm import install


def _has_dep(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


_REQUIRED = ("networkx", "matplotlib", "matplotlib.pyplot")
_MISSING = [m for m in _REQUIRED if not _has_dep(m)]
_PY_OK = sys.version_info >= (3, 11)

POST_STEPS: list = []


def capture_post_step(ctx):
    step = ctx.get("step") or {}
    POST_STEPS.append(
        {
            "agent_id": (ctx.get("agent") or {}).get("id"),
            "scheduled": step.get("scheduled_activity"),
            "activity": step.get("activity"),
            "changed": step.get("changed"),
            "change_reason": step.get("change_reason"),
        }
    )


def force_income_activity(ctx):
    """Economy-style pre-step hook: override the seeded activity."""
    step = ctx.get("step")
    if isinstance(step, dict):
        step["activity"] = "临时兼职赚钱"
        step["change_reason"] = "wealth_pursuit_income_seek"


@unittest.skipIf(_MISSING, f"missing runtime deps: {_MISSING}")
@unittest.skipUnless(_PY_OK, "requires Python 3.11+ (datetime.UTC)")
class TestRoutineChangeMainline(unittest.TestCase):
    def setUp(self) -> None:
        POST_STEPS.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original_cwd = os.getcwd()
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_src = os.path.join(repo_root, "data")
        if os.path.isdir(data_src):
            shutil.copytree(data_src, os.path.join(self.tmp.name, "data"))
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.original_cwd)

    def _patch_config(self, extra_pre_step_hooks=()) -> None:
        from gaworld.settings import CONFIG

        originals: dict[str, object] = {}
        touched = (
            "agent_ids", "sim_days", "stateful", "simulate_realtime",
            "seconds_per_day", "news", "intervention", "extensions",
            "external_environment_service", "distributed", "visualization",
            "life_events", "external_rag",
        )
        for key in touched:
            if key in CONFIG:
                originals[key] = CONFIG[key]

        def _restore() -> None:
            for k, v in originals.items():
                CONFIG[k] = v

        self.addCleanup(_restore)

        CONFIG["agent_ids"] = [4]
        CONFIG["sim_days"] = 1
        CONFIG["stateful"] = False
        CONFIG["simulate_realtime"] = False
        CONFIG["seconds_per_day"] = 1
        CONFIG["extensions"] = dict(CONFIG.get("extensions", {}))
        hooks = {
            phase: list(paths)
            for phase, paths in CONFIG["extensions"].get("hooks", {}).items()
        }
        hooks.setdefault("on_agent_post_step", []).append(
            "tests.test_routine_change_mainline:capture_post_step"
        )
        for path in extra_pre_step_hooks:
            hooks.setdefault("on_agent_pre_step", []).append(path)
        CONFIG["extensions"]["hooks"] = hooks
        for key in (
            "news", "intervention", "external_environment_service",
            "distributed", "visualization", "life_events",
        ):
            if isinstance(CONFIG.get(key), dict):
                CONFIG[key] = dict(CONFIG[key])
                CONFIG[key]["enabled"] = False
        if isinstance(CONFIG.get("news"), dict):
            CONFIG["news"]["info_seek"] = dict(CONFIG["news"].get("info_seek", {}))
            CONFIG["news"]["info_seek"]["enabled"] = False
        if isinstance(CONFIG.get("external_rag"), dict):
            CONFIG["external_rag"] = dict(CONFIG["external_rag"])
            CONFIG["external_rag"]["bootstrap"] = dict(
                CONFIG["external_rag"].get("bootstrap", {})
            )
            CONFIG["external_rag"]["bootstrap"]["enabled"] = False

    def _patch_module_constants(self, sim) -> None:
        sim.AGENT_IDS = [4]
        sim.SIM_DAYS = 1
        sim.STATEFUL = False
        sim.SIMULATE_REALTIME = False
        sim.SECONDS_PER_DAY = 1
        sim.NEWS_ENABLED = False
        sim.INTERVENTION_ENABLED = False
        sim.HUMAN_REALISM_ENABLED = False
        sim.VISUALIZATION_ENABLED = False
        sim.LIFE_EVENTS_ENABLED = False

    def test_llm_adjustment_survives_to_final_step(self) -> None:
        import generative_city_sim as sim

        self._patch_config()
        self._patch_module_constants(sim)

        def always_change(agent, time_str, scheduled_activity, *args, **kwargs):
            return "临时去公园散步", "测试强制改变", True

        with install(), patch.object(sim, "maybe_adjust_activity", always_change):
            sim.run_simulation()

        self.assertTrue(POST_STEPS)
        changed_steps = [s for s in POST_STEPS if s["changed"]]
        self.assertTrue(
            changed_steps,
            "maybe_adjust_activity changed every step but no step recorded a change "
            "(the pre-K2 clobber is back)",
        )
        self.assertTrue(
            any(s["activity"] == "临时去公园散步" for s in changed_steps),
            f"adjusted activity lost; final activities: "
            f"{sorted({s['activity'] for s in POST_STEPS})}",
        )

    def test_pre_step_hook_override_still_wins(self) -> None:
        import generative_city_sim as sim

        self._patch_config(
            extra_pre_step_hooks=(
                "tests.test_routine_change_mainline:force_income_activity",
            )
        )
        self._patch_module_constants(sim)

        def always_change(agent, time_str, scheduled_activity, *args, **kwargs):
            return "临时去公园散步", "测试强制改变", True

        with install(), patch.object(sim, "maybe_adjust_activity", always_change):
            sim.run_simulation()

        self.assertTrue(POST_STEPS)
        self.assertTrue(
            any(s["activity"] == "临时兼职赚钱" for s in POST_STEPS),
            "hook-forced activity did not win over the LLM adjustment",
        )


if __name__ == "__main__":
    unittest.main()
