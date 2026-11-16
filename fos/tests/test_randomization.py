# Tests for the experimental unblinding randomization kit (Gui & Toubia 2025).
#
# These tests specify a not-yet-existing module `fos.experiments.randomization`
# that holds:
# - RandomizationDesign: a frozen dataclass describing one randomized treatment
#   variable (its name, human label, support min/max, unit, distribution, how
#   many grid points, blinding, seed, and which covariates are specified).
# - Methods on the design: sample a value, build a fixed sweep grid, render the
#   unblinding system-prompt paragraph, and convert to/from JSON for storage.
# - Diagnostics helpers with no p-values anywhere (confidence intervals only):
#   spearman_with_ci, check_confounding, check_monotonicity,
#   check_step_function, check_non_response, count_specified_covariates,
#   lint_covariate_count.
#
# Every test here is expected to FAIL right now because the module does not
# exist yet — that is the RED phase of TDD.

import json
import math
import random
from dataclasses import FrozenInstanceError, replace

import pytest

from fos.experiments.randomization import (
    RandomizationDesign,
    check_confounding,
    check_monotonicity,
    check_non_response,
    check_step_function,
    count_specified_covariates,
    lint_covariate_count,
    spearman_with_ci,
)


def _price_design(**overrides):
    """Make a paper-style price design (0 to 200 percent of regular price)."""
    base = RandomizationDesign(
        variable="price",
        label="the price of the product",
        min_value=0.0,
        max_value=200.0,
        unit="% of regular price",
        distribution="uniform",
        grid_points=11,
        blinding="unblinded",
        seed=None,
        blind_to_randomization=True,
        covariates_specified=[],
    )
    return replace(base, **overrides)


# ---------------------------------------------------------------------------
# 1. RandomizationDesign — frozen dataclass with documented defaults
# ---------------------------------------------------------------------------


class TestRandomizationDesignShape:
    def test_design_has_expected_default_field_values(self):
        """A design with only the four required fields gets the documented defaults."""
        design = RandomizationDesign(
            variable="price", label="the price", min_value=0.0, max_value=200.0
        )
        assert design.variable == "price"
        assert design.label == "the price"
        assert design.min_value == 0.0
        assert design.max_value == 200.0
        assert design.unit == ""
        assert design.distribution == "uniform"
        assert design.grid_points == 11
        assert design.blinding == "unblinded"
        assert design.seed is None
        assert design.blind_to_randomization is True
        assert design.covariates_specified == []

    def test_design_is_frozen_and_cannot_be_mutated(self):
        """Assigning a field on a frozen design must raise FrozenInstanceError."""
        design = _price_design()
        with pytest.raises(FrozenInstanceError):
            design.variable = "renamed"

    def test_design_allows_all_fields_to_be_set_explicitly(self):
        """A design built with every field set keeps all of those values."""
        design = _price_design(
            distribution="grid",
            grid_points=11,
            blinding="blinded",
            seed=7,
            blind_to_randomization=False,
            covariates_specified=["income", "age"],
        )
        assert design.distribution == "grid"
        assert design.grid_points == 11
        assert design.blinding == "blinded"
        assert design.seed == 7
        assert design.blind_to_randomization is False
        assert design.covariates_specified == ["income", "age"]


# ---------------------------------------------------------------------------
# 2. sample() and grid() — draws and fixed sweeps
# ---------------------------------------------------------------------------


class TestSamplingAndGrid:
    def test_sample_returns_values_within_support_for_uniform(self):
        """Every draw from a uniform price design stays between 0 and 200."""
        design = _price_design()
        rng = random.Random(1)
        values = [design.sample(rng) for _ in range(500)]
        for value in values:
            assert design.min_value <= value <= design.max_value, (
                f"draw {value} escaped the support [{design.min_value}, {design.max_value}]"
            )

    def test_sample_is_deterministic_for_the_same_seed(self):
        """Two fresh Random(seed) objects fed to the same design give the same draws."""
        design = _price_design(seed=42)
        first = [design.sample(random.Random(99)) for _ in range(10)]
        second = [design.sample(random.Random(99)) for _ in range(10)]
        assert first == second

    def test_grid_for_grid_distribution_is_exact_paper_sweep(self):
        """0..200 percent in 11 points must be exactly 0, 20, ..., 200."""
        design = _price_design(distribution="grid")
        assert design.grid() == [0.0, 20.0, 40.0, 60.0, 80.0, 100.0,
                                 120.0, 140.0, 160.0, 180.0, 200.0]

    def test_uniform_design_also_provides_an_even_grid(self):
        """Even a continuous uniform design offers a fixed sweep for diagnostics."""
        design = _price_design(distribution="uniform", grid_points=5)
        grid = design.grid()
        assert grid[0] == 0.0
        assert grid[-1] == 200.0
        assert len(grid) == 5
        steps = [grid[i + 1] - grid[i] for i in range(len(grid) - 1)]
        assert all(math.isclose(step, 50.0, rel_tol=0, abs_tol=1e-9) for step in steps)


# ---------------------------------------------------------------------------
# 3. render_unblinding() — the paper's Prompt-6 system paragraph
# ---------------------------------------------------------------------------


class TestRenderUnblinding:
    def test_unblinded_prompt_names_the_distribution_and_support(self):
        """The paragraph must say 'uniform' and quote the support numbers."""
        text = _price_design().render_unblinding()
        lowered = text.lower()
        assert "uniform" in lowered
        assert "0" in text and "200" in text

    def test_unblinded_prompt_says_the_value_is_randomly_drawn(self):
        """The paragraph must say the variable is randomly drawn."""
        text = _price_design().render_unblinding()
        assert "random" in text.lower()

    def test_unblinded_prompt_says_the_subject_is_blind(self):
        """The paragraph must say the subject is blind to the randomization."""
        text = _price_design().render_unblinding()
        assert "blind" in text.lower()

    def test_unblinded_prompt_mentions_the_variable_label(self):
        """The paragraph quotes the human label of the variable."""
        text = _price_design(label="the price of the product").render_unblinding()
        assert "the price of the product" in text

    def test_blinded_design_renders_no_paragraph(self):
        """A blinded design must render the empty string, not a paragraph."""
        blinded = _price_design(blinding="blinded")
        assert blinded.render_unblinding() == ""


# ---------------------------------------------------------------------------
# 4. to_json() / from_json() — storage round trip
# ---------------------------------------------------------------------------


class TestJsonRoundTrip:
    def test_to_json_and_from_json_round_trip_preserves_all_fields(self):
        """A design survives to_json then from_json unchanged."""
        design = _price_design(
            distribution="grid",
            seed=5,
            covariates_specified=["income", "age"],
        )
        assert RandomizationDesign.from_json(design.to_json()) == design

    def test_to_json_is_serializable_to_a_json_string(self):
        """to_json output must survive json.dumps/loads and still rebuild the design."""
        design = _price_design()
        restored = RandomizationDesign.from_json(json.loads(json.dumps(design.to_json())))
        assert restored == design


# ---------------------------------------------------------------------------
# 5. spearman_with_ci() — correlation with bootstrap CI, no p-values
# ---------------------------------------------------------------------------


class TestSpearmanWithCi:
    def test_spearman_with_ci_returns_rho_and_ci_keys(self):
        """The result is a dict with float rho and a ci_lo/ci_hi interval."""
        x = list(range(30))
        result = spearman_with_ci(x, x)
        assert set(result) == {"rho", "ci_lo", "ci_hi"}
        assert isinstance(result["rho"], float)
        assert isinstance(result["ci_lo"], float)
        assert isinstance(result["ci_hi"], float)
        assert result["ci_lo"] <= result["ci_hi"]

    def test_perfectly_monotone_data_gives_rho_one_and_ci_excluding_zero(self):
        """On perfectly monotone data rho is ~1.0 and the CI stays above 0."""
        x = list(range(60))
        result = spearman_with_ci(x, x)
        assert math.isclose(result["rho"], 1.0, abs_tol=1e-9)
        assert result["ci_lo"] > 0.0

    def test_noise_data_ci_includes_zero(self):
        """On shuffled noise the CI must include 0."""
        x = list(range(60))
        y = x[:]
        random.Random(7).shuffle(y)
        result = spearman_with_ci(x, y)
        assert result["ci_lo"] <= 0.0 <= result["ci_hi"]


# ---------------------------------------------------------------------------
# 6. check_confounding() — covariate leaks treatment level
# ---------------------------------------------------------------------------


def _confounding_records(make_covariate, n=300, treatment_seed=11, noise_seed=12):
    """Build n records whose treatment runs 0..200 and covariate comes from make_covariate."""
    treatment = random.Random(treatment_seed)
    noise = random.Random(noise_seed)
    records = []
    for _ in range(n):
        t = treatment.uniform(0.0, 200.0)
        records.append({"price": t, "last_price_paid": make_covariate(t, noise)})
    return records


class TestCheckConfounding:
    def test_severe_flag_when_covariate_tracks_the_treatment(self):
        """A covariate almost equal to the treatment is flagged severe."""
        records = _confounding_records(
            lambda t, noise: t + noise.gauss(0.0, 1.0), n=200
        )
        result = check_confounding(records, "price", "last_price_paid")
        assert {"rho", "ci_lo", "ci_hi", "flag"} <= set(result)
        assert result["flag"] == "severe"
        assert result["ci_lo"] > 0.0 or result["ci_hi"] < 0.0

    def test_ok_flag_when_covariate_is_unrelated_noise(self):
        """An independent-noise covariate is not confounded and is flagged ok."""
        records = _confounding_records(lambda t, noise: noise.gauss(0.0, 50.0), n=300)
        result = check_confounding(records, "price", "last_price_paid")
        assert result["flag"] == "ok"
        assert result["ci_lo"] <= 0.0 <= result["ci_hi"]

    def test_mild_flag_for_a_moderate_correlation(self):
        """A moderate positive correlation is flagged mild, not severe or ok."""
        records = _confounding_records(
            lambda t, noise: 0.5 * t + noise.gauss(0.0, 66.0), n=600
        )
        result = check_confounding(records, "price", "last_price_paid")
        assert result["flag"] == "mild"
        assert result["ci_lo"] > 0.0


# ---------------------------------------------------------------------------
# 7. check_monotonicity() — outcome curves vs the theory direction
# ---------------------------------------------------------------------------


class TestCheckMonotonicity:
    def test_downward_curve_is_monotone_when_expected_down(self):
        """A steadily decreasing curve has no violations when expected down."""
        levels = [0, 40, 80, 120, 160, 200]
        means = [10.0, 8.0, 6.0, 4.0, 2.0, 1.0]
        result = check_monotonicity(levels, means, expected="down")
        assert result["monotone"] is True
        assert result["violations"] == []

    def test_inverted_u_curve_is_flagged_for_expected_down(self):
        """A rise-then-fall curve is not monotone down and flags its rising peak."""
        levels = [0, 40, 80, 120, 160, 200]
        means = [1.0, 2.0, 4.0, 6.0, 4.0, 2.0]
        result = check_monotonicity(levels, means, expected="down")
        assert result["monotone"] is False
        assert len(result["violations"]) >= 1
        for index in result["violations"]:
            assert 0 <= index < len(means) - 1
            assert means[index] < means[index + 1], (
                f"violation index {index} does not point at a rising step"
            )

    def test_upward_curve_is_monotone_when_expected_up(self):
        """A steadily increasing curve has no violations when expected up."""
        levels = [0, 40, 80, 120, 160, 200]
        means = [1.0, 2.0, 4.0, 6.0, 8.0, 10.0]
        result = check_monotonicity(levels, means, expected="up")
        assert result["monotone"] is True
        assert result["violations"] == []


# ---------------------------------------------------------------------------
# 8. check_step_function() — one level jumps far above its neighbours
# ---------------------------------------------------------------------------


class TestCheckStepFunction:
    def test_sharp_single_jump_is_detected_as_a_step(self):
        """One level far above the others with tight within-level spread is a step."""
        levels = [0, 40, 80, 120, 160, 200]
        all_draws = []
        for level_mean in [1.0, 1.0, 1.0, 1.0, 60.0, 1.0]:
            rng = random.Random(level_mean)
            all_draws.append([level_mean + rng.uniform(-0.2, 0.2) for _ in range(30)])
        result = check_step_function(levels, all_draws)
        assert set(result) == {"is_step", "max_jump_ratio"}
        assert result["is_step"] is True
        assert result["max_jump_ratio"] > 1.0

    def test_smooth_linear_ramp_is_not_a_step(self):
        """A gentle linear ramp with noisy draws is not step behaviour."""
        levels = [0, 40, 80, 120, 160, 200]
        all_draws = []
        for level_mean in [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]:
            rng = random.Random(level_mean)
            all_draws.append([level_mean + rng.uniform(-5.0, 5.0) for _ in range(30)])
        result = check_step_function(levels, all_draws)
        assert result["is_step"] is False


# ---------------------------------------------------------------------------
# 9. check_non_response() — the model ignores the treatment entirely
# ---------------------------------------------------------------------------


class TestCheckNonResponse:
    def test_flat_curve_is_reported_as_non_response(self):
        """Means that barely move across levels are flagged flat."""
        levels = [0, 40, 80, 120, 160, 200]
        means = [0.500, 0.505, 0.498, 0.502, 0.500, 0.504]
        result = check_non_response(levels, means)
        assert set(result) == {"is_flat"}
        assert result["is_flat"] is True

    def test_curve_with_real_response_is_not_flat(self):
        """A curve that moves well beyond the tolerance is not non-response."""
        levels = [0, 40, 80, 120, 160, 200]
        means = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
        result = check_non_response(levels, means)
        assert result["is_flat"] is False

    def test_tolerance_parameter_is_respected(self):
        """A small wiggle is flat only once the tolerance is large enough."""
        levels = [0, 40, 80, 120, 160, 200]
        means = [0.45, 0.50, 0.55, 0.50, 0.45, 0.50]
        assert check_non_response(levels, means)["is_flat"] is False
        assert check_non_response(levels, means, tol=0.12)["is_flat"] is True


# ---------------------------------------------------------------------------
# 10. count_specified_covariates() — heuristic focalism lint input
# ---------------------------------------------------------------------------


class TestCountSpecifiedCovariates:
    def test_plain_prose_counts_zero(self):
        """Text without key: value pairs contains no specified covariates."""
        text = (
            "You are an expert marketer. Decide whether to buy the product "
            "and explain your reasoning in one short paragraph."
        )
        assert count_specified_covariates(text) == 0

    def test_bulleted_key_value_lines_are_counted(self):
        """Persona lines like '- age: 35' each count as one specified covariate."""
        text = (
            "EMBODY THIS PERSON:\n"
            "- age: 35\n"
            "- household income: 72000\n"
            "- education level: college\n"
            "You are buying for your family."
        )
        assert count_specified_covariates(text) == 3

    def test_fourteen_line_persona_block_counts_fourteen(self):
        """A 14-line persona block is counted as 14 specified covariates."""
        lines = [
            "age: 41",
            "gender: female",
            "household income: 83000",
            "marital status: married",
            "number of children: 2",
            "education level: masters",
            "occupation: teacher",
            "city of residence: hangzhou",
            "home ownership: owns",
            "car ownership: one",
            "monthly grocery budget: 3200",
            "primary shopper: yes",
            "prefers organic food: sometimes",
            "price sensitivity: high",
        ]
        block = "EMBODY THIS PERSON:\n" + "\n".join(f"- {line}" for line in lines)
        assert count_specified_covariates(block) == 14


# ---------------------------------------------------------------------------
# 11. lint_covariate_count() — warn/flag tiers from paper Fig. 5
# ---------------------------------------------------------------------------


class TestLintCovariateCount:
    def test_counts_up_to_ten_are_ok(self):
        """Up to 10 specified covariates are fine."""
        assert lint_covariate_count(0) == "ok"
        assert lint_covariate_count(10) == "ok"

    def test_counts_eleven_to_twenty_warn(self):
        """11 to 20 specified covariates trigger a warning."""
        assert lint_covariate_count(11) == "warn"
        assert lint_covariate_count(20) == "warn"

    def test_counts_above_twenty_are_flagged(self):
        """More than 20 specified covariates are hard-flagged."""
        assert lint_covariate_count(21) == "flag"
        assert lint_covariate_count(30) == "flag"
