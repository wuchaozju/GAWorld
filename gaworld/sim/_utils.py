"""Pure utility helpers extracted from ``generative_city_sim.py``.

These functions are stateless and only depend on the Python standard
library. They are kept private (leading underscore) because they remain
internal implementation details of the simulator — the public API is
re-defined as part of the sim sub-package once the migration is complete.

Originally lived as the "Utils" banner in ``generative_city_sim.py``
(plus the two log-mode helpers at the top of that file). Behaviour is
preserved byte-for-byte; this file is intentionally a straight lift.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Text-cleaning helpers (used by the env-context summariser and reflection
# post-processor).
# ---------------------------------------------------------------------------

def _clean_env_context(env_text: str, max_chars: int = 80) -> str:
    """Strip static background and intervention text; return dynamic events only.

    The env context string is structured as:
      背景：<static>  当前环境事件：<dynamic>  平台干预推荐：<intervention>

    In simple mode we only want the dynamic part, and skip it entirely when
    it only contains the boilerplate "今日外部环境总体平稳" phrase.
    """
    if not env_text:
        return ""
    # Drop platform intervention section (verbose, repeated, often truncated).
    for marker in ("平台干预推荐：", "\n平台干预推荐"):
        idx = env_text.find(marker)
        if idx != -1:
            env_text = env_text[:idx]
    env_text = env_text.strip()
    # Keep only the part after "当前环境事件：".
    dyn_marker = "当前环境事件："
    idx = env_text.find(dyn_marker)
    if idx != -1:
        env_text = env_text[idx + len(dyn_marker):].strip()
    # Skip uninformative boilerplate.
    if not env_text or "今日外部环境总体平稳" in env_text:
        return ""
    if len(env_text) > max_chars:
        env_text = env_text[:max_chars].rstrip() + "…"
    return env_text


def _clean_reflection(text: str, max_chars: int = 160) -> str:
    """Return a clean Chinese reflection, stripping LLM reasoning leakage.

    Some LLM backends prepend English chain-of-thought ("The user says: …")
    before the actual Chinese answer.  When detected, we try to extract only
    the structured Chinese key-value pairs (感受/教训/后续倾向).
    """
    if not text:
        return text
    # Measure English-character ratio.
    ascii_alpha = sum(1 for c in text if c.isascii() and c.isalpha())
    if ascii_alpha / max(len(text), 1) < 0.10:
        # Looks clean — just truncate.
        return text[:max_chars] + ("…" if len(text) > max_chars else "")
    # Extract structured Chinese parts, skipping polluted 结果 field.
    parts: list[str] = []
    for key in ("感受", "教训", "后续倾向"):
        m = re.search(rf"{key}[：:]\s*([^；\n]+)", text)
        if not m:
            continue
        val = m.group(1).strip()
        val_ascii = sum(1 for c in val if c.isascii() and c.isalpha())
        if val_ascii / max(len(val), 1) < 0.30:
            parts.append(f"{key}：{val}")
    if parts:
        return "；".join(parts)
    # Fallback: truncate original.
    return text[:max_chars] + ("…" if len(text) > max_chars else "")


# ---------------------------------------------------------------------------
# Time / minute conversion helpers.
# ---------------------------------------------------------------------------

def _parse_step_minutes(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower()
    if not text:
        return None
    match = re.match(r"^(\d+)\s*(m|min|mins|minute|minutes|h|hour|hours)?$", text)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    if not unit or unit.startswith("m"):
        return amount
    if unit.startswith("h"):
        return amount * 60
    return amount


def _time_str_to_minutes(time_str: str) -> int | None:
    if not re.match(r"^\d{2}:\d{2}$", str(time_str)):
        return None
    hh, mm = time_str.split(":")
    return int(hh) * 60 + int(mm)


def _minutes_to_time_str(minutes: int) -> str:
    minutes = int(minutes) % (24 * 60)
    hh = minutes // 60
    mm = minutes % 60
    return f"{hh:02d}:{mm:02d}"


def _build_time_grid(step_minutes: int) -> list[str]:
    step = max(1, int(step_minutes))
    return [_minutes_to_time_str(m) for m in range(0, 24 * 60, step)]


def _snap_time_to_grid(time_str: str, step_minutes: int) -> str | None:
    """Round a ``"HH:MM"`` string to the nearest point of a ``step_minutes`` grid.

    Returns ``None`` for unparseable input so callers can drop the slot.
    Rounding is clamped to the last grid point of the day, so a late time such
    as ``23:50`` on a 30-minute grid snaps back to ``23:30`` rather than
    wrapping around to ``00:00`` and breaking the day's ordering.

    Exact midpoints round up (``08:15`` → ``08:30`` on a 30-minute grid).
    ``round()`` is deliberately avoided here: its banker's rounding would send
    ``08:15`` down and ``08:45`` up on the same grid, which is hard to reason
    about when comparing schedules.
    """
    minutes = _time_str_to_minutes(time_str)
    if minutes is None:
        return None
    step = max(1, int(step_minutes))
    last_index = (24 * 60 - 1) // step
    index = min((minutes + step // 2) // step, last_index)
    return _minutes_to_time_str(index * step)


def snap_schedule_to_grid(
    schedule: Sequence[tuple[str, str]], step_minutes: int
) -> list[tuple[str, str]]:
    """Align a ``[(time, activity), …]`` schedule onto a fixed time grid.

    Every retained slot lands on a point of ``_build_time_grid(step_minutes)``,
    which is what keeps the master timeline O(1) in agent count instead of
    growing with the union of every agent's LLM-authored times.

    When two activities collapse onto the same grid slot the later one wins,
    matching the "last write at this time" semantics of
    ``apply_schedule_override`` and ``get_activity_for_time``. Slots with an
    unparseable time are dropped.
    """
    if not schedule or not step_minutes:
        return [tuple(slot) for slot in schedule]  # type: ignore[misc]
    snapped: dict[str, str] = {}
    for slot in schedule:
        time_str, activity = slot[0], slot[1]
        grid_time = _snap_time_to_grid(time_str, step_minutes)
        if grid_time is None:
            continue
        snapped[grid_time] = activity
    return sorted(snapped.items(), key=lambda item: _time_str_to_minutes(item[0]) or 0)


# ---------------------------------------------------------------------------
# External-environment event formatter.
# ---------------------------------------------------------------------------

def _format_external_env_event(ev: Any) -> str:
    if not isinstance(ev, dict):
        return str(ev)
    etype = str(ev.get("type", "event"))
    topic = str(ev.get("topic", "")).strip()
    severity = float(ev.get("severity", 0.0))
    description = str(ev.get("description", ev.get("name", ""))).strip()
    topic_part = f"/{topic}" if topic else ""
    return f"{etype}{topic_part}({severity:.2f}) {description}".strip()


# ---------------------------------------------------------------------------
# Weekday / calendar helpers.
# ---------------------------------------------------------------------------

_WEEKDAY_ORDER: list[str] = [
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
]
_WEEKDAY_ZH: list[str] = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_WEEKDAY_ALIASES: dict[str, str] = {
    "mon": "monday",
    "tue": "tuesday",
    "wed": "wednesday",
    "thu": "thursday",
    "fri": "friday",
    "sat": "saturday",
    "sun": "sunday",
    "周一": "monday",
    "周二": "tuesday",
    "周三": "wednesday",
    "周四": "thursday",
    "周五": "friday",
    "周六": "saturday",
    "周日": "sunday",
}


def _weekday_to_index(name: Any) -> int | None:
    key = str(name or "").strip().lower()
    key = _WEEKDAY_ALIASES.get(key, key)
    if key not in _WEEKDAY_ORDER:
        return None
    return _WEEKDAY_ORDER.index(key)


def _build_weekend_indexes(raw_days: Any) -> set[int]:
    if not isinstance(raw_days, (list, tuple, set)):
        raw_days = [raw_days]
    indexes: set[int] = set()
    for day_name in raw_days:
        idx = _weekday_to_index(day_name)
        if idx is not None:
            indexes.add(idx)
    return indexes or {5, 6}


def _parse_sim_start_date(value: Any) -> date:
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() == "today":
        return date.today()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return date.today()


def _resolve_day_context(
    day_number: Any,
    start_weekday_idx: int = 0,
    weekend_indexes: Iterable[int] | None = None,
    start_date: date | None = None,
) -> dict[str, Any]:
    safe_day = max(1, int(day_number or 1))
    sim_date: date | None = None
    if isinstance(start_date, date):
        sim_date = start_date + timedelta(days=safe_day - 1)
        idx = sim_date.weekday()
    else:
        idx = (int(start_weekday_idx) + safe_day - 1) % 7
    weekend_set = set(weekend_indexes) if weekend_indexes is not None else {5, 6}
    is_weekend = idx in weekend_set
    return {
        "sim_date": sim_date.isoformat() if sim_date else "",
        "sim_date_zh": (
            f"{sim_date.year}年{sim_date.month:02d}月{sim_date.day:02d}日"
            if sim_date else ""
        ),
        "weekday_index": idx,
        "weekday_en": _WEEKDAY_ORDER[idx],
        "weekday_zh": _WEEKDAY_ZH[idx],
        "day_type": "weekend" if is_weekend else "weekday",
        "day_type_zh": "周末" if is_weekend else "工作日",
    }


# ---------------------------------------------------------------------------
# Filesystem / JSON helpers.
# ---------------------------------------------------------------------------

def _clear_dir(path: str | None) -> None:
    if not path or not os.path.exists(path):
        return
    for name in os.listdir(path):
        target = os.path.join(path, name)
        try:
            if os.path.islink(target) or os.path.isfile(target):
                os.remove(target)
            elif os.path.isdir(target):
                shutil.rmtree(target)
        except OSError:
            continue


def _stable_json_marker(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return repr(value)


# ---------------------------------------------------------------------------
# Misc coercion helpers.
# ---------------------------------------------------------------------------

def _coerce_positive_int_list(values: Any) -> list[int]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    seen: set[int] = set()
    out: list[int] = []
    for raw in values:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _sanitize_extra_text(text: Any, max_chars: int = 2000) -> str:
    """Collapse runs of whitespace and clip to ``max_chars``.

    Used by the RAG bootstrap helpers (and 19 other call sites in the
    legacy simulator) to keep stored memory snippets short and uniform.
    """
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return cleaned


__all__ = [
    "_WEEKDAY_ALIASES",
    "_WEEKDAY_ORDER",
    "_WEEKDAY_ZH",
    "_build_time_grid",
    "_build_weekend_indexes",
    "_clean_env_context",
    "_clean_reflection",
    "_clear_dir",
    "_coerce_positive_int_list",
    "_format_external_env_event",
    "_minutes_to_time_str",
    "_parse_sim_start_date",
    "_parse_step_minutes",
    "_resolve_day_context",
    "_sanitize_extra_text",
    "_snap_time_to_grid",
    "_stable_json_marker",
    "_time_str_to_minutes",
    "_weekday_to_index",
    "snap_schedule_to_grid",
]
