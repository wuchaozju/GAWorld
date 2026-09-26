"""Let the model explain the numbers — and only the numbers.

The verdicts are already decided by :mod:`gaworld.research.evaluate`. What
a model adds is the reading a social scientist would give: what the pattern
across hypotheses means, what the quality issues do to the conclusion, and
what to run next. What it must not add is a conclusion of its own, so the
prompt hands over the evaluation as a table, every finding has to hang on
a hypothesis id, and :func:`check_claims` marks the ones that do not.

A failed interpretation is not a failed study: the report renders without
this section rather than without its results.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from gaworld.city.knowledge import _parse_json_object
from gaworld.research.protocol import Protocol
from gaworld.research.workbench import ResearchError

INTERPRET_MAX_TOKENS = 3_000
_LANGUAGE_LABELS = {"zh-CN": "简体中文", "en": "English"}

_PROMPT = """你是 GAWorld 平台的研究解读助手。下面是一项已经跑完、并且已经由代码判定过的仿真研究。你的任务只是解释这些数字，不是重新判定：
- 每条 finding 必须挂在一个假设 id 上，只能引用表里出现的数字；
- 判定为 inconclusive / unmeasured 的假设，不要写成有效应；
- 数据质量问题必须体现在 limitations 里；
- next_studies 给 2–3 个能在 GAWorld 平行世界里继续做的研究（剂量反应、机制探查、稳健性），每个说明相对本研究改什么。

## 研究：{title}
{notes}

## 条件
{conditions}

## 逐假设结果（verdict 由代码判定）
{table}

## 数据质量
{quality}

输出语言：{language_label}。只输出一个 JSON 对象，不要解释：
{{
  "findings": [{{"hypothesis": "H1", "claim": "一句话结论", "evidence": "引用的数字"}}],
  "limitations": ["…"],
  "next_studies": [{{"title": "…", "rationale": "为什么值得做", "change": "相对本研究改什么"}}]
}}"""


def _fmt(value: Any) -> str:
    return "—" if value is None else f"{float(value):+.4f}"


def build_interpret_prompt(protocol: Protocol, evaluation: dict[str, Any]) -> str:
    conditions = "\n".join(
        f"- {cond['id']}（{cond['role']}）：{cond['label']}；事件 "
        + ("；".join(f"Day {e['day']} {e['name']}" for e in cond.get("events") or []) or "无")
        for cond in protocol.conditions
    )
    rows = ["| id | 假设 | 指标 | 对比 | 预测方向 | 各种子效应 | 均值 | 噪声底线 | verdict | 原因 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for item in evaluation.get("hypotheses") or []:
        effects = ", ".join(f"s{row['seed']}: {_fmt(row.get('effect'))}" for row in item.get("effects") or [])
        rows.append(
            f"| {item['id']} | {item.get('statement', '')} | {item.get('measure_label', item['measure'])} "
            f"| {item['treatment']} vs {item['control']} | {item['direction']} | {effects} "
            f"| {_fmt(item.get('mean_effect'))} | {_fmt(item.get('noise')) if item.get('noise') is not None else '—'} "
            f"| {item['verdict']} | {'；'.join(item.get('reasons') or [])} |"
        )
    quality = evaluation.get("quality") or {}
    issues = [f"- {issue.get('issue')}（{issue.get('detail', '')}）" for issue in quality.get("issues") or []]
    return _PROMPT.format(
        title=protocol.title,
        notes=f"备注：{protocol.notes}" if protocol.notes else "",
        conditions=conditions,
        table="\n".join(rows),
        quality="\n".join(issues) or "无",
        language_label=_LANGUAGE_LABELS.get(protocol.language, "简体中文"),
    )


def _text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)[:limit]
    return str(value).strip()[:limit]


def check_claims(interpretation: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
    """Mark every finding with whether it hangs on a real hypothesis.

    Nothing is deleted: an ungrounded finding still shows in the report,
    flagged, because a reader who sees what the model wanted to claim and
    that it could not back it learns more than one who sees a gap.
    """
    known = {item["id"]: item for item in evaluation.get("hypotheses") or []}
    for finding in interpretation.get("findings") or []:
        hid = str(finding.get("hypothesis") or "").strip().upper()
        finding["hypothesis"] = hid
        finding["grounded"] = hid in known
        finding["verdict"] = known[hid]["verdict"] if hid in known else ""
    return interpretation


def interpretation_from_answer(answer: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    raw_findings = answer.get("findings")
    for item in raw_findings if isinstance(raw_findings, list) else []:
        if not isinstance(item, dict):
            continue
        claim = _text(item.get("claim"), 800)
        if claim:
            findings.append({
                "hypothesis": _text(item.get("hypothesis"), 16),
                "claim": claim,
                "evidence": _text(item.get("evidence"), 600),
            })
    limitations = [_text(item, 600) for item in answer.get("limitations") or [] if _text(item, 600)]
    next_studies: list[dict[str, str]] = []
    raw_next = answer.get("next_studies")
    for item in raw_next if isinstance(raw_next, list) else []:
        if isinstance(item, str):
            item = {"title": item}
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title"), 160)
        if title:
            next_studies.append({
                "title": title,
                "rationale": _text(item.get("rationale"), 600),
                "change": _text(item.get("change"), 600),
            })
    if not (findings or limitations or next_studies):
        raise ResearchError("模型没有返回可用的解读内容")
    return check_claims(
        {"findings": findings[:20], "limitations": limitations[:15], "next_studies": next_studies[:6]},
        evaluation,
    )


def interpret(
    protocol: Protocol,
    evaluation: dict[str, Any],
    *,
    llm_fn: Callable[[str], str],
) -> dict[str, Any]:
    prompt = build_interpret_prompt(protocol, evaluation)
    try:
        raw = llm_fn(prompt)
    except Exception as exc:  # surfaced in the report, not raised past it
        raise ResearchError(f"模型调用失败：{exc}") from exc
    answer = _parse_json_object(raw)
    if not answer:
        raise ResearchError("模型没有返回可解析的 JSON 解读")
    return interpretation_from_answer(answer, evaluation)


__all__ = ["INTERPRET_MAX_TOKENS", "build_interpret_prompt", "check_claims", "interpret", "interpretation_from_answer"]
