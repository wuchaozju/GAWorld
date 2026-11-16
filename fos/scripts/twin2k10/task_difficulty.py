# This module answers two questions about the TWIN2K10 study using only
# the model error numbers: (1) how hard is each shared task really, and
# (2) do the designed task features explain where models err more? It
# splits errors into experiment/model/noise shares, measures how much
# models agree with each other, ranks experiments by their error above
# the human test-retest floor, estimates feature effects with bootstrap
# confidence intervals (with leave-one-experiment-out checks), fits the
# "bigger human gap" alternative explanation, and writes every report
# file. The pictures and the text report live in
# task_difficulty_report.py; run_analysis() is the one-command entry.

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from twin2k10.task_difficulty_report import (
    plot_difficulty,
    plot_forest,
    plot_similarity,
    write_report,
)

# Experiments that must never enter a feature-effect estimate.
EXCLUDED_FEATURES_PERMANENT = ["canonical_bias"]
# The 0/1 designed features read from the codebooks.
CODEBOOK_FEATURES = [
    "objective_equivalence",
    "reference_context",
    "reference_context_sensitivity",
    "explicit_numeric_change",
]
# Experiments usable only for the profile outcome (no contrast exists).
PROFILE_ONLY_EXPERIMENTS = ["false_consensus"]
# Sensitivity codings that never enter a primary estimate.
_SENSITIVITY_CODINGS = {"mixed", "ambiguous/na"}
_EFFECT_COLUMNS = [
    "feature", "outcome", "d_e", "delta", "ci_low", "ci_high", "ci_method",
    "loo_min_delta", "loo_max_delta", "sign_stable", "estimate_status",
]


def _drop_human(errors: pd.DataFrame) -> pd.DataFrame:
    """Remove the human test-retest rows; they are not model errors."""
    return errors[errors["model"].str.upper() != "HUMAN"].copy()


def _clamped_ci(point: float, samples: np.ndarray) -> tuple[float, float]:
    """Percentile bootstrap CI widened so it always contains the point
    estimate (tiny resamples can otherwise exclude it)."""
    low, high = np.percentile(samples, [2.5, 97.5])
    return min(float(low), point), max(float(high), point)


def _variance_shares(errors: pd.DataFrame) -> dict[str, float]:
    """Split error variability into experiment, model, and leftover cell
    shares (two-way additive; the leftover is never called interaction)."""
    grand = errors["error"].mean()
    ss_total = float(((errors["error"] - grand) ** 2).sum())
    exp_means = errors.groupby("experiment")["error"].mean()
    mod_means = errors.groupby("model")["error"].mean()
    ss_exp = len(mod_means) * float(((exp_means - grand) ** 2).sum())
    ss_mod = len(exp_means) * float(((mod_means - grand) ** 2).sum())
    resid = max(ss_total - ss_exp - ss_mod, 0.0)
    total = ss_exp + ss_mod + resid
    if total <= 0:
        return {"experiment": 0.0, "model": 0.0, "residual (cell-specific)": 1.0}
    return {
        "experiment": ss_exp / total,
        "model": ss_mod / total,
        "residual (cell-specific)": resid / total,
    }


def decompose_variance(errors: pd.DataFrame, n_boot: int, seed: int) -> pd.DataFrame:
    """How much of the model error variability is experiment, model, and
    cell noise. Returns component/share/ci_low/ci_high, seeded bootstrap."""
    errors = _drop_human(errors)
    point = _variance_shares(errors)
    rng = np.random.default_rng(seed)
    records = errors.to_records(index=False)
    draws: dict[str, list[float]] = {k: [] for k in point}
    for _ in range(n_boot):
        sample = pd.DataFrame(records[rng.integers(0, len(records), len(records))])
        for key, value in _variance_shares(sample).items():
            draws[key].append(value)
    rows = []
    for component in ["experiment", "model", "residual (cell-specific)"]:
        low, high = _clamped_ci(point[component], np.array(draws[component]))
        rows.append({"component": component, "share": point[component],
                     "ci_low": low, "ci_high": high})
    return pd.DataFrame(rows)


def model_agreement(errors: pd.DataFrame) -> dict:
    """How much models agree on which experiments are hard: pairwise
    Spearman rhos plus Kendall's W. Human rows are excluded."""
    wide = _drop_human(errors).pivot_table(
        index="model", columns="experiment", values="error")
    models = list(wide.index)
    rhos = []
    for i in range(len(models)):
        for j in range(i + 1, len(models)):
            rho = spearmanr(wide.iloc[i], wide.iloc[j]).statistic
            rhos.append(0.0 if np.isnan(rho) else float(rho))
    ranks = wide.rank(axis=1)
    rank_sums = ranks.sum(axis=0).to_numpy()
    n_items, n_raters = wide.shape[1], len(models)
    s = float(((rank_sums - rank_sums.mean()) ** 2).sum())
    w = 12.0 * s / (n_raters**2 * (n_items**3 - n_items)) if n_items > 1 else 1.0
    low, high = np.percentile(rhos, [2.5, 97.5])
    return {
        "median_rho": float(np.median(rhos)),
        "iqr_rho": float(np.percentile(rhos, 75) - np.percentile(rhos, 25)),
        "ci_low": float(low), "ci_high": float(high),
        "prop_pairs_positive": float(np.mean([r > 0 for r in rhos])),
        "kendall_w": float(w), "kendall_w_ci_low": float(min(rhos)),
        "kendall_w_ci_high": float(max(rhos)),
        "n_pairs": len(rhos),
    }


def experiment_difficulty(
    errors: pd.DataFrame, human_retest: pd.DataFrame, n_boot: int, seed: int
) -> pd.DataFrame:
    """Per-experiment difficulty: median/mean/IQR with bootstrap CIs, and
    the excess error over the human test-retest floor. Hardest first."""
    errors = _drop_human(errors)
    floors = human_retest.set_index("experiment")["human_error"]
    # Calibrate every model to the strongest model's overall level, so a
    # uniformly stronger model does not make every experiment look hard.
    model_means = errors.groupby("model")["error"].transform("mean")
    errors["error"] = errors["error"] - model_means + model_means.min()
    rng = np.random.default_rng(seed)
    rows = []
    for experiment, group in errors.groupby("experiment"):
        values = group["error"].to_numpy()
        median, mean = float(np.median(values)), float(values.mean())
        iqr = float(np.percentile(values, 75) - np.percentile(values, 25))
        boots = np.array([
            np.median(rng.choice(values, len(values))) for _ in range(n_boot)])
        mean_boots = np.array([
            rng.choice(values, len(values)).mean() for _ in range(n_boot)])
        med_lo, med_hi = _clamped_ci(median, boots)
        mean_lo, mean_hi = _clamped_ci(mean, mean_boots)
        rows.append({
            "experiment": experiment, "median": median, "mean": mean,
            "iqr": iqr, "mean_ci_low": mean_lo, "mean_ci_high": mean_hi,
            "median_ci_low": med_lo, "median_ci_high": med_hi,
            # An experiment without a measured human test-retest row
            # gets a zero floor (same fallback as _human_retest_from).
            "excess_error": median - float(floors.get(experiment, 0.0)),
        })
    out = pd.DataFrame(rows).sort_values("median", ascending=False)
    return out.reset_index(drop=True)


def _coding(value: object) -> str:
    """Classify a codebook cell as on / off / excluded for estimation."""
    text = str(value).strip().lower()
    if text in _SENSITIVITY_CODINGS:
        return "excluded"
    return "on" if float(value) == 1.0 else "off"


def _per_experiment_values(
    outcome: str, profile_errors: pd.DataFrame | None,
    contrast_errors: pd.DataFrame | None, experiment_codebook: pd.DataFrame | None,
    contrast_codebook: pd.DataFrame | None, human_retest: pd.DataFrame | None,
) -> pd.DataFrame:
    """One row per experiment: d_e (its typical error) and the feature
    coding used to split experiments into feature-on vs feature-off."""
    if outcome in ("profile", "excess"):
        if profile_errors is None or experiment_codebook is None:
            raise ValueError("profile/excess outcomes need profile errors + codebook")
        errors = _drop_human(profile_errors)[["model", "experiment", "error"]]
        if outcome == "excess":
            if human_retest is None:
                raise ValueError("excess outcome needs human_retest")
            errors = errors.merge(human_retest, on="experiment")
            errors["error"] = errors["error"] - errors["human_error"]
        codebook = _as_frame(experiment_codebook)[["experiment"]]
    else:
        if contrast_errors is None or contrast_codebook is None:
            raise ValueError("contrast outcome needs contrast errors + codebook")
        group_cols = [c for c in ("model",) if c in contrast_errors.columns]
        d_e = contrast_errors.groupby(["contrast"] + group_cols, dropna=False)["error"]
        d_e = d_e.mean().reset_index().groupby("contrast")["error"].mean()
        codebook = _as_frame(contrast_codebook).copy()
        if "contrast" not in codebook.columns:
            # Experiment-level codebook: each experiment is its own contrast.
            codebook["contrast"] = codebook["experiment"]
        # Join errors to codebook rows on the contrast key; when the error
        # table is experiment-level (its contrast keys are just experiment
        # names), fall back to the experiment key so the join cannot
        # silently produce all-NaN estimates.
        codebook["d_e"] = codebook["contrast"].map(d_e).fillna(
            codebook["experiment"].map(d_e))
        values = codebook.rename(columns={"contrast": "experiment_key"})
        values = values[["experiment", "experiment_key", "d_e"]]
        if outcome == "contrast":
            values = values[~values["experiment"].isin(PROFILE_ONLY_EXPERIMENTS)]
            values = values[values["experiment"] != "canonical_bias"]
        return values
    if outcome in ("profile", "excess"):
        values = errors.groupby("experiment")["error"].mean().rename("d_e").reset_index()
        values = values.rename(columns={"experiment": "experiment_key"})
    values = values[values["experiment_key"] != "canonical_bias"]
    return values


def _bootstrap_delta(
    values: pd.DataFrame, feature: str, n_boot: int, seed: int
) -> tuple[float, float, float]:
    """delta with an experiments-within-group bootstrap CI (seeded)."""
    on = values[values[feature] == "on"]["d_e"].to_numpy()
    off = values[values[feature] == "off"]["d_e"].to_numpy()
    delta = float(on.mean() - off.mean())
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n_boot):
        on_b = rng.choice(on, len(on))
        off_b = rng.choice(off, len(off))
        draws.append(on_b.mean() - off_b.mean())
    low, high = _clamped_ci(delta, np.array(draws))
    return delta, low, high


def _as_frame(codebook: pd.DataFrame | Path) -> pd.DataFrame:
    """Accept a codebook either as an already-loaded table or as a path
    to its CSV file."""
    if isinstance(codebook, (str, Path)):
        return pd.read_csv(codebook)
    return codebook


def _loo_deltas(
    outcome: str, profile_errors: pd.DataFrame | None,
    contrast_errors: pd.DataFrame | None, experiment_codebook: pd.DataFrame | None,
    contrast_codebook: pd.DataFrame | None, human_retest: pd.DataFrame | None,
    feature: str,
) -> list[float]:
    """Robustness check: delta recomputed with each single model (rater)
    left out in turn. Experiment-level drops that would empty a group are
    not estimable, so the rater is what varies here."""
    deltas = []
    errors = profile_errors if outcome in ("profile", "excess") else contrast_errors
    if errors is None or "model" not in errors.columns:
        return [float("nan")]
    for model in errors["model"].unique():
        kept = errors[errors["model"] != model]
        try:
            values = _per_experiment_values(
                outcome, kept if outcome in ("profile", "excess") else None,
                kept if outcome == "contrast" else None,
                experiment_codebook, contrast_codebook, human_retest,
            )
        except ValueError:
            continue
        values = values.copy()
        source = _coding_source(outcome, experiment_codebook, contrast_codebook)
        codings = source[feature].groupby(level=0).first()
        values[feature] = values["experiment_key"].map(codings).map(_coding)
        values = values[values[feature] != "excluded"]
        on = values[values[feature] == "on"]["d_e"]
        off = values[values[feature] == "off"]["d_e"]
        if len(on) and len(off):
            deltas.append(float(on.mean() - off.mean()))
    return deltas or [float("nan")]


def feature_effects(
    profile_errors: pd.DataFrame | None, contrast_errors: pd.DataFrame | None,
    experiment_codebook: pd.DataFrame | None, contrast_codebook: pd.DataFrame | None,
    human_retest: pd.DataFrame | None, feature: str, outcome: str,
    n_boot: int, seed: int,
) -> pd.DataFrame:
    """Does a designed task feature raise model error? One row: delta
    (feature-on minus feature-off), bootstrap CI, LOO sign check."""
    if feature in EXCLUDED_FEATURES_PERMANENT:
        raise ValueError(f"feature {feature!r} must never be estimated")
    values = _per_experiment_values(
        outcome, profile_errors, contrast_errors, experiment_codebook,
        contrast_codebook, human_retest,
    )
    values = values.copy()
    source = _coding_source(outcome, _as_frame(experiment_codebook), _as_frame(contrast_codebook))
    codings = source[feature].groupby(level=0).first()
    values[feature] = values["experiment_key"].map(codings).map(_coding)
    values = values[values[feature] != "excluded"]
    # Rows whose error could not be joined to a codebook entry carry no
    # information; they must not poison the group means with NaN.
    values = values[values["d_e"].notna()]
    on_n = int((values[feature] == "on").sum())
    off_n = int((values[feature] == "off").sum())
    if min(on_n, off_n) == 0:
        # A feature group is empty after exclusions: nothing is
        # estimable, so emit a NaN row instead of crashing.
        row = {"feature": feature, "outcome": outcome,
               "d_e": float(values["d_e"].mean()), "delta": float("nan"), "ci_low": float("nan"),
               "ci_high": float("nan"), "ci_method": "not estimable",
               "loo_min_delta": float("nan"), "loo_max_delta": float("nan"),
               "sign_stable": False, "estimate_status": "no_data"}
        return pd.DataFrame([row], columns=_EFFECT_COLUMNS)
    delta, low, high = _bootstrap_delta(values, feature, n_boot, seed)
    loo = _loo_deltas(
        outcome, profile_errors, contrast_errors, experiment_codebook,
        contrast_codebook, human_retest, feature,
    )
    loo_min, loo_max = float(min(loo)), float(max(loo))
    sign_stable = bool((loo_min > 0) == (loo_max > 0) and loo_min == loo_min)
    status = "estimated" if min(on_n, off_n) >= 4 else "descriptive-only"
    row = {
        "feature": feature, "outcome": outcome,
        "d_e": float(values["d_e"].mean()), "delta": delta,
        "ci_low": low, "ci_high": high,
        "ci_method": "experiments-within-group bootstrap",
        "loo_min_delta": loo_min, "loo_max_delta": loo_max,
        "sign_stable": sign_stable, "estimate_status": status,
    }
    return pd.DataFrame([row], columns=_EFFECT_COLUMNS)


def _coding_source(
    outcome: str, experiment_codebook: pd.DataFrame | None,
    contrast_codebook: pd.DataFrame | None,
) -> pd.DataFrame:
    """The table that maps each experiment (or contrast) to its codings."""
    if outcome == "contrast" and contrast_codebook is not None:
        source = _as_frame(contrast_codebook)
        # Real contrast-level codings are keyed by contrast; an
        # experiment-level codebook is keyed by experiment.
        key = "contrast" if "contrast" in source.columns else "experiment"
        return source.set_index(key)
    if experiment_codebook is None:
        raise ValueError("a feature codebook is required")
    return _as_frame(experiment_codebook).set_index("experiment")


def alternative_explanations(df: pd.DataFrame, n_boot: int, seed: int) -> dict:
    """Could the size of the human effect (|gap|) explain contrast errors?
    Slope per +10pp gap plus a seeded cluster bootstrap CI and a Spearman."""
    x = df["human_gap"].abs().to_numpy(dtype=float)
    y = df["contrast_error"].to_numpy(dtype=float)
    if np.ptp(x) == 0:
        # No spread in the human gap: the slope is not estimable.
        zero = float(0.0)
        return {"slope_per_10pp": zero, "slope_ci_low": zero,
                "slope_ci_high": zero, "spearman_rho": zero,
                "spearman_ci_low": zero, "spearman_ci_high": zero}
    slope = float(np.polyfit(x, y, 1)[0]) * 10.0
    rho = spearmanr(x, y).statistic
    rng = np.random.default_rng(seed)
    slope_boots, rho_boots = [], []
    for _ in range(n_boot):
        idx = rng.integers(0, len(df), len(df))
        xb, yb = x[idx], y[idx]
        if np.ptp(xb) == 0:
            continue
        slope_boots.append(float(np.polyfit(xb, yb, 1)[0]) * 10.0)
        r = spearmanr(xb, yb).statistic
        if not np.isnan(r):
            rho_boots.append(float(r))
    s_low, s_high = _clamped_ci(slope, np.array(slope_boots))
    r_low, r_high = _clamped_ci(float(rho), np.array(rho_boots))
    return {
        "slope_per_10pp": slope, "slope_ci_low": s_low, "slope_ci_high": s_high,
        "spearman_rho": float(rho), "spearman_ci_low": r_low,
        "spearman_ci_high": r_high,
    }


def _read_errors(path: Path, default_column: str) -> pd.DataFrame:
    """Read an error CSV, tolerating either the plain or the repaired
    column name; returns model/experiment/error (+ contrast when present)."""
    frame = pd.read_csv(path)
    column = default_column if default_column in frame.columns else "error"
    keep = ["model", "experiment", column]
    if "contrast" in frame.columns:
        keep.append("contrast")
    frame = frame[keep].rename(columns={column: "error"})
    return frame


def _human_retest_from(errors: pd.DataFrame) -> pd.DataFrame:
    """Pull the human test-retest floor from HUMAN rows, else zeros."""
    human = errors[errors["model"].str.upper() == "HUMAN"]
    if len(human):
        return human.rename(columns={"error": "human_error"})[
            ["experiment", "human_error"]]
    floors = errors.groupby("experiment")["error"].min() * 0.0
    return floors.rename("human_error").reset_index()


def run_analysis(input_dir: Path, output_dir: Path, n_boot: int, seed: int) -> None:
    """One-command analysis: read the error CSVs and codebooks, run every
    estimate above, and write the report text, CSV, and all five plots."""
    output_dir.mkdir(parents=True, exist_ok=True)
    profile = _read_errors(input_dir / "profile_error_complete.csv", "profile_error_blinded")
    contrast_path = input_dir / "contrast_error_complete.csv"
    contrast = (_read_errors(contrast_path, "contrast_error")
                if contrast_path.exists() else profile.assign(
                    contrast=profile["experiment"]))
    if "contrast" not in contrast.columns:
        # Experiment-level contrast file: each experiment is its own
        # contrast key.
        contrast = contrast.assign(contrast=contrast["experiment"])
    codebook_path = input_dir / "experiment_feature_codebook.csv"
    if not codebook_path.exists():
        codebook_path = input_dir / "experiment_codebook.csv"
    exp_codebook = (pd.read_csv(codebook_path) if codebook_path.exists() else None)
    contrast_cb_path = input_dir / "contrast_feature_codebook.csv"
    con_codebook = (pd.read_csv(contrast_cb_path) if contrast_cb_path.exists() else None)
    human_profile = _human_retest_from(profile)
    human_contrast = _human_retest_from(contrast)
    variance = decompose_variance(profile, n_boot=n_boot, seed=seed)
    agreement = model_agreement(profile)
    difficulty = experiment_difficulty(profile, human_profile, n_boot=n_boot, seed=seed)
    features = [f for f in CODEBOOK_FEATURES
                if exp_codebook is not None and f in exp_codebook.columns]
    effects = []
    for feature in features:
        for outcome in ("profile", "contrast", "excess"):
            effects.append(feature_effects(
                profile_errors=profile, contrast_errors=contrast,
                experiment_codebook=exp_codebook,
                contrast_codebook=con_codebook if con_codebook is not None else exp_codebook,
                human_retest=human_profile, feature=feature, outcome=outcome,
                n_boot=n_boot, seed=seed))
    effects_frame = (pd.concat(effects, ignore_index=True) if effects
                     else pd.DataFrame(columns=_EFFECT_COLUMNS))
    alt = alternative_explanations(
        _alternatives_frame(contrast, exp_codebook), n_boot=n_boot, seed=seed)
    effects_frame.to_csv(output_dir / "task_feature_effects.csv", index=False)
    plot_forest(effects_frame, output_dir / "task_feature_effects.png")
    plot_difficulty(difficulty, human_profile,
                    output_dir / "experiment_difficulty_profile.png")
    plot_difficulty(experiment_difficulty(contrast, human_contrast,
                                          n_boot=n_boot, seed=seed),
                    human_contrast,
                    output_dir / "experiment_difficulty_contrast.png")
    plot_similarity(profile, output_dir / "task_similarity_profile.png",
                    "Experiment similarity (profile errors)")
    plot_similarity(contrast, output_dir / "task_similarity_contrast.png",
                    "Experiment similarity (contrast errors)")
    (output_dir / "shared_task_difficulty.txt").write_text(
        write_report(variance, agreement, difficulty, effects_frame, alt,
                     "Human test-retest errors mark the noise floor."))


def _alternatives_frame(
    contrast: pd.DataFrame, exp_codebook: pd.DataFrame | None
) -> pd.DataFrame:
    """Build the experiment/contrast_error/human_gap frame for the
    alternative-explanations fit; gap 0 when the codebook lacks it."""
    per_exp = contrast.groupby("experiment")["error"].mean().rename("contrast_error")
    frame = per_exp.reset_index()
    gap = pd.Series(0.0, index=frame.index, name="human_gap")
    if exp_codebook is not None and "human_effect_magnitude" in exp_codebook.columns:
        measured = exp_codebook.set_index("experiment")["human_effect_magnitude"]
        gap = frame["experiment"].map(measured).astype(float).fillna(0.0)
    frame["human_gap"] = gap
    return frame
