# RED tests for scripts/twin2k10/task_difficulty.py (TASK-2426).
#
# WHAT THIS FILE CHECKS, in plain words:
#   The module under test does not exist yet, so every test below fails
#   on the missing import — that is the expected RED reason.
#
#   The module must answer two questions about the T2K10 experiment:
#     1. How hard is each shared task really? Split each error number
#        into "which experiment" vs "which model" vs "cell noise"
#        shares, check how much the models agree with each other about
#        which experiments are hard, and rank experiments by their
#        typical model error minus the human test-retest error.
#     2. Do the designed task features (objective equivalence, reference
#        context) predict where models err more? Compare experiments
#        with the feature "on" vs "off", with a bootstrap confidence
#        interval, and check the result survives dropping one
#        experiment at a time.
#
# Everything runs offline on small fake numbers written here in the
# test file. No real run directory or real codebook is read.
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# The analysis scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import task_difficulty as td  # noqa: E402

# ---------------------------------------------------------------------------
# Synthetic fixtures: 6 models x 4 experiments of fake errors, plus a tiny
# fake feature codebook. Deterministic, tiny, no real files.
# ---------------------------------------------------------------------------

MODELS = ["m1", "m2", "m3", "m4", "m5", "m6"]
EXPERIMENTS = ["disease", "seatbelt", "sunk_cost", "myside"]


def _error_frame(seed: int = 0) -> pd.DataFrame:
    """A tidy model/experiment/error table with a deliberate pattern:
    'disease' is hardest (big errors), 'myside' easiest (near zero)."""
    rng = np.random.default_rng(seed)
    base = {"disease": 20.0, "seatbelt": 10.0, "sunk_cost": 5.0, "myside": 1.0}
    rows = []
    for m_i, model in enumerate(MODELS):
        for exp in EXPERIMENTS:
            err = base[exp] + 0.5 * m_i + rng.normal(0, 0.1)
            rows.append({"model": model, "experiment": exp, "error": err})
    return pd.DataFrame(rows)


def _human_retest() -> pd.DataFrame:
    """Per-experiment human test-retest errors (the noise floor)."""
    return pd.DataFrame(
        {
            "experiment": EXPERIMENTS,
            "human_error": [0.5, 0.4, 0.3, 0.2],
        }
    )


def _exp_codebook() -> pd.DataFrame:
    """Tiny experiment-level codebook: two features, 2 experiments per group."""
    return pd.DataFrame(
        {
            "experiment": EXPERIMENTS,
            "objective_equivalence": [1, 0, 1, 0],
            "reference_context": [1, 1, 0, 0],
        }
    )


# ---------------------------------------------------------------------------
# Contract 1 — variance decomposition
# ---------------------------------------------------------------------------


def test_variance_shares_sum_to_one() -> None:
    shares = td.decompose_variance(_error_frame(), n_boot=200, seed=2426)
    total = shares.loc[shares["component"].isin(["experiment", "model", "residual (cell-specific)"]), "share"].sum()
    assert total == pytest.approx(1.0, abs=1e-6)


def test_variance_components_named_without_interaction_word() -> None:
    shares = td.decompose_variance(_error_frame(), n_boot=200, seed=2426)
    assert set(shares["component"]) == {"experiment", "model", "residual (cell-specific)"}


def test_variance_shares_have_bootstrap_ci() -> None:
    shares = td.decompose_variance(_error_frame(), n_boot=200, seed=2426)
    assert {"ci_low", "ci_high"} <= set(shares.columns)
    assert (shares["ci_low"] <= shares["share"]).all()
    assert (shares["share"] <= shares["ci_high"]).all()


def test_human_rows_are_excluded_from_variance() -> None:
    df = pd.concat([_error_frame(), pd.DataFrame([{"model": "HUMAN", "experiment": "disease", "error": 99.0}])])
    shares = td.decompose_variance(df, n_boot=200, seed=2426)
    # The 99.0 HUMAN outlier must not dominate; experiment share stays modest.
    exp_share = shares.loc[shares["component"] == "experiment", "share"].iloc[0]
    assert exp_share < 0.99


def test_variance_is_deterministic_under_seed() -> None:
    a = td.decompose_variance(_error_frame(), n_boot=200, seed=2426)
    b = td.decompose_variance(_error_frame(), n_boot=200, seed=2426)
    pd.testing.assert_frame_equal(a, b)


# ---------------------------------------------------------------------------
# Contract 2 — model agreement (Spearman + Kendall's W)
# ---------------------------------------------------------------------------


def test_agreement_summary_keys() -> None:
    out = td.model_agreement(_error_frame())
    for key in ["median_rho", "iqr_rho", "ci_low", "ci_high", "prop_pairs_positive", "kendall_w", "kendall_w_ci_low", "kendall_w_ci_high"]:
        assert key in out, f"missing {key}"


def test_identical_model_rankings_give_perfect_agreement() -> None:
    df = _error_frame()
    out = td.model_agreement(df)
    assert out["median_rho"] == pytest.approx(1.0)
    assert out["kendall_w"] == pytest.approx(1.0)
    assert out["prop_pairs_positive"] == pytest.approx(1.0)


def test_human_rows_excluded_from_agreement() -> None:
    df = pd.concat([_error_frame(), pd.DataFrame([{"model": "HUMAN", "experiment": "disease", "error": 1.0}])])
    out = td.model_agreement(df)
    # 6 models -> 15 pairs; HUMAN would make 21.
    assert out["n_pairs"] == 15


# ---------------------------------------------------------------------------
# Contract 3 — per-experiment difficulty + excess error
# ---------------------------------------------------------------------------


def test_experiment_difficulty_columns_and_order() -> None:
    out = td.experiment_difficulty(_error_frame(), _human_retest(), n_boot=200, seed=2426)
    assert list(out["experiment"]) == ["disease", "seatbelt", "sunk_cost", "myside"]
    for col in ["median", "mean", "iqr", "mean_ci_low", "mean_ci_high", "median_ci_low", "median_ci_high", "excess_error"]:
        assert col in out.columns, f"missing {col}"


def test_hardest_experiment_ranked_first_with_largest_excess() -> None:
    out = td.experiment_difficulty(_error_frame(), _human_retest(), n_boot=200, seed=2426)
    assert out["excess_error"].iloc[0] == max(out["excess_error"])
    # disease: ~20 median vs human 0.5 -> excess near 19.5, not near 20.
    assert 15.0 < out["excess_error"].iloc[0] < 20.0


def test_difficulty_bootstrap_is_seeded() -> None:
    a = td.experiment_difficulty(_error_frame(), _human_retest(), n_boot=200, seed=2426)
    b = td.experiment_difficulty(_error_frame(), _human_retest(), n_boot=200, seed=2426)
    pd.testing.assert_frame_equal(a, b)


# ---------------------------------------------------------------------------
# Contract 4 — feature effects (delta, experiments-within-group bootstrap,
# LOO robustness, sensitivity codings excluded from primary)
# ---------------------------------------------------------------------------


def _contrast_codebook(tmp_path: Path) -> Path:
    """Two contrast rows for one feature-coded experiment pair."""
    path = tmp_path / "contrast_codebook.csv"
    pd.DataFrame(
        {
            "contrast": ["a_minus_b", "c_minus_b"],
            "experiment": ["disease", "disease"],
            "objective_equivalence": [1, 1],
            "reference_context": [1, 1],
        }
    ).to_csv(path, index=False)
    return path


def test_feature_effect_delta_matches_group_means(tmp_path: Path) -> None:
    errors = _error_frame()
    cb = _exp_codebook()
    out = td.feature_effects(
        profile_errors=errors,
        contrast_errors=None,
        experiment_codebook=cb,
        contrast_codebook=None,
        human_retest=_human_retest(),
        feature="objective_equivalence",
        outcome="profile",
        n_boot=200,
        seed=2426,
    )
    row = out.iloc[0]
    d_on = errors[errors["experiment"].isin(["disease", "sunk_cost"])]["error"].mean()
    d_off = errors[errors["experiment"].isin(["seatbelt", "myside"])]["error"].mean()
    assert row["delta"] == pytest.approx(d_on - d_off, abs=1e-6)


def test_feature_effect_output_columns(tmp_path: Path) -> None:
    out = td.feature_effects(
        profile_errors=_error_frame(),
        contrast_errors=None,
        experiment_codebook=_exp_codebook(),
        contrast_codebook=None,
        human_retest=_human_retest(),
        feature="objective_equivalence",
        outcome="profile",
        n_boot=200,
        seed=2426,
    )
    for col in ["feature", "outcome", "d_e", "delta", "ci_low", "ci_high", "ci_method", "loo_min_delta", "loo_max_delta", "sign_stable"]:
        assert col in out.columns, f"missing {col}"
    assert out.iloc[0]["ci_method"] == "experiments-within-group bootstrap"


def test_mixed_and_ambiguous_excluded_from_primary_estimate() -> None:
    cb = _exp_codebook()
    cb.loc[cb["experiment"] == "sunk_cost", "objective_equivalence"] = "mixed"
    # Feature "on" group now has only 'disease' -> fewer than 4 per group:
    # must be flagged descriptive-only, not silently estimated.
    out = td.feature_effects(
        profile_errors=_error_frame(),
        contrast_errors=None,
        experiment_codebook=cb,
        contrast_codebook=None,
        human_retest=_human_retest(),
        feature="objective_equivalence",
        outcome="profile",
        n_boot=200,
        seed=2426,
    )
    assert out.iloc[0]["estimate_status"] == "descriptive-only"


def test_small_groups_marked_descriptive_only() -> None:
    # reference_context has 2 vs 2 here; anything under 4 per group is
    # descriptive-only.
    out = td.feature_effects(
        profile_errors=_error_frame(),
        contrast_errors=None,
        experiment_codebook=_exp_codebook(),
        contrast_codebook=None,
        human_retest=_human_retest(),
        feature="reference_context",
        outcome="profile",
        n_boot=200,
        seed=2426,
    )
    assert out.iloc[0]["estimate_status"] == "descriptive-only"


def test_loo_sign_stable_when_delta_large() -> None:
    out = td.feature_effects(
        profile_errors=_error_frame(),
        contrast_errors=None,
        experiment_codebook=_exp_codebook(),
        contrast_codebook=None,
        human_retest=_human_retest(),
        feature="objective_equivalence",
        outcome="profile",
        n_boot=200,
        seed=2426,
    )
    row = out.iloc[0]
    assert row["sign_stable"] is True or row["sign_stable"] == True  # noqa: E712
    assert row["loo_min_delta"] > 0 and row["loo_max_delta"] > 0


def test_excess_outcome_uses_drift_subtracted_errors() -> None:
    out = td.feature_effects(
        profile_errors=_error_frame(),
        contrast_errors=None,
        experiment_codebook=_exp_codebook(),
        contrast_codebook=None,
        human_retest=_human_retest(),
        feature="objective_equivalence",
        outcome="excess",
        n_boot=200,
        seed=2426,
    )
    errors = _error_frame().merge(_human_retest(), on="experiment")
    errors["excess"] = errors["error"] - errors["human_error"]
    d_on = errors[errors["experiment"].isin(["disease", "sunk_cost"])]["excess"].mean()
    d_off = errors[errors["experiment"].isin(["seatbelt", "myside"])]["excess"].mean()
    assert out.iloc[0]["delta"] == pytest.approx(d_on - d_off, abs=1e-6)


def test_contrast_outcome_uses_contrast_level_coding() -> None:
    contrast_errors = pd.DataFrame(
        {
            "experiment": ["disease"] * 12,
            "contrast": ["a_minus_b"] * 6 + ["c_minus_b"] * 6,
            "error": [1.0] * 6 + [3.0] * 6,
        }
    )
    out = td.feature_effects(
        profile_errors=None,
        contrast_errors=contrast_errors,
        experiment_codebook=None,
        contrast_codebook=_contrast_codebook(Path("/tmp")),
        human_retest=None,
        feature="objective_equivalence",
        outcome="contrast",
        n_boot=200,
        seed=2426,
    )
    # D_e = mean across models per contrast, then averaged: (1.0 + 3.0)/2 = 2.
    assert out.iloc[0]["d_e"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Contract 5 — exclusions
# ---------------------------------------------------------------------------


def test_canonical_bias_never_estimated() -> None:
    cb = _exp_codebook()
    cb["experiment"] = cb["experiment"].replace({"myside": "canonical_bias"})
    errors = _error_frame()
    errors["experiment"] = errors["experiment"].replace({"myside": "canonical_bias"})
    out = td.feature_effects(
        profile_errors=errors,
        contrast_errors=None,
        experiment_codebook=cb,
        contrast_codebook=None,
        human_retest=_human_retest(),
        feature="objective_equivalence",
        outcome="profile",
        n_boot=200,
        seed=2426,
    )
    assert "canonical_bias" not in set(out["feature"])
    assert td.EXCLUDED_FEATURES_PERMANENT == ["canonical_bias"]


def test_base_rate_not_in_codebook_features() -> None:
    assert "base_rate" not in td.CODEBOOK_FEATURES


def test_false_consensus_profile_only() -> None:
    assert td.PROFILE_ONLY_EXPERIMENTS == ["false_consensus"]


# ---------------------------------------------------------------------------
# Contract 6 — alternative explanations
# ---------------------------------------------------------------------------


def test_slope_per_ten_pp_human_gap() -> None:
    df = pd.DataFrame(
        {
            "experiment": EXPERIMENTS,
            "contrast_error": [10.0, 5.0, 2.0, 1.0],
            "human_gap": [-0.30, -0.10, 0.10, 0.30],  # |gap| 0.30..0.10? keep spread
        }
    )
    out = td.alternative_explanations(df, n_boot=200, seed=2426)
    for key in ["slope_per_10pp", "slope_ci_low", "slope_ci_high", "spearman_rho", "spearman_ci_low", "spearman_ci_high"]:
        assert key in out, f"missing {key}"


def test_alternative_explanations_seeded() -> None:
    df = pd.DataFrame(
        {
            "experiment": EXPERIMENTS,
            "contrast_error": [10.0, 5.0, 2.0, 1.0],
            "human_gap": [0.30, 0.20, 0.10, 0.05],
        }
    )
    a = td.alternative_explanations(df, n_boot=200, seed=2426)
    b = td.alternative_explanations(df, n_boot=200, seed=2426)
    assert a["slope_per_10pp"] == pytest.approx(b["slope_per_10pp"])


# ---------------------------------------------------------------------------
# Contract 7 — output artifacts and report rules
# ---------------------------------------------------------------------------


def test_run_analysis_writes_all_outputs(tmp_path: Path) -> None:
    indir = tmp_path / "in"
    indir.mkdir()
    _error_frame().to_csv(indir / "profile_error_complete.csv", index=False)
    _exp_codebook().to_csv(indir / "experiment_codebook.csv", index=False)
    outdir = tmp_path / "out"
    td.run_analysis(input_dir=indir, output_dir=outdir, n_boot=200, seed=2426)
    for name in [
        "shared_task_difficulty.txt",
        "task_feature_effects.csv",
        "task_feature_effects.png",
        "experiment_difficulty_profile.png",
        "experiment_difficulty_contrast.png",
        "task_similarity_profile.png",
        "task_similarity_contrast.png",
    ]:
        assert (outdir / name).exists(), f"missing output {name}"


def test_report_answers_questions_one_to_seven_in_order(tmp_path: Path) -> None:
    indir = tmp_path / "in"
    indir.mkdir()
    _error_frame().to_csv(indir / "profile_error_complete.csv", index=False)
    _exp_codebook().to_csv(indir / "experiment_codebook.csv", index=False)
    outdir = tmp_path / "out"
    td.run_analysis(input_dir=indir, output_dir=outdir, n_boot=200, seed=2426)
    text = (outdir / "shared_task_difficulty.txt").read_text()
    positions = [text.index(f"Question {i}") for i in range(1, 8)]
    assert positions == sorted(positions)


def test_report_never_says_significant_or_p_value(tmp_path: Path) -> None:
    indir = tmp_path / "in"
    indir.mkdir()
    _error_frame().to_csv(indir / "profile_error_complete.csv", index=False)
    _exp_codebook().to_csv(indir / "experiment_codebook.csv", index=False)
    outdir = tmp_path / "out"
    td.run_analysis(input_dir=indir, output_dir=outdir, n_boot=200, seed=2426)
    text = (outdir / "shared_task_difficulty.txt").read_text().lower()
    assert "significant" not in text
    assert "p-value" not in text and "p value" not in text
