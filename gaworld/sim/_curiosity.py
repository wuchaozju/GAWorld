"""Contextual curiosity / knowledge-seeking helpers.

Three concerns, isolated from the news/HTTP plumbing in ``_news.py``:

1. ``assemble_curiosity_context`` — pure: pack the agent's current
   activity, recent events, emotional state, and growth focus into a
   compact dict.
2. ``should_seek_knowledge`` — cheap heuristic gate (no LLM), budget-aware.
3. ``propose_contextual_keywords`` — LLM, called only after the gate
   passes; falls back to the existing template query builder.

LLM access uses module-attribute dispatch (``_llm_providers.call_llm``)
so the test mock installer's ``providers.call_llm = mock`` reassignment
is picked up.
"""

from __future__ import annotations

import json
import random
from typing import Any

from gaworld.llm import providers as _llm_providers
from gaworld.sim._schedule import _extract_json_array_block
from gaworld.sim._utils import _sanitize_extra_text


def assemble_curiosity_context(
    agent: dict[str, Any],
    *,
    scheduled_activity: str = "",
    recent_events: list[str] | None = None,
    day: int | None = None,
    time_str: str | None = None,
) -> dict[str, Any]:
    """Pack the four signal groups into a compact context dict (pure)."""
    state = agent.get("state", {}) if isinstance(agent, dict) else {}
    try:
        from gaworld.interests import growth_focus
        focus = growth_focus(agent.get("growth_profile"), limit=3)
    except Exception:  # pragma: no cover - defensive
        focus = []
    return {
        "activity": str(scheduled_activity or "").strip(),
        "recent_events": [str(e).strip() for e in (recent_events or []) if str(e).strip()],
        "state": {
            "stress": float(state.get("stress", 0.5)),
            "econ_security": float(state.get("econ_security", 0.5)),
        },
        "growth_focus": focus,
        "day": day,
        "time_str": time_str,
    }


def should_seek_knowledge(
    agent: dict[str, Any],
    context: dict[str, Any],
    *,
    budget_left: int,
    config: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Cheap heuristic gate. Returns ``(trigger?, reason)``.

    A hard condition must hold first (fresh event / high stress / high
    estimated curiosity / salient growth focus); then a single
    ``trigger_chance_on_event`` dice roll smooths the frequency.
    """
    cfg = (config or {}).get("event_driven", {}) or {}
    if not cfg.get("enabled", True):
        return False, ""
    if budget_left <= 0:
        return False, ""

    stress_threshold = float(cfg.get("stress_threshold", 0.6))
    curiosity_threshold = float(cfg.get("curiosity_threshold", 0.6))

    reason = ""
    if context.get("recent_events"):
        reason = "event"
    elif float(context.get("state", {}).get("stress", 0.5)) >= stress_threshold:
        reason = "stress"
    elif _curiosity_score(agent) >= curiosity_threshold:
        reason = "curiosity"
    elif context.get("growth_focus"):
        reason = "growth"
    if not reason:
        return False, ""

    chance = float(cfg.get("trigger_chance_on_event", 0.5))
    if random.random() > chance:
        return False, ""
    return True, reason


def _curiosity_score(agent: dict[str, Any]) -> float:
    """Reuse the existing curiosity estimator from the news module."""
    from gaworld.sim._news import _estimate_curiosity
    return _estimate_curiosity(agent)


_KEYWORD_PROMPT = """你是{name}，正在生活和工作中。请根据你当前的处境，提出你此刻最想上网查证/了解的搜索关键词。

当前活动：{activity}
最近发生的事：{events}
当前状态：压力={stress:.2f}，经济安全感={econ:.2f}
你正在发展的兴趣/技能：{growth}

要求：
1) 输出 1-{max_items} 个中文搜索关键词，每个 4-16 字，像真实搜索框里会输入的词。
2) 关键词要贴合“你当前的处境”，不要泛泛而谈。
3) 仅输出 JSON 字符串数组，不要输出其他文字。"""


def propose_contextual_keywords(
    agent: dict[str, Any],
    context: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
) -> list[str]:
    """LLM-propose contextual search keywords; fall back to the template builder."""
    cfg = config or {}
    max_items = max(1, int(cfg.get("contextual_max_keywords", 3)))
    prompt = _KEYWORD_PROMPT.format(
        name=agent.get("name", "该居民"),
        activity=context.get("activity") or "日常活动",
        events="；".join(context.get("recent_events", [])) or "无特别事件",
        stress=float(context.get("state", {}).get("stress", 0.5)),
        econ=float(context.get("state", {}).get("econ_security", 0.5)),
        growth="、".join(context.get("growth_focus", [])) or "无",
        max_items=max_items,
    )
    try:
        response = _llm_providers.call_llm(
            prompt, task="curiosity_keywords", agent_id=agent.get("id")
        )
    except Exception:  # pragma: no cover - defensive; fall back to template
        response = ""

    keywords = _parse_keywords(response, max_items=max_items)
    if keywords:
        return keywords
    return _fallback_keywords(agent, max_items=max_items)


def _parse_keywords(text: str, *, max_items: int) -> list[str]:
    blob = _extract_json_array_block(text or "")
    if not blob:
        return []
    try:
        raw = json.loads(blob)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        cleaned = _sanitize_extra_text(str(item), max_chars=32)
        if cleaned and cleaned not in out:
            out.append(cleaned)
        if len(out) >= max_items:
            break
    return out


def _fallback_keywords(agent: dict[str, Any], *, max_items: int) -> list[str]:
    from gaworld.sim._news import _build_search_query
    query = _build_search_query(agent)
    return [query] if query else []
