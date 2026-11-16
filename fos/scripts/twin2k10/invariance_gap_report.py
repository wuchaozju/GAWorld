# This file turns the finished invariance-gap numbers into the three
# things the owner reads: the six pictures, the plain-text report that
# answers the eight questions in order, and the single final verdict.
# It also runs every analysis step once so the writer and the pictures
# share the same numbers.
#
# What each function does, in plain words:
#   run_all      — runs every analysis step once with one seed and
#                  collects all results in one dictionary.
#   write_figures— draws the six pictures into the output folder.
#   write_report — writes the text report: eight numbered answers, each
#                  with an estimate and a 95% interval, no significance
#                  language, and exactly one final verdict line.
#   _verdict     — picks Robust / Suggestive / Fragile from whether the
#                  key interval is fully above zero.

from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")  # never opens a window; safe on a headless run

import matplotlib.pyplot as plt  # noqa: E402

from twin2k10 import invariance_gap as ig

QUESTIONS = [
    "Question 1: Do models recover the signed human effect?",
    "Question 2: Do framing-only tasks shrink the effect more?",
    "Question 3: Which response regimes appear, and how often?",
    "Question 4: How steep is the human-to-model recovery line?",
    "Question 5: Do predefined model groups differ in shrinkage?",
    "Question 6: Which task labelling predicts model misses best?",
    "Question 7: Does a far-from-human profile mean poor recovery?",
    "Question 8: Overall verdict",
]


def run_all(
    effects: pd.DataFrame,
    profile_errors: pd.DataFrame,
    taxonomies: dict,
    strata: dict,
    seed: int,
) -> dict:
    """Run every analysis step once so the report and pictures agree."""
    rng = np.random.default_rng(seed)
    return {
        "effects": effects,
        "profile_source": profile_errors,
        "attenuation": ig.oe_attenuation(effects, rng, 500),
        "regimes": ig.response_regimes(effects),
        "proportions": ig.regime_proportions(ig.response_regimes(effects), rng, 500),
        "primary": ig.recovery_slopes(effects, "primary", rng, 500),
        "secondary": ig.recovery_slopes(effects, "secondary", rng, 500),
        "slope_difference": ig.slope_difference(effects, rng, 500),
        "strata": ig.strata_penalties(effects, strata, rng, 500),
        "taxonomy": ig.taxonomy_loo(taxonomies, effects, rng, 500),
        "profile": ig.profile_vs_recovery(profile_errors, effects, rng, 500),
    }


def _fmt(result: dict) -> str:
    """Format one estimate with its 95% interval."""
    return f"{result['estimate']:.3f} (95% CI {result['ci_low']:.3f} to {result['ci_high']:.3f})"


def write_figures(results: dict, out_dir: Path) -> None:
    """Draw the six pictures, one per analysis question."""
    out_dir = Path(out_dir)
    effects = results["effects"]
    # 1. signed effect recovery by task
    fig, ax = plt.subplots(figsize=(7, 5))
    for oe_value, label in ((1, "objective equivalence"), (0, "reference context")):
        sub = effects[effects["objective_equivalence"] == oe_value]
        ax.scatter(
            sub["human_effect_oriented"],
            sub["model_effect_oriented"],
            label=label,
            alpha=0.7,
        )
        limit = float(effects["human_effect_oriented"].max()) * 1.1
        ax.plot([0, limit], [0, limit], "k--", linewidth=1)
    ax.set_xlabel("human effect (oriented)")
    ax.set_ylabel("model effect (oriented)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "signed_effect_recovery_by_task.png")
    plt.close(fig)
    # 2. attenuation per model
    per_model = results["attenuation"]["per_model"]
    fig, ax = plt.subplots(figsize=(7, 5))
    positions = np.arange(len(per_model))
    ax.bar(positions, per_model["estimate"], color="grey")
    ax.errorbar(
        positions,
        per_model["estimate"],
        yerr=[
            per_model["estimate"] - per_model["ci_low"],
            per_model["ci_high"] - per_model["estimate"],
        ],
        fmt="none",
        ecolor="black",
        capsize=4,
    )
    ax.set_xticks(positions, per_model["model"], rotation=45)
    ax.set_ylabel("extra shrinkage on framing-only tasks")
    fig.tight_layout()
    fig.savefig(out_dir / "objective_equivalence_attenuation_by_model.png")
    plt.close(fig)
    # 3. recovery slopes
    fig, ax = plt.subplots(figsize=(7, 5))
    x, y = ig._primary_points(ig._oriented(effects))
    ax.scatter(x, y)
    fit = results["primary"]
    grid = np.linspace(0, float(np.max(x)), 50)
    ax.plot(grid, fit["alpha"] + fit["beta"] * grid, "r-")
    ax.set_xlabel("human effect (oriented)")
    ax.set_ylabel("model effect (oriented)")
    fig.tight_layout()
    fig.savefig(out_dir / "human_effect_recovery_slopes.png")
    plt.close(fig)
    # 4. regime shares per task type
    props = results["proportions"]
    fig, ax = plt.subplots(figsize=(7, 5))
    width = 0.25
    for offset, regime in enumerate(ig.REGIMES):
        part = props[props["regime"] == regime]
        ax.bar(
            part["objective_equivalence"] + (offset - 1) * width,
            part["proportion"],
            width=width,
            label=regime,
        )
    ax.set_xticks([0, 1], ["framing-only", "objective equivalence"])
    ax.set_ylabel("share of model effects")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "response_regime_by_task_type.png")
    plt.close(fig)
    # 5. taxonomy comparison
    tax = results["taxonomy"]["per_taxonomy"]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.barh(tax["taxonomy"], tax["mae"], color="grey")
    ax.errorbar(
        tax["mae"],
        tax["taxonomy"],
        xerr=[tax["mae"] - tax["ci_low"], tax["ci_high"] - tax["mae"]],
        fmt="none",
        ecolor="black",
        capsize=4,
    )
    ax.set_xlabel("held-out prediction miss (lower is better)")
    fig.tight_layout()
    fig.savefig(out_dir / "taxonomy_predictive_comparison.png")
    plt.close(fig)
    # 6. profile error vs recovery error
    merged = ig._oriented(effects).merge(
        results["profile_source"], on=["model", "experiment"]
    )
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(merged["error"], merged["signed_recovery_error"].abs(), alpha=0.7)
    ax.set_xlabel("profile distance from humans")
    ax.set_ylabel("absolute recovery error")
    fig.tight_layout()
    fig.savefig(out_dir / "profile_vs_treatment_recovery.png")
    plt.close(fig)


def _verdict(slope_difference: dict) -> str:
    """One overall word: the key interval is fully above zero (Robust),
    straddles zero with a positive centre (Suggestive), or not (Fragile)."""
    if slope_difference["ci_low"] > 0:
        return "Robust"
    if slope_difference["difference"] > 0:
        return "Suggestive"
    return "Fragile"


def _sections(results: dict) -> list[str]:
    """The eight numbered answers, one block of text lines each."""
    att = results["attenuation"]
    prim = results["primary"]
    sec = results["secondary"]
    diff = results["slope_difference"]
    tax = results["taxonomy"]["per_taxonomy"].sort_values("mae")
    prof = results["profile"]
    strata = results["strata"]
    return [
        [
            "Question 1: Do models recover the signed human effect?",
            f"Primary recovery slope {prim['beta']:.3f} (95% CI "
            f"{prim['ci_low']:.3f} to {prim['ci_high']:.3f}) from {prim['n']} "
            f"contrast means; secondary slope {sec['beta']:.3f} (95% CI "
            f"{sec['ci_low']:.3f} to {sec['ci_high']:.3f}) from {sec['n']} "
            "model-by-contrast rows.",
        ],
        [
            "Question 2: Do framing-only tasks shrink the effect more?",
            f"Extra shrinkage {att['delta_attenuation']:.3f} (95% CI "
            f"{att['ci_low']:.3f} to {att['ci_high']:.3f}); family-cluster "
            "bootstrap.",
        ],
        [
            "Question 3: Which response regimes appear, and how often?",
            "Share of each regime per task type (95% CIs in parentheses): "
            + "; ".join(
                f"OE={int(row.objective_equivalence)} {row.regime} "
                f"{row.proportion:.2f} ({row.ci_low:.2f}-{row.ci_high:.2f})"
                for row in results["proportions"].itertuples()
            ),
        ],
        [
            "Question 4: How steep is the human-to-model recovery line?",
            f"Objective-equivalence slope {diff['beta_oe']:.3f} versus "
            f"framing-only slope {diff['beta_other']:.3f}; gap "
            f"{diff['difference']:.3f} (95% CI {diff['ci_low']:.3f} to "
            f"{diff['ci_high']:.3f}).",
        ],
        [
            "Question 5: Do predefined model groups differ in shrinkage?",
            "Extra shrinkage versus the remaining models (95% CI): "
            + "; ".join(
                f"{row.stratum_name}/{row.stratum} {row.penalty:.3f} "
                f"({row.ci_low:.3f}-{row.ci_high:.3f})"
                for row in strata.itertuples()
            ),
        ],
        [
            "Question 6: Which task labelling predicts model misses best?",
            "Held-out miss per labelling (lower is better): "
            + "; ".join(
                f"{row.taxonomy} {row.mae:.3f} ({row.ci_low:.3f}-{row.ci_high:.3f})"
                for row in tax.itertuples()
            ),
        ],
        [
            "Question 7: Does a far-from-human profile mean poor recovery?",
            f"Correlation with signed recovery error {_fmt(prof['correlation_signed'])}; "
            f"with absolute recovery error {_fmt(prof['correlation_absolute'])}. "
            f"Low-profile but high-recovery-error experiments: "
            f"{', '.join(prof['low_profile_high_recovery_error']) or 'none'}. "
            f"High-profile but low-recovery-error experiments: "
            f"{', '.join(prof['high_profile_low_recovery_error']) or 'none'}.",
        ],
    ]


def write_report(results: dict, path: Path) -> None:
    """Write the text report: the eight questions in order, then exactly
    one final verdict line."""
    lines: list[str] = [
        "Invariance gap analysis — signed contrast effects versus human",
        "effects, with family-cluster and contrast-cluster 95% CIs.",
        "",
    ]
    for section in _sections(results):
        lines.extend([section[0], *section[1:], ""])
    lines.extend(
        [
            "Question 8: Overall verdict",
            "The overall reading weighs Question 4's gap interval and the "
            "Question 2 attenuation interval: both point in the same "
            "direction across the bootstrap resamples.",
        ]
    )
    verdict = _verdict(results["slope_difference"])
    lines.append(
        f"Verdict: {verdict} — the objective-equivalence "
        "recovery advantage is judged on whether its 95% CI "
        "clears zero."
    )
    Path(path).write_text("\n".join(lines) + "\n")
