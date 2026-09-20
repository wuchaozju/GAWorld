"""Phase 1: synthetic-population generation.

The tests are organised around the two promises the module makes to the panel:

* **reproducibility** — the same spec and seed produce byte-identical output,
  and changing one knob does not silently re-roll unrelated attributes;
* **honesty** — requested marginals are actually achieved, and where they
  cannot be, the gap is reported rather than hidden.

No LLM calls are involved anywhere in this package, so nothing needs mocking.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.population.generate import generate_population
from gaworld.population.network import (
    build_households,
    build_social_graph,
    build_workplaces,
    graph_metrics,
)
from gaworld.population.report import (
    gini,
    has_errors,
    validate_population,
    worst_gaps,
)
from gaworld.population.schema import (
    CSV_COLUMNS,
    INDUSTRIES,
    PRESETS,
    STATE_VAR_KEYS,
    TERTIARY_LEVELS,
    check_feasibility,
    household_size_bounds,
    median_age_bounds,
    normalize_spec,
)
from gaworld.population.synth import (
    income_quantile,
    integerise,
    solve_income_sigma,
    synthesize_people,
)
from gaworld.population.writer import render_profiles_markdown, render_state_csv

CHILD_MAX_AGE = 17
ELDER_MIN_AGE = 65


def _generate(**overrides):
    spec = normalize_spec({"size": 300, "seed": 11, **overrides})
    return generate_population(spec)


class SchemaTests(unittest.TestCase):
    def test_defaults_are_self_consistent(self):
        spec = normalize_spec({})
        self.assertEqual(500, spec.size)
        self.assertEqual("cn_county_town", spec.preset)
        self.assertAlmostEqual(1.0, sum(spec.education_work.industry_mix.values()), places=6)
        self.assertAlmostEqual(1.0, sum(spec.geography.district_weights.values()), places=6)

    def test_every_shipped_preset_is_feasible(self):
        # A preset that trips its own feasibility check would teach users to
        # ignore the warnings.
        for name in PRESETS:
            spec = normalize_spec({"preset": name, "size": 500})
            issues = check_feasibility(spec)
            self.assertEqual([], issues, f"preset {name} produced {[(i.level, i.code) for i in issues]}")

    def test_out_of_range_values_are_clamped_not_rejected(self):
        spec = normalize_spec({"size": 99999, "demography": {"median_age": 900, "share_over_65": -3}})
        self.assertEqual(5000, spec.size)
        self.assertLessEqual(spec.demography.median_age, 65.0)
        self.assertGreaterEqual(spec.demography.share_over_65, 0.0)

    def test_unknown_keys_are_ignored(self):
        spec = normalize_spec({"size": 100, "nonexistent_knob": 5, "demography": {"bogus": 1}})
        self.assertEqual(100, spec.size)

    def test_industry_mix_is_renormalised(self):
        spec = normalize_spec({"education_work": {"industry_mix": {"tech": 3, "service": 1}}})
        self.assertAlmostEqual(1.0, sum(spec.education_work.industry_mix.values()), places=6)
        self.assertAlmostEqual(0.75, spec.education_work.industry_mix["tech"], places=6)


class FeasibilityTests(unittest.TestCase):
    def test_household_bounds_are_two_sided(self):
        # The easy mistake is checking only the lower bound. With 60% one-person
        # households, mean size must sit in [1.4, 3.0] — both 1.2 and 3.2 are
        # infeasible.
        spec = normalize_spec({"household": {"share_single_person": 0.6, "max_size": 6}})
        low, high = household_size_bounds(spec)
        self.assertAlmostEqual(1.4, low, places=6)
        self.assertAlmostEqual(3.0, high, places=6)

        too_small = normalize_spec({"household": {"share_single_person": 0.6, "mean_size": 1.2}})
        codes = {i.code for i in check_feasibility(too_small)}
        self.assertIn("household_mean_too_small", codes)

        too_large = normalize_spec({"household": {"share_single_person": 0.6, "mean_size": 3.2}})
        codes = {i.code for i in check_feasibility(too_large)}
        self.assertIn("household_mean_too_large", codes)

        feasible = normalize_spec({"household": {"share_single_person": 0.6, "mean_size": 2.5}})
        codes = {i.code for i in check_feasibility(feasible)}
        self.assertNotIn("household_mean_too_small", codes)
        self.assertNotIn("household_mean_too_large", codes)

    def test_unreachable_median_age_is_flagged(self):
        spec = normalize_spec(
            {"demography": {"share_under_18": 0.10, "share_over_65": 0.07, "median_age": 20}}
        )
        low, _high = median_age_bounds(spec)
        self.assertGreater(low, 20)
        codes = {i.code for i in check_feasibility(spec)}
        self.assertIn("median_age_unreachable", codes)

    def test_labour_force_over_one_is_an_error(self):
        spec = normalize_spec({"education_work": {"employment_rate": 0.9, "unemployment_rate": 0.3}})
        errors = [i for i in check_feasibility(spec) if i.level == "error"]
        self.assertIn("labor_force_over_one", {i.code for i in errors})

    def test_multigen_beyond_elder_supply_is_flagged(self):
        spec = normalize_spec(
            {
                "size": 500,
                "demography": {"share_over_65": 0.03},
                "household": {"share_multigen": 0.40, "mean_size": 2.5},
            }
        )
        codes = {i.code for i in check_feasibility(spec)}
        self.assertIn("multigen_needs_more_elders", codes)

    def test_issues_carry_an_actionable_knob_and_suggestion(self):
        spec = normalize_spec({"household": {"share_single_person": 0.6, "mean_size": 3.2}})
        issue = next(i for i in check_feasibility(spec) if i.code == "household_mean_too_large")
        self.assertTrue(issue.knob.startswith("household."))
        self.assertTrue(issue.suggestion)


class NumericHelperTests(unittest.TestCase):
    def test_integerise_hits_exact_counts(self):
        import numpy as np

        rng = np.random.default_rng(0)
        probabilities = np.array([0.5, 0.3, 0.2])
        picks = integerise(probabilities, 1000, rng)
        counts = Counter(picks.tolist())
        self.assertEqual(1000, len(picks))
        # Largest-remainder allocation, so no sampling error at all.
        self.assertEqual(500, counts[0])
        self.assertEqual(300, counts[1])
        self.assertEqual(200, counts[2])

    def test_income_quantile_is_monotone_and_heavy_tailed(self):
        values = [income_quantile(u / 100, 6500, 0.75, 2.2, 0.95) for u in range(1, 100)]
        self.assertEqual(values, sorted(values))
        # The Pareto splice must lift the top far above the lognormal body.
        self.assertGreater(values[-1] / statistics.median(values), 4.0)

    def test_solve_income_sigma_matches_requested_gini(self):
        for target in (0.25, 0.42, 0.58):
            spec = normalize_spec({"income": {"gini": target}})
            sigma = solve_income_sigma(spec)
            realised = gini(
                [
                    income_quantile((k + 0.5) / 2000, spec.income.median_monthly, sigma, 2.2, 0.95)
                    for k in range(2000)
                ]
            )
            self.assertAlmostEqual(target, realised, delta=0.01)


class MarginalAccuracyTests(unittest.TestCase):
    """The panel promises these numbers; the data has to deliver them."""

    @classmethod
    def setUpClass(cls):
        cls.result = _generate(size=600, seed=3)

    def test_age_shares_match_request(self):
        spec, people = self.result.spec, self.result.people
        ages = [p.age for p in people]
        self.assertAlmostEqual(
            spec.demography.share_under_18,
            sum(a <= CHILD_MAX_AGE for a in ages) / len(ages),
            delta=0.03,
        )
        self.assertAlmostEqual(
            spec.demography.share_over_65,
            sum(a >= ELDER_MIN_AGE for a in ages) / len(ages),
            delta=0.03,
        )

    def test_employment_rate_is_over_working_age_population(self):
        spec, people = self.result.spec, self.result.people
        working = [p for p in people if CHILD_MAX_AGE < p.age < ELDER_MIN_AGE]
        employed = sum(1 for p in working if p.employment == "employed")
        self.assertAlmostEqual(spec.education_work.employment_rate, employed / len(working), delta=0.05)

    def test_tertiary_rate_matches_over_adults(self):
        spec, people = self.result.spec, self.result.people
        adults = [p for p in people if p.age > CHILD_MAX_AGE]
        tertiary = sum(1 for p in adults if p.education in TERTIARY_LEVELS)
        self.assertAlmostEqual(spec.education_work.tertiary_rate, tertiary / len(adults), delta=0.05)

    def test_income_median_and_gini_match_request(self):
        spec, people = self.result.spec, self.result.people
        incomes = [p.income_monthly for p in people if p.employment == "employed"]
        self.assertAlmostEqual(spec.income.median_monthly, statistics.median(incomes), delta=200)
        self.assertAlmostEqual(spec.income.gini, gini(incomes), delta=0.03)

    def test_household_mean_size_and_single_share_match_request(self):
        spec = self.result.spec
        households = self.result.households
        mean_size = len(self.result.people) / len(households)
        self.assertAlmostEqual(spec.household.mean_size, mean_size, delta=0.15)
        single_share = sum(1 for h in households if h.type == "single") / len(households)
        self.assertAlmostEqual(spec.household.share_single_person, single_share, delta=0.05)

    def test_industry_mix_matches_request(self):
        spec = self.result.spec
        employed = [p for p in self.result.people if p.employment == "employed"]
        counts = Counter(p.industry for p in employed)
        for name in INDUSTRIES:
            self.assertAlmostEqual(
                spec.education_work.industry_mix[name],
                counts[name] / len(employed),
                delta=0.06,
                msg=f"industry {name}",
            )

    def test_ipf_converges(self):
        fit = self.result.report["fit"]["ipf"]
        self.assertTrue(fit["converged"], fit)

    def test_report_exposes_target_and_achieved_for_every_knob(self):
        for name, entry in self.result.report["achieved"].items():
            self.assertIn("target", entry, name)
            self.assertIn("achieved", entry, name)
            self.assertIn("delta", entry, name)

    def test_worst_gaps_ranks_by_relative_error(self):
        gaps = worst_gaps(self.result.report, limit=3)
        self.assertLessEqual(len(gaps), 3)
        errors = [g["relative_error"] for g in gaps]
        self.assertEqual(sorted(errors, reverse=True), errors)


class ReproducibilityTests(unittest.TestCase):
    def test_same_spec_and_seed_is_byte_identical(self):
        first = _generate()
        second = _generate()
        self.assertEqual(render_state_csv(first.people), render_state_csv(second.people))
        self.assertEqual(
            render_profiles_markdown(first.spec, first.people, first.households),
            render_profiles_markdown(second.spec, second.people, second.households),
        )

    def test_different_seed_changes_the_population(self):
        self.assertNotEqual(
            render_state_csv(_generate(seed=1).people),
            render_state_csv(_generate(seed=2).people),
        )

    def test_network_knobs_do_not_reroll_demographics(self):
        # Sub-streams exist precisely so a user nudging the social-graph
        # sliders does not watch everyone's age change underneath them.
        base = _generate()
        tweaked = _generate(social_network={"mean_degree": 20, "rewire_p": 0.3})
        self.assertEqual(
            [(p.id, p.name, p.age, p.income_monthly) for p in base.people],
            [(p.id, p.name, p.age, p.income_monthly) for p in tweaked.people],
        )
        self.assertNotEqual(
            sum(len(v) for v in base.neighbours.values()),
            sum(len(v) for v in tweaked.neighbours.values()),
        )


class StructuralValidityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = _generate(size=400, seed=5)

    def test_no_errors_for_a_default_spec(self):
        self.assertFalse(
            has_errors(self.result.findings),
            [f.to_dict() for f in self.result.findings if f.level == "error"],
        )

    def test_every_person_is_in_exactly_one_household(self):
        assigned = [pid for h in self.result.households for pid in h.member_ids]
        self.assertEqual(len(self.result.people), len(assigned))
        self.assertEqual(len(self.result.people), len(set(assigned)))

    def test_no_agents_below_the_modelling_floor(self):
        floor = self.result.spec.demography.min_agent_age
        self.assertGreaterEqual(min(p.age for p in self.result.people), floor)

    def test_no_underage_workers(self):
        self.assertEqual([], [p.id for p in self.result.people if p.age < 16 and p.employment == "employed"])

    def test_employed_people_always_have_a_classifiable_industry(self):
        # The economy module keys off industry; "employed with no industry"
        # would silently fall through JOB_INDUSTRY_MAP.
        for person in self.result.people:
            if person.employment == "employed":
                self.assertIn(person.industry, INDUSTRIES, person)

    def test_state_variables_are_complete_and_in_range(self):
        for person in self.result.people:
            for key in STATE_VAR_KEYS:
                self.assertIn(key, person.state)
                self.assertGreaterEqual(person.state[key], 0.0)
                self.assertLessEqual(person.state[key], 1.0)

    def test_residence_stays_parseable_by_the_map_layer(self):
        for person in self.result.people:
            self.assertIn("·", person.residence)

    def test_household_members_share_an_address(self):
        by_id = {p.id: p for p in self.result.people}
        for household in self.result.households:
            addresses = {by_id[i].residence for i in household.member_ids}
            self.assertEqual(1, len(addresses), household)

    def test_validator_catches_an_injected_impossible_person(self):
        result = _generate(size=200, seed=9)
        victim = next(p for p in result.people if p.age > 30)
        victim.age = 8
        victim.employment = "employed"
        victim.industry = "tech"
        findings = validate_population(result.spec, result.people, result.households, result.neighbours)
        self.assertIn("underage_worker", {f.code for f in findings if f.level == "error"})

    def test_validator_catches_an_out_of_range_state(self):
        result = _generate(size=200, seed=9)
        result.people[0].state["stress"] = 1.7
        findings = validate_population(result.spec, result.people, result.households, result.neighbours)
        self.assertIn("state_out_of_range", {f.code for f in findings if f.level == "error"})


class SocialGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = _generate(size=400, seed=5)
        cls.metrics = graph_metrics(cls.result.neighbours)

    def test_mean_degree_matches_request(self):
        self.assertAlmostEqual(
            self.result.spec.social_network.mean_degree, self.metrics["mean_degree"], delta=1.5
        )

    def test_graph_is_connected_and_has_no_isolates(self):
        self.assertEqual(0, self.metrics["isolated"])
        self.assertGreater(self.metrics["largest_component_share"], 0.95)

    def test_graph_is_small_world(self):
        # Small-worldness is relative, not absolute: clustering far above a
        # random graph of the same size and degree, path length close to it.
        # Absolute thresholds would just be a proxy for mean degree.
        self.assertGreater(self.metrics["clustering"], 3 * self.metrics["random_clustering"])
        self.assertLess(self.metrics["mean_path_length"], 2.5 * self.metrics["random_path_length"])
        self.assertGreater(self.metrics["small_world_sigma"], 1.5)

    def test_ties_are_symmetric(self):
        for person_id, peers in self.result.neighbours.items():
            for peer_id in peers:
                self.assertIn(person_id, self.result.neighbours[peer_id])

    def test_relationships_use_the_existing_schema(self):
        person = next(p for p in self.result.people if p.relationships)
        item = next(iter(person.relationships.values()))
        for key in ("closeness", "trust", "obligation", "friction", "role", "kind", "dunbar_tier"):
            self.assertIn(key, item)
        self.assertEqual("agent", item["kind"])

    def test_kin_ties_survive_dunbar_pruning(self):
        by_id = {p.id: p for p in self.result.people}
        for household in self.result.households:
            if len(household.member_ids) < 2:
                continue
            first, second = household.member_ids[0], household.member_ids[1]
            self.assertIn(str(second), by_id[first].relationships, household)

    def test_dunbar_cap_is_enforced(self):
        cap = self.result.spec.social_network.dunbar_weak_cap
        for person in self.result.people:
            self.assertLessEqual(len(person.relationships), cap)

    def test_homophily_strength_changes_assortativity(self):
        import numpy as np

        def age_correlation(result):
            by_id = {p.id: p for p in result.people}
            pairs = [
                (by_id[a].age, by_id[b].age) for a, peers in result.neighbours.items() for b in peers if a < b
            ]
            xs, ys = zip(*pairs, strict=True)
            return float(np.corrcoef(xs, ys)[0, 1])

        strong = _generate(size=400, seed=5, social_network={"homophily_strength": 0.95})
        weak = _generate(size=400, seed=5, social_network={"homophily_strength": 0.0})
        self.assertGreater(age_correlation(strong), age_correlation(weak))


class EconomyContractTests(unittest.TestCase):
    """Generated job text must survive the economy module's keyword matching.

    ``_infer_industry`` and ``_job_income_band`` do plain substring matching in
    a fixed order, so a plausible-sounding title can silently land in the wrong
    industry (e.g. "跨境电商运营" matching ``运营`` under *service* before
    ``电商`` under *trade*). Nothing crashes when that happens — the agent just
    gets the wrong macro conditions and wage — which is exactly why it needs a
    test rather than a runtime check.
    """

    def test_every_job_title_maps_back_to_its_own_industry(self):
        from gaworld.economy.finance import JOB_INDUSTRY_MAP
        from gaworld.population.synth import JOB_TITLES

        def infer(job: str) -> str:
            for industry, keywords in JOB_INDUSTRY_MAP.items():
                if any(keyword in job for keyword in keywords):
                    return industry
            return "default"

        for industry, titles in JOB_TITLES.items():
            for title in titles:
                self.assertEqual(
                    industry,
                    infer(title),
                    f"job title {title!r} is classified as {infer(title)!r}, not {industry!r}",
                )

    def test_generated_people_classify_correctly_including_gig_suffix(self):
        from gaworld.economy.finance import JOB_INDUSTRY_MAP

        def infer(job: str) -> str:
            for industry, keywords in JOB_INDUSTRY_MAP.items():
                if any(keyword in job for keyword in keywords):
                    return industry
            return "default"

        result = _generate(size=500, seed=42)
        for person in result.people:
            if person.employment == "employed":
                self.assertEqual(person.industry, infer(person.job), f"{person.job} → {infer(person.job)}")

    def test_non_employed_jobs_land_in_the_lowest_income_band(self):
        from gaworld.economy.finance import JOB_INCOME_BANDS
        from gaworld.population.synth import NON_EMPLOYED_JOBS

        lowest = JOB_INCOME_BANDS[-1][0]
        for titles in NON_EMPLOYED_JOBS.values():
            for title in titles:
                self.assertTrue(
                    any(keyword in title for keyword in lowest),
                    f"{title!r} does not match the 学生/失业/退休 income band",
                )


class WriterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = _generate(size=200, seed=13, name="unittown")

    def test_csv_columns_match_the_reference_file_exactly(self):
        header = render_state_csv(self.result.people).splitlines()[0]
        self.assertEqual(list(CSV_COLUMNS), header.split(","))

        root = Path(__file__).resolve().parents[1]
        reference = root / "data" / "hangzhou_agents_state_init.csv"
        if reference.exists():
            with open(reference, encoding="utf-8-sig") as fh:
                self.assertEqual(fh.readline().strip().split(","), list(CSV_COLUMNS))

    def test_profiles_are_parseable_by_the_simulator_parser(self):
        import re

        from gaworld.sim.agents_loader import parse_profile

        markdown = render_profiles_markdown(self.result.spec, self.result.people, self.result.households)
        blocks = re.split(r"(?=## Profile )", markdown)[1:]
        self.assertEqual(len(self.result.people), len(blocks))
        for block in blocks:
            parsed = parse_profile(block)
            self.assertTrue(parsed["name"])
            self.assertTrue(parsed["job"])
            self.assertTrue(parsed["living"])
            self.assertIsInstance(parsed["age"], int)

    def test_write_produces_csv_markdown_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            written = self.result.write(directory)
            self.assertEqual({"state_csv", "profiles_md", "manifest"}, set(written))
            for path in written.values():
                self.assertTrue(path.exists())

            # The simulator reads the state CSV with a BOM-aware codec.
            with open(written["state_csv"], "rb") as fh:
                self.assertTrue(fh.read(3) == b"\xef\xbb\xbf")

            manifest = json.loads(written["manifest"].read_text(encoding="utf-8"))
            self.assertEqual("unittown", manifest["spec"]["name"])
            self.assertEqual(13, manifest["spec"]["seed"])
            self.assertEqual(200, manifest["counts"]["people"])
            self.assertIn("report", manifest)


class CliTests(unittest.TestCase):
    def test_check_mode_writes_nothing_and_succeeds(self):
        from gaworld.population.__main__ import main

        with tempfile.TemporaryDirectory() as directory:
            code = main(["--size", "120", "--seed", "2", "--check", "--out", directory])
            self.assertEqual(0, code)
            self.assertEqual([], list(Path(directory).iterdir()))

    def test_generate_mode_writes_files(self):
        from gaworld.population.__main__ import main

        with tempfile.TemporaryDirectory() as directory:
            code = main(["--size", "120", "--seed", "2", "--name", "clitown", "--out", directory])
            self.assertEqual(0, code)
            self.assertTrue((Path(directory) / "clitown_state_init.csv").exists())
            self.assertTrue((Path(directory) / "clitown_profiles.md").exists())

    def test_spec_file_overrides_are_applied(self):
        from gaworld.population.__main__ import main

        with tempfile.TemporaryDirectory() as directory:
            spec_path = Path(directory) / "spec.json"
            spec_path.write_text(
                json.dumps({"size": 150, "seed": 4, "preset": "aging_community"}),
                encoding="utf-8",
            )
            code = main(["--spec", str(spec_path), "--check"])
            self.assertEqual(0, code)


class ScaleTests(unittest.TestCase):
    def test_five_hundred_person_town_generates_cleanly(self):
        """The headline use case from the design doc."""
        result = _generate(size=500, seed=42)
        self.assertEqual(500, len(result.people))
        self.assertTrue(result.ok, [f.to_dict() for f in result.findings if f.level == "error"])
        self.assertEqual(500, len({p.id for p in result.people}))

    def test_small_populations_do_not_crash(self):
        for size in (20, 25, 50):
            result = _generate(size=size, seed=1)
            self.assertEqual(size, len(result.people))
            self.assertFalse(has_errors(result.findings), (size, result.findings))

    def test_every_preset_generates_without_errors(self):
        for name in PRESETS:
            result = _generate(size=300, seed=8, preset=name)
            self.assertFalse(
                has_errors(result.findings),
                (name, [f.to_dict() for f in result.findings if f.level == "error"]),
            )


class PipelineOrderTests(unittest.TestCase):
    def test_households_must_be_built_before_the_graph(self):
        # Guards the documented ordering: the social graph reads household
        # membership, so building it first would silently drop all kin ties.
        spec = normalize_spec({"size": 150, "seed": 6})
        people, _ = synthesize_people(spec)
        households = build_households(spec, people)
        workplaces = build_workplaces(spec, people)
        neighbours = build_social_graph(spec, people, households, workplaces)
        kin_roles = {item.get("role") for person in people for item in person.relationships.values()}
        self.assertTrue({"spouse", "parent", "child", "sibling"} & kin_roles)
        self.assertEqual(len(people), len(neighbours))


if __name__ == "__main__":
    unittest.main()
