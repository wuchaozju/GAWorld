"""Wiring tests for the SkillsPlugin (K3c migration).

Skill injection used to be hard-wired inside ``_cognition.perception`` and
skill distillation inside ``memory.lifecycle``; both now ride the plugin
surface. Pinned here:

1. an agent with an attached global skill gets the "你已经掌握的小技能"
   block inside a perception prompt (via ``perception.sections``);
2. ``inject_into_cognition=False`` suppresses the block;
3. skill consolidation runs per agent on the ``memory.consolidate`` event
   honoring the configured cadence.
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

SKILL_MARKER = "你已经掌握的小技能"


def attach_skill_hook(ctx):
    """agents.built hook: attach a global skill to every agent."""
    for agent in ctx.get("agents", []):
        agent["skill_ids"] = ["poster-layout-grid"]


@unittest.skipIf(_MISSING, f"missing runtime deps: {_MISSING}")
@unittest.skipUnless(_PY_OK, "requires Python 3.11+ (datetime.UTC)")
class TestSkillsPlugin(unittest.TestCase):
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
        from gaworld.skills.registry import reset_default_registry

        reset_default_registry()
        self.addCleanup(reset_default_registry)

    def _patch_config(
        self,
        *,
        inject: bool = True,
        attach_hook: bool = True,
        skill_consolidation: dict | None = None,
    ) -> None:
        from gaworld.settings import CONFIG

        originals: dict[str, object] = {}
        touched = (
            "agent_ids", "sim_days", "stateful", "simulate_realtime",
            "seconds_per_day", "news", "intervention", "extensions",
            "skills", "memory",
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
        CONFIG["skills"] = dict(CONFIG.get("skills", {}))
        CONFIG["skills"]["inject_into_cognition"] = inject
        CONFIG["memory"] = dict(CONFIG.get("memory", {}))
        CONFIG["memory"]["skill_consolidation"] = skill_consolidation or {
            "enabled": False
        }
        if attach_hook:
            CONFIG["extensions"] = dict(CONFIG.get("extensions", {}))
            hooks = {
                phase: list(paths)
                for phase, paths in CONFIG["extensions"].get("hooks", {}).items()
            }
            hooks.setdefault("agents.built", []).append(
                "tests.test_skills_plugin:attach_skill_hook"
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

    def test_attached_skill_reaches_perception_prompt(self) -> None:
        import generative_city_sim as sim

        self._patch_config(inject=True)
        self._patch_module_constants(sim)

        with install() as mock:
            sim.run_simulation()

        perception_prompts = [
            e["prompt"] for e in mock.calls if e["task"] == "perception"
        ]
        self.assertTrue(perception_prompts)
        self.assertTrue(
            any(SKILL_MARKER in p for p in perception_prompts),
            "attached skill block never reached a perception prompt",
        )

    def test_injection_disabled_suppresses_block(self) -> None:
        import generative_city_sim as sim

        self._patch_config(inject=False)
        self._patch_module_constants(sim)

        with install() as mock:
            sim.run_simulation()

        self.assertFalse(
            any(SKILL_MARKER in e["prompt"] for e in mock.calls),
            "skill block injected although inject_into_cognition=False",
        )

    def test_consolidation_runs_on_memory_consolidate_event(self) -> None:
        import generative_city_sim as sim

        self._patch_config(
            attach_hook=False,
            skill_consolidation={"enabled": True, "every_days": 1},
        )
        self._patch_module_constants(sim)

        calls: list = []

        def fake_consolidation(agent, llm=None, today=None):
            calls.append({"agent_id": agent.get("id"), "day": today})
            return None

        with install(), patch(
            "gaworld.skills.consolidation.run_skill_consolidation",
            fake_consolidation,
        ):
            sim.run_simulation()

        self.assertEqual(
            calls,
            [{"agent_id": 4, "day": 1}],
            "skill consolidation did not run exactly once per agent-day",
        )


if __name__ == "__main__":
    unittest.main()
