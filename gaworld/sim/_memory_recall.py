"""Decision-time memory recall + behavioural context helpers.

Extracted from ``generative_city_sim.py`` L1314–L1814 as the first
prerequisite for lifting ``run_simulation`` (see
``docs/RUN_SIMULATION_EXTRACTION_PLAN.md``).

Three layers live here:

1. **Recall mechanics** — ``evoke_memory`` + helpers
   (``_join_query_parts``, ``_memory_recall_top_k``,
   ``_infer_recall_valence``, ``_apply_recall_effect``,
   ``_format_recollection``). Pulls top-k memories from the vector DB
   biased by stage and agent state, formats them, optionally nudges
   ``emotion`` / ``stress`` based on valence.

2. **Memory review** — ``maybe_review_memories``, ``_heuristic_memory_review``.
   Periodically asks the LLM (or a heuristic fallback) to summarise
   the last few salient episodes into a higher-order self-insight.

3. **Decision context bundle** — the broad ``_build_decision_reference_bundle``
   + 11 supporting predicates (``_is_*_relevant``,
   ``_summarize_environment_refs``, ``_current_emotion_text``,
   ``_social_relationship_snapshot``, ``_activity_matches_keywords``,
   ``_is_meaningful_text``, ``_same_activity_habit_entry``,
   ``_behavioral_action_fallbacks``, ``_ensure_behavioral_action_balance``,
   ``_build_recall_context_labels``, ``_commitment_weight``). These
   determine which environment / social / location signals to
   include in the planning + action prompts.

Two scalar utilities round it out: ``_clip01`` (used by recall
effects) and ``_join_query_parts``.

LLM access uses module-attribute dispatch (``_llm_providers.call_llm``)
so the test mock installer's ``llm_providers.call_llm = mock``
reassignment is picked up. CONFIG-derived knobs
(``human_realism.enabled`` / ``.memory.recall.*`` / ``.memory.review.*``
/ ``.behavior.*``) are read at call time via the ``_*_cfg()``
helpers — module-load snapshots break under test fixtures that
replace ``CONFIG[section]`` wholesale.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import numpy as np
import requests

from gaworld.cognition.realism import build_context_key
from gaworld.llm import providers as _llm_providers
from gaworld.logging_setup import get_logger
from gaworld.memory.store import _format_memory_hint, retrieve_relevant_memories
from gaworld.settings import CONFIG
from gaworld.sim._diary import _append_memory_record
from gaworld.sim._schedule import (
    _action_style_tags,
    _compact_text,
    _state_recall_labels,
    is_sleep_activity,
)
from gaworld.sim._utils import _time_str_to_minutes

_LOG = get_logger("gaworld.sim.memory_recall")


# ---------------------------------------------------------------------------
# CONFIG runtime lookups — see module docstring.
# ---------------------------------------------------------------------------

def _realism_cfg() -> dict[str, Any]:
    return CONFIG.get("human_realism", {}) or {}


def _realism_enabled() -> bool:
    return bool(_realism_cfg().get("enabled", False))


def _human_memory_cfg() -> dict[str, Any]:
    if not _realism_enabled():
        return {}
    return _realism_cfg().get("memory", {}) or {}


def _recall_cfg() -> dict[str, Any]:
    return _human_memory_cfg().get("recall", {}) or {}


def _memory_review_cfg() -> dict[str, Any]:
    return _human_memory_cfg().get("review", {}) or {}


def _behavior_cfg() -> dict[str, Any]:
    if not _realism_enabled():
        return {}
    return _realism_cfg().get("behavior", {}) or {}


# ---------------------------------------------------------------------------
# Stage labels + recall hint vocabularies (pure literals — direct copy).
# ---------------------------------------------------------------------------

RECALL_STAGE_ENTRY_TYPES = {
    "planning": ["meta_memory", "memory", "episode", "reflection", "plan", "action", "log"],
    "action": ["episode", "reflection", "meta_memory", "memory", "action", "plan", "log"],
    "reflection": ["reflection", "episode", "meta_memory", "memory", "action", "plan", "log"],
    "interview": ["meta_memory", "memory", "episode", "reflection", "action", "plan", "log"],
}
RECALL_STAGE_HINTS = {
    "planning": ["计划", "打算", "安排", "经验", "教训"],
    "action": ["行动", "选择", "做法", "后果"],
    "reflection": ["反思", "感受", "经验", "情绪"],
    "interview": ["访谈", "经历", "回忆", "看法"],
}
POSITIVE_RECALL_HINTS = (
    "顺利",
    "满意",
    "开心",
    "支持",
    "完成",
    "收获",
    "稳定",
    "放松",
    "认可",
)
NEGATIVE_RECALL_HINTS = (
    "失败",
    "挫败",
    "焦虑",
    "压力",
    "冲突",
    "不满",
    "拖延",
    "后悔",
    "疲惫",
    "孤独",
)


# ---------------------------------------------------------------------------
# Behavioural action fallbacks (used by choose_action to maintain balance).
# ---------------------------------------------------------------------------

def _commitment_weight(level: str) -> float:
    behavior_cfg = _behavior_cfg()
    weights = behavior_cfg.get("commitment_weights", {}) if isinstance(behavior_cfg, dict) else {}
    default_map = {"high": 1.2, "medium": 0.6, "low": 0.2}
    return float(weights.get(level, default_map.get(level, 0.2)))


def _build_recall_context_labels(
    agent: dict[str, Any], activity: str = "",
    time_str: str = "", location: str = "", commitment_level: str = "",
) -> list[str]:
    labels = list(_state_recall_labels(agent))
    if activity:
        labels.append(f"activity {activity}")
    if time_str and location and activity:
        labels.append(f"context {build_context_key(time_str, location, activity)}")
    if commitment_level:
        labels.append(f"{commitment_level}_commitment")
    return labels


GENERIC_BEHAVIORAL_ACTION_FALLBACKS = {
    "progress": "先把眼前这件事往前推进一点",
    "maintain": "按原节奏继续当前安排",
    "avoidant": "先拖一会儿再说，顺手刷会儿手机",
    "social": "联系一下相关的人确认接下来的安排",
}

# Activity family → keyword trigger + category fallbacks. Ordered: the
# first matching family wins, so put the sharper (event-response) families
# ahead of the broad routine ones.
_BEHAVIORAL_FALLBACK_FAMILIES: list[tuple[list[str], dict[str, str]]] = [
    (
        ["避雨", "躲雨", "避险", "阴凉", "暖和", "撑伞", "避风"],
        {
            "progress": "就近进便利店或商场避一避，顺手把手头的事处理掉",
            "maintain": "撑着伞按原计划继续赶路",
            "avoidant": "在屋檐下发呆等雨小一点",
            "social": "联系要见的人说明会晚到一会儿",
        },
    ),
    (
        ["通勤", "出行", "路线", "绕路", "改去", "前往", "赶路", "堵"],
        {
            "progress": "重新规划一条路线，尽快到目的地",
            "maintain": "按原来的走法继续赶路",
            "avoidant": "先在原地刷会儿手机，晚点再走",
            "social": "联系对方确认到达时间",
        },
    ),
    (
        ["工作", "学习", "会议", "上课", "实验"],
        {
            "progress": "推进最重要的一项任务",
            "maintain": "按原计划继续处理例行事项",
            "avoidant": "拖一会儿再开始，先刷手机分心",
            "social": "联系相关的人确认进度和分工",
        },
    ),
    (
        ["买菜", "购物", "办事", "逛"],
        {
            "progress": "尽快把最需要买的东西先办完",
            "maintain": "按清单照常处理手头事务",
            "avoidant": "先随便逛一会儿拖时间",
            "social": "发消息问熟人有没有顺路需求",
        },
    ),
    (
        ["吃饭", "早饭", "午饭", "晚饭", "早餐", "午餐", "晚餐", "做饭", "外卖", "咖啡店"],
        {
            "progress": "认真准备一顿，好好吃完",
            "maintain": "照常吃平时那一口",
            "avoidant": "边刷手机边随便对付两口",
            "social": "约熟人一起吃，顺便聊天",
        },
    ),
    (
        ["社交", "聚会", "聊天", "拜访", "会面", "约朋友", "见面"],
        {
            "progress": "把想谈的事当面确认清楚",
            "maintain": "照常寒暄几句，维持往来",
            "avoidant": "少说话，刷手机等场子散",
            "social": "多聊天，问问对方的近况",
        },
    ),
    (
        ["休息", "睡前", "放松", "个人时间", "下班"],
        {
            "progress": "顺手整理一下明天的安排",
            "maintain": "按平时的节奏继续休息",
            "avoidant": "躺着刷手机，拖到很晚",
            "social": "回消息，联系一下惦记的人",
        },
    ),
]


def _behavioral_action_fallbacks(activity: str) -> dict[str, str]:
    """Category → filler action for an activity whose action space is thin.

    Family-specific wording matters: a generic "先把眼前这件事往前推进一点"
    is meaningless for an interrupt activity such as 找地方避雨, and once
    picked it seeds an equally meaningless habit.
    """
    text = str(activity or "")
    for keywords, fallbacks in _BEHAVIORAL_FALLBACK_FAMILIES:
        if any(k in text for k in keywords):
            return dict(fallbacks)
    return dict(GENERIC_BEHAVIORAL_ACTION_FALLBACKS)


def is_fallback_only_action_list(activity: str, actions: list[str]) -> bool:
    """True when every action is filler — i.e. the LLM produced nothing.

    Such an action space must not be cached: ``load_agent_actions`` would
    replay it on every later run and the agent would be stuck with four
    generic actions forever.
    """
    cleaned = [str(a).strip() for a in (actions or []) if str(a).strip()]
    if not cleaned:
        return True
    filler = set(_behavioral_action_fallbacks(activity).values())
    filler.update(GENERIC_BEHAVIORAL_ACTION_FALLBACKS.values())
    return all(action in filler for action in cleaned)


def _ensure_behavioral_action_balance(activity: str, actions: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for action in actions or []:
        text = str(action).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    fallbacks = _behavioral_action_fallbacks(activity)
    for category in ("progress", "maintain", "avoidant", "social"):
        if not any(category in _action_style_tags(action) for action in cleaned):
            fallback = fallbacks.get(category, "")
            if fallback and fallback not in seen:
                cleaned.append(fallback)
                seen.add(fallback)
    return cleaned


# ---------------------------------------------------------------------------
# Decision-context predicates (used by _build_decision_reference_bundle).
# ---------------------------------------------------------------------------

def _social_relationship_snapshot(agent: dict[str, Any]) -> dict[str, float]:
    relationships = agent.get("relationships", {}) if isinstance(agent, dict) else {}
    partner_ids = list(agent.get("_recent_social_partners", []) or [])
    selected: list[dict[str, Any]] = []
    for pid in partner_ids:
        item = relationships.get(str(pid), {})
        if isinstance(item, dict):
            selected.append(item)
    if not selected:
        for item in relationships.values():
            if isinstance(item, dict):
                selected.append(item)
            if len(selected) >= 3:
                break
    if not selected:
        return {"obligation": 0.5, "friction": 0.5, "support": 0.5}
    return {
        "obligation": float(np.mean([float(item.get("obligation", 0.5)) for item in selected])),
        "friction": float(np.mean([float(item.get("friction", 0.5)) for item in selected])),
        "support": float(np.mean([float(item.get("closeness", 0.5)) for item in selected])),
    }


def _current_emotion_text(agent: dict[str, Any]) -> str:
    state = agent.get("state", {}) if isinstance(agent, dict) else {}
    emotion = float(state.get("emotion", 0.5))
    stress = float(state.get("stress", 0.5))
    if emotion >= 0.7:
        mood = "明显偏积极"
    elif emotion <= 0.35:
        mood = "明显偏低落"
    else:
        mood = "中性偏波动"
    if stress >= 0.72:
        pressure = "压力偏高"
    elif stress <= 0.35:
        pressure = "压力较低"
    else:
        pressure = "压力中等"
    return f"当前情绪：{mood}（emotion={emotion:.2f}）；当前压力：{pressure}（stress={stress:.2f}）"


def _is_meaningful_text(text: Any) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    return cleaned not in {"无", "无特殊变化", "今天几乎没有与熟人互动。"}


def _activity_matches_keywords(activity: str, keywords: list[str]) -> bool:
    text = str(activity or "")
    return any(keyword in text for keyword in keywords)


def _is_location_time_relevant(activity: str, time_str: str = "", location: str = "") -> bool:
    if _activity_matches_keywords(
        activity,
        [
            "通勤", "前往", "移动", "会面", "拜访", "上班", "工作", "上课", "学习",
            "买菜", "购物", "吃饭", "早餐", "午饭", "晚饭", "散步", "运动", "看病",
            "医院", "诊所", "睡前", "休息",
        ],
    ):
        return True
    if is_sleep_activity(str(activity or "")):
        return True
    return bool(str(time_str).strip() and str(location).strip())


def _is_social_context_relevant(agent: dict[str, Any], activity: str, social_context: Any) -> bool:
    if not _is_meaningful_text(social_context):
        return False
    if _activity_matches_keywords(
        activity,
        ["社交", "联系", "沟通", "拜访", "会面", "聚会", "聊天", "会议", "组会", "讨论", "协作", "家人", "朋友"],
    ):
        return True
    snapshot = _social_relationship_snapshot(agent)
    state = agent.get("state", {}) if isinstance(agent, dict) else {}
    if snapshot["obligation"] > 0.65 or snapshot["friction"] > 0.65:
        return True
    if float(state.get("social_need", 0.4)) > 0.65:
        return True
    return False


def _is_physical_environment_relevant(
    activity: str, env_context: Any, env_events: list[dict[str, Any]] | None,
) -> bool:
    if not _is_meaningful_text(env_context) and not env_events:
        return False
    combined = " ".join(
        [str(env_context or "")] + [str(ev.get("description", ev.get("name", ""))) for ev in (env_events or [])]
    )
    physical_keywords = ["雨", "雪", "风", "高温", "降温", "寒潮", "拥堵", "封路", "施工", "停电", "噪音", "天气", "路况"]
    activity_keywords = ["通勤", "前往", "移动", "散步", "运动", "买菜", "购物", "拜访", "会面", "看病"]
    return any(keyword in combined for keyword in physical_keywords) and _activity_matches_keywords(activity, activity_keywords)


def _is_social_environment_relevant(
    activity: str, env_events: list[dict[str, Any]] | None, policy_desc: Any,
) -> bool:
    combined = " ".join(
        [str(policy_desc or "")] + [str(ev.get("description", ev.get("name", ""))) for ev in (env_events or [])]
    )
    if not _is_meaningful_text(combined):
        return False
    social_keywords = ["政策", "工资", "就业", "监管", "物价", "裁员", "舆论", "抗议", "社区", "学校", "医院", "平台"]
    activity_keywords = ["工作", "上班", "学习", "上课", "买菜", "购物", "社交", "联系", "沟通", "社区", "看病"]
    return any(keyword in combined for keyword in social_keywords) and _activity_matches_keywords(activity, activity_keywords)


def _summarize_environment_refs(
    env_context: Any, env_events: list[dict[str, Any]] | None, policy_desc: Any,
) -> dict[str, str]:
    physical: list[str] = []
    social: list[str] = []
    for ev in env_events or []:
        desc = str(ev.get("description", ev.get("name", ""))).strip()
        if not desc:
            continue
        ev_type = str(ev.get("type", "")).strip().lower()
        if ev_type in {"natural", "weather"} or any(k in desc for k in ["雨", "雪", "风", "高温", "拥堵", "封路", "施工", "停电"]):
            physical.append(desc)
        else:
            social.append(desc)
    if _is_meaningful_text(env_context) and not physical and not social:
        physical.append(str(env_context).strip())
    if _is_meaningful_text(policy_desc):
        social.append(str(policy_desc).strip())
    return {
        "physical": "；".join(dict.fromkeys(physical)),
        "social": "；".join(dict.fromkeys(social)),
    }


def _build_decision_reference_bundle(
    agent: dict[str, Any],
    activity: str,
    memory_hint: str = "",
    recollection: str = "",
    time_str: str = "",
    location: str = "",
    env_context: Any = "",
    env_events: list[dict[str, Any]] | None = None,
    policy_desc: Any = "",
    social_context: Any = "",
) -> dict[str, Any]:
    env_summary = _summarize_environment_refs(env_context, env_events or [], policy_desc)
    refs = {
        "emotion_text": _current_emotion_text(agent),
        "memory_hint": memory_hint or "暂无重要经验",
        "recollection": recollection or "无明显回忆",
        "physical_env_relevant": _is_physical_environment_relevant(activity, env_context, env_events or []),
        "social_env_relevant": _is_social_environment_relevant(activity, env_events or [], policy_desc),
        "location_time_relevant": _is_location_time_relevant(activity, time_str=time_str, location=location),
        "social_network_relevant": _is_social_context_relevant(agent, activity, social_context),
        "physical_env_text": env_summary.get("physical", ""),
        "social_env_text": env_summary.get("social", ""),
        "location_time_text": (
            f"当前地点：{location or '未知'}；当前时间：{time_str or '未知'}"
            if _is_location_time_relevant(activity, time_str=time_str, location=location)
            else ""
        ),
        "social_network_text": social_context if _is_social_context_relevant(agent, activity, social_context) else "",
    }
    return refs


def _same_activity_habit_entry(agent: dict[str, Any], activity: str) -> dict[str, Any]:
    habits = agent.get("habits", {}) if isinstance(agent, dict) else {}
    if not isinstance(habits, dict):
        return {}
    counts: dict[str, int] = defaultdict(int)
    strength_total = 0.0
    strength_count = 0
    for key, item in habits.items():
        if not str(key).endswith(f"|{activity}"):
            continue
        if not isinstance(item, dict):
            continue
        for action, count in item.get("action_counts", {}).items():
            try:
                counts[str(action)] += int(count)
            except (TypeError, ValueError):
                continue
        strength_total += float(item.get("strength", 0.0))
        strength_count += 1
    if not counts:
        return {}
    preferred_action = max(counts.items(), key=lambda x: x[1])[0]
    avg_strength = strength_total / max(1, strength_count)
    return {
        "preferred_action": preferred_action,
        "strength": avg_strength,
    }


# ---------------------------------------------------------------------------
# Recall mechanics — evoke_memory and friends.
# ---------------------------------------------------------------------------

def _clip01(value: Any) -> float:
    return float(np.clip(float(value), 0.0, 1.0))


def _join_query_parts(*parts: Any) -> str:
    chunks: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, (list, tuple, set)):
            chunks.extend(str(x).strip() for x in part if str(x).strip())
        else:
            text = str(part).strip()
            if text:
                chunks.append(text)
    return " ".join(chunks)


def _memory_recall_top_k(agent: dict[str, Any], stage: str) -> int:
    recall_cfg = _recall_cfg()
    base = max(1, int(recall_cfg.get("base_top_k", 2)))
    stage_top = max(base, int(recall_cfg.get(f"{stage}_top_k", base)))
    max_top = max(stage_top, int(recall_cfg.get("max_top_k", 5)))
    state = agent.get("state", {}) if isinstance(agent, dict) else {}
    stress = abs(float(state.get("stress", 0.5)) - 0.5)
    emotion = abs(float(state.get("emotion", 0.5)) - 0.5)
    hunger = abs(float(state.get("hunger", 0.5)) - 0.5)
    social_need = abs(float(state.get("social_need", 0.5)) - 0.5)
    fatigue = abs(float(state.get("fatigue_debt", 0.2)) - 0.5)
    self_control = abs(float(state.get("self_control", 0.6)) - 0.5)
    time_pressure = abs(float(state.get("time_pressure", 0.25)) - 0.5)
    bonus = 0
    if max(stress, emotion, hunger, social_need, fatigue, self_control, time_pressure) >= 0.22:
        bonus += 1
    if stage == "interview":
        bonus += 1
    return max(1, min(stage_top + bonus, max_top))


def _infer_recall_valence(hits: list[Any]) -> float:
    if not hits:
        return 0.0
    score = 0.0
    for item in hits[:3]:
        text = str(item.get("text", "") if isinstance(item, dict) else item)
        score += sum(1 for hint in POSITIVE_RECALL_HINTS if hint in text)
        score -= sum(1 for hint in NEGATIVE_RECALL_HINTS if hint in text)
    return float(np.clip(score / 4.0, -1.0, 1.0))


def _apply_recall_effect(
    agent: dict[str, Any], valence: float, stage: str, top_score: float = 0.0,
) -> dict[str, float]:
    if not isinstance(agent, dict) or abs(float(valence)) < 0.01 or stage == "interview":
        return {}
    state = agent.setdefault("state", {})
    if "emotion" not in state or "stress" not in state:
        return {}
    scale = float(_recall_cfg().get("effect_scale", 0.015))
    strength = scale * (1.0 + min(max(float(top_score), 0.0), 1.0))
    emotion_delta = strength * float(valence)
    stress_delta = -0.7 * strength * float(valence)
    state["emotion"] = _clip01(float(state.get("emotion", 0.5)) + emotion_delta)
    state["stress"] = _clip01(float(state.get("stress", 0.5)) + stress_delta)
    return {
        "emotion": round(emotion_delta, 4),
        "stress": round(stress_delta, 4),
    }


def _format_recollection(stage: str, hits: list[Any]) -> str:
    if not hits:
        return ""
    prefix = {
        "planning": "这让你想起",
        "action": "你临时想起",
        "reflection": "你又联想到",
        "interview": "这些问题让你回忆起",
    }.get(stage, "你想起")
    type_label = {
        "episode": "一段经历",
        "reflection": "之前的反思",
        "meta_memory": "更高层的总结",
        "memory": "过去的记忆",
        "action": "某次做法",
        "plan": "先前的打算",
        "log": "一个生活片段",
    }
    items: list[str] = []
    for hit in hits[:2]:
        if isinstance(hit, dict):
            label = type_label.get(str(hit.get("type", "")), "一个片段")
            text = _compact_text(hit.get("text", ""), max_chars=60)
        else:
            label = "一个片段"
            text = _compact_text(hit, max_chars=60)
        if text:
            items.append(f"{label}：{text}")
    if not items:
        return ""
    return f"{prefix}{'；'.join(items)}"


def evoke_memory(
    agent: dict[str, Any], stage: str, *parts: Any,
    entry_types: list[str] | None = None, context_labels: list[str] | None = None,
) -> dict[str, Any]:
    query = _join_query_parts(RECALL_STAGE_HINTS.get(stage, []), context_labels or [], parts)
    hits = retrieve_relevant_memories(
        agent,
        query,
        max_items=_memory_recall_top_k(agent, stage),
        entry_types=entry_types or RECALL_STAGE_ENTRY_TYPES.get(stage),
    )
    recall_cfg = _recall_cfg()
    hint = _format_memory_hint(hits, max_chars=max(120, int(recall_cfg.get("hint_chars", 240))))
    top_score = float(hits[0].get("score", 0.0)) if hits and isinstance(hits[0], dict) else 0.0
    min_score = float(recall_cfg.get("surface_min_score", 0.08))
    recollection = ""
    valence = 0.0
    effect: dict[str, float] = {}
    if hits and (stage == "interview" or top_score >= min_score):
        recollection = _format_recollection(stage, hits)
        valence = _infer_recall_valence(hits)
        effect = _apply_recall_effect(agent, valence, stage, top_score=top_score)
    return {
        "query": query,
        "hits": hits,
        "hint": hint,
        "recollection": recollection,
        "valence": valence,
        "effect": effect,
        "top_score": top_score,
    }


# ---------------------------------------------------------------------------
# Memory review (periodic high-order self-insight).
# ---------------------------------------------------------------------------

def _heuristic_memory_review(agent: dict[str, Any], selected: list[dict[str, Any]]) -> str:
    tags: list[str] = []
    for ep in selected:
        tags.extend(ep.get("tags", []))
    drivers = [str(ep.get("decision_driver", "")).strip() for ep in selected if str(ep.get("decision_driver", "")).strip()]
    activities = [str(ep.get("final_activity", "")).strip() for ep in selected if str(ep.get("final_activity", "")).strip()]
    repeated = ""
    if activities:
        counts: dict[str, int] = defaultdict(int)
        for activity in activities:
            counts[activity] += 1
        repeated, repeated_count = max(counts.items(), key=lambda x: x[1])
        if repeated_count < 2:
            repeated = ""
    repeated_driver = ""
    if drivers:
        counts = defaultdict(int)
        for driver in drivers:
            counts[driver] += 1
        repeated_driver, repeated_driver_count = max(counts.items(), key=lambda x: x[1])
        if repeated_driver_count < 2:
            repeated_driver = ""
    if "failure" in tags or "conflict" in tags:
        insight = "最近有些做法会反复带来压力，接下来最好更早调整。"
    elif "success" in tags:
        insight = "最近有效的做法值得继续保留。"
    elif "health" in tags:
        insight = "身体状态和恢复节奏正在明显影响你的判断。"
    else:
        insight = "这几段经历说明你的日常节奏正在慢慢塑造接下来的选择。"
    if repeated_driver:
        return f"回顾最近几段经历后，你意识到自己常常被“{repeated_driver}”推着走，{insight}"
    if repeated:
        return f"回顾最近几段经历后，你意识到自己总会被“{repeated}”牵引，{insight}"
    return f"回顾最近几段经历后，你意识到{insight}"


def maybe_review_memories(
    agent: dict[str, Any], day: int, time_str: str,
    recent_episode: dict[str, Any] | None = None,
    llm_budget_ctx: dict[str, Any] | None = None,
) -> str:
    if not _realism_enabled():
        return ""
    now = _time_str_to_minutes(time_str)
    if now is None:
        return ""
    if agent.get("_memory_review_day") != day:
        agent["_memory_review_day"] = day
        agent["_memory_review_count"] = 0
        agent["_last_memory_review_minute"] = -10**9
    review_cfg = _memory_review_cfg()
    max_reviews = max(1, int(review_cfg.get("max_per_day", 3)))
    if int(agent.get("_memory_review_count", 0)) >= max_reviews:
        return ""
    interval = max(60, int(review_cfg.get("interval_minutes", 240)))
    last_minute = int(agent.get("_last_memory_review_minute", -10**9))
    recent_salience = 0.0
    if isinstance(recent_episode, dict):
        recent_salience = float(recent_episode.get("salience", recent_episode.get("decayed_salience", 0.0)))
    trigger_salience = float(review_cfg.get("trigger_salience", 0.72))
    if now - last_minute < interval and recent_salience < trigger_salience:
        return ""
    top_k = max(1, int(review_cfg.get("top_k", 4)))
    episodes = sorted(
        agent.get("episodes", []),
        key=lambda e: float(e.get("decayed_salience", e.get("salience", 0.0))),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    for ep in episodes:
        ep_day = int(ep.get("day", ep.get("created_at_day", 0)) or 0)
        if ep_day < max(0, int(day) - 2):
            continue
        selected.append(ep)
        if len(selected) >= top_k:
            break
    if not selected and isinstance(recent_episode, dict):
        selected = [recent_episode]
    if not selected:
        return ""
    summary_lines = [
        f"{ep.get('time', '')} {ep.get('final_activity', '')} -> {ep.get('action', '')} / {ep.get('reflection', '')}"
        for ep in selected
    ]
    summary = _heuristic_memory_review(agent, selected)
    if isinstance(llm_budget_ctx, dict) and llm_budget_ctx.get("remaining", 0) > 0:
        prompt = f"""
你是城市模拟器中的“记忆复盘器”。
请根据角色近期经历，写一句更高层次的自我认识，像人在回顾自己最近状态时形成的结论。
角色：{agent.get('name', '')}
近期经历：
{json.dumps(summary_lines, ensure_ascii=False, indent=2)}

要求：
1) 只输出一句中文，不超过60字。
2) 要体现模式、偏好、教训或状态变化，不要重复流水账。
3) 不要输出其他文字。
"""
        llm_budget_ctx["remaining"] = max(0, int(llm_budget_ctx.get("remaining", 0)) - 1)
        try:
            response = _llm_providers.call_llm(prompt, task="memory_review", agent_id=agent["id"]).strip()
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            _LOG.warning("memory_review LLM call failed for agent %s: %s", agent.get("id"), exc)
            response = ""
        if response:
            summary = _compact_text(response, max_chars=90)
    review_text = f"[Day {day} {time_str} MemoryReview] {summary}"
    _append_memory_record(agent, review_text, entry_type="meta_memory", day=day, time_str=time_str)
    agent["_memory_review_count"] = int(agent.get("_memory_review_count", 0)) + 1
    agent["_last_memory_review_minute"] = now
    return review_text


__all__ = [
    "GENERIC_BEHAVIORAL_ACTION_FALLBACKS",
    "NEGATIVE_RECALL_HINTS",
    "POSITIVE_RECALL_HINTS",
    "RECALL_STAGE_ENTRY_TYPES",
    "RECALL_STAGE_HINTS",
    "_activity_matches_keywords",
    "_apply_recall_effect",
    "_behavioral_action_fallbacks",
    "_build_decision_reference_bundle",
    "_build_recall_context_labels",
    "_clip01",
    "_commitment_weight",
    "_current_emotion_text",
    "_ensure_behavioral_action_balance",
    "_format_recollection",
    "_heuristic_memory_review",
    "_infer_recall_valence",
    "_is_location_time_relevant",
    "_is_meaningful_text",
    "_is_physical_environment_relevant",
    "_is_social_context_relevant",
    "_is_social_environment_relevant",
    "_join_query_parts",
    "_memory_recall_top_k",
    "_same_activity_habit_entry",
    "_social_relationship_snapshot",
    "_summarize_environment_refs",
    "evoke_memory",
    "is_fallback_only_action_list",
    "maybe_review_memories",
]
