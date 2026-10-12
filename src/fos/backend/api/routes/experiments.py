from __future__ import annotations

import logging

from typing import List
from pydantic import BaseModel
from litestar import post, get, Router
from litestar.exceptions import HTTPException
from litestar.connection import Request

from fos.i18n import T
from fos.backend.core.database import get_session
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from fos.backend.api.routes.simulations.helpers import get_simulation_and_tree_for_owner, broadcast_tree_event
from fos.backend.dependencies import extract_bearer_token, resolve_current_user
from fos.backend.models.simulation import Simulation
from fos.backend.models.user import ProviderConfig
from fos.backend.models.llm_usage import LLMUsage
from fos.backend.services.experiment_runner import (
    create_experiment_db,
    start_experiment_run_background,
)
from fos.backend.models.experiment import Experiment

logger = logging.getLogger(__name__)


class VariantSpec(BaseModel):
    name: str
    ops: List[dict] = []


class CreateExperimentRequest(BaseModel):
    name: str
    # Accept numeric base_node (float allowed) and coerce to int in handler.
    base_node: float
    variants: List[VariantSpec]


class RunExperimentRequest(BaseModel):
    turns: int = 1


class CompareRequest(BaseModel):
    node_a: int
    node_b: int
    use_llm: bool = False


@post("/{simulation_id:str}/experiments")
async def create_experiment(request: Request, simulation_id: str, data: CreateExperimentRequest) -> dict:
    # Authenticate and verify ownership
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
    # persist experiment to DB
    # coerce base_node to int (floor) to tolerate frontend float inputs like 2.1
    exp_id = await create_experiment_db(simulation_id, int(data.base_node), data.name, None, [v.dict() for v in data.variants])
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await session.get(Simulation, simulation_id.upper())
        stmt = select(Experiment).options(selectinload(Experiment.variants)).where(Experiment.id == exp_id)
        res = await session.execute(stmt)
        exp = res.scalars().first()
        if exp is None:
            raise HTTPException(status_code=404, detail=T("api.errors.experiment_not_found_after_creation"))

        _, record = await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        tree = record.tree
        node_mapping = []
        for v in exp.variants or []:
            cid = tree.branch(int(exp.base_node), [dict(op) for op in (v.ops or [])])
            v.node_id = int(cid)
            tree.nodes[int(cid)]["meta"] = {
                **dict(tree.nodes[int(cid)].get("meta") or {}),
                "experiment_id": exp.id,
                "variant_id": v.id,
                "variant_name": v.name,
                "experiment_name": exp.name,
                "base_node": int(exp.base_node),
                "ops": [dict(op) for op in (v.ops or [])],
            }
            session.add(v)
            node_mapping.append({"variant_id": v.id, "node_id": int(cid), "variant_name": v.name})

        exp.status = "branched"
        session.add(exp)
        if sim is not None:
            sim.latest_state = tree.serialize()
            session.add(sim)
        await session.commit()
    return {"experiment_id": exp_id, "node_mapping": node_mapping}


@post("/{simulation_id:str}/experiments/{exp_id:str}/run")
async def run_experiment(request: Request, simulation_id: str, exp_id: str, data: RunExperimentRequest) -> dict:
    logger.info(
        "[EXPERIMENT_RUN] request simulation_id=%s exp_id=%s turns=%s",
        simulation_id,
        exp_id,
        int(data.turns),
    )
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        _, record = await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        # broadcast run starts for visibility
        broadcast_tree_event(record, {"type": "experiment_run_start", "data": {"experiment": exp_id}})
    # start background run (Celery if configured)
    run_id = await start_experiment_run_background(simulation_id, exp_id, int(data.turns))
    # attempt to return any already-assigned variant->node mapping if available
    node_mapping = []
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        # Eager-load variants to avoid lazy loading side-effects
        from sqlalchemy.orm import selectinload
        stmt = select(Experiment).options(selectinload(Experiment.variants)).where(Experiment.id == exp_id)
        res = await session.execute(stmt)
        exp = res.scalars().first()
        if exp is not None:
            for v in (exp.variants or []):
                if getattr(v, "node_id", None):
                    node_mapping.append({"variant_id": v.id, "node_id": int(v.node_id)})

    res = {"run_id": run_id, "node_mapping": node_mapping}
    logger.info(
        "[EXPERIMENT_RUN] response simulation_id=%s exp_id=%s run_id=%s node_mapping=%s",
        simulation_id,
        exp_id,
        run_id,
        node_mapping,
    )
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        _, record = await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        broadcast_tree_event(record, {"type": "experiment_run_finish", "data": {"experiment": exp_id, "nodes": res.get("finished", [])}})
    return res


@get("/{simulation_id:str}/experiments")
async def list_experiments(request: Request, simulation_id: str) -> dict:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        result = await session.execute(
            select(Experiment).where(Experiment.simulation_id == simulation_id.upper())
        )
        items = result.scalars().all()
        data = [
            {
                "id": e.id,
                "name": e.name,
                "base_node": e.base_node,
                "created_at": getattr(e, "created_at", None),
                "status": e.status,
            }
            for e in items
        ]
    return {"experiments": data}


@get("/{simulation_id:str}/experiments/{exp_id:str}")
async def get_experiment(request: Request, simulation_id: str, exp_id: str) -> dict:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        # Eager-load variants and runs to avoid lazy-loading outside session
        stmt = select(Experiment).options(selectinload(Experiment.variants), selectinload(Experiment.runs)).where(Experiment.id == exp_id)
        res = await session.execute(stmt)
        exp = res.scalars().first()
        if exp is None:
            return {"error": T('api.experiments.not_found')}
        # serialize minimal experiment info
        return {
            "experiment": {
                "id": exp.id,
                "name": exp.name,
                "base_node": exp.base_node,
                "variants": [{"id": v.id, "name": v.name, "ops": v.ops, "node_id": v.node_id} for v in (exp.variants or [])],
                "runs": [{"id": r.id, "turns": r.turns, "status": r.status, "result_meta": r.result_meta} for r in (exp.runs or [])],
            }
        }


@post("/{simulation_id:str}/compare")
async def compare_nodes(request: Request, simulation_id: str, data: dict) -> dict:
    # Accept a flexible payload (node ids may be strings in the frontend). Validate and coerce here.
    # Log incoming body to help debug invalid requests from older frontend bundles
    try:
        logger.debug("compare_nodes payload: %s", data)
    except Exception:
        pass
    node_a_raw = data.get("node_a")
    node_b_raw = data.get("node_b")
    use_llm = bool(data.get("use_llm", False))
    locale = data.get("locale", "en")

    if node_a_raw is None or node_b_raw is None:
        raise HTTPException(status_code=400, detail=T('api.errors.missing_nodes'))

    try:
        node_a = int(node_a_raw)
        node_b = int(node_b_raw)
    except Exception:
        raise HTTPException(status_code=400, detail=T('api.errors.invalid_node_ids'))

    async with get_session() as session:
        token = extract_bearer_token(request)
        current_user = await resolve_current_user(session, token)
        sim, record = await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        tree = record.tree

    a = tree.nodes.get(int(node_a))
    b = tree.nodes.get(int(node_b))
    if a is None or b is None:
        raise HTTPException(status_code=400, detail=T('api.errors.node_not_found'))

    logs_a = a.get("logs") or []
    logs_b = b.get("logs") or []

    # lightweight event sequence diff: events only in A / only in B based on stringified content
    set_a = set((str(ev.get("type")) + ":" + str(ev.get("data")) for ev in logs_a))
    set_b = set((str(ev.get("type")) + ":" + str(ev.get("data")) for ev in logs_b))
    only_a = [ev for ev in logs_a if (str(ev.get("type")) + ":" + str(ev.get("data")) ) not in set_b]
    only_b = [ev for ev in logs_b if (str(ev.get("type")) + ":" + str(ev.get("data")) ) not in set_a]

    # agent property diffs (compare numeric properties when possible)
    sim_a = a.get("sim")
    sim_b = b.get("sim")
    agents_a = {name: getattr(ag, "properties", {}) for name, ag in (sim_a.agents.items() if sim_a else [])}
    agents_b = {name: getattr(ag, "properties", {}) for name, ag in (sim_b.agents.items() if sim_b else [])}
    agent_diffs = {}
    for name in set(list(agents_a.keys()) + list(agents_b.keys())):
        pa = agents_a.get(name, {})
        pb = agents_b.get(name, {})
        diffs = {}
        for k in set(list(pa.keys()) + list(pb.keys())):
            va = pa.get(k)
            vb = pb.get(k)
            if va != vb:
                diffs[k] = {"a": va, "b": vb}
        if diffs:
            agent_diffs[name] = diffs

    # node metadata for labelling
    meta_a = a.get("meta") or {}
    meta_b = b.get("meta") or {}
    label_a = meta_a.get("variant_name") or meta_a.get("experiment_name") or f"Node {node_a}"
    label_b = meta_b.get("variant_name") or meta_b.get("experiment_name") or f"Node {node_b}"
    sim_a_state = a.get("sim")
    sim_b_state = b.get("sim")
    round_a = getattr(sim_a_state, "turns", None) or len(logs_a) if sim_a_state else len(logs_a)
    round_b = getattr(sim_b_state, "turns", None) or len(logs_b) if sim_b_state else len(logs_b)

    # construct a conservative natural-language summary from diffs (no external LLM by default)
    parts: List[str] = []
    parts.append(f"{label_a} (node {node_a}, ~{round_a} rounds): {len(only_a)} unique events")
    parts.append(f"{label_b} (node {node_b}, ~{round_b} rounds): {len(only_b)} unique events")
    if agent_diffs:
        parts.append(T('api.compare.agent_property_diffs', count=len(agent_diffs)))
    if not parts:
        parts.append(T('api.compare.no_obvious_diff'))

    summary = "；".join(parts)

    # Optional: use LLM to produce a short, conservative summary if requested and safe
    if use_llm:
        # Safety checks / usage guards
        total_events = len(only_a) + len(only_b)
        if total_events > 200 or len(agent_diffs) > 50:
            # Avoid expensive/hallucination-prone calls for very large diffs
            summary = summary + T('api.errors.llm_disabled_large_diff')
        else:
            # Try to get an LLM client from the tree's clients if available
            llm_client = None
            try:
                llm_client = getattr(tree, "clients", {}).get("chat") if hasattr(tree, "clients") else None
            except Exception:
                llm_client = None

            if llm_client is None:
                summary = summary + T('api.errors.llm_no_client')
            else:
                # Build compact prompt with counts and a few examples (limit length)
                def stringify_event(ev: dict) -> str:
                    try:
                        t = ev.get("type") or ev.get("event_type") or ""
                        d = ev.get("data") or {}
                        return f"{t}: {str(d)[:200]}"
                    except Exception:
                        return str(ev)[:200]

                examples_a = "\n".join([stringify_event(e) for e in only_a[:8]])
                examples_b = "\n".join([stringify_event(e) for e in only_b[:8]])
                agent_diff_lines = []
                for name, diffs in list(agent_diffs.items())[:20]:
                    for k, v in list(diffs.items())[:5]:
                        agent_diff_lines.append(f"{name}.{k}: A={v.get('a')} B={v.get('b')}")
                agent_diff_text = "\n".join(agent_diff_lines[:200])

                if locale.startswith("zh"):
                    lang_instr_system = "in Chinese"
                    lang_instr_user = "Please respond in Chinese, <= 3 sentences."
                else:
                    lang_instr_system = "in English"
                    lang_instr_user = "Please respond in English, <= 3 sentences."

                system_msg = {
                    "role": "system",
                    "content": (
                        "You are a concise and conservative summarizer for simulation diffs. "
                        f"Given only the provided diff examples and agent property differences, produce a short (<=3 sentences) summary {lang_instr_system} describing the most likely notable differences and avoid hallucinating any facts not present in the input. "
                        "If uncertain, say so briefly."
                    ),
                }
                user_msg = {
                    "role": "user",
                    "content": (
                        f"Group A: {label_a} (node {node_a}, ~{round_a} rounds), unique events={len(only_a)}. Examples:\n{examples_a}\n\n"
                        f"Group B: {label_b} (node {node_b}, ~{round_b} rounds), unique events={len(only_b)}. Examples:\n{examples_b}\n\n"
                        f"Agent property differences (sample):\n{agent_diff_text}\n\n"
                        f"{lang_instr_user} Use only the above information."
                    ),
                }

                # Estimate token consumption (very conservative): chars/4
                prompt_text = (system_msg["content"] + "\n" + user_msg["content"]) if isinstance(system_msg, dict) else str(system_msg) + "\n" + str(user_msg)
                est_tokens = max(1, int(len(prompt_text) / 4))

                # Check per-user/provider quota before calling LLM and reserve tokens (DB-level lock)
                try:
                    result = await session.execute(select(ProviderConfig).where(ProviderConfig.user_id == sim.owner_id))
                    providers = result.scalars().all()
                    active = [p for p in providers if (p.config or {}).get("active")]
                    provider = active[0] if active else (providers[0] if providers else None)
                except Exception:
                    provider = None

                quota_allowed = True
                usage = None
                if provider is not None:
                    quota = int((provider.config or {}).get("quota", 100000))
                    # Acquire a DB lock on the LLMUsage row to reserve tokens
                    try:
                        async with session.begin():
                            stmt = select(LLMUsage).where(LLMUsage.user_id == sim.owner_id, LLMUsage.provider_id == provider.id).with_for_update()
                            res = await session.execute(stmt)
                            usage = res.scalars().first()
                            if usage is None:
                                usage = LLMUsage(user_id=sim.owner_id, provider_id=provider.id, tokens_used=0, tokens_reserved=0)
                                session.add(usage)
                                await session.flush()
                            # check available tokens (used + reserved cannot exceed quota)
                            available = quota - ((usage.tokens_used or 0) + (usage.tokens_reserved or 0))
                            if available < est_tokens:
                                quota_allowed = False
                            else:
                                # reserve tokens
                                usage.tokens_reserved = (usage.tokens_reserved or 0) + est_tokens
                                await session.flush()
                    except Exception:
                        # If any DB locking error, fall back to denying LLM to be safe
                        quota_allowed = False

                if not quota_allowed:
                    summary = summary + T('api.errors.llm_quota_exhausted')
                else:
                    try:
                        text = llm_client.chat([system_msg, user_msg])
                        if isinstance(text, str) and text.strip():
                            # Truncate to reasonable length
                            summary = (text.strip()[:1000])
                        # on success, consume reserved tokens (best-effort)
                        if provider is not None and usage is not None:
                            try:
                                async with session.begin():
                                    # re-load with lock
                                    stmt2 = select(LLMUsage).where(LLMUsage.user_id == sim.owner_id, LLMUsage.provider_id == provider.id).with_for_update()
                                    r2 = await session.execute(stmt2)
                                    u2 = r2.scalars().first()
                                    if u2 is not None:
                                        u2.tokens_reserved = max(0, (u2.tokens_reserved or 0) - est_tokens)
                                        u2.tokens_used = (u2.tokens_used or 0) + est_tokens
                                        await session.flush()
                            except Exception:
                                # best-effort: ignore usage persist errors
                                pass
                    except Exception:
                        # On LLM failure, release reserved tokens
                        if provider is not None and usage is not None:
                            try:
                                async with session.begin():
                                    stmt3 = select(LLMUsage).where(LLMUsage.user_id == sim.owner_id, LLMUsage.provider_id == provider.id).with_for_update()
                                    r3 = await session.execute(stmt3)
                                    u3 = r3.scalars().first()
                                    if u3 is not None:
                                        u3.tokens_reserved = max(0, (u3.tokens_reserved or 0) - est_tokens)
                                        await session.flush()
                            except Exception:
                                pass

    return {
        "node_a": int(node_a),
        "node_b": int(node_b),
        "only_in_a": only_a,
        "only_in_b": only_b,
        "agent_diffs": agent_diffs,
        "summary": summary,
    }


router = Router(path="/simulations", route_handlers=[create_experiment, run_experiment, list_experiments, get_experiment, compare_nodes])
