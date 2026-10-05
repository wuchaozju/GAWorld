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

Each seed's parallel worlds report also carries paired per-resident
estimates (:mod:`gaworld.parallel.causal`). When a hypothesis's control is
the world those were computed against, they are a second, stricter gate:
``supported`` / ``contradicted`` additionally need every seed's paired test
to be significant (BH q < 0.05, 95% CI excluding 0) in the claimed
direction, or the verdict falls back to ``inconclusive``. The paired test
reads the post-event mean, which is why it gates and does not replace the
pre-registered effect. A seed-level t-interval is reported alongside.

A composite study's survey measures get the same gate from the survey
itself: the same residents answered in every world, so each resident's
answer in the treatment world minus their answer in the control world is one
individual effect (bootstrap CI, sign-flip p, BH across that seed's survey
hypotheses), whatever the control is.

Every hypothesis also carries the provenance grade of its measure
(:mod:`gaworld.research.measures`). The verdict rules do not change with it;
what changes is how the number may be read: on a (c) measure — driven by
values we chose, not calibrated — the direction is the finding and the size
is not, and the result says so next to the effect.

Quality checks run alongside and go into the same result: a world without
state data, or a measure that never varied across any world (the
``misinformation_risk == 0.0`` case from the early experiments), is
something the reader must see before the verdicts.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from gaworld.core.comparability import describe as describe_epoch
from gaworld.core.comparability import same_epoch
from gaworld.parallel.analysis import metric_label
from gaworld.parallel.causal import ALPHA, RNG_SEED, bh_qvalues, bootstrap_ci, sign_flip_p, t_interval
from gaworld.research import survey as survey_mod
from gaworld.research.measures import direction_only, registry
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


def survey_values(run: dict[str, Any]) -> dict[str, dict[str, float]]:
    """``world_id -> measure -> score`` from one seed's survey, scored ones only."""
    out: dict[str, dict[str, float]] = {}
    for world_id, block in (run.get("survey") or {}).items():
        if not isinstance(block, dict):
            continue
        for metric, score in (block.get("scores") or {}).items():
            value = _finite((score or {}).get("value"))
            if value is not None:
                out.setdefault(str(world_id), {})[str(metric)] = value
    return out


def _survey_quality(protocol: Protocol, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if protocol.kind != "composite":
        return issues
    for run in runs:
        block = run.get("survey")
        if not isinstance(block, dict) or block.get("error"):
            issues.append({"seed": run.get("seed"), "condition": None, "issue": "问卷没有跑成",
                           "detail": str((block or {}).get("error") or "没有问卷结果")})
            continue
        for cond in protocol.conditions:
            world = block.get(cond["id"])
            if not isinstance(world, dict) or world.get("error"):
                issues.append({"seed": run.get("seed"), "condition": cond["id"], "issue": "这个世界的问卷没有结果",
                               "detail": str((world or {}).get("error") or "missing")})
                continue
            for metric, score in (world.get("scores") or {}).items():
                asked = int(score.get("asked") or 0)
                unparsed = int(score.get("unparsed") or 0)
                if asked and unparsed / asked > 0.2:
                    issues.append({"seed": run.get("seed"), "condition": cond["id"],
                                   "issue": f"{metric}：{unparsed}/{asked} 个回答无法计分",
                                   "detail": "回答没能对上选项或是/否，已排除在得分之外"})
    return issues


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


def paired_estimate(report: dict[str, Any], treatment: str, control: str, metric: str) -> dict[str, Any] | None:
    """The per-resident estimate of ``treatment`` vs ``control`` in one seed's
    report, when the report's estimates were computed against that control."""
    causal = report.get("causal") or {}
    if causal.get("baseline_id") != control:
        return None
    for row in causal.get("estimates") or []:
        if row.get("world_id") == treatment and row.get("metric") == metric and row.get("ate") is not None:
            return {
                key: row.get(key)
                for key in ("ate", "ci_low", "ci_high", "p_value", "q_value", "n", "verdict")
            }
    return None


def measure_provenance(protocol: Protocol) -> dict[str, dict[str, str]]:
    """``measure id -> {grade, basis}``: as the protocol recorded it, else as
    the catalogue has it today (protocols compiled before grades existed)."""
    reg = {**registry(), **survey_mod.survey_measures(protocol.survey)}
    out = {mid: {"grade": m.grade, "basis": m.basis} for mid, m in reg.items()}
    for item in protocol.measures or []:
        if isinstance(item, dict) and item.get("grade"):
            out[str(item.get("id"))] = {"grade": str(item["grade"]), "basis": str(item.get("basis") or "")}
    return out


def survey_paired(protocol: Protocol, runs: list[dict[str, Any]]) -> dict[tuple[int, str, str, str], dict[str, Any]]:
    """``(seed, treatment, control, measure) -> paired test`` for survey hypotheses."""
    out: dict[tuple[int, str, str, str], dict[str, Any]] = {}
    for run in runs:
        seed = int(run.get("seed", 0))
        block = run.get("survey") or {}
        rng = np.random.default_rng(RNG_SEED + seed)
        tests: dict[tuple[int, str, str, str], dict[str, Any]] = {}
        for hypothesis in protocol.hypotheses:
            metric = hypothesis["measure"]
            key = (seed, hypothesis["treatment"], hypothesis["control"], metric)
            if not metric.startswith(survey_mod.PREFIX) or key in tests:
                continue
            answers = [
                (((block.get(world) or {}).get("scores") or {}).get(metric) or {}).get("by_resident") or {}
                for world in (hypothesis["treatment"], hypothesis["control"])
            ]
            both = sorted(set(answers[0]) & set(answers[1]))
            if not both:
                continue
            diffs = np.array([float(answers[0][ref]) - float(answers[1][ref]) for ref in both])
            low, high, _ = bootstrap_ci(diffs, rng)
            tests[key] = {"ate": float(diffs.mean()), "ci_low": low, "ci_high": high,
                          "p_value": sign_flip_p(diffs, rng), "n": len(both)}
        for test, q in zip(tests.values(), bh_qvalues([t["p_value"] for t in tests.values()]), strict=True):
            test["q_value"] = q
        out.update(tests)
    return out


def _paired_gate(verdict: str, direction: str, rows: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Downgrade a call the residents' own paired tests do not back."""
    evidence = [row for row in rows if row.get("effect") is not None]
    paired = [row for row in evidence if row.get("paired")]
    if not paired:
        return verdict, []
    if len(paired) < len(evidence):
        return verdict, [f"仅 {len(paired)}/{len(evidence)} 个种子有居民配对检验，未作为判定条件"]
    if verdict not in ("supported", "contradicted"):
        return verdict, []
    sign = 1.0 if direction == "increase" else -1.0
    if verdict == "contradicted":
        sign = -sign
    failing = []
    for row in paired:
        test = row["paired"]
        low, high, q = test.get("ci_low"), test.get("ci_high"), test.get("q_value")
        clears = low is not None and high is not None and (low > 0 if sign > 0 else high < 0)
        if not (clears and q is not None and q < ALPHA):
            failing.append(
                f"种子 {row['seed']}（ATE {test['ate']:+.4f}，95% CI "
                f"{'—' if low is None else f'{low:+.4f}'} ~ {'—' if high is None else f'{high:+.4f}'}，"
                f"q={'—' if q is None else f'{q:.3g}'}）"
            )
    if failing:
        return "inconclusive", ["居民配对检验（事件后均值）在以下种子不显著，降为 inconclusive：" + "；".join(failing)]
    return verdict, [f"所有 {len(paired)} 个种子的居民配对检验都在同一方向显著（q<{ALPHA}）"]


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
    issues += _survey_quality(protocol, runs)
    return {"ok": not issues, "issues": issues}


def evaluate(protocol: Protocol, runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Verdict per hypothesis, the value table behind it, and quality issues.

    ``runs`` is what :func:`gaworld.research.backends.run_protocol` returns:
    one entry per seed with the parallel worlds ``report`` attached.
    """
    baseline = protocol.baseline_id
    placebo = next((cond["id"] for cond in protocol.conditions if cond["role"] == "placebo"), None)
    per_run: dict[int, dict[str, dict[str, dict[str, float]]]] = {}
    reports: dict[int, dict[str, Any]] = {}
    for run in runs:
        seed = int(run.get("seed", 0))
        report = run.get("report") or {}
        reports[seed] = report
        per_run[seed] = {agg: world_values(report, agg) for agg in ("final", "mean")}
        # A composite study's post-run survey: one score per world, asked once,
        # so the same number serves both aggregations.
        for world_id, block in survey_values(run).items():
            for metric, value in block.items():
                for agg in ("final", "mean"):
                    per_run[seed][agg].setdefault(metric, {})[world_id] = value

    # Seeds produced by different code (a pause, a code change, a resume) are
    # not replicates of one design: the gap between them is the code change.
    epochs = {seed: report.get("comparability_epoch") for seed, report in reports.items()}
    mixed_epochs = not same_epoch(epochs.values())
    epoch_reason = (
        "各种子来自不同的可比性版本（"
        + "；".join(f"种子 {seed}：{describe_epoch(epoch)}" for seed, epoch in sorted(epochs.items()))
        + "），按规定不合并判定"
    )

    # metric -> world -> seed -> final value: the table the report prints.
    table: dict[str, dict[str, dict[int, float]]] = {}
    for seed, by_agg in per_run.items():
        for metric, by_world in by_agg["final"].items():
            for world_id, value in by_world.items():
                table.setdefault(metric, {}).setdefault(world_id, {})[seed] = value

    labels = {str(m.get("id")): str(m.get("label") or "") for m in protocol.measures}
    provenance = measure_provenance(protocol)
    surveyed = survey_paired(protocol, runs)
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
                "paired": (
                    surveyed.get((seed, hypothesis["treatment"], hypothesis["control"], metric))
                    if metric.startswith(survey_mod.PREFIX)
                    else paired_estimate(reports.get(seed) or {}, hypothesis["treatment"], hypothesis["control"], metric)
                ),
            })
        noise = max(placebo_gaps) if placebo_gaps else None
        verdict, reasons = _judge(
            hypothesis["direction"], effects, float(hypothesis.get("min_effect") or 0.0), noise, placebo is not None
        )
        verdict, gate_reasons = _paired_gate(verdict, hypothesis["direction"], rows)
        if mixed_epochs and verdict in ("supported", "contradicted"):
            verdict = "inconclusive"
            gate_reasons.append(epoch_reason)
        seed_ci = t_interval(effects)
        if seed_ci is not None:
            reasons.append(f"种子层面 95% t 区间 {seed_ci[0]:+.4f} ~ {seed_ci[1]:+.4f}")
        reasons += gate_reasons
        source = provenance.get(metric) or {}
        grade = source.get("grade") or "?"
        sized = not direction_only(grade)
        if not sized and effects:
            reasons.append(f"指标来源 ({grade}) 级：只读方向，效应大小不作数")
        hypotheses.append({
            **hypothesis,
            "measure_label": labels.get(metric) or metric_label(metric),
            "measure_grade": grade,
            "measure_basis": source.get("basis") or "",
            "direction_only": not sized,
            "effects": rows,
            "mean_effect": _mean(effects) if effects else None,
            "seed_ci": list(seed_ci) if seed_ci is not None else None,
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
        "comparability": {"epochs": epochs, "mixed": mixed_epochs},
    }


__all__ = ["VERDICTS", "evaluate", "measure_provenance", "survey_paired", "survey_values", "world_values"]
