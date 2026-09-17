"""End-to-end smoke for :func:`generative_city_sim.run_simulation`.

What it asserts
---------------
With a mocked LLM, ``sim_days=1`` over the first two configured agents,
``stateful=False`` (so no prior memory leaks in), the simulator must:

* finish without raising,
* produce the expected per-agent artefacts under ``output/``,
* dispatch at least the canonical task names through ``call_llm``.

What it does *not* assert
-------------------------
* Specific prompt contents (those are subject to refactor).
* Numerical agent state values (LLM determinism is approximated via the
  mock — if a default response changes, downstream values drift).
* Absolute file sizes.

Test environment
----------------
The simulator imports ``networkx`` and ``matplotlib`` at module load
time, plus uses ``datetime.UTC`` (Python 3.11+). Sandboxes that lack
those dependencies will see this test SKIPPED, not failed. CI installs
the full ``requirements.txt`` so it always runs there.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.fixtures.mock_llm import MockLLM, install


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
class TestRunSimulationSmoke(unittest.TestCase):
    """Run a 1-day, 2-agent simulation against the mock LLM."""

    def setUp(self) -> None:
        # Each test gets its own working directory so the simulator's
        # output/ writes are isolated.
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original_cwd = os.getcwd()
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Copy the fixture data the simulator needs into the temp dir.
        data_src = os.path.join(repo_root, "data")
        data_dst = os.path.join(self.tmp.name, "data")
        if os.path.isdir(data_src):
            shutil.copytree(data_src, data_dst)
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.original_cwd)

    def _patch_config(self) -> None:
        """Override CONFIG to keep the run short and deterministic."""
        from gaworld.settings import CONFIG

        # Snapshot keys we'll mutate so cleanup can restore them.
        originals: dict[str, object] = {}
        for key in (
            "agent_ids",
            "sim_days",
            "stateful",
            "simulate_realtime",
            "seconds_per_day",
            "news",
            "human_realism",
            "intervention",
            "external_environment_service",
            "distributed",
            "visualization",
            "life_events",
            "external_rag",
        ):
            if key in CONFIG:
                originals[key] = CONFIG[key]

        def _restore() -> None:
            for k, v in originals.items():
                CONFIG[k] = v

        self.addCleanup(_restore)

        # Smoke run shape.
        CONFIG["agent_ids"] = [4, 5]  # two of the seeded agents
        CONFIG["sim_days"] = 1
        CONFIG["stateful"] = False
        CONFIG["simulate_realtime"] = False
        CONFIG["seconds_per_day"] = 1
        # Disable I/O-heavy side branches that aren't part of the smoke.
        if isinstance(CONFIG.get("news"), dict):
            CONFIG["news"] = dict(CONFIG["news"])
            CONFIG["news"]["enabled"] = False
            CONFIG["news"]["info_seek"] = dict(CONFIG["news"].get("info_seek", {}))
            CONFIG["news"]["info_seek"]["enabled"] = False
        if isinstance(CONFIG.get("external_rag"), dict):
            CONFIG["external_rag"] = dict(CONFIG["external_rag"])
            CONFIG["external_rag"]["bootstrap"] = dict(
                CONFIG["external_rag"].get("bootstrap", {})
            )
            CONFIG["external_rag"]["bootstrap"]["enabled"] = False
        if isinstance(CONFIG.get("intervention"), dict):
            CONFIG["intervention"] = dict(CONFIG["intervention"])
            CONFIG["intervention"]["enabled"] = False
        if isinstance(CONFIG.get("external_environment_service"), dict):
            CONFIG["external_environment_service"] = dict(
                CONFIG["external_environment_service"]
            )
            CONFIG["external_environment_service"]["enabled"] = False
        if isinstance(CONFIG.get("distributed"), dict):
            CONFIG["distributed"] = dict(CONFIG["distributed"])
            CONFIG["distributed"]["enabled"] = False
        if isinstance(CONFIG.get("visualization"), dict):
            CONFIG["visualization"] = dict(CONFIG["visualization"])
            CONFIG["visualization"]["enabled"] = False
        if isinstance(CONFIG.get("life_events"), dict):
            CONFIG["life_events"] = dict(CONFIG["life_events"])
            CONFIG["life_events"]["enabled"] = False

    def test_run_one_day_two_agents(self) -> None:
        # Defer the heavy import until after deps have been confirmed.
        import generative_city_sim as sim

        self._patch_config()

        # Re-read the module-level CONFIG-derived constants the
        # simulator captured at import time.
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
        # This smoke exercises the fine-grained tick loop; force off the
        # long-run fast-forward mode in case a local dashboard_config.json
        # enabled it (that path skips the per-tick planning/reflection tasks
        # this test asserts on).
        sim.LONG_RUN_ENABLED = False

        with install() as mock:
            try:
                sim.run_simulation()
            except SystemExit as exc:
                # Some CLI failure modes call sys.exit; surface with context.
                self.fail(f"run_simulation exited unexpectedly: {exc}")

        # The simulator must dispatch at least these tasks per day.
        seen = set(mock.tasks_seen())
        # We expect one of {'schedule', 'daily_routine'} for routine
        # generation, and at least one of {'planning', 'reflection',
        # 'perception', 'daily_diary'} per agent-day.
        self.assertTrue(
            seen & {"schedule", "daily_routine"},
            f"expected routine task in {seen}",
        )
        self.assertTrue(
            seen & {"planning", "reflection", "perception", "daily_diary"},
            f"expected per-step task in {seen}",
        )

        # Per-agent log files should exist, wherever the config points them —
        # a selected city moves the whole run tree under output/cities/<slug>/.
        from gaworld.settings import CONFIG

        log_dir = os.path.join(self.tmp.name, CONFIG.get("log_dir", "output/logs"))
        self.assertTrue(os.path.isdir(log_dir), f"{log_dir} not created")
        for aid in (4, 5):
            log_path = os.path.join(log_dir, f"agent_{aid}.log")
            self.assertTrue(os.path.exists(log_path), f"missing {log_path}")
            self.assertGreater(os.path.getsize(log_path), 0, f"empty {log_path}")


class TestEnvOnlySmokeShape(unittest.TestCase):
    """Always-runnable shape check: confirm the smoke test module
    parses and the dependency-skip logic is wired correctly."""

    def test_skip_logic_explains_missing_deps(self):
        # If we are in a sandbox missing networkx, the docstring above
        # promises a SKIP rather than a hard failure. This test fails
        # only if someone removes the skip decorators by accident.
        import inspect

        source = inspect.getsource(TestRunSimulationSmoke)
        self.assertIn("@unittest.skipIf", source)
        self.assertIn("@unittest.skipUnless", source)


if __name__ == "__main__":
    unittest.main()
