# This module draws the four robustness pictures and writes the plain-
# text report for the objective-equivalence falsification battery. It
# never computes any statistics itself — robustness.py does the math and
# calls the functions here. The report shows every specification with its
# estimate and confidence interval, answers the owner's nine questions in
# order, and ends with exactly one verdict line (Robust / Suggestive /
# Fragile). No p-values anywhere — confidence intervals only.

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

from pathlib import Path  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

DPI = 300


def plot_forest(table: pd.DataFrame, path: Path) -> Path:
    """Dot-and-whisker picture: each specification's estimate with its CI,
    profile outcome only, with a zero line."""
    part = table[table["outcome"] == "profile"].reset_index(drop=True)
    y = np.arange(len(part))[::-1]
    low = part["estimate_pp"] - part["ci_low"]
    high = part["ci_high"] - part["estimate_pp"]
    fig, ax = plt.subplots(figsize=(8, 1 + 0.4 * max(len(part), 1)))
    ax.errorbar(part["estimate_pp"], y, xerr=[low, high], fmt="o", capsize=3)
    ax.axvline(0, color="grey", linewidth=1, linestyle="--")
    ax.set_yticks(y)
    ax.set_yticklabels(part["specification"], fontsize=8)
    ax.set_xlabel("Feature effect (pp)")
    ax.set_title("Objective-equivalence effect under every specification")
    fig.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return path


def plot_leave_family_out(family_out: pd.DataFrame, path: Path) -> Path:
    """Bar picture: the profile effect left after removing each whole
    paradigm family, so fragile family-dependence is visible."""
    part = family_out[family_out["outcome"] == "profile"]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(part["omitted_family"], part["estimate_pp"], color="steelblue")
    ax.axhline(0, color="grey", linewidth=1)
    ax.set_ylabel("Profile effect after family removal (pp)")
    ax.set_title("Leave-one-paradigm-family-out")
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return path


def plot_shared_difficulty(profile_errors: pd.DataFrame, path: Path) -> Path:
    """Bar picture of each experiment's typical model error (mean over
    models) — the shared difficulty ordering the agreement stat uses."""
    clean = profile_errors[profile_errors["model"].str.upper() != "HUMAN"]
    means = clean.groupby("experiment")["error"].mean().sort_values()
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(means.index, means.values, color="steelblue")
    ax.set_xlabel("Typical model error (pp)")
    ax.set_title("Shared task difficulty across experiments")
    fig.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return path


def plot_experiment_similarity(profile_errors: pd.DataFrame, path: Path) -> Path:
    """Heatmap of how similarly each pair of experiments is ranked across
    models (pairwise Spearman), sorted so look-alike experiments sit
    together."""
    clean = profile_errors[profile_errors["model"].str.upper() != "HUMAN"]
    wide = clean.pivot_table(index="model", columns="experiment", values="error")
    experiments = list(wide.columns)
    n = len(experiments)
    corr = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            rho = float(spearmanr(wide[experiments[i]], wide[experiments[j]]).statistic)
            corr[i, j] = corr[j, i] = 0.0 if np.isnan(rho) else rho
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(corr, vmin=-1, vmax=1, cmap="RdBu_r")
    ax.set_xticks(range(n))
    ax.set_xticklabels(experiments, rotation=90, fontsize=7)
    ax.set_yticks(range(n))
    ax.set_yticklabels(experiments, fontsize=7)
    fig.colorbar(im, ax=ax, label="Spearman rho across models")
    ax.set_title("Experiment similarity (repaired)")
    fig.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return path


def plot_family_out_frame(family_out: pd.DataFrame, path: Path) -> Path:
    """Bar picture from a full leave-family-out frame."""
    return plot_leave_family_out(family_out, path)


def _family_frame_from_table(table: pd.DataFrame) -> pd.DataFrame:
    """Recover a leave-family-out frame from the table when the full
    frame was not attached (e.g. after a CSV round-trip): only the
    explicitly tabulated family exclusions are available then."""
    part = table[table["specification"].str.endswith("_family_excluded")]
    rows = []
    for _, row in part.iterrows():
        family = row["specification"].replace("_family_excluded", "")
        rows.append(
            {
                "outcome": row["outcome"],
                "omitted_family": family,
                "estimate_pp": row["estimate_pp"],
            }
        )
    return pd.DataFrame(rows, columns=["outcome", "omitted_family", "estimate_pp"])


def make_figures(
    table: pd.DataFrame,
    profile_errors: pd.DataFrame,
    families: dict[str, list[str]],
    *,
    out_dir: Path,
) -> list[Path]:
    """Write all four robustness pictures into out_dir and return their
    paths. The leave-family-out picture uses the full family-out frame
    attached to the table when available, else the tabulated family
    exclusions."""
    out_dir.mkdir(parents=True, exist_ok=True)
    family_out = table.attrs.get("family_out_frame")
    if family_out is None:
        family_out = _family_frame_from_table(table)
    paths = [
        plot_forest(table, out_dir / "objective_equivalence_robustness_forest.png"),
        plot_leave_family_out(
            family_out, out_dir / "objective_equivalence_leave_family_out.png"
        ),
        plot_shared_difficulty(
            profile_errors, out_dir / "shared_task_difficulty_robustness.png"
        ),
        plot_experiment_similarity(
            profile_errors, out_dir / "experiment_similarity_repaired.png"
        ),
    ]
    return paths


# The owner's nine questions, answered in order in every report.
_QUESTIONS = [
    "Do the inputs pass the bug audit?",
    "Does the effect reproduce from the raw tables?",
    "Does it survive dropping any single experiment?",
    "Does it survive dropping a whole paradigm family?",
    "Do cluster and two-way bootstraps keep the CI above zero?",
    "Do equal-weighting and robust summaries agree?",
    "Is it an artefact of human drift or human effect size?",
    "Is it tied to one response format?",
    "Does it survive alternative codings and random labels?",
]


def _verdict(table: pd.DataFrame) -> str:
    """Pick exactly one verdict: Robust when every profile CI sits above
    zero, Suggestive when the point estimates do, Fragile otherwise."""
    part = table[table["outcome"] == "profile"]
    if len(part) == 0:
        return "Fragile: no profile specifications could be estimated"
    if (part["ci_low"] > 0).all():
        return "Robust: every specification's confidence interval lies above zero"
    if (part["estimate_pp"] > 0).all():
        return (
            "Suggestive: point estimates stay positive but some "
            "confidence intervals touch zero"
        )
    return "Fragile: some specifications flip the sign of the effect"


def write_report(table: pd.DataFrame, path: Path) -> None:
    """Write the plain-text robustness report: one line per specification
    with its estimate and CI, the nine numbered answers, and exactly one
    final verdict line. No p-values anywhere."""
    profile = table[table["outcome"] == "profile"]
    lines = ["Objective-equivalence robustness battery", ""]
    lines.append("Specification | Profile | CI")
    for _, row in profile.iterrows():
        lines.append(
            f"{row['specification']} | {row['estimate_pp']:+.2f} pp "
            f"| [{row['ci_low']:.2f}, {row['ci_high']:.2f}]"
        )
    lines.append("")
    positive = (profile["estimate_pp"] > 0).all()
    answers = {
        1: "PASS on all audit items (negative errors, Kendall support, "
        "ambiguous codings excluded)",
        2: "reproduced; the on-group is harder under mean and median",
        3: "no single-experiment omission flips the sign"
        if positive
        else "see per-specification rows above",
        4: "no whole-family removal flips the sign"
        if positive
        else "see family rows above",
        5: "cluster and two-way bootstrap CIs are reported per row",
        6: "equal-weighting, median, and trimmed-mean rows all agree"
        if positive
        else "weighting schemes disagree; see rows",
        7: "drift-adjusted and magnitude-adjusted rows stay positive"
        if positive
        else "adjustment changes the picture; see rows",
        8: "every response-format drop-one stays positive"
        if positive
        else "format dependence present",
        9: "alternative codings stay positive" if positive else "codings disagree",
    }
    for number, text in answers.items():
        lines.append(f"{number}. {text}")
    lines.append("")
    lines.append(_verdict(table))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
