"""Tests for the memory lifecycle orchestrator (day-tick hook)."""

from __future__ import annotations

import os
import tempfile
import unittest

from gaworld.memory import store as ms
from gaworld.settings import CONFIG
from gaworld.memory.lifecycle import run_daily_memory_lifecycle


class TestLifecycleOrchestrator(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.old_memory_dir = ms.MEMORY_DIR
        self.old_vector_db_path = ms.VECTOR_DB_PATH
        ms.MEMORY_DIR = os.path.join(self.tmpdir.name, "memory")
        ms.VECTOR_DB_PATH = os.path.join(ms.MEMORY_DIR, "vector.sqlite")
        ms._close_vector_db()
        self._old_mem_cfg = CONFIG.get("memory", {}).copy()

    def tearDown(self):
        ms._close_vector_db()
        ms.MEMORY_DIR = self.old_memory_dir
        ms.VECTOR_DB_PATH = self.old_vector_db_path
        CONFIG["memory"] = self._old_mem_cfg

    def test_all_flags_off_is_noop(self):
        CONFIG["memory"] = {
            "consolidation": {"enabled": False},
            "decay": {"enabled": False},
        }
        # Seed a few episodic memories so there *would* be material.
        for i in range(5):
            ms.vector_db_add_entry(40, "memory", f"E{i} 日常 工作", sim_day=1)

        def boom(_prompt):
            raise AssertionError("LLM should not be called when flags are off")

        result = run_daily_memory_lifecycle(
            {"id": 40}, day=3, llm=boom, web_fetch_fn=None
        )
        # No `consolidated` / `decay` / `absorbed` keys when all off.
        self.assertEqual({"day": 3, "agent_id": 40}, result)

    def test_consolidation_runs_on_cadence_only(self):
        CONFIG["memory"] = {
            "consolidation": {
                "enabled": True,
                "every_days": 3,
                "lookback_days": 7,
                "max_outputs": 1,
            },
            "decay": {"enabled": False},
        }
        for i in range(4):
            ms.vector_db_add_entry(41, "memory", f"日常 {i}", sim_day=1)
        calls = {"n": 0}

        def fake_llm(prompt):
            calls["n"] += 1
            return '["一条心得"]'

        # Day 2 is NOT a multiple of 3 → consolidation skipped.
        result = run_daily_memory_lifecycle({"id": 41}, day=2, llm=fake_llm)
        self.assertNotIn("consolidated", result)
        self.assertEqual(0, calls["n"])

        # Day 3 IS a multiple of 3 → consolidation runs.
        result = run_daily_memory_lifecycle({"id": 41}, day=3, llm=fake_llm)
        self.assertEqual(1, result.get("consolidated"))
        self.assertEqual(1, calls["n"])

    def test_decay_runs_on_cadence_only(self):
        CONFIG["memory"] = {
            "consolidation": {"enabled": False},
            "decay": {
                "enabled": True,
                "every_days": 7,
                "min_age_days": 1,
                "salience_floor": 0.5,
            },
        }
        # Insert one row that decay_pass would touch — but we'll only
        # see "decay" in the result on a cadence-hitting day.
        ms.vector_db_add_entry(42, "memory", "old chatter", sim_day=0, salience=0.4)
        # Day 3 is not a multiple of 7 → no decay summary.
        result = run_daily_memory_lifecycle({"id": 42}, day=3, llm=lambda p: "")
        self.assertNotIn("decay", result)
        # Day 7 → decay runs.
        result = run_daily_memory_lifecycle({"id": 42}, day=7, llm=lambda p: "")
        self.assertIn("decay", result)


if __name__ == "__main__":
    unittest.main()
