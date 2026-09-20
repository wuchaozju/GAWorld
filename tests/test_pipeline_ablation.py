"""K2 acceptance tests: pipeline ablation and custom-stage insertion.

The cognition pipeline is configuration (`CONFIG["pipeline"]["agent_step"]`).
These tests prove the two capabilities the design doc promises:

1. **Ablation**: removing ``reflect`` from the order runs a full simulation
   with zero reflection LLM calls — cognitive ablation experiments become a
   config change instead of a code fork.
2. **Insertion**: an external stage referenced by ``module:function`` path
   runs once per agent-step with the step data bus visible.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import unittest

from gaworld.sim.pipeline import DEFAULT_AGENT_STEP_ORDER

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

STAGE_TRACE: list = []


def tracing_stage(agent, step, ctx):
    """Custom stage loaded by import path from CONFIG."""
    STAGE_TRACE.append(
        {
            "agent_id": agent.get("id"),
            "has_perception": bool(step.get("_perception")),
            "clock_day": ctx.clock.day if ctx is not None else None,
        }
    )


@unittest.skipIf(_MISSING, f"missing runtime deps: {_MISSING}")
@unittest.skipUnless(_PY_OK, "requires Python 3.11+ (datetime.UTC)")
class TestPipelineAblation(unittest.TestCase):
    def setUp(self) -> None:
        STAGE_TRACE.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original_cwd = os.getcwd()
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_src = os.path.join(repo_root, "data")
        if os.path.isdir(data_src):
            shutil.copytree(data_src, os.path.join(self.tmp.name, "data"))
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.original_cwd)

    def _patch_config(self, agent_step_order) -> None:
        from gaworld.settings import CONFIG

        originals: dict[str, object] = {}
        touched = (
            "agent_ids", "sim_days", "stateful", "simulate_realtime",
            "seconds_per_day", "news", "intervention", "pipeline",
            "external_environment_service", "distributed", "visualization",
            "life_events", "external_rag",
        )
        for key in touched:
            if key in CONFIG:
                originals[key] = CONFIG[key]

        def _restore() -> None:
            CONFIG.pop("pipeline", None)
            for k, v in originals.items():
                CONFIG[k] = v

        self.addCleanup(_restore)

        CONFIG["agent_ids"] = [4, 5]
        CONFIG["sim_days"] = 1
        CONFIG["stateful"] = False
        CONFIG["simulate_realtime"] = False
        CONFIG["seconds_per_day"] = 1
        CONFIG["pipeline"] = {"agent_step": list(agent_step_order)}
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
        sim.AGENT_IDS = [4, 5]
        sim.SIM_DAYS = 1
        sim.STATEFUL = False
        sim.SIMULATE_REALTIME = False
        sim.SECONDS_PER_DAY = 1
        sim.NEWS_ENABLED = False
        sim.INTERVENTION_ENABLED = False
        sim.HUMAN_REALISM_ENABLED = False
        sim.VISUALIZATION_ENABLED = False
        sim.LIFE_EVENTS_ENABLED = False

    def test_reflect_ablation_makes_zero_reflection_llm_calls(self) -> None:
        import generative_city_sim as sim

        order = [n for n in DEFAULT_AGENT_STEP_ORDER if n != "reflect"]
        self._patch_config(order)
        self._patch_module_constants(sim)

        with install() as mock:
            sim.run_simulation()

        self.assertEqual(
            mock.call_count("reflection"),
            0,
            "reflect stage removed but reflection LLM calls still happened",
        )
        # The rest of the loop still ran: planning calls happened as usual.
        self.assertGreater(mock.call_count("planning"), 0)

    def test_custom_stage_inserted_by_path_runs_per_step(self) -> None:
        import generative_city_sim as sim

        order = list(DEFAULT_AGENT_STEP_ORDER)
        # Insert after perceive so the stage can see step["_perception"].
        order.insert(
            order.index("perceive") + 1,
            "tests.test_pipeline_ablation:tracing_stage",
        )
        self._patch_config(order)
        self._patch_module_constants(sim)

        with install():
            sim.run_simulation()

        self.assertGreater(len(STAGE_TRACE), 0, "custom stage never ran")
        seen_agents = {entry["agent_id"] for entry in STAGE_TRACE}
        self.assertEqual(seen_agents, {4, 5})
        self.assertTrue(all(entry["has_perception"] for entry in STAGE_TRACE))
        self.assertTrue(all(entry["clock_day"] == 1 for entry in STAGE_TRACE))


if __name__ == "__main__":
    unittest.main()
