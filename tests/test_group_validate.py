"""Phase 3: the L0–L4 validation gate.

A validation suite is only worth having if it can fail. Most of the tests here
are therefore **negative controls**: they construct a candidate that is broken
in a specific, known way and assert that the corresponding layer catches it. A
gate that only ever passes is indistinguishable from no gate.

The other thing under test is the gate's own epistemic honesty: when the
reference process does not generate the phenomenon a layer measures, that layer
must report ``inconclusive`` rather than pass. Reporting a ratio of two
near-zero numbers as a verdict is how a suite ends up confidently wrong.
"""

from __future__ import annotations

import copy
import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.group.metrics import (
    average_treatment_effect,
    distribution_gap,
    effect_heterogeneity_spread,
    first_passage_days,
    heterogeneous_effects,
    ks_statistic,
    morans_i,
    sign_agreement,
    tail_shares,
    wasserstein1,
)
from gaworld.group.validate import (
    FOCUS_KEYS,
    cross_seed_baseline,
    make_reference_day,
    render_verdict,
    run_group_tier,
    run_reference_tier,
    run_validation,
)
from gaworld.population.generate import generate_population
from gaworld.population.schema import STATE_VAR_KEYS, normalize_spec


def _population(size: int = 100, seed: int = 42):
    result = generate_population(normalize_spec({"size": size, "seed": seed}))
    agents = [
        {
            "id": p.id,
            "name": p.name,
            "age": p.age,
            "gender": p.gender,
            "hukou": p.hukou,
            "industry": p.industry,
            "employment": p.employment,
            "residence": p.residence,
            "district": p.district,
            "state": dict(p.state),
        }
        for p in result.people
    ]
    return agents, result.neighbours


class MetricTests(unittest.TestCase):
    def test_wasserstein_is_zero_for_identical_samples(self):
        sample = [0.1, 0.4, 0.5, 0.9]
        self.assertAlmostEqual(0.0, wasserstein1(sample, sample), places=12)

    def test_wasserstein_equals_the_shift_for_a_translated_sample(self):
        base = [0.1, 0.2, 0.3, 0.4]
        shifted = [v + 0.05 for v in base]
        self.assertAlmostEqual(0.05, wasserstein1(base, shifted), places=9)

    def test_wasserstein_handles_unequal_sample_sizes(self):
        self.assertGreater(wasserstein1([0.0, 0.1], [0.9, 0.95, 0.99]), 0.5)

    def test_wasserstein_is_symmetric(self):
        a, b = [0.1, 0.5, 0.7], [0.2, 0.3, 0.99]
        self.assertAlmostEqual(wasserstein1(a, b), wasserstein1(b, a), places=12)

    def test_wasserstein_ignores_a_pure_variance_change_less_than_ks(self):
        # Both metrics are reported because they see different things; this
        # documents that they are not redundant.
        tight = [0.5] * 50
        wide = list(np.linspace(0.0, 1.0, 50))
        self.assertGreater(ks_statistic(tight, wide), 0.4)
        self.assertGreater(wasserstein1(tight, wide), 0.2)

    def test_ks_is_zero_for_identical_and_one_for_disjoint(self):
        self.assertAlmostEqual(0.0, ks_statistic([0.1, 0.2], [0.1, 0.2]), places=12)
        self.assertAlmostEqual(1.0, ks_statistic([0.0, 0.1], [0.9, 1.0]), places=12)

    def test_empty_input_does_not_raise(self):
        self.assertEqual(0.0, wasserstein1([], [0.5]))
        self.assertEqual(0.0, ks_statistic([], []))

    def test_morans_i_is_positive_when_neighbours_agree(self):
        # Two tight clusters with opposite values: strong positive
        # autocorrelation.
        neighbours = {1: [2, 3], 2: [1, 3], 3: [1, 2], 4: [5, 6], 5: [4, 6], 6: [4, 5]}
        values = {1: 1.0, 2: 1.0, 3: 1.0, 4: -1.0, 5: -1.0, 6: -1.0}
        self.assertGreater(morans_i(values, neighbours), 0.8)

    def test_morans_i_is_negative_when_neighbours_alternate(self):
        neighbours = {1: [2], 2: [1, 3], 3: [2, 4], 4: [3]}
        values = {1: 1.0, 2: -1.0, 3: 1.0, 4: -1.0}
        self.assertLess(morans_i(values, neighbours), 0.0)

    def test_morans_i_degenerate_inputs_return_zero_not_nan(self):
        self.assertEqual(0.0, morans_i({1: 0.5, 2: 0.5, 3: 0.5}, {1: [2], 2: [1], 3: []}))
        self.assertEqual(0.0, morans_i({1: 0.1}, {1: []}))
        self.assertEqual(0.0, morans_i({1: 0.1, 2: 0.9, 3: 0.5}, {1: [], 2: [], 3: []}))

    def test_tail_shares_detects_compression(self):
        wide = list(np.linspace(0.0, 1.0, 100))
        narrow = list(np.linspace(0.45, 0.55, 100))
        self.assertGreater(tail_shares(wide)["low_share"], tail_shares(narrow)["low_share"])
        self.assertGreater(tail_shares(wide)["p10_p90_spread"], tail_shares(narrow)["p10_p90_spread"])

    def test_first_passage_reports_rate_and_timing_separately(self):
        never = {1: [0.1] * 10}
        late = {1: [0.1] * 8 + [0.9, 0.9]}
        early = {1: [0.9] * 10}
        self.assertEqual(0.0, first_passage_days(never, 0.8)["crossing_rate"])
        self.assertTrue(math.isnan(first_passage_days(never, 0.8)["median_first_passage_day"]))
        self.assertEqual(9.0, first_passage_days(late, 0.8)["median_first_passage_day"])
        self.assertEqual(1.0, first_passage_days(early, 0.8)["median_first_passage_day"])

    def test_ate_is_a_paired_difference(self):
        control = {1: 0.5, 2: 0.5}
        treated = {1: 0.4, 2: 0.2}
        self.assertAlmostEqual(-0.2, average_treatment_effect(control, treated), places=9)

    def test_heterogeneous_effects_split_by_subgroup(self):
        control = {1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5}
        treated = {1: 0.4, 2: 0.4, 3: 0.6, 4: 0.6}
        groups = {1: "a", 2: "a", 3: "b", 4: "b"}
        effects = heterogeneous_effects(control, treated, groups)
        self.assertAlmostEqual(-0.1, effects["a"], places=9)
        self.assertAlmostEqual(0.1, effects["b"], places=9)
        self.assertGreater(effect_heterogeneity_spread(effects), 0.05)

    def test_sign_agreement_catches_a_flip(self):
        self.assertEqual(1.0, sign_agreement({"a": -0.1, "b": 0.2}, {"a": -0.05, "b": 0.3}))
        self.assertEqual(0.5, sign_agreement({"a": -0.1, "b": 0.2}, {"a": 0.05, "b": 0.3}))

    def test_distribution_gap_reports_sd_ratio(self):
        ref = {"x": list(np.linspace(0.0, 1.0, 50))}
        cand = {"x": list(np.linspace(0.4, 0.6, 50))}
        gap = distribution_gap(ref, cand)["x"]
        self.assertLess(gap["sd_ratio"], 0.5)


class ReferenceTierTests(unittest.TestCase):
    def test_contagion_produces_positive_social_autocorrelation(self):
        """The reference must actually generate what L2 measures.

        Guards the bug this replaced: a mean-reversion social term
        (``peer_mean − own_value``) makes neighbouring *changes*
        anti-correlated, leaving Moran's I at zero and L2 unable to
        discriminate anything.
        """
        agents, neighbours = _population(120, seed=7)
        result = run_reference_tier(agents, neighbours, days=14, seed=1)
        signals = []
        for key in FOCUS_KEYS:
            traj = result["trajectories"][key]
            change = {i: s[-1] - s[0] for i, s in traj.items() if s}
            signals.append(morans_i(change, neighbours))
        self.assertGreater(max(signals), 0.05, f"no contagion signal: {signals}")

    def test_contagion_reads_yesterdays_deltas_not_todays(self):
        # If influence read same-day deltas, iteration order would matter and a
        # single day would propagate across the whole graph.
        agents, neighbours = _population(80, seed=7)
        forward = run_reference_tier([copy.deepcopy(a) for a in agents], neighbours, days=5, seed=1)
        reversed_agents = list(reversed([copy.deepcopy(a) for a in agents]))
        backward = run_reference_tier(reversed_agents, neighbours, days=5, seed=1)
        forward_by_id = {a["id"]: a["state"]["stress"] for a in forward["agents"]}
        backward_by_id = {a["id"]: a["state"]["stress"] for a in backward["agents"]}
        # Per-agent noise draws follow iteration order, so values differ; what
        # must not differ is the population distribution.
        self.assertAlmostEqual(
            float(np.mean(list(forward_by_id.values()))),
            float(np.mean(list(backward_by_id.values()))),
            delta=0.02,
        )

    def test_shock_only_applies_from_its_start_day(self):
        agents, neighbours = _population(60, seed=7)
        no_shock = run_reference_tier([copy.deepcopy(a) for a in agents], neighbours, days=6, seed=1)
        late_shock = run_reference_tier(
            [copy.deepcopy(a) for a in agents],
            neighbours,
            days=6,
            seed=1,
            shock={"econ_security": -0.05},
            shock_from_day=99,
        )
        self.assertEqual(
            [a["state"]["econ_security"] for a in no_shock["agents"]],
            [a["state"]["econ_security"] for a in late_shock["agents"]],
        )

    def test_shock_moves_the_outcome_in_its_own_direction(self):
        agents, neighbours = _population(60, seed=7)
        control = run_reference_tier([copy.deepcopy(a) for a in agents], neighbours, days=10, seed=1)
        treated = run_reference_tier(
            [copy.deepcopy(a) for a in agents],
            neighbours,
            days=10,
            seed=1,
            shock={"econ_security": -0.05},
            shock_from_day=3,
        )
        self.assertLess(
            float(np.mean([a["state"]["econ_security"] for a in treated["agents"]])),
            float(np.mean([a["state"]["econ_security"] for a in control["agents"]])),
        )

    def test_reference_is_reproducible(self):
        agents, neighbours = _population(60, seed=7)
        first = run_reference_tier([copy.deepcopy(a) for a in agents], neighbours, days=5, seed=3)
        second = run_reference_tier([copy.deepcopy(a) for a in agents], neighbours, days=5, seed=3)
        self.assertEqual([a["state"] for a in first["agents"]], [a["state"] for a in second["agents"]])

    def test_state_stays_in_range(self):
        agents, neighbours = _population(60, seed=7)
        result = run_reference_tier(agents, neighbours, days=20, seed=1)
        for agent in result["agents"]:
            for key in STATE_VAR_KEYS:
                self.assertGreaterEqual(agent["state"][key], 0.0)
                self.assertLessEqual(agent["state"][key], 1.0)

    def test_day_fn_signature_tolerates_missing_context(self):
        _agents, neighbours = _population(30, seed=7)
        day = make_reference_day(neighbours, seed=0)
        agent = {"id": 1, "state": dict.fromkeys(STATE_VAR_KEYS, 0.5)}
        outcome = day(agent, day=1)
        self.assertIn("state_changes", outcome)


class BaselineTests(unittest.TestCase):
    def test_baseline_is_positive_and_finite(self):
        agents, neighbours = _population(80, seed=11)
        baseline = cross_seed_baseline(agents, neighbours, days=10, seeds=(1, 2, 3))
        self.assertGreater(baseline["wasserstein1_max"], 0.0)
        self.assertTrue(math.isfinite(baseline["wasserstein1_max"]))
        self.assertEqual([1, 2, 3], baseline["seeds"])

    def test_baseline_grows_with_horizon(self):
        # Longer runs diverge more between seeds, so the tolerance the gate
        # grants must scale with the horizon rather than being a constant.
        agents, neighbours = _population(80, seed=11)
        short = cross_seed_baseline(agents, neighbours, days=3, seeds=(1, 2))
        long = cross_seed_baseline(agents, neighbours, days=20, seeds=(1, 2))
        self.assertGreater(long["wasserstein1_max"], short["wasserstein1_max"])


class GateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agents, cls.neighbours = _population(100, seed=42)
        cls.verdict = run_validation(cls.agents, cls.neighbours, days=14, seed=1, materialization_budget=20)

    def test_all_four_layers_are_evaluated(self):
        self.assertEqual(["L1", "L2", "L3", "L4"], [r.layer for r in self.verdict.layers])

    def test_every_layer_carries_a_status_and_detail(self):
        for result in self.verdict.layers:
            self.assertIn(result.status, {"pass", "fail", "inconclusive"})
            self.assertTrue(result.detail)
            self.assertTrue(result.note)

    def test_l2_fails_without_network_coupling(self):
        """The Phase 3 finding, pinned: uniform cohort shifts cannot carry graph
        structure.

        With ``network_coupling=0`` a cohort delta is the same for every member
        and the cohort partition is not the social graph, so neighbour-mediated
        co-movement is structurally unreachable. Phase 4 fixes this with a
        mean-zero graph term; this test keeps the *unfixed* behaviour pinned so
        the fix cannot be silently reverted into a false pass.
        """
        l2 = next(r for r in self.verdict.layers if r.layer == "L2")
        self.assertFalse(l2.passed)
        self.assertFalse(l2.inconclusive, "the reference must generate a usable signal")
        self.assertGreater(l2.detail["worst_z"], l2.detail["tolerance_z"])

    def test_l4_passes_so_policy_effects_are_usable(self):
        l4 = next(r for r in self.verdict.layers if r.layer == "L4")
        self.assertTrue(l4.passed, l4.detail)
        self.assertTrue(l4.detail["same_sign"])
        self.assertLess(l4.detail["magnitude_relative_error"], 0.20)

    def test_gate_is_not_passed_while_a_dividing_line_fails(self):
        self.assertFalse(self.verdict.gate_passed)
        self.assertFalse(self.verdict.all_passed)

    def test_verdict_renders_without_raising(self):
        text = render_verdict(self.verdict)
        self.assertIn("L1", text)
        self.assertIn("L4", text)
        self.assertIn("关口结论", text)

    def test_verdict_serialises(self):
        payload = self.verdict.to_dict()
        self.assertEqual(4, len(payload["layers"]))
        self.assertIn("gate_passed", payload)
        self.assertIn("baseline", payload)


class NegativeControlTests(unittest.TestCase):
    """Each test breaks the candidate in one way and demands the gate notice."""

    def test_l1_fails_when_the_candidate_distribution_is_shifted(self):
        agents, neighbours = _population(100, seed=42)

        def biased_delta(cohort, day):
            return {"stress": 0.05, "emotion": 0.05}

        reference = run_reference_tier([copy.deepcopy(a) for a in agents], neighbours, days=10, seed=1)
        biased = run_group_tier(
            [copy.deepcopy(a) for a in agents],
            neighbours,
            days=10,
            seed=1,
            cohort_delta_fn=biased_delta,
        )
        from gaworld.group.metrics import state_columns

        gaps = distribution_gap(
            state_columns(reference["agents"], FOCUS_KEYS),
            state_columns(biased["agents"], FOCUS_KEYS),
        )
        baseline = cross_seed_baseline(agents, neighbours, days=10, seeds=(1, 2, 3))
        # A systematic daily bias must exceed the reference's own seed noise.
        self.assertGreater(
            gaps["stress"]["wasserstein1"],
            baseline["wasserstein1_by_key"]["stress"] * 2.0,
        )

    def test_l3_detects_a_collapsed_distribution(self):
        wide = list(np.linspace(0.0, 1.0, 100))
        collapsed = [0.5] * 100
        ref = tail_shares(wide)
        cand = tail_shares(collapsed)
        self.assertGreater(abs(cand["low_share"] - ref["low_share"]), 0.10)

    def test_l4_detects_a_sign_flip(self):
        control = {1: 0.5, 2: 0.5, 3: 0.5}
        reference_treated = {1: 0.4, 2: 0.4, 3: 0.4}
        flipped_treated = {1: 0.6, 2: 0.6, 3: 0.6}
        ref_ate = average_treatment_effect(control, reference_treated)
        bad_ate = average_treatment_effect(control, flipped_treated)
        self.assertNotEqual(ref_ate >= 0, bad_ate >= 0)

    def test_l4_detects_collapsed_heterogeneity(self):
        control = dict.fromkeys(range(1, 5), 0.5)
        groups = {1: "a", 2: "a", 3: "b", 4: "b"}
        varied = {1: 0.3, 2: 0.3, 3: 0.7, 4: 0.7}
        flat = {1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5}
        varied_spread = effect_heterogeneity_spread(heterogeneous_effects(control, varied, groups))
        flat_spread = effect_heterogeneity_spread(heterogeneous_effects(control, flat, groups))
        self.assertGreater(varied_spread, 0.1)
        self.assertLess(flat_spread / varied_spread, 0.5)

    def test_l2_reports_inconclusive_rather_than_passing_on_noise(self):
        """A reference with no social mechanism must not yield a verdict.

        This is the guard for the gate's original mistake: dividing two
        near-zero Moran's I values produced ratios like −75.9, which looked like
        a precise finding and was pure noise.
        """
        from gaworld.group.validate import _evaluate_l2

        flat = {"trajectories": {key: {i: [0.5, 0.5] for i in range(1, 21)} for key in FOCUS_KEYS}}
        neighbours = {i: [i % 20 + 1] for i in range(1, 21)}
        baseline = {"morans_i_sd_by_key": dict.fromkeys(FOCUS_KEYS, 0.02)}
        result = _evaluate_l2([(flat, flat)], neighbours, baseline, 2.0)
        self.assertTrue(result.inconclusive)
        self.assertEqual("inconclusive", result.status)
        self.assertFalse(result.passed)

    def test_inconclusive_dividing_line_does_not_pass_the_gate(self):
        from gaworld.group.validate import LayerResult, ValidationVerdict

        verdict = ValidationVerdict(
            population=10,
            days=1,
            layers=[
                LayerResult(layer="L2", name="x", passed=False, inconclusive=True),
                LayerResult(layer="L4", name="y", passed=True),
            ],
        )
        self.assertFalse(verdict.gate_passed)
        self.assertEqual(["L2"], verdict.inconclusive_layers)


class NetworkCouplingTests(unittest.TestCase):
    """Phase 4: the graph term that fixes L2.

    Its safety rests on one property — the coupling is mean-zero within each
    cohort, so it redistributes *within* the group without touching the group
    mean the cohort layer predicted. That is what lets it fix L2 without putting
    the already-passing L1 and L4 at risk.
    """

    def test_coupling_preserves_the_cohort_mean_exactly(self):
        from gaworld.group.cohort import (
            NetworkCoupling,
            apply_cohort_state_changes,
            partition_cohorts,
            refresh_cohort_statistics,
        )

        agents, neighbours = _population(200, seed=3)
        by_id = {a["id"]: a for a in agents}
        cohort = partition_cohorts(agents)[0]
        refresh_cohort_statistics(cohort, by_id)
        before = cohort.centroid["stress"]

        previous = {a["id"]: {"stress": 0.05 if a["id"] % 2 else -0.05} for a in agents}
        apply_cohort_state_changes(
            cohort,
            {"stress": 0.04},
            by_id,
            coupling=NetworkCoupling(neighbours=neighbours, previous_deltas=previous, weight=0.7),
        )
        # Mean moves by exactly the cohort delta; the graph term cancels.
        self.assertAlmostEqual(before + 0.04, cohort.centroid["stress"], places=6)

    def test_coupling_creates_per_member_variation(self):
        from gaworld.group.cohort import (
            NetworkCoupling,
            apply_cohort_state_changes,
            partition_cohorts,
            refresh_cohort_statistics,
        )

        agents, neighbours = _population(200, seed=3)
        by_id = {a["id"]: a for a in agents}
        cohort = partition_cohorts(agents)[0]
        refresh_cohort_statistics(cohort, by_id)
        previous = {a["id"]: {"stress": 0.05 if a["id"] % 2 else -0.05} for a in agents}
        apply_cohort_state_changes(
            cohort,
            {"stress": 0.04},
            by_id,
            coupling=NetworkCoupling(neighbours=neighbours, previous_deltas=previous, weight=0.7),
        )
        applied = [d["stress"] for d in cohort.last_member_deltas.values() if "stress" in d]
        self.assertGreater(len({round(v, 6) for v in applied}), 1)

    def test_zero_weight_is_identical_to_no_coupling(self):
        from gaworld.group.cohort import (
            NetworkCoupling,
            apply_cohort_state_changes,
            partition_cohorts,
            refresh_cohort_statistics,
        )

        def run(coupling):
            agents, neighbours = _population(150, seed=3)
            by_id = {a["id"]: a for a in agents}
            cohort = partition_cohorts(agents)[0]
            refresh_cohort_statistics(cohort, by_id)
            previous = {a["id"]: {"stress": 0.05} for a in agents}
            apply_cohort_state_changes(
                cohort,
                {"stress": 0.04},
                by_id,
                coupling=(
                    NetworkCoupling(neighbours=neighbours, previous_deltas=previous, weight=0.0)
                    if coupling
                    else None
                ),
            )
            return [by_id[m]["state"]["stress"] for m in cohort.members]

        self.assertEqual(run(False), run(True))

    def test_coupling_raises_the_group_tiers_social_autocorrelation(self):
        agents, neighbours = _population(150, seed=3)
        signals = {}
        for weight in (0.0, 0.7):
            result = run_group_tier(
                [copy.deepcopy(a) for a in agents],
                neighbours,
                days=14,
                seed=1,
                materialization_budget=10,
                network_coupling=weight,
            )
            traj = result["trajectories"]["city_identity"]
            change = {i: s[-1] - s[0] for i, s in traj.items() if s}
            signals[weight] = morans_i(change, neighbours)
        self.assertGreater(signals[0.7], signals[0.0])

    def test_driver_rejects_coupling_without_a_graph(self):
        # A positive coupling with no graph would silently behave like the
        # unfixed version while looking configured.
        from gaworld.group.driver import GroupRunConfig, run_group_simulation

        agents, _ = _population(60, seed=3)
        with self.assertRaises(ValueError):
            run_group_simulation(agents, GroupRunConfig(days=1, network_coupling=0.5))

    def test_gate_passes_with_coupling_and_fails_without(self):
        """The Phase 4 result, pinned end to end."""
        agents, neighbours = _population(100, seed=42)
        without = run_validation(
            agents,
            neighbours,
            days=14,
            seed=1,
            materialization_budget=20,
            network_coupling=0.0,
        )
        with_coupling = run_validation(
            agents,
            neighbours,
            days=14,
            seed=1,
            materialization_budget=20,
            network_coupling=0.7,
        )
        self.assertFalse(without.gate_passed)
        self.assertTrue(with_coupling.gate_passed, with_coupling.to_dict()["layers"])
        # The layers that already passed must not have been traded away.
        for layer in ("L1", "L3", "L4"):
            self.assertTrue(next(r for r in with_coupling.layers if r.layer == layer).passed, layer)


class ReproducibilityTests(unittest.TestCase):
    def test_the_whole_gate_is_reproducible(self):
        agents, neighbours = _population(80, seed=42)
        first = run_validation(agents, neighbours, days=8, seed=2, materialization_budget=10)
        second = run_validation(agents, neighbours, days=8, seed=2, materialization_budget=10)
        self.assertEqual(
            [(r.layer, r.status) for r in first.layers],
            [(r.layer, r.status) for r in second.layers],
        )
        self.assertEqual(first.baseline, second.baseline)

    def test_gate_does_not_mutate_the_input_population(self):
        agents, neighbours = _population(60, seed=42)
        before = [dict(a["state"]) for a in agents]
        run_validation(agents, neighbours, days=5, seed=1, materialization_budget=5)
        self.assertEqual(before, [dict(a["state"]) for a in agents])


if __name__ == "__main__":
    unittest.main()
