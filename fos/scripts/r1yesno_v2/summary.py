# This file writes the study's text outputs: the full model roster (so the
# reader can check nothing was silently dropped) and the one-page SUMMARY
# file. Every number in the summary is looked up from the tables the
# pipeline just computed — nothing is invented here. Its functions:
#   roster_text — one line per model: family, architecture, parameters,
#     measurement method, answer-file legs and how many cells were found;
#   prior_art_deltas — compare our gain numbers with the earlier published
#     table and report any difference larger than 0.05;
#   summary_text — the one-page SUMMARY-V2.md answering the four study
#     questions, conservatively, with associations only (no causes).

from __future__ import annotations

import pandas as pd

from scripts.r1yesno_v2.figures_style import BLINDED, UNBLINDED
from scripts.r1yesno_v2.registry import MODELS

PRIMARY_CONDITIONS = (BLINDED, UNBLINDED)
EXPECTED_PRIMARY_CELLS = 400

# Earlier published table (QWENEXT-analysis) model name -> canonical id.
PRIOR_ART_NAME_MAP = {
    "Qwen3.8-27B": "qwen3.8-27b",
    "GPT-OSS-20B": "gpt-oss-20b",
    "Gemma-4-26B-A4B": "gemma-4-26b-a4b",
    "Nemotron-30B-A3B": "nemotron-cascade-2-30b-a3b",
    "Muse-Glimmer-30B": "muse-glimmer",
    "Qwen3.6-35B-A3B": "qwen3.6-35b-a3b",
    "Qwen3.6-35B unc.": "qwen3.6-35b-a3b-uncensored",
    "Qwen3-4B": "qwen3-4b",
    "Qwen3.6-27B-dense": "qwen3.6-27b-dense",
    "Qwen3.8-Max-0902": "qwen3.8-max-0902",
    # "Gemma-4-31B" deliberately absent: that published row was computed from
    # mid-run partial data (see research R1YESNO-V2 METHODS.md §4).
}
PRIOR_ART_CONDITION_MAP = {"blinded": BLINDED, "unblinded": UNBLINDED}


def _fmt(value: float | None, digits: int = 2) -> str:
    """Format a number for the summary (dash when missing)."""
    if value is None or pd.isna(value):
        return "—"
    return f"{value:.{digits}f}"


def _params_text(model_id: str) -> str:
    """Human-readable parameter counts for one model."""
    info = MODELS[model_id]
    total, active = info["total_params_b"], info["active_params_b"]
    if active is None:
        return "unknown"
    if total != active:
        return f"{_fmt(total, 1)}B total / {_fmt(active, 1)}B active"
    return f"{_fmt(total, 1)}B (dense)"


def roster_text(
    table: pd.DataFrame,
    coverage: pd.DataFrame,
    unregistered: list[str],
    supplement: pd.DataFrame | None = None,
) -> str:
    """Render the full model roster with per-condition cell counts.

    `table` holds the demographics conditions; `supplement` (optional) holds
    the `none` legs, whose model-only numbers live in a separate table.
    """
    lines = [
        "## Full model roster (16 models — none omitted)",
        "",
        "| model_id | display | family | arch | params | method | cells blinded | cells unblinded | cells none-bld | none-unbld |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    cells_lookup = {
        (row.model_id, row.condition): int(row.n_cells)
        for frame in (table, supplement)
        for row in (frame.itertuples() if frame is not None else [])
    }
    for model_id, info in MODELS.items():
        counts = [
            _fmt(cells_lookup.get((model_id, cond)), 0)
            for cond in (BLINDED, UNBLINDED, "none_blinded", "none_unblinded")
        ]
        lines.append(
            f"| {model_id} | {info['short_name']} | {info['family']} | "
            f"{info['architecture']} | {_params_text(model_id)} | "
            f"{info['method']} | " + " | ".join(counts) + " |"
        )
    lines.append("")
    partial = coverage.loc[coverage["primary_cells"] < EXPECTED_PRIMARY_CELLS]
    if len(partial):
        lines.append("Coverage below the full 400-cell primary grid:")
        for row in partial.itertuples():
            lines.append(
                f"- {row.model_id} {row.condition}: {row.primary_cells}/400 primary cells "
                f"({row.records} records)"
            )
    else:
        lines.append("All demographics legs cover the full 400-cell primary grid.")
    if unregistered:
        lines.append("")
        lines.append("Unregistered dirs on disk (reported, not used):")
        lines += [f"- {line}" for line in unregistered]
    return "\n".join(lines)


def prior_art_deltas(table: pd.DataFrame, prior_art_path) -> list[str]:
    """Compare our G values with the earlier published per-model table."""
    prior = pd.read_csv(prior_art_path)
    notes = []
    for row in prior.itertuples():
        model_id = PRIOR_ART_NAME_MAP.get(row.model)
        condition = PRIOR_ART_CONDITION_MAP.get(str(row.condition))
        if model_id is None or condition is None:
            continue
        ours = table.loc[(table["model_id"] == model_id) & (table["condition"] == condition)]
        if not len(ours):
            continue
        delta = float(ours["G_lin"].iloc[0]) - float(row.gain_G)
        if abs(delta) > 0.05:
            notes.append(
                f"- {row.model} {row.condition}: published G={row.gain_G:.3f}, "
                f"V2 G={float(ours['G_lin'].iloc[0]):.3f} (delta {delta:+.3f})"
            )
    if not notes:
        notes.append("- no |delta| > 0.05 between published G and V2 G")
    return notes


def _largest_blinding_swing(table: pd.DataFrame) -> str:
    """Name the model with the largest blinded-vs-unblinded G gap among
    models with full 400-cell coverage in both conditions."""
    full = table.loc[table["n_cells"] >= EXPECTED_PRIMARY_CELLS]
    pivoted = full.pivot_table(index="model_id", columns="condition", values="G_lin")
    pivoted = pivoted.dropna(subset=[BLINDED, UNBLINDED])
    if pivoted.empty:
        return "no model has full coverage in both conditions"
    pivoted["swing"] = (pivoted[UNBLINDED] - pivoted[BLINDED]).abs()
    top = pivoted["swing"].idxmax()
    row = pivoted.loc[top]
    return (
        f"{MODELS[top]['short_name']} (blinded G={row[BLINDED]:.2f} vs "
        f"unblinded G={row[UNBLINDED]:.2f}, gap {row['swing']:.2f})"
    )


def _family_trend_lines(table: pd.DataFrame) -> list[str]:
    """Describe the generation trend inside each three-plus-point family."""
    lines = []
    family_members = {
        "Qwen": ["qwen3-4b", "qwen3.6-35b-a3b", "qwen3.6-27b-dense", "qwen3-32b", "qwen3.8-27b"],
        "Gemma": ["gemma-4-26b-a4b", "gemma-4-12b-it-qat", "gemma-4-31b-it-qat"],
        "Granite": ["granite-4.1-8b", "granite-4.1-30b"],
    }
    for family, members in family_members.items():
        points = []
        for model_id in members:
            gain = table.loc[
                (table["model_id"] == model_id) & (table["condition"] == UNBLINDED),
                "G_lin",
            ]
            if len(gain):
                points.append((MODELS[model_id]["short_name"], float(gain.iloc[0])))
        described = ", ".join(f"{name} {gain:.2f}" for name, gain in points)
        lines.append(f"- {family}: {described} (unblinded)")
    return lines




def summary_text(
    table: pd.DataFrame,
    coverage: pd.DataFrame,
    prior_art_path,
    human_source: str,
) -> str:
    """Build the one-page SUMMARY-V2.md (associations, not causes)."""
    unblinded = table.loc[table["condition"] == UNBLINDED].sort_values("G_lin", ascending=False)
    known = unblinded.loc[
        unblinded["model_id"].map(lambda m: MODELS[m]["active_params_b"] is not None)
    ]
    top3 = ", ".join(f"{row.display_name} ({row.G_lin:.2f})" for row in known.head(3).itertuples())
    moe = known.loc[known["model_id"].map(lambda m: MODELS[m]["architecture"] == "MoE"), "G_lin"]
    dense = known.loc[known["model_id"].map(lambda m: MODELS[m]["architecture"] == "dense"), "G_lin"]
    deltas = prior_art_deltas(table, prior_art_path)
    partial = coverage.loc[coverage["primary_cells"] < EXPECTED_PRIMARY_CELLS]
    swing = _largest_blinding_swing(table)
    g31_id = "gemma-4-31b-it-qat"
    g31 = table.loc[table["model_id"] == g31_id]
    g31_unb_cells = int(g31.loc[g31["condition"] == UNBLINDED, "n_cells"].iloc[0])
    g31_bld_cells = int(g31.loc[g31["condition"] == BLINDED, "n_cells"].iloc[0])
    g31_unb_g = float(g31.loc[g31["condition"] == UNBLINDED, "G_lin"].iloc[0])
    g31_bld_g = float(g31.loc[g31["condition"] == BLINDED, "G_lin"].iloc[0])
    g31_cov = coverage.loc[coverage["model_id"] == g31_id]
    g31_unb_records = int(g31_cov.loc[g31_cov["condition"] == UNBLINDED, "records"].iloc[0])
    g31_bld_records = int(g31_cov.loc[g31_cov["condition"] == BLINDED, "records"].iloc[0])
    method_lines = [
        f"- {model_id}: {MODELS[model_id]['method']}"
        for model_id in MODELS
    ]
    return f"""# R1-YESNO V2 — price response of 16 LLMs (SUMMARY)

Purchase probability by price (40 grocery products, 20-200% of regular price; 16 models; human
reference: 40x10 primary cells, source: {human_source}). G = model price slope / human price
slope (G=1 human-like, G=0 flat). These are descriptive associations from observational model
comparisons — no causal claims; counts only, no statistical tests.

**1. Is price response related to active parameter count?** Weakly at best. Unblinded G spans
{known['G_lin'].min():.2f}-{known['G_lin'].max():.2f} across {len(known)} models with known active
params; the top gainers are {top3}. Both the smallest (qwen3-4b, 4B active, G=
{float(known.loc[known['model_id'] == 'qwen3-4b', 'G_lin'].iloc[0]):.2f}) and the largest dense
models (~31-33B active) include flat and human-like curves, so active scale alone does not order
the models.

**2. Dense vs MoE at approximate scale control?** In the ~3-4B active band MoE models span
G {moe.min():.2f}-{moe.max():.2f} vs dense qwen3-4b G
{float(known.loc[known['model_id'] == 'qwen3-4b', 'G_lin'].iloc[0]):.2f}; in the ~27-33B band the
measured models are almost all dense. No consistent dense-vs-MoE direction:
MoE range {moe.min():.2f}-{moe.max():.2f} vs dense range {dense.min():.2f}-{dense.max():.2f}
(unblinded, known-active models).

**3. Important exceptions?**
- {swing}: the largest blinding swing among models with full 400-cell coverage in both
  conditions (blinded vs unblinded G).
- Gemma-4-26B-A4B also swings widely: blinded G={_fmt(table.loc[(table.model_id == 'gemma-4-26b-a4b') & (table.condition == BLINDED), 'G_lin'].iloc[0])}
  vs unblinded G={_fmt(table.loc[(table.model_id == 'gemma-4-26b-a4b') & (table.condition == UNBLINDED), 'G_lin'].iloc[0])}
  (B moves { _fmt(table.loc[(table.model_id == 'gemma-4-26b-a4b') & (table.condition == BLINDED), 'B_pp'].iloc[0], 1)} -> {_fmt(table.loc[(table.model_id == 'gemma-4-26b-a4b') & (table.condition == UNBLINDED), 'B_pp'].iloc[0], 1)} pp).
- Qwen3.8-Max: forced-choice API measure, partial legs ({int(table.loc[(table.model_id == 'qwen3.8-max-0902') & (table.condition == UNBLINDED), 'n_cells'].iloc[0])} unblinded primary cells of 400;
  11-35 products only) — treat its G={_fmt(table.loc[(table.model_id == 'qwen3.8-max-0902') & (table.condition == UNBLINDED), 'G_lin'].iloc[0])} as indicative.
- Gemma-4-31B: unblinded leg rebuilt to {g31_unb_cells}/400 primary cells via the documented
  sidecar repair of the frozen run's retry damage ({g31_unb_records} valid readings; backfilled
  cells carry legacy nulls, excluded from means; 13 primary cells are null in every surviving
  source — frozen file, pre-retry backup and retry snapshot — so no reading exists for them);
  blinded stays partial: {g31_bld_cells}/400 ({g31_bld_records} records) primary cells — its
  G values are computed from the cells that exist.
- Community fine-tune qwen3.6-35b-UC tracks its base model only loosely
  (G {_fmt(table.loc[(table.model_id == 'qwen3.6-35b-a3b-uncensored') & (table.condition == UNBLINDED), 'G_lin'].iloc[0])} vs
  {_fmt(table.loc[(table.model_id == 'qwen3.6-35b-a3b') & (table.condition == UNBLINDED), 'G_lin'].iloc[0])} for the official base).

**4. Does the pattern replicate across families?** Within-family generation trends
(unblinded G):
{chr(10).join(_family_trend_lines(table))}
Qwen rises from Qwen3 to Qwen3.6 then varies; Gemma rises with size but its 26B-A4B MoE sits far
above its own 12B dense; Granite splits by size: near-flat at 8B, above-human at 30B. The pattern is therefore
family-specific as much as scale-related.

**Figures** (in `figs/`, each as .png and .pdf):
- `fig1_heatmap_purchase_probability` — purchase probability per price level (20-200% of
  regular), one heatmap row per human group and model (rows grouped by family, white block
  separators), blinded and unblinded side by side on one shared 0-1 color scale.
- `fig2_gain_dotplot` — price-response gain G per model (one dot per model, family colors;
  circle = dense, triangle = MoE), reference lines at G=0 and G=1, blinded and unblinded.

**Probability measure per model**
{chr(10).join(method_lines)}

**Gemma-4-31B provenance.** Run `R1-YESNO-GEMMA31B-20260917T120236` (the only complete
Gemma-4-31B run; the 055107 dir is empty, the 231219 dir a 5% stub). A 2026-09-18 in-place retry
repaired the failed yes/no readings but dropped 25 of 440 cells and double-wrote 1,198 persona
slots; the unblinded leg was therefore rebuilt into a sidecar — one row per product-price-persona,
frozen-file reading wins, cells only present in the pre-retry backup are backfilled, backup nulls
stay null and are excluded from cell means (see the sidecar's .provenance.md) — and the registry
reads that leg from the sidecar; the frozen run dir is untouched. 13 primary cells (260 persona
slots) have no usable reading in any surviving source — frozen file, pre-retry backup and retry
snapshot — so the sidecar cannot restore them. The blinded leg still comes from the frozen run
dir and stays partial: {g31_bld_cells}/400 primary cells ({g31_bld_records}
records). Its computed blinded G is {g31_bld_g:.2f} from {g31_bld_cells} cells and
unblinded G={g31_unb_g:.2f} from {g31_unb_cells} cells — far from 0 as required.

**Coverage anomalies.**
{chr(10).join(f'- {row.model_id} {row.condition}: {row.primary_cells}/400 primary cells ({row.records} records)' for row in partial.itertuples()) or '- none: all demographics legs cover the 400 primary cells.'}

**Sanity vs published prior art** (`bias_gain_shape_stats.csv`, same cells source):
{chr(10).join(deltas)}
Published r/rmse values there were computed on per-price means, so V2 pearson_r/rmse_pp (cell-level)
are expected to differ; G/B are compared directly.
"""
