"""Comparison metrics for the group-vs-individual validation gate.

Pure functions, no simulation state. Each one answers a question the design
doc's validation layers pose, and each is implemented from scratch rather than
pulled from ``scipy`` — the project deliberately has no scipy dependency, and
these are all short enough that a hand-rolled version is auditable.

The choice of metric per layer matters more than the arithmetic:

``L1``  Wasserstein-1 and the KS statistic, because the claim being tested is
        distributional. Comparing means would pass an approximation that had
        collapsed the distribution to a point at the right centre.
``L2``  Moran's I on the social graph, because the question is whether
        neighbour-mediated co-movement survives. Degree and clustering are
        properties of the *static* graph and are identical in both tiers by
        construction, so testing them would be a tautology.
``L3``  tail shares and first-passage times, kept separate from L1 because
        aggregate approximation is known to compress tails while leaving the
        bulk distribution looking fine.
``L4``  treatment effects and their heterogeneity across subgroups, because a
        run can match on every static statistic and still respond to a policy
        shock in the wrong direction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# L1 — distributional distance
# ---------------------------------------------------------------------------


def wasserstein1(a: Sequence[float], b: Sequence[float]) -> float:
    """Earth-mover distance between two 1-D empirical distributions.

    For equal-length samples this is the mean absolute difference of sorted
    values; the general case interleaves both supports and integrates the CDF
    gap. Reported in the same units as the variable, so a value of 0.03 on a
    [0,1] state variable means "the distributions are 3 percentage points apart
    on average", which is directly interpretable.
    """
    x = np.sort(np.asarray(a, dtype=float))
    y = np.sort(np.asarray(b, dtype=float))
    if x.size == 0 or y.size == 0:
        return 0.0
    if x.size == y.size:
        return float(np.abs(x - y).mean())
    grid = np.sort(np.concatenate([x, y]))
    cdf_x = np.searchsorted(x, grid, side="right") / x.size
    cdf_y = np.searchsorted(y, grid, side="right") / y.size
    widths = np.diff(grid)
    return float(np.sum(np.abs(cdf_x[:-1] - cdf_y[:-1]) * widths))


def ks_statistic(a: Sequence[float], b: Sequence[float]) -> float:
    """Two-sample Kolmogorov–Smirnov statistic (the sup CDF gap)."""
    x = np.sort(np.asarray(a, dtype=float))
    y = np.sort(np.asarray(b, dtype=float))
    if x.size == 0 or y.size == 0:
        return 0.0
    grid = np.sort(np.concatenate([x, y]))
    cdf_x = np.searchsorted(x, grid, side="right") / x.size
    cdf_y = np.searchsorted(y, grid, side="right") / y.size
    return float(np.max(np.abs(cdf_x - cdf_y)))


def distribution_gap(
    reference: Mapping[str, Sequence[float]], candidate: Mapping[str, Sequence[float]]
) -> dict[str, dict[str, float]]:
    """Per-variable L1 comparison of two populations."""
    out: dict[str, dict[str, float]] = {}
    for key in reference:
        if key not in candidate:
            continue
        ref = np.asarray(reference[key], dtype=float)
        cand = np.asarray(candidate[key], dtype=float)
        out[key] = {
            "wasserstein1": wasserstein1(ref.tolist(), cand.tolist()),
            "ks": ks_statistic(ref.tolist(), cand.tolist()),
            "mean_gap": float(cand.mean() - ref.mean()) if ref.size and cand.size else 0.0,
            "sd_ratio": (
                float(cand.std() / ref.std()) if ref.size and cand.size and ref.std() > 1e-9 else 1.0
            ),
        }
    return out


# ---------------------------------------------------------------------------
# L2 — network-mediated co-movement
# ---------------------------------------------------------------------------


def morans_i(values: Mapping[int, float], neighbours: Mapping[int, Sequence[int]]) -> float:
    """Moran's I: spatial (here, social) autocorrelation of ``values``.

    +1 means connected agents move together, 0 means the graph carries no
    signal, −1 means neighbours move oppositely. This is the L2 discriminator:
    an individual tier with social influence should produce positive I on state
    *changes*, while a cohort tier that applies a uniform within-cohort shift
    can only produce co-movement along cohort boundaries — which is not the
    same graph and generally gives I near zero.

    Returns 0.0 for a degenerate input (no edges, or no variance in values)
    rather than NaN, so callers can threshold it without special-casing.
    """
    ids = [i for i in values if i in neighbours]
    if len(ids) < 3:
        return 0.0
    index = {node: position for position, node in enumerate(ids)}
    x = np.array([float(values[i]) for i in ids])
    deviation = x - x.mean()
    denominator = float((deviation**2).sum())
    if denominator <= 1e-12:
        return 0.0

    weight_total = 0.0
    cross = 0.0
    for node in ids:
        position = index[node]
        for peer in neighbours.get(node, ()):
            peer_position = index.get(peer)
            if peer_position is None:
                continue
            weight_total += 1.0
            cross += deviation[position] * deviation[peer_position]
    if weight_total <= 0:
        return 0.0
    return float((len(ids) / weight_total) * (cross / denominator))


# ---------------------------------------------------------------------------
# L3 — tails and rare events
# ---------------------------------------------------------------------------


def tail_shares(values: Sequence[float], *, low: float = 0.2, high: float = 0.8) -> dict[str, float]:
    """Share of the population in each tail, plus the interdecile spread."""
    x = np.asarray(values, dtype=float)
    if x.size == 0:
        return {"low_share": 0.0, "high_share": 0.0, "p10_p90_spread": 0.0}
    return {
        "low_share": float((x <= low).mean()),
        "high_share": float((x >= high).mean()),
        "p10_p90_spread": float(np.percentile(x, 90) - np.percentile(x, 10)),
    }


def first_passage_days(
    trajectories: Mapping[int, Sequence[float]], threshold: float, *, above: bool = True
) -> dict[str, float]:
    """When agents first cross ``threshold``, and how many ever do.

    Aggregate approximations tend to delay and under-count threshold crossings,
    because a smoothed mean reaches an extreme later than the fastest members
    of a heterogeneous population do. Reporting both the *rate* and the *timing*
    separates "nobody got there" from "everybody got there late".
    """
    times: list[int] = []
    crossed = 0
    for series in trajectories.values():
        for day, value in enumerate(series, start=1):
            hit = float(value) >= threshold if above else float(value) <= threshold
            if hit:
                times.append(day)
                crossed += 1
                break
    total = max(1, len(trajectories))
    return {
        "crossing_rate": crossed / total,
        "median_first_passage_day": float(np.median(times)) if times else float("nan"),
        "n_crossed": float(crossed),
    }


# ---------------------------------------------------------------------------
# L4 — treatment effects
# ---------------------------------------------------------------------------


def average_treatment_effect(control: Mapping[int, float], treated: Mapping[int, float]) -> float:
    """Mean paired difference. Pairing is by agent id, so the same initial
    population is compared against itself under two conditions and individual
    heterogeneity cancels instead of adding noise."""
    shared = [i for i in control if i in treated]
    if not shared:
        return 0.0
    return float(np.mean([treated[i] - control[i] for i in shared]))


def heterogeneous_effects(
    control: Mapping[int, float],
    treated: Mapping[int, float],
    subgroups: Mapping[int, str],
) -> dict[str, float]:
    """Per-subgroup ATE. The design doc's L4 bar is that these must not
    *vanish*: an approximation that reproduces the overall effect while
    flattening its distribution across subgroups is useless for policy work,
    which is usually about who is affected rather than by how much on average.
    """
    buckets: dict[str, list[float]] = {}
    for agent_id, group in subgroups.items():
        if agent_id in control and agent_id in treated:
            buckets.setdefault(group, []).append(treated[agent_id] - control[agent_id])
    return {group: float(np.mean(values)) for group, values in buckets.items() if values}


def effect_heterogeneity_spread(effects: Mapping[str, float]) -> float:
    """Spread of subgroup effects — the quantity L4 checks has not collapsed."""
    values = list(effects.values())
    return float(np.std(values)) if len(values) > 1 else 0.0


def sign_agreement(reference: Mapping[str, float], candidate: Mapping[str, float]) -> float:
    """Fraction of subgroups where both runs agree on the direction of effect.

    Checked separately from magnitude because a sign flip is a qualitatively
    different failure: it would lead a researcher to the opposite policy
    conclusion, which no amount of magnitude accuracy compensates for.
    """
    shared = [k for k in reference if k in candidate]
    if not shared:
        return 1.0
    agree = sum(1 for k in shared if (reference[k] >= 0) == (candidate[k] >= 0) or abs(reference[k]) < 1e-9)
    return agree / len(shared)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def state_columns(agents: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> dict[str, list[float]]:
    """Pivot a list of agent dicts into per-state-variable columns."""
    columns: dict[str, list[float]] = {key: [] for key in keys}
    for agent in agents:
        state = agent.get("state") or {}
        for key in keys:
            value = state.get(key)
            if isinstance(value, (int, float)):
                columns[key].append(float(value))
    return columns


__all__ = [
    "average_treatment_effect",
    "distribution_gap",
    "effect_heterogeneity_spread",
    "first_passage_days",
    "heterogeneous_effects",
    "ks_statistic",
    "morans_i",
    "sign_agreement",
    "state_columns",
    "tail_shares",
    "wasserstein1",
]
