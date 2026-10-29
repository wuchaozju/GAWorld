"""
Randomization designs and sanity diagnostics for unblinded LLM experiments.

This module is the "experimental unblinding randomization kit" behind the
Gui & Toubia (2025) comparison. It holds:

- RandomizationDesign: a frozen record describing one treatment variable
  (its machine name, human label, support min/max, unit, distribution,
  number of grid points, blinding setting, seed, and the covariates the
  prompt specifies).
- RandomizationDesign.sample(rng): draw one treatment value.
- RandomizationDesign.grid(): build the fixed sweep of treatment values that
  diagnostics sweep over.
- RandomizationDesign.render_unblinding(): render the unblinding system-prompt
  paragraph (blinded designs render nothing).
- RandomizationDesign.to_json() / from_json(): store and rebuild a design.
- spearman_with_ci: Spearman rank correlation with a bootstrap confidence
  interval (never a p-value).
- check_confounding: does a covariate leak the treatment level?
- check_monotonicity: does the outcome curve follow the expected direction?
- check_step_function: does the outcome jump at one level (focalism)?
- check_non_response: does the outcome ignore the treatment entirely?
- count_specified_covariates: heuristic count of key: value persona pairs.
- lint_covariate_count: warn/flag tiers for too many specified covariates.
- covariate_count_for_depth: map a persona depth ("none", "demographics",
  or an Appendix E stage depth "stage2".."stage12") onto how many
  covariates that depth pins in the prompt; the removed behavioural tiers
  (tightwad/time_preference/risk_preference), the non-depth "stage1", and
  any other unknown name raise.
- COVARIATE_COUNT_FOR_DEPTH: the module-level table behind that mapping.
- STAGE_COVARIATE_COUNTS / stage_covariate_count: Table E.1's cumulative
  covariate count per stage (1..12) - 14, 15, 17 ... 30.
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field, fields
from statistics import median
from typing import Any

from fos.i18n import T

# Keys that a linear ramp design can expect the outcome curve to follow.
_SUPPORTED_EXPECTED = ("down", "up", "none")

# Focalism tiers from the paper's Fig. 5 (error is non-monotonic in how many
# covariates the prompt pins down).
_WARN_COVARIATES_ABOVE = 10
_FLAG_COVARIATES_ABOVE = 20

# Adjacent-level jump must exceed this multiple of the within-level spread
# before the curve counts as a step function.
_STEP_JUMP_RATIO = 3.0

# Confounding tiers: how large |rho| must be once the CI excludes zero.
_MILD_RHO = 0.2
_SEVERE_RHO = 0.5

# Table E.1 of Gui & Toubia (2025): cumulative covariate count per stage of
# the measured-covariate sensitivity analysis. Stage 1 is the 14 Prompt-12
# demographics; each later stage adds one behavioural/psychological measure
# chunk (the Big Five at stage 12), so the counts run 14, 15, 17 ... 30.
STAGE_COVARIATE_COUNTS = {
    1: 14,
    2: 15,
    3: 17,
    4: 18,
    5: 19,
    6: 20,
    7: 21,
    8: 22,
    9: 23,
    10: 24,
    11: 25,
    12: 30,
}


def stage_covariate_count(stage: int) -> int:
    """Return Table E.1's cumulative covariate count for one stage (1..12).

    Stages outside 1..12 (0, 13, a string, None) raise ValueError instead of
    guessing a budget.
    """
    if stage not in STAGE_COVARIATE_COUNTS:
        raise ValueError(T("error.randomization.unsupported_stage", stage=repr(stage)))
    return STAGE_COVARIATE_COUNTS[stage]


# How many covariates each persona depth pins in the survey prompt. The
# paper's depth ladder keeps the two levels {1, 2} (Gui & Toubia 2025
# Appendix D): "none" adds no persona block at all and "demographics" pins
# the 11 Appendix D demographic fields. Appendix E extends the vocabulary
# with the measured-covariate stage depths "stage2".."stage12" (Table E.1
# cumulative counts 15..30); "stage1" is a Table E.1 stage, not a depth
# name, so it stays out of the map and raises like any unknown name.
COVARIATE_COUNT_FOR_DEPTH = {
    "none": 0,
    "demographics": 11,
    **{f"stage{stage}": STAGE_COVARIATE_COUNTS[stage] for stage in range(2, 13)},
}


@dataclass(frozen=True)
class RandomizationDesign:
    """One randomized treatment variable for an experiment.

    Attributes:
        variable: machine name of the treatment, e.g. "price".
        label: human-readable name, e.g. "the price of the product".
        min_value: low end of the treatment support.
        max_value: high end of the treatment support.
        unit: display unit, e.g. "% of regular price" ("" when none).
        distribution: "uniform" (continuous draws) or "grid" (fixed levels).
        grid_points: how many levels grid() returns (11 by default).
        blinding: "unblinded" (render a paragraph) or "blinded" (no paragraph).
        seed: optional design-level seed, kept as metadata for storage.
        blind_to_randomization: True when the subject never sees the design.
        covariates_specified: persona covariates the prompt pins down.
        persona_depth: how deep the persona block goes: "none" (no block),
            "demographics" (the 11 demographic fields), or an Appendix E
            stage depth "stage2".."stage12". The removed behavioural tiers
            of the pre-drift ladder and any other name raise ValueError.
        covariate_count: how many covariates the chosen depth pins (0, 11,
            or a Table E.1 count 15..30), kept as explicit metadata so
            stored records self-describe.
    """

    variable: str
    label: str
    min_value: float
    max_value: float
    unit: str = ""
    distribution: str = "uniform"
    grid_points: int = 11
    blinding: str = "unblinded"
    seed: int | None = None
    blind_to_randomization: bool = True
    covariates_specified: list[str] = field(default_factory=list)
    persona_depth: str = "none"
    covariate_count: int = 0

    def __post_init__(self) -> None:
        """Reject an unknown persona depth at construction time.

        Only "none", "demographics" and the Appendix E stage depths
        "stage2".."stage12" are legal values; a typo such as "occluded", the
        superseded "extended", the removed behavioural tiers
        (tightwad/time_preference/risk_preference), or the non-depth
        "stage1" must fail loudly instead of silently producing a run that
        never renders a persona block. The error text goes through T() so it
        stays localizable like every other error here.
        """
        if self.persona_depth not in COVARIATE_COUNT_FOR_DEPTH:
            raise ValueError(
                T(
                    "error.randomization.unsupported_persona_depth",
                    depth=repr(self.persona_depth),
                    supported=", ".join(sorted(COVARIATE_COUNT_FOR_DEPTH)),
                )
            )

    def sample(self, rng: random.Random) -> float:
        """Draw one treatment value inside the support.

        A grid design picks one level evenly; a uniform design draws a
        continuous value. Unknown distributions raise instead of guessing.
        """
        if self.distribution == "grid":
            return float(rng.choice(self.grid()))
        if self.distribution == "uniform":
            return rng.uniform(self.min_value, self.max_value)
        raise ValueError(
            T(
                "error.randomization.unsupported_distribution",
                distribution=repr(self.distribution),
            )
        )

    def grid(self) -> list[float]:
        """Return the evenly spaced sweep of treatment levels.

        The sweep always covers min_value .. max_value in grid_points steps
        (for the paper price design: 0..200 in 11 steps of 20).
        """
        if self.grid_points <= 1:
            return [float(self.min_value)]
        step = (self.max_value - self.min_value) / (self.grid_points - 1)
        return [self.min_value + index * step for index in range(self.grid_points)]

    def render_unblinding(self) -> str:
        """Render the unblinding system-prompt paragraph.

        Mirrors Gui & Toubia Prompt 6: it states that the variable is
        randomly and uniformly drawn from min to max and that the subject is
        blind to the randomization. A blinded design renders the empty string
        so the user prompt stays identical across the A/B split.
        """
        if self.blinding == "blinded":
            return ""
        unit_text = f" {self.unit}" if self.unit else ""
        return (
            "You, AI, are an expert in predicting human behavior. In the "
            f"survey, {self.label} is randomly and uniformly drawn from "
            f"{self.min_value:g} to {self.max_value:g}{unit_text}. The subject "
            "is only presented with one value and is blind to this "
            "randomization design."
        )

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-friendly dict describing this design."""
        return {
            "variable": self.variable,
            "label": self.label,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "unit": self.unit,
            "distribution": self.distribution,
            "grid_points": self.grid_points,
            "blinding": self.blinding,
            "seed": self.seed,
            "blind_to_randomization": self.blind_to_randomization,
            "covariates_specified": list(self.covariates_specified),
            "persona_depth": self.persona_depth,
            "covariate_count": self.covariate_count,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "RandomizationDesign":
        """Rebuild a design from the dict to_json() produced.

        Extra keys (for example a schema version) are ignored so old stored
        designs keep loading.
        """
        known = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})


def covariate_count_for_depth(depth: str) -> int:
    """Return how many covariates one persona depth pins in the prompt.

    "none" pins nothing (0), "demographics" pins the 11 Appendix D
    demographic fields (11), and the Appendix E stage depths "stage2"..
    "stage12" pin Table E.1's cumulative counts (15..30). The removed
    behavioural tiers (tightwad/time_preference/risk_preference), the
    non-depth "stage1", and any unknown depth raise ValueError so a typo
    never silently runs with the wrong covariate budget.
    """
    if depth not in COVARIATE_COUNT_FOR_DEPTH:
        raise ValueError(
            T(
                "error.randomization.unsupported_persona_depth",
                depth=repr(depth),
                supported=", ".join(sorted(COVARIATE_COUNT_FOR_DEPTH)),
            )
        )
    return COVARIATE_COUNT_FOR_DEPTH[depth]


# ── Spearman correlation with a bootstrap CI ────────────────────────────────


def _rank(values: list[float]) -> list[float]:
    """Rank a list, giving tied values the average of their rank slots."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(values):
        end = cursor
        while end + 1 < len(values) and values[order[end + 1]] == values[order[cursor]]:
            end += 1
        average_rank = (cursor + end) / 2.0 + 1.0
        for index in range(cursor, end + 1):
            ranks[order[index]] = average_rank
        cursor = end + 1
    return ranks


def _pearson(a: list[float], b: list[float]) -> float:
    """Pearson correlation of two equal-length lists.

    A fully constant list has no defined spread; when both sides are constant
    and equal we report perfect agreement (1.0), otherwise no agreement (0.0).
    """
    count = len(a)
    mean_a = sum(a) / count
    mean_b = sum(b) / count
    covariance = sum((left - mean_a) * (right - mean_b) for left, right in zip(a, b))
    variance_a = sum((value - mean_a) ** 2 for value in a)
    variance_b = sum((value - mean_b) ** 2 for value in b)
    if variance_a == 0.0 and variance_b == 0.0:
        return 1.0 if a == b else 0.0
    if variance_a == 0.0 or variance_b == 0.0:
        return 0.0
    return covariance / math.sqrt(variance_a * variance_b)


def spearman_with_ci(
    x: list[float], y: list[float], n_boot: int = 200, seed: int = 0
) -> dict[str, float]:
    """Spearman rank correlation of x and y with a 95% bootstrap CI.

    Pairs are resampled with replacement n_boot times and the confidence
    interval is the 2.5th .. 97.5th percentile of the resampled rhos. Only
    confidence intervals are reported — never p-values.
    """
    rank_x = _rank(x)
    rank_y = _rank(y)
    rho = _pearson(rank_x, rank_y)
    count = len(x)
    boot_rng = random.Random(seed)
    boot_rhos: list[float] = []
    for _ in range(n_boot):
        picks = [boot_rng.randrange(count) for _ in range(count)]
        sample_x = [rank_x[pick] for pick in picks]
        sample_y = [rank_y[pick] for pick in picks]
        boot_rhos.append(_pearson(sample_x, sample_y))
    boot_rhos.sort()
    low_index = int(0.025 * (n_boot - 1))
    high_index = int(0.975 * (n_boot - 1))
    return {
        "rho": rho,
        "ci_lo": boot_rhos[low_index],
        "ci_hi": boot_rhos[high_index],
    }


# ── Confounding diagnostic ──────────────────────────────────────────────────


def check_confounding(
    records: list[dict[str, float]], treatment_key: str, value_key: str
) -> dict[str, Any]:
    """Check whether one covariate leaks the treatment level.

    Each record must hold a treatment value under treatment_key and the
    covariate value under value_key. Returns Spearman rho, its bootstrap CI,
    and a flag: "ok" when the CI includes zero, otherwise "mild" or "severe"
    depending on how far |rho| sits from zero.
    """
    treatments = [record[treatment_key] for record in records]
    values = [record[value_key] for record in records]
    stats = spearman_with_ci(treatments, values)
    rho = stats["rho"]
    ci_lo = stats["ci_lo"]
    ci_hi = stats["ci_hi"]
    if ci_lo <= 0.0 <= ci_hi:
        flag = "ok"
    elif abs(rho) >= _SEVERE_RHO:
        flag = "severe"
    else:
        flag = "mild"
    return {"rho": rho, "ci_lo": ci_lo, "ci_hi": ci_hi, "flag": flag}


# ── Outcome-curve sanity checks ─────────────────────────────────────────────


def check_monotonicity(
    levels: list[float], means: list[float], expected: str = "down"
) -> dict[str, Any]:
    """Check that the outcome means follow the expected direction.

    For expected="down" a violation is a rising step (means[i] < means[i+1]);
    for expected="up" it is a falling step. Returns whether the curve is
    monotone and the list of violating step indices.
    """
    if expected not in _SUPPORTED_EXPECTED:
        raise ValueError(
            T(
                "error.randomization.unsupported_expected",
                supported=", ".join(_SUPPORTED_EXPECTED),
            )
        )
    if expected == "none":
        return {"monotone": True, "violations": []}
    if expected == "down":
        violations = [
            index for index in range(len(means) - 1) if means[index] < means[index + 1]
        ]
    else:
        violations = [
            index for index in range(len(means) - 1) if means[index] > means[index + 1]
        ]
    return {"monotone": len(violations) == 0, "violations": violations}


def _level_mads(all_draws: list[list[float]]) -> list[float]:
    """Median absolute deviation of each level's draws around its own median."""
    mads: list[float] = []
    for draws in all_draws:
        center = median(draws)
        deviations = [abs(value - center) for value in draws]
        mads.append(median(deviations))
    return mads


def check_step_function(
    levels: list[float], all_draws: list[list[float]]
) -> dict[str, Any]:
    """Check whether one treatment level jumps far above its neighbours.

    Compares the largest jump between adjacent levels with the typical
    within-level spread (median absolute deviation). When the jump exceeds
    3x the spread the curve behaves like a step function (focalism).
    """
    level_means = [sum(draws) / len(draws) for draws in all_draws]
    jumps = [
        abs(level_means[index + 1] - level_means[index])
        for index in range(len(level_means) - 1)
    ]
    max_jump = max(jumps) if jumps else 0.0
    typical_spread = median(_level_mads(all_draws)) if all_draws else 0.0
    if typical_spread == 0.0:
        max_jump_ratio = math.inf if max_jump > 0.0 else 0.0
    else:
        max_jump_ratio = max_jump / typical_spread
    return {
        "is_step": max_jump_ratio > _STEP_JUMP_RATIO,
        "max_jump_ratio": max_jump_ratio,
    }


def check_non_response(
    levels: list[float], means: list[float], tol: float = 0.02
) -> dict[str, bool]:
    """Check whether the outcome ignores the treatment entirely.

    When every level mean sits within tol of the others the curve is flat and
    the model is treated as not responding to the treatment.
    """
    spread = max(means) - min(means)
    return {"is_flat": spread <= tol}


# ── Covariate-count focalism lint ───────────────────────────────────────────

_COVARIATE_LINE = re.compile(r"^\s*(?:[-*]\s+)?[A-Za-z][A-Za-z0-9 _/.-]*\s*:\s*\S")


def count_specified_covariates(text: str) -> int:
    """Count how many key: value pairs a prompt pins down.

    Each line may carry an optional "-" or "*" bullet. At most one pair is
    counted per line, so prose headers such as "EMBODY THIS PERSON:" (which
    has no value after the colon) do not count.
    """
    count = 0
    for line in text.splitlines():
        if _COVARIATE_LINE.search(line):
            count += 1
    return count


def lint_covariate_count(n: int) -> str:
    """Tier a covariate count for the focalism lint.

    Returns "ok" up to 10 specified covariates, "warn" from 11 to 20, and
    "flag" above 20 (the paper's Fig. 5 thresholds).
    """
    if n <= _WARN_COVARIATES_ABOVE:
        return "ok"
    if n <= _FLAG_COVARIATES_ABOVE:
        return "warn"
    return "flag"
