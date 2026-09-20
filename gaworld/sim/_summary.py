"""End-of-simulation summary helpers.

After ``run_simulation()`` finishes, this module is responsible for
producing a per-agent recap and an overall narrative covering the
dimensions the user asked for:

* days run + basic info
* important events (life events + external env events)
* main activities (top-N from episode log)
* state / emotion changes (start vs end + peaks/troughs)
* memory changes (count delta + most recent diary line)
* ability / growth changes (interests level deltas)
* schedule changes (first-day vs last-day diff)
* relationship changes (closeness / trust deltas)
* human-realism qualitative read

Structured data is gathered deterministically from the agent dicts and
``state_history``; the narrative is then produced by a single LLM call
per agent via ``llm_fn``. If ``llm_fn`` is None or the LLM call fails,
the structured block alone is printed.

Public entry point: ``summarize_simulation``.
"""

from __future__ import annotations

import copy
import json
import os
from collections import Counter
from typing import Any, Callable

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.sim.summary")

# Type aliases for readability.
_Agent = dict[str, Any]
_Snapshot = dict[str, Any]


# ---------------------------------------------------------------------------
# Snapshot taken at simulation start. Captured early so we can diff against
# the agent's end-of-run state.
# ---------------------------------------------------------------------------

def take_initial_snapshot(agent: _Agent, schedule: list[Any] | None = None) -> _Snapshot:
    """Capture the bits of agent state we need to diff at the end."""
    state = agent.get("state", {}) or {}
    growth = agent.get("growth_profile", {}) or {}
    relationships = agent.get("relationships", {}) or {}
    return {
        "state": {k: float(v) for k, v in state.items() if isinstance(v, (int, float))},
        "schedule": copy.deepcopy(schedule) if schedule is not None else [],
        "memory_count": len(agent.get("memory", []) or []),
        "episodes_count": len(agent.get("episodes", []) or []),
        "growth_profile": copy.deepcopy(growth),
        "relationships": {
            str(k): {
                "closeness": float(v.get("closeness", 0.0) or 0.0),
                "trust": float(v.get("trust", 0.0) or 0.0),
            }
            for k, v in relationships.items()
            if isinstance(v, dict)
        },
    }


# ---------------------------------------------------------------------------
# Per-agent extraction helpers — each one is a pure function over data
# already in memory at end-of-sim.
# ---------------------------------------------------------------------------

def _top_activities(agent: _Agent, start_day: int, end_day: int, top_n: int = 5) -> list[tuple[str, int]]:
    """Count activities from episode log within the sim's day range."""
    counter: Counter[str] = Counter()
    for ep in agent.get("episodes", []) or []:
        try:
            day = int(ep.get("day", ep.get("created_at_day", 0)) or 0)
        except (TypeError, ValueError):
            continue
        if day < start_day or day > end_day:
            continue
        name = str(ep.get("final_activity") or ep.get("activity") or "").strip()
        if name:
            counter[name] += 1
    return counter.most_common(top_n)


def _state_deltas(
    initial: _Snapshot, agent: _Agent, history: dict[str, list[float]] | None
) -> dict[str, dict[str, float]]:
    """Return {metric: {start, end, min, max, delta}} for each state key."""
    out: dict[str, dict[str, float]] = {}
    end_state = agent.get("state", {}) or {}
    init_state = initial.get("state", {}) or {}
    keys = set(init_state) | {k for k, v in end_state.items() if isinstance(v, (int, float))}
    for k in sorted(keys):
        start = float(init_state.get(k, 0.0) or 0.0)
        end = float(end_state.get(k, 0.0) or 0.0)
        series = (history or {}).get(k) or []
        floats = [float(x) for x in series if isinstance(x, (int, float))]
        out[k] = {
            "start": start,
            "end": end,
            "delta": end - start,
            "min": min(floats) if floats else end,
            "max": max(floats) if floats else end,
        }
    return out


def _growth_diff(initial: _Snapshot, agent: _Agent) -> list[dict[str, Any]]:
    """Return growth items whose level/minutes changed during the run.

    Reads the actual ``GrowthProfile`` schema: ``items`` with float
    ``level`` (0-1) and int ``total_minutes``.
    """
    before = (initial.get("growth_profile") or {}).get("items", []) or []
    after = (agent.get("growth_profile") or {}).get("items", []) or []
    before_by_name = {str(it.get("name") or ""): it for it in before if isinstance(it, dict)}
    diffs: list[dict[str, Any]] = []
    for item in after:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        prev = before_by_name.get(name, {})
        prev_level = float(prev.get("level", 0.0) or 0.0)
        new_level = float(item.get("level", 0.0) or 0.0)
        prev_min = float(prev.get("total_minutes", 0.0) or 0.0)
        new_min = float(item.get("total_minutes", 0.0) or 0.0)
        if abs(new_level - prev_level) >= 0.005 or new_min - prev_min >= 1.0:
            diffs.append(
                {
                    "name": name,
                    "level_from": round(prev_level, 3),
                    "level_to": round(new_level, 3),
                    "minutes_gained": round(new_min - prev_min, 1),
                }
            )
    diffs.sort(key=lambda d: (d["level_to"] - d["level_from"], d["minutes_gained"]), reverse=True)
    return diffs


def _relationship_deltas(initial: _Snapshot, agent: _Agent, top_n: int = 5) -> list[dict[str, Any]]:
    """Return relationships whose closeness/trust shifted most."""
    before = initial.get("relationships", {}) or {}
    after = agent.get("relationships", {}) or {}
    rows: list[dict[str, Any]] = []
    for key, cur in after.items():
        if not isinstance(cur, dict):
            continue
        prev = before.get(str(key), {})
        d_close = float(cur.get("closeness", 0.0) or 0.0) - float(prev.get("closeness", 0.0) or 0.0)
        d_trust = float(cur.get("trust", 0.0) or 0.0) - float(prev.get("trust", 0.0) or 0.0)
        if abs(d_close) < 0.02 and abs(d_trust) < 0.02:
            continue
        rows.append(
            {
                "neighbor": str(key),
                "closeness_delta": round(d_close, 3),
                "trust_delta": round(d_trust, 3),
            }
        )
    rows.sort(key=lambda r: abs(r["closeness_delta"]) + abs(r["trust_delta"]), reverse=True)
    return rows[:top_n]


def _schedule_changed(initial: _Snapshot, end_schedule: list[Any]) -> bool:
    return list(initial.get("schedule") or []) != list(end_schedule or [])


def _life_events_in_range(life_events: list[dict[str, Any]], agent_id: int) -> list[str]:
    out: list[str] = []
    for ev in life_events or []:
        ids = ev.get("agent_ids") or []
        if ids and agent_id not in [int(x) for x in ids if str(x).strip().lstrip("-").isdigit()]:
            continue
        title = str(ev.get("title") or "").strip()
        desc = str(ev.get("description") or "").strip()
        if title or desc:
            out.append(f"{title}: {desc}".strip(": ").strip())
    return out


def _env_event_titles(env_timeline_path: str | None, max_items: int = 8) -> list[str]:
    """Pull a small set of representative external-env event lines."""
    if not env_timeline_path or not os.path.exists(env_timeline_path):
        return []
    titles: list[str] = []
    try:
        with open(env_timeline_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                events = row.get("events") or []
                for ev in events:
                    if not isinstance(ev, dict):
                        continue
                    title = str(ev.get("title") or ev.get("summary") or "").strip()
                    if title and title not in titles:
                        titles.append(title)
                        if len(titles) >= max_items:
                            return titles
    except OSError:
        return titles
    return titles


# ---------------------------------------------------------------------------
# Per-agent payload + console rendering.
# ---------------------------------------------------------------------------

def _build_agent_payload(
    agent: _Agent,
    initial: _Snapshot,
    state_history: dict[str, list[float]] | None,
    start_day: int,
    end_day: int,
    life_events: list[dict[str, Any]] | None,
    env_event_titles: list[str],
) -> dict[str, Any]:
    schedule_now = agent.get("schedule") or []
    return {
        "id": agent.get("id"),
        "name": agent.get("name", str(agent.get("id"))),
        "days_run": max(0, end_day - start_day + 1),
        "top_activities": _top_activities(agent, start_day, end_day),
        "state_deltas": _state_deltas(initial, agent, state_history),
        "growth_changes": _growth_diff(initial, agent),
        "relationship_changes": _relationship_deltas(initial, agent),
        "schedule_changed": _schedule_changed(initial, schedule_now),
        "memory_count_delta": len(agent.get("memory", []) or []) - int(initial.get("memory_count", 0)),
        "episodes_count_delta": len(agent.get("episodes", []) or []) - int(initial.get("episodes_count", 0)),
        "recent_diary": _recent_diary_line(agent),
        "life_events": _life_events_in_range(life_events or [], int(agent.get("id", 0))),
        "env_event_titles": env_event_titles,
    }


def _recent_diary_line(agent: _Agent) -> str:
    memory = agent.get("memory", []) or []
    for entry in reversed(memory):
        text = str(entry or "").strip()
        if text:
            return text[:240]
    return ""


def _format_agent_block(payload: dict[str, Any]) -> str:
    lines = [f"\n── 智能体 {payload['name']} (id={payload['id']}) ──"]
    lines.append(f"运行 {payload['days_run']} 天")
    activities = payload.get("top_activities") or []
    if activities:
        joined = "、".join(f"{name}×{count}" for name, count in activities)
        lines.append(f"主要活动：{joined}")
    state_lines = []
    for key, info in (payload.get("state_deltas") or {}).items():
        state_lines.append(
            f"{key} {info['start']:.2f}→{info['end']:.2f} "
            f"(Δ{info['delta']:+.2f}, 区间 {info['min']:.2f}-{info['max']:.2f})"
        )
    if state_lines:
        lines.append("状态/情绪：" + "；".join(state_lines))
    growth = payload.get("growth_changes") or []
    if growth:
        joined = "、".join(
            f"{g['name']} L{g['level_from']}→L{g['level_to']}(+{g['minutes_gained']}分钟)"
            for g in growth[:5]
        )
        lines.append(f"能力/成长：{joined}")
    rel = payload.get("relationship_changes") or []
    if rel:
        joined = "、".join(
            f"#{r['neighbor']} 亲密{r['closeness_delta']:+.2f}/信任{r['trust_delta']:+.2f}"
            for r in rel
        )
        lines.append(f"关系变化：{joined}")
    lines.append(
        f"记忆新增 {payload['memory_count_delta']} 条；"
        f"经历新增 {payload['episodes_count_delta']} 条；"
        f"日程{'有调整' if payload['schedule_changed'] else '保持不变'}"
    )
    if payload.get("life_events"):
        lines.append("人生事件：" + "；".join(payload["life_events"][:4]))
    if payload.get("recent_diary"):
        lines.append(f"最近记忆：{payload['recent_diary']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM narrative — single call per agent, asks for the dimensions the user
# explicitly requested.
# ---------------------------------------------------------------------------

_NARRATIVE_PROMPT = """你正在为一次生成式智能体仿真撰写总结。请只用中文，以连贯的段落（不要使用要点列表）描述这个智能体在本次仿真中的整体情况，覆盖：

1. 运行了多少天、整体节奏。
2. 发生了哪些重要的事情（外部环境事件、人生事件、明显的活动调整）。
3. 主要做了什么事（高频活动、值得一提的行为）。
4. 情绪和状态的变化（哪些指标上升/下降，是否出现明显波动）。
5. 能力/成长的变化（兴趣或技能的累计、等级变化）。
6. 记忆和日程的变化（新增了多少记忆，日程是否被打破）。
7. 关系变化（亲密度/信任度的明显波动）。
8. 这个智能体此次表现出的"真实人类感"如何——哪些地方像真人，哪些地方还显得机械。

要求：
- 客观、克制，基于下面的结构化数据，不要编造未提及的事件。
- 总长 200–350 字。
- 不要使用项目符号或编号，写成自然段落。

智能体：{name} (id={agent_id})
结构化数据（JSON）：
{payload_json}
"""


def _llm_narrative(payload: dict[str, Any], llm_fn: Callable[..., str] | None) -> str:
    if llm_fn is None:
        return ""
    prompt = _NARRATIVE_PROMPT.format(
        name=payload.get("name", ""),
        agent_id=payload.get("id", ""),
        payload_json=json.dumps(payload, ensure_ascii=False, indent=2),
    )
    try:
        text = llm_fn(prompt, task="sim_summary", agent_id=payload.get("id"))
    except Exception as exc:  # noqa: BLE001 - never let summary crash the run
        _LOG.warning("sim summary LLM call failed for %s: %s", payload.get("name"), exc)
        return ""
    return str(text or "").strip()


# ---------------------------------------------------------------------------
# Public entry point — invoked at the very end of ``run_simulation``.
# ---------------------------------------------------------------------------

def summarize_simulation(
    agents: list[_Agent],
    initial_snapshots: dict[int, _Snapshot],
    state_history: dict[int, dict[str, list[float]]] | None,
    start_day: int,
    end_day: int,
    *,
    life_events: list[dict[str, Any]] | None = None,
    env_timeline_path: str | None = None,
    llm_fn: Callable[..., str] | None = None,
) -> None:
    """Print a multi-agent end-of-simulation summary to the console."""
    header = (
        f"\n============================================================\n"
        f"📊 仿真总结  (Day {start_day} → Day {end_day}, 共 {max(0, end_day - start_day + 1)} 天, "
        f"{len(agents)} 个智能体)\n"
        f"============================================================"
    )
    print(header)

    env_titles = _env_event_titles(env_timeline_path)
    if env_titles:
        print("外部环境关键事件：" + "；".join(env_titles))

    for agent in agents:
        try:
            snap = initial_snapshots.get(int(agent.get("id", -1))) or take_initial_snapshot(agent)
            history = (state_history or {}).get(agent.get("id")) if state_history else None
            payload = _build_agent_payload(
                agent,
                snap,
                history,
                start_day,
                end_day,
                life_events,
                env_titles,
            )
            print(_format_agent_block(payload))
            narrative = _llm_narrative(payload, llm_fn)
            if narrative:
                print("叙述：" + narrative)
        except Exception as exc:  # noqa: BLE001 - never abort the run on summary error
            _LOG.warning("summary block failed for agent %s: %s", agent.get("id"), exc)

    print("============================================================\n")


__all__ = ["take_initial_snapshot", "summarize_simulation"]
