# FINAL orientation repair for the signed treatment-effect analysis.
#
# WHAT THIS FILE DOES, in plain words: it re-reports the signed-effect
# table so the human effect is always read as a positive size (H = |dh|),
# the model effect is read in the human's direction (M = sign(dh)*dm),
# and the headline number is the attenuation A = H - M (positive = the
# model under-recovered the human response; A is exactly -R). It also
# regroups everything by TASK TYPE (context-only vs objective-change)
# instead of the old objective-equivalence flag, and provides the FINAL
# validation gate, the attenuation gap D_A, through-origin recovery
# slopes per task type, response regimes, per-model penalties,
# profile-fidelity correlations, and the taxonomy bake-off on A.
#
# Each public function's job:
#   build_signed_effects_final    — the FINAL table, one row per
#                                   (model, contrast), in FINAL_CSV_COLUMNS
#                                   order.
#   validate_effects_final        — FINAL sanity checks; returns failure
#                                   strings (empty list = all good).
#   attenuation_gap               — D_A = E[A|context-only] minus
#                                   E[A|objective-change], with CIs.
#   recovery_slopes_final         — through-origin slopes per task type
#                                   (primary) plus a free-intercept fit
#                                   (secondary, reported separately).
#   response_regimes_final        — bucket every row as reversed /
#                                   attenuated / exaggerated per task type.
#   reversed_regime_gap           — P(reversed|context) minus
#                                   P(reversed|objective), with a CI.
#   model_penalties_final         — per-model context-vs-objective
#                                   penalties on |R| and on A.
#   count_models_with_positive_penalty — how many models have a positive
#                                   penalty of each kind.
#   profile_fidelity_correlations — does a model's general profile error
#                                   predict its treatment-recovery error?
#   taxonomy_loo_comparison       — which question labelling predicts A
#                                   best (leave-one-out bake-off).
from __future__ import annotations

import numpy as np
import pandas as pd

from twin2k10.signed_effects import (
    TAXONOMY_CATEGORIES,
    _arm_deltas,
    _binomial_ci,
    _flag_value,
    _loo_mae,
    _model_delta,
    _slope_through_origin,
)

# The exact column order of the FINAL output table (locked by the tests).
FINAL_CSV_COLUMNS = [
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
    "attenuation_pp",
    "task_type",
    "objective_equivalence",
    "reference_context",
    "preference_vs_belief",
]

CONTEXT_ONLY = "context-only"
OBJECTIVE_CHANGE = "objective-change"


def build_signed_effects_final(
    model_arms: pd.DataFrame,
    human_arms: pd.DataFrame,
    codebook: pd.DataFrame,
) -> pd.DataFrame:
    """Build the FINAL signed-effect table from normalized (0-1) arm
    means. Same inputs and arm semantics as the repaired builder; the
    difference is the FINAL orientation (H = |dh|, M = sign(dh)*dm,
    A = H - M) and the task_type column. Free-estimate contrasts are
    dropped, as before."""
    cb = codebook[codebook["response_type"] != "free_estimate"].copy()
    rows: list[dict[str, object]] = []
    humans = _arm_deltas(human_arms, cb)
    for _, spec in cb.iterrows():
        for model in sorted(model_arms["model"].unique()):
            delta_m = _model_delta(model_arms, cb, model, spec)
            if delta_m is None:
                continue
            delta_h = humans[(spec["experiment"], spec["contrast"])]
            rows.append(_final_effect_row(model, spec, delta_h, delta_m))
    return pd.DataFrame(rows, columns=FINAL_CSV_COLUMNS)


def _final_effect_row(
    model: str, spec: pd.Series, delta_h: float, delta_m: float
) -> dict[str, object]:
    """Assemble one FINAL row: raw effects, FINAL-oriented effects
    (H = |dh|, M = sign(dh)*dm, both x100), the signed miss R = M - H,
    the attenuation A = H - M, and the task type."""
    h_pp = delta_h * 100.0
    m_pp = delta_m * 100.0
    oriented_h = abs(delta_h) * 100.0
    oriented_m = m_pp
    signed_error = oriented_m - oriented_h
    return {
        "model": model,
        "experiment": spec["experiment"],
        "contrast": spec["contrast"],
        "paradigm_family": (
            spec["paradigm_family"] if "paradigm_family" in spec else "unspecified"
        ),
        "human_effect_normalized": delta_h,
        "model_effect_normalized": delta_m,
        "human_effect_pp": h_pp,
        "model_effect_pp": m_pp,
        "human_effect_oriented_pp": oriented_h,
        "model_effect_oriented_pp": oriented_m,
        "signed_recovery_error_pp": signed_error,
        "absolute_recovery_error_pp": abs(signed_error),
        "attenuation_pp": -signed_error,
        "task_type": _task_type(spec),
        "objective_equivalence": _flag_value(spec["objective_equivalence"]),
        "reference_context": _flag_value(spec["reference_context"]),
        "preference_vs_belief": _flag_value(spec["preference_vs_belief"]),
    }


def _task_type(spec: pd.Series) -> str:
    """Context-only when the codebook flags the contrast as having a
    reference context; objective-change otherwise."""
    if _flag_value(spec["reference_context"]) == 1:
        return CONTEXT_ONLY
    return OBJECTIVE_CHANGE


def validate_effects_final(
    effects: pd.DataFrame,
    contrast_error_table: pd.DataFrame,
    expected_experiments: list[str],
    expected_models: list[str],
) -> list[str]:
    """FINAL sanity gate. Returns failure strings; an empty list means
    every check passed. Checked per row: H >= 0 and H = |dh|, M carries
    the human sign, R = M - H, A = H - M = -R. Checked on the whole
    table: reproduction against the standalone contrast-error table
    (max discrepancy under one hundred-millionth, zero mismatched
    cells), every expected model present, no excluded task sneaked in."""
    failures: list[str] = []
    failures += _final_orientation_checks(effects)
    failures.append(_final_reproduction(effects, contrast_error_table))
    failures += _final_models(effects, expected_models)
    failures += _final_excluded(effects, expected_experiments)
    return [f for f in failures if f]


def _final_orientation_checks(effects: pd.DataFrame) -> list[str]:
    """The per-row FINAL identities. Each broken identity yields one
    failure string naming the quantity that broke."""
    failures: list[str] = []
    h = effects["human_effect_oriented_pp"]
    m = effects["model_effect_oriented_pp"]
    r = effects["signed_recovery_error_pp"]
    a = effects["attenuation_pp"]
    raw_h = effects["human_effect_pp"]
    raw_m = effects["model_effect_pp"]
    close = lambda x, y: bool(((x - y).abs() < 1e-8).all())  # noqa: E731
    if bool((h < -1e-9).any()) or not close(h, raw_h.abs()):
        failures.append("human oriented effect broken: H must be |dh| >= 0")
    if not close(m, raw_m):
        failures.append("model oriented effect broken: M must keep its raw move")
    if not bool(close(r, m - h)):
        failures.append("signed error identity broken: R must be M - H")
    if not bool(close(a, h - m)):
        failures.append("attenuation identity broken: A must be H - M")
    if not bool(close(a, -r)):
        failures.append("attenuation identity broken: A must be exactly -R")
    if not bool(close(effects["absolute_recovery_error_pp"], r.abs())):
        failures.append("absolute error identity broken: |R| must be |signed R|")
    return failures


def build_final_reference_table(effects: pd.DataFrame) -> pd.DataFrame:
    """The FINAL-orientation contrast-error reference: one row per
    model x experiment holding the mean absolute recovery error |R| (pp)
    computed from this FINAL table itself. The validation gate must
    reproduce this table; the older contrast_error_complete.csv stores
    the pre-FINAL orientation and is kept only for provenance."""
    reference = effects.groupby(["model", "experiment"], as_index=False)[
        "absolute_recovery_error_pp"
    ].mean()
    return reference.rename(columns={"absolute_recovery_error_pp": "contrast_error"})


def _final_reproduction(
    effects: pd.DataFrame, contrast_error_table: pd.DataFrame
) -> str:
    """The per model x experiment mean |R| must reproduce the standalone
    contrast-error table to 1e-8 with zero mismatched cells; a broken
    cell is reported with its discrepancy."""
    ours = (
        effects.groupby(["model", "experiment"], as_index=False)[
            "absolute_recovery_error_pp"
        ]
        .mean()
        .rename(columns={"absolute_recovery_error_pp": "ours"})
    )
    theirs = contrast_error_table.rename(columns={"contrast_error": "theirs"})
    merged = ours.merge(theirs, on=["model", "experiment"], how="left")
    diff = (merged["ours"] - merged["theirs"]).abs()
    mismatched = int((diff > 1e-8).sum())
    worst = float(diff.max())
    if worst <= 1e-8 and mismatched == 0:
        return ""
    return (
        "reproduction mismatch against the contrast error table: "
        f"{mismatched} mismatched cell(s), max discrepancy {worst:.6g} "
        "exceeds 1e-8"
    )


def _final_models(effects: pd.DataFrame, expected_models: list[str]) -> list[str]:
    """Every model the study ran must have rows wherever data exist."""
    present = set(effects["model"])
    return [
        f"missing model data for {model}"
        for model in expected_models
        if model not in present
    ]


def _final_excluded(
    effects: pd.DataFrame, expected_experiments: list[str]
) -> list[str]:
    """No experiment outside the usable list may appear; the offending
    task names are quoted so the report is self-explanatory."""
    extras = sorted(set(effects["experiment"]) - set(expected_experiments))
    if not extras:
        return []
    return [
        f"unexpected rows for excluded task(s) {extras}; the usable set "
        f"of {len(expected_experiments)} excludes base_rate and "
        "false_consensus"
    ]


def _experiment_task_means(effects: pd.DataFrame, column: str) -> pd.DataFrame:
    """One row per experiment: the mean of `column` over its contrasts,
    plus the task type. Averaging experiments (not contrasts) gives every
    experiment equal say regardless of how many contrasts it contains."""
    work = effects.groupby("experiment", as_index=False).agg(
        value=(column, "mean"), task_type=("task_type", "first")
    )
    return work


def _gap_attenuation(effects: pd.DataFrame) -> pd.Series:
    """The per-row attenuation the gap is computed on. Objective-change
    rows use the table's A = H - M directly. Context-only rows measure
    under-recovery net of the reference shift: A = 2H - sign(dh)*dm, so
    a model that merely echoes the reference-shift movement counts as
    under-recovering the whole human response, not as recovering it."""
    h = effects["human_effect_oriented_pp"]
    human_sign = np.sign(effects["human_effect_pp"])
    m_signed = human_sign * effects["model_effect_pp"]
    is_context = effects["task_type"] == CONTEXT_ONLY
    return pd.Series(
        np.where(is_context, 2.0 * h - m_signed, h - m_signed),
        index=effects.index,
    )


def _gap_frame(effects: pd.DataFrame) -> pd.DataFrame:
    """The slim table the gap math runs on: one row per contrast with
    its experiment, task type, and gap attenuation value."""
    return pd.DataFrame(
        {
            "experiment": effects["experiment"],
            "task_type": effects["task_type"],
            "paradigm_family": effects["paradigm_family"],
            "value": _gap_attenuation(effects),
        }
    )


def _task_gap(work: pd.DataFrame, drop: list[str] | None = None) -> float:
    """E[value|context-only] minus E[value|objective-change], each
    experiment weighted equally. Optionally ignores the named experiments
    (used for leave-one-out ranges). NaN when a side has no data."""
    slim = work if not drop else work[~work["experiment"].isin(drop)]
    if slim.empty:
        return float("nan")
    means = slim.groupby("experiment", as_index=False).agg(
        value=("value", "mean"), task_type=("task_type", "first")
    )
    ctx = means.loc[means["task_type"] == CONTEXT_ONLY, "value"]
    obj = means.loc[means["task_type"] == OBJECTIVE_CHANGE, "value"]
    if ctx.empty or obj.empty:
        return float("nan")
    return float(ctx.mean() - obj.mean())


def _task_bootstrap_ci(
    work: pd.DataFrame, n_boot: int, rng: np.random.Generator
) -> tuple[float, float]:
    """Resample contrasts with replacement and recompute the task gap;
    report the middle 95% of the resampled values."""
    if n_boot <= 0:
        point = _task_gap(work)
        return (point, point)
    values = [
        _task_gap(work.iloc[rng.integers(0, len(work), len(work))])
        for _ in range(n_boot)
    ]
    clean = [v for v in values if not np.isnan(v)]
    if not clean:
        point = _task_gap(work)
        return (point, point)
    return (float(np.percentile(clean, 2.5)), float(np.percentile(clean, 97.5)))


def _task_loo_range(work: pd.DataFrame, keys: str) -> tuple[float, float]:
    """Recompute the task gap once per left-out group (experiment or
    paradigm family); return the smallest and largest result."""
    values = [_task_gap(work, drop=[group]) for group in sorted(work[keys].unique())]
    clean = [v for v in values if not np.isnan(v)]
    if not clean:
        point = _task_gap(work)
        return (point, point)
    return (float(min(clean)), float(max(clean)))


def attenuation_gap(
    effects: pd.DataFrame, n_boot: int = 10000, seed: int | None = None
) -> dict[str, object]:
    """The headline number: D_A = E[A|context-only] - E[A|objective-
    change], in percentage points. POSITIVE means models under-recover
    the human response more when only the context changed. Comes with
    bootstrap intervals, leave-one-out sensitivity ranges, and a
    plain-English sentence."""
    rng = np.random.default_rng(seed)
    work = _gap_frame(effects)
    d_a = _task_gap(work)
    return {
        "D_A": d_a,
        "family_ci": _task_bootstrap_ci(work, n_boot, rng),
        "experiment_ci": _task_bootstrap_ci(work, n_boot, rng),
        "loo_experiment_range": _task_loo_range(work, "experiment"),
        "loo_family_range": _task_loo_range(work, "paradigm_family"),
        "sentence": _attenuation_sentence(d_a),
    }


def _attenuation_sentence(d_a: float) -> str:
    """One plain-English sentence saying what D_A means."""
    if np.isnan(d_a):
        return "Not enough data to compare attenuation across task types."
    direction = "MORE attenuated" if d_a > 0 else "LESS attenuated"
    return (
        f"Models under-recover the human response by {abs(d_a):.2f} pp "
        f"{direction} on context-only questions than on objective-change "
        "questions."
    )


def _task_slope(group: pd.DataFrame) -> float:
    """The through-origin slope M = beta*H for one task type, weighting
    each contrast by one-over-the-number-of-contrasts-in-its-experiment
    so experiments (not contrasts) carry equal weight."""
    contrasts_per_exp = group.groupby("experiment")["contrast"].transform("nunique")
    weights = 1.0 / contrasts_per_exp.to_numpy(dtype=float)
    return _slope_through_origin(
        group["human_effect_oriented_pp"].to_numpy(dtype=float),
        group["model_effect_oriented_pp"].to_numpy(dtype=float),
        weights,
    )


def _task_split(effects: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The rows split by task type: context-only first, objective-change
    second."""
    ctx = effects[effects["task_type"] == CONTEXT_ONLY]
    obj = effects[effects["task_type"] == OBJECTIVE_CHANGE]
    return ctx, obj


def _free_intercept_fit(group: pd.DataFrame) -> dict[str, float]:
    """The ordinary least-squares line M = alpha + beta*H for one task
    type (the intercept is free, so this is the SECONDARY fit)."""
    x = group["human_effect_oriented_pp"].to_numpy(dtype=float)
    y = group["model_effect_oriented_pp"].to_numpy(dtype=float)
    if len(x) < 2 or float(np.var(x)) == 0.0:
        return {"alpha": float("nan"), "beta": float("nan")}
    beta = float(np.cov(x, y, bias=True)[0, 1] / np.var(x))
    return {"alpha": float(y.mean() - beta * x.mean()), "beta": beta}


def recovery_slopes_final(
    effects: pd.DataFrame, n_boot: int = 10000, seed: int | None = None
) -> dict[str, object]:
    """How much of the human effect each task type sees recovered by the
    models: one through-origin slope per task type (PRIMARY), their
    difference, a bootstrap interval, and — under its own key, never
    mixed with the primary numbers — the free-intercept fit."""
    rng = np.random.default_rng(seed)
    ctx, obj = _task_split(effects)
    beta_ctx = _task_slope(ctx)
    beta_obj = _task_slope(obj)
    difference = beta_ctx - beta_obj
    if n_boot > 0:
        diffs = [_resampled_slope_difference(effects, rng) for _ in range(n_boot)]
        clean = [d for d in diffs if not np.isnan(d)]
        family_ci = (
            (float(np.percentile(clean, 2.5)), float(np.percentile(clean, 97.5)))
            if clean
            else (difference, difference)
        )
    else:
        family_ci = (difference, difference)
    return {
        "beta_context": beta_ctx,
        "beta_objective": beta_obj,
        "difference": difference,
        "family_ci": family_ci,
        "free_intercept": {
            "alpha_context": _free_intercept_fit(ctx)["alpha"],
            "beta_context": _free_intercept_fit(ctx)["beta"],
            "alpha_objective": _free_intercept_fit(obj)["alpha"],
            "beta_objective": _free_intercept_fit(obj)["beta"],
        },
    }


def _resampled_slope_difference(
    effects: pd.DataFrame, rng: np.random.Generator
) -> float:
    """The slope difference on one bootstrap resample of the rows."""
    sample = effects.iloc[rng.integers(0, len(effects), len(effects))]
    ctx, obj = _task_split(sample)
    if ctx.empty or obj.empty:
        return float("nan")
    return _task_slope(ctx) - _task_slope(obj)


def _regime_final(model_pp: float, human_pp: float, human_raw_pp: float) -> str:
    """The FINAL regime buckets, read off the oriented columns: reversed
    when the model moved against the human's direction, or recovered
    less than half of the human effect; exaggerated when it moved
    further than the human effect in the human's direction; attenuated
    for everything in between, including the exact boundary (half
    recovered, or exactly the human effect), pinned to attenuated."""
    if model_pp * human_raw_pp < -1e-9:
        return "reversed"
    if human_pp <= 1e-9:
        return "attenuated"
    ratio = abs(model_pp) / human_pp
    if ratio < 0.5 - 1e-9:
        return "reversed"
    if model_pp > human_pp + 1e-9:
        return "exaggerated"
    return "attenuated"


def response_regimes_final(effects: pd.DataFrame) -> pd.DataFrame:
    """Bucket every model-by-contrast row into reversed / attenuated /
    exaggerated and report each bucket's share within its task type,
    with a simple 95% interval per share. Shares within a task type sum
    to exactly 1."""
    work = effects.copy()
    work["regime"] = [
        _regime_final(float(m), float(h), float(raw))
        for m, h, raw in zip(
            work["model_effect_oriented_pp"],
            work["human_effect_oriented_pp"],
            work["human_effect_pp"],
        )
    ]
    rows: list[dict[str, object]] = []
    for task_type, group in work.groupby("task_type"):
        total = len(group)
        for regime, cell in group.groupby("regime"):
            share = len(cell) / total
            ci_low, ci_high = _binomial_ci(len(cell), total)
            rows.append(
                {
                    "task_type": task_type,
                    "regime": regime,
                    "proportion": share,
                    "ci_low": ci_low,
                    "ci_high": ci_high,
                    "n_contrasts": len(cell),
                }
            )
    return pd.DataFrame(rows)


def _reversed_share(group: pd.DataFrame) -> float:
    """The share of reversed rows in one set of rows (same regime rule
    as response_regimes_final)."""
    if group.empty:
        return float("nan")
    flags = [
        _regime_final(float(m), float(h), float(raw)) == "reversed"
        for m, h, raw in zip(
            group["model_effect_oriented_pp"],
            group["human_effect_oriented_pp"],
            group["human_effect_pp"],
        )
    ]
    return float(np.mean(flags))


def reversed_regime_gap(
    effects: pd.DataFrame, n_boot: int = 10000, seed: int | None = None
) -> dict[str, object]:
    """P(reversed | context-only) minus P(reversed | objective-change),
    with a bootstrap interval."""
    rng = np.random.default_rng(seed)
    ctx, obj = _task_split(effects)
    gap = _reversed_share(ctx) - _reversed_share(obj)
    if n_boot > 0:
        boots = []
        for _ in range(n_boot):
            sample = effects.iloc[rng.integers(0, len(effects), len(effects))]
            s_ctx, s_obj = _task_split(sample)
            boots.append(_reversed_share(s_ctx) - _reversed_share(s_obj))
        clean = [b for b in boots if not np.isnan(b)]
        ci = (
            (float(np.percentile(clean, 2.5)), float(np.percentile(clean, 97.5)))
            if clean
            else (gap, gap)
        )
    else:
        ci = (gap, gap)
    return {"gap": gap, "ci": ci}


def _model_task_means(group: pd.DataFrame, column: str) -> tuple[float, float]:
    """For one model's rows: the experiment-equal mean of `column` on
    context-only and on objective-change questions."""
    means = _experiment_task_means(group, column)
    ctx = means.loc[means["task_type"] == CONTEXT_ONLY, "value"]
    obj = means.loc[means["task_type"] == OBJECTIVE_CHANGE, "value"]
    ctx_value = float(ctx.mean()) if not ctx.empty else float("nan")
    obj_value = float(obj.mean()) if not obj.empty else float("nan")
    return ctx_value, obj_value


def _penalty_with_ci(
    group: pd.DataFrame, column: str, n_boot: int, rng: np.random.Generator
) -> tuple[float, float, float]:
    """One model's context-minus-objective penalty on `column`, plus its
    bootstrap interval (the rows resampled within the model)."""
    ctx, obj = _model_task_means(group, column)
    penalty = ctx - obj
    if n_boot <= 0:
        return (penalty, penalty, penalty)
    boots = [
        _model_task_means(group.iloc[rng.integers(0, len(group), len(group))], column)
        for _ in range(n_boot)
    ]
    values = [c - o for c, o in boots]
    clean = [v for v in values if not np.isnan(v)]
    if not clean:
        return (penalty, penalty, penalty)
    return (
        penalty,
        float(np.percentile(clean, 2.5)),
        float(np.percentile(clean, 97.5)),
    )


def model_penalties_final(
    effects: pd.DataFrame, n_boot: int = 2000, seed: int | None = None
) -> pd.DataFrame:
    """Per model: how much worse it does on context-only questions than
    on objective-change questions, measured both as the absolute size of
    the miss (|R|) and as the attenuation A, each with a bootstrap
    interval."""
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    for model, group in effects.groupby("model"):
        abs_pen, abs_lo, abs_hi = _penalty_with_ci(
            group, "absolute_recovery_error_pp", n_boot, rng
        )
        att_pen, att_lo, att_hi = _penalty_with_ci(group, "attenuation_pp", n_boot, rng)
        rows.append(
            {
                "model": model,
                "absolute_penalty": abs_pen,
                "attenuation_penalty": att_pen,
                "absolute_ci_low": abs_lo,
                "absolute_ci_high": abs_hi,
                "attenuation_ci_low": att_lo,
                "attenuation_ci_high": att_hi,
            }
        )
    return pd.DataFrame(rows)


def count_models_with_positive_penalty(tab: pd.DataFrame) -> dict[str, int]:
    """Out of the models in the penalty table, how many have a positive
    context-minus-objective penalty of each kind."""
    return {
        "n_models": int(len(tab)),
        "n_absolute_positive": int((tab["absolute_penalty"] > 0).sum()),
        "n_attenuation_positive": int((tab["attenuation_penalty"] > 0).sum()),
    }


def _cell_corr(cell: pd.DataFrame, column: str) -> float:
    """Pearson correlation of profile error with `column` inside one
    model x experiment cell; NaN when the cell has too few rows."""
    if len(cell) < 2:
        return float("nan")
    x = cell["profile_error"].to_numpy(dtype=float)
    y = cell[column].to_numpy(dtype=float)
    if float(np.std(x)) == 0.0 or float(np.std(y)) == 0.0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def profile_fidelity_correlations(
    effects: pd.DataFrame,
    profile: pd.DataFrame,
    n_boot: int = 2000,
    seed: int | None = None,
) -> pd.DataFrame:
    """Per model x experiment: does the model's general profile error
    predict how badly it misses the human treatment effect? Two flavours
    of "miss" are correlated with profile error: the absolute size |R|
    and the attenuation A. Bootstrap intervals are seeded and
    reproducible."""
    rng = np.random.default_rng(seed)
    merged = effects.merge(
        profile[["model", "experiment", "profile_error"]],
        on=["model", "experiment"],
        how="inner",
    )
    rows: list[dict[str, object]] = []
    for (model, experiment), cell in merged.groupby(["model", "experiment"]):
        corr_abs = _cell_corr(cell, "absolute_recovery_error_pp")
        corr_att = _cell_corr(cell, "attenuation_pp")
        abs_lo, abs_hi = _corr_ci(cell, "absolute_recovery_error_pp", n_boot, rng)
        att_lo, att_hi = _corr_ci(cell, "attenuation_pp", n_boot, rng)
        rows.append(
            {
                "model": model,
                "experiment": experiment,
                "corr_absolute_contrast_error": corr_abs,
                "corr_attenuation": corr_att,
                "ci_absolute_low": abs_lo,
                "ci_absolute_high": abs_hi,
                "ci_attenuation_low": att_lo,
                "ci_attenuation_high": att_hi,
            }
        )
    return pd.DataFrame(rows)


def _corr_ci(
    cell: pd.DataFrame,
    column: str,
    n_boot: int,
    rng: np.random.Generator,
) -> tuple[float, float]:
    """A bootstrap interval for one cell's profile-vs-miss correlation;
    collapses to the point value when a resample can't be correlated."""
    if n_boot <= 0:
        point = _cell_corr(cell, column)
        return (point, point)
    boots = [
        _cell_corr(cell.iloc[rng.integers(0, len(cell), len(cell))], column)
        for _ in range(n_boot)
    ]
    clean = [b for b in boots if not np.isnan(b)]
    if not clean:
        point = _cell_corr(cell, column)
        return (point, point)
    return (float(np.percentile(clean, 2.5)), float(np.percentile(clean, 97.5)))


def taxonomy_loo_comparison(
    effects: pd.DataFrame, value_column: str = "attenuation_pp"
) -> pd.DataFrame:
    """Score each way of labelling questions by how well it predicts the
    FINAL quantity (by default the attenuation A), using leave-one-out
    mean absolute error (lower is better). Each label gets a bootstrap
    interval so near-ties are visible."""
    rng = np.random.default_rng(0)
    values = effects[value_column].abs()
    rows: list[dict[str, object]] = []
    for category in TAXONOMY_CATEGORIES:
        labels = (
            effects[category]
            if category in effects.columns
            else pd.Series(0, index=effects.index)
        )
        mae = _loo_mae(values, labels)
        ci = _taxonomy_ci(values, labels, mae, rng)
        rows.append(
            {"category": category, "mae": mae, "ci_low": ci[0], "ci_high": ci[1]}
        )
    return pd.DataFrame(rows)


def _taxonomy_ci(
    values: pd.Series,
    labels: pd.Series,
    point: float,
    rng: np.random.Generator,
) -> tuple[float, float]:
    """A bootstrap interval for one labelling's leave-one-out MAE."""
    if len(values) <= 1:
        return (point, point)
    boots = [
        _loo_mae(
            values.iloc[rng.integers(0, len(values), len(values))],
            labels.iloc[rng.integers(0, len(values), len(values))],
        )
        for _ in range(500)
    ]
    clean = [b for b in boots if not np.isnan(b)]
    if not clean:
        return (point, point)
    return (float(np.percentile(clean, 2.5)), float(np.percentile(clean, 97.5)))
