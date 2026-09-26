"""Tests for the Track B spatial-redistribution harness.

The judgement is the separation of two curves against cross-seed spread, not
an absolute threshold — the group-agent work established both that a single
seed is noise and that an absolute band ends up measuring estimator error.
"""

import json
import tempfile
import unittest
from pathlib import Path

import trackb_spatial as tb


def _run(tmp: Path, name: str, per_day_counts) -> Path:
    """Write one fake run's occupancy table. ``per_day_counts``: {day: [counts]}."""
    run_dir = tmp / name
    run_dir.mkdir(parents=True)
    with open(run_dir / tb.TABLE, "w", encoding="utf-8") as fh:
        for day, ticks in sorted(per_day_counts.items()):
            for counts in ticks:
                fh.write(json.dumps({"counts": counts, "_day": day,
                                     "nodes": len(counts),
                                     "people": sum(counts.values())}) + "\n")
    return run_dir


def _spread(lump, others, n=9):
    """One tick: ``lump`` people in one node, ``others`` in each of the rest."""
    return {"hub": lump, **{f"n{i}": others for i in range(n)}}


class TestHerfindahl(unittest.TestCase):
    def test_even_spread_is_one_over_n(self):
        self.assertAlmostEqual(tb.herfindahl({f"n{i}": 5 for i in range(20)}), 0.05)

    def test_everyone_in_one_place_is_one(self):
        self.assertAlmostEqual(tb.herfindahl({"hub": 300}), 1.0)

    def test_concentration_rises_as_people_pile_up(self):
        self.assertLess(tb.herfindahl(_spread(10, 10)), tb.herfindahl(_spread(90, 1)))

    def test_empty_and_zero_are_safe(self):
        self.assertEqual(tb.herfindahl({}), 0.0)
        self.assertEqual(tb.herfindahl({"a": 0, "b": 0}), 0.0)


class TestDailyConcentration(unittest.TestCase):
    def test_a_missing_table_is_empty_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(tb.daily_concentration(Path(tmp) / "nope"), {})

    def test_days_are_averaged_over_their_ticks(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = _run(Path(tmp), "r", {1: [_spread(90, 1), _spread(10, 10)]})
            daily = tb.daily_concentration(run)
            self.assertEqual(set(daily), {1})
            self.assertAlmostEqual(
                daily[1],
                (tb.herfindahl(_spread(90, 1)) + tb.herfindahl(_spread(10, 10))) / 2)

    def test_a_corrupt_line_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = _run(Path(tmp), "r", {1: [_spread(10, 10)]})
            with open(run / tb.TABLE, "a", encoding="utf-8") as fh:
                fh.write("{not json\n")
            self.assertEqual(set(tb.daily_concentration(run)), {1})


class TestComparison(unittest.TestCase):
    def _sides(self, tmp, treatment_lump):
        """Three seeds a side; treatment differs only in how lumpy it is."""
        tmp = Path(tmp)
        ref, trt = [], []
        for seed in range(3):
            jitter = seed  # a little cross-seed spread, as a real run has
            ref.append(_run(tmp, f"ref{seed}",
                            {d: [_spread(60 + jitter, 4)] for d in range(1, 11)}))
            trt.append(_run(tmp, f"trt{seed}",
                            {d: [_spread(treatment_lump + jitter, 4)] for d in range(1, 11)}))
        return ref, trt

    def test_a_clear_effect_separates(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref, trt = self._sides(tmp, treatment_lump=10)
            result = tb.compare(ref, trt)
            self.assertEqual(result["verdict"], "separated")
            self.assertLess(result["days"][-1]["separation"], 0, "avoidance should spread people out")

    def test_no_effect_is_not_reported_as_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref, trt = self._sides(tmp, treatment_lump=60)
            self.assertEqual(tb.compare(ref, trt)["verdict"], "inconclusive")

    def test_one_seed_is_never_enough(self):
        """A single seed was shown to swing the group-agent gate from 0.32 to 2.66."""
        with tempfile.TemporaryDirectory() as tmp:
            ref, trt = self._sides(tmp, treatment_lump=10)
            result = tb.compare(ref[:1], trt[:1])
            self.assertEqual(result["verdict"], "inconclusive")
            self.assertIn("seed", result["note"])

    def test_no_data_is_said_plainly(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = tb.compare([Path(tmp) / "a"], [Path(tmp) / "b"])
            self.assertEqual(result["status"], "no_data")


class TestSelfCheck(unittest.TestCase):
    def test_it_runs_without_a_simulator(self):
        self.assertGreater(tb._self_check()["herfindahl_lumpy"],
                           tb._self_check()["herfindahl_even"])


if __name__ == "__main__":
    unittest.main()
