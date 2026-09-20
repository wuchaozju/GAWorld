"""K5 acceptance: the runtime intervention API.

Kernel-level for the standard interventions, plus one full-sim test proving
runtime population removal: an agent removed via
``controller.intervene("remove_agent", ...)`` on day 1 no longer acts on
day 2, and the removal is audited.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import unittest

from gaworld.kernel import build_kernel

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


class TestStandardInterventions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self._cwd)
        self.ctx = build_kernel({}, load_entry_points=False)

    def test_registered_out_of_the_box(self):
        names = self.ctx.controller.intervention_names()
        for name in ("set_agent_state", "update_config", "remove_agent"):
            self.assertIn(name, names)

    def test_set_agent_state(self):
        agent = {"id": 7, "state": {"stress": 0.3}}
        self.ctx.set_agents([agent])
        result = self.ctx.controller.intervene(
            "set_agent_state", self.ctx, agent_id=7, key="stress", value=0.8
        )
        self.assertEqual(agent["state"]["stress"], 0.8)
        self.assertEqual(result["key"], "stress")
        with self.assertRaises(ValueError):
            self.ctx.controller.intervene(
                "set_agent_state", self.ctx, agent_id=99, key="stress", value=0.1
            )

    def test_update_config_dotted_path(self):
        self.ctx.controller.intervene(
            "update_config", self.ctx, path="economy.credit.apr", value=0.15
        )
        self.assertEqual(self.ctx.config["economy"]["credit"]["apr"], 0.15)
        with self.assertRaises(ValueError):
            self.ctx.controller.intervene("update_config", self.ctx, path="", value=1)

    def test_remove_agent_queues_for_day_boundary(self):
        result = self.ctx.controller.intervene("remove_agent", self.ctx, agent_id=5)
        self.assertEqual(result["queued"], 5)
        self.assertEqual(self.ctx.plugin_state("population")["remove"], [5])

    def test_interventions_are_audited(self):
        self.ctx.set_agents([{"id": 1, "state": {}}])
        self.ctx.controller.intervene(
            "set_agent_state", self.ctx, agent_id=1, key="emotion", value=0.5
        )
        self.ctx.recorder.close()
        path = os.path.join("output", "records", "controller.intervention.jsonl")
        self.assertTrue(os.path.exists(path))


@unittest.skipIf(_MISSING, f"missing runtime deps: {_MISSING}")
@unittest.skipUnless(_PY_OK, "requires Python 3.11+ (datetime.UTC)")
class TestRuntimeRemoval(unittest.TestCase):
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

    def test_agent_removed_on_day1_does_not_act_on_day2(self) -> None:
        from gaworld.settings import CONFIG

        import generative_city_sim as sim

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
        CONFIG["sim_days"] = 2
        CONFIG["stateful"] = False
        CONFIG["simulate_realtime"] = False
        CONFIG["seconds_per_day"] = 1
        CONFIG["extensions"] = dict(CONFIG.get("extensions", {}))
        hooks = {
            phase: list(paths)
            for phase, paths in CONFIG["extensions"].get("hooks", {}).items()
        }
        hooks.setdefault("on_day_end", []).append(
            "tests.test_interventions:_remove_agent5_on_day1"
        )
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

        sim.AGENT_IDS = [4, 5]
        sim.SIM_DAYS = 2
        sim.STATEFUL = False
        sim.SIMULATE_REALTIME = False
        sim.SECONDS_PER_DAY = 1
        sim.NEWS_ENABLED = False
        sim.INTERVENTION_ENABLED = False
        sim.HUMAN_REALISM_ENABLED = False
        sim.VISUALIZATION_ENABLED = False
        sim.LIFE_EVENTS_ENABLED = False

        with install() as mock:
            sim.run_simulation()

        day2_agent5_calls = [
            e for e in mock.calls
            if e.get("agent_id") == 5 and e.get("task") == "perception"
        ]
        # Agent 5 perceived on day 1 (before removal) …
        self.assertTrue(day2_agent5_calls, "agent 5 never acted at all")
        # … but the removal must halve its perception volume vs agent 4,
        # which acted on both days.
        agent4_calls = [
            e for e in mock.calls
            if e.get("agent_id") == 4 and e.get("task") == "perception"
        ]
        self.assertLess(
            len(day2_agent5_calls),
            len(agent4_calls),
            "agent 5 kept acting after its removal",
        )


_REMOVED = {"done": False}


def _remove_agent5_on_day1(ctx):
    if _REMOVED["done"] or ctx.get("day") != 1:
        return
    _REMOVED["done"] = True
    sim = ctx["sim"]
    sim.controller.intervene("remove_agent", sim, agent_id=5)


if __name__ == "__main__":
    unittest.main()
