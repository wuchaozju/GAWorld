# This file is the command-line entry point of the analysis pipeline. It
# loads every model's answers, computes the price-response numbers, writes
# the CSV tables and the two paper figures (fig1_heatmap_purchase_probability,
# fig2_gain_dotplot), prints the full model roster, and writes SUMMARY-V2.md. Run it as:
#   python -m scripts.r1yesno_v2.run_analysis --results-root <results/unblinding>
#     --outdir <output dir> [--copy-to <mirror dir>]

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pandas as pd

from scripts.r1yesno_v2 import figures_dotplot, figures_heatmap, load, metrics, summary
from scripts.r1yesno_v2.registry import (
    EXPECTED_FULL_CELLS,
    EXPECTED_NONE_RECORDS,
    EXPECTED_PRIMARY_CELLS,
    MODELS,
    scan_unregistered,
    verify_registry_paths,
)

DEFAULT_PRIOR_ART = Path.home() / "work/research/QWENEXT-analysis/bias_gain_shape_stats.csv"
SUPPLEMENT_CONDITIONS = ("none_blinded", "none_unblinded")


def parse_args() -> argparse.Namespace:
    """Read the pipeline's command-line arguments."""
    parser = argparse.ArgumentParser(description="R1-YESNO V2 analysis pipeline")
    parser.add_argument("--results-root", type=Path, required=True,
                        help="the results/unblinding directory of the fos repo")
    parser.add_argument("--cells-ref", type=Path, default=load.PRIMARY_HUMAN_CELLS,
                        help="validated human reference cells file")
    parser.add_argument("--prior-art", type=Path, default=DEFAULT_PRIOR_ART,
                        help="published G/B table for sanity comparison")
    parser.add_argument("--outdir", type=Path, required=True,
                        help="output directory (csv/ and figs/ written inside)")
    parser.add_argument("--copy-to", type=Path, default=None,
                        help="optional mirror directory to copy outputs into")
    return parser.parse_args()


def load_all_models(results_root: Path) -> tuple[dict, dict, pd.DataFrame, pd.DataFrame]:
    """Load every registered model's cells and count what each leg holds.

    Returns (cells per model-condition, record counts per leg, coverage
    table, raw records per model-condition). Raises FileNotFoundError if a
    registered folder is missing.
    """
    verify_registry_paths(results_root)
    cells_by_model_cond: dict[tuple[str, str], pd.DataFrame] = {}
    records_by_model_cond: dict[tuple[str, str], pd.DataFrame] = {}
    coverage_rows: list[dict] = []
    for model_id, info in MODELS.items():
        model_path = results_root / info["run_dir"] / info["safe_dir"]
        reader = (load.load_logprob_records if info["method"] == "logprob_p_yes_binary"
                  else load.load_forced_choice_records)
        for leg_dir in sorted(path for path in model_path.iterdir() if path.is_dir()):
            condition = leg_dir.name.strip().lower()
            records_path = _records_path(results_root, model_id, info, condition, leg_dir)
            records = reader(records_path)
            cells = load.primary_cells(records)
            cells_by_model_cond[(model_id, condition)] = cells
            records_by_model_cond[(model_id, condition)] = records
            coverage_rows.append(_coverage_row(model_id, condition, records, cells))
    coverage = pd.DataFrame(coverage_rows)
    return cells_by_model_cond, records_by_model_cond, coverage, _print_coverage(coverage)


def _records_path(
    results_root: Path, model_id: str, info: dict, condition: str, leg_dir: Path
) -> Path:
    """Resolve one leg's answer file; a registered sidecar override wins.

    Registry entries may redirect a single leg ("leg_overrides") to a repaired
    file stored under the results root — used when the frozen run-dir file is
    known-damaged and must stay untouched. Raises FileNotFoundError when an
    override is registered but missing on disk, so the failure is loud.
    """
    override = info.get("leg_overrides", {}).get(condition)
    if override is None:
        return leg_dir / "records.jsonl"
    resolved = results_root / override
    if not resolved.is_file():
        raise FileNotFoundError(f"sidecar override for {model_id} {condition} missing: {resolved}")
    print(f"  {model_id} {condition}: reading repaired sidecar {resolved.name}")
    return resolved


def _coverage_row(
    model_id: str, condition: str, records: pd.DataFrame, cells: pd.DataFrame
) -> dict:
    """Summarize one model-leg: record count and distinct cells observed."""
    observed_full = records.groupby(["product", "price"]).ngroups
    return {
        "model_id": model_id,
        "condition": condition,
        "records": int(len(records)),
        "observed_full_cells": int(observed_full),
        "primary_cells": int(len(cells)),
    }


def _print_coverage(coverage: pd.DataFrame) -> pd.DataFrame:
    """Print each leg's observed cells vs the expected grid."""
    expected_records = {
        "none": EXPECTED_NONE_RECORDS,
        "demographics": 8_800,
    }
    for row in coverage.itertuples():
        depth = "none" if row.condition.startswith("none") else "demographics"
        note = (
            "OK"
            if row.observed_full_cells == EXPECTED_FULL_CELLS
            and row.records == expected_records[depth]
            else "PARTIAL"
        )
        print(
            f"  {row.model_id} {row.condition}: {row.records} records, "
            f"{row.observed_full_cells}/{EXPECTED_FULL_CELLS} cells, "
            f"{row.primary_cells}/{EXPECTED_PRIMARY_CELLS} primary -> {note}"
        )
    return coverage


def build_metrics_table(
    cells_by_model_cond: dict, human_cells: pd.DataFrame
) -> pd.DataFrame:
    """Join each model's primary cells to the human cells and summarize.

    Only demographics conditions have a human reference; the `none` legs are
    summarized separately (supplement table, model-only numbers).
    """
    primary_cells_by_model = {
        key: cells
        for key, cells in cells_by_model_cond.items()
        if key[1] in load.PRIMARY_CONDITIONS
    }
    return metrics.model_metrics_table(primary_cells_by_model, human_cells)


def build_supplement_table(
    records_by_model_cond: dict, cells_by_model_cond: dict
) -> pd.DataFrame:
    """Model-only numbers for the `none` legs (no human reference exists)."""
    rows = []
    for (model_id, condition), cells in sorted(cells_by_model_cond.items()):
        if condition not in SUPPLEMENT_CONDITIONS:
            continue
        info = MODELS[model_id]
        rows.append(
            {
                "model_id": model_id,
                "display_name": info["short_name"],
                "condition": condition,
                "n_cells": int(len(cells)),
                "B_pp": float("nan"),
                "G_lin": float("nan"),
                "endpoint_response_pp": metrics.endpoint_response_pp(cells),
                "calib_a": float("nan"),
                "calib_b": float("nan"),
                "calib_rmse_pp": float("nan"),
                "calib_r2": float("nan"),
                "pearson_r": float("nan"),
                "probability_method": info["method"],
                "run_dir": info["run_dir"],
            }
        )
    return pd.DataFrame(rows)


def write_metadata_csv(out_csv: Path) -> None:
    """Write the promoted model-metadata table (TASK-2030 DRAFT, canonical ids)."""
    columns = [
        "model_id", "display_name", "family", "generation", "architecture",
        "total_params_b", "active_params_b", "posttrained_or_base", "local_or_api",
        "quantization", "metadata_source", "notes",
    ]
    rows = []
    for model_id, info in MODELS.items():
        rows.append(
            {
                "model_id": model_id,
                "display_name": info["display_name"],
                "family": info["family"],
                "generation": info["generation"],
                "architecture": info["architecture"],
                "total_params_b": info["total_params_b"],
                "active_params_b": info["active_params_b"],
                "posttrained_or_base": "posttrained",
                "local_or_api": info["local_or_api"],
                "quantization": info["quantization"],
                "metadata_source": info["metadata_source"],
                "notes": info["notes"],
            }
        )
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=columns).to_csv(out_csv, index=False)


def main() -> None:
    """Run the whole pipeline: load, metrics, CSVs, figures, summary."""
    args = parse_args()
    print(f"[1/7] verifying registry under {args.results_root}")
    verify_registry_paths(args.results_root)
    unregistered = scan_unregistered(args.results_root)
    for line in unregistered:
        print(f"  !! {line}")
    if not unregistered:
        print("  no unregistered dirs found")
    print("[2/7] loading all models")
    cells_by_model_cond, records_by_model_cond, coverage, _ = load_all_models(args.results_root)
    human_cells, human_source = load.load_human_cells(args.cells_ref)
    print(f"  human reference: {human_source}")
    print("[3/7] computing metrics")
    table = build_metrics_table(cells_by_model_cond, human_cells)
    supplement = build_supplement_table(records_by_model_cond, cells_by_model_cond)
    csv_dir = args.outdir / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(csv_dir / "model_price_response_metrics.csv", index=False)
    supplement.to_csv(csv_dir / "model_price_response_metrics_none_supplement.csv", index=False)
    write_metadata_csv(csv_dir / "model_metadata.csv")
    print("[4/7] drawing figures")
    figures_heatmap.fig1_heatmap_purchase_probability(
        cells_by_model_cond, human_cells, args.outdir / "figs"
    )
    figures_dotplot.fig2_gain_dotplot(table, args.outdir / "figs")
    print("[5/7] model roster")
    print(summary.roster_text(table, coverage, unregistered, supplement))
    print("[6/7] writing SUMMARY-V2.md")
    summary_path = args.outdir / "SUMMARY-V2.md"
    summary_path.write_text(
        summary.summary_text(table, coverage, args.prior_art, human_source)
        + "\n\n"
        + summary.roster_text(table, coverage, unregistered, supplement)
        + "\n",
        encoding="utf-8",
    )
    print(f"  wrote {summary_path}")
    if args.copy_to is not None:
        print("[7/7] mirroring outputs")
        _mirror(args.outdir, args.copy_to)
    else:
        print("[7/7] no mirror requested")


V2_CSVS = (
    "model_metadata.csv",
    "model_price_response_metrics.csv",
    "model_price_response_metrics_none_supplement.csv",
)
V2_FIGS = (
    "fig1_heatmap_purchase_probability",
    "fig2_gain_dotplot",
)


def _mirror(outdir: Path, mirror_dir: Path) -> None:
    """Copy the V2 outputs (csv tables, figures, summary) into the mirror
    directory — only this run's files, never the older V1 artifacts."""
    mirror_dir.mkdir(parents=True, exist_ok=True)
    (mirror_dir / "csv").mkdir(exist_ok=True)
    (mirror_dir / "figs").mkdir(exist_ok=True)
    for name in V2_CSVS:
        shutil.copy2(outdir / "csv" / name, mirror_dir / "csv" / name)
    for name in V2_FIGS:
        for suffix in (".png", ".pdf"):
            shutil.copy2(outdir / "figs" / f"{name}{suffix}",
                         mirror_dir / "figs" / f"{name}{suffix}")
    shutil.copy2(outdir / "SUMMARY-V2.md", mirror_dir / "SUMMARY-V2.md")
    print(f"  mirrored to {mirror_dir}")


if __name__ == "__main__":
    main()
