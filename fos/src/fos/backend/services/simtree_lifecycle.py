"""SimTree GAWorld branch lifecycle helpers (Phase 8).

Owns the request-level guards (branch cap, branch-day budget) and the
lifecycle vocabulary shared by the advance routes and the frontend:

- RUNTIME_STATUSES / TERMINAL_STATUSES: the full set of runtime_status
  values a node meta can carry.
- validate_branch_request / validate_branch_day_budget: reject over-cap or
  over-budget advance_multi requests BEFORE any node is created or any
  subprocess is launched, with requested-vs-max/allowed in the error.
- resolve_terminal_outcome: arbitrate the timeout-vs-finish race so exactly
  one terminal outcome is recorded.
- isolate_branch_failure: record one branch's failure on that branch only,
  so siblings are never affected.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Maximum GAWorld branches allowed per advance_multi request.
MAX_GAWORLD_BRANCHES_PER_REQUEST = 8

RUNTIME_STATUSES: tuple[str, ...] = (
    "queued",
    "running",
    "completed",
    "cancelled",
    "failed",
    "timed_out",
    "attention_required",
)

TERMINAL_STATUSES: tuple[str, ...] = (
    "completed",
    "cancelled",
    "failed",
    "timed_out",
)


class BranchRequestError(ValueError):
    """A branch request was refused before anything was created/launched."""


class BranchDayBudgetError(BranchRequestError):
    """The requested additional days exceed the configured budget."""


def validate_branch_request(count: int, max_branches: int = MAX_GAWORLD_BRANCHES_PER_REQUEST) -> None:
    """Reject over-cap branch requests before creating/launching anything.

    Within-cap and exactly-at-cap requests pass; there is no silent
    truncation.
    """
    count = int(count)
    max_branches = int(max_branches)
    if count > max_branches:
        raise BranchRequestError(
            f"too many GAWorld branches requested: requested {count} branches "
            f"but the maximum per request is {max_branches}"
        )


def validate_branch_day_budget(requested_days: int, allowed: int) -> None:
    """Reject requests whose summed additional days exceed the budget.

    Runs BEFORE launch, so a refusal launches zero subprocesses.
    """
    requested_days = int(requested_days)
    allowed = int(allowed)
    if requested_days > allowed:
        raise BranchDayBudgetError(
            f"branch day budget exceeded: requested {requested_days} additional "
            f"days but only {allowed} are allowed"
        )


def resolve_terminal_outcome(first: str | None, second: str | None = None) -> tuple[str | None, None]:
    """Arbitrate a terminal-outcome race (e.g. timeout vs normal finish).

    Returns ``(winner, None)``: exactly one terminal outcome is recorded —
    the first terminal status wins, a non-terminal first status is replaced
    by the terminal one, and the second slot is always ``None`` so callers
    can never record two competing outcomes.
    """
    if first in TERMINAL_STATUSES:
        return first, None
    if second in TERMINAL_STATUSES:
        return second, None
    return first or second, None


def isolate_branch_failure(node: dict, error: BaseException | str | None, *, status: str = "failed") -> dict:
    """Record one branch's failure on that branch only; siblings untouched."""
    meta = node.setdefault("meta", {})
    message = str(error) if error is not None else "unknown branch failure"
    meta["runtime_status"] = status if status in RUNTIME_STATUSES else "failed"
    meta["runtime_error"] = message
    logger.warning("branch failure isolated: status=%s error=%s", meta["runtime_status"], message)
    return node


def mark_node_cancelled(node: dict, reason: str = "cancelled") -> dict:
    """Mark a tree node cancelled (terminal); never a recovery action."""
    meta = node.setdefault("meta", {})
    meta["runtime_status"] = "cancelled"
    meta["runtime_error"] = reason
    return node


def release_slots(slots: list[Any]) -> None:
    """Release semaphore slots defensively (double release tolerated)."""
    for slot in slots or []:
        try:
            slot.release()
        except (ValueError, AttributeError):
            pass
