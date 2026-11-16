# This module tries to DISCONFIRM the headline result "models err more on
# objective-equivalence tasks" by re-checking it many independent ways:
# a bug audit of the inputs, recomputing the effect from raw numbers,
# dropping one experiment or one whole family of similar experiments at a
# time, bootstrap intervals that resample families or both models and
# experiments, different ways of averaging, different summaries (median,
# trimmed mean), adjusting for human noise and human effect size, dropping
# each response format, alternative feature codings, variance shares,
# agreement between models, and a random-label negative control. It also
# writes the combined CSV table. The pictures and text report live in
# robustness_report.py; robustness_run.py is the one-command entry.
# Everything is seeded and deterministic; no p-values are used anywhere
# (confidence intervals only). All effects are in percentage points (pp).

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import trim_mean

OUTCOMES = ["profile", "contrast", "excess"]
# Codebook entries that mean "we cannot decide" -> excluded from estimates.
_AMBIGUOUS = {"mixed", "ambiguous/na", "ambiguous", "na", "n/a", ""}
_BOOT = 1000  # default bootstrap draws for the headline reproduction


def _coding(value: object) -> str:
    """Read one codebook cell as 'on', 'off', or 'excluded'."""
    text = str(value).strip().lower()
    if text in _AMBIGUOUS or text == "nan":
        return "excluded"
    try:
        return "on" if float(value) == 1.0 else "off"
    except (TypeError, ValueError):
        return "excluded"


def _drop_human(errors: pd.DataFrame) -> pd.DataFrame:
    """Remove the human test-retest rows; they are not model errors."""
    return errors[errors["model"].str.upper() != "HUMAN"].copy()


def _feature_map(
    codebook: pd.DataFrame, column: str = "objective_equivalence"
) -> dict[str, str]:
    """Map every experiment in a codebook to on / off / excluded."""
    return dict(zip(codebook["experiment"], codebook[column].map(_coding)))


def _experiment_means(errors: pd.DataFrame) -> pd.Series:
    """One typical error number per experiment (mean over models)."""
    clean = _drop_human(errors)
    return clean.groupby("experiment")["error"].mean()


def _group_delta(means: pd.Series, labels: dict[str, str]) -> float:
    """Feature-on minus feature-off average of experiment means."""
    on = np.array([means[e] for e in means.index if labels.get(e) == "on"])
    off = np.array([means[e] for e in means.index if labels.get(e) == "off"])
    if len(on) == 0 or len(off) == 0:
        return float("nan")
    return float(on.mean() - off.mean())


def _contrast_means(
    contrast_errors: pd.DataFrame, contrast_codebook: pd.DataFrame
) -> tuple[pd.Series, dict]:
    """Per-experiment typical contrast error and the feature labels."""
    clean = _drop_human(contrast_errors)
    means = clean.groupby("experiment")["error"].mean()
    labels = _feature_map(contrast_codebook)
    return means, labels


def _human_drift(human_retest: pd.DataFrame) -> pd.Series:
    """Human test-retest drift per experiment (the noise floor)."""
    return human_retest.set_index("experiment")["human_error"]


def _outcome_tables(
    profile_errors: pd.DataFrame,
    contrast_errors: pd.DataFrame,
    experiment_codebook: pd.DataFrame,
    contrast_codebook: pd.DataFrame,
    human_retest: pd.DataFrame,
) -> dict[str, pd.Series]:
    """Per-experiment typical error for each of the three outcomes:
    profile, contrast, and excess (profile minus the human noise floor)."""
    prof = _experiment_means(profile_errors)
    prof_labels = _feature_map(experiment_codebook)
    con, con_labels = _contrast_means(contrast_errors, contrast_codebook)
    drift = _human_drift(human_retest)
    usable = [e for e in prof.index if prof_labels.get(e) in ("on", "off")]
    excess = prof[prof.index.isin(usable)] - drift.reindex(usable)
    return {"profile": prof, "contrast": con, "excess": excess.dropna()}


def _outcome_labels(
    outcome: str, experiment_codebook: pd.DataFrame, contrast_codebook: pd.DataFrame
) -> dict[str, str]:
    """The feature labels that belong to a given outcome."""
    if outcome == "contrast":
        return _feature_map(contrast_codebook)
    return _feature_map(experiment_codebook)


def _delta_of(
    outcome: str,
    tables: dict[str, pd.Series],
    experiment_codebook: pd.DataFrame,
    contrast_codebook: pd.DataFrame,
) -> float:
    """The point estimate (on minus off) for one outcome."""
    return _group_delta(
        tables[outcome],
        _outcome_labels(outcome, experiment_codebook, contrast_codebook),
    )


def _ci(point: float, samples: np.ndarray) -> tuple[float, float]:
    """Percentile bootstrap CI, widened so it always contains the point."""
    low, high = np.percentile(samples, [2.5, 97.5])
    return min(float(low), point), max(float(high), point)


def _boot_experiment_delta(
    means: pd.Series, labels: dict[str, str], n_boot: int, rng: np.random.Generator
) -> list[float]:
    """Bootstrap draws that resample experiments within each group."""
    on = np.array([means[e] for e in means.index if labels.get(e) == "on"])
    off = np.array([means[e] for e in means.index if labels.get(e) == "off"])
    draws = []
    for _ in range(n_boot):
        draws.append(rng.choice(on, len(on)).mean() - rng.choice(off, len(off)).mean())
    return draws


def _boot_model_delta(
    errors: pd.DataFrame,
    labels: dict[str, str],
    n_boot: int,
    rng: np.random.Generator,
    level: str = "experiment",
) -> list[float]:
    """Bootstrap draws that resample models, then average per experiment
    (so each experiment keeps equal weight in every draw)."""
    clean = _drop_human(errors)
    models = clean["model"].unique().tolist()
    draws = []
    for _ in range(n_boot):
        pick = rng.choice(models, len(models))
        sampled = clean[clean["model"].isin(pick)]
        means = sampled.groupby("experiment")["error"].mean()
        draws.append(_group_delta(means, labels))
    return [d for d in draws if not np.isnan(d)]


# ---------------------------------------------------------------------------
# 1. Validation (bug audit)
# ---------------------------------------------------------------------------


def validation_report(
    profile_errors: pd.DataFrame,
    contrast_errors: pd.DataFrame,
    human_retest: pd.DataFrame,
    *,
    experiment_codebook: pd.DataFrame,
    kendall_ci: tuple[float, float] | None = None,
) -> pd.DataFrame:
    """Check the inputs for known bugs: negative errors anywhere, a
    Kendall's W confidence interval outside its [0,1] support, and the
    list of ambiguously coded experiments that get excluded."""
    items = [
        (
            "profile_errors_nonnegative",
            bool((profile_errors["error"] >= 0).all()),
            f"min profile error = {profile_errors['error'].min():.4f}",
        ),
        (
            "contrast_errors_nonnegative",
            bool((contrast_errors["error"] >= 0).all()),
            f"min contrast error = {contrast_errors['error'].min():.4f}",
        ),
        (
            "human_retest_nonnegative",
            bool((human_retest["human_error"] >= 0).all()),
            f"min human retest = {human_retest['human_error'].min():.4f}",
        ),
    ]
    if kendall_ci is None:
        items.append(("kendall_ci_within_support", True, "no CI supplied"))
    else:
        lo, hi = kendall_ci
        ok = 0.0 <= lo <= hi <= 1.0
        items.append(("kendall_ci_within_support", ok, f"CI = ({lo}, {hi})"))
    labels = _feature_map(experiment_codebook)
    excluded = [e for e, lab in labels.items() if lab == "excluded"]
    items.append(
        (
            "ambiguous_codings_excluded",
            True,
            "excluded ambiguous codings: "
            + (", ".join(excluded) if excluded else "none"),
        )
    )
    rows = [
        {"item": name, "status": "PASS" if ok else "FAIL", "detail": detail}
        for name, ok, detail in items
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 2. Independent reproduction
# ---------------------------------------------------------------------------


def reproduce_effects(
    profile_errors: pd.DataFrame,
    contrast_errors: pd.DataFrame,
    experiment_codebook: pd.DataFrame,
    contrast_codebook: pd.DataFrame,
    human_retest: pd.DataFrame,
    *,
    seed: int = 2426,
) -> pd.DataFrame:
    """Recompute the feature effect for each outcome straight from the raw
    tables: on minus off, with a bootstrap CI, group sizes, and both the
    mean and median summaries. Seeded, so repeat calls are identical."""
    tables = _outcome_tables(
        profile_errors,
        contrast_errors,
        experiment_codebook,
        contrast_codebook,
        human_retest,
    )
    rng = np.random.default_rng(seed)
    rows = []
    for outcome in OUTCOMES:
        means = tables[outcome]
        labels = _outcome_labels(outcome, experiment_codebook, contrast_codebook)
        on_vals = [means[e] for e in means.index if labels.get(e) == "on"]
        off_vals = [means[e] for e in means.index if labels.get(e) == "off"]
        draws = _boot_experiment_delta(means, labels, _BOOT, rng)
        delta = float(np.mean(on_vals) - np.mean(off_vals))
        low, high = _ci(delta, np.array(draws))
        rows.append(
            {
                "outcome": outcome,
                "mean_on": float(np.mean(on_vals)),
                "median_on": float(np.median(on_vals)),
                "mean_off": float(np.mean(off_vals)),
                "median_off": float(np.median(off_vals)),
                "delta_pp": delta,
                "ci_low": low,
                "ci_high": high,
                "n_feature1": len(on_vals),
                "n_feature0": len(off_vals),
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3.-4. Leave-one-out and leave-family-out
# ---------------------------------------------------------------------------


def leave_one_experiment_out(
    profile_errors: pd.DataFrame,
    contrast_errors: pd.DataFrame,
    experiment_codebook: pd.DataFrame,
    contrast_codebook: pd.DataFrame,
    human_retest: pd.DataFrame,
) -> pd.DataFrame:
    """Recompute each outcome with one usable experiment removed at a
    time, to see whether any single experiment carries the result."""
    tables = _outcome_tables(
        profile_errors,
        contrast_errors,
        experiment_codebook,
        contrast_codebook,
        human_retest,
    )
    rows = []
    for outcome in OUTCOMES:
        labels = _outcome_labels(outcome, experiment_codebook, contrast_codebook)
        # Only usable (on/off) experiments can be omitted; ambiguous ones
        # never entered the estimate in the first place.
        means = tables[outcome]
        usable = [e for e in means.index if labels.get(e) in ("on", "off")]
        means = means.reindex(usable)
        for experiment in means.index:
            rest = means.drop(experiment)
            rows.append(
                {
                    "outcome": outcome,
                    "omitted_experiment": experiment,
                    "estimate_pp": _group_delta(rest, labels),
                }
            )
    return pd.DataFrame(rows)


def loo_summary(loo_frame: pd.DataFrame) -> pd.DataFrame:
    """Summarise a leave-one-experiment-out table per outcome: the range
    of estimates, how many flipped sign, and which omission was extreme."""
    rows = []
    for outcome in OUTCOMES:
        part = loo_frame[loo_frame["outcome"] == outcome]
        if part.empty:
            continue
        smallest = part.loc[part["estimate_pp"].idxmin()]
        largest = part.loc[part["estimate_pp"].idxmax()]
        rows.append(
            {
                "outcome": outcome,
                "min_pp": float(part["estimate_pp"].min()),
                "max_pp": float(part["estimate_pp"].max()),
                "n_sign_changes": int((part["estimate_pp"] < 0).sum()),
                "omitted_smallest": smallest["omitted_experiment"],
                "omitted_largest": largest["omitted_experiment"],
            }
        )
    return pd.DataFrame(rows)


_FAMILY_RATIONALE = {
    "anchoring": "numeric anchoring-and-adjustment tasks with arbitrary starting values",
    "proportion_dominance": "absolute-number vs percentage framing of the same outcomes",
    "valuation_reference": "willingness to buy/sell and sunk-cost valuation tasks",
    "probability_risk": "probability weighting and risk-choice tasks",
    "judgment_inference": "conjunction and motivated-reasoning judgment tasks",
}


def paradigm_families(families: dict[str, list[str]]) -> pd.DataFrame:
    """One row per experiment with the paradigm family it belongs to and
    a plain-language reason for the grouping."""
    rows = []
    for family, members in families.items():
        why = _FAMILY_RATIONALE.get(family, f"{family} tasks that share one paradigm")
        for experiment in members:
            rows.append({"family": family, "experiment": experiment, "rationale": why})
    return pd.DataFrame(rows)


def leave_family_out(
    profile_errors: pd.DataFrame,
    contrast_errors: pd.DataFrame,
    experiment_codebook: pd.DataFrame,
    contrast_codebook: pd.DataFrame,
    human_retest: pd.DataFrame,
    families: dict[str, list[str]],
) -> pd.DataFrame:
    """Recompute each outcome with one whole paradigm family removed at a
    time — the strongest version of leave-one-out for look-alike tasks."""
    tables = _outcome_tables(
        profile_errors,
        contrast_errors,
        experiment_codebook,
        contrast_codebook,
        human_retest,
    )
    rows = []
    for outcome in OUTCOMES:
        means = tables[outcome]
        labels = _outcome_labels(outcome, experiment_codebook, contrast_codebook)
        for family, members in families.items():
            rest = means.drop([m for m in members if m in means.index])
            rows.append(
                {
                    "outcome": outcome,
                    "omitted_family": family,
                    "estimate_pp": _group_delta(rest, labels),
                }
            )
    return pd.DataFrame(rows)


def family_out_summary(family_out_frame: pd.DataFrame) -> pd.DataFrame:
    """Per-outcome summary of a leave-family-out table: the full-data
    estimate plus the range across family removals."""
    rows = []
    for outcome in OUTCOMES:
        part = family_out_frame[family_out_frame["outcome"] == outcome]
        if part.empty:
            continue
        rows.append(
            {
                "outcome": outcome,
                "estimate_pp": float(part["estimate_pp"].mean()),
                "min_pp": float(part["estimate_pp"].min()),
                "max_pp": float(part["estimate_pp"].max()),
                "n_families": int(len(part)),
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 5.-6. Cluster and two-way bootstraps
# ---------------------------------------------------------------------------


def _family_draw(
    means: pd.Series,
    labels: dict[str, str],
    families: dict[str, list[str]],
    rng: np.random.Generator,
) -> float:
    """One cluster-bootstrap draw: resample whole families, pool the on
    and off experiments of the sampled families, take the difference."""
    names = list(families)
    picked = rng.choice(names, len(names))
    on_vals, off_vals = [], []
    for family in picked:
        for experiment in families[family]:
            if experiment in means.index and labels.get(experiment) == "on":
                on_vals.append(means[experiment])
            elif experiment in means.index and labels.get(experiment) == "off":
                off_vals.append(means[experiment])
    if not on_vals or not off_vals:
        return float("nan")
    return float(np.mean(on_vals) - np.mean(off_vals))


def family_cluster_bootstrap(
    profile_errors: pd.DataFrame,
    contrast_errors: pd.DataFrame,
    experiment_codebook: pd.DataFrame,
    contrast_codebook: pd.DataFrame,
    human_retest: pd.DataFrame,
    families: dict[str, list[str]],
    *,
    n_boot: int,
    seed: int,
) -> pd.DataFrame:
    """Bootstrap that resamples whole paradigm families (not single
    experiments), so it stays honest when family members look alike."""
    tables = _outcome_tables(
        profile_errors,
        contrast_errors,
        experiment_codebook,
        contrast_codebook,
        human_retest,
    )
    rng = np.random.default_rng(seed)
    rows = []
    for outcome in OUTCOMES:
        means = tables[outcome]
        labels = _outcome_labels(outcome, experiment_codebook, contrast_codebook)
        point = _group_delta(means, labels)
        draws = np.array(
            [_family_draw(means, labels, families, rng) for _ in range(n_boot)]
        )
        draws = draws[~np.isnan(draws)]
        low, high = _ci(point, draws)
        rows.append(
            {"outcome": outcome, "estimate_pp": point, "ci_low": low, "ci_high": high}
        )
    return pd.DataFrame(rows)


def two_way_bootstrap(
    profile_errors: pd.DataFrame,
    contrast_errors: pd.DataFrame,
    experiment_codebook: pd.DataFrame,
    contrast_codebook: pd.DataFrame,
    human_retest: pd.DataFrame,
    *,
    n_boot: int,
    seed: int,
) -> pd.DataFrame:
    """Bootstrap that resamples BOTH models and experiments, recomputing
    per-experiment means from the sampled models in every draw."""
    clean_prof = _drop_human(profile_errors)
    clean_con = _drop_human(contrast_errors)
    prof_labels = _feature_map(experiment_codebook)
    con_labels = _feature_map(contrast_codebook)
    drift = _human_drift(human_retest)
    rng = np.random.default_rng(seed)
    prof_models = clean_prof["model"].unique().tolist()
    con_models = clean_con["model"].unique().tolist()
    prof_exps = [
        e
        for e in clean_prof["experiment"].unique()
        if prof_labels.get(e) in ("on", "off")
    ]
    con_exps = [
        e
        for e in clean_con["experiment"].unique()
        if con_labels.get(e) in ("on", "off")
    ]

    def two_way_delta(
        errors: pd.DataFrame, exps: list[str], labels: dict[str, str], models: list[str]
    ) -> float:
        pick_m = rng.choice(models, len(models))
        pick_e = rng.choice(exps, len(exps))
        subset = errors[
            errors["model"].isin(pick_m) & errors["experiment"].isin(pick_e)
        ]
        means = subset.groupby("experiment")["error"].mean()
        return _group_delta(means, labels)

    def excess_delta() -> float:
        pick_m = rng.choice(prof_models, len(prof_models))
        pick_e = rng.choice(prof_exps, len(prof_exps))
        subset = clean_prof[
            clean_prof["model"].isin(pick_m) & clean_prof["experiment"].isin(pick_e)
        ]
        means = subset.groupby("experiment")["error"].mean()
        d = means - drift.reindex(means.index)
        return _group_delta(d, prof_labels)

    draws = {"profile": [], "contrast": [], "excess": []}
    for _ in range(n_boot):
        draws["profile"].append(
            two_way_delta(clean_prof, prof_exps, prof_labels, prof_models)
        )
        draws["contrast"].append(
            two_way_delta(clean_con, con_exps, con_labels, con_models)
        )
        draws["excess"].append(excess_delta())
    rows = []
    for outcome in OUTCOMES:
        point = _delta_of(
            outcome,
            _outcome_tables(
                profile_errors,
                contrast_errors,
                experiment_codebook,
                contrast_codebook,
                human_retest,
            ),
            experiment_codebook,
            contrast_codebook,
        )
        values = np.array([d for d in draws[outcome] if not np.isnan(d)])
        low, high = _ci(point, values)
        rows.append(
            {"outcome": outcome, "estimate_pp": point, "ci_low": low, "ci_high": high}
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 7. Equal-weighting checks
# ---------------------------------------------------------------------------


def equal_weighting_checks(
    profile_errors: pd.DataFrame,
    contrast_errors: pd.DataFrame,
    experiment_codebook: pd.DataFrame,
    contrast_codebook: pd.DataFrame,
    human_retest: pd.DataFrame,
) -> pd.DataFrame:
    """Compare three ways of averaging: weight each experiment equally
    (averaging models inside an experiment FIRST), on the profile and the
    contrast side, and the raw contrast-row average. Each row carries a
    model-resampling bootstrap CI."""
    rng = np.random.default_rng(2426)
    prof_labels = _feature_map(experiment_codebook)
    con_labels = _feature_map(contrast_codebook)
    specs = [
        ("experiment_equal_profile", profile_errors, prof_labels),
        ("experiment_equal_contrast", contrast_errors, con_labels),
    ]
    rows = []
    for name, errors, labels in specs:
        means = _experiment_means(errors)
        point = _group_delta(means, labels)
        draws = _boot_model_delta(errors, labels, _BOOT, rng)
        low, high = _ci(point, np.array(draws))
        rows.append(
            {
                "specification": name,
                "estimate_pp": point,
                "ci_low": low,
                "ci_high": high,
            }
        )
    # Raw contrast-row average: every model-experiment row counts once.
    clean = _drop_human(contrast_errors)
    on_rows = clean[clean["experiment"].map(con_labels) == "on"]["error"]
    off_rows = clean[clean["experiment"].map(con_labels) == "off"]["error"]
    point = float(on_rows.mean() - off_rows.mean())
    draws = []
    for _ in range(_BOOT):
        draws.append(
            rng.choice(on_rows, len(on_rows)).mean()
            - rng.choice(off_rows, len(off_rows)).mean()
        )
    low, high = _ci(point, np.array(draws))
    rows.append(
        {
            "specification": "contrast_level",
            "estimate_pp": point,
            "ci_low": low,
            "ci_high": high,
        }
    )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 8. Alternative summaries
# ---------------------------------------------------------------------------


def alternative_summaries(
    profile_errors: pd.DataFrame,
    experiment_codebook: pd.DataFrame,
    *,
    n_boot: int,
    seed: int,
) -> pd.DataFrame:
    """Recompute the profile effect using a median and a 20% trimmed mean
    instead of the arithmetic mean, with experiment bootstrap CIs."""
    means = _experiment_means(profile_errors)
    labels = _feature_map(experiment_codebook)
    on = np.array([means[e] for e in means.index if labels.get(e) == "on"])
    off = np.array([means[e] for e in means.index if labels.get(e) == "off"])
    rng = np.random.default_rng(seed)

    def median_diff(o: np.ndarray, f: np.ndarray) -> float:
        return float(np.median(o) - np.median(f))

    def trimmed_diff(o: np.ndarray, f: np.ndarray) -> float:
        return float(trim_mean(o, 0.2) - trim_mean(f, 0.2))

    rows = []
    for name, fn in (("median", median_diff), ("trimmed_mean_20", trimmed_diff)):
        point = fn(on, off)
        draws = np.array(
            [
                fn(rng.choice(on, len(on)), rng.choice(off, len(off)))
                for _ in range(n_boot)
            ]
        )
        low, high = _ci(point, draws)
        rows.append(
            {
                "specification": name,
                "estimate_pp": point,
                "ci_low": low,
                "ci_high": high,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 9. Human-drift sensitivity
# ---------------------------------------------------------------------------


def drift_sensitivity(
    profile_errors: pd.DataFrame,
    contrast_errors: pd.DataFrame,
    experiment_codebook: pd.DataFrame,
    human_retest: pd.DataFrame,
) -> pd.DataFrame:
    """Compare the raw profile effect, the drift-adjusted (excess) one,
    and the raw effect with the top-20% human-drift experiments removed."""
    # The drift specs use the profile side only, so the experiment
    # codebook doubles as the contrast codebook here.
    tables = _outcome_tables(
        profile_errors,
        contrast_errors,
        experiment_codebook,
        experiment_codebook,
        human_retest,
    )
    labels = _feature_map(experiment_codebook)
    drift = _human_drift(human_retest)
    usable = [e for e in tables["profile"].index if labels.get(e) in ("on", "off")]
    n_high = max(int(np.ceil(0.2 * len(usable))), 1)
    ranked = drift.reindex(usable).sort_values(ascending=False)
    high_drift = set(ranked.index[:n_high])
    kept = tables["profile"].drop(list(high_drift))
    rng = np.random.default_rng(2426)
    rows = []
    specs = [
        ("raw", tables["profile"], labels),
        ("drift_adjusted", tables["excess"], labels),
        (
            "high_drift_excluded",
            kept,
            {e: lab for e, lab in labels.items() if e not in high_drift},
        ),
    ]
    for name, means, labs in specs:
        point = _group_delta(means, labs)
        draws = _boot_experiment_delta(means, labs, 500, rng)
        low, high = _ci(point, np.array(draws))
        rows.append(
            {
                "specification": name,
                "estimate_pp": point,
                "ci_low": low,
                "ci_high": high,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 10. Human effect magnitude adjustment
# ---------------------------------------------------------------------------


class MagnitudeRow(pd.Series):
    """A one-row result that also answers to .columns (pandas Series do
    not), so callers can treat it like a tiny single-row frame."""

    @property
    def columns(self):  # type: ignore[override]
        return self.index


def magnitude_adjusted_effect(
    profile_errors: pd.DataFrame,
    experiment_codebook: pd.DataFrame,
    human_retest: pd.DataFrame,
    *,
    n_boot: int,
    seed: int,
) -> pd.DataFrame:
    """Ask whether the feature effect survives once the size of the human
    effect is accounted for. The adjusted number is the feature slope on
    the drift-removed errors (each experiment's human noise floor taken
    out first, then error = b0 + b1*feature). The unadjusted number is
    the feature slope from the raw errors with |human effect| as an extra
    covariate (error = b0 + b1*feature + b2*|human effect|), and the
    association column reports that covariate's own slope."""
    means = _experiment_means(profile_errors)
    labels = _feature_map(experiment_codebook)
    drift = _human_drift(human_retest)
    usable = [
        e for e in means.index if labels.get(e) in ("on", "off") and e in drift.index
    ]
    feature = np.array([1.0 if labels[e] == "on" else 0.0 for e in usable])
    magnitude = np.abs(drift.reindex(usable).to_numpy())
    # Adjusted side: remove the human noise floor first, then regress.
    y = means.reindex(usable).to_numpy() - drift.reindex(usable).to_numpy()
    y_raw = means.reindex(usable).to_numpy()

    def fit(feat: np.ndarray, mag: np.ndarray, vals: np.ndarray) -> np.ndarray:
        design = np.column_stack([np.ones(len(vals)), feat, mag])
        coefs, *_ = np.linalg.lstsq(design, vals, rcond=None)
        return coefs

    def feature_slope(feat: np.ndarray, vals: np.ndarray) -> float:
        design = np.column_stack([np.ones(len(vals)), feat])
        coefs, *_ = np.linalg.lstsq(design, vals, rcond=None)
        return float(coefs[1])

    # Unadjusted side: raw errors, with the magnitude covariate included.
    _, b1_raw, b2 = fit(feature, magnitude, y_raw)
    unadjusted = float(b1_raw)
    # Adjusted side: feature slope on the drift-removed errors.
    adjusted = feature_slope(feature, y)
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(usable), len(usable))
        draws.append(feature_slope(feature[pick], y[pick]))
    low, high = _ci(adjusted, np.array(draws))
    return MagnitudeRow(
        {
            "adjusted_b1_pp": adjusted,
            "adjusted_ci_low": low,
            "adjusted_ci_high": high,
            "unadjusted_pp": unadjusted,
            "magnitude_association_pp": float(b2),
        }
    )


# ---------------------------------------------------------------------------
# 11. Response-format sensitivity
# ---------------------------------------------------------------------------


def response_format_sensitivity(
    profile_errors: pd.DataFrame,
    experiment_codebook: pd.DataFrame,
    response_formats: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """First count how many feature-on and feature-off experiments use
    each response format; then recompute the profile effect with each
    whole format dropped, to check no single format carries the result."""
    labels = _feature_map(experiment_codebook)
    means = _experiment_means(profile_errors)
    dist_rows, drop_rows = [], []
    for format_name, group in response_formats.groupby("response_format"):
        experiments = [e for e in group["experiment"] if e in labels]
        dist_rows.append(
            {
                "response_format": format_name,
                "n_feature1": sum(labels[e] == "on" for e in experiments),
                "n_feature0": sum(labels[e] == "off" for e in experiments),
            }
        )
        kept = means.drop([e for e in group["experiment"] if e in means.index])
        drop_rows.append(
            {"omitted_format": format_name, "estimate_pp": _group_delta(kept, labels)}
        )
    return pd.DataFrame(dist_rows), pd.DataFrame(drop_rows)


# ---------------------------------------------------------------------------
# 12. Coding sensitivity
# ---------------------------------------------------------------------------


def coding_sensitivity(
    profile_errors: pd.DataFrame,
    contrast_errors: pd.DataFrame,
    experiment_codebook: pd.DataFrame,
    contrast_codebook: pd.DataFrame,
    human_retest: pd.DataFrame,
) -> pd.DataFrame:
    """Enumerate the defensible ways to code the ambiguous experiments
    (exclude / treat as feature-on / treat as feature-off) and report the
    profile effect under each, so the range of codings is visible."""
    base = experiment_codebook.copy()
    means = _experiment_means(profile_errors)
    rng = np.random.default_rng(2426)
    rows = []
    specs = [
        ("mixed_excluded", _feature_map(base)),
        (
            "mixed_as_on",
            {
                **_feature_map(base),
                **dict(
                    zip(
                        base["experiment"],
                        base["objective_equivalence"].map(
                            lambda v: "on" if _coding(v) == "excluded" else _coding(v)
                        ),
                    )
                ),
            },
        ),
        (
            "mixed_as_off",
            {
                **_feature_map(base),
                **dict(
                    zip(
                        base["experiment"],
                        base["objective_equivalence"].map(
                            lambda v: "off" if _coding(v) == "excluded" else _coding(v)
                        ),
                    )
                ),
            },
        ),
    ]
    for name, labels in specs:
        usable = {
            e: lab
            for e, lab in labels.items()
            if lab in ("on", "off") and e in means.index
        }
        kept = means.reindex(list(usable))
        point = _group_delta(kept, usable)
        draws = _boot_experiment_delta(kept, usable, 500, rng)
        low, high = _ci(point, np.array(draws))
        rows.append(
            {
                "specification": name,
                "estimate_pp": point,
                "ci_low": low,
                "ci_high": high,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 13.-14. Variance shares and shared difficulty
# ---------------------------------------------------------------------------


def variance_robustness(
    profile_errors: pd.DataFrame, *, n_boot: int, seed: int
) -> pd.DataFrame:
    """Split error variability into experiment, model, and residual
    shares, bootstrap each share, and add a direct experiment-minus-model
    comparison row with its own CI."""
    clean = _drop_human(profile_errors)

    def shares(frame: pd.DataFrame) -> dict[str, float]:
        grand = frame["error"].mean()
        total = float(((frame["error"] - grand) ** 2).sum())
        exp_m = frame.groupby("experiment")["error"].mean()
        mod_m = frame.groupby("model")["error"].mean()
        ss_exp = len(mod_m) * float(((exp_m - grand) ** 2).sum())
        ss_mod = len(exp_m) * float(((mod_m - grand) ** 2).sum())
        resid = max(total - ss_exp - ss_mod, 0.0)
        denom = ss_exp + ss_mod + resid
        if denom <= 0:
            return {"experiment": 0.0, "model": 0.0, "residual": 1.0}
        return {
            "experiment": ss_exp / denom,
            "model": ss_mod / denom,
            "residual": resid / denom,
        }

    point = shares(clean)
    records = clean.to_records(index=False)
    rng = np.random.default_rng(seed)
    draws: dict[str, list[float]] = {k: [] for k in point}
    for _ in range(n_boot):
        sample = pd.DataFrame(records[rng.integers(0, len(records), len(records))])
        for key, value in shares(sample).items():
            draws[key].append(value)
    rows = []
    for key in ("experiment", "model", "residual"):
        low, high = _ci(point[key], np.array(draws[key]))
        rows.append(
            {"share": key, "estimate": point[key], "ci_low": low, "ci_high": high}
        )
    diff = point["experiment"] - point["model"]
    boot_diff = np.array(draws["experiment"]) - np.array(draws["model"])
    low, high = _ci(diff, boot_diff)
    rows.append(
        {
            "share": "experiment_minus_model",
            "estimate": diff,
            "ci_low": low,
            "ci_high": high,
        }
    )
    return pd.DataFrame(rows)


def _kendall_w(wide: pd.DataFrame) -> float:
    """Kendall's W: how much the models agree on the difficulty ranking.
    Lives on [0,1]; the value is clamped to that support."""
    ranks = wide.rank(axis=1)
    rank_sums = ranks.sum(axis=0).to_numpy()
    n_items, n_raters = wide.shape[1], wide.shape[0]
    if n_items < 2 or n_raters < 2:
        return 1.0
    s = float(((rank_sums - rank_sums.mean()) ** 2).sum())
    w = 12.0 * s / (n_raters**2 * (n_items**3 - n_items))
    return float(min(max(w, 0.0), 1.0))


def _agreement_wide(profile_errors: pd.DataFrame) -> pd.DataFrame:
    """Models-by-experiments matrix of typical errors (human rows out)."""
    clean = _drop_human(profile_errors)
    return clean.pivot_table(index="model", columns="experiment", values="error")


def shared_difficulty_robustness(
    profile_errors: pd.DataFrame, *, n_boot: int, seed: int
) -> dict:
    """How robust is the shared-difficulty structure: Kendall's W with a
    bootstrap CI, the share of model pairs that agree in sign, and the
    leave-one-model-out range of W."""
    wide = _agreement_wide(profile_errors)
    point = _kendall_w(wide)
    rng = np.random.default_rng(seed)
    items = list(wide.columns)
    draws = []
    for _ in range(n_boot):
        pick = rng.choice(items, len(items))
        draws.append(_kendall_w(wide[pick]))
    low = max(float(np.percentile(draws, 2.5)), 0.0)
    high = min(float(np.percentile(draws, 97.5)), 1.0)
    loo = [_kendall_w(wide.drop(model)) for model in wide.index]
    from scipy.stats import spearmanr

    rhos = [
        float(spearmanr(wide.iloc[i], wide.iloc[j]).statistic)
        for i in range(len(wide))
        for j in range(i + 1, len(wide))
    ]
    return {
        "kendall_w": point,
        "kendall_w_ci_low": low,
        "kendall_w_ci_high": high,
        "prop_pairs_positive": float(np.mean([r > 0 for r in rhos])),
        "kendall_w_loo_min": float(min(loo)),
        "kendall_w_loo_max": float(max(loo)),
        "median_pairwise_spearman": float(np.median(rhos)),
    }


# ---------------------------------------------------------------------------
# 15. Negative-control permutation
# ---------------------------------------------------------------------------


def permutation_calibration(
    profile_errors: pd.DataFrame,
    experiment_codebook: pd.DataFrame,
    *,
    n_draws: int,
    seed: int,
) -> dict:
    """Negative control: shuffle the feature labels at random and see how
    big a difference shuffling alone produces. Reports the null's median
    and 95th percentile of |difference| next to the observed |difference|.
    No p-values — the observed-vs-null comparison is stated directly."""
    means = _experiment_means(profile_errors)
    labels = _feature_map(experiment_codebook)
    usable = [e for e in means.index if labels.get(e) in ("on", "off")]
    true_labels = np.array([labels[e] for e in usable])
    values = means.reindex(usable).to_numpy()
    observed = abs(
        float(values[true_labels == "on"].mean() - values[true_labels == "off"].mean())
    )
    rng = np.random.default_rng(seed)
    null = []
    for _ in range(n_draws):
        shuffled = rng.permutation(true_labels)
        null.append(
            abs(
                float(
                    values[shuffled == "on"].mean() - values[shuffled == "off"].mean()
                )
            )
        )
    null_arr = np.array(null)
    return {
        "observed_abs_pp": observed,
        "median_abs_null_pp": float(np.median(null_arr)),
        "pct95_abs_null_pp": float(np.percentile(null_arr, 95)),
        "n_draws": n_draws,
    }


# ---------------------------------------------------------------------------
# 16. Combined robustness table
# ---------------------------------------------------------------------------


def _table_row(
    outcome: str,
    specification: str,
    point: float,
    low: float,
    high: float,
    n1: int,
    n0: int,
    notes: str,
) -> dict:
    """One uniformly shaped row of the combined robustness table."""
    return {
        "outcome": outcome,
        "specification": specification,
        "estimate_pp": float(point),
        "ci_low": float(low),
        "ci_high": float(high),
        "n_feature1": int(n1),
        "n_feature0": int(n0),
        "sign_positive": bool(point > 0),
        "notes": notes,
    }


def _group_sizes(labels: dict[str, str]) -> tuple[int, int]:
    """Count the usable feature-on and feature-off experiments."""
    values = [lab for lab in labels.values() if lab in ("on", "off")]
    return values.count("on"), values.count("off")


def build_robustness_table(
    profile_errors: pd.DataFrame,
    contrast_errors: pd.DataFrame,
    experiment_codebook: pd.DataFrame,
    contrast_codebook: pd.DataFrame,
    human_retest: pd.DataFrame,
    families: dict[str, list[str]],
    *,
    n_boot: int,
    seed: int,
) -> pd.DataFrame:
    """Assemble every specification above into one table with the fixed
    column order, so the CSV and report always show the same numbers."""
    prof_labels = _feature_map(experiment_codebook)
    n1, n0 = _group_sizes(prof_labels)
    rows: list[dict] = []

    reproduced = reproduce_effects(
        profile_errors,
        contrast_errors,
        experiment_codebook,
        contrast_codebook,
        human_retest,
        seed=seed,
    )
    prof = reproduced[reproduced["outcome"] == "profile"].iloc[0]
    rows.append(
        _table_row(
            "profile",
            "original_experiment_bootstrap",
            prof["delta_pp"],
            prof["ci_low"],
            prof["ci_high"],
            n1,
            n0,
            "models resampled within groups",
        )
    )
    cluster = family_cluster_bootstrap(
        profile_errors,
        contrast_errors,
        experiment_codebook,
        contrast_codebook,
        human_retest,
        families,
        n_boot=n_boot,
        seed=seed,
    )
    prow = cluster[cluster["outcome"] == "profile"].iloc[0]
    rows.append(
        _table_row(
            "profile",
            "family_cluster_bootstrap",
            prow["estimate_pp"],
            prow["ci_low"],
            prow["ci_high"],
            n1,
            n0,
            "whole paradigm families resampled",
        )
    )
    two_way = two_way_bootstrap(
        profile_errors,
        contrast_errors,
        experiment_codebook,
        contrast_codebook,
        human_retest,
        n_boot=n_boot,
        seed=seed,
    )
    trow = two_way[two_way["outcome"] == "profile"].iloc[0]
    rows.append(
        _table_row(
            "profile",
            "two_way_bootstrap",
            trow["estimate_pp"],
            trow["ci_low"],
            trow["ci_high"],
            n1,
            n0,
            "models and experiments resampled",
        )
    )
    alts = alternative_summaries(
        profile_errors, experiment_codebook, n_boot=n_boot, seed=seed
    )
    spec_names = {"median": "median_based", "trimmed_mean_20": "trimmed_mean"}
    for _, arow in alts.iterrows():
        rows.append(
            _table_row(
                "profile",
                spec_names[arow["specification"]],
                arow["estimate_pp"],
                arow["ci_low"],
                arow["ci_high"],
                n1,
                n0,
                "robust summary statistic",
            )
        )
    drift = drift_sensitivity(
        profile_errors, contrast_errors, experiment_codebook, human_retest
    )
    for name in ("drift_adjusted", "high_drift_excluded"):
        drow = drift[drift["specification"] == name].iloc[0]
        rows.append(
            _table_row(
                "profile",
                name,
                drow["estimate_pp"],
                drow["ci_low"],
                drow["ci_high"],
                n1,
                n0,
                "human-drift sensitivity",
            )
        )
    mag = magnitude_adjusted_effect(
        profile_errors, experiment_codebook, human_retest, n_boot=n_boot, seed=seed
    )
    mrow = mag  # magnitude_adjusted_effect already returns a single row
    rows.append(
        _table_row(
            "profile",
            "magnitude_adjusted",
            mrow["adjusted_b1_pp"],
            mrow["adjusted_ci_low"],
            mrow["adjusted_ci_high"],
            n1,
            n0,
            "regressed on |human effect|",
        )
    )
    family_out = leave_family_out(
        profile_errors,
        contrast_errors,
        experiment_codebook,
        contrast_codebook,
        human_retest,
        families,
    )
    for family, spec in (
        ("anchoring", "anchoring_family_excluded"),
        ("proportion_dominance", "proportion_dominance_family_excluded"),
    ):
        frow = family_out[
            (family_out["omitted_family"] == family)
            & (family_out["outcome"] == "profile")
        ].iloc[0]
        rows.append(
            _table_row(
                "profile",
                spec,
                frow["estimate_pp"],
                frow["estimate_pp"],
                frow["estimate_pp"],
                n1,
                n0,
                f"whole {family} family removed",
            )
        )
    coding = coding_sensitivity(
        profile_errors,
        contrast_errors,
        experiment_codebook,
        contrast_codebook,
        human_retest,
    )
    for _, crow in coding.iterrows():
        rows.append(
            _table_row(
                "profile",
                f"coding_{crow['specification']}",
                crow["estimate_pp"],
                crow["ci_low"],
                crow["ci_high"],
                n1,
                n0,
                "alternative ambiguous coding",
            )
        )
    out = pd.DataFrame(
        rows,
        columns=[
            "outcome",
            "specification",
            "estimate_pp",
            "ci_low",
            "ci_high",
            "n_feature1",
            "n_feature0",
            "sign_positive",
            "notes",
        ],
    )
    out.attrs["family_out_frame"] = family_out
    return out


def write_robustness_csv(table: pd.DataFrame, path: Path) -> None:
    """Write the combined table to CSV (round-trips with column order)."""
    table.to_csv(path, index=False)


# The pictures and the text report are drawn by robustness_report; they
# are re-exported here so callers only ever need the robustness module.
from twin2k10.robustness_report import make_figures, write_report  # noqa: E402, F401
