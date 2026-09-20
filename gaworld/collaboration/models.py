from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class SessionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


ALLOWED_TRANSITIONS = {
    SessionStatus.QUEUED: {SessionStatus.RUNNING, SessionStatus.CANCELLED},
    SessionStatus.RUNNING: {
        SessionStatus.PAUSED,
        SessionStatus.COMPLETED,
        SessionStatus.CANCELLED,
        SessionStatus.FAILED,
        SessionStatus.INTERRUPTED,
    },
    SessionStatus.PAUSED: {SessionStatus.RUNNING, SessionStatus.CANCELLED},
    SessionStatus.FAILED: {SessionStatus.RUNNING, SessionStatus.CANCELLED},
    SessionStatus.INTERRUPTED: {SessionStatus.RUNNING, SessionStatus.CANCELLED},
    SessionStatus.COMPLETED: set(),
    SessionStatus.CANCELLED: set(),
}


@dataclass(slots=True)
class CollaborationSession:
    id: str
    kind: str
    member_ids: list[int]
    status: SessionStatus = SessionStatus.QUEUED
    title: str = ""
    topic: str = ""
    task: str = ""
    leader_id: int | None = None
    role_overrides: dict[str, str] = field(default_factory=dict)
    roles: dict[str, str] = field(default_factory=dict)
    max_rounds: int = 6
    current_round: int = 0
    current_step: int = 0
    plan: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def new(cls, *, kind: str, member_ids: list[int], **values: Any) -> CollaborationSession:
        return cls(
            id=f"cs_{datetime.now(UTC):%Y%m%d}_{uuid4().hex[:10]}",
            kind=kind,
            member_ids=list(member_ids),
            **values,
        )

    def transition(self, target: SessionStatus) -> None:
        if target not in ALLOWED_TRANSITIONS[self.status]:
            raise ValueError(f"invalid session transition: {self.status} -> {target}")
        self.status = target
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CollaborationSession:
        values = dict(payload)
        values["status"] = SessionStatus(values["status"])
        return cls(**values)


@dataclass(frozen=True, slots=True)
class SessionEvent:
    seq: int
    type: str
    timestamp: str
    content: str = ""
    agent_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
