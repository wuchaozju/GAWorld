"""
Simulation CRUD API routes.

Handles basic Create, Read, Update, Delete operations for simulations.
Provides endpoints for listing user simulations and retrieving simulation details.

All routes require authentication via bearer token.

Contains:
    - list_simulations: GET all simulations for current user
    - create_simulation: POST create new simulation
    - read_simulation: GET single simulation by ID
    - update_simulation: PATCH update simulation
    - delete_simulation: DELETE simulation by ID
    - _normalize_agent_config: Convert camelCase to snake_case for agent fields
"""

import copy
import logging

from litestar import get, post, patch, delete
from litestar.connection import Request
from litestar.exceptions import HTTPException
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from fos.backend.core.database import get_session
from fos.backend.dependencies import extract_bearer_token, resolve_current_user
from fos.backend.models.simulation import Simulation
from fos.backend.schemas.simulation import (
    SimulationBase,
    SimulationCreate,
    SimulationUpdate,
)
from fos.backend.schemas.simtree import UpdateAgentLLMConfigRequest
from fos.backend.services.simulations import generate_simulation_id, generate_simulation_name
from fos.backend.services.simtree_runtime import SIM_TREE_REGISTRY
from fos.i18n import T

from .helpers import (
    get_simulation_for_owner,
)


logger = logging.getLogger(__name__)


def _normalize_agent_config(agent_config: dict) -> dict:
    """
    Normalize agent config field names from camelCase to snake_case.

    Frontend sends camelCase field names (rolePrompt, userProfile, avatarUrl)
    but backend expects snake_case (role_prompt, user_profile, avatar_url).
    This function also ensures required fields have proper defaults.

    Args:
        agent_config: Raw agent config dict from frontend

    Returns:
        Normalized agent config dict with snake_case field names
    """
    if not agent_config:
        return agent_config

    agents = agent_config.get("agents", [])
    normalized_agents = []

    for agent in agents:
        if not isinstance(agent, dict):
            normalized_agents.append(agent)
            continue

        normalized = {}

        # Copy fields as-is, but normalize specific camelCase keys
        for key, value in agent.items():
            # Field name mapping: camelCase -> snake_case
            # NOTE: "role" is kept separate from "role_prompt"
            # "role" is just a role name (e.g., "Citizen"), while "role_prompt" is a full role description
            if key == "role":
                # Keep role as-is, don't map to role_prompt
                normalized["role"] = value
            elif key == "rolePrompt":
                normalized["role_prompt"] = value
            elif key == "userProfile":
                normalized["user_profile"] = value
            elif key == "avatarUrl":
                normalized["avatar_url"] = value
                # Also preserve in properties for display
                if "properties" not in normalized or not isinstance(normalized["properties"], dict):
                    normalized["properties"] = {}
                normalized["properties"]["avatarUrl"] = value
            elif key == "llmConfig":
                normalized["llm_config"] = value
            elif key == "knowledgeBase":
                normalized["knowledge_base"] = value
            elif key == "providerId":
                normalized["provider_id"] = value
            elif key == "actionSpace":
                normalized["action_space"] = value
            else:
                # Keep original key for already snake_case fields
                normalized[key] = value

        # Ensure required fields have defaults
        if "history" not in normalized or normalized["history"] is None:
            normalized["history"] = {}
        if "memory" not in normalized or normalized["memory"] is None:
            normalized["memory"] = []
        if "score" not in normalized or normalized["score"] is None:
            normalized["score"] = 0
        if "properties" not in normalized or normalized["properties"] is None:
            normalized["properties"] = {}

        # Preserve profile/user_profile mapping for backend compatibility
        # Frontend sends user_profile, backend expects profile OR user_profile
        if "user_profile" in normalized and "profile" not in normalized:
            normalized["profile"] = normalized["user_profile"]

        normalized_agents.append(normalized)

    return {
        **agent_config,
        "agents": normalized_agents
    }


@get("/")
async def list_simulations(request: Request) -> list[SimulationBase]:
    """
    List all simulations for the authenticated user.

    Returns simulations ordered by creation date (newest first).

    Args:
        request: Litestar request with auth token

    Returns:
        List of simulation summaries

    Raises:
        HTTPException: If authentication fails
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        result = await session.execute(
            select(Simulation)
            .where(Simulation.owner_id == current_user.id)
            .order_by(Simulation.created_at.desc())
        )
        sims = result.scalars().all()
        return [SimulationBase.model_validate(sim) for sim in sims]


@post("/", status_code=201)
async def create_simulation(
    request: Request,
    data: SimulationCreate,
) -> SimulationBase:
    """
    Create a new simulation.

    Validates LLM provider configuration before creating the simulation.
    Generates a unique simulation ID and uses the provided name or
    generates a default one.

    Args:
        request: Litestar request with auth token
        data: Simulation creation payload

    Returns:
        Created simulation object

    Raises:
        HTTPException: If authentication fails or provider not configured
        RuntimeError: If provider configuration is invalid
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)

        # Normalize agent config field names from camelCase to snake_case
        normalized_agent_config = _normalize_agent_config(data.agent_config or {})

        sim_id = generate_simulation_id()
        name = data.name or generate_simulation_name(sim_id)

        sim = Simulation(
            id=sim_id,
            owner_id=current_user.id,
            name=name,
            scene_type=data.scene_type,
            scene_config=data.scene_config,
            agent_config=normalized_agent_config,
            status="draft",
        )
        session.add(sim)
        await session.commit()
        await session.refresh(sim)
        return SimulationBase.model_validate(sim)


@get("/{simulation_id:str}")
async def read_simulation(
    request: Request,
    simulation_id: str,
) -> SimulationBase:
    """
    Get a single simulation by ID.

    User must be the owner of the simulation.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier

    Returns:
        Simulation object

    Raises:
        HTTPException: If authentication fails or simulation not found
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)
        return SimulationBase.model_validate(sim)


@patch("/{simulation_id:str}")
async def update_simulation(
    request: Request,
    simulation_id: str,
    data: SimulationUpdate,
) -> SimulationBase:
    """
    Update a simulation.

    Supports updating name, status, notes, agent_config, and scene_config.
    Agent config updates are merged with existing config to preserve
    documents and knowledge bases.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier
        data: Update payload with fields to update

    Returns:
        Updated simulation object

    Raises:
        HTTPException: If authentication fails or simulation not found
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)

        if data.name is not None:
            sim.name = data.name
        if data.status is not None:
            sim.status = data.status
        if data.notes is not None:
            sim.notes = data.notes

        if data.agent_config is not None:
            logger.debug(
                f"update_simulation: Received agent_config update for sim {simulation_id}"
            )

            # Normalize incoming agent config field names
            normalized_agent_config = _normalize_agent_config(data.agent_config)

            # Merge incoming agent_config with existing to preserve documents
            existing_agent_config = (
                copy.deepcopy(sim.agent_config) if sim.agent_config else {"agents": []}
            )
            incoming_agents = normalized_agent_config.get("agents", [])
            existing_agents = existing_agent_config.get("agents", [])

            # Create a map of existing agents by name for quick lookup
            existing_by_name = {agent.get("name"): agent for agent in existing_agents}

            # Merge incoming agents with existing agents
            merged_agents = []
            for incoming_agent in incoming_agents:
                agent_name = incoming_agent.get("name")
                if agent_name in existing_by_name:
                    # Merge: keep existing documents, update with incoming data
                    merged_agent = copy.deepcopy(existing_by_name[agent_name])
                    for key, value in incoming_agent.items():
                        merged_agent[key] = value
                    merged_agents.append(merged_agent)
                else:
                    # New agent, use as-is
                    merged_agents.append(incoming_agent)

            # Keep agents that were in existing but not in incoming
            for existing_agent in existing_agents:
                agent_name = existing_agent.get("name")
                if agent_name not in {a.get("name") for a in incoming_agents}:
                    merged_agents.append(copy.deepcopy(existing_agent))

            merged_config = copy.deepcopy(normalized_agent_config)
            merged_config["agents"] = merged_agents

            # Debug logging for knowledge bases
            agents_in_config = merged_config.get("agents", [])
            for i, agent in enumerate(agents_in_config):
                kb = agent.get("knowledgeBase", [])
                docs = agent.get("documents", {})
                logger.debug(
                    f"  Agent {i} '{agent.get('name', 'unknown')}': "
                    f"{len(kb)} knowledge items, {len(docs)} documents"
                )

            sim.agent_config = merged_config
            flag_modified(sim, "agent_config")

            # Update cached tree if exists
            updated = SIM_TREE_REGISTRY.update_agent_knowledge(simulation_id, merged_config)
            if not updated:
                logger.debug(f"update_simulation: No cached tree to update for sim {simulation_id}")

        if data.scene_config is not None:
            # Merge scene_config with existing to preserve other settings
            existing_scene_config = sim.scene_config or {}
            merged_scene_config = {**existing_scene_config, **data.scene_config}
            sim.scene_config = merged_scene_config
            flag_modified(sim, "scene_config")
            logger.debug(
                f"update_simulation: Updated scene_config for sim {simulation_id}, "
                f"environment_enabled={merged_scene_config.get('environment_enabled')}, "
                f"social_network={merged_scene_config.get('social_network', {})}"
            )

        await session.commit()
        await session.refresh(sim)
        return SimulationBase.model_validate(sim)


@delete("/{simulation_id:str}", status_code=204)
async def delete_simulation(
    request: Request,
    simulation_id: str,
) -> None:
    """
    Delete a simulation.

    Permanently removes the simulation and all associated data
    (logs, snapshots, tree nodes). Also removes the tree from
    the runtime registry.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier

    Raises:
        HTTPException: If authentication fails or simulation not found
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)

        await session.delete(sim)
        await session.commit()

        # Remove from runtime registry
        SIM_TREE_REGISTRY.remove(simulation_id)


@delete("/all", status_code=204)
async def delete_all_user_simulations(
    request: Request,
) -> None:
    """
    Delete all simulations for the authenticated user.

    Removes every simulation owned by the current user, including their
    tree nodes, logs, snapshots, and sync logs. Also removes each
    simulation from the runtime registry.

    Args:
        request: Litestar request with auth token

    Raises:
        HTTPException: If authentication fails
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        result = await session.execute(
            select(Simulation).where(Simulation.owner_id == current_user.id)
        )
        sims = result.scalars().all()
        for sim in sims:
            SIM_TREE_REGISTRY.remove(sim.id)
            await session.delete(sim)
        await session.commit()


@patch("/{simulation_id:str}/agents/llm-config")
async def update_agent_llm_config(
    request: Request,
    simulation_id: str,
    data: UpdateAgentLLMConfigRequest,
) -> dict:
    """
    Update an agent's LLM configuration.

    Finds the agent by agent_id in the simulation's agent_config and updates
    their llm_config field. The change is persisted to the database.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier
        data: Request payload with agent_id and llm_config

    Returns:
        Success message with updated agent info

    Raises:
        HTTPException: If authentication fails or simulation/agent not found
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)

        agent_config = sim.agent_config or {"agents": []}
        agents = agent_config.get("agents", [])

        # Find agent by agent_id or name (frontend uses name as identifier)
        agent_found = False
        for agent in agents:
            if isinstance(agent, dict) and (
                agent.get("id") == data.agent_id or agent.get("name") == data.agent_id
            ):
                agent["llm_config"] = data.llm_config
                if data.provider_id is not None:
                    agent["provider_id"] = data.provider_id
                    properties = agent.get("properties") or {}
                    properties["provider_id"] = data.provider_id
                    agent["properties"] = properties
                agent_found = True
                break

        if not agent_found:
            raise HTTPException(
                status_code=404,
                detail=T("api.errors.agent_id_not_found", agent_id=data.agent_id)
            )

        sim.agent_config = agent_config
        flag_modified(sim, "agent_config")
        await session.commit()
        await session.refresh(sim)

        return {
            "message": "Agent LLM config updated successfully",
            "agent_id": data.agent_id,
            "llm_config": data.llm_config,
            "provider_id": data.provider_id,
        }
