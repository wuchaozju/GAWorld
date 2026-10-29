# This module draws the pictures and writes the summary report for the
# task-difficulty analysis. It never computes any statistics itself —
# task_difficulty.py does the math and calls the functions here.
#   plot_forest          — dot-and-line picture of each feature effect and
#                          its confidence interval, with a zero line
#   plot_difficulty      — bar picture of each experiment's typical model
#                          error, with the human test-retest error marked
#   plot_similarity      — heatmap of how similarly each pair of
#                          experiments is ranked across models, sorted so
#                          look-alike experiments sit together
#   write_report         — the plain-text report answering the owner's
#                          seven questions, in order, confidence
#                          intervals only (never says "significant")

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

from pathlib import Path  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.cluster.hierarchy import leaves_list, linkage  # noqa: E402
from scipy.spatial.distance import squareform  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

DPI = 300


def plot_forest(effects: pd.DataFrame, path: Path) -> None:
    """One row per feature/outcome: the delta dot with its CI whiskers."""
    fig, ax = plt.subplots(figsize=(8, 1 + 0.4 * max(len(effects), 1)))
    labels = [f"{f} [{o}]" for f, o in zip(effects["feature"], effects["outcome"])]
    y = np.arange(len(effects))[::-1]
    low = effects["delta"] - effects["ci_low"]
    high = effects["ci_high"] - effects["delta"]
    ax.errorbar(effects["delta"], y, xerr=[low, high], fmt="o", capsize=3)
    ax.axvline(0.0, color="grey", linewidth=1)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.set_xlabel("effect on error (95% CI)")
    fig.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def plot_difficulty(diff: pd.DataFrame, human_retest: pd.DataFrame, path: Path) -> None:
    """Bars of median model error per experiment; a diamond marks the
    human test-retest error (the noise floor) on each bar."""
    human = dict(zip(human_retest["experiment"], human_retest["human_error"]))
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.arange(len(diff))
    ax.bar(x, diff["median"], yerr=None, color="#4477aa")
    ax.errorbar(
        x,
        diff["median"],
        yerr=[diff["median"] - diff["median_ci_low"], diff["median_ci_high"] - diff["median"]],
        fmt="none",
        capsize=3,
        color="black",
    )
    for i, exp in enumerate(diff["experiment"]):
        if exp in human:
            ax.plot(i, human[exp], "D", color="darkred", label="human test-retest")
    ax.set_xticks(x)
    ax.set_xticklabels(diff["experiment"], rotation=45, ha="right")
    ax.set_ylabel("median error")
    ax.legend(["human test-retest"], frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def _experiment_similarity(errors: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    """Experiment-by-experiment Spearman correlation of the error vectors
    across models, reordered by hierarchical clustering."""
    wide = errors.pivot_table(index="model", columns="experiment", values="error")
    wide = wide.dropna(axis=0, how="any")
    experiments = list(wide.columns)
    corr = np.eye(len(experiments))
    for i in range(len(experiments)):
        for j in range(i + 1, len(experiments)):
            rho = spearmanr(wide.iloc[:, i], wide.iloc[:, j]).statistic
            corr[i, j] = corr[j, i] = 0.0 if np.isnan(rho) else rho
    if len(experiments) > 1:
        order = leaves_list(linkage(squareform(1.0 - corr, checks=False)))
        corr = corr[np.ix_(order, order)]
        experiments = [experiments[k] for k in order]
    return experiments, corr


def plot_similarity(errors: pd.DataFrame, path: Path, title: str) -> None:
    """Clustered heatmap: darker cells mean the two experiments are
    ranked more differently across models."""
    experiments, corr = _experiment_similarity(errors)
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.imshow(corr, cmap="RdBu_r", vmin=-1.0, vmax=1.0)
    ax.set_xticks(range(len(experiments)))
    ax.set_xticklabels(experiments, rotation=45, ha="right")
    ax.set_yticks(range(len(experiments)))
    ax.set_yticklabels(experiments)
    ax.set_title(title)
    fig.colorbar(ax.images[0], ax=ax, label="Spearman rho")
    fig.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def _fmt(effect_row: pd.Series) -> str:
    """One human-readable line for a feature effect estimate."""
    status = effect_row["estimate_status"]
    return (
        f"  {effect_row['feature']} [{effect_row['outcome']}]: "
        f"delta = {effect_row['delta']:.3f} "
        f"(95% CI {effect_row['ci_low']:.3f} to {effect_row['ci_high']:.3f}, "
        f"{effect_row['ci_method']}); LOO range "
        f"{effect_row['loo_min_delta']:.3f} to {effect_row['loo_max_delta']:.3f}; "
        f"sign stable: {bool(effect_row['sign_stable'])}; status: {status}"
    )


def write_report(
    variance: pd.DataFrame,
    agreement: dict,
    difficulty: pd.DataFrame,
    effects: pd.DataFrame,
    alternatives: dict,
    human_note: str,
) -> str:
    """The whole plain-text report. Answers the owner's seven questions
    in order, using confidence intervals only."""
    lines: list[str] = ["Shared task difficulty — T2K10 analysis", ""]
    lines.append("Question 1: How much of the error is about the task itself?")
    for _, row in variance.iterrows():
        lines.append(
            f"  {row['component']}: {row['share']:.3f} "
            f"(95% CI {row['ci_low']:.3f} to {row['ci_high']:.3f})"
        )
    lines.append(
        f"  Model agreement: median Spearman rho = {agreement['median_rho']:.3f} "
        f"(95% CI {agreement['ci_low']:.3f} to {agreement['ci_high']:.3f}), "
        f"Kendall W = {agreement['kendall_w']:.3f} "
        f"(95% CI {agreement['kendall_w_ci_low']:.3f} to "
        f"{agreement['kendall_w_ci_high']:.3f})"
    )
    lines.append("")
    lines.append("Question 2: Which experiments are hardest for models?")
    for _, row in difficulty.iterrows():
        lines.append(
            f"  {row['experiment']}: median error {row['median']:.3f}, "
            f"excess over human test-retest {row['excess_error']:.3f}"
        )
    lines.append(f"  {human_note}")
    lines.append("")
    lines.append("Question 3: Do designed task features predict profile errors?")
    lines += [_fmt(r) for _, r in effects[effects["outcome"] == "profile"].iterrows()]
    lines.append("")
    lines.append("Question 4: Do the same features predict contrast errors?")
    lines += [_fmt(r) for _, r in effects[effects["outcome"] == "contrast"].iterrows()]
    lines.append("")
    lines.append("Question 5: Which effects survive removing the human drift?")
    lines += [_fmt(r) for _, r in effects[effects["outcome"] == "excess"].iterrows()]
    lines.append("")
    lines.append("Question 6: Do models agree on which experiments are alike?")
    lines.append("  See task_similarity_profile.png and task_similarity_contrast.png")
    lines.append("  (clustered heatmaps of experiment-by-experiment Spearman rho).")
    lines.append("")
    lines.append("Question 7: Could bigger human-model gaps explain the errors?")
    lines.append(
        f"  Contrast error change per +10pp human gap: "
        f"{alternatives['slope_per_10pp']:.3f} "
        f"(95% CI {alternatives['slope_ci_low']:.3f} to "
        f"{alternatives['slope_ci_high']:.3f})"
    )
    lines.append(
        f"  Spearman rho (contrast error vs |human gap|): "
        f"{alternatives['spearman_rho']:.3f} "
        f"(95% CI {alternatives['spearman_ci_low']:.3f} to "
        f"{alternatives['spearman_ci_high']:.3f})"
    )
    lines.append("")
    lines.append("All uncertainty statements are bootstrap confidence intervals.")
    return "\n".join(lines) + "\n"
