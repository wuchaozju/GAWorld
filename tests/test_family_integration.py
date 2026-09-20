"""End-to-end: a real ``run_simulation`` produces families that are lived in.

The unit tests in ``test_family.py`` pin each piece in isolation. This one
answers the question those cannot: do the hooks actually fire, in the right
order, inside the real simulator loop? Specifically —

* households exist and reach the agents (``agent["family"]``);
* an in-sim couple genuinely shares one ``home`` node;
* kin ties survive the relationship reset / roster bootstrap that happens
  *after* ``agents.built`` (the ordering trap the plugin is built around);
* the family reaches the LLM prompts, not just the data structures;
* day-end household billing charges the economy.

Harness mirrors ``tests/test_action_gate.py``: temp cwd, mocked LLM,
one short day.
"""

from __future__ import annotations

import importlib
import json
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

# Enough agents (and enough of them married) that at least one in-sim couple
# is guaranteed by the default marital bands.
AGENT_IDS = [13, 16, 21, 28, 15, 42]


@unittest.skipIf(_MISSING, f"missing runtime deps: {_MISSING}")
@unittest.skipUnless(_PY_OK, "requires Python 3.11+ (datetime.UTC)")
class TestFamilyEndToEnd(unittest.TestCase):
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
        self._patch_config()

    def _patch_config(self) -> None:
        from gaworld.settings import CONFIG

        touched = (
            "agent_ids", "sim_days", "stateful", "simulate_realtime",
            "seconds_per_day", "news", "intervention",
            "external_environment_service", "distributed", "visualization",
            "external_rag", "family", "human_realism",
        )
        originals = {k: CONFIG[k] for k in touched if k in CONFIG}

        def _restore() -> None:
            CONFIG.pop("plugins", None)
            for key, value in originals.items():
                CONFIG[key] = value

        self.addCleanup(_restore)

        CONFIG["agent_ids"] = list(AGENT_IDS)
        CONFIG["sim_days"] = 1
        CONFIG["stateful"] = False
        CONFIG["simulate_realtime"] = False
        CONFIG["seconds_per_day"] = 1
        for key in ("news", "intervention", "external_environment_service",
                    "distributed", "visualization"):
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
        # The off-screen roster (and therefore the family/roster reconciliation
        # this test checks) is gated on human_realism. Set it explicitly rather
        # than inheriting whatever an earlier test left on the module.
        CONFIG["human_realism"] = dict(CONFIG.get("human_realism", {}))
        CONFIG["human_realism"]["enabled"] = True

    def _patch_module_constants(self, sim) -> None:
        """Pin the simulator's module-level constants — and restore them.

        These are module globals, so a test that only sets them leaks into
        every later test in the same process (and inherits whatever an
        earlier one left behind).
        """
        pinned = {
            "AGENT_IDS": list(AGENT_IDS),
            "SIM_DAYS": 1,
            "STATEFUL": False,
            "SIMULATE_REALTIME": False,
            "SECONDS_PER_DAY": 1,
            "NEWS_ENABLED": False,
            "INTERVENTION_ENABLED": False,
            "VISUALIZATION_ENABLED": False,
            "LONG_RUN_ENABLED": False,
            "HUMAN_REALISM_ENABLED": True,
            "LIFE_EVENTS_ENABLED": True,
        }
        originals = {name: getattr(sim, name) for name in pinned if hasattr(sim, name)}
        self.addCleanup(lambda: [setattr(sim, k, v) for k, v in originals.items()])
        for name, value in pinned.items():
            setattr(sim, name, value)

    def _read_records(self, table):
        path = os.path.join("output", "records", f"{table}.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def test_family_survives_a_real_run(self) -> None:
        import generative_city_sim as sim

        self._patch_module_constants(sim)
        with install() as mock:
            sim.run_simulation()

        households = self._read_records("family.household")
        self.assertTrue(households, "no households were recorded")
        self.assertEqual(
            sorted(aid for hh in households for aid in hh["agent_ids"]),
            sorted(AGENT_IDS),
            "every agent must land in exactly one household",
        )

        # An in-sim couple shares a home node. This is the difference between
        # a family and two strangers with matching addresses.
        shared = [hh for hh in households if len(hh["agent_ids"]) > 1]
        self.assertTrue(shared, "expected at least one multi-agent household")
        for household in shared:
            self.assertTrue(household["home"], "a shared household needs a home node")

        # The family reached the prompts, not just the data structures.
        family_prompts = [c["prompt"] for c in mock.calls if "家庭状况：" in c["prompt"]]
        self.assertTrue(family_prompts, "family never reached an LLM prompt")

        # Kin ties survived the post-`agents.built` relationship reset and the
        # off-screen roster bootstrap.
        kin_prompts = [
            c for c in mock.calls
            if c.get("task") == "social_backstory" and "不要**再编造配偶" in c["prompt"]
        ]
        self.assertTrue(kin_prompts, "roster bootstrap was not told about the family")

    def test_the_dashboard_api_can_read_what_the_run_recorded(self) -> None:
        """The card's backend parses the recorder output directly, so the
        shape the plugin writes and the shape the panel expects have to be
        checked against each other — unit tests on either side alone would
        both stay green while the panel showed nothing."""
        import generative_city_sim as sim
        from gaworld.apps import dashboard_server as ds
        from gaworld.apps import family_api

        self._patch_module_constants(sim)
        with install():
            sim.run_simulation()

        original = ds.RECORDS_DIR
        self.addCleanup(lambda: setattr(ds, "RECORDS_DIR", original))
        ds.RECORDS_DIR = os.path.join(os.getcwd(), "output", "records")

        payload, status = family_api.handle_get("/api/family/overview", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["available"], "the panel would render an empty card")
        self.assertEqual(
            sorted(a["agent_id"] for a in payload["agents"]),
            sorted(AGENT_IDS),
        )
        for row in payload["agents"]:
            self.assertTrue(row["household_id"])
            self.assertTrue(row["household_type"])
            self.assertTrue(row["marital_status"])
            self.assertIsInstance(row["members"], list)
        self.assertTrue(
            any(row["brief"] for row in payload["agents"]),
            "at least one resident should have a rendered family brief",
        )

    def test_household_billing_hits_the_economy(self) -> None:
        import generative_city_sim as sim
        from gaworld.settings import CONFIG

        # Make sure at least one household has an expensive dependant, so the
        # assertion is about the wiring rather than about the dice.
        CONFIG["family"] = dict(CONFIG["family"])
        CONFIG["family"]["fertility"] = dict(CONFIG["family"]["fertility"])
        CONFIG["family"]["fertility"]["p_any_child"] = [{"age": [0, 200], "p": 1.0}]
        self._patch_module_constants(sim)

        with install():
            sim.run_simulation()

        rows = self._read_records("family.finance")
        self.assertTrue(rows, "day-end household settlement never ran")
        self.assertGreater(
            sum(float(r.get("dependant_cost", 0)) for r in rows),
            0.0,
            "households with children must be billed",
        )


if __name__ == "__main__":
    unittest.main()
