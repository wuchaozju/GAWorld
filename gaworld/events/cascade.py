"""事件影响的筛选与日程落地。

**实际影响 = 客观影响 × 主体预估。** 本模块是那条乘法的落地处：

* :func:`select_impacts` — 按关注权重、感知放大系数与韧性系数给客观影响池
  缩放排序，并按配置截断；
* :func:`plan_actions_to_impacts` — 把模型给的行动计划翻译成同一种影响单，
  于是"模型说要去看病"和"模板说要看病"走的是同一条路；
* :func:`apply_schedule_impacts` — 把日程类影响落到当天的日程上；
* :class:`ImpactLedger` — 记住什么已经施加过，避免一场暴雨在一天里扣十几次车费。
"""

from __future__ import annotations

from typing import Any

from gaworld.events.impact import MAX_SCALE, MIN_SCALE, Impact, normalize_impact

#: 感知放大系数的上下限（相对客观严重度）。
PERCEPTION_BAND = (0.5, 1.8)

#: 日程改写时不被替换的活动（吃饭、休息、睡眠）。
_PROTECTED = ("吃饭", "午饭", "早饭", "晚饭", "休息", "午睡", "睡")


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _time_to_minutes(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except (TypeError, ValueError):
        return None


def _minutes_to_time(minutes: int) -> str:
    minutes = max(0, min(24 * 60 - 1, int(minutes)))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def perception_factor(appraisal: dict[str, Any]) -> float:
    """How much bigger (or smaller) this person finds the event than it is.

    Uses the *unclipped* perceived severity: at a high objective severity a
    clipped value would saturate for nearly every resident and the individual
    difference would disappear.
    """
    raw = appraisal.get("perceived_severity_raw")
    if raw is None:
        raw = appraisal.get("perceived_severity")
    perceived = _to_float(raw, 0.5)
    objective = _to_float(appraisal.get("objective_severity"), 0.5)
    ratio = perceived / max(objective, 0.05)
    return _clip(ratio, PERCEPTION_BAND[0], PERCEPTION_BAND[1])


def select_impacts(
    objective_impacts: list[Impact] | None,
    appraisal: dict[str, Any],
    *,
    max_impacts: int = 4,
) -> list[dict[str, Any]]:
    """The impacts that will actually land, with their final scale.

    Scale = 影响自身强度 × 关注权重 × 感知放大 × 韧性。
    """
    concerns = appraisal.get("concerns") or {}
    resilience = _clip(_to_float(appraisal.get("resilience"), 1.0), 0.4, 1.6)
    factor = perception_factor(appraisal)
    objective_severity = _to_float(appraisal.get("objective_severity"), 0.5)

    selected: list[dict[str, Any]] = []
    for impact in objective_impacts or []:
        if not isinstance(impact, Impact):
            continue
        # The concern weight is the resident's *absolute* exposure to this
        # domain (interest × exposure), so two residents hit by the same event
        # land differently. It is not divided by the maximum: that would erase
        # the difference the layer exists to produce.
        weight = _to_float(concerns.get(impact.domain), 1.0) if impact.domain in concerns else 1.0
        weight = max(0.0, weight)
        scale = impact.scale * weight * factor * resilience
        if scale < MIN_SCALE:
            continue
        scale = min(scale, MAX_SCALE)
        selected.append(
            {
                "impact": impact,
                "scale": round(scale, 4),
                "objective_severity": round(objective_severity, 4),
                "domain": impact.domain,
                "kind": impact.kind,
            }
        )
    selected.sort(key=lambda row: -row["scale"])
    limit = max(1, int(max_impacts))
    return selected[:limit]


def plan_actions_to_impacts(
    actions: Any,
    *,
    time_str: str = "",
) -> list[Impact]:
    """The model's plan, translated into impacts of the same shape.

    A plan that says "上午的班改成去医院" has to reach the schedule through
    exactly the same door as a template that says so — otherwise the two paths
    drift and only one of them works.
    """
    out: list[Impact] = []
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        kind = str(action.get("kind", "")).strip().lower()
        if kind == "activity_replace":
            target = str(action.get("target", "") or "").strip()
            replacement = str(action.get("replacement", "") or "").strip()
            if not target or not replacement:
                continue
            impact = normalize_impact(
                {
                    "domain": "schedule",
                    "kind": "activity_replace",
                    "params": {
                        "targets": [target],
                        "replacement": replacement,
                        "window_minutes": 240,
                    },
                    "scale": 1.0,
                    "duration_days": 1,
                    "note": f"因为事件把「{target}」改成了「{replacement}」",
                }
            )
        elif kind == "activity_add":
            activity = str(action.get("activity", "") or "").strip()
            if not activity:
                continue
            impact = normalize_impact(
                {
                    "domain": "schedule",
                    "kind": "activity_add",
                    "params": {
                        "activity": activity,
                        "time": str(action.get("time", "") or time_str or ""),
                        "minutes": max(5, min(480, int(_to_float(action.get("minutes"), 30)))),
                    },
                    "scale": 1.0,
                    "duration_days": 1,
                    "note": f"新增安排：{activity}",
                }
            )
        elif kind == "contact":
            target = str(action.get("target", "") or "").strip()
            if not target:
                continue
            impact = normalize_impact(
                {
                    "domain": "schedule",
                    "kind": "activity_add",
                    "params": {
                        "activity": f"联系{target}",
                        "time": str(time_str or ""),
                        "minutes": 20,
                    },
                    "scale": 0.8,
                    "duration_days": 1,
                    "note": f"想找{target}说说这件事",
                }
            )
        elif kind == "seek_info":
            note = str(action.get("note", "") or "").strip()
            activity = str(action.get("activity", "") or "").strip()
            label = activity or (f"了解{note}" if note else "查证信息")
            impact = normalize_impact(
                {
                    "domain": "schedule",
                    "kind": "activity_add",
                    "params": {
                        "activity": label,
                        "time": str(time_str or ""),
                        "minutes": 30,
                    },
                    "scale": 0.7,
                    "duration_days": 1,
                    "note": f"需要先弄清楚：{label}",
                }
            )
        else:
            continue
        if impact is not None:
            out.append(impact)
    return out


# ---------------------------------------------------------------------------
# Ledger — what has already been applied to this resident.
# ---------------------------------------------------------------------------


def ledger_key(event: Any, domain: str, kind: str, day: Any, signature: str = "") -> str:
    """The dedup key for one applied impact.

    Life events carry a stable id and are applied once, ever. Environment
    events are regenerated every tick with a fresh id, so they are keyed by
    (day, domain, kind) instead — otherwise a three-hour storm charges the
    resident for a taxi twenty times.

    ``signature`` distinguishes two impacts of the same domain and kind that
    are genuinely different: a template that says "the morning goes to the
    hospital" and a resident's own plan that says "the morning goes to the
    clinic" are two changes, not one applied twice.
    """
    if isinstance(event, dict) and event.get("life_event") and event.get("id"):
        base = f"event:{event['id']}"
    elif isinstance(event, dict) and event.get("template_key"):
        base = f"event:{event.get('template_key')}:{event.get('id', '')}"
    else:
        try:
            day_key = int(day)
        except (TypeError, ValueError):
            day_key = 0
        base = f"day:{day_key}"
    suffix = f":{signature}" if signature else ""
    return f"{base}:{domain}:{kind}{suffix}"


def appraisal_key(event: Any, day: Any) -> str:
    """The key under which an event is marked as *already assessed*.

    One assessment per event per resident: an event's consequences must not
    depend on how many times the tick loop happens to look at it. Life events
    carry a stable id; environment events are regenerated every tick, so they
    are keyed by (day, type, topic) instead.
    """
    if isinstance(event, dict) and event.get("template_key"):
        return f"event:{event.get('id') or event.get('template_key')}:appraised"
    etype = str(event.get("type", "")) if isinstance(event, dict) else ""
    topic = str(event.get("topic", "")) if isinstance(event, dict) else ""
    try:
        day_key = int(day)
    except (TypeError, ValueError):
        day_key = 0
    return f"day:{day_key}:appraised:{etype}|{topic}"


class ImpactLedger:
    """Per-resident record of applied impacts."""

    def __init__(self, agent: Any):
        self._agent = agent
        store = agent.get("_impact_ledger") if isinstance(agent, dict) else None
        if not isinstance(store, dict):
            store = {}
            if isinstance(agent, dict):
                agent["_impact_ledger"] = store
        self._store = store

    def already_applied(self, key: str) -> bool:
        return key in self._store

    def mark(self, key: str, payload: Any = None) -> None:
        self._store[key] = payload if payload is not None else True

    def entries(self) -> dict[str, Any]:
        return dict(self._store)


# ---------------------------------------------------------------------------
# Schedule landing.
# ---------------------------------------------------------------------------


def _schedule_items(schedule: Any) -> list[tuple[str, str]]:
    """Normalize a schedule into ``(time, activity)`` pairs."""
    out: list[tuple[str, str]] = []
    for item in schedule or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            out.append((str(item[0]), str(item[1])))
        elif isinstance(item, dict):
            out.append((str(item.get("time", "")), str(item.get("activity", ""))))
    return out


def _restore_schedule(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The schedule back in the canonical ``(time, activity)`` shape.

    Tuples are the form every reader of ``schedule_map`` understands
    (``get_activity_for_time``, ``apply_schedule_override``,
    ``reshape_day_for_life_event``). Two places in the simulator write the
    dict form instead; this cascade always writes the tuple form so a
    rewritten day stays readable.
    """
    return sorted(items, key=lambda kv: _time_to_minutes(kv[0]) or 0)


def _is_protected(activity: str) -> bool:
    return any(key in activity for key in _PROTECTED)


def _matches_target(activity: str, targets: list[str]) -> bool:
    return any(target and target in activity for target in targets)


def apply_schedule_impacts(
    schedule: Any,
    selected: list[dict[str, Any]],
    *,
    time_str: str = "",
) -> tuple[Any, list[dict[str, Any]]]:
    """Apply schedule-domain impacts to a day's schedule.

    Returns ``(new_schedule, changes)``. The result is always in the
    canonical ``(time, activity)`` tuple form — the shape every reader of
    ``schedule_map`` understands.
    """
    items = _schedule_items(schedule)
    changes: list[dict[str, Any]] = []
    if not items:
        return schedule, changes

    current = _time_to_minutes(time_str)
    if current is None:
        current = _time_to_minutes(items[0][0]) or 0

    for row in selected or []:
        impact = row.get("impact")
        if not isinstance(impact, Impact) or impact.domain != "schedule":
            continue
        params = impact.params or {}
        scale = _to_float(row.get("scale"), 1.0)

        if impact.kind == "activity_replace":
            targets = [str(t) for t in (params.get("targets") or []) if str(t).strip()]
            replacement = str(params.get("replacement", "") or "").strip()
            if not targets or not replacement:
                continue
            window = max(30, int(_to_float(params.get("window_minutes"), 240)))
            end = current + window
            replaced: list[tuple[str, str]] = []
            for slot_time, activity in items:
                minutes = _time_to_minutes(slot_time)
                if minutes is None:
                    replaced.append((slot_time, activity))
                    continue
                if _is_protected(activity) or not _matches_target(activity, targets):
                    replaced.append((slot_time, activity))
                    continue
                if current <= minutes < end:
                    changes.append(
                        {
                            "time": slot_time,
                            "from": activity,
                            "to": replacement,
                            "kind": "impact_replace",
                            "scale": scale,
                        }
                    )
                    replaced.append((slot_time, replacement))
                else:
                    replaced.append((slot_time, activity))
            items = replaced
            # The current slot always gets the replacement, even when nothing
            # matched: the event happened *now*, and the resident has to do
            # something about it.
            if not any(c["kind"] == "impact_replace" for c in changes):
                for index, (slot_time, activity) in enumerate(items):
                    if (_time_to_minutes(slot_time) or 0) >= current:
                        changes.append(
                            {
                                "time": slot_time,
                                "from": activity,
                                "to": replacement,
                                "kind": "impact_insert",
                                "scale": scale,
                            }
                        )
                        items[index] = (slot_time, replacement)
                        break

        elif impact.kind == "activity_add":
            activity = str(params.get("activity", "") or "").strip()
            if not activity:
                continue
            at = _time_to_minutes(params.get("time")) or current
            duration = max(5, min(480, int(_to_float(params.get("minutes"), 30))))
            end_at = at + duration
            kept: list[tuple[str, str]] = []
            inserted = False
            for slot_time, slot_activity in items:
                minutes = _time_to_minutes(slot_time)
                if minutes is not None and at <= minutes < end_at:
                    changes.append(
                        {
                            "time": slot_time,
                            "from": slot_activity,
                            "to": activity,
                            "kind": "impact_add",
                            "scale": scale,
                        }
                    )
                    if not inserted:
                        kept.append((_minutes_to_time(at), activity))
                        inserted = True
                    continue
                kept.append((slot_time, slot_activity))
            if not inserted:
                kept.append((_minutes_to_time(at), activity))
                changes.append(
                    {
                        "time": _minutes_to_time(at),
                        "from": None,
                        "to": activity,
                        "kind": "impact_add",
                        "scale": scale,
                    }
                )
            items = kept

    return _restore_schedule(items), changes


__all__ = [
    "PERCEPTION_BAND",
    "ImpactLedger",
    "apply_schedule_impacts",
    "appraisal_key",
    "ledger_key",
    "perception_factor",
    "plan_actions_to_impacts",
    "select_impacts",
]
