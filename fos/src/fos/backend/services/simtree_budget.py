"""LLM budget preflight for SimTree GAWorld branches (Phase 8).

Estimates per-provider LLM usage for a branch request BEFORE any subprocess
is launched, and refuses the whole request with a structured error when a
provider would exceed its budget. The estimate respects Phase 4 per-agent
routing: agents pinned to a provider (exact int agent IDs in
``llm.routing.agents``) count only against that provider.

Estimation heuristic (documented, conservative): one LLM call per agent per
simulated day at minimum — ``estimated = routed agents + explicitly pinned
agents``. There is NO provider substitution: an over-budget provider is a
refusal, never a silent rewrite. Refusals carry only
{provider, estimated, budget, unit, ok, explanation} — never API keys or
any other provider credentials.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_UNIT = "calls"

#: Fields copied from a provider budget config into a verdict. Anything not
#: listed here (notably api_key) can never leak into a refusal payload.
_VERDICT_FIELDS = ("budget", "unit")


def estimate_llm_budget(
    providers: dict[str, dict[str, Any]] | None,
    routing: dict[str, int] | None,
    agent_routing: dict[int, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Estimate per-provider usage and flag over-budget providers.

    Args:
        providers: {provider_name: {"budget": int, "unit": str, ...}} —
            extra keys (credentials) are ignored and never echoed back.
        routing: {provider_name: agent_count} — Phase 4 base routing.
        agent_routing: {agent_id: provider_name} — per-agent overrides
            (exact int IDs); each pinned agent counts against its provider.

    Returns:
        {provider_name: verdict} where verdict has ``ok``, ``estimated``,
        ``budget``, ``unit``, ``provider`` and an ``explanation``; over-budget
        providers get ``ok=False`` and ``substitute=False`` (never rewritten).
    """
    verdicts: dict[str, dict[str, Any]] = {}
    agent_routing = agent_routing or {}
    for provider, config in (providers or {}).items():
        budget = int(config.get("budget", 0) or 0)
        unit = str(config.get("unit", DEFAULT_UNIT) or DEFAULT_UNIT)
        base_agents = int(routing.get(provider, 0) or 0)
        pinned = [agent_id for agent_id, target in agent_routing.items() if target == provider]
        estimated = base_agents + len(pinned)
        explanation = (
            f"conservative estimate: {base_agents} routed agents plus "
            f"{len(pinned)} agents pinned to this provider, 1 call per agent-day"
        )
        verdict: dict[str, Any] = {
            "provider": provider,
            "estimated": estimated,
            "budget": budget,
            "unit": unit,
            "ok": estimated <= budget,
            "explanation": explanation,
        }
        if not verdict["ok"]:
            # Refusal, not substitution: the provider is never rewritten.
            verdict["substitute"] = False
            logger.warning(
                "LLM budget preflight refusal: provider=%s estimated=%d budget=%d unit=%s",
                provider,
                estimated,
                budget,
                unit,
            )
        verdicts[provider] = verdict
    return verdicts


def format_budget_refusal(verdict: dict[str, Any]) -> str:
    """Human-readable, credential-free refusal message."""
    return (
        f"LLM budget exceeded for provider {verdict.get('provider')}: "
        f"estimated {verdict.get('estimated')} {verdict.get('unit')} "
        f"but budget is {verdict.get('budget')} {verdict.get('unit')}"
    )
