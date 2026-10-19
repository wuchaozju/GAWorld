"""Adapter base class — turn a WorkBrief into artifacts on disk."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

from gaworld.work.schemas import WorkBrief, WorkResult

LlmFn = Callable[[str], str]


@dataclass
class AdapterContext:
    """Runtime injection so adapters don't reach for globals."""

    artifacts_root: str          # e.g. "output/work"
    llm: LlmFn                   # call_llm wrapper; tests pass a stub
    config: dict                 # adapter-specific config block

    def task_dir(self, brief: WorkBrief) -> str:
        path = os.path.join(
            self.artifacts_root,
            f"agent_{brief.agent_id}",
            brief.task_id,
        )
        os.makedirs(path, exist_ok=True)
        return path


class WorkAdapter(Protocol):
    """A work adapter implementation contract."""

    name: str
    supported_deliverables: frozenset[str]

    def run(self, brief: WorkBrief, ctx: AdapterContext) -> WorkResult: ...


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_failed(brief: WorkBrief, error: str, started_at: float) -> WorkResult:
    return WorkResult(
        task_id=brief.task_id,
        agent_id=brief.agent_id,
        status="failed",
        artifact_paths=[],
        summary="",
        error=error[:400],
        finished_at=time.time(),
        duration_seconds=max(0.0, time.time() - started_at),
        skill_ids=list(brief.skill_ids),
    )


def make_ok(
    brief: WorkBrief,
    artifact_paths: Iterable[str],
    summary: str,
    started_at: float,
) -> WorkResult:
    return WorkResult(
        task_id=brief.task_id,
        agent_id=brief.agent_id,
        status="ok",
        artifact_paths=list(artifact_paths),
        summary=summary[:400],
        error=None,
        finished_at=time.time(),
        duration_seconds=max(0.0, time.time() - started_at),
        skill_ids=list(brief.skill_ids),
    )


__all__ = ["AdapterContext", "LlmFn", "WorkAdapter", "make_failed", "make_ok"]
