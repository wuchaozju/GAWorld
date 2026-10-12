from __future__ import annotations

import asyncio
import os
import time
from typing import Dict, List
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from fos.backend.models.simulation import Simulation
from fos.i18n import T
from fos.backend.models.user import ProviderConfig

from fos.backend.core.database import get_session
from fos.backend.models.experiment import Experiment, ExperimentVariant, ExperimentRun
from fos.backend.services.simtree_runtime import SIM_TREE_REGISTRY, SimTreeRecord
from fos.backend.services.simtree_runtime import get_runtime_agent_map
from fos.backend.services.runtime_tasks import RUNTIME_TASKS
from fos.backend.celery_app import celery_app

# Import the Celery task here to avoid circular imports at module import time
try:
    from fos.backend.services.experiment_tasks import run_experiment_task
except Exception:
    run_experiment_task = None


async def create_experiment_db(simulation_id: str, base_node: int, name: str, description: str | None, variants: List[dict]) -> str:
    async with get_session() as session:
        exp_id = f"exp-{int(time.time() * 1000)}"
        exp = Experiment(id=exp_id, simulation_id=simulation_id.upper(), base_node=int(base_node), name=name or exp_id, description=description or "", model_meta={})
        session.add(exp)
        await session.flush()
        for v in variants:
            ops = v.get("ops") or []
            ev = ExperimentVariant(experiment_id=exp.id, name=v.get("name") or "variant", ops=ops)
            session.add(ev)
        await session.commit()
        return exp_id


async def run_experiment_db(simulation_id: str, exp_id: str, turns: int) -> List[int]:
    # Load experiment and variants, create a run record, branch variants then run them
    async with get_session() as session:
        sim = await session.get(Simulation, simulation_id.upper())
        if sim is None:
            raise RuntimeError(T("api.errors.simulation_not_found"))
        exp = await session.get(Experiment, exp_id)
        if exp is None:
            raise RuntimeError(T("api.errors.experiment_not_found"))
        # load variants
        await session.refresh(exp)
        variants = list(exp.variants or [])

        # ensure SimTree is loaded
        rec: SimTreeRecord = SIM_TREE_REGISTRY.get(simulation_id.upper())
        if rec is None:
            raise RuntimeError(T("api.errors.simulation_tree_not_loaded"))
        tree = rec.tree

        # Create a run record
        run = ExperimentRun(experiment_id=exp.id, turns=int(turns), status="running", result_meta={})
        session.add(run)
        await session.flush()

        node_ids = []
        # For each variant, branch from base_node and record node id
        for v in variants:
            ops = v.ops or []
            cid = tree.branch(int(exp.base_node), [dict(op) for op in ops])
            v.node_id = int(cid)
            node_ids.append(int(cid))
            tree.nodes[int(cid)]["meta"] = {
                **dict(tree.nodes[int(cid)].get("meta") or {}),
                "experiment_id": exp.id,
                "variant_id": v.id,
                "variant_name": v.name,
                "experiment_name": exp.name,
            }
            session.add(v)

        sim.latest_state = tree.serialize()
        await session.commit()

        # Run variants in parallel (threaded simulation runs)
        async def _run(nid: int) -> int:
            sim = tree.nodes[int(nid)]["sim"]
            await asyncio.to_thread(sim.run, int(turns))
            return int(nid)

        # mark running
        for nid in node_ids:
            rec.running.add(int(nid))

        try:
            finished = await asyncio.gather(*[_run(n) for n in node_ids])
        finally:
            for nid in node_ids:
                if int(nid) in rec.running:
                    rec.running.remove(int(nid))

        # collect per-node summaries (agents end-state, turns, sample events)
        summaries: dict = {}
        for nid in node_ids:
            node = tree.nodes.get(int(nid))
            if node is None:
                continue
            sim = node.get("sim")
            logs = node.get("logs") or []
            # agents snapshot (shallow props)
            agents = {}
            for name, ag in (get_runtime_agent_map(sim).items() if sim else []):
                agents[name] = getattr(ag, "properties", {})
            summaries[int(nid)] = {
                "node_id": int(nid),
                "turns": getattr(sim, "turns", 0) if sim else 0,
                "agents": agents,
                "sample_events": logs[-200:],
            }

        # compute lightweight aggregated metrics per node
        for nid, s in list(summaries.items()):
            evs = s.get("sample_events", []) or []
            votes = {}
            emotion_series = {}
            for ev in evs:
                etype = ev.get("type") or ev.get("event_type")
                data = ev.get("data") or {}
                if etype == "action_end":
                    action = (data.get("action") or {}).get("action") if isinstance(data.get("action"), dict) else data.get("action")
                    if action == "vote" or data.get("vote") or data.get("candidate"):
                        cand = data.get("candidate") or data.get("vote") or str(data.get("choice") or "unknown")
                        votes[cand] = votes.get(cand, 0) + 1
                if etype == "emotion_update" or data.get("emotion"):
                    actor = data.get("actor") or data.get("agent") or ev.get("agent")
                    if actor:
                        emotion_series.setdefault(actor, []).append({"t": ev.get("timestamp"), "emotion": data.get("emotion") or data.get("value")})

            s["metrics"] = {"voting_distribution": votes, "emotion_series": emotion_series}

        # update run record
        run.status = "finished"
        run.result_meta = {"finished_nodes": finished, "summaries": summaries}
        sim.latest_state = tree.serialize()
        await session.commit()
        return finished


class ExperimentRegistry:
    def __init__(self) -> None:
        # key: simulation_id -> dict of exp_id -> metadata
        self._data: Dict[str, Dict[str, dict]] = {}
        self._lock = asyncio.Lock()

    async def create_experiment(self, simulation_id: str, exp: dict) -> str:
        async with self._lock:
            sid = simulation_id.upper()
            self._data.setdefault(sid, {})
            exp_id = f"exp-{int(time.time() * 1000)}"
            exp_record = dict(exp)
            exp_record.update({"id": exp_id, "created_at": time.time(), "status": "created"})
            self._data[sid][exp_id] = exp_record
            return exp_id

    async def set_experiment(self, simulation_id: str, exp_id: str, value: dict) -> None:
        async with self._lock:
            sid = simulation_id.upper()
            if sid in self._data and exp_id in self._data[sid]:
                self._data[sid][exp_id].update(value)

    async def get_experiment(self, simulation_id: str, exp_id: str) -> dict | None:
        sid = simulation_id.upper()
        return self._data.get(sid, {}).get(exp_id)

    async def list_experiments(self, simulation_id: str) -> List[dict]:
        sid = simulation_id.upper()
        return list(self._data.get(sid, {}).values())


EXPERIMENT_REGISTRY = ExperimentRegistry()


async def create_and_branch(simulation_id: str, base_node: int, variants: List[dict]) -> dict:
    """Create branches under base_node for each variant.

    Each variant: {name: str, ops: list[dict]}.
    Returns mapping of variant name -> node id.
    """
    rec: SimTreeRecord = SIM_TREE_REGISTRY.get(simulation_id.upper())
    if rec is None:
        raise RuntimeError(T("api.errors.simulation_tree_not_loaded"))
    tree = rec.tree
    mapping = {}
    for v in variants:
        name = v.get("name") or "variant"
        ops = v.get("ops") or []
        cid = tree.branch(int(base_node), [dict(op) for op in ops])
        mapping[name] = int(cid)
    return mapping


async def run_variants_parallel(simulation_id: str, node_ids: List[int], turns: int) -> List[int]:
    """Run given node_ids in parallel by invoking their simulator.run in threads.

    Returns list of node ids that finished.
    """
    rec: SimTreeRecord = SIM_TREE_REGISTRY.get(simulation_id.upper())
    if rec is None:
        raise RuntimeError(T("api.errors.simulation_tree_not_loaded"))
    tree = rec.tree

    # mark running
    for nid in node_ids:
        rec.running.add(int(nid))

    async def _run(nid: int) -> int:
        sim = tree.nodes[int(nid)]["sim"]
        await asyncio.to_thread(sim.run, int(turns))
        return int(nid)

    tasks = [_run(n) for n in node_ids]
    try:
        finished = await asyncio.gather(*tasks)
    finally:
        for nid in node_ids:
            if int(nid) in rec.running:
                rec.running.remove(int(nid))

    return finished


# In-memory map to track running ExperimentRun tasks: run_id -> asyncio.Task
_RUN_TASKS: dict[int, asyncio.Task] = {}
_USE_CELERY_EXPERIMENTS = str(os.environ.get("FOS_USE_CELERY_EXPERIMENTS") or "").strip().lower() in {"1", "true", "yes", "on"}


def _experiment_runtime_task_id(run_id: int) -> str:
    return f"experiment_run:{int(run_id)}"


async def start_experiment_run_background(simulation_id: str, exp_id: str, turns: int) -> int:
    """Create a run record and start the run in background, returning run_id."""
    async with get_session() as session:
        # Eager-load variants to avoid lazy-loading during later processing
        stmt = select(Experiment).options(selectinload(Experiment.variants)).where(Experiment.id == exp_id)
        res = await session.execute(stmt)
        exp = res.scalars().first()
        if exp is None:
            raise RuntimeError(T("api.errors.experiment_not_found"))
        run = ExperimentRun(experiment_id=exp.id, turns=int(turns), status="queued", result_meta={})
        session.add(run)
        await session.flush()
        run_id = int(run.id)
        # attach provider/model info into run.result_meta for reproducibility
        try:
            sim = await session.get(Simulation, simulation_id.upper())
            if sim is not None:
                result = await session.execute(
                    select(ProviderConfig).where(ProviderConfig.user_id == sim.owner_id)
                )
                prov = result.scalars().first()
                if prov:
                    run.result_meta = {"provider": {"id": prov.id, "provider": prov.provider, "model": prov.model}}
                else:
                    run.result_meta = {}
            else:
                run.result_meta = {}
        except Exception:
            run.result_meta = {}
        await session.flush()
        # serialize tree state for worker
        rec: SimTreeRecord = SIM_TREE_REGISTRY.get(simulation_id.upper())
        if rec is None:
            # still persist run but mark error
            run.status = "error"
            run.result_meta = {"error": "SimTree not loaded"}
            RUNTIME_TASKS.start(
                "experiment_run",
                f"Experiment run {run_id}",
                task_id=_experiment_runtime_task_id(run_id),
                status="error",
                metadata={
                    "simulation_id": simulation_id.upper(),
                    "experiment_id": exp_id,
                    "run_id": run_id,
                },
            )
            RUNTIME_TASKS.fail(_experiment_runtime_task_id(run_id), "SimTree not loaded")
            await session.commit()
            return run_id
        tree = rec.tree

        # Materialize branch nodes immediately so frontend can render them right away.
        variants = []
        for v in list(exp.variants or []):
            node_id = v.node_id
            if not node_id or int(node_id) not in tree.nodes:
                node_id = tree.branch(int(exp.base_node), [dict(op) for op in (v.ops or [])])
                v.node_id = int(node_id)
                session.add(v)
            tree.nodes[int(node_id)]["meta"] = {
                **dict(tree.nodes[int(node_id)].get("meta") or {}),
                "experiment_id": exp.id,
                "variant_id": v.id,
                "variant_name": v.name,
                "experiment_name": exp.name,
            }
            variants.append({"id": v.id, "name": v.name, "ops": v.ops or [], "base_node": int(exp.base_node), "node_id": int(node_id)})

        sim.latest_state = tree.serialize()
        tree_state = sim.latest_state

        await session.commit()

    # Only use Celery when explicitly enabled; local/dev runs should execute in-process
    RUNTIME_TASKS.start(
        "experiment_run",
        f"Experiment run {run_id}",
        task_id=_experiment_runtime_task_id(run_id),
        status="queued",
        metadata={
            "simulation_id": simulation_id.upper(),
            "experiment_id": exp_id,
            "run_id": run_id,
            "turns": int(turns),
        },
    )
    if _USE_CELERY_EXPERIMENTS and run_experiment_task is not None:
        # enqueue Celery task
        async_result = run_experiment_task.delay(simulation_id, exp_id, run_id, int(turns), tree_state, variants)
        task_id = getattr(async_result, "id", None)
        # persist task id
        async with get_session() as session:
            run = await session.get(ExperimentRun, run_id)
            if run:
                run.task_id = task_id
                run.status = "queued"
                await session.commit()
        RUNTIME_TASKS.update(
            _experiment_runtime_task_id(run_id),
            metadata={"celery_task_id": task_id},
        )
        return run_id
    else:
        # fallback: schedule internal asyncio worker and keep in-memory tracking
        task = asyncio.create_task(_run_experiment_worker(simulation_id, exp_id, run_id, int(turns)))
        _RUN_TASKS[run_id] = task
        task.add_done_callback(lambda _task, task_run_id=run_id: _RUN_TASKS.pop(task_run_id, None))
        return run_id


async def _run_experiment_worker(simulation_id: str, exp_id: str, run_id: int, turns: int) -> None:
    """Background worker that performs branching (if needed), runs variants, and updates DB run record."""
    runtime_task_id = _experiment_runtime_task_id(run_id)
    try:
        RUNTIME_TASKS.mark_running(runtime_task_id)
        async with get_session() as session:
            # Eager-load variants to avoid lazy-loading them later outside session
            stmt = select(Experiment).options(selectinload(Experiment.variants)).where(Experiment.id == exp_id)
            res = await session.execute(stmt)
            exp = res.scalars().first()
            if exp is None:
                raise RuntimeError(T("api.errors.experiment_not_found"))
            # Convert variant DB objects to plain dicts for safe background processing
            variants = [{"id": v.id, "name": v.name, "ops": (v.ops or []), "node_id": v.node_id} for v in (exp.variants or [])]

            rec: SimTreeRecord = SIM_TREE_REGISTRY.get(simulation_id.upper())
            if rec is None:
                raise RuntimeError(T("api.errors.simulation_tree_not_loaded"))
            tree = rec.tree

            # ensure each variant has node_id; branch if missing
            node_ids = []
            for v in variants:
                # v is a dict here (id, name, ops, node_id)
                if not v.get("node_id") or int(v.get("node_id")) not in tree.nodes:
                    cid = tree.branch(int(exp.base_node), [dict(op) for op in (v.get("ops") or [])])
                    v["node_id"] = int(cid)
                meta = dict(tree.nodes[int(v.get("node_id"))].get("meta") or {})
                meta.update(
                    {
                        "experiment_id": exp.id,
                        "variant_id": v.get("id"),
                        "variant_name": v.get("name"),
                        "experiment_name": exp.name,
                    }
                )
                tree.nodes[int(v.get("node_id"))]["meta"] = meta
                node_ids.append(int(v.get("node_id")))
                # we don't add the dict back to session; persist node_id to DB below if needed

            for v in exp.variants or []:
                for dv in variants:
                    if dv.get("id") == v.id and dv.get("node_id"):
                        v.node_id = int(dv.get("node_id"))
                        session.add(v)

            sim_record = await session.get(Simulation, simulation_id.upper())
            sim_record.latest_state = tree.serialize()

            # update run status to running
            run = await session.get(ExperimentRun, run_id)
            run.status = "running"
            await session.commit()

        # perform parallel runs
        async def _run(nid: int) -> int:
            sim = tree.nodes[int(nid)]["sim"]
            await asyncio.to_thread(sim.run, int(turns))
            return int(nid)

        # mark running
        for nid in node_ids:
            rec.running.add(int(nid))

        # gather and allow cancellation
        gather_task = asyncio.gather(*[_run(n) for n in node_ids])
        try:
            finished = await gather_task
        finally:
            for nid in node_ids:
                if int(nid) in rec.running:
                    rec.running.remove(int(nid))

        # write results: collect per-node summaries
        summaries: dict = {}
        for nid in node_ids:
            node = tree.nodes.get(int(nid))
            if node is None:
                continue
            sim = node.get("sim")
            logs = node.get("logs") or []
            agents = {}
            for name, ag in (get_runtime_agent_map(sim).items() if sim else []):
                agents[name] = getattr(ag, "properties", {})
            summaries[int(nid)] = {
                "node_id": int(nid),
                "turns": getattr(sim, "turns", 0) if sim else 0,
                "agents": agents,
                "sample_events": logs[-50:],
            }

        results_summary = {"finished_nodes": finished, "summaries": summaries}
        async with get_session() as session:
            # persist node_id back to experiment_variants in DB if they were empty
            stmt = select(Experiment).options(selectinload(Experiment.variants)).where(Experiment.id == exp_id)
            res = await session.execute(stmt)
            exp_db = res.scalars().first()
            if exp_db:
                for v in exp_db.variants or []:
                    # find matching dict variant by id and update node_id if missing
                    for dv in variants:
                        if dv.get("id") == v.id and dv.get("node_id") and not v.node_id:
                            v.node_id = int(dv.get("node_id"))
                            session.add(v)
            run = await session.get(ExperimentRun, run_id)
            run.status = "finished"
            run.result_meta = results_summary
            sim_record = await session.get(Simulation, simulation_id.upper())
            sim_record.latest_state = tree.serialize()
            await session.commit()
        RUNTIME_TASKS.finish(
            runtime_task_id,
            metadata={"finished_nodes": finished},
        )
    except asyncio.CancelledError:
        # mark run as cancelled
        async with get_session() as session:
            run = await session.get(ExperimentRun, run_id)
            if run:
                run.status = "cancelled"
                await session.commit()
        RUNTIME_TASKS.cancel(runtime_task_id)
        raise
    except Exception as e:
        async with get_session() as session:
            run = await session.get(ExperimentRun, run_id)
            if run:
                run.status = "error"
                run.result_meta = {"error": str(e)}
                await session.commit()
        RUNTIME_TASKS.fail(runtime_task_id, e)
        raise


async def cancel_run(run_id: int) -> bool:
    """Attempt to cancel a running background run. Returns True if cancelled."""
    # First, try to revoke Celery task if present
    async with get_session() as session:
        run = await session.get(ExperimentRun, int(run_id))
        if run is None:
            return False
        if getattr(run, "task_id", None):
            try:
                if celery_app is not None:
                    celery_app.control.revoke(run.task_id, terminate=True)
            except Exception:
                # best-effort
                pass
            run.status = "cancelled"
            await session.commit()
            RUNTIME_TASKS.cancel(_experiment_runtime_task_id(int(run_id)))
            return True

    # Fallback to in-memory asyncio task cancellation
    task = _RUN_TASKS.get(int(run_id))
    if task is None:
        return False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    _RUN_TASKS.pop(int(run_id), None)
    RUNTIME_TASKS.cancel(_experiment_runtime_task_id(int(run_id)))
    return True


async def rerun_experiment(simulation_id: str, exp_id: str, run_id: int | None, turns: int) -> int:
    """Start a new run for the given experiment (optionally based on previous run). Returns new run_id."""
    # For now just start a fresh background run
    return await start_experiment_run_background(simulation_id, exp_id, turns)
