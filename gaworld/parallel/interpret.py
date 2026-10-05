"""A model's reading of a parallel worlds experiment — of its numbers only.

The estimates are already computed (:mod:`gaworld.parallel.causal`) and
judged by fixed rules. What a model adds is the paragraph a social scientist
would write: what the pattern means, what the mechanism order and the
subgroups suggest, what the design cannot rule out, what to run next. What
it must not add is an effect of its own. So the prompt carries the tables
and nothing else, every finding has to name a (world, metric) pair that is
in them, and :func:`check_claims` attaches that row's verdict — a finding
built on an effect the rules did not call robust is shown as such, and one
that names no row is shown as not counting.

Same shape as ``gaworld.research.interpret`` for studies; kept separate
because the evidence here is a table of estimates, not a list of
pre-registered hypotheses.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from gaworld.city.knowledge import _parse_json_object
from gaworld.parallel.analysis import METRIC_LABELS, metric_label

INTERPRET_MAX_TOKENS = 3_000
#: Rows of the estimates table shown to the model; ranked robust-first, so
#: the cut drops the nulls.
MAX_ROWS = 40
_LANGUAGE_LABELS = {"zh-CN": "简体中文", "en": "English"}

_PROMPT = """你是 GAWorld 平台的研究解读助手。下面是一次平行世界实验：所有世界共用同一批居民和同一个随机种子，只是发生的事不同。
效应已经由代码算好并按固定规则判定过。你的任务只是解释这些数字，不是重新判定：
- 每条 finding 必须写明 world（世界 id）和 metric（指标 id），且这一对必须出现在估计表里；只能引用表里的数字；
- 判定不是「robust」的效应，不能写成确定的效应（可以写「没有证据表明……」）；
- 如果没有安慰剂世界、只有一个种子、或有事件前不平衡，必须写进 limitations；
- 机制顺序只是线索，不是因果证明；
- next_experiments 给 2–3 个能在平行世界里继续做的实验（加安慰剂、加种子、剂量梯度、机制探查、换对照），每个说明怎么设计。

## 实验：{name}
对照世界：{control}；噪声参照：{reference}；种子：{seeds}

## 世界
{worlds}

## 效应估计（个体效应 = 处理 − 对照，事件后窗口均值；区间为按居民 bootstrap；q 为 BH-FDR）
{table}

## 起效顺序（机制线索）
{dynamics}

## 跨种子重复
{replication}

## 剂量反应
{dose}

## 警告
{warnings}

输出语言：{language_label}。只输出一个 JSON 对象，不要解释：
{{
  "summary": "两三句话的总体结论",
  "findings": [{{"world": "世界 id", "metric": "指标 id", "claim": "一句话结论", "evidence": "引用的数字"}}],
  "limitations": ["…"],
  "next_experiments": [{{"title": "…", "rationale": "为什么值得做", "design": "世界怎么设、改什么"}}]
}}"""


def _fmt(value: Any, signed: bool = True) -> str:
    if value is None:
        return "—"
    return f"{float(value):+.4f}" if signed else f"{float(value):.4g}"


def build_prompt(report: dict[str, Any], language: str = "zh-CN") -> str:
    """The prompt for one experiment report (as ``experiment_report`` returns it)."""
    causal = report.get("causal") or {}
    worlds = report.get("worlds") or []
    labels = {str(world.get("id")): world.get("label", world.get("id")) for world in worlds}
    world_lines = []
    for world in worlds:
        events = "；".join(
            f"Day {e.get('day')} {e.get('time', '')} {e.get('name', '')}" for e in world.get("events") or []
        )
        bits = [f"- {world.get('id')}「{world.get('label')}」"]
        if world.get("role"):
            bits.append(f"角色 {world['role']}")
        if world.get("dose") is not None:
            bits.append(f"剂量 {world['dose']}")
        bits.append(f"事件 {events or '无'}")
        if world.get("config"):
            bits.append(f"配置改动 {json.dumps(world['config'], ensure_ascii=False)[:200]}")
        world_lines.append("，".join(bits))

    rows = [
        "| world | metric | 指标 | ATE | 95% CI | p | q | DiD | 事件前差 | n | verdict |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in (causal.get("estimates") or [])[:MAX_ROWS]:
        rows.append(
            f"| {row['world_id']} | {row['metric']} | {row.get('label', '')} | {_fmt(row.get('ate'))} "
            f"| {_fmt(row.get('ci_low'))} ~ {_fmt(row.get('ci_high'))} | {_fmt(row.get('p_value'), False)} "
            f"| {_fmt(row.get('q_value'), False)} | {_fmt(row.get('did'))} | {_fmt(row.get('pre_gap'))} "
            f"| {row.get('n')} | {row.get('verdict')} |"
        )

    per_day = report.get("steps_per_day")
    dynamics = []
    for world_id, entry in (causal.get("dynamics") or {}).items():
        order = []
        for metric in entry.get("order") or []:
            item = entry["metrics"][metric]
            when = item["onset_step"]
            when_text = f"D{when / per_day + 1:.1f}" if per_day else f"第 {when} 步"
            order.append(
                f"{metric}（{when_text}，峰值 {_fmt(item.get('peak'))}，持续度 {_fmt(item.get('persistence'), False)}）"
            )
        if order:
            dynamics.append(f"- {world_id}：" + " → ".join(order))

    replication = report.get("replication") or {}
    rep_lines = [
        f"- {row['world_id']} · {row['metric']}：各种子 "
        + ", ".join(_fmt(item["ate"]) for item in row.get("per_seed") or [])
        + f"；均值 {_fmt(row.get('mean'))}；t 区间 {_fmt(row.get('ci_low'))} ~ {_fmt(row.get('ci_high'))}；{row.get('verdict')}"
        for row in (replication.get("rows") or [])[:20]
    ]
    dose_lines = [
        f"- {row['metric']}：斜率 {_fmt(row.get('slope'))}，R² {_fmt(row.get('r2'), False)}，单调 {'是' if row.get('monotonic') else '否'}"
        for row in causal.get("dose_response") or []
    ]
    warning_lines = [
        f"- {item['kind']}：{item.get('world_id')} · {item.get('metric')}"
        for item in causal.get("warnings") or []
    ]
    if not causal.get("placebo_ids"):
        warning_lines.append("- 没有安慰剂世界：无法把效应与仿真自身的噪声分开")
    seeds = replication.get("seeds") or [report.get("seed")]
    return _PROMPT.format(
        name=report.get("name") or report.get("experiment_id") or "",
        control=f"{causal.get('baseline_id')}「{labels.get(str(causal.get('baseline_id')), '')}」",
        reference=causal.get("noise_reference_id") or causal.get("baseline_id"),
        seeds=", ".join(str(seed) for seed in seeds if seed is not None) or "—",
        worlds="\n".join(world_lines) or "—",
        table="\n".join(rows),
        dynamics="\n".join(dynamics) or "无（没有指标稳定越过阈值）",
        replication="\n".join(rep_lines) or "只有一个种子",
        dose="\n".join(dose_lines) or "无",
        warnings="\n".join(warning_lines) or "无",
        language_label=_LANGUAGE_LABELS.get(language, "简体中文"),
    )


def _text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)[:limit]
    return str(value).strip()[:limit]


def _resolve(value: str, ids: set[str], by_label: dict[str, str]) -> str:
    text = value.strip()
    if text in ids:
        return text
    return by_label.get(text, by_label.get(text.lower(), text))


def check_claims(interpretation: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """Tie every finding to a row of the estimates table, or mark it as not.

    Models answer in the prompt's language, so a world may come back as its
    label and a metric as ``"压力"``; both are mapped to ids first. Nothing is
    deleted — an ungrounded finding is shown flagged, which tells the reader
    more than a gap would.
    """
    estimates = {
        (row["world_id"], row["metric"]): row for row in (report.get("causal") or {}).get("estimates") or []
    }
    world_ids = {str(world.get("id")) for world in report.get("worlds") or []}
    world_labels = {str(world.get("label")): str(world.get("id")) for world in report.get("worlds") or []}
    metric_ids = set(METRIC_LABELS) | {metric for _, metric in estimates}
    metric_labels = {label: metric for metric, label in METRIC_LABELS.items()}
    metric_labels.update({metric.lower(): metric for metric in metric_ids})
    for finding in interpretation.get("findings") or []:
        world = _resolve(str(finding.get("world") or ""), world_ids, world_labels)
        metric = _resolve(str(finding.get("metric") or ""), metric_ids, metric_labels)
        row = estimates.get((world, metric))
        finding.update(
            world=world,
            metric=metric,
            metric_label=metric_label(metric),
            grounded=row is not None,
            verdict=row.get("verdict", "") if row else "",
            ate=row.get("ate") if row else None,
        )
    return interpretation


def interpretation_from_answer(answer: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """Normalise the model's JSON; ``ValueError`` when nothing usable came back."""
    findings = []
    raw = answer.get("findings")
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        claim = _text(item.get("claim"), 800)
        if claim:
            findings.append(
                {
                    "world": _text(item.get("world"), 64),
                    "metric": _text(item.get("metric"), 64),
                    "claim": claim,
                    "evidence": _text(item.get("evidence"), 600),
                }
            )
    limitations = [_text(item, 600) for item in answer.get("limitations") or [] if _text(item, 600)]
    next_experiments = []
    raw_next = answer.get("next_experiments")
    for item in raw_next if isinstance(raw_next, list) else []:
        if isinstance(item, str):
            item = {"title": item}
        if isinstance(item, dict) and _text(item.get("title"), 160):
            next_experiments.append(
                {
                    "title": _text(item.get("title"), 160),
                    "rationale": _text(item.get("rationale"), 600),
                    "design": _text(item.get("design"), 600),
                }
            )
    summary = _text(answer.get("summary"), 1200)
    if not (summary or findings or limitations or next_experiments):
        raise ValueError("模型没有返回可用的解读内容")
    return check_claims(
        {
            "summary": summary,
            "findings": findings[:20],
            "limitations": limitations[:12],
            "next_experiments": next_experiments[:5],
        },
        report,
    )


def interpret(
    report: dict[str, Any], *, llm_fn: Callable[[str], str], language: str = "zh-CN"
) -> dict[str, Any]:
    """One model call over the report's tables; ``ValueError`` on any failure."""
    if not (report.get("causal") or {}).get("estimates"):
        raise ValueError("这个实验还没有可解读的效应估计")
    try:
        raw = llm_fn(build_prompt(report, language))
    except Exception as exc:  # the panel shows the message; nothing else depends on it
        raise ValueError(f"模型调用失败：{exc}") from exc
    answer = _parse_json_object(raw)
    if not answer:
        raise ValueError("模型没有返回可解析的 JSON 解读")
    return interpretation_from_answer(answer, report)


__all__ = ["INTERPRET_MAX_TOKENS", "build_prompt", "check_claims", "interpret", "interpretation_from_answer"]
