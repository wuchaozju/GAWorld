"""Per-agent resume: a never-run agent starts the calendar over.

``sim_state.json`` keeps one world-wide ``last_day``. Resuming off it alone
means a fresh resident inherits however many years other agents have already
lived — picking a new agent after a long run woke them up in 2047 instead of
on the configured start date. These cover the per-agent cursor that fixes it,
including the migration path for state files written before it existed.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

import generative_city_sim as sim
from gaworld.memory import store


class TestResumeStartDay(unittest.TestCase):
    def test_never_run_agent_starts_at_day_one(self):
        cursor = {"37": 7832}
        self.assertEqual(sim._resume_start_day(cursor, [1]), 1)

    def test_previously_run_agent_resumes(self):
        cursor = {"37": 7832}
        self.assertEqual(sim._resume_start_day(cursor, [37]), 7833)

    def test_mixed_run_resumes_from_the_furthest_agent(self):
        cursor = {"37": 7832, "2": 10}
        self.assertEqual(sim._resume_start_day(cursor, [1, 2, 37]), 7833)

    def test_empty_state_starts_at_day_one(self):
        self.assertEqual(sim._resume_start_day({}, [1, 2]), 1)

    def test_persist_records_only_this_runs_agents(self):
        cursor = {"37": 7832}
        with tempfile.TemporaryDirectory() as tmp:
            saved = store.MEMORY_DIR
            store.MEMORY_DIR = tmp
            self.addCleanup(lambda: setattr(store, "MEMORY_DIR", saved))
            sim._persist_sim_day(5, cursor, [1, 2])
            with open(os.path.join(tmp, "sim_state.json"), encoding="utf-8") as f:
                state = json.load(f)
        self.assertEqual(state["last_day"], 5)
        self.assertEqual(state["agent_last_day"], {"37": 7832, "1": 5, "2": 5})


class TestAgentLastDayMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        saved = store.MEMORY_DIR
        store.MEMORY_DIR = self.tmp.name
        self.addCleanup(lambda: setattr(store, "MEMORY_DIR", saved))

    def _write_agent_memory(self, agent_id):
        path = os.path.join(self.tmp.name, f"agent_{agent_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f)

    def test_old_state_seeds_every_agent_with_memory_on_disk(self):
        self._write_agent_memory(37)
        self._write_agent_memory(2)
        cursor = sim._agent_last_day_map({"last_day": 7832})
        self.assertEqual(cursor, {"2": 7832, "37": 7832})
        # The migrated agents still resume; an agent with no memory does not.
        self.assertEqual(sim._resume_start_day(cursor, [37]), 7833)
        self.assertEqual(sim._resume_start_day(cursor, [1]), 1)

    def test_new_state_is_used_verbatim(self):
        self._write_agent_memory(37)
        cursor = sim._agent_last_day_map(
            {"last_day": 7832, "agent_last_day": {"37": 7832}}
        )
        self.assertEqual(cursor, {"37": 7832})

    def test_fresh_state_migrates_to_nothing(self):
        self._write_agent_memory(37)
        self.assertEqual(sim._agent_last_day_map({"last_day": 0}), {})


if __name__ == "__main__":
    unittest.main()
