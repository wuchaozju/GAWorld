"""Comparability epochs: the log is append-only and every producer stamps it.

See ``gaworld/core/comparability.py``. Four changes each wrote "old runs are
not comparable" into a proposal or the changelog, and nothing else; these
tests keep the machine-readable version honest.
"""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest

from gaworld.core import comparability
from gaworld.core.run_manifest import ManifestBuilder


class EpochLogTest(unittest.TestCase):
    def test_numbers_are_consecutive_and_current_is_the_last(self):
        numbers = [item.number for item in comparability.EPOCHS]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
        self.assertEqual(comparability.CURRENT_EPOCH, numbers[-1])

    def test_dates_never_go_back_and_every_entry_is_sourced(self):
        # Two changes may land on the same day (epochs 6 and 7 did); the
        # number, not the date, orders them.
        dates = [dt.date.fromisoformat(item.since) for item in comparability.EPOCHS]
        self.assertEqual(dates, sorted(dates))
        for item in comparability.EPOCHS:
            self.assertTrue(item.change and item.source and item.affects, item)

    def test_unstamped_runs_only_match_each_other(self):
        self.assertTrue(comparability.same_epoch([5, 5]))
        self.assertTrue(comparability.same_epoch([None, None]))
        self.assertFalse(comparability.same_epoch([5, None]))
        self.assertFalse(comparability.same_epoch([4, 5]))
        self.assertIn("未标", comparability.describe(None))
        self.assertIn("2026-09-19", comparability.describe(4))


class StampTest(unittest.TestCase):
    def test_every_run_manifest_carries_the_epoch(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = ManifestBuilder(repo_root=".", manifest_dir=tmp, config={}).build(outcome="ok")
        self.assertEqual(manifest["comparability_epoch"], comparability.CURRENT_EPOCH)

    def test_the_benchmark_reads_the_same_epoch_by_path(self):
        import importlib.util
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "benchmark" / "gaworld_bench.py"
        spec = importlib.util.spec_from_file_location("_bench_for_epoch_test", path)
        bench = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bench)
        self.assertEqual(bench.CURRENT_EPOCH, comparability.CURRENT_EPOCH)


if __name__ == "__main__":
    unittest.main()
