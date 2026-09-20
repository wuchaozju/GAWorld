"""End-to-end proof of the K1/K2 plugin chain.

A plugin declared **only in CONFIG["plugins"]** (no simulator source edits)
must, during a real 1-day mock-LLM ``run_simulation``:

1. be assembled by the PluginRegistry and have ``setup``/``teardown`` called,
2. contribute a perception snippet via the ``perception.compose`` collect
   hook and see it reach an LLM prompt,
3. observe/rewrite selected actions via the ``action.selected`` filter hook.

This is the acceptance test for "新增子系统零侵入" — if it passes, a third
party can extend GAWorld cognition without touching generative_city_sim.py.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import unittest

from gaworld.kernel import Plugin

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

PERCEPTION_MARKER = "内核探针广播-KERNELPROBE"

# Module-level so the plugin instance created by the registry (from the
# class path string) can report back to the test.
PROBE: dict = {}


class ProbePlugin(Plugin):
    """Test plugin loaded via CONFIG["plugins"] class path."""

    id = "probe"

    def setup(self, ctx):
        PROBE["setup"] = PROBE.get("setup", 0) + 1
        PROBE["active_at_setup"] = list(ctx.registry.ids())
        ctx.bus.on("perception.compose", self._contribute_perception)
        ctx.bus.on("action.selected", self._filter_action)

    def teardown(self, ctx):
        PROBE["teardown"] = PROBE.get("teardown", 0) + 1

    def _contribute_perception(self, hook_ctx):
        PROBE["perception_calls"] = PROBE.get("perception_calls", 0) + 1
        PROBE.setdefault("perception_ctx_keys", set()).update(hook_ctx.keys())
        return [PERCEPTION_MARKER]

    def _filter_action(self, value, hook_ctx):
        PROBE.setdefault("actions_seen", []).append(str(value))
        return value  # observe-only rewrite; keep behavior unchanged


@unittest.skipIf(_MISSING, f"missing runtime deps: {_MISSING}")
@unittest.skipUnless(_PY_OK, "requires Python 3.11+ (datetime.UTC)")
class TestPluginEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        PROBE.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original_cwd = os.getcwd()
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_src = os.path.join(repo_root, "data")
        if os.path.isdir(data_src):
            shutil.copytree(data_src, os.path.join(self.tmp.name, "data"))
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.original_cwd)

    def _patch_config(self) -> None:
        from gaworld.settings import CONFIG

        originals: dict[str, object] = {}
        touched = (
            "agent_ids", "sim_days", "stateful", "simulate_realtime",
            "seconds_per_day", "news", "human_realism", "intervention",
            "external_environment_service", "distributed", "visualization",
            "life_events", "external_rag", "plugins",
        )
        for key in touched:
            if key in CONFIG:
                originals[key] = CONFIG[key]

        def _restore() -> None:
            CONFIG.pop("plugins", None)
            for k, v in originals.items():
                CONFIG[k] = v

        self.addCleanup(_restore)

        CONFIG["agent_ids"] = [4, 5]
        CONFIG["sim_days"] = 1
        CONFIG["stateful"] = False
        CONFIG["simulate_realtime"] = False
        CONFIG["seconds_per_day"] = 1
        # The line under test: plugin assembly purely from config.
        CONFIG["plugins"] = [{"class": "tests.test_kernel_plugin_e2e:ProbePlugin"}]
        for key, flag in (
            ("news", "enabled"),
            ("intervention", "enabled"),
            ("external_environment_service", "enabled"),
            ("distributed", "enabled"),
            ("visualization", "enabled"),
            ("life_events", "enabled"),
        ):
            if isinstance(CONFIG.get(key), dict):
                CONFIG[key] = dict(CONFIG[key])
                CONFIG[key][flag] = False
        if isinstance(CONFIG.get("news"), dict):
            CONFIG["news"]["info_seek"] = dict(CONFIG["news"].get("info_seek", {}))
            CONFIG["news"]["info_seek"]["enabled"] = False
        if isinstance(CONFIG.get("external_rag"), dict):
            CONFIG["external_rag"] = dict(CONFIG["external_rag"])
            CONFIG["external_rag"]["bootstrap"] = dict(
                CONFIG["external_rag"].get("bootstrap", {})
            )
            CONFIG["external_rag"]["bootstrap"]["enabled"] = False

    def test_config_declared_plugin_participates_in_cognition(self) -> None:
        import generative_city_sim as sim

        self._patch_config()
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
        # This test exercises the fine-grained tick loop; force off the
        # long-run fast-forward mode in case a local dashboard_config.json
        # enabled it (that would skip the tick pipeline entirely).
        sim.LONG_RUN_ENABLED = False

        with install() as mock:
            sim.run_simulation()

        # 1. Lifecycle: assembled from config, setup + teardown ran once.
        self.assertEqual(PROBE.get("setup"), 1)
        self.assertEqual(PROBE.get("teardown"), 1)
        self.assertIn("probe", PROBE.get("active_at_setup", []))

        # 2. perception.compose fired per agent-step with the documented
        #    context keys, and the contribution reached an LLM prompt.
        self.assertGreater(PROBE.get("perception_calls", 0), 0)
        self.assertLessEqual(
            {"agent", "day", "time_str", "scheduled_activity", "sim"},
            PROBE.get("perception_ctx_keys", set()),
        )
        marker_prompts = [
            entry for entry in mock.calls if PERCEPTION_MARKER in entry["prompt"]
        ]
        self.assertTrue(
            marker_prompts,
            "plugin perception snippet never reached an LLM prompt",
        )

        # 3. action.selected saw every chosen action.
        self.assertGreater(len(PROBE.get("actions_seen", [])), 0)


if __name__ == "__main__":
    unittest.main()
