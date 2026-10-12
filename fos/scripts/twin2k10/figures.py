# This module makes the twin2k10 study's four publication figures (plus
# the tidy CSVs and a short report that back them) from numbers that the
# caller passes in memory — it never reads a run directory itself.
#
# What each part does, in plain words:
#   MODEL_ORDER / EXPERIMENT_ORDER — the fixed row/column order for every
#     figure and CSV (the 15 study models in family/generation order, the
#     16 experiments in registry order). Nothing is ever sorted
#     alphabetically or by result, so no ranking sneaks in.
#   normalize — moves one experiment's raw answer onto a 0-1 scale using
#     the experiment's own registered minimum and maximum. Answers stay
#     pointing the same way (bigger stays bigger); this is NOT a z-score.
#     If the registry has no rule (the two anchoring estimates), it says
#     so by returning None.
#   profile_error — how far a model's arm-by-arm answers sit from the
#     humans', averaged over the arms and times 100. Zero means the model
#     matched the human pattern exactly.
#   contrast_error — the same idea but for the pre-specified contrasts
#     (the "difference between two arms" numbers humans were predicted to
#     show).
#   profile_error_first_digit — the profile-error variant for experiments
#     where a model's answer is a whole distribution over the digits 0-9
#     (used for base_rate).
#   ErrorRow — one line of the result table: which model, which
#     experiment, which method was used, and the two error numbers.
#   compute_error_rows — builds that table for every model and experiment
#     found in the caller's data, applying the special cases
#     (false_consensus has no human contrast; anchoring has no
#     normalization rule; base_rate uses the first-digit variant).
#   human_test_retest_errors — the same two error formulas, but run
#     between the humans' two waves (wave1_3 vs wave4). This band shows
#     how much the same humans wobble between sittings; it is a
#     test-retest band, never a split-half band.
#   variance_components — splits the model-x-experiment error table into
#     three descriptive shares (model, experiment, leftover) that add up
#     to 1. Purely descriptive; no significance testing.
#   profile_contrast_correlation — for each model, how its profile error
#     moves with its contrast error across experiments (None when there
#     are too few points to say anything).
#   write_outputs — draws the four PNGs (300 dpi), writes the three CSVs
#     and report.txt into the caller's folder, and touches nothing else.

from __future__ import annotations

import csv
from pathlib import Path
from typing import Mapping

import matplotlib

matplotlib.use("Agg")  # never opens a window; safe on a headless run

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

# The test harness hands each test its own output folder by attaching it to
# the pytest module; that attachment only works when the slot already
# exists, so create an empty one here (the harness overwrites it per test).
try:
    import pytest  # noqa: E402

    if not hasattr(pytest, "out_dir"):
        pytest.out_dir = None
except ImportError:
    pass  # pytest is only needed when running under the test suite

from PIL import Image  # noqa: E402

# The 15 registry models in family/generation order (the registry's own
# listing order), pinned so figures never depend on dict or data order.
from twin2k10.figures_metrics import (  # noqa: F401 — re-exported
    EXPERIMENT_ORDER,
    MODEL_ORDER,
    ErrorRow,
    compute_error_rows,
    contrast_error,
    human_test_retest_errors,
    normalize,
    profile_contrast_correlation,
    profile_error,
    profile_error_first_digit,
    variance_components,
)
from twin2k10.figures_repair import (  # noqa: F401 — re-exported
    CONTRAST_ERROR_AXIS_LABEL,
    PROFILE_ERROR_AXIS_LABEL,
    write_repair_outputs,
)

# Dark = small error = close to humans; light = far away.
HEATMAP_CMAP = plt.get_cmap("Greys_r")

DPI = 300


def _set_png_dpi(path: Path, dpi: int) -> None:
    """Stamp the 300-dpi density tag (pHYs) onto a finished PNG; newer
    matplotlib versions no longer write it themselves."""
    with Image.open(path) as img:
        img.save(path, dpi=(dpi, dpi))


def _distribution_figure(
    rows: list[ErrorRow], key: str, title: str, path: Path, band: Mapping | None
) -> None:
    """One horizontal error-distribution figure: a dot for every
    (model, experiment) pair with data, rows in MODEL_ORDER, a
    median+IQR overlay, and the shaded test-retest band."""
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
    if band and labels:
        lows = [
            band[lab][key]
            for lab in labels
            if lab in band and band[lab].get(key) is not None
        ]
        if lows:
            ax.axvspan(
                min(lows),
                max(lows),
                color="grey",
                alpha=0.2,
                zorder=1,
                label="human test-retest",
            )
            ax.legend(loc="lower right")
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel(title)
    fig.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    _set_png_dpi(path, DPI)


def _heatmap_figure(rows: list[ErrorRow], key: str, title: str, path: Path) -> None:
    """One error heatmap: rows are models (MODEL_ORDER), columns are
    experiments with data; dark means a small error (close to humans)."""
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
        ax.imshow(matrix, cmap=HEATMAP_CMAP, aspect="auto", vmin=0.0)
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


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    """Write one tidy CSV with the given header and data rows."""
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def _report_text(
    rows: list[ErrorRow], band: Mapping | None, correlations: Mapping
) -> str:
    """Compose the short report: method notes, the anchoring exclusion,
    the base_rate variant actually used, the omitted pricing marker, and
    the test-retest band (never a split-half band)."""
    base_rate_used_first_digit = any(
        row.experiment == "base_rate" and row.method == "first_digit" for row in rows
    )
    if base_rate_used_first_digit:
        base_rate_note = (
            "- base_rate: the model side is a first-digit distribution, so "
            "its\n  rows use the first_digit profile-error variant."
        )
    else:
        base_rate_note = (
            "- base_rate: no first_digit_profile flag in the registry and "
            "the 0-100\n  estimate is unrecoverable from first-token digit "
            "mass, so its rows\n  use the arm_mean method and stay blank "
            "(NEEDS-OWNER)."
        )
    lines = [
        "Twin2k10 figures report",
        "",
        "Methods:",
        "- Profile Error: mean |model arm mean - human arm mean| on the",
        "  0-1 registry-normalized scale, x100 (arm_mean method).",
        "- Contrast Error: mean |model contrast - human contrast| x100.",
        "- Normalization uses each experiment's registered min/max only",
        "  (no z-scores, no effect-ratio metrics).",
        "",
        "Notes:",
        "- anchoring_redwood / anchoring_african: no registered 0-1",
        "  normalization rule (NEEDS-OWNER), so their profile errors are",
        "  excluded from figures and left blank in the CSVs.",
        base_rate_note,
        "- Pricing marker: no pricing experiment could be identified among",
        "  the 16 registry experiments, so no distinctive pricing marker is",
        "  drawn in the figures.",
        "- The shaded reference band is a human test-retest band (wave1_3",
        "  vs wave4, same metrics).",
    ]
    if band:
        lines.append("")
        lines.append("Human test-retest band (wave1_3 vs wave4):")
        for experiment, values in band.items():
            lines.append(
                f"  {experiment}: profile={values['profile_error']},"
                f" contrast={values['contrast_error']}"
            )
    lines.append("")
    lines.append(
        "Per-model profile-vs-contrast correlation (None = too few"
        " comparable experiments):"
    )
    for model, value in correlations.items():
        if model in {r.model for r in rows}:
            lines.append(f"  {model}: {value}")
    return "\n".join(lines) + "\n"


def write_outputs(
    rows: list[ErrorRow], out_dir: Path, test_retest: Mapping | None = None
) -> None:
    """Write EXACTLY the eight pinned outputs (4 PNGs, 3 CSVs, report.txt)
    into out_dir, and nothing anywhere else."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _distribution_figure(
        rows,
        "profile_error_blinded",
        "Profile error (blinded), 0 = humans",
        out_dir / "figure2_profile_error_distribution.png",
        test_retest,
    )
    _heatmap_figure(
        rows,
        "profile_error_blinded",
        "Profile error heatmap (dark = close to humans)",
        out_dir / "figure2_profile_error_heatmap.png",
    )
    _distribution_figure(
        rows,
        "contrast_error",
        "Contrast error, 0 = humans",
        out_dir / "figure3_contrast_error_distribution.png",
        test_retest,
    )
    _heatmap_figure(
        rows,
        "contrast_error",
        "Contrast error heatmap (dark = close to humans)",
        out_dir / "figure3_contrast_error_heatmap.png",
    )

    profile_rows = [
        [
            r.model,
            r.experiment,
            r.method,
            r.profile_error_blinded,
            r.profile_error_unblinded,
        ]
        for r in rows
        if r.profile_error_blinded is not None
    ]
    _write_csv(
        out_dir / "profile_error.csv",
        [
            "model",
            "experiment",
            "method",
            "profile_error_blinded",
            "profile_error_unblinded",
        ],
        profile_rows,
    )
    contrast_rows = [
        [r.model, r.experiment, r.method, r.contrast_error]
        for r in rows
        if r.contrast_error is not None
    ]
    _write_csv(
        out_dir / "contrast_error.csv",
        ["model", "experiment", "method", "contrast_error"],
        contrast_rows,
    )
    correlations = profile_contrast_correlation(rows)
    summary_rows = []
    for model in MODEL_ORDER:
        mine = [r for r in rows if r.model == model]
        if not mine:
            continue
        prof = [
            r.profile_error_blinded for r in mine if r.profile_error_blinded is not None
        ]
        con = [r.contrast_error for r in mine if r.contrast_error is not None]
        summary_rows.append(
            [
                model,
                float(np.mean(prof)) if prof else None,
                float(np.mean(con)) if con else None,
                correlations.get(model),
            ]
        )
    _write_csv(
        out_dir / "error_summary.csv",
        [
            "model",
            "mean_profile_error",
            "mean_contrast_error",
            "profile_contrast_correlation",
        ],
        summary_rows,
    )
    report = _report_text(rows, test_retest, correlations)
    (out_dir / "report.txt").write_text(report)
    # The TASK-2410 REPAIR outputs land next to the base eight.
    write_repair_outputs(rows, out_dir, test_retest)
