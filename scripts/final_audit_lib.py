# Generic weighted-statistics helpers for the final auditable analysis.
#
# WHAT THIS FILE DOES, in plain words: it carries the small maths
# building blocks the analysis is built from — weighted averages, the
# group-gap statistic, a slope forced through zero, and the two
# resampling tools (cluster bootstrap and leave-one-out). Nothing here
# knows about the experiments; it works on any table with a "weight"
# column.
#
# Each function's job:
#   sha256_of            — file fingerprint, for the report header.
#   weighted_mean        — average with per-row weights (NaN if empty).
#   group_gap            — weighted mean of a column in group 1 minus
#                          group 0 (the D statistic).
#   slope_through_origin — least-squares slope of y on x forced through 0.
#   _slope_stat          — the through-origin slope of M on H for one group.
#   cluster_ci           — percentile bootstrap CI resampling whole clusters.
#   loo_stats            — leave-one-unit-out values of a statistic.
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
from pathlib import Path


def sha256_of(path) -> str:
    """The file's SHA256 fingerprint, for the report header."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    """Weighted average of a column (NaN when the sample is empty)."""
    total = float(np.sum(weights))
    return float(np.sum(values * weights) / total) if total > 0 else float("nan")


def group_gap(df: pd.DataFrame, column: str, group_col: str = "objective_equivalence",
              one: object = 1, zero: object = 0) -> float:
    """Weighted mean of a column for group 1 minus group 0 (the D stat)."""
    hi = df[df[group_col] == one]
    lo = df[df[group_col] == zero]
    return (weighted_mean(hi[column].to_numpy(), hi["weight"].to_numpy())
            - weighted_mean(lo[column].to_numpy(), lo["weight"].to_numpy()))


def slope_through_origin(x: np.ndarray, y: np.ndarray,
                         w: np.ndarray) -> float:
    """Least-squares slope of y on x forced through the origin."""
    denom = float(np.sum(w * x * x))
    return float(np.sum(w * x * y) / denom) if denom > 0 else float("nan")


def _slope_stat(df: pd.DataFrame, group: object) -> float:
    """The through-origin slope of M on H for one OE group."""
    sub = df[df["objective_equivalence"] == group]
    return slope_through_origin(sub["H_pp"].to_numpy(), sub["M_pp"].to_numpy(),
                                sub["weight"].to_numpy())


def cluster_ci(df: pd.DataFrame, stat_fn, clusters: pd.Series, draws: int,
               rng: np.random.Generator) -> tuple[float, float]:
    """Percentile bootstrap CI: resample whole clusters (families or
    experiments) with replacement, recompute the statistic each time."""
    labels = pd.unique(clusters)
    stats = []
    index = {lab: df[clusters == lab] for lab in labels}
    for _ in range(draws):
        pick = rng.choice(labels, size=len(labels), replace=True)
        sample = pd.concat([index[lab] for lab in pick], ignore_index=True)
        value = stat_fn(sample)
        if np.isfinite(value):
            stats.append(value)
    if len(stats) < 100:
        raise AssertionError(
            f"ASSERTION FAILED [bootstrap] only {len(stats)} usable draws")
    lo, hi = np.percentile(stats, [2.5, 97.5])
    return float(lo), float(hi)


def loo_stats(df: pd.DataFrame, stat_fn, units: pd.Series) -> list[float]:
    """Leave-one-unit-out values of a statistic (robustness check)."""
    out = []
    for unit in pd.unique(units):
        out.append(stat_fn(df[units != unit]))
    return out


