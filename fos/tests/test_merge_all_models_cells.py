# This file checks the combined 16-model cell merger (scripts/r1yesno_v2/
# merge_all_models_cells.py). It builds tiny fake answer files and checks that
# the merger: averages only the usable answers in each product-and-price cell,
# still counts unusable (null) answers in its record totals, strips company
# name prefixes from model folder names, marks prices 20-200% as primary, and
# carries over the human reference purchase rate from the existing cells file.

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.r1yesno_v2 import merge_all_models_cells as merger


def _write_logprob_leg(leg_dir: Path, records: list[dict]) -> None:
    """Create a records.jsonl answer file for one logprob-era leg."""
    leg_dir.mkdir(parents=True)
    with open(leg_dir / "records.jsonl", "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _logprob_record(product: str, price: float, p_yes: float | None) -> dict:
    """Build one fake yes/no logprob answer row."""
    return {
        "model": "google/gemma-4-26b-a4b",
        "product": product,
        "category": "Fruit Juice",
        "blinding": "blinded",
        "persona_depth": "demographics",
        "persona_index": 0,
        "treatment_value": price,
        "p_yes_binary": p_yes,
        "parsed_purchase": None,
        "branch_mass": 0.99,
    }


def _forced_record(product: str, price: float, parsed: bool | None) -> dict:
    """Build one fake forced-choice API answer row."""
    return {
        "model": "qwen/qwen3.8-max-0902",
        "product": product,
        "category": "Fruit Juice",
        "condition": "none_blinded",
        "persona_depth": "none",
        "persona_index": 0,
        "treatment_value": price,
        "p_yes_binary": None,
        "parsed_purchase": parsed,
    }


def _write_human_cells(path: Path) -> Path:
    """Create a tiny stand-in for the existing analysis cells.csv file."""
    frame = pd.DataFrame(
        {
            "model": ["google_gemma-4-26b-a4b", "google_gemma-4-26b-a4b"],
            "condition": ["demographics_blinded", "demographics_blinded"],
            "product": ["Apple Juice 1L", "Apple Juice 1L"],
            "price": [20.0, 0.0],
            "human_p": [0.75, 0.40],
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


GEMMA_SPEC = merger.ModelSpec(
    model="gemma-4-26b-a4b",
    display_name="gemma-4-26b",
    family="Gemma",
    run_dir="R1-YESNO-TEST",
    safe_model="google_gemma-4-26b-a4b",
    price_method=merger.PRICE_METHOD_LOGPROB,
)
QWEN_SPEC = merger.ModelSpec(
    model="qwen3.8-max-0902",
    display_name="qwen3.8-max",
    family="Qwen",
    run_dir="R1-API-TEST",
    safe_model="qwen_qwen3.8-max-0902",
    price_method=merger.PRICE_METHOD_FORCED,
)


def _build_root(tmp_path: Path) -> tuple[Path, Path]:
    """Lay out one fake run tree with a logprob model and an API model."""
    root = tmp_path / "results" / "unblinding"
    _write_logprob_leg(
        root / "R1-YESNO-TEST" / "google_gemma-4-26b-a4b" / "demographics_blinded",
        [
            _logprob_record("Apple Juice 1L", 20.0, 1.0),
            _logprob_record("Apple Juice 1L", 20.0, 0.0),
            _logprob_record("Apple Juice 1L", 20.0, None),
            _logprob_record("Apple Juice 1L", 0.0, 0.0),
        ],
    )
    _write_logprob_leg(
        root / "R1-API-TEST" / "qwen_qwen3.8-max-0902" / "none_blinded",
        [
            _forced_record("Apple Juice 1L", 200.0, True),
            _forced_record("Apple Juice 1L", 200.0, False),
            _forced_record("Apple Juice 1L", 200.0, None),
        ],
    )
    human_csv = _write_human_cells(tmp_path / "cells.csv")
    return root, human_csv


def _build_cells(tmp_path: Path) -> pd.DataFrame:
    """Build the merged cell table for the two fake models in the fake tree."""
    root, human_csv = _build_root(tmp_path)
    return merger.build_all_cells(
        root,
        human_csv,
        specs=(GEMMA_SPEC, QWEN_SPEC),
        legs_by_model={
            GEMMA_SPEC.model: ("demographics_blinded",),
            QWEN_SPEC.model: ("none_blinded",),
        },
    )


def test_cell_mean_uses_only_non_null_records(tmp_path: Path) -> None:
    """A cell's purchase rate averages the usable answers, ignoring nulls."""
    cells = _build_cells(tmp_path)
    row = cells.loc[(cells["model"] == "gemma-4-26b-a4b") & (cells["price"] == 20.0)]
    assert len(row) == 1
    assert float(row["p_purchase"].iloc[0]) == pytest.approx(0.5)


def test_null_records_count_in_totals_but_not_in_mean(tmp_path: Path) -> None:
    """Null answers raise n_records but never n_valid or the mean."""
    cells = _build_cells(tmp_path)
    row = cells.loc[(cells["model"] == "gemma-4-26b-a4b") & (cells["price"] == 20.0)]
    assert int(row["n_records"].iloc[0]) == 3
    assert int(row["n_valid"].iloc[0]) == 2


def test_org_prefix_is_stripped_from_model_name(tmp_path: Path) -> None:
    """Folder names like google_gemma-... lose the company prefix."""
    cells = _build_cells(tmp_path)
    assert "gemma-4-26b-a4b" in set(cells["model"])
    assert "qwen3.8-max-0902" in set(cells["model"])


def test_forced_choice_share_uses_parsed_purchase(tmp_path: Path) -> None:
    """API-era cells average purchase/not-purchase over parsed draws only."""
    cells = _build_cells(tmp_path)
    row = cells.loc[(cells["model"] == "qwen3.8-max-0902") & (cells["price"] == 200.0)]
    assert float(row["p_purchase"].iloc[0]) == pytest.approx(0.5)
    assert int(row["n_records"].iloc[0]) == 3
    assert int(row["n_valid"].iloc[0]) == 2
    assert (row["price_method"] == "forced_choice_share").all()


def test_price_method_flags_logprob_models(tmp_path: Path) -> None:
    """Logprob-era rows are labelled logprob_p_yes_binary."""
    cells = _build_cells(tmp_path)
    logprob_rows = cells.loc[cells["model"] == "gemma-4-26b-a4b"]
    assert (logprob_rows["price_method"] == "logprob_p_yes_binary").all()


def test_in_primary_marks_prices_20_to_200(tmp_path: Path) -> None:
    """0% is outside the primary range; 20% and 200% are inside it."""
    cells = _build_cells(tmp_path)
    flagged = cells.set_index(["model", "price"])["in_primary"]
    assert not bool(flagged.loc[("gemma-4-26b-a4b", 0.0)])
    assert bool(flagged.loc[("gemma-4-26b-a4b", 20.0)])
    assert bool(flagged.loc[("qwen3.8-max-0902", 200.0)])


def test_human_p_joined_from_existing_cells(tmp_path: Path) -> None:
    """The human reference rate travels from the old cells file to each row."""
    cells = _build_cells(tmp_path)
    row = cells.loc[(cells["model"] == "gemma-4-26b-a4b") & (cells["price"] == 20.0)]
    assert float(row["human_p"].iloc[0]) == pytest.approx(0.75)


def test_product_and_category_travel_to_output(tmp_path: Path) -> None:
    """Each row keeps its product name and category."""
    cells = _build_cells(tmp_path)
    assert set(cells["product"]) == {"Apple Juice 1L"}
    assert set(cells["category"]) == {"Fruit Juice"}


def test_no_duplicate_model_condition_product_price_rows(tmp_path: Path) -> None:
    """Every (model, condition, product, price) key appears exactly once."""
    cells = _build_cells(tmp_path)
    assert not cells.duplicated(subset=["model", "condition", "product", "price"]).any()


def test_registry_lists_sixteen_unique_models() -> None:
    """The built-in model table has the 16 canonical models, each once."""
    assert len(merger.MODEL_RUNS) == 16
    names = [spec.model for spec in merger.MODEL_RUNS]
    assert len(set(names)) == 16
