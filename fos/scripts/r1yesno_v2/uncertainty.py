# This file puts error bars on the model-vs-human price comparison. Instead
# of one number for "how much faster than humans does the model lose interest
# with price" (the ratio G), it re-computes that number many times on
# resampled data to get a range of plausible values. Its functions:
#   ols_slope — the slope of the best straight line through (price, answer)
#     points;
#   collect_clusters — group long answer tables into one bundle per
#     (product, persona) pair, keeping every row with its own bundle;
#   full_sample_slope — the straight-line slope of all rows of all bundles
#     pooled into one fit (the point estimate the resamples vary around);
#   cluster_bootstrap — re-draw whole bundles with replacement (the same
#     bundles for the model and the human inside one draw) and return the
#     spread of slopes and of G = model slope / human slope;
#   bayesian_bootstrap — same idea, but each bundle gets a random weight
#     (all rows in a bundle share the weight) instead of in-or-out;
#   summarize — turn a spread of draws into (center, low, high) using the
#     middle 95% bounds, ignoring broken (NaN) draws;
#   paired_difference — subtract two draw arrays draw-by-draw (used to
#     compare blinded vs unblinded runs on the same resamples).

from __future__ import annotations

import numpy as np
import pandas as pd

VALUE_COLUMNS = ("price_scaled", "p")
_DRAW_CHUNK = 500


def ols_slope(x: np.ndarray, y: np.ndarray) -> float:
    """Return the slope of the best straight line through (x, y) points.

    Needs at least two points and at least two distinct x values; otherwise
    a ValueError is raised (a slope through one point or one x value does
    not exist).
    """
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    if x_arr.ndim != 1 or y_arr.ndim != 1:
        raise ValueError("ols_slope needs one-dimensional x and y arrays")
    if x_arr.size != y_arr.size:
        raise ValueError(
            f"x and y must have equal length, got {x_arr.size} vs {y_arr.size}"
        )
    if x_arr.size < 2:
        raise ValueError(f"need at least 2 points for a slope, got {x_arr.size}")
    x_centered = x_arr - x_arr.mean()
    sxx = float((x_centered**2).sum())
    if sxx == 0.0:
        raise ValueError("all x values are identical; slope is undefined")
    sxy = float((x_centered * (y_arr - y_arr.mean())).sum())
    return sxy / sxx


def collect_clusters(
    df: pd.DataFrame, persona_cols: tuple[str, ...] = ("product", "persona")
) -> dict[tuple, np.ndarray]:
    """Group a long answer table into one bundle per (product, persona) pair.

    `df` needs the group columns (`persona_cols`) plus the value columns
    `price_scaled` and `p`. Every row lands in exactly one bundle and keeps
    its own price and answer; bundles are (n_rows, 2) arrays of
    [price_scaled, p] stacked as rows. Rows with a null group value or a
    null value column raise a ValueError — drop or fix them first, nothing
    is silently discarded here.
    """
    required = set(persona_cols) | set(VALUE_COLUMNS)
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"cluster table missing columns: {sorted(missing)}")
    null_keys = df[list(persona_cols)].isna().any(axis=1)
    if null_keys.any():
        raise ValueError(
            f"{int(null_keys.sum())} rows have a null cluster key; drop them first"
        )
    null_values = df[list(VALUE_COLUMNS)].isna().any(axis=1)
    if null_values.any():
        raise ValueError(
            f"{int(null_values.sum())} rows have a null price_scaled/p; drop them first"
        )
    clusters: dict[tuple, np.ndarray] = {}
    for key, group in df.groupby(list(persona_cols), sort=True):
        tuple_key = key if isinstance(key, tuple) else (key,)
        clusters[tuple_key] = np.column_stack(
            [group["price_scaled"].to_numpy(float), group["p"].to_numpy(float)]
        )
    return clusters


def _cluster_stats(cluster: np.ndarray) -> np.ndarray:
    """Summarize one bundle as (n, mean_x, mean_y, centered sxx, centered sxy).

    The centered sums (deviations from the bundle's own means) let many
    bundles be pooled later without re-reading the raw rows.
    """
    arr = np.asarray(cluster, dtype=float)
    x = arr[:, 0]
    y = arr[:, 1]
    x_mean = float(x.mean())
    y_mean = float(y.mean())
    x_centered = x - x_mean
    return np.array(
        [
            float(x.size),
            x_mean,
            y_mean,
            float((x_centered**2).sum()),
            float((x_centered * (y - y_mean)).sum()),
        ]
    )


def _stats_matrix(clusters: dict[tuple, np.ndarray]) -> np.ndarray:
    """Stack the per-bundle summaries of a cluster dict into one matrix."""
    return np.array([_cluster_stats(cluster) for cluster in clusters.values()])


def _pooled_slopes(bundles: np.ndarray) -> np.ndarray:
    """Slope of the pooled points of one or many bundles-of-bundles.

    `bundles` is (…, n_bundles, 5): per-bundle stats (n, mean_x, mean_y,
    centered sxx, centered sxy) with any number of leading batch dimensions.
    Every batch entry is re-centered on its own pooled means (the standard
    parallel update), so pooled points whose answers are all flat give a
    slope of exactly 0.0, and pooled points with no price variation give
    NaN. A 2-D input returns one scalar; a 3-D input returns one slope per
    batch row.
    """
    arr = np.asarray(bundles, dtype=float)
    single = arr.ndim == 2
    if single:
        arr = arr[None, :, :]
    n, x_mean, y_mean = arr[..., 0], arr[..., 1], arr[..., 2]
    sxx, sxy = arr[..., 3], arr[..., 4]
    total_n = n.sum(axis=-1, keepdims=True)
    pooled_x = (n * x_mean).sum(axis=-1, keepdims=True) / total_n
    pooled_y = (n * y_mean).sum(axis=-1, keepdims=True) / total_n
    pooled_sxx = (sxx + n * (x_mean - pooled_x) ** 2).sum(axis=-1)
    pooled_sxy = (sxy + n * (x_mean - pooled_x) * (y_mean - pooled_y)).sum(axis=-1)
    slopes = np.where(pooled_sxx == 0.0, np.nan, pooled_sxy / pooled_sxx)
    return slopes[0] if single else slopes


def full_sample_slope(clusters: dict[tuple, np.ndarray]) -> float:
    """Slope of every observation in every bundle pooled into one fit."""
    return float(_pooled_slopes(_stats_matrix(clusters)))


def _classical_slopes(stats: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """Pooled slope of each resample, from sampled-bundle stats.

    `idx` is (n_draws, n_clusters) of sampled bundle positions; row d pools
    the stats of the bundles it sampled. Processed in chunks so the gathered
    (chunk, n_clusters, 5) tensor stays small.
    """
    slopes = np.empty(idx.shape[0], dtype=float)
    for start in range(0, idx.shape[0], _DRAW_CHUNK):
        sel = idx[start : start + _DRAW_CHUNK]
        slopes[start : start + sel.shape[0]] = _pooled_slopes(stats[sel])
    return slopes


def _weighted_slopes(stats: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Weighted pooled slope for every weight vector (one per draw).

    `weights` is (n_draws, n_clusters); every row in a bundle carries its
    bundle's weight. Only the count-like stat components (n, centered sxx,
    centered sxy) scale with the weight — the bundle means stay as they are
    so that weight*mean*count products stay linear in the weight (multiplying
    everything would square the weight). Pooling the scaled rows exactly
    reproduces the weighted least-squares slope.
    """
    slopes = np.empty(weights.shape[0], dtype=float)
    for start in range(0, weights.shape[0], _DRAW_CHUNK):
        w = weights[start : start + _DRAW_CHUNK]
        weighted = np.empty((w.shape[0], stats.shape[0], stats.shape[1]), dtype=float)
        weighted[..., 0] = w * stats[None, :, 0]
        weighted[..., 1] = stats[None, :, 1]
        weighted[..., 2] = stats[None, :, 2]
        weighted[..., 3] = w * stats[None, :, 3]
        weighted[..., 4] = w * stats[None, :, 4]
        slopes[start : start + w.shape[0]] = _pooled_slopes(weighted)
    return slopes


def _safe_ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    """Divide draw-by-draw, mapping zero (or NaN) denominators to NaN.

    G = model slope / human slope is meaningless when the human slope is 0,
    so those draws become NaN and are dropped later, never read as infinity.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = numerator / denominator
    return np.where(denominator == 0.0, np.nan, ratio)


def _aligned_human_stats(
    model_clusters: dict[tuple, np.ndarray],
    human_clusters: dict[tuple, np.ndarray],
) -> tuple[list[tuple], np.ndarray, np.ndarray]:
    """Stack model and human bundle summaries in one shared key order.

    The sampling frame is the model's keys; the human table must contain
    every one of them (its extra keys, if any, are unused). Returns the key
    list plus both stats matrices in that order.
    """
    if not model_clusters:
        raise ValueError("model_clusters is empty; nothing to resample")
    keys = list(model_clusters.keys())
    missing = [key for key in keys if key not in human_clusters]
    if missing:
        raise ValueError(
            f"human_clusters is missing {len(missing)} model cluster keys, e.g. {missing[:3]}"
        )
    model_stats = _stats_matrix(model_clusters)
    human_stats = np.array(
        [_cluster_stats(human_clusters[key]) for key in keys], dtype=float
    )
    return keys, model_stats, human_stats


def _draws_to_result(
    beta_human: np.ndarray, beta_model: np.ndarray
) -> dict[str, np.ndarray]:
    """Bundle slope draws and their ratio into the contract result dict."""
    return {
        "beta_human": beta_human,
        "beta_model": beta_model,
        "G": _safe_ratio(beta_model, beta_human),
    }


def cluster_bootstrap(
    model_clusters: dict[tuple, np.ndarray],
    human_clusters: dict[tuple, np.ndarray],
    n_draws: int = 5000,
    seed: int = 42,
) -> dict[str, np.ndarray]:
    """Re-draw whole bundles with replacement; return slope and G draws.

    Each draw samples the (product, persona) bundles with replacement and
    refits BOTH slopes on the same sampled bundles — the model's rows and
    the human's rows of those bundles — so G stays a like-for-like ratio.
    Same seed gives byte-identical draws.
    """
    keys, model_stats, human_stats = _aligned_human_stats(
        model_clusters, human_clusters
    )
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(keys), size=(n_draws, len(keys)))
    beta_model = _classical_slopes(model_stats, idx)
    beta_human = _classical_slopes(human_stats, idx)
    return _draws_to_result(beta_human, beta_model)


def bayesian_bootstrap(
    model_clusters: dict[tuple, np.ndarray],
    human_clusters: dict[tuple, np.ndarray],
    n_draws: int = 5000,
    seed: int = 43,
) -> dict[str, np.ndarray]:
    """Weight every bundle by a random share instead of in-or-out.

    Each draw pulls one weight vector from a flat Dirichlet over the
    bundles; every row inside a bundle carries its bundle's weight, and both
    slopes are refit with those same weights. Same seed gives identical
    weights, hence identical draws.
    """
    keys, model_stats, human_stats = _aligned_human_stats(
        model_clusters, human_clusters
    )
    rng = np.random.default_rng(seed)
    weights = rng.dirichlet(np.ones(len(keys)), size=n_draws)
    beta_model = _weighted_slopes(model_stats, weights)
    beta_human = _weighted_slopes(human_stats, weights)
    return _draws_to_result(beta_human, beta_model)


def summarize(draws: np.ndarray, point_estimate: float) -> tuple[float, float, float]:
    """Return (point estimate, 2.5th, 97.5th percentile) of a draw array.

    NaN draws (meaningless ratios) are ignored. If every draw is NaN there
    is no interval to report and a ValueError is raised.
    """
    arr = np.asarray(draws, dtype=float)
    valid = arr[~np.isnan(arr)]
    if valid.size == 0:
        raise ValueError("all draws are NaN; no interval can be formed")
    lo, hi = np.percentile(valid, [2.5, 97.5])
    return (float(point_estimate), float(lo), float(hi))


def paired_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Subtract two draw arrays draw-by-draw (a minus b).

    The arrays must have identical shapes so draw d is always compared with
    draw d; anything else raises a ValueError instead of misaligning.
    """
    a_arr = np.asarray(a, dtype=float)
    b_arr = np.asarray(b, dtype=float)
    if a_arr.shape != b_arr.shape:
        raise ValueError(
            f"paired_difference needs equal shapes, got {a_arr.shape} vs {b_arr.shape}"
        )
    return a_arr - b_arr
