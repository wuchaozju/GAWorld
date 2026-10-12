# Locked RED-phase tests for the price-response metrics module (TASK-2031).
#
# WHAT THIS FILE DOES: it pins down, one behaviour per test, how the
# to-be-built module `scripts/r1yesno_v2/` must turn "would you buy it at
# this price?" answers into summary numbers:
#   - G_lin: how much more steeply the model than the humans lose interest
#     as the price rises (ratio of the two straight-line slopes);
#   - B_pp: how far the model sits from humans on average, in percentage
#     points;
#   - endpoint_response_pp: the drop in purchase intent between the
#     cheapest (20%) and priciest (200%) price points;
#   - calibration a, b, rmse_pp, r2 and pearson_r: how well the model's
#     numbers line up with the humans' numbers;
#   - primary_cells: how raw per-persona (or per-draw) rows are averaged
#     into one number per product-and-price cell, keeping only the main
#     price range (20 to 200) and dropping the free (0%) rows.
#
# Every test imports the module INSIDE the test function on purpose: until
# the module exists each test must FAIL with ModuleNotFoundError (the
# missing feature), never ERROR at collection time (which would mean a
# typo in this file instead).
#
# Functions in this file:
#   _metrics, _load — fetch the modules under test, imported at call time.
#   _human_at_prices, _frame — build small made-up answer tables for tests.
#   _cells — build a model-vs-human cell table for one product.
#   _persona_records, _draw_records — build raw observation tables whose
#     averages can be worked out by hand.
#   _oracle_summarize — recompute every summary number straight from the
#     real-data fixture with plain numpy, independently of the module.
#   test_* — the locked tests, named so anyone can read what is checked.

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

FIXTURE = (
    Path(__file__).parent / "fixtures" / "r1yesno_v2" / "qwen38_27b_unblinded_cells.csv"
)
PRICES = [20, 50, 100, 150, 200]


def _metrics():
    from scripts.r1yesno_v2 import metrics

    return metrics


def _load():
    from scripts.r1yesno_v2 import load

    return load


def _human_at_prices(prices):
    """The human answers the task's worked example: 0.9 minus 0.003 per price unit."""
    return [0.9 - 0.003 * price for price in prices]


def _frame(prices, values):
    """One product's answers: a table with just price and p columns."""
    return pd.DataFrame({"price": [float(p) for p in prices], "p": values})


def _cells(prices, model_values, human_values):
    """A cell table (product, price, p_model, p_human) for one product."""
    return pd.DataFrame(
        {
            "product": "TestProduct",
            "price": [float(p) for p in prices],
            "p_model": model_values,
            "p_human": human_values,
        }
    )


def _persona_records():
    """Raw rows for two personas per cell; averages are easy to check by hand:
    A@20 -> (0.4+0.6)/2 = 0.5, A@200 -> 0.2, B@150 -> 0.5;
    the 0% (free) and 300% rows fall outside the main 20-200 range."""
    values = {
        ("A", 0.0): [0.9, 0.7],
        ("A", 20.0): [0.4, 0.6],
        ("A", 200.0): [0.1, 0.3],
        ("B", 0.0): [1.0, 0.0],
        ("B", 150.0): [0.8, 0.2],
        ("B", 300.0): [0.5, 0.5],
    }
    rows = [
        {"product": product, "price": price, "p": p, "persona": i}
        for (product, price), ps in values.items()
        for i, p in enumerate(ps)
    ]
    return pd.DataFrame(rows)


def _draw_records():
    """Raw forced-choice rows: each cell has several draws whose 1/0 outcomes
    average to shares anyone can compute: Cereal@20 -> 3/4, Cereal@100 -> 1/4,
    Soap@20 -> 2/4, Soap@100 -> 3/4."""
    outcomes = {
        ("Cereal", 20.0): [1, 1, 0, 1],
        ("Cereal", 100.0): [0, 0, 1, 0],
        ("Soap", 20.0): [1, 0, 1, 0],
        ("Soap", 100.0): [1, 1, 0, 1],
    }
    rows = [
        {"product": product, "price": price, "p": float(outcome), "draw_id": i}
        for (product, price), draws in outcomes.items()
        for i, outcome in enumerate(draws)
    ]
    return pd.DataFrame(rows)


def _oracle_summarize(cells):
    """Recompute the whole summary straight from a cell table with plain
    numpy, so the real-data test does not have to trust the module."""
    price = cells["price"].to_numpy(float)
    p_model = cells["p_model"].to_numpy(float)
    p_human = cells["p_human"].to_numpy(float)

    model_slope = float(np.polyfit(price, p_model, 1)[0])
    human_slope = float(np.polyfit(price, p_human, 1)[0])

    slope, intercept = np.polyfit(p_human, p_model, 1)
    predicted = intercept + slope * p_human
    ss_res = float(((p_model - predicted) ** 2).sum())
    ss_tot = float(((p_model - p_model.mean()) ** 2).sum())

    return {
        "n_cells": len(cells),
        "B_pp": float((p_model.mean() - p_human.mean()) * 100.0),
        "G_lin": model_slope / human_slope,
        "endpoint_response_pp": float(
            (p_model[price == 20.0].mean() - p_model[price == 200.0].mean()) * 100.0
        ),
        "calib_a": float(intercept),
        "calib_b": float(slope),
        "calib_rmse_pp": float(np.sqrt(ss_res / len(cells)) * 100.0),
        "calib_r2": float(1.0 - ss_res / ss_tot),
        "pearson_r": float(np.corrcoef(p_model, p_human)[0, 1]),
    }


SUMMARY_KEYS = {
    "n_cells",
    "B_pp",
    "G_lin",
    "endpoint_response_pp",
    "calib_a",
    "calib_b",
    "calib_rmse_pp",
    "calib_r2",
    "pearson_r",
}


def test_primary_price_range_constants_are_20_and_200():
    load = _load()
    assert load.PRIMARY_PRICE_MIN == 20.0
    assert load.PRIMARY_PRICE_MAX == 200.0


def test_gain_is_one_when_model_matches_human_exactly():
    metrics = _metrics()
    human = _human_at_prices(PRICES)
    got = metrics.linear_gain(_frame(PRICES, human), _frame(PRICES, human))
    assert got == pytest.approx(1.0, abs=1e-6)


def test_gain_is_zero_when_model_response_is_flat():
    metrics = _metrics()
    human = _human_at_prices(PRICES)
    got = metrics.linear_gain(_frame(PRICES, [0.5] * len(PRICES)), _frame(PRICES, human))
    assert got == pytest.approx(0.0, abs=1e-9)


def test_gain_is_two_when_model_slope_is_double_the_human_slope():
    metrics = _metrics()
    human = _human_at_prices(PRICES)
    model = [0.9 - 0.006 * price for price in PRICES]
    got = metrics.linear_gain(_frame(PRICES, model), _frame(PRICES, human))
    assert got == pytest.approx(2.0, abs=1e-9)


def test_bias_is_twenty_points_when_model_says_70_and_human_says_50():
    metrics = _metrics()
    rows = [
        {"product": product, "price": float(price), "p": 0.7}
        for product in ("A", "B")
        for price in PRICES
    ]
    model = pd.DataFrame(rows)
    human = model.copy()
    human["p"] = 0.5
    got = metrics.bias_b(model, human)
    assert got == pytest.approx(20.0, abs=1e-9)


def test_endpoint_response_is_fifty_points_from_price_20_to_200():
    metrics = _metrics()
    df = _frame([20, 100, 200], [0.8, 0.55, 0.3])  # 100 is a decoy price
    got = metrics.endpoint_response_pp(df)
    assert got == pytest.approx(50.0, abs=1e-9)


def test_calibration_is_perfect_when_model_equals_human():
    metrics = _metrics()
    human = [0.2, 0.35, 0.5, 0.65, 0.8]
    got = metrics.calibration_fit(_frame(PRICES, human), _frame(PRICES, human))
    assert got["a"] == pytest.approx(0.0, abs=1e-9)
    assert got["b"] == pytest.approx(1.0, abs=1e-9)
    assert got["rmse_pp"] == pytest.approx(0.0, abs=1e-9)
    assert got["r2"] == pytest.approx(1.0, abs=1e-9)


def test_calibration_recovers_intercept_0_2_and_slope_0_5():
    metrics = _metrics()
    human = [0.2, 0.35, 0.5, 0.65, 0.8]
    model = [0.2 + 0.5 * p for p in human]
    got = metrics.calibration_fit(_frame(PRICES, model), _frame(PRICES, human))
    assert got["a"] == pytest.approx(0.2, abs=1e-9)
    assert got["b"] == pytest.approx(0.5, abs=1e-9)


def test_calibration_rmse_matches_hand_computed_residuals():
    metrics = _metrics()
    human = [0.2, 0.4, 0.6]
    model = [0.3, 0.5, 0.4]
    got = metrics.calibration_fit(_frame([20, 100, 200], model), _frame([20, 100, 200], human))
    # Worked by hand: line is 0.3 + 0.25*p_human, residuals -0.05/+0.10/-0.05,
    # so rmse = sqrt(0.015/3)*100 = 7.0710678... pp and r2 = 1 - 0.015/0.02 = 0.25.
    assert got["a"] == pytest.approx(0.3, abs=1e-9)
    assert got["b"] == pytest.approx(0.25, abs=1e-9)
    assert got["rmse_pp"] == pytest.approx(7.0710678118654755, abs=1e-9)
    assert got["r2"] == pytest.approx(0.25, abs=1e-9)


def test_primary_cells_drops_free_price_zero_rows():
    load = _load()
    out = load.primary_cells(_persona_records())
    assert not (out["price"] == 0.0).any(), "the free 0% price must be dropped"


def test_primary_cells_averages_persona_rows_per_product_and_price():
    load = _load()
    out = load.primary_cells(_persona_records()).sort_values(
        ["product", "price"]
    ).reset_index(drop=True)
    expected = pd.DataFrame(
        {"product": ["A", "A", "B"], "price": [20.0, 200.0, 150.0], "p": [0.5, 0.2, 0.5]}
    )
    pd.testing.assert_frame_equal(out[["product", "price", "p"]], expected)


def test_primary_cells_keeps_only_prices_between_20_and_200():
    load = _load()
    out = load.primary_cells(_persona_records())
    assert out["price"].between(20.0, 200.0).all(), "prices outside 20-200 must be dropped"
    assert set(out["price"]) == {20.0, 150.0, 200.0}


def test_primary_cells_output_has_exactly_product_price_p_columns():
    load = _load()
    out = load.primary_cells(_persona_records())
    assert set(out.columns) == {"product", "price", "p"}


def test_primary_cells_averages_draw_level_outcomes_to_purchase_share():
    load = _load()
    out = load.primary_cells(_draw_records()).sort_values(["product", "price"]).reset_index(drop=True)
    expected = pd.DataFrame(
        {
            "product": ["Cereal", "Cereal", "Soap", "Soap"],
            "price": [20.0, 100.0, 20.0, 100.0],
            "p": [0.75, 0.25, 0.5, 0.75],
        }
    )
    pd.testing.assert_frame_equal(out[["product", "price", "p"]], expected)


def test_summarize_model_returns_all_nine_summary_keys():
    metrics = _metrics()
    human = _human_at_prices(PRICES)
    got = metrics.summarize_model(_cells(PRICES, human, human))
    assert set(got.keys()) == SUMMARY_KEYS
    assert got["n_cells"] == len(PRICES)


def test_summarize_model_matches_numpy_recomputation_of_qwen_fixture():
    metrics = _metrics()
    cells = pd.read_csv(FIXTURE)
    want = _oracle_summarize(cells)
    got = metrics.summarize_model(cells)
    assert got["n_cells"] == want["n_cells"] == 400
    for key in sorted(SUMMARY_KEYS - {"n_cells"}):
        assert got[key] == pytest.approx(want[key], abs=1e-9), key


def test_fixture_gain_and_bias_match_published_reference_row():
    metrics = _metrics()
    cells = pd.read_csv(FIXTURE)
    got = metrics.summarize_model(cells)
    # Reference row (Qwen3.8-27B, unblinded) in bias_gain_shape_stats.csv:
    # G_lin=0.583, B_pp=1.51, calib_a=0.1892, calib_b=0.5698. Raw-cell
    # recomputation: G=0.582651, B=1.509467, a=0.180652, b=0.590937 — all
    # four inside the task tolerances (±0.02 for G/B, ±0.03 for a/b).
    assert got["G_lin"] == pytest.approx(0.583, abs=0.02)
    assert got["B_pp"] == pytest.approx(1.51, abs=0.02)
    assert got["calib_a"] == pytest.approx(0.1892, abs=0.03)
    assert got["calib_b"] == pytest.approx(0.5698, abs=0.03)
    # DELTAS DOCUMENTED (task instruction: trust the raw cells where they
    # disagree). For pearson_r the raw-cell recomputation (0.856859, also
    # rmse_pp=8.757615) is far from the reference r=0.9877 / rmse=1.62, and
    # the reference values reproduce EXACTLY when the fit is run on the 10
    # per-price means instead of the 400 raw cells (per-price means:
    # intercept=0.1892, slope=0.5698, r=0.9877). The reference row is
    # therefore per-price aggregated for r/rmse (its n_prices=10 column
    # agrees). The contract locked here is over cells, so pearson_r and
    # rmse_pp are asserted against the numpy recomputation in
    # test_summarize_model_matches_numpy_recomputation_of_qwen_fixture,
    # not against the reference row.
