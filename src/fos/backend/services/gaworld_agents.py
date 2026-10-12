"""This file prepares default GAWorld agents for the experiment builder.

- parse_agent_ids cleans a comma-separated list of agent IDs.
- get_default_gaworld_agents loads GAWorld profile data and turns it into FOS agents.
"""

from __future__ import annotations

from fos.core.experiment.scenes.gaworld import profiles as profiles_module


def parse_agent_ids(agent_ids: str | None) -> list[str] | None:
    """Split a comma-separated agent ID list into clean values."""
    if not agent_ids:
        return None
    ids = [part.strip() for part in agent_ids.split(",") if part.strip()]
    return ids or None


def get_default_gaworld_agents(agent_ids: str | None = None) -> list[dict]:
    """Load GAWorld profile agents, optionally keeping only selected IDs."""
    profiles = profiles_module.load_profiles()
    return profiles_module.profiles_to_fos_agents(
        profiles,
        agent_ids=parse_agent_ids(agent_ids),
    )
