"""Counterfactual inference over parallel worlds.

The divergence report (:mod:`analysis`) describes *how far* histories drift.
This module answers what a study actually asks of them — *what did the
intervention cause, how sure can we be, and for whom?* — and it can, because
parallel worlds are an unusually clean design: every world holds the **same
residents** under the same seed, so each resident is observed under both the
treated and the control history. The potential-outcomes setup is literal
here: an individual effect ``Y_i(treated) − Y_i(control)`` is a subtraction,
not an imputation.

Per (world, metric), against the comparison world:

* **ATE** over the post-event window, with a resident-level bootstrap 95% CI,
  a sign-flip randomization p-value and the paired effect size *d_z*;
  Benjamini–Hochberg q-values across every test in the experiment.
* **Balance and DiD.** Before the first event the worlds share their trunk,
  so the pre-event gap should be ~0. When it is not (the model is not
  deterministic), the difference-in-differences is the better estimate and
  the effect is flagged rather than called.
* **Noise floor.** A world whose role is ``placebo`` bounds what the
  simulator produces on its own; an effect inside that bound is not called.
* **Dynamics.** Onset, peak, persistence and half-life of the effect curve,
  and the order in which metrics moved — a hint at the mechanism.
* **Heterogeneity** (on demand): conditional effects by resident attribute,
  with a permutation test of whether the attribute matters at all.
* **Dose–response** across worlds that carry a numeric ``dose``.
* **Replication** across seeds, pooled with a t-interval over seed effects.

Everything is deterministic (fixed RNG seed): the same artifacts give the
same intervals, so any number in a report can be reproduced.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

import numpy as np

from gaworld.parallel.analysis import DEFAULT_SPLIT_THRESHOLD, _split_step, metric_label

ALPHA = 0.05
BOOTSTRAP_SAMPLES = 2000
PERMUTATIONS = 5000
#: Up to this many residents the sign-flip test enumerates every assignment.
EXACT_PERMUTATION_MAX_N = 12
RNG_SEED = 20261002
#: A pre-event gap below this (on 0–1 metrics) is the trunk holding.
BALANCE_TOLERANCE = 0.01
#: An individual effect smaller than this is "did not move".
RESPONDER_EPS = 0.01
#: Fewer residents than this and an interval means nothing.
MIN_RESIDENTS = 3

VERDICTS = ("robust", "below_noise", "unbalanced", "suggestive", "null", "insufficient")
REPLICATION_VERDICTS = ("replicated", "consistent", "mixed", "single")

#: Two-sided 97.5% Student-t quantiles by degrees of freedom; beyond the
#: table the df=20 value is used, which is conservative for every larger df.
_T975 = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
}

_AGE_BANDS = ((30, "<30"), (45, "30–44"), (60, "45–59"))


# ---------------------------------------------------------------------------
# Small numerics
# ---------------------------------------------------------------------------


def _num(value: Any) -> float | None:
    """A finite float for JSON, or ``None``."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rng() -> np.random.Generator:
    return np.random.default_rng(RNG_SEED)


def bootstrap_ci(values: np.ndarray, rng: np.random.Generator) -> tuple[float, float, float]:
    """Percentile 95% CI and standard error of the mean, resampling residents."""
    n = len(values)
    if n == 0:
        return math.nan, math.nan, math.nan
    if n == 1:
        return float(values[0]), float(values[0]), 0.0
    means = values[rng.integers(0, n, size=(BOOTSTRAP_SAMPLES, n))].mean(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return float(low), float(high), float(means.std(ddof=1))


def sign_flip_p(values: np.ndarray, rng: np.random.Generator) -> float:
    """Two-sided randomization p-value for "the paired effect is zero".

    Under the null, which world a resident's history counts as "treated" is
    arbitrary, so each individual effect's sign is exchangeable. Exact for
    small cohorts; Monte Carlo (with the +1 correction) above that.
    """
    n = len(values)
    if n == 0:
        return math.nan
    observed = abs(float(values.mean()))
    if observed == 0.0:
        return 1.0
    tolerance = 1e-12
    if n <= EXACT_PERMUTATION_MAX_N:
        signs = np.array(list(itertools.product((1.0, -1.0), repeat=n)))
        stats = np.abs((signs * values).mean(axis=1))
        return float((stats >= observed - tolerance).mean())
    signs = rng.choice((1.0, -1.0), size=(PERMUTATIONS, n))
    stats = np.abs((signs * values).mean(axis=1))
    return float(((stats >= observed - tolerance).sum() + 1) / (PERMUTATIONS + 1))


def bh_qvalues(pvalues: list[float]) -> list[float]:
    """Benjamini–Hochberg adjusted p-values, in the input order."""
    m = len(pvalues)
    if not m:
        return []
    order = sorted(range(m), key=lambda index: pvalues[index])
    adjusted = [1.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        index = order[rank - 1]
        running = min(running, pvalues[index] * m / rank)
        adjusted[index] = min(1.0, running)
    return adjusted


def _row_mean(grid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-row mean over the non-NaN cells, and the mask of rows that had any."""
    present = ~np.isnan(grid)
    counts = present.sum(axis=1)
    sums = np.where(present, grid, 0.0).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        means = sums / counts
    return means, counts > 0


def _row_last(grid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-row value at the last non-NaN step."""
    present = ~np.isnan(grid)
    has = present.any(axis=1)
    if grid.shape[1] == 0:
        return np.full(grid.shape[0], np.nan), has
    last = grid.shape[1] - 1 - np.argmax(present[:, ::-1], axis=1)
    return grid[np.arange(grid.shape[0]), last], has


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------


def event_step(world: dict[str, Any], steps_per_day: float | None, steps: int) -> int | None:
    """Step of a world's first event, or ``None`` (no events, or no day scale).

    ``None`` means the whole horizon is the post-event window — the right
    reading for a world that differs by config from step zero.
    """
    events = [event for event in world.get("events") or [] if int(event.get("day") or 0) >= 1]
    if not events or not steps_per_day or steps <= 0:
        return None
    first = min(events, key=lambda event: (int(event["day"]), str(event.get("time") or "")))
    minutes = 0
    hours, _, mins = str(first.get("time") or "").partition(":")
    if hours.isdigit() and mins.isdigit():
        minutes = int(hours) * 60 + int(mins)
    step = (int(first["day"]) - 1) * steps_per_day + (minutes / 1440.0) * steps_per_day
    return max(0, min(steps - 1, math.floor(step)))


def _aligned(
    treated: dict[str, Any], control: dict[str, Any], metric: str
) -> tuple[list[str], np.ndarray, np.ndarray] | None:
    """The two worlds' grids for one metric, rows matched by resident id."""
    a = (treated.get("values") or {}).get(metric)
    b = (control.get("values") or {}).get(metric)
    if a is None or b is None:
        return None
    a_rows = {agent: index for index, agent in enumerate(treated.get("agents") or [])}
    b_rows = {agent: index for index, agent in enumerate(control.get("agents") or [])}
    common = [agent for agent in control.get("agents") or [] if agent in a_rows]
    if not common:
        return None
    steps = min(a.shape[1], b.shape[1])
    a_idx = [a_rows[agent] for agent in common]
    b_idx = [b_rows[agent] for agent in common]
    return common, a[a_idx, :steps], b[b_idx, :steps]


def _individual_effects(
    treated: dict[str, Any], control: dict[str, Any], metric: str, t0: int | None
) -> dict[str, Any] | None:
    """Per-resident effects: post-window mean, final, and pre-window gap."""
    aligned = _aligned(treated, control, metric)
    if aligned is None:
        return None
    agents, a, b = aligned
    diff = a - b
    start = t0 or 0
    post, has_post = _row_mean(diff[:, start:])
    final_a, has_a = _row_last(a)
    final_b, has_b = _row_last(b)
    if start > 0:
        pre, has_pre = _row_mean(diff[:, :start])
    else:
        pre, has_pre = np.full(len(agents), np.nan), np.zeros(len(agents), dtype=bool)
    base_post, has_base = _row_mean(b[:, start:])
    return {
        "agents": agents,
        "diff": diff,
        "post": post,
        "has_post": has_post,
        "final": final_a - final_b,
        "has_final": has_a & has_b,
        "pre": pre,
        "has_pre": has_pre,
        "base_post": base_post,
        "has_base": has_base,
        "start": start,
    }


# ---------------------------------------------------------------------------
# Estimates
# ---------------------------------------------------------------------------


def _estimate(world_id: str, metric: str, cells: dict[str, Any], rng: np.random.Generator) -> dict[str, Any]:
    ite = cells["post"][cells["has_post"]]
    n = len(ite)
    row: dict[str, Any] = {
        "world_id": world_id,
        "metric": metric,
        "label": metric_label(metric),
        "n": n,
        "event_step": cells["start"] or None,
    }
    if n == 0:
        row.update(ate=None, ci_low=None, ci_high=None, se=None, p_value=None, d_z=None)
        return row
    ate = float(ite.mean())
    low, high, se = bootstrap_ci(ite, rng)
    sd = float(ite.std(ddof=1)) if n > 1 else 0.0
    finals = cells["final"][cells["has_final"]]
    base_level = cells["base_post"][cells["has_base"]]
    both = cells["has_post"] & cells["has_pre"]
    pre_gap = float(cells["pre"][cells["has_pre"]].mean()) if cells["has_pre"].any() else None
    did = float((cells["post"][both] - cells["pre"][both]).mean()) if both.any() else None
    baseline_mean = float(base_level.mean()) if len(base_level) else None
    row.update(
        ate=ate,
        ci_low=low,
        ci_high=high,
        se=se,
        p_value=sign_flip_p(ite, rng),
        d_z=(ate / sd) if sd > 0 else None,
        ate_final=float(finals.mean()) if len(finals) else None,
        baseline_mean=baseline_mean,
        relative=(ate / baseline_mean) if baseline_mean else None,
        pre_gap=pre_gap,
        did=did,
        balanced=(None if pre_gap is None else abs(pre_gap) <= max(BALANCE_TOLERANCE, 0.25 * abs(ate))),
        share_up=float((ite > RESPONDER_EPS).mean()),
        share_down=float((ite < -RESPONDER_EPS).mean()),
    )
    return row


def _verdict(row: dict[str, Any], noise: float | None) -> str:
    """Fixed rules, so a verdict can be re-derived from the row by hand."""
    if row.get("ate") is None or row["n"] < MIN_RESIDENTS:
        return "insufficient"
    excludes_zero = row["ci_low"] > 0 or row["ci_high"] < 0
    if row.get("q_value", 1.0) < ALPHA and excludes_zero:
        if noise is not None and abs(row["ate"]) <= noise:
            return "below_noise"
        if row.get("balanced") is False:
            return "unbalanced"
        return "robust"
    if row["p_value"] < ALPHA or excludes_zero:
        return "suggestive"
    return "null"


def _dynamics(curve: np.ndarray, threshold: float) -> dict[str, Any]:
    """Onset, peak, persistence and half-life of one mean effect curve."""
    values = [None if math.isnan(value) else abs(float(value)) for value in curve]
    present = [(index, value) for index, value in enumerate(values) if value is not None]
    if not present:
        return {
            "onset_step": None,
            "peak_step": None,
            "peak": None,
            "final": None,
            "persistence": None,
            "half_life": None,
            "threshold": threshold,
        }
    peak_step, peak_abs = max(present, key=lambda item: item[1])
    final_step = present[-1][0]
    half_life = None
    if peak_abs > 0:
        for index, value in present:
            if index > peak_step and value < peak_abs / 2:
                half_life = index - peak_step
                break
    return {
        "onset_step": _split_step(values, threshold),
        "peak_step": peak_step,
        "peak": float(curve[peak_step]),
        "final": float(curve[final_step]),
        "persistence": (abs(float(curve[final_step])) / peak_abs) if peak_abs > 0 else None,
        "half_life": half_life,
        "threshold": threshold,
    }


def _curve_band(diff: np.ndarray) -> dict[str, list[float | None]]:
    """Mean paired effect per step with a normal-approximation 95% band."""
    present = ~np.isnan(diff)
    counts = present.sum(axis=0)
    filled = np.where(present, diff, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = filled.sum(axis=0) / counts
        var = (np.where(present, (diff - mean) ** 2, 0.0)).sum(axis=0) / np.maximum(counts - 1, 1)
        half = 1.96 * np.sqrt(var / counts)
    half = np.where(counts > 1, half, 0.0)

    def rounded(series: np.ndarray) -> list[float | None]:
        return [None if not math.isfinite(value) else round(float(value), 5) for value in series]

    return {"mean": rounded(mean), "lo": rounded(mean - half), "hi": rounded(mean + half)}


def dose_response(
    estimates: list[dict[str, Any]], worlds: list[dict[str, Any]], baseline_id: str
) -> list[dict[str, Any]]:
    """Slope of the effect against ``dose`` across the dosed treatment worlds.

    The comparison world anchors the line at its own dose (0 when unset) with
    an effect of zero by definition. Needs two dosed worlds besides it.
    """
    doses: dict[str, float] = {}
    for world in worlds:
        dose = _num(world.get("dose"))
        if world.get("id") == baseline_id:
            doses[baseline_id] = dose if dose is not None else 0.0
        elif dose is not None and world.get("role") != "placebo":
            doses[str(world.get("id"))] = dose
    if len(doses) < 3:
        return []
    rows: list[dict[str, Any]] = []
    by_metric: dict[str, list[tuple[float, float, str]]] = {}
    for row in estimates:
        if row["world_id"] in doses and row.get("ate") is not None:
            by_metric.setdefault(row["metric"], []).append(
                (doses[row["world_id"]], row["ate"], row["world_id"])
            )
    for metric, points in by_metric.items():
        points = [(doses[baseline_id], 0.0, baseline_id), *points]
        if len(points) < 3:
            continue
        x = np.array([point[0] for point in points])
        y = np.array([point[1] for point in points])
        if float(x.std()) == 0.0:
            continue
        slope, intercept = np.polyfit(x, y, 1)
        fitted = slope * x + intercept
        total = float(((y - y.mean()) ** 2).sum())
        r2 = 1.0 - float(((y - fitted) ** 2).sum()) / total if total > 0 else None
        ordered = [point[1] for point in sorted(points, key=lambda point: point[0])]
        steps = [b - a for a, b in itertools.pairwise(ordered)]
        monotonic = all(step >= -1e-9 for step in steps) or all(step <= 1e-9 for step in steps)
        rows.append(
            {
                "metric": metric,
                "label": metric_label(metric),
                "slope": float(slope),
                "intercept": float(intercept),
                "r2": r2,
                "monotonic": monotonic,
                "points": [{"world_id": wid, "dose": dose, "ate": ate} for dose, ate, wid in sorted(points)],
            }
        )
    rows.sort(key=lambda row: abs(row["slope"]), reverse=True)
    return rows


def estimate_effects(
    spec: dict[str, Any],
    panels: dict[str, dict[str, Any]],
    *,
    baseline_id: str,
    steps: int,
    steps_per_day: float | None,
    noise_reference_id: str | None = None,
) -> dict[str, Any]:
    """Every counterfactual estimate for one experiment (one seed).

    ``panels`` maps world id to the ``panel`` from
    :func:`analysis.read_state_series`; worlds without one are skipped.

    ``noise_reference_id`` is the no-intervention world a placebo is measured
    against; it defaults to ``baseline_id``. When another world is the
    comparison (two treatments read against each other), "placebo − mild" is
    a real contrast, not noise — so the floor is still measured against the
    reference, and the placebo's own row is judged like any other.
    """
    rng = _rng()
    noise_ref = noise_reference_id or baseline_id
    worlds = list(spec.get("worlds") or [])
    base_panel = panels.get(baseline_id)
    result: dict[str, Any] = {
        "baseline_id": baseline_id,
        "alpha": ALPHA,
        "method": {
            "estimand": "post_event_mean",
            "bootstrap": BOOTSTRAP_SAMPLES,
            "permutations": PERMUTATIONS,
            "exact_permutation_max_n": EXACT_PERMUTATION_MAX_N,
            "balance_tolerance": BALANCE_TOLERANCE,
            "responder_eps": RESPONDER_EPS,
            "rng_seed": RNG_SEED,
        },
        "estimates": [],
        "noise": {},
        "dynamics": {},
        "effect_curves": {},
        "event_steps": {},
        "dose_response": [],
        "placebo_ids": [],
        "noise_reference_id": noise_ref,
        "warnings": [],
        "summary": dict.fromkeys(VERDICTS, 0),
    }
    if base_panel is None:
        return result

    estimates: list[dict[str, Any]] = []
    diffs: dict[tuple[str, str], np.ndarray] = {}
    for world in worlds:
        world_id = str(world.get("id"))
        panel = panels.get(world_id)
        if world_id == baseline_id or panel is None:
            continue
        t0 = event_step(world, steps_per_day, steps)
        result["event_steps"][world_id] = t0
        metrics = sorted(set(panel.get("values") or {}) & set(base_panel.get("values") or {}))
        for metric in metrics:
            cells = _individual_effects(panel, base_panel, metric, t0)
            if cells is None:
                continue
            row = _estimate(world_id, metric, cells, rng)
            row["role"] = world.get("role") or ""
            estimates.append(row)
            diffs[(world_id, metric)] = cells["diff"]

    tested = [row for row in estimates if row.get("p_value") is not None]
    for row, q in zip(tested, bh_qvalues([row["p_value"] for row in tested]), strict=True):
        row["q_value"] = q

    placebo_ids = [
        str(w.get("id")) for w in worlds if w.get("role") == "placebo" and w.get("id") != noise_ref
    ]
    result["placebo_ids"] = placebo_ids
    # Whether this table's placebo rows *are* the noise measurement.
    measuring = noise_ref == baseline_id
    noise: dict[str, float] = {}
    if measuring:
        noise_rows = [row for row in estimates if row["world_id"] in placebo_ids]
    else:
        noise_rows = []
        ref_panel = panels.get(noise_ref)
        for world in worlds:
            world_id = str(world.get("id"))
            panel = panels.get(world_id)
            if world_id not in placebo_ids or panel is None or ref_panel is None:
                continue
            t0 = event_step(world, steps_per_day, steps)
            for metric in sorted(set(panel.get("values") or {}) & set(ref_panel.get("values") or {})):
                cells = _individual_effects(panel, ref_panel, metric, t0)
                if cells is not None:
                    noise_rows.append(_estimate(world_id, metric, cells, rng))
    for row in noise_rows:
        if row.get("ci_low") is not None:
            bound = max(abs(row["ci_low"]), abs(row["ci_high"]))
            noise[row["metric"]] = max(noise.get(row["metric"], 0.0), bound)
    result["noise"] = noise

    for row in estimates:
        is_placebo = measuring and row["world_id"] in placebo_ids
        row["noise"] = None if is_placebo else noise.get(row["metric"])
        row["verdict"] = _verdict(row, row["noise"])
        result["summary"][row["verdict"]] += 1
        if is_placebo and row["verdict"] == "robust":
            result["warnings"].append(
                {"kind": "placebo_moved", "world_id": row["world_id"], "metric": row["metric"]}
            )
        if row["verdict"] == "unbalanced":
            result["warnings"].append(
                {"kind": "unbalanced", "world_id": row["world_id"], "metric": row["metric"]}
            )

    for (world_id, metric), diff in diffs.items():
        threshold = (
            DEFAULT_SPLIT_THRESHOLD
            if measuring and world_id in placebo_ids
            else max(DEFAULT_SPLIT_THRESHOLD, noise.get(metric, 0.0))
        )
        band = _curve_band(diff)
        curve = np.array([math.nan if value is None else value for value in band["mean"]], dtype=float)
        result["dynamics"].setdefault(world_id, {"metrics": {}, "order": []})["metrics"][metric] = _dynamics(
            curve, threshold
        )
        result["effect_curves"].setdefault(world_id, {})[metric] = band
    for entry in result["dynamics"].values():
        onsets = [
            (item["onset_step"], -abs(item["peak"] or 0.0), metric)
            for metric, item in entry["metrics"].items()
            if item["onset_step"] is not None
        ]
        entry["order"] = [metric for _, _, metric in sorted(onsets)]

    estimates.sort(key=lambda row: (VERDICTS.index(row["verdict"]), -abs(row.get("ate") or 0.0)))
    result["estimates"] = estimates
    result["dose_response"] = dose_response(estimates, worlds, baseline_id)
    return result


def summarize_effects(causal: dict[str, Any], labels: dict[str, str]) -> list[str]:
    """Plain sentences for the Markdown report and the CLI."""
    lines: list[str] = []
    for row in causal.get("estimates") or []:
        if row["verdict"] not in ("robust", "below_noise", "unbalanced"):
            continue
        name = labels.get(row["world_id"], row["world_id"])
        tail = {
            "robust": "稳健",
            "below_noise": "未超过安慰剂噪声",
            "unbalanced": f"事件前已有差距 {row['pre_gap']:+.4f}，宜看 DiD {row['did']:+.4f}"
            if row.get("pre_gap") is not None and row.get("did") is not None
            else "事件前不平衡",
        }[row["verdict"]]
        lines.append(
            f"{name} · {row['label']}：ATE {row['ate']:+.4f}"
            f"（95% CI {row['ci_low']:+.4f} ~ {row['ci_high']:+.4f}，p={row['p_value']:.3g}，"
            f"q={row.get('q_value', 1.0):.3g}，n={row['n']}）— {tail}"
        )
    for warning in causal.get("warnings") or []:
        if warning["kind"] == "placebo_moved":
            lines.append(
                f"警告：安慰剂世界 {labels.get(warning['world_id'], warning['world_id'])} 在"
                f"{metric_label(warning['metric'])}上出现了显著变化——仿真本身的噪声不小"
            )
    if not lines:
        lines.append("没有任何效应同时通过 FDR 校正与置信区间检验")
    return lines


# ---------------------------------------------------------------------------
# Heterogeneity
# ---------------------------------------------------------------------------


def _age_band(value: Any) -> str | None:
    age = _num(value)
    if age is None:
        return None
    for limit, label in _AGE_BANDS:
        if age < limit:
            return label
    return "60+"


def resident_attributes(rows: list[dict[str, Any]], *, max_levels: int = 8) -> dict[str, dict[str, str]]:
    """``agent_id -> {attribute: group}`` from seed-CSV rows.

    Kept generic so another city's CSV works: ``age`` becomes bands, any
    non-numeric column with 2..``max_levels`` distinct values becomes a
    grouping, everything else (names, addresses, state metrics) is skipped.
    """
    if not rows:
        return {}
    id_key = "id" if "id" in rows[0] else "agent_id" if "agent_id" in rows[0] else None
    if id_key is None:
        return {}
    columns = [key for key in rows[0] if key not in (id_key, "name")]
    keep: list[str] = []
    for column in columns:
        values = {str(row.get(column) or "").strip() for row in rows} - {""}
        if column == "age":
            keep.append(column)
            continue
        if not 2 <= len(values) <= max_levels:
            continue
        if all(_num(value) is not None for value in values):
            continue
        keep.append(column)
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        agent = str(row.get(id_key) or "").strip()
        if not agent:
            continue
        groups: dict[str, str] = {}
        for column in keep:
            group = (
                _age_band(row.get(column))
                if column == "age"
                else (str(row.get(column) or "").strip() or None)
            )
            if group:
                groups[column] = group
        out[agent] = groups
    return out


def heterogeneity(
    treated: dict[str, Any],
    control: dict[str, Any],
    metric: str,
    t0: int | None,
    attributes: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Conditional effects by resident attribute, plus "does it matter at all".

    Besides the supplied attributes, residents are split at the median of
    their pre-event level on the same metric (``initial``) — the covariate
    most likely to matter (ceilings, regression to the mean). The test per
    attribute shuffles group labels over the individual effects and compares
    the between-group sum of squares.
    """
    rng = _rng()
    cells = _individual_effects(treated, control, metric, t0)
    if cells is None:
        return {"metric": metric, "label": metric_label(metric), "n": 0, "ate": None, "attributes": []}
    keep = cells["has_post"]
    agents = [agent for agent, ok in zip(cells["agents"], keep, strict=True) if ok]
    ite = cells["post"][keep]

    aligned = _aligned(treated, control, metric)
    groupings: dict[str, list[str | None]] = {}
    if aligned is not None:
        _, _, base = aligned
        start = cells["start"]
        level, has_level = _row_mean(base[:, :start] if start > 0 else base[:, :1])
        level = level[keep]
        has_level = has_level[keep]
        if has_level.sum() >= 2 * MIN_RESIDENTS:
            median = float(np.median(level[has_level]))
            groupings["initial"] = [
                None if not ok else ("low" if value <= median else "high")
                for value, ok in zip(level, has_level, strict=True)
            ]
    for attr in sorted({key for groups in (attributes or {}).values() for key in groups}):
        groupings[attr] = [(attributes or {}).get(agent, {}).get(attr) for agent in agents]

    out_attrs: list[dict[str, Any]] = []
    for attr, labels in groupings.items():
        index = [i for i, label in enumerate(labels) if label is not None]
        names = sorted({labels[i] for i in index}, key=str)
        if len(names) < 2:
            continue
        values = ite[index]
        codes = np.array([names.index(labels[i]) for i in index])
        groups: list[dict[str, Any]] = []
        for code, name in enumerate(names):
            subset = values[codes == code]
            low, high, _ = bootstrap_ci(subset, rng)
            groups.append(
                {
                    "group": name,
                    "n": len(subset),
                    "cate": _num(subset.mean()) if len(subset) else None,
                    "ci_low": _num(low),
                    "ci_high": _num(high),
                }
            )
        sized = [group for group in groups if group["n"] >= MIN_RESIDENTS and group["cate"] is not None]
        spread = (max(g["cate"] for g in sized) - min(g["cate"] for g in sized)) if len(sized) >= 2 else None

        def between(codes_: np.ndarray, values_: np.ndarray = values, k: int = len(names)) -> float:
            total = 0.0
            grand = values_.mean()
            for code in range(k):
                subset = values_[codes_ == code]
                if len(subset):
                    total += len(subset) * (subset.mean() - grand) ** 2
            return float(total)

        observed = between(codes)
        p_value = None
        if len(sized) >= 2 and observed > 0:
            hits = sum(between(rng.permutation(codes)) >= observed - 1e-12 for _ in range(2000))
            p_value = (hits + 1) / 2001
        out_attrs.append({"id": attr, "groups": groups, "spread": spread, "p_value": p_value})
    out_attrs.sort(key=lambda item: (item["p_value"] is None, item["p_value"] or 1.0))
    return {
        "metric": metric,
        "label": metric_label(metric),
        "n": len(ite),
        "ate": _num(ite.mean()) if len(ite) else None,
        "attributes": out_attrs,
    }


# ---------------------------------------------------------------------------
# Replication
# ---------------------------------------------------------------------------


def t_interval(values: Any) -> tuple[float, float] | None:
    """Two-sided 95% Student-t interval for the mean; ``None`` below two values."""
    array = np.asarray(list(values), dtype=float)
    n = len(array)
    if n < 2:
        return None
    mean = float(array.mean())
    half = _T975.get(n - 1, _T975[20]) * float(array.std(ddof=1)) / math.sqrt(n)
    return mean - half, mean + half


def pool_replicates(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Pool one design run under several seeds.

    ``runs`` are ``{"seed", "root", "causal"}``. A seed is one draw of the
    whole simulation, so the unit of replication is the seed-level ATE: the
    pooled interval is a t-interval over those, not over residents.
    """
    seeds = [run.get("seed") for run in runs]
    cells: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for run in runs:
        for row in (run.get("causal") or {}).get("estimates") or []:
            if row.get("ate") is None:
                continue
            cells.setdefault((row["world_id"], row["metric"]), []).append(
                {
                    "seed": run.get("seed"),
                    "ate": row["ate"],
                    "ci_low": row.get("ci_low"),
                    "ci_high": row.get("ci_high"),
                    "verdict": row.get("verdict"),
                }
            )
    rows: list[dict[str, Any]] = []
    for (world_id, metric), per_seed in cells.items():
        effects = np.array([item["ate"] for item in per_seed], dtype=float)
        n = len(effects)
        mean = float(effects.mean())
        sd = float(effects.std(ddof=1)) if n > 1 else None
        interval = t_interval(effects)
        half = (interval[1] - mean) if interval is not None else None
        sign = 1.0 if mean > 0 else -1.0 if mean < 0 else 0.0
        agree = int(sum(1 for value in effects if value * sign > 0))
        if n < 2:
            verdict = "single"
        elif agree == n and half is not None and abs(mean) > half:
            verdict = "replicated"
        elif agree == n:
            verdict = "consistent"
        else:
            verdict = "mixed"
        rows.append(
            {
                "world_id": world_id,
                "metric": metric,
                "label": metric_label(metric),
                "seeds": n,
                "per_seed": per_seed,
                "mean": mean,
                "sd": sd,
                "ci_low": (mean - half) if half is not None else None,
                "ci_high": (mean + half) if half is not None else None,
                "agree": agree,
                "verdict": verdict,
            }
        )
    rows.sort(key=lambda row: (REPLICATION_VERDICTS.index(row["verdict"]), -abs(row["mean"])))
    return {
        "seeds": seeds,
        "roots": [run.get("root") for run in runs],
        "rows": rows,
        "summary": {
            verdict: sum(1 for row in rows if row["verdict"] == verdict) for verdict in REPLICATION_VERDICTS
        },
    }


__all__ = [
    "ALPHA",
    "REPLICATION_VERDICTS",
    "VERDICTS",
    "bh_qvalues",
    "bootstrap_ci",
    "dose_response",
    "estimate_effects",
    "event_step",
    "heterogeneity",
    "pool_replicates",
    "resident_attributes",
    "sign_flip_p",
    "summarize_effects",
    "t_interval",
]
