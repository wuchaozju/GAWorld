# This file draws the paper's overview heatmap:
#   fig1_heatmap_purchase_probability — ONE picture with TWO panels
#     (blinded left, unblinded right) under one shared title. Rows come in
#     four family blocks (Qwen, Gemma, Granite, Other), and each block
#     STARTS with a repeat of the human reference row — 20 rows in all.
#     Every repeated human row gets a bold "Human" label and a thin black
#     border around the row in both panels, so repeats are unmistakable.
#     Blocks are separated by a visibly larger vertical gap than the normal
#     row spacing, and each block's name is written vertically on the
#     far-left margin, clear of the row labels. Columns are the ten price
#     levels from 20% to 200% of the regular price; a cell's color is the
#     share of "yes, I would buy" answers at that price, averaged over the
#     40 products. Both panels share one color scale from 0 to 1 with a
#     single colorbar labelled "Probability of purchase". A price level
#     with no data at all is drawn light grey and one note line below the
#     axes says so. No architecture symbols and no other text are written
#     inside the panels.
# Every panel must hold exactly the 16 registered models; anything else
# raises an error instead of quietly drawing an incomplete picture.

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from scripts.r1yesno_v2.figures_style import (
    BLINDED,
    CONDITIONS,
    PANEL_TITLES,
    apply_style,
    figure_blocks,
    figure_row_order,
    purchase_cmap,
    save_figure,
)
from scripts.r1yesno_v2.load import PRIMARY_PRICE_MAX, PRIMARY_PRICE_MIN
from scripts.r1yesno_v2.registry import MODELS

EXPECTED_MODELS = 16
EXPECTED_ROWS = 20  # 4 repeated human rows + 16 models
EXPECTED_PRICE_COLUMNS = 10
X_TICK_PRICES = (20.0, 60.0, 100.0, 140.0, 180.0, 200.0)
BLOCK_GAP = 0.9  # extra empty rows of space between family blocks
ROW_LABEL_FONTSIZE = 7.5
FAMILY_LABEL_FONTSIZE = 9
FAMILY_LABEL_COLOR = "0.35"
FAMILY_LABEL_PAD_PT = 10  # points of clear space left of the row labels
HUMAN_ROW_LINEWIDTH = 1.1
NO_DATA_NOTE = "grey = no data"
COLORBAR_LABEL = "Probability of purchase"
FIGURE_TITLE = "Purchase response to price across models"


def _primary_prices(human_cells: pd.DataFrame) -> list[float]:
    """Return the ten primary price levels (20% to 200%), sorted ascending.

    The human reference table defines the column grid; anything outside the
    primary range (the free 0% rows) is excluded. Raises ValueError when
    the count is not exactly ten.
    """
    primary = human_cells.loc[
        human_cells["price"].between(PRIMARY_PRICE_MIN, PRIMARY_PRICE_MAX)
    ]
    prices = sorted(float(price) for price in primary["price"].unique())
    if len(prices) != EXPECTED_PRICE_COLUMNS:
        raise ValueError(
            f"expected {EXPECTED_PRICE_COLUMNS} primary price levels, found {prices}"
        )
    return prices


def _level_means(cells: pd.DataFrame, prices: list[float]) -> np.ndarray:
    """Average one subject's cells over products: one value per price level.

    A price level the subject has no cell for becomes NaN (drawn grey).
    """
    means = cells.groupby("price")["p"].mean()
    return np.array([means.get(price, np.nan) for price in prices], dtype=float)


def _display_rows() -> tuple[list[tuple[str | None, str]], list[int], list[str]]:
    """Lay out the 20 rows top to bottom, plus where each block starts.

    Each family block begins with a repeat of the human reference row
    (model id None, label "Human") followed by the block's models with
    their short names. Returns the rows, the row index each block starts
    at, and the block names in the same order.
    """
    rows: list[tuple[str | None, str]] = []
    block_starts: list[int] = []
    block_names: list[str] = []
    for name, model_ids in figure_blocks():
        block_starts.append(len(rows))
        block_names.append(name)
        rows.append((None, "Human"))
        rows.extend((model_id, MODELS[model_id]["short_name"]) for model_id in model_ids)
    return rows, block_starts, block_names


def _row_edges(row_count: int, block_starts: list[int]) -> np.ndarray:
    """Y edges for the heatmap: unit-height rows with gaps between blocks.

    The extra gap is inserted after the last row of every block except the
    final one, so the four family blocks read as clearly separated groups.
    """
    gap_after_rows = {start - 1 for start in block_starts[1:]}
    edges = [0.0]
    for row in range(row_count):
        step = 1.0 + (BLOCK_GAP if row in gap_after_rows else 0.0)
        edges.append(edges[-1] + step)
    return np.array(edges)


def _condition_matrix(
    cells_by_model_cond: dict[tuple[str, str], pd.DataFrame],
    human_cells: pd.DataFrame,
    condition: str,
    display_rows: list[tuple[str | None, str]],
    prices: list[float],
) -> np.ndarray:
    """Stack one panel's color matrix: repeated human rows plus the models.

    Every human row carries the same human data. Raises ValueError when a
    model has no cells for this condition.
    """
    human = human_cells.loc[human_cells["condition"] == condition]
    human_row = _level_means(human.rename(columns={"p_human": "p"}), prices)
    rows = []
    for model_id, _ in display_rows:
        if model_id is None:
            rows.append(human_row)
            continue
        key = (model_id, condition)
        if key not in cells_by_model_cond:
            raise ValueError(f"{condition}: no cells loaded for model {model_id}")
        rows.append(_level_means(cells_by_model_cond[key], prices))
    return np.array(rows)


def _configure_columns(ax: plt.Axes, prices: list[float]) -> None:
    """Label the requested price columns in percent (error if untested).

    Raises ValueError when a requested tick price is not one of the actual
    tested price levels, so ticks can never point at a column that has no
    data.
    """
    tick_positions = []
    for price in X_TICK_PRICES:
        if price not in prices:
            raise ValueError(f"tick price {price} not among tested levels {prices}")
        tick_positions.append(prices.index(price) + 0.5)
    ax.set_xticks(tick_positions)
    ax.set_xticklabels([f"{int(price)}%" for price in X_TICK_PRICES])
    ax.tick_params(axis="x", labelsize=8)  # 180% and 200% sit close together
    ax.set_xlabel("Price (% of regular)")
    ax.grid(False)  # cell borders come from the heatmap itself, not the grid


def _draw_panel(
    ax: plt.Axes,
    matrix: np.ndarray,
    title: str,
    prices: list[float],
    y_edges: np.ndarray,
    row_centers: np.ndarray,
    row_labels: list[str],
    human_centers: list[float],
    show_row_labels: bool,
) -> None:
    """Draw one condition's heatmap panel with bordered human rows."""
    ax.pcolormesh(
        np.arange(matrix.shape[1] + 1),
        y_edges,
        np.ma.masked_invalid(matrix),
        vmin=0.0,
        vmax=1.0,
        cmap=purchase_cmap(),
    )
    ax.set_title(title, fontsize=10)
    ax.set_yticks(row_centers)
    if show_row_labels:
        ax.set_yticklabels(row_labels, fontsize=ROW_LABEL_FONTSIZE)
        for tick_label in ax.get_yticklabels():
            if tick_label.get_text() == "Human":
                tick_label.set_fontweight("bold")  # repeated rows stand out
    else:
        ax.tick_params(axis="y", labelleft=False)
    for center in human_centers:  # thin black border around each human row
        ax.add_patch(
            Rectangle(
                (0, center - 0.5),
                matrix.shape[1],
                1.0,
                fill=False,
                edgecolor="black",
                linewidth=HUMAN_ROW_LINEWIDTH,
                zorder=4,
            )
        )
    _configure_columns(ax, prices)


def _add_family_names(
    fig: plt.Figure,
    ax: plt.Axes,
    block_names: list[str],
    block_starts: list[int],
    y_edges: np.ndarray,
) -> None:
    """Write each block's name vertically on the far-left margin.

    The names sit a fixed pad left of the widest row label, measured from
    the drawn tick labels, so they can never collide with them. Each name
    is centered on its block's full span (human row included).
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    label_boxes = [tick.get_window_extent(renderer) for tick in ax.get_yticklabels()]
    if not label_boxes:
        return
    x_pixels = min(box.x0 for box in label_boxes) - FAMILY_LABEL_PAD_PT * fig.dpi / 72
    for name, start, end_rows in zip(
        block_names, block_starts, block_starts[1:] + [EXPECTED_ROWS]
    ):
        top, bottom = y_edges[start], y_edges[end_rows]
        y_pixels = ax.transData.transform((0.0, (top + bottom) / 2.0))[1]
        fig.text(
            x_pixels / fig.bbox.width,
            y_pixels / fig.bbox.height,
            name,
            rotation=90,
            ha="center",
            va="center",
            fontsize=FAMILY_LABEL_FONTSIZE,
            color=FAMILY_LABEL_COLOR,
        )


def fig1_heatmap_purchase_probability(
    cells_by_model_cond: dict[tuple[str, str], pd.DataFrame],
    human_cells: pd.DataFrame,
    outdir: Path,
) -> list[Path]:
    """Figure 1: purchase probability heatmap, blinded and unblinded.

    Rows are four family blocks, each starting with a repeated human row
    (20 rows total; blocks separated by larger gaps); columns are the ten
    price levels from 20% to 200%. Cell color = purchase probability
    averaged over products; both panels share one 0-1 color scale and one
    colorbar. A fully missing price level is drawn light grey and noted
    below the axes. Raises ValueError when the roster is not exactly the
    registered sixteen models or a tick price is untested.
    """
    apply_style()
    model_ids = sorted({model_id for model_id, _ in cells_by_model_cond})
    ordered_ids = figure_row_order(model_ids)
    if len(ordered_ids) != EXPECTED_MODELS:
        raise ValueError(
            f"expected {EXPECTED_MODELS} models, found {len(ordered_ids)}: {ordered_ids}"
        )
    prices = _primary_prices(human_cells)
    display_rows, block_starts, block_names = _display_rows()
    if len(display_rows) != EXPECTED_ROWS:
        raise ValueError(f"expected {EXPECTED_ROWS} rows, found {len(display_rows)}")
    y_edges = _row_edges(len(display_rows), block_starts)
    row_centers = (y_edges[:-1] + y_edges[1:]) / 2.0
    human_centers = [float(row_centers[i]) for i, row in enumerate(display_rows) if row[0] is None]
    matrices = {
        condition: _condition_matrix(
            cells_by_model_cond, human_cells, condition, display_rows, prices
        )
        for condition in CONDITIONS
    }
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 8.2), sharey=True)
    for ax, condition in zip(axes, CONDITIONS):
        _draw_panel(
            ax,
            matrices[condition],
            PANEL_TITLES[condition],
            prices,
            y_edges,
            row_centers,
            [label for _, label in display_rows],
            human_centers,
            show_row_labels=condition == BLINDED,
        )
    has_no_data = any(bool(np.isnan(matrix).any()) for matrix in matrices.values())
    fig.tight_layout(rect=(0, 0.03 if has_no_data else 0.0, 1, 0.95))
    fig.suptitle(FIGURE_TITLE, fontsize=12)
    axes[0].invert_yaxis()  # first row at the top (once: the axes share y)
    colorbar = fig.colorbar(
        axes[0].collections[0], ax=list(axes), pad=0.02, fraction=0.035
    )
    colorbar.set_label(COLORBAR_LABEL)
    if has_no_data:
        fig.text(0.01, 0.006, NO_DATA_NOTE, fontsize=7, color="grey", ha="left", va="bottom")
    _add_family_names(fig, axes[0], block_names, block_starts, y_edges)
    return save_figure(fig, outdir, "fig1_heatmap_purchase_probability")
