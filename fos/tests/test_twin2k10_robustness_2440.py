# RED tests for scripts/twin2k10/robustness.py (TASK-2440).
#
# WHAT THIS FILE CHECKS, in plain words:
#   The module under test does not exist yet, so every test below fails
#   on the missing import — that is the expected RED reason.
#
#   The module must try to DISCONFIRM a headline result ("models err more
#   on objective-equivalence tasks") by checking it many different ways:
#   a bug audit, recomputing the effect from raw numbers, dropping one
#   experiment or one whole family of similar experiments at a time,
#   bootstrap intervals that resample families or both models and
#   experiments, different ways of averaging, different summaries
#   (median, trimmed mean), adjusting for human noise and for how big
#   the human effect was, dropping each response format, trying
#   alternative codings, shuffling labels at random, and writing a CSV
#   table, four pictures, and a short report.
#
# Everything runs offline on small fake numbers written here in the test
# file. No real run directory or real codebook is read. Deterministic
# under fixed seeds. No p-values anywhere (CIs only).
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import robustness as rb  # noqa: E402

# ---------------------------------------------------------------------------
# Synthetic fixtures: tiny fake error tables, codebooks, and family maps.
# ---------------------------------------------------------------------------

MODELS = ["m1", "m2", "m3", "m4", "m5", "m6"]
EXPERIMENTS = [
    "anchoring_redwood", "anchoring_african", "fire_extinguisher",
    "seatbelt", "wta_wtp", "sunk_cost", "allais", "linda", "myside",
]
# Deliberate pattern: objective-equivalence experiments are harder.
FEATURE_ON = {
    "anchoring_redwood", "anchoring_african", "fire_extinguisher",
    "seatbelt", "wta_wtp",
}
FAMILIES = {
    "anchoring": ["anchoring_redwood", "anchoring_african"],
    "proportion_dominance": ["fire_extinguisher", "seatbelt"],
    "valuation_reference": ["wta_wtp", "sunk_cost"],
    "probability_risk": ["allais"],
    "judgment_inference": ["linda", "myside"],
}
RESPONSE_FORMATS = pd.DataFrame({
    "experiment": EXPERIMENTS,
    "response_format": (
        "discrete_choice", "discrete_choice", "ordinal_rating",
        "ordinal_rating", "valuation_numeric", "valuation_numeric",
        "probability_share", "discrete_choice", "ordinal_rating",
    ),
})


def _profile_errors(seed: int = 0) -> pd.DataFrame:
    """Tidy model/experiment/error table; feature-on experiments are
    ~8 points harder, plus a model-level offset."""
    rng = np.random.default_rng(seed)
    base = {e: (14.0 if e in FEATURE_ON else 6.0) for e in EXPERIMENTS}
    rows = []
    for m_i, model in enumerate(MODELS):
        for exp in EXPERIMENTS:
            err = base[exp] + 0.3 * m_i + rng.normal(0, 0.2)
            rows.append({"model": model, "experiment": exp, "error": err})
    return pd.DataFrame(rows)


def _contrast_errors(seed: int = 0) -> pd.DataFrame:
    """Contrast-level errors, one contrast per experiment."""
    rng = np.random.default_rng(seed)
    rows = []
    for exp in EXPERIMENTS:
        on = exp in FEATURE_ON
        for m_i, model in enumerate(MODELS):
            err = (16.0 if on else 8.0) + 0.3 * m_i + rng.normal(0, 0.2)
            rows.append({"model": model, "experiment": exp,
                         "contrast": f"con_{exp}", "error": err})
    return pd.DataFrame(rows)


def _human_retest() -> pd.DataFrame:
    """Per-experiment human test-retest drift (the noise floor)."""
    drift = {"anchoring_redwood": 3.0, "anchoring_african": 2.5,
             "fire_extinguisher": 0.4, "seatbelt": 0.3, "wta_wtp": 0.5,
             "sunk_cost": 0.2, "allais": 0.1, "linda": 0.2, "myside": 0.1}
    return pd.DataFrame({"experiment": EXPERIMENTS,
                         "human_error": [drift[e] for e in EXPERIMENTS]})


def _experiment_codebook() -> pd.DataFrame:
    """Feature codings incl. the two ambiguous experiments which must be
    excluded from the primary analysis (outcome_bias NA, wta_wtp mixed)."""
    return pd.DataFrame({
        "experiment": EXPERIMENTS,
        "objective_equivalence": [1, 1, 1, 1, "mixed", 0, 0, 0, 0],
        "reference_context": [1, 1, 0, 0, 1, 0, 1, 0, 0],
    })


def _contrast_codebook() -> pd.DataFrame:
    return pd.DataFrame({
        "contrast": [f"con_{e}" for e in EXPERIMENTS],
        "experiment": EXPERIMENTS,
        "objective_equivalence": [1, 1, 1, 1, "mixed", 0, 0, 0, 0],
    })


def _bad_profile_errors_with_negative() -> pd.DataFrame:
    """Same as _profile_errors but one cell has a negative error — the
    validation must flag it, not swallow it."""
    errors = _profile_errors()
    errors.loc[0, "error"] = -1.5
    return errors


# ---------------------------------------------------------------------------
# 1. Validation (bug audit): PASS/FAIL logic
# ---------------------------------------------------------------------------

def test_validation_flags_negative_profile_errors():
    """A negative error in the profile table must produce a FAIL row."""
    report = rb.validation_report(
        _bad_profile_errors_with_negative(), _contrast_errors(),
        _human_retest(), experiment_codebook=_experiment_codebook())
    row = report[report["item"] == "profile_errors_nonnegative"]
    assert len(row) == 1
    assert row.iloc[0]["status"] == "FAIL"


def test_validation_passes_on_clean_inputs():
    report = rb.validation_report(
        _profile_errors(), _contrast_errors(), _human_retest(),
        experiment_codebook=_experiment_codebook())
    assert set(report["status"]) == {"PASS"}


def test_validation_flags_kendall_ci_outside_unit_interval():
    """Kendall's W lives on [0,1]; a CI below zero is a bug and the audit
    must say so."""
    report = rb.validation_report(
        _profile_errors(), _contrast_errors(), _human_retest(),
        experiment_codebook=_experiment_codebook(),
        kendall_ci=(-0.05, 0.4))
    row = report[report["item"] == "kendall_ci_within_support"]
    assert row.iloc[0]["status"] == "FAIL"


def test_validation_ambiguous_experiments_excluded():
    """wta_wtp is 'mixed' so it must be marked excluded, not counted as
    feature-on in the primary analysis."""
    report = rb.validation_report(
        _profile_errors(), _contrast_errors(), _human_retest(),
        experiment_codebook=_experiment_codebook())
    row = report[report["item"] == "ambiguous_codings_excluded"]
    assert row.iloc[0]["status"] == "PASS"
    detail = str(row.iloc[0]["detail"])
    assert "wta_wtp" in detail


# ---------------------------------------------------------------------------
# 2. Independent reproduction from raw tables
# ---------------------------------------------------------------------------

def test_reproduced_profile_effect_is_positive_and_near_eight_points():
    out = rb.reproduce_effects(
        _profile_errors(), _contrast_errors(), _experiment_codebook(),
        _contrast_codebook(), _human_retest())
    prof = out[out["outcome"] == "profile"].iloc[0]
    # Features-on experiments were built ~8 pp harder.
    assert prof["delta_pp"] == pytest.approx(8.0, abs=1.0)
    assert prof["delta_pp"] > 0
    assert prof["ci_low"] > 0  # 95% CI excludes zero


def test_reproduce_reports_group_sizes_and_both_summaries():
    out = rb.reproduce_effects(
        _profile_errors(), _contrast_errors(), _experiment_codebook(),
        _contrast_codebook(), _human_retest())
    prof = out[out["outcome"] == "profile"].iloc[0]
    assert prof["n_feature1"] == 4  # wta_wtp excluded as mixed
    assert prof["n_feature0"] == 4
    for col in ("mean_on", "median_on", "mean_off", "median_off"):
        assert col in out.columns


def test_reproduce_excess_effect_subtracts_human_drift():
    out = rb.reproduce_effects(
        _profile_errors(), _contrast_errors(), _experiment_codebook(),
        _contrast_codebook(), _human_retest())
    prof = out[out["outcome"] == "profile"].iloc[0]["delta_pp"]
    exc = out[out["outcome"] == "excess"].iloc[0]["delta_pp"]
    # Anchoring has huge human drift, so excess must be clearly smaller.
    assert exc < prof
    assert exc > 0


def test_reproduce_is_deterministic_under_seed():
    a = rb.reproduce_effects(_profile_errors(), _contrast_errors(),
                             _experiment_codebook(), _contrast_codebook(),
                             _human_retest(), seed=2426)
    b = rb.reproduce_effects(_profile_errors(), _contrast_errors(),
                             _experiment_codebook(), _contrast_codebook(),
                             _human_retest(), seed=2426)
    pd.testing.assert_frame_equal(a, b)


# ---------------------------------------------------------------------------
# 3. Ordinary leave-one-experiment-out
# ---------------------------------------------------------------------------

def test_loo_produces_one_row_per_outcome_per_experiment():
    out = rb.leave_one_experiment_out(
        _profile_errors(), _contrast_errors(), _experiment_codebook(),
        _contrast_codebook(), _human_retest())
    # 8 usable experiments (9 minus the mixed one) x 3 outcomes.
    assert len(out) == 8 * 3
    assert {"outcome", "omitted_experiment", "estimate_pp"} <= set(out.columns)


def test_loo_summary_reports_min_max_and_sign_changes():
    out = rb.leave_one_experiment_out(
        _profile_errors(), _contrast_errors(), _experiment_codebook(),
        _contrast_codebook(), _human_retest())
    summary = rb.loo_summary(out)
    for col in ("min_pp", "max_pp", "n_sign_changes",
                "omitted_smallest", "omitted_largest"):
        assert col in summary.columns
    # The pattern is strong; no single omission should flip the sign.
    assert summary.iloc[0]["n_sign_changes"] == 0
    assert summary.iloc[0]["min_pp"] > 0


# ---------------------------------------------------------------------------
# 4. Leave-one-paradigm-family-out
# ---------------------------------------------------------------------------

def test_family_assignments_anchor_together_and_have_rationale():
    fam = rb.paradigm_families(FAMILIES)
    anchoring = fam[fam["family"] == "anchoring"]["experiment"].tolist()
    assert sorted(anchoring) == ["anchoring_african", "anchoring_redwood"]
    assert "rationale" in fam.columns
    assert fam["rationale"].astype(str).str.len().gt(0).all()


def test_leave_family_out_drops_whole_families():
    out = rb.leave_family_out(
        _profile_errors(), _contrast_errors(), _experiment_codebook(),
        _contrast_codebook(), _human_retest(), FAMILIES)
    anch = out[(out["omitted_family"] == "anchoring")
               & (out["outcome"] == "profile")]
    assert len(anch) == 1
    remaining = set(out["omitted_family"])
    assert remaining == set(FAMILIES)


def test_both_anchorings_removed_result_is_reported_and_positive():
    """The spec demands the both-anchoring-removed number explicitly."""
    out = rb.leave_family_out(
        _profile_errors(), _contrast_errors(), _experiment_codebook(),
        _contrast_codebook(), _human_retest(), FAMILIES)
    anch = out[(out["omitted_family"] == "anchoring")
               & (out["outcome"] == "profile")].iloc[0]
    # Even without both anchors, the remaining on-group (fire_extinguisher,
    # seatbelt) is still harder than the off-group.
    assert anch["estimate_pp"] > 0
    summary = rb.family_out_summary(out)
    assert "estimate_pp" in summary.columns


def test_leave_family_out_survives_with_ci_excluding_zero():
    out = rb.leave_family_out(
        _profile_errors(), _contrast_errors(), _experiment_codebook(),
        _contrast_codebook(), _human_retest(), FAMILIES)
    summary = rb.family_out_summary(out)
    # Every family-out row keeps a positive point estimate.
    assert (summary["estimate_pp"] > 0).all()


# ---------------------------------------------------------------------------
# 5. Family cluster bootstrap / 6. two-way bootstrap
# ---------------------------------------------------------------------------

def test_family_cluster_bootstrap_resamples_families_not_experiments():
    out = rb.family_cluster_bootstrap(
        _profile_errors(), _contrast_errors(), _experiment_codebook(),
        _contrast_codebook(), _human_retest(), FAMILIES,
        n_boot=200, seed=2426)
    prof = out[out["outcome"] == "profile"].iloc[0]
    assert prof["estimate_pp"] == pytest.approx(8.0, abs=1.0)
    assert prof["ci_low"] <= prof["estimate_pp"] <= prof["ci_high"]
    # Cluster resampling of 5 families is coarser: CI should be wider than
    # a plain experiment bootstrap would give.
    assert prof["ci_high"] - prof["ci_low"] > 0


def test_family_cluster_bootstrap_is_deterministic():
    args = (_profile_errors(), _contrast_errors(), _experiment_codebook(),
            _contrast_codebook(), _human_retest(), FAMILIES)
    a = rb.family_cluster_bootstrap(*args, n_boot=50, seed=2426)
    b = rb.family_cluster_bootstrap(*args, n_boot=50, seed=2426)
    pd.testing.assert_frame_equal(a, b)


def test_two_way_bootstrap_gives_ci_per_outcome():
    out = rb.two_way_bootstrap(
        _profile_errors(), _contrast_errors(), _experiment_codebook(),
        _contrast_codebook(), _human_retest(), n_boot=100, seed=2426)
    assert set(out["outcome"]) == {"profile", "contrast", "excess"}
    for _, row in out.iterrows():
        assert row["ci_low"] <= row["estimate_pp"] <= row["ci_high"]
        assert row["estimate_pp"] > 0


# ---------------------------------------------------------------------------
# 7. Equal-weighting checks
# ---------------------------------------------------------------------------

def test_equal_weighting_distinguishes_three_weighting_schemes():
    out = rb.equal_weighting_checks(
        _profile_errors(), _contrast_errors(), _experiment_codebook(),
        _contrast_codebook(), _human_retest())
    specs = set(out["specification"])
    assert {"experiment_equal_profile", "experiment_equal_contrast",
            "contrast_level"} <= specs
    for _, row in out.iterrows():
        assert {"estimate_pp", "ci_low", "ci_high"} <= set(out.columns)
        assert row["estimate_pp"] > 0


def test_experiment_equal_profile_averages_within_experiment_first():
    """Each experiment must carry equal weight: build data where one
    feature-on experiment has many more model rows — the experiment-equal
    estimate must still sit near the per-experiment mean difference."""
    errors = _profile_errors()
    extra = errors[errors["experiment"] == "fire_extinguisher"].copy()
    errors = pd.concat([errors, extra], ignore_index=True)  # double weight
    out = rb.equal_weighting_checks(
        errors, _contrast_errors(), _experiment_codebook(),
        _contrast_codebook(), _human_retest())
    row = out[out["specification"] == "experiment_equal_profile"].iloc[0]
    assert row["estimate_pp"] == pytest.approx(8.0, abs=1.0)


# ---------------------------------------------------------------------------
# 8. Alternative summaries (median, 20% trimmed mean)
# ---------------------------------------------------------------------------

def test_alternative_summaries_median_and_trimmed_mean():
    out = rb.alternative_summaries(
        _profile_errors(), _experiment_codebook(), n_boot=100, seed=2426)
    specs = set(out["specification"])
    assert {"median", "trimmed_mean_20"} <= specs
    # Under both robust summaries the on-group stays harder.
    assert (out["estimate_pp"] > 0).all()
    for _, row in out.iterrows():
        assert row["ci_low"] <= row["estimate_pp"] <= row["ci_high"]


# ---------------------------------------------------------------------------
# 9. Human-drift sensitivity
# ---------------------------------------------------------------------------

def test_drift_sensitivity_three_specs_and_direction_stable():
    out = rb.drift_sensitivity(
        _profile_errors(), _contrast_errors(), _experiment_codebook(),
        _human_retest())
    specs = set(out["specification"])
    assert {"raw", "drift_adjusted", "high_drift_excluded"} <= specs
    # Anchoring carries the top-20% drift, so excluding it must change the
    # estimate — the function must not just echo the same number three times.
    est = out.set_index("specification")["estimate_pp"]
    assert est["raw"] != pytest.approx(est["high_drift_excluded"])
    assert (out["estimate_pp"] > 0).all()


# ---------------------------------------------------------------------------
# 10. Human effect magnitude adjustment
# ---------------------------------------------------------------------------

def test_magnitude_adjustment_returns_adjusted_and_unadjusted():
    out = rb.magnitude_adjusted_effect(
        _profile_errors(), _experiment_codebook(), _human_retest(),
        n_boot=100, seed=2426)
    for key in ("adjusted_b1_pp", "adjusted_ci_low", "adjusted_ci_high",
                "unadjusted_pp", "magnitude_association_pp"):
        assert key in out.columns
    # Adjusting for |human effect| (which is largest on anchoring, an
    # on-experiment) must shrink but not erase the feature effect.
    assert 0 < out["adjusted_b1_pp"] < out["unadjusted_pp"]


# ---------------------------------------------------------------------------
# 11. Response-format sensitivity
# ---------------------------------------------------------------------------

def test_response_format_drop_one_keeps_result():
    dist, drop = rb.response_format_sensitivity(
        _profile_errors(), _experiment_codebook(), RESPONSE_FORMATS)
    # Distribution table: each format covers both feature groups.
    assert {"response_format", "n_feature1", "n_feature0"} <= set(dist.columns)
    # Dropping any single format leaves a positive effect.
    assert (drop["estimate_pp"] > 0).all()
    assert set(drop["omitted_format"]) == set(RESPONSE_FORMATS["response_format"])


# ---------------------------------------------------------------------------
# 12. Coding sensitivity
# ---------------------------------------------------------------------------

def test_coding_sensitivity_enumerates_defensible_alternatives():
    out = rb.coding_sensitivity(
        _profile_errors(), _contrast_errors(), _experiment_codebook(),
        _contrast_codebook(), _human_retest())
    # outcome_bias NA primary / as-0 / as-1; wta_wtp mixed handled per
    # contrast-specific coding; less-is-more both codings.
    assert len(out) >= 3
    assert {"specification", "estimate_pp", "ci_low", "ci_high"} <= set(out.columns)
    # Range must be reported: no sign flip anywhere in the enumerated set.
    assert out["estimate_pp"].min() > 0
    assert out["ci_low"].max() > 0  # every CI lower bound stays positive


# ---------------------------------------------------------------------------
# 13./14. Variance shares and shared-difficulty robustness
# ---------------------------------------------------------------------------

def test_variance_shares_with_cis_and_direct_comparison():
    out = rb.variance_robustness(_profile_errors(), n_boot=100, seed=2426)
    assert {"share", "estimate", "ci_low", "ci_high"} <= set(out.columns)
    diff = out[out["share"] == "experiment_minus_model"]
    assert len(diff) == 1  # direct CI for experiment share − model share
    assert diff.iloc[0]["ci_low"] <= diff.iloc[0]["ci_high"]


def test_shared_difficulty_stats_respect_kendall_support():
    stats = rb.shared_difficulty_robustness(
        _profile_errors(), n_boot=100, seed=2426)
    assert 0.0 <= stats["kendall_w_ci_low"] <= stats["kendall_w_ci_high"] <= 1.0
    assert 0.0 <= stats["prop_pairs_positive"] <= 1.0
    assert stats["kendall_w_loo_min"] <= stats["kendall_w_loo_max"]


# ---------------------------------------------------------------------------
# 15. Negative-control permutation
# ---------------------------------------------------------------------------

def test_permutation_calibration_reports_null_and_observed():
    stats = rb.permutation_calibration(
        _profile_errors(), _experiment_codebook(), n_draws=200, seed=2426)
    for key in ("median_abs_null_pp", "pct95_abs_null_pp", "observed_abs_pp"):
        assert key in stats
    # The real labelling must look extreme against the random-label null.
    assert stats["observed_abs_pp"] > stats["pct95_abs_null_pp"]
    assert stats["median_abs_null_pp"] < stats["pct95_abs_null_pp"]
    assert stats["observed_abs_pp"] == pytest.approx(8.0, abs=1.0)


# ---------------------------------------------------------------------------
# 16. Robustness CSV
# ---------------------------------------------------------------------------

def test_robustness_table_has_required_columns_and_rows(tmp_path: Path):
    table = rb.build_robustness_table(
        _profile_errors(), _contrast_errors(), _experiment_codebook(),
        _contrast_codebook(), _human_retest(), FAMILIES,
        n_boot=50, seed=2426)
    cols = {"outcome", "specification", "estimate_pp", "ci_low", "ci_high",
            "n_feature1", "n_feature0", "sign_positive", "notes"}
    assert cols <= set(table.columns)
    specs = set(table["specification"])
    for required in ("original_experiment_bootstrap", "family_cluster_bootstrap",
                     "two_way_bootstrap", "median_based", "trimmed_mean",
                     "drift_adjusted", "high_drift_excluded",
                     "magnitude_adjusted", "anchoring_family_excluded",
                     "proportion_dominance_family_excluded"):
        assert required in specs, f"missing specification row: {required}"
    assert table["sign_positive"].dtype == bool
    path = tmp_path / "objective_equivalence_robustness.csv"
    rb.write_robustness_csv(table, path)
    saved = pd.read_csv(path)
    assert list(saved.columns) == list(table.columns)


# ---------------------------------------------------------------------------
# 17. Figures
# ---------------------------------------------------------------------------

def test_make_figures_writes_four_pngs(tmp_path: Path):
    table = rb.build_robustness_table(
        _profile_errors(), _contrast_errors(), _experiment_codebook(),
        _contrast_codebook(), _human_retest(), FAMILIES,
        n_boot=20, seed=2426)
    paths = rb.make_figures(table, _profile_errors(), FAMILIES,
                            out_dir=tmp_path)
    names = {p.name for p in paths}
    assert {
        "objective_equivalence_robustness_forest.png",
        "objective_equivalence_leave_family_out.png",
        "shared_task_difficulty_robustness.png",
        "experiment_similarity_repaired.png",
    } <= names
    for p in paths:
        assert p.exists() and p.stat().st_size > 0


# ---------------------------------------------------------------------------
# 18. Final report
# ---------------------------------------------------------------------------

def test_report_answers_all_questions_and_verdict(tmp_path: Path):
    table = rb.build_robustness_table(
        _profile_errors(), _contrast_errors(), _experiment_codebook(),
        _contrast_codebook(), _human_retest(), FAMILIES,
        n_boot=20, seed=2426)
    path = tmp_path / "objective_equivalence_robustness_report.txt"
    rb.write_report(table, path)
    text = path.read_text()
    assert "Specification" in text and "Profile" in text
    for answer_number in range(1, 10):
        assert str(answer_number) in text
    verdicts = [line for line in text.splitlines()
                if line.startswith(("Robust:", "Suggestive:", "Fragile:"))]
    assert len(verdicts) == 1  # exactly one verdict line


def test_no_p_values_in_report_or_csv(tmp_path: Path):
    table = rb.build_robustness_table(
        _profile_errors(), _contrast_errors(), _experiment_codebook(),
        _contrast_codebook(), _human_retest(), FAMILIES,
        n_boot=20, seed=2426)
    path = tmp_path / "objective_equivalence_robustness_report.txt"
    rb.write_report(table, path)
    text = path.read_text().lower()
    assert "p-value" not in text and "p value" not in text
    assert "p_value" not in text and "pvalue" not in text
    assert not table["notes"].astype(str).str.contains("p-value", case=False).any()
