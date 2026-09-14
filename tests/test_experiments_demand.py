"""Tests for the demand-estimation prompt experiment.

The load-bearing properties are the experimental-design ones: that the
pre-treatment covariates cannot move with the treatment, and that the
elicitation question never contains its own answer.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gaworld.experiments import runner
from gaworld.experiments.analysis import (
    confounding,
    demand_curve,
    focalism,
    load_results,
    ols_slope,
    parse_elicit,
    parse_purchase,
    render_markdown,
    shape,
    summarize,
)
from gaworld.experiments.arms import ARMS, _budget_phrase, build_prompt
from gaworld.experiments.runner import RunSpec, build_cells
from gaworld.experiments.stimulus import (
    RELATIVE_PRICE_GRID,
    Product,
    Treatment,
    load_catalog,
    price_grid,
)
from gaworld.experiments.subjects import Subject, load_subjects, world_context

_PRODUCT = Product(
    id=1,
    group="饮料",
    category="碳酸饮料",
    name="可口可乐",
    spec="330ml×12罐",
    regular_price=35.90,
    competitor="百事可乐 330ml×12罐",
    competitor_price=33.90,
    shelf_life_days=270,
)

_SUBJECT = Subject(
    id=1,
    name="李泽宇",
    gender="男",
    age=24,
    residence="余杭·未来科技城",
    job="互联网公司后端工程师",
    personality="偏内向，压力大时会独处",
    daily_life="工作日晚上常点外卖，周末补觉",
    state={"econ_security": 0.5},
    monthly_income=18000.0,
)


class TestStimulus(unittest.TestCase):
    def test_grid_has_eleven_levels_from_zero_to_two(self):
        self.assertEqual(11, len(RELATIVE_PRICE_GRID))
        self.assertEqual(0.0, RELATIVE_PRICE_GRID[0])
        self.assertEqual(2.0, RELATIVE_PRICE_GRID[-1])

    def test_regular_price_is_the_hundred_percent_point(self):
        treatment = Treatment(_PRODUCT, 1.0)
        self.assertEqual(_PRODUCT.regular_price, treatment.price)
        self.assertEqual("p1@100", treatment.id)

    def test_catalog_loads_and_filters_by_group(self):
        products = load_catalog()
        self.assertEqual(40, len(products))
        self.assertEqual(4, len({item.group for item in products}))
        drinks = load_catalog(groups=["饮料"])
        self.assertTrue(all(item.group == "饮料" for item in drinks))

    def test_price_grid_crosses_products_with_levels(self):
        products = load_catalog(limit=3)
        self.assertEqual(3 * 11, len(price_grid(products)))


class TestWorldContextIsPreTreatment(unittest.TestCase):
    """The core identification property of the agent arms."""

    def test_context_is_deterministic_for_a_subject_product_pair(self):
        first = world_context(_SUBJECT, _PRODUCT, seed=42)
        second = world_context(_SUBJECT, _PRODUCT, seed=42)
        self.assertEqual(first, second)

    def test_context_does_not_depend_on_the_treatment_price(self):
        # The signature has no price argument at all, which is the point:
        # there is no code path by which the treatment could reach it.
        contexts = {
            world_context(_SUBJECT, _PRODUCT, seed=42) for _ in RELATIVE_PRICE_GRID
        }
        self.assertEqual(1, len(contexts))

    def test_context_varies_across_products_and_seeds(self):
        other = Product(**{**vars(_PRODUCT), "id": 2})
        self.assertNotEqual(
            world_context(_SUBJECT, _PRODUCT, seed=42),
            world_context(_SUBJECT, other, seed=42),
        )
        self.assertNotEqual(
            world_context(_SUBJECT, _PRODUCT, seed=42),
            world_context(_SUBJECT, _PRODUCT, seed=7),
        )


class TestPrompts(unittest.TestCase):
    def test_blind_arm_has_no_persona_and_no_covariates(self):
        prompt = build_prompt("blind", "purchase", Treatment(_PRODUCT, 1.0))
        self.assertIn("你，AI，是一位顾客", prompt.system)
        self.assertNotIn("李泽宇", prompt.user)
        self.assertNotIn("百事可乐", prompt.user)

    def test_unblinded_system_prompt_states_the_randomization_support(self):
        prompt = build_prompt(
            "unblinded", "purchase", Treatment(_PRODUCT, 1.0), grid=RELATIVE_PRICE_GRID
        )
        self.assertIn("均匀随机抽取", prompt.system)
        self.assertIn("0.00", prompt.system)
        self.assertIn("71.80", prompt.system)  # 2 × 35.90

    def test_agent_arm_carries_persona_and_lived_covariates(self):
        context = world_context(_SUBJECT, _PRODUCT, seed=42)
        prompt = build_prompt(
            "agent", "purchase", Treatment(_PRODUCT, 1.0), subject=_SUBJECT, context=context
        )
        self.assertIn("李泽宇", prompt.user)
        self.assertIn(f"{context.last_paid:.2f}", prompt.user)
        # The budget arrives qualitatively, never as a number to compute with.
        self.assertNotIn(f"{context.monthly_food_budget:.2f}", prompt.user)

    def test_budget_signal_actually_varies(self):
        # A background signal that reads the same for everyone is not a
        # covariate, it is a constant — and it silently stops doing the
        # work the grounded arms exist to do.
        products = load_catalog(limit=8)
        subjects = load_subjects(limit=8, seed=42)
        phrases = {
            _budget_phrase(world_context(subject, product, seed=42))
            for subject in subjects
            for product in products
        }
        self.assertGreaterEqual(len(phrases), 3)

    def test_budget_phrase_carries_no_number(self):
        # A number here invites arithmetic against the treatment price,
        # which is the focalism failure the grounded arms avoid.
        for ratio in (0.15, 0.5, 0.85):
            context = world_context(_SUBJECT, _PRODUCT, seed=42)
            context = type(context)(**{**vars(context), "budget_left_ratio": ratio})
            self.assertFalse(any(char.isdigit() for char in _budget_phrase(context)))

    def test_covariate_arm_states_covariates_as_explicit_facts(self):
        context = world_context(_SUBJECT, _PRODUCT, seed=42)
        prompt = build_prompt(
            "covariate", "purchase", Treatment(_PRODUCT, 1.0), subject=_SUBJECT, context=context
        )
        self.assertIn("你的基本情况", prompt.user)
        self.assertIn("月收入", prompt.user)

    def test_elicitation_prompt_never_contains_its_own_answer(self):
        context = world_context(_SUBJECT, _PRODUCT, seed=42)
        for arm_id in ARMS:
            with self.subTest(arm=arm_id):
                prompt = build_prompt(
                    arm_id,
                    "elicit",
                    Treatment(_PRODUCT, 1.6),
                    subject=_SUBJECT,
                    context=context,
                )
                self.assertNotIn(f"{context.last_paid:.2f}", prompt.user)
                self.assertNotIn(f"{context.competitor_price:.2f}", prompt.user)
                self.assertNotIn(str(context.shelf_life_days), prompt.user)

    def test_elicit_fields_can_be_narrowed_to_the_papers_prompt_1(self):
        prompt = build_prompt(
            "blind", "elicit", Treatment(_PRODUCT, 1.0), elicit_fields=("last_price",)
        )
        self.assertIn("你上一次购买这个商品时", prompt.user)
        self.assertNotIn("保质期", prompt.user)

    def test_unknown_arm_and_question_are_rejected(self):
        with self.assertRaises(ValueError):
            build_prompt("nope", "purchase", Treatment(_PRODUCT, 1.0))
        with self.assertRaises(ValueError):
            build_prompt("blind", "nope", Treatment(_PRODUCT, 1.0))

    def test_grounded_arm_requires_a_subject(self):
        with self.assertRaises(ValueError):
            build_prompt("agent", "purchase", Treatment(_PRODUCT, 1.0))


class TestParsing(unittest.TestCase):
    def test_negative_is_checked_before_positive(self):
        # "不购买" contains "购买"; a naive parser flips every refusal to a sale.
        self.assertIs(False, parse_purchase("不购买"))
        self.assertIs(True, parse_purchase("购买"))
        self.assertIs(False, parse_purchase("我不会买"))
        self.assertIsNone(parse_purchase(""))
        self.assertIsNone(parse_purchase("这取决于很多因素"))

    def test_elicit_reads_a_csv_answer(self):
        parsed = parse_elicit("32.50,31.00,180", ("last_price", "competitor_price", "shelf_life_days"))
        self.assertEqual({"last_price": 32.5, "competitor_price": 31.0, "shelf_life_days": 180.0}, parsed)

    def test_elicit_returns_none_when_numbers_are_missing(self):
        self.assertIsNone(parse_elicit("大概三十多块", ("last_price",)))
        self.assertIsNone(parse_elicit("32.50", ("last_price", "competitor_price")))


class TestEstimands(unittest.TestCase):
    def _purchase_rows(self, probabilities: dict[float, float], products=(1, 2)):
        rows = []
        for product_id in products:
            for relative_price, probability in probabilities.items():
                buys = int(round(probability * 10))
                for draw in range(10):
                    rows.append(
                        {
                            "arm": "test",
                            "question": "purchase",
                            "product_id": product_id,
                            "relative_price": relative_price,
                            "purchase": draw < buys,
                        }
                    )
        return rows

    def test_demand_curve_recovers_the_generating_probabilities(self):
        curve = demand_curve(self._purchase_rows({0.5: 0.9, 1.0: 0.6, 1.5: 0.2}))
        self.assertEqual([0.5, 1.0, 1.5], [price for price, _, _ in curve])
        self.assertAlmostEqual(0.9, curve[0][1])
        self.assertAlmostEqual(0.2, curve[2][1])

    def test_shape_flags_a_downward_curve_and_an_inverted_u(self):
        downward = demand_curve(self._purchase_rows({0.2: 0.9, 1.0: 0.6, 1.8: 0.2}))
        self.assertEqual(1.0, shape(downward)["monotone_share"])
        self.assertFalse(shape(downward)["inverted_u"])

        inverted = demand_curve(self._purchase_rows({0.2: 0.3, 1.0: 0.9, 1.8: 0.2}))
        self.assertTrue(shape(inverted)["inverted_u"])
        self.assertEqual(1.0, shape(inverted)["peak_relative_price"])

    def test_confounding_slope_is_zero_when_the_covariate_is_fixed(self):
        rows = [
            {
                "arm": "test",
                "question": "elicit",
                "product_id": 1,
                "relative_price": level,
                "elicited": {"last_price": 30.0},
            }
            for level in (0.5, 1.0, 1.5)
        ]
        self.assertAlmostEqual(0.0, confounding(rows, "last_price")["slope"])

    def test_confounding_slope_is_positive_when_the_covariate_tracks_price(self):
        rows = [
            {
                "arm": "test",
                "question": "elicit",
                "product_id": 1,
                "relative_price": level,
                "elicited": {"last_price": 20.0 + 10.0 * level},
            }
            for level in (0.5, 1.0, 1.5)
        ]
        self.assertGreater(confounding(rows, "last_price")["slope"], 0.2)

    def _decisions(self, rule, competitor_price=30.0, products=(1, 2)):
        rows = []
        for product_id in products:
            for level in (0.2, 0.6, 1.0, 1.4, 1.8):
                price = 30.0 * level
                for draw in range(10):
                    rows.append(
                        {
                            "arm": "test",
                            "question": "purchase",
                            "product_id": product_id,
                            "relative_price": level,
                            "price": price,
                            "purchase": rule(price, draw),
                            "world": {"competitor_price": competitor_price},
                        }
                    )
        return rows

    def test_focalism_flags_a_step_function(self):
        # Exactly the degenerate rule: buy iff price <= competitor price.
        rows = self._decisions(lambda price, _: price <= 30.0)
        result = focalism(rows)
        self.assertEqual(1.0, result["step_rule_agreement"])
        # Saturated at 1.0, collapsed at the very next grid point: the
        # narrowest transition the grid can express (one step = 0.4 here).
        self.assertEqual(0.4, result["transition_width"])

    def test_a_low_price_refusal_does_not_widen_the_transition(self):
        # An occasional "no" at a near-free price is not part of the ramp.
        # Measuring the span of all interior points would let it double
        # the reported width of exactly the arm under scrutiny.
        def _rule(price, draw):
            if price <= 6.0:  # the 0.2 level: one refusal in ten
                return draw > 0
            return price <= 30.0

        result = focalism(self._decisions(_rule))
        self.assertEqual(0.4, result["transition_width"])

    def test_focalism_sees_a_ramp_when_consumers_are_heterogeneous(self):
        # Probability falls smoothly with price instead of switching.
        def _rule(price, draw):
            probability = max(0.0, min(1.0, 1.2 - price / 45.0))
            return draw < round(probability * 10)

        result = focalism(self._decisions(_rule))
        self.assertGreater(result["transition_width"], 0.5)
        self.assertLess(result["step_rule_agreement"], 1.0)

    def test_focalism_is_undefined_without_a_competitor_price(self):
        rows = self._decisions(lambda price, _: True)
        for row in rows:
            row.pop("world")
        self.assertIsNone(focalism(rows))

    def test_ols_slope_handles_degenerate_input(self):
        self.assertIsNone(ols_slope([(1.0, 2.0)]))
        self.assertIsNone(ols_slope([(1.0, 2.0), (1.0, 3.0)]))


class TestSubjectsAndGrid(unittest.TestCase):
    def test_subjects_load_from_the_simulator_corpus(self):
        subjects = load_subjects(limit=3, seed=42)
        self.assertEqual(3, len(subjects))
        for subject in subjects:
            self.assertTrue(subject.name)
            self.assertGreater(subject.age, 0)
            self.assertGreater(subject.monthly_income, 0)

    def test_income_is_stable_across_loads(self):
        first = load_subjects(limit=3, seed=42)
        second = load_subjects(limit=3, seed=42)
        self.assertEqual(
            [item.monthly_income for item in first], [item.monthly_income for item in second]
        )

    def test_stateless_arms_have_no_subject_dimension(self):
        spec = RunSpec(
            arms=["blind", "agent"],
            questions=["purchase"],
            product_limit=2,
            subject_limit=3,
            draws=2,
            subject_draws=1,
        )
        cells = build_cells(spec)
        blind = [cell for cell in cells if cell.arm == "blind"]
        agent = [cell for cell in cells if cell.arm == "agent"]
        # blind: 2 products × 11 prices × 1 (no subject) × 2 draws
        self.assertEqual(2 * 11 * 1 * 2, len(blind))
        # agent: same grid × 3 subjects, whose heterogeneity replaces draws
        self.assertEqual(2 * 11 * 3 * 1, len(agent))
        self.assertTrue(all(cell.subject is None for cell in blind))
        self.assertEqual(len(cells), len({cell.key for cell in cells}))

    def test_draws_and_subject_draws_are_independent(self):
        # Guards the cost blow-up: without the split, an arm with subjects
        # would cost subjects × draws for variation it already has.
        spec = RunSpec(
            arms=["blind", "covariate", "agent"],
            questions=["purchase"],
            product_limit=1,
            subject_limit=4,
            draws=10,
            subject_draws=2,
        )
        counts = {}
        for cell in build_cells(spec):
            counts[cell.arm] = counts.get(cell.arm, 0) + 1
        self.assertEqual(11 * 10, counts["blind"])
        self.assertEqual(11 * 4 * 2, counts["covariate"])
        self.assertEqual(11 * 4 * 2, counts["agent"])

    def test_spec_rejects_unknown_arms(self):
        with self.assertRaises(ValueError):
            build_cells(RunSpec(arms=["nope"]))


class TestRunnerEndToEnd(unittest.TestCase):
    """The sweep, the log and the report, with the model stubbed out."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.calls = []

        def _fake_call(prompt, task=None, provider=None, system=None, temperature=None, **_):
            self.calls.append({"prompt": prompt, "system": system, "temperature": temperature})
            return "不购买" if "你会不会购买" in prompt else "30.00,29.00,200"

        patcher = mock.patch.object(runner, "call_llm", _fake_call)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _spec(self, **overrides):
        base = dict(
            arms=["blind", "agent"],
            questions=["elicit", "purchase"],
            product_limit=1,
            subject_limit=2,
            grid=(0.5, 1.0),
            draws=1,
            name="unittest",
            output_dir=self._tmp.name,
        )
        base.update(overrides)
        return RunSpec(**base)

    def test_dry_run_writes_no_results(self):
        path = runner.run(self._spec(), dry_run=True)
        self.assertFalse(path.exists())
        self.assertEqual([], self.calls)

    def test_run_logs_one_row_per_cell_and_parses_answers(self):
        spec = self._spec()
        path = runner.run(spec)
        rows = load_results(path)
        self.assertEqual(len(build_cells(spec)), len(rows))
        purchases = [row for row in rows if row["question"] == "purchase"]
        self.assertTrue(all(row["purchase"] is False for row in purchases))
        elicits = [row for row in rows if row["question"] == "elicit"]
        self.assertTrue(all(row["elicited"]["last_price"] == 30.0 for row in elicits))
        # Grounded rows carry the world's own values so fidelity is computable.
        self.assertTrue(all("world" in row for row in rows if row["arm"] == "agent"))
        self.assertTrue(all("world" not in row for row in rows if row["arm"] == "blind"))

    def test_temperature_and_system_prompt_reach_the_model(self):
        runner.run(self._spec(temperature=1.0))
        self.assertTrue(all(call["temperature"] == 1.0 for call in self.calls))
        self.assertTrue(all(call["system"] for call in self.calls))

    def test_resume_skips_completed_cells(self):
        spec = self._spec()
        runner.run(spec)
        first_pass = len(self.calls)
        self.calls.clear()
        runner.run(spec)
        self.assertEqual(0, len(self.calls))
        # And the log did not grow a second copy of every row.
        self.assertEqual(first_pass, len(load_results(Path(self._tmp.name) / "unittest" / "results.jsonl")))

    def test_a_dead_backend_aborts_instead_of_burning_the_grid(self):
        # An exhausted quota fails every cell identically. Without the
        # circuit breaker the sweep runs to completion and leaves a file
        # of errors that looks like a finished run.
        spec = self._spec(arms=["blind"], questions=["purchase"], product_limit=8)
        total = len(build_cells(spec))
        with mock.patch.object(runner, "call_llm", side_effect=RuntimeError("HTTP 429")):
            with self.assertRaises(RuntimeError) as ctx:
                runner.run(spec, abort_after=5)
        self.assertIn("中止", str(ctx.exception))
        rows = load_results(Path(self._tmp.name) / "unittest" / "results.jsonl")
        self.assertLess(len(rows), total)

    def test_partial_failure_does_not_trip_the_breaker(self):
        calls = {"n": 0}

        def _flaky(prompt, **_):
            calls["n"] += 1
            if calls["n"] % 2:
                raise RuntimeError("transient")
            return "购买"

        spec = self._spec(arms=["blind"], questions=["purchase"], product_limit=2)
        with mock.patch.object(runner, "call_llm", _flaky):
            path = runner.run(spec, abort_after=5)
        rows = load_results(path)
        self.assertEqual(len(build_cells(spec)), len(rows))
        self.assertTrue(any("error" not in row for row in rows))

    def test_failed_cells_are_logged_and_retried_on_resume(self):
        spec = self._spec(arms=["blind"], questions=["purchase"])
        with mock.patch.object(runner, "call_llm", side_effect=RuntimeError("boom")):
            path = runner.run(spec)
        rows = load_results(path)
        self.assertTrue(all("error" in row for row in rows))
        runner.run(spec)  # the stub from setUp answers this time
        self.assertEqual(len(build_cells(spec)), len(self.calls))

    def test_a_second_run_on_the_same_output_dir_is_refused(self):
        # Two processes appending to one log duplicate cells and silently
        # double-weight whichever arm was in flight — this actually
        # happened, and cost a run's worth of trustworthy numbers.
        spec = self._spec(arms=["blind"], questions=["purchase"], product_limit=1)
        lock = Path(self._tmp.name) / "unittest" / "run.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("99999\n")
        with self.assertRaises(RuntimeError) as ctx:
            runner.run(spec)
        self.assertIn("run.lock", str(ctx.exception))

    def test_the_lock_is_released_after_a_run(self):
        spec = self._spec(arms=["blind"], questions=["purchase"], product_limit=1)
        runner.run(spec)
        self.assertFalse((Path(self._tmp.name) / "unittest" / "run.lock").exists())
        runner.run(spec)  # a second, sequential run is fine

    def test_duplicate_cells_are_dropped_when_loading(self):
        path = Path(self._tmp.name) / "dupes.jsonl"
        rows = [
            {"key": "a", "arm": "x", "question": "purchase", "purchase": True},
            {"key": "a", "arm": "x", "question": "purchase", "purchase": False},
            {"key": "b", "arm": "x", "question": "purchase", "purchase": True},
        ]
        path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
        self.assertEqual(2, len(load_results(path)))
        self.assertEqual(3, len(load_results(path, dedupe=False)))

    def test_summary_and_report_render(self):
        path = runner.run(self._spec())
        summary = summarize(load_results(path), elicit_fields=("last_price",))
        self.assertEqual({"blind", "agent"}, set(summary["arms"]))
        self.assertEqual(0.0, summary["arms"]["blind"]["parse_failure_rate"]["purchase"])
        report = render_markdown(summary)
        self.assertIn("需求曲线", report)
        self.assertIn("混淆诊断", report)


if __name__ == "__main__":
    unittest.main()
