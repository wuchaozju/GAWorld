"""Dashboard readers follow the selected city's run root.

A selected city moves every run path under ``output/cities/<slug>/``
(``gaworld.city.config.RUN_PATHS``); the simulator writes there. The economy
snapshot (Agent Studio's finance card) and the recorded streams (family card,
live SSE stream) were still read from the fixed ``output/economy`` and
``output/records`` — the default world's numbers, or the test suite's, shown
as the current run's.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from gaworld.apps import world_paths


def _city_config():
    return {
        "run_output_dir": "output/cities/x",
        "economy": {"output_dir": "output/cities/x/economy"},
        "records": {"output_dir": "output/cities/x/records"},
    }


class RunRootTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(world_paths, "REPO_ROOT", "/repo")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_selected_city_moves_every_reader(self):
        with mock.patch.object(world_paths, "effective_config", _city_config):
            self.assertEqual(world_paths.run_root(), "/repo/output/cities/x")
            self.assertEqual(world_paths.economy_snapshot_path(),
                             "/repo/output/cities/x/economy/wealth_snapshot.csv")
            self.assertEqual(world_paths.records_dir(), "/repo/output/cities/x/records")

    def test_without_the_sections_the_defaults_stand(self):
        with mock.patch.object(world_paths, "effective_config", dict):
            self.assertEqual(world_paths.run_root(), os.path.join("/repo", "output"))
            self.assertEqual(world_paths.economy_snapshot_path(), world_paths.ECONOMY_SNAPSHOT_PATH)
            self.assertEqual(world_paths.records_dir(), world_paths.RECORDS_DIR)

    def test_the_benchmark_scores_the_active_run_root_by_default(self):
        from gaworld.apps import bench_api

        started = []
        with mock.patch.object(world_paths, "effective_config", _city_config), \
                mock.patch.object(bench_api.ownership, "spawn", lambda fn, job, name: started.append(job)), \
                mock.patch.object(bench_api, "_JOBS", {}), \
                mock.patch("os.makedirs"):
            bench_api.start({"kind": "bench", "track": "A"})
            bench_api._JOBS.clear()
            bench_api.start({"kind": "bench", "synthetic": True})
        self.assertEqual(started[0]["argv"][-2:], ["--output-dir", "/repo/output/cities/x"])
        self.assertNotIn("--output-dir", started[1]["argv"])


if __name__ == "__main__":
    unittest.main()
