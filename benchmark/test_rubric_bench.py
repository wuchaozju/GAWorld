"""Unit tests for GAWorld-Rubric-Bench (run: `cd benchmark && python3 -m unittest test_rubric_bench`)."""

import random
import unittest

from rubric import ablate, aggregate, judge, rules, runner, synth


def _ep(time, location, minutes=0, distance=0.0, mode="walk", **extra):
    ep = {"day": 1, "time": time, "location": location, "target_location": location,
          "travel": ({"mode": mode, "minutes": minutes, "distance_km": distance,
                      "status": "arrived"} if minutes or distance else {})}
    ep.update(extra)
    return ep


class TestTimeBudget(unittest.TestCase):
    def test_clean_day_scores_2(self):
        unit = {"episodes": [_ep("08:00", "A"), _ep("09:00", "B", 20, 2.0, "walk")]}
        self.assertEqual(rules.r4_1_time_budget(unit)["score"], 2)

    def test_travel_longer_than_gap_fails(self):
        unit = {"episodes": [_ep("08:00", "A"), _ep("08:05", "B", 40, 3.0, "walk")]}
        self.assertEqual(rules.r4_1_time_budget(unit)["score"], 0)

    def test_time_going_backwards_fails(self):
        unit = {"episodes": [_ep("10:00", "A"), _ep("09:00", "B")]}
        self.assertEqual(rules.r4_1_time_budget(unit)["score"], 0)

    def test_single_episode_abstains(self):
        self.assertTrue(rules.r4_1_time_budget({"episodes": [_ep("08:00", "A")]})["abstain"])


class TestReachability(unittest.TestCase):
    def test_teleport_fails(self):
        unit = {"episodes": [_ep("08:00", "A"), _ep("10:00", "B")]}
        res = rules.r4_2_reachability(unit)
        self.assertEqual(res["score"], 0)
        self.assertEqual(res["facts"]["n_teleport"], 1)

    def test_impossible_speed_fails(self):
        unit = {"episodes": [_ep("08:00", "A"), _ep("10:00", "B", 10, 100.0, "walk")]}
        self.assertEqual(rules.r4_2_reachability(unit)["score"], 0)

    def test_plausible_trip_scores_2(self):
        unit = {"episodes": [_ep("08:00", "A"), _ep("10:00", "B", 30, 8.0, "e-bike")]}
        self.assertEqual(rules.r4_2_reachability(unit)["score"], 2)

    def test_unknown_mode_skips_speed_check(self):
        unit = {"episodes": [_ep("08:00", "A"), _ep("10:00", "B", 5, 500.0, "teleporter")]}
        self.assertEqual(rules.r4_2_reachability(unit)["score"], 2)


class TestAffordability(unittest.TestCase):
    def test_negative_balance_fails(self):
        unit = {"ledger": {"balance": -5.0, "expense": 10.0, "income": 0.0},
                "conservation_drift": 0.0}
        self.assertEqual(rules.r4_3_affordability(unit)["score"], 0)

    def test_drift_fails(self):
        unit = {"ledger": {"balance": 100.0, "expense": 10.0, "income": 20.0},
                "conservation_drift": 3.0}
        self.assertEqual(rules.r4_3_affordability(unit)["score"], 0)

    def test_missing_ledger_abstains(self):
        self.assertTrue(rules.r4_3_affordability({"ledger": None})["abstain"])


class TestTrend(unittest.TestCase):
    def test_monotone_series_is_significant(self):
        tau, p = rules._mann_kendall([float(i) for i in range(12)])
        self.assertAlmostEqual(tau, 1.0, places=6)
        self.assertLess(p, 0.05)

    def test_short_series_returns_null_result(self):
        self.assertEqual(rules._mann_kendall([1.0, 2.0]), (0.0, 1.0))

    def test_amplitude_ratio_penalises_jitter(self):
        drift = rules._amplitude_ratio([0, 1, 2, 3, 4, 5])
        jitter = rules._amplitude_ratio([0, 5, 0, 5, 0, 0])
        self.assertGreater(drift, jitter)


class TestReciprocity(unittest.TestCase):
    def test_mutual_claims_score_2(self):
        unit = {"episodes": {
            1: [{"day": 1, "social_partners": [2]}],
            2: [{"day": 1, "social_partners": [1]}]}}
        self.assertEqual(rules.r3_1_reciprocity(unit)["score"], 2)

    def test_one_sided_claims_score_0(self):
        unit = {"episodes": {
            1: [{"day": 1, "social_partners": [2]}],
            2: [{"day": 1, "social_partners": []}]}}
        res = rules.r3_1_reciprocity(unit)
        self.assertEqual(res["score"], 0)
        self.assertEqual(res["facts"]["reciprocity_rate"], 0.0)

    def test_no_social_data_abstains(self):
        unit = {"episodes": {1: [{"day": 1, "social_partners": []}]}}
        self.assertTrue(rules.r3_1_reciprocity(unit)["abstain"])


class TestJudgeParsing(unittest.TestCase):
    def test_score_without_evidence_is_discarded(self):
        out = judge.parse_response('{"score": 2, "evidence": [], "reasoning": "很像人"}')
        self.assertTrue(out["abstain"])
        self.assertIsNone(out["score"])

    def test_valid_response_kept(self):
        out = judge.parse_response('{"score": 1, "evidence": ["原文"], "reasoning": "ok"}')
        self.assertEqual(out["score"], 1)
        self.assertFalse(out["abstain"])

    def test_garbage_abstains(self):
        self.assertTrue(judge.parse_response("模型今天不想说话")["abstain"])

    def test_out_of_range_score_abstains(self):
        self.assertTrue(judge.parse_response('{"score": 5, "evidence": ["x"]}')["abstain"])

    def test_provider_exception_becomes_abstain(self):
        def boom(prompt, provider):
            raise RuntimeError("no api key")

        item = {"id": "R1.1", "proposition": "p", "anchors": {}, "failure_modes": []}
        out = judge.judge_item(item, "sample", None, providers=["x"], samples_per_judge=1,
                               call=boom)
        self.assertTrue(out["abstain"])


class TestAblation(unittest.TestCase):
    def setUp(self):
        self.unit = {"kind": "agent_day", "unit_id": "AD:1:1",
                     "episodes": [_ep("08:00", "A"), _ep("09:00", "B", 20, 2.0, "walk")],
                     "ledger": {"balance": 100.0}, "conservation_drift": 0.0}

    def test_n7_breaks_all_three_world_rules(self):
        bad = ablate.n7_break_budget(self.unit, random.Random(0))
        self.assertEqual(rules.r4_1_time_budget(bad)["score"], 0)
        self.assertEqual(rules.r4_2_reachability(bad)["score"], 0)
        self.assertEqual(rules.r4_3_affordability(bad)["score"], 0)

    def test_ablation_does_not_mutate_the_original(self):
        ablate.n7_break_budget(self.unit, random.Random(0))
        self.assertEqual(rules.r4_1_time_budget(self.unit)["score"], 2)

    def test_n4_collapses_a_trajectory(self):
        eps = [_ep("08:00", "A", **{"day": d, "growth_progress": {"s": d / 40}})
               for d in range(1, 36)]
        for ep, d in zip(eps, range(1, 36)):
            ep["day"] = d
        unit = {"kind": "trajectory", "episodes": eps, "series": {}}
        before = rules.r2_1_nontrivial_trajectory(unit, min_days=30)["score"]
        after = rules.r2_1_nontrivial_trajectory(
            ablate.n4_duplicate_first_day(unit, random.Random(0)), min_days=30)
        self.assertEqual(before, 2)
        self.assertLess(after["score"] if after["score"] is not None else 0, before)


class TestAggregate(unittest.TestCase):
    def test_low_discrimination_item_is_dropped(self):
        rubric = {
            "rubric_version": "t", "gates": {"discrimination_min": 0.15, "abstain_max": 0.3},
            "dimensions": {"R4": {"name": "世界一致性", "pass": 0.8}},
            "items": [
                {"id": "A", "dim": "R4", "unit": "agent_day", "checker": "rule", "weight": 1},
                {"id": "B", "dim": "R4", "unit": "agent_day", "checker": "rule", "weight": 1},
            ],
        }
        results = {"A": [{"score": 2, "abstain": False}], "B": [{"score": 2, "abstain": False}]}
        card = aggregate.build_scorecard(rubric, results, {"agent_day": 1.0},
                                         discrimination_by_item={"A": 0.9, "B": 0.01})
        self.assertIn("B", card["dropped_items"])
        self.assertEqual(card["dimensions"]["R4"]["n_items_used"], 1)

    def test_coverage_discount_applies(self):
        rubric = {
            "rubric_version": "t", "gates": {"discrimination_min": 0.15, "abstain_max": 0.3},
            "dimensions": {"R4": {"name": "世界一致性", "pass": 0.8}},
            "items": [{"id": "A", "dim": "R4", "unit": "agent_day", "checker": "rule",
                       "weight": 1}],
        }
        results = {"A": [{"score": 2, "abstain": False}]}
        card = aggregate.build_scorecard(rubric, results, {"agent_day": 0.5},
                                         discrimination_by_item={"A": 0.9})
        self.assertEqual(card["dimensions"]["R4"]["raw_score"], 1.0)
        self.assertEqual(card["dimensions"]["R4"]["score"], 0.5)

    def test_alpha_perfect_agreement(self):
        alpha = aggregate.krippendorff_alpha_ordinal([[2, 2], [0, 0], [1, 1], [2, 2]])
        self.assertGreater(alpha, 0.9)

    def test_qwk_perfect_and_inverted(self):
        self.assertAlmostEqual(
            aggregate.quadratic_weighted_kappa([0, 1, 2, 0, 2], [0, 1, 2, 0, 2]), 1.0, places=6)
        self.assertLess(aggregate.quadratic_weighted_kappa([0, 0, 2, 2], [2, 2, 0, 0]), 0)


class TestEndToEnd(unittest.TestCase):
    """The synthetic self-test: every rule item must separate real from ablated."""

    def test_rule_items_discriminate_on_synthetic_data(self):
        data = synth.build(n_agents=6, n_days=32, seed=3)
        card = runner.run(data, providers=[], sample_seed=7,
                          ablations=["N3", "N4", "N6", "N7"])
        rule_ids = [i for i, v in card["items"].items() if v["checker"] == "rule"]
        self.assertTrue(rule_ids)
        for iid in rule_ids:
            disc = card["items"][iid]["discrimination"]
            self.assertIsNotNone(disc, f"{iid} 没有判别力读数")
            self.assertGreaterEqual(disc, 0.3, f"{iid} 判别力仅 {disc}")

    def test_fast_forward_run_abstains_instead_of_scoring_zero(self):
        """A fast-forward run has no episodes. R1/R3/R4 must abstain (missing
        data), while R2 must still find trajectories from the state history."""
        data = synth.build_fast_forward(n_agents=6, n_days=35, seed=3)
        self.assertFalse(data["capabilities"]["episodes"])
        self.assertFalse(data["capabilities"]["authored_diary"])
        self.assertTrue(data["capabilities"]["series"])

        card = runner.run(data, providers=[], sample_seed=7)
        for iid in ("R1.1", "R4.1", "R4.2", "R3.1"):
            self.assertEqual(card["items"][iid]["abstain_rate"], 1.0, iid)
            self.assertIsNone(card["items"][iid]["mean_score"], iid)
        # R2.1 is a rule item over the state series -- it must still score.
        self.assertIsNotNone(card["items"]["R2.1"]["mean_score"])
        self.assertGreater(card["items"]["R2.1"]["n_scored"], 0)

    def test_fast_forward_evolution_items_still_discriminate(self):
        """N3/N4 must bite on a fast-forward trajectory too -- there the state
        series is the only signal, so an operator that only touches episodes
        would silently become a no-op."""
        data = synth.build_fast_forward(n_agents=6, n_days=35, seed=3)
        card = runner.run(data, providers=[], sample_seed=7, ablations=["N3", "N4"])
        for iid in ("R2.1", "R2.5"):
            self.assertGreaterEqual(card["items"][iid]["discrimination"], 0.3, iid)

    def test_full_run_keeps_episode_items_scoreable(self):
        data = synth.build(n_agents=6, n_days=32, seed=3)
        self.assertTrue(data["capabilities"]["episodes"])
        card = runner.run(data, providers=[], sample_seed=7)
        self.assertIsNotNone(card["items"]["R4.1"]["mean_score"])

    def test_no_judges_means_llm_items_abstain_not_zero(self):
        data = synth.build(n_agents=4, n_days=31, seed=5)
        card = runner.run(data, providers=[], sample_seed=7)
        llm_items = [v for v in card["items"].values() if v["checker"] != "rule"]
        self.assertTrue(all(v["abstain_rate"] == 1.0 for v in llm_items))
        self.assertTrue(all(v["mean_score"] is None for v in llm_items))


if __name__ == "__main__":
    unittest.main()
