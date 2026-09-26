"""Score a protocol's predictions against what the worlds actually did.

Deterministic on purpose. Every number a report or a model interpretation
can cite comes from here, computed from the parallel worlds reports with
arithmetic a reader can redo by hand: one effect per hypothesis per seed,
its mean across seeds, the placebo world's gap from the baseline as the
noise floor, and a verdict from fixed rules.

The rules are conservative by design, because the failure this package
exists to prevent is a confident conclusion on a single seed with no
control for the simulator's own wobble:

``supported``
    every seed moved the way the prediction said, the mean effect clears
    ``min_effect`` and the placebo noise floor;
``contradicted``
    every seed moved the *other* way, by the same margins;
``inconclusive``
    anything else — and the ceiling for a single seed without a placebo;
``unmeasured``
    no seed produced both values.

Quality checks run alongside and go into the same result: a world without
state data, or a measure that never varied across any world (the
``misinformation_risk == 0.0`` case from the early experiments), is
something the reader must see before the verdicts.
"""

from __future__ import annotations

import math
from typing import Any

from gaworld.parallel.analysis import metric_label
from gaworld.research.protocol import Protocol

VERDICTS = ("supported", "contradicted", "inconclusive", "unmeasured")


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def world_values(report: dict[str, Any], aggregation: str) -> dict[str, dict[str, float]]:
    """``metric -> world_id -> value`` from one parallel worlds report.

    Read off the trajectories rather than the delta rows so the baseline
    world gets its own entry and a world with no data simply has none.
    """
    values: dict[str, dict[str, float]] = {}
    for metric, by_world in (report.get("trajectories") or {}).items():
        for world_id, series in (by_world or {}).items():
            present = [number for number in (_finite(item) for item in series or []) if number is not None]
            if not present:
                continue
            values.setdefault(str(metric), {})[str(world_id)] = (
                present[-1] if aggregation == "final" else _mean(present)
            )
    return values


def _judge(
    direction: str,
    effects: list[float],
    min_effect: float,
    noise: float | None,
    has_placebo: bool,
) -> tuple[str, list[str]]:
    if not effects:
        return "unmeasured", ["没有任何种子同时拿到处理与对照两个条件的值"]
    sign = 1.0 if direction == "increase" else -1.0
    mean = _mean(effects)
    aligned = sum(1 for effect in effects if effect * sign > 0)
    opposite = sum(1 for effect in effects if effect * sign < 0)
    reasons = [
        f"{aligned}/{len(effects)} 个种子的方向与预测一致",
        f"均值效应 {mean:+.4f}，最小效应要求 {min_effect:.4f}",
    ]
    if noise is None:
        reasons.append("没有安慰剂世界，无噪声底线")
    else:
        reasons.append(f"安慰剂噪声底线 {noise:.4f}")
    if len(effects) < 2 and not has_placebo:
        reasons.append("只有一个种子且无安慰剂，无法排除运行噪声")
        return "inconclusive", reasons

    clears = abs(mean) >= min_effect and (noise is None or abs(mean) > noise)
    if aligned == len(effects) and clears:
        return "supported", reasons
    if opposite == len(effects) and clears:
        reasons.append("所有种子都朝预测的反方向移动")
        return "contradicted", reasons
    if not clears:
        reasons.append("效应没有同时超过最小效应与噪声底线")
    if 0 < aligned < len(effects):
        reasons.append("种子之间方向不一致")
    return "inconclusive", reasons


def _quality(protocol: Protocol, runs: list[dict[str, Any]], table: dict[str, dict[str, dict[int, float]]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    for run in runs:
        report = run.get("report") or {}
        by_id = {str(world.get("id")): world for world in report.get("worlds") or []}
        for cond in protocol.conditions:
            world = by_id.get(cond["id"])
            if world is None or not world.get("has_data"):
                issues.append({
                    "seed": run.get("seed"),
                    "condition": cond["id"],
                    "issue": "没有状态数据（未完成或运行失败）",
                    "detail": str((world or {}).get("error") or (world or {}).get("status") or "missing"),
                })
    for measure in protocol.measures:
        values = [value for by_seed in table.get(measure["id"], {}).values() for value in by_seed.values()]
        if runs and not values:
            issues.append({
                "seed": None,
                "condition": None,
                "issue": f"指标 {measure['label']}（{measure['id']}）没有任何数据",
                "detail": "记录它的插件可能没有开启",
            })
        elif values and len({round(value, 6) for value in values}) <= 1:
            issues.append({
                "seed": None,
                "condition": None,
                "issue": f"指标 {measure['label']}（{measure['id']}）在所有世界、所有种子里都没有变化",
                "detail": f"恒为 {values[0]:.4f}",
            })
    return {"ok": not issues, "issues": issues}


def evaluate(protocol: Protocol, runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Verdict per hypothesis, the value table behind it, and quality issues.

    ``runs`` is what :func:`gaworld.research.backends.run_protocol` returns:
    one entry per seed with the parallel worlds ``report`` attached.
    """
    baseline = protocol.baseline_id
    placebo = next((cond["id"] for cond in protocol.conditions if cond["role"] == "placebo"), None)
    per_run: dict[int, dict[str, dict[str, dict[str, float]]]] = {}
    for run in runs:
        seed = int(run.get("seed", 0))
        report = run.get("report") or {}
        per_run[seed] = {agg: world_values(report, agg) for agg in ("final", "mean")}

    # metric -> world -> seed -> final value: the table the report prints.
    table: dict[str, dict[str, dict[int, float]]] = {}
    for seed, by_agg in per_run.items():
        for metric, by_world in by_agg["final"].items():
            for world_id, value in by_world.items():
                table.setdefault(metric, {}).setdefault(world_id, {})[seed] = value

    hypotheses: list[dict[str, Any]] = []
    for hypothesis in protocol.hypotheses:
        metric = hypothesis["measure"]
        aggregation = hypothesis.get("aggregation") or "final"
        rows: list[dict[str, Any]] = []
        effects: list[float] = []
        placebo_gaps: list[float] = []
        for seed, by_agg in per_run.items():
            by_world = by_agg[aggregation].get(metric, {})
            treatment = by_world.get(hypothesis["treatment"])
            control = by_world.get(hypothesis["control"])
            gap = None
            if placebo is not None and placebo in by_world and baseline in by_world:
                gap = abs(by_world[placebo] - by_world[baseline])
                placebo_gaps.append(gap)
            effect = None if treatment is None or control is None else treatment - control
            if effect is not None:
                effects.append(effect)
            rows.append({
                "seed": seed,
                "treatment_value": treatment,
                "control_value": control,
                "effect": effect,
                "placebo_gap": gap,
            })
        noise = max(placebo_gaps) if placebo_gaps else None
        verdict, reasons = _judge(
            hypothesis["direction"], effects, float(hypothesis.get("min_effect") or 0.0), noise, placebo is not None
        )
        hypotheses.append({
            **hypothesis,
            "measure_label": metric_label(metric),
            "effects": rows,
            "mean_effect": _mean(effects) if effects else None,
            "noise": noise,
            "seeds_with_data": len(effects),
            "verdict": verdict,
            "reasons": reasons,
        })

    summary = {verdict: sum(1 for item in hypotheses if item["verdict"] == verdict) for verdict in VERDICTS}
    return {
        "seeds": sorted(per_run),
        "baseline_id": baseline,
        "placebo_id": placebo,
        "hypotheses": hypotheses,
        "values": table,
        "quality": _quality(protocol, runs, table),
        "summary": summary,
    }


__all__ = ["VERDICTS", "evaluate", "world_values"]
