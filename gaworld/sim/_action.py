"""Action choice + action-space generation extracted from ``generative_city_sim.py``.

Three layers:

1. **Pure JSON parsers** — ``_parse_action_space``, ``_parse_location_bias``,
   ``_parse_policy_effect``. Decode LLM JSON-array / JSON-object outputs.

2. **LLM-generated action spaces** — ``_llm_generate_actions``,
   ``_llm_generate_location_bias``, ``get_location_action_bias`` (cached
   per-location), ``generate_actions``, ``build_action_space_for_agent``.

3. **Action selection** — ``choose_action`` (the 340-line weighted
   random pick), ``fallback_action`` (heuristic when LLM produced
   nothing), ``ensure_action_space_for_activity`` (on-demand top-up).

CONFIG-derived knobs (``stateful``, ``human_realism.*``,
``interests.enabled``, ``spontaneity.*``, ``vector_db_top_k``) are
read at *call* time via the ``_*()`` helpers below — module-load
snapshots break under tests that replace ``CONFIG[section]``
wholesale. LLM access uses module-attribute dispatch
(``_llm_providers.call_llm``) so the test mock installer's
``llm_providers.call_llm = mock`` reassignment is picked up.
"""

from __future__ import annotations

import json
import re
import random
from typing import Any

from gaworld.cognition.realism import build_context_key
from gaworld.interests import match_growth_items
from gaworld.llm import providers as _llm_providers
from gaworld.logging_setup import get_logger
from gaworld.personality import personality_line, style_fit, trait_modifier
from gaworld.memory.store import (
    _format_memory_hint,
    _memory_action_bias,
    load_recent_actions,
    retrieve_relevant_memories,
    save_agent_actions,
    save_agent_location_action_bias,
)
from gaworld.settings import CONFIG
from gaworld.sim._memory_recall import (
    NEGATIVE_RECALL_HINTS,
    POSITIVE_RECALL_HINTS,
    _activity_matches_keywords,
    _build_recall_context_labels,
    _commitment_weight,
    _ensure_behavioral_action_balance,
    _same_activity_habit_entry,
    _social_relationship_snapshot,
    evoke_memory,
    is_fallback_only_action_list,
)
from gaworld.sim._schedule import (
    _action_style_tags,
    _activity_commitment_level,
    _extract_json_block,
    loads_tolerant,
    repair_inner_quotes,
    is_sleep_activity,
)

_LOG = get_logger("gaworld.sim.action")


# ---------------------------------------------------------------------------
# CONFIG runtime lookups — see module docstring for why.
# ---------------------------------------------------------------------------

def _stateful() -> bool:
    return bool(CONFIG.get("stateful", False))


def _realism_cfg() -> dict[str, Any]:
    return CONFIG.get("human_realism", {}) or {}


def _realism_enabled() -> bool:
    return bool(_realism_cfg().get("enabled", False))


def _behavior_cfg() -> dict[str, Any]:
    if not _realism_enabled():
        return {}
    return _realism_cfg().get("behavior", {}) or {}


def _interests_enabled() -> bool:
    return bool(CONFIG.get("interests", {}).get("enabled", True))


def _spontaneity_cfg() -> dict[str, Any]:
    return CONFIG.get("spontaneity", {}) or {}


def _spontaneity_enabled() -> bool:
    return bool(_spontaneity_cfg().get("enabled", True))


def _spontaneity_random_chance() -> float:
    return float(_spontaneity_cfg().get("random_action_chance", 0.05))


def _vector_db_top_k() -> int:
    return int(CONFIG.get("vector_db_top_k", 3))


# ---------------------------------------------------------------------------
# Layer 1 — pure JSON parsers.
# ---------------------------------------------------------------------------

#: One ``"activity": [ ... ]`` pair whose list actually closed. Non-greedy, so
#: it stops at the first ``]``; action phrases contain no brackets.
_ACTIVITY_PAIR = re.compile(r'"((?:[^"\\]|\\.)*)"\s*:\s*\[(.*?)\]', re.S)
_QUOTED_ITEM = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _salvage_action_space(text: str, activities: list[str]) -> dict[str, list[str]]:
    """Activities whose list survived, from an object the model never finished.

    Only pairs with a closing ``]`` are taken, so a half-written list is
    dropped rather than handed on as a short one -- the conservative direction,
    since the caller's retry will ask for whatever is missing.
    """
    source = repair_inner_quotes(text or "")
    salvaged: dict[str, list[str]] = {}
    for match in _ACTIVITY_PAIR.finditer(source):
        activity = match.group(1).strip()
        if activity not in activities:
            continue
        items = [
            item.group(1).strip().replace('\\"', '"')
            for item in _QUOTED_ITEM.finditer(match.group(2))
        ]
        items = [item for item in items if item]
        if items:
            salvaged[activity] = items
    return salvaged


def _parse_action_space(text: str, activities: list[str]) -> dict[str, list[str]]:
    """Parse an action-space response, tolerating the two ways it really fails.

    Measured on 848 real ``actions`` responses captured by the A4 arm, the
    strict parser below returned ``{}`` for **354 of them (41.7%)**:

    * **318 truncated.** The prompt asks for four activities of five to ten
      actions each, and the provider's default ``max_tokens`` of 512 cuts the
      object off mid-list (lengths 618-993, median 914, not one empty
      response). Production is worse than this sample, not better:
      ``generate_actions`` passes every distinct activity in a day's schedule,
      which is more than the four this was measured with.
    * **36 syntactically broken.** ASCII quotes inside Chinese strings; see
      :func:`repair_inner_quotes`.

    Returning ``{}`` made both look identical to "the model said nothing", and
    the consequence was not a caught error: the caller retries with *the same*
    activity list, hits the same cap, and the agent spends the day on four
    generic filler actions per activity. Two calls spent, nothing learned.

    With the two fallbacks below, 0/4 recovery goes from 41.7% to **0%**, and
    93.4% of responses yield three or four of the four activities. The caller's
    existing retry then asks only for the one or two that are genuinely
    missing, which is a short enough request to fit.

    Both fallbacks run only where the strict parse already failed, so no call
    that works today can change behaviour.
    """
    json_blob = _extract_json_block(text)
    raw = loads_tolerant(json_blob)
    if not isinstance(raw, dict):
        return _salvage_action_space(text, activities)
    action_space: dict[str, list[str]] = {}
    for activity in activities:
        acts = raw.get(activity, [])
        if not isinstance(acts, list):
            continue
        cleaned = [str(a).strip() for a in acts if str(a).strip()]
        if cleaned:
            action_space[activity] = cleaned
    return action_space or _salvage_action_space(text, activities)


def _parse_location_bias(
    text: str, activities: list[str]
) -> dict[str, dict[str, list[str]]]:
    json_blob = _extract_json_block(text)
    if not json_blob:
        return {}
    raw = loads_tolerant(json_blob)
    if not isinstance(raw, dict):
        return {}
    bias_map: dict[str, dict[str, list[str]]] = {}
    for activity in activities:
        item = raw.get(activity, {})
        if not isinstance(item, dict):
            continue
        prefer = item.get("prefer", [])
        avoid = item.get("avoid", [])
        if not isinstance(prefer, list):
            prefer = []
        if not isinstance(avoid, list):
            avoid = []
        cleaned_prefer = [str(a).strip() for a in prefer if str(a).strip()]
        cleaned_avoid = [str(a).strip() for a in avoid if str(a).strip()]
        if cleaned_prefer or cleaned_avoid:
            bias_map[activity] = {
                "prefer": cleaned_prefer,
                "avoid": cleaned_avoid,
            }
    return bias_map


def _parse_policy_effect(text: str) -> dict[str, float]:
    json_blob = _extract_json_block(text)
    if not json_blob:
        return {}
    raw = loads_tolerant(json_blob)
    if not isinstance(raw, dict):
        return {}
    allowed = {
        "emotion",
        "stress",
        "econ_security",
        "city_identity",
        "policy_sensitivity",
        "platform_dependence",
        "risk_preference",
        "voice_propensity",
        "mobility_intent",
    }
    effect: dict[str, float] = {}
    for k in allowed:
        if k in raw:
            try:
                effect[k] = float(raw[k])
            except (TypeError, ValueError):
                continue
    return effect


# ---------------------------------------------------------------------------
# Layer 2 — LLM-generated action spaces.
# ---------------------------------------------------------------------------

def _activities_per_call() -> int:
    """Chunk size from CONFIG, floored at 1 so a bad value cannot stall."""
    try:
        raw = int((CONFIG.get("action_space", {}) or {}).get("activities_per_call", 3))
    except (TypeError, ValueError):
        return 3
    return max(1, raw)


def _llm_generate_actions(
    agent: dict[str, Any], activities: list[str],
    seed_actions: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    """Action space for ``activities``, asked for in chunks that actually fit.

    The un-chunked version could not have worked at production scale, and the
    numbers say so rather than a hunch. Across 848 real completions one
    activity's block is 193 characters at the median (215 at p75), while the
    provider's default 512-token cap passes about 916. Four activities sit on
    the edge -- 37.5% of that sample came back truncated -- and six or more
    never fit. A real day carries **ten** distinct activities, so the single
    call returned the first four at best, and the retry, asked for the other
    six, hit the same wall. What kept the caches healthy was
    ``ensure_action_space_for_activity`` quietly buying the rest back one call
    at a time, later.

    Chunking is not the more expensive option, which is the part that is easy
    to get backwards: ten activities become four calls that succeed, against
    two that fail plus a per-activity top-up for each one afterwards.

    Truncation recovery in :func:`_parse_action_space` stays -- chunk sizes are
    sized off a median, and a verbose agent can still overrun one.
    """
    activities = list(activities)
    chunk = _activities_per_call()
    if len(activities) <= chunk:
        return _llm_generate_actions_batch(agent, activities, seed_actions)
    merged: dict[str, list[str]] = {}
    for start in range(0, len(activities), chunk):
        group = activities[start:start + chunk]
        seeds = None
        if seed_actions:
            # Only this chunk's seeds: the rest are prompt weight with nothing
            # to contribute to the answer being asked for.
            seeds = {a: seed_actions[a] for a in group if a in seed_actions} or None
        merged.update(_llm_generate_actions_batch(agent, group, seeds))
    return merged


def _llm_generate_actions_batch(
    agent: dict[str, Any], activities: list[str],
    seed_actions: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    """One generation call plus its top-up retry, for a chunk that should fit."""
    profile_text = "\n".join([
        f"姓名：{agent.get('name', '')}",
        f"年龄：{agent.get('age', '')}",
        f"职业：{agent.get('job', '')}",
        personality_line(agent, "action"),
        f"日常生活与习惯：{agent.get('daily_life', '')}",
        f"价值观与公共事务态度：{agent.get('values', '')}",
    ])
    memory_context = " ".join(activities)
    memory_hits = retrieve_relevant_memories(agent, memory_context, max_items=_vector_db_top_k())
    memory_hint = _format_memory_hint(memory_hits)
    seed_text = ""
    if seed_actions:
        seed_text = f"\n已有动作参考（可改写、扩展、去重）：\n{json.dumps(seed_actions, ensure_ascii=False, indent=2)}"
    prompt = f"""
你是城市生活模拟器的动作生成器。请基于角色资料，为每个活动生成具体动作。
角色资料：
{profile_text}
活动列表：{", ".join(activities)}
可参考的近期记忆：{memory_hint}
要求：
1) 每个活动给出 5-10 个动作，中文短语。
2) 动作要符合角色职业、性格与生活习惯。
3) 每个活动尽量同时覆盖：推进型、维持型、回避型、社交/协调型动作。
4) 仅输出 JSON 对象，键为活动名，值为动作列表，不要输出其他文字。
{seed_text}
"""
    response = _llm_providers.call_llm(prompt, task="actions", agent_id=agent["id"])
    action_space = _parse_action_space(response, activities)
    missing = [a for a in activities if a not in action_space]
    if missing:
        retry_prompt = f"""
请只为以下活动补全动作，仍然严格输出 JSON。
角色资料：
{profile_text}
活动列表：{", ".join(missing)}
每个活动 5-10 个动作，中文短语。
"""
        retry_response = _llm_providers.call_llm(retry_prompt, task="actions", agent_id=agent["id"])
        retry_actions = _parse_action_space(retry_response, missing)
        for activity, acts in retry_actions.items():
            action_space[activity] = acts
    still_missing = [a for a in activities if a not in action_space]
    if still_missing:
        _LOG.warning(
            "action space generation produced nothing for agent %s: %s "
            "— falling back to generic behavioural actions (not cached)",
            agent.get("id"),
            "、".join(still_missing),
        )
    balanced: dict[str, list[str]] = {}
    for activity in activities:
        balanced[activity] = _ensure_behavioral_action_balance(activity, action_space.get(activity, []))
    return balanced


def strip_fallback_only_activities(action_space: dict[str, list[str]]) -> dict[str, list[str]]:
    """Drop activities whose action list is pure filler before persisting."""
    return {
        activity: acts
        for activity, acts in (action_space or {}).items()
        if not is_fallback_only_action_list(activity, acts)
    }


def save_action_space(agent_id: Any, action_space: dict[str, list[str]]) -> None:
    """Persist an action space, minus the entries the LLM failed to fill.

    Caching a fallback-only entry poisons the agent permanently: the cache
    is honoured on the next run and ``ensure_action_space_for_activity``
    skips any activity already present, so the LLM is never retried.
    """
    save_agent_actions(agent_id, strip_fallback_only_activities(action_space))


def _llm_generate_location_bias(
    agent: dict[str, Any], location: str, city_map_text: str,
    action_space: dict[str, list[str]],
) -> dict[str, dict[str, list[str]]]:
    activities = list(action_space.keys())
    if not activities:
        return {}
    profile_text = "\n".join([
        f"姓名：{agent.get('name', '')}",
        f"年龄：{agent.get('age', '')}",
        f"职业：{agent.get('job', '')}",
        personality_line(agent, "action"),
        f"日常生活与习惯：{agent.get('daily_life', '')}",
        f"价值观与公共事务态度：{agent.get('values', '')}",
    ])
    actions_text = json.dumps(action_space, ensure_ascii=False, indent=2)
    prompt = f"""
你是城市生活模拟器的“地点动作偏好”生成器。请基于角色资料、地点与城市地图，
为每个活动在该地点给出“偏好动作/避免动作”。

角色资料：
{profile_text}

地点：{location}

城市地图（完整）：
{city_map_text}

活动与可选动作（仅可从下列动作中选择）：
{actions_text}

要求：
1) 仅输出 JSON 对象，键为活动名，值为对象：{{"prefer":[...], "avoid":[...]}}。
2) prefer/avoid 中的动作必须来自给定动作列表，使用完全一致的动作文本。
3) 每个活动 0-5 个 prefer，0-5 个 avoid，允许为空数组。
4) 不要输出其他文字。
"""
    response = _llm_providers.call_llm(prompt, task="location_actions", agent_id=agent["id"])
    return _parse_location_bias(response, activities)


def get_location_action_bias(
    agent: dict[str, Any], location: str, city_map_text: str,
    action_space: dict[str, list[str]],
) -> dict[str, dict[str, list[str]]]:
    if not city_map_text:
        return {}
    bias_cache = agent.setdefault("location_action_bias", {})
    cached = bias_cache.get(location)
    if isinstance(cached, dict):
        return cached
    bias = _llm_generate_location_bias(agent, location, city_map_text, action_space)
    bias_cache[location] = bias
    save_agent_location_action_bias(agent["id"], bias_cache)
    return bias


def generate_actions(
    agent: dict[str, Any], schedule: list[tuple[str, str]]
) -> dict[str, list[str]]:
    activities = sorted({activity for _, activity in schedule})
    return _llm_generate_actions(agent, activities)


def build_action_space_for_agent(
    agent: dict[str, Any], base_actions: dict[str, list[str]],
) -> dict[str, list[str]]:
    activities = list(base_actions.keys())
    refined_actions = _llm_generate_actions(agent, activities, seed_actions=base_actions)
    action_space = {k: list(v) for k, v in base_actions.items()}
    for activity, acts in refined_actions.items():
        action_space.setdefault(activity, [])
        for act in acts:
            if act not in action_space[activity]:
                action_space[activity].append(act)
    return action_space


DEFAULT_ACTIONS = {
    "工作": "继续处理手头工作",
    "时间": "发呆",
}


# ---------------------------------------------------------------------------
# Layer 3 — action selection.
# ---------------------------------------------------------------------------

def fallback_action(activity: str) -> str:
    for k, v in DEFAULT_ACTIONS.items():
        if k in activity:
            return v
    return "继续当前活动"


def ensure_action_space_for_activity(
    agent: dict[str, Any], action_space: dict[str, list[str]], activity: str,
) -> bool:
    if activity in action_space:
        return False
    generated = _llm_generate_actions(agent, [activity])
    acts = generated.get(activity, [])
    if not acts:
        acts = [fallback_action(activity)]
    action_space[activity] = acts
    return True


def choose_action(
    agent: dict[str, Any],
    activity: str,
    action_space: dict[str, list[str]],
    context: str | None = None,
    location_bias: dict[str, dict[str, list[str]]] | None = None,
    location: str | None = None,
    time_str: str | None = None,
    recall_context: dict[str, Any] | None = None,
    decision_refs: dict[str, Any] | None = None,
    return_debug: bool = False,
):
    if is_sleep_activity(activity):
        result = "睡觉"
        if return_debug:
            return result, {
                "decision_driver": "恢复需求",
                "commitment_level": _activity_commitment_level(activity),
                "scores": {result: {"weight": 1.0, "components": {}}},
            }
        return result
    options = action_space.get(activity, [])

    if not options:
        result = fallback_action(activity)
        if return_debug:
            return result, {
                "decision_driver": "动作空间缺省",
                "commitment_level": _activity_commitment_level(activity),
                "scores": {result: {"weight": 1.0, "components": {}}},
            }
        return result

    weights: list[float] = []
    score_map: dict[str, dict[str, Any]] = {}
    s = agent["state"]
    recent_actions: list[str] = []
    memory_hits: list[Any] = []
    if _stateful():
        recent_actions = load_recent_actions(agent["id"], max_items=6)
    refs = decision_refs or {}
    transient_thought = refs.get("transient_thought") if isinstance(refs.get("transient_thought"), dict) else {}
    thought_intensity = float(transient_thought.get("intensity", 0.0) or 0.0)
    thought_source = str(transient_thought.get("source", ""))
    thought_kind = str(transient_thought.get("kind", ""))
    thought_suggestion = str(transient_thought.get("activity_suggestion", "")).strip()
    use_location_time = bool(refs.get("location_time_relevant", True))
    default_social_relevant = _activity_matches_keywords(
        activity,
        ["社交", "联系", "沟通", "拜访", "会面", "聚会", "聊天", "会议", "组会", "讨论", "协作", "家人", "朋友"],
    )
    if not default_social_relevant:
        snapshot = _social_relationship_snapshot(agent)
        default_social_relevant = snapshot["obligation"] > 0.65 or snapshot["friction"] > 0.65
    use_social_network = bool(refs.get("social_network_relevant", default_social_relevant))
    if isinstance(recall_context, dict):
        memory_hits = list(recall_context.get("hits", []) or [])
    elif context or activity:
        query = context if context else activity
        memory_hits = evoke_memory(
            agent,
            "action",
            activity,
            query,
            (location or "") if use_location_time else "",
            (time_str or "") if use_location_time else "",
            context_labels=_build_recall_context_labels(
                agent,
                activity=activity,
                time_str=time_str if use_location_time else "",
                location=location if use_location_time else "",
                commitment_level=_activity_commitment_level(activity),
            ),
        ).get("hits", [])
    bias = (location_bias or {}).get(activity, {})
    prefer_set = set(bias.get("prefer", [])) if isinstance(bias, dict) and use_location_time else set()
    avoid_set = set(bias.get("avoid", [])) if isinstance(bias, dict) and use_location_time else set()
    realism_enabled = _realism_enabled()
    habits = agent.get("habits", {}) if realism_enabled else {}
    behavior_cfg = _behavior_cfg()
    inertia_weight = float(behavior_cfg.get("inertia_weight", 0.25))
    # Open agents entertain more of the field before settling; the jitter
    # width is the closest thing choose_action has to "how firmly decided".
    decision_noise = float(behavior_cfg.get("decision_noise", 0.18)) * trait_modifier(
        agent, "decision_noise"
    )
    avoidance_bonus_scale = float(behavior_cfg.get("avoidance_bonus_scale", 1.1))
    need_weights = behavior_cfg.get("need_weights", {}) if isinstance(behavior_cfg, dict) else {}
    energy_w = float(need_weights.get("energy", 0.45))
    hunger_w = float(need_weights.get("hunger", 0.30))
    social_w = float(need_weights.get("social_need", 0.25))
    context_key = build_context_key(time_str or "", location or "", activity) if use_location_time else ""
    if use_location_time:
        habit_entry = habits.get(context_key, {}) if isinstance(habits, dict) else {}
    else:
        habit_entry = _same_activity_habit_entry(agent, activity)
    preferred_habit_action = str(habit_entry.get("preferred_action", ""))
    habit_strength = float(habit_entry.get("strength", 0.0))
    energy = float(s.get("energy", 0.75))
    hunger = float(s.get("hunger", 0.25))
    social_need = float(s.get("social_need", 0.4))
    fatigue = float(s.get("fatigue_debt", 0.20))
    self_control = float(s.get("self_control", 0.60))
    time_pressure = float(s.get("time_pressure", 0.25))
    commitment_level = _activity_commitment_level(activity)
    commitment_weight = _commitment_weight(commitment_level)
    relation_snapshot = _social_relationship_snapshot(agent) if use_social_network else {
        "obligation": 0.5,
        "friction": 0.5,
        "support": 0.5,
    }
    driver_labels = {
        "stress_avoidance": "压力驱动",
        "low_mood_avoidance": "低情绪回避",
        "growth_drive": "成长动机",
        "night_reflection": "夜间反思惯性",
        "recent_repeat": "近期惯性",
        "memory_recall": "记忆牵引",
        "memory_penalty": "负面记忆提醒",
        "memory_support": "正面记忆支撑",
        "location_prefer": "地点偏好",
        "location_avoid": "地点阻力",
        "habit": "习惯惯性",
        "activity_inertia": "延续当前节奏",
        "action_inertia": "重复上一步做法",
        "energy_need": "体力不足",
        "hunger_need": "饥饿驱动",
        "social_need": "社交需求",
        "solitude_need": "想独处恢复",
        "fatigue_pressure": "疲劳积累",
        "commitment_guardrail": "现实承诺约束",
        "commitment_slack": "低承诺时段更松",
        "self_control_penalty": "低自控偏向省力",
        "self_control_support": "自控尚可",
        "time_pressure_bias": "时间压力",
        "relation_pull": "关系牵引",
        "relation_friction": "关系摩擦",
        "external_trigger": "外界事件触发",
        "social_trigger": "他人/消息触发",
        "need_trigger": "身体需求插队",
        "task_trigger": "任务压力触发",
        "impulse_pull": "临时冲动",
        "suggested_by_thought": "临时念头牵引",
        "growth_interest": "兴趣恢复",
        "growth_skill": "技能成长",
        "growth_career": "职业成长牵引",
        "trait_style_fit": "性格倾向",
    }
    growth_profile = agent.get("growth_profile") if _interests_enabled() else {}
    activity_growth_matches = match_growth_items(growth_profile, activity) if growth_profile else []

    for act in options:
        components: dict[str, float] = {}
        styles = _action_style_tags(act)
        avoidant = "avoidant" in styles
        social = "social" in styles
        progress = "progress" in styles
        maintain = "maintain" in styles
        restorative = "restorative" in styles
        quick = "quick" in styles

        # Personality enters the decision loop here and nowhere else in this
        # function: one additive term, sized like `growth_drive` next to it,
        # scored against the style tags the loop already computes. Exactly 0.0
        # for an agent with no traits, so the key never appears and the draw is
        # bit-identical to the pre-personality build.
        trait_fit = style_fit(agent, styles)
        if trait_fit:
            components["trait_style_fit"] = trait_fit

        if s["stress"] > 0.7 and avoidant:
            components["stress_avoidance"] = 1.2 * avoidance_bonus_scale
        if s["emotion"] < 0.4 and avoidant:
            components["low_mood_avoidance"] = 1.0 * avoidance_bonus_scale
        if s["econ_security"] > 0.6 and progress:
            components["growth_drive"] = 0.6
        if activity == "睡前" and "回顾" in act:
            components["night_reflection"] = 1.0

        growth_matches = match_growth_items(growth_profile, activity, act) if growth_profile else []
        if growth_matches:
            for item in growth_matches:
                priority = float(item.get("priority", 0.5) or 0.5)
                level = float(item.get("level", 0.2) or 0.2)
                if item.get("kind") == "skill":
                    base = 0.28 + priority * 0.55 + max(0.0, 0.45 - level) * 0.20
                    if progress or maintain or quick:
                        base += 0.18
                    if float(s.get("econ_security", 0.5)) < 0.5 or item.get("career_link"):
                        components["growth_career"] = components.get("growth_career", 0.0) + 0.20 * priority
                    components["growth_skill"] = components.get("growth_skill", 0.0) + base
                else:
                    base = 0.20 + priority * 0.45
                    if restorative or social or avoidant:
                        base += 0.16
                    if float(s.get("stress", 0.5)) > 0.60 or float(s.get("fatigue_debt", 0.2)) > 0.55:
                        base += 0.12
                    components["growth_interest"] = components.get("growth_interest", 0.0) + base
        elif activity_growth_matches and any(k in act for k in ["练习", "学习", "继续", "整理", "完成", "阅读"]):
            components["growth_skill"] = components.get("growth_skill", 0.0) + 0.20

        if act in recent_actions:
            components["recent_repeat"] = 0.4
        components["memory_recall"] = _memory_action_bias(act, memory_hits)
        for hit in memory_hits[:4]:
            if not isinstance(hit, dict):
                continue
            text = str(hit.get("text", ""))
            if act not in text:
                continue
            if any(hint in text for hint in NEGATIVE_RECALL_HINTS):
                components["memory_penalty"] = components.get("memory_penalty", 0.0) - 0.85
            if any(hint in text for hint in POSITIVE_RECALL_HINTS):
                components["memory_support"] = components.get("memory_support", 0.0) + 0.35

        if act in prefer_set:
            components["location_prefer"] = 1.0
        if act in avoid_set:
            components["location_avoid"] = -0.6

        if transient_thought:
            act_blob = f"{act} {thought_suggestion}"
            if thought_suggestion and (thought_suggestion in act or act in thought_suggestion):
                components["suggested_by_thought"] = 0.85 * thought_intensity
            if thought_source in {"external_event", "policy"}:
                if quick or progress or maintain or any(k in act_blob for k in ["查看", "调整", "确认", "避开", "改线", "通知", "消息"]):
                    components["external_trigger"] = 0.65 * thought_intensity
            if thought_source == "social" and (social or any(k in act_blob for k in ["回复", "联系", "消息", "沟通", "确认"])):
                components["social_trigger"] = 0.75 * thought_intensity
            if thought_source == "task" and (quick or progress or maintain or any(k in act_blob for k in ["待办", "处理", "确认", "完成"])):
                components["task_trigger"] = 0.70 * thought_intensity
            if thought_kind == "hunger" and any(k in act_blob for k in ["吃", "餐", "饭", "菜", "外卖", "食堂"]):
                components["need_trigger"] = 0.80 * thought_intensity
            if thought_kind == "recovery" and (restorative or any(k in act_blob for k in ["休息", "放松", "缓", "散步", "咖啡"])):
                components["need_trigger"] = 0.70 * thought_intensity
            if thought_source == "impulse" and (avoidant or quick or restorative or social):
                components["impulse_pull"] = 0.65 * thought_intensity

        if realism_enabled:
            if act == preferred_habit_action:
                components["habit"] = habit_strength * 0.9
            if agent.get("last_activity") == activity:
                components["activity_inertia"] = inertia_weight
            if agent.get("last_action") == act:
                components["action_inertia"] = inertia_weight * 0.6

            if energy < 0.35 and restorative:
                components["energy_need"] = (0.35 - energy) * 2.4 * energy_w
            if hunger > 0.65 and any(k in act for k in ["吃", "买菜", "做饭", "餐", "饭"]):
                components["hunger_need"] = (hunger - 0.65) * 2.4 * hunger_w
            if social_need > 0.65 and social:
                components["social_need"] = (social_need - 0.65) * 2.4 * social_w
            if social_need < 0.25 and any(k in act for k in ["独处", "安静", "放空", "回家"]):
                components["solitude_need"] = (0.25 - social_need) * 2.0 * social_w
            if fatigue > 0.60 and (avoidant or restorative):
                components["fatigue_pressure"] = (fatigue - 0.60) * 2.6 * avoidance_bonus_scale

            if commitment_level == "high":
                if progress or maintain:
                    components["commitment_guardrail"] = commitment_weight * 0.75
                elif avoidant:
                    components["commitment_guardrail"] = -commitment_weight * 0.9
            elif commitment_level == "medium":
                if progress or social:
                    components["commitment_guardrail"] = commitment_weight * 0.55
                elif avoidant:
                    components["commitment_guardrail"] = -commitment_weight * 0.35
            else:
                if avoidant or restorative:
                    components["commitment_slack"] = commitment_weight * 0.55

            if self_control < 0.40 and avoidant:
                components["self_control_penalty"] = (0.40 - self_control) * 2.8
            elif self_control > 0.70 and progress:
                components["self_control_support"] = (self_control - 0.70) * 1.6

            if time_pressure > 0.60:
                if quick or progress or maintain:
                    components["time_pressure_bias"] = (time_pressure - 0.60) * 2.0
                elif social and not quick:
                    components["time_pressure_bias"] = -(time_pressure - 0.60) * 1.2

            if social:
                relation_pull = (
                    (relation_snapshot["obligation"] - 0.5) * 1.8
                    + (relation_snapshot["support"] - 0.5) * 0.9
                    - max(0.0, relation_snapshot["friction"] - 0.5) * 1.5
                )
                components["relation_pull"] = relation_pull
            if relation_snapshot["friction"] > 0.65 and any(k in act for k in ["见面", "拜访", "聚会"]):
                components["relation_friction"] = -(relation_snapshot["friction"] - 0.65) * 1.8

        total_weight = 1.0 + sum(components.values())
        if realism_enabled and decision_noise > 0:
            total_weight *= random.uniform(max(0.5, 1.0 - decision_noise), 1.0 + decision_noise)
        total_weight = max(total_weight, 0.01)
        weights.append(total_weight)
        score_map[act] = {
            "weight": round(total_weight, 4),
            "components": {k: round(v, 4) for k, v in components.items() if abs(v) > 0.0001},
            "styles": sorted(styles),
        }
    impulse_choice = False
    if transient_thought and _spontaneity_enabled():
        random_action_chance = _spontaneity_random_chance() + thought_intensity * 0.12
        if thought_source == "impulse":
            random_action_chance += 0.08
        # Low conscientiousness makes the weighted draw easier to bypass
        # altogether. Multiplicative and narrowly bounded because this branch
        # already tops out at 0.40 and compounds over every step of the day.
        random_action_chance *= trait_modifier(agent, "impulse_gate")
        if random.random() < min(0.40, random_action_chance):
            impulse_pool: list[str] = []
            for option in options:
                option_styles = _action_style_tags(option)
                if thought_source == "impulse" and option_styles & {"avoidant", "quick", "restorative", "social"}:
                    impulse_pool.append(option)
                elif thought_source == "social" and "social" in option_styles:
                    impulse_pool.append(option)
                elif thought_kind == "recovery" and "restorative" in option_styles:
                    impulse_pool.append(option)
                elif thought_kind == "hunger" and any(k in option for k in ["吃", "餐", "饭", "菜", "外卖", "食堂"]):
                    impulse_pool.append(option)
                elif thought_source in {"external_event", "policy", "task"} and option_styles & {"quick", "progress", "maintain"}:
                    impulse_pool.append(option)
            choice = random.choice(impulse_pool or options)
            impulse_choice = True
        else:
            choice = random.choices(options, weights=weights, k=1)[0]
    else:
        choice = random.choices(options, weights=weights, k=1)[0]
    if not return_debug:
        return choice
    chosen = score_map.get(choice, {})
    components = chosen.get("components", {})
    if impulse_choice:
        if thought_source == "impulse":
            driver = "临时冲动"
        elif thought_source in {"external_event", "policy"}:
            driver = "外界事件触发"
        elif thought_source == "social":
            driver = "他人/消息触发"
        else:
            driver = "临时念头"
    elif components:
        best_key, best_value = max(
            components.items(),
            key=lambda item: (item[1] > 0, abs(item[1])),
        )
        if best_value > 0:
            driver = driver_labels.get(best_key, "多重因素")
        else:
            driver = f"{driver_labels.get(best_key, '约束因素')}压住了其他选择"
    else:
        driver = "惯性延续"
    return choice, {
        "decision_driver": driver,
        "commitment_level": commitment_level,
        "scores": score_map,
    }


__all__ = [
    "DEFAULT_ACTIONS",
    "_llm_generate_actions",
    "_llm_generate_location_bias",
    "_parse_action_space",
    "_parse_location_bias",
    "_parse_policy_effect",
    "build_action_space_for_agent",
    "choose_action",
    "ensure_action_space_for_activity",
    "fallback_action",
    "generate_actions",
    "get_location_action_bias",
    "save_action_space",
    "strip_fallback_only_activities",
]
