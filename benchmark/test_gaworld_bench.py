"""Unit tests for the GAWorld-Bench harness scoring (run: `cd benchmark && python3 -m unittest test_gaworld_bench`)."""

import json
import unittest

import gaworld_bench as gb


class TestCi95(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(gb.ci95([]), (None, None, False, 0))

    def test_single_sample_not_significant(self):
        m, hw, sig, n = gb.ci95([0.5])
        self.assertEqual((m, hw, sig, n), (0.5, None, False, 1))

    def test_tight_nonzero_is_significant(self):
        m, hw, sig, n = gb.ci95([-0.05, -0.06, -0.04, -0.055, -0.045])
        self.assertTrue(sig)
        self.assertLess(abs(m) - hw, abs(m))  # CI excludes 0
        self.assertEqual(n, 5)

    def test_straddling_zero_is_not_significant(self):
        _, hw, sig, _ = gb.ci95([0.02, -0.01, 0.03, -0.02, 0.01])
        self.assertFalse(sig)
        self.assertIsNotNone(hw)


class TestTrackCMultiseed(unittest.TestCase):
    def test_significance_aware_scoring(self):
        res = gb.track_c_multiseed(gb.make_synthetic_multiseed(), None, None, None)
        sign = res["sign"]
        self.assertEqual(res["mode"], "multiseed")
        self.assertEqual(sign["n_significant"], 3)   # tax/econ_security is ns
        self.assertEqual(sign["n_correct"], 3)
        self.assertEqual(sign["score"], 1.0)
        self.assertEqual(res["coverage"], 1.0)        # all 4 had data
        self.assertEqual(res["significance_coverage"], 0.75)
        self.assertTrue(res["pass"])
        # the ns test must be flagged, not scored as correct/incorrect
        ns = [t for t in sign["tests"] if not t["significant"]]
        self.assertEqual([(t["name"], t["metric"]) for t in ns],
                         [("tax_cut", "econ_security")])

    def test_significant_but_wrong_sign_fails(self):
        # all five seeds agree on a strong WRONG-signed effect -> significant, incorrect
        samples = {("layoff_shock", "econ_security"): [0.12, 0.13, 0.11, 0.125, 0.115]}
        res = gb.track_c_multiseed(samples, None, None, None)
        layoff = next(t for t in res["sign"]["tests"]
                      if t["name"] == "layoff_shock" and t["metric"] == "econ_security")
        self.assertTrue(layoff["significant"])
        self.assertFalse(layoff["correct"])
        self.assertFalse(res["pass"])


class TestCheckpointResume(unittest.TestCase):
    """Simulate a quota failure mid-run, then --continue resuming."""

    def _fake_run_factory(self, calls, fail_after):
        import csv as _csv
        import tempfile as _tf
        from pathlib import Path

        def fake_run(name, desc, days, seed, provider, fast=False):
            calls["n"] += 1
            if calls["n"] > fail_after:
                return None  # simulate compare-event failure (e.g. API quota)
            d = Path(_tf.mkdtemp())
            with open(d / "comparison_metrics.csv", "w", newline="") as f:
                w = _csv.writer(f)
                w.writerow(["metric", "delta_final", "delta_mean"])
                for m, v in (("mobility_intent", 0.30), ("econ_security", -0.05), ("stress", 0.17)):
                    w.writerow([m, v, v])
            return d
        return fake_run

    def test_resume_skips_completed_units(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        seeds = [1, 2]
        n_units = len(gb.INTERVENTIONS) * len(seeds)  # 6
        with tempfile.TemporaryDirectory() as tmp:
            ckpt = Path(tmp) / "ckpt.json"
            calls = {"n": 0}
            with patch.object(gb, "CHECKPOINT_PATH", ckpt):
                # Phase 1: fail after 3 successes -> incomplete + checkpoint with 3 units
                with patch.object(gb, "_run_compare_event",
                                  side_effect=self._fake_run_factory(calls, fail_after=3)):
                    res1 = gb.orchestrate_track_c_multiseed(seeds, 30, None, None, None, resume=False)
                self.assertEqual(res1["status"], "incomplete")
                self.assertTrue(ckpt.exists())
                self.assertEqual(len(json.loads(ckpt.read_text())["completed"]), 3)

                # Phase 2: --continue with everything succeeding -> only remaining 3 run
                calls["n"] = 0
                with patch.object(gb, "_run_compare_event",
                                  side_effect=self._fake_run_factory(calls, fail_after=999)):
                    res2 = gb.orchestrate_track_c_multiseed(seeds, 30, None, None, None, resume=True)
                self.assertEqual(res2["status"], "ok")
                self.assertEqual(calls["n"], n_units - 3)   # completed units were skipped
                self.assertFalse(ckpt.exists())             # checkpoint cleared on success

    def test_resume_rejects_mismatched_params(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            ckpt = Path(tmp) / "ckpt.json"
            ckpt.write_text(json.dumps({"seeds": [1, 2], "days": 30, "completed": []}))
            with patch.object(gb, "CHECKPOINT_PATH", ckpt):
                res = gb.orchestrate_track_c_multiseed([1, 2], 3, None, None, None, resume=True)
            self.assertEqual(res["status"], "n/a")  # days mismatch (3 vs 30) refused


class TestFastAnnotation(unittest.TestCase):
    def test_marker_detected_and_flagged_in_scorecard(self):
        import csv
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root / "layoff_shock"
            d.mkdir()
            (d / "run_meta.json").write_text(json.dumps({"fast": True}))
            with open(d / "comparison_metrics.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["metric", "delta_final", "delta_mean"])
                w.writerow(["econ_security", -0.05, -0.05])
            self.assertTrue(gb._dir_is_fast(d))
            res = gb.track_c_causal({t["name"]: root / t["name"] for t in gb.SIGN_TESTS},
                                    None, None, None)
            self.assertTrue(res["fast"])
            sc = gb.build_scorecard({"C": res})
            self.assertTrue(sc["fast"])
            self.assertIn("低保真", gb.render_scorecard_md(sc))

    def test_no_marker_means_not_fast(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(gb._dir_is_fast(Path(tmp)))  # no run_meta.json

    def test_multiseed_fast_param(self):
        ms = gb.track_c_multiseed({("layoff_shock", "stress"): [0.1, 0.11]},
                                  None, None, None, fast=True)
        self.assertTrue(ms["fast"])


class TestFastFlag(unittest.TestCase):
    def _capture_cmd(self, fast):
        from unittest.mock import patch
        captured = {}

        class _R:
            returncode = 1  # force early return after capturing the command

        def fake(cmd, cwd=None):
            captured["cmd"] = cmd
            return _R()

        with patch.object(gb.subprocess, "run", side_effect=fake):
            gb._run_compare_event("裁员", "desc", 30, 1, "ollama_gemma4", fast=fast)
        return captured["cmd"]

    def test_fast_true_adds_flag(self):
        self.assertIn("--fast", self._capture_cmd(True))

    def test_fast_false_omits_flag(self):
        self.assertNotIn("--fast", self._capture_cmd(False))


if __name__ == "__main__":
    unittest.main()
