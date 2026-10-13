"""Scenario API routes.

Provides endpoints for fetching scenario definitions and actions, plus the
live GAWorld population endpoints used by the experiment builder (Step 4):
populations/cities, paginated agents, generation jobs and export.

GAWorld is the source of truth for populations — there is no fallback to the
bundled hangzhou_50.json snapshot on these paths. A down GAWorld surfaces as
HTTP 503 with an explicit "GAWorld backend unavailable" message.
"""

from typing import Any

from litestar import Response, Router, get, post
from litestar.exceptions import NotFoundException

from fos.core.scenarios import get_all_scenarios, get_scenario, get_scenario_actions
from fos.backend.services import gaworld_agents as gaworld_service
from fos.backend.services.gaworld_agents import GAWorldUnavailableError

GAWORLD_UNAVAILABLE = "GAWorld backend unavailable"


def _unavailable_response() -> Response:
    return Response(
        content={"error": GAWORLD_UNAVAILABLE},
        status_code=503,
    )


def _live_default_agents(agent_ids: str | None = None) -> list[dict]:
    """Default agents for legacy callers, now served from live GAWorld data."""
    parsed = gaworld_service.parse_agent_ids(agent_ids)
    payload = gaworld_service.get_agents(city="")
    agents = payload["agents"]
    if parsed:
        wanted = {str(agent_id) for agent_id in parsed}
        agents = [agent for agent in agents if str(agent.get("id")) in wanted]
    return [gaworld_service.to_fos_agent(agent) for agent in agents]


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
        try:
            scenario["default_agents"] = _live_default_agents()
        except GAWorldUnavailableError:
            scenario["default_agents"] = []
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
) -> list[dict] | Response:
    """Get default editable agents for scenarios backed by live GAWorld data."""
    if scenario_id != "gaworld":
        raise NotFoundException(f"Scenario '{scenario_id}' has no default agents")

    try:
        return _live_default_agents(agent_ids)
    except GAWorldUnavailableError:
        return _unavailable_response()


@get("/gaworld/default-agents")
async def get_gaworld_default_agents(agent_ids: str | None = None) -> list[dict] | Response:
    """Get editable GAWorld agents from the live GAWorld dashboard."""
    try:
        return _live_default_agents(agent_ids)
    except GAWorldUnavailableError:
        return _unavailable_response()


@get("/default-agents/gaworld")
async def get_gaworld_default_agents_fallback(
    agent_ids: str | None = None,
) -> list[dict] | Response:
    """Get editable GAWorld agents using a static fallback path (live data)."""
    try:
        return _live_default_agents(agent_ids)
    except GAWorldUnavailableError:
        return _unavailable_response()


# ---------------------------------------------------------------------------
# Live GAWorld population endpoints (Phase 3)
# ---------------------------------------------------------------------------


@get("/gaworld/populations")
async def list_gaworld_populations() -> dict | Response:
    """List GAWorld cities/populations available as experiment populations."""
    try:
        return gaworld_service.list_populations()
    except GAWorldUnavailableError:
        return _unavailable_response()


@get("/gaworld/agents")
async def list_gaworld_agents(
    city: str = "",
    limit: int = 200,
    offset: int = 0,
) -> dict | Response:
    """Page through one GAWorld city's agents (exact int IDs preserved)."""
    try:
        return gaworld_service.get_agents(city=city, limit=limit, offset=offset)
    except GAWorldUnavailableError:
        return _unavailable_response()


@get("/gaworld/agents/{agent_id:int}")
async def get_gaworld_agent_detail(agent_id: int, city: str = "") -> dict | Response:
    """Fetch one GAWorld agent's full detail (including profile text)."""
    try:
        return gaworld_service.get_agent_detail(agent_id, city=city)
    except GAWorldUnavailableError:
        return _unavailable_response()


@post("/gaworld/populations/generate", status_code=202)
async def generate_gaworld_population(data: dict[str, Any] | None = None) -> dict | Response:
    """Start a GAWorld population generation job; returns the job reference."""
    spec = (data or {}).get("spec") or {}
    try:
        return gaworld_service.generate_population(spec)
    except GAWorldUnavailableError:
        return _unavailable_response()


@get("/gaworld/populations/jobs/{job_id:str}")
async def poll_gaworld_population_job(job_id: str) -> dict | Response:
    """Poll one GAWorld population generation job (done→completed, error→failed)."""
    try:
        return gaworld_service.poll_population_job(job_id)
    except GAWorldUnavailableError:
        return _unavailable_response()


@get("/gaworld/populations/export")
async def export_gaworld_population(format: str = "json") -> dict | Response:
    """Export the last generated GAWorld population in the given format."""
    try:
        return gaworld_service.export_population(format)
    except GAWorldUnavailableError:
        return _unavailable_response()


router = Router(
    path="/scenarios",
    route_handlers=[
        list_scenarios,
        get_gaworld_default_agents,
        get_gaworld_default_agents_fallback,
        get_scenario_actions_endpoint,
        get_scenario_default_agents,
        get_scenario_detail,
        list_gaworld_populations,
        list_gaworld_agents,
        get_gaworld_agent_detail,
        generate_gaworld_population,
        poll_gaworld_population_job,
        export_gaworld_population,
    ],
)
