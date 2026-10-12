"""
Simulation lifecycle management API routes.

Handles simulation state transitions including starting, resuming, resetting,
and copying simulations. Manages the execution state of simulations.

Contains:
    - start_simulation: Start a paused simulation
    - resume_simulation: Resume from a specific node or snapshot
    - reset_simulation: Reset simulation to initial state
    - copy_simulation: Create a copy of existing simulation
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from litestar import post, get
from litestar.exceptions import HTTPException
from litestar.connection import Request
from sqlalchemy import delete as sa_delete

from fos.i18n import T
from fos.backend.core.database import get_session
from fos.backend.dependencies import extract_bearer_token, resolve_current_user
from fos.backend.models.simulation import Simulation, SimulationLog
from fos.backend.schemas.common import Message
from fos.backend.schemas.simulation import SimulationBase

from .helpers import (
    get_simulation_for_owner,
    get_tree_record,
)
from fos.backend.services.simulations import generate_simulation_id, generate_simulation_name
from fos.core.simtree import SimTree
from fos.backend.services.simtree_runtime import SIM_TREE_REGISTRY

logger = logging.getLogger(__name__)


@post("/{simulation_id:str}/start")
async def start_simulation(
    request: Request,
    simulation_id: str,
) -> Message:
    """
    Start a simulation.

    Changes the simulation status to "running" and updates the
    updated_at timestamp. The actual simulation execution
    happens asynchronously.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier

    Returns:
        Success message

    Raises:
        HTTPException: If authentication fails or simulation not found
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)

        sim.status = "running"
        sim.updated_at = datetime.now(timezone.utc)
        await session.commit()

        return Message(message=T('api.lifecycle.start_enqueued'))


@post("/{simulation_id:str}/resume")
async def resume_simulation(
    request: Request,
    simulation_id: str,
    snapshot_id: int | None = None,
) -> Message:
    """
    Resume a simulation from a specific node or snapshot.

    If snapshot_id is provided, loads the simulation state from
    that snapshot. Otherwise resumes from the current state.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier
        snapshot_id: Optional snapshot ID to resume from

    Returns:
        Success message

    Raises:
        HTTPException: If authentication fails, simulation not found,
                      or snapshot not found
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)
        record = await get_tree_record(sim, session, current_user.id)

        if snapshot_id is not None:
            from fos.backend.models.simulation import SimulationSnapshot

            snapshot = await session.get(SimulationSnapshot, snapshot_id)
            assert snapshot is not None and snapshot.simulation_id == sim.id

            tree_state = snapshot.state
            new_tree = SimTree.deserialize(tree_state, record.tree.clients)
            loop = asyncio.get_running_loop()
            new_tree.attach_event_loop(loop)

            def _fanout(event: dict) -> None:
                if int(event.get("node", -1)) not in record.running:
                    return
                for q in list(record.subs):
                    try:
                        loop.call_soon_threadsafe(q.put_nowait, event)
                    except Exception:
                        logger.exception("failed to fanout event to tree subscriber")

            new_tree.set_tree_broadcast(_fanout)
            record.running.clear()
            record.tree = new_tree

        sim.status = "running"
        sim.updated_at = datetime.now(timezone.utc)
        await session.commit()

        return Message(message=T('api.lifecycle.resume_enqueued'))


@post("/{simulation_id:str}/reset")
async def reset_simulation(
    request: Request,
    simulation_id: str,
) -> Message:
    """
    Reset a simulation to its initial state.

    Clears all logs, snapshots, and the in-memory tree.
    Rebuilds an empty tree for fresh execution.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier

    Returns:
        Success message

    Raises:
        HTTPException: If authentication fails or simulation not found
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)

        # Clear logs and snapshots
        from fos.backend.models.simulation import SimulationSnapshot

        await session.execute(sa_delete(SimulationLog).where(
            SimulationLog.simulation_id == sim.id
        ))
        await session.execute(sa_delete(SimulationSnapshot).where(
            SimulationSnapshot.simulation_id == sim.id
        ))
        sim.latest_state = None
        await session.commit()

        # Remove from registry and rebuild
        from fos.backend.services.simtree_runtime import SIM_TREE_REGISTRY

        SIM_TREE_REGISTRY.remove(sim.id)
        await get_tree_record(sim, session, current_user.id)

        return Message(message=T('api.lifecycle.reset_rebuilt'))


@post("/{simulation_id:str}/copy", status_code=201)
async def copy_simulation(
    request: Request,
    simulation_id: str,
) -> SimulationBase:
    """
    Create a copy of an existing simulation.

    Creates a new simulation with the same configuration but a new ID.
    The copy is created in "draft" status.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier to copy

    Returns:
        Newly created simulation object

    Raises:
        HTTPException: If authentication fails or simulation not found
    """
    from fos.backend.schemas.simulation import SimulationBase

    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)

        new_id = generate_simulation_id()
        new_sim = Simulation(
            id=new_id,
            owner_id=current_user.id,
            name=generate_simulation_name(new_id),
            scene_type=sim.scene_type,
            scene_config=sim.scene_config,
            agent_config=sim.agent_config,
            status="draft",
        )
        session.add(new_sim)
        await session.commit()
        await session.refresh(new_sim)

        return SimulationBase.model_validate(new_sim)


@get("/{simulation_id:str}/rehydrate")
async def rehydrate_simulation(
    request: Request,
    simulation_id: str,
) -> Any:
    """Return persisted latest_state for restart recovery."""
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)

        if sim.latest_state:
            return sim.latest_state

        record = SIM_TREE_REGISTRY.get(simulation_id.upper())
        if record is None:
            record = await get_tree_record(sim, session, current_user.id)

        if record and record.tree:
            return record.tree.serialize()

        raise HTTPException(status_code=404, detail=T("api.errors.simtree.no_persisted_state"))
