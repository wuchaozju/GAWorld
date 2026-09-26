"""What a day out of town looks like.

A trip replaces the resident's day, it does not decorate it. The main loop
reads each tick's activity out of ``schedule_map`` via
``get_activity_for_time``, so rewriting that one list at day start is enough
to change a whole day — the master timeline never has to move.

Schedules are lists of ``(time, activity)`` tuples, which is what the
simulator's own schedule helpers iterate over.
"""

from __future__ import annotations

from typing import Any

PURPOSE_ZH: dict[str, str] = {
    "business": "出差",
    "family": "探亲",
    "leisure": "旅行",
}

MODE_ZH: dict[str, str] = {"rail": "高铁", "air": "飞机"}

#: When someone sets off, and when they start heading back. Early enough that
#: the journey lands inside the same simulated day at every distance the
#: catalogue offers.
DEPART_AT = "07:30"
RETURN_AT = "09:00"


def _add_hours(time_str: str, hours: float) -> str:
    try:
        hh, mm = str(time_str).split(":")
        total = int(hh) * 60 + int(mm) + int(round(float(hours) * 60))
    except (ValueError, TypeError):
        return time_str
    total = min(total, 23 * 60 + 30)
    return f"{total // 60:02d}:{total % 60:02d}"


def _evening(place: str, purpose: str) -> list[tuple[str, str]]:
    rest = {
        "business": f"在{place}的酒店整理工作",
        "family": "陪家人说话",
        "leisure": f"在{place}吃当地的晚饭",
    }.get(purpose, f"在{place}休息")
    return [("19:00", rest), ("22:30", "睡觉")]


def depart_day(trip: dict[str, Any]) -> list[tuple[str, str]]:
    """Leaving: home, the journey, then the first evening away."""
    place = str(trip.get("place", "外地"))
    mode = MODE_ZH.get(str(trip.get("mode", "")), "长途交通")
    purpose = str(trip.get("purpose", ""))
    arrive = _add_hours(DEPART_AT, float(trip.get("hours", 2.0) or 2.0))
    return [
        ("06:30", "起床收拾行李"),
        (DEPART_AT, f"乘{mode}前往{place}"),
        (arrive, f"抵达{place}，安顿下来"),
        *_evening(place, purpose),
    ]


def away_day(trip: dict[str, Any]) -> list[tuple[str, str]]:
    """A full day away, shaped by why the trip happened."""
    place = str(trip.get("place", "外地"))
    purpose = str(trip.get("purpose", ""))
    if purpose == "business":
        core = [
            ("08:30", f"在{place}见客户、开会"),
            ("12:00", "和对接人一起吃午饭"),
            ("14:00", f"在{place}继续处理工作"),
            ("18:00", "整理今天谈成的事"),
        ]
    elif purpose == "family":
        name = str(trip.get("tie_name", "") or "家人")
        core = [
            ("08:30", f"陪{name}吃早饭、说话"),
            ("11:00", f"帮{name}处理家里的事"),
            ("14:00", f"陪{name}出门走走"),
            ("18:00", "一起做晚饭"),
        ]
    else:
        core = [
            ("09:00", f"在{place}逛"),
            ("12:00", "找一家本地馆子吃饭"),
            ("14:30", f"在{place}继续走走看看"),
            ("18:00", "回住处歇一会儿"),
        ]
    return [("07:30", "起床"), *core, *_evening(place, purpose)]


def return_day(trip: dict[str, Any]) -> list[tuple[str, str]]:
    """Coming back: the return leg, then home."""
    place = str(trip.get("place", "外地"))
    mode = MODE_ZH.get(str(trip.get("mode", "")), "长途交通")
    arrive = _add_hours(RETURN_AT, float(trip.get("hours", 2.0) or 2.0))
    return [
        ("07:30", "起床，收拾返程的行李"),
        (RETURN_AT, f"乘{mode}返回"),
        (arrive, "到家，把行李放下"),
        ("19:00", "在家吃晚饭"),
        ("22:30", "睡觉"),
    ]


def schedule_for(trip: dict[str, Any], day: int) -> list[tuple[str, str]]:
    """The day's schedule for whichever leg of the trip ``day`` falls on."""
    if int(day) == int(trip.get("depart_day", day)):
        return depart_day(trip)
    if int(day) >= int(trip.get("return_day", day)):
        return return_day(trip)
    return away_day(trip)


def perception_line(trip: dict[str, Any], day: int) -> str:
    """The one line that tells the agent it is not at home."""
    place = str(trip.get("place", "外地"))
    purpose_zh = PURPOSE_ZH.get(str(trip.get("purpose", "")), "外出")
    depart = int(trip.get("depart_day", day))
    return_day_ = int(trip.get("return_day", day))
    nth = max(1, int(day) - depart + 1)
    if int(day) >= return_day_:
        return f"你今天从{place}回本市，这趟{purpose_zh}到今天结束。"
    left = max(0, return_day_ - int(day))
    return (
        f"你现在不在本市，人在{place}（{purpose_zh}第 {nth} 天，还有 {left} 天回去）。"
        f"本市的日常、同事和邻居今天都不在你身边。"
    )


def absence_line(trip: dict[str, Any]) -> str:
    """What the trip means for whoever is still at home."""
    place = str(trip.get("place", "外地"))
    return f"你不在家，家里的事这几天得由家人顶着——你人在{place}。"
