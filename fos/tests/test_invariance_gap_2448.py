# RED tests for scripts/twin2k10/invariance_gap.py (TASK-2448).
#
# WHAT THIS FILE CHECKS, in plain words:
#   The module under test does not exist yet, so every test below fails
#   on the missing import — that is the expected RED reason.
#
#   The module must answer the owner's central claim with numbers: models
#   copy human treatment effects better when a manipulation changes the
#   objective information that matters for the decision, and they
#   SHRINK (attenuate) the human effect when the manipulation only
#   changes framing, anchors, or reference points.
#
#   Concretely it must: build a signed table comparing each model's
#   blinded effect with the humans' effect on the same scale; measure the
#   extra shrinkage on objective-equivalence tasks with bootstrap
#   intervals; sort each model effect into reversed / attenuated /
#   exaggerated; fit recovery lines (model effect vs human effect) per
#   group; compare predefined model groups; check which way of labelling
#   tasks best predicts where models miss; relate the profile error to
#   the recovery error; and write one CSV, six pictures, and a plain
#   text report answering the owner's eight questions in order with
#   confidence intervals, no p-values, and one final verdict.
#
# Everything runs offline on small fake numbers written here in the test
# file. No real run directory, codebook, or benchmarks file is read.
# Deterministic under fixed seeds. No p-values anywhere (CIs only).
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import invariance_gap as ig  # noqa: E402

# ---------------------------------------------------------------------------
# Synthetic fixtures: tiny fake contrasts, codebook, humans, profile errors.
# ---------------------------------------------------------------------------

MODELS = ["m1", "m2", "m3", "m4", "m5", "m6"]
EXPERIMENTS = [
    "anchoring_redwood", "anchoring_african", "fire_extinguisher",
    "seatbelt", "wta_wtp", "sunk_cost", "allais", "linda", "myside",
]
FAMILIES = {
    "anchoring": ["anchoring_redwood", "anchoring_african"],
    "proportion_dominance": ["fire_extinguisher", "seatbelt"],
    "valuation_reference": ["wta_wtp", "sunk_cost"],
    "probability_risk": ["allais"],
    "judgment_inference": ["linda", "myside"],
}
# Deliberate pattern: objective-equivalence experiments show big human
# effects that models copy; reference-context experiments show effects
# that models shrink toward zero.
OE_ON = {
    "anchoring_redwood", "anchoring_african", "fire_extinguisher",
    "seatbelt", "wta_wtp",
}
HUMAN_EFFECT = {
    "anchoring_redwood": 0.40, "anchoring_african": 0.30,
    "fire_extinguisher": 0.25, "seatbelt": 0.20, "wta_wtp": 0.35,
    "sunk_cost": 0.15, "allais": -0.10, "linda": 0.12, "myside": 0.08,
}
CODEBOOK = pd.DataFrame({
    "contrast": [f"c_{e}" for e in EXPERIMENTS],
    "experiment": EXPERIMENTS,
    "objective_equivalence": [1 if e in OE_ON else 0 for e in EXPERIMENTS],
    "reference_context": [0 if e in OE_ON else 1 for e in EXPERIMENTS],
    "explicit_numeric_change": [1 if e.startswith("anchoring") else 0
                                for e in EXPERIMENTS],
})


def _model_effect(model: str, experiment: str) -> float:
    """Fake blinded contrast: OE tasks recover well, others shrink."""
    h = HUMAN_EFFECT[experiment]
    if experiment in OE_ON:
        return h + (0.02 * MODELS.index(model) - 0.05)
    return 0.3 * h


def _contrasts_frame() -> pd.DataFrame:
    rows = []
    for m in MODELS:
        for e in EXPERIMENTS:
            rows.append({
                "model": m, "experiment": e, "contrast": f"c_{e}",
                "blinding": "blinded", "value": _model_effect(m, e),
            })
    # Unblinded rows exist and must never leak into the primary table.
    rows.append({"model": "m1", "experiment": "allais",
                 "contrast": "c_allais", "blinding": "unblinded",
                 "value": 99.0})
    return pd.DataFrame(rows)


def _effects_frame() -> pd.DataFrame:
    """A valid signed-effects table built by hand (no module under test)."""
    rows = []
    for m in MODELS:
        for e in EXPERIMENTS:
            h = HUMAN_EFFECT[e]
            sign = 1.0 if h >= 0 else -1.0
            mo = _model_effect(m, e)
            rows.append({
                "model": m, "experiment": e, "contrast": f"c_{e}",
                "human_effect_raw": h, "model_effect_raw": mo,
                "orientation_sign": sign,
                "human_effect_oriented": abs(h),
                "model_effect_oriented": sign * mo,
                "signed_recovery_error": mo - h,
                "objective_equivalence": int(e in OE_ON),
                "reference_context": int(e not in OE_ON),
                "paradigm_family":
                    next(f for f, es in FAMILIES.items() if e in es),
            })
    return pd.DataFrame(rows)


def _profile_errors() -> pd.DataFrame:
    """Fake per model-x-experiment profile errors (arm-mean distance)."""
    rows = []
    for m in MODELS:
        for e in EXPERIMENTS:
            rows.append({
                "model": m, "experiment": e,
                "error": 5.0 + 2.0 * (e not in OE_ON),
            })
    return pd.DataFrame(rows)


TAXONOMIES = {
    "objective_equivalence": pd.DataFrame({
        "experiment": EXPERIMENTS,
        "category": ["oe" if e in OE_ON else "other" for e in EXPERIMENTS],
    }),
    "preference_vs_belief": pd.DataFrame({
        "experiment": EXPERIMENTS,
        "category": ["belief" if e in OE_ON else "preference"
                     for e in EXPERIMENTS],
    }),
    "direct_vs_internal": pd.DataFrame({
        "experiment": EXPERIMENTS,
        "category": ["direct" if e not in OE_ON else "internal"
                     for e in EXPERIMENTS],
    }),
}

STRATA = {
    "older_vs_newer": pd.DataFrame({
        "model": MODELS,
        "stratum": ["older"] * 3 + ["newer"] * 3,
    }),
    "qwen3_vs_36_38": pd.DataFrame({
        "model": MODELS,
        "stratum": ["qwen3", "qwen3", "qwen3", "new", "new", "new"],
    }),
    "granite_8b_vs_30b": pd.DataFrame({
        "model": MODELS,
        "stratum": ["8b", "8b", "8b", "30b", "30b", "30b"],
    }),
    "gemma_variants": pd.DataFrame({
        "model": MODELS,
        "stratum": ["gemma_a", "gemma_a", "gemma_b",
                    "gemma_b", "gemma_a", "gemma_b"],
    }),
}

EXPECTED_COLUMNS = [
    "model", "experiment", "contrast", "human_effect_raw",
    "model_effect_raw", "orientation_sign", "human_effect_oriented",
    "model_effect_oriented", "signed_recovery_error",
    "objective_equivalence", "reference_context", "paradigm_family",
]

FIGURE_NAMES = [
    "signed_effect_recovery_by_task.png",
    "objective_equivalence_attenuation_by_model.png",
    "human_effect_recovery_slopes.png",
    "response_regime_by_task_type.png",
    "taxonomy_predictive_comparison.png",
    "profile_vs_treatment_recovery.png",
]

QUESTION_HEADINGS = [
    "Question 1", "Question 2", "Question 3", "Question 4",
    "Question 5", "Question 6", "Question 7", "Question 8",
]


# ---------------------------------------------------------------------------
# Contract 1 — signed effects table
# ---------------------------------------------------------------------------

def test_build_signed_effects_table_has_pinned_columns():
    table = ig.build_signed_effects(
        _contrasts_frame(), CODEBOOK, HUMAN_EFFECT)
    for col in EXPECTED_COLUMNS:
        assert col in table.columns, f"missing column {col}"


def test_signed_effects_use_blinded_rows_only():
    table = ig.build_signed_effects(
        _contrasts_frame(), CODEBOOK, HUMAN_EFFECT)
    m1 = table[(table["model"] == "m1") & (table["experiment"] == "allais")]
    assert float(m1["model_effect_raw"].iloc[0]) != 99.0, (
        "unblinded value leaked into the signed effects table")


def test_orientation_matches_human_sign():
    table = ig.build_signed_effects(
        _contrasts_frame(), CODEBOOK, HUMAN_EFFECT)
    neg = table[table["experiment"] == "allais"]
    assert (neg["orientation_sign"] == -1.0).all(), (
        "allais has a negative human effect; orientation sign must be -1")
    assert (neg["human_effect_oriented"] > 0).all()


def test_signed_recovery_error_is_model_minus_human():
    table = ig.build_signed_effects(
        _contrasts_frame(), CODEBOOK, HUMAN_EFFECT)
    recomputed = (table["model_effect_raw"] - table["human_effect_raw"])
    assert np.allclose(table["signed_recovery_error"], recomputed)


def test_signed_effects_join_codebook_features():
    table = ig.build_signed_effects(
        _contrasts_frame(), CODEBOOK, HUMAN_EFFECT)
    merged = table.merge(CODEBOOK[["experiment", "objective_equivalence"]],
                         on="experiment", suffixes=("", "_cb"))
    assert (merged["objective_equivalence"]
            == merged["objective_equivalence_cb"]).all()


# ---------------------------------------------------------------------------
# Contract 2 — objective-equivalence attenuation with bootstrap CIs
# ---------------------------------------------------------------------------

def test_oe_attenuation_is_positive_in_synthetic_data():
    result = ig.oe_attenuation(
        _effects_frame(), rng=np.random.default_rng(0), n_boot=200)
    assert result["delta_attenuation"] > 0, (
        "fixture shrinks non-OE effects, so OE-vs-non-OE gap must be "
        "positive — the test data assumption failed")


def test_oe_attenuation_ci_brackets_point_estimate():
    result = ig.oe_attenuation(
        _effects_frame(), rng=np.random.default_rng(0), n_boot=200)
    assert result["ci_low"] <= result["delta_attenuation"] <= result["ci_high"]


def test_oe_attenuation_is_deterministic_under_seed():
    a = ig.oe_attenuation(
        _effects_frame(), rng=np.random.default_rng(7), n_boot=100)
    b = ig.oe_attenuation(
        _effects_frame(), rng=np.random.default_rng(7), n_boot=100)
    assert a == b, "same seed must give identical bootstrap results"


def test_oe_attenuation_reports_per_model_with_family_bootstrap():
    result = ig.oe_attenuation(
        _effects_frame(), rng=np.random.default_rng(0), n_boot=200)
    assert set(result["per_model"]["model"]) == set(MODELS)
    for _, row in result["per_model"].iterrows():
        assert row["ci_low"] <= row["estimate"] <= row["ci_high"], (
            f"per-model CI for {row['model']} does not bracket estimate")


# ---------------------------------------------------------------------------
# Contract 3 — response regimes
# ---------------------------------------------------------------------------

def test_regimes_classify_reversed_attenuated_exaggerated():
    table = ig.response_regimes(_effects_frame())
    oe = table[table["objective_equivalence"] == 1]
    assert (oe["regime"] == "attenuated").all(), (
        "fixture OE effects are slightly below human; regime must be "
        "attenuated (0 <= M < H)")
    non_oe = table[table["objective_equivalence"] == 0]
    assert (non_oe["regime"] == "attenuated").all()
    assert set(table["regime"]) <= {"reversed", "attenuated", "exaggerated"}


def test_regimes_mark_negative_model_effects_as_reversed():
    effects = _effects_frame()
    effects.loc[effects["experiment"] == "allais",
                "model_effect_raw"] = -0.05
    table = ig.response_regimes(effects)
    allais = table[table["experiment"] == "allais"]
    assert (allais["regime"] == "reversed").all(), (
        "model effect below zero after orientation must be 'reversed'")


def test_regime_proportions_by_oe_group_with_cis():
    result = ig.regime_proportions(
        ig.response_regimes(_effects_frame()),
        rng=np.random.default_rng(0), n_boot=200)
    for group in (0, 1):
        part = result[result["objective_equivalence"] == group]
        assert len(part) == 3, "need one row per regime per OE group"
        assert ((part["ci_low"] <= part["proportion"])
                & (part["proportion"] <= part["ci_high"])).all()


# ---------------------------------------------------------------------------
# Contract 4 — recovery slopes
# ---------------------------------------------------------------------------

def test_primary_slope_recovers_approximately_one_on_fixture():
    fit = ig.recovery_slopes(
        _effects_frame(), level="primary",
        rng=np.random.default_rng(0), n_boot=200)
    assert fit["n"] == len(EXPERIMENTS), (
        "primary fit regresses contrast-level mean M on H, one point per "
        "contrast")
    assert 0.0 < fit["beta"] <= 1.2, "fixture slopes should be near 1 (OE)" \
        " or near 0.3 (non-OE), pooled somewhere below"
    assert fit["ci_low"] <= fit["beta"] <= fit["ci_high"]
    assert {"alpha", "beta", "ci_low", "ci_high", "n"} <= set(fit)


def test_secondary_slope_uses_model_intercepts():
    fit = ig.recovery_slopes(
        _effects_frame(), level="secondary",
        rng=np.random.default_rng(0), n_boot=200)
    assert fit["n"] == len(MODELS) * len(EXPERIMENTS)
    assert set(fit["model_intercepts"]) == set(MODELS), (
        "secondary fit must include one intercept per model")


def test_slope_difference_oe_minus_other_with_ci():
    diff = ig.slope_difference(
        _effects_frame(), rng=np.random.default_rng(0), n_boot=200)
    assert diff["beta_oe"] > diff["beta_other"], (
        "fixture OE slopes (~1) exceed non-OE slopes (~0.3)")
    assert diff["ci_low"] <= (diff["beta_oe"] - diff["beta_other"]) \
        <= diff["ci_high"]


# ---------------------------------------------------------------------------
# Contract 5 — model strata attenuation penalties
# ---------------------------------------------------------------------------

def test_strata_penalties_cover_all_predefined_strata():
    table = ig.strata_penalties(
        _effects_frame(), STRATA, rng=np.random.default_rng(0), n_boot=100)
    assert set(table["stratum_name"]) == set(STRATA)
    for _, row in table.iterrows():
        assert row["ci_low"] <= row["penalty"] <= row["ci_high"], (
            f"stratum {row['stratum_name']} CI must bracket its penalty")


def test_strata_penalty_is_positive_when_group_attenuates_more():
    effects = _effects_frame()
    # Make the 'older' stratum shrink non-OE effects to exactly zero.
    old = effects[(effects["model"].isin(MODELS[:3]))
                  & (effects["objective_equivalence"] == 0)]
    effects.loc[old.index, "model_effect_raw"] = 0.0
    table = ig.strata_penalties(
        effects, STRATA, rng=np.random.default_rng(0), n_boot=100)
    older = table[(table["stratum_name"] == "older_vs_newer")
                  & (table["stratum"] == "older")]
    assert (older["penalty"] > 0).all(), (
        "older models shrink non-OE effects to zero, penalty must be "
        "positive")


# ---------------------------------------------------------------------------
# Contract 6 — taxonomy leave-one-experiment-out comparison
# ---------------------------------------------------------------------------

def test_taxonomy_loo_returns_mae_and_ci_per_taxonomy():
    result = ig.taxonomy_loo(
        TAXONOMIES, _effects_frame(),
        rng=np.random.default_rng(0), n_boot=100)
    assert set(result["per_taxonomy"]["taxonomy"]) == set(TAXONOMIES)
    for _, row in result["per_taxonomy"].iterrows():
        assert row["ci_low"] <= row["mae"] <= row["ci_high"]


def test_taxonomy_loo_pairwise_differences_with_cis():
    result = ig.taxonomy_loo(
        TAXONOMIES, _effects_frame(),
        rng=np.random.default_rng(0), n_boot=100)
    pairs = set(zip(result["pairwise"]["taxonomy_a"],
                    result["pairwise"]["taxonomy_b"]))
    expected = {(a, b) for a in TAXONOMIES for b in TAXONOMIES if a < b}
    assert pairs == expected, "every taxonomy pair must be compared"
    for _, row in result["pairwise"].iterrows():
        assert row["ci_low"] <= row["difference"] <= row["ci_high"]


def test_taxonomy_loo_prefers_objective_equivalence_on_fixture():
    result = ig.taxonomy_loo(
        TAXONOMIES, _effects_frame(),
        rng=np.random.default_rng(0), n_boot=100)
    maes = dict(zip(result["per_taxonomy"]["taxonomy"],
                    result["per_taxonomy"]["mae"]))
    assert maes["objective_equivalence"] == min(maes.values()), (
        "fixture errors are driven by the OE split, so the OE taxonomy "
        "must predict held-out error best")


# ---------------------------------------------------------------------------
# Contract 7 — profile error vs recovery error
# ---------------------------------------------------------------------------

def test_profile_vs_recovery_correlations_with_cis():
    result = ig.profile_vs_recovery(
        _profile_errors(), _effects_frame(),
        rng=np.random.default_rng(0), n_boot=100)
    signed = result["correlation_signed"]
    absolute = result["correlation_absolute"]
    for corr in (signed, absolute):
        assert corr["ci_low"] <= corr["estimate"] <= corr["ci_high"]
    assert absolute["estimate"] > 0.5, (
        "fixture profile errors are large exactly where recovery errors "
        "are large, so the absolute correlation must be strongly positive")


def test_profile_vs_recovery_flags_quadrant_experiments():
    result = ig.profile_vs_recovery(
        _profile_errors(), _effects_frame(),
        rng=np.random.default_rng(0), n_boot=100)
    low_profile_high_error = set(
        result["low_profile_high_recovery_error"])
    high_profile_low_error = set(
        result["high_profile_low_recovery_error"])
    assert low_profile_high_error and high_profile_low_error, (
        "both quadrant lists must be non-empty on the fixture")
    assert not (low_profile_high_error & high_profile_low_error), (
        "an experiment cannot sit in both quadrants")


# ---------------------------------------------------------------------------
# Contract 8 — outputs: CSV, six figures, report
# ---------------------------------------------------------------------------

def test_write_outputs_creates_csv_six_figures_and_report(tmp_path):
    outputs = ig.write_outputs(
        contrasts=_contrasts_frame(), codebook=CODEBOOK,
        humans=HUMAN_EFFECT, profile_errors=_profile_errors(),
        taxonomies=TAXONOMIES, strata=STRATA,
        out_dir=tmp_path, seed=0)
    assert (tmp_path / "signed_contrast_effects.csv").exists()
    for name in FIGURE_NAMES:
        assert (tmp_path / name).exists(), f"missing figure {name}"
    report = tmp_path / "invariance_gap_analysis_report.txt"
    assert report.exists()
    text = report.read_text()
    positions = [text.find(q) for q in QUESTION_HEADINGS]
    assert all(p >= 0 for p in positions), (
        "report must answer the owner's eight questions")
    assert positions == sorted(positions), (
        "the eight questions must appear in order")


def test_write_outputs_report_avoids_p_value_language(tmp_path):
    ig.write_outputs(
        contrasts=_contrasts_frame(), codebook=CODEBOOK,
        humans=HUMAN_EFFECT, profile_errors=_profile_errors(),
        taxonomies=TAXONOMIES, strata=STRATA,
        out_dir=tmp_path, seed=0)
    text = (tmp_path
            / "invariance_gap_analysis_report.txt").read_text().lower()
    assert "p-value" not in text and "p value" not in text
    assert "significant" not in text, (
        "report must speak in confidence intervals, never significance")


def test_write_outputs_report_ends_with_one_verdict_line(tmp_path):
    ig.write_outputs(
        contrasts=_contrasts_frame(), codebook=CODEBOOK,
        humans=HUMAN_EFFECT, profile_errors=_profile_errors(),
        taxonomies=TAXONOMIES, strata=STRATA,
        out_dir=tmp_path, seed=0)
    lines = [ln for ln in (tmp_path
              / "invariance_gap_analysis_report.txt").read_text()
             .splitlines() if ln.strip()]
    verdicts = [ln for ln in lines
                if any(v in ln for v in ("Robust", "Suggestive", "Fragile"))]
    assert len(verdicts) == 1, (
        "exactly one final verdict line (Robust / Suggestive / Fragile)")
    assert lines[-1] == verdicts[0], "verdict must be the final line"


def test_write_outputs_csv_round_trips(tmp_path):
    ig.write_outputs(
        contrasts=_contrasts_frame(), codebook=CODEBOOK,
        humans=HUMAN_EFFECT, profile_errors=_profile_errors(),
        taxonomies=TAXONOMIES, strata=STRATA,
        out_dir=tmp_path, seed=0)
    back = pd.read_csv(tmp_path / "signed_contrast_effects.csv")
    for col in EXPECTED_COLUMNS:
        assert col in back.columns
    assert len(back) == len(MODELS) * len(EXPERIMENTS)
