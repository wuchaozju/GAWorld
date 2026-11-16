# This file turns "would you buy it at this price?" answers into summary
# numbers. Its functions compare a model's answers with the human answers:
#   linear_gain — how much more steeply the model than the humans lose
#     interest as the price rises (ratio of the two straight-line slopes);
#   bias_b — how far the model sits from humans on average, in percentage
#     points;
#   endpoint_response_pp — the drop in purchase intent between the cheapest
#     (20%) and priciest (200%) price points;
#   calibration_fit — how well model values line up with human values
#     (straight-line fit: intercept a, slope b, error size rmse_pp, r2);
#   pearson_r — the straight-line correlation between model and human values;
#   summarize_model — all of the above in one small table row;
#   model_metrics_table — one row per model and condition for the whole study.

from __future__ import annotations

import numpy as np
import pandas as pd

PRIMARY_PRICE_MIN = 20.0
PRIMARY_PRICE_MAX = 200.0

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


def _ols_slope(x: np.ndarray, y: np.ndarray) -> float:
    """Return the slope of the best straight line through (x, y) points."""
    if len(x) < 2:
        raise ValueError(f"need at least 2 points for a slope, got {len(x)}")
    return float(np.polyfit(x, y, 1)[0])


def linear_gain(model_df: pd.DataFrame, human_df: pd.DataFrame) -> float:
    """Return G: the model's price slope divided by the human price slope.

    Both arguments are tables with `price` and `p` columns. A value of 1
    means the model drops with price exactly as fast as humans do; 0 means
    the model curve is flat; 2 means it drops twice as fast.
    """
    model_slope = _ols_slope(model_df["price"].to_numpy(float), model_df["p"].to_numpy(float))
    human_slope = _ols_slope(human_df["price"].to_numpy(float), human_df["p"].to_numpy(float))
    if human_slope == 0.0:
        raise ValueError("human price slope is 0; gain is undefined")
    return model_slope / human_slope


def bias_b(model_df: pd.DataFrame, human_df: pd.DataFrame) -> float:
    """Return B: mean(model p) minus mean(human p), in percentage points."""
    delta = float(model_df["p"].mean()) - float(human_df["p"].mean())
    return delta * 100.0


def endpoint_response_pp(df: pd.DataFrame) -> float:
    """Return p(20%) minus p(200%) from a `price`/`p` table, in percentage
    points. A positive value means purchase intent falls as price rises."""
    low = df.loc[df["price"] == PRIMARY_PRICE_MIN, "p"]
    high = df.loc[df["price"] == PRIMARY_PRICE_MAX, "p"]
    if low.empty or high.empty:
        raise ValueError(
            f"frame must contain price {PRIMARY_PRICE_MIN} and {PRIMARY_PRICE_MAX} rows"
        )
    return (float(low.mean()) - float(high.mean())) * 100.0


def calibration_fit(model_df: pd.DataFrame, human_df: pd.DataFrame) -> dict[str, float]:
    """Fit a straight line predicting the model's p from the human p.

    Returns a dict with keys `a` (intercept), `b` (slope), `rmse_pp` (typical
    miss in percentage points) and `r2` (share of model variance explained).
    """
    human = human_df["p"].to_numpy(float)
    model = model_df["p"].to_numpy(float)
    if len(human) != len(model) or len(human) < 2:
        raise ValueError(f"need equal lengths >= 2, got {len(model)} vs {len(human)}")
    b, a = np.polyfit(human, model, 1)
    predicted = a + b * human
    ss_res = float(((model - predicted) ** 2).sum())
    ss_tot = float(((model - model.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {
        "a": float(a),
        "b": float(b),
        "rmse_pp": float(np.sqrt(ss_res / len(model))) * 100.0,
        "r2": float(r2),
    }


def pearson_r(model_df: pd.DataFrame, human_df: pd.DataFrame) -> float:
    """Return the straight-line correlation between model and human p values."""
    model = model_df["p"].to_numpy(float)
    human = human_df["p"].to_numpy(float)
    if len(model) != len(human) or len(model) < 2:
        raise ValueError(f"need equal lengths >= 2, got {len(model)} vs {len(human)}")
    return float(np.corrcoef(model, human)[0, 1])


def summarize_model(cells: pd.DataFrame) -> dict[str, float]:
    """Summarize one model-vs-human cell table.

    `cells` needs the columns `product`, `price`, `p_model`, `p_human` — one
    row per product-and-price cell. Returns the nine summary numbers in
    SUMMARY_KEYS.
    """
    required = {"product", "price", "p_model", "p_human"}
    missing = required - set(cells.columns)
    if missing:
        raise ValueError(f"cells table missing columns: {sorted(missing)}")
    if cells.empty:
        raise ValueError("cells table is empty")
    model_frame = pd.DataFrame({"price": cells["price"], "p": cells["p_model"]})
    human_frame = pd.DataFrame({"price": cells["price"], "p": cells["p_human"]})
    calib = calibration_fit(model_frame, human_frame)
    return {
        "n_cells": int(len(cells)),
        "B_pp": bias_b(model_frame, human_frame),
        "G_lin": linear_gain(model_frame, human_frame),
        "endpoint_response_pp": endpoint_response_pp(model_frame),
        "calib_a": calib["a"],
        "calib_b": calib["b"],
        "calib_rmse_pp": calib["rmse_pp"],
        "calib_r2": calib["r2"],
        "pearson_r": pearson_r(model_frame, human_frame),
    }


def _model_info_row(model_id: str) -> dict[str, str]:
    """Look up display name, method and run directory for one model id.

    The run_dir column carries the registry's provenance string, which for
    repaired legs reads "<run dir> + repaired sidecar" (see registry).
    """
    from scripts.r1yesno_v2.registry import MODELS

    info = MODELS.get(model_id)
    if info is None:
        raise KeyError(f"model id {model_id!r} is not in the registry")
    return {
        "display_name": info["short_name"],
        "probability_method": info["method"],
        "run_dir": info.get("run_provenance", info["run_dir"]),
    }


def model_metrics_table(
    cells_by_model_cond: dict[tuple[str, str], pd.DataFrame],
    human_cells: pd.DataFrame,
) -> pd.DataFrame:
    """Build one summary row per (model, condition).

    `cells_by_model_cond` maps (model_id, condition) to a table with columns
    `product`, `price`, `p` (the model's own cells). `human_cells` is one
    table with `condition`, `product`, `price`, `p_human`. Each model's cells
    are joined to the human cells on product and price, then summarized.
    """
    rows: list[dict] = []
    for (model_id, condition), model_cells in sorted(cells_by_model_cond.items()):
        cond_human = human_cells.loc[human_cells["condition"] == condition]
        merged = model_cells.merge(
            cond_human[["product", "price", "p_human"]],
            on=["product", "price"],
            how="inner",
        ).rename(columns={"p": "p_model"})
        summary = summarize_model(merged)
        row = {"model_id": model_id, "condition": condition, **summary, **_model_info_row(model_id)}
        rows.append(row)
    columns = [
        "model_id",
        "display_name",
        "condition",
        "n_cells",
        "B_pp",
        "G_lin",
        "endpoint_response_pp",
        "calib_a",
        "calib_b",
        "calib_rmse_pp",
        "calib_r2",
        "pearson_r",
        "probability_method",
        "run_dir",
    ]
    return pd.DataFrame(rows, columns=columns)
