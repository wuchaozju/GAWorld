"""Schedule, sleep and text-format helpers extracted from ``generative_city_sim.py``.

Scope of this module — the *pure / agent-dict-only* subset of the legacy
``# Schedule & Action`` banner:

* JSON-array extraction and schedule parsing
* Heuristic baseline schedules per profile archetype
* Schedule timing helpers (strictly-increasing check, anchor rounding,
  daily-planning start alignment)
* Sleep keyword detection and forced sleep insertion
* Workday signature heuristic
* Text compaction + plan/reflection format helpers
* Activity commitment-level classifier
* Action-style tag classifier
* Agent state-driven recall labels

Intentionally out of scope (stay in ``generative_city_sim.py`` until
their callees are also migrated):

* ``_parse_structured_json`` — depends on a ``_extract_json_block`` whose
  semantics differ slightly between ``generative_city_sim`` and
  ``human_realism``.
* ``_commitment_weight`` — reads the module-level ``HUMAN_REALISM_CONFIG``
  constant; will move with the broader CONFIG migration.
* ``_build_recall_context_labels`` — depends on ``human_realism.build_context_key``.
* External-RAG / memory-recall helpers — much larger flow.
"""

from __future__ import annotations

import json
import random
import re
from typing import Any

from gaworld.settings import CONFIG
from gaworld.sim._utils import _minutes_to_time_str, _time_str_to_minutes

# ---------------------------------------------------------------------------
# JSON-array extraction and schedule parsing.
# ---------------------------------------------------------------------------

def _extract_json_array_block(text: str) -> str:
    block_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    if block_match:
        return block_match.group(1)
    inline_match = re.search(r"\[.*\]", text, re.S)
    return inline_match.group(0) if inline_match else ""


def _extract_json_block(text: str) -> str:
    """Extract the first ``{...}`` JSON object from a possibly markdown-fenced string."""
    block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if block_match:
        return block_match.group(1)
    inline_match = re.search(r"\{.*\}", text, re.S)
    return inline_match.group(0) if inline_match else ""


#: Characters that can legally follow a JSON string's closing quote.
_JSON_STRING_DELIMITERS = ",]}:"


def repair_inner_quotes(blob: str) -> str:
    """Escape ASCII quotes that appear *inside* a JSON string value.

    The models write Chinese quoted speech with ASCII quotes --
    ``"同事提议一起下楼吃时以"来不及"为由拒绝"`` -- which closes the string
    early and makes the whole object unparseable. Measured on 848 real
    ``actions`` responses, this accounted for 36 of 354 parse failures (4.2%
    of all calls) with no truncation involved.

    In this grammar a string only ends when the next non-space character is one
    of ``, ] } :`` — so any other quote is content. That rule is what makes the
    repair safe rather than a guess, and it was checked rather than assumed:
    on the 494 responses that already parsed, the repaired text yields a
    byte-identical result, 494/494.
    """
    out: list[str] = []
    index = 0
    length = len(blob)
    in_string = False
    while index < length:
        char = blob[index]
        if not in_string:
            out.append(char)
            if char == '"':
                in_string = True
            index += 1
            continue
        if char == "\\" and index + 1 < length:
            out.append(blob[index:index + 2])
            index += 2
            continue
        if char == '"':
            probe = index + 1
            while probe < length and blob[probe] in " \t\r\n":
                probe += 1
            if probe < length and blob[probe] in _JSON_STRING_DELIMITERS:
                out.append(char)
                in_string = False
            else:
                out.append('\\"')
            index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def loads_tolerant(blob: str) -> Any:
    """``json.loads``, retried once on quote-repaired text. ``None`` on failure.

    Only ever reached on input ``json.loads`` has already rejected, so it
    cannot change the behaviour of any call that works today -- which is what
    makes it safe to put behind every parser rather than just the one whose
    failures were measured.
    """
    if not blob:
        return None
    try:
        return json.loads(blob)
    except (ValueError, TypeError):
        pass
    try:
        return json.loads(repair_inner_quotes(blob))
    except (ValueError, TypeError):
        return None


def _parse_schedule_change(text: str) -> dict[str, Any]:
    """Parse a routine-change JSON snippet returned by the LLM.

    Expected shape: ``{"change": bool|str, "activity": str, "reason": str}``.
    String values for ``change`` are coerced to bool by checking against
    a set of affirmative tokens — preserves the legacy gen_city_sim
    behaviour byte-for-byte.
    """
    json_blob = _extract_json_block(text)
    if not json_blob:
        return {}
    raw = loads_tolerant(json_blob)
    if not isinstance(raw, dict):
        return {}
    change = raw.get("change")
    if isinstance(change, str):
        change = change.strip().lower() in ("true", "yes", "y", "1", "是", "需要", "改变", "变更")
    change = bool(change)
    activity = str(raw.get("activity", "")).strip()
    reason = str(raw.get("reason", "")).strip()
    return {"change": change, "activity": activity, "reason": reason}


def _parse_schedule(text: str) -> list[tuple[str, str]]:
    json_blob = _extract_json_array_block(text)
    if not json_blob:
        return []
    raw = loads_tolerant(json_blob)
    if not isinstance(raw, list):
        return []
    schedule: list[tuple[str, str]] = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            time_str, activity = item
        elif isinstance(item, dict) and "time" in item and "activity" in item:
            time_str, activity = item["time"], item["activity"]
        else:
            continue
        time_str = str(time_str).strip()
        activity = str(activity).strip()
        if re.match(r"^\d{2}:\d{2}$", time_str) and activity:
            schedule.append((time_str, activity))
    if not schedule:
        return []
    seen: set[str] = set()
    cleaned: list[tuple[str, str]] = []
    for time_str, activity in schedule:
        if time_str in seen:
            continue
        seen.add(time_str)
        cleaned.append((time_str, activity))
    return cleaned


def _parse_interview(text: str, questions: list[str]) -> list[dict[str, str]]:
    """Parse the LLM's JSON interview response into a list of Q&A dicts.

    Accepts either ``[["question", "answer"], ...]`` or
    ``[{"question": "...", "answer": "..."}, ...]``. When a returned
    question is empty, falls back to the same-index input question.
    """
    json_blob = _extract_json_array_block(text)
    if not json_blob:
        return []
    raw = loads_tolerant(json_blob)
    if not isinstance(raw, list):
        return []
    parsed: list[dict[str, str]] = []
    for i, item in enumerate(raw):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            q, a = item
        elif isinstance(item, dict):
            q = item.get("question")
            a = item.get("answer")
        else:
            continue
        q = str(q).strip() if q else ""
        a = str(a).strip() if a else ""
        if not q:
            q = questions[i] if i < len(questions) else ""
        if q and a:
            parsed.append({"question": q, "answer": a})
    return parsed


# ---------------------------------------------------------------------------
# Heuristic baseline schedules per archetype.
# ---------------------------------------------------------------------------

def _heuristic_schedule(agent: dict[str, Any]) -> list[tuple[str, str]]:
    profile_blob = " ".join([
        agent.get("job", ""),
        agent.get("personality", ""),
        agent.get("daily_life", ""),
        agent.get("values", ""),
    ])

    is_student = any(k in profile_blob for k in ["学生", "硕士", "博士", "课题组"])
    is_retired = any(k in profile_blob for k in ["退休", "无业", "待业", "失业", "家庭主妇", "家庭主夫"])
    late_schedule = any(k in profile_blob for k in ["夜间活跃", "晚睡", "作息偏晚"])

    if is_retired:
        base = [
            ("07:30", "晨练"),
            ("08:30", "吃早饭"),
            ("10:00", "买菜"),
            ("11:30", "午饭"),
            ("13:00", "午休"),
            ("16:00", "散步"),
            ("18:00", "晚饭"),
            ("20:00", "个人时间"),
            ("22:30", "睡前"),
        ]
        return base

    if is_student:
        base = [
            ("09:30", "吃早饭"),
            ("10:00", "上午学习"),
            ("12:00", "午饭"),
            ("14:00", "下午学习"),
            ("18:00", "下课"),
            ("20:30", "个人时间"),
            ("00:30", "睡前"),
        ]
        return base

    if late_schedule:
        base = [
            ("09:30", "吃早饭"),
            ("10:30", "通勤"),
            ("11:00", "上午工作"),
            ("12:30", "午饭"),
            ("14:30", "下午工作"),
        ]
        base += [("19:30", "加班" if "加班" in agent["work_style"] else "下班")]
        base += [("22:00", "个人时间"), ("01:00", "睡前")]
        return base

    base = [
        ("08:00", "吃早饭"),
        ("09:00", "通勤"),
        ("10:00", "上午工作"),
        ("12:00", "午饭"),
        ("14:00", "下午工作"),
    ]
    base += [("18:30", "加班" if "加班" in agent["work_style"] else "下班")]
    base += [("21:00", "个人时间"), ("23:30", "睡前")]
    return base


def _schedule_profile_flags(agent: dict[str, Any]) -> tuple[bool, bool, bool, bool]:
    profile_blob = " ".join([
        agent.get("job", ""),
        agent.get("personality", ""),
        agent.get("daily_life", ""),
        agent.get("values", ""),
        agent.get("work_style", ""),
    ])
    is_student = any(k in profile_blob for k in ["学生", "硕士", "博士", "课题组", "上课", "学习"])
    is_retired = any(k in profile_blob for k in ["退休", "无业", "待业", "失业", "家庭主妇", "家庭主夫", "已退休"])
    late_schedule = any(k in profile_blob for k in ["夜间活跃", "晚睡", "作息偏晚"])
    overtime = "加班" in agent.get("work_style", "")
    return is_student, is_retired, late_schedule, overtime


# ---------------------------------------------------------------------------
# Sleep keyword detection and forced sleep insertion.
# ---------------------------------------------------------------------------

SLEEP_KEYWORDS = ["睡前", "睡觉", "睡眠", "入睡", "就寝"]


def is_sleep_activity(activity: str) -> bool:
    return any(k in activity for k in SLEEP_KEYWORDS)


def ensure_sleep_in_schedule(
    agent: dict[str, Any], schedule: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    if any(is_sleep_activity(activity) for _, activity in schedule):
        return schedule
    is_student, is_retired, late_schedule, _ = _schedule_profile_flags(agent)
    if is_retired:
        sleep_time = "22:30"
    elif is_student:
        sleep_time = "00:30"
    elif late_schedule:
        sleep_time = "01:00"
    else:
        sleep_time = "23:30"

    used_times = {t for t, _ in schedule}
    sleep_minutes = _time_str_to_minutes(sleep_time)
    if sleep_minutes is None:
        sleep_minutes = 23 * 60 + 30
    max_minutes = max(
        (_time_str_to_minutes(t) for t in used_times if _time_str_to_minutes(t) is not None),
        default=None,
    )
    if max_minutes is not None and max_minutes >= sleep_minutes:
        sleep_minutes = min(max_minutes + 60, 23 * 60 + 59)
    candidate = _minutes_to_time_str(sleep_minutes)
    if candidate in used_times:
        for _ in range(48):
            sleep_minutes = (sleep_minutes + 30) % (24 * 60)
            candidate = _minutes_to_time_str(sleep_minutes)
            if candidate not in used_times:
                break

    schedule = list(schedule) + [(candidate, "睡前")]
    schedule.sort(key=lambda x: _time_str_to_minutes(x[0]) or 0)
    return schedule


# ---------------------------------------------------------------------------
# Schedule timing helpers.
# ---------------------------------------------------------------------------

def _schedule_times(schedule: list[tuple[str, str]]) -> list[str]:
    return [t for t, _ in schedule]


def _is_strictly_increasing_times(schedule: list[tuple[str, str]]) -> bool:
    minutes: list[int] = []
    for t, _ in schedule:
        m = _time_str_to_minutes(t)
        if m is None:
            return False
        minutes.append(m)
    return all(a < b for a, b in zip(minutes, minutes[1:]))


def _round_to_anchor(minutes: int, anchor_step: int = 30) -> int:
    step = max(1, int(anchor_step))
    return int(round(minutes / step) * step)


# ---------------------------------------------------------------------------
# Same-day replanning (P3).
# ---------------------------------------------------------------------------

def replan_affected_interval(
    schedule: list[tuple[str, str]],
    start_time: str,
    end_time: str,
    *,
    is_affected,
    relocate=None,
    defer: bool = True,
    defer_gap_minutes: int = 30,
) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
    """Rebuild only the schedule slots disrupted within ``[start, end)``.

    Surgical by design — slots outside the affected window are untouched
    (contrast with regenerating the whole day). For each affected slot:

    * ``relocate`` (if given) swaps the activity in place — e.g. send the
      agent to an alternative venue while keeping the time;
    * otherwise, when ``defer`` is set, the activity is pushed to the
      first free slot at/after ``end_time`` (spaced by ``defer_gap_minutes``);
    * otherwise the slot is dropped.

    Returns ``(new_schedule, changes)`` where ``changes`` is a list of
    ``{"time","from","to","kind"}`` records describing what moved.
    """
    start_min = _time_str_to_minutes(start_time)
    end_min = _time_str_to_minutes(end_time)
    if not schedule or start_min is None or end_min is None or end_min <= start_min:
        return list(schedule or []), []

    gap = max(1, int(defer_gap_minutes))
    kept: list[tuple[str, str]] = []
    deferred: list[str] = []
    changes: list[dict[str, Any]] = []

    for t, act in schedule:
        tmin = _time_str_to_minutes(t)
        if tmin is None or not (start_min <= tmin < end_min) or not is_affected(t, act):
            kept.append((t, act))
            continue
        if relocate is not None:
            new_act = relocate(t, act)
            if new_act and new_act != act:
                kept.append((t, new_act))
                changes.append({"time": t, "from": act, "to": new_act, "kind": "relocate"})
            else:
                kept.append((t, act))
        elif defer:
            deferred.append(act)
            changes.append({"time": t, "from": act, "to": None, "kind": "defer"})
        else:
            changes.append({"time": t, "from": act, "to": None, "kind": "drop"})

    # Re-place deferred activities at the first free grid slots after the window.
    used = {m for m in (_time_str_to_minutes(t) for t, _ in kept) if m is not None}
    cursor = end_min
    for act in deferred:
        while cursor in used and cursor < 24 * 60:
            cursor += gap
        if cursor >= 24 * 60:
            # No room left in the day — drop and record it.
            changes.append({"time": end_time, "from": act, "to": None, "kind": "drop_no_room"})
            continue
        new_time = _minutes_to_time_str(cursor)
        kept.append((new_time, act))
        for c in changes:
            if c["kind"] == "defer" and c["from"] == act and c["to"] is None:
                c["to"] = new_time
                break
        used.add(cursor)
        cursor += gap

    kept.sort(key=lambda x: _time_str_to_minutes(x[0]) or 0)
    return kept, changes


# ---------------------------------------------------------------------------
# Life-event-driven same-day reshaping (Part B).
#
# The probabilistic routine-change gate (``maybe_adjust_activity``) is easily
# won by a high-commitment activity's resistance, so a serious life event —
# illness, a family emergency, being framed — could barely dent the day. These
# helpers let such an event *deterministically* bend the rest of the day around
# it: the current slot becomes the event's immediate response, and upcoming
# high/medium-commitment slots inside a window are swapped for a follow-on
# activity. Low-commitment slots (meals, rest, sleep) are left in place so the
# agent still eats and sleeps.
# ---------------------------------------------------------------------------

# Impact tags that make an event worth reshaping the day around. Positive or
# purely internal events (a promotion, a lottery win) are intentionally absent:
# they colour mood and actions via state effects, but don't pull you out of work.
LIFE_EVENT_ROUTINE_TAGS = frozenset({"routine", "health", "obligation", "family", "conflict"})

# (immediate response activity, follow-on activity for later high-commit slots),
# keyed by template_key first, then by impact tag.
_LIFE_EVENT_ACTIVITY_MAP = {
    "illness": ("就医处理", "在家休养"),
    "health": ("就医处理", "在家休养"),
    "family_emergency": ("处理家中急事", "陪伴家人"),
    "family": ("处理家中急事", "陪伴家人"),
    "framed": ("处理纠纷", "善后与澄清"),
    "conflict": ("处理纠纷", "善后处理"),
    "relationship_break": ("处理冲突情绪", "独自缓一缓"),
    # "求职投递" rather than "找工作": INCOME_KEYWORDS matches the substring
    # 工作, and a job hunt must not pay wages.
    "unemployment": ("办理离职交接", "求职投递"),
    "job_change": ("办理入职交接", "熟悉新工作"),
    "obligation": ("处理急事", "跟进后续"),
    "routine": ("临时处理要务", "跟进后续"),
}


def resolve_life_event_activities(event: dict[str, Any]) -> tuple[str, str]:
    """Pick ``(immediate, follow)`` activities for a routine-impacting event."""
    template = str((event or {}).get("template_key", "")).strip()
    if template in _LIFE_EVENT_ACTIVITY_MAP:
        return _LIFE_EVENT_ACTIVITY_MAP[template]
    for tag in (event or {}).get("impact_tags", []) or []:
        tag = str(tag).strip()
        if tag in _LIFE_EVENT_ACTIVITY_MAP:
            return _LIFE_EVENT_ACTIVITY_MAP[tag]
    return ("临时处理要务", "跟进后续")


def is_routine_impacting_event(
    event: dict[str, Any], tags: frozenset[str] = LIFE_EVENT_ROUTINE_TAGS
) -> bool:
    """True when the event carries a tag that warrants reshaping the day."""
    if not isinstance(event, dict):
        return False
    ev_tags = {str(t).strip() for t in (event.get("impact_tags") or [])}
    return bool(ev_tags & tags)


def reshape_day_for_life_event(
    schedule: list[tuple[str, str]],
    time_str: str,
    event: dict[str, Any],
    *,
    window_minutes: int = 240,
    immediate_activity: str | None = None,
    follow_activity: str | None = None,
) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
    """Deterministically bend the rest of the day around a serious life event.

    * the slot at ``time_str`` (or a fresh slot, if none lands there) becomes
      ``immediate_activity``;
    * within ``[time_str, time_str + window_minutes)``, high/medium-commitment
      activities are swapped for ``follow_activity``;
    * low-commitment slots (meals, rest) and sleep are left untouched.

    Returns ``(new_schedule, changes)``; an empty ``changes`` means nothing
    needed reshaping (caller should treat that as a no-op).
    """
    cur = _time_str_to_minutes(time_str)
    if cur is None or not event:
        return list(schedule or []), []
    if immediate_activity is None or follow_activity is None:
        _imm, _fol = resolve_life_event_activities(event)
        immediate_activity = immediate_activity or _imm
        follow_activity = follow_activity or _fol
    end = min(24 * 60 - 1, cur + max(1, int(window_minutes)))

    changes: list[dict[str, Any]] = []
    kept: list[tuple[str, str]] = []
    overrode_current = False
    for t, act in schedule or []:
        tmin = _time_str_to_minutes(t)
        if tmin is None:
            kept.append((t, act))
            continue
        if tmin == cur:
            if act != immediate_activity:
                changes.append({"time": t, "from": act, "to": immediate_activity, "kind": "override"})
            kept.append((t, immediate_activity))
            overrode_current = True
        elif (
            cur < tmin < end
            and not is_sleep_activity(act)
            and _activity_commitment_level(act) in ("high", "medium")
        ):
            changes.append({"time": t, "from": act, "to": follow_activity, "kind": "relocate"})
            kept.append((t, follow_activity))
        else:
            kept.append((t, act))

    if not overrode_current:
        kept.append((time_str, immediate_activity))
        changes.append({"time": time_str, "from": None, "to": immediate_activity, "kind": "insert"})

    kept = _dedupe_schedule_items(kept)
    kept.sort(key=lambda x: _time_str_to_minutes(x[0]) or 0)
    return kept, changes


def _align_daily_planning_start_time(
    schedule: list[tuple[str, str]],
    anchor_step: int = 30,
    max_delay: int = 10,
    min_gap: int = 20,
) -> list[tuple[str, str]]:
    if not schedule:
        return []
    minute_points = [_time_str_to_minutes(t) for t, _ in schedule]
    if any(m is None for m in minute_points):
        return list(schedule)

    start_idx = 0
    for idx, (_, activity) in enumerate(schedule):
        if not is_sleep_activity(activity):
            start_idx = idx
            break

    anchor = _round_to_anchor(minute_points[start_idx], anchor_step=anchor_step)
    target = min(23 * 60 + 59, anchor + random.randint(0, max(0, int(max_delay))))

    lower_bound = 0
    if start_idx > 0:
        lower_bound = minute_points[start_idx - 1] + max(1, int(min_gap))
    upper_bound = 23 * 60 + 59
    if start_idx + 1 < len(minute_points):
        upper_bound = minute_points[start_idx + 1] - max(1, int(min_gap))

    if upper_bound < lower_bound:
        return list(schedule)
    minute_points[start_idx] = max(lower_bound, min(target, upper_bound))
    return [(_minutes_to_time_str(m), act) for m, (_, act) in zip(minute_points, schedule)]


def _has_workday_signature(schedule: list[tuple[str, str]]) -> bool:
    if not schedule:
        return False
    keywords = ["通勤", "工作", "上班", "加班", "会议", "办公", "出差", "上课", "实验", "课题"]
    return any(any(k in str(activity) for k in keywords) for _, activity in schedule)


# ---------------------------------------------------------------------------
# Text compaction + plan/reflection formatting.
# ---------------------------------------------------------------------------

def _compact_text(text: Any, max_chars: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    clipped = cleaned[:max_chars]
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.rstrip("，,；;。.") + "..."


def _fallback_plan_struct(raw_text: str = "") -> dict[str, str]:
    text = _compact_text(raw_text, max_chars=80) or "先按当前情况稳住节奏。"
    return {
        "goal": "先把当前时段过稳",
        "constraint": "时间和状态都有限",
        "urge": "也想顺着当下感觉稍微省点力",
        "plan": text,
        "expected_outcome": "希望不把后面的安排弄得更乱",
    }


def _fallback_reflection_struct(raw_text: str = "") -> dict[str, str]:
    text = _compact_text(raw_text, max_chars=80) or "这一步暂时就这样。"
    return {
        "result": text,
        "feeling": "情绪有一点波动",
        "lesson": "下次还是要更早判断状态和代价",
        "next_bias": "接下来会更偏向省力或稳妥的做法",
    }


def format_plan_text(plan: Any) -> str:
    if not isinstance(plan, dict):
        return _compact_text(plan, max_chars=120)
    return "；".join(
        part
        for part in [
            f"目标：{plan.get('goal', '').strip()}".strip("："),
            f"顾虑：{plan.get('constraint', '').strip()}".strip("："),
            f"冲动：{plan.get('urge', '').strip()}".strip("："),
            f"打算：{plan.get('plan', '').strip()}".strip("："),
            f"预期：{plan.get('expected_outcome', '').strip()}".strip("："),
        ]
        if part and not part.endswith("：")
    )


def format_reflection_text(reflection: Any) -> str:
    if not isinstance(reflection, dict):
        return _compact_text(reflection, max_chars=120)
    return "；".join(
        part
        for part in [
            f"结果：{reflection.get('result', '').strip()}".strip("："),
            f"感受：{reflection.get('feeling', '').strip()}".strip("："),
            f"教训：{reflection.get('lesson', '').strip()}".strip("："),
            f"后续倾向：{reflection.get('next_bias', '').strip()}".strip("："),
        ]
        if part and not part.endswith("：")
    )


# ---------------------------------------------------------------------------
# Activity commitment-level and action-style tag classifiers.
# ---------------------------------------------------------------------------

def _activity_commitment_level(activity: Any) -> str:
    text = str(activity or "")
    if any(k in text for k in ["工作", "上班", "会议", "开会", "上课", "学习", "实验", "看病", "医院", "诊所", "面试", "报告"]):
        return "high"
    if any(k in text for k in ["购物", "买菜", "社交", "聚会", "拜访", "办事", "沟通", "会面", "约见", "联系"]):
        return "medium"
    return "low"


def _action_style_tags(action_text: Any) -> set[str]:
    text = str(action_text or "")
    tags: set[str] = set()
    if any(k in text for k in ["推进", "完成", "整理", "处理", "准备", "学习", "规划", "落实", "回复", "确认"]):
        tags.add("progress")
    if any(k in text for k in ["继续", "维持", "例行", "按原计划", "照常", "看看进度", "简单处理"]):
        tags.add("maintain")
    if any(k in text for k in ["拖延", "刷手机", "摸鱼", "发呆", "放空", "晚点再说", "逃避", "躺平"]):
        tags.add("avoidant")
    if any(k in text for k in ["聊天", "联系", "沟通", "拜访", "会面", "回消息", "确认安排", "聚会"]):
        tags.add("social")
    if any(k in text for k in ["休息", "放松", "回家", "睡", "午休", "吃饭", "散步"]):
        tags.add("restorative")
    if any(k in text for k in ["先", "立刻", "马上", "顺手", "简单", "快速"]):
        tags.add("quick")
    return tags


# ---------------------------------------------------------------------------
# Agent state-driven recall labels.
# ---------------------------------------------------------------------------

def _state_recall_labels(agent: Any) -> list[str]:
    state = agent.get("state", {}) if isinstance(agent, dict) else {}
    labels: list[str] = []
    if float(state.get("self_control", 0.6)) < 0.4:
        labels.append("low_self_control")
    if float(state.get("fatigue_debt", 0.2)) > 0.6:
        labels.append("high_fatigue")
    if float(state.get("time_pressure", 0.25)) > 0.6:
        labels.append("high_time_pressure")
    if float(state.get("hunger", 0.25)) > 0.65:
        labels.append("high_hunger")
    if float(state.get("energy", 0.75)) < 0.35:
        labels.append("low_energy")
    return labels


# ---------------------------------------------------------------------------
# Schedule normalisation helpers (six pure functions, extracted in 1j).
#
# ``normalize_flexible_schedule`` reads six ``DAILY_PLAN_*`` knobs that
# previously lived as module-level snapshots of ``CONFIG["daily_planning"]
# ["flexible"]`` in ``generative_city_sim.py``.  We read those at *call*
# time instead — module-load snapshots are fragile (test fixtures replace
# CONFIG sections wholesale, leaving snapshots pointing at the old dict;
# see the S3 ``_bootstrap_agent_external_rag`` perf-fix story).
# ---------------------------------------------------------------------------

def _daily_plan_flex_config() -> dict[str, Any]:
    return CONFIG.get("daily_planning", {}).get("flexible", {}) or {}


def _jitter_schedule_times(
    base_schedule: list[tuple[str, str]],
    max_shift: int = 45,
    min_gap: int = 20,
) -> list[tuple[str, str]]:
    if not base_schedule:
        return []
    base_minutes = [_time_str_to_minutes(t) for t, _ in base_schedule]
    if any(m is None for m in base_minutes):
        return list(base_schedule)
    adjusted_minutes: list[int] = []
    prev = None
    for m in base_minutes:
        shift = random.randint(-max_shift, max_shift)
        target = m + shift
        if prev is None:
            target = max(0, target)
        else:
            target = max(prev + min_gap, target)
        target = min(target, 23 * 60 + 59)
        adjusted_minutes.append(target)
        prev = target
    adjusted = [(_minutes_to_time_str(m), act) for m, (_, act) in zip(adjusted_minutes, base_schedule)]
    return adjusted


def normalize_schedule_to_base(
    base_schedule: list[tuple[str, str]],
    candidate_schedule: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    if not base_schedule:
        return candidate_schedule
    if not candidate_schedule:
        return base_schedule
    candidate_by_time = {t: a for t, a in candidate_schedule}
    normalized: list[tuple[str, str]] = []
    for t, base_act in base_schedule:
        act = candidate_by_time.get(t, base_act)
        normalized.append((t, act))
    return normalized


def _dedupe_schedule_items(schedule: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen_times: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    cleaned: list[tuple[str, str]] = []
    for time_str, activity in schedule or []:
        time_str = str(time_str).strip()
        activity = str(activity).strip()
        if not activity or _time_str_to_minutes(time_str) is None:
            continue
        pair = (time_str, activity)
        if time_str in seen_times or pair in seen_pairs:
            continue
        seen_times.add(time_str)
        seen_pairs.add(pair)
        cleaned.append(pair)
    return cleaned


def _enforce_schedule_min_gap(
    schedule: list[tuple[str, str]], min_gap: int = 15
) -> list[tuple[str, str]]:
    if not schedule:
        return []
    sorted_schedule = sorted(schedule, key=lambda x: _time_str_to_minutes(x[0]) or 0)
    kept: list[tuple[str, str]] = []
    prev_minutes: int | None = None
    for time_str, activity in sorted_schedule:
        minutes = _time_str_to_minutes(time_str)
        if minutes is None:
            continue
        if prev_minutes is not None and minutes - prev_minutes < max(1, int(min_gap)):
            continue
        kept.append((time_str, activity))
        prev_minutes = minutes
    return kept


def _has_enough_schedule_anchors(
    base_schedule: list[tuple[str, str]],
    candidate_schedule: list[tuple[str, str]],
    max_shift_minutes: int,
    min_ratio: float = 0.45,
) -> bool:
    if not base_schedule or not candidate_schedule:
        return False
    if max_shift_minutes <= 0:
        return True
    base_minutes = [
        _time_str_to_minutes(t)
        for t, activity in base_schedule
        if _time_str_to_minutes(t) is not None and not is_sleep_activity(activity)
    ]
    candidate_minutes = [
        _time_str_to_minutes(t)
        for t, _ in candidate_schedule
        if _time_str_to_minutes(t) is not None
    ]
    if not base_minutes or not candidate_minutes:
        return True
    close_count = 0
    for base_minute in base_minutes:
        if any(abs(candidate_minute - base_minute) <= max_shift_minutes for candidate_minute in candidate_minutes):
            close_count += 1
    ratio = max(0.0, min(1.0, float(min_ratio)))
    required = min(len(base_minutes), max(2, int(round(len(base_minutes) * ratio))))
    return close_count >= required


def normalize_flexible_schedule(
    base_schedule: list[tuple[str, str]],
    candidate_schedule: list[tuple[str, str]],
) -> list[tuple[str, str]] | None:
    if not candidate_schedule or not base_schedule:
        return None
    cleaned = _dedupe_schedule_items(candidate_schedule)
    if not cleaned:
        return None

    # Runtime CONFIG lookup — see ``_daily_plan_flex_config`` docstring above
    # for why this is *not* a module-level snapshot.
    flex_cfg = _daily_plan_flex_config()
    flex_enabled = bool(flex_cfg.get("enabled", True))
    min_items = max(3, int(flex_cfg.get("min_items", 6)))
    max_items = max(min_items, int(flex_cfg.get("max_items", 12)))
    max_shift_minutes = max(0, int(flex_cfg.get("max_time_shift_minutes", 120)))
    min_gap_minutes = max(1, int(flex_cfg.get("min_gap_minutes", 15)))
    allow_insertions = bool(flex_cfg.get("allow_insertions", True))
    min_anchor_match = float(flex_cfg.get("min_anchor_match", 0.45))

    if not flex_enabled:
        if len(cleaned) != len(base_schedule):
            return None
        sorted_candidate = sorted(cleaned, key=lambda x: _time_str_to_minutes(x[0]) or 0)
        if not _is_strictly_increasing_times(sorted_candidate):
            return None
        return sorted_candidate

    cleaned = _enforce_schedule_min_gap(cleaned, min_gap=min_gap_minutes)
    if not _is_strictly_increasing_times(cleaned):
        return None
    if not allow_insertions and len(cleaned) != len(base_schedule):
        return None
    if len(cleaned) < min_items or len(cleaned) > max_items:
        return None
    if not _has_enough_schedule_anchors(
        base_schedule,
        cleaned,
        max_shift_minutes=max_shift_minutes,
        min_ratio=min_anchor_match,
    ):
        return None
    return cleaned


__all__ = [
    "SLEEP_KEYWORDS",
    "_action_style_tags",
    "_activity_commitment_level",
    "_align_daily_planning_start_time",
    "_compact_text",
    "_dedupe_schedule_items",
    "_enforce_schedule_min_gap",
    "_extract_json_array_block",
    "_extract_json_block",
    "loads_tolerant",
    "repair_inner_quotes",
    "_fallback_plan_struct",
    "_fallback_reflection_struct",
    "_has_enough_schedule_anchors",
    "_has_workday_signature",
    "_heuristic_schedule",
    "_is_strictly_increasing_times",
    "_jitter_schedule_times",
    "_parse_interview",
    "_parse_schedule",
    "_parse_schedule_change",
    "_round_to_anchor",
    "_schedule_profile_flags",
    "_schedule_times",
    "_state_recall_labels",
    "LIFE_EVENT_ROUTINE_TAGS",
    "resolve_life_event_activities",
    "is_routine_impacting_event",
    "reshape_day_for_life_event",
    "ensure_sleep_in_schedule",
    "format_plan_text",
    "format_reflection_text",
    "is_sleep_activity",
    "normalize_flexible_schedule",
    "normalize_schedule_to_base",
]
