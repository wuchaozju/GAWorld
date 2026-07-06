import json
import random
import re

import requests

from gaworld.interests import format_growth_context, growth_focus
from gaworld.logging_setup import get_logger
from gaworld.llm.providers import call_llm
from gaworld.personality import personality_line
from gaworld.sim._schedule import loads_tolerant

_LOG = get_logger("gaworld.realism")


def _clamp(value, lo=0.0, hi=1.0):
    return float(max(lo, min(hi, value)))


def _contains_any(text, keywords):
    blob = str(text or "")
    return any(k in blob for k in keywords)


def _time_str_to_minutes(time_str):
    text = str(time_str or "")
    if not re.match(r"^\d{2}:\d{2}$", text):
        return None
    hh, mm = text.split(":")
    return int(hh) * 60 + int(mm)


def _extract_json_block(text):
    if not text:
        return ""
    block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if block_match:
        return block_match.group(1)
    inline_match = re.search(r"\{.*\}", text, re.S)
    return inline_match.group(0) if inline_match else ""


def _parse_json_dict(text):
    blob = _extract_json_block(text)
    if not blob:
        return {}
    data = loads_tolerant(blob)
    return data if isinstance(data, dict) else {}


def time_bucket(time_str):
    if not re.match(r"^\d{2}:\d{2}$", str(time_str)):
        return "unknown"
    hh = int(time_str.split(":")[0])
    if 5 <= hh < 11:
        return "morning"
    if 11 <= hh < 17:
        return "afternoon"
    if 17 <= hh < 22:
        return "evening"
    return "night"


def location_bucket(location):
    text = str(location or "")
    if any(k in text for k in ["Block", "Home", "Residential", "Village"]):
        return "home"
    if any(k in text for k in ["Office", "Labs", "School", "Clinic", "Hospital", "Studio", "Station"]):
        return "work"
    return "public"


def build_context_key(time_str, location, activity):
    return f"{time_bucket(time_str)}|{location_bucket(location)}|{activity}"


def compute_episode_salience(delta_stress, event_intensity, novelty, goal_relevance):
    salience = (
        0.35 * abs(float(delta_stress))
        + 0.25 * float(event_intensity)
        + 0.20 * float(novelty)
        + 0.20 * float(goal_relevance)
    )
    return _clamp(salience)


def _behavior_cfg(cfg=None):
    root = cfg if isinstance(cfg, dict) else {}
    return root.get("behavior", {}) if isinstance(root.get("behavior", {}), dict) else {}


def update_needs(agent, time_str, activity, cfg=None, changed=False, travel=None):
    behavior_cfg = _behavior_cfg(cfg)
    fatigue_work_gain = float(behavior_cfg.get("fatigue_work_gain", 0.035))
    fatigue_sleep_recovery = float(behavior_cfg.get("fatigue_sleep_recovery", 0.18))
    self_control_recovery = float(behavior_cfg.get("self_control_recovery", 0.08))
    time_pressure_decay = float(behavior_cfg.get("time_pressure_decay", 0.06))
    state = agent.setdefault("state", {})
    state["energy"] = float(state.get("energy", 0.75))
    state["hunger"] = float(state.get("hunger", 0.25))
    state["social_need"] = float(state.get("social_need", 0.40))
    state["fatigue_debt"] = float(state.get("fatigue_debt", 0.20))
    state["self_control"] = float(state.get("self_control", 0.60))
    state["time_pressure"] = float(state.get("time_pressure", 0.25))
    text = str(activity or "")
    minutes = _time_str_to_minutes(time_str)
    work_like = _contains_any(
        text,
        [
            "工作",
            "上班",
            "学习",
            "上课",
            "通勤",
            "加班",
            "研究",
            "实验",
            "论文",
            "备课",
            "指导",
            "项目",
            "邮件",
            "开会",
            "会议",
            "报告",
        ],
    )
    sleep_like = _contains_any(text, ["睡", "入睡", "就寝"])
    rest_like = _contains_any(text, ["休息", "睡", "午休", "睡前", "放松", "躺", "小憩"])
    meal_like = _contains_any(
        text,
        [
            "早饭",
            "早餐",
            "午饭",
            "午餐",
            "晚饭",
            "晚餐",
            "吃饭",
            "用餐",
            "外卖",
            "餐馆",
            "餐厅",
            "食堂",
            "做饭",
            "买菜",
            "咖啡",
            "茶歇",
        ],
    )
    social_like = _contains_any(
        text,
        [
            "聊天",
            "聚会",
            "同事",
            "朋友",
            "家人",
            "拜访",
            "学生",
            "合作者",
            "组会",
            "讨论",
            "交流",
            "沟通",
            "协作",
            "社区",
            "通话",
            "会面",
        ],
    )
    active_like = _contains_any(text, ["通勤", "散步", "运动", "健身", "跑步", "采购", "买菜", "出行"])
    transit_like = str((travel or {}).get("status", "")).strip() in {"departed", "in_transit"} or _contains_any(
        text,
        ["通勤", "前往", "移动", "赶路"],
    )
    quiet_recovery = rest_like and not social_like and not work_like
    late_hour = minutes is not None and (minutes >= 21 * 60 or minutes < 5 * 60)

    energy_delta = -0.012
    if work_like:
        energy_delta -= 0.02
    if active_like:
        energy_delta -= 0.01
    if rest_like:
        energy_delta += 0.08
    if meal_like:
        energy_delta += 0.01
    state["energy"] += energy_delta

    hunger_delta = 0.035
    if minutes is not None and minutes in range(690, 841):
        hunger_delta += 0.015
    if minutes is not None and minutes in range(1050, 1201):
        hunger_delta += 0.015
    if work_like or active_like:
        hunger_delta += 0.01
    if meal_like:
        hunger_delta -= 0.28
    state["hunger"] += hunger_delta

    social_delta = 0.015
    if work_like and not social_like:
        social_delta += 0.01
    if rest_like and not social_like:
        social_delta += 0.01
    if social_like:
        social_delta -= 0.08
    state["social_need"] += social_delta

    fatigue_delta = 0.0
    if work_like:
        fatigue_delta += fatigue_work_gain
    if active_like:
        fatigue_delta += 0.018
    if transit_like:
        fatigue_delta += 0.025
    if late_hour and not sleep_like:
        fatigue_delta += 0.015
    if sleep_like:
        fatigue_delta -= fatigue_sleep_recovery
    elif quiet_recovery:
        fatigue_delta -= fatigue_sleep_recovery * 0.35
    if meal_like:
        fatigue_delta -= 0.015
    state["fatigue_debt"] += fatigue_delta

    time_pressure_delta = 0.008
    if work_like:
        time_pressure_delta += 0.015
    if transit_like:
        time_pressure_delta += 0.06
    if changed:
        time_pressure_delta += 0.10
    if rest_like or sleep_like:
        time_pressure_delta -= time_pressure_decay
    elif meal_like:
        time_pressure_delta -= time_pressure_decay * 0.35
    state["time_pressure"] += time_pressure_delta

    stress = float(state.get("stress", 0.5))
    fatigue = float(state.get("fatigue_debt", 0.20))
    hunger = float(state.get("hunger", 0.25))
    strain = _clamp(0.42 * stress + 0.36 * fatigue + 0.22 * hunger)
    self_control_delta = -0.01
    if strain > 0.55:
        self_control_delta -= (strain - 0.55) * 0.20
    if sleep_like:
        self_control_delta += self_control_recovery
    elif quiet_recovery:
        self_control_delta += self_control_recovery * 0.45
    if meal_like:
        self_control_delta += 0.03
    if social_like and state["social_need"] > 0.60:
        self_control_delta += 0.02
    if changed:
        self_control_delta -= 0.03
    if late_hour and work_like:
        self_control_delta -= 0.02
    state["self_control"] += self_control_delta

    state["energy"] = _clamp(state["energy"])
    state["hunger"] = _clamp(state["hunger"])
    state["social_need"] = _clamp(state["social_need"])
    state["fatigue_debt"] = _clamp(state["fatigue_debt"])
    state["self_control"] = _clamp(state["self_control"])
    state["time_pressure"] = _clamp(state["time_pressure"])


def infer_episode_tags(activity, action, reflection, env_events=None, policy_event=None):
    tags = set()
    blob = " ".join([
        str(activity or ""),
        str(action or ""),
        str(reflection or ""),
        " ".join(str(e) for e in (env_events or [])),
        str(policy_event or ""),
    ])
    if any(k in blob for k in ["工作", "上班", "通勤", "加班", "会议"]):
        tags.add("work")
    if any(k in blob for k in ["家", "家人", "陪伴", "照顾"]):
        tags.add("family")
    if any(k in blob for k in ["医院", "诊所", "锻炼", "健康", "晨练"]):
        tags.add("health")
    if any(k in blob for k in ["政策", "制度", "监管"]):
        tags.add("policy")
    if any(k in blob for k in ["争执", "冲突", "不满", "抗议"]):
        tags.add("conflict")
    if any(k in blob for k in ["完成", "顺利", "满意", "进展"]):
        tags.add("success")
    if any(k in blob for k in ["失败", "挫败", "焦虑", "拖延"]):
        tags.add("failure")
    return sorted(tags) if tags else ["routine"]


def _fallback_intentions(agent, recent_episodes):
    state = agent.get("state", {})
    priorities = []
    if state.get("stress", 0.5) > 0.65:
        priorities.append("降低压力")
    if state.get("econ_security", 0.5) < 0.45:
        priorities.append("提高收入稳定性")
    if state.get("city_identity", 0.5) < 0.45:
        priorities.append("保持社区连接")
    if not priorities:
        priorities.append("维持日常节奏")
    top_tags = []
    for ep in recent_episodes[:3]:
        top_tags.extend(ep.get("tags", []))
    if "health" in top_tags:
        priorities.append("保证身体状态")
    avoidances = ["冲动决策"] if state.get("stress", 0.5) > 0.7 else ["长时间无效分心"]
    target_social = "增加与熟人的正向互动" if state.get("social_need", 0.5) > 0.55 else "保持适度社交"
    target_recovery = "确保休息与进食节奏"
    focus = growth_focus(agent.get("growth_profile"), limit=2)
    for name in focus:
        priorities.append(f"发展{name}")
    return {
        "priorities": priorities[:4],
        "avoidances": avoidances[:2],
        "target_social": target_social,
        "target_recovery": target_recovery,
        "growth_focus": focus,
    }


def build_daily_intentions(agent, recent_episodes, cfg, llm_budget_ctx, goals_context="无"):
    fallback = _fallback_intentions(agent, recent_episodes)
    if not isinstance(llm_budget_ctx, dict) or llm_budget_ctx.get("remaining", 0) <= 0:
        return fallback
    profile_text = "\n".join([
        f"姓名：{agent.get('name', '')}",
        f"职业：{agent.get('job', '')}",
        personality_line(agent, "routine"),
        f"当前状态：{json.dumps(agent.get('state', {}), ensure_ascii=False)}",
        f"兴趣与技能成长画像：\n{format_growth_context(agent.get('growth_profile'))}",
    ])
    eps = recent_episodes[:5]
    eps_text = json.dumps(
        [
            {
                "activity": e.get("final_activity", ""),
                "action": e.get("action", ""),
                "salience": e.get("salience", 0),
                "tags": e.get("tags", []),
                "reflection": e.get("reflection", ""),
            }
            for e in eps
        ],
        ensure_ascii=False,
        indent=2,
    )
    prompt = f"""
你是城市模拟器中的“每日意图生成器”。
请根据角色信息与最近高显著性经历，给出今天的行为意图。
角色信息：
{profile_text}
近期经历：
{eps_text}
当前人生与阶段目标：
{goals_context}

只输出 JSON：
{{
  "priorities": ["...","..."],
  "avoidances": ["..."],
  "target_social": "...",
  "target_recovery": "...",
  "growth_focus": ["今日重点发展的兴趣或技能名称"]
}}
要求：
1) priorities 2-4项，avoidances 1-2项。
2) 都是中文短语，可自然包含兴趣恢复、技能练习或职业转型准备。
3) growth_focus 0-2项，只能来自兴趣与技能成长画像里的名称。
4) 若“当前人生与阶段目标”不为“无”，priorities 中自然包含 0-2 项与短期目标相关的事项；状态不佳时可为恢复让位。
5) 不要输出其他文字。
"""
    llm_budget_ctx["remaining"] = max(0, int(llm_budget_ctx.get("remaining", 0)) - 1)
    try:
        resp = call_llm(prompt, task="daily_intentions", agent_id=agent["id"])
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        _LOG.warning("daily_intentions LLM call failed for agent %s: %s", agent.get("id"), exc)
        return fallback
    parsed = _parse_json_dict(resp)
    if not parsed:
        return fallback
    priorities = parsed.get("priorities", [])
    avoidances = parsed.get("avoidances", [])
    growth_items = parsed.get("growth_focus", [])
    if not isinstance(priorities, list):
        priorities = []
    if not isinstance(avoidances, list):
        avoidances = []
    if not isinstance(growth_items, list):
        growth_items = []
    result = {
        "priorities": [str(x).strip() for x in priorities if str(x).strip()][:4] or fallback["priorities"],
        "avoidances": [str(x).strip() for x in avoidances if str(x).strip()][:2] or fallback["avoidances"],
        "target_social": str(parsed.get("target_social", "")).strip() or fallback["target_social"],
        "target_recovery": str(parsed.get("target_recovery", "")).strip() or fallback["target_recovery"],
        "growth_focus": [str(x).strip() for x in growth_items if str(x).strip()][:2]
        or fallback.get("growth_focus", []),
    }
    return result


def update_habits_from_episode(agent, episode, cfg):
    behavior_cfg = (cfg or {}).get("behavior", {})
    learning_rate = float(behavior_cfg.get("habit_learning_rate", 0.08))
    min_occurrences = int(behavior_cfg.get("habit_min_occurrences", 3))
    habits = agent.setdefault("habits", {})
    ctx = build_context_key(episode.get("time", ""), episode.get("location", ""), episode.get("final_activity", ""))
    action = str(episode.get("action", "")).strip()
    if not action:
        return habits
    item = habits.setdefault(
        ctx,
        {
            "action_counts": {},
            "preferred_action": action,
            "strength": 0.1,
            "last_updated_day": int(episode.get("day", 0)),
        },
    )
    counts = item.setdefault("action_counts", {})
    counts[action] = int(counts.get(action, 0)) + 1
    preferred = max(counts.items(), key=lambda x: x[1])[0]
    item["preferred_action"] = preferred
    item["last_updated_day"] = int(episode.get("day", 0))
    if sum(counts.values()) < min_occurrences:
        # A context seen once or twice — typically a one-off interrupt such
        # as 找地方避雨 — is not a habit yet. Keep counting, but leave the
        # strength at zero so it exerts no pull on action choice.
        item["strength"] = 0.0
        return habits
    if preferred == action:
        item["strength"] = _clamp(float(item.get("strength", 0.1)) + learning_rate * (1 - float(item.get("strength", 0.1))))
    else:
        item["strength"] = _clamp(float(item.get("strength", 0.1)) * (1 - learning_rate * 0.5))
    return habits


def consolidate_day(agent, day, episodes, cfg, llm_budget_ctx, goals_context="无"):
    memory_cfg = (cfg or {}).get("memory", {})
    top_k = int(memory_cfg.get("daily_consolidation_top_k", 12))
    selected = sorted(
        episodes,
        key=lambda e: float(e.get("decayed_salience", e.get("salience", 0.0))),
        reverse=True,
    )[:top_k]
    fallback_intentions = _fallback_intentions(agent, selected)
    if not selected:
        return {
            "summary": "今天整体较平稳，按常规节奏推进。",
            "intentions": fallback_intentions,
            "top_episode_ids": [],
            "goal_progress": [],
            "memory_text": f"[Day {day}] 今天整体较平稳，按常规节奏推进。",
        }
    summary_lines = []
    for e in selected[:5]:
        driver = str(e.get("decision_driver", "")).strip()
        cost = str(e.get("change_reason", "")).strip()
        expected = str(e.get("expected_outcome", "")).strip()
        line = (
            f"{e.get('time', '')} {e.get('final_activity', '')} -> {e.get('action', '')} "
            f"(salience={float(e.get('salience', 0.0)):.2f})"
        )
        if driver:
            line += f" driver={driver}"
        if cost:
            line += f" cost={cost}"
        if expected:
            line += f" expect={expected}"
        summary_lines.append(line)
    base_summary = "；".join(summary_lines)
    result = {
        "summary": base_summary,
        "intentions": fallback_intentions,
        "top_episode_ids": [str(e.get("episode_id", "")) for e in selected if e.get("episode_id")],
        "goal_progress": [],
    }
    if isinstance(llm_budget_ctx, dict) and llm_budget_ctx.get("remaining", 0) > 0:
        prompt = f"""
你是城市模拟器中的“日终经验整合器”。
请根据以下经历生成一句经验总结，并给出明日行为意图。
角色：{agent.get('name', '')}
经历：
{json.dumps(summary_lines, ensure_ascii=False, indent=2)}
当前人生与阶段目标（长期/短期目标带[编号]）：
{goals_context}
输出 JSON：
{{
  "summary": "...",
  "priorities": ["...","..."],
  "avoidances": ["..."],
  "target_social": "...",
  "target_recovery": "...",
  "growth_focus": ["..."],
  "goal_progress": [{{"id":"stg1","progress":0.55,"note":"15字内的推进说明"}}]
}}
goal_progress 仅包含今天确有推进或明确受挫的目标；id 必须使用目标里的[编号]；没有则给 []。
仅输出 JSON。
"""
        llm_budget_ctx["remaining"] = max(0, int(llm_budget_ctx.get("remaining", 0)) - 1)
        try:
            resp = call_llm(prompt, task="memory_consolidation", agent_id=agent["id"])
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            _LOG.warning("memory_consolidation LLM call failed for agent %s: %s", agent.get("id"), exc)
            resp = ""
        parsed = _parse_json_dict(resp)
        if parsed:
            parsed_growth_focus = parsed.get("growth_focus", [])
            if not isinstance(parsed_growth_focus, list):
                parsed_growth_focus = []
            result["summary"] = str(parsed.get("summary", "")).strip() or result["summary"]
            result["intentions"] = {
                "priorities": [str(x).strip() for x in parsed.get("priorities", []) if str(x).strip()][:4]
                or fallback_intentions["priorities"],
                "avoidances": [str(x).strip() for x in parsed.get("avoidances", []) if str(x).strip()][:2]
                or fallback_intentions["avoidances"],
                "target_social": str(parsed.get("target_social", "")).strip() or fallback_intentions["target_social"],
                "target_recovery": str(parsed.get("target_recovery", "")).strip() or fallback_intentions["target_recovery"],
                "growth_focus": [str(x).strip() for x in parsed_growth_focus if str(x).strip()][:2]
                or fallback_intentions.get("growth_focus", []),
            }
            parsed_goal_progress = parsed.get("goal_progress", [])
            result["goal_progress"] = (
                parsed_goal_progress if isinstance(parsed_goal_progress, list) else []
            )
    result["memory_text"] = f"[Day {day} Consolidation] {result['summary']}"
    return result


def relationship_update(agent, neighbor_id, interaction_signal, cfg):
    relationships = agent.setdefault("relationships", {})
    key = str(neighbor_id)
    item = relationships.setdefault(
        key,
        {
            "closeness": 0.5,
            "trust": 0.5,
            "obligation": 0.5,
            "friction": 0.5,
            "last_interaction_day": int(agent.get("current_day", 0)),
            "phase": 1,
        },
    )
    signal = str(interaction_signal or "neutral")
    phase = int(item.get("phase", 1))
    closeness = float(item.get("closeness", 0.5))
    if closeness > 0.7 and phase < 3:
        phase += 1
        item["phase"] = phase
    elif closeness < 0.3 and phase > -1:
        phase -= 1
        item["phase"] = phase
    else:
        item["phase"] = phase
    mult = 2.0 if phase >= 3 else 1.0
    if signal == "positive":
        item["closeness"] = _clamp(float(item.get("closeness", 0.5)) + 0.03 * mult)
        item["trust"] = _clamp(float(item.get("trust", 0.5)) + 0.02 * mult)
        item["obligation"] = _clamp(float(item.get("obligation", 0.5)) + 0.015 * mult)
        item["friction"] = _clamp(float(item.get("friction", 0.5)) - 0.02 * mult)
    elif signal == "negative":
        item["closeness"] = _clamp(float(item.get("closeness", 0.5)) - 0.04 * mult)
        item["trust"] = _clamp(float(item.get("trust", 0.5)) - 0.03 * mult)
        item["obligation"] = _clamp(float(item.get("obligation", 0.5)) + 0.01 * mult)
        item["friction"] = _clamp(float(item.get("friction", 0.5)) + 0.05 * mult)
    else:
        item["closeness"] = _clamp(float(item.get("closeness", 0.5)) + 0.01 * mult)
        item["obligation"] = _clamp(float(item.get("obligation", 0.5)) + 0.015 * mult)
        item["friction"] = _clamp(float(item.get("friction", 0.5)) - 0.005 * mult)
    today = int(agent.get("current_day", 0))
    item["last_interaction_day"] = today
    # Mirror to last_contact_day so the social_network decay/dunbar
    # subsystems share a single "last touched" clock.
    item["last_contact_day"] = today
    _update_emotion_state(agent, signal)
    return item


def _update_emotion_state(agent, signal):
    state = agent.setdefault("state", {})
    current = int(state.get("emotion_state", 1))
    energy = float(state.get("energy", 0.75))
    fatigue = float(state.get("fatigue_debt", 0.20))
    hunger = float(state.get("hunger", 0.25))
    if signal == "positive":
        if current in (2, 3, 4):
            new = 1
        else:
            new = max(0, current - 1)
    elif signal == "negative":
        if current == 0:
            new = 2
        elif current == 1:
            new = 3 if random.random() < 0.4 else 2
        else:
            new = min(4, current + 1)
    elif energy < 0.3 or fatigue > 0.7 or hunger > 0.7:
        if current < 2:
            new = current + 1
        elif current > 2 and random.random() < 0.2:
            new = current - 1
        else:
            new = current
    else:
        new = current
    state["emotion_state"] = new


def apply_relationship_decay(agent, current_day):
    rels = agent.get("relationships", {})
    for item in rels.values():
        if not isinstance(item, dict):
            continue
        last_day = int(item.get("last_interaction_day", item.get("last_contact_day", 0)))
        days_no_interact = int(current_day) - last_day
        if days_no_interact <= 1:
            continue
        decay = 0.05 * (days_no_interact - 1)
        item["closeness"] = _clamp(float(item.get("closeness", 0.5)) - decay)
        item["trust"] = _clamp(float(item.get("trust", 0.5)) - decay * 0.5)
        closeness = float(item.get("closeness", 0.5))
        phase = int(item.get("phase", 1))
        if closeness < 0.3 and phase > -1:
            item["phase"] = phase - 1
        elif closeness > 0.7 and phase < 3:
            item["phase"] = phase + 1


def relationship_weight(agent, neighbor_id):
    rel = agent.get("relationships", {})
    item = rel.get(str(neighbor_id), {})
    if isinstance(item, dict) and item.get("role"):
        # Defer to the role-aware weight when the schema is populated.
        try:
            from gaworld.social.network import role_aware_weight
        except ImportError:  # pragma: no cover - fallback only if module missing
            role_aware_weight = None  # type: ignore[assignment]
        if role_aware_weight is not None:
            return role_aware_weight(item)
    closeness = float(item.get("closeness", 0.5))
    trust = float(item.get("trust", 0.5))
    obligation = float(item.get("obligation", 0.5))
    friction = float(item.get("friction", 0.5))
    return max(0.01, closeness * 0.45 + trust * 0.30 + obligation * 0.20 - friction * 0.15)


def infer_interaction_signal(reflection_text):
    text = str(reflection_text or "")
    if any(k in text for k in ["满意", "开心", "顺利", "支持", "放松"]):
        return "positive"
    if any(k in text for k in ["冲突", "焦虑", "烦躁", "不满", "争执"]):
        return "negative"
    return "neutral"


def intention_text(intentions):
    if not isinstance(intentions, dict):
        return "无明确意图"
    priorities = intentions.get("priorities", [])
    avoidances = intentions.get("avoidances", [])
    social = intentions.get("target_social", "")
    recovery = intentions.get("target_recovery", "")
    growth = intentions.get("growth_focus", [])
    p_text = "、".join(str(x) for x in priorities if str(x).strip()) or "无"
    a_text = "、".join(str(x) for x in avoidances if str(x).strip()) or "无"
    g_text = "、".join(str(x) for x in growth if str(x).strip()) or "无"
    return f"优先：{p_text}；避免：{a_text}；社交：{social or '无'}；恢复：{recovery or '无'}；成长：{g_text}"
