"""
API routes for experiment template management and execution.

Researchers can:
- Create, list, update, delete experiment templates
- Run experiments from templates
- List available action types for template creation
"""

from datetime import datetime, timezone
from typing import Any

from litestar import Router, post, get, put, delete
from litestar.connection import Request
from litestar.exceptions import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fos.i18n import T
from fos.backend.core.database import get_session
from fos.backend.dependencies import extract_bearer_token, resolve_current_user
from fos.backend.models.experiment_template import ExperimentTemplate
from fos.backend.models.simulation import Simulation
from fos.backend.schemas.experiment import (
    ACTION_DESCRIPTIONS,
    ActionType,
    AvailableActionTypes,
    ExperimentTemplateCreate,
    ExperimentTemplateResponse,
    ExperimentTemplateUpdate,
    ExperimentRunRequest,
    ExperimentRunResponse,
)


async def get_template_for_owner(
    session: AsyncSession,
    user_id: int,
    template_id: int,
) -> ExperimentTemplate:
    """
    Get an experiment template and verify ownership.

    Args:
        session: Database session
        user_id: Current user ID
        template_id: Template ID to fetch

    Returns:
        The experiment template

    Raises:
        HTTPException: If template not found or access denied
    """
    template = await session.get(ExperimentTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=T("api.errors.template_not_found"))

    if template.created_by != user_id:
        raise HTTPException(status_code=403, detail=T("api.errors.access_denied"))

    return template


def _convert_action_to_dict(action: Any) -> dict[str, Any]:
    """Convert an ExperimentAction schema to the dict format expected by the scene.

    Args:
        action: ExperimentAction from the schema

    Returns:
        Dict representation compatible with ExperimentScene
    """
    # Get the action name - use custom_action_name for custom actions
    if hasattr(action, "action_type") and action.action_type == ActionType.CUSTOM:
        action_name = getattr(action, "custom_action_name", "custom")
    else:
        action_name = getattr(action, "action_type", "action")

    # Preserve the full parameter schema so runtime follow-up can reconstruct types.
    parameters = []
    if hasattr(action, "parameters") and action.parameters:
        for param in action.parameters:
            parameters.append({
                "name": param.name,
                "type": param.type,
                "description": param.description,
                "required": param.required,
                "default": param.default,
            })

    return {
        "name": action_name,
        "description": getattr(action, "description", ""),
        "parameters": parameters,
    }


@get("/action-types")
async def list_action_types() -> AvailableActionTypes:
    """
    List available action types for experiment template creation.

    Returns a list of predefined action types with their descriptions.
    The frontend can use this to populate action selection dropdowns.

    Returns:
        AvailableActionTypes with list of actions including value, label, and description
    """
    actions_list = [
        {
            "value": action.value,
            "label": action.value.replace("_", " ").title(),
            "description": ACTION_DESCRIPTIONS.get(action.value, "")
        }
        for action in ActionType
        if action.value != "custom"  # Custom is handled separately in UI
    ]

    return AvailableActionTypes(actions=actions_list)


@post("/templates", status_code=201)
async def create_template(
    request: Request,
    data: ExperimentTemplateCreate,
) -> ExperimentTemplateResponse:
    """
    Create a new experiment template.

    Args:
        request: Litestar request with auth token
        data: Template creation data

    Returns:
        Created experiment template

    Raises:
        HTTPException: If authentication fails
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)

        # Convert structured actions to dict format for storage
        actions_dict = [_convert_action_to_dict(a) for a in data.actions]

        # Convert settings to dict
        settings_dict = data.settings.model_dump() if hasattr(data.settings, "model_dump") else data.settings

        db_template = ExperimentTemplate(
            name=data.name,
            description=data.description,
            actions=actions_dict,
            settings=settings_dict,
            created_by=current_user.id,
        )
        session.add(db_template)
        await session.commit()
        await session.refresh(db_template)

        return ExperimentTemplateResponse.model_validate(db_template)


@get("/templates")
async def list_templates(
    request: Request,
    skip: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """
    List all templates for current user.

    Args:
        request: Litestar request with auth token
        skip: Number of templates to skip (pagination)
        limit: Maximum number of templates to return

    Returns:
        Dictionary with list of templates

    Raises:
        HTTPException: If authentication fails
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)

        result = await session.execute(
            select(ExperimentTemplate)
            .where(ExperimentTemplate.created_by == current_user.id)
            .offset(skip)
            .limit(limit)
            .order_by(ExperimentTemplate.created_at.desc())
        )
        templates = result.scalars().all()

        return {
            "templates": [
                ExperimentTemplateResponse.model_validate(t)
                for t in templates
            ],
            "count": len(templates),
        }


@get("/templates/{template_id:int}")
async def get_template(
    request: Request,
    template_id: int,
) -> ExperimentTemplateResponse:
    """
    Get a specific experiment template.

    Args:
        request: Litestar request with auth token
        template_id: Template ID

    Returns:
        Experiment template details

    Raises:
        HTTPException: If authentication fails, template not found,
                      or access denied
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        template = await get_template_for_owner(session, current_user.id, template_id)

        return ExperimentTemplateResponse.model_validate(template)


@put("/templates/{template_id:int}")
async def update_template(
    request: Request,
    template_id: int,
    data: ExperimentTemplateUpdate,
) -> ExperimentTemplateResponse:
    """
    Update an existing experiment template.

    Args:
        request: Litestar request with auth token
        template_id: Template ID
        data: Template update data

    Returns:
        Updated experiment template

    Raises:
        HTTPException: If authentication fails, template not found,
                      or access denied
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        template = await get_template_for_owner(session, current_user.id, template_id)

        # Update fields that are set
        update_data = data.model_dump(exclude_unset=True)

        # Handle actions conversion if provided
        if "actions" in update_data and update_data["actions"] is not None:
            actions_dict = [_convert_action_to_dict(a) for a in data.actions]
            template.actions = actions_dict
            del update_data["actions"]

        # Handle settings conversion if provided
        if "settings" in update_data and update_data["settings"] is not None:
            settings_dict = data.settings.model_dump() if hasattr(data.settings, "model_dump") else data.settings
            template.settings = settings_dict
            del update_data["settings"]

        # Apply remaining updates
        for field, value in update_data.items():
            setattr(template, field, value)

        template.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(template)

        return ExperimentTemplateResponse.model_validate(template)


@delete("/templates/{template_id:int}", status_code=200)
async def delete_template(
    request: Request,
    template_id: int,
) -> dict[str, str]:
    """
    Delete an experiment template.

    Args:
        request: Litestar request with auth token
        template_id: Template ID

    Returns:
        Success message

    Raises:
        HTTPException: If authentication fails, template not found,
                      or access denied
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        template = await get_template_for_owner(session, current_user.id, template_id)

        await session.delete(template)
        await session.commit()

        return {"message": T('api.templates.deleted')}


@post("/run")
async def run_experiment(
    request: Request,
    data: ExperimentRunRequest,
) -> ExperimentRunResponse:
    """
    Launch an experiment from a template.

    Creates a new simulation based on the template configuration
    and returns the experiment ID for tracking.

    Args:
        request: Litestar request with auth token
        data: Experiment run request data

    Returns:
        Experiment run response with experiment ID and initial state

    Raises:
        HTTPException: If authentication fails, template not found,
                      or access denied

    Note:
        This endpoint creates a simulation record using the new
        Three-Layer Architecture experiment platform. The experiment
        runs when the simulation is started via the simulator.
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)

        # Get and verify template ownership
        template = await get_template_for_owner(session, current_user.id, data.template_id)

        # Create simulation record from template
        from fos.backend.services.simulations import generate_simulation_id

        simulation_id = generate_simulation_id()

        # Build scene_config from template for ExperimentScene
        settings_dict = template.settings.model_dump() if hasattr(template.settings, "model_dump") else template.settings
        scene_config = {
            "description": template.description,
            "actions": [a.model_dump() for a in template.actions],
            "parameters": {
                # Pass ALL non-reserved settings as parameters (generic approach)
                k: v for k, v in settings_dict.items()
                if k not in ["round_visibility", "max_rounds", "scenario_id"]
            },
            "scenario_id": settings_dict.get("scenario_id", "custom"),
            "round_visibility": settings_dict.get("round_visibility", "simultaneous"),
        }

        simulation = Simulation(
            id=simulation_id,
            owner_id=current_user.id,
            name=f"Experiment: {template.name}",
            scene_type="experiment_template",
            scene_config=scene_config,
            agent_config={"agents": data.agents},
            status="running",  # Set to running so the tree can be loaded
        )
        session.add(simulation)
        await session.commit()
        await session.refresh(simulation)

        # Load the tree into registry so it's ready to run
        from fos.backend.api.routes.simulations.helpers import get_tree_record

        try:
            record = await get_tree_record(simulation, session, current_user.id)
            # Mark the root node as running
            record.running.add(0)
        except Exception:
            # If tree loading fails, still return the simulation
            # The frontend can retry by starting the simulation
            pass

        return ExperimentRunResponse(
            experiment_id=simulation.id,
            status="running",
            initial_state={
                "simulation_id": simulation.id,
                "template_id": template.id,
                "scene_config": scene_config,
                "max_rounds": settings_dict.get("max_rounds", 10),
                "round_visibility": settings_dict.get("round_visibility", "simultaneous"),
            },
        )


router = Router(
    path="/experiment-templates",
    route_handlers=[
        list_action_types,
        create_template,
        list_templates,
        get_template,
        update_template,
        delete_template,
        run_experiment,
    ],
)
