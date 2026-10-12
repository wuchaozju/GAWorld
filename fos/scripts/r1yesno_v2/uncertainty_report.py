# This file turns the uncertainty tables into text outputs: it picks out the
# models whose G intervals exclude a reference value (in both bootstrap
# methods), names the models whose unblinding-delta intervals exclude zero,
# and writes the numbers-only SUMMARY section (interval statements only — no
# p-values, no significance language). Its functions:
#   models_excluding — model names whose interval sits wholly below, wholly
#     above, wholly outside, or straddling a reference value (both methods
#     must agree);
#   delta_models_excluding_zero — model names whose same-draw delta interval
#     excludes zero in both methods;
#   summary_section — the full SUMMARY text section;
#   append_summary — add (or replace) that section in SUMMARY-V2.md;
#   mirror_outputs — copy the CSVs and summary into the mirror directory.

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from scripts.r1yesno_v2.figures_style import BLINDED, CONDITIONS, UNBLINDED
from scripts.r1yesno_v2.registry import MODELS

METHODS = ("classical", "bayesian")
DELTAS = ("delta_beta", "delta_G")
PARTIAL_MODELS = ("gemma-4-31b-it-qat", "qwen3.8-max-0902")
SUMMARY_MARKER = "## Uncertainty (cluster & Bayesian bootstrap)"


def models_excluding(
    df: pd.DataFrame, metric: str, value: float, side: str
) -> list[str]:
    """Model display names whose interval for `metric` relates to `value`.

    Kept only when BOTH methods agree; `side` picks 'below' (interval wholly
    under the value), 'above' (wholly over), 'outside' (wholly on either
    side, i.e. the interval excludes the value) or 'straddle' (contains it).
    """
    selected: set[str] | None = None
    for method in METHODS:
        block = df.loc[(df["metric"] == metric) & (df["method"] == method)]
        if side == "below":
            hit = set(block.loc[block["hi"] < value, "display_name"])
        elif side == "above":
            hit = set(block.loc[block["lo"] > value, "display_name"])
        elif side == "outside":
            hit = set(
                block.loc[(block["lo"] > value) | (block["hi"] < value), "display_name"]
            )
        else:
            hit = set(
                block.loc[(block["lo"] < value) & (block["hi"] > value), "display_name"]
            )
        selected = hit if selected is None else selected & hit
    return sorted(selected or set())


def delta_models_excluding_zero(delta_df: pd.DataFrame, metric: str) -> list[str]:
    """Models whose same-draw delta interval excludes 0 in BOTH methods."""
    names: set[str] | None = None
    for method in METHODS:
        block = delta_df.loc[
            (delta_df["metric"] == metric) & (delta_df["method"] == method)
        ]
        hit = set(block.loc[(block["lo"] > 0) | (block["hi"] < 0), "display_name"])
        names = hit if names is None else names & hit
    return sorted(names or set())


def _interval_text(names: list[str]) -> str:
    """Comma-joined model names, or 'none' when the list is empty."""
    return ", ".join(names) if names else "none"


def summary_section(
    uncertainty_df: pd.DataFrame,
    delta_df: pd.DataFrame,
    cluster_log: dict[tuple[str, str, str], int],
) -> str:
    """Build the numbers-only SUMMARY section (interval statements, nothing else)."""
    lines = [SUMMARY_MARKER, ""]
    lines.append(
        "Uncertainty from 5,000 cluster-bootstrap draws (seed 42) and 5,000 Bayesian\n"
        "bootstrap draws (seed 43) per model, condition and method; resampling unit is\n"
        "the complete product x persona price curve; clusters = product x persona.\n"
        "Intervals are 2.5/97.5 percentiles (classical) and 95% credible intervals\n"
        "(Bayesian). Interval statements only."
    )
    for condition, label in ((BLINDED, "Blinded"), (UNBLINDED, "Unblinded")):
        block = uncertainty_df.loc[uncertainty_df["condition"] == condition]
        lines.append("")
        lines.append(f"**{label} condition.**")
        lines.append(
            f"- 95% G interval excludes 1 (both methods): "
            f"{_interval_text(models_excluding(block, 'G', 1.0, 'outside'))}"
        )
        lines.append(
            f"- G interval entirely below 0: "
            f"{_interval_text(models_excluding(block, 'G', 0.0, 'below'))}; "
            f"straddles 0: {_interval_text(models_excluding(block, 'G', 0.0, 'straddle'))}"
        )
    lines.append("")
    lines.append("**Unblinding effect (unblinded minus blinded, same resamples).**")
    lines.append(
        f"- delta_G interval excludes 0: "
        f"{_interval_text(delta_models_excluding_zero(delta_df, 'delta_G'))}"
    )
    lines.append(
        f"- delta_beta interval excludes 0: "
        f"{_interval_text(delta_models_excluding_zero(delta_df, 'delta_beta'))}"
    )
    return _cluster_caveat_lines(lines, cluster_log)


def _cluster_caveat_lines(
    lines: list[str], cluster_log: dict[tuple[str, str, str], int]
) -> str:
    """Add the partial-coverage cluster counts and close the section."""
    lines.append("")
    lines.append("**Cluster-count caveats.**")
    for model_id in PARTIAL_MODELS:
        counts = [
            f"{cond.replace('demographics_', '')}: "
            f"{cluster_log.get((model_id, cond, 'clusters'), 0)}"
            for cond in CONDITIONS
        ]
        note = (
            "(partial coverage; forced-choice draws kept whole per cluster)"
            if model_id == "qwen3.8-max-0902"
            else "(partial coverage)"
        )
        lines.append(
            f"- {MODELS[model_id]['short_name']}: n_clusters {'; '.join(counts)} {note}"
        )
    return "\n".join(lines) + "\n"


def append_summary(outdir: Path, section: str) -> Path:
    """Append (or replace) the uncertainty section of SUMMARY-V2.md."""
    summary_path = outdir / "SUMMARY-V2.md"
    text = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
    if SUMMARY_MARKER in text:
        text = text[: text.index(SUMMARY_MARKER)].rstrip() + "\n\n"
    summary_path.write_text(text.rstrip() + "\n\n" + section, encoding="utf-8")
    return summary_path


def mirror_outputs(outdir: Path, mirror: Path) -> None:
    """Copy the two uncertainty CSVs and the summary into the mirror dir."""
    (mirror / "csv").mkdir(parents=True, exist_ok=True)
    for name in (
        "model_price_response_uncertainty.csv",
        "unblinding_effect_uncertainty.csv",
    ):
        shutil.copy2(outdir / "csv" / name, mirror / "csv" / name)
    shutil.copy2(outdir / "SUMMARY-V2.md", mirror / "SUMMARY-V2.md")
