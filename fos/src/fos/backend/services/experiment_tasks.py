from __future__ import annotations

import concurrent.futures
from typing import List

from fos.backend.celery_app import celery_app
from fos.core.database import get_session
from fos.backend.models.experiment import Experiment, ExperimentRun
from fos.backend.models.simulation import Simulation
from fos.i18n import T
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from fos.backend.services.simtree_runtime import SimTree, get_runtime_agent_map
from fos.core.llm import create_llm_client
from fos.core.llm_config import LLMConfig, guess_supports_vision
from fos.backend.models.user import ProviderConfig, SearchProviderConfig
from fos.backend.services.default_providers import get_default_ollama_base_url
from fos.backend.services.provider_dialect import normalize_provider_runtime
from fos.core.tools.web.search import create_search_client
from fos.core.search_config import SearchConfig
from fos.backend.services.runtime_tasks import RUNTIME_TASKS


@celery_app.task(bind=True)
def run_experiment_task(self, simulation_id: str, exp_id: str, run_id: int, turns: int, tree_state: dict, variants: List[dict]) -> dict:
    """Celery task: runs experiment variants on a deserialized SimTree copy and updates DB.

    - Recreates LLM + search clients from DB ProviderConfig for the sim owner.
    - Deserializes tree_state into a SimTree instance local to worker.
    - Branches each variant if needed and runs each branch's simulator (in parallel threads).
    - Writes back ExperimentRun.status/result_meta.
    """

    # Worker body
    async def _worker():
        async with get_session() as session:
            # Eager-load variants to avoid triggering lazy-loads outside the session
            stmt = select(Experiment).options(selectinload(Experiment.variants)).where(Experiment.id == exp_id)
            res = await session.execute(stmt)
            exp = res.scalars().first()
            if exp is None:
                raise RuntimeError(T("api.errors.experiment_not_found"))

            # Load simulation to determine owner and provider configs
            sim = await session.get(Simulation, simulation_id.upper())
            if sim is None:
                raise RuntimeError(T("api.errors.simulation_not_found"))

            # Build clients (LLM + search) from provider configs for the sim owner
            result = await session.execute(
                select(ProviderConfig).where(ProviderConfig.user_id == sim.owner_id)
            )
            items = result.scalars().all()

            # Create LLM clients for ALL providers (not just active) to support provider distribution
            # This allows different agents to use different LLM providers
            provider_clients = {}
            default_llm_client = None
            active_provider = None  # Track active provider for quota management

            for provider in items:
                dialect, base_url = normalize_provider_runtime(provider.provider, provider.base_url)
                cfg = LLMConfig(
                    dialect=dialect,
                    api_key=provider.api_key or "",
                    model=provider.model,
                    base_url=base_url or (get_default_ollama_base_url() if dialect == "ollama" else None),
                    temperature=0.0,
                    top_p=1.0,
                    frequency_penalty=0.0,
                    presence_penalty=0.0,
                    max_tokens=1024,
                    supports_vision=guess_supports_vision(provider.model),
                )
                llm_client = create_llm_client(cfg)

                # Store in provider_clients mapping (provider_id -> client)
                provider_clients[provider.id] = llm_client

                # Use the active provider as the default client
                if (provider.config or {}).get("active"):
                    default_llm_client = llm_client
                    active_provider = provider  # Save for quota logic

            # If no active provider found, use the first one as default
            if default_llm_client is None and provider_clients:
                default_llm_client = list(provider_clients.values())[0]

            # Build clients dict with provider distribution support
            if default_llm_client is not None:
                # search provider
                result_s = await session.execute(
                    select(SearchProviderConfig).where(SearchProviderConfig.user_id == sim.owner_id)
                )
                sprov = result_s.scalars().first()
                if sprov is None:
                    s_cfg = SearchConfig(dialect="ddg", api_key="", base_url=None, params={})
                else:
                    s_cfg = SearchConfig(
                        dialect=(sprov.provider or "ddg"),
                        api_key=sprov.api_key or "",
                        base_url=sprov.base_url,
                        params=sprov.config or {},
                    )
                search_client = create_search_client(s_cfg)

                clients = {
                    "chat": default_llm_client,
                    "default": default_llm_client,
                    "search": search_client,
                    "providers": provider_clients,  # Provider distribution mapping
                }
            else:
                # No providers configured
                clients = {}

            # create local SimTree from provided tree_state
            tree = SimTree.deserialize(tree_state, clients=clients)

            node_ids = [int(v.get("node_id")) for v in variants if v.get("node_id") and int(v.get("node_id")) in tree.nodes]

            # Reserve a conservative per-run budget if provider configured
            per_run_budget = int((active_provider.config or {}).get("per_run_budget", 1024)) if active_provider is not None else 0
            if per_run_budget and node_ids:
                try:
                    from ..models.llm_usage import LLMUsage
                    async with get_session() as s2:
                        stmt = select(LLMUsage).where(LLMUsage.user_id == sim.owner_id, LLMUsage.provider_id == active_provider.id).with_for_update()
                        resu = await s2.execute(stmt)
                        usage = resu.scalars().first()
                        if usage is None:
                            usage = LLMUsage(user_id=sim.owner_id, provider_id=active_provider.id, tokens_used=0, tokens_reserved=0)
                            s2.add(usage)
                            await s2.flush()
                        total_needed = per_run_budget * len(node_ids)
                        available = int((active_provider.config or {}).get("quota", 100000)) - ((usage.tokens_used or 0) + (usage.tokens_reserved or 0))
                        if available < total_needed:
                            # Not enough quota for full reservation; disable LLM for this run
                            clients = {}
                        else:
                            usage.tokens_reserved = (usage.tokens_reserved or 0) + total_needed
                            await s2.flush()
                except Exception:
                    # on error, be conservative and disable LLM usage during run
                    clients = {}

            # Branch variants if needed. Materialize variant data into plain dicts
            node_ids = []
            db_variants = list(exp.variants or [])
            for index, v in enumerate(variants):
                ops = v.get("ops") or []
                cid = v.get("node_id")
                if not cid or int(cid) not in tree.nodes:
                    cid = tree.branch(int(v.get("base_node", tree.root)), [dict(op) for op in ops])
                if index < len(db_variants):
                    db_variants[index].node_id = int(cid)
                    session.add(db_variants[index])
                    tree.nodes[int(cid)]["meta"] = {
                        **dict(tree.nodes[int(cid)].get("meta") or {}),
                        "experiment_id": exp.id,
                        "variant_id": db_variants[index].id,
                        "variant_name": db_variants[index].name,
                        "experiment_name": exp.name,
                    }
                node_ids.append(int(cid))

            sim.latest_state = tree.serialize()
            await session.commit()

            # create thread pool to run simulators in parallel
            def run_sim(nid: int):
                sim = tree.nodes[int(nid)]["sim"]
                # sim.run is synchronous and may call LLM clients configured in tree.clients
                sim.run(int(turns))
                return int(nid)

            finished = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, max(1, len(node_ids)))) as ex:
                futs = [ex.submit(run_sim, nid) for nid in node_ids]
                for f in concurrent.futures.as_completed(futs):
                    try:
                        finished.append(f.result())
                    except Exception as e:
                        # mark error and continue
                        async with get_session() as s2:
                            run = await s2.get(ExperimentRun, run_id)
                            if run:
                                run.status = "error"
                                run.result_meta = {"error": str(e)}
                                await s2.commit()
                        raise

            # collect summaries
            summaries = {}
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
                    "sample_events": logs[-200:],
                }
            # compute lightweight aggregated metrics for each summary
            for nid, s in summaries.items():
                evs = s.get("sample_events", []) or []
                # voting distribution
                votes = {}
                # emotion time series per agent
                emotion_series = {}
                for ev in evs:
                    etype = ev.get("type") or ev.get("event_type")
                    data = ev.get("data") or {}
                    # simple vote detection heuristics
                    if etype == "action_end":
                        action = (data.get("action") or {}).get("action") if isinstance(data.get("action"), dict) else data.get("action")
                        if action == "vote" or data.get("vote") or data.get("candidate"):
                            cand = data.get("candidate") or data.get("vote") or str(data.get("choice") or "unknown")
                            votes[cand] = votes.get(cand, 0) + 1
                    # emotion updates
                    if etype == "emotion_update" or data.get("emotion"):
                        actor = data.get("actor") or data.get("agent") or ev.get("agent")
                        if actor:
                            emotion_series.setdefault(actor, []).append({"t": ev.get("timestamp"), "emotion": data.get("emotion") or data.get("value")})

                s["metrics"] = {
                    "voting_distribution": votes,
                    "emotion_series": emotion_series,
                }

            async with get_session() as session2:
                run = await session2.get(ExperimentRun, run_id)
                sim2 = await session2.get(Simulation, simulation_id.upper())
                if run:
                    run.status = "finished"
                    run.result_meta = {"finished_nodes": finished, "summaries": summaries}
                if sim2:
                    sim2.latest_state = tree.serialize()
                await session2.commit()
            return {"finished": finished}

    runtime_task_id = f"experiment_run:{int(run_id)}"
    RUNTIME_TASKS.start(
        "experiment_run",
        f"Experiment run {run_id}",
        task_id=runtime_task_id,
        status="running",
        metadata={
            "simulation_id": simulation_id.upper(),
            "experiment_id": exp_id,
            "run_id": int(run_id),
            "turns": int(turns),
            "worker": "celery",
        },
    )

    # run the async worker synchronously in Celery process
    import asyncio as _asyncio
    try:
        result = _asyncio.run(_worker())
    except Exception as exc:
        RUNTIME_TASKS.fail(runtime_task_id, exc)
        raise
    RUNTIME_TASKS.finish(runtime_task_id, metadata=result)
    return result
