"""Prompt-fragment builders extracted from ``generative_city_sim.py``.

Five pure functions that turn agent state into short Chinese prompt
sections used inside daily-routine and decision-stage LLM prompts:

* :func:`_band_label` — bucket a scalar in [0, 1] into a 3-tier label.
* :func:`_state_brief_for_prompt` — multi-line summary of the agent's
  current physiological + emotional state.
* :func:`_yesterday_recap_for_prompt` — 2–3 salient episodes from the
  previous simulation day.
* :func:`_recent_life_events_for_prompt` — recent triggered life events
  that may still be influencing today.
* :func:`_social_pulse_for_prompt` — top relationships with recent
  interactions, ranked by relationship weight.

All functions read agent state and external files but do NOT call the
LLM and do NOT have side effects. Tests access these directly via
``sim.<name>(...)`` so the legacy file re-exports them at their
original positions.
"""

from __future__ import annotations

from typing import Any

from gaworld.cognition.realism import relationship_weight
from gaworld.events.life import list_life_events


def _band_label(
    value: float, low: float, high: float,
    low_text: str, mid_text: str, high_text: str,
) -> str:
    """Categorize a scalar in [0, 1] into a 3-tier human-readable label."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return mid_text
    if v <= low:
        return low_text
    if v >= high:
        return high_text
    return mid_text


def _state_brief_for_prompt(agent: dict[str, Any]) -> str:
    """Return a short Chinese paragraph summarising the agent's current state.

    Reads ``agent['state']`` — emotion, stress, energy, hunger,
    fatigue_debt, time_pressure, self_control, social_need.  Each value is
    bucketed into a coarse band so the prompt language is robust to small
    numeric jitter.
    """
    state = agent.get("state", {}) if isinstance(agent, dict) else {}

    def _get(key, default):
        try:
            return float(state.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    emotion = _get("emotion", 0.5)
    stress = _get("stress", 0.5)
    energy = _get("energy", 0.6)
    hunger = _get("hunger", 0.3)
    fatigue = _get("fatigue_debt", 0.3)
    time_pressure = _get("time_pressure", 0.3)
    self_control = _get("self_control", 0.6)
    social_need = _get("social_need", 0.5)

    lines = [
        f"- 情绪{_band_label(emotion, 0.4, 0.65, '偏低落', '中性', '偏积极')}"
        f"（emotion={emotion:.2f}），"
        f"压力{_band_label(stress, 0.4, 0.65, '较低', '中等', '偏高')}"
        f"（stress={stress:.2f}）",
        f"- 体力{_band_label(energy, 0.35, 0.7, '不足', '一般', '充沛')}"
        f"（energy={energy:.2f}），"
        f"饥饿{_band_label(hunger, 0.3, 0.65, '轻微', '一般', '明显')}"
        f"（hunger={hunger:.2f}）",
        f"- 疲劳{_band_label(fatigue, 0.35, 0.65, '尚可', '一般', '较重')}"
        f"（fatigue_debt={fatigue:.2f}），"
        f"时间紧迫感{_band_label(time_pressure, 0.35, 0.65, '较低', '中等', '偏高')}"
        f"（time_pressure={time_pressure:.2f}）",
        f"- 自控{_band_label(self_control, 0.4, 0.65, '偏弱', '一般', '偏强')}"
        f"（self_control={self_control:.2f}），"
        f"社交需求{_band_label(social_need, 0.4, 0.65, '较低', '中等', '偏高')}"
        f"（social_need={social_need:.2f}）",
    ]
    return "当前身心状态：\n" + "\n".join(lines)


def _yesterday_recap_for_prompt(
    agent: dict[str, Any], day: int | None, top_k: int = 3
) -> str:
    """Surface 2-3 salient events from the previous simulation day.

    When ``day`` is None or the agent has no prior-day episodes, returns a
    short fallback line so the prompt section never becomes ``"None"`` or
    an empty bullet list.
    """
    if day is None:
        return "昨日关键回顾：昨日为模拟首日，无可参考回顾。"
    try:
        prev_day = int(day) - 1
    except (TypeError, ValueError):
        return "昨日关键回顾：昨日为模拟首日，无可参考回顾。"
    if prev_day < 1:
        return "昨日关键回顾：昨日为模拟首日，无可参考回顾。"

    episodes = agent.get("episodes", []) if isinstance(agent, dict) else []
    prev_eps = [
        ep for ep in episodes
        if isinstance(ep, dict) and int(ep.get("day", 0) or 0) == prev_day
    ]
    if not prev_eps:
        return f"昨日关键回顾（Day {prev_day}）：昨日没有显著事件，整体平稳。"

    prev_eps.sort(
        key=lambda e: float(e.get("decayed_salience", e.get("salience", 0.0)) or 0.0),
        reverse=True,
    )
    selected = prev_eps[: max(1, int(top_k))]
    lines = []
    for ep in selected:
        time_str = str(ep.get("time", "")).strip() or "??:??"
        activity = str(ep.get("final_activity", "")).strip() or "—"
        action = str(ep.get("action", "")).strip()
        reflection = str(ep.get("reflection", "")).strip()
        line = f"- {time_str} {activity}"
        if action:
            line += f" → {action}"
        if reflection:
            # Reflections can be long — trim to keep the prompt focused.
            line += f"（{reflection[:40]}）"
        lines.append(line)
    return f"昨日关键回顾（Day {prev_day}）：\n" + "\n".join(lines)


def _recent_life_events_for_prompt(
    agent: dict[str, Any], day: int | None, max_age_days: int = 2
) -> str:
    """Return a section describing recent triggered life events.

    Reads ``output/life_events/events.json`` via :func:`list_life_events`
    (no extra state on the agent dict).  Filters to events that:
      * have been consumed (``status == "consumed"``) — i.e. actually fired,
      * triggered within the last ``max_age_days`` simulation days,
      * either target this agent or are unscoped (``agent_ids`` empty).
    """
    if day is None:
        return "近期突发事件：无。"
    try:
        current_day = int(day)
    except (TypeError, ValueError):
        return "近期突发事件：无。"

    try:
        all_events = list_life_events(include_consumed=True)
    except (OSError, ValueError):
        return "近期突发事件：无。"

    agent_id = agent.get("id") if isinstance(agent, dict) else None
    try:
        agent_id_int = int(agent_id) if agent_id is not None else None
    except (TypeError, ValueError):
        agent_id_int = None

    relevant = []
    for ev in all_events:
        if not isinstance(ev, dict):
            continue
        if ev.get("status") != "consumed":
            continue
        try:
            triggered_day = int(ev.get("triggered_day", 0))
        except (TypeError, ValueError):
            continue
        if triggered_day <= 0:
            continue
        if triggered_day > current_day or current_day - triggered_day > int(max_age_days):
            continue
        if agent_id_int is not None:
            agent_ids = ev.get("agent_ids") or []
            if agent_ids and agent_id_int not in [
                int(x) for x in agent_ids if isinstance(x, (int, float, str)) and str(x).strip().lstrip("-").isdigit()
            ]:
                continue
        relevant.append(ev)

    if not relevant:
        return "近期突发事件：无。"

    relevant.sort(
        key=lambda e: (int(e.get("triggered_day", 0)), str(e.get("triggered_time", ""))),
        reverse=True,
    )
    lines = []
    for ev in relevant[:3]:
        title = str(ev.get("title") or "突发事件").strip()
        desc = str(ev.get("description") or "").strip()
        try:
            severity = float(ev.get("severity", 0.0) or 0.0)
        except (TypeError, ValueError):
            severity = 0.0
        trig_day = int(ev.get("triggered_day", 0))
        trig_time = str(ev.get("triggered_time", "")).strip()
        lines.append(
            f"- Day {trig_day} {trig_time} {title}（严重度 {severity:.2f}）：{desc[:80]}".rstrip()
        )
    return "近期突发事件（仍在影响今天）：\n" + "\n".join(lines)


def _event_aftermath_for_prompt(agent: dict[str, Any], day: int | None = None) -> str:
    """Describe still-active event aftermath as a planning constraint.

    Reads ``agent["event_aftermath"]`` (maintained + decayed at day start by
    the LifeEventsPlugin), so it reflects serious events *beyond* the 2-day
    recency window of :func:`_recent_life_events_for_prompt`. The residual is
    surfaced qualitatively so the planner scales its response to how fresh the
    event still is.
    """
    entries = agent.get("event_aftermath") if isinstance(agent, dict) else None
    if not entries:
        return "事件余波：无。"
    ranked = sorted(entries, key=lambda e: float(e.get("residual", 0.0)), reverse=True)
    lines = []
    for entry in ranked[:3]:
        residual = float(entry.get("residual", 0.0))
        if residual >= 0.5:
            strength = "影响仍然很强"
        elif residual >= 0.3:
            strength = "影响尚在持续"
        else:
            strength = "影响正在消退"
        title = str(entry.get("title", "突发事件")).strip()
        started = entry.get("started_day")
        started_txt = f"Day {int(started)} 起" if isinstance(started, int) else ""
        lines.append(f"- {title}（{started_txt}，{strength}）")
    return (
        "事件余波（近日发生、今天仍需为之调整）：\n"
        + "\n".join(lines)
    )


def _social_pulse_for_prompt(
    agent: dict[str, Any], day: int | None,
    agents_by_id: dict[Any, Any] | None = None,
    max_age_days: int = 2, top_k: int = 3,
) -> str:
    """Pick the top relationships that had recent interactions.

    Ranks by ``relationship_weight`` (already in human_realism), filtered to
    ``last_interaction_day >= day - max_age_days``.  If ``agents_by_id`` is
    provided, we resolve names for friendlier prompt text.
    """
    if day is None:
        return "近期社交脉动：无。"
    try:
        current_day = int(day)
    except (TypeError, ValueError):
        return "近期社交脉动：无。"

    relationships = agent.get("relationships", {}) if isinstance(agent, dict) else {}
    if not isinstance(relationships, dict) or not relationships:
        return "近期社交脉动：无。"

    candidates = []
    for raw_id, item in relationships.items():
        if not isinstance(item, dict):
            continue
        try:
            last_day = int(item.get("last_interaction_day", item.get("last_contact_day", 0)))
        except (TypeError, ValueError):
            continue
        if current_day - last_day > int(max_age_days):
            continue
        try:
            weight = float(relationship_weight(agent, raw_id))
        except (TypeError, ValueError):
            weight = 0.0
        candidates.append((weight, raw_id, item, last_day))

    if not candidates:
        return "近期社交脉动：无。"

    candidates.sort(key=lambda x: x[0], reverse=True)
    lines = []
    for weight, raw_id, item, last_day in candidates[: max(1, int(top_k))]:
        name = None
        if isinstance(agents_by_id, dict):
            peer = agents_by_id.get(raw_id) or agents_by_id.get(str(raw_id))
            if peer is None:
                try:
                    peer = agents_by_id.get(int(raw_id))
                except (TypeError, ValueError):
                    peer = None
            if isinstance(peer, dict):
                name = peer.get("name")
        label = name if name else f"邻居 #{raw_id}"
        closeness = float(item.get("closeness", 0.5))
        trust = float(item.get("trust", 0.5))
        friction = float(item.get("friction", 0.5))
        lines.append(
            f"- {label}（亲密 {closeness:.2f}，信任 {trust:.2f}，"
            f"摩擦 {friction:.2f}，最近互动 Day {last_day}）"
        )
    return "近期社交脉动：\n" + "\n".join(lines)


__all__ = [
    "_band_label",
    "_state_brief_for_prompt",
    "_yesterday_recap_for_prompt",
    "_recent_life_events_for_prompt",
    "_event_aftermath_for_prompt",
    "_social_pulse_for_prompt",
]
