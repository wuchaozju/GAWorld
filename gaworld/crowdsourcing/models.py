"""Data model for swarm crowdsourcing sessions.

A crowd session is not a collaboration session: nobody is given a role and
nobody talks to anybody. A task goes to a *pool* of residents, they answer it
independently, a judge scores the answers, and the pool is narrowed towards
the agents that did well. The session keeps the whole trajectory (bids,
attempts, scores, survivors) so an observer can see *why* the crowd converged
on an answer instead of only seeing the answer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class CrowdStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


ALLOWED_TRANSITIONS = {
    # A crowd session can be paused before its worker thread has even picked
    # it up, so ``queued -> paused`` has to be legal — otherwise a pause in
    # that window raises instead of pausing.
    CrowdStatus.QUEUED: {
        CrowdStatus.RUNNING,
        CrowdStatus.PAUSED,
        CrowdStatus.CANCELLED,
    },
    CrowdStatus.RUNNING: {
        CrowdStatus.PAUSED,
        CrowdStatus.COMPLETED,
        CrowdStatus.CANCELLED,
        CrowdStatus.FAILED,
        CrowdStatus.INTERRUPTED,
    },
    CrowdStatus.PAUSED: {CrowdStatus.RUNNING, CrowdStatus.CANCELLED},
    CrowdStatus.FAILED: {CrowdStatus.RUNNING, CrowdStatus.CANCELLED},
    CrowdStatus.INTERRUPTED: {CrowdStatus.RUNNING, CrowdStatus.CANCELLED},
    CrowdStatus.COMPLETED: set(),
    CrowdStatus.CANCELLED: set(),
}


@dataclass(slots=True)
class CrowdSession:
    """One crowdsourced task and everything observed while it ran."""

    id: str
    task: str
    strategy: str
    agent_ids: list[int]
    rounds: int = 3
    participants_per_round: int = 5
    criteria: str = ""
    title: str = ""
    prune: dict[str, Any] = field(default_factory=dict)
    status: CrowdStatus = CrowdStatus.QUEUED
    current_round: int = 0
    round_summaries: list[dict[str, Any]] = field(default_factory=list)
    leaderboard: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str = ""
    final_agent_id: int | None = None
    final_method: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def new(
        cls,
        *,
        task: str,
        strategy: str,
        agent_ids: list[int],
        **values: Any,
    ) -> CrowdSession:
        return cls(
            id=f"cw_{datetime.now(UTC):%Y%m%d}_{uuid4().hex[:10]}",
            task=task,
            strategy=strategy,
            agent_ids=list(agent_ids),
            **values,
        )

    def transition(self, target: CrowdStatus) -> None:
        if target not in ALLOWED_TRANSITIONS[self.status]:
            raise ValueError(f"invalid session transition: {self.status} -> {target}")
        self.status = target
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CrowdSession:
        values = dict(payload)
        values["status"] = CrowdStatus(values["status"])
        return cls(**values)


@dataclass(frozen=True, slots=True)
class CrowdEvent:
    """One line of the session's live feed."""

    seq: int
    type: str
    timestamp: str
    content: str = ""
    agent_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
