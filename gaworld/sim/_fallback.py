"""Structured provenance for action-space fallbacks.

When the LLM cannot produce usable actions for an activity even after the
top-up retry, :mod:`gaworld.sim._action` fills generic behavioural actions.
Those keep the run alive but are filler, so every one of them is recorded:

- one JSONL record per fallback batch, written next to the run log
  (``output/logs/action_space_fallbacks.jsonl``, override with
  ``GAWORLD_FALLBACK_LOG``);
- a run-level aggregate (``action_space_fallback_count`` plus the affected
  agents and activities) kept in memory and mirrored to a sibling
  ``*_summary.json`` so analysis / status endpoints can read it without
  parsing the JSONL.

Fallbacks never fail the simulation, and they are never cached
(``strip_fallback_only_activities`` keeps handling that).
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.sim.fallback")

FALLBACK_LOG_ENV = "GAWORLD_FALLBACK_LOG"
FALLBACK_LOG_PATH = os.path.join("output", "logs", "action_space_fallbacks.jsonl")

_LOCK = threading.Lock()
_AGGREGATE: dict[str, Any] = {
    "action_space_fallback_count": 0,
    "agents": [],
    "activities": [],
}


def fallback_log_path() -> str:
    return os.environ.get(FALLBACK_LOG_ENV) or FALLBACK_LOG_PATH


def summary_path() -> str:
    return os.path.splitext(fallback_log_path())[0] + "_summary.json"


def reset_fallback_aggregate() -> None:
    """Clear the in-memory run-level aggregate (start of a new run)."""
    with _LOCK:
        _AGGREGATE["action_space_fallback_count"] = 0
        _AGGREGATE["agents"] = []
        _AGGREGATE["activities"] = []


def fallback_aggregate() -> dict[str, Any]:
    """Run-level view: how many fallback batches fired and for whom."""
    with _LOCK:
        return {
            "action_space_fallback_count": _AGGREGATE["action_space_fallback_count"],
            "agents": list(_AGGREGATE["agents"]),
            "activities": list(_AGGREGATE["activities"]),
        }


def _write_summary_unlocked(aggregate: dict[str, Any]) -> None:
    try:
        path = summary_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, ensure_ascii=False, default=str, indent=2)
    except OSError:
        _LOG.exception("could not write action-space fallback summary")


def record_action_fallback(
    agent_id: Any,
    activities: list[str],
    reason: str = "llm_response_unusable_after_retry",
    attempts: int = 2,
) -> dict[str, Any]:
    """Record one structured fallback event. Never raises into the sim."""
    record = {
        "agent_id": agent_id,
        "activities": list(activities),
        "reason": reason,
        "attempts": attempts,
        "fallback": True,
        "timestamp": time.time(),
    }
    try:
        path = fallback_log_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        _LOG.exception("could not write action-space fallback record")
    with _LOCK:
        _AGGREGATE["action_space_fallback_count"] += 1
        if agent_id not in _AGGREGATE["agents"]:
            _AGGREGATE["agents"].append(agent_id)
        for activity in activities:
            if activity not in _AGGREGATE["activities"]:
                _AGGREGATE["activities"].append(activity)
        snapshot = {
            "action_space_fallback_count": _AGGREGATE["action_space_fallback_count"],
            "agents": list(_AGGREGATE["agents"]),
            "activities": list(_AGGREGATE["activities"]),
        }
    _write_summary_unlocked(snapshot)
    return record
