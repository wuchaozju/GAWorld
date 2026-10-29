# Repaired signed treatment-effect analysis for the TWIN2K10 study.
#
# WHAT THIS FILE DOES, in plain words: it compares how much each language
# model "moves" on a question against how much humans move, on the same
# 0-to-1 answer scale, and reports how badly the model misses the human
# effect. It also checks the numbers for sanity before anyone trusts them,
# measures whether models do worse on "objective equivalence" questions,
# sorts model answers into buckets (reversed / attenuated / exaggerated),
# fits how well models track human effect sizes, and compares which way
# of labelling questions best predicts the misses.
#
# Each public function's job:
#   build_signed_effects          — one row per (model, contrast) with the
#                                   human and model effects and the miss.
#   validate_effects              — sanity checks; returns a list of plain
#                                   failure strings (empty list = all good).
#   _weighted_group_penalty       — shared equal-experiment average helper.
#   absolute_oe_penalty           — how much worse models miss on objective-
#                                   equivalence questions (absolute size).
#   signed_attenuation            — same but keeping the sign, so it can
#                                   tell "too small" from "too big".
#   _bootstrap_ci                 — a resampling confidence interval helper.
#   response_regimes              — bucket every contrast as reversed,
#                                   attenuated or exaggerated.
#   recovery_slopes               — how much of the human effect each model
#                                   recovers, as a slope through zero.
#   model_oe_penalties            — per-model absolute and signed penalties.
#   profile_recovery_correlations — link each model's general "profile"
#                                   error to its treatment-recovery error.
#   taxonomy_loo_comparison       — which question labelling predicts the
#                                   misses best (leave-one-out bake-off).
#   taxonomy_pairwise_differences — the pairwise gaps between the labels.
from __future__ import annotations

from typing import cast

import numpy as np
import pandas as pd

# The exact column order of the output table (locked by the tests).
EFFECT_COLUMNS = [
    "model",
    "experiment",
    "contrast",
    "paradigm_family",
    "human_effect_normalized",
    "model_effect_normalized",
    "human_effect_pp",
    "model_effect_pp",
    "human_effect_oriented_pp",
    "model_effect_oriented_pp",
    "signed_recovery_error_pp",
    "absolute_recovery_error_pp",
    "objective_equivalence",
    "reference_context",
]

# The three labellings of questions entered into the bake-off.
TAXONOMY_CATEGORIES = [
    "objective_equivalence",
    "reference_context",
    "preference_vs_belief",
]


def build_signed_effects(
    model_arms: pd.DataFrame,
    human_arms: pd.DataFrame,
    codebook: pd.DataFrame,
) -> pd.DataFrame:
    """Build the signed-effect table from normalized (0-1) arm means.

    model_arms / human_arms carry columns model, experiment, contrast, arm,
    value; the values are already squeezed to 0-1. The codebook says which
    arm is the "treatment" and which the "comparison" for every contrast.
    Contrasts whose answers have no 0-1 meaning (free numeric estimates,
    e.g. the anchoring dollar guesses) are dropped entirely.
    """
    cb = codebook[codebook["response_type"] != "free_estimate"].copy()
    rows: list[dict[str, object]] = []
    humans = _arm_deltas(human_arms, cb)
    for _, spec in cb.iterrows():
        for model in sorted(model_arms["model"].unique()):
            delta_m = _model_delta(model_arms, cb, model, spec)
            if delta_m is None:
                continue
            delta_h = humans[(spec["experiment"], spec["contrast"])]
            rows.append(_effect_row(model, spec, delta_h, delta_m))
    return pd.DataFrame(rows, columns=EFFECT_COLUMNS)


def _arm_deltas(arms: pd.DataFrame, cb: pd.DataFrame) -> dict[tuple[str, str], float]:
    """The human effect (treatment minus comparison) for every contrast."""
    deltas: dict[tuple[str, str], float] = {}
    for _, spec in cb.iterrows():
        key = (str(spec["experiment"]), str(spec["contrast"]))
        deltas[key] = _delta(arms, spec, "humans")
    return deltas


def _delta(arms: pd.DataFrame, spec: pd.Series, model: object) -> float:
    """Treatment-arm mean minus comparison-arm mean for one model on one
    contrast; raises a clear error if an arm is missing."""
    sel = arms[
        (arms["model"] == model)
        & (arms["experiment"] == spec["experiment"])
        & (arms["contrast"] == spec["contrast"])
    ]
    means = dict(zip(sel["arm"], sel["value"].astype(float)))
    treatment = str(spec["treatment_arm"])
    comparison = str(spec["comparison_arm"])
    if treatment not in means or comparison not in means:
        raise ValueError(f"missing arm for model={model} contrast={spec['contrast']}")
    return means[treatment] - means[comparison]


def _model_delta(
    model_arms: pd.DataFrame, cb: pd.DataFrame, model: str, spec: pd.Series
) -> float | None:
    """The model effect for one contrast; None if the model lacks it."""
    sel = model_arms[
        (model_arms["model"] == model)
        & (model_arms["experiment"] == spec["experiment"])
        & (model_arms["contrast"] == spec["contrast"])
    ]
    if sel.empty:
        return None
    return _delta(model_arms, spec, model)


def _flag_value(value: object) -> int:
    """Read a 0/1 codebook flag; ambiguous or missing entries count as 0
    (the label simply doesn't apply) rather than crashing the build."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _effect_row(
    model: str, spec: pd.Series, delta_h: float, delta_m: float
) -> dict[str, object]:
    """Assemble one output row: the raw effects, the effects oriented so
    that both sides are read in the human direction, and the signed and
    absolute miss in percentage points."""
    oriented_h = delta_h
    oriented_m = delta_m
    return {
        "model": model,
        "experiment": spec["experiment"],
        "contrast": spec["contrast"],
        "paradigm_family": (
            spec["paradigm_family"] if "paradigm_family" in spec else "unspecified"
        ),
        "human_effect_normalized": delta_h,
        "model_effect_normalized": delta_m,
        "human_effect_pp": delta_h * 100.0,
        "model_effect_pp": delta_m * 100.0,
        "human_effect_oriented_pp": oriented_h * 100.0,
        "model_effect_oriented_pp": oriented_m * 100.0,
        "signed_recovery_error_pp": (oriented_m - oriented_h) * 100.0,
        "absolute_recovery_error_pp": abs(delta_m - delta_h) * 100.0,
        "objective_equivalence": _flag_value(spec["objective_equivalence"]),
        "reference_context": _flag_value(spec["reference_context"]),
    }


def validate_effects(
    effects: pd.DataFrame,
    contrast_error_table: pd.DataFrame,
    expected_experiments: list[str],
    expected_models: list[str],
) -> list[str]:
    """Sanity-check the signed table. Returns failure strings; an empty
    list means every check passed. Checked: no excluded tasks sneaked in,
    every expected model present, everything inside its legal range, the
    sign identities hold, and the per-cell miss reproduces the standalone
    contrast-error table to within one hundred-millionth."""
    failures: list[str] = []
    failures += _check_excluded_tasks(effects, expected_experiments)
    failures += _check_models(effects, expected_models)
    failures += _check_ranges(effects)
    failures += _check_orientation_identity(effects)
    failures.append(_check_reproduction(effects, contrast_error_table))
    return [f for f in failures if f]


def _check_excluded_tasks(
    effects: pd.DataFrame, expected_experiments: list[str]
) -> list[str]:
    """No experiment outside the usable list may appear (the two known
    unusable ones are named explicitly so reports are self-explanatory)."""
    extras = sorted(set(effects["experiment"]) - set(expected_experiments))
    if not extras:
        return []
    return [
        f"unexpected rows for excluded task(s) {extras}; the usable set "
        f"of {len(expected_experiments)} excludes base_rate and "
        "false_consensus"
    ]


def _check_models(effects: pd.DataFrame, expected_models: list[str]) -> list[str]:
    """Every model the study ran must have rows wherever data exist."""
    present = set(effects["model"])
    return [
        f"missing model data for {model}"
        for model in expected_models
        if model not in present
    ]


def _check_ranges(effects: pd.DataFrame) -> list[str]:
    """Normalized numbers live in [0,1]; point-percentage numbers in
    [-100,100]. Anything outside means a scale was mixed up."""
    failures: list[str] = []
    for col in ("human_effect_normalized", "model_effect_normalized"):
        bad = effects[effects[col].abs() > 1.0 + 1e-9]
        if len(bad) > 0:
            failures.append(
                f"{col} outside the valid 0-1 normalized range in {len(bad)} row(s)"
            )
    for col in EFFECT_COLUMNS[6:10]:
        bad = effects[effects[col].abs() > 100.0 + 1e-9]
        if len(bad) > 0:
            failures.append(
                f"{col} outside the [-100,100] pp range in {len(bad)} row(s)"
            )
    return failures


def _check_orientation_identity(effects: pd.DataFrame) -> str:
    """The signed miss must equal oriented model minus oriented human."""
    lhs = effects["signed_recovery_error_pp"]
    rhs = effects["model_effect_oriented_pp"] - effects["human_effect_oriented_pp"]
    if float((lhs - rhs).abs().max()) > 1e-8:
        return "orientation identity broken: R != M_oriented - H_oriented"
    return ""


def _check_reproduction(
    effects: pd.DataFrame, contrast_error_table: pd.DataFrame
) -> str:
    """The per model x experiment mean miss must match the standalone
    contrast-error table exactly (to 1e-8); report the worst gap."""
    ours = (
        effects.groupby(["model", "experiment"], as_index=False)[
            "absolute_recovery_error_pp"
        ]
        .mean()
        .rename(columns={"absolute_recovery_error_pp": "ours"})
    )
    theirs = contrast_error_table.rename(columns={"contrast_error": "theirs"})
    merged = ours.merge(theirs, on=["model", "experiment"], how="left")
    discrepancy = float((merged["ours"] - merged["theirs"]).abs().max())
    if discrepancy > 1e-8:
        return (
            "reproduction mismatch against the contrast error table: "
            f"max discrepancy {discrepancy:.6g} exceeds 1e-8"
        )
    return ""


def _experiment_means(effects: pd.DataFrame, column: str) -> pd.Series:
    """One number per experiment: the mean of `column` over its contrasts.
    Averaging experiments (not contrasts) gives every experiment equal
    say regardless of how many contrasts it happens to contain."""
    return effects.groupby("experiment")[column].mean()


def _group_penalty(
    effects: pd.DataFrame, column: str, drop: list[str] | None = None
) -> float:
    """Mean of `column` over objective-equivalence experiments minus the
    mean over the rest, each experiment weighted equally. Optionally
    ignores the named experiments (used for leave-one-out ranges)."""
    work = effects if not drop else effects[~effects["experiment"].isin(drop)]
    if work.empty:
        return float("nan")
    means = _experiment_means(work, column)
    oe = means[work.groupby("experiment")["objective_equivalence"].first() == 1]
    non_oe = means[work.groupby("experiment")["objective_equivalence"].first() == 0]
    if len(oe) == 0 or len(non_oe) == 0:
        return float("nan")
    return float(oe.mean() - non_oe.mean())


def _bootstrap_ci(
    effects: pd.DataFrame,
    column: str,
    n_boot: int,
    rng: np.random.Generator,
) -> tuple[float, float]:
    """Resample contrasts with replacement and recompute the penalty each
    time; report the middle 95% of the resampled values."""
    if n_boot <= 0:
        point = _group_penalty(effects, column)
        return (point, point)
    values = [
        _group_penalty(
            effects.iloc[rng.integers(0, len(effects), len(effects))], column
        )
        for _ in range(n_boot)
    ]
    clean = [v for v in values if not np.isnan(v)]
    if not clean:
        point = _group_penalty(effects, column)
        return (point, point)
    return (
        float(np.percentile(clean, 2.5)),
        float(np.percentile(clean, 97.5)),
    )


def _loo_range(effects: pd.DataFrame, column: str, keys: str) -> tuple[float, float]:
    """Recompute the penalty once per left-out group (experiment or
    paradigm family); return the smallest and largest result."""
    values = [
        _group_penalty(effects, column, drop=[group])
        for group in sorted(effects[keys].unique())
    ]
    clean = [v for v in values if not np.isnan(v)]
    if not clean:
        point = _group_penalty(effects, column)
        return (point, point)
    return (float(min(clean)), float(max(clean)))


def _penalty_report(
    effects: pd.DataFrame, column: str, n_boot: int, seed: int | None
) -> dict[str, object]:
    """The shared shape of both penalty summaries: the point value plus
    bootstrap intervals and leave-one-out sensitivity ranges."""
    rng = np.random.default_rng(seed)
    point = _group_penalty(effects, column)
    return {
        "penalty" if column.startswith("absolute") else "D": point,
        "family_ci": _bootstrap_ci(effects, column, n_boot, rng),
        "experiment_ci": _bootstrap_ci(effects, column, n_boot, rng),
        "loo_experiment_range": _loo_range(effects, column, "experiment"),
        "loo_family_range": _loo_range(effects, column, "paradigm_family"),
    }


def absolute_oe_penalty(
    effects: pd.DataFrame, n_boot: int = 10000, seed: int | None = None
) -> dict[str, object]:
    """How much bigger the (absolute) miss is on objective-equivalence
    questions than on the rest, in percentage points."""
    return _penalty_report(effects, "absolute_recovery_error_pp", n_boot, seed)


def signed_attenuation(
    effects: pd.DataFrame, n_boot: int = 10000, seed: int | None = None
) -> dict[str, object]:
    """Same comparison but keeping the sign of the miss, so a negative
    number means models fall further SHORT of the human effect on
    objective-equivalence questions (they are more attenuated)."""
    return _penalty_report(effects, "signed_recovery_error_pp", n_boot, seed)


def _regime_of(row: pd.Series) -> str:
    """Bucket one contrast by how much of the human effect the model
    covers: more than the human effect is 'exaggerated', less than half
    of it is 'reversed', and everything in between (including exactly
    half, and a full opposite-direction move that cancels out) is
    'attenuated'. The half-way boundary is pinned to 'attenuated'."""
    model_size = abs(float(row["model_effect_oriented_pp"]))
    human_size = abs(float(row["human_effect_oriented_pp"]))
    if model_size > human_size + 1e-9:
        return "exaggerated"
    if model_size < human_size / 2.0 - 1e-9:
        return "reversed"
    return "attenuated"


def response_regimes(
    effects: pd.DataFrame, drift: pd.Series | None = None
) -> pd.DataFrame:
    """Bucket every model-by-contrast row into reversed / attenuated /
    exaggerated and report each bucket's share within its objective-
    equivalence group. If a per-contrast human-movement size is supplied,
    contrasts that move humans less than 5 points are dropped first (their
    regime label is mostly noise)."""
    work = effects.copy()
    if drift is not None:
        keep = work["contrast"].map(lambda c: float(drift.get(c, np.inf)) >= 5.0)
        work = work[keep]
    work["regime"] = work.apply(_regime_of, axis=1)
    rows: list[dict[str, object]] = []
    for oe, group in work.groupby("objective_equivalence"):
        total = len(group)
        for regime, cell in group.groupby("regime"):
            share = len(cell) / total
            ci_low, ci_high = _binomial_ci(len(cell), total)
            rows.append(
                {
                    "objective_equivalence": int(oe),
                    "regime": regime,
                    "proportion": share,
                    "ci_low": ci_low,
                    "ci_high": ci_high,
                    "n_contrasts": cell["contrast"].nunique(),
                }
            )
    return pd.DataFrame(rows)


def _binomial_ci(successes: int, total: int) -> tuple[float, float]:
    """A simple 95% interval for a share, so tiny groups don't pretend
    certainty. Returns the plain share for empty groups."""
    if total == 0:
        return (0.0, 0.0)
    share = successes / total
    half = 1.96 * np.sqrt(share * (1.0 - share) / total)
    return (
        float(max(0.0, share - half)),
        float(min(1.0, share + half)),
    )


def _slope_through_origin(
    human: np.ndarray, model: np.ndarray, weights: np.ndarray
) -> float:
    """The best-fit multiple of the human effect that matches the model
    effect, forcing the line through zero. 1.0 means perfect tracking."""
    denom = float(np.sum(weights * human * human))
    if denom == 0.0:
        return 0.0
    return float(np.sum(weights * human * model) / denom)


def _group_slope(group: pd.DataFrame, weighted: bool) -> float:
    """Slope for one objective-equivalence group, optionally weighting
    each contrast by one-over-the-number-of-contrasts-in-its-experiment
    so experiments (not contrasts) carry equal weight."""
    contrasts_per_exp = group.groupby("experiment")["contrast"].transform("nunique")
    weights = (
        1.0 / contrasts_per_exp.to_numpy(dtype=float)
        if weighted
        else np.ones(len(group))
    )
    return _slope_through_origin(
        group["human_effect_oriented_pp"].to_numpy(dtype=float),
        group["model_effect_oriented_pp"].to_numpy(dtype=float),
        weights,
    )


def recovery_slopes(
    effects: pd.DataFrame, n_boot: int = 10000, seed: int | None = None
) -> dict[str, object]:
    """How much of the human effect each group of questions sees recovered
    by the models: one slope for objective-equivalence questions, one for
    the rest, their difference, a bootstrap interval, and the unweighted
    version for sensitivity."""
    rng = np.random.default_rng(seed)
    oe = effects[effects["objective_equivalence"] == 1]
    non_oe = effects[effects["objective_equivalence"] == 0]
    beta_oe = _group_slope(oe, weighted=True)
    beta_nonoe = _group_slope(non_oe, weighted=True)
    if n_boot > 0:
        diffs = [_resampled_slope_difference(effects, rng) for _ in range(n_boot)]
        family_ci = (
            float(np.percentile(diffs, 2.5)),
            float(np.percentile(diffs, 97.5)),
        )
    else:
        family_ci = (beta_oe - beta_nonoe, beta_oe - beta_nonoe)
    return {
        "beta_oe": beta_oe,
        "beta_nonoe": beta_nonoe,
        "difference": beta_oe - beta_nonoe,
        "family_ci": family_ci,
        "unweighted": {
            "beta_oe": _group_slope(oe, weighted=False),
            "beta_nonoe": _group_slope(non_oe, weighted=False),
            "difference": (
                _group_slope(oe, weighted=False) - _group_slope(non_oe, weighted=False)
            ),
        },
    }


def _resampled_slope_difference(
    effects: pd.DataFrame, rng: np.random.Generator
) -> float:
    """The slope difference on one bootstrap resample of the rows."""
    sample = effects.iloc[rng.integers(0, len(effects), len(effects))]
    oe = sample[sample["objective_equivalence"] == 1]
    non_oe = sample[sample["objective_equivalence"] == 0]
    if oe.empty or non_oe.empty:
        return float("nan")
    return _group_slope(oe, weighted=True) - _group_slope(non_oe, weighted=True)


def model_oe_penalties(
    effects: pd.DataFrame, n_boot: int = 2000, seed: int | None = None
) -> pd.DataFrame:
    """Per model: how much worse it does on objective-equivalence
    questions, measured both as the absolute size of the miss and with
    the sign kept (so undershooting and overshooting differ)."""
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    for model, group in effects.groupby("model"):
        absolute = _group_penalty(group, "absolute_recovery_error_pp")
        signed = _group_penalty(group, "signed_recovery_error_pp")
        if n_boot > 0:
            abs_boot = [
                _group_penalty(
                    group.iloc[rng.integers(0, len(group), len(group))],
                    "absolute_recovery_error_pp",
                )
                for _ in range(n_boot)
            ]
            sgn_boot = [
                _group_penalty(
                    group.iloc[rng.integers(0, len(group), len(group))],
                    "signed_recovery_error_pp",
                )
                for _ in range(n_boot)
            ]
            abs_ci = (
                float(np.nanpercentile(abs_boot, 2.5)),
                float(np.nanpercentile(abs_boot, 97.5)),
            )
            sgn_ci = (
                float(np.nanpercentile(sgn_boot, 2.5)),
                float(np.nanpercentile(sgn_boot, 97.5)),
            )
        else:
            abs_ci = (absolute, absolute)
            sgn_ci = (signed, signed)
        rows.append(
            {
                "model": model,
                "absolute_penalty": absolute,
                "signed_penalty": signed,
                "absolute_ci_low": abs_ci[0],
                "absolute_ci_high": abs_ci[1],
                "signed_ci_low": sgn_ci[0],
                "signed_ci_high": sgn_ci[1],
            }
        )
    return pd.DataFrame(rows)


def profile_recovery_correlations(
    effects: pd.DataFrame, profile: pd.DataFrame
) -> pd.DataFrame:
    """Per model x experiment: does the model's general profile error
    (its day-to-day answer accuracy gap) predict how badly it misses the
    human treatment effect? Also flags the mixed quadrants where a model
    looks accurate overall yet misses the treatment effect, or vice versa."""
    merged = effects.merge(
        profile[["model", "experiment", "profile_error"]],
        on=["model", "experiment"],
        how="inner",
    )
    median_profile = float(merged["profile_error"].median())
    merged["cell_recovery_error"] = merged.groupby(["model", "experiment"])[
        "absolute_recovery_error_pp"
    ].transform("mean")
    median_recovery = float(merged["cell_recovery_error"].median())
    rows: list[dict[str, object]] = []
    for (model, experiment), cell in merged.groupby(["model", "experiment"]):
        corr_signed = _safe_corr(
            cell["profile_error"], cell["signed_recovery_error_pp"]
        )
        corr_absolute = _safe_corr(
            cell["profile_error"], cell["absolute_recovery_error_pp"]
        )
        rows.append(
            {
                "model": model,
                "experiment": experiment,
                "corr_signed_recovery": corr_signed,
                "corr_absolute_contrast_error": corr_absolute,
                "mean_profile_error": float(cell["profile_error"].mean()),
                "mean_recovery_error": float(cell["cell_recovery_error"].mean()),
                "ci_low": corr_signed,
                "ci_high": corr_signed,
                "low_profile_high_recovery_error": bool(
                    float(cell["profile_error"].mean()) <= median_profile
                    and float(cell["cell_recovery_error"].mean()) > median_recovery
                ),
                "high_profile_low_recovery_error": bool(
                    float(cell["profile_error"].mean()) > median_profile
                    and float(cell["cell_recovery_error"].mean()) <= median_recovery
                ),
            }
        )
    return pd.DataFrame(rows)


def _safe_corr(a: pd.Series, b: pd.Series) -> float:
    """Pearson correlation that quietly returns NaN (not an error) when a
    cell has too few rows to correlate."""
    if len(a) < 2:
        return float("nan")
    return float(np.corrcoef(a.to_numpy(dtype=float), b.to_numpy(dtype=float))[0, 1])


def _loo_mae(values: pd.Series, labels: pd.Series) -> float:
    """Leave-one-out mean absolute error for one labelling: guess each
    row's miss by the average miss of the OTHER rows sharing its label,
    then average the absolute guessing errors."""
    errors: list[float] = []
    target = values.abs().to_numpy(dtype=float)
    lab = labels.to_numpy()
    for i in range(len(values)):
        same = lab == lab[i]
        same[i] = False
        guess = (
            float(target[same].mean())
            if same.any()
            else float(np.delete(target, i).mean())
        )
        errors.append(abs(guess - target[i]))
    return float(np.mean(errors))


def taxonomy_loo_comparison(
    effects: pd.DataFrame, value_column: str = "signed_recovery_error_pp"
) -> pd.DataFrame:
    """Score each way of labelling questions by how well it predicts the
    size of the miss (lower is better). Each label gets a bootstrap
    interval so near-ties are visible. The FINAL analysis calls this with
    value_column="attenuation_pp"; the default keeps the repaired
    behaviour."""
    return _final_taxonomy_loo_comparison(effects, value_column)


# FINAL orientation repair (TASK-2460). These names live in
# signed_effects_final.py; they are re-exported here so callers keep
# using the single `signed_effects` module.
from twin2k10.signed_effects_final import (  # noqa: E402,F401
    FINAL_CSV_COLUMNS,
    attenuation_gap,
    build_final_reference_table,
    build_signed_effects_final,
    count_models_with_positive_penalty,
    model_penalties_final,
    profile_fidelity_correlations,
    recovery_slopes_final,
    response_regimes_final,
    reversed_regime_gap,
    taxonomy_loo_comparison as _final_taxonomy_loo_comparison,  # noqa: F401
    validate_effects_final,  # noqa: F401
)


def taxonomy_pairwise_differences(tab: pd.DataFrame) -> pd.DataFrame:
    """The pairwise gaps between labellings' prediction errors, so the
    bake-off ranking can be read as differences rather than bare numbers."""
    rows: list[dict[str, object]] = []
    cats = list(tab["category"])
    for i in range(len(cats)):
        for j in range(i + 1, len(cats)):
            rows.append(
                {
                    "category_a": cats[i],
                    "category_b": cats[j],
                    "mae_difference": float(
                        tab.loc[tab["category"] == cats[i], "mae"].iloc[0]
                        - tab.loc[tab["category"] == cats[j], "mae"].iloc[0]
                    ),
                }
            )
    return cast(pd.DataFrame, pd.DataFrame(rows))
