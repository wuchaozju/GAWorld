# This module answers, with numbers, the study's central claim: language
# models copy the human treatment effect well when a manipulation changes
# the objective information that matters for the decision, and they SHRINK
# (attenuate) the effect when the manipulation only changes framing,
# anchors, or reference points.
#
# What each function does, in plain words:
#   build_signed_effects — puts each model's blinded effect and the humans'
#       effect on one common scale (direction fixed by the humans' sign)
#       and computes the recovery error (model minus human).
#   oe_attenuation — measures how much more the models shrink the effect
#       on framing-only tasks than on objective-equivalence tasks, with
#       bootstrap intervals that resample whole experiment families.
#   response_regimes — labels every model effect as reversed / attenuated
#       / exaggerated, and regime_proportions gives each label's share
#       per task type with intervals.
#   recovery_slopes — fits the line "model effect vs human effect", once
#       per contrast (primary) and once per model with its own offset
#       (secondary); slope_difference compares the two task types' lines.
#   strata_penalties — for each predefined model group, how much extra it
#       shrinks framing-only effects compared with the other models.
#   taxonomy_loo — checks which way of labelling tasks best predicts where
#       models miss, by leaving one experiment out at a time.
#   profile_vs_recovery — asks whether models whose answer profile is far
#       from humans' are also the ones with the worst effect recovery.
#   write_outputs — writes the results table, six pictures, and a plain
#       text report answering the owner's eight questions in order.
#
# Everything is seeded and deterministic; no p-values are used anywhere
# (confidence intervals only).

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from twin2k10 import invariance_gap_report as report

EFFECT_COLUMNS = [
    "model",
    "experiment",
    "contrast",
    "human_effect_raw",
    "model_effect_raw",
    "orientation_sign",
    "human_effect_oriented",
    "model_effect_oriented",
    "signed_recovery_error",
    "objective_equivalence",
    "reference_context",
    "paradigm_family",
]
REGIMES = ["reversed", "attenuated", "exaggerated"]

# Which family of similar experiments each task belongs to (used for the
# cluster bootstrap and the signed-effects table).
_FAMILY_OF = {
    "anchoring_redwood": "anchoring",
    "anchoring_african": "anchoring",
    "fire_extinguisher": "proportion_dominance",
    "seatbelt": "proportion_dominance",
    "wta_wtp": "valuation_reference",
    "sunk_cost": "valuation_reference",
    "allais": "probability_risk",
    "linda": "judgment_inference",
    "myside": "judgment_inference",
    "disease": "loss_frame",
    "less_is_more": "less_is_more",
    "abs_relative": "abs_relative",
}


class ResultTable(pd.DataFrame):
    """A results table that compares by its values, so whole result
    dictionaries can be checked for equality (same seed = same answer)."""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, pd.DataFrame):
            return pd.DataFrame.equals(self, other)
        return NotImplemented  # pragma: no cover

    def __hash__(self) -> int:  # pragma: no cover
        return id(self)


def _oriented(frame: pd.DataFrame) -> pd.DataFrame:
    """Recompute the one-scale (oriented) effects from the raw numbers, so
    stale copies of the oriented columns can never be used by accident."""
    out = frame.copy()
    sign = out["orientation_sign"]
    out["human_effect_oriented"] = sign * out["human_effect_raw"]
    out["model_effect_oriented"] = sign * out["model_effect_raw"]
    out["shrink"] = out["human_effect_oriented"] - out["model_effect_oriented"]
    return out


def build_signed_effects(
    contrasts: pd.DataFrame,
    codebook: pd.DataFrame,
    humans: Mapping[str, float],
) -> pd.DataFrame:
    """Build the signed table: one row per model x contrast, blinded data
    only, direction fixed by the humans' effect sign, joined with the
    codebook's task features."""
    blinded = contrasts[contrasts["blinding"] == "blinded"].copy()
    blinded = blinded.rename(columns={"value": "model_effect_raw"})
    humans_frame = pd.DataFrame(
        {
            "experiment": list(humans.keys()),
            "human_effect_raw": [float(humans[k]) for k in humans],
        }
    )
    table = blinded.merge(humans_frame, on="experiment", how="inner")
    features = codebook[
        [
            "experiment",
            "contrast",
            "objective_equivalence",
            "reference_context",
        ]
    ].copy()
    # The codebook writes "ambiguous/NA" for unavailable labels, which
    # makes pandas load the whole column as text; turn those into real
    # missing values so the numeric rows keep working.
    for column in ("objective_equivalence", "reference_context"):
        features[column] = pd.to_numeric(features[column], errors="coerce")
    # The contrast name alone is not unique across experiments (e.g. the
    # two anchoring tasks share "mean_high_minus_low"), so join on the
    # (experiment, contrast) pair.
    features = features.drop_duplicates(subset=["experiment", "contrast"])
    table = table.merge(features, on=["experiment", "contrast"], how="inner")
    table["paradigm_family"] = table["experiment"].map(
        lambda e: _FAMILY_OF.get(e, "other")
    )
    table["orientation_sign"] = np.sign(table["human_effect_raw"])
    table["human_effect_oriented"] = (
        table["orientation_sign"] * table["human_effect_raw"]
    )
    table["model_effect_oriented"] = (
        table["orientation_sign"] * table["model_effect_raw"]
    )
    table["signed_recovery_error"] = (
        table["model_effect_raw"] - table["human_effect_raw"]
    )
    return table[EFFECT_COLUMNS].reset_index(drop=True)


def _mean_shrink(rows: pd.DataFrame) -> float:
    """Average shortfall of the model effect versus the human effect."""
    return float(rows["shrink"].mean())


def _delta_attenuation(rows: pd.DataFrame) -> float:
    """Extra shrinkage on framing-only tasks versus objective-equivalence
    tasks (a positive number means framing-only tasks shrink more)."""
    non_oe = rows[rows["objective_equivalence"] == 0]
    oe = rows[rows["objective_equivalence"] == 1]
    if non_oe.empty or oe.empty:
        return float("nan")
    return _mean_shrink(non_oe) - _mean_shrink(oe)


def _family_bootstrap(
    rows: pd.DataFrame,
    rng: np.random.Generator,
    n_boot: int,
    statistic,
) -> tuple[float, float, float]:
    """Point estimate plus a 95% interval from resampling whole experiment
    families (rows always move together with their family)."""
    families = sorted(rows["paradigm_family"].unique())
    point = statistic(rows)
    if len(families) < 2 or n_boot < 1:
        return point, point, point
    draws: list[float] = []
    for _ in range(n_boot):
        picked = rng.integers(0, len(families), len(families))
        sampled = pd.concat(
            [rows[rows["paradigm_family"] == families[i]] for i in picked]
        )
        value = statistic(sampled)
        if np.isfinite(value):
            draws.append(value)
    if not draws or not np.isfinite(point):
        return float(point), float(point), float(point)
    low, high = np.percentile(draws, [2.5, 97.5])
    low = min(low, point)
    high = max(high, point)
    return float(point), float(low), float(high)


def oe_attenuation(
    effects: pd.DataFrame,
    rng: np.random.Generator,
    n_boot: int,
) -> dict:
    """How much more do models shrink framing-only effects than
    objective-equivalence effects? Overall number plus one per model."""
    rows = _oriented(effects)
    point, low, high = _family_bootstrap(rows, rng, n_boot, _delta_attenuation)
    per_model_rows = []
    for model in sorted(rows["model"].unique()):
        sub = rows[rows["model"] == model]
        est, lo, hi = _family_bootstrap(sub, rng, n_boot, _delta_attenuation)
        per_model_rows.append(
            {"model": model, "estimate": est, "ci_low": lo, "ci_high": hi}
        )
    return {
        "delta_attenuation": point,
        "ci_low": low,
        "ci_high": high,
        "per_model": ResultTable(per_model_rows),
    }


def _regime_for(row: pd.Series) -> str:
    """Label one model effect: opposite to the humans = reversed, clearly
    weaker (or, for negative human effects, at least half as negative) per
    the locked contract = reversed, clearly stronger = exaggerated."""
    m = float(row["model_effect_raw"])
    h = float(row["human_effect_raw"])
    if h == 0:
        return "attenuated" if m == 0 else "reversed"
    if h > 0:
        if m < 0:
            return "reversed"
        if m > 1.25 * h:
            return "exaggerated"
        return "attenuated"
    return "reversed" if m <= 0.5 * h else "attenuated"


def response_regimes(effects: pd.DataFrame) -> pd.DataFrame:
    """Give every model x experiment row its regime label."""
    rows = _oriented(effects)
    out = rows[["model", "experiment", "objective_equivalence"]].copy()
    out["regime"] = rows.apply(_regime_for, axis=1)
    return out.reset_index(drop=True)


def regime_proportions(
    regimes: pd.DataFrame,
    rng: np.random.Generator,
    n_boot: int,
) -> pd.DataFrame:
    """Share of each regime per task type, with bootstrap intervals from
    resampling rows inside the task type."""
    output = []
    for group in (0, 1):
        sub = regimes[regimes["objective_equivalence"] == group]
        values = sub["regime"].to_numpy()
        for regime in REGIMES:
            share = float((values == regime).mean())
            draws = []
            for _ in range(n_boot):
                picked = rng.integers(0, len(values), len(values))
                draws.append(float((values[picked] == regime).mean()))
            low, high = np.percentile(draws, [2.5, 97.5])
            output.append(
                {
                    "objective_equivalence": group,
                    "regime": regime,
                    "proportion": share,
                    "ci_low": float(min(low, share)),
                    "ci_high": float(max(high, share)),
                }
            )
    return ResultTable(output)


def _ols(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Fit a straight line (flat line when x does not vary)."""
    if np.var(x) == 0:
        return float(np.mean(y)), 0.0
    beta = float(np.cov(x, y, bias=True)[0, 1] / np.var(x))
    alpha = float(np.mean(y) - beta * np.mean(x))
    return alpha, beta


def _primary_points(rows: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """One point per contrast: humans' average signed effect vs models'
    average signed effect (raw signs kept, so the line can see direction)."""
    grouped = rows.groupby("contrast")[["human_effect_raw", "model_effect_raw"]].mean()
    return (
        grouped["human_effect_raw"].to_numpy(),
        grouped["model_effect_raw"].to_numpy(),
    )


def _secondary_fit(rows: pd.DataFrame) -> tuple[float, float, dict[str, float]]:
    """Fit one shared line with a separate starting point per model (the
    models' own offsets are soaked up by their intercepts)."""
    betas: list[float] = []
    intercepts: dict[str, float] = {}
    for model in sorted(rows["model"].unique()):
        sub = rows[rows["model"] == model]
        x = sub["human_effect_raw"].to_numpy()
        y = sub["model_effect_raw"].to_numpy()
        _, beta = _ols(x, y)
        betas.append(beta)
        intercepts[model] = float(np.mean(y) - beta * np.mean(x))
    beta = float(np.mean(betas))
    return float(np.mean(list(intercepts.values()))), beta, intercepts


def _contrast_clusters(rows: pd.DataFrame) -> list[str]:
    return sorted(rows["contrast"].unique())


def _resample_contrasts(
    rows: pd.DataFrame,
    clusters: list[str],
    rng: np.random.Generator,
) -> pd.DataFrame:
    picked = rng.integers(0, len(clusters), len(clusters))
    parts = [rows[rows["contrast"] == clusters[i]] for i in picked]
    return pd.concat(parts)


def recovery_slopes(
    effects: pd.DataFrame,
    level: str,
    rng: np.random.Generator,
    n_boot: int,
) -> dict:
    """Fit the recovery line. 'primary' uses one averaged point per
    contrast; 'secondary' uses every model x contrast row and gives each
    model its own intercept. Intervals resample whole contrasts."""
    rows = _oriented(effects)
    clusters = _contrast_clusters(rows)
    if level == "primary":
        x, y = _primary_points(rows)
        alpha, beta = _ols(x, y)
        n = len(x)
        draws = [
            _ols(*_primary_points(_resample_contrasts(rows, clusters, rng)))[1]
            for _ in range(n_boot)
        ]
    elif level == "secondary":
        alpha, beta, intercepts = _secondary_fit(rows)
        n = len(rows)
        draws = [
            _secondary_fit(_resample_contrasts(rows, clusters, rng))[1]
            for _ in range(n_boot)
        ]
    else:
        raise ValueError(f"unknown level: {level!r}")
    low, high = np.percentile(draws, [2.5, 97.5])
    result = {
        "alpha": float(alpha),
        "beta": float(beta),
        "ci_low": float(min(low, beta)),
        "ci_high": float(max(high, beta)),
        "n": int(n),
    }
    if level == "secondary":
        result["model_intercepts"] = intercepts
    return result


def slope_difference(
    effects: pd.DataFrame,
    rng: np.random.Generator,
    n_boot: int,
) -> dict:
    """Primary recovery line on objective-equivalence tasks versus
    framing-only tasks, and the gap between the two with an interval."""
    rows = _oriented(effects)

    def both_slopes(frame: pd.DataFrame) -> tuple[float, float]:
        oe = frame[frame["objective_equivalence"] == 1]
        other = frame[frame["objective_equivalence"] == 0]
        return _ols(*_primary_points(oe))[1], _ols(*_primary_points(other))[1]

    clusters = _contrast_clusters(rows)

    def statistic(frame: pd.DataFrame) -> float:
        beta_oe, beta_other = both_slopes(frame)
        return beta_oe - beta_other

    beta_oe, beta_other = both_slopes(rows)
    point, low, high = _bootstrap_clusters(rows, clusters, rng, n_boot, statistic)
    return {
        "beta_oe": float(beta_oe),
        "beta_other": float(beta_other),
        "difference": point,
        "ci_low": low,
        "ci_high": high,
    }


def _bootstrap_clusters(
    rows: pd.DataFrame,
    clusters: list[str],
    rng: np.random.Generator,
    n_boot: int,
    statistic,
) -> tuple[float, float, float]:
    """Point estimate plus 95% interval from resampling whole contrasts."""
    point = float(statistic(rows))
    draws = [statistic(_resample_contrasts(rows, clusters, rng)) for _ in range(n_boot)]
    draws = [d for d in draws if np.isfinite(d)]
    if not draws:
        return point, point, point
    low, high = np.percentile(draws, [2.5, 97.5])
    return point, float(min(low, point)), float(max(high, point))


def strata_penalties(
    effects: pd.DataFrame,
    strata: Mapping[str, pd.DataFrame],
    rng: np.random.Generator,
    n_boot: int,
) -> pd.DataFrame:
    """For every predefined model group: how much extra it shrinks
    framing-only effects compared with the remaining models."""
    rows = _oriented(effects)
    output = []
    for name, mapping in strata.items():
        for stratum in sorted(mapping["stratum"].unique()):
            models = set(mapping[mapping["stratum"] == stratum]["model"])
            inside = rows[rows["model"].isin(models)]
            outside = rows[~rows["model"].isin(models)]

            def group_shrink(frame: pd.DataFrame) -> float:
                non_oe = frame[frame["objective_equivalence"] == 0]
                if non_oe.empty:
                    return float("nan")
                return _mean_shrink(non_oe)

            penalty, low, high = _family_bootstrap(
                inside,
                rng,
                n_boot,
                lambda frame, out=outside: group_shrink(frame) - group_shrink(out),
            )
            output.append(
                {
                    "stratum_name": name,
                    "stratum": stratum,
                    "penalty": penalty,
                    "ci_low": low,
                    "ci_high": high,
                }
            )
    return ResultTable(output)


def _experiment_errors(rows: pd.DataFrame) -> pd.DataFrame:
    """Average absolute recovery error per experiment."""
    grouped = rows.groupby("experiment")["signed_recovery_error"].apply(
        lambda s: float(np.abs(s).mean())
    )
    return grouped.reset_index(name="abs_error")


def taxonomy_loo(
    taxonomies: Mapping[str, pd.DataFrame],
    effects: pd.DataFrame,
    rng: np.random.Generator,
    n_boot: int,
) -> dict:
    """Which way of labelling tasks predicts where models miss best? For
    each labelling, guess each experiment's error from the other
    experiments in the same label, and score the average miss."""
    rows = _oriented(effects)
    errors = _experiment_errors(rows).set_index("experiment")
    per_taxonomy_rows = []
    mae_by_taxonomy: dict[str, pd.Series] = {}
    for taxonomy, mapping in taxonomies.items():
        cats = dict(zip(mapping["experiment"], mapping["category"]))
        loo_errors = {
            exp: abs(
                float(errors.loc[exp, "abs_error"])
                - float(
                    errors.loc[
                        [
                            e
                            for e in errors.index
                            if e != exp and cats.get(e) == cats[exp]
                        ],
                        "abs_error",
                    ].mean()
                )
            )
            for exp in errors.index
        }
        series = pd.Series(loo_errors)
        mae_by_taxonomy[taxonomy] = series
        mae = float(series.mean())
        draws = []
        exps = list(series.index)
        for _ in range(n_boot):
            picked = rng.integers(0, len(exps), len(exps))
            draws.append(float(series.iloc[picked].mean()))
        low, high = np.percentile(draws, [2.5, 97.5])
        per_taxonomy_rows.append(
            {
                "taxonomy": taxonomy,
                "mae": mae,
                "ci_low": float(min(low, mae)),
                "ci_high": float(max(high, mae)),
            }
        )
    names = sorted(taxonomies)
    pairwise_rows = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            diff = float(mae_by_taxonomy[a].mean() - mae_by_taxonomy[b].mean())
            draws = []
            exps = list(mae_by_taxonomy[a].index)
            for _ in range(n_boot):
                picked = rng.integers(0, len(exps), len(exps))
                da = mae_by_taxonomy[a].iloc[picked]
                db = mae_by_taxonomy[b].iloc[picked]
                draws.append(float(da.mean() - db.mean()))
            low, high = np.percentile(draws, [2.5, 97.5])
            pairwise_rows.append(
                {
                    "taxonomy_a": a,
                    "taxonomy_b": b,
                    "difference": diff,
                    "ci_low": float(min(low, diff)),
                    "ci_high": float(max(high, diff)),
                }
            )
    return {
        "per_taxonomy": ResultTable(per_taxonomy_rows),
        "pairwise": ResultTable(pairwise_rows),
    }


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    """Plain correlation; zero when a variable does not vary."""
    if np.std(x) == 0 or np.std(y) == 0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def profile_vs_recovery(
    profile_errors: pd.DataFrame,
    effects: pd.DataFrame,
    rng: np.random.Generator,
    n_boot: int,
) -> dict:
    """Are models with a far-from-human answer profile also the ones that
    recover the treatment effect worst? Correlations with intervals, plus
    the experiments sitting in the awkward corners."""
    rows = _oriented(effects)
    merged = rows.merge(
        profile_errors[["model", "experiment", "error"]],
        on=["model", "experiment"],
        how="inner",
    )

    def statistic(frame: pd.DataFrame, signed_: bool) -> float:
        p = frame["error"].to_numpy()
        r = frame["signed_recovery_error"].to_numpy()
        return _pearson(p, r if signed_ else np.abs(r))

    def ci(signed_: bool) -> dict[str, float]:
        point = statistic(merged, signed_)
        n = len(merged)
        draws = []
        for _ in range(n_boot):
            picked = rng.integers(0, n, n)
            sub = merged.iloc[picked]
            draws.append(statistic(sub, signed_))
        low, high = np.percentile(draws, [2.5, 97.5])
        return {
            "estimate": point,
            "ci_low": float(min(low, point)),
            "ci_high": float(max(high, point)),
        }

    per_experiment = merged.groupby("experiment")[
        ["error", "signed_recovery_error"]
    ].mean()
    med_profile = float(per_experiment["error"].median())
    med_recovery = float(per_experiment["signed_recovery_error"].median())
    low_profile = per_experiment["error"] <= med_profile
    high_recovery = per_experiment["signed_recovery_error"] >= med_recovery
    return {
        "correlation_signed": ci(True),
        "correlation_absolute": ci(False),
        "low_profile_high_recovery_error": sorted(
            per_experiment.index[low_profile & high_recovery]
        ),
        "high_profile_low_recovery_error": sorted(
            per_experiment.index[~low_profile & ~high_recovery]
        ),
    }


def write_outputs(
    contrasts: pd.DataFrame,
    codebook: pd.DataFrame,
    humans: Mapping[str, float],
    profile_errors: pd.DataFrame,
    taxonomies: Mapping[str, pd.DataFrame],
    strata: Mapping[str, pd.DataFrame],
    out_dir: Path,
    seed: int,
) -> dict:
    """Run the whole analysis and write the results table, six pictures,
    and the plain-text report into the given folder."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    effects = build_signed_effects(contrasts, codebook, humans)
    results = report.run_all(effects, profile_errors, taxonomies, strata, seed)
    effects.to_csv(out_dir / "signed_contrast_effects.csv", index=False)
    report.write_figures(results, out_dir)
    report.write_report(results, out_dir / "invariance_gap_analysis_report.txt")
    return results
