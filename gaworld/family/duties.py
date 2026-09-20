"""What the family actually makes an agent *do* on a given day.

This is the part that turns a relationship graph into a life. A schedule
generator that knows an agent has a five-year-old and a co-resident mother
writes a different day than one that only knows their job — school runs
bracket the working day, dinner is a fixed point, and a weekend belongs to
the household rather than to the agent.

Two outputs:

* :func:`daily_duties` — Chinese phrases injected into the daily-routine
  prompt, varying by weekday/weekend and by who lives in the house.
* :func:`care_load` — a 0..1 scalar the state and finance layers consume, so
  "two young kids and an 80-year-old" costs time, money and calm rather than
  only appearing in prose.
"""

from __future__ import annotations

import random
from typing import Any

from gaworld.family.schema import family_config


def _children(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        m
        for m in (record or {}).get("members", []) or []
        if m.get("role") == "child" and m.get("coresident")
    ]


def _coresident_elders(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        m
        for m in (record or {}).get("members", []) or []
        if m.get("role") in ("father", "mother", "parent") and m.get("coresident")
    ]


def _remote_parents(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        m
        for m in (record or {}).get("members", []) or []
        if m.get("role") in ("father", "mother", "parent") and not m.get("coresident")
    ]


def _partner(record: dict[str, Any]) -> dict[str, Any] | None:
    for member in (record or {}).get("members", []) or []:
        if member.get("role") in ("spouse", "partner"):
            return member
    return None


def care_load(record: dict[str, Any] | None, config: dict[str, Any] | None = None) -> float:
    """0..1 caregiving burden.

    A partner *reduces* the load (the work is shared) but does not erase it;
    a single parent carries the whole thing, which is the point of modelling
    single-parent households separately at all.
    """
    if not record:
        return 0.0
    cfg = family_config(config).get("duties", {})
    preschool_max = int(cfg.get("preschool_age_max", 6))
    school_max = int(cfg.get("school_age_max", 15))
    elder_age = int(cfg.get("elder_care_age", 75))

    load = 0.0
    for child in _children(record):
        age = int(child.get("age", 0) or 0)
        if age <= preschool_max:
            load += 0.34
        elif age <= school_max:
            load += 0.20
        elif age <= 18:
            load += 0.10
        else:
            load += 0.03
    for elder in _coresident_elders(record):
        load += 0.26 if int(elder.get("age", 0) or 0) >= elder_age else 0.10
    partner = _partner(record)
    if partner and partner.get("coresident"):
        load *= 0.62
    return max(0.0, min(1.0, load))


def daily_duties(
    record: dict[str, Any] | None,
    *,
    day: int | None = None,
    is_weekend: bool = False,
    config: dict[str, Any] | None = None,
) -> list[str]:
    """Family duties for one day, most binding first, capped by config."""
    if not record:
        return []
    cfg = family_config(config)
    duties_cfg = cfg.get("duties", {})
    if not duties_cfg.get("enabled", True):
        return []
    preschool_max = int(duties_cfg.get("preschool_age_max", 6))
    school_max = int(duties_cfg.get("school_age_max", 15))
    elder_age = int(duties_cfg.get("elder_care_age", 75))
    max_per_day = int(duties_cfg.get("max_per_day", 3))

    rng = random.Random(f"{cfg.get('seed')}::{record.get('household_id')}::{day}")
    partner = _partner(record)
    elders = _coresident_elders(record)
    children = _children(record)
    has_helper = bool(partner and partner.get("coresident")) or bool(elders)

    duties: list[str] = []
    for child in sorted(children, key=lambda c: int(c.get("age", 0) or 0)):
        age = int(child.get("age", 0) or 0)
        name = str(child.get("name", "孩子"))
        if age <= preschool_max:
            if is_weekend:
                duties.append(f"周末带{age}岁的{name}外出活动，全天需要有人看着")
            elif has_helper and rng.random() < 0.5:
                duties.append(f"和家人轮换接送{name}上下幼儿园（今天不一定轮到你）")
            else:
                duties.append(f"早晚各一次接送{name}上下幼儿园，晚上还要陪玩和哄睡")
        elif age <= school_max:
            if is_weekend:
                duties.append(f"周末要管{name}的作业和兴趣班接送")
            else:
                duties.append(f"晚饭后要陪{name}写作业、检查功课")
        elif age <= 18 and rng.random() < 0.4:
            duties.append(f"关心{name}的学业和晚归情况")

    for elder in elders:
        age = int(elder.get("age", 0) or 0)
        name = str(elder.get("name", "老人"))
        if age >= elder_age:
            duties.append(f"照料同住的{name}（{age}岁）：吃药、陪诊或搭把手")
        elif rng.random() < 0.45:
            duties.append(f"和同住的{name}一起吃饭、说说话")

    if partner and partner.get("coresident"):
        if is_weekend:
            duties.append("周末和伴侣一起处理家务、采买或安排家庭活动")
        elif rng.random() < 0.75:
            duties.append("晚上尽量回家和伴侣一起吃晚饭")
    elif partner:
        duties.append("和分居的伴侣保持联系")

    remote_parents = _remote_parents(record)
    if remote_parents and (is_weekend or rng.random() < 0.18):
        names = "、".join(str(p.get("name", "父母")) for p in remote_parents[:2])
        duties.append(f"抽空给{names}打个电话或回去看看")

    if record.get("household_type") == "single_parent" and children:
        duties.insert(0, "单亲家庭，家里的事没人替你分担")

    return duties[:max_per_day]


def duty_hint(
    record: dict[str, Any] | None,
    *,
    day: int | None = None,
    is_weekend: bool = False,
    config: dict[str, Any] | None = None,
) -> str:
    """The duties rendered as one prompt line (empty when there are none)."""
    duties = daily_duties(record, day=day, is_weekend=is_weekend, config=config)
    if not duties:
        return ""
    return "今日家庭责任：" + "；".join(duties)
