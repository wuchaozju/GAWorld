"""Scenario API routes.

Provides endpoints for fetching scenario definitions and actions.
"""

from litestar import Router, get
from litestar.exceptions import NotFoundException

from fos.core.scenarios import get_all_scenarios, get_scenario, get_scenario_actions
from fos.backend.services.gaworld_agents import get_default_gaworld_agents


@get()
async def list_scenarios() -> list[dict]:
    """Get all scenario definitions.

    Returns list of scenarios with id, name, category, description,
    parameters shape, and actions.
    """
    return get_all_scenarios()


@get("/{scenario_id:str}")
async def get_scenario_detail(scenario_id: str) -> dict:
    """Get full details of a single scenario.

    Args:
        scenario_id: The unique scenario identifier

    Returns:
        Full scenario dict

    Raises:
        NotFoundException: If scenario not found
    """
    scenario = get_scenario(scenario_id)
    if not scenario:
        raise NotFoundException(f"Scenario '{scenario_id}' not found")
    if scenario_id == "gaworld":
        scenario = dict(scenario)
        scenario["default_agents"] = get_default_gaworld_agents()
    return scenario


@get("/{scenario_id:str}/actions")
async def get_scenario_actions_endpoint(scenario_id: str) -> list[dict]:
    """Get actions for a specific scenario.

    Args:
        scenario_id: The unique scenario identifier

    Returns:
        List of action dicts with name and description.
        Returns empty list if scenario not found.
    """
    return get_scenario_actions(scenario_id)


@get("/{scenario_id:str}/default-agents")
async def get_scenario_default_agents(
    scenario_id: str,
    agent_ids: str | None = None,
) -> list[dict]:
    """Get default editable agents for scenarios that provide bundled profiles."""
    if scenario_id != "gaworld":
        raise NotFoundException(f"Scenario '{scenario_id}' has no default agents")

    return get_default_gaworld_agents(agent_ids)


@get("/gaworld/default-agents")
async def get_gaworld_default_agents(agent_ids: str | None = None) -> list[dict]:
    """Get editable bundled GAWorld profile agents."""
    return get_default_gaworld_agents(agent_ids)


@get("/default-agents/gaworld")
async def get_gaworld_default_agents_fallback(agent_ids: str | None = None) -> list[dict]:
    """Get editable bundled GAWorld profile agents using a static fallback path."""
    return get_default_gaworld_agents(agent_ids)


router = Router(
    path="/scenarios",
    route_handlers=[
        list_scenarios,
        get_gaworld_default_agents,
        get_gaworld_default_agents_fallback,
        get_scenario_actions_endpoint,
        get_scenario_default_agents,
        get_scenario_detail,
    ],
)
