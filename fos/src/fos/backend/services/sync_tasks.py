from __future__ import annotations

import logging
from typing import Optional

from ..celery_app import celery_app
from ..core.database import get_session
from ..models.simulation import Simulation, SimulationSyncLog

logger = logging.getLogger(__name__)


@celery_app.task(bind=True)
def run_sync_task(self, simulation_id: Optional[str], user_id: Optional[int], payload: dict, sync_log_id: Optional[int] = None) -> dict:
    """Background task to create/update simulation and record detailed sync logs.

    - If `simulation_id` corresponds to an existing Simulation, update it.
    - Otherwise create a new Simulation and return its id.
    - Updates SimulationSyncLog.details with incremental messages and sets final status.
    """
    import asyncio as _asyncio

    async def _worker():
        async with get_session() as session:
            sync_log = None
            if sync_log_id is not None:
                sync_log = await session.get(SimulationSyncLog, sync_log_id)
            # helper to append message
            async def append(msg: str):
                nonlocal sync_log
                if sync_log is None:
                    return
                det = sync_log.details or []
                det.append(str(msg))
                sync_log.details = det
                await session.flush()

            try:
                if sync_log:
                    sync_log.status = 'started'
                    await session.flush()
                    await append('[START] Task started')
                # Normalize payload
                scene_type = payload.get('scene_type') or payload.get('sceneType') or 'unknown'
                scene_config = payload.get('scene_config') or payload.get('sceneConfig') or {}
                agent_config = payload.get('agent_config') or payload.get('agentConfig') or {}
                social_network = payload.get('social_network') or payload.get('socialNetwork') or {}

                # Merge social_network into scene_config
                if social_network:
                    scene_config = {**scene_config, "social_network": social_network}
                    logger.debug(f"[sync_tasks] Merging social_network into scene_config: {social_network}")

                # determine create vs update
                sim = None
                if simulation_id:
                    sim = await session.get(Simulation, str(simulation_id).upper())
                if sim is None:
                    # create
                    new_id = payload.get('id') or None
                    sim = Simulation(
                        id=new_id or ("SIM" + str(int(self.request.id) if hasattr(self.request, 'id') else "0")),
                        owner_id=user_id or None,
                        name=payload.get('name') or 'Imported Simulation',
                        scene_type=scene_type,
                        scene_config=scene_config,
                        agent_config=agent_config,
                        status='draft',
                    )
                    session.add(sim)
                    await session.commit()
                    await session.refresh(sim)
                    if sync_log:
                        await append(f"[OK] Created simulation id={sim.id}")
                else:
                    # update existing
                    sim.name = payload.get('name') or sim.name
                    sim.scene_type = scene_type
                    sim.scene_config = scene_config
                    sim.agent_config = agent_config
                    sim.latest_state = payload.get('latest_state') or sim.latest_state
                    await session.commit()
                    if sync_log:
                        await append(f"[OK] Updated simulation id={sim.id}")

                if sync_log:
                    sync_log.status = 'finished'
                    await append('[DONE] Task finished')
                    await session.commit()
                return {"simulation_id": sim.id}
            except Exception as e:
                if sync_log:
                    sync_log.status = 'error'
                    await append(f"[ERROR] {str(e)}")
                    await session.commit()
                raise

    return _asyncio.run(_worker())
