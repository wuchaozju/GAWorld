"""Shared run-status model and failure-isolation primitives.

Every worldrun launch — and both adapters (parallel worlds, SimTree) — speak
these statuses. Adapters translate to their user-facing vocabulary; the
internal model is exactly this set. Failure isolation is structural: each
handle owns its own status and output dir, so one failed world can never
cancel or fail a sibling.
"""

from __future__ import annotations

#: The shared status model. Nothing outside this set is ever reported.
STATUSES = frozenset({"created", "running", "completed", "failed", "cancelled", "timed_out"})

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "timed_out"})


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


def failure_status(returncode: int | None, *, timed_out: bool = False) -> str:
    """Map an exit condition onto the shared status model."""
    if timed_out:
        return "timed_out"
    if returncode is None:
        return "failed"
    return "completed" if returncode == 0 else "failed"


__all__ = ["STATUSES", "TERMINAL_STATUSES", "failure_status", "is_terminal"]
