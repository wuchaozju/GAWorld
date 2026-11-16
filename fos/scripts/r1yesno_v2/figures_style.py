# This file holds the shared look and the shared ordering for every figure
# of the paper: the four family blocks and one fixed color per block, the
# blinding-condition names both figures use, the one fixed model row order
# both figures share (the user's explicit choice, NOT a performance sort),
# the marker symbol per architecture, the heatmap color scale, and the
# picture-quality and saving settings. Its functions:
#   apply_style — turn on the shared look (font, resolution, tight margins);
#   block_of_family — which family block (Qwen, Gemma, Granite, Other) a
#     model family belongs to;
#   family_color — the fixed block color for one model family;
#   arch_marker — the symbol for one architecture (dense=circle,
#     MoE=triangle; anything else raises an error so no unknown symbol can
#     ever be drawn);
#   figure_row_order — the one fixed model order both figures share;
#   figure_blocks — the four family blocks with their model ids, in that
#     fixed order;
#   purchase_cmap — the heatmap color scale (viridis) with light grey set
#     aside for "no data" cells;
#   save_figure — write one picture as PNG (300 dpi) and PDF.

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw to files, no screen needed
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import Colormap  # noqa: E402

from scripts.r1yesno_v2.registry import MODELS  # noqa: E402

# The four family blocks both figures use, in display order. Registry
# families not named here (OpenAI, NVIDIA, Meta-Muse, GLM) all belong to
# the "Other" block.
FAMILY_BLOCKS: tuple[str, ...] = ("Qwen", "Gemma", "Granite", "Other")

# Fixed block colors (muted, mutually distinct; human is always black).
# Qwen/Gemma/Granite are pinned by the figure spec (blue/orange/green);
# "Other" is a muted reddish purple so it stays clearly separate from the
# three pinned colors even at dot size.
BLOCK_COLORS: dict[str, str] = {
    "Qwen": "#0072B2",     # blue
    "Gemma": "#E69F00",    # orange
    "Granite": "#009E73",  # green
    "Other": "#CC79A7",    # muted reddish purple
}

HUMAN_COLOR = "#000000"

# One symbol per architecture, used in every figure. An architecture with
# no entry here raises an error, so a figure can never silently draw an
# "unknown" symbol.
ARCH_MARKERS: dict[str, str] = {
    "dense": "o",
    "MoE": "^",
}

# The two blinding conditions every figure shows side by side.
BLINDED = "demographics_blinded"
UNBLINDED = "demographics_unblinded"
CONDITIONS = (BLINDED, UNBLINDED)
PANEL_TITLES = {BLINDED: "Blinded", UNBLINDED: "Unblinded"}

NO_DATA_COLOR = "lightgrey"

# The one model row order both figures share: four family blocks, and
# inside each block the user's explicit chosen order (NOT sorted by
# performance or size). The Human reference rows are added by the heatmap
# itself; this list is the 16 models only.
FIGURE_ROW_ORDER: tuple[str, ...] = (
    # Qwen block
    "qwen3-4b",
    "qwen3-32b",
    "qwen3.6-35b-a3b",
    "qwen3.6-35b-a3b-uncensored",
    "qwen3.6-27b-dense",
    "qwen3.8-27b",
    "qwen3.8-max-0902",
    # Gemma block
    "gemma-4-12b-it-qat",
    "gemma-4-26b-a4b",
    "gemma-4-31b-it-qat",
    # Granite block
    "granite-4.1-8b",
    "granite-4.1-30b",
    # Other block
    "gpt-oss-20b",
    "nemotron-cascade-2-30b-a3b",
    "muse-glimmer",
    "glm-4.7-flash",
)


def apply_style() -> None:
    """Turn on the shared look for all figures (call once per process)."""
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
            "pdf.fonttype": 42,  # embed TrueType text (editable in papers)
            "figure.dpi": 300,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "grid.linewidth": 0.4,
        }
    )


def block_of_family(family: str) -> str:
    """Return the family block one model family belongs to."""
    return family if family in FAMILY_BLOCKS else "Other"


def family_color(family: str) -> str:
    """Return the fixed block color for one model family."""
    return BLOCK_COLORS[block_of_family(family)]


def arch_marker(architecture: str) -> str:
    """Return the marker symbol for one architecture; error if unknown."""
    if architecture not in ARCH_MARKERS:
        raise ValueError(f"no marker defined for architecture {architecture!r}")
    return ARCH_MARKERS[architecture]


def figure_row_order(model_ids: list[str]) -> list[str]:
    """Return the one fixed model order both figures share.

    Raises ValueError when the loaded models are not exactly the registered
    sixteen, so an incomplete or extended roster can never be drawn quietly.
    """
    if set(model_ids) != set(FIGURE_ROW_ORDER):
        missing = sorted(set(FIGURE_ROW_ORDER) - set(model_ids))
        extra = sorted(set(model_ids) - set(FIGURE_ROW_ORDER))
        raise ValueError(f"model roster mismatch; missing={missing} extra={extra}")
    return list(FIGURE_ROW_ORDER)


def figure_blocks() -> list[tuple[str, list[str]]]:
    """Return the family blocks with their model ids in the fixed order."""
    blocks: list[tuple[str, list[str]]] = []
    for block in FAMILY_BLOCKS:
        ids = [
            model_id for model_id in FIGURE_ROW_ORDER
            if block_of_family(MODELS[model_id]["family"]) == block
        ]
        blocks.append((block, ids))
    return blocks


def purchase_cmap() -> Colormap:
    """Return the heatmap color scale: viridis, light grey = no data."""
    cmap = matplotlib.colormaps["viridis"].copy()
    cmap.set_bad(NO_DATA_COLOR)
    return cmap


def save_figure(fig: plt.Figure, outdir: Path, name: str) -> list[Path]:
    """Write one figure as PNG (300 dpi) and PDF; return the written paths."""
    outdir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for suffix in (".png", ".pdf"):
        path = outdir / f"{name}{suffix}"
        fig.savefig(path)
        written.append(path)
    plt.close(fig)
    return written
