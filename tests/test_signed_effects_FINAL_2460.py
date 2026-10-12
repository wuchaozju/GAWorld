# Tests for the TASK-2460 FINAL orientation repair of the signed-effect
# analysis.
#
# WHAT THIS FILE CHECKS, in plain words:
#   The repaired analysis reported the human effect with its original sign
#   and the "miss" R = M - H. The FINAL repair changes the reporting
#   orientation: the human effect is always read as a positive size
#   (H = |dh|), the model effect is read in the human's direction
#   (M = sign(dh) * dm), and the PRIMARY reported quantity is the
#   attenuation A = H - M (positive = the model under-recovered the human
#   response; A is exactly -R). On top of that, the analysis is grouped by
#   TASK TYPE (context-only vs objective-change) instead of the old
#   objective-equivalence flag, gets a FINAL assertion gate, through-origin
#   recovery slopes per task type, response regimes with sum-to-1 checks,
#   per-model penalty plots drawn as horizontal dot-and-interval charts,
#   and ten output files carrying the exact FINAL names.
#
#   Every test uses small synthetic numbers made up on the spot (seeded
#   where randomness is involved). No real results file is ever read.
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

# The FINAL table's locked column order.
FINAL_CSV_COLUMNS = [
    "model", "experiment", "contrast", "paradigm_family",
    "human_effect_normalized", "model_effect_normalized",
    "human_effect_pp", "model_effect_pp",
    "human_effect_oriented_pp", "model_effect_oriented_pp",
    "signed_recovery_error_pp", "absolute_recovery_error_pp",
    "attenuation_pp", "task_type",
    "objective_equivalence", "reference_context", "preference_vs_belief",
]

# The ten FINAL-named outputs.
FINAL_OUTPUTS = [
    "signed_contrast_effects_FINAL.csv",
    "signed_analysis_validation_FINAL.txt",
    "attenuation_by_task_type_FINAL.png",
    "human_effect_recovery_slopes_FINAL.png",
    "absolute_error_by_model_FINAL.png",
    "attenuation_by_model_FINAL.png",
    "response_regime_FINAL.png",
    "profile_vs_contrast_FINAL.png",
    "taxonomy_comparison_FINAL.png",
    "invariance_gap_analysis_FINAL.txt",
]

# The FINAL mechanism classification: exactly one of these four lines may
# appear in the report.
FINAL_CLASSIFICATIONS = [
    "Robust attenuation mechanism",
    "Suggestive attenuation-reversal mechanism",
    "Absolute context-only difficulty only; signed mechanism unsupported",
    "Context-only difficulty fails to reproduce",
]


def _codebook_row(contrast, experiment, treatment="T", comparison="C",
                  oe=0, ref_ctx=0, pref_belief=0, family="judgment",
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


def _final_fixture():
    """Two models x two experiments, one objective-change (humans move
    +0.40) and one context-only (humans move -0.20).

      m1 objective: model +0.30  -> H=40, M=+30, A=+10 (attenuated)
      m2 objective: model -0.40  -> H=40, M=-40, A=+80 (reversed)
      m1 context:   model -0.20  -> H=20, M=+20, A=0  (exact recovery)
      m2 context:   model +0.05  -> H=20, M=-5,  A=+25 (reversed)
    """
    codebook = pd.DataFrame([
        _codebook_row("c1", "disease", oe=1, family="judgment"),
        _codebook_row("c2", "allais", ref_ctx=1, pref_belief=1,
                      family="choice"),
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
    return codebook, human, model


def _build_final():
    codebook, human, model = _final_fixture()
    return se.build_signed_effects_final(model, human, codebook)


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


def _effects_profile(effects):
    return pd.DataFrame({
        "model": ["m1", "m1", "m2", "m2"],
        "experiment": ["disease", "allais", "disease", "allais"],
        "profile_error": [10.0, 25.0, 5.0, 30.0],
    })


# ---------------------------------------------------------------- contract 1
# The FINAL orientation: H = |dh| >= 0, M = sign(dh)*dm, A = H - M.


def test_final_human_oriented_effect_is_always_nonnegative():
    """H = |dh|: the human effect must come out >= 0 in every row, even
    when the raw human contrast was negative."""
    fx = _build_final()
    assert (fx["human_effect_oriented_pp"] >= 0).all(), (
        "FINAL orientation demands H = |dh| >= 0 in every row"
    )


def test_final_human_oriented_equals_absolute_human_effect():
    """H must be exactly |dh| (x100), not the signed dh."""
    fx = _build_final()
    lhs = fx["human_effect_oriented_pp"]
    rhs = fx["human_effect_pp"].abs()
    assert (lhs - rhs).abs().max() < 1e-10


def test_final_model_oriented_carries_human_sign():
    """M = sign(dh) * dm. Humans moved -0.20 on the context task; a model
    moving +0.05 must be reported as M = -5, not +5."""
    fx = _build_final()
    row = fx[(fx.contrast == "c2") & (fx.model == "m2")].iloc[0]
    assert row["model_effect_oriented_pp"] == pytest.approx(-5.0, abs=1e-9)
    row_pos = fx[(fx.contrast == "c1") & (fx.model == "m1")].iloc[0]
    assert row_pos["model_effect_oriented_pp"] == pytest.approx(30.0, abs=1e-9)


def test_final_attenuation_is_human_minus_model():
    """A = H - M. m1 on the objective task: H=40, M=30, so A=+10 (the
    model under-recovered 10 pp of the human response)."""
    fx = _build_final()
    row = fx[(fx.contrast == "c1") & (fx.model == "m1")].iloc[0]
    assert row["attenuation_pp"] == pytest.approx(10.0, abs=1e-9)


def test_final_attenuation_is_exactly_negative_signed_error():
    """A must equal -R to machine precision in every row."""
    fx = _build_final()
    lhs = fx["attenuation_pp"]
    rhs = -fx["signed_recovery_error_pp"]
    assert (lhs - rhs).abs().max() < 1e-10


def test_final_signed_error_is_model_minus_human():
    """R = M - H as before, but on the FINAL orientation values."""
    fx = _build_final()
    lhs = fx["signed_recovery_error_pp"]
    rhs = (fx["model_effect_oriented_pp"]
           - fx["human_effect_oriented_pp"])
    assert (lhs - rhs).abs().max() < 1e-10


def test_final_absolute_error_is_absolute_signed_error():
    fx = _build_final()
    lhs = fx["absolute_recovery_error_pp"]
    rhs = fx["signed_recovery_error_pp"].abs()
    assert (lhs - rhs).abs().max() < 1e-10


def test_final_csv_has_exactly_the_contracted_columns():
    fx = _build_final()
    assert list(fx.columns) == FINAL_CSV_COLUMNS, list(fx.columns)


def test_final_task_type_labels_context_and_objective():
    """Every row carries a task_type of 'context-only' or
    'objective-change', from the codebook flags."""
    fx = _build_final()
    assert set(fx["task_type"]) <= {"context-only", "objective-change"}
    assert set(fx["task_type"]) == {"context-only", "objective-change"}, (
        "the fixture spans both task types"
    )
    ctx = fx[fx.contrast == "c2"]["task_type"].unique()
    obj = fx[fx.contrast == "c1"]["task_type"].unique()
    assert list(ctx) == ["context-only"]
    assert list(obj) == ["objective-change"]


# ---------------------------------------------------------------- contract 2
# The FINAL validation gate: every orientation identity per row, plus the
# reproduction check against contrast_error_complete.


def test_final_validation_passes_on_wellformed_input():
    fx = _build_final()
    failures = se.validate_effects_final(
        fx, _reference_table(fx), USABLE, ["m1", "m2"]
    )
    assert failures == [], failures


def test_final_validation_flags_broken_attenuation_identity():
    """Tampering with attenuation_pp must trip the gate: A = H - M and
    A = -R are per-row mandatory assertions."""
    fx = _build_final()
    fx.loc[0, "attenuation_pp"] += 3.0
    failures = se.validate_effects_final(
        fx, _reference_table(fx), USABLE, ["m1", "m2"]
    )
    assert any("attenuation" in f.lower() for f in failures), failures


def test_final_validation_flags_negative_human_oriented_effect():
    fx = _build_final()
    fx.loc[0, "human_effect_oriented_pp"] = -1.0
    failures = se.validate_effects_final(
        fx, _reference_table(fx), USABLE, ["m1", "m2"]
    )
    assert any("human" in f.lower() for f in failures), failures


def test_final_validation_flags_misoriented_model_effect():
    fx = _build_final()
    # flip m2's context row back to the un-oriented +5
    bad = (fx.contrast == "c2") & (fx.model == "m2")
    fx.loc[bad, "model_effect_oriented_pp"] = 5.0
    failures = se.validate_effects_final(
        fx, _reference_table(fx), USABLE, ["m1", "m2"]
    )
    assert any("model" in f.lower() for f in failures), failures


def test_final_validation_reproduces_contrast_error_table():
    """Mean |R| per model x experiment must reproduce the standalone
    table to 1e-8 with ZERO mismatched cells; a corrupted cell must be
    reported with its discrepancy."""
    fx = _build_final()
    ref = _reference_table(fx)
    ref.loc[0, "contrast_error"] += 5.0
    failures = se.validate_effects_final(
        fx, ref, USABLE, ["m1", "m2"]
    )
    assert any("reproduc" in f.lower() for f in failures), failures
    assert any("5" in f for f in failures if "reproduc" in f.lower())


def test_final_validation_flags_missing_model():
    fx = _build_final()
    fx = fx[fx.model != "m2"]
    failures = se.validate_effects_final(
        fx, _reference_table(fx), USABLE, ["m1", "m2"]
    )
    assert any("m2" in f for f in failures), failures


def test_final_validation_flags_excluded_task():
    fx = _build_final()
    cb = pd.DataFrame([_codebook_row("x", "base_rate")])
    h = pd.DataFrame(_arms("humans", "base_rate", "x", 0.6, 0.4))
    m = pd.DataFrame(_arms("m1", "base_rate", "x", 0.5, 0.4))
    fx = pd.concat([fx, se.build_signed_effects_final(m, h, cb)],
                   ignore_index=True)
    failures = se.validate_effects_final(
        fx, _reference_table(fx), USABLE, ["m1", "m2"]
    )
    assert any("base_rate" in f for f in failures), failures


# ------------------------------------------------------- TASK-2475 contract
# The FINAL reference table: the gate must compare against a reference
# built under the FINAL orientation (mean |R| per model x experiment,
# regenerated from the FINAL table itself), not the stale legacy file.


def test_final_reference_built_from_table_itself_passes_gate():
    """Rebuilding the reference as mean |R| per model x experiment from
    the FINAL table itself must give a table the validation gate
    reproduces with ZERO mismatched cells."""
    fx = _build_final()
    ref = se.build_final_reference_table(fx)
    failures = se.validate_effects_final(fx, ref, USABLE, ["m1", "m2"])
    assert failures == [], failures


def test_reference_loader_final_orientation_reads_final_reference_csv(tmp_path):
    """With orientation="final" the loader must read the persisted FINAL
    reference file, not the legacy contrast_error_complete.csv."""
    legacy = pd.DataFrame({
        "model": ["m1"], "experiment": ["disease"],
        "method": ["arm_mean"], "contrast_error": [11.0],
    })
    final = pd.DataFrame({
        "model": ["m1"], "experiment": ["disease"],
        "contrast_error": [30.0],
    })
    legacy.to_csv(tmp_path / "contrast_error_complete.csv", index=False)
    final.to_csv(
        tmp_path / "contrast_error_complete_FINAL_reference.csv", index=False
    )
    loaded = runmod.load_contrast_error_table(tmp_path, orientation="final")
    assert float(loaded["contrast_error"].iloc[0]) == pytest.approx(30.0)


# ---------------------------------------------------------------- contract 3
# The main result: D_A = E[A|context-only] - E[A|objective-change].
# POSITIVE D_A = models under-recover more when only context changed.


def test_attenuation_gap_positive_when_context_more_attenuated():
    """Context task: model recovers none of the 20 pp (A=20). Objective
    task: model recovers it all (A=0). D_A = 20 - 0 = +20."""
    codebook = pd.DataFrame([
        _codebook_row("a", "disease", oe=1),
        _codebook_row("c", "allais", ref_ctx=1),
    ])
    human = pd.DataFrame(
        _arms("humans", "disease", "a", 0.7, 0.3)
        + _arms("humans", "allais", "c", 0.3, 0.5)
    )
    model = pd.DataFrame(
        _arms("m1", "disease", "a", 0.7, 0.3)   # M=40, A=0
        + _arms("m1", "allais", "c", 0.3, 0.5)  # M=0, A=20
    )
    fx = se.build_signed_effects_final(model, human, codebook)
    res = se.attenuation_gap(fx, n_boot=0)
    assert res["D_A"] == pytest.approx(20.0, abs=1e-9), res


def test_attenuation_gap_uses_experiment_equal_weighting():
    """Objective experiment has 2 contrasts (A=10 each), context has 1
    (A=40). Equal weighting: D_A = 40 - 10 = 30, NOT the pooled 40 - 10."""
    codebook = pd.DataFrame([
        _codebook_row("a", "disease", oe=1),
        _codebook_row("b", "disease", oe=1),
        _codebook_row("c", "allais", ref_ctx=1),
    ])
    human = pd.DataFrame(
        _arms("humans", "disease", "a", 0.7, 0.3)
        + _arms("humans", "disease", "b", 0.7, 0.3)
        + _arms("humans", "allais", "c", 0.3, 0.5)
    )
    model = pd.DataFrame(
        _arms("m1", "disease", "a", 0.6, 0.3)    # A = 40-30 = 10
        + _arms("m1", "disease", "b", 0.6, 0.3)  # A = 10
        + _arms("m1", "allais", "c", 0.3, 0.3)   # M=-20, A=40
    )
    fx = se.build_signed_effects_final(model, human, codebook)
    res = se.attenuation_gap(fx, n_boot=0)
    assert res["D_A"] == pytest.approx(30.0, abs=1e-9), res


def test_attenuation_gap_reports_cis_and_loo_ranges():
    fx = _build_final()
    res = se.attenuation_gap(fx, n_boot=200, seed=7)
    for key in ("family_ci", "experiment_ci",
                "loo_experiment_range", "loo_family_range"):
        assert key in res, f"missing {key} in {sorted(res)}"
    lo, hi = res["family_ci"]
    assert lo <= res["D_A"] + 1e-9 <= hi or lo == hi


def test_attenuation_gap_bootstrap_is_seeded_and_reproducible():
    fx = _build_final()
    a = se.attenuation_gap(fx, n_boot=100, seed=123)["family_ci"]
    b = se.attenuation_gap(fx, n_boot=100, seed=123)["family_ci"]
    assert a == b


def test_attenuation_gap_includes_plain_english_sentence():
    fx = _build_final()
    res = se.attenuation_gap(fx, n_boot=0)
    assert "sentence" in res and isinstance(res["sentence"], str)
    assert len(res["sentence"]) > 20, "must be a real sentence, not a label"


# ---------------------------------------------------------------- contract 4
# Recovery slopes: through-origin M = beta*H per task type (PRIMARY),
# free-intercept M = alpha + beta*H (SECONDARY, never mixed).


def test_through_origin_slope_is_half_when_model_recovers_half():
    """Model recovers exactly half of every human effect, so the
    through-origin slope must be 0.5 regardless of weighting."""
    codebook = pd.DataFrame([
        _codebook_row("a", "disease", oe=1),
        _codebook_row("b", "disease", oe=1),
        _codebook_row("c", "allais", ref_ctx=1),
    ])
    human = pd.DataFrame(
        _arms("humans", "disease", "a", 0.7, 0.3)
        + _arms("humans", "disease", "b", 0.5, 0.3)
        + _arms("humans", "allais", "c", 0.6, 0.3)
    )
    model = pd.DataFrame(
        _arms("m1", "disease", "a", 0.5, 0.3)
        + _arms("m1", "disease", "b", 0.4, 0.3)
        + _arms("m1", "allais", "c", 0.45, 0.3)
    )
    fx = se.build_signed_effects_final(model, human, codebook)
    res = se.recovery_slopes_final(fx, n_boot=0)
    assert res["beta_objective"] == pytest.approx(0.5, abs=1e-9), res
    assert res["beta_context"] == pytest.approx(0.5, abs=1e-9), res


def test_slopes_report_difference_and_cis():
    fx = _build_final()
    res = se.recovery_slopes_final(fx, n_boot=200, seed=3)
    for key in ("beta_objective", "beta_context", "difference", "family_ci"):
        assert key in res, f"missing {key}"


def test_free_intercept_fit_reported_separately():
    """The free-intercept fit (alpha + beta*H) must be reported under its
    own key, never merged with the through-origin numbers."""
    fx = _build_final()
    res = se.recovery_slopes_final(fx, n_boot=0)
    assert "free_intercept" in res, sorted(res)
    sub = res["free_intercept"]
    for key in ("beta_objective", "beta_context"):
        assert key in sub, f"missing {key} in free_intercept"


def test_slope_survives_reversed_model_on_negative_human_effect():
    """Humans move -0.20, model moves +0.05: H=20, M=-5. A negative
    slope contribution must pull the context slope below 1."""
    codebook = pd.DataFrame([_codebook_row("c", "allais", ref_ctx=1)])
    human = pd.DataFrame(_arms("humans", "allais", "c", 0.3, 0.5))
    model = pd.DataFrame(_arms("m1", "allais", "c", 0.45, 0.5))
    fx = se.build_signed_effects_final(model, human, codebook)
    res = se.recovery_slopes_final(fx, n_boot=0)
    assert res["beta_context"] == pytest.approx(-0.25, abs=1e-9), res


# ---------------------------------------------------------------- contract 5
# Regimes: reversed (M<0), attenuated (0<=M<H), exaggerated (M>H).


def test_regimes_partition_each_task_type():
    fx = _build_final()
    reg = se.response_regimes_final(fx)
    sums = reg.groupby("task_type")["proportion"].sum()
    assert np.allclose(sorted(sums.values), 1.0), sums


def test_regime_proportions_all_in_unit_interval():
    fx = _build_final()
    reg = se.response_regimes_final(fx)
    assert ((reg["proportion"] >= 0) & (reg["proportion"] <= 1)).all()


def test_regime_labels_match_definitions():
    """M<0 reversed; 0<=M<H attenuated; M>H exaggerated. The fixture:
    m1 objective attenuated (M=30<H=40); m2 objective reversed (M=-40);
    m1 context attenuated (M=H=20 boundary -> attenuated); m2 context
    reversed (M=-5<0)."""
    fx = _build_final()
    reg = se.response_regimes_final(fx)
    got = reg.set_index(["task_type", "regime"])["proportion"]
    assert got.loc[("objective-change", "attenuated")] == pytest.approx(
        0.5, abs=1e-12)
    assert got.loc[("objective-change", "reversed")] == pytest.approx(
        0.5, abs=1e-12)
    assert got.loc[("context-only", "reversed")] == pytest.approx(
        0.5, abs=1e-12)
    assert got.loc[("context-only", "attenuated")] == pytest.approx(
        0.5, abs=1e-12)


def test_reversed_regime_gap_context_minus_objective_with_ci():
    """P(reversed|context) - P(reversed|objective), here 0.5 - 0.5 = 0,
    with a CI key present."""
    fx = _build_final()
    res = se.reversed_regime_gap(fx, n_boot=100, seed=5)
    assert res["gap"] == pytest.approx(0.0, abs=1e-12), res
    assert "ci" in res, sorted(res)


# ---------------------------------------------------------------- contract 6
# Per-model penalties on the FINAL grouping + positive-penalty counts.


def test_model_penalties_have_absolute_and_attenuation_columns():
    fx = _build_final()
    tab = se.model_penalties_final(fx, n_boot=0)
    for col in ("model", "absolute_penalty", "attenuation_penalty",
                "absolute_ci_low", "absolute_ci_high",
                "attenuation_ci_low", "attenuation_ci_high"):
        assert col in tab.columns, f"missing {col}"
    assert set(tab["model"]) == {"m1", "m2"}


def test_model_attenuation_penalty_value():
    """m2: context A=25, objective A=80 -> attenuation penalty
    25 - 80 = -55 (m2 suffers MORE on objective-change)."""
    fx = _build_final()
    tab = se.model_penalties_final(fx, n_boot=0)
    got = float(tab.loc[tab.model == "m2", "attenuation_penalty"].iloc[0])
    assert got == pytest.approx(-55.0, abs=1e-9), tab


def test_count_models_with_positive_penalty():
    fx = _build_final()
    tab = se.model_penalties_final(fx, n_boot=0)
    counts = se.count_models_with_positive_penalty(tab)
    assert "n_absolute_positive" in counts
    assert "n_attenuation_positive" in counts
    assert counts["n_models"] == 2


# ---------------------------------------------------------------- contract 7
# Profile vs treatment fidelity, FINAL flavours.


def test_profile_fidelity_correlations_final_columns():
    fx = _build_final()
    tab = se.profile_fidelity_correlations(fx, _effects_profile(fx))
    for col in ("model", "experiment",
                "corr_absolute_contrast_error", "corr_attenuation",
                "ci_absolute_low", "ci_absolute_high",
                "ci_attenuation_low", "ci_attenuation_high"):
        assert col in tab.columns, f"missing {col}"


def test_profile_fidelity_correlations_are_seeded_reproducible():
    fx = _build_final()
    a = se.profile_fidelity_correlations(fx, _effects_profile(fx),
                                         n_boot=50, seed=11)
    b = se.profile_fidelity_correlations(fx, _effects_profile(fx),
                                         n_boot=50, seed=11)
    assert a.equals(b)


# ---------------------------------------------------------------- contract 8
# Taxonomy comparison on the FINAL quantity (A), cautious wording only.


def test_taxonomy_loo_on_attenuation_ranks_three_categories():
    fx = _build_final()
    tab = se.taxonomy_loo_comparison(fx, value_column="attenuation_pp")
    assert set(tab["category"]) == {
        "objective_equivalence", "reference_context", "preference_vs_belief",
    }
    for col in ("mae", "ci_low", "ci_high"):
        assert col in tab.columns, f"missing {col}"


# ---------------------------------------------------------------- contract 9
# The FINAL runner: ten FINAL-named outputs, VALIDATION first, A-G
# answers, exactly-one classification.


def test_final_runner_writes_all_ten_outputs(tmp_path):
    fx = _build_final()
    runmod.run_final(fx, _reference_table(fx), _effects_profile(fx),
                     tmp_path, seed=20260923)
    for name in FINAL_OUTPUTS:
        assert (tmp_path / name).exists(), name


def test_final_csv_output_has_contracted_columns(tmp_path):
    fx = _build_final()
    runmod.run_final(fx, _reference_table(fx), _effects_profile(fx),
                     tmp_path, seed=20260923)
    out = pd.read_csv(tmp_path / "signed_contrast_effects_FINAL.csv")
    assert list(out.columns) == FINAL_CSV_COLUMNS


def test_final_report_validation_block_comes_first(tmp_path):
    fx = _build_final()
    runmod.run_final(fx, _reference_table(fx), _effects_profile(fx),
                     tmp_path, seed=20260923)
    text = (tmp_path / "invariance_gap_analysis_FINAL.txt").read_text()
    assert text.lstrip().startswith("VALIDATION") or (
        text.splitlines()[0].strip().upper().startswith("VALIDATION")
    ), "VALIDATION block must come first"


def test_final_report_answers_a_through_g(tmp_path):
    fx = _build_final()
    runmod.run_final(fx, _reference_table(fx), _effects_profile(fx),
                     tmp_path, seed=20260923)
    text = (tmp_path / "invariance_gap_analysis_FINAL.txt").read_text()
    for letter in "ABCDEFG":
        assert f"{letter}." in text or f"{letter}:" in text, (
            f"answer {letter} missing"
        )


def test_final_report_classifies_exactly_one_mechanism(tmp_path):
    fx = _build_final()
    runmod.run_final(fx, _reference_table(fx), _effects_profile(fx),
                     tmp_path, seed=20260923)
    text = (tmp_path / "invariance_gap_analysis_FINAL.txt").read_text()
    hits = [label for label in FINAL_CLASSIFICATIONS if label in text]
    assert len(hits) == 1, f"expected exactly one classification, got {hits}"


def test_final_report_mentions_overall_slope_and_D_A(tmp_path):
    fx = _build_final()
    runmod.run_final(fx, _reference_table(fx), _effects_profile(fx),
                     tmp_path, seed=20260923)
    text = (tmp_path / "invariance_gap_analysis_FINAL.txt").read_text()
    assert "D_A" in text
    assert "slope" in text.lower()


def test_final_validation_file_written_and_lists_assertions(tmp_path):
    fx = _build_final()
    summary = runmod.run_final(fx, _reference_table(fx), _effects_profile(fx),
                               tmp_path, seed=20260923)
    text = (tmp_path / "signed_analysis_validation_FINAL.txt").read_text()
    assert "PASS" in text
    assert summary["validation_pass"] is True


def test_final_runner_stops_on_validation_failure(tmp_path):
    fx = _build_final()
    ref = _reference_table(fx)
    ref.loc[0, "contrast_error"] += 9.0  # corrupt reproduction
    with pytest.raises(runmod.ValidationFailure):
        runmod.run_final(fx, ref, _effects_profile(fx),
                         tmp_path, seed=20260923)


def test_penalty_plots_are_horizontal_dot_ci_not_vertical_bars(tmp_path):
    """The per-model penalty figures must be horizontal dot-and-interval
    charts: horizontal errorbars present, vertical bar patches absent."""
    fx = _build_final()
    runmod.run_final(fx, _reference_table(fx), _effects_profile(fx),
                     tmp_path, seed=20260923)
    from matplotlib import pyplot as plt
    penalty_figs = [f for f in map(plt.figure, plt.get_fignums())]
    assert penalty_figs, "expected at least one open figure to inspect"
    has_bars = any(
        len(ax.patches) > 0
        for fig in penalty_figs for ax in fig.axes
    )
    assert not has_bars, (
        "FINAL penalty plots must not use bar patches (horizontal "
        "dot-CI charts only)"
    )
    plt.close("all")
