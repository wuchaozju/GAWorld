"""Time-of-day plausibility for resident activities and actions.

Residents used to do things that made no sense at the hour: a work wrap-up at
06:00, a work lunch at 08:30, a mid-day errand at 03:00. The prompts already
carry the current time, but a prompt is a suggestion — the model still writes
whatever the sentence asks for, and the action space of an activity is
generated once and reused for the whole day.

This module is the deterministic half of the fix: a small table of *when a
thing plausibly happens*, used in three places.

* :func:`activity_time_fit` — does this activity belong to this hour?
* :func:`action_time_fit` — does this action belong to this hour?
* :func:`repair_schedule` — move a schedule item whose hour does not fit.

The randomness the user asked for is not removed, it is *bounded*: an
implausible action is heavily de-weighted rather than deleted, so it can still
happen occasionally, while a plausible one (a jog at dawn, a slow walk at
lunch) is untouched. Verdict vocabulary:

``ok``
    Inside the core window. Nothing happens.
``soft``
    Just outside the core window, inside the gray zone. Allowed, slightly
    de-weighted.
``bad``
    Outside the gray zone. Implausible: de-weighted hard, or refused.
``unknown``
    No rule matched — free text we cannot judge. Always allowed, because
    refusing what we do not understand would delete most real behaviour.

The table is deliberately coarse. It encodes "a 03:00 office wrap-up is odd",
not "a 09:40 office wrap-up is fine".
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from gaworld.settings import CONFIG
from gaworld.sim._utils import _minutes_to_time_str, _time_str_to_minutes

#: Verdict vocabulary — see the module docstring.
OK = "ok"
SOFT = "soft"
BAD = "bad"
UNKNOWN = "unknown"

#: ``(label, start, end)`` in minutes from midnight.
DAY_PARTS: tuple[tuple[str, int, int], ...] = (
    ("深夜", 0, 300),
    ("清晨", 300, 420),
    ("早晨", 420, 540),
    ("上午", 540, 690),
    ("中午", 690, 810),
    ("下午", 810, 1020),
    ("傍晚", 1020, 1110),
    ("夜间", 1110, 1290),
    ("深夜", 1290, 1440),
)


@dataclass(frozen=True)
class TimeRule:
    """One plausibility rule.

    ``windows`` are ``(start, end)`` minute ranges; an empty range is never
    used, and a window never wraps midnight (sleep uses two windows instead).
    ``soft`` is the width of the gray zone on each side of the core window.
    ``exclude`` cancels the rule when one of its phrases shows up — "跑流程"
    is a work phrase that shares the character with a run.
    """

    label: str
    keywords: tuple[str, ...]
    windows: tuple[tuple[int, int], ...]
    soft: int = 45
    exclude: tuple[str, ...] = ()


def _h(hour: int, minute: int = 0) -> int:
    return hour * 60 + minute


#: Phrases that cancel the bare "跑" catch-all: "跑一遍数据" is work, "跑两
#: 公里" is a run. The specific rules (晨跑 / 夜跑 / 跑步) still apply.
_RUN_EXCLUSIONS: tuple[str, ...] = (
    "跑流程",
    "跑业务",
    "跑数据",
    "跑测试",
    "跑通",
    "跑腿",
    "跑赢",
    "跑量",
    "工作",
    "数据",
    "业务",
    "流程",
    "任务",
    "报表",
    "程序",
    "代码",
    "测试",
    "脚本",
    "系统",
    "订单",
    "项目",
    "客户",
    "上线",
    "部署",
)


# ---------------------------------------------------------------------------
# The tables.
#
# Order matters only for ties (two keywords of the same length matching the
# same text): the earlier rule wins. The more specific keyword always wins on
# length — "工作餐" (lunch) beats "工作" (work), "夜跑" beats "跑".
# ---------------------------------------------------------------------------

ACTIVITY_RULES: tuple[TimeRule, ...] = (
    TimeRule(
        "夜间睡眠",
        ("睡觉", "睡眠", "入睡", "就寝", "睡前", "上床", "睡下"),
        ((_h(21, 30), _h(24)), (_h(0), _h(5))),
        60,
    ),
    TimeRule("午睡", ("午睡", "午休", "小憩", "打盹", "眯一会"), ((_h(11, 30), _h(16)),), 60),
    TimeRule("早饭", ("早饭", "早餐", "吃早饭", "吃早餐"), ((_h(5), _h(10)),), 45),
    TimeRule(
        "午饭", ("工作餐", "午饭", "午餐", "中饭", "吃午饭", "食堂", "盒饭"), ((_h(10, 30), _h(14, 30)),), 90
    ),
    TimeRule("晚饭", ("晚饭", "晚餐", "吃晚饭"), ((_h(16, 30), _h(21)),), 75),
    TimeRule("夜宵", ("夜宵", "宵夜"), ((_h(21, 30), _h(24)), (_h(0), _h(4))), 45),
    TimeRule(
        "通勤",
        ("通勤", "赶车", "地铁", "公交", "打车", "开车", "在路上"),
        ((_h(5, 30), _h(10, 30)), (_h(16), _h(20, 30))),
        45,
    ),
    TimeRule("收工", ("收尾", "收工", "下班", "打烊", "散会"), ((_h(17), _h(23)),), 60),
    TimeRule("夜班工作", ("夜班", "值夜班", "通宵", "大夜"), ((_h(19), _h(24)), (_h(0), _h(7))), 60),
    TimeRule("加班", ("加班", "通宵加班"), ((_h(17), _h(22, 30)),), 45),
    TimeRule(
        "工作",
        ("工作", "上班", "开会", "会议", "办公", "值班", "面试", "培训", "汇报", "写材料", "处理文件"),
        ((_h(7, 30), _h(19)),),
        60,
        ("工作餐",),
    ),
    TimeRule("学习", ("上课", "学习", "自习", "实验", "课题", "论文", "写作业"), ((_h(7), _h(21, 30)),), 60),
    TimeRule("晨练", ("晨练", "晨跑", "早锻炼", "晨运"), ((_h(5), _h(10)),), 60),
    TimeRule(
        "运动",
        ("跑步", "锻炼", "健身", "运动", "散步", "遛弯", "瑜伽", "骑车", "游泳"),
        ((_h(5), _h(21, 30)),),
        45,
    ),
    TimeRule("运动", ("跑",), ((_h(5), _h(21, 30)),), 45, _RUN_EXCLUSIONS),
    TimeRule("购物", ("买菜", "购物", "逛街", "超市", "商场", "采购"), ((_h(7), _h(22)),), 45),
    TimeRule(
        "家务", ("打扫", "收拾", "家务", "洗衣", "做饭", "整理房间", "洗漱", "洗澡"), ((_h(5), _h(23)),), 45
    ),
    TimeRule("育儿", ("接送", "接孩子", "幼儿园", "家长会", "陪孩子", "辅导孩子"), ((_h(7), _h(20)),), 45),
    TimeRule("社交", ("聚会", "会面", "拜访", "约见", "聚餐", "喝茶", "咖啡"), ((_h(7), _h(22)),), 60),
    TimeRule(
        "办事",
        ("办事", "缴费", "取快递", "看医生", "看病", "医院", "体检", "银行", "政务", "排队"),
        ((_h(7), _h(21)),),
        60,
    ),
    TimeRule(
        "休闲",
        ("刷手机", "看电视", "追剧", "上网", "发呆", "休闲", "个人时间", "自由活动"),
        ((_h(0), _h(24)),),
        0,
    ),
)

ACTION_RULES: tuple[TimeRule, ...] = (
    TimeRule(
        "收工",
        (
            "收尾",
            "收工",
            "收摊",
            "下班",
            "打烊",
            "结算",
            "对账",
            "交接班",
            "总结今天",
            "今日总结",
            "复盘今天",
            "盘点今天",
        ),
        ((_h(17), _h(23)),),
        60,
    ),
    TimeRule(
        "开始工作",
        ("晨会", "早会", "开工", "开始一天", "上班", "报到", "打卡", "签到"),
        ((_h(5), _h(12)),),
        60,
    ),
    TimeRule("午休", ("午休", "午睡", "打盹"), ((_h(11, 30), _h(16)),), 60),
    TimeRule("早饭", ("早饭", "早餐"), ((_h(5), _h(10)),), 45),
    TimeRule("午饭", ("工作餐", "午饭", "午餐", "中饭"), ((_h(10, 30), _h(14, 30)),), 90),
    TimeRule("晚饭", ("晚饭", "晚餐"), ((_h(16, 30), _h(21)),), 75),
    TimeRule(
        "通勤",
        ("通勤", "地铁", "公交", "打车", "开车", "在路上"),
        ((_h(5, 30), _h(10, 30)), (_h(16), _h(20, 30))),
        45,
    ),
    TimeRule("加班", ("加班",), ((_h(17), _h(22, 30)),), 45),
    TimeRule("汇报", ("工作汇报", "汇报工作", "汇报进展", "写报告", "写材料"), ((_h(7), _h(19)),), 60),
    TimeRule("会议", ("开会", "会议", "讨论", "评审"), ((_h(7), _h(20)),), 60),
    TimeRule("夜跑", ("夜跑",), ((_h(17, 30), _h(23)),), 45),
    TimeRule(
        "运动",
        ("跑步", "锻炼", "健身", "运动", "散步", "遛弯", "瑜伽", "骑车", "游泳"),
        ((_h(5), _h(21, 30)),),
        45,
    ),
    TimeRule("运动", ("跑",), ((_h(5), _h(21, 30)),), 45, _RUN_EXCLUSIONS),
    TimeRule("洗漱", ("洗漱", "洗澡", "刷牙"), ((_h(5), _h(23, 30)),), 30),
    TimeRule("入睡", ("睡觉", "入睡", "躺下", "上床"), ((_h(21, 30), _h(24)), (_h(0), _h(7))), 60),
    TimeRule("购物", ("买菜", "购物", "逛街", "超市"), ((_h(7), _h(22)),), 45),
    TimeRule("育儿", ("接送", "接孩子", "幼儿园", "家长会"), ((_h(7), _h(20)),), 45),
)


# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "repair_schedule": True,
    "gate_actions": True,
    "gate_activity_changes": True,
    "max_shift_minutes": 180,
    "min_gap_minutes": 15,
    "soft_penalty": 0.35,
    "hard_penalty": 2.0,
    "deviation_chance": 0.04,
}


def time_fit_config() -> dict[str, Any]:
    """The ``time_plausibility`` knobs, read at call time.

    Read at call time (not snapshot at import) so a test or the dashboard can
    flip a switch without reloading the process — the same rule the rest of
    the sim package follows.
    """
    raw = CONFIG.get("time_plausibility", {}) or {}
    cfg = dict(_DEFAULTS)
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key in cfg:
                cfg[key] = value
    return cfg


def enabled() -> bool:
    return bool(time_fit_config().get("enabled", True))


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


def day_part(minutes: int | None) -> str:
    """The Chinese name of the part of the day (``"清晨"``, ``"下午"`` …)."""
    if minutes is None:
        return "未知时段"
    clamped = max(0, min(24 * 60 - 1, int(minutes)))
    for label, start, end in DAY_PARTS:
        if start <= clamped < end:
            return label
    return "未知时段"


def _match_rule(text: str, rules: tuple[TimeRule, ...]) -> tuple[TimeRule, str] | None:
    """The most specific rule that ``text`` matches, or ``None``.

    "Most specific" = the longest keyword that occurs in the text. Ties go to
    the earlier rule, so the table reads top-down for equal-length keywords.
    """
    best: tuple[TimeRule, str] | None = None
    best_len = 0
    for rule in rules:
        if any(phrase in text for phrase in rule.exclude):
            continue
        for keyword in rule.keywords:
            if keyword not in text:
                continue
            length = len(keyword)
            if length > best_len:
                best = (rule, keyword)
                best_len = length
    return best


def _verdict_for(rule: TimeRule, minutes: int | None) -> tuple[str, str]:
    if minutes is None:
        return UNKNOWN, "时间未知"
    for start, end in rule.windows:
        if start <= minutes < end:
            return OK, f"{rule.label}（正常时段）"
    for start, end in rule.windows:
        if minutes < start and start - minutes <= rule.soft:
            return SOFT, f"{rule.label}（略微提前）"
        if minutes >= end and minutes - end <= rule.soft:
            return SOFT, f"{rule.label}（略微延后）"
    windows = "、".join(f"{_minutes_to_time_str(s)}-{_minutes_to_time_str(e)}" for s, e in rule.windows)
    return BAD, f"{rule.label}（合理时段 {windows}）"


def activity_time_fit(activity: str, minutes: int | None) -> tuple[str, str]:
    """Is ``activity`` plausible at ``minutes``?

    Returns ``(verdict, reason)``. ``unknown`` means no rule matched and the
    activity is left alone — we do not refuse what we cannot judge.
    """
    text = str(activity or "")
    if not text:
        return UNKNOWN, "无活动"
    matched = _match_rule(text, ACTIVITY_RULES)
    if not matched:
        return UNKNOWN, "无时间约束"
    rule, keyword = matched
    verdict, reason = _verdict_for(rule, minutes)
    return verdict, f"{reason}·命中「{keyword}」"


def action_time_fit(action: str, minutes: int | None) -> tuple[str, str]:
    """Is ``action`` plausible at ``minutes``? Same verdicts as above."""
    text = str(action or "")
    if not text:
        return UNKNOWN, "无动作"
    matched = _match_rule(text, ACTION_RULES)
    if not matched:
        return UNKNOWN, "无时间约束"
    rule, keyword = matched
    verdict, reason = _verdict_for(rule, minutes)
    return verdict, f"{reason}·命中「{keyword}」"


def is_fitting(verdict: str) -> bool:
    """True for the verdicts that may stand without penalty."""
    return verdict in (OK, UNKNOWN)


# ---------------------------------------------------------------------------
# Schedule repair
# ---------------------------------------------------------------------------


def _nearest_in_window(minutes: int, window: tuple[int, int]) -> int:
    """The point of ``window`` closest to ``minutes`` (clamped to its edges)."""
    start, end = window
    return max(start, min(end - 1, minutes))


def _candidate_times(minutes: int, rule: TimeRule) -> list[int]:
    """Times inside ``rule`` worth moving the item to, closest first."""
    candidates: list[int] = []
    for start, end in rule.windows:
        candidates.append(_nearest_in_window(minutes, (start, end)))
        candidates.append(start)
        candidates.append(max(start, end - 1))
    unique = sorted(set(candidates))
    return sorted(unique, key=lambda value: (abs(value - minutes), value))


def _looks_like_night_shift(items: list[tuple[int, str]]) -> bool:
    """True when the schedule itself says "this person works at night".

    Without this, a night-shift resident's 22:00 "上班" would be dragged back
    into the 07:30-19:00 window by the repair. The schedule is the only
    evidence available here (the agent profile is not in scope), so a
    work-ish activity already placed in the small hours counts as consent.
    """
    work_keywords = ("工作", "上班", "值班", "夜班", "加班", "开会", "会议")
    for minutes, activity in items:
        if not any(keyword in activity for keyword in work_keywords):
            continue
        if minutes >= _h(22) or minutes < _h(6):
            return True
    return False


def repair_schedule(
    schedule: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
    """Move schedule items whose hour does not fit their activity.

    Returns ``(repaired, changes)``. ``changes`` describes every move so the
    caller can log it. Items that cannot be placed are left where they are —
    dropping a resident's activity is worse than an occasional odd hour.

    The repair is *local*: an item moves at most ``max_shift_minutes`` and
    only into the core window of the rule it matched, so a schedule keeps its
    shape.
    """
    cfg = time_fit_config()
    if not cfg.get("enabled", True) or not cfg.get("repair_schedule", True):
        return list(schedule), []
    if not schedule:
        return [], []

    min_gap = max(1, int(cfg.get("min_gap_minutes", 15)))
    max_shift = max(0, int(cfg.get("max_shift_minutes", 180)))

    parsed: list[tuple[int, str, str]] = []
    unparsed: list[tuple[str, str]] = []
    for time_str, activity in schedule:
        minutes = _time_str_to_minutes(time_str)
        if minutes is None:
            # An unparseable time is not our business to fix — keep the item.
            unparsed.append((str(time_str), str(activity)))
            continue
        parsed.append((minutes, str(time_str), str(activity)))
    if not parsed:
        return list(schedule), []
    parsed.sort(key=lambda item: item[0])

    night_shift = _looks_like_night_shift([(m, a) for m, _, a in parsed])

    placed: list[tuple[int, str]] = []
    changes: list[dict[str, Any]] = []
    previous: int | None = None
    for minutes, time_str, activity in parsed:
        verdict, reason = activity_time_fit(activity, minutes)
        matched = _match_rule(activity, ACTIVITY_RULES)
        rule = matched[0] if matched else None
        target = minutes
        if verdict == BAD and rule is not None and not (night_shift and rule.label == "工作"):
            for candidate in _candidate_times(minutes, rule):
                if abs(candidate - minutes) > max_shift:
                    continue
                if previous is not None and candidate < previous + min_gap:
                    continue
                target = candidate
                break
        if target != minutes:
            changes.append(
                {
                    "from": time_str,
                    "to": _minutes_to_time_str(target),
                    "activity": activity,
                    "reason": reason,
                }
            )
        placed.append((target, activity))
        previous = target

    placed.sort(key=lambda item: item[0])
    repaired: list[tuple[str, str]] = []
    last: int | None = None
    for minutes, activity in placed:
        if last is not None and minutes - last < min_gap:
            changes.append(
                {
                    "from": _minutes_to_time_str(minutes),
                    "to": "",
                    "activity": activity,
                    "reason": "与前一项间隔过近，已合并",
                }
            )
            continue
        repaired.append((_minutes_to_time_str(minutes), activity))
        last = minutes
    repaired.extend(unparsed)
    return repaired, changes


def should_keep_deviation(verdict: str) -> bool:
    """Roll the dice for a bounded deviation.

    ``soft`` always survives — it is the gray zone, and the whole point of the
    feature is that people do unusual things sometimes. ``bad`` survives only
    on a small dice roll, so an implausible hour is rare but not impossible.
    """
    if verdict in (OK, UNKNOWN):
        return True
    if verdict == SOFT:
        return True
    chance = float(time_fit_config().get("deviation_chance", 0.04))
    return chance > 0.0 and random.random() < chance


__all__ = [
    "ACTION_RULES",
    "ACTIVITY_RULES",
    "BAD",
    "DAY_PARTS",
    "OK",
    "SOFT",
    "UNKNOWN",
    "action_time_fit",
    "activity_time_fit",
    "day_part",
    "enabled",
    "is_fitting",
    "repair_schedule",
    "should_keep_deviation",
    "time_fit_config",
]
