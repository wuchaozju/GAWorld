"""A model's reading of a fidelity run: where the residents part from the people, and why.

The comparison is already done by code (:func:`gaworld.research.replication.compare`).
What a model adds is the paragraph a methodologist would write: which
deviations matter, what they look like (too uniform, pulled to the middle,
more prosocial, an effect that vanished or flipped), how much of the gap the
difference between the paper's participants and the city's residents could
explain, and what to try next.

What it must not add is a number of its own. So the prompt carries the tables
and nothing else, every finding has to cite the ``ref`` of a row in them, and
:func:`check_findings` attaches that row and tests the claimed pattern against
it — "the effect vanished" on a row where the agents' effect is larger than the
humans' is shown as a conflict, and a finding that cites no row is shown as not
counting. Nothing is deleted.
"""

from __future__ import annotations

import json
import re
import statistics
import time
from collections.abc import Callable
from typing import Any

from gaworld.research import replication as rp

INTERPRET_MAX_TOKENS = 4_000
#: Rows per table shown to the model.
MAX_ROWS = 60
_LANGUAGE_LABELS = {"zh-CN": "简体中文", "en": "English"}
#: How far an agent effect must sit from the human one before "weakened" or "exaggerated" holds.
RATIO_BAND = 1.5

PATTERNS = {
    "homogeneity": "回答过于一致",
    "central": "趋向中间",
    "extreme": "趋向极端",
    "prosocial": "更亲社会 / 社会期许",
    "level_shift": "整体偏高或偏低",
    "missing_effect": "效应消失或变弱",
    "exaggerated": "效应被放大",
    "reversed": "效应方向相反",
    "group_gap": "分组差异没有再现",
    "population": "人群差异",
    "other": "其他",
}

_PROMPT = """你是一位社会科学方法学家。下面是一次「拟合度」检验：一篇文献报告了真人的调查或实验结果，
我们让一座虚拟城市里的一批居民（大模型按每位居民的档案扮演）按同样的设计重做了一遍，比较已经由代码算好。
你的任务是解读居民与真人的偏差：偏在哪里、是什么样的偏差、可能的原因、下一步怎么改。要求：
- 每条 finding 必须写 ref，且 ref 必须是下面表格里某一行的 ref；只能引用表里的数字，不要自己计算新的数字；
- pattern 从这些里选一个：{patterns}；
- explanation 写可能的原因，并区分三类：文献人群与居民样本的差别（国家、年龄、教育、时代）、题目与材料在翻译或情境上的差别、
  模型扮演本身的偏差（回答过于一致、社会期许、风险厌恶、缺少真实激励等）；拿不准就说拿不准；
- 小样本（n 小、标注「样本少」）的单元格只能作为线索；判定不是「复现」的效应不要写成复现；
- population_gap 专门写文献人群和这批居民的差别，以及它最可能解释哪些偏差；
- suggestions 给 2–4 条在这个工具里就能做的下一步（调整年龄范围或换城市、加大样本、换配对设计、换模型、改写材料、核对抽取的数字），
  每条说明为什么、怎么做。

## 文献
{study}

## 居民样本
{sample}

## 汇总（由代码计算）
{summary}

## 逐题对照（误差按量程归一到 0–1；SD 比 = 居民 SD / 真人 SD，小于 1 表示居民比真人更一致）
{cells}

## 处理效应（处理 − 对照，按量程归一）
{effects}

## 分组对照
{group_cells}

## 分组差异（分组 − 参照组，按量程归一）
{group_gaps}

输出语言：{language_label}。只输出一个 JSON 对象，不要解释：
{{
  "summary": "两三句话：居民在多大程度上、在哪些方面重现了真人的结果",
  "findings": [{{"ref": "表格里的 ref", "pattern": "上面的一个", "claim": "一句话的偏差描述", "evidence": "引用的数字", "explanation": "可能的原因"}}],
  "population_gap": "文献人群与这批居民的差别及其影响",
  "limitations": ["…"],
  "suggestions": [{{"title": "…", "rationale": "为什么", "how": "在工具里怎么做"}}]
}}"""


def _fmt(value: Any, digits: int = 3) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def _dist(distribution: dict[str, float] | None) -> str:
    return " / ".join(f"{k} {v:.0%}" for k, v in (distribution or {}).items()) or "—"


def _cell_text(item: dict[str, Any], cell: dict[str, Any]) -> tuple[str, str]:
    human, agent = cell.get("human"), cell["agent"]
    if item["kind"] == "choice":
        return (_dist(human.get("distribution")) if human else "未报告"), _dist(agent.get("distribution"))
    h = f"{_fmt(cell.get('human_mean'), 2)}" + (
        f"（SD {_fmt(human.get('sd'), 2)}）" if human and human.get("sd") else ""
    )
    a = (
        f"{_fmt(agent.get('mean'), 2)}（SD {_fmt(agent.get('sd'), 2)}）"
        if agent.get("mean") is not None
        else "—"
    )
    return (h if human else "未报告"), a


def _sample_text(run: dict[str, Any]) -> str:
    residents = run.get("residents") or []
    ages = [int(r.get("age") or 0) for r in residents if r.get("age")]
    genders = {g: sum(1 for r in residents if r.get("gender") == g) for g in ("男", "女")}
    hukou: dict[str, int] = {}
    for r in residents:
        hukou[str(r.get("hukou") or "未知")] = hukou.get(str(r.get("hukou") or "未知"), 0) + 1
    design = "组间随机分配" if run.get("design") == "between" else "配对（每人答每个条件）"
    lines = [
        f"- 城市：{run.get('city_name') or run.get('city') or '默认世界'}；{len(residents)} 位居民；{design}；"
        f"无效回答 {run.get('failed', 0)} / {len(run.get('responses') or [])}",
        f"- 性别：男 {genders['男']}，女 {genders['女']}；户籍："
        + "，".join(f"{k} {v}" for k, v in hukou.items()),
    ]
    if ages:
        lines.append(f"- 年龄：{min(ages)}–{max(ages)} 岁，中位数 {statistics.median(ages):g}")
    return "\n".join(lines)


def _study_text(spec: dict[str, Any]) -> str:
    lines = [
        f"- {spec.get('title') or '未命名研究'}；{spec.get('citation') or ''}",
        f"- 真人受访者：{spec.get('population') or '未说明'}（N = {spec.get('human_n') or '未报告'}）",
    ]
    if spec.get("intro"):
        lines.append(f"- 说明：{spec['intro'][:400]}")
    for condition in spec["conditions"]:
        lines.append(
            f"- 条件 {condition['id']}「{condition['label']}」：{(condition.get('stimulus') or '无额外材料')[:400]}"
        )
    for item in spec["items"]:
        lines.append(f"- {rp._item_line(item)}")
    for group in spec.get("groups") or []:
        lines.append(f"- 分组 {group['id']}「{group['label']}」：{rp.group_text(group)}")
    if spec.get("notes"):
        lines.append(f"- 备注：{spec['notes'][:400]}")
    return "\n".join(lines)


def build_prompt(run: dict[str, Any], language: str = "zh-CN") -> str:
    spec, comparison = run["spec"], run["comparison"]
    items = {i["id"]: i for i in spec["items"]}
    labels = {c["id"]: c["label"] for c in spec["conditions"]}
    groups = {g["id"]: g for g in spec.get("groups") or []}
    summary = comparison["summary"]

    cells = [
        "| ref | 题目 | 条件 | 真人 | 居民 | 差值 | 误差 | 真人值在居民 95% 区间内 | SD 比 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for cell in comparison["cells"][:MAX_ROWS]:
        item = items[cell["item"]]
        h, a = _cell_text(item, cell)
        inside = "—" if "within_ci" not in cell else ("是" if cell["within_ci"] else "否")
        cells.append(
            f"| {cell['ref']} | {item['text'][:40]} | {labels[cell['condition']]} | {h} | {a}，n={cell['agent']['n']} | "
            f"{_fmt(cell.get('diff'), 2)} | {_fmt(cell.get('error'))} | {inside} | {_fmt(cell.get('sd_ratio'), 2)} |"
        )

    def contrast_rows(rows: list[dict[str, Any]], name: Callable[[dict[str, Any]], str]) -> str:
        out = [
            "| ref | 题目 | 对比 | 真人 | 居民 | 居民 p | 真人 p | 判定 |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for row in rows[:MAX_ROWS]:
            option = f"（「{row['option']}」占比）" if row.get("option") else ""
            out.append(
                f"| {row['ref']} | {row['item']}{option} | {name(row)} | {_fmt(row['human_effect'])} | "
                f"{_fmt(row['agent_effect'])} | {_fmt(row.get('agent_p'))} | {_fmt(row.get('human_p'))} | "
                f"{rp.VERDICTS[row['verdict']]} |"
            )
        return "\n".join(out) if rows else "无"

    group_cells = ["| ref | 题目 | 条件 | 分组 | 真人 | 居民 | 误差 |", "|---|---|---|---|---|---|---|"]
    for cell in (comparison.get("group_cells") or [])[:MAX_ROWS]:
        h, a = _cell_text(items[cell["item"]], cell)
        thin = "，样本少" if cell.get("thin") else ""
        group_cells.append(
            f"| {cell['ref']} | {cell['item']} | {labels[cell['condition']]} | {groups[cell['group']]['label']} | {h} | "
            f"{a}，n={cell['agent']['n']}{thin} | {_fmt(cell.get('error'))} |"
        )
    summary_lines = [
        f"- 拟合度分 {summary.get('score')}；水平准确度 {_fmt(summary.get('level_accuracy'))}；"
        f"真人值落在居民 95% 区间内 {_fmt(summary.get('within_ci_rate'))}；单元格相关 r {_fmt(summary.get('level_r'))}；"
        f"平均 SD 比 {_fmt(summary.get('mean_sd_ratio'), 2)}",
        f"- 效应方向一致率 {_fmt(summary.get('direction_rate'))}，显著复现率 {_fmt(summary.get('replication_rate'))}"
        f"（{summary.get('effects_judged')} 个效应），效应相关 r {_fmt(summary.get('effect_r'))}",
    ]
    if summary.get("group_cells_compared"):
        summary_lines.append(
            f"- 分组水平准确度 {_fmt(summary.get('group_level_accuracy'))}；分组差异方向一致率 "
            f"{_fmt(summary.get('group_direction_rate'))}（{summary.get('group_gaps_judged')} 个差异）"
        )
    return _PROMPT.format(
        patterns="、".join(f"{key}（{label}）" for key, label in PATTERNS.items()),
        study=_study_text(spec),
        sample=_sample_text(run),
        summary="\n".join(summary_lines),
        cells="\n".join(cells),
        effects=contrast_rows(
            comparison["effects"], lambda r: f"{labels[r['condition']]} − {labels[r['base']]}"
        ),
        group_cells="\n".join(group_cells) if comparison.get("group_cells") else "无",
        group_gaps=contrast_rows(
            comparison.get("group_gaps") or [],
            lambda r: (
                f"{labels[r['condition']]}：{groups[r['group']]['label']} − {groups[r['base_group']]['label']}"
            ),
        ),
        language_label=_LANGUAGE_LABELS.get(language, "简体中文"),
    )


# ---------------------------------------------------------------------------
# Checking the model's claims against the rows
# ---------------------------------------------------------------------------


def _norm_ref(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper().replace("－", "-").replace("／", "/")


def rows_by_ref(run: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    comparison = run["comparison"]
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for kind, key in (
        ("cell", "cells"),
        ("effect", "effects"),
        ("group_cell", "group_cells"),
        ("group_gap", "group_gaps"),
    ):
        for row in comparison.get(key) or []:
            if row.get("ref"):
                out[_norm_ref(row["ref"])] = (kind, row)
    return out


def _pattern_check(pattern: str, kind: str, row: dict[str, Any], item: dict[str, Any]) -> str:
    """``ok`` / ``conflict`` / ``unchecked``: does the row's arithmetic agree with the claimed pattern?"""
    contrast = kind in ("effect", "group_gap")
    if pattern in ("missing_effect", "exaggerated", "reversed", "group_gap"):
        if not contrast:
            return "conflict"  # an effect pattern needs an effect row
        human, agent = row["human_effect"], row["agent_effect"]
        if pattern == "missing_effect":
            weak = abs(agent) * RATIO_BAND < abs(human) or row["verdict"] not in (
                "replicated",
                "no_human_effect",
            )
            return "ok" if weak else "conflict"
        if pattern == "exaggerated":
            return "ok" if abs(agent) > RATIO_BAND * abs(human) and agent * human > 0 else "conflict"
        if pattern == "reversed":
            return "ok" if agent * human < 0 else "conflict"
        return "ok" if row["verdict"] not in ("replicated",) else "conflict"
    if contrast:
        return "unchecked"
    if pattern == "homogeneity":
        if row.get("sd_ratio") is not None:
            return "ok" if row["sd_ratio"] < 1 else "conflict"
        human, agent = row.get("human") or {}, row["agent"]
        if item["kind"] in ("choice", "scale") and human.get("distribution") and agent.get("distribution"):
            return (
                "ok"
                if max(agent["distribution"].values()) > max(human["distribution"].values())
                else "conflict"
            )
        return "unchecked"
    if pattern in ("central", "extreme") and item.get("min") is not None and item.get("max") is not None:
        if row.get("human_mean") is None or row["agent"].get("mean") is None:
            return "unchecked"
        middle = (item["min"] + item["max"]) / 2
        closer = abs(row["agent"]["mean"] - middle) < abs(row["human_mean"] - middle)
        return "ok" if closer == (pattern == "central") else "conflict"
    if pattern == "level_shift":
        return "ok" if (row.get("error") or 0) > 0 else "conflict"
    return "unchecked"


def check_findings(interpretation: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    rows = rows_by_ref(run)
    items = {i["id"]: i for i in run["spec"]["items"]}
    for finding in interpretation.get("findings") or []:
        found = rows.get(_norm_ref(finding.get("ref")))
        if found is None:
            finding.update(grounded=False, kind="", check="unchecked")
            continue
        kind, row = found
        finding.update(
            ref=row["ref"],
            grounded=True,
            kind=kind,
            verdict=row.get("verdict", ""),
            error=row.get("error"),
            check=_pattern_check(finding.get("pattern", ""), kind, row, items[row["item"]]),
        )
    return interpretation


def _text(value: Any, limit: int) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)[:limit]
    return str(value or "").strip()[:limit]


def interpretation_from_answer(answer: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """Normalise the model's JSON; ``ValueError`` when nothing usable came back."""
    raw_findings = answer.get("findings")
    findings = []
    for item in raw_findings if isinstance(raw_findings, list) else []:
        if not isinstance(item, dict) or not _text(item.get("claim"), 600):
            continue
        pattern = _text(item.get("pattern"), 32).lower()
        findings.append(
            {
                "ref": _text(item.get("ref"), 40),
                "pattern": pattern if pattern in PATTERNS else "other",
                "claim": _text(item.get("claim"), 600),
                "evidence": _text(item.get("evidence"), 400),
                "explanation": _text(item.get("explanation"), 800),
            }
        )
    raw_suggestions = answer.get("suggestions")
    suggestions = []
    for item in raw_suggestions if isinstance(raw_suggestions, list) else []:
        if isinstance(item, str):
            item = {"title": item}
        if isinstance(item, dict) and _text(item.get("title"), 160):
            suggestions.append(
                {
                    "title": _text(item["title"], 160),
                    "rationale": _text(item.get("rationale"), 500),
                    "how": _text(item.get("how"), 500),
                }
            )
    limitations = [_text(x, 500) for x in answer.get("limitations") or [] if _text(x, 500)]
    summary = _text(answer.get("summary"), 1200)
    population_gap = _text(answer.get("population_gap"), 1200)
    if not (summary or findings):
        raise ValueError("模型没有返回可用的解读内容")
    return check_findings(
        {
            "summary": summary,
            "findings": findings[:20],
            "population_gap": population_gap,
            "limitations": limitations[:10],
            "suggestions": suggestions[:5],
        },
        run,
    )


def interpret(
    run: dict[str, Any], *, llm_fn: Callable[[str], str], language: str = "zh-CN"
) -> dict[str, Any]:
    """One model call over the run's tables; ``ValueError`` on any failure."""
    if not run["comparison"]["summary"].get("cells_compared"):
        raise ValueError("这次运行没有可比较的单元格，无从解读")
    try:
        raw = llm_fn(build_prompt(run, language))
    except Exception as exc:  # the panel shows the message; the run itself is unaffected
        raise ValueError(f"模型调用失败：{exc}") from exc
    answer = rp.parse_json(raw)
    if not answer:
        raise ValueError("模型没有返回可解析的 JSON 解读")
    result = interpretation_from_answer(answer, run)
    result["created_at"] = time.time()
    return result


CHECK_LABELS = {"ok": "数字支持", "conflict": "与数字不符", "unchecked": "未核对"}


def interpretation_markdown(interpretation: dict[str, Any]) -> list[str]:
    lines = ["## 偏差解读（模型撰写，数字以上表为准）", ""]
    if interpretation.get("summary"):
        lines += [interpretation["summary"], ""]
    for finding in interpretation.get("findings") or []:
        tag = (
            f"{finding['ref']} · {CHECK_LABELS.get(finding.get('check', ''), '')}"
            if finding.get("grounded")
            else f"{finding.get('ref') or '无 ref'} · 不作数（表里没有这一行）"
        )
        lines.append(
            f"- **[{PATTERNS.get(finding['pattern'], finding['pattern'])}]** {finding['claim']}（{tag}）"
        )
        if finding.get("evidence"):
            lines.append(f"  - 依据：{finding['evidence']}")
        if finding.get("explanation"):
            lines.append(f"  - 可能原因：{finding['explanation']}")
    if interpretation.get("population_gap"):
        lines += ["", f"**人群差异**：{interpretation['population_gap']}"]
    if interpretation.get("limitations"):
        lines += ["", "**局限**", ""] + [f"- {x}" for x in interpretation["limitations"]]
    if interpretation.get("suggestions"):
        lines += ["", "**下一步**", ""]
        for item in interpretation["suggestions"]:
            lines.append(f"- **{item['title']}**：{item.get('rationale', '')} {item.get('how', '')}".rstrip())
    return lines


__all__ = [
    "CHECK_LABELS",
    "INTERPRET_MAX_TOKENS",
    "PATTERNS",
    "build_prompt",
    "check_findings",
    "interpret",
    "interpretation_from_answer",
    "interpretation_markdown",
    "rows_by_ref",
]
