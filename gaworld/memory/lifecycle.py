"""Day-tick orchestrator for the memory enhancement features.

Bundles the three flag-gated hooks added by the RAG enhancement plan
into one call so the simulator's day loop only has to invoke a single
function. Each step is independently gated; with all flags OFF this
orchestrator is a no-op that costs only the time to read three config
keys, which lets us land the sim-loop wiring without changing default
behavior.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from gaworld.settings import CONFIG
from gaworld.logging_setup import get_logger
from gaworld.memory.consolidation import consolidate_recent
from gaworld.memory.decay import decay_pass
from gaworld.memory.ingest import absorb_external_for_agent

_LOG = get_logger("gaworld.memory.lifecycle")


def _div_due(day: int, every_days: int) -> bool:
    """Return True if ``day`` lands on a multiple of ``every_days``.

    Defensive against zero/negative cadence values: if ``every_days``
    is non-positive, treat it as "every day" rather than crashing.
    """
    if not isinstance(day, int):
        try:
            day = int(day)
        except (TypeError, ValueError):
            return False
    step = max(1, int(every_days or 1))
    return day > 0 and day % step == 0


def run_daily_memory_lifecycle(
    agent: dict[str, Any],
    *,
    day: int,
    time_str: str = "end_of_day",
    llm: Callable[[str], str],
    web_fetch_fn: Callable[[str], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run consolidation + decay + absorb for one agent at the day boundary.

    Returns a summary dict for logging; the simulator can ignore it.
    The expected wiring is::

        for agent in agents:
            run_daily_memory_lifecycle(
                agent, day=day, time_str="end_of_day",
                llm=call_llm,
                web_fetch_fn=my_search_adapter,  # or None
            )

    Each underlying call honors its own enable flag — this function
    just sequences them and adds the periodic cadence check (so the
    simulator doesn't need to know "every N days").
    """
    if not isinstance(agent, dict):
        return {}
    mem_cfg = CONFIG.get("memory", {}) or {}
    cons_cfg = mem_cfg.get("consolidation", {}) or {}
    decay_cfg = mem_cfg.get("decay", {}) or {}

    summary: dict[str, Any] = {"day": day, "agent_id": agent.get("id")}

    # Consolidation: run on its own cadence so we don't pay the LLM
    # cost every single day; default cadence is in CONFIG.
    if cons_cfg.get("enabled", False) and _div_due(day, cons_cfg.get("every_days", 3)):
        try:
            written = consolidate_recent(agent, llm=llm, today=day)
            summary["consolidated"] = len(written)
        except Exception as exc:
            _LOG.warning("consolidation failed for agent %s: %s", agent.get("id"), exc)

    # Decay/forgetting: cheaper, but still keep it on a cadence so we
    # don't churn the DB every tick.
    if decay_cfg.get("enabled", False) and _div_due(day, decay_cfg.get("every_days", 7)):
        try:
            result = decay_pass(int(agent.get("id", 0) or 0), today=day)
            summary["decay"] = result
        except Exception as exc:
            _LOG.warning("decay failed for agent %s: %s", agent.get("id"), exc)

    # Skill consolidation moved to gaworld.skills.plugin.SkillsPlugin (K3c),
    # which rides the `memory.consolidate` event the simulator emits right
    # after this function at the day boundary.

    # Runtime absorption: gated by its own flag inside the function;
    # also no-op if the caller didn't supply a web fetch adapter.
    if web_fetch_fn is not None:
        try:
            written = absorb_external_for_agent(
                agent,
                day=day,
                time_str=time_str,
                llm=llm,
                web_fetch_fn=web_fetch_fn,
            )
            summary["absorbed"] = len(written)
        except Exception as exc:
            _LOG.warning("ingest failed for agent %s: %s", agent.get("id"), exc)

    return summary


__all__ = ["run_daily_memory_lifecycle"]
