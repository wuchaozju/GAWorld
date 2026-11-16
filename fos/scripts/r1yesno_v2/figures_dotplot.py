# This file draws the paper's gain dot plot:
#   fig2_gain_dotplot — ONE picture with TWO panels (blinded left,
#     unblinded right) under one shared title. Each of the 16 models is one
#     row, top to bottom in the shared figure order — the same family
#     blocks and within-block order as the heatmap, minus the human rows
#     (the human group is the reference the gain is measured against, not a
#     data point). Family blocks are separated by slightly larger gaps. A
#     model's dot sits at the model's price-response gain G and takes the
#     model family block's fixed color; circles are dense models, triangles
#     are mixture-of-experts models. Row labels read "name — NNB dense" or
#     "name — NNB active MoE". A MoE's active count keeps one decimal when
#     it is fractional ("3.6B active MoE") and reads as a whole number when
#     it is not ("3B active MoE"); dense counts round to whole billions; a
#     user-provided approximate count keeps a "~" prefix.
#     Vertical reference lines mark G=0 (grey dotted, "No price response")
#     and G=1 (black dashed, "Human-sized response"); each label appears
#     once per panel, near the top, small and grey. Both panels share the
#     same x range, wide enough for every gain plus margin. One legend sits
#     above the figure (dense/MoE symbols and the four family-block
#     colors), and one footnote line sits below the axes. Nothing else is
#     written inside the panels: no point labels, no trend lines, no extra
#     annotations.
# Every model must have a G value for both conditions; anything missing
# raises an error instead of drawing a hole.

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from scripts.r1yesno_v2.figures_style import (
    BLINDED,
    BLOCK_COLORS,
    CONDITIONS,
    FAMILY_BLOCKS,
    PANEL_TITLES,
    UNBLINDED,
    apply_style,
    arch_marker,
    block_of_family,
    family_color,
    figure_row_order,
    save_figure,
)
from scripts.r1yesno_v2.registry import MODELS

EXPECTED_MODELS = 16
G_REFERENCE = 1.0  # model falls with price exactly as fast as humans
G_ZERO = 0.0  # model shows no price response
DOT_SIZE = 55
ROW_LABEL_FONTSIZE = 8.0
REF_LABEL_FONTSIZE = 7.0
REF_LABEL_COLOR = "0.35"
BLOCK_GAP = 0.7  # extra rows of space between family blocks
LABEL_HEADROOM = 1.6  # empty rows kept above the first dot for line labels
LIMIT_PAD_FRACTION = 0.12  # margin added on both ends of the x range
FIGURE_TITLE = "Strength of price response relative to humans"
X_LABEL = "Price-response gain (G)"
FOOTNOTE = "G = 1 means human-sized price sensitivity; G = 0 means no price response."
G_ZERO_LABEL = "No price response"
G_ONE_LABEL = "Human-sized response"


def _format_count(params_b: float) -> str:
    """Show a parameter count without losing precision to rounding.

    A whole number of billions prints as a plain integer ("3", "95"); a
    fractional count keeps one decimal ("3.6", "3.8") so an active count
    of 3.6 billion is never over-rounded to "4B".
    """
    if float(params_b).is_integer():
        return str(int(params_b))
    return f"{params_b:.1f}"


def _row_label(model_id: str) -> str:
    """Build one row label: name plus parameter count and architecture.

    Counts come from the registry (the same numbers written to
    model_metadata.csv). A MoE's active count keeps one decimal when
    fractional; dense counts round to whole billions. A user-provided
    approximate count keeps a "~" prefix so it is never read as exact.
    Raises ValueError when the active parameter count is missing.
    """
    info = MODELS[model_id]
    if info["active_params_b"] is None:
        raise ValueError(f"{model_id}: no active parameter count; cannot label the row")
    approximate = str(info["metadata_source"]).startswith("user-provided")
    prefix = "~" if approximate else ""
    name = info["short_name"]
    if info["architecture"] == "MoE":
        active = _format_count(float(info["active_params_b"]))
        return f"{name} — {prefix}{active}B active MoE"
    dense = round(float(info["active_params_b"]))
    return f"{name} — {prefix}{dense}B dense"


def _row_positions(ordered_ids: list[str]) -> list[float]:
    """Y position per row: unit spacing inside a block, larger gap between.

    Blocks are detected from the registry family of each model in the
    shared order, so the gaps always fall exactly on the block edges both
    figures share.
    """
    positions: list[float] = []
    y = 0.0
    previous_block: str | None = None
    for model_id in ordered_ids:
        block = block_of_family(MODELS[model_id]["family"])
        if previous_block is not None and block != previous_block:
            y += BLOCK_GAP
        positions.append(y)
        y += 1.0
        previous_block = block
    return positions


def _gain_table(table: pd.DataFrame, ordered_ids: list[str]) -> pd.DataFrame:
    """Pivot G by model and condition; fail loudly on any missing value."""
    pivoted = table.pivot_table(index="model_id", columns="condition", values="G_lin")
    for model_id in ordered_ids:
        for condition in CONDITIONS:
            missing = (
                model_id not in pivoted.index
                or pd.isna(pivoted.loc[model_id, condition])
            )
            if missing:
                raise ValueError(f"missing G value for {model_id} {condition}")
    return pivoted


def _gain_limits(pivoted: pd.DataFrame) -> tuple[float, float]:
    """Return the shared x-limits: every gain, 0 and 1, with a margin."""
    gains = pd.concat([pivoted[BLINDED], pivoted[UNBLINDED]])
    low = float(min(gains.min(), G_ZERO))
    high = float(max(gains.max(), G_REFERENCE))
    pad = LIMIT_PAD_FRACTION * (high - low)
    return low - pad, high + pad


def _add_reference_labels(ax: plt.Axes, limits: tuple[float, float]) -> None:
    """Write each reference line's label once, near the top, small and grey.

    "No price response" sits just right of the G=0 line (the panel edge
    leaves no room on its left); "Human-sized response" is right-aligned
    just left of the G=1 line. The two sit at slightly different heights so
    they can never collide.
    """
    span = limits[1] - limits[0]
    ax.text(
        G_ZERO + 0.02 * span, -LABEL_HEADROOM + 0.55, G_ZERO_LABEL,
        fontsize=REF_LABEL_FONTSIZE, color=REF_LABEL_COLOR, ha="left", va="center",
    )
    ax.text(
        G_REFERENCE - 0.02 * span, -LABEL_HEADROOM + 1.1, G_ONE_LABEL,
        fontsize=REF_LABEL_FONTSIZE, color=REF_LABEL_COLOR, ha="right", va="center",
    )


def _draw_panel(
    ax: plt.Axes,
    pivoted: pd.DataFrame,
    condition: str,
    ordered_ids: list[str],
    positions: list[float],
    limits: tuple[float, float],
) -> None:
    """Draw one condition's dots plus the two labelled reference lines."""
    for model_id, y in zip(ordered_ids, positions):
        info = MODELS[model_id]
        ax.scatter(
            float(pivoted.loc[model_id, condition]),
            y,
            s=DOT_SIZE,
            c=family_color(info["family"]),
            marker=arch_marker(info["architecture"]),
            edgecolors="black",
            linewidths=0.5,
            zorder=3,
        )
    ax.axvline(G_ZERO, color="grey", linestyle=":", linewidth=0.9)
    ax.axvline(G_REFERENCE, color="black", linestyle="--", linewidth=1.0)
    _add_reference_labels(ax, limits)
    ax.set_xlim(*limits)
    ax.set_ylim(positions[-1] + 0.8, -LABEL_HEADROOM)  # first model at the top
    ax.set_title(PANEL_TITLES[condition], fontsize=10)
    ax.set_xlabel(X_LABEL)


def _legend_handles() -> list:
    """Build the one shared legend: shapes first, then the block colors."""
    handles: list = [
        Line2D([], [], linestyle="none", marker="o", color="black",
               markersize=6, label="Dense"),
        Line2D([], [], linestyle="none", marker="^", color="black",
               markersize=6, label="MoE"),
    ]
    handles.extend(
        Patch(facecolor=BLOCK_COLORS[block], label=block) for block in FAMILY_BLOCKS
    )
    return handles


def fig2_gain_dotplot(table: pd.DataFrame, outdir: Path) -> list[Path]:
    """Figure 2: price-response gain G per model, blinded and unblinded.

    Two side-by-side panels sharing the heatmap's model order (16 rows, no
    human rows, larger gaps between family blocks). Each model is one dot
    at its G, colored by family block, circle for dense and triangle for
    MoE models. Reference lines at G=0 (grey dotted) and G=1 (black
    dashed) carry one small grey label each near the top; both panels
    share one x range fitted to the data with a margin. Legend above the
    figure, footnote below the axes. Raises ValueError when a model, G
    value, or parameter count is missing.
    """
    apply_style()
    ordered_ids = figure_row_order(sorted(table["model_id"].unique()))
    if len(ordered_ids) != EXPECTED_MODELS:
        raise ValueError(
            f"expected {EXPECTED_MODELS} models, found {len(ordered_ids)}: {ordered_ids}"
        )
    pivoted = _gain_table(table, ordered_ids)
    limits = _gain_limits(pivoted)
    positions = _row_positions(ordered_ids)
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 6.8), sharey=True)
    for ax, condition in zip(axes, CONDITIONS):
        _draw_panel(ax, pivoted, condition, ordered_ids, positions, limits)
    axes[0].set_yticks(positions)
    axes[0].set_yticklabels(
        [_row_label(model_id) for model_id in ordered_ids],
        fontsize=ROW_LABEL_FONTSIZE,
    )
    axes[1].tick_params(axis="y", labelleft=False)
    fig.suptitle(FIGURE_TITLE, fontsize=12, y=1.0)
    fig.tight_layout(rect=(0, 0.035, 1, 0.92))
    fig.legend(
        handles=_legend_handles(),
        loc="upper center",
        bbox_to_anchor=(0.5, 0.965),
        ncol=6,
        frameon=False,
        fontsize=8,
        columnspacing=1.6,
        handletextpad=0.4,
    )
    fig.text(0.01, 0.008, FOOTNOTE, fontsize=7.5, color="0.35", ha="left", va="bottom")
    return save_figure(fig, outdir, "fig2_gain_dotplot")
