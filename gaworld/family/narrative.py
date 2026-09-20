"""Render a family into the Chinese text the prompts actually read.

Three renderings, deliberately different lengths:

* :func:`family_brief` — one line for the *profile* block of schedule and
  daily-routine prompts. It has to compete with six other profile lines, so
  it is dense and never mentions anything that does not change behaviour.
* :func:`family_section` — a short block for the per-tick perception prompt,
  including who is at home right now.
* :func:`family_summary_line` — a log/console line.
"""

from __future__ import annotations

from typing import Any

from gaworld.family.schema import (
    HOUSEHOLD_TYPE_ZH,
    MARITAL_STATUS_ZH,
    ROLE_ZH,
)


def _members(record: dict[str, Any], *, role: str | None = None, coresident: bool | None = None):
    for member in (record or {}).get("members", []) or []:
        if role and member.get("role") != role:
            continue
        if coresident is not None and bool(member.get("coresident")) != coresident:
            continue
        yield member


def _partner(record: dict[str, Any]) -> dict[str, Any] | None:
    for member in _members(record):
        if member.get("role") in ("spouse", "partner"):
            return member
    return None


def _child_phrase(children: list[dict[str, Any]]) -> str:
    if not children:
        return ""
    parts = []
    for child in sorted(children, key=lambda c: -int(c.get("age", 0) or 0)):
        gender = "儿子" if child.get("gender") == "男" else "女儿"
        parts.append(f"{gender}{child.get('name', '')}（{int(child.get('age', 0) or 0)}岁）")
    return "、".join(parts)


def family_brief(record: dict[str, Any] | None) -> str:
    """One dense line. Empty string when there is no family record."""
    if not record:
        return ""
    status = MARITAL_STATUS_ZH.get(record.get("marital_status", ""), "")
    hh_type = HOUSEHOLD_TYPE_ZH.get(record.get("household_type", ""), "")
    bits: list[str] = []
    partner = _partner(record)
    if partner:
        label = "配偶" if partner.get("role") == "spouse" else "同居伴侣"
        where = "同住" if partner.get("coresident") else "分居"
        bits.append(f"{label}{partner.get('name', '')}（{int(partner.get('age', 0) or 0)}岁，{where}）")
    children = list(_members(record, role="child"))
    coresident_children = [c for c in children if c.get("coresident")]
    away_children = [c for c in children if not c.get("coresident")]
    if coresident_children:
        bits.append("同住子女：" + _child_phrase(coresident_children))
    if away_children:
        bits.append("已独立子女：" + _child_phrase(away_children))
    elders = [
        m
        for m in _members(record, coresident=True)
        if m.get("role") in ("father", "mother", "parent")
    ]
    if elders:
        names = "、".join(
            f"{ROLE_ZH.get(e.get('role'), '父母')}{e.get('name', '')}（{int(e.get('age', 0) or 0)}岁）"
            for e in elders
        )
        bits.append(f"同住长辈：{names}")
    remote_parents = [
        m
        for m in _members(record, coresident=False)
        if m.get("role") in ("father", "mother", "parent")
    ]
    if remote_parents:
        names = "、".join(
            f"{ROLE_ZH.get(p.get('role'), '父母')}{p.get('name', '')}（{int(p.get('age', 0) or 0)}岁）"
            for p in remote_parents
        )
        bits.append(f"不同住的{names}")
    roommates = list(_members(record, role="roommate"))
    if roommates:
        bits.append("合租室友：" + "、".join(str(m.get("name", "")) for m in roommates))
    ex = next((m for m in _members(record, role="ex")), None)
    if ex:
        bits.append(f"前任{ex.get('name', '')}（因子女仍有往来）" if children else f"前任{ex.get('name', '')}")
    head = "；".join(x for x in (status, hh_type) if x)
    if not bits:
        return f"{head}，独自生活" if head else ""
    return f"{head}。" + "；".join(bits)


def family_section(record: dict[str, Any] | None, *, at_home: bool = False) -> str:
    """Perception-prompt block. ``at_home`` switches to present tense."""
    brief = family_brief(record)
    if not brief:
        return ""
    lines = [f"家庭状况：{brief}"]
    if at_home:
        present = [
            str(m.get("name", ""))
            for m in _members(record, coresident=True)
            if m.get("name")
        ]
        if present:
            lines.append("此刻在家里的还有：" + "、".join(present) + "。")
    return "\n".join(lines)


def family_summary_line(agent_name: str, record: dict[str, Any] | None) -> str:
    if not record:
        return f"[Family] {agent_name}: 无家庭记录"
    return (
        f"[Family] {agent_name}: "
        f"{MARITAL_STATUS_ZH.get(record.get('marital_status', ''), '?')}/"
        f"{HOUSEHOLD_TYPE_ZH.get(record.get('household_type', ''), '?')} "
        f"({record.get('household_id', '')}) — {family_brief(record) or '独自生活'}"
    )
