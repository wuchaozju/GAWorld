"""Unit tests for gaworld.sim.pipeline.StagePipeline (K2)."""

from __future__ import annotations

import unittest

from gaworld.sim.pipeline import DEFAULT_AGENT_STEP_ORDER, StagePipeline

TRACE: list[str] = []


def custom_stage(agent, step, ctx):
    TRACE.append("custom")
    step["custom_ran"] = True


def _builtin(name):
    def stage(agent, step, ctx):
        TRACE.append(name)
        step.setdefault("ran", []).append(name)

    return stage


BUILTIN = {name: _builtin(name) for name in DEFAULT_AGENT_STEP_ORDER}


class TestStagePipeline(unittest.TestCase):
    def setUp(self):
        TRACE.clear()

    def test_default_order(self):
        pipe = StagePipeline.from_config(None, BUILTIN)
        self.assertEqual(pipe.stage_names, list(DEFAULT_AGENT_STEP_ORDER))
        step = pipe.run_step({"id": 1}, {}, None)
        self.assertEqual(step["ran"], list(DEFAULT_AGENT_STEP_ORDER))

    def test_ablation_removes_stage(self):
        order = [n for n in DEFAULT_AGENT_STEP_ORDER if n != "reflect"]
        pipe = StagePipeline.from_config({"agent_step": order}, BUILTIN)
        step = pipe.run_step({"id": 1}, {}, None)
        self.assertNotIn("reflect", step["ran"])
        self.assertEqual(len(step["ran"]), len(DEFAULT_AGENT_STEP_ORDER) - 1)

    def test_custom_stage_by_import_path(self):
        order = ["prepare", "tests.test_sim_pipeline:custom_stage", "record"]
        pipe = StagePipeline.from_config({"agent_step": order}, BUILTIN)
        step = pipe.run_step({"id": 1}, {}, None)
        self.assertTrue(step.get("custom_ran"))
        self.assertEqual(TRACE, ["prepare", "custom", "record"])

    def test_dict_entry_with_display_name(self):
        order = [{"name": "probe", "call": "tests.test_sim_pipeline:custom_stage"}]
        pipe = StagePipeline.from_config({"agent_step": order}, BUILTIN)
        self.assertEqual(pipe.stage_names, ["probe"])

    def test_unknown_stage_skipped_with_warning(self):
        pipe = StagePipeline.from_config(
            {"agent_step": ["prepare", "no_such_stage", "record"]}, BUILTIN
        )
        self.assertEqual(pipe.stage_names, ["prepare", "record"])

    def test_zero_stages_raises(self):
        with self.assertRaises(ValueError):
            StagePipeline.from_config({"agent_step": ["nope"]}, BUILTIN)

    def test_stage_errors_propagate(self):
        def boom(agent, step, ctx):
            raise RuntimeError("stage failure")

        pipe = StagePipeline([("boom", boom)])
        with self.assertRaises(RuntimeError):
            pipe.run_step({"id": 1}, {}, None)


if __name__ == "__main__":
    unittest.main()
