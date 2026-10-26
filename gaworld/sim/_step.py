"""Per-step routine changes and transient thoughts, moved out of ``generative_city_sim.py``.

Each tick, before an agent acts:

* ``maybe_generate_transient_thought`` may surface a passing thought (an
  event, a message someone is waiting on, hunger, fatigue, time pressure,
  or a random impulse), weighted by how strongly it presses;
* ``maybe_adjust_activity`` decides whether the scheduled activity gives
  way: trigger strength (state + event severity + the thought) against the
  activity's commitment resistance, then one model call to name the new
  activity;
* ``_pick_reshape_life_event`` picks the life event, if any, severe enough
  to rewrite the rest of the day.

The ``routine_change.*``, ``spontaneity.*`` and
``life_events.reshape.severity_threshold`` knobs are read at *call* time
(the module-level snapshots they replaced ignored a ``CONFIG`` changed after
import). LLM access goes through ``_llm_providers.call_llm`` so the test mock
installer's ``llm_providers.call_llm = mock`` reassignment is picked up.

``generative_city_sim`` re-exports every name here: ``run_simulation`` calls
them as bare names, and tests patch ``sim.maybe_adjust_activity``.
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np

from gaworld.llm import providers as _llm_providers
from gaworld.personality import personality_line
from gaworld.settings import CONFIG
from gaworld.sim._memory_recall import _commitment_weight
from gaworld.sim._schedule import (
    _activity_commitment_level,
    _compact_text,
    _parse_schedule_change,
    is_routine_impacting_event,
    is_sleep_activity,
)
from gaworld.sim._timefit import (
    BAD as _TIME_BAD,
)
from gaworld.sim._timefit import (
    activity_time_fit as _activity_time_fit,
)
from gaworld.sim._timefit import (
    should_keep_deviation as _should_keep_deviation,
)
from gaworld.sim._utils import _time_str_to_minutes

# ---------------------------------------------------------------------------
# CONFIG runtime lookups — defaults and coercions as the old snapshots had them.
# ---------------------------------------------------------------------------


def _routine_change_knobs() -> dict[str, Any]:
    cfg = CONFIG.get("routine_change", {}) or {}
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "base_chance": float(cfg.get("base_chance", 0.08)),
        "event_boost": float(cfg.get("event_boost", 0.08)),
        "policy_boost": float(cfg.get("policy_boost", 0.05)),
        "max_chance": float(cfg.get("max_chance", 0.45)),
        "severity_pivot": float(cfg.get("severity_pivot", 0.4)),
        "randomness": float(np.clip(cfg.get("randomness", 0.0), 0.0, 1.0)),
        "event_trigger_scale": float(cfg.get("event_trigger_scale", 1.0)),
        "event_trigger_cap": float(cfg.get("event_trigger_cap", 0.6)),
    }


def _spontaneity_knobs() -> dict[str, Any]:
    cfg = CONFIG.get("spontaneity", {}) or {}
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "base_thought_chance": float(cfg.get("base_thought_chance", 0.18)),
        "max_thought_chance": float(cfg.get("max_thought_chance", 0.68)),
        "event_boost": float(cfg.get("event_boost", 0.10)),
        "policy_boost": float(cfg.get("policy_boost", 0.08)),
        "social_boost": float(cfg.get("social_boost", 0.08)),
        "low_self_control_boost": float(cfg.get("low_self_control_boost", 0.22)),
        "stress_boost": float(cfg.get("stress_boost", 0.18)),
        "fatigue_boost": float(cfg.get("fatigue_boost", 0.14)),
        "hunger_boost": float(cfg.get("hunger_boost", 0.12)),
        "impulse_activity_chance": float(cfg.get("impulse_activity_chance", 0.10)),
        "max_override_bonus": float(cfg.get("max_override_bonus", 0.35)),
    }


def _reshape_severity_threshold() -> float:
    life = CONFIG.get("life_events", {}) if isinstance(CONFIG, dict) else {}
    reshape = life.get("reshape", {}) if isinstance(life, dict) else {}
    return float(reshape.get("severity_threshold", 0.7))


# ---------------------------------------------------------------------------
# Routine change and transient thoughts.
# ---------------------------------------------------------------------------


def _event_severity(event):
    """Severity of an env/life event, defaulting to 0.5 when unspecified.

    The 0.5 fallback is deliberate: it makes a plain env event (which
    historically carried no severity) contribute the same routine-change
    pressure it did before severity-weighting was introduced.
    """
    if not isinstance(event, dict):
        return 0.5
    raw = event.get("severity")
    if raw is None:
        return 0.5
    try:
        return float(np.clip(float(raw), 0.0, 1.0))
    except (TypeError, ValueError):
        return 0.5


def _pick_reshape_life_event(events):
    """Highest-severity routine-impacting life event above the reshape
    threshold, or ``None`` when no event this tick warrants reshaping the day."""
    threshold = _reshape_severity_threshold()
    best = None
    best_sev = -1.0
    for ev in events or []:
        if not isinstance(ev, dict) or not is_routine_impacting_event(ev):
            continue
        sev = _event_severity(ev)
        if sev < threshold:
            continue
        if sev > best_sev:
            best = ev
            best_sev = sev
    return best


def _routine_change_probability(agent, env_events, policy_desc):
    rc = _routine_change_knobs()
    if not rc["enabled"]:
        return 0.0
    prob = rc["base_chance"]
    if env_events:
        # Weight each event by severity: sev=0.5 reproduces the old flat
        # per-event boost, a serious life event (0.86) counts ~1.36×.
        weighted = sum(min(2.0, 0.5 + _event_severity(ev)) for ev in env_events)
        prob += rc["event_boost"] * weighted
    if policy_desc:
        prob += rc["policy_boost"]
    s = agent.get("state", {})
    stress = float(s.get("stress", 0.5))
    emotion = float(s.get("emotion", 0.5))
    hunger = float(s.get("hunger", 0.25))
    fatigue = float(s.get("fatigue_debt", 0.2))
    time_pressure = float(s.get("time_pressure", 0.25))
    if stress > 0.6:
        prob += (stress - 0.6) * 0.3
    if emotion < 0.4:
        prob += (0.4 - emotion) * 0.25
    if hunger > 0.65:
        prob += (hunger - 0.65) * 0.18
    if fatigue > 0.65:
        prob += (fatigue - 0.65) * 0.16
    if time_pressure > 0.65:
        prob += (time_pressure - 0.65) * 0.12
    return float(max(0.0, min(prob, rc["max_chance"])))


def _routine_change_trigger_strength(agent, env_events, policy_desc):
    rc = _routine_change_knobs()
    state = agent.get("state", {}) if isinstance(agent, dict) else {}
    stress = float(state.get("stress", 0.5))
    hunger = float(state.get("hunger", 0.25))
    fatigue = float(state.get("fatigue_debt", 0.2))
    time_pressure = float(state.get("time_pressure", 0.25))
    self_control = float(state.get("self_control", 0.6))
    energy = float(state.get("energy", 0.75))
    trigger = 0.0
    trigger += max(0.0, stress - 0.62) * 0.65
    trigger += max(0.0, hunger - 0.68) * 0.55
    trigger += max(0.0, fatigue - 0.62) * 0.55
    trigger += max(0.0, time_pressure - 0.60) * 0.45
    trigger += max(0.0, 0.42 - self_control) * 0.65
    trigger += max(0.0, 0.35 - energy) * 0.35
    # Severity-weighted event pressure (was flat 0.10 per event, capped 0.25):
    # each event contributes in proportion to how far its severity exceeds the
    # pivot, so a high-severity life event can single-handedly beat a
    # high-commitment activity's resistance.
    event_pressure = sum(max(0.0, _event_severity(ev) - rc["severity_pivot"]) for ev in env_events or [])
    trigger += min(rc["event_trigger_cap"], event_pressure * rc["event_trigger_scale"])
    if policy_desc:
        trigger += 0.10
    return float(np.clip(trigger, 0.0, 1.0))


def _routine_change_resistance(agent, activity):
    state = agent.get("state", {}) if isinstance(agent, dict) else {}
    self_control = float(state.get("self_control", 0.6))
    commitment_level = _activity_commitment_level(activity)
    commitment_weight = _commitment_weight(commitment_level)
    resistance = 0.08 + commitment_weight * 0.55 + max(0.0, self_control - 0.5) * 0.20
    return commitment_level, float(np.clip(resistance, 0.0, 1.0))


def _social_context_has_trigger(social_context, inbox_messages=None):
    text = str(social_context or "")
    if inbox_messages:
        return True
    keywords = [
        "等你回应",
        "责任压力",
        "顾虑",
        "摩擦",
        "消息",
        "回复",
        "配合",
        "分工",
        "安排",
        "支持感",
    ]
    return any(k in text for k in keywords)


def _top_env_event(env_events):
    best = None
    best_score = -1.0
    for ev in env_events or []:
        if not isinstance(ev, dict):
            continue
        try:
            severity = float(ev.get("severity", 0.0))
        except (TypeError, ValueError):
            severity = 0.0
        desc = str(ev.get("description", ev.get("name", ""))).strip()
        score = severity + (0.08 if desc else 0.0)
        if score > best_score:
            best = ev
            best_score = score
    return best


def _suggest_activity_for_event(event, policy_desc, scheduled_activity):
    event_text = ""
    event_type = ""
    impact_tags = []
    if isinstance(event, dict):
        event_text = str(event.get("description", event.get("name", "")))
        event_type = str(event.get("type", "")).lower()
        impact_tags = [str(x).lower() for x in event.get("impact_tags", []) if str(x).strip()]
    if policy_desc:
        event_text = f"{event_text} {policy_desc}".strip()
        if not event_type:
            event_type = "policy"
    activity_text = str(scheduled_activity or "")
    combined = f"{event_text} {activity_text}"
    if (
        any(
            k in combined
            for k in ["雨", "雪", "风", "高温", "寒潮", "拥堵", "封路", "施工", "停电", "天气", "路况"]
        )
        or "mobility" in impact_tags
    ):
        if any(k in activity_text for k in ["通勤", "前往", "散步", "运动", "买菜", "购物", "会面", "拜访"]):
            return "调整出行"
        return "查看天气"
    if any(k in combined for k in ["工资", "就业", "裁员", "收入", "物价", "市场", "经济"]):
        return "盘算开支"
    if any(k in combined for k in ["政策", "监管", "制度", "社区", "通知"]):
        return "查看通知"
    if any(k in combined for k in ["平台", "技术", "服务", "系统", "应用"]):
        return "查看消息"
    if event_type:
        return "关注事件"
    return ""


def _spontaneity_probability(agent, env_events, policy_desc, social_context, inbox_messages=None):
    sp = _spontaneity_knobs()
    if not sp["enabled"]:
        return 0.0
    state = agent.get("state", {}) if isinstance(agent, dict) else {}
    prob = sp["base_thought_chance"]
    if env_events:
        prob += min(0.30, sp["event_boost"] * len(env_events))
        top_event = _top_env_event(env_events)
        if isinstance(top_event, dict):
            try:
                severity = float(top_event.get("severity", 0.0) or 0.0)
            except (TypeError, ValueError):
                severity = 0.0
            prob += 0.08 * severity
    if policy_desc:
        prob += sp["policy_boost"]
    if _social_context_has_trigger(social_context, inbox_messages=inbox_messages):
        prob += sp["social_boost"]
    stress = float(state.get("stress", 0.5))
    hunger = float(state.get("hunger", 0.25))
    fatigue = float(state.get("fatigue_debt", 0.2))
    self_control = float(state.get("self_control", 0.6))
    if self_control < 0.5:
        prob += (0.5 - self_control) * sp["low_self_control_boost"]
    if stress > 0.55:
        prob += (stress - 0.55) * sp["stress_boost"]
    if fatigue > 0.5:
        prob += (fatigue - 0.5) * sp["fatigue_boost"]
    if hunger > 0.55:
        prob += (hunger - 0.55) * sp["hunger_boost"]
    return float(np.clip(prob, 0.0, sp["max_thought_chance"]))


def _weighted_thought_pick(candidates):
    if not candidates:
        return {}
    weights = [max(0.01, float(item.get("intensity", 0.1))) for item in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def maybe_generate_transient_thought(
    agent,
    time_str,
    scheduled_activity,
    perception_text,
    env_events=None,
    policy_desc=None,
    social_context="",
    inbox_messages=None,
):
    sp = _spontaneity_knobs()
    prob = _spontaneity_probability(
        agent,
        env_events or [],
        policy_desc,
        social_context,
        inbox_messages=inbox_messages,
    )
    if prob <= 0 or random.random() > prob:
        return {}

    state = agent.get("state", {}) if isinstance(agent, dict) else {}
    candidates = []
    top_event = _top_env_event(env_events or [])
    if top_event or policy_desc:
        try:
            severity = float(top_event.get("severity", 0.35) if isinstance(top_event, dict) else 0.45)
        except (TypeError, ValueError):
            severity = 0.35
        suggestion = _suggest_activity_for_event(top_event, policy_desc, scheduled_activity)
        event_desc = ""
        if isinstance(top_event, dict):
            event_desc = str(top_event.get("description", top_event.get("name", ""))).strip()
        if policy_desc:
            event_desc = f"{event_desc} {policy_desc}".strip()
        candidates.append(
            {
                "source": "external_event" if top_event else "policy",
                "kind": "event_trigger",
                "thought": f"外面的变化可能会影响原安排，想先处理一下：{_compact_text(event_desc, max_chars=54)}",
                "activity_suggestion": suggestion or "关注事件",
                "reason": _compact_text(event_desc, max_chars=80) or "外部环境变化",
                "intensity": float(np.clip(0.35 + 0.55 * severity, 0.0, 1.0)),
            }
        )

    if _social_context_has_trigger(social_context, inbox_messages=inbox_messages):
        candidates.append(
            {
                "source": "social",
                "kind": "social_trigger",
                "thought": "突然想到有人可能在等回应，想先处理一下关系或消息。",
                "activity_suggestion": "回复消息",
                "reason": _compact_text(social_context, max_chars=80) or "社交消息触发",
                "intensity": float(np.clip(0.45 + 0.25 * float(state.get("social_need", 0.4)), 0.0, 1.0)),
            }
        )

    hunger = float(state.get("hunger", 0.25))
    energy = float(state.get("energy", 0.75))
    fatigue = float(state.get("fatigue_debt", 0.2))
    stress = float(state.get("stress", 0.5))
    emotion = float(state.get("emotion", 0.5))
    self_control = float(state.get("self_control", 0.6))
    time_pressure = float(state.get("time_pressure", 0.25))
    if hunger > 0.62:
        candidates.append(
            {
                "source": "need",
                "kind": "hunger",
                "thought": "肚子有点占据注意力，想先找点吃的。",
                "activity_suggestion": "找点吃的",
                "reason": f"hunger={hunger:.2f}",
                "intensity": float(np.clip((hunger - 0.45) * 1.25, 0.0, 1.0)),
            }
        )
    if energy < 0.42 or fatigue > 0.62:
        candidates.append(
            {
                "source": "need",
                "kind": "recovery",
                "thought": "身体有点撑不住，想临时缓一缓。",
                "activity_suggestion": "休息片刻",
                "reason": f"energy={energy:.2f}, fatigue={fatigue:.2f}",
                "intensity": float(np.clip(max(0.42 - energy, fatigue - 0.55) * 1.4, 0.0, 1.0)),
            }
        )
    if time_pressure > 0.66:
        candidates.append(
            {
                "source": "task",
                "kind": "time_pressure",
                "thought": "时间压力突然冒出来，想先把最急的事处理掉。",
                "activity_suggestion": "处理待办",
                "reason": f"time_pressure={time_pressure:.2f}",
                "intensity": float(np.clip((time_pressure - 0.55) * 1.35, 0.0, 1.0)),
            }
        )

    impulse_chance = sp["impulse_activity_chance"]
    impulse_chance += max(0.0, 0.48 - self_control) * 0.35
    impulse_chance += max(0.0, stress - 0.62) * 0.22
    impulse_chance += max(0.0, 0.42 - emotion) * 0.18
    if random.random() < min(0.55, impulse_chance):
        impulse_pool = [
            ("刷手机", "想逃开当前节奏，手已经想去刷手机。"),
            ("临时散步", "突然想出去走几分钟，换一下脑子。"),
            ("买杯咖啡", "突然想买点喝的，让自己重新提神。"),
            ("发消息聊天", "突然想找人说两句，缓一下心情。"),
            ("查看新闻", "突然想看看外面又发生了什么。"),
            ("顺手购物", "突然想顺手买点东西，满足一下即时念头。"),
            ("整理待办", "突然觉得脑子乱，想先整理一下接下来要做什么。"),
        ]
        suggestion, thought_text = random.choice(impulse_pool)
        candidates.append(
            {
                "source": "impulse",
                "kind": "random_impulse",
                "thought": thought_text,
                "activity_suggestion": suggestion,
                "reason": f"self_control={self_control:.2f}, stress={stress:.2f}",
                "intensity": float(
                    np.clip(0.35 + max(0.0, 0.55 - self_control) + max(0.0, stress - 0.60), 0.0, 1.0)
                ),
            }
        )

    picked = _weighted_thought_pick(candidates)
    if not picked:
        return {}
    picked["time"] = str(time_str)
    picked["scheduled_activity"] = str(scheduled_activity)
    picked["probability"] = round(prob, 3)
    picked["perception_excerpt"] = _compact_text(perception_text, max_chars=70)
    picked["intensity"] = round(float(np.clip(picked.get("intensity", 0.0), 0.0, 1.0)), 3)
    return picked


def format_transient_thought(thought):
    if not isinstance(thought, dict) or not thought:
        return ""
    source = str(thought.get("source", "thought"))
    kind = str(thought.get("kind", ""))
    intensity = float(thought.get("intensity", 0.0) or 0.0)
    suggestion = str(thought.get("activity_suggestion", "")).strip()
    body = str(thought.get("thought", "")).strip()
    reason = str(thought.get("reason", "")).strip()
    parts = [f"{source}/{kind}({intensity:.2f})"]
    if body:
        parts.append(body)
    if suggestion:
        parts.append(f"倾向：{suggestion}")
    if reason:
        parts.append(f"原因：{reason}")
    return "；".join(parts)


def maybe_adjust_activity(
    agent,
    time_str,
    scheduled_activity,
    perception_text,
    plan_text,
    env_context,
    env_events,
    policy_desc,
    transient_thought=None,
    social_context="",
):
    rc = _routine_change_knobs()
    sp = _spontaneity_knobs()
    prob = _routine_change_probability(agent, env_events, policy_desc)
    if prob <= 0:
        return scheduled_activity, "", False
    commitment_level, resistance = _routine_change_resistance(agent, scheduled_activity)
    trigger = _routine_change_trigger_strength(agent, env_events, policy_desc)
    thought = transient_thought if isinstance(transient_thought, dict) else {}
    thought_intensity = float(thought.get("intensity", 0.0) or 0.0)
    if thought:
        prob = min(rc["max_chance"], prob + min(sp["max_override_bonus"], thought_intensity * 0.40))
        trigger = float(np.clip(trigger + thought_intensity * 0.55, 0.0, 1.0))
        source = str(thought.get("source", ""))
        if source in {"external_event", "policy", "social", "task"}:
            resistance = max(0.0, resistance - 0.08)
        elif source == "impulse":
            self_control = float(agent.get("state", {}).get("self_control", 0.6))
            if self_control < 0.45:
                resistance = max(0.0, resistance - 0.10)
    # Global routine-randomness: the higher the knob, the less agents stick to
    # their routine. It relaxes the current activity's commitment resistance,
    # injects free-floating restlessness into the trigger (so an agent can go
    # off-script even without a state/event push), and lifts the deviation
    # probability. Sleep slots are exempt so high randomness doesn't keep
    # agents up all night. 0 keeps the tuned defaults unchanged.
    if rc["randomness"] > 0.0 and not is_sleep_activity(scheduled_activity):
        r = rc["randomness"]
        resistance = max(0.0, resistance * (1.0 - 0.70 * r))
        trigger = float(np.clip(trigger + 0.45 * r, 0.0, 1.0))
        prob = min(0.97, prob + 0.45 * r)
    if trigger <= resistance:
        return scheduled_activity, "", False
    activation = min(0.95, prob + max(0.0, trigger - resistance) * 0.9)
    if random.random() > activation:
        return scheduled_activity, "", False

    profile_text = "\n".join(
        [
            f"姓名：{agent.get('name', '')}",
            f"年龄：{agent.get('age', '')}",
            f"职业：{agent.get('job', '')}",
            personality_line(agent, "action"),
            f"日常生活与习惯：{agent.get('daily_life', '')}",
            f"价值观与公共事务态度：{agent.get('values', '')}",
        ]
    )
    state = agent.get("state", {})
    state_text = (
        f"emotion={state.get('emotion', 0.5):.2f}, "
        f"stress={state.get('stress', 0.5):.2f}, "
        f"econ_security={state.get('econ_security', 0.5):.2f}, "
        f"risk_preference={state.get('risk_preference', 0.5):.2f}, "
        f"fatigue_debt={state.get('fatigue_debt', 0.2):.2f}, "
        f"self_control={state.get('self_control', 0.6):.2f}, "
        f"time_pressure={state.get('time_pressure', 0.25):.2f}"
    )
    prompt = f"""
你是城市生活模拟器的“临时改程”决策器。
当前时间：{time_str}
原计划活动：{scheduled_activity}
该活动承诺等级：{commitment_level}
角色资料：
{profile_text}
当前状态数值：{state_text}
当前感知：{perception_text}
当前计划：{plan_text}
环境事件：{env_context if env_context else "无"}
政策事件：{policy_desc if policy_desc else "无"}
社交/任务触发：{social_context if social_context else "无"}
临时念头：{format_transient_thought(thought) if thought else "无"}
改程触发强度：{trigger:.2f}
原计划承诺阻力：{resistance:.2f}

请判断是否需要因个人意愿或环境/事件影响而临时更改该时段活动。
要求：
1) 仅输出 JSON：{{"change": true/false, "activity": "活动", "reason": "原因"}}。
2) 若不改变，change=false，activity 可留空。
3) 若改变，activity 为中文短语（2-8字），能合理反映动机与情境。
4) 高承诺活动除非触发很强，否则尽量不改；低承诺活动可以更灵活。
5) 不要输出其他文字。
"""
    response = _llm_providers.call_llm(prompt, task="routine_change", agent_id=agent["id"])
    parsed = _parse_schedule_change(response)
    if not parsed:
        suggestion = str(thought.get("activity_suggestion", "")).strip()
        if suggestion and suggestion != scheduled_activity:
            reason = str(thought.get("reason", "")).strip() or "临时念头触发"
            return _accept_activity_change(suggestion, time_str, scheduled_activity, reason)
        return scheduled_activity, "", False
    if not parsed.get("change"):
        return scheduled_activity, parsed.get("reason", ""), False
    activity = parsed.get("activity", "").strip()
    if not activity or activity == scheduled_activity:
        return scheduled_activity, parsed.get("reason", ""), False
    return _accept_activity_change(activity, time_str, scheduled_activity, parsed.get("reason", ""))


def _accept_activity_change(
    activity: str,
    time_str: str | None,
    scheduled_activity: str,
    reason: str,
) -> tuple[str, str, bool]:
    """Take the new activity only if it belongs to this hour.

    A change that contradicts the clock ("收尾今天的工作" at 06:00) is
    refused. The refusal is not absolute: a small dice roll keeps it
    possible, because people do break their own rules — just rarely, and
    never at every hour of the day.
    """
    cfg = CONFIG.get("time_plausibility", {}) or {}
    if not cfg.get("enabled", True) or not cfg.get("gate_activity_changes", True):
        return activity, reason, True
    verdict, fit_reason = _activity_time_fit(activity, _time_str_to_minutes(time_str))
    if verdict == _TIME_BAD and not _should_keep_deviation(verdict):
        return scheduled_activity, f"时段不合适，改回原计划（{fit_reason}）", False
    return activity, reason, True
