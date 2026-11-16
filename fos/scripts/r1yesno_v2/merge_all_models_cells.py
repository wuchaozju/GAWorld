# This file merges the scattered model answer files into ONE big table with
# one row per model-condition-product-price cell, covering all 16 study
# models. Its functions:
#   strip_org_prefix — turn folder names like google_gemma-4-26b-a4b into the
#     short model id used everywhere else (gemma-4-26b-a4b);
#   load_leg_records — read one answer file into simple rows (product, price,
#     category, and the purchase answer, or "no answer" when it is null);
#   aggregate_cells — squash those rows into one row per product-and-price
#     cell: the average over usable answers, plus how many answers the cell
#     has in total and how many of those were usable;
#   load_human_lookup — read the human reference purchase rates from the
#     existing analysis cells file, one value per product and price;
#   build_model_leg_cells — collect and squash the answer file of one model
#     for one condition, tagging every row with model info and file location;
#   build_all_cells — do that for all 16 models and all four conditions, join
#     the human reference rate onto every row, and mark prices 20-200% as
#     the primary price range;
#   coverage_markdown — write the per-model-per-condition cell counts and the
#     known caveats as a short markdown report;
#   main — run everything from the command line and save the CSV plus the
#     markdown report.
#
# The table this script writes is NEW both times; it never changes any file
# under the results folders or any existing analysis file.

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

LEGS = (
    "none_blinded",
    "none_unblinded",
    "demographics_blinded",
    "demographics_unblinded",
)
PRICE_METHOD_LOGPROB = "logprob_p_yes_binary"
PRICE_METHOD_FORCED = "forced_choice_share"
PRIMARY_PRICE_MIN = 20.0
PRIMARY_PRICE_MAX = 200.0
DEFAULT_RESULTS_ROOT = Path("/home/justin/Documents/ZJU work/fos/results/unblinding")
DEFAULT_HUMAN_CELLS = Path(
    "/home/justin/Documents/output/R1-YESNO-analysis/csv/cells.csv"
)
DEFAULT_OUT_DIR = Path("/home/justin/Documents/output/R1-YESNO-analysis/csv")

ORG_PREFIXES = ("openai_", "google_", "qwen_", "ibm_", "nvidia_", "meta_", "glm_")


@dataclass(frozen=True)
class ModelSpec:
    """One study model: its ids, family, and where its answer files live."""

    model: str
    display_name: str
    family: str
    run_dir: str
    safe_model: str
    price_method: str


MODEL_RUNS: tuple[ModelSpec, ...] = (
    ModelSpec(
        "gpt-oss-20b",
        "gpt-oss-20b",
        "OpenAI",
        "R1-YESNO-20260912T003134",
        "openai_gpt-oss-20b",
        PRICE_METHOD_LOGPROB,
    ),
    ModelSpec(
        "gemma-4-26b-a4b",
        "gemma-4-26b",
        "Gemma",
        "R1-YESNO-20260912T003134",
        "google_gemma-4-26b-a4b",
        PRICE_METHOD_LOGPROB,
    ),
    ModelSpec(
        "gemma-4-31b-it-qat",
        "gemma-4-31b",
        "Gemma",
        "R1-YESNO-GEMMA31B-20260917T120236",
        "google_gemma-4-31b-it-qat",
        PRICE_METHOD_LOGPROB,
    ),
    ModelSpec(
        "gemma-4-12b-it-qat",
        "gemma-4-12b",
        "Gemma",
        "R1-YESNO-NEWBATCH-20260918T000738",
        "google_gemma-4-12b-it-qat",
        PRICE_METHOD_LOGPROB,
    ),
    ModelSpec(
        "qwen3.8-27b",
        "qwen3.8-27b",
        "Qwen",
        "R1-YESNO-20260912T003134",
        "qwen_qwen3.8-27b",
        PRICE_METHOD_LOGPROB,
    ),
    ModelSpec(
        "qwen3.8-max-0902",
        "qwen3.8-max",
        "Qwen",
        "R1-API-QWEN38MAX-20260915T051942",
        "qwen_qwen3.8-max-0902",
        PRICE_METHOD_FORCED,
    ),
    ModelSpec(
        "qwen3.6-27b-dense",
        "qwen3.6-27b-dense",
        "Qwen",
        "R1-YESNO-QWEN36D-20260916T231053",
        "qwen_qwen3.6-27b-dense",
        PRICE_METHOD_LOGPROB,
    ),
    ModelSpec(
        "qwen3.6-35b-a3b",
        "qwen3.6-35b",
        "Qwen",
        "R1-YESNO-QWENEXT-20260915T012431",
        "qwen_qwen3.6-35b-a3b",
        PRICE_METHOD_LOGPROB,
    ),
    ModelSpec(
        "qwen3.6-35b-a3b-uncensored",
        "qwen3.6-35b-UC",
        "Qwen (FT)",
        "R1-YESNO-QWENEXT-20260915T012431",
        "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive",
        PRICE_METHOD_LOGPROB,
    ),
    ModelSpec(
        "qwen3-32b",
        "qwen3-32b",
        "Qwen",
        "R1-YESNO-NEWBATCH-20260918T000738",
        "qwen_qwen3-32b",
        PRICE_METHOD_LOGPROB,
    ),
    ModelSpec(
        "qwen3-4b",
        "qwen3-4b",
        "Qwen",
        "R1-YESNO-QWENEXT-20260915T012431",
        "qwen3-4b",
        PRICE_METHOD_LOGPROB,
    ),
    ModelSpec(
        "granite-4.1-8b",
        "granite-4.1-8b",
        "Granite",
        "R1-YESNO-NEWBATCH-20260918T000738",
        "ibm_granite-4.1-8b",
        PRICE_METHOD_LOGPROB,
    ),
    ModelSpec(
        "granite-4.1-30b",
        "granite-4.1-30b",
        "Granite",
        "R1-YESNO-NEWBATCH-20260918T000738",
        "ibm_granite-4.1-30b",
        PRICE_METHOD_LOGPROB,
    ),
    ModelSpec(
        "nemotron-cascade-2-30b-a3b",
        "nemotron-cascade-2-30b",
        "NVIDIA",
        "R1-YESNO-20260912T003134",
        "nvidia_nemotron-cascade-2-30b-a3b",
        PRICE_METHOD_LOGPROB,
    ),
    ModelSpec(
        "muse-glimmer",
        "muse-glimmer",
        "Meta-Muse",
        "R1-YESNO-20260912T003134",
        "meta_muse-glimmer",
        PRICE_METHOD_LOGPROB,
    ),
    ModelSpec(
        "glm-4.7-flash",
        "glm-4.7-flash",
        "GLM",
        "R1-YESNO-QWENEXT-GLM-20260915T063042",
        "glm_glm-4.7-flash",
        PRICE_METHOD_LOGPROB,
    ),
)


def strip_org_prefix(name: str) -> str:
    """Remove the company prefix from a folder-style model name.

    For example google_gemma-4-26b-a4b becomes gemma-4-26b-a4b. Names without
    a known company prefix (like qwen3-4b) come back unchanged.
    """
    for prefix in ORG_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def _record_probability(record: dict, price_method: str) -> float | None:
    """Pull the purchase answer out of one record; None when unusable.

    Logprob-era records carry a yes-chance (p_yes_binary); API-era records
    carry a buy/not-buy decision (parsed_purchase) that becomes 1 or 0.
    """
    if price_method == PRICE_METHOD_LOGPROB:
        value = record.get("p_yes_binary")
        return None if value is None else float(value)
    if price_method == PRICE_METHOD_FORCED:
        value = record.get("parsed_purchase")
        return None if value is None else (1.0 if value else 0.0)
    raise ValueError(f"unknown price method: {price_method!r}")


def load_leg_records(jsonl_path: Path, price_method: str) -> pd.DataFrame:
    """Read one answer file into rows of product, price, category, p.

    Rows whose answer failed (null) are kept with an empty p so the totals
    can still count them.
    """
    rows: list[dict] = []
    with open(jsonl_path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"{jsonl_path} line {line_number}: bad JSON"
                ) from error
            rows.append(
                {
                    "product": record["product"],
                    "price": float(record["treatment_value"]),
                    "category": record["category"],
                    "p": _record_probability(record, price_method),
                }
            )
    if not rows:
        raise ValueError(f"no records at all in {jsonl_path}")
    return pd.DataFrame(rows)


def aggregate_cells(records: pd.DataFrame) -> pd.DataFrame:
    """Squash answer rows into one row per product-and-price cell.

    p_purchase is the average over the usable (non-null) answers only;
    n_records counts every row in the cell and n_valid counts the usable ones.
    """
    required = {"product", "price", "category", "p"}
    missing = required - set(records.columns)
    if missing:
        raise ValueError(f"records table missing columns: {sorted(missing)}")

    def squash(group: pd.DataFrame) -> pd.Series:
        usable = group["p"].dropna()
        return pd.Series(
            {
                "category": group["category"].iloc[0],
                "p_purchase": usable.mean() if not usable.empty else float("nan"),
                "n_records": int(len(group)),
                "n_valid": int(len(usable)),
            }
        )

    cells = (
        records.groupby(["product", "price"], sort=True)[
            ["product", "price", "category", "p"]
        ]
        .apply(squash, include_groups=False)
        .reset_index()
    )
    return cells


def load_human_lookup(human_csv: Path) -> pd.DataFrame:
    """Read the human reference purchase rate per product and price.

    The existing analysis cells file repeats the same human value on every
    model's rows; this checks that really is true, then keeps one value per
    product and price.
    """
    frame = pd.read_csv(human_csv)
    needed = {"condition", "product", "price", "human_p"}
    missing = needed - set(frame.columns)
    if missing:
        raise ValueError(f"{human_csv} is missing columns: {sorted(missing)}")
    humans = frame.dropna(subset=["human_p"])
    if humans.empty:
        raise ValueError(f"{human_csv} has no human_p values at all")
    conflicts = humans.groupby(["product", "price"])["human_p"].nunique()
    if float(conflicts.max()) != 1.0:
        bad = conflicts[conflicts > 1]
        raise ValueError(f"human_p disagrees between rows for {bad.index[:3]}")
    return humans.groupby(["product", "price"], as_index=False)["human_p"].first()


def build_model_leg_cells(
    spec: ModelSpec, leg: str, results_root: Path
) -> pd.DataFrame:
    """Collect and squash one model's answers for one condition.

    Returns one row per product-and-price cell, tagged with the model's ids,
    family, condition, answering method, and the run folder it came from.
    """
    jsonl_path = results_root / spec.run_dir / spec.safe_model / leg / "records.jsonl"
    if not jsonl_path.exists():
        raise FileNotFoundError(f"missing answer file: {jsonl_path}")
    records = load_leg_records(jsonl_path, spec.price_method)
    cells = aggregate_cells(records)
    cells.insert(0, "model", spec.model)
    cells.insert(1, "display_name", spec.display_name)
    cells.insert(2, "family", spec.family)
    cells.insert(3, "condition", leg)
    cells["price_method"] = spec.price_method
    cells["run_dir"] = spec.run_dir
    return cells


def build_all_cells(
    results_root: Path,
    human_csv: Path,
    specs: tuple[ModelSpec, ...] = MODEL_RUNS,
    legs_by_model: dict[str, tuple[str, ...]] | None = None,
) -> pd.DataFrame:
    """Build the full combined table for all 16 models and all conditions.

    `specs` defaults to the built-in 16-model table; `legs_by_model` maps a
    model id to the conditions to read (default: all four). Tests can pass a
    smaller set of either. Joins the human reference purchase rate onto every
    row and marks prices from 20% to 200% as the primary price range. Raises
    immediately if any model is missing an answer file, so partial merges can
    never be written.
    """
    wanted_legs = legs_by_model or {}
    frames: list[pd.DataFrame] = []
    for spec in specs:
        for leg in wanted_legs.get(spec.model, LEGS):
            frames.append(build_model_leg_cells(spec, leg, results_root))
    cells = pd.concat(frames, ignore_index=True)
    cells = cells.merge(
        load_human_lookup(human_csv), on=["product", "price"], how="left"
    )
    cells["in_primary"] = cells["price"].between(PRIMARY_PRICE_MIN, PRIMARY_PRICE_MAX)
    cells = _sort_output(cells)
    return cells[
        [
            "model",
            "display_name",
            "family",
            "condition",
            "product",
            "category",
            "price",
            "p_purchase",
            "n_records",
            "n_valid",
            "price_method",
            "human_p",
            "in_primary",
            "run_dir",
        ]
    ]


def _sort_output(cells: pd.DataFrame) -> pd.DataFrame:
    """Order rows by the study's model table, then condition, price, product."""
    order = {spec.model: number for number, spec in enumerate(MODEL_RUNS)}
    condition_order = {leg: number for number, leg in enumerate(LEGS)}
    cells = cells.copy()
    cells["_model_order"] = cells["model"].map(order)
    cells["_condition_order"] = cells["condition"].map(condition_order)
    return (
        cells.sort_values(
            ["_model_order", "_condition_order", "price", "product"],
            kind="stable",
        )
        .drop(columns=["_model_order", "_condition_order"])
        .reset_index(drop=True)
    )


def coverage_markdown(cells: pd.DataFrame) -> str:
    """Write the per-model-per-condition cell counts and caveats as markdown."""
    counts = (
        cells.groupby(["model", "condition"], sort=False).size().unstack(fill_value=0)
    )
    lines = [
        "# cells_all_models.csv coverage report",
        "",
        "Cells = distinct product-and-price combinations actually present in the",
        "combined table (full grid would be 440 per condition). Data used as-is;",
        "nothing was re-run or filtered beyond what the files already contain.",
        "",
        "| model | " + " | ".join(LEGS) + " |",
        "|---|" + "---|" * len(LEGS),
    ]
    for model, row in counts.iterrows():
        lines.append(
            f"| {model} | " + " | ".join(str(int(row[leg])) for leg in LEGS) + " |"
        )
    lines += [
        "",
        "## Caveats",
        "",
        "- gemma-4-31b-it-qat demographics_blinded has 284/440 cells: the current",
        "  records.jsonl only holds the valid (non-null) rows (4,745 records).",
        "  Kept as-is by user decision; .bak files were never touched.",
        "- gemma-4-31b-it-qat none legs hold 440 records each but only 425/417",
        "  distinct cells (blinded/unblinded): the interrupted run re-drew some",
        "  product-price pairs and never filled others (documented in",
        "  DATA_INVENTORY.md as 440 records, 425/417 with data). Duplicated",
        "  draws are averaged into one cell here.",
        "- qwen3.8-max-0902 is partial by design (11-35 products, 4 personas,",
        "  over-drawn cells); p_purchase is the share of parsed draws choosing",
        "  purchase (price_method=forced_choice_share), all other models use the",
        "  yes/no first-token logprob chance (price_method=logprob_p_yes_binary).",
        "- 19 qwen3.8-max-0902 cells hold records but no parsed decision (17 in",
        "  none_unblinded, 2 in demographics_unblinded); those rows carry an",
        "  empty p_purchase and n_valid=0.",
        "- human_p comes from the existing analysis cells.csv; it is constant",
        "  per product-and-price there, and every merged row found a match.",
        "- in_primary marks prices 20-200% (the primary price range).",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Run the merge from the command line and save the two output files."""
    parser = argparse.ArgumentParser(
        description="Merge all 16 model runs into one cell-level CSV.",
    )
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--human-csv", type=Path, default=DEFAULT_HUMAN_CELLS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    cells = build_all_cells(args.results_root, args.human_csv)
    duplicates = cells.duplicated(subset=["model", "condition", "product", "price"])
    if duplicates.any():
        raise ValueError(f"{int(duplicates.sum())} duplicate cell rows produced")
    out_csv = args.out_dir / "cells_all_models.csv"
    out_md = args.out_dir / "cells_all_models_COVERAGE.md"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    cells.to_csv(out_csv, index=False)
    out_md.write_text(coverage_markdown(cells), encoding="utf-8")
    per_model = cells.groupby("model", sort=False).size()
    print(f"wrote {len(cells)} rows to {out_csv}")
    print(f"wrote coverage report to {out_md}")
    print("rows per model:")
    print(per_model.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
