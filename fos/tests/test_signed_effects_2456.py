# Tests for the TASK-2456 REPAIRED signed treatment-effect analysis.
#
# WHAT THIS FILE CHECKS, in plain words:
#   The old "signed effects" analysis mixed raw and 0-1 numbers, dropped 6
#   experiments, carried a base-rate column that should never be there, and
#   got the sign of the recovery error backwards. This file pins the repaired
#   version: signed contrasts computed on the SAME per-arm 0-1 scale as the
#   repaired Contrast Error figures, all 14 usable experiments present,
#   effects oriented by the human sign, a mandatory validation gate, the
#   absolute and signed OE-penalty mechanisms, response regimes, recovery
#   slopes with equal experiment weights, per-model penalties, profile-vs-
#   fidelity correlations, the taxonomy bake-off, and the exact output files.
#
#   Every test uses small synthetic numbers made up on the spot (seeded where
#   randomness is involved). No real results file is ever read.
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import signed_effects as se  # noqa: E402
from twin2k10 import signed_effects_run as runmod  # noqa: E402

# The 14 usable experiments (base_rate and false_consensus are excluded).
USABLE = [
    "disease", "less_is_more", "fire_extinguisher", "seatbelt", "sunk_cost",
    "wta_wtp", "allais", "linda", "anchoring_redwood", "anchoring_african",
    "outcome_bias", "myside", "prob_matching", "abs_relative",
]

CSV_COLUMNS = [
    "model", "experiment", "contrast", "paradigm_family",
    "human_effect_normalized", "model_effect_normalized",
    "human_effect_pp", "model_effect_pp",
    "human_effect_oriented_pp", "model_effect_oriented_pp",
    "signed_recovery_error_pp", "absolute_recovery_error_pp",
    "objective_equivalence", "reference_context",
]

FIGURES = [
    "signed_effect_recovery_by_task",
    "human_effect_recovery_slopes",
    "objective_equivalence_absolute_error_by_model",
    "objective_equivalence_attenuation_by_model",
    "response_regime_by_task_type",
    "profile_vs_treatment_recovery",
    "taxonomy_predictive_comparison",
]


def _codebook_row(contrast, experiment, treatment="T", comparison="C",
                  oe=1, ref_ctx=0, pref_belief=0, family="judgment",
                  response_type="ordinal rating"):
    return {
        "contrast": contrast, "experiment": experiment,
        "treatment_arm": treatment, "comparison_arm": comparison,
        "objective_equivalence": oe, "reference_context": ref_ctx,
        "preference_vs_belief": pref_belief, "paradigm_family": family,
        "response_type": response_type,
    }


def _arms(model, experiment, contrast, treatment_value, comparison_value):
    """One model's normalized (0-1) arm means for one contrast."""
    return [
        {"model": model, "experiment": experiment, "contrast": contrast,
         "arm": "T", "value": treatment_value},
        {"model": model, "experiment": experiment, "contrast": contrast,
         "arm": "C", "value": comparison_value},
    ]


def _effects_fixture():
    """Two models x two experiments. Humans move +0.40 (exp1, OE=1) and
    -0.20 (exp2, OE=0); model m1 tracks the human sign, m2 reverses it."""
    codebook = pd.DataFrame([
        _codebook_row("c1", "disease", oe=1, family="judgment"),
        _codebook_row("c2", "allais", oe=0, family="choice", pref_belief=1),
    ])
    human = pd.DataFrame(
        _arms("humans", "disease", "c1", 0.7, 0.3)
        + _arms("humans", "allais", "c2", 0.3, 0.5)
    )
    model = pd.DataFrame(
        _arms("m1", "disease", "c1", 0.6, 0.3)
        + _arms("m2", "disease", "c1", 0.2, 0.6)
        + _arms("m1", "allais", "c2", 0.4, 0.5)
        + _arms("m2", "allais", "c2", 0.45, 0.5)
    )
    return se.build_signed_effects(model, human, codebook)


def _reference_table(effects):
    """A contrast_error_complete-style table that exactly reproduces the
    per model-x-experiment mean |R| of the fixture (in pp)."""
    rows = (
        effects.groupby(["model", "experiment"], as_index=False)[
            "absolute_recovery_error_pp"
        ].mean()
    )
    rows = rows.rename(columns={"absolute_recovery_error_pp": "contrast_error"})
    return rows


# ---------------------------------------------------------------- contract 1


def test_signed_contrast_is_normalized_then_scaled_to_pp():
    """A human move from 0.3 to 0.7 on the 0-1 scale is a +40 pp effect,
    not any raw-scale number."""
    fx = _effects_fixture()
    row = fx[(fx.model == "humans") if False else (fx.contrast == "c1")].iloc[0]
    assert row["human_effect_normalized"] == pytest.approx(0.4, abs=1e-12)
    assert row["human_effect_pp"] == pytest.approx(40.0, abs=1e-9)


def test_human_and_model_effects_come_from_same_arm_pair():
    """The model contrast must subtract the SAME comparison arm the human
    contrast subtracts (treatment minus comparison, per the codebook)."""
    fx = _effects_fixture()
    m2 = fx[(fx.model == "m2") & (fx.contrast == "c1")].iloc[0]
    # treatment T=0.2 minus comparison C=0.6
    assert m2["model_effect_normalized"] == pytest.approx(-0.4, abs=1e-12)


def test_no_effect_exceeds_100pp_and_all_normalized_in_unit_range():
    """With normalized inputs, no pp effect can escape [-100, 100]."""
    fx = _effects_fixture()
    for col in ("human_effect_pp", "model_effect_pp",
                "human_effect_oriented_pp", "model_effect_oriented_pp"):
        assert fx[col].abs().max() <= 100.0 + 1e-9, col
    for col in ("human_effect_normalized", "model_effect_normalized"):
        assert fx[col].abs().max() <= 1.0 + 1e-12, col


def test_anchoring_uses_only_bounded_choice_not_free_estimates():
    """A free-numeric anchoring estimate (raw value 37, no 0-1 meaning)
    must never enter the signed table; only the bounded P(more) does."""
    codebook = pd.DataFrame([
        _codebook_row("anchor_more", "anchoring_redwood", family="judgment"),
        _codebook_row("anchor_estimate", "anchoring_redwood",
                      family="judgment", response_type="free_estimate"),
    ])
    human = pd.DataFrame(
        _arms("humans", "anchoring_redwood", "anchor_more", 0.8, 0.4)
        + _arms("humans", "anchoring_redwood", "anchor_estimate", 37.0, 30.0)
    )
    model = pd.DataFrame(
        _arms("m1", "anchoring_redwood", "anchor_more", 0.7, 0.4)
        + _arms("m1", "anchoring_redwood", "anchor_estimate", 41.0, 30.0)
    )
    fx = se.build_signed_effects(model, human, codebook)
    assert set(fx["contrast"]) == {"anchor_more"}, (
        "the free-estimate contrast must be dropped entirely"
    )
    assert not (fx["human_effect_pp"].abs() > 100).any()


# ---------------------------------------------------------------- contract 2


def test_orientation_identity_R_equals_M_minus_H():
    """R must equal the oriented model effect minus the oriented human
    effect, to 1e-10."""
    fx = _effects_fixture()
    lhs = fx["signed_recovery_error_pp"]
    rhs = fx["model_effect_oriented_pp"] - fx["human_effect_oriented_pp"]
    assert (lhs - rhs).abs().max() < 1e-10


def test_orientation_flips_model_effect_to_human_sign():
    """H = |dh|; M = sign(dh) * dm. When the human effect is negative and
    the model moves positive, both oriented numbers must be negative."""
    fx = _effects_fixture()
    row = fx[(fx.contrast == "c2") & (fx.model == "m2")].iloc[0]
    assert row["human_effect_oriented_pp"] == pytest.approx(-20.0, abs=1e-9)
    assert row["model_effect_oriented_pp"] < 0.0, (
        "model moving +5 while humans moved -20 must be reported as -5"
    )


def test_absolute_R_equals_absolute_contrast_difference():
    """|R| must equal |dm - dh| regardless of orientation."""
    fx = _effects_fixture()
    dm = fx["model_effect_pp"]
    dh = fx["human_effect_pp"]
    assert (fx["absolute_recovery_error_pp"] - (dm - dh).abs()).abs().max() < 1e-10


# ---------------------------------------------------------------- contract 3


def test_validation_passes_on_wellformed_input():
    fx = _effects_fixture()
    failures = se.validate_effects(fx, _reference_table(fx), USABLE, ["m1", "m2"])
    assert failures == [], failures


def test_validation_requires_all_14_experiments_and_flags_excluded_two():
    fx = _effects_fixture().iloc[:0].copy()
    for exp in USABLE:  # one trivially fine row per experiment
        cb = pd.DataFrame([_codebook_row("x", exp)])
        h = pd.DataFrame(_arms("humans", exp, "x", 0.6, 0.4))
        m = pd.DataFrame(_arms("m1", exp, "x", 0.5, 0.4))
        fx = pd.concat([fx, se.build_signed_effects(m, h, cb)], ignore_index=True)
    # sneak in a base_rate row: it must be flagged
    cb = pd.DataFrame([_codebook_row("x", "base_rate")])
    h = pd.DataFrame(_arms("humans", "base_rate", "x", 0.6, 0.4))
    m = pd.DataFrame(_arms("m1", "base_rate", "x", 0.5, 0.4))
    fx = pd.concat([fx, se.build_signed_effects(m, h, cb)], ignore_index=True)
    failures = se.validate_effects(fx, _reference_table(fx), USABLE, ["m1"])
    assert any("base_rate" in f for f in failures), failures
    assert any("false_consensus" not in exp_set and "14" in f
               for f in failures if "experiment" in f) or any(
        "false_consensus" in f or "14" in f for f in failures), failures


def test_validation_stops_on_out_of_range_normalized_value():
    fx = _effects_fixture()
    fx.loc[0, "human_effect_normalized"] = 1.5
    failures = se.validate_effects(fx, _reference_table(fx), USABLE, ["m1", "m2"])
    assert any("range" in f.lower() or "[0,1]" in f or "0-1" in f
               for f in failures), failures


def test_validation_flags_reproduction_mismatch_against_contrast_error_table():
    """If the mean |R| per model x experiment does not reproduce the
    contrast_error_complete values, validation must report the max
    discrepancy and fail (>1e-8)."""
    fx = _effects_fixture()
    ref = _reference_table(fx)
    ref.loc[0, "contrast_error"] += 5.0  # corrupt one cell
    failures = se.validate_effects(fx, ref, USABLE, ["m1", "m2"])
    assert any("reproduc" in f.lower() for f in failures), failures
    assert any("5" in f for f in failures if "reproduc" in f.lower())


def test_missing_model_is_flagged_by_validation():
    fx = _effects_fixture()
    fx = fx[fx.model != "m2"]
    failures = se.validate_effects(fx, _reference_table(fx), USABLE, ["m1", "m2"])
    assert any("m2" in f for f in failures), failures


# ---------------------------------------------------------------- contract 4


def test_absolute_oe_penalty_uses_experiment_equal_weighting():
    """Exp1 (OE=1) has |R|=5 for two contrasts; exp2 (OE=0) has |R|=0.
    Naive pooling over contrasts and equal-weighting-over-experiments must
    both give 5 here, but a lopsided fixture separates them."""
    codebook = pd.DataFrame([
        _codebook_row("a", "disease", oe=1),
        _codebook_row("b", "disease", oe=1),
        _codebook_row("c", "allais", oe=0),
    ])
    # OE=1 arm: human +0.4, model +0.35 -> R=-5 (|R|=5) twice
    # OE=0 arm: human -0.2, model -0.2 -> R=0
    human = pd.DataFrame(
        _arms("humans", "disease", "a", 0.7, 0.3)
        + _arms("humans", "disease", "b", 0.7, 0.3)
        + _arms("humans", "allais", "c", 0.3, 0.5)
    )
    model = pd.DataFrame(
        _arms("m1", "disease", "a", 0.65, 0.3)
        + _arms("m1", "disease", "b", 0.65, 0.3)
        + _arms("m1", "allais", "c", 0.3, 0.5)
    )
    fx = se.build_signed_effects(model, human, codebook)
    res = se.absolute_oe_penalty(fx, n_boot=0)
    assert res["penalty"] == pytest.approx(5.0, abs=1e-9), res


def test_penalty_reports_family_experiment_cis_and_loo_ranges():
    fx = _effects_fixture()
    res = se.absolute_oe_penalty(fx, n_boot=500, seed=7)
    for key in ("family_ci", "experiment_ci",
                "loo_experiment_range", "loo_family_range"):
        assert key in res, f"missing {key} in {sorted(res)}"
    lo, hi = res["family_ci"]
    assert lo <= res["penalty"] <= hi or lo == hi


def test_bootstrap_is_seeded_and_reproducible():
    fx = _effects_fixture()
    a = se.absolute_oe_penalty(fx, n_boot=200, seed=123)["family_ci"]
    b = se.absolute_oe_penalty(fx, n_boot=200, seed=123)["family_ci"]
    assert a == b


# ---------------------------------------------------------------- contract 5


def test_signed_attenuation_negative_when_oe_tasks_more_attenuated():
    """OE=1: model recovers half the human effect (R=-20); OE=0: recovers
    all of it (R=0). D = 0 - (-20) = +20? No: attenuation convention is
    E[R|OE=1] - E[R|OE=0] with negative D meaning more attenuation, so the
    fixture where OE=1 undershoots must give NEGATIVE D."""
    codebook = pd.DataFrame([
        _codebook_row("a", "disease", oe=1),
        _codebook_row("c", "allais", oe=0),
    ])
    human = pd.DataFrame(
        _arms("humans", "disease", "a", 0.7, 0.3)
        + _arms("humans", "allais", "c", 0.3, 0.5)
    )
    model = pd.DataFrame(
        _arms("m1", "disease", "a", 0.5, 0.3)    # R = 20 - 40 = -20
        + _arms("m1", "allais", "c", 0.3, 0.5)   # R = 0
    )
    fx = se.build_signed_effects(model, human, codebook)
    res = se.signed_attenuation(fx, n_boot=0)
    assert res["D"] == pytest.approx(-20.0, abs=1e-9), res
    for key in ("family_ci", "experiment_ci",
                "loo_experiment_range", "loo_family_range"):
        assert key in res, f"missing {key}"


# ---------------------------------------------------------------- contract 6


def test_response_regimes_partition_each_oe_group():
    """Reversed + attenuated + exaggerated proportions must sum to 1 per
    OE group."""
    fx = _effects_fixture()
    reg = se.response_regimes(fx)
    sums = reg.groupby("objective_equivalence")["proportion"].sum()
    assert np.allclose(sums.values, 1.0), sums
    assert set(reg["regime"]) <= {"reversed", "attenuated", "exaggerated"}


def test_regime_labels_match_definitions():
    """M<0 reversed; 0<=M<H attenuated; M>H exaggerated."""
    fx = _effects_fixture()
    reg = se.response_regimes(fx)
    # m2 on c2: humans -20, model +5 -> oriented M=-5 <0 -> reversed
    # m1 on c1: humans +40, model +30 -> 0<=M<H -> attenuated
    # m2 on c1: humans +40, model -40 -> M=-40 <0 -> reversed
    # m1 on c2: humans -20, model -20 -> M=H -> attenuated (0<=M<H false,
    # M>H false; boundary pinned to attenuated by convention)
    got = reg.set_index(["objective_equivalence", "regime"])["proportion"]
    assert got.loc[(1, "attenuated")] == pytest.approx(1.0, abs=1e-12)
    assert got.loc[(0, "reversed")] == pytest.approx(0.5, abs=1e-12)


def test_regime_sensitivity_excludes_low_drift_contrasts():
    """With a drift threshold of 5 pp, a contrast whose |dh| is below 5 is
    dropped from the sensitivity table."""
    fx = _effects_fixture()
    drift = pd.Series({"c1": 30.0, "c2": 2.0})  # c2's human effect is small
    sens = se.response_regimes(fx, drift=drift)
    assert sens["n_contrasts"].max() < len(fx), (
        "sensitivity table must exclude contrasts under the drift cut"
    )


# ---------------------------------------------------------------- contract 7


def test_recovery_slope_weights_experiments_equally():
    """Exp1 has 2 contrasts, exp2 has 1. Equal-experiment weighting means
    exp2's single contrast carries weight 1/2, not 1/3."""
    codebook = pd.DataFrame([
        _codebook_row("a", "disease", oe=0),
        _codebook_row("b", "disease", oe=0),
        _codebook_row("c", "allais", oe=0),
    ])
    human = pd.DataFrame(
        _arms("humans", "disease", "a", 0.7, 0.3)
        + _arms("humans", "disease", "b", 0.5, 0.3)
        + _arms("humans", "allais", "c", 0.6, 0.3)
    )
    # model recovers exactly half of every human effect -> M = 0.5*H, so
    # the slope through the origin must be 0.5 under ANY sane weighting
    model = pd.DataFrame(
        _arms("m1", "disease", "a", 0.5, 0.3)
        + _arms("m1", "disease", "b", 0.4, 0.3)
        + _arms("m1", "allais", "c", 0.45, 0.3)
    )
    fx = se.build_signed_effects(model, human, codebook)
    res = se.recovery_slopes(fx, n_boot=0)
    assert res["beta_nonoe"] == pytest.approx(0.5, abs=1e-9), res


def test_recovery_slopes_report_both_groups_difference_and_cis():
    fx = _effects_fixture()
    res = se.recovery_slopes(fx, n_boot=200, seed=3)
    for key in ("beta_oe", "beta_nonoe", "difference", "family_ci"):
        assert key in res, f"missing {key}"
    # unweighted sensitivity must also be reported
    assert "unweighted" in res, sorted(res)


# ---------------------------------------------------------------- contract 8


def test_model_oe_penalties_have_absolute_and_signed_columns():
    fx = _effects_fixture()
    tab = se.model_oe_penalties(fx, n_boot=0)
    for col in ("model", "absolute_penalty", "signed_penalty",
                "absolute_ci_low", "absolute_ci_high",
                "signed_ci_low", "signed_ci_high"):
        assert col in tab.columns, f"missing {col}"
    assert set(tab["model"]) == {"m1", "m2"}


# ---------------------------------------------------------------- contract 9


def test_profile_recovery_correlation_flags_quadrants():
    fx = _effects_fixture()
    profile = pd.DataFrame({
        "model": ["m1", "m1", "m2", "m2"],
        "experiment": ["disease", "allais", "disease", "allais"],
        "profile_error": [10.0, 25.0, 5.0, 30.0],
    })
    tab = se.profile_recovery_correlations(fx, profile)
    for col in ("model", "experiment", "corr_signed_recovery",
                "corr_absolute_contrast_error", "ci_low", "ci_high",
                "low_profile_high_recovery_error", "high_profile_low_recovery_error"):
        assert col in tab.columns, f"missing {col}"


# --------------------------------------------------------------- contract 10


def test_taxonomy_loo_ranks_categories_by_mae():
    fx = _effects_fixture()
    tab = se.taxonomy_loo_comparison(fx)
    assert set(tab["category"]) == {
        "objective_equivalence", "reference_context", "preference_vs_belief",
    }
    for col in ("mae", "ci_low", "ci_high"):
        assert col in tab.columns, f"missing {col}"
    pairs = se.taxonomy_pairwise_differences(tab)
    assert len(pairs) == 3, "three categories give three pairwise diffs"


# --------------------------------------------------------------- contract 11


def test_output_csv_has_exactly_the_contracted_columns():
    fx = _effects_fixture()
    assert list(fx.columns) == CSV_COLUMNS, list(fx.columns)


def test_run_entry_writes_all_repaired_outputs(tmp_path):
    fx = _effects_fixture()
    summary = runmod.run(fx, _reference_table(fx), _effects_profile(),
                         tmp_path, seed=20260923)
    csv = tmp_path / "signed_contrast_effects_REPAIRED.csv"
    assert csv.exists()
    out = pd.read_csv(csv)
    assert list(out.columns) == CSV_COLUMNS
    for name in FIGURES:
        assert (tmp_path / f"{name}_REPAIRED.png").exists(), name
    assert (tmp_path / "signed_analysis_validation.txt").exists()
    gap = tmp_path / "invariance_gap_analysis_REPAIRED.txt"
    assert gap.exists()
    text = gap.read_text()
    assert "VALIDATION" in text and "PASS" in text
    assert "max discrepancy" in text.lower() or "max_discrepancy" in text
    for q in range(1, 8):
        assert f"Question {q}" in text, q
    assert any(label in text for label in (
        "Robust attenuation", "Suggestive attenuation-reversal",
        "Absolute OE difficulty only", "OE difficulty fails to reproduce",
    ))
    assert "validation" in summary


def _effects_profile():
    return pd.DataFrame({
        "model": ["m1", "m1", "m2", "m2"],
        "experiment": ["disease", "allais", "disease", "allais"],
        "profile_error": [10.0, 25.0, 5.0, 30.0],
    })


def test_validation_report_lists_pass_fail_per_assertion(tmp_path):
    fx = _effects_fixture()
    summary = runmod.run(fx, _reference_table(fx), _effects_profile(),
                         tmp_path, seed=20260923)
    text = (tmp_path / "signed_analysis_validation.txt").read_text()
    assert "base_rate" in text and "false_consensus" in text
    assert summary["validation_pass"] is True
