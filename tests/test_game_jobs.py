"""Tests for the shared playground job store (gaworld.apps.game_jobs).

What we defend:

* a job reports progress while it runs and carries its result when it ends;
* a raising job becomes a failed record rather than a silent dead thread;
* eviction drops finished jobs oldest-first and never a running one;
* ``results()`` returns finished runs newest-first by ``created_at``;
* two stores never see each other's jobs — the reason each game owns one.
"""

from __future__ import annotations

import time
import unittest

from gaworld.apps.game_jobs import JobStore


def _settle(store: JobStore, job_id: str, timeout: float = 2.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = store.status(job_id)
        if record and record["status"] != "running":
            return record
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never finished")


class JobStoreTest(unittest.TestCase):
    def test_a_finished_job_carries_its_result_and_progress(self) -> None:
        store = JobStore("demo")
        job_id = store.run(lambda progress: (progress(0.5, "半路"), {"ok": 1})[1])
        record = _settle(store, job_id)
        self.assertEqual(record["status"], "done")
        self.assertEqual(record["result"], {"ok": 1})
        self.assertEqual(record["progress"], 1.0)
        self.assertIsNotNone(record["finished_at"])
        self.assertTrue(job_id.startswith("demo-"))

    def test_progress_is_visible_while_running(self) -> None:
        store = JobStore("demo")
        seen: list[float] = []
        gate = [False]

        def work(progress):
            progress(0.25, "四分之一")
            while not gate[0]:
                time.sleep(0.005)
            return {}

        job_id = store.run(work)
        deadline = time.time() + 2
        while time.time() < deadline:
            record = store.status(job_id)
            if record and record["progress"] >= 0.25:
                seen.append(record["progress"])
                self.assertEqual(record["message"], "四分之一")
                self.assertEqual(record["status"], "running")
                break
            time.sleep(0.01)
        gate[0] = True
        _settle(store, job_id)
        self.assertTrue(seen, "progress never became visible")

    def test_a_raising_job_is_recorded_as_failed(self) -> None:
        store = JobStore("demo")

        def boom(progress):
            raise RuntimeError("nope")

        record = _settle(store, store.run(boom))
        self.assertEqual(record["status"], "failed")
        self.assertIn("RuntimeError: nope", record["error"])
        self.assertIsNone(record["result"])

    def test_eviction_drops_finished_jobs_and_spares_the_running_one(self) -> None:
        store = JobStore("demo", max_jobs=3)
        done = [_settle(store, store.run(lambda progress: {"created_at": 1.0})) for _ in range(3)]
        gate = [False]

        def slow(progress):
            while not gate[0]:
                time.sleep(0.005)
            return {}

        running = store.run(slow)
        for _ in range(2):
            _settle(store, store.run(lambda progress: {"created_at": 2.0}))

        self.assertIsNotNone(store.status(running))  # never evicted
        self.assertIsNone(store.status(done[0]["id"]))  # oldest finished went first
        gate[0] = True
        _settle(store, running)

    def test_results_are_newest_first(self) -> None:
        store = JobStore("demo")
        for created in (10.0, 30.0, 20.0):
            _settle(store, store.run(lambda progress, c=created: {"created_at": c}))
        self.assertEqual([row["result"]["created_at"] for row in store.results()], [30.0, 20.0, 10.0])

    def test_stores_are_isolated(self) -> None:
        left, right = JobStore("left"), JobStore("right")
        job_id = _settle(left, left.run(lambda progress: {"created_at": 1.0}))["id"]
        self.assertIsNone(right.status(job_id))
        self.assertEqual(right.results(), [])

    def test_reset_empties_the_store(self) -> None:
        store = JobStore("demo")
        _settle(store, store.run(lambda progress: {"created_at": 1.0}))
        store.reset()
        self.assertEqual(store.results(), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
