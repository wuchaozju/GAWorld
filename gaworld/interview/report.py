"""Render a finished interview as one self-contained Markdown document.

"Self-contained" is the requirement that shapes this file. The download is
what leaves the tool and goes into a paper, a slide or a colleague's inbox,
so it has to carry its own provenance: which model answered, when, who was
asked, what the questions were, and — importantly — what did *not* work.
A document that quietly omits the six residents whose answers failed to
parse is a document that overstates its own sample.

Ordering is summary → statistics → every answer verbatim. A reader who wants
one number stops at the top; a reader checking whether the numbers are
believable reads to the bottom and finds the raw transcript.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from gaworld.interview.schema import Question, Transcript

#: Axis labels for the cross-tab headings.
AXIS_LABELS = {
    "city": "城市",
    "age_band": "年龄段",
    "gender": "性别",
    "hukou": "户籍",
    "district": "片区",
}

KIND_LABELS = {"open": "开放题", "choice": "选择题", "boolean": "是非题"}

#: The default world carries the empty slug, which becomes ``"default"`` in
#: the demographics (a breakdown axis cannot have an empty key). Readers of
#: the document should not have to know that.
DEFAULT_CITY_LABEL = "默认世界"


def _city_label(value: Any) -> str:
    text = str(value or "").strip()
    return DEFAULT_CITY_LABEL if text in ("", "default") else text


def _escape_cell(text: Any) -> str:
    """Make a value safe for a Markdown table cell."""
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def _meta_block(meta: dict[str, Any]) -> list[str]:
    asked_at = meta.get("finished_at") or meta.get("started_at") or ""
    if isinstance(asked_at, (int, float)) and asked_at:
        asked_at = datetime.fromtimestamp(asked_at).strftime("%Y-%m-%d %H:%M")
    lines = [
        "| 项 | 值 |",
        "| --- | --- |",
        f"| 采访时间 | {_escape_cell(asked_at)} |",
        f"| 受访者 | {meta.get('respondents', 0)} 位（个体 {meta.get('individuals', 0)}，"
        f"群体智能体 {meta.get('cohorts', 0)}） |",
        f"| 代表人数 | {meta.get('people', 0)} 人 |",
        f"| 涉及城市 | {_escape_cell('、'.join(_city_label(name) for name in meta.get('cities', [])))} |",
        f"| 问题数 | {meta.get('question_count', 0)}（共 {meta.get('rounds', 1)} 轮） |",
        f"| 回答模型 | {_escape_cell(meta.get('provider') or '默认路由')} |",
    ]
    return lines


def _question_heading(question: Question, index: int) -> str:
    kind = KIND_LABELS.get(question.kind, question.kind)
    return f"### Q{index}. {question.text}\n\n*（{kind}，第 {question.round} 轮）*"


def _stats_table(stats: dict[str, Any]) -> list[str]:
    rows = stats.get("rows") or []
    if not rows:
        return []
    lines = [
        "| 选项 | 受访者 | 代表人数 | 占比 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {_escape_cell(row['label'])} | {row['respondents']} | {row['people']} | {row['share']:.1%} |"
        )
    return lines


def _coverage_line(stats: dict[str, Any]) -> str:
    parts = [f"有效回答 {stats.get('answered', 0)} 份"]
    if stats.get("answered_people"):
        parts.append(f"代表 {stats['answered_people']} 人")
    if stats.get("unparsed"):
        parts.append(f"**{stats['unparsed']} 份未按题型作答，未计入统计**")
    if stats.get("missing"):
        parts.append(f"{stats['missing']} 份缺失或出错")
    return "；".join(parts) + "。"


def _breakdown_tables(entry: dict[str, Any]) -> list[str]:
    breakdown = entry.get("breakdown") or {}
    if not breakdown:
        return []
    buckets = [row["label"] for row in (entry.get("stats", {}).get("rows") or [])]
    if not buckets:
        return []
    lines: list[str] = []
    for axis, groups in breakdown.items():
        label = AXIS_LABELS.get(axis, axis)
        lines.append(f"**按{label}拆分**（单元格为代表人数 / 该组占比）\n")
        header = f"| {label} | " + " | ".join(_escape_cell(b) for b in buckets) + " | 有效回答 |"
        lines.append(header)
        lines.append("| --- | " + " | ".join("---:" for _ in buckets) + " | ---: |")
        for group in groups:
            total = group.get("answered_people") or 0
            cells = []
            for bucket in buckets:
                people = group["people"].get(bucket, 0)
                share = (people / total) if total else 0.0
                cells.append(f"{people} / {share:.0%}")
            value = _city_label(group["value"]) if axis == "city" else group["value"]
            lines.append(
                f"| {_escape_cell(value)} | " + " | ".join(cells) + f" | {group.get('answered', 0)} |"
            )
        lines.append("")
    return lines


def _material_lines(question: Question) -> list[str]:
    if not question.attachments:
        return []
    lines = ["随问题提供的材料："]
    for item in question.attachments:
        if item.kind == "url":
            lines.append(f"- 网址：<{item.value}>" + (f" — {item.caption}" if item.caption else ""))
        else:
            # The image bytes are not embedded: a base64 PNG per question
            # would turn a readable document into a megabyte of noise.
            lines.append(f"- 图片：{item.caption or '（无说明）'}")
    return lines


def _answer_text(answer: Any, question: Question) -> str:
    if answer is None:
        return "*（未作答）*"
    if answer.error:
        return f"*（出错：{answer.error}）*"
    bits: list[str] = []
    if question.kind == "choice" and answer.choice:
        bits.append(f"**选择：{'、'.join(answer.choice)}**")
    elif question.kind == "boolean" and answer.boolean is not None:
        bits.append(f"**回答：{'是' if answer.boolean else '否'}**")
    body = answer.text.strip() or answer.reason.strip()
    if body:
        bits.append(body)
    if answer.unparsed:
        bits.append("*（未能按题型解析，未计入统计）*")
    if answer.degraded:
        bits.append(f"*（材料降级：{answer.degraded}）*")
    return "\n\n".join(bits) if bits else "*（空回答）*"


def render_markdown(
    *,
    title: str,
    context: str,
    questions: list[Question],
    transcripts: list[Transcript],
    analysis: dict[str, Any],
    meta: dict[str, Any] | None = None,
) -> str:
    """The complete interview document."""
    meta = dict(meta or {})
    meta.setdefault("respondents", analysis.get("respondents", len(transcripts)))
    meta.setdefault("people", analysis.get("people", 0))
    meta.setdefault("cohorts", analysis.get("cohorts", 0))
    meta.setdefault("individuals", analysis.get("individuals", 0))
    meta.setdefault("cities", analysis.get("cities", []))
    meta.setdefault("question_count", len(questions))
    meta.setdefault("rounds", max((q.round for q in questions), default=1))

    entries = {
        entry["question"]["id"]: entry
        for entry in analysis.get("questions", [])
        if isinstance(entry.get("question"), dict)
    }

    out: list[str] = [f"# {title or '群体采访结果'}", ""]
    out += _meta_block(meta)
    out.append("")
    if context.strip():
        out += ["## 访谈背景", "", context.strip(), ""]

    out += ["## 一、汇总摘要", ""]
    for index, question in enumerate(questions, start=1):
        entry = entries.get(question.id, {})
        stats = entry.get("stats", {})
        out.append(_question_heading(question, index))
        out.append("")
        summary = (entry.get("summary") or "").strip()
        out.append(summary or "*（未生成摘要）*")
        out.append("")
        table = _stats_table(stats)
        if table:
            out += table
            out.append("")
        out.append(_coverage_line(stats))
        out.append("")

    countable = [q for q in questions if q.kind != "open" and entries.get(q.id, {}).get("breakdown")]
    if countable:
        out += ["## 二、分组统计", ""]
        for index, question in enumerate(questions, start=1):
            entry = entries.get(question.id, {})
            tables = _breakdown_tables(entry)
            if not tables:
                continue
            out.append(f"### Q{index}. {question.text}")
            out.append("")
            out += tables

    section = "三" if countable else "二"
    out += [f"## {section}、全部回答", ""]
    for transcript in transcripts:
        respondent = transcript.respondent
        tags = [
            f"{key}={_city_label(value) if key == 'city' else value}"
            for key, value in respondent.demographics.items()
            if value
        ]
        kind = "群体智能体" if respondent.kind == "cohort" else "个体"
        head = f"### {respondent.label}"
        out.append(head)
        out.append("")
        out.append(f"*{kind}｜代表 {respondent.size} 人｜{'，'.join(tags)}*")
        out.append("")
        if transcript.error:
            out.append(f"*（该受访者未能作答：{transcript.error}）*")
            out.append("")
            continue
        answers = transcript.by_question()
        for index, question in enumerate(questions, start=1):
            out.append(f"**Q{index}. {question.text}**")
            out.append("")
            out.append(_answer_text(answers.get(question.id), question))
            out.append("")

    failed = analysis.get("failed") or []
    if failed:
        out += ["## 附录 A：未能作答的受访者", ""]
        for item in failed:
            out.append(f"- {item.get('label') or item.get('uid')}：{item.get('error')}")
        out.append("")

    out += ["## 附录 B：问题清单", ""]
    for index, question in enumerate(questions, start=1):
        out.append(f"{index}. **{question.text}** — {KIND_LABELS.get(question.kind, question.kind)}")
        if question.options:
            out.append(f"   - 选项：{'；'.join(question.options)}" + ("（可多选）" if question.multi else ""))
        for line in _material_lines(question):
            out.append(f"   {line}")
        out.append("")

    # Guard against a stray double blank line at the join seams.
    text = "\n".join(out)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip() + "\n"


__all__ = ["AXIS_LABELS", "KIND_LABELS", "render_markdown"]
