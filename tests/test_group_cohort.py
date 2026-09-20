"""Phase 2: the cohort (group) tier.

The tests are organised around the four claims the tier makes:

* **partition integrity** — every resident is in exactly one cohort, always;
* **dispersion survives** — a cohort day moves the group mean without
  collapsing within-group spread, because collapsing it is precisely the
  representative-agent failure the tier is designed to avoid;
* **the residual is meaningful** — it is zero when the cohort's prediction was
  right and non-zero when it was wrong, independent of which members happened
  to be sampled;
* **cost scales with cohort count, not headcount**.

Every LLM interaction is mocked; nothing here touches the network.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.group.cohort import (
    DEFAULT_COHORT_AXES,
    Cohort,
    apply_cohort_state_changes,
    cohort_summary,
    partition_cohorts,
    refresh_cohort_statistics,
)
from gaworld.group.cohort_day import (
    COHORT_STATE_KEYS,
    effective_state_changes,
    fallback_cohort_digest,
    normalize_cohort_digest,
    render_cohort_brief_block,
    simulate_cohort_day,
)
from gaworld.group.driver import GroupRunConfig, render_day_block, run_group_simulation
from gaworld.group.materialize import (
    audit_residual,
    cohort_distance,
    select_materialized,
)
from gaworld.population.generate import generate_population
from gaworld.population.schema import STATE_VAR_KEYS, normalize_spec


def _agents(size: int = 200, seed: int = 5) -> list[dict]:
    result = generate_population(normalize_spec({"size": size, "seed": seed}))
    return [
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


def _mock_llm(**overrides):
    payload = {
        "brief": "这群人今天照常上班，普遍感到物价压力。",
        "divergence": "其中平台接单的一部分人收入波动更大",
        "memory": "菜价又涨了",
        "state_changes": {"stress": 0.05, "econ_security": -0.04},
        "share_affected": 1.0,
    }
    payload.update(overrides)

    def call(prompt, task=None, agent_id=None):
        return json.dumps(payload, ensure_ascii=False)

    return call


class PartitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agents = _agents(300, seed=3)
        cls.cohorts = partition_cohorts(cls.agents)

    def test_every_agent_is_in_exactly_one_cohort(self):
        members = [m for c in self.cohorts for m in c.members]
        self.assertEqual(len(self.agents), len(members))
        self.assertEqual(len(self.agents), len(set(members)))
        self.assertEqual({int(a["id"]) for a in self.agents}, set(members))

    def test_cohort_count_is_in_a_workable_range(self):
        # The design target is tens of cohorts for a few hundred residents:
        # enough to be heterogeneous, few enough that a cohort-day per cohort
        # is cheap.
        self.assertGreaterEqual(len(self.cohorts), 5)
        self.assertLessEqual(len(self.cohorts), 80)

    def test_no_cohort_below_the_minimum_size(self):
        for cohort in self.cohorts:
            self.assertGreaterEqual(cohort.size, 4, cohort.label())

    def test_tiny_cells_are_merged_not_dropped(self):
        # A single-axis partition on a rare attribute creates tiny cells; they
        # must be absorbed, never discarded.
        cohorts = partition_cohorts(self.agents, axes=("industry",), min_size=40)
        members = [m for c in cohorts for m in c.members]
        self.assertEqual(len(self.agents), len(set(members)))

    def test_unknown_axis_raises_rather_than_silently_coarsening(self):
        with self.assertRaises(ValueError):
            partition_cohorts(self.agents, axes=("age_band", "not_an_axis"))

    def test_empty_axes_rejected(self):
        with self.assertRaises(ValueError):
            partition_cohorts(self.agents, axes=())

    def test_finer_axes_produce_more_cohorts(self):
        coarse = partition_cohorts(self.agents, axes=("age_band",), min_size=1)
        fine = partition_cohorts(self.agents, axes=DEFAULT_COHORT_AXES, min_size=1)
        self.assertGreater(len(fine), len(coarse))

    def test_tiny_population_still_yields_a_valid_partition(self):
        agents = _agents(25, seed=9)
        cohorts = partition_cohorts(agents)
        members = [m for c in cohorts for m in c.members]
        self.assertEqual(len(agents), len(set(members)))
        self.assertGreaterEqual(len(cohorts), 1)


class StatisticsTests(unittest.TestCase):
    def test_centroid_and_dispersion_match_members(self):
        agents = [
            {"id": 1, "state": dict.fromkeys(STATE_VAR_KEYS, 0.2)},
            {"id": 2, "state": dict.fromkeys(STATE_VAR_KEYS, 0.8)},
        ]
        cohort = Cohort(id="c", key=("x",), axes=("age_band",), members=[1, 2])
        refresh_cohort_statistics(cohort, {a["id"]: a for a in agents})
        for key in STATE_VAR_KEYS:
            self.assertAlmostEqual(0.5, cohort.centroid[key], places=6)
            self.assertAlmostEqual(0.3, cohort.dispersion[key], places=6)

    def test_summary_reports_spread_not_just_the_mean(self):
        agents = [
            {"id": 1, "state": dict.fromkeys(STATE_VAR_KEYS, 0.1)},
            {"id": 2, "state": dict.fromkeys(STATE_VAR_KEYS, 0.9)},
        ]
        cohort = Cohort(id="c", key=("x",), axes=("age_band",), members=[1, 2])
        refresh_cohort_statistics(cohort, {a["id"]: a for a in agents})
        summary = cohort_summary(cohort)
        self.assertIn("离散", summary)
        # A cohort split between extremes must say so, not report "0.50".
        self.assertTrue("低于0.4" in summary or "高于0.6" in summary, summary)

    def test_empty_cohort_statistics_are_neutral_not_nan(self):
        cohort = Cohort(id="c", key=("x",), axes=("age_band",), members=[])
        refresh_cohort_statistics(cohort, {})
        for key in STATE_VAR_KEYS:
            self.assertEqual(0.5, cohort.centroid[key])
            self.assertEqual(0.0, cohort.dispersion[key])


class ApplyDeltaTests(unittest.TestCase):
    def _cohort(self):
        agents = {
            i: {"id": i, "state": dict.fromkeys(STATE_VAR_KEYS, value)}
            for i, value in zip(range(1, 6), [0.2, 0.35, 0.5, 0.65, 0.8], strict=True)
        }
        cohort = Cohort(id="c", key=("x",), axes=("age_band",), members=list(agents))
        refresh_cohort_statistics(cohort, agents)
        return cohort, agents

    def test_group_delta_moves_the_mean(self):
        cohort, agents = self._cohort()
        before = cohort.centroid["stress"]
        apply_cohort_state_changes(cohort, {"stress": 0.1}, agents)
        self.assertAlmostEqual(before + 0.1, cohort.centroid["stress"], places=6)

    def test_group_delta_preserves_dispersion(self):
        """The load-bearing property of the whole tier."""
        cohort, agents = self._cohort()
        before = cohort.dispersion["stress"]
        apply_cohort_state_changes(cohort, {"stress": 0.1}, agents)
        self.assertAlmostEqual(before, cohort.dispersion["stress"], places=6)

    def test_delta_is_clamped(self):
        cohort, agents = self._cohort()
        applied = apply_cohort_state_changes(cohort, {"stress": 5.0}, agents, max_delta=0.12)
        self.assertAlmostEqual(0.12, applied["stress"], places=6)

    def test_unknown_keys_ignored(self):
        cohort, agents = self._cohort()
        applied = apply_cohort_state_changes(cohort, {"not_a_state": 0.1}, agents)
        self.assertEqual({}, applied)

    def test_materialized_members_are_skipped(self):
        cohort, agents = self._cohort()
        before = agents[1]["state"]["stress"]
        apply_cohort_state_changes(cohort, {"stress": 0.1}, agents, skip=[1])
        self.assertEqual(before, agents[1]["state"]["stress"])
        self.assertAlmostEqual(0.35 + 0.1, agents[2]["state"]["stress"], places=6)

    def test_values_stay_in_range(self):
        cohort, agents = self._cohort()
        for _ in range(20):
            apply_cohort_state_changes(cohort, {"stress": 0.12}, agents)
        for agent in agents.values():
            self.assertLessEqual(agent["state"]["stress"], 1.0)
            self.assertGreaterEqual(agent["state"]["stress"], 0.0)

    def test_dispersion_retention_contracts_spread_when_asked(self):
        cohort, agents = self._cohort()
        before = cohort.dispersion["stress"]
        apply_cohort_state_changes(cohort, {"stress": 0.0}, agents, dispersion_retention=0.5)
        self.assertLess(cohort.dispersion["stress"], before)


class CohortDayTests(unittest.TestCase):
    def _cohort(self):
        agents = {i: {"id": i, "state": dict.fromkeys(STATE_VAR_KEYS, 0.5)} for i in range(1, 11)}
        cohort = Cohort(
            id="c001", key=("18-34", "tech", "本地"), axes=DEFAULT_COHORT_AXES, members=list(agents)
        )
        refresh_cohort_statistics(cohort, agents)
        return cohort

    def test_llm_path_parses_a_digest(self):
        digest = simulate_cohort_day(self._cohort(), day=1, llm_fn=_mock_llm())
        self.assertFalse(digest["fallback"])
        self.assertTrue(digest["brief"])
        self.assertEqual({"stress", "econ_security"}, set(digest["state_changes"]))

    def test_prompt_frames_the_group_as_heterogeneous(self):
        captured = {}

        def spy(prompt, task=None, agent_id=None):
            captured["prompt"] = prompt
            return json.dumps({"brief": "x"}, ensure_ascii=False)

        simulate_cohort_day(self._cohort(), day=1, llm_fn=spy)
        # Without this framing the cohort call degenerates into a
        # representative-agent call.
        self.assertIn("有内部差异", captured["prompt"])
        self.assertIn("离散", captured["prompt"])

    def test_fallback_when_llm_disabled(self):
        digest = simulate_cohort_day(self._cohort(), day=1, use_llm=False, llm_fn=_mock_llm())
        self.assertTrue(digest["fallback"])
        self.assertTrue(digest["brief"], "a fallback day must still say something")

    def test_fallback_when_llm_raises(self):
        def boom(prompt, task=None, agent_id=None):
            raise RuntimeError("provider down")

        digest = simulate_cohort_day(self._cohort(), day=1, llm_fn=boom)
        self.assertTrue(digest["fallback"])

    def test_fallback_on_unparseable_response(self):
        digest = simulate_cohort_day(self._cohort(), day=1, llm_fn=lambda *a, **k: "sorry, no JSON here")
        self.assertTrue(digest["fallback"])

    def test_bare_magicmock_response_does_not_explode(self):
        # A test that patches call_llm without configuring a return value is a
        # common mistake; it should degrade to the fallback, not raise a
        # confusing TypeError from inside `re`.
        digest = simulate_cohort_day(self._cohort(), day=1, llm_fn=MagicMock())
        self.assertTrue(digest["fallback"])

    def test_deltas_are_clamped_and_keys_filtered(self):
        digest = simulate_cohort_day(
            self._cohort(),
            day=1,
            max_delta=0.1,
            llm_fn=_mock_llm(state_changes={"stress": 9.0, "bogus": 0.5}),
        )
        self.assertEqual({"stress"}, set(digest["state_changes"]))
        self.assertAlmostEqual(0.1, digest["state_changes"]["stress"], places=6)

    def test_share_affected_scales_the_group_mean_shift(self):
        digest = normalize_cohort_digest(
            {"brief": "x", "state_changes": {"stress": 0.10}, "share_affected": 0.4},
            max_delta=0.12,
            brief_max_chars=200,
        )
        scaled = effective_state_changes(digest)
        # 10% effect on 40% of the group is a 4% shift in the group mean.
        self.assertAlmostEqual(0.04, scaled["stress"], places=6)

    def test_share_affected_is_clamped_to_a_probability(self):
        digest = normalize_cohort_digest(
            {"brief": "x", "share_affected": 7.5}, max_delta=0.12, brief_max_chars=200
        )
        self.assertEqual(1.0, digest["share_affected"])

    def test_cohort_state_keys_cover_voice_and_risk(self):
        # Group mode exists partly to study polarisation and collective voice;
        # the individual fast-forward's key set omits these two, and inheriting
        # that omission would make the tier unable to represent its own subject.
        self.assertIn("voice_propensity", COHORT_STATE_KEYS)
        self.assertIn("risk_preference", COHORT_STATE_KEYS)

    def test_fallback_digest_is_marked_and_renderable(self):
        cohort = self._cohort()
        digest = fallback_cohort_digest(cohort, day=3)
        block = render_cohort_brief_block(cohort, 3, digest)
        self.assertIn("fallback", block)


class MaterializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agents = _agents(300, seed=7)
        cls.by_id = {a["id"]: a for a in cls.agents}
        cls.cohorts = partition_cohorts(cls.agents)

    def test_focal_agents_are_always_included(self):
        plan = select_materialized(
            self.cohorts,
            self.by_id,
            day=1,
            budget=1,
            focal_ids=[5, 11, 17],
            audit_fraction=0.05,
        )
        # Budget of 1 must not silently drop the agents the researcher named.
        for agent_id in (5, 11, 17):
            self.assertIn(agent_id, plan.all_ids)
            self.assertEqual("focal", plan.reason_for(agent_id))

    def test_event_agents_are_included_and_labelled(self):
        plan = select_materialized(
            self.cohorts, self.by_id, day=1, budget=10, event_ids=[23], audit_fraction=0.0
        )
        self.assertIn(23, plan.all_ids)
        self.assertEqual("event", plan.reason_for(23))

    def test_audit_sample_is_drawn_and_sized_from_the_fraction(self):
        plan = select_materialized(self.cohorts, self.by_id, day=1, budget=40, audit_fraction=0.05)
        self.assertGreater(len(plan.audit), 0)
        self.assertLessEqual(len(plan.audit), round(0.05 * len(self.agents)))

    def test_audit_sample_spans_multiple_cohorts(self):
        plan = select_materialized(self.cohorts, self.by_id, day=1, budget=60, audit_fraction=0.10)
        member_to_cohort = {m: c.id for c in self.cohorts for m in c.members}
        covered = {member_to_cohort[m] for m in plan.audit}
        self.assertGreater(len(covered), 1, "audit must not concentrate in one cohort")

    def test_tail_selection_prefers_members_far_from_their_centroid(self):
        plan = select_materialized(self.cohorts, self.by_id, day=1, budget=30, audit_fraction=0.0)
        self.assertTrue(plan.tail)
        cohort_of = {m: c for c in self.cohorts for m in c.members}
        tail_scores = [cohort_distance(cohort_of[m], self.by_id[m]) for m in plan.tail]
        others = [
            cohort_distance(c, self.by_id[m])
            for c in self.cohorts
            for m in c.members
            if m not in set(plan.all_ids)
        ]
        self.assertGreater(min(tail_scores), np.median(others))

    def test_no_duplicates_across_categories(self):
        plan = select_materialized(
            self.cohorts, self.by_id, day=1, budget=40, focal_ids=[5], audit_fraction=0.05
        )
        self.assertEqual(len(plan.all_ids), len(set(plan.all_ids)))

    def test_distance_is_scaled_by_within_cohort_spread(self):
        # The same absolute deviation should score higher in a tight cohort
        # than in a scattered one — otherwise tail selection ranks by raw
        # deviation and misses the members their cohort actually cannot speak
        # for.
        tight_members = {i: {"id": i, "state": dict.fromkeys(STATE_VAR_KEYS, 0.5)} for i in range(1, 6)}
        loose_members = {
            i: {"id": i, "state": dict.fromkeys(STATE_VAR_KEYS, v)}
            for i, v in zip(range(1, 6), [0.1, 0.3, 0.5, 0.7, 0.9], strict=True)
        }
        tight = Cohort(id="t", key=("x",), axes=("age_band",), members=list(tight_members))
        loose = Cohort(id="l", key=("x",), axes=("age_band",), members=list(loose_members))
        refresh_cohort_statistics(tight, tight_members)
        refresh_cohort_statistics(loose, loose_members)
        outlier = {"id": 99, "state": dict.fromkeys(STATE_VAR_KEYS, 0.8)}
        self.assertGreater(cohort_distance(tight, outlier), cohort_distance(loose, outlier))


class AuditResidualTests(unittest.TestCase):
    def _setup(self):
        agents = {i: {"id": i, "state": dict.fromkeys(STATE_VAR_KEYS, 0.5)} for i in range(1, 21)}
        cohort = Cohort(id="c", key=("x",), axes=("age_band",), members=list(agents))
        refresh_cohort_statistics(cohort, agents)
        before = {i: dict(agents[i]["state"]) for i in agents}
        return cohort, agents, before

    def test_zero_when_the_prediction_was_exactly_right(self):
        cohort, agents, before = self._setup()
        for agent in agents.values():
            agent["state"]["stress"] += 0.05
        residual = audit_residual(cohort, agents, [1, 2, 3], {"stress": 0.05}, before)
        self.assertAlmostEqual(0.0, residual["residual_l1"], places=9)

    def test_nonzero_when_the_prediction_was_wrong(self):
        cohort, agents, before = self._setup()
        for agent in agents.values():
            agent["state"]["stress"] += 0.05
        residual = audit_residual(cohort, agents, [1, 2, 3], {"stress": 0.0}, before)
        self.assertAlmostEqual(0.05, residual["residual"]["stress"], places=9)

    def test_zero_when_nothing_happened_and_nothing_was_predicted(self):
        cohort, agents, before = self._setup()
        residual = audit_residual(cohort, agents, [1, 2, 3], {}, before)
        self.assertAlmostEqual(0.0, residual["residual_l1"], places=9)

    def test_invariant_to_which_members_were_sampled(self):
        """The bug this replaced: residual must not measure sampling error.

        Members start at *different* levels. A residual defined on levels would
        report a large value here purely because the sampled members are not at
        their cohort's mean. Defined on changes, it is zero.
        """
        agents = {i: {"id": i, "state": dict.fromkeys(STATE_VAR_KEYS, 0.1 + 0.04 * i)} for i in range(1, 21)}
        cohort = Cohort(id="c", key=("x",), axes=("age_band",), members=list(agents))
        refresh_cohort_statistics(cohort, agents)
        before = {i: dict(agents[i]["state"]) for i in agents}
        for agent in agents.values():
            agent["state"]["stress"] = min(1.0, agent["state"]["stress"] + 0.05)

        low = audit_residual(cohort, agents, [1, 2, 3], {"stress": 0.05}, before)
        high = audit_residual(cohort, agents, [17, 18, 19], {"stress": 0.05}, before)
        self.assertAlmostEqual(0.0, low["residual_l1"], places=9)
        self.assertAlmostEqual(0.0, high["residual_l1"], places=9)

    def test_empty_sample_is_handled(self):
        cohort, agents, before = self._setup()
        residual = audit_residual(cohort, agents, [], {"stress": 0.05}, before)
        self.assertEqual(0, residual["sample_size"])
        self.assertEqual(0.0, residual["residual_l1"])


class DriverTests(unittest.TestCase):
    def test_null_run_reports_zero_residual(self):
        """Sanity floor: if nothing changes, the measured error must be zero."""
        result = run_group_simulation(_agents(200, seed=5), GroupRunConfig(days=3, use_llm=False, seed=1))
        self.assertEqual(0.0, max(d.max_residual_l1 for d in result.days))

    def test_llm_cost_scales_with_cohort_count_not_population(self):
        agents = _agents(200, seed=5)
        cfg = GroupRunConfig(days=4, materialization_budget=0, audit_fraction=0.0, seed=1)
        result = run_group_simulation(agents, cfg, llm_fn=_mock_llm())
        self.assertEqual(len(result.cohorts) * 4, result.total_llm_calls)
        self.assertLess(result.total_llm_calls, len(agents))

    def test_state_actually_evolves(self):
        agents = _agents(200, seed=5)
        before = [a["state"]["stress"] for a in agents]
        run_group_simulation(agents, GroupRunConfig(days=3, seed=1), llm_fn=_mock_llm())
        after = [a["state"]["stress"] for a in agents]
        self.assertNotEqual(before, after)

    def test_dispersion_does_not_collapse_over_a_run(self):
        agents = _agents(200, seed=5)
        cfg = GroupRunConfig(days=10, seed=1)
        result = run_group_simulation(agents, cfg, llm_fn=_mock_llm())
        for cohort in result.cohorts:
            if cohort.size < 5:
                continue
            # Some spread must remain; a cohort that has become a point mass
            # is a representative agent by another name.
            self.assertGreater(max(cohort.dispersion.values()), 0.01, cohort.label())

    def test_focal_agent_is_materialised_every_day(self):
        agents = _agents(200, seed=5)
        cfg = GroupRunConfig(days=4, focal_ids=[9], seed=1)
        result = run_group_simulation(agents, cfg, llm_fn=_mock_llm())
        for record in result.days:
            self.assertIn(9, record.plan.all_ids)

    def test_run_is_reproducible(self):
        def run():
            agents = _agents(150, seed=5)
            cfg = GroupRunConfig(days=3, seed=11)
            result = run_group_simulation(agents, cfg, llm_fn=_mock_llm())
            return [a["state"]["stress"] for a in agents], [d.plan.to_dict() for d in result.days]

        first_states, first_plans = run()
        second_states, second_plans = run()
        self.assertEqual(first_states, second_states)
        self.assertEqual(first_plans, second_plans)

    def test_residual_detects_a_divergent_individual_tier(self):
        agents = _agents(300, seed=5)
        rng = np.random.default_rng(0)

        def individual_day(agent, *, day):
            # Individuals move the *opposite* way from the cohort prediction.
            agent["state"]["stress"] = float(
                np.clip(agent["state"]["stress"] - 0.10 + rng.normal(0, 0.01), 0, 1)
            )
            return {"llm_calls": 198}

        cfg = GroupRunConfig(days=3, materialization_budget=25, audit_fraction=0.05, seed=1)
        result = run_group_simulation(agents, cfg, llm_fn=_mock_llm(), individual_day_fn=individual_day)
        self.assertGreater(max(d.max_residual_l1 for d in result.days), 0.05)

    def test_cost_summary_is_arithmetically_consistent(self):
        agents = _agents(200, seed=5)
        cfg = GroupRunConfig(days=5, materialization_budget=10, audit_fraction=0.0, seed=1)
        result = run_group_simulation(
            agents, cfg, llm_fn=_mock_llm(), individual_day_fn=lambda a, *, day: {"llm_calls": 198}
        )
        cost = result.cost_summary(individual_calls_per_agent_day=198)
        self.assertEqual(200 * 5 * 198, cost["full_individual_llm_calls_estimate"])
        self.assertEqual(
            len(result.cohorts) * 5 + result.total_individual_days * 198,
            cost["group_llm_calls"],
        )
        self.assertGreater(cost["savings_factor"], 1.0)

    def test_env_context_reaches_the_cohort_prompt(self):
        captured = []

        def spy(prompt, task=None, agent_id=None):
            captured.append(prompt)
            return json.dumps({"brief": "x"}, ensure_ascii=False)

        run_group_simulation(
            _agents(100, seed=5),
            GroupRunConfig(days=1, seed=1),
            llm_fn=spy,
            env_context_for_day=lambda day: "台风橙色预警",
        )
        self.assertTrue(all("台风橙色预警" in p for p in captured))

    def test_render_day_block_is_non_empty_and_bounded(self):
        agents = _agents(100, seed=5)
        result = run_group_simulation(agents, GroupRunConfig(days=1, seed=1), llm_fn=_mock_llm())
        block = render_day_block(result, 1)
        self.assertIn("Day 1", block)
        self.assertEqual("", render_day_block(result, 99))

    def test_cohort_memory_stays_bounded(self):
        agents = _agents(100, seed=5)
        result = run_group_simulation(agents, GroupRunConfig(days=25, seed=1), llm_fn=_mock_llm())
        for cohort in result.cohorts:
            self.assertLessEqual(len(cohort.memory), 10)


class PluginTests(unittest.TestCase):
    def _ctx(self, agents, config):
        recorded = []

        class Bus:
            def __init__(self):
                self.handlers = {}

            def on(self, event, handler, **_kw):
                self.handlers.setdefault(event, []).append(handler)

        class Recorder:
            def record(self, kind, payload):
                recorded.append((kind, payload))

        class Ctx:
            def __init__(self):
                self.bus = Bus()
                self.recorder = Recorder()
                self.config = config
                self.agents = agents
                self._state = {}

            def plugin_state(self, plugin_id):
                return self._state.setdefault(plugin_id, {})

        return Ctx(), recorded

    def test_disabled_by_default_records_nothing(self):
        from gaworld.group.plugin import GroupPlugin

        ctx, recorded = self._ctx(_agents(60, seed=5), {})
        plugin = GroupPlugin()
        plugin.setup(ctx)
        for handler in ctx.bus.handlers["on_simulation_start"]:
            handler(ctx=ctx)
        for handler in ctx.bus.handlers["on_day_end"]:
            handler(ctx=ctx)
        self.assertEqual([], recorded)

    def test_enabled_records_partition_and_daily_stats(self):
        from gaworld.group.plugin import GroupPlugin

        ctx, recorded = self._ctx(_agents(60, seed=5), {"group": {"enabled": True}})
        plugin = GroupPlugin()
        plugin.setup(ctx)
        for handler in ctx.bus.handlers["on_simulation_start"]:
            handler(ctx=ctx)
        for handler in ctx.bus.handlers["on_day_end"]:
            handler(ctx=ctx)
        kinds = [kind for kind, _ in recorded]
        self.assertIn("group.partition", kinds)
        self.assertIn("group.cohort_stats", kinds)

    def test_plugin_does_not_mutate_agent_state(self):
        from gaworld.group.plugin import GroupPlugin

        agents = _agents(60, seed=5)
        before = [dict(a["state"]) for a in agents]
        ctx, _ = self._ctx(agents, {"group": {"enabled": True}})
        plugin = GroupPlugin()
        plugin.setup(ctx)
        for handler in ctx.bus.handlers["on_simulation_start"]:
            handler(ctx=ctx)
        for handler in ctx.bus.handlers["on_day_end"]:
            handler(ctx=ctx)
        self.assertEqual(before, [dict(a["state"]) for a in agents])


class CliTests(unittest.TestCase):
    def test_no_llm_run_succeeds(self):
        from gaworld.group.__main__ import main

        self.assertEqual(0, main(["--size", "120", "--days", "2", "--no-llm"]))

    def test_focal_ids_are_parsed(self):
        from gaworld.group.__main__ import main

        self.assertEqual(0, main(["--size", "120", "--days", "1", "--no-llm", "--focal", "3,9"]))

    def test_network_coupling_flag_runs(self):
        from gaworld.group.__main__ import main

        self.assertEqual(0, main(["--size", "120", "--days", "2", "--no-llm", "--network-coupling", "0.7"]))

    def test_network_coupling_rejected_with_a_state_csv(self):
        """A state CSV has no edges, so the coupling cannot be applied.

        Running anyway would look configured while doing nothing — the same
        silent-no-op failure the driver's own ValueError guards against.
        """
        import tempfile

        from gaworld.group.__main__ import main
        from gaworld.population.generate import generate_population

        with tempfile.TemporaryDirectory() as directory:
            written = generate_population(normalize_spec({"size": 60, "seed": 4, "name": "t"})).write(
                directory
            )
            code = main(
                [
                    "--population",
                    str(written["state_csv"]),
                    "--days",
                    "1",
                    "--no-llm",
                    "--network-coupling",
                    "0.7",
                ]
            )
            self.assertEqual(1, code)

    def test_population_csv_round_trip(self):
        import tempfile

        from gaworld.group.__main__ import main
        from gaworld.population.generate import generate_population

        with tempfile.TemporaryDirectory() as directory:
            result = generate_population(normalize_spec({"size": 120, "seed": 4, "name": "t"}))
            written = result.write(directory)
            # The state CSV has no industry column, so the CLI must fall back
            # to axes the data supports rather than raising.
            code = main(["--population", str(written["state_csv"]), "--days", "1", "--no-llm"])
            self.assertEqual(0, code)


if __name__ == "__main__":
    unittest.main()
