# Locked RED-phase tests for the human split-half benchmark band
# (TASK-2124).
#
# WHAT THIS FILE DOES: it pins down, one behaviour per test, how the
# to-be-built module `scripts/r1yesno_v2/human_split_half_band.py` must
# work. The module measures how much human demand curves wobble against
# THEMSELVES: split the 2,058 Twin-2K-500 participants into two random
# halves 1,000 times, and see how far apart the two halves' answers land.
# That wobble band tells us how much of a model's error is just human
# noise. The tests use small made-up data so every number can be checked
# by hand:
#   - reading a pricing question out of a persona_json record (product
#     name and shown dollar price from the question text);
#   - mapping a shown price onto the price grid (level k = price over
#     regular price, times five, rounded to the nearest whole level);
#   - flagging prices that do NOT sit on the grid (grid violations);
#   - coding the answer (1 = yes-buy, 2 = no) and rejecting anything else;
#   - the split logic (two disjoint halves covering everyone);
#   - the three error numbers per split (cell MAE, pooled-curve MAE,
#     per-level MAE) worked out by hand on toy data;
#   - the p5/p50/p95 summary of a list of errors.
#
# Every test imports the module INSIDE the test function on purpose: until
# the module exists each test must FAIL with ModuleNotFoundError (the
# missing feature), never ERROR at collection time (which would mean a
# typo in this file instead).
#
# Functions in this file:
#   _mod — fetch the module under test, imported at call time.
#   _question — build one fake persona_json pricing question.
#   _persona — build one fake participant's persona_json (a list of
#              survey blocks, the shape the real dataset uses).
#   _products — build a tiny two-product price registry.
#   test_* — the locked tests, named so anyone can read what is checked.

from __future__ import annotations

import json

import numpy as np


def _mod():
    from scripts.r1yesno_v2 import human_split_half_band

    return human_split_half_band


def _question(product: str, price: str, answer: int) -> dict:
    """One fake pricing question exactly as the dataset words it."""
    text = (
        "Please consider the following product category: Test Category. "
        "Suppose you are in a grocery store, and you see the following "
        f"product in that category: {product}. The product is priced at: "
        f"${price}. Would you buy this product?"
    )
    return {
        "QuestionID": "QID90001",
        "QuestionText": text,
        "QuestionType": "MC",
        "Answers": {"SelectedByPosition": answer},
    }


def _persona(pid: int, questions: list[dict]) -> tuple[int, str]:
    """One fake participant: pid plus a persona_json blob (list of blocks)."""
    block = {"ElementType": "Block", "BlockName": "Pricing", "Questions": questions}
    return pid, json.dumps([block])


def _products() -> list[dict]:
    """A tiny two-product price registry (regular prices $2.00 and $4.00)."""
    return [
        {"product": "Apple", "regular_price": 2.0},
        {"product": "Cake", "regular_price": 4.0},
    ]


# ---------------------------------------------------------------- price parse


def test_product_name_is_read_from_question_text():
    mod = _mod()
    q = _question("Apple", "2.00", 1)
    assert mod.product_from_text(q["QuestionText"]) == "Apple"


def test_shown_price_is_read_from_question_text():
    mod = _mod()
    q = _question("Apple", "3.49", 1)
    assert mod.price_from_text(q["QuestionText"]) == 3.49


def test_unrelated_question_gives_no_product():
    mod = _mod()
    assert mod.product_from_text("What is your favourite colour?") is None


# --------------------------------------------------------------- grid mapping


def test_price_lands_on_grid_level_k():
    mod = _mod()
    # $1.00 on a $2.00 regular product is half price = k 2.5 -> cent-rounded
    # shown prices must snap to the nearest whole level: k = 2 or 3 is a
    # violation; here $1.00 is exactly k 2.5 -- use a clean case instead:
    # $0.40 on a $2.00 product is 20% = k 1.
    assert mod.grid_level(0.40, 2.00) == 1


def test_free_price_is_grid_level_zero():
    mod = _mod()
    assert mod.grid_level(0.0, 2.00) == 0


def test_double_regular_price_is_grid_level_ten():
    mod = _mod()
    assert mod.grid_level(4.00, 2.00) == 10


def test_cent_rounded_price_snaps_to_nearest_level():
    mod = _mod()
    # Stores show cent-rounded prices: 20% of a $9.43 regular product is
    # $1.886, shown as $1.89 -- 0.002 levels off the exact grid, so it must
    # snap to k 1 rather than be called a violation.
    assert mod.grid_level(1.89, 9.43) == 1


def test_price_far_off_grid_is_a_violation():
    mod = _mod()
    # $2.63 on a $2.00 product is k 6.575 -- nowhere near a whole level.
    assert mod.grid_level(2.63, 2.00) is None


def test_extract_builds_tidy_rows_with_answer_coding():
    mod = _mod()
    personas = [
        _persona(1, [_question("Apple", "0.00", 1), _question("Cake", "8.00", 2)]),
    ]
    rows = mod.extract_tidy_table(personas, _products())
    assert len(rows) == 2
    apple = next(r for r in rows if r["product"] == "Apple")
    cake = next(r for r in rows if r["product"] == "Cake")
    # Answer coding: SelectedByPosition 1 = yes-buy -> True, 2 = no -> False.
    assert apple["answer"] is True and apple["level"] == 0
    assert cake["answer"] is False and cake["level"] == 10


def test_extract_skips_and_counts_unreadable_questions():
    mod = _mod()
    bad = {
        "QuestionID": "QID90002",
        "QuestionText": "Do you like soda?",
        "Answers": {"SelectedByPosition": 1},
    }
    personas = [_persona(1, [_question("Apple", "0.00", 1), bad])]
    rows, skipped = mod.extract_tidy_table_with_skips(personas, _products())
    assert len(rows) == 1
    assert skipped == 1


# --------------------------------------------------------------- split logic


def test_random_halves_are_disjoint_and_cover_everyone():
    mod = _mod()
    pids = np.arange(7)
    a, b = mod.split_pids(pids, seed=42)
    assert sorted(np.concatenate([a, b]).tolist()) == list(range(7))
    assert len(set(a.tolist()) & set(b.tolist())) == 0
    assert abs(len(a) - len(b)) <= 1


def test_same_seed_gives_same_halves():
    mod = _mod()
    pids = np.arange(20)
    a1, b1 = mod.split_pids(pids, seed=42)
    a2, b2 = mod.split_pids(pids, seed=42)
    assert list(a1) == list(a2) and list(b1) == list(b2)


# ------------------------------------------------------------------ MAE math


def _half_curves_from_rows(mod, rows, pids):
    """Helper: per-cell and per-level p(buy) for one half's rows."""
    return mod.half_curves(rows, pids, levels=range(11))


def test_cell_mae_zero_when_halves_identical():
    mod = _mod()
    rows = [
        {"pid": 1, "product": "Apple", "level": 0, "answer": True},
        {"pid": 2, "product": "Apple", "level": 0, "answer": True},
    ]
    cells_a = mod.cell_buy_share(rows, [1, 2])
    mae = mod.cell_mae(cells_a, cells_a)
    assert mae == 0.0


def test_cell_mae_hand_computed():
    mod = _mod()
    # Cell (Apple, 0): half A says 1/2 buy, half B says 1/1 buy -> |0.5-1.0|
    # Cell (Cake, 10): both halves say nobody buys -> 0. Mean = 0.25.
    rows = [
        {"pid": 1, "product": "Apple", "level": 0, "answer": True},
        {"pid": 2, "product": "Apple", "level": 0, "answer": False},
        {"pid": 3, "product": "Apple", "level": 0, "answer": True},
        {"pid": 1, "product": "Cake", "level": 10, "answer": False},
        {"pid": 3, "product": "Cake", "level": 10, "answer": False},
    ]
    cells_a = mod.cell_buy_share(rows, [1])
    cells_b = mod.cell_buy_share(rows, [2, 3])
    assert mod.cell_mae(cells_a, cells_b) == 0.25


def test_pooled_curve_mae_hand_computed():
    mod = _mod()
    # Level 0 pool: A (pid 1) buys 0/1, B (pids 2,3) buys 1/2 -> 0.5.
    rows = [
        {"pid": 1, "product": "Apple", "level": 0, "answer": False},
        {"pid": 2, "product": "Apple", "level": 0, "answer": True},
        {"pid": 3, "product": "Apple", "level": 0, "answer": False},
    ]
    curve_a = mod.pooled_curve(rows, [1])
    curve_b = mod.pooled_curve(rows, [2, 3])
    assert curve_a[0] == 0.0 and curve_b[0] == 0.5
    assert mod.curve_mae(curve_a, curve_b) == 0.5


def test_level_mae_per_level_hand_computed():
    mod = _mod()
    # Level 0 has one product; A (pid 1) 0.0 vs B (pids 2,3) 0.5 -> 0.5.
    rows = [
        {"pid": 1, "product": "Apple", "level": 0, "answer": False},
        {"pid": 2, "product": "Apple", "level": 0, "answer": True},
        {"pid": 3, "product": "Apple", "level": 0, "answer": False},
    ]
    cells_a = mod.cell_buy_share(rows, [1])
    cells_b = mod.cell_buy_share(rows, [2, 3])
    level_maes = mod.level_maes(cells_a, cells_b, levels=range(11))
    assert level_maes[0] == 0.5
    assert all(level_maes[k] == 0.0 for k in range(1, 11))


# ------------------------------------------------------------------ summary


def test_percentiles_p5_p50_p95():
    mod = _mod()
    values = np.arange(1, 101, dtype=float)  # 1..100
    p5, p50, p95 = mod.percentiles(values)
    assert p50 == 50.5
    assert 5.0 <= p5 <= 6.0
    assert 95.0 <= p95 <= 96.0


def test_split_metrics_row_has_all_columns():
    mod = _mod()
    rows = [
        {"pid": 1, "product": "Apple", "level": 0, "answer": True},
        {"pid": 2, "product": "Apple", "level": 0, "answer": False},
        {"pid": 1, "product": "Cake", "level": 10, "answer": False},
        {"pid": 2, "product": "Cake", "level": 10, "answer": False},
    ]
    result = mod.split_metrics(rows, pids=np.array([1, 2]), seed=42)
    assert result["cell_mae"] >= 0.0
    assert result["curve_mae"] >= 0.0
    assert len(result["level_mae"]) == 11


def test_run_splits_produces_requested_number_of_rows():
    mod = _mod()
    rows = [
        {"pid": pid, "product": prod, "level": 0, "answer": pid % 2 == 0}
        for pid in range(1, 9)
        for prod in ("Apple", "Cake")
    ]
    frame = mod.run_splits(rows, n_splits=5, seed=42)
    assert len(frame) == 5
    assert list(frame.columns) == ["split_id", "cell_mae", "curve_mae"] + [
        f"level_{k}_mae" for k in range(11)
    ]
    assert frame["cell_mae"].notna().all()
