"""End-to-end proof that the twin stages run inside a real simulation tick.

Why this exists
---------------
``tests/test_twin_stages.py`` verifies ``twin_mirror`` against a hand-built
step dict and a stand-in ``move``. That proves the logic but NOT the
integration: if a ``step`` key is renamed, if ``CONFIG["pipeline"]`` stops
being read, or if the ``"module:function"`` entry fails to resolve, the unit
tests still pass and the mirror silently does nothing.

This test runs the real :func:`generative_city_sim.run_simulation` against a
mocked LLM with the twin stages configured, then asserts the intervention
audit trail actually contains a mirror write. It is the only test that would
fail if the pipeline integration broke.

Follows the environment guards of ``tests/test_e2e_smoke.py``: sandboxes
missing networkx/matplotlib SKIP rather than fail.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
import time
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

TWIN_AGENT_ID = 4
MIRROR_NODE = "twin-test-node"


@unittest.skipIf(_MISSING, f"missing runtime deps: {_MISSING}")
@unittest.skipUnless(_PY_OK, "requires Python 3.11+ (datetime.UTC)")
class TestTwinPipelineIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original_cwd = os.getcwd()
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_src = os.path.join(repo_root, "data")
        data_dst = os.path.join(self.tmp.name, "data")
        if os.path.isdir(data_src):
            shutil.copytree(data_src, data_dst)
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.original_cwd)

    def _seed_twin_report(self) -> None:
        """Write a snapshot fresh enough for the mirror to apply."""
        from gaworld.twin import store

        store.append_reports(
            TWIN_AGENT_ID,
            [
                {
                    "report_id": "e2e-1",
                    # Real wall-clock time: the mirror's freshness check runs
                    # against time.time(), not the simulation clock.
                    "ts": time.time(),
                    "tz_offset": 480,
                    "loc": {"lat": 30.2741, "lng": 120.1551, "acc_m": 8, "source": "gps"},
                    "grid": {"x": 0.0, "y": 0.0},
                    "node_id": MIRROR_NODE,
                    "snap_km": 0.1,
                    "out_of_map": False,
                    "action_tag": "work",
                    "note": "端到端验证",
                }
            ],
            root="output/twin",
        )

    def _patch_config(self) -> None:
        from gaworld.settings import CONFIG

        originals: dict[str, object] = {}
        for key in (
            "agent_ids", "sim_days", "stateful", "simulate_realtime",
            "seconds_per_day", "news", "human_realism", "intervention",
            "external_environment_service", "distributed", "visualization",
            "life_events", "external_rag", "twin", "pipeline",
        ):
            if key in CONFIG:
                originals[key] = CONFIG[key]

        def _restore() -> None:
            for key in list(CONFIG):
                if key in originals:
                    CONFIG[key] = originals[key]
            # `pipeline` and `twin` may not have existed before; drop the
            # overrides so later tests see a pristine CONFIG.
            for key in ("pipeline", "twin"):
                if key not in originals:
                    CONFIG.pop(key, None)

        self.addCleanup(_restore)

        CONFIG["agent_ids"] = [TWIN_AGENT_ID]
        CONFIG["sim_days"] = 1
        CONFIG["stateful"] = False
        CONFIG["simulate_realtime"] = False
        CONFIG["seconds_per_day"] = 1
        for key in ("news", "external_rag", "intervention",
                    "external_environment_service", "distributed",
                    "visualization", "life_events"):
            if isinstance(CONFIG.get(key), dict):
                CONFIG[key] = dict(CONFIG[key])
                CONFIG[key]["enabled"] = False
        if isinstance(CONFIG.get("news"), dict):
            CONFIG["news"]["info_seek"] = {"enabled": False}
        if isinstance(CONFIG.get("external_rag"), dict):
            CONFIG["external_rag"]["bootstrap"] = {"enabled": False}

        CONFIG["twin"] = {
            "enabled": True,
            "root": "output/twin",
            "bindings_path": "data/twin_bindings.json",
            "snapshot_ttl_minutes": 30,
            "max_snap_km": 3.0,
        }
        # The ordering documented in the spec and Plan 2.
        CONFIG["pipeline"] = {
            "agent_step": [
                "prepare", "perceive", "gaworld.twin.stages:twin_perceive",
                "interrupts", "plan", "adjust_activity", "move", "select_action",
                "gaworld.twin.stages:twin_mirror", "reflect", "update_state",
                "broadcast", "memorize", "record",
            ]
        }

    def test_mirror_fires_inside_a_real_run(self) -> None:
        import generative_city_sim as sim

        self._seed_twin_report()
        self._patch_config()

        sim.AGENT_IDS = [TWIN_AGENT_ID]
        sim.SIM_DAYS = 1
        sim.STATEFUL = False
        sim.SIMULATE_REALTIME = False
        sim.SECONDS_PER_DAY = 1
        sim.NEWS_ENABLED = False
        sim.INTERVENTION_ENABLED = False
        sim.HUMAN_REALISM_ENABLED = False
        sim.VISUALIZATION_ENABLED = False
        sim.LIFE_EVENTS_ENABLED = False
        sim.LONG_RUN_ENABLED = False

        with install():
            try:
                sim.run_simulation()
            except SystemExit as exc:
                self.fail(f"run_simulation exited unexpectedly: {exc}")

        audit_path = os.path.join("output", "records", "controller.intervention.jsonl")
        self.assertTrue(
            os.path.exists(audit_path),
            "no intervention audit file — the mirror never reached the controller",
        )
        with open(audit_path, "r", encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]

        mirror_rows = [
            row for row in rows
            if (row.get("data") or row).get("name") == "set_agent_twin_state"
        ]
        self.assertTrue(
            mirror_rows,
            f"twin_mirror never fired in a real tick; audit rows: {rows[:5]}",
        )

        # The audited write must carry the real location, not a simulated one.
        payloads = [(row.get("data") or row).get("kwargs", {}) for row in mirror_rows]
        self.assertTrue(
            any(p.get("location") == MIRROR_NODE for p in payloads),
            f"mirror fired but did not carry the reported node: {payloads[:3]}",
        )


if __name__ == "__main__":
    unittest.main()
