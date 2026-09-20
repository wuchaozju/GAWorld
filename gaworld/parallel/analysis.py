"""Turn finished world runs into a divergence report.

The old comparison only looked at the last row: two numbers per metric and
their difference. That answers "did it matter?" but not "when did it start to
matter, and to whom?" — and those are the questions that make a
counterfactual worth running. So this module reconstructs the full per-step
trajectory of every world and reports three views of the same data:

* **trajectories** — mean metric value per step per world, the raw material
  for a line chart.
* **divergence** — the distance from the baseline world at each step, one
  curve per world. The step at which it first crosses a threshold is the
  point the histories split.
* **movers** — the same distance measured per agent at the end of the run,
  which is how you find the residents an intervention actually landed on
  instead of reading a population mean that averages them away.

Everything reads ``state/agent_state_history.csv``, which the simulator writes
at the end of a run with one row per (agent, step, metric).
"""

from __future__ import annotations

import csv
import math
import os
from typing import Any

#: Display names for the state metrics, so every surface (console, CLI,
#: report) names them the same way.
METRIC_LABELS: dict[str, str] = {
    "emotion": "情绪",
    "stress": "压力",
    "econ_security": "经济安全感",
    "city_identity": "城市认同",
    "policy_sensitivity": "政策敏感度",
    "platform_dependence": "平台依赖",
    "risk_preference": "风险偏好",
    "voice_propensity": "表达倾向",
    "mobility_intent": "流动意愿",
    "stance_score": "平均立场",
    "toxicity_score": "毒性风险",
    "misinformation_risk": "误信息风险",
    "cross_viewpoint_exposure": "跨观点曝光",
    "intervention_reward": "干预奖励",
    "energy": "精力",
    "hunger": "饥饿",
    "fatigue_debt": "疲劳负债",
    "self_control": "自控力",
    "social_need": "社交需求",
    "time_pressure": "时间压力",
}

#: Divergence below this is indistinguishable from the run-to-run wobble two
#: identically-configured runs show, so a split point is only called once a
#: world clears it.
DEFAULT_SPLIT_THRESHOLD = 0.02

#: Cap on the per-agent table handed to the browser.
_MAX_MOVERS = 60


def metric_label(metric: str) -> str:
    return METRIC_LABELS.get(metric, metric)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def read_state_series(path: str) -> dict[str, Any]:
    """Read one world's ``agent_state_history.csv`` into trajectories.

    Returns ``{"steps", "metrics": {metric: [mean per step]}, "agents":
    {agent_id: {metric: final}}}``. Steps are the simulator's per-agent tick
    index; a step is averaged over whichever agents reported at it, so a
    cohort where one agent stops early degrades gracefully instead of
    tearing a hole in the curve.
    """
    empty: dict[str, Any] = {"steps": 0, "metrics": {}, "agents": {}, "rows": 0}
    if not path or not os.path.exists(path):
        return empty

    # metric -> step -> [values]; agent -> metric -> (max_step, value)
    buckets: dict[str, dict[int, list[float]]] = {}
    per_agent: dict[str, dict[str, tuple[int, float]]] = {}
    rows = 0
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                value = _finite(row.get("value"))
                metric = str(row.get("metric", "")).strip()
                if value is None or not metric:
                    continue
                try:
                    step = int(float(row.get("step", 0)))
                except (TypeError, ValueError):
                    continue
                rows += 1
                buckets.setdefault(metric, {}).setdefault(step, []).append(value)
                agent = str(row.get("agent_id", "")).strip()
                if agent:
                    seen = per_agent.setdefault(agent, {}).get(metric)
                    if seen is None or step >= seen[0]:
                        per_agent[agent][metric] = (step, value)
    except OSError:
        return empty

    if not buckets:
        return empty

    steps = max(max(series) for series in buckets.values()) + 1
    metrics: dict[str, list[float | None]] = {}
    for metric, series in buckets.items():
        # `None` where no agent reported: the UI draws a gap rather than a
        # line dropping to zero, and divergence skips the step entirely.
        metrics[metric] = [
            (sum(series[step]) / len(series[step])) if step in series else None
            for step in range(steps)
        ]

    agents = {
        agent: {metric: value for metric, (_, value) in per_metric.items()}
        for agent, per_metric in per_agent.items()
    }
    return {"steps": steps, "metrics": metrics, "agents": agents, "rows": rows}


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _series_stats(series: list[float | None]) -> dict[str, float]:
    present = [value for value in series if value is not None]
    return {
        "final": present[-1] if present else 0.0,
        "mean": _mean(present),
        "first": present[0] if present else 0.0,
    }


def _divergence_curve(
    world_metrics: dict[str, list[float | None]],
    base_metrics: dict[str, list[float | None]],
    metrics: list[str],
    steps: int,
) -> list[float | None]:
    """Mean absolute gap from the baseline across metrics, step by step."""
    curve: list[float | None] = []
    for step in range(steps):
        gaps = []
        for metric in metrics:
            mine = world_metrics.get(metric) or []
            theirs = base_metrics.get(metric) or []
            if step >= len(mine) or step >= len(theirs):
                continue
            a, b = mine[step], theirs[step]
            if a is None or b is None:
                continue
            gaps.append(abs(a - b))
        curve.append(_mean(gaps) if gaps else None)
    return curve


def _split_step(curve: list[float | None], threshold: float) -> int | None:
    """First step where divergence clears the threshold and stays clear.

    "Stays clear" matters: a single tick above the line is the LLM being
    non-deterministic, not two histories parting ways.
    """
    for index, value in enumerate(curve):
        if value is None or value < threshold:
            continue
        tail = [item for item in curve[index : index + 3] if item is not None]
        if tail and all(item >= threshold for item in tail):
            return index
    return None


def _movers(
    world_agents: dict[str, dict[str, float]],
    base_agents: dict[str, dict[str, float]],
    metrics: list[str],
) -> list[dict[str, Any]]:
    """Per-agent end-of-run distance from the same agent in the baseline."""
    rows = []
    for agent_id, values in world_agents.items():
        baseline = base_agents.get(agent_id)
        if not baseline:
            continue
        deltas = {
            metric: values[metric] - baseline[metric]
            for metric in metrics
            if metric in values and metric in baseline
        }
        if not deltas:
            continue
        top_metric = max(deltas, key=lambda metric: abs(deltas[metric]))
        rows.append({
            "agent_id": agent_id,
            "distance": _mean([abs(value) for value in deltas.values()]),
            "top_metric": top_metric,
            "top_label": metric_label(top_metric),
            "top_delta": deltas[top_metric],
            "deltas": deltas,
        })
    rows.sort(key=lambda row: row["distance"], reverse=True)
    return rows[:_MAX_MOVERS]


def build_report(
    manifest: dict[str, Any],
    series_by_world: dict[str, dict[str, Any]],
    *,
    split_threshold: float = DEFAULT_SPLIT_THRESHOLD,
) -> dict[str, Any]:
    """Compare every world against the baseline named in ``manifest``.

    Worlds whose state artifacts are missing (still running, or crashed) are
    reported with ``"has_data": false`` rather than dropped, so the console can
    show a half-finished experiment instead of an empty page.
    """
    spec = manifest.get("spec", {})
    world_specs = spec.get("worlds", []) or []
    baseline_id = spec.get("baseline_id") or (world_specs[0]["id"] if world_specs else "")
    baseline = series_by_world.get(baseline_id, {"steps": 0, "metrics": {}, "agents": {}})
    base_metrics: dict[str, list[float | None]] = baseline.get("metrics", {})

    metrics = sorted({
        metric
        for series in series_by_world.values()
        for metric in (series.get("metrics") or {})
    })
    steps = max((series.get("steps", 0) for series in series_by_world.values()), default=0)

    sim_days = spec.get("sim_days")
    steps_per_day = (steps / sim_days) if (sim_days and steps) else None

    worlds: list[dict[str, Any]] = []
    trajectories: dict[str, dict[str, list[float | None]]] = {
        metric: {} for metric in metrics
    }
    divergence: dict[str, list[float | None]] = {}
    deltas: list[dict[str, Any]] = []
    movers: dict[str, list[dict[str, Any]]] = {}

    for world in world_specs:
        world_id = world.get("id")
        series = series_by_world.get(world_id) or {"steps": 0, "metrics": {}, "agents": {}}
        world_metrics: dict[str, list[float | None]] = series.get("metrics", {})
        has_data = bool(world_metrics)
        for metric in metrics:
            if metric in world_metrics:
                trajectories[metric][world_id] = world_metrics[metric]

        is_baseline = world_id == baseline_id
        curve = (
            [0.0] * steps
            if is_baseline
            else _divergence_curve(world_metrics, base_metrics, metrics, steps)
        )
        divergence[world_id] = curve
        present = [value for value in curve if value is not None]

        if not is_baseline and has_data:
            for metric in metrics:
                mine = world_metrics.get(metric)
                theirs = base_metrics.get(metric)
                if not mine or not theirs:
                    continue
                mine_stats = _series_stats(mine)
                base_stats = _series_stats(theirs)
                deltas.append({
                    "world_id": world_id,
                    "metric": metric,
                    "label": metric_label(metric),
                    "baseline_final": base_stats["final"],
                    "final": mine_stats["final"],
                    "delta_final": mine_stats["final"] - base_stats["final"],
                    "baseline_mean": base_stats["mean"],
                    "mean": mine_stats["mean"],
                    "delta_mean": mine_stats["mean"] - base_stats["mean"],
                })
            movers[world_id] = _movers(
                series.get("agents", {}), baseline.get("agents", {}), metrics
            )

        world_deltas = [row for row in deltas if row["world_id"] == world_id]
        top = max(world_deltas, key=lambda row: abs(row["delta_final"]), default=None)
        worlds.append({
            "id": world_id,
            "label": world.get("label", world_id),
            "events": world.get("events", []),
            "config": world.get("config", {}),
            "is_baseline": is_baseline,
            "has_data": has_data,
            "steps": series.get("steps", 0),
            "agents": len(series.get("agents", {})),
            "divergence_final": present[-1] if present else 0.0,
            "divergence_peak": max(present) if present else 0.0,
            "split_step": None if is_baseline else _split_step(curve, split_threshold),
            "top_metric": top["metric"] if top else None,
            "top_label": top["label"] if top else None,
            "top_delta": top["delta_final"] if top else 0.0,
        })

    deltas.sort(key=lambda row: abs(row["delta_final"]), reverse=True)
    return {
        "baseline_id": baseline_id,
        "metrics": metrics,
        "metric_labels": {metric: metric_label(metric) for metric in metrics},
        "steps": steps,
        "steps_per_day": steps_per_day,
        "sim_days": sim_days,
        "split_threshold": split_threshold,
        "worlds": worlds,
        "trajectories": trajectories,
        "divergence": divergence,
        "deltas": deltas,
        "movers": movers,
    }


def summarize_report(report: dict[str, Any]) -> list[str]:
    """A few plain sentences about what the experiment found."""
    lines: list[str] = []
    baseline = next(
        (world for world in report.get("worlds", []) if world.get("is_baseline")),
        None,
    )
    if baseline:
        lines.append(f"基准世界：{baseline['label']}")
    for world in report.get("worlds", []):
        if world.get("is_baseline"):
            continue
        if not world.get("has_data"):
            lines.append(f"{world['label']}：无状态数据（未完成或运行失败）")
            continue
        split = world.get("split_step")
        when = f"第 {split} 步开始分叉" if split is not None else "全程未明显分叉"
        top = world.get("top_label") or "—"
        direction = "上升" if world.get("top_delta", 0) > 0 else "下降"
        lines.append(
            f"{world['label']}：{when}，终局距离基准 {world['divergence_final']:.4f}"
            f"（峰值 {world['divergence_peak']:.4f}），最大变化为{top}{direction}"
            f" {abs(world.get('top_delta', 0.0)):.4f}"
        )
    return lines


__all__ = [
    "DEFAULT_SPLIT_THRESHOLD",
    "METRIC_LABELS",
    "build_report",
    "metric_label",
    "read_state_series",
    "summarize_report",
]
