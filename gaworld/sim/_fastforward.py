"""Long-horizon fast-forward: day, month and year compression.

The normal main loop simulates a day at fine granularity: an intra-day
timeline of ticks, each running the full cognition pipeline (one LLM call
per agent per tick). That is the right fidelity for a handful of days, but
it makes long horizons (60, 600 days) intractable — both in wall-clock and
in LLM cost.

**Fast-forward mode** collapses one *step* into a single brief per agent:
one LLM call authors a short "what happened" sketch plus a set of
approximate, clamped deltas (mood/state, goal progress, memory lines, next
step's intentions, social signals). The main loop applies those deltas so
memory, goals, relationships and state still *evolve* — just at a coarse,
approximate resolution — and the step's log is the brief rather than a
per-tick trace.

The **step unit** (``long_run.unit``) picks how much wall-time one step
covers:

* ``day`` — one brief per agent per day (the original fast-forward);
* ``month`` — one brief per agent per calendar month;
* ``year`` — one brief per agent per calendar year.

Month/year steps are what make decade-scale runs affordable: 10 simulated
years for 50 residents is 500 LLM calls at ``unit="year"`` versus 182,500
at ``unit="day"``. Everything below the digest still advances in *days* —
the sim-day counter, the calendar, and the day-boundary hooks, which the
main loop replays in chunks of at most ``long_run.hook_chunk_days`` days so
the economy's 30-day settlement cadence keeps landing (see
:func:`plan_hook_chunks`).

This module owns the reusable, side-effect-free pieces:

* :func:`long_run_config` / :func:`long_run_enabled` / :func:`long_run_unit`
  — read the config block;
* :class:`Period` + :func:`plan_horizon` / :func:`span_days` — turn a run
  length into the list of steps to execute;
* :func:`simulate_agent_day` / :func:`simulate_agent_period` — the
  one-call-per-agent digest (LLM fast path + deterministic fallback);
* :func:`apply_state_changes` — clamp and apply the approximate state deltas;
* :func:`render_day_brief_block` / :func:`render_period_brief_block` — the
  console/log "Day N 简报" / "第 N 月 简报" block.

Orchestration that touches ``run_simulation`` locals (hooks, persistence,
diary/vector-DB writes) stays in the main loop, mirroring how the per-tick
pipeline stages are wired there.

LLM access goes through ``gaworld.llm.providers`` by module attribute (not a
``from`` import) so the test mock installer's ``call_llm`` reassignment is
honoured, matching :mod:`gaworld.sim._diary`.
"""

from __future__ import annotations

import json
import random as _random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

from gaworld.llm import providers as _llm_providers
from gaworld.logging_setup import get_logger
from gaworld.settings import CONFIG
from gaworld.sim._schedule import _compact_text

_LOG = get_logger("gaworld.sim.fastforward")

# State metrics the digest may nudge. Restricting to the human-meaningful
# dimensions keeps the LLM from inventing keys; everything else evolves
# through the existing day-end hooks (economy, growth, interests, decay).
LONG_RUN_STATE_KEYS: tuple[str, ...] = (
    "emotion",
    "stress",
    "econ_security",
    "city_identity",
    "policy_sensitivity",
    "platform_dependence",
    "mobility_intent",
)

_DEFAULT_MAX_DELTA = 0.15
_DEFAULT_BRIEF_MAX_CHARS = 240
_DEFAULT_RANDOMNESS = 0.3

# Step units, coarsest last. ``day`` is the original fast-forward.
LONG_RUN_UNITS: tuple[str, ...] = ("day", "month", "year")
_UNIT_ZH = {"day": "天", "month": "月", "year": "年"}
_UNIT_TITLE = {"day": "Day", "month": "Month", "year": "Year"}

_DEFAULT_HOOK_CHUNK_DAYS = 30
_DEFAULT_PERIOD_BRIEF_MAX_CHARS = 480

# How much further a *cumulative* state delta may travel when one step
# covers a month / a year. Deliberately not ``sqrt(days)``: a month of life
# moves a person considerably more than a day, but nowhere near 30
# independent days of random walk — people regress to their set point.
_PERIOD_DELTA_SCALE = {"day": 1.0, "month": 2.0, "year": 3.0}
# Same idea for the stochastic jitter amplitude.
_PERIOD_JITTER_SCALE = {"day": 1.0, "month": 1.8, "year": 2.4}
# Sanity cap on how many unplanned events one brief is asked to carry.
_MAX_BURSTS = 4

# Randomness shaping. ``randomness`` r ∈ [0,1] scales two effects:
#   * burst events — per-agent-per-day chance of an unplanned event =
#     ``_BURST_BASE_CHANCE * r`` (so ~30% of agent-days at r=1);
#   * state volatility — daily zero-mean jitter of amplitude
#     ``_JITTER_SCALE * r`` per key, amplified ``_BURST_JITTER_MULT``× on a
#     burst day. At r=0 there are no bursts and no jitter — identical to the
#     deterministic fast-forward day.
_BURST_BASE_CHANCE = 0.30
_BURST_JITTER_MULT = 3.0
_JITTER_SCALE = 0.06
# The keys jitter perturbs (the human-meaningful, fast-moving ones).
_JITTER_STATE_KEYS: tuple[str, ...] = ("emotion", "stress", "econ_security", "city_identity")

_BURST_PROMPT_HINT = (
    "【突发】今天发生了一件计划外的事（可好可坏，如意外开销/机会/冲突/健康/人际变故等）。"
    "请在简报里自然地体现这件事，并让相关状态出现明显（但合理）的波动。"
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def long_run_config(config: dict | None = None) -> dict[str, Any]:
    cfg = config if isinstance(config, dict) else CONFIG
    block = cfg.get("long_run", {}) if isinstance(cfg, dict) else {}
    return block if isinstance(block, dict) else {}


def long_run_enabled(config: dict | None = None) -> bool:
    """Is fast-forward on?

    A coarse step unit implies it. ``unit="year"`` with ``enabled=False`` is
    not a meaningful configuration — there is no per-year tick loop — and
    silently resolving it to "run 365 tick-loop days" is the expensive wrong
    answer. The CLI already reads it this way (``--sim-years`` implies
    ``--fast-forward``); this makes every other entry point agree, including
    a dashboard user who picks 年 without ticking the box.
    """
    block = long_run_config(config)
    if bool(block.get("enabled", False)):
        return True
    raw = str(block.get("unit", "day") or "day").strip().lower()
    return raw in LONG_RUN_UNITS and raw != "day"


def _brief_max_chars(cfg: dict[str, Any]) -> int:
    try:
        return max(40, int(cfg.get("brief_max_chars", _DEFAULT_BRIEF_MAX_CHARS)))
    except (TypeError, ValueError):
        return _DEFAULT_BRIEF_MAX_CHARS


def _period_brief_max_chars(cfg: dict[str, Any], unit: str) -> int:
    """Length budget for a month/year brief (a year gets 1.5× a month's)."""
    try:
        base = max(80, int(cfg.get("period_brief_max_chars", _DEFAULT_PERIOD_BRIEF_MAX_CHARS)))
    except (TypeError, ValueError):
        base = _DEFAULT_PERIOD_BRIEF_MAX_CHARS
    return int(base * 1.5) if unit == "year" else base


def _max_delta(cfg: dict[str, Any]) -> float:
    try:
        return max(0.0, min(1.0, float(cfg.get("max_state_delta", _DEFAULT_MAX_DELTA))))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_DELTA


def randomness_level(config: dict | None = None) -> float:
    """Long-run randomness r ∈ [0,1]; higher → more bursts + bigger swings."""
    cfg = long_run_config(config)
    try:
        return max(0.0, min(1.0, float(cfg.get("randomness", _DEFAULT_RANDOMNESS))))
    except (TypeError, ValueError):
        return _DEFAULT_RANDOMNESS


def long_run_unit(config: dict | None = None) -> str:
    """Step unit — ``day`` (default), ``month`` or ``year``.

    Anything unrecognised falls back to ``day``, so a typo degrades to the
    familiar behaviour instead of silently skipping a decade.
    """
    raw = str(long_run_config(config).get("unit", "day") or "day").strip().lower()
    return raw if raw in LONG_RUN_UNITS else "day"


def hook_chunk_days(config: dict | None = None) -> int:
    """Max days per day-boundary hook emission inside one coarse step.

    Keeping this at or below 30 means a chunk crosses at most one 30-day
    boundary, which is what lets the economy's monthly settlement stay
    exactly as written (one month of accrued gross wages per settlement).
    """
    try:
        value = int(long_run_config(config).get("hook_chunk_days", _DEFAULT_HOOK_CHUNK_DAYS))
    except (TypeError, ValueError):
        value = _DEFAULT_HOOK_CHUNK_DAYS
    return max(1, min(30, value))


def max_state_delta_for(unit: str, config: dict | None = None) -> float:
    """Per-step cumulative state-delta cap for ``unit``."""
    base = _max_delta(long_run_config(config))
    return min(1.0, base * _PERIOD_DELTA_SCALE.get(unit, 1.0))


# ---------------------------------------------------------------------------
# Horizon planning — turning a run length into a list of steps
# ---------------------------------------------------------------------------

_DAYS_PER_UNIT_FALLBACK = {"day": 1, "month": 30, "year": 365}


@dataclass(frozen=True)
class Period:
    """One simulation step: a contiguous, inclusive range of sim days.

    ``unit="day"`` periods are single days, so the day loop and the
    month/year loop are the same loop.
    """

    unit: str
    index: int  # 1-based ordinal within this run
    start_day: int  # inclusive sim-day number
    end_day: int  # inclusive
    start_date: date | None = None
    end_date: date | None = None

    @property
    def days(self) -> int:
        return max(1, self.end_day - self.start_day + 1)

    @property
    def title(self) -> str:
        """Log marker, e.g. ``Day 12`` / ``Month 3`` / ``Year 2``."""
        if self.unit == "day":
            return f"Day {self.end_day}"
        return f"{_UNIT_TITLE.get(self.unit, 'Step')} {self.index}"

    def describe(self, day_desc: str = "") -> str:
        """Human-facing span description used in prompts and headers."""
        if self.unit == "day":
            return str(day_desc or "").strip()
        label = f"第{self.index}{_UNIT_ZH.get(self.unit, '步')}"
        if self.start_date and self.end_date:
            return (
                f"{label}（{self.start_date.isoformat()} ~ "
                f"{self.end_date.isoformat()}，共{self.days}天）"
            )
        return f"{label}（Day {self.start_day}~{self.end_day}，共{self.days}天）"


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return (date(year + 1, 1, 1) - date(year, 12, 1)).days
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def _add_months(anchor: date, months: int) -> date:
    """Calendar month arithmetic, clamping the day-of-month (Jan 31 + 1m)."""
    total = anchor.month - 1 + int(months)
    year = anchor.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(anchor.day, _days_in_month(year, month)))


def span_days(
    unit: str, count: int, *, start_date: date | None = None, start_day: int = 1
) -> int:
    """Total sim days covered by ``count`` steps of ``unit``.

    With a calendar ``start_date`` the span is exact (leap years, 28/31-day
    months included); without one it falls back to 30/365-day units.
    """
    count = max(1, int(count))
    unit = unit if unit in LONG_RUN_UNITS else "day"
    if unit == "day":
        return count
    if start_date is None:
        return count * _DAYS_PER_UNIT_FALLBACK[unit]
    anchor = start_date + timedelta(days=max(1, int(start_day)) - 1)
    months = count if unit == "month" else 12 * count
    return (_add_months(anchor, months) - anchor).days


def plan_horizon(
    start_day: int,
    total_days: int,
    unit: str = "day",
    *,
    start_date: date | None = None,
) -> list[Period]:
    """Split ``total_days`` sim days starting at ``start_day`` into steps.

    Month/year periods are anchored on the run's first simulated date (not
    on calendar month starts), so ``--sim-months 6`` is always exactly six
    steps. The final period is clipped to the requested horizon, so it can
    be short.
    """
    unit = unit if unit in LONG_RUN_UNITS else "day"
    total_days = max(0, int(total_days))
    if total_days <= 0:
        return []
    start_day = int(start_day)
    last_day = start_day + total_days - 1

    def _date_for(day_number: int) -> date | None:
        if start_date is None:
            return None
        return start_date + timedelta(days=day_number - 1)

    if unit == "day":
        return [
            Period(
                unit="day",
                index=idx,
                start_day=day,
                end_day=day,
                start_date=_date_for(day),
                end_date=_date_for(day),
            )
            for idx, day in enumerate(range(start_day, last_day + 1), start=1)
        ]

    months_per_step = 1 if unit == "month" else 12
    anchor = _date_for(start_day)
    periods: list[Period] = []
    cursor = start_day
    index = 0
    while cursor <= last_day:
        index += 1
        if anchor is not None:
            next_start = start_day + (_add_months(anchor, months_per_step * index) - anchor).days
        else:
            next_start = start_day + _DAYS_PER_UNIT_FALLBACK[unit] * index
        end_day = min(next_start - 1, last_day)
        if end_day < cursor:  # degenerate config; never loop forever
            break
        periods.append(
            Period(
                unit=unit,
                index=index,
                start_day=cursor,
                end_day=end_day,
                start_date=_date_for(cursor),
                end_date=_date_for(end_day),
            )
        )
        cursor = end_day + 1
    return periods


def plan_hook_chunks(period: Period, chunk_days: int) -> list[tuple[int, int]]:
    """Split a period into ``(end_day, days)`` day-boundary hook emissions.

    The day-boundary hooks (economy settlement, interest decay, household
    duties, goal reviews) are written against a *day*; a month/year step
    replays them in chunks instead of once, so a year does not book a single
    day of rent. Each chunk is reported by its last day, which is the day
    number the hooks see.
    """
    chunk_days = max(1, int(chunk_days))
    chunks: list[tuple[int, int]] = []
    cursor = period.start_day
    while cursor <= period.end_day:
        end = min(cursor + chunk_days - 1, period.end_day)
        chunks.append((end, end - cursor + 1))
        cursor = end + 1
    return chunks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _schedule_text(base_schedule: Any, max_items: int = 8) -> str:
    """Compact one-line rendering of an agent's planned (base) schedule."""
    if not base_schedule:
        return "（无固定安排）"
    parts: list[str] = []
    for slot in list(base_schedule)[:max_items]:
        try:
            t, act = slot
        except (TypeError, ValueError):
            continue
        parts.append(f"{t} {act}")
    return "；".join(parts) if parts else "（无固定安排）"


def _recent_memory_text(agent: dict[str, Any], max_items: int = 3) -> str:
    memory = agent.get("memory", []) or []
    lines = [str(m).strip() for m in memory[-max_items:] if str(m or "").strip()]
    return " / ".join(lines) if lines else "（暂无近期记忆）"


def _state_summary(agent: dict[str, Any]) -> str:
    state = agent.get("state", {}) or {}
    keys = ("emotion", "stress", "econ_security", "city_identity")
    parts = [
        f"{k}={float(state[k]):.2f}"
        for k in keys
        if isinstance(state.get(k), (int, float))
    ]
    return "，".join(parts) if parts else "（无）"


def _neighbor_text(
    agent: dict[str, Any], agents_by_id: dict[Any, dict[str, Any]], max_items: int = 5
) -> str:
    neighbors = agent.get("social_neighbors", []) or []
    names = []
    for nid in list(neighbors)[:max_items]:
        name = (agents_by_id.get(nid) or {}).get("name", str(nid))
        names.append(f"{name}(#{nid})")
    return "、".join(names) if names else "（几乎没有熟人往来）"


def _relationship_text(
    agent: dict[str, Any], agents_by_id: dict[Any, dict[str, Any]], max_items: int = 6
) -> str:
    """Key ties *with their current closeness*, strongest first.

    A bare name list tells the model who exists but not where the
    relationship stands, so it can only report "talked to them" pings. Over a
    month or a year the interesting thing is the trajectory — who is drifting,
    who is becoming central — and that needs the current value as the anchor.
    """
    relationships = agent.get("relationships", {})
    rows: list[tuple[float, str]] = []
    if isinstance(relationships, dict):
        for key, item in relationships.items():
            if not isinstance(item, dict):
                continue
            try:
                closeness = float(item.get("closeness", 0.5))
            except (TypeError, ValueError):
                closeness = 0.5
            name = (agents_by_id.get(key) or agents_by_id.get(str(key)) or {}).get("name")
            if not name:
                try:
                    name = (agents_by_id.get(int(key)) or {}).get("name")
                except (TypeError, ValueError):
                    name = None
            label = str(item.get("role") or "").strip()
            display = name or str(key)
            rows.append((closeness, f"{display}(#{key}{'/' + label if label else ''}) 亲密度{closeness:.2f}"))
    if not rows:
        return _neighbor_text(agent, agents_by_id, max_items)
    rows.sort(key=lambda row: row[0], reverse=True)
    return "、".join(text for _, text in rows[:max_items])


def _growth_text(agent: dict[str, Any], max_items: int = 4) -> str:
    """Where this person's skills and interests currently stand."""
    profile = agent.get("growth_profile") or {}
    items = profile.get("items") if isinstance(profile, dict) else None
    if not isinstance(items, list) or not items:
        return "（暂无成长档案）"
    parts = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        try:
            level = float(item.get("level", 0.0))
        except (TypeError, ValueError):
            level = 0.0
        weekly = item.get("weekly_target_minutes")
        target = f"，每周目标{int(weekly)}分钟" if isinstance(weekly, (int, float)) and weekly else ""
        parts.append(f"{name}（水平{level:.2f}{target}）")
    return "；".join(parts) if parts else "（暂无成长档案）"


def _situation_text(agent: dict[str, Any]) -> str:
    """The person's standing circumstances — the frame a long step needs.

    A day is well described by a timetable; a year is not. What carries a
    year is the situation the person is *in*: how old they are, what they do
    for a living, who they live with.
    """
    bits = []
    age = agent.get("age")
    if isinstance(age, (int, float)) and age:
        bits.append(f"{int(age)}岁")
    for key, label in (("gender", ""), ("job", ""), ("living", "居住：")):
        value = str(agent.get(key, "") or "").strip()
        if value:
            bits.append(f"{label}{value}")
    household = agent.get("household") or {}
    if isinstance(household, dict):
        htype = str(household.get("type_zh") or household.get("type") or "").strip()
        if htype:
            bits.append(f"家庭：{htype}")
    return "，".join(bits) if bits else "（无）"


def _period_history_text(agent: dict[str, Any], max_items: int = 3) -> str:
    """The previous steps' briefs — continuity at the step's own scale.

    The day digest looks back at the last few memory lines. Over a year that
    is the wrong window: it shows three sentences from one week and none of
    the arc. Fast-forward keeps the last few *period* briefs instead.
    """
    history = agent.get("_period_briefs") or []
    lines = [str(item).strip() for item in list(history)[-max_items:] if str(item or "").strip()]
    return " ｜ ".join(lines) if lines else "（这是第一个阶段）"


def _env_text(env_events: Any, env_context: str) -> str:
    ctx = str(env_context or "").strip()
    if ctx:
        return _compact_text(ctx, max_chars=200)
    if isinstance(env_events, (list, tuple)) and env_events:
        bits = []
        for ev in list(env_events)[:3]:
            if isinstance(ev, dict):
                bits.append(str(ev.get("title") or ev.get("summary") or "").strip())
            else:
                bits.append(str(ev).strip())
        joined = "；".join(b for b in bits if b)
        if joined:
            return _compact_text(joined, max_chars=200)
    return "整体平稳，无特别事件"


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = raw.strip("`")
        if "\n" in raw:
            raw = raw.split("\n", 1)[1]
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(raw[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# Digest normalisation
# ---------------------------------------------------------------------------

def _normalize_memories(parsed: dict[str, Any], memory: str, max_items: int) -> list[str]:
    """The step's memory lines: ``memory`` plus any ``highlights`` entries.

    A day yields one line; a month or a year yields several, so the run's
    memory stream stays roughly as dense per simulated *month* whatever the
    step unit is.
    """
    lines: list[str] = [memory] if memory else []
    raw = parsed.get("highlights", [])
    if isinstance(raw, list):
        for item in raw:
            text = _compact_text(str(item or "").strip(), max_chars=60)
            if text and text not in lines:
                lines.append(text)
    return lines[: max(1, int(max_items))]


def _normalize_digest(
    parsed: dict[str, Any],
    *,
    max_delta: float,
    brief_max_chars: int,
    max_memories: int = 1,
    life_move_keys: set[str] | None = None,
    known_tie_keys: set[str] | None = None,
    tie_candidate_keys: set[str] | None = None,
) -> dict[str, Any]:
    brief = _compact_text(str(parsed.get("brief", "")).strip(), max_chars=brief_max_chars)
    memory = _compact_text(str(parsed.get("memory", "")).strip(), max_chars=60)

    changes: dict[str, float] = {}
    raw_changes = parsed.get("state_changes", {})
    if isinstance(raw_changes, dict):
        for key, value in raw_changes.items():
            if key not in LONG_RUN_STATE_KEYS:
                continue
            try:
                delta = float(value)
            except (TypeError, ValueError):
                continue
            changes[key] = max(-max_delta, min(max_delta, delta))

    goal_progress = parsed.get("goal_progress", [])
    if not isinstance(goal_progress, list):
        goal_progress = []

    social: list[dict[str, Any]] = []
    raw_social = parsed.get("social", [])
    if isinstance(raw_social, list):
        for item in raw_social:
            if not isinstance(item, dict):
                continue
            neighbor = item.get("neighbor")
            signal = str(item.get("signal", "neutral")).strip().lower()
            if signal not in ("positive", "negative", "neutral"):
                signal = "neutral"
            if neighbor is not None:
                social.append({"neighbor": neighbor, "signal": signal})

    intentions = parsed.get("intentions", {})
    if not isinstance(intentions, dict):
        intentions = {}

    return {
        "brief": brief,
        "memory": memory,
        "memories": _normalize_memories(parsed, memory, max_memories),
        "state_changes": changes,
        "goal_progress": goal_progress,
        "social": social,
        "life_moves": _normalize_life_moves(parsed.get("life_moves"), life_move_keys or set()),
        "development": _normalize_development(parsed.get("development")),
        "relationships": _normalize_relationship_moves(
            parsed.get("relationships"), known_tie_keys or set()),
        "new_ties": _normalize_new_ties(parsed.get("new_ties"), tie_candidate_keys or set()),
        "intentions": intentions,
    }


def _fallback_digest(
    agent: dict[str, Any],
    *,
    day: int,
    base_schedule: Any,
    brief_max_chars: int,
    burst: bool = False,
    unit: str = "day",
    span_desc: str = "",
) -> dict[str, Any]:
    """Deterministic brief when the LLM is disabled or the call fails."""
    plan = _schedule_text(base_schedule, max_items=4)
    if unit == "day":
        label = f"Day {day}"
        window, span = "这一天", "这一天"
    else:
        label = span_desc or f"{_UNIT_ZH.get(unit, '步')} {day}"
        window = f"这{_UNIT_ZH.get(unit, '段')}"
        span = "这段时间"
    if burst:
        brief = _compact_text(
            f"原计划（{plan}）被计划外的事打断，{span}过得比平时起伏。",
            max_chars=brief_max_chars,
        )
        memory = f"[{label}] 计划外的事打乱了节奏。"
    else:
        brief = _compact_text(
            f"按计划推进了{window}（{plan}），整体节奏平稳，没有特别的波动。",
            max_chars=brief_max_chars,
        )
        memory = f"[{label}] 平稳，按常规节奏推进。"
    return {
        "brief": brief,
        "memory": memory,
        "memories": [memory],
        "state_changes": {},
        "goal_progress": [],
        "social": [],
        "life_moves": [],
        "development": [],
        "relationships": [],
        "new_ties": [],
        "intentions": {},
        "burst": burst,
        "burst_count": 1 if burst else 0,
    }


# ---------------------------------------------------------------------------
# Public: one-call-per-agent daily digest
# ---------------------------------------------------------------------------

_DIGEST_PROMPT = """你是生成式城市模拟中的“单日快进整合器”。请为下面这个人物，把一整天压缩成一份简短的日简报，并给出这一天的近似变化。不要逐时刻展开，只写这一天的概貌。

人物：{name}（id={agent_id}）
日期：Day {day} {day_desc}
今天的计划（作息骨架，供参考，可偏离）：{schedule}
最近的记忆：{recent_memory}
当前状态（0-1）：{state_summary}
人生与阶段目标（带[编号]）：{goals}
熟人：{neighbors}
外部环境：{env}
{burst_hint}
请只输出 JSON（不要额外解释）：
{{
  "brief": "≤{brief_chars}字，这一天的速写：主要做了什么、若有关键事件、心情与感受",
  "memory": "≤30字，今天最值得记住的一条经验或感受",
  "state_changes": {{"emotion": 0.0, "stress": 0.0, "econ_security": 0.0, "city_identity": 0.0}},
  "goal_progress": [{{"id": "stg1", "progress": 0.5, "note": "≤15字推进说明"}}],
  "social": [{{"neighbor": 3, "signal": "positive"}}],
  "intentions": {{"priorities": ["..."], "avoidances": ["..."]}}
}}

要求：
- state_changes 是相对“今天”的增量（-{max_delta}~{max_delta} 之间的小幅变化），只填确有变化的键；键只能取 {state_keys}。
- goal_progress 仅包含今天确有推进或受挫的目标，id 用目标里的[编号]，没有则给 []。
- social 仅列今天真正互动过的熟人及其大致基调（positive/negative/neutral），没有则给 []。
- 基于给定信息，克制、不要编造夸张的大事。仅输出 JSON。
"""


_PERIOD_DIGEST_PROMPT = """你是生成式城市模拟中的“长时段整合器”。请为下面这个人物，把{span_zh}压缩成一份阶段简报，并给出这段时间累计的近似变化。写这段时间的整体轨迹与转折，不要逐日展开。

人物：{name}（id={agent_id}）
处境：{situation}
时间跨度：{span_desc}
之前几个阶段发生了什么：{history}
起始状态（0-1）：{state_summary}
成长档案（技能/兴趣的当前水平）：{growth}
重要关系（含当前亲密度 0-1）：{relations}
人生与阶段目标（带[编号]）：{goals}
外部环境（这段时间的大背景）：{env}
生活底色（他平时大致怎么过日子，仅供参考，不要逐日展开）：{schedule}
可选的人生动作（{span_zh}最多发生 1-2 件，多数时候一件都没有）：{life_moves}
可能结识的人（只能从这里选，没有合适的就不写）：{tie_candidates}
{burst_hint}
请只输出 JSON（不要额外解释）：
{{
  "brief": "≤{brief_chars}字，这段时间的整体经历：主线在做什么、有哪些变化与转折、状态与心境的走向",
  "memory": "≤30字，这段时间最值得记住的一条经验或感受",
  "highlights": ["≤30字的关键事件/里程碑", "..."],
  "state_changes": {{"emotion": 0.0, "stress": 0.0, "econ_security": 0.0, "city_identity": 0.0}},
  "goal_progress": [{{"id": "stg1", "progress": 0.5, "note": "≤15字推进说明"}}],
  "social": [{{"neighbor": 3, "signal": "positive"}}],
  "life_moves": [{{"key": "job_change", "new_job": "可留空", "note": "≤20字原因"}}],
  "development": [{{"item": "阅读", "weekly_minutes": 120, "note": "≤15字进展"}}],
  "relationships": [{{"neighbor": 3, "closeness_delta": 0.12, "note": "≤15字走向"}}],
  "new_ties": [{{"neighbor": 7, "role": "coworker", "note": "≤15字怎么认识的"}}],
  "intentions": {{"priorities": ["..."], "avoidances": ["..."]}}
}}

要求：
- state_changes 是{span_zh}的**累计**增量（-{max_delta}~{max_delta} 之间），只填确有变化的键；键只能取 {state_keys}。
- highlights 给 {highlight_hint} 条，按时间先后排列；平淡无事就给 []。
- goal_progress 仅包含这段时间确有推进或受挫的目标，id 用目标里的[编号]，没有则给 []。
- social 仅列这段时间真正来往过的熟人及其大致基调（positive/negative/neutral），没有则给 []。
- life_moves 是**这段时间真正发生的人生变动**，key 只能从上面的清单里选，最多 2 件，没有就给 []。
  这些 key 会被模拟器真正执行（换工作会改写职业与收入、失业会中断收入），所以**只在简报里确实写了这件事时才填**；
  清单以外的变化写进 brief 与 highlights 即可，不要硬塞进 life_moves。
- development 写**这段时间他在成长档案里的项目上实际投入的程度**：`item` 用档案里的名字，
  `weekly_minutes` 是这段时间**平均每周**投入的分钟数（0 表示搁下了，不必列出）。
  这段时间越长，坚持与荒废的差别越应该体现在这里。
- relationships 写**这段时间关系的净走向**：`closeness_delta` 是亲密度的累计增量
  （-{rel_delta}~{rel_delta}），只写确实变化了的人，`neighbor` 用上面「重要关系」里的编号。
  走近要有来往，变淡通常不需要理由——不写就等于自然疏远。
- new_ties 只在**确实建立了新关系**时写，`neighbor` 只能取「可能结识的人」里的编号，
  role 从 {tie_roles} 中选；一般 0 个，搬家/换工作/入学这类变动之后才可能有 1-2 个。
- 不要逐日展开日程。这个尺度上要写的是：发生了什么事、状态怎么变、
  环境与人际怎么推着他走、他自己长成了什么样。
- 尊重时间尺度：{scale_hint}。基于给定信息推演，不要编造夸张的大事。仅输出 JSON。
"""

_SCALE_HINT = {
    "month": "一个月足够让工作、关系或习惯发生可见的变化，但人生轨迹通常不会被改写",
    "year": "一年可以容纳搬家、换工作、关系变化、健康起落这类真实转折，但仍要与人物的处境和年龄相称",
}


#: Digest keys that name a *life move* rather than a mood swing. Restricted to
#: the life-event templates because those are the moves that actually change
#: the world — a template carries `state_effects`, and the employment ones
#: rewrite `agent["job"]` and redraw income. Anything outside this list would
#: be prose the model never acts on, which is the failure mode this exists to
#: avoid: at month/year granularity "他换了工作" has to mean he changed jobs.
_LIFE_MOVE_NOTE_MAX_CHARS = 20


def life_move_catalog() -> list[dict[str, str]]:
    """The coarse-grained action space: what a person can *do* in a step.

    A day's action space is the intra-day activity list (work, shop, rest); a
    month's or a year's is life moves — change job, fall ill, break up. Read
    from the life-event templates so the menu and the machinery that applies
    it can never drift apart.
    """
    from gaworld.events.life import list_life_event_templates

    catalog: list[dict[str, str]] = []
    for template in list_life_event_templates() or []:
        if not isinstance(template, dict):
            continue
        key = str(template.get("key", "")).strip()
        title = str(template.get("title", "")).strip()
        if not key or not title:
            continue
        catalog.append({
            "key": key,
            "title": title,
            "description": _compact_text(str(template.get("description", "")), max_chars=48),
        })
    return catalog


def _life_move_menu_text(catalog: list[dict[str, str]]) -> str:
    if not catalog:
        return "（无）"
    return "；".join(
        f"{item['key']}={item['title']}（{item['description']}）"
        if item["description"] else f"{item['key']}={item['title']}"
        for item in catalog
    )


#: Roles a newly formed in-sim tie may take. Deliberately narrow: a step
#: digest can plausibly report meeting a colleague or a neighbour, not
#: discovering a sibling.
#: Cap on how far one step may move a single tie's closeness. A year of
#: growing closer is a real change; jumping a stranger to a confidant is not.
_REL_DELTA_CAP = 0.25

NEW_TIE_ROLES: tuple[str, ...] = (
    "acquaintance", "coworker", "friend", "neighbor", "online_friend", "classmate",
)


def _tie_candidates_text(
    agent: dict[str, Any], agents_by_id: dict[Any, dict[str, Any]], max_items: int = 5
) -> tuple[str, set[str]]:
    """Residents this agent does *not* yet know — the only legal new ties.

    Left unconstrained the digest invents neighbours, so a new tie has to be
    picked from people who actually exist in the run and are not already
    connected.
    """
    relationships = agent.get("relationships") or {}
    known = {str(k) for k in relationships} if isinstance(relationships, dict) else set()
    known.add(str(agent.get("id")))
    rows, keys = [], set()
    for aid, other in (agents_by_id or {}).items():
        key = str(aid)
        if key in known or not isinstance(other, dict):
            continue
        keys.add(key)
        rows.append(f"{other.get('name', key)}(#{key}，{other.get('job', '')})".replace("，)", ")"))
        if len(rows) >= max_items:
            break
    if not rows:
        return "（暂无可结识的新对象）", keys
    return "、".join(rows), keys


def _normalize_relationship_moves(
    raw: Any, known_keys: set[str], max_items: int = 6
) -> list[dict[str, Any]]:
    """Closeness trajectories, restricted to ties the agent actually has."""
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("neighbor", "")).strip()
        if not key or key in seen or (known_keys and key not in known_keys):
            continue
        try:
            delta = float(entry.get("closeness_delta", 0) or 0)
        except (TypeError, ValueError):
            continue
        if delta == 0:
            continue
        seen.add(key)
        out.append({
            "neighbor": key,
            "closeness_delta": delta,
            "note": _compact_text(str(entry.get("note", "")).strip(), max_chars=15),
        })
    return out[:max_items]


def _normalize_new_ties(raw: Any, candidate_keys: set[str], max_items: int = 2) -> list[dict[str, Any]]:
    """New acquaintances, restricted to residents who exist and are unknown."""
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("neighbor", "")).strip()
        if not key or key in seen or key not in candidate_keys:
            continue
        role = str(entry.get("role", "")).strip()
        seen.add(key)
        out.append({
            "neighbor": key,
            "role": role if role in NEW_TIE_ROLES else "acquaintance",
            "note": _compact_text(str(entry.get("note", "")).strip(), max_chars=15),
        })
    return out[:max_items]


def _normalize_development(raw: Any, max_items: int = 6) -> list[dict[str, Any]]:
    """Per-item practice intensity for the step, clamped to a sane week.

    ``weekly_minutes`` is the *average week* inside the period, so the caller
    can replay the existing power-law learning curve once per elapsed week
    instead of inventing a second growth model.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("item", "")).strip()
        if not name or name in seen:
            continue
        try:
            minutes = float(entry.get("weekly_minutes", 0) or 0)
        except (TypeError, ValueError):
            continue
        # A week has 10080 minutes; anything past ~20h/week of one pursuit is
        # the model losing the plot, not a person.
        minutes = max(0.0, min(1200.0, minutes))
        if minutes <= 0:
            continue
        seen.add(name)
        out.append({
            "item": name,
            "weekly_minutes": minutes,
            "note": _compact_text(str(entry.get("note", "")).strip(), max_chars=15),
        })
    return out[:max_items]


def _normalize_life_moves(raw: Any, allowed: set[str]) -> list[dict[str, str]]:
    """Whitelist the digest's life moves to keys the simulator can apply."""
    if not isinstance(raw, list):
        return []
    moves: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        if key not in allowed or key in seen:
            continue
        seen.add(key)
        move = {"key": key, "note": _compact_text(
            str(item.get("note", "")).strip(), max_chars=_LIFE_MOVE_NOTE_MAX_CHARS)}
        new_job = str(item.get("new_job", "") or "").strip()[:60]
        if new_job:
            move["new_job"] = new_job
        moves.append(move)
    return moves


def _draw_burst_count(days: int, randomness: float, rng: Any) -> int:
    """How many unplanned events fire across ``days``.

    Expected count is ``_BURST_BASE_CHANCE * r * days``; the fractional part
    is resolved with a single draw. At ``days=1`` this is exactly the
    original per-day coin flip, so day-unit runs are bit-identical.
    """
    try:
        r = max(0.0, min(1.0, float(randomness)))
    except (TypeError, ValueError):
        return 0
    if r <= 0.0:
        return 0
    expected = _BURST_BASE_CHANCE * r * max(1, int(days))
    whole = int(expected)
    if rng.random() < (expected - whole):
        whole += 1
    return min(whole, _MAX_BURSTS)


def _run_digest(
    agent: dict[str, Any],
    *,
    prompt: str,
    task: str,
    max_delta: float,
    brief_max_chars: int,
    max_memories: int,
    llm_fn: Callable[..., str],
    life_move_keys: set[str] | None = None,
    known_tie_keys: set[str] | None = None,
    tie_candidate_keys: set[str] | None = None,
) -> dict[str, Any] | None:
    """One digest call; ``None`` when the response is unusable."""
    try:
        resp = llm_fn(prompt, task=task, agent_id=agent.get("id"))
    except Exception as exc:  # noqa: BLE001 - never let a fast-forward step crash the run
        _LOG.warning("%s LLM call failed for agent %s: %s", task, agent.get("id"), exc)
        resp = ""
    parsed = _parse_json_object(resp)
    if not parsed or not str(parsed.get("brief", "")).strip():
        return None
    return _normalize_digest(
        parsed,
        max_delta=max_delta,
        brief_max_chars=brief_max_chars,
        max_memories=max_memories,
        life_move_keys=life_move_keys,
        known_tie_keys=known_tie_keys,
        tie_candidate_keys=tie_candidate_keys,
    )


def simulate_agent_day(
    agent: dict[str, Any],
    *,
    day: int,
    day_desc: str,
    base_schedule: Any,
    goals_context: str = "无",
    env_events: Any = None,
    env_context: str = "",
    agents_by_id: dict[Any, dict[str, Any]] | None = None,
    config: dict | None = None,
    llm_fn: Callable[..., str] | None = None,
    rng: "_random.Random | None" = None,
) -> dict[str, Any]:
    """Compress one day for one agent into a normalized digest dict.

    Returns keys: ``brief``, ``memory``, ``memories``, ``state_changes``
    (clamped deltas over :data:`LONG_RUN_STATE_KEYS`), ``goal_progress``,
    ``social``, ``intentions``, ``burst`` (whether a randomness-driven
    sudden event fired today). Falls back to a deterministic brief on any
    LLM failure or when ``llm_fn`` is None / ``long_run.brief_llm`` is False.

    ``rng`` (a ``random.Random``) makes the burst roll injectable for tests;
    it defaults to the module RNG so runs honour the global ``random_seed``.
    """
    cfg = long_run_config(config)
    brief_max_chars = _brief_max_chars(cfg)
    max_delta = _max_delta(cfg)
    randomness = randomness_level(config)  # takes the full config, not the unwrapped block
    burst = _draw_burst_count(1, randomness, rng or _random) > 0
    use_llm = bool(cfg.get("brief_llm", True)) and llm_fn is not None

    def _fallback() -> dict[str, Any]:
        return _fallback_digest(
            agent, day=day, base_schedule=base_schedule,
            brief_max_chars=brief_max_chars, burst=burst,
        )

    if not use_llm:
        return _fallback()

    prompt = _DIGEST_PROMPT.format(
        name=agent.get("name", agent.get("id")),
        agent_id=agent.get("id"),
        day=int(day),
        day_desc=str(day_desc or "").strip(),
        schedule=_schedule_text(base_schedule),
        recent_memory=_recent_memory_text(agent),
        state_summary=_state_summary(agent),
        goals=str(goals_context or "无"),
        neighbors=_neighbor_text(agent, agents_by_id or {}),
        env=_env_text(env_events, env_context),
        burst_hint=(_BURST_PROMPT_HINT if burst else ""),
        brief_chars=brief_max_chars,
        max_delta=max_delta,
        state_keys="、".join(LONG_RUN_STATE_KEYS),
    )
    digest = _run_digest(
        agent,
        prompt=prompt,
        task="fast_forward_day",
        max_delta=max_delta,
        brief_max_chars=brief_max_chars,
        max_memories=1,
        llm_fn=llm_fn,
    )
    if digest is None:
        return _fallback()
    digest["burst"] = burst
    digest["burst_count"] = 1 if burst else 0
    return digest


def simulate_agent_period(
    agent: dict[str, Any],
    *,
    period: Period,
    base_schedule: Any,
    day_desc: str = "",
    goals_context: str = "无",
    env_events: Any = None,
    env_context: str = "",
    agents_by_id: dict[Any, dict[str, Any]] | None = None,
    config: dict | None = None,
    llm_fn: Callable[..., str] | None = None,
    rng: "_random.Random | None" = None,
) -> dict[str, Any]:
    """Compress a whole month/year for one agent into one digest.

    Same shape as :func:`simulate_agent_day`, with three differences that
    follow from the wider window: the state-delta cap is scaled by
    :data:`_PERIOD_DELTA_SCALE`, ``memories`` carries several milestone
    lines instead of one, and ``burst_count`` can exceed 1 (a month rarely
    passes without *something* unplanned). A ``day``-unit period is
    delegated to :func:`simulate_agent_day` so callers can stay unit-blind.
    """
    if period.unit == "day":
        return simulate_agent_day(
            agent,
            day=period.end_day,
            day_desc=period.describe(day_desc),
            base_schedule=base_schedule,
            goals_context=goals_context,
            env_events=env_events,
            env_context=env_context,
            agents_by_id=agents_by_id,
            config=config,
            llm_fn=llm_fn,
            rng=rng,
        )

    cfg = long_run_config(config)
    brief_max_chars = _period_brief_max_chars(cfg, period.unit)
    max_delta = max_state_delta_for(period.unit, config)
    randomness = randomness_level(config)
    burst_count = _draw_burst_count(period.days, randomness, rng or _random)
    span_desc = period.describe(day_desc)
    span_zh = "这一个月" if period.unit == "month" else "这一年"
    max_memories = 3 if period.unit == "month" else 5
    # The coarse-grained action space. Only offered for month/year steps: a
    # day's action space is already the intra-day activity list, and changing
    # it there would move the day-unit build off its current behaviour.
    catalog = life_move_catalog()
    life_move_keys = {item["key"] for item in catalog}
    # Social moves are whitelisted the same way: an existing tie can move,
    # and a new tie may only be someone who actually exists in the run.
    _relations = agent.get("relationships") or {}
    known_tie_keys = {str(k) for k in _relations} if isinstance(_relations, dict) else set()
    candidates_text, tie_candidate_keys = _tie_candidates_text(agent, agents_by_id or {})
    use_llm = bool(cfg.get("brief_llm", True)) and llm_fn is not None

    def _fallback() -> dict[str, Any]:
        digest = _fallback_digest(
            agent, day=period.end_day, base_schedule=base_schedule,
            brief_max_chars=brief_max_chars, burst=burst_count > 0,
            unit=period.unit, span_desc=span_desc,
        )
        digest["burst_count"] = burst_count
        return digest

    if not use_llm:
        return _fallback()

    burst_hint = ""
    if burst_count > 0:
        burst_hint = (
            f"【突发】{span_zh}里发生了 {burst_count} 件计划外的事"
            "（可好可坏，如意外开销/机会/冲突/健康/人际或工作变故等）。"
            "请在简报和 highlights 里自然地体现它们，并让相关状态出现明显（但合理）的波动。"
        )
    prompt = _PERIOD_DIGEST_PROMPT.format(
        name=agent.get("name", agent.get("id")),
        agent_id=agent.get("id"),
        span_zh=span_zh,
        span_desc=span_desc,
        schedule=_schedule_text(base_schedule, max_items=4),
        situation=_situation_text(agent),
        history=_period_history_text(agent),
        state_summary=_state_summary(agent),
        growth=_growth_text(agent),
        goals=str(goals_context or "无"),
        relations=_relationship_text(agent, agents_by_id or {}),
        env=_env_text(env_events, env_context),
        life_moves=_life_move_menu_text(catalog),
        tie_candidates=candidates_text,
        tie_roles="/".join(NEW_TIE_ROLES),
        rel_delta=_REL_DELTA_CAP,
        burst_hint=burst_hint,
        brief_chars=brief_max_chars,
        max_delta=round(max_delta, 2),
        state_keys="、".join(LONG_RUN_STATE_KEYS),
        highlight_hint=f"0-{max_memories - 1}",
        scale_hint=_SCALE_HINT.get(period.unit, ""),
    )
    digest = _run_digest(
        agent,
        prompt=prompt,
        task="fast_forward_period",
        max_delta=max_delta,
        brief_max_chars=brief_max_chars,
        max_memories=max_memories,
        llm_fn=llm_fn,
        life_move_keys=life_move_keys,
        known_tie_keys=known_tie_keys,
        tie_candidate_keys=tie_candidate_keys,
    )
    if digest is None:
        return _fallback()
    digest["burst"] = burst_count > 0
    digest["burst_count"] = burst_count
    return digest


# ---------------------------------------------------------------------------
# Public: apply approximate state deltas
# ---------------------------------------------------------------------------

def apply_state_changes(
    agent: dict[str, Any], state_changes: dict[str, float], *, max_delta: float | None = None
) -> dict[str, float]:
    """Apply clamped per-day state deltas in place; return the applied set.

    Only keys already present on the agent's state are touched, and each
    resulting value is clamped to ``[0, 1]``. A ``None`` ``max_delta`` reads
    the configured cap.
    """
    if not isinstance(state_changes, dict):
        return {}
    cap = _max_delta(long_run_config()) if max_delta is None else max(0.0, float(max_delta))
    state = agent.setdefault("state", {})
    applied: dict[str, float] = {}
    for key, delta in state_changes.items():
        if key not in LONG_RUN_STATE_KEYS or not isinstance(state.get(key), (int, float)):
            continue
        try:
            step = max(-cap, min(cap, float(delta)))
        except (TypeError, ValueError):
            continue
        if step == 0.0:
            continue
        state[key] = _clamp01(float(state[key]) + step)
        applied[key] = step
    return applied


def jitter_scale_for(unit: str) -> float:
    """Jitter amplitude multiplier for a step covering one ``unit``."""
    return _PERIOD_JITTER_SCALE.get(unit, 1.0)


def apply_random_jitter(
    agent: dict[str, Any],
    *,
    randomness: float,
    burst: bool = False,
    rng: "_random.Random | None" = None,
    scale: float = 1.0,
) -> dict[str, float]:
    """Add zero-mean stochastic jitter to a few state keys, in place.

    Amplitude scales with ``randomness`` (× :data:`_BURST_JITTER_MULT` on a
    burst day, × ``scale`` for a coarser step unit — see
    :func:`jitter_scale_for`). At ``randomness <= 0`` this is a no-op, so a
    fast-forward step with randomness off stays fully deterministic. Returns
    the applied per-key deltas; every touched value is clamped to ``[0, 1]``.
    """
    try:
        r = max(0.0, min(1.0, float(randomness)))
    except (TypeError, ValueError):
        return {}
    if r <= 0.0:
        return {}
    try:
        span = max(0.0, float(scale))
    except (TypeError, ValueError):
        span = 1.0
    _rng = rng or _random
    amp = _JITTER_SCALE * r * span * (_BURST_JITTER_MULT if burst else 1.0)
    state = agent.setdefault("state", {})
    applied: dict[str, float] = {}
    for key in _JITTER_STATE_KEYS:
        if not isinstance(state.get(key), (int, float)):
            continue
        step = _rng.uniform(-amp, amp)
        if step == 0.0:
            continue
        state[key] = _clamp01(float(state[key]) + step)
        applied[key] = step
    return applied


# ---------------------------------------------------------------------------
# Public: render the day's brief block for console / logs
# ---------------------------------------------------------------------------

def _render_brief_block(
    title: str, desc: str, agent_briefs: list[tuple[str, str]], world_line: str, empty: str
) -> str:
    header = f"\n========== {title} 简报 ({str(desc).strip()}) =========="
    lines = [header]
    if str(world_line or "").strip():
        lines.append(f"🌆 {str(world_line).strip()}")
    for name, brief in agent_briefs:
        text = str(brief or "").strip() or empty
        lines.append(f"• {name}：{text}")
    lines.append("=" * len(header.strip()))
    return "\n".join(lines)


def render_day_brief_block(
    day: int, day_desc: str, agent_briefs: list[tuple[str, str]], world_line: str = ""
) -> str:
    """Build the ``Day N 简报`` block: one line per agent + optional world note."""
    return _render_brief_block(
        f"Day {int(day)}", day_desc, agent_briefs, world_line, "（这一天平稳度过）"
    )


def render_period_brief_block(
    period: Period,
    agent_briefs: list[tuple[str, str]],
    world_line: str = "",
    day_desc: str = "",
) -> str:
    """Build the step's 简报 block, labelled by the period's unit."""
    if period.unit == "day":
        return render_day_brief_block(
            period.end_day, day_desc or period.describe(), agent_briefs, world_line
        )
    return _render_brief_block(
        period.title, period.describe(), agent_briefs, world_line, "（这段时间平稳度过）"
    )


__all__ = [
    "LONG_RUN_STATE_KEYS",
    "LONG_RUN_UNITS",
    "Period",
    "apply_random_jitter",
    "apply_state_changes",
    "hook_chunk_days",
    "jitter_scale_for",
    "life_move_catalog",
    "long_run_config",
    "long_run_enabled",
    "long_run_unit",
    "max_state_delta_for",
    "plan_hook_chunks",
    "plan_horizon",
    "randomness_level",
    "render_day_brief_block",
    "render_period_brief_block",
    "simulate_agent_day",
    "simulate_agent_period",
    "span_days",
]
