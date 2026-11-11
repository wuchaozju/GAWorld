"""Bounded invitations during long awake silences; no forced relocation or consent."""

from __future__ import annotations

from typing import Any

VERSION = "invitation-1"
IDLE_MINUTES = 120
COOLDOWN_MINUTES = 90
BUSY = {"睡觉", "午睡", "睡前阅读", "处理工作邮件", "看书", "写日记", "练琴", "画一会儿画", "洗澡"}


def invite(session: Any) -> tuple[Any, Any, str] | None:
    now = session.virtual_clock_minutes
    if not 7 <= (now // 60) % 24 < 21 or session.pending_tick is not None:
        return None
    recent = [
        session.opening_clock_minutes + e.tick * getattr(session, "tick_minutes", 5)
        for e in session.events
        if e.kind == "interact" and e.dialogue and not e.note.startswith("fallback")
    ]
    if now - max(recent, default=session.opening_clock_minutes) < IDLE_MINUTES:
        return None
    if now - getattr(session, "engagement_last_attempt", 0) < COOLDOWN_MINUTES:
        return None
    people = [r for r in session.residents if r.activity not in BUSY]
    if len(people) < 2:
        return None
    session.engagement_last_attempt = now
    # Least-recent pair first. No random model call for scheduling.
    pairs = [(a, b) for i, a in enumerate(people) for b in people[i + 1 :]]

    def latest(pair: tuple[Any, Any]) -> int:
        ids = {r.agent_id for r in pair}
        return max(
            (e.tick for e in session.events if e.kind == "interact" and set(e.actor_ids) == ids), default=-1
        )

    a, b = min(pairs, key=latest)
    return a, b, a.room
