"""Dynamic Behavior System — makes agent daily routines feel human.

Four interlocking engines:

1. **InterruptEngine** — manages a priority queue of potential schedule
   interruptions (external events, social triggers, impulses, tasks).
   Each interrupt is scored against the current activity's commitment
   level; the highest-net-priority interrupt (if any) wins.

2. **SpontaneityEngine** — generates context-aware impromptu urges
   driven by emotion, fatigue, stress, hunger, personality, time of
   day, and recent experience.  Replaces the old fixed ``impulse_pool``.

3. **SocialChainResolver** — detects co-located agents, evaluates
   encounter probability based on relationship strength, and produces
   social behaviour chains (chance meetings, invitations, contagion).

4. **EnvironmentResponsePipeline** — converts weather changes, traffic
   jams, shop promotions, breaking news, etc. into concrete behaviour
   modification proposals, filtered by personality and proximity.

All four engines produce **InterruptCandidate** dicts that feed into
InterruptEngine.  The main simulation loop calls
``evaluate_step_dynamics()`` once per agent per time-step; it returns
a final activity (possibly changed), the reason, and side-effects
(schedule insertions, social interactions, mood shifts).

Design goals
------------
- Pure Python, no heavy dependencies (only stdlib + numpy).
- Deterministic when seeded via ``random.seed()``.
- Fully decoupled from LLM calls — all decisions are rule-based so
  they execute instantly.  The LLM is only used *after* the dynamic
  system has decided to change an activity, to generate narrative text
  via the existing ``maybe_adjust_activity`` / ``call_llm`` path.
- Backward compatible: the module is opt-in via
  ``CONFIG["dynamic_behavior"]["enabled"]``.
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Tuple

# Leaf import: gaworld.personality.traits is stdlib-only, so this module keeps
# its "no heavy dependencies" property.
from gaworld.personality.traits import trait_modifier, traits_of

try:
    import numpy as np  # type: ignore
except ImportError:  # pragma: no cover — numpy is optional at import time
    np = None  # type: ignore

# =========================================================================
# Utilities
# =========================================================================

def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _time_to_minutes(t: Optional[str]) -> Optional[int]:
    if not t or not isinstance(t, str):
        return None
    parts = t.split(":")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return None


def _minutes_to_time(m: int) -> str:
    m = m % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def _contains_any(text: str, keywords: list) -> bool:
    return any(k in text for k in keywords)


# =========================================================================
# Constants — Commitment Levels
# =========================================================================

# How hard it is to interrupt an activity (0 = trivial, 1 = immovable).
COMMITMENT_KEYWORDS: List[Tuple[float, List[str]]] = [
    (0.95, ["考试", "面试", "手术", "急救", "值班", "开庭"]),
    (0.85, ["开会", "会议", "上课", "教学", "培训", "演出", "比赛"]),
    (0.70, ["工作", "上班", "加班", "实验", "写代码", "值日"]),
    (0.55, ["做饭", "接孩子", "送孩子", "看病", "取快递"]),
    (0.40, ["通勤", "午饭", "晚饭", "吃饭", "购物", "买菜"]),
    (0.25, ["散步", "锻炼", "看书", "学习", "浏览新闻"]),
    (0.15, ["刷手机", "发呆", "休息", "闲逛", "聊天"]),
    (0.05, ["睡前准备", "个人时间"]),
]


def activity_commitment(activity: str) -> float:
    """Return the commitment level of an activity (0–1)."""
    for level, keywords in COMMITMENT_KEYWORDS:
        if _contains_any(activity, keywords):
            return level
    return 0.35  # default moderate commitment


# =========================================================================
# 1.  InterruptEngine
# =========================================================================

class InterruptCandidate:
    """A potential schedule interruption."""
    __slots__ = (
        "source", "kind", "activity", "reason", "priority",
        "duration_minutes", "resumable", "mood_delta", "extra",
    )

    def __init__(
        self,
        source: str,            # "environment", "social", "spontaneous", "task"
        kind: str,              # sub-type, e.g. "weather_change", "encounter"
        activity: str,          # proposed replacement activity
        reason: str,            # human-readable reason
        priority: float,        # 0–1, higher = more urgent
        duration_minutes: int = 30,
        resumable: bool = True, # can the original activity resume after?
        mood_delta: float = 0.0,
        extra: Optional[Dict] = None,
    ):
        self.source = source
        self.kind = kind
        self.activity = activity
        self.reason = reason
        self.priority = _clip(priority)
        self.duration_minutes = max(5, duration_minutes)
        self.resumable = resumable
        self.mood_delta = mood_delta
        self.extra = extra or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "kind": self.kind,
            "activity": self.activity,
            "reason": self.reason,
            "priority": round(self.priority, 3),
            "duration_minutes": self.duration_minutes,
            "resumable": self.resumable,
            "mood_delta": round(self.mood_delta, 3),
            "extra": self.extra,
        }


def evaluate_interrupts(
    candidates: List[InterruptCandidate],
    current_activity: str,
    agent: Dict,
) -> Optional[InterruptCandidate]:
    """Pick the winning interrupt, if any, from the candidate list.

    An interrupt wins only if its *net priority* (priority minus the
    activity's commitment resistance) exceeds a personality-dependent
    threshold.
    """
    if not candidates:
        return None

    commitment = activity_commitment(current_activity)
    state = agent.get("state", {}) if isinstance(agent, dict) else {}

    # Personality modifiers
    self_control = _f(state.get("self_control", 0.6), 0.6)
    risk_pref = _f(state.get("risk_preference", 0.5), 0.5)

    # Threshold: high self-control + high commitment = very hard to interrupt
    threshold = 0.10 + commitment * 0.55 + self_control * 0.15 - risk_pref * 0.08
    # Conscientiousness raises the bar, neuroticism lowers it. Multiplicative
    # and narrowly bounded: this threshold is consulted every step, so a wide
    # band would compound into an agent that is either never or always
    # interruptible.
    threshold *= trait_modifier(agent, "interrupt_threshold")

    best: Optional[InterruptCandidate] = None
    best_net = -1.0

    for c in candidates:
        net = c.priority - threshold
        # Source-specific adjustments
        if c.source == "environment":
            net += 0.05  # environment interrupts are slightly harder to ignore
        elif c.source == "social":
            social_need = _f(state.get("social_need", 0.5), 0.5)
            net += (social_need - 0.5) * 0.15
        elif c.source == "spontaneous":
            net -= self_control * 0.10  # self-control resists impulses

        if net > best_net:
            best_net = net
            best = c

    if best is not None and best_net > 0:
        # Stochastic gate: even a net-positive interrupt may be suppressed
        # by the agent's discipline.
        accept_prob = _clip(0.40 + best_net * 1.2)
        if random.random() < accept_prob:
            return best

    return None


# =========================================================================
# 2.  SpontaneityEngine
# =========================================================================

# Mood-indexed activity pools: (activity, thought_text, base_intensity)
SPONTANEOUS_POOLS: Dict[str, List[Tuple[str, str, float]]] = {
    "happy": [
        ("约朋友出去", "心情不错，想找人一起出去走走。", 0.55),
        ("逛街购物", "心情好想犒劳一下自己。", 0.45),
        ("去咖啡店", "想找个舒服的地方坐坐享受一下。", 0.40),
        ("唱歌", "心情好到想哼几句。", 0.30),
    ],
    "stressed": [
        ("独自散步", "压力有点大，想一个人安静走走。", 0.55),
        ("去公园坐坐", "想找个安静的地方放空一下。", 0.50),
        ("买杯奶茶", "想用一点甜的东西缓解压力。", 0.40),
        ("听音乐", "想戴上耳机隔绝一下周围的噪音。", 0.35),
    ],
    "tired": [
        ("找地方休息", "身体在抗议了，需要缓一缓。", 0.65),
        ("买杯咖啡", "需要补充一点能量才能撑下去。", 0.50),
        ("坐下来发呆", "脑子已经转不动了，想放空几分钟。", 0.40),
        ("小憩片刻", "太困了，想闭眼几分钟。", 0.55),
    ],
    "bored": [
        ("刷手机", "无聊到手已经在找手机了。", 0.50),
        ("查看新闻", "想看看外面有什么有趣的事情。", 0.40),
        ("找人聊天", "无聊想找个人说说话。", 0.45),
        ("顺手购物", "既然闲着不如看看有什么想买的。", 0.35),
    ],
    "anxious": [
        ("整理待办", "焦虑让人想把事情理清楚。", 0.50),
        ("来回踱步", "坐不住，想起来走动走动。", 0.40),
        ("反复确认计划", "总觉得有什么遗漏，想再检查一遍。", 0.45),
        ("深呼吸放松", "试着让自己冷静下来。", 0.35),
    ],
    "lonely": [
        ("发消息给朋友", "突然想找人说两句。", 0.60),
        ("去人多的地方", "想感受一下人气。", 0.45),
        ("刷社交媒体", "想看看别人在干什么。", 0.40),
        ("打电话给家人", "突然想听听熟悉的声音。", 0.50),
    ],
}

# Time-of-day filters: activities that don't make sense at certain hours
_TIME_BLOCKED: Dict[str, List[Tuple[int, int]]] = {
    "逛街购物": [(22 * 60, 7 * 60)],    # no shopping after 22:00
    "约朋友出去": [(23 * 60, 6 * 60)],
    "唱歌": [(23 * 60, 8 * 60)],
    "去咖啡店": [(22 * 60, 6 * 60)],
    "买杯奶茶": [(22 * 60, 7 * 60)],
    "顺手购物": [(22 * 60, 7 * 60)],
}


def _is_time_blocked(activity: str, time_minutes: Optional[int]) -> bool:
    if time_minutes is None:
        return False
    blocks = _TIME_BLOCKED.get(activity)
    if not blocks:
        return False
    for start, end in blocks:
        if start > end:  # wraps midnight
            if time_minutes >= start or time_minutes < end:
                return True
        else:
            if start <= time_minutes < end:
                return True
    return False


def _classify_mood(state: Dict) -> str:
    """Classify the agent's current mood into a pool key."""
    emotion = _f(state.get("emotion", 0.5), 0.5)
    stress = _f(state.get("stress", 0.5), 0.5)
    energy = _f(state.get("energy", 0.7), 0.7)
    fatigue = _f(state.get("fatigue_debt", 0.2), 0.2)
    social_need = _f(state.get("social_need", 0.5), 0.5)

    if energy < 0.35 or fatigue > 0.65:
        return "tired"
    if stress > 0.70:
        return "stressed"
    if emotion > 0.70 and stress < 0.45:
        return "happy"
    if emotion < 0.35:
        return "anxious"
    if social_need > 0.70:
        return "lonely"
    # Boredom: moderate everything, low engagement
    engagement = _f(state.get("engagement", 0.5), 0.5)
    if engagement < 0.35 and energy > 0.50:
        return "bored"
    return "bored" if random.random() < 0.3 else "happy"


def generate_spontaneous_urge(
    agent: Dict,
    time_str: Optional[str] = None,
    current_activity: str = "",
) -> Optional[InterruptCandidate]:
    """Maybe produce a spontaneous behaviour urge.

    Returns None if the agent's current state doesn't trigger anything,
    or if personality / self-control suppresses the urge.
    """
    state = agent.get("state", {}) if isinstance(agent, dict) else {}
    self_control = _f(state.get("self_control", 0.6), 0.6)

    # Base probability of having a spontaneous thought
    base_prob = 0.25 - self_control * 0.15
    base_prob *= trait_modifier(agent, "spontaneity_chance")
    stress = _f(state.get("stress", 0.5), 0.5)
    base_prob += max(0.0, stress - 0.55) * 0.20
    base_prob += max(0.0, 0.45 - _f(state.get("emotion", 0.5), 0.5)) * 0.15

    if random.random() > _clip(base_prob, 0.05, 0.60):
        return None

    mood = _classify_mood(state)
    pool = SPONTANEOUS_POOLS.get(mood, SPONTANEOUS_POOLS["bored"])

    time_min = _time_to_minutes(time_str)

    # Filter by time-of-day
    valid = [(act, thought, inten) for act, thought, inten in pool
             if not _is_time_blocked(act, time_min)]
    if not valid:
        valid = pool

    # Filter out activities identical to current
    valid = [(a, t, i) for a, t, i in valid if a != current_activity]
    if not valid:
        return None

    # Weighted random pick by intensity
    weights = [i for _, _, i in valid]
    idx = random.choices(range(len(valid)), weights=weights, k=1)[0]
    act, thought, intensity = valid[idx]

    # Personality scaling
    personality_blob = " ".join([
        str(agent.get("personality", "")),
        str(agent.get("daily_life", "")),
    ])
    if _contains_any(personality_blob, ["外向", "活泼", "社交", "热情"]):
        if mood in ("happy", "lonely"):
            intensity *= 1.2
    if _contains_any(personality_blob, ["内向", "安静", "独处", "沉稳"]):
        if mood in ("stressed", "anxious"):
            intensity *= 1.15
        if act in ("约朋友出去", "找人聊天", "去人多的地方"):
            intensity *= 0.6

    # Duration estimation
    if "散步" in act or "踱步" in act:
        duration = random.randint(10, 25)
    elif "咖啡" in act or "奶茶" in act:
        duration = random.randint(10, 20)
    elif "购物" in act or "逛街" in act:
        duration = random.randint(20, 60)
    elif "休息" in act or "小憩" in act or "发呆" in act:
        duration = random.randint(10, 20)
    else:
        duration = random.randint(10, 30)

    return InterruptCandidate(
        source="spontaneous",
        kind=f"mood_{mood}",
        activity=act,
        reason=thought,
        priority=_clip(intensity, 0.10, 0.85),
        duration_minutes=duration,
        resumable=True,
        mood_delta=_spontaneous_mood_delta(mood),
    )


def _spontaneous_mood_delta(mood: str) -> float:
    return {
        "happy": 0.03,
        "stressed": 0.05,
        "tired": 0.02,
        "bored": 0.04,
        "anxious": 0.03,
        "lonely": 0.04,
    }.get(mood, 0.0)


# =========================================================================
# 2b. Need-Based Interrupts (hunger, fatigue, time pressure)
# =========================================================================

def generate_need_interrupts(
    agent: Dict,
    time_str: Optional[str] = None,
) -> List[InterruptCandidate]:
    """Produce interrupt candidates driven by physiological / task needs.

    Covers hunger, fatigue/energy, and time-pressure needs that were
    previously scattered inside ``maybe_generate_transient_thought``.
    """
    state = agent.get("state", {}) if isinstance(agent, dict) else {}
    candidates: List[InterruptCandidate] = []

    hunger = _f(state.get("hunger", 0.25), 0.25)
    energy = _f(state.get("energy", 0.75), 0.75)
    fatigue = _f(state.get("fatigue_debt", 0.2), 0.2)
    time_pressure = _f(state.get("time_pressure", 0.25), 0.25)

    # --- Hunger ---
    if hunger > 0.60:
        time_min = _time_to_minutes(time_str)
        # More likely to act on hunger near meal times
        meal_bonus = 0.0
        if time_min is not None:
            if 11 * 60 <= time_min <= 13 * 60 or 17 * 60 <= time_min <= 19 * 60:
                meal_bonus = 0.12
        intensity = _clip((hunger - 0.45) * 1.25 + meal_bonus, 0.0, 0.90)
        candidates.append(InterruptCandidate(
            source="need",
            kind="hunger",
            activity="找点吃的",
            reason=f"肚子有点占据注意力，想先找点吃的。(hunger={hunger:.2f})",
            priority=intensity,
            duration_minutes=random.randint(20, 45),
            resumable=True,
            mood_delta=0.02,
        ))

    # --- Fatigue / low energy ---
    if energy < 0.40 or fatigue > 0.60:
        intensity = _clip(max(0.40 - energy, fatigue - 0.50) * 1.4, 0.0, 0.85)
        if energy < 0.25:
            act, reason = "小憩片刻", "身体在发出强烈信号，需要闭眼休息几分钟。"
            duration = random.randint(15, 30)
        else:
            act, reason = "休息片刻", "身体有点撑不住，想临时缓一缓。"
            duration = random.randint(10, 20)
        candidates.append(InterruptCandidate(
            source="need",
            kind="recovery",
            activity=act,
            reason=f"{reason}(energy={energy:.2f}, fatigue={fatigue:.2f})",
            priority=intensity,
            duration_minutes=duration,
            resumable=True,
            mood_delta=0.01,
        ))

    # --- Time pressure ---
    if time_pressure > 0.65:
        intensity = _clip((time_pressure - 0.55) * 1.35, 0.0, 0.80)
        candidates.append(InterruptCandidate(
            source="task",
            kind="time_pressure",
            activity="处理待办",
            reason=f"时间压力突然冒出来，想先把最急的事处理掉。(tp={time_pressure:.2f})",
            priority=intensity,
            duration_minutes=random.randint(15, 40),
            resumable=True,
            mood_delta=-0.02,
        ))

    return candidates


# =========================================================================
# 2c. Inbox / Social Message Triggers
# =========================================================================

def generate_inbox_interrupts(
    agent: Dict,
    social_context: str = "",
    inbox_messages: Optional[List] = None,
) -> List[InterruptCandidate]:
    """Produce interrupt candidates from unread messages or social pings."""
    candidates: List[InterruptCandidate] = []
    state = agent.get("state", {}) if isinstance(agent, dict) else {}
    social_need = _f(state.get("social_need", 0.5), 0.5)

    has_trigger = False
    if inbox_messages:
        has_trigger = True
    elif social_context:
        trigger_kws = ["@", "提到", "回复", "消息", "邀请", "请求",
                       "留言", "呼叫", "私信", "通知"]
        if _contains_any(social_context, trigger_kws):
            has_trigger = True

    if has_trigger:
        intensity = _clip(0.40 + social_need * 0.25, 0.0, 0.75)
        candidates.append(InterruptCandidate(
            source="social",
            kind="inbox_message",
            activity="回复消息",
            reason="突然想到有人可能在等回应，想先处理一下关系或消息。",
            priority=intensity,
            duration_minutes=random.randint(5, 15),
            resumable=True,
            mood_delta=0.02,
            extra={"inbox_count": len(inbox_messages) if inbox_messages else 0},
        ))

    return candidates


# =========================================================================
# 3.  SocialChainResolver
# =========================================================================

def detect_co_located_agents(
    agent: Dict,
    all_agents: List[Dict],
    agents_by_id: Dict,
) -> List[Dict]:
    """Find other agents at the same location this time step."""
    my_loc = agent.get("locations", {}).get("current", "")
    if not my_loc:
        return []
    my_id = agent.get("id")
    co_located = []
    for other in all_agents:
        if other.get("id") == my_id:
            continue
        other_loc = other.get("locations", {}).get("current", "")
        if other_loc == my_loc and not other.get("locations", {}).get("in_transit"):
            co_located.append(other)
    return co_located


def _relationship_closeness(agent: Dict, other_id) -> float:
    rels = agent.get("relationships", {})
    if not isinstance(rels, dict):
        return 0.3
    rel = rels.get(str(other_id), {})
    if not isinstance(rel, dict):
        return 0.3
    return _f(rel.get("closeness", 0.3), 0.3)


def generate_social_interrupts(
    agent: Dict,
    co_located: List[Dict],
    time_str: Optional[str] = None,
) -> List[InterruptCandidate]:
    """Produce social interrupt candidates from co-located agents."""
    if not co_located:
        return []

    state = agent.get("state", {}) if isinstance(agent, dict) else {}
    social_need = _f(state.get("social_need", 0.5), 0.5)
    # Traits first, keyword sniffing as the fallback for agents the Big Five
    # plugin never seeded. Keeping both is not double-counting: the branch
    # below picks exactly one.
    has_traits = any(traits_of(agent, "rules").values())
    personality_blob = str(agent.get("personality", ""))
    is_extrovert = _contains_any(personality_blob, ["外向", "活泼", "社交", "热情", "开朗"])

    candidates = []

    for other in co_located:
        other_id = other.get("id")
        other_name = other.get("name", str(other_id))
        closeness = _relationship_closeness(agent, other_id)

        # Encounter probability: higher closeness + social need = more likely
        encounter_prob = closeness * 0.35 + social_need * 0.20
        if has_traits:
            encounter_prob *= trait_modifier(agent, "social_encounter")
        elif is_extrovert:
            encounter_prob += 0.10
        encounter_prob = _clip(encounter_prob, 0.05, 0.70)

        if random.random() > encounter_prob:
            continue

        # What kind of social interaction?
        other_activity = ""
        other_schedule = other.get("_current_activity", "")
        other_activity = other_schedule

        if closeness > 0.65:
            # Close friend: invitation
            time_min = _time_to_minutes(time_str)
            if time_min and 11 * 60 <= time_min <= 13 * 60:
                act = f"和{other_name}一起吃午饭"
                reason = f"偶遇好友{other_name}，顺便一起吃个饭。"
                duration = random.randint(30, 50)
                priority = 0.55 + closeness * 0.15
            elif time_min and 17 * 60 <= time_min <= 19 * 60:
                act = f"和{other_name}一起吃晚饭"
                reason = f"遇到{other_name}，邀请一起吃个饭。"
                duration = random.randint(30, 60)
                priority = 0.55 + closeness * 0.15
            else:
                act = f"和{other_name}聊天"
                reason = f"偶遇{other_name}，停下来聊了一会儿。"
                duration = random.randint(10, 25)
                priority = 0.45 + closeness * 0.15
        elif closeness > 0.40:
            # Acquaintance: brief chat
            act = f"和{other_name}打招呼聊几句"
            reason = f"在路上碰到了{other_name}，寒暄了几句。"
            duration = random.randint(5, 15)
            priority = 0.30 + closeness * 0.15
        else:
            # Stranger-ish: behaviour contagion
            if other_activity and _contains_any(other_activity,
                    ["排队", "围观", "买", "奶茶", "咖啡", "促销"]):
                act = f"跟着{other_name}一起{other_activity}"
                reason = f"看到{other_name}在{other_activity}，好奇凑了过去。"
                duration = random.randint(10, 20)
                priority = 0.25
            else:
                continue

        candidates.append(InterruptCandidate(
            source="social",
            kind="encounter" if closeness > 0.40 else "contagion",
            activity=act,
            reason=reason,
            priority=_clip(priority, 0.15, 0.80),
            duration_minutes=duration,
            resumable=True,
            mood_delta=0.03 + closeness * 0.05,
            extra={"other_agent_id": other_id, "other_name": other_name,
                   "closeness": round(closeness, 2)},
        ))

    return candidates


# =========================================================================
# 4.  EnvironmentResponsePipeline
# =========================================================================

# Event type → (activity_suggestion, base_priority, duration_minutes)
_ENV_RESPONSE_MAP: Dict[str, List[Tuple[str, str, float, int]]] = {
    "weather": [
        ("rain", "找地方避雨", 0.55, 15),
        ("snow", "调整出行计划", 0.50, 15),
        ("hot", "找阴凉处休息", 0.35, 10),
        ("cold", "去室内暖和一下", 0.35, 10),
        ("storm", "就地避险", 0.85, 30),
    ],
    "traffic": [
        ("congestion", "改变路线避开拥堵", 0.40, 20),
        ("accident", "绕路避开事故路段", 0.50, 25),
        ("road_closure", "重新规划出行", 0.55, 20),
    ],
    "commercial": [
        ("promotion", "顺便看看促销", 0.30, 15),
        ("new_store", "好奇去看看新开的店", 0.25, 15),
        ("sale", "趁打折去逛逛", 0.35, 20),
    ],
    "news": [
        ("breaking", "查看突发新闻", 0.45, 10),
        ("local", "关注本地动态", 0.30, 10),
        ("social_media", "刷一下热搜", 0.25, 10),
    ],
    "emergency": [
        ("fire", "撤离现场", 0.95, 30),
        ("earthquake", "就地避险", 0.95, 30),
        ("flood", "转移到高处", 0.90, 40),
    ],
}

# Personality modifiers for environment response
_PERSONALITY_RESPONSE_MODIFIERS: Dict[str, Dict[str, float]] = {
    "cautious":  {"weather": 1.3, "traffic": 1.2, "emergency": 1.1, "commercial": 0.7, "news": 0.8},
    "adventurous": {"weather": 0.7, "traffic": 0.8, "emergency": 1.0, "commercial": 1.2, "news": 1.1},
    "curious":   {"weather": 0.9, "traffic": 0.9, "emergency": 1.0, "commercial": 1.4, "news": 1.5},
    "pragmatic": {"weather": 1.1, "traffic": 1.3, "emergency": 1.0, "commercial": 0.8, "news": 0.7},
}

_PERSONALITY_KEYWORDS: Dict[str, List[str]] = {
    "cautious": ["谨慎", "保守", "小心", "稳重", "理性", "风险厌恶"],
    "adventurous": ["冒险", "大胆", "好奇", "外向", "开放", "活泼"],
    "curious": ["好奇", "求知", "探索", "学习", "观察", "研究"],
    "pragmatic": ["务实", "实际", "效率", "目标导向", "计划性"],
}


#: OCEAN loadings for the four response archetypes above. Note that the
#: keyword table and the Big Five disagree about the word 开放: it sits under
#: ``adventurous`` there, while Openness here also feeds ``curious``. That is
#: precisely why traits win outright rather than being blended in — two
#: vocabularies for the same word would make the archetype unreadable.
_TRAIT_ARCHETYPES: Dict[str, Dict[str, float]] = {
    "cautious": {"n": 0.60, "o": -0.40},
    "adventurous": {"o": 0.60, "e": 0.35, "n": -0.25},
    "curious": {"o": 0.75, "e": -0.20},
    "pragmatic": {"c": 0.70, "o": -0.20},
}

#: Below this the trait vector says nothing distinctive and the keyword
#: fallback is the better guess.
_ARCHETYPE_FLOOR = 0.35


def _classify_personality(agent: Dict) -> str:
    traits = traits_of(agent, "rules")
    if any(traits.values()):
        scored = {
            name: sum(w * traits.get(dim, 0.0) for dim, w in loadings.items())
            for name, loadings in _TRAIT_ARCHETYPES.items()
        }
        best_trait_type = max(scored, key=lambda name: scored[name])
        if scored[best_trait_type] >= _ARCHETYPE_FLOOR:
            return best_trait_type
    blob = " ".join([
        str(agent.get("personality", "")),
        str(agent.get("values", "")),
        str(agent.get("daily_life", "")),
    ])
    best_type = "pragmatic"
    best_score = 0
    for ptype, keywords in _PERSONALITY_KEYWORDS.items():
        score = sum(1 for k in keywords if k in blob)
        if score > best_score:
            best_score = score
            best_type = ptype
    return best_type


def _classify_event_type(event: Dict) -> Tuple[str, str]:
    """Classify an environment event into (category, sub_type).

    Structured-first (P1): the ``EnvironmentSystem`` already tags every
    event with ``type`` (natural/economic/political/technology),
    ``topic`` and ``impact_tags``. We consult those before falling back
    to brittle description-keyword matching, and we check emergencies
    *first* so a ``natural``-typed earthquake is no longer masked as
    ordinary weather (the previous ordering bug).
    """
    ev_type = str(event.get("type", "")).lower()
    topic = str(event.get("topic", "")).lower()
    desc = str(event.get("description", event.get("name", ""))).lower()
    severity = _f(event.get("severity", 0.3), 0.3)

    # 1. Emergencies first — highest stakes, must not be masked by other types.
    if ev_type == "emergency" or _contains_any(desc, ["火灾", "爆炸", "起火"]):
        if _contains_any(desc, ["地震", "震"]):
            return "emergency", "earthquake"
        if _contains_any(desc, ["洪水", "溃堤", "泥石流"]) or "洪" in desc:
            return "emergency", "flood"
        return "emergency", "fire"
    if _contains_any(desc, ["地震"]):
        return "emergency", "earthquake"
    if _contains_any(desc, ["洪水", "溃堤", "泥石流"]):
        return "emergency", "flood"

    # 2. Traffic — structured mobility signal or keywords.
    if _contains_any(desc, ["拥堵", "堵车", "封路", "施工", "封闭"]) or (
        topic == "traffic" and "mobility" in {str(t).lower() for t in (event.get("impact_tags") or [])}
    ):
        if _contains_any(desc, ["事故"]):
            return "traffic", "accident"
        if _contains_any(desc, ["封路", "封闭"]):
            return "traffic", "road_closure"
        return "traffic", "congestion"

    # 3. Weather / natural — prefer structured type/topic over wording.
    if topic == "weather" or ev_type in ("weather", "natural") or _contains_any(
        desc, ["雨", "雪", "风", "高温", "暴风", "冰雹", "寒潮", "降温"]
    ):
        if _contains_any(desc, ["暴风", "台风", "暴雨", "雷暴", "强降雨"]):
            return "weather", "storm"
        if "雪" in desc:
            return "weather", "snow"
        if _contains_any(desc, ["高温", "酷热"]) or "热" in desc:
            return "weather", "hot"
        if _contains_any(desc, ["寒", "降温"]) or "冷" in desc:
            return "weather", "cold"
        return "weather", "rain"

    # 4. Commercial.
    if ev_type == "commercial" or _contains_any(desc, ["促销", "打折", "开业", "新开", "特价", "优惠"]):
        if _contains_any(desc, ["开业", "新开"]):
            return "commercial", "new_store"
        if _contains_any(desc, ["打折", "特价"]):
            return "commercial", "sale"
        return "commercial", "promotion"

    # 5. Info-driven domains (economic / political / technology): route to
    #    'news' with severity deciding breaking-vs-local. Previously these
    #    silently fell through to the generic fallback at fixed priority.
    if ev_type in ("economic", "political", "technology") or _contains_any(
        desc, ["新闻", "热搜", "突发", "头条", "政策", "市场", "监管", "舆论"]
    ):
        return ("news", "breaking") if severity >= 0.7 else ("news", "local")

    return "news", "local"


# Impact tags (set by EnvironmentSystem) → small additive priority boost.
# Lets the generation-side semantics influence the reaction side instead of
# being discarded. We add the single largest matching boost (no stacking).
_IMPACT_TAG_PRIORITY_BOOST: Dict[str, float] = {
    "mobility": 0.06,
    "mobility_intent": 0.04,
    "public_service": 0.05,
    "stress": 0.05,
}

# Anomaly escalation (P2): events flagged ``anomaly`` by EnvironmentSystem
# get a priority bump; a high anomaly score forces a non-resumable reaction
# (you don't calmly resume your plan during a genuine anomaly).
_ANOMALY_PRIORITY_BOOST = 0.15
_ANOMALY_NON_RESUMABLE_SCORE = 0.8


def generate_environment_interrupts(
    agent: Dict,
    env_events: List[Dict],
    current_location: str = "",
) -> List[InterruptCandidate]:
    """Convert environment events into interrupt candidates."""
    if not env_events:
        return []

    ptype = _classify_personality(agent)
    p_mods = _PERSONALITY_RESPONSE_MODIFIERS.get(ptype, {})
    candidates = []

    for event in env_events:
        category, sub_type = _classify_event_type(event)
        severity = _f(event.get("severity", 0.3), 0.3)
        tags = [str(t).lower() for t in (event.get("impact_tags") or [])]

        # Find matching response
        responses = _ENV_RESPONSE_MAP.get(category, [])
        match = None
        for resp_sub, act, base_pri, dur in responses:
            if resp_sub == sub_type:
                match = (act, base_pri, dur)
                break
        if not match:
            # Use first response in category as fallback
            if responses:
                _, act, base_pri, dur = responses[0]
                match = (act, base_pri, dur)
            else:
                continue

        act, base_pri, dur = match
        # Apply severity scaling
        priority = base_pri * (0.5 + severity * 0.8)
        # Apply personality modifier
        priority *= p_mods.get(category, 1.0)
        # Apply impact-tag boost (consume the structured signal, P1).
        tag_boost = max((_IMPACT_TAG_PRIORITY_BOOST[t] for t in tags
                         if t in _IMPACT_TAG_PRIORITY_BOOST), default=0.0)
        priority += tag_boost
        # Anomaly escalation (P2).
        is_anomaly = bool(event.get("anomaly"))
        anomaly_score = _f(event.get("anomaly_score", 0.0), 0.0)
        if is_anomaly:
            priority += _ANOMALY_PRIORITY_BOOST
        resumable = category != "emergency" and not (
            is_anomaly and anomaly_score >= _ANOMALY_NON_RESUMABLE_SCORE
        )

        desc = str(event.get("description", event.get("name", ""))).strip()
        reason = f"{desc}——{act}" if desc else act

        candidates.append(InterruptCandidate(
            source="environment",
            kind=f"{category}_{sub_type}",
            activity=act,
            reason=reason,
            priority=_clip(priority, 0.10, 0.95),
            duration_minutes=dur,
            resumable=resumable,
            mood_delta=-severity * 0.08 if category in ("emergency", "weather") or is_anomaly else 0.0,
            extra={"event_type": category, "sub_type": sub_type,
                   "severity": round(severity, 2), "impact_tags": tags,
                   "anomaly": is_anomaly, "anomaly_score": round(anomaly_score, 2)},
        ))

    return candidates


# =========================================================================
# 4a. Local physical reactions (P1)
# =========================================================================

def generate_local_physical_interrupts(
    agent: Dict,
    local_physical: Optional[Dict] = None,
    current_activity: str = "",
) -> List[InterruptCandidate]:
    """Turn the agent's *local* physical state into interrupt candidates.

    Consumes the per-agent snapshot produced by
    ``gaworld.world.local_physical`` (crowding / opening hours). Returns
    an empty list when no snapshot is available or the agent is moving,
    so the feature is naturally gated by whether P0 populated the data.
    """
    state = local_physical if isinstance(local_physical, dict) else (
        agent.get("_local_physical") if isinstance(agent, dict) else None
    )
    if not isinstance(state, dict) or state.get("in_transit"):
        return []

    location = str(state.get("location") or "").strip()
    if not location:
        return []

    candidates: List[InterruptCandidate] = []

    # Venue closed: you cannot do the intended thing here → must relocate.
    if state.get("is_open", True) is False:
        candidates.append(InterruptCandidate(
            source="environment",
            kind="venue_closed",
            activity="改去其他开门的地方",
            reason=f"{location}此刻不在营业时间，得换个地方",
            priority=0.55,
            duration_minutes=20,
            resumable=False,
            mood_delta=-0.03,
            extra={"event_type": "local_physical", "sub_type": "venue_closed",
                   "location": location},
        ))

    # Overcrowding: discomfort scales with how packed it is. An emergent
    # crowd *surge* (P2 anomaly) escalates priority and forces relocation.
    crowding = str(state.get("crowding") or "")
    ratio = _f(state.get("occupancy_ratio", 0.0), 0.0)
    is_anomaly = bool(state.get("anomaly"))
    if crowding == "非常拥挤" or is_anomaly:
        candidates.append(InterruptCandidate(
            source="environment",
            kind="crowd_anomaly" if is_anomaly else "crowd_packed",
            activity="尽快离开拥挤区域" if is_anomaly else "避开人群换个地方",
            reason=(
                f"{location}人流突然激增，想尽快离开" if is_anomaly
                else f"{location}此刻非常拥挤，想换个清静点的地方"
            ),
            priority=_clip((0.55 if is_anomaly else 0.30) + ratio * 0.25,
                           0.20, 0.80 if is_anomaly else 0.60),
            duration_minutes=20,
            resumable=not is_anomaly,
            mood_delta=-0.07 if is_anomaly else -0.04,
            extra={"event_type": "local_physical",
                   "sub_type": "crowd_anomaly" if is_anomaly else "crowd_packed",
                   "location": location, "occupancy_ratio": round(ratio, 2),
                   "anomaly": is_anomaly},
        ))

    return candidates


# =========================================================================
# 4b. Event Cascade Chains
# =========================================================================

# A cascade describes knock-on effects: the key event triggers the value
# events with some probability.  Each value is (description, severity,
# probability, mood_delta).
EVENT_CASCADES: Dict[str, List[Tuple[str, float, float, float]]] = {
    "weather_rain": [
        ("打车需求增加，排队等出租车", 0.30, 0.35, -0.03),
        ("路面湿滑，步行小心翼翼", 0.15, 0.25, -0.01),
    ],
    "weather_storm": [
        ("交通大面积延误", 0.55, 0.60, -0.05),
        ("部分路段积水无法通行", 0.50, 0.45, -0.04),
        ("快递和外卖延迟送达", 0.25, 0.50, -0.02),
    ],
    "traffic_congestion": [
        ("上班可能迟到", 0.40, 0.50, -0.04),
        ("心情因堵车而变差", 0.20, 0.55, -0.03),
    ],
    "traffic_accident": [
        ("围观群众聚集", 0.15, 0.30, 0.0),
        ("救护车通过，道路临时封闭", 0.45, 0.40, -0.02),
    ],
    "emergency_fire": [
        ("消防车封锁道路", 0.50, 0.70, -0.04),
        ("周围建筑疏散", 0.60, 0.55, -0.05),
    ],
}


def generate_cascade_interrupts(
    primary_interrupt: InterruptCandidate,
    agent: Dict,
) -> List[InterruptCandidate]:
    """Given a primary environment interrupt, generate possible knock-on
    effects as additional lower-priority interrupts."""
    cascade_key = f"{primary_interrupt.extra.get('event_type', '')}_{primary_interrupt.extra.get('sub_type', '')}"
    chains = EVENT_CASCADES.get(cascade_key, [])
    if not chains:
        return []

    results = []
    for desc, severity, prob, mood_d in chains:
        if random.random() > prob:
            continue
        results.append(InterruptCandidate(
            source="environment",
            kind="cascade",
            activity=desc.split("，")[0] if "，" in desc else desc[:8],
            reason=f"连锁反应：{desc}",
            priority=_clip(primary_interrupt.priority * 0.5 + severity * 0.3, 0.05, 0.60),
            duration_minutes=random.randint(10, 25),
            resumable=True,
            mood_delta=mood_d,
            extra={
                "cascade_from": cascade_key,
                "severity": round(severity, 2),
            },
        ))
    return results


# =========================================================================
# 5.  Schedule Insertion Helpers
# =========================================================================

def insert_activity_into_schedule(
    schedule: List[Tuple[str, str]],
    insert_time: str,
    activity: str,
    duration_minutes: int = 30,
    resumable: bool = True,
    original_activity: str = "",
) -> List[Tuple[str, str]]:
    """Insert a new activity into the schedule, shifting later items.

    If ``resumable`` is True and there's enough room, the original
    activity is appended after the inserted one.
    """
    insert_min = _time_to_minutes(insert_time)
    if insert_min is None:
        return schedule

    new_schedule = []
    inserted = False

    for i, (t, act) in enumerate(schedule):
        t_min = _time_to_minutes(t)
        if t_min is None:
            new_schedule.append((t, act))
            continue

        if not inserted and t_min >= insert_min:
            # Insert the new activity
            new_schedule.append((insert_time, activity))
            inserted = True

            # If resumable, push the current activity to after the interruption
            if resumable and original_activity:
                resume_min = insert_min + duration_minutes
                resume_time = _minutes_to_time(resume_min)
                # Only add resume if it's before the next scheduled item
                if i + 1 < len(schedule):
                    next_min = _time_to_minutes(schedule[i + 1][0])
                    if next_min and resume_min < next_min:
                        new_schedule.append((resume_time, original_activity))
                else:
                    new_schedule.append((resume_time, original_activity))

            # Shift subsequent items
            for j in range(i, len(schedule)):
                sj_time, sj_act = schedule[j]
                sj_min = _time_to_minutes(sj_time)
                if sj_min and sj_min < insert_min + duration_minutes:
                    # This item overlaps with the insertion — skip or shift
                    shifted_min = insert_min + duration_minutes
                    if resumable and sj_act == original_activity:
                        continue  # already added as resume
                    new_schedule.append((_minutes_to_time(shifted_min), sj_act))
                else:
                    new_schedule.append((sj_time, sj_act))
            break
        else:
            new_schedule.append((t, act))

    if not inserted:
        new_schedule.append((insert_time, activity))

    # Deduplicate and sort
    seen_times = set()
    deduped = []
    for t, act in sorted(new_schedule, key=lambda x: _time_to_minutes(x[0]) or 0):
        if t not in seen_times:
            deduped.append((t, act))
            seen_times.add(t)

    return deduped


# =========================================================================
# 6.  Main Entry Point — evaluate_step_dynamics
# =========================================================================

def evaluate_step_dynamics(
    agent: Dict,
    time_str: str,
    scheduled_activity: str,
    env_events: List[Dict],
    all_agents: List[Dict],
    agents_by_id: Dict,
    config: Optional[Dict] = None,
    social_context: str = "",
    inbox_messages: Optional[List] = None,
) -> Dict[str, Any]:
    """Run all engines and return the step's dynamic behaviour result.

    This is the single entry point called once per agent per time-step.
    It runs, in order:

    1. Environment response pipeline (+ cascade chains)
    2. Social chain resolver (co-location encounters)
    3. Inbox / social-message triggers
    4. Need-based interrupts (hunger, fatigue, time pressure)
    5. Spontaneity engine (mood-driven urges)
    6. Interrupt evaluator (picks the best candidate vs. commitment)

    Returns
    -------
    dict with keys:
        "activity" : str — final activity (may be unchanged)
        "changed" : bool — whether the activity was modified
        "reason" : str — why it changed (empty if not)
        "interrupt" : dict or None — the winning interrupt details
        "social_encounters" : list — any social interactions detected
        "mood_delta" : float — cumulative mood adjustment
        "schedule_insert" : dict or None — schedule insertion if applicable
        "all_candidates" : int — total number of candidates considered
        "cascade_events" : list — any cascade events that fired
    """
    cfg = config or {}
    dyn_cfg = cfg.get("dynamic_behavior", {})
    if not dyn_cfg.get("enabled", True):
        return _no_change_result(scheduled_activity)

    candidates: List[InterruptCandidate] = []
    cascade_events: List[Dict] = []

    # --- 1. Environment responses ---
    env_candidates = generate_environment_interrupts(
        agent, env_events,
        current_location=agent.get("locations", {}).get("current", ""),
    )
    candidates.extend(env_candidates)

    # --- 1b. Event cascades from primary env interrupts ---
    for ec in env_candidates:
        cascades = generate_cascade_interrupts(ec, agent)
        candidates.extend(cascades)
        for cc in cascades:
            cascade_events.append(cc.to_dict())

    # --- 1c. Local physical reactions (P1): crowding / venue closed.
    #     Reads the per-agent snapshot stored on the agent by P0; absent
    #     that snapshot this yields nothing, so it's self-gating.
    candidates.extend(
        generate_local_physical_interrupts(
            agent, agent.get("_local_physical"), current_activity=scheduled_activity,
        )
    )

    # --- 2. Social chain (co-location encounters) ---
    co_located = detect_co_located_agents(agent, all_agents, agents_by_id)
    social_candidates = generate_social_interrupts(agent, co_located, time_str)
    candidates.extend(social_candidates)

    # --- 3. Inbox / social-message triggers ---
    inbox_candidates = generate_inbox_interrupts(
        agent, social_context=social_context,
        inbox_messages=inbox_messages,
    )
    candidates.extend(inbox_candidates)

    # --- 4. Need-based interrupts ---
    need_candidates = generate_need_interrupts(agent, time_str)
    candidates.extend(need_candidates)

    # --- 5. Spontaneous urges ---
    spontaneous = generate_spontaneous_urge(
        agent, time_str=time_str, current_activity=scheduled_activity,
    )
    if spontaneous:
        candidates.append(spontaneous)

    # --- 6. Evaluate ---
    winner = evaluate_interrupts(candidates, scheduled_activity, agent)

    social_encounters = [
        c.to_dict() for c in social_candidates
        if c.extra.get("other_agent_id")
    ]
    # Also include inbox-triggered social encounters
    for ic in inbox_candidates:
        social_encounters.append(ic.to_dict())

    if winner is None:
        return {
            "activity": scheduled_activity,
            "changed": False,
            "reason": "",
            "interrupt": None,
            "social_encounters": social_encounters,
            "mood_delta": 0.0,
            "schedule_insert": None,
            "all_candidates": len(candidates),
            "cascade_events": cascade_events,
        }

    # Cumulative mood delta: winner's direct effect + any cascade mood
    mood_delta = winner.mood_delta
    for ce in cascade_events:
        mood_delta += ce.get("mood_delta", 0.0)

    # Build schedule insertion info
    schedule_insert = None
    if winner.resumable:
        schedule_insert = {
            "insert_time": time_str,
            "activity": winner.activity,
            "duration_minutes": winner.duration_minutes,
            "original_activity": scheduled_activity,
        }

    return {
        "activity": winner.activity,
        "changed": True,
        "reason": winner.reason,
        "interrupt": winner.to_dict(),
        "social_encounters": social_encounters,
        "mood_delta": mood_delta,
        "schedule_insert": schedule_insert,
        "all_candidates": len(candidates),
        "cascade_events": cascade_events,
    }


def _no_change_result(scheduled_activity: str) -> Dict[str, Any]:
    return {
        "activity": scheduled_activity,
        "changed": False,
        "reason": "",
        "interrupt": None,
        "social_encounters": [],
        "mood_delta": 0.0,
        "schedule_insert": None,
        "all_candidates": 0,
        "cascade_events": [],
    }


# =========================================================================
# 7. Bridge API — compatible with legacy maybe_generate_transient_thought
# =========================================================================

def dynamic_transient_thought(
    agent: Dict,
    time_str: str,
    scheduled_activity: str,
    perception_text: str = "",
    env_events: Optional[List[Dict]] = None,
    policy_desc: Optional[str] = None,
    social_context: str = "",
    inbox_messages: Optional[List] = None,
    all_agents: Optional[List[Dict]] = None,
    agents_by_id: Optional[Dict] = None,
    config: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Bridge function matching the old ``maybe_generate_transient_thought``
    return format while using the new dynamic behaviour engines internally.

    Returns a dict with keys compatible with the old format:
        source, kind, thought, activity_suggestion, reason, intensity,
        time, scheduled_activity, probability, perception_excerpt,
    plus the new ``dynamic_result`` key containing the full
    ``evaluate_step_dynamics`` output for downstream use.

    If the system decides nothing should change, returns ``{}``.
    """
    result = evaluate_step_dynamics(
        agent=agent,
        time_str=time_str,
        scheduled_activity=scheduled_activity,
        env_events=env_events or [],
        all_agents=all_agents or [],
        agents_by_id=agents_by_id or {},
        config=config,
        social_context=social_context,
        inbox_messages=inbox_messages,
    )

    if not result.get("changed"):
        # Even if not changed, there might be social encounters worth noting
        if result.get("social_encounters"):
            return {
                "source": "social",
                "kind": "social_awareness",
                "thought": "注意到了周围的人。",
                "activity_suggestion": "",
                "reason": "社交感知",
                "intensity": 0.1,
                "time": time_str,
                "scheduled_activity": scheduled_activity,
                "probability": 0.0,
                "perception_excerpt": "",
                "dynamic_result": result,
            }
        return {}

    interrupt = result.get("interrupt", {})
    return {
        "source": interrupt.get("source", "dynamic"),
        "kind": interrupt.get("kind", "dynamic_trigger"),
        "thought": result.get("reason", ""),
        "activity_suggestion": result.get("activity", ""),
        "reason": result.get("reason", ""),
        "intensity": _clip(interrupt.get("priority", 0.5)),
        "time": time_str,
        "scheduled_activity": scheduled_activity,
        "probability": 1.0,
        "perception_excerpt": str(perception_text)[:70] if perception_text else "",
        "dynamic_result": result,
    }
