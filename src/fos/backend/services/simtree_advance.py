"""Helpers for running one simulation tree step.

run_simulator_for_advance runs a simulator and returns runtime problems instead
of hiding them, so the caller can still show the node logs to the user.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fos.backend.services.readable_errors import make_readable_error


logger = logging.getLogger(__name__)


async def run_simulator_for_advance(
    simulator: Any,
    max_turns: int,
) -> RuntimeError | FileNotFoundError | None:
    """Run a simulator step and return user-visible runtime failures."""
    try:
        await asyncio.to_thread(simulator.run, max_turns=max_turns)
    except (RuntimeError, FileNotFoundError) as error:
        logger.exception("simulation runtime failed during tree advance")
        return error
    runtime_error = getattr(simulator, "last_runtime_error", None)
    if isinstance(runtime_error, RuntimeError):
        return runtime_error
    return None


def get_advance_turn_count(simulator: Any, requested_turns: int) -> int:
    """Return runtime turns for legacy simulators and experiment adapters."""
    try:
        from fos.backend.services.simtree_runtime import ExperimentRunnerAdapter

        if isinstance(simulator, ExperimentRunnerAdapter):
            return max(1, int(requested_turns))
    except Exception:
        logger.exception("failed to inspect simulator type for turn count")
    agents = getattr(simulator, "agents", {}) or {}
    return max(1, int(requested_turns)) * max(1, len(agents))


def record_advance_runtime_failure(
    node: dict,
    simulator: Any,
    error: RuntimeError | FileNotFoundError,
) -> str:
    """Store a user-visible runtime failure on a tree node and its logs."""
    raw_message = str(error)
    readable = make_readable_error(raw_message)
    message = readable["message"]
    meta = node.setdefault("meta", {})
    meta["runtime_status"] = "failed"
    meta["runtime_error"] = raw_message
    meta["runtime_error_readable"] = message
    meta["runtime_error_category"] = readable["category"]
    has_error_log = any(
        log.get("type") in {"error", "run_failed"} for log in node.get("logs", [])
    )
    if not has_error_log and callable(getattr(simulator, "log_event", None)):
        simulator.log_event(
            "run_failed",
            {
                "message": message,
                "error": raw_message,
                "category": readable["category"],
                "error_type": type(error).__name__,
            },
        )
    return message
