"""K4 acceptance: the Controller's move-validation gate, end to end.

Design-doc acceptance criterion: inject a "go to a nonexistent place"
action and observe deny + perception feedback. A config-declared plugin
rewrites every resolved location to a bogus one via ``location.resolve``;
the ``location_exists`` validator (LocalPhysicalPlugin, on by default) must:

1. deny the move (audited in ``output/records/action.denied.jsonl``),
2. keep the agent where it is (move_agent falls back to the origin),
3. surface "刚才的行动受阻…并不存在" in the agent's next perception prompt.

The control test pins the other side: a normal run produces zero denials —
``location_exists`` is a safety net, not a behavior change.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import unittest
import tempfile

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

BOGUS_LOCATION = "海市蜃楼大厦"


class BogusLocationPlugin(Plugin):
    """Test plugin: rewrite every resolved location to a nonexistent one."""

    id = "bogus_location"

    def setup(self, ctx):
        ctx.bus.on("location.resolve", self._rewrite)

    def _rewrite(self, value, hook_ctx):
        return BOGUS_LOCATION if value else None


@unittest.skipIf(_MISSING, f"missing runtime deps: {_MISSING}")
@unittest.skipUnless(_PY_OK, "requires Python 3.11+ (datetime.UTC)")
class TestActionGate(unittest.TestCase):
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

    def _patch_config(self, *, bogus_plugin: bool) -> None:
        from gaworld.settings import CONFIG

        originals: dict[str, object] = {}
        touched = (
            "agent_ids", "sim_days", "stateful", "simulate_realtime",
            "seconds_per_day", "news", "intervention", "plugins",
            "external_environment_service", "distributed", "visualization",
            "life_events", "external_rag",
        )
        for key in touched:
            if key in CONFIG:
                originals[key] = CONFIG[key]

        def _restore() -> None:
            CONFIG.pop("plugins", None)
            for k, v in originals.items():
                CONFIG[k] = v

        self.addCleanup(_restore)

        CONFIG["agent_ids"] = [4]
        CONFIG["sim_days"] = 1
        CONFIG["stateful"] = False
        CONFIG["simulate_realtime"] = False
        CONFIG["seconds_per_day"] = 1
        if bogus_plugin:
            CONFIG["plugins"] = [
                {"class": "tests.test_action_gate:BogusLocationPlugin"}
            ]
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
        # The action gate lives in the per-tick pipeline; force off long-run
        # fast-forward (which skips the tick loop) in case a local
        # dashboard_config.json enabled it.
        sim.LONG_RUN_ENABLED = False

    def test_nonexistent_destination_denied_and_fed_back(self) -> None:
        import generative_city_sim as sim

        self._patch_config(bogus_plugin=True)
        self._patch_module_constants(sim)

        with install() as mock:
            sim.run_simulation()

        denied_path = os.path.join("output", "records", "action.denied.jsonl")
        self.assertTrue(os.path.exists(denied_path), "denials were not audited")
        with open(denied_path, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        self.assertGreater(len(rows), 0)
        self.assertEqual(rows[0]["action"], "move")
        self.assertIn(BOGUS_LOCATION, rows[0]["reason"])

        feedback_prompts = [
            e["prompt"]
            for e in mock.calls
            if "刚才的行动受阻" in e["prompt"] and BOGUS_LOCATION in e["prompt"]
        ]
        self.assertTrue(
            feedback_prompts,
            "denial reason never reached a subsequent perception prompt",
        )

    def test_normal_run_produces_zero_denials(self) -> None:
        import generative_city_sim as sim

        self._patch_config(bogus_plugin=False)
        self._patch_module_constants(sim)

        with install():
            sim.run_simulation()

        self.assertFalse(
            os.path.exists(os.path.join("output", "records", "action.denied.jsonl")),
            "location_exists must never fire in normal operation",
        )


if __name__ == "__main__":
    unittest.main()
