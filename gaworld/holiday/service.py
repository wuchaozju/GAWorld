"""Pure holiday logic — no plugin, no LLM, no IO.

Everything here is deterministic and testable in isolation:

- :class:`HolidayState` — small struct carried on ``agent["_holiday"]`` that
  records which agents are on holiday, from which sim day, for how long,
  and with which themed plan slots ("freedom bank": 旅行 / 宅家 / 学习 /
  社交 / 健身, each represented by a band of hours).
- :func:`start_holiday` / :func:`end_holiday` / :func:`cancel_holiday` —
  transitions over that state, including a guard so a K-day window is
  never silently re-armed while the old one is still running.
- :func:`pick_replacement_activity` — given an agent, the sim time, and
  the per-day freedom bank, choose one new activity for this time slot
  that does *not* collide with the underlying routine entry but still
  respects sleep hours (sleep is sacred even on holiday).
- :func:`format_holiday_plan_block` — wraps the chosen plan as a short
  prompt snippet the existing plan stage can append without disrupting
  its budget.
- :func:`holiday_status_for_agent` / :func:`holiday_overall_status` —
  the read side; the dashboard polls this through ``/api/interventions``.

The plugin layer (``gaworld.holiday.plugin``) is the only thing that
imports this module via the kernel surface; the controller routes
``start_holiday`` / ``end_holiday`` / ``cancel_holiday`` here.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Freedom bank: a small, opinionated set of life activities the user can
# approve without LLM input. Each entry is keyed on Chinese so the prompt
# snippet reads naturally in the simulator's target language, and each
# carries a short explanation so the planner can pass the reason through
# to the action space the rest of the stage is searching against.
# ---------------------------------------------------------------------------
FREEDOM_BANK = (
    {
        "key": "travel",
        "label": "短途出游",
        "reason": "出门看看风景，换一个节奏过日子",
        # Bands in HH (integer hour). ``pick_replacement_activity`` matches
        # ``start <= hour <= end`` so an 8:30 tick still lands in (7, 10).
        "bands": ((7, 10), (14, 17)),
    },
    {
        "key": "indoor_rest",
        "label": "宅家充电",
        "reason": "把平时没空做的几件事集中做完",
        "bands": ((9, 12), (20, 23)),
    },
    {
        "key": "study",
        "label": "自学新东西",
        "reason": "挑一门一直想学的技能认真投入一段时间",
        "bands": ((10, 12), (15, 17)),
    },
    {
        "key": "social",
        "label": "社交聚会",
        "reason": "去见几个平时没空见的朋友",
        "bands": ((18, 22),),
    },
    {
        "key": "exercise",
        "label": "运动健身",
        "reason": "出门跑步、骑车或去健身房",
        "bands": ((6, 8), (17, 19)),
    },
    {
        "key": "errands",
        "label": "办事逛街",
        "reason": "把积压的小事一次性处理掉",
        "bands": ((11, 13), (16, 18)),
    },
    {
        "key": "creative",
        "label": "创作动手",
        "reason": "画画、写作、做手工",
        "bands": ((13, 17), (21, 23)),
    },
)


# Sleep windows are universal regardless of routine. Even on holiday a
# sensible agent won't choose a "spontaneous outing" at 02:00 — we force
# sleep into the activity replacement during the protected band. The
# numbers are inclusive of the integer minutes, matching how the
# schedule_map stores HH:MM strings.
SLEEP_WINDOW = (0, 6 * 60)  # 00:00 .. 06:00
LATE_SLEEP_WINDOW = (23 * 60, 24 * 60 - 1)  # 23:00 .. 23:59
# Meals matter too — a well-fed agent doesn't decompose, and the
# loop-most-of-the-day bench notes that skipped meals cascade into ill
# state, so the freedom bank keeps obvious gaps around them.
MEAL_WINDOWS = (
    (7 * 60, 9 * 60),    # breakfast band
    (11 * 60, 13 * 60),  # lunch band
    (17 * 60, 19 * 60),  # dinner band
)


@dataclass
class HolidayState:
    """Per-agent holiday window.

    The same shape lives under ``agent["_holiday"]`` while a holiday is
    active. ``current_plan_key`` lets the per-day ``rng`` seed across
    days so an agent's day-2 plan differs from day-1 even with the
    same agent personality.
    """

    started_day: int
    days: int
    plan_key: str
    day_rng: random.Random = field(default_factory=random.Random)
    daily_log: list[str] = field(default_factory=list)

    @property
    def ends_day(self) -> int:
        return self.started_day + self.days - 1

    def covers(self, day: int) -> bool:
        return self.started_day <= day <= self.ends_day

    def remaining(self, day: int) -> int:
        return max(0, self.ends_day - day + 1)


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def start_holiday(agents, *, day, days, plan_key=None, seed=None):
    """Arm a holiday window across ``agents`` starting on ``day``.

    ``agents`` is the list of dicts the simulator hands in; we mutate
    each one in place by writing ``agent["_holiday"]``. We refuse to
    re-arm a still-active window, because stacking two windows would
    reset ``ends_day`` mid-run — that has been a silent bug in earlier
    prototypes. ``seed`` is forwarded to the per-agent RNG so the
    daily plan is reproducible across runs of the same seed.
    """
    days = max(1, int(days))
    out = []
    blocked = []
    for agent in agents or []:
        if not isinstance(agent, dict):
            continue
        existing = agent.get("_holiday")
        if isinstance(existing, dict) and existing.get("ends_day", -1) >= day:
            blocked.append(int(agent.get("id", -1)))
            continue
        rng = random.Random()
        if seed is not None:
            rng.seed(int(seed) + int(agent.get("id", 0)))
        chosen_key = plan_key or _pick_plan_key(rng)
        state = HolidayState(
            started_day=int(day),
            days=days,
            plan_key=chosen_key,
            day_rng=rng,
        )
        agent["_holiday"] = {
            "started_day": state.started_day,
            "ends_day": state.ends_day,
            "days": days,
            "plan_key": chosen_key,
            "daily_log": state.daily_log,
        }
        out.append(int(agent.get("id", -1)))
    return {"armed": out, "blocked": blocked, "day": int(day), "days": days}


def end_holiday(agents, *, day):
    """End any holiday window covering ``day`` immediately.

    Used both by the natural expiry ("放假最后一天") and by the
    dashboard's explicit "提前收假" intervention.
    """
    ended = []
    for agent in agents or []:
        if not isinstance(agent, dict):
            continue
        existing = agent.get("_holiday")
        if not isinstance(existing, dict):
            continue
        if existing.get("ends_day", -1) < day:
            continue
        existing["ends_day"] = int(day) - 1
        if existing["ends_day"] < existing["started_day"]:
            agent.pop("_holiday", None)
        ended.append(int(agent.get("id", -1)))
    return {"ended": ended, "day": int(day)}


def cancel_holiday(agents):
    """Cancel every active holiday window (no expiry floor)."""
    cancelled = []
    for agent in agents or []:
        if isinstance(agent, dict) and isinstance(agent.get("_holiday"), dict):
            agent.pop("_holiday", None)
            cancelled.append(int(agent.get("id", -1)))
    return {"cancelled": cancelled}


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def holiday_overall_status(agents, *, day):
    """Compact dict for the dashboard's holiday status panel."""
    active = 0
    remaining_total = 0
    plans = {}
    for agent in agents or []:
        state = agent.get("_holiday") if isinstance(agent, dict) else None
        if not isinstance(state, dict):
            continue
        if not (state.get("started_day", 1) <= int(day) <= state.get("ends_day", 0)):
            continue
        active += 1
        remaining_total += max(0, int(state.get("ends_day", 0)) - int(day) + 1)
        key = str(state.get("plan_key") or "default")
        plans[key] = plans.get(key, 0) + 1
    return {
        "day": int(day),
        "active_agents": active,
        "remaining_agent_days": remaining_total,
        "plans": plans,
    }


def holiday_status_for_agent(agent, *, day):
    state = agent.get("_holiday") if isinstance(agent, dict) else None
    if not isinstance(state, dict):
        return None
    if not (state.get("started_day", 1) <= int(day) <= state.get("ends_day", 0)):
        return None
    return {
        "started_day": int(state["started_day"]),
        "ends_day": int(state["ends_day"]),
        "days": int(state["days"]),
        "remaining_days": max(0, int(state["ends_day"]) - int(day) + 1),
        "plan_key": str(state.get("plan_key") or "default"),
    }


# ---------------------------------------------------------------------------
# Per-time-slot activity replacement
# ---------------------------------------------------------------------------


def _pick_plan_key(rng):
    choices = [entry["key"] for entry in FREEDOM_BANK]
    return rng.choice(choices)


def _parse_hhmm(text):
    """Parse 'HH:MM' or 'H:MM' to integer minutes since midnight.

    Returns ``None`` when the input doesn't parse, so callers can
    fallback to a sensible default. Sleeping and ``is_sleep_activity``
    rely on this — the simulator normally hands us 'HH:MM' but a busy
    override path might drop the leading zero.
    """
    text = str(text or "").strip()
    if not text or ":" not in text:
        return None
    head, _, tail = text.partition(":")
    try:
        h = int(head)
        m = int(tail)
    except ValueError:
        return None
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    return h * 60 + m


def _is_protected_minute(minute):
    """Return ``True`` if the agent should still sleep / eat on holiday."""
    if minute is None:
        return False
    if SLEEP_WINDOW[0] <= minute <= SLEEP_WINDOW[1]:
        return True
    if LATE_SLEEP_WINDOW[0] <= minute <= LATE_SLEEP_WINDOW[1]:
        return True
    for start, end in MEAL_WINDOWS:
        if start <= minute <= end:
            return True
    return False


def _activity_in_minutes_range(activity, band_minutes):
    """``True`` if the band's start/end covers the agent's sleep-ish minute."""
    start, end = band_minutes
    return start <= end and start <= band_minutes and band_minutes <= end


# A handful of strings the simulator already treats as "sleep" — the
# dynamic-behaviour / life-events pipelines share these; matching them
# here means a holiday never overrides an "在睡觉" slot, just substitutes
# during waking hours even if the routine table mislabels a slot.
SLEEP_ACTIVITY_KEYWORDS = (
    "睡觉",
    "休息",
    "睡眠",
    "床上",
    "午睡",
    "小憩",
    "sleep",
    "rest",
)


def _is_sleep_activity(activity):
    text = str(activity or "").lower()
    return any(key in text for key in SLEEP_ACTIVITY_KEYWORDS)


def pick_replacement_activity(agent, *, time_str, original_activity, rng=None):
    """Choose one new activity for this tick.

    Rules — in order — applied to the time-of-day:

    1. Inside the protected meal/sleep band, the original activity
       wins. Holiday does not turn a sensible sleep schedule into an
       impromptu hike.
    2. If the original activity is itself a sleep keyword, leave it.
    3. Otherwise pick a freedom-bank entry whose band covers this
       minute and whose ``label`` does not collide with the original
       activity's wording (a routine of "在公园散步" shouldn't be
       replaced with another "户外散步"-shape label).
    4. Fall back to the agent's ``job`` / ``daily_life`` if everything
       above fails — a graceful degradation instead of a generic
       placeholder.
    """
    rng = rng or random
    minute = _parse_hhmm(time_str)
    if minute is None:
        return None
    if _is_protected_minute(minute):
        return None
    if _is_sleep_activity(original_activity):
        return None

    state = agent.get("_holiday") if isinstance(agent, dict) else None
    plan_key = state.get("plan_key") if isinstance(state, dict) else None
    primary = _bank_entry(plan_key)
    candidates = [primary] if primary else []
    candidates.extend(
        entry for entry in FREEDOM_BANK if entry["key"] != (plan_key or "")
    )
    hour = minute // 60
    for entry in candidates:
        for start, end in entry["bands"]:
            if start <= hour <= end:
                # Skip a candidate whose label collides with the routine
                if str(original_activity or "") and _collides(
                    str(original_activity), entry["label"]
                ):
                    continue
                return _wrap_reason(entry["label"], entry["reason"], plan_key)

    # Graceful fallback: weave the agent's own daily_life snippet so
    # the action space still gets a meaningful, persona-shaped label.
    fallback = (
        agent.get("daily_life") if isinstance(agent, dict) else None
    ) or (
        agent.get("hobby") if isinstance(agent, dict) else None
    )
    if fallback:
        snippet = _first_phrase(fallback)
        if snippet:
            return _wrap_reason(snippet, "挑一件平时没时间做的事", plan_key)
    return None


def _bank_entry(plan_key):
    if not plan_key:
        return None
    for entry in FREEDOM_BANK:
        if entry["key"] == plan_key:
            return entry
    return None


def _collides(original, candidate_label):
    """Treat two activities as a collision only on direct label overlap.

    "在公园散步" vs "出门看看风景" is fine; "在公园散步" vs "散步" is
    not. We tokenize on common Chinese connectors and compare the
    intersection.
    """
    if not original or not candidate_label:
        return False
    a = _tokenize_activity(original)
    b = _tokenize_activity(candidate_label)
    if not a or not b:
        return False
    return len(a & b) >= max(1, min(len(a), len(b)) // 2)


def _tokenize_activity(text):
    cleaned = "".join(ch if "\u4e00" <= ch <= "\u9fff" else " " for ch in str(text).lower())
    parts = [tok for tok in cleaned.split() if len(tok) >= 2]
    return set(parts)


def _first_phrase(text):
    cleaned = re.sub(r"[，。,.\n；;]+", " ", str(text)).strip()
    if not cleaned:
        return ""
    head = cleaned.split(maxsplit=1)[0]
    if len(head) > 12:
        head = head[:12]
    return head.replace("的", "").strip() or cleaned[:8]


def _wrap_reason(label, reason, plan_key):
    return {
        "activity": label,
        "reason": reason,
        "plan_key": plan_key or "default",
    }


def format_holiday_plan_block(replacement, *, plan_key=None, budget_chars=240):
    """Build a short prompt snippet the planner stage can append.

    The trailing wrapper question — the user-visible promise that
    holiday mode means "做全新的、自由的安排" — is preserved even when
    the body must be truncated to fit ``budget_chars``. Without this
    guarantee, the LLM receives a request to "abandon the routine"
    that gets silently mangled into an ordinary re-plan prompt.
    """
    if not isinstance(replacement, dict) or not replacement.get("activity"):
        return ""
    activity = str(replacement["activity"]).strip()
    reason = str(replacement.get("reason") or "").strip()
    wrapper = "请放弃原定 routine，做一个全新的、自由的安排。"
    head = f"[放假模式·{plan_key or replacement.get('plan_key') or 'free'}] 今天不按原计划，跳出 routine 来安排：{activity}"
    if reason:
        head = f"{head}（{reason}）"
    body = f"{head}。{wrapper}"
    if len(body) <= budget_chars:
        return body
    # Truncate the head, but never the wrapper — without the wrapper the
    # LLM cannot tell whether the request comes from holiday mode.
    available = max(20, budget_chars - len(wrapper) - 2)  # 2 = "。" + "…"
    short_head = head[:available].rstrip() + "…"
    return f"{short_head}。{wrapper}"


def summarize_replacement_log(replacement):
    """One-line summary to append to the agent's daily log."""
    if not isinstance(replacement, dict):
        return ""
    activity = str(replacement.get("activity") or "").strip()
    reason = str(replacement.get("reason") or "").strip()
    if not activity:
        return ""
    if reason:
        return f"[放假] {activity}（{reason}）"
    return f"[放假] {activity}"


__all__ = [
    "FREEDOM_BANK",
    "SLEEP_ACTIVITY_KEYWORDS",
    "HolidayState",
    "start_holiday",
    "end_holiday",
    "cancel_holiday",
    "holiday_overall_status",
    "holiday_status_for_agent",
    "pick_replacement_activity",
    "format_holiday_plan_block",
    "summarize_replacement_log",
    "Any",
    "Iterable",
]
