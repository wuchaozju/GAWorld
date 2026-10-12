#!/usr/bin/env python3
"""Score an R1LP logprob run against the human benchmark.

R1LP records carry the model's own probability of "purchase" in
`p_buy_logprob` instead of a sampled yes/no decision. This script turns a
finished (or still-running) run directory into the same kind of table the
sampling run's interim report produces, so the two can be compared side by
side:

  * per (model, depth, blinding) condition,
  * per-cell p(buy) = the mean of p_buy_logprob over the personas (or the
    plain draws) of that (product x price level) cell,
  * the cell MAE against the human benchmark
    (research/TASK-1496/pbuy_product_level.csv),
  * the mean per-product shape correlation (Pearson r across price levels),
  * every metric twice: the 0% (free) price level excluded (primary, the
    sampling report's convention) and included (robustness).

It only reads files and never touches the network. A leg whose records are
still being written is reported honestly with the records present so far.

Plain-language function map:
    discover_conditions(run_dir) - find each condition's records.
    load_human_benchmark(path)   - read the product x level human table.
    cell_pbuy(records)           - mean p_buy per (product, level) cell.
    cell_mae(model, human, ...)  - mean |model - human| over shared cells.
    shape_correlation(...)       - mean per-product Pearson r.
    analyze_condition(...)       - one condition's row of numbers.
    print_table(rows)            - the console table.
    main(argv)                   - CLI entry point.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

DEFAULT_HUMAN = "/home/justin/work/research/TASK-1496/pbuy_product_level.csv"
FREE_LEVEL = 0.0


def _read_records(condition_dir: Path) -> tuple[list[dict[str, Any]], int]:
    """Read every JSONL record of one condition dir; count torn lines."""
    records: list[dict[str, Any]] = []
    torn = 0
    for path in sorted(condition_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    torn += 1
                    continue
                if isinstance(parsed, dict):
                    records.append(parsed)
    return records, torn


def discover_conditions(run_dir: Path) -> list[dict[str, Any]]:
    """Find every condition's records under a run directory.

    Supports both layouts: the R1LP/queue layout
    <run>/<safe_model>/<depth>_<blinding>/ and the single-model layout
    <run>/<depth>_<blinding>/. A condition with no records yet appears with
    an empty list so an in-flight run is reported honestly.
    """
    conditions: list[dict[str, Any]] = []
    if not run_dir.is_dir():
        return conditions
    for folder in sorted(run_dir.iterdir()):
        if not folder.is_dir():
            continue
        if folder.name.endswith(("_blinded", "_unblinded")):
            depth, blinding = folder.name.rsplit("_", 1)
            records, torn = _read_records(folder)
            conditions.append(
                {
                    "model": "",
                    "depth": depth,
                    "blinding": blinding,
                    "records": records,
                    "torn": torn,
                }
            )
            continue
        for leg in sorted(folder.iterdir()):
            if not leg.is_dir() or not leg.name.endswith(("_blinded", "_unblinded")):
                continue
            depth, blinding = leg.name.rsplit("_", 1)
            records, torn = _read_records(leg)
            conditions.append(
                {
                    "model": folder.name,
                    "depth": depth,
                    "blinding": blinding,
                    "records": records,
                    "torn": torn,
                }
            )
    return conditions


def load_human_benchmark(path: Path) -> tuple[dict[str, dict[float, float]], list[float]]:
    """Read the human p(buy) table: one row per product, one column per level.

    Returns (table, levels) where table[product][level] = human p(buy). The
    CSV's first column is the product name and every other header is a
    percentage price level (0, 20, ... 200).
    """
    table: dict[str, dict[float, float]] = {}
    levels: list[float] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        levels = [float(column) for column in header[1:]]
        for row in reader:
            if not row:
                continue
            product = row[0]
            values: dict[float, float] = {}
            for level, cell in zip(levels, row[1:]):
                if cell == "":
                    continue
                try:
                    values[level] = float(cell)
                except ValueError:
                    continue
            table[product] = values
    return table, levels


def cell_pbuy(records: list[dict[str, Any]]) -> dict[str, dict[float, float]]:
    """Per (product, level) cell: the mean p_buy_logprob over its records.

    The mean is taken over personas for a demographics leg and over the
    plain draws for a bare leg; records whose score failed (no numeric
    p_buy_logprob) are skipped, never counted as a zero.
    """
    totals: dict[tuple[str, float], float] = {}
    counts: dict[tuple[str, float], int] = {}
    for record in records:
        value = record.get("p_buy_logprob")
        product = record.get("product")
        level = record.get("treatment_value")
        if not isinstance(value, (int, float)) or product is None or level is None:
            continue
        key = (str(product), float(level))
        totals[key] = totals.get(key, 0.0) + float(value)
        counts[key] = counts.get(key, 0) + 1
    cells: dict[str, dict[float, float]] = {}
    for (product, level), total in totals.items():
        cells.setdefault(product, {})[level] = total / counts[(product, level)]
    return cells


def cell_mae(
    model_cells: dict[str, dict[float, float]],
    human_cells: dict[str, dict[float, float]],
    *,
    exclude_levels: tuple[float, ...] = (FREE_LEVEL,),
) -> float | None:
    """Mean |p_model - p_human| over the (product, level) cells both share.

    exclude_levels drops the free (0%) level from the primary number; pass
    an empty tuple for the robustness number that keeps it. None when no
    cell is shared.
    """
    diffs: list[float] = []
    for product, row in model_cells.items():
        human_row = human_cells.get(product, {})
        for level, p_model in row.items():
            if level in exclude_levels:
                continue
            p_human = human_row.get(level)
            if p_human is None:
                continue
            diffs.append(abs(p_model - p_human))
    return sum(diffs) / len(diffs) if diffs else None


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation of two equal-length lists (None when degenerate)."""
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0.0 or var_y <= 0.0:
        return None
    return cov / math.sqrt(var_x * var_y)


def shape_correlation(
    model_cells: dict[str, dict[float, float]],
    human_cells: dict[str, dict[float, float]],
    *,
    exclude_levels: tuple[float, ...] = (FREE_LEVEL,),
) -> float | None:
    """Mean per-product Pearson r of the model vs human curve over levels.

    Only products with at least two shared levels (after exclusions) take
    part; the returned number is the mean of their correlations, so a run
    that tracks the human shape scores near 1.0.
    """
    correlations: list[float] = []
    for product, row in model_cells.items():
        human_row = human_cells.get(product, {})
        shared = sorted(
            level
            for level in row
            if level not in exclude_levels and level in human_row
        )
        if len(shared) < 2:
            continue
        r = _pearson(
            [row[level] for level in shared], [human_row[level] for level in shared]
        )
        if r is not None:
            correlations.append(r)
    return sum(correlations) / len(correlations) if correlations else None


def analyze_condition(
    condition: dict[str, Any],
    human_cells: dict[str, dict[float, float]],
) -> dict[str, Any]:
    """One condition's comparison row: cells, MAE and shape correlation.

    The primary metrics exclude the free (0%) level; the robustness metrics
    keep it. Cells is how many (product, level) model cells had a score.
    """
    cells = cell_pbuy(condition["records"])
    scored = sum(len(row) for row in cells.values())
    return {
        "model": condition["model"],
        "depth": condition["depth"],
        "blinding": condition["blinding"],
        "records": len(condition["records"]),
        "torn": condition["torn"],
        "cells": scored,
        "mae_excl_free": cell_mae(cells, human_cells, exclude_levels=(FREE_LEVEL,)),
        "mae_with_free": cell_mae(cells, human_cells, exclude_levels=()),
        "shape_excl_free": shape_correlation(
            cells, human_cells, exclude_levels=(FREE_LEVEL,)
        ),
        "shape_with_free": shape_correlation(cells, human_cells, exclude_levels=()),
    }


def _fmt(value: float | None) -> str:
    """A number to three decimals, or a dash when it is None."""
    return "-" if value is None else f"{value:.3f}"


def print_table(rows: list[dict[str, Any]]) -> None:
    """Print the comparison table, one row per condition."""
    header = (
        f"{'model':<28} {'condition':<26} {'cells':>6} {'records':>8} "
        f"{'MAE(excl 0%)':>12} {'MAE(with 0%)':>12} "
        f"{'r(excl 0%)':>10} {'r(with 0%)':>10}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        condition = f"{row['depth']}_{row['blinding']}"
        print(
            f"{row['model']:<28} {condition:<26} {row['cells']:>6} "
            f"{row['records']:>8} {_fmt(row['mae_excl_free']):>12} "
            f"{_fmt(row['mae_with_free']):>12} {_fmt(row['shape_excl_free']):>10} "
            f"{_fmt(row['shape_with_free']):>10}"
        )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the run dir and the human benchmark path."""
    parser = argparse.ArgumentParser(
        prog="r1_logprob_analysis",
        description=(
            "Score an R1LP logprob run against the human p(buy) benchmark "
            "(per-cell MAE and per-product shape correlation)."
        ),
    )
    parser.add_argument("run_dir", help="the logprob run directory")
    parser.add_argument(
        "--human",
        default=DEFAULT_HUMAN,
        help=f"human benchmark CSV (default {DEFAULT_HUMAN})",
    )
    parser.add_argument(
        "--out",
        default="",
        help="optional path to also write the comparison table as CSV",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Read the run and the benchmark, print the table, optionally write it."""
    args = _parse_args(argv)
    run_dir = Path(args.run_dir)
    human_path = Path(args.human)
    if not run_dir.is_dir():
        print(f"error: run dir not found: {run_dir}", file=sys.stderr)
        return 2
    if not human_path.exists():
        print(f"error: human benchmark not found: {human_path}", file=sys.stderr)
        return 2
    human_cells, human_levels = load_human_benchmark(human_path)
    conditions = discover_conditions(run_dir)
    if not conditions:
        print(f"error: no condition records under {run_dir}", file=sys.stderr)
        return 2
    rows = [analyze_condition(condition, human_cells) for condition in conditions]
    print(f"R1LP logprob analysis: {run_dir}")
    print(f"human benchmark: {human_path} ({len(human_cells)} products, levels {human_levels})")
    print_table(rows)
    if args.out:
        out = Path(args.out)
        columns = [
            "model",
            "depth",
            "blinding",
            "records",
            "torn",
            "cells",
            "mae_excl_free",
            "mae_with_free",
            "shape_excl_free",
            "shape_with_free",
        ]
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
