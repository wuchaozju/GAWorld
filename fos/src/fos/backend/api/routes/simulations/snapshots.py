"""
Simulation snapshot API routes.

Manages simulation snapshots for saving and restoring simulation states.
Snapshots allow users to save points in time and return to them later.

Snapshots store the complete tree state including all nodes, edges,
agent states, and event logs.

Contains:
    - create_snapshot: Save current simulation state as a snapshot
    - list_snapshots: Get all snapshots for a simulation
    - list_logs: Get simulation event logs
"""

from datetime import datetime, timezone

from litestar import get, post
from litestar.connection import Request
from sqlalchemy import select

from fos.backend.core.database import get_session
from fos.backend.dependencies import extract_bearer_token, resolve_current_user
from fos.backend.models.simulation import SimulationSnapshot, SimulationLog
from fos.backend.schemas.simulation import SnapshotBase, SnapshotCreate, SimulationLogEntry

from .helpers import (
    get_simulation_for_owner,
)
from fos.backend.services.simtree_runtime import SIM_TREE_REGISTRY


@post("/{simulation_id:str}/save", status_code=201)
async def create_snapshot(
    request: Request,
    simulation_id: str,
    data: SnapshotCreate,
) -> SnapshotBase:
    """
    Create a snapshot of the current simulation state.

    Saves the complete tree state including all nodes, agent states,
    and configuration. The snapshot can be used to resume the
    simulation from this point later.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier
        data: Optional label for the snapshot

    Returns:
        Created snapshot object

    Raises:
        HTTPException: If authentication fails or simulation not found
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)

        # Get or create tree record
        record = SIM_TREE_REGISTRY.get(simulation_id)
        if record is None:
            from .helpers import get_tree_record
            record = await get_tree_record(sim, session, current_user.id)

        tree_state = record.tree.serialize()

        # Find max turns from all nodes
        max_turns = 0
        for node in tree_state.get("nodes", []):
            sim_snap = node.get("sim") or {}
            t = int(sim_snap.get("turns", 0)) if isinstance(sim_snap, dict) else 0
            if t > max_turns:
                max_turns = t

        label = data.label or f"Snapshot {datetime.now(timezone.utc).isoformat()}"

        snapshot = SimulationSnapshot(
            simulation_id=sim.id,
            label=label,
            state=tree_state,
            turns=max_turns,
            meta={},
        )
        session.add(snapshot)

        # Update simulation.latest_state for restart recovery
        sim.latest_state = tree_state
        await session.commit()
        await session.refresh(snapshot)

        return SnapshotBase.model_validate(snapshot)


@get("/{simulation_id:str}/snapshots")
async def list_snapshots(
    request: Request,
    simulation_id: str,
) -> list[SnapshotBase]:
    """
    List all snapshots for a simulation.

    Returns snapshots ordered by creation date (newest first).

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier

    Returns:
        List of snapshot objects

    Raises:
        HTTPException: If authentication fails or simulation not found
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)

        result = await session.execute(
            select(SimulationSnapshot)
            .where(SimulationSnapshot.simulation_id == sim.id)
            .order_by(SimulationSnapshot.created_at.desc())
        )
        snapshots = result.scalars().all()

        return [SnapshotBase.model_validate(s) for s in snapshots]


@get("/{simulation_id:str}/logs")
async def list_logs(
    request: Request,
    simulation_id: str,
    limit: int = 200,
) -> list[SimulationLogEntry]:
    """
    Get simulation event logs.

    Returns recent log entries for the simulation, ordered by
    sequence (most recent first). Useful for debugging and
    understanding simulation history.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier
        limit: Maximum number of log entries to return (default: 200)

    Returns:
        List of log entries in chronological order

    Raises:
        HTTPException: If authentication fails or simulation not found
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)

        result = await session.execute(
            select(SimulationLog)
            .where(SimulationLog.simulation_id == sim.id)
            .order_by(SimulationLog.sequence.desc())
            .limit(limit)
        )
        logs = list(reversed(result.scalars().all()))

        return [SimulationLogEntry.model_validate(log) for log in logs]
