# This file reads the raw experiment answers and squashes them into one
# number per product-and-price cell. Its functions:
#   primary_cells — keep only the main price range (20% to 200%) and average
#     the answers within each product-and-price cell;
#   load_logprob_records — read one answer file from the logprob era (models
#     that answered yes/no and we read the first-token probabilities);
#   load_forced_choice_records — read one answer file from the API era (the
#     model picked "purchase" or "not purchase" outright);
#   load_model_cells — read every answer file of one model and return cells
#     per condition (blinded/unblinded, demographics/none);
#   load_human_cells — build the human reference cell table from the
#     validated analysis file, checking it is identical everywhere;
#     fall back to the older TASK-1592 file if the primary file is incomplete;
#   join_model_human — match a model's cells to the human cells, one row per
#     shared product-and-price cell.

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

PRIMARY_PRICE_MIN = 20.0
PRIMARY_PRICE_MAX = 200.0

PRIMARY_HUMAN_CELLS = Path.home() / "work/research/QWENEXT-analysis/cells_extended.csv"
FALLBACK_HUMAN_CELLS = Path.home() / "work/research/TASK-1592/csv/cells.csv"
PRIMARY_CONDITIONS = ("demographics_blinded", "demographics_unblinded")
SUPPLEMENTAL_CONDITIONS = ("none_blinded", "none_unblinded")
EXPECTED_PRODUCTS = 40
EXPECTED_FULL_PRICES = 11
EXPECTED_PRIMARY_CELLS = EXPECTED_PRODUCTS * 10  # 40 products x prices 20..200


def primary_cells(records: pd.DataFrame) -> pd.DataFrame:
    """Average raw answer rows into one row per product-and-price cell.

    `records` needs `product`, `price`, `p` columns (one row per persona or
    draw). Rows priced below 20% or above 200% are dropped, the rest are
    averaged per cell. Returns exactly the columns product, price, p.
    """
    required = {"product", "price", "p"}
    missing = required - set(records.columns)
    if missing:
        raise ValueError(f"records table missing columns: {sorted(missing)}")
    in_range = records.loc[records["price"].between(PRIMARY_PRICE_MIN, PRIMARY_PRICE_MAX)]
    cells = (
        in_range.groupby(["product", "price"], as_index=False)["p"]
        .mean()
        .loc[:, ["product", "price", "p"]]
    )
    return cells


def load_logprob_records(jsonl_path: Path) -> pd.DataFrame:
    """Read one logprob-era answer file into rows of product/price/p/persona.

    The model answered yes/no and we read how much of the first-token
    probability sat on "yes" (`p_yes_binary`). Rows without that value are
    unusable and dropped here, never counted.
    """
    rows: list[dict] = []
    with open(jsonl_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            p_yes = record.get("p_yes_binary")
            if p_yes is None:
                continue
            rows.append(
                {
                    "product": record["product"],
                    "price": float(record["treatment_value"]),
                    "p": float(p_yes),
                    "persona": record.get("persona_index"),
                    "draw_id": record.get("draw_id", 0),
                }
            )
    if not rows:
        raise ValueError(f"no usable records in {jsonl_path}")
    return pd.DataFrame(rows)


def load_forced_choice_records(jsonl_path: Path) -> pd.DataFrame:
    """Read one API-era answer file into rows of product/price/p/persona.

    The model picked "purchase" or "not purchase"; a purchase becomes p=1,
    otherwise p=0. Rows whose decision failed to parse are dropped. (The
    `succeeded` flag in these files is mis-set on every row, so it is never
    used to judge validity.)
    """
    rows: list[dict] = []
    with open(jsonl_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            parsed = record.get("parsed_purchase")
            if parsed is None:
                continue
            rows.append(
                {
                    "product": record["product"],
                    "price": float(record["treatment_value"]),
                    "p": 1.0 if parsed else 0.0,
                    "persona": record.get("persona_index"),
                    "draw_id": record.get("draw_index", 0),
                }
            )
    if not rows:
        raise ValueError(f"no usable records in {jsonl_path}")
    return pd.DataFrame(rows)


def _leg_condition(leg_dir: Path) -> str:
    """Return the condition name for a leg directory (its folder name)."""
    return leg_dir.name.strip().lower()


def load_model_cells(model_dir: Path, method: str) -> dict[str, pd.DataFrame]:
    """Read all four answer files of one model; return cells per condition.

    `model_dir` holds one sub-folder per condition (for example
    `demographics_blinded`); `method` picks the reader ("logprob_p_yes_binary"
    or "forced_choice_share"). Returns {condition: cells table}.
    """
    if method == "logprob_p_yes_binary":
        read_records = load_logprob_records
    elif method == "forced_choice_share":
        read_records = load_forced_choice_records
    else:
        raise ValueError(f"unknown probability method: {method!r}")
    cells_by_condition: dict[str, pd.DataFrame] = {}
    for leg_dir in sorted(path for path in model_dir.iterdir() if path.is_dir()):
        condition = _leg_condition(leg_dir)
        records_path = leg_dir / "records.jsonl"
        if not records_path.exists():
            raise FileNotFoundError(f"missing records file for {condition}: {records_path}")
        records = read_records(records_path)
        cells_by_condition[condition] = primary_cells(records)
    if not cells_by_condition:
        raise FileNotFoundError(f"no leg folders found in {model_dir}")
    return cells_by_condition


def _human_from_cells_file(path: Path) -> pd.DataFrame:
    """Build the human reference table from a QWENEXT-style cells file.

    The file holds one row per model-cell; the `human_p` column repeats the
    same human value on every model's rows. We check it really is identical
    everywhere (it must be — there is only one human study), then keep one
    copy per condition/product/price.
    """
    frame = pd.read_csv(path)
    if "human_p" not in frame.columns:
        raise ValueError(f"{path} has no human_p column")
    humans = frame.dropna(subset=["human_p"])
    if humans.empty:
        raise ValueError(f"{path} carries no human_p values at all")
    unique_check = humans.groupby(["condition", "product", "price"])["human_p"].nunique()
    if float(unique_check.max()) != 1.0:
        bad = unique_check[unique_check > 1]
        raise ValueError(f"human_p disagrees between models, e.g.:\n{bad.head()}")
    cells = (
        humans.groupby(["condition", "product", "price"], as_index=False)["human_p"]
        .first()
        .rename(columns={"human_p": "p_human"})
    )
    return cells


def _count_primary_cells(cells: pd.DataFrame) -> int:
    """Return the number of primary-range human cells in a condition table."""
    primary = cells.loc[cells["price"].between(PRIMARY_PRICE_MIN, PRIMARY_PRICE_MAX)]
    return int(len(primary))


def load_human_cells(cells_ref: Path) -> tuple[pd.DataFrame, str]:
    """Return (human cell table, source description) for the study.

    Uses the validated QWENEXT cells file; if it is missing or its primary
    range coverage is short of 400 cells per condition, falls back to the
    older TASK-1592 file. The returned table has columns condition, product,
    price, p_human.
    """
    try:
        cells = _human_from_cells_file(cells_ref)
    except (FileNotFoundError, ValueError) as error:
        fallback = _human_from_cells_file(FALLBACK_HUMAN_CELLS)
        return fallback, f"fallback {FALLBACK_HUMAN_CELLS} (primary failed: {error})"
    coverage = {
        condition: _count_primary_cells(cells.loc[cells["condition"] == condition])
        for condition in cells["condition"].unique()
    }
    short = {condition: n for condition, n in coverage.items() if n < EXPECTED_PRIMARY_CELLS}
    if short:
        fallback = _human_from_cells_file(FALLBACK_HUMAN_CELLS)
        return (
            fallback,
            f"fallback {FALLBACK_HUMAN_CELLS} (primary short on primary-range cells: {short})",
        )
    return cells, f"primary {cells_ref}"


def join_model_human(model_cells: pd.DataFrame, human_cells: pd.DataFrame) -> pd.DataFrame:
    """Match one model's cells to the human cells on product and price.

    Returns a table with product, price, p_model, p_human — one row per cell
    the model actually has data for (partial models keep only their own
    cells, with the matching human value).
    """
    return model_cells.merge(
        human_cells[["product", "price", "p_human"]],
        on=["product", "price"],
        how="inner",
    ).rename(columns={"p": "p_model"})
