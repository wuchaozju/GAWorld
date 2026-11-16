# This module adds the TASK-2410 REPAIR outputs on top of the base
# figures: the two "complete" CSVs (every computable row, including an
# explicit HUMAN row per experiment), four ..._FIXED.png figures whose
# axis labels state the unit and what zero means, a diagnostic summary
# (the model/experiment/residual variance split, the humans' median and
# interquartile drift, and one Profile-vs-effect correlation per model),
# and a short repair report that opens with the exact scope counts.
# figures.py imports and re-exports everything from here.

from __future__ import annotations

import csv
from pathlib import Path
from typing import Mapping

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

from twin2k10.figures_metrics import (
    EXPERIMENT_ORDER,
    MODEL_ORDER,
    ErrorRow,
    profile_contrast_correlation,
    variance_components,
)


# Stamp the 300-dpi density tag (pHYs) onto a finished PNG; newer
# matplotlib versions no longer write it themselves.
def _set_png_dpi(path: Path, dpi: int) -> None:
    with Image.open(path) as img:
        img.save(path, dpi=(dpi, dpi))


# Owner-pinned axis wording: the unit (percentage points) and the meaning
# of zero (an exact match) are stated on every FIXED figure.
PROFILE_ERROR_AXIS_LABEL = (
    "Profile error vs. human reference (percentage points; 0 = exact match)"
)
CONTRAST_ERROR_AXIS_LABEL = (
    "Experimental-effect error (percentage points; 0 = exact human effect)"
)

DPI = 300


def _human_profile_points(test_retest: Mapping | None) -> list[tuple[str, float]]:
    """One (experiment, drift) point per experiment where the humans'
    wave1_3-vs-wave4 profile drift is computable. Single-arm experiments
    are skipped: one number is not a pattern to drift."""
    if not test_retest:
        return []
    return [
        (experiment, entry["profile_error"])
        for experiment, entry in test_retest.items()
        if entry.get("profile_error") is not None and entry.get("n_arms", 0) >= 2
    ]


def _human_contrast_points(test_retest: Mapping | None) -> list[tuple[str, float]]:
    """One (experiment, drift) point per experiment where the humans'
    wave1_3-vs-wave4 effect drift is computable."""
    if not test_retest:
        return []
    return [
        (experiment, entry["contrast_error"])
        for experiment, entry in test_retest.items()
        if entry.get("contrast_error") is not None
    ]


def _median_iqr(values: list[float]) -> tuple[float | None, float | None]:
    """The median and the interquartile range of a list of errors."""
    if not values:
        return None, None
    median = float(np.median(values))
    q1, q3 = float(np.percentile(values, 25)), float(np.percentile(values, 75))
    return median, q3 - q1


def _fixed_distribution_figure(
    rows: list[ErrorRow],
    key: str,
    xlabel: str,
    path: Path,
    human_points: list[tuple[str, float]],
) -> None:
    """The FIXED error-distribution figure: one dot per (model,
    experiment) pair with data, plus an explicit HUMAN test-retest row
    (median diamond + IQR bar) at the bottom."""
    fig, ax = plt.subplots(figsize=(8, 6))
    labels: list[str] = []
    for y, model in enumerate(MODEL_ORDER):
        values = [
            getattr(r, key)
            for r in rows
            if r.model == model and getattr(r, key) is not None
        ]
        if not values:
            continue
        labels.append(model)
        rng = np.random.default_rng(y)
        jitter = rng.uniform(-0.15, 0.15, size=len(values))
        ax.scatter(values, y + jitter, s=18, alpha=0.7, zorder=3)
        median = float(np.median(values))
        q1, q3 = float(np.percentile(values, 25)), float(np.percentile(values, 75))
        ax.plot([q1, q3], [y, y], color="tab:blue", lw=6, alpha=0.3, zorder=2)
        ax.plot([median], [y], marker="D", color="tab:blue", zorder=4)
    human_y = len(labels)
    if human_points:
        values = [v for _, v in human_points]
        median, q1, q3 = (
            float(np.median(values)),
            float(np.percentile(values, 25)),
            float(np.percentile(values, 75)),
        )
        ax.plot(
            [q1, q3], [human_y, human_y], color="tab:red", lw=6, alpha=0.3, zorder=2
        )
        ax.plot([median], [human_y], marker="D", color="tab:red", zorder=4)
        labels.append("HUMAN (test-retest)")
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel(xlabel)
    fig.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    _set_png_dpi(path, DPI)


def _fixed_heatmap_figure(
    rows: list[ErrorRow], key: str, title: str, path: Path
) -> None:
    """The FIXED error heatmap: models in the pinned order, experiments
    with data as columns; dark means a small error (close to humans)."""
    experiments = [
        e
        for e in EXPERIMENT_ORDER
        if any(r.experiment == e and getattr(r, key) is not None for r in rows)
    ]
    matrix = np.full((len(MODEL_ORDER), len(experiments)), np.nan)
    for r in rows:
        value = getattr(r, key)
        if value is None or r.experiment not in experiments:
            continue
        matrix[MODEL_ORDER.index(r.model), experiments.index(r.experiment)] = value
    fig, ax = plt.subplots(figsize=(10, 6))
    if experiments:
        ax.imshow(matrix, cmap=plt.get_cmap("Greys_r"), aspect="auto", vmin=0.0)
    ax.set_xticks(range(len(experiments)))
    ax.set_xticklabels(experiments, rotation=45, ha="right")
    ax.set_yticks(range(len(MODEL_ORDER)))
    ax.set_yticklabels(MODEL_ORDER)
    ax.set_title(title)
    if experiments:
        fig.colorbar(ax.images[0], ax=ax, label="error (0 = humans)")
    fig.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    _set_png_dpi(path, DPI)


def _write_complete_csvs(
    rows: list[ErrorRow], out_dir: Path, test_retest: Mapping | None
) -> None:
    """The two complete CSVs: every computable model row plus one HUMAN
    (test-retest) row per experiment, through the same pipeline."""
    profile_header = [
        "model",
        "experiment",
        "profile_error_blinded",
        "profile_error_unblinded",
        "method",
    ]
    profile_rows = [
        [
            r.model,
            r.experiment,
            r.profile_error_blinded,
            r.profile_error_unblinded,
            r.method,
        ]
        for r in rows
        if r.profile_error_blinded is not None
    ]
    for experiment, value in _human_profile_points(test_retest):
        profile_rows.append(["HUMAN", experiment, value, value, "test_retest"])
    _write_csv(out_dir / "profile_error_complete.csv", profile_header, profile_rows)

    contrast_header = ["model", "experiment", "contrast_error", "method"]
    contrast_rows = [
        [r.model, r.experiment, r.contrast_error, r.method]
        for r in rows
        if r.contrast_error is not None
    ]
    for experiment, value in _human_contrast_points(test_retest):
        contrast_rows.append(["HUMAN", experiment, value, "test_retest"])
    _write_csv(out_dir / "contrast_error_complete.csv", contrast_header, contrast_rows)


def _write_diagnostic_summary(
    rows: list[ErrorRow], out_dir: Path, test_retest: Mapping | None
) -> tuple[float | None, float | None]:
    """diagnostic_summary.csv: the model/experiment/residual variance
    shares, the humans' median + IQR drift, and per-model correlations.
    Returns the human profile median and IQR for the report."""
    out: list[list] = []
    for name, value in variance_components(rows).items():
        out.append(["variance_share", name, value])
    prof_values = [v for _, v in _human_profile_points(test_retest)]
    con_values = [v for _, v in _human_contrast_points(test_retest)]
    prof_median, prof_iqr = _median_iqr(prof_values)
    con_median, con_iqr = _median_iqr(con_values)
    out.append(["human_test_retest", "median_profile_error", prof_median])
    out.append(["human_test_retest", "iqr_profile_error", prof_iqr])
    out.append(["human_test_retest", "median_contrast_error", con_median])
    out.append(["human_test_retest", "iqr_contrast_error", con_iqr])
    for model, corr in profile_contrast_correlation(rows).items():
        out.append(["per_model_correlation", model, corr])
    _write_csv(out_dir / "diagnostic_summary.csv", ["section", "name", "value"], out)
    return prof_median, prof_iqr


def _repair_report(
    rows: list[ErrorRow],
    test_retest: Mapping | None,
    prof_median: float | None,
    prof_iqr: float | None,
) -> str:
    """The repair report: opens with the exact scope (models x
    experiments), then what was missing, what was fixed, and what stays
    non-comparable — in plain words."""
    lines = [
        f"Figures repair report: {len(MODEL_ORDER)} models x"
        f" {len(EXPERIMENT_ORDER)} experiments.",
        "",
        "What was missing:",
        "- Effect errors existed only for the four experiments already on",
        "  the 0-1 scale; raw-scale experiments were silently dropped.",
        "- The anchoring experiments had no computable Profile or effect",
        "  error at all, and no HUMAN test-retest row existed anywhere.",
        "",
        "What was fixed:",
        "- Every human arm is put on its comparable 0-1 observable FIRST",
        "  (registry min/max normalization, or the bounded anchor-choice",
        "  share for the anchoring experiments), and the effect error is",
        "  the gap between the two 0-1 effects, x100 (percentage points).",
        "- The anchoring Profile and effect errors now come from the",
        "  bounded 'did the answerer pick more?' choice share (0-1).",
        "- Every complete CSV gains an explicit HUMAN row: how far the",
        "  humans themselves drift between wave1_3 and wave4, through the",
        "  SAME pipeline",
        f"  (human median profile drift: {prof_median}, IQR: {prof_iqr}).",
        "",
        "What stays non-comparable (documented, not silently blank):",
        "- base_rate: not computable — the model side is first-token",
        "  first-digit mass only and the humans' comparable first-digit",
        "  distribution is unavailable, so it is excluded from the",
        "  Profile and effect figures.",
        "- The anchoring FREE NUMERIC ESTIMATE is unbounded (no instrument",
        "  bounds exist) and the LLM side stores no multi-digit numbers,",
        "  so it stays excluded everywhere; only the bounded anchor",
        "  choice is used.",
        "- false_consensus: no pre-specified human effect, so no effect",
        "  error exists for it.",
    ]
    if test_retest:
        lines.append("")
        lines.append("Human test-retest drift (wave1_3 vs wave4), per experiment:")
        for experiment, entry in test_retest.items():
            lines.append(
                f"  {experiment}: profile={entry.get('profile_error')},"
                f" contrast={entry.get('contrast_error')}"
            )
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    """Write one tidy CSV with the given header and data rows."""
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def write_repair_outputs(
    rows: list[ErrorRow], out_dir: Path, test_retest: Mapping | None = None
) -> None:
    """Write the eight REPAIR outputs (2 complete CSVs, 4 FIXED PNGs,
    diagnostic_summary.csv, repair_report.txt) into out_dir, next to the
    base figures — and nothing anywhere else."""
    out_dir = Path(out_dir)
    _write_complete_csvs(rows, out_dir, test_retest)
    _fixed_distribution_figure(
        rows,
        "profile_error_blinded",
        PROFILE_ERROR_AXIS_LABEL,
        out_dir / "figure2_profile_error_distribution_FIXED.png",
        _human_profile_points(test_retest),
    )
    _fixed_heatmap_figure(
        rows,
        "profile_error_blinded",
        PROFILE_ERROR_AXIS_LABEL,
        out_dir / "figure2_profile_error_heatmap_FIXED.png",
    )
    _fixed_distribution_figure(
        rows,
        "contrast_error",
        CONTRAST_ERROR_AXIS_LABEL,
        out_dir / "figure3_contrast_error_distribution_FIXED.png",
        _human_contrast_points(test_retest),
    )
    _fixed_heatmap_figure(
        rows,
        "contrast_error",
        CONTRAST_ERROR_AXIS_LABEL,
        out_dir / "figure3_contrast_error_heatmap_FIXED.png",
    )
    prof_median, prof_iqr = _write_diagnostic_summary(rows, out_dir, test_retest)
    (out_dir / "repair_report.txt").write_text(
        _repair_report(rows, test_retest, prof_median, prof_iqr)
    )
