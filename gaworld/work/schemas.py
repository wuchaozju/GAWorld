"""Dataclasses for the real-work subsystem.

These are deliberately plain dataclasses (no pydantic) to match the
project's lightweight dependency profile. They serialise to/from
JSON via ``asdict`` + ``cls(**d)`` round-trip.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional


# ---------------------------------------------------------------------------
# Capability layer
# ---------------------------------------------------------------------------

# Fixed enums keep the LLM from drifting into unroutable values.
JOB_LABELS = (
    "ui_designer",
    "algorithm_engineer",
    "content_creator",
    "teacher_researcher",
    "other",
)

DELIVERABLES = (
    "html_landing",
    "poster_svg",
    "py_script",
    "py_test",
    "md_article",
    "lesson_plan",
    "research_note",
)

ADAPTERS = ("web_design", "code", "content", "teaching")


@dataclass
class AgentCapabilities:
    """LLM-derived structured view of an agent's professional surface."""

    agent_id: int
    job_label: str = "other"
    skills: list[str] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)
    adapter_priority: list[str] = field(default_factory=list)
    notes: str = ""
    source_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentCapabilities":
        return cls(
            agent_id=int(payload.get("agent_id", 0)),
            job_label=str(payload.get("job_label", "other")),
            skills=list(payload.get("skills") or []),
            interests=list(payload.get("interests") or []),
            deliverables=list(payload.get("deliverables") or []),
            adapter_priority=list(payload.get("adapter_priority") or []),
            notes=str(payload.get("notes", "")),
            source_hash=str(payload.get("source_hash", "")),
        )


# ---------------------------------------------------------------------------
# Work brief & result
# ---------------------------------------------------------------------------

@dataclass
class WorkBrief:
    """A unit of work submitted from the simulation to the work queue."""

    task_id: str
    agent_id: int
    sim_day: int
    sim_time: str
    activity: str
    chosen_action: str
    deliverable: str
    adapter: str
    brief_text: str
    estimated_minutes: int
    submitted_at: float
    market_job_id: Optional[str] = None  # set if dispatched via JobMarket
    skill_ids: list[str] = field(default_factory=list)  # skills pasted into brief_text

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkBrief":
        return cls(
            task_id=str(payload["task_id"]),
            agent_id=int(payload["agent_id"]),
            sim_day=int(payload["sim_day"]),
            sim_time=str(payload["sim_time"]),
            activity=str(payload.get("activity", "")),
            chosen_action=str(payload.get("chosen_action", "")),
            deliverable=str(payload["deliverable"]),
            adapter=str(payload["adapter"]),
            brief_text=str(payload.get("brief_text", "")),
            estimated_minutes=int(payload.get("estimated_minutes", 30)),
            submitted_at=float(payload.get("submitted_at", 0.0)),
            market_job_id=payload.get("market_job_id"),
            skill_ids=[str(s) for s in (payload.get("skill_ids") or [])],
        )


WorkStatus = Literal["ok", "failed", "timeout"]


@dataclass
class WorkResult:
    """Outcome of running a WorkBrief through an adapter."""

    task_id: str
    agent_id: int
    status: WorkStatus
    artifact_paths: list[str] = field(default_factory=list)
    summary: str = ""
    error: Optional[str] = None
    finished_at: float = 0.0
    duration_seconds: float = 0.0
    skill_ids: list[str] = field(default_factory=list)  # the brief's skills, as finally run

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkResult":
        return cls(
            task_id=str(payload["task_id"]),
            agent_id=int(payload["agent_id"]),
            status=payload.get("status", "failed"),  # type: ignore[arg-type]
            artifact_paths=list(payload.get("artifact_paths") or []),
            summary=str(payload.get("summary", "")),
            error=payload.get("error"),
            finished_at=float(payload.get("finished_at", 0.0)),
            duration_seconds=float(payload.get("duration_seconds", 0.0)),
            skill_ids=[str(s) for s in (payload.get("skill_ids") or [])],
        )


# ---------------------------------------------------------------------------
# Market layer
# ---------------------------------------------------------------------------

JobStatus = Literal["open", "taken", "done", "failed", "expired"]


@dataclass
class MarketJob:
    """A posted job in the mock market that agents can browse and accept."""

    job_id: str
    title: str
    description: str
    deliverable: str
    required_skills: list[str] = field(default_factory=list)
    required_job_labels: list[str] = field(default_factory=list)
    reward_econ: float = 0.0
    reward_text: str = ""
    posted_sim_day: int = 0
    deadline_sim_day: int = 0
    status: JobStatus = "open"
    taken_by_agent_id: Optional[int] = None
    taken_at_sim_time: Optional[str] = None
    linked_task_id: Optional[str] = None
    source_tag: str = "mock_seed"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MarketJob":
        return cls(
            job_id=str(payload["job_id"]),
            title=str(payload.get("title", "")),
            description=str(payload.get("description", "")),
            deliverable=str(payload.get("deliverable", "")),
            required_skills=list(payload.get("required_skills") or []),
            required_job_labels=list(payload.get("required_job_labels") or []),
            reward_econ=float(payload.get("reward_econ", 0.0)),
            reward_text=str(payload.get("reward_text", "")),
            posted_sim_day=int(payload.get("posted_sim_day", 0)),
            deadline_sim_day=int(payload.get("deadline_sim_day", 0)),
            status=payload.get("status", "open"),  # type: ignore[arg-type]
            taken_by_agent_id=payload.get("taken_by_agent_id"),
            taken_at_sim_time=payload.get("taken_at_sim_time"),
            linked_task_id=payload.get("linked_task_id"),
            source_tag=str(payload.get("source_tag", "mock_seed")),
        )


__all__ = [
    "ADAPTERS",
    "AgentCapabilities",
    "DELIVERABLES",
    "JOB_LABELS",
    "JobStatus",
    "MarketJob",
    "WorkBrief",
    "WorkResult",
    "WorkStatus",
]
