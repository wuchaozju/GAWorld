"""In-memory runtime task status and error visibility."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeTask:
    id: str
    kind: str
    status: str
    label: str
    started_at: float
    updated_at: float
    finished_at: float | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def serialize(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "label": self.label,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "metadata": dict(self.metadata),
        }


class RuntimeTaskRegistry:
    """Small task registry for visibility; durable state remains in DB models."""

    def __init__(self, max_recent: int = 100) -> None:
        self._tasks: dict[str, RuntimeTask] = {}
        self._max_recent = max_recent

    def start(
        self,
        kind: str,
        label: str,
        *,
        task_id: str | None = None,
        status: str = "running",
        metadata: dict[str, Any] | None = None,
    ) -> RuntimeTask:
        now = time.time()
        task = RuntimeTask(
            id=task_id or f"{kind}:{uuid.uuid4().hex}",
            kind=kind,
            status=status,
            label=label,
            started_at=now,
            updated_at=now,
            metadata=dict(metadata or {}),
        )
        self._tasks[task.id] = task
        self._trim_completed()
        return task

    def mark_running(self, task_id: str, metadata: dict[str, Any] | None = None) -> None:
        self.update(task_id, status="running", metadata=metadata)

    def finish(self, task_id: str, metadata: dict[str, Any] | None = None) -> None:
        now = time.time()
        self.update(
            task_id,
            status="finished",
            metadata=metadata,
            finished_at=now,
            error=None,
        )

    def fail(self, task_id: str, error: BaseException | str, metadata: dict[str, Any] | None = None) -> None:
        now = time.time()
        self.update(
            task_id,
            status="error",
            metadata=metadata,
            finished_at=now,
            error=str(error),
        )

    def cancel(self, task_id: str, metadata: dict[str, Any] | None = None) -> None:
        now = time.time()
        self.update(
            task_id,
            status="cancelled",
            metadata=metadata,
            finished_at=now,
            error=None,
        )

    def update(
        self,
        task_id: str,
        *,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
        finished_at: float | None = None,
        error: str | None = None,
    ) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        task.updated_at = time.time()
        if status is not None:
            task.status = status
        if metadata:
            task.metadata.update(metadata)
        if finished_at is not None:
            task.finished_at = finished_at
        if error is not None:
            task.error = error
        elif status == "finished":
            task.error = None
        self._trim_completed()

    def active_count(self) -> int:
        return sum(1 for task in self._tasks.values() if task.status in {"queued", "running"})

    def snapshot(self, limit: int = 20) -> dict[str, Any]:
        tasks = sorted(self._tasks.values(), key=lambda task: task.updated_at, reverse=True)
        return {
            "active": self.active_count(),
            "recent": [task.serialize() for task in tasks[:limit]],
        }

    def clear(self) -> None:
        self._tasks.clear()

    def _trim_completed(self) -> None:
        if len(self._tasks) <= self._max_recent:
            return
        completed = [
            task
            for task in self._tasks.values()
            if task.status not in {"queued", "running"}
        ]
        completed.sort(key=lambda task: task.updated_at)
        overflow = len(self._tasks) - self._max_recent
        for task in completed[:overflow]:
            self._tasks.pop(task.id, None)


RUNTIME_TASKS = RuntimeTaskRegistry()
