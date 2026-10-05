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


class TestAnchorScope(unittest.TestCase):
    """City-wide anchors must not score a district run.

    ``data/citymap.md`` is ~19x15 km of one Hangzhou district, where over half
    of commutes are under 5 km; the commuting anchors describe Hangzhou as a
    whole. Across the whole distance-decay range the district reproduces the
    city's within-5 km share (52.3% vs 52%) but tops out at a 5.94 km mean
    against the city's 8.1 km — the tail does not exist on that map. Scoring
    one against the other measures the mismatch, not the model.
    """

    def test_every_anchor_declares_a_scope(self):
        for key, anchor in gb.ANCHORS.items():
            with self.subTest(anchor=key):
                self.assertIn("scope", anchor, f"{key} has no declared scope")

    def test_the_commuting_anchors_are_out_of_scope(self):
        for key in ("commute_minutes", "transit_share"):
            self.assertNotIn(gb.ANCHORS[key]["scope"], gb.SCORED_SCOPES)

    def test_the_economic_anchors_are_still_scored(self):
        for key in ("engel_coefficient", "savings_rate", "wealth_gini"):
            self.assertIn(gb.ANCHORS[key]["scope"], gb.SCORED_SCOPES)

    def test_an_out_of_scope_anchor_is_reported_but_not_scored(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "economy").mkdir()
            (root / "economy" / "wealth_snapshot.csv").write_text(
                "engel_coefficient,savings_rate\n0.29,0.34\n0.28,0.36\n", encoding="utf-8")
            commute = root / "commute"
            commute.mkdir()
            (commute / "commute.csv").write_text(
                "avg_travel_time\n12.0\n13.0\n", encoding="utf-8")
            result = gb.track_a_macro_fit(root)

        self.assertEqual(result.get("sim_scope"), "district")
        self.assertIn("engel_coefficient", result["metrics"])
        if "commute_minutes" in result.get("context_metrics", {}):
            row = result["context_metrics"]["commute_minutes"]
            self.assertIsNone(row["score"])
            self.assertIn("context only", row["note"])
        # Whatever the extractor found, no out-of-scope anchor may be scored.
        for key in result["metrics"]:
            self.assertIn(gb.ANCHORS[key]["scope"], gb.SCORED_SCOPES)


class TestProvenance(unittest.TestCase):
    """A fixture scorecard must never read as a simulation result.

    The 2026-09-25 headline (trust gate OK, composite 0.9361, Track C 4/4) was
    the --synthetic fixture: its four deltas are exactly ``make_synthetic()``'s.
    """

    def _det_ok_tracks(self):
        return {"C": {"status": "ok", "score": 1.0, "pass": True, "det_status": "ok"}}

    def test_synthetic_source_forces_the_fixture_gate(self):
        sc = gb.build_scorecard(self._det_ok_tracks(),
                                gb.build_provenance(synthetic=True, inputs={}))
        self.assertEqual(sc["trust_gate"], "FIXTURE")
        self.assertEqual(sc["provenance"]["source"], "synthetic")
        self.assertIn("不是 GAWorld 仿真结果", gb.render_scorecard_md(sc))

    def test_real_source_keeps_the_determinism_gate(self):
        sc = gb.build_scorecard(self._det_ok_tracks(),
                                gb.build_provenance(synthetic=False, inputs={"output_dir": "x"}))
        self.assertEqual(sc["trust_gate"], "OK")
        self.assertEqual(sc["provenance"]["inputs"], {"output_dir": "x"})
        self.assertIn("数据来源: `real`", gb.render_scorecard_md(sc))

    def test_fixture_cards_are_written_apart_from_the_headline(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(gb, "RESULTS_DIR", root), \
                    mock.patch.object(gb, "SYNTHETIC_DIR", root / "synthetic"), \
                    mock.patch.object(gb.sys, "argv", ["gaworld_bench.py", "--synthetic"]):
                self.assertEqual(gb.main(), 0)
                card = json.loads((root / "synthetic" / "scorecard.json").read_text(encoding="utf-8"))
                self.assertEqual(card["trust_gate"], "FIXTURE")
                self.assertFalse((root / "scorecard.json").exists())
                self.assertFalse((root / "report.md").exists())
                self.assertTrue((root / "synthetic" / "report.md").exists())
                self.assertIn("合成夹具", (root / "synthetic" / "report.md").read_text(encoding="utf-8"))


class TestEpochGate(unittest.TestCase):
    """Comparisons from older code measure that code: no OK gate on them."""

    def _tracks(self, epochs):
        return {"C": {"status": "ok", "score": 1.0, "pass": True, "det_status": "ok",
                      "epochs": epochs}}

    def test_current_epoch_comparisons_keep_ok(self):
        sc = gb.build_scorecard(self._tracks({"layoff_shock": gb.CURRENT_EPOCH}),
                                gb.build_provenance(synthetic=False, inputs={}))
        self.assertEqual((sc["trust_gate"], sc["trust_reasons"]), ("OK", []))

    def test_old_or_unstamped_comparisons_are_unverified(self):
        sc = gb.build_scorecard(self._tracks({"layoff_shock": gb.CURRENT_EPOCH, "tax_cut": None,
                                              "placebo": gb.CURRENT_EPOCH - 1}),
                                gb.build_provenance(synthetic=False, inputs={}))
        self.assertEqual(sc["trust_gate"], "UNVERIFIED")
        self.assertIn("2/3 个对照不是当前代码版本", sc["trust_reasons"][0])
        self.assertIn("tax_cut=未标", gb.render_scorecard_md(sc))

    def test_epoch_is_read_from_run_meta(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self.assertIsNone(gb._dir_epoch(d))
            (d / "run_meta.json").write_text(json.dumps({"comparability_epoch": 3}))
            self.assertEqual(gb._dir_epoch(d), 3)


class TestWealthGiniPopulation(unittest.TestCase):
    """wealth_gini is scored over the labour force only (decision 2026-10-03):
    students, homemakers and retirees carry a placeholder income band."""

    def _track_a(self, csv_text):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "economy").mkdir()
            (root / "economy" / "wealth_snapshot.csv").write_text(csv_text, encoding="utf-8")
            return gb.track_a_macro_fit(root)

    def test_people_outside_the_labour_force_are_left_out(self):
        rows = ["balance,housing_fund,debt,employment_status",
                "1000,0,0,employed", "90000,0,0,employed", "5000,0,0,unemployed",
                "100,0,0,student", "200,0,0,not_in_labor_force", "300,0,0,retired"]
        result = self._track_a("\n".join(rows) + "\n")
        row = result["metrics"]["wealth_gini"]
        self.assertAlmostEqual(row["sim"], round(gb.gini([1000.0, 90000.0, 5000.0]), 4))
        self.assertEqual(row["population"], "labour_force (3/6)")

    def test_old_outputs_without_the_column_say_they_used_everyone(self):
        result = self._track_a("balance,housing_fund,debt\n1000,0,0\n9000,0,0\n")
        self.assertTrue(result["metrics"]["wealth_gini"]["population"].startswith("all (2;"))


class TestMetricProvenance(unittest.TestCase):
    """MECHANISM_PROVENANCE rule 3: a cited metric carries its weakest dependency."""

    def _track_a(self, csv_text):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "economy").mkdir()
            (root / "economy" / "wealth_snapshot.csv").write_text(csv_text, encoding="utf-8")
            return gb.track_a_macro_fit(root)

    def test_every_anchor_has_a_grade_and_a_weakest_dependency(self):
        for key in gb.ANCHORS:
            prov = gb.METRIC_PROVENANCE[key]
            self.assertIn(prov["grade"], ("a", "b", "c"), key)
            self.assertTrue(prov["weakest"], key)

    def test_the_engel_columns_are_flagged_as_an_echo_of_the_configured_table(self):
        result = self._track_a("engel_coefficient,savings_rate,balance,employment_status\n"
                               "0.30,0.25,5000,employed\n0.38,0.15,9000,employed\n")
        for key in ("engel_coefficient", "savings_rate"):
            self.assertEqual(result["metrics"][key]["grade"], "c")
            self.assertIn("engel_curve", result["metrics"][key]["echo"])
        self.assertNotIn("echo", result["metrics"]["wealth_gini"])
        diag, recs = gb._report_track_a(result)
        self.assertTrue(any("回显" in line for line in diag))
        self.assertTrue(any("不是模型证据" in r for r in recs))

    def test_the_scorecard_lists_the_sources(self):
        result = self._track_a("engel_coefficient,savings_rate,balance,employment_status\n"
                               "0.30,0.25,5000,employed\n0.38,0.15,9000,employed\n")
        c = gb.track_c_multiseed(gb.make_synthetic_multiseed(), None, None, None)
        sc = gb.build_scorecard({"A": result, "C": c}, gb.build_provenance(synthetic=False, inputs={}))
        md = gb.render_scorecard_md(sc)
        self.assertIn("**指标来源**", md)
        self.assertIn("`engel_coefficient` (c)", md)
        self.assertIn("**回显**", md)
        self.assertIn("infer_event_effect", md)
        self.assertTrue(all(t["grade"] == "c" for t in c["sign"]["tests"]))

    def test_track_c_grade_matches_the_research_catalogue(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from gaworld.research.measures import registry

        reg = registry()
        for test in gb.SIGN_TESTS:
            self.assertEqual(reg[test["metric"]].grade, gb.STATE_PROVENANCE["grade"], test["metric"])
            self.assertIn("infer_event_effect", reg[test["metric"]].basis)


class TestTrackBGames(unittest.TestCase):
    """Track B (games level): pre-registered facts over archived playground games."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "games"

    def tearDown(self):
        self._tmp.cleanup()

    def _game(self, kind, i, result, provider="p1"):
        folder = self.dir / kind
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"g{i}.json").write_text(
            json.dumps({"kind": kind, "provider": provider, "result": result}, ensure_ascii=False),
            encoding="utf-8")

    @staticmethod
    def _voters(pairs):
        return [{"private": {"stance": a}, "public": {"stance": b}} for a, b in pairs]

    def _fact(self, result, fact_id):
        return next(f for f in result["facts"] if f["id"] == fact_id)

    def test_binomial_tail(self):
        self.assertAlmostEqual(gb.binom_upper_p(10, 10), 1 / 1024)
        self.assertEqual(gb.binom_upper_p(0, 7), 1.0)
        self.assertAlmostEqual(gb.binom_upper_p(7, 8), 9 / 256)

    def test_the_synthetic_archive_reproduces_all_three(self):
        gb.make_synthetic_games(self.dir)
        result = gb.track_b_games(self.dir)
        self.assertEqual((result["status"], result["score"], result["pass"]), ("ok", 1.0, True))
        self.assertEqual(result["games"], {"referendum": 5, "disaster": 5, "rumor": 5})
        self.assertTrue(all(f["grade"] == "c" and f["cue"] for f in result["facts"]))

    def test_no_games_means_every_fact_abstains(self):
        result = gb.track_b_games(self.dir)
        self.assertEqual(result["status"], "n/a")
        self.assertTrue(all(f["reproduced"] is None for f in result["facts"]))
        self.assertIn("对局不足", result["note"])
        md = gb.generate_report(gb.build_scorecard({"B": result}))
        self.assertIn("未评估", md)
        self.assertIn("多玩几局 referendum，不填宣传口径", md)
        self.assertNotIn("未评估：Track B", md)

    def test_four_games_are_not_enough(self):
        gb.make_synthetic_games(self.dir)
        for kind in gb.GAME_KINDS:
            sorted((self.dir / kind).glob("*.json"))[0].unlink()
        result = gb.track_b_games(self.dir)
        self.assertEqual(result["status"], "n/a")
        self.assertEqual(self._fact(result, "disaster_panic_rare")["abstain"], "可用对局 4/5")

    def test_conformity_skips_campaigns_and_ties_and_counts_both_directions(self):
        for i in range(5):  # majority 支持; one toward, one away per game
            self._game("referendum", i, {"campaign": "", "voters": self._voters(
                [("支持", "支持"), ("支持", "支持"), ("反对", "支持"), ("支持", "弃权")])})
        self._game("referendum", 5, {"campaign": "为了孩子", "voters": self._voters(
            [("支持", "支持"), ("支持", "支持"), ("反对", "支持")])})
        self._game("referendum", 6, {"campaign": "", "voters": self._voters(
            [("支持", "反对"), ("反对", "反对")])})
        fact = self._fact(gb.track_b_games(self.dir), "referendum_conformity")
        self.assertEqual((fact["games"], fact["units"]), (5, 10))
        self.assertEqual((fact["values"]["toward"], fact["values"]["away"]), (5, 5))
        self.assertIs(fact["reproduced"], False)

    def test_panic_ignores_unreadable_replies_and_fails_when_panic_is_common(self):
        for i in range(5):
            self._game("disaster", i, {"agents": [{"reactions": [
                {"action": "避险逃离", "panic": 5, "help": True},
                {"action": "囤积物资", "panic": 5, "help": True},
                {"action": "打探消息", "panic": 2, "help": True},
                {"action": "救助他人", "panic": 3, "help": True},
                {"action": "其他", "panic": 3, "help": False}]}]})
        fact = self._fact(gb.track_b_games(self.dir), "disaster_panic_rare")
        self.assertEqual(fact["units"], 20)
        self.assertEqual((fact["values"]["extreme_share"], fact["values"]["help_rate"]), (0.5, 1.0))
        self.assertIs(fact["reproduced"], False)

    def test_continued_influence_needs_a_residual_and_skips_old_archives(self):
        for i in range(5):
            self._game("rumor", i, {"nodes": [{"beliefs": [80, 5]}, {"beliefs": [90, 10]}]})
        self._game("rumor", 9, {"nodes": [{"belief": 90}]})  # archived before beliefs existed
        fact = self._fact(gb.track_b_games(self.dir), "rumor_continued_influence")
        self.assertEqual((fact["games"], fact["units"]), (5, 10))
        self.assertEqual(fact["values"]["down"], 10)
        self.assertLess(fact["values"]["residual"], gb.CIE_RESIDUAL_MIN)
        self.assertIs(fact["reproduced"], False)  # corrected, but erased: no continued influence

    def test_abstentions_count_against_the_score(self):
        gb.make_synthetic_games(self.dir)
        for path in (self.dir / "rumor").glob("*.json"):
            path.unlink()
        result = gb.track_b_games(self.dir)
        self.assertEqual((result["status"], result["n_assessed"], result["n_reproduced"]), ("ok", 2, 2))
        self.assertEqual((result["score"], result["coverage"], result["pass"]), (0.6667, 0.6667, True))
        md = gb.render_scorecard_md(gb.build_scorecard({"B": result}))
        self.assertIn("复现 2/2 条可评（另 1 条弃权）", md)
        self.assertIn("Track B 各条 (c)", md)

    def test_mixed_providers_and_unreadable_files_are_reported(self):
        gb.make_synthetic_games(self.dir)
        self._game("disaster", 9, {"agents": []}, provider="p2")
        (self.dir / "rumor" / "broken.json").write_text("{", encoding="utf-8")
        result = gb.track_b_games(self.dir)
        self.assertEqual(result["providers"], {"synthetic": 15, "p2": 1})
        self.assertEqual(result["unreadable"], 1)
        diag, recs = gb._report_track_b(result)
        self.assertTrue(any("混合了" in line for line in diag))
        self.assertTrue(any("1 个文件读不了" in line for line in diag))
        self.assertTrue(any("按模型分开" in r for r in recs))

    def test_cli_track_b_reads_the_games_dir(self):
        from pathlib import Path
        from unittest import mock

        gb.make_synthetic_games(self.dir)
        root = Path(self._tmp.name) / "results"
        argv = ["gaworld_bench.py", "--track", "B", "--games-dir", str(self.dir)]
        with mock.patch.object(gb, "RESULTS_DIR", root), mock.patch.object(gb.sys, "argv", argv):
            self.assertEqual(gb.main(), 0)
        card = json.loads((root / "scorecard.json").read_text(encoding="utf-8"))
        self.assertEqual(card["tracks"]["B"]["score"], 1.0)
        self.assertNotIn("A", card["tracks"])
        self.assertTrue(card["provenance"]["inputs"]["games_dir"].endswith("games"))


class TestTrackDWhois(unittest.TestCase):
    """Track D (human judges): residents' pass rate against people's own."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "games"

    def tearDown(self):
        self._tmp.cleanup()

    def _room(self, i, rh, rn, hh, hn, provider="p1"):
        folder = self.dir / "whois"
        folder.mkdir(parents=True, exist_ok=True)
        results = {"resident_judged_human": rh, "resident_judgments": rn,
                   "human_judged_human": hh, "human_judgments": hn,
                   "judges": [{"alias": "1号", "correct": rn - rh + hh, "total": rn + hn}]}
        (folder / f"r{i}.json").write_text(
            json.dumps({"kind": "whois", "provider": provider, "result": {"results": results}}), encoding="utf-8")

    def test_wilson_interval(self):
        low, high = gb.wilson(5, 10)
        self.assertLess(low, 0.5)
        self.assertGreater(high, 0.5)
        self.assertIsNone(gb.wilson(0, 0))
        self.assertEqual(gb.wilson(10, 10)[1], 1.0)

    def test_the_synthetic_archive_passes(self):
        gb.make_synthetic_games(self.dir)
        result = gb.track_d_whois(self.dir)
        self.assertEqual((result["status"], result["rooms"], result["pass"]), ("ok", 5, True))
        self.assertEqual(result["score"], round(min(1.0, (25 / 30) / 1.0), 4))

    def test_too_few_rooms_or_judgments_abstain(self):
        result = gb.track_d_whois(self.dir)
        self.assertEqual(result["status"], "n/a")
        self.assertIn("对局 0/5", result["abstain"])
        for i in range(5):
            self._room(i, 3, 4, 0, 0)  # one person per room: nobody judges a person
        result = gb.track_d_whois(self.dir)
        self.assertEqual(result["status"], "n/a")
        self.assertIn("对真人的判断 0/10", result["abstain"])
        md = gb.generate_report(gb.build_scorecard({"D": result}))
        self.assertIn("每局至少两个真人座位", md)
        self.assertNotIn("未评估：Track D", md)

    def test_score_is_the_ratio_capped_at_one_and_fails_below_the_bar(self):
        for i in range(5):
            self._room(i, 1, 6, 2, 2)  # residents 5/30 judged human, people 10/10
        result = gb.track_d_whois(self.dir)
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(result["score"], (5 / 30) / 1.0, places=4)
        self.assertFalse(result["pass"])
        _, recs = gb._report_track_d(result)
        self.assertTrue(any("更容易被认出来" in r for r in recs))
        for i in range(5, 10):
            self._room(i, 6, 6, 1, 2)
        capped = gb.track_d_whois(self.dir)
        self.assertLessEqual(capped["score"], 1.0)

    def test_mixed_providers_and_unreadable_rooms_are_reported(self):
        for i in range(5):
            self._room(i, 4, 6, 2, 2, provider="p1" if i else "p2")
        (self.dir / "whois" / "broken.json").write_text("{", encoding="utf-8")
        result = gb.track_d_whois(self.dir)
        self.assertEqual((result["unreadable"], result["providers"]), (1, {"p2": 1, "p1": 4}))
        md = gb.render_scorecard_md(gb.build_scorecard({"D": result}))
        self.assertIn("Track D[人类判别]", md)
        self.assertIn("混合 2 个模型", md)

    def test_cli_track_d(self):
        from pathlib import Path
        from unittest import mock

        gb.make_synthetic_games(self.dir)
        root = Path(self._tmp.name) / "results"
        argv = ["gaworld_bench.py", "--track", "D", "--games-dir", str(self.dir)]
        with mock.patch.object(gb, "RESULTS_DIR", root), mock.patch.object(gb.sys, "argv", argv):
            self.assertEqual(gb.main(), 0)
        card = json.loads((root / "scorecard.json").read_text(encoding="utf-8"))
        self.assertEqual(card["tracks"]["D"]["status"], "ok")
        self.assertNotIn("B", [k for k, v in card["tracks"].items() if v.get("status") == "ok"])
