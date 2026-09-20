"""Wiring tests for the InterventionPlugin (K3a migration).

The intervention subsystem used to be inlined in run_simulation; it now
rides the kernel plugin surface. These tests pin the migrated behavior:

1. enabled: the feed snippet reaches LLM prompts and
   ``output/intervention/intervention_metrics.csv`` accumulates rows;
2. disabled: the five metric keys are still seeded into ``agent["state"]``
   before the initial snapshot (schema parity with the old inline init),
   and no metrics CSV is produced.
"""

from __future__ import annotations

import csv
import importlib
import os
import shutil
import sys
import tempfile
import unittest

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

METRIC_KEYS = (
    "stance_score",
    "toxicity_score",
    "misinformation_risk",
    "cross_viewpoint_exposure",
    "intervention_reward",
)


@unittest.skipIf(_MISSING, f"missing runtime deps: {_MISSING}")
@unittest.skipUnless(_PY_OK, "requires Python 3.11+ (datetime.UTC)")
class TestInterventionPlugin(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original_cwd = os.getcwd()
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_src = os.path.join(repo_root, "data")
        if os.path.isdir(data_src):
            shutil.copytree(data_src, os.path.join(self.tmp.name, "data"))
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.original_cwd)

    def _patch_config(self, intervention_enabled: bool) -> None:
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

        CONFIG["agent_ids"] = [4, 5]
        CONFIG["sim_days"] = 1
        CONFIG["stateful"] = False
        CONFIG["simulate_realtime"] = False
        CONFIG["seconds_per_day"] = 1
        CONFIG["intervention"] = dict(CONFIG.get("intervention", {}))
        CONFIG["intervention"]["enabled"] = intervention_enabled
        CONFIG["intervention"]["output_dir"] = "output/intervention"
        for key in (
            "news", "external_environment_service", "distributed",
            "visualization", "life_events",
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
        sim.HUMAN_REALISM_ENABLED = False
        sim.VISUALIZATION_ENABLED = False
        sim.LIFE_EVENTS_ENABLED = False

    def test_enabled_feed_reaches_prompts_and_metrics_csv_written(self) -> None:
        import generative_city_sim as sim

        self._patch_config(intervention_enabled=True)
        self._patch_module_constants(sim)

        with install() as mock:
            sim.run_simulation()

        feed_prompts = [
            entry for entry in mock.calls if "平台干预推荐" in entry["prompt"]
        ]
        self.assertTrue(
            feed_prompts, "intervention feed snippet never reached an LLM prompt"
        )

        csv_path = os.path.join("output", "intervention", "intervention_metrics.csv")
        self.assertTrue(os.path.exists(csv_path), "metrics CSV not written")
        with open(csv_path, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertGreater(len(rows), 0)
        for key in METRIC_KEYS + ("day", "time", "agent_id", "feed_items"):
            self.assertIn(key, rows[0], f"metrics CSV missing column {key}")

    def test_disabled_still_seeds_metric_state_keys(self) -> None:
        import generative_city_sim as sim

        self._patch_config(intervention_enabled=False)
        self._patch_module_constants(sim)

        # The probe hook captures agent dict references at `agents.built`;
        # assertions after the run then see the (mutated) seeded state.
        captured: list = []
        from gaworld.settings import CONFIG

        CONFIG["extensions"] = dict(CONFIG.get("extensions", {}))
        hooks = dict(CONFIG["extensions"].get("hooks", {}))
        hooks["agents.built"] = ["tests.test_intervention_plugin:_probe_hook"]
        CONFIG["extensions"]["hooks"] = hooks
        global _PROBE_SINK
        _PROBE_SINK = captured

        with install():
            sim.run_simulation()

        self.assertTrue(captured, "agents.built never fired")
        for agent in captured:
            for key in METRIC_KEYS:
                self.assertIn(key, agent.get("state", {}), f"missing seeded {key}")
        self.assertFalse(
            os.path.exists(
                os.path.join("output", "intervention", "intervention_metrics.csv")
            ),
            "disabled run must not write metrics CSV",
        )


_PROBE_SINK: list = []


def _probe_hook(ctx):
    _PROBE_SINK.extend(ctx.get("agents", []))


if __name__ == "__main__":
    unittest.main()
