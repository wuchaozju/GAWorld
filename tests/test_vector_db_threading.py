"""The vector DB is read from worker threads, so it must tolerate them.

When ``CONFIG["concurrency"]`` is on, the main loop runs daily-routine
generation for every resident through ``gaworld.core.runner.parallel_map``.
That stage recalls memories, so ``vector_db_search`` runs on a worker thread
while the connection was opened on the main one. Before the fix this raised
``sqlite3.ProgrammingError: SQLite objects created in a thread can only be
used in that same thread`` on the first parallel day, which made the shipped
``concurrency`` knob unusable (congestion proposal §16.7).

These tests fail without ``check_same_thread=False`` on the connection.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from gaworld.core.runner import parallel_map
from gaworld.memory import store as ms


class _TempStore:
    def _setup_tmp_store(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.old_memory_dir = ms.MEMORY_DIR
        self.old_vector_db_path = ms.VECTOR_DB_PATH
        ms.MEMORY_DIR = os.path.join(self.tmpdir.name, "memory")
        ms.VECTOR_DB_PATH = os.path.join(ms.MEMORY_DIR, "vector.sqlite")
        ms._close_vector_db()
        self.addCleanup(self._teardown_tmp_store)

    def _teardown_tmp_store(self):
        ms._close_vector_db()
        ms.MEMORY_DIR = self.old_memory_dir
        ms.VECTOR_DB_PATH = self.old_vector_db_path


class TestVectorDbAcrossThreads(unittest.TestCase, _TempStore):
    def setUp(self):
        self._setup_tmp_store()
        # Opening happens here, on the main thread — that is the whole point.
        for agent_id in range(1, 5):
            ms.vector_db_add_entry(
                agent_id, "episode", f"agent {agent_id} went to the market",
                sim_day=1, sim_time="09:00",
            )

    def test_search_from_worker_threads(self):
        """The failing case: recall on a thread that did not open the db."""
        results = parallel_map(
            lambda agent_id: ms.vector_db_search(agent_id, "market", top_k=3),
            [1, 2, 3, 4],
            max_workers=4,
            label="test_search",
        )
        self.assertEqual(4, len(results))
        for hits in results:
            self.assertTrue(hits, "worker thread got no memories back")

    def test_write_from_worker_threads(self):
        """Writes go through the lock rather than interleaving commits."""
        parallel_map(
            lambda agent_id: ms.vector_db_add_entry(
                agent_id, "episode", f"agent {agent_id} came home",
                sim_day=2, sim_time="18:00",
            ),
            [1, 2, 3, 4],
            max_workers=4,
            label="test_write",
        )
        conn = ms._vector_db_connect()
        rows = conn.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
        self.assertEqual(8, rows, "a concurrent write was lost")

    def test_results_keep_input_order(self):
        """parallel_map's ordering contract, exercised through the db."""
        order = parallel_map(
            lambda agent_id: (agent_id, bool(ms.vector_db_search(agent_id, "market"))),
            [4, 1, 3, 2],
            max_workers=4,
        )
        self.assertEqual([4, 1, 3, 2], [a for a, _ in order])


if __name__ == "__main__":
    unittest.main()
