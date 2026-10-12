"""GAWorld-specific helpers for SimTree runtime construction."""

from __future__ import annotations

import os
import re


def resolve_gaworld_path(startup_path: str | None) -> str | None:
    """Resolve GAWorld path from the startup snapshot, then the live env."""
    return startup_path or os.environ.get("GAWORLD_PATH")


def _looks_like_generated_placeholder_agent(agent: dict) -> bool:
    raw_name = str(agent.get("name") or "").strip()
    if not raw_name:
        return True
    if agent.get("id"):
        return False
    numbered_name = re.fullmatch(
        r"(Agent|代理|智能体|角色)\s*#?\s*\d+", raw_name, re.IGNORECASE
    )
    generic_profile = str(
        agent.get("profile") or agent.get("role") or agent.get("role_prompt") or ""
    ).strip()
    empty_properties = not bool(agent.get("properties") or {})
    return bool(numbered_name and empty_properties and not generic_profile)


def should_use_gaworld_profile_agents(agents: list[dict]) -> bool:
    """Return True when GAWorld should replace missing or placeholder agents."""
    if not agents:
        return True
    if all(not agent.get("id") for agent in agents):
        return True
    return all(_looks_like_generated_placeholder_agent(agent) for agent in agents)


def resolve_gaworld_agents(agent_config: dict) -> list[dict]:
    """Return GAWorld profile agents when request agents are not meaningful."""
    agents = list(agent_config.get("agents") or [])
    if not agents:
        from fos.core.experiment.scenes.gaworld import profiles as profiles_module

        return profiles_module.profiles_to_fos_agents(profiles_module.load_profiles())

    if not should_use_gaworld_profile_agents(agents):
        return agents

    from fos.core.experiment.scenes.gaworld import profiles as profiles_module

    profile_agents = profiles_module.profiles_to_fos_agents(
        profiles_module.load_profiles()
    )
    if not profile_agents:
        return agents

    requested_count = len(agents)
    if requested_count < len(profile_agents):
        profile_agents = profile_agents[:requested_count]

    return profile_agents


def resolve_gaworld_agent_ids(params: dict, agents: list[dict]) -> list[str]:
    """Build the GAWorld agent ID list from params first, then explicit agents."""
    raw_agent_ids = params.get("agent_ids", [])
    if isinstance(raw_agent_ids, str):
        ids = [part.strip() for part in raw_agent_ids.split(",") if part.strip()]
        if ids:
            return ids
    elif isinstance(raw_agent_ids, list):
        ids = [
            str(agent_id).strip() for agent_id in raw_agent_ids if str(agent_id).strip()
        ]
        if ids:
            return ids

    resolved_ids: list[str] = []
    for agent in agents:
        raw_agent_id = agent.get("id")
        if raw_agent_id is None:
            continue
        agent_id = str(raw_agent_id).strip()
        if agent_id:
            resolved_ids.append(agent_id)
    return resolved_ids
