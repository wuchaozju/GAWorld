"""Startup reconciliation of stale "running" simulations (task 2845, defect L).

A simulation whose worker/process died while the backend was down — or
without ever receiving a terminal event — would stay ``status="running"`` in
the DB forever. At startup every such row is checked against registry /
process liveness; rows with no live entry are moved to a terminal
``interrupted`` status with a reason. Rows that MIGHT still be running are
never marked completed.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

logger = logging.getLogger(__name__)

RECONCILE_NOTE = (
    "Reconciled at startup: status was 'running' but no live registry or "
    "worker entry was found (process likely died while the backend was down)."
)


async def reconcile_stale_running_simulations(session) -> list[str]:
    """Mark DB simulations stuck in ``running`` without a live entry as
    ``interrupted``. Returns the reconciled simulation IDs."""
    from fos.backend.models.simulation import Simulation
    from .simtree_runtime import SIM_TREE_REGISTRY

    result = await session.execute(
        select(Simulation).where(Simulation.status == "running")
    )
    sims = list(result.scalars())
    reconciled: list[str] = []
    for sim in sims:
        if SIM_TREE_REGISTRY.is_live(sim.id):
            continue
        sim.status = "interrupted"
        sim.notes = "\n".join(part for part in (sim.notes, RECONCILE_NOTE) if part)
        reconciled.append(sim.id)
    if reconciled:
        await session.commit()
        logger.warning(
            "Reconciled %d stale 'running' simulation(s) to 'interrupted': %s",
            len(reconciled),
            reconciled,
        )
    return reconciled


async def reconcile_stale_running_on_startup() -> None:
    """Startup hook wrapper; never blocks app startup on failure."""
    from fos.backend.core.database import get_session

    try:
        async with get_session() as session:
            await reconcile_stale_running_simulations(session)
    except Exception:
        logger.exception("Stale-running reconciliation failed; continuing startup")
