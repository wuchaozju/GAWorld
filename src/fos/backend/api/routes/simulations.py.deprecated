import asyncio
import copy
import logging
from datetime import datetime, timezone
from urllib.parse import unquote

from jose import JWTError, jwt
from litestar import Router, delete, get, patch, post, websocket
from litestar.connection import Request, WebSocket
from litestar.datastructures import UploadFile
from litestar.exceptions import WebSocketDisconnect, HTTPException  # ✅ 新增 HTTPException
from litestar.enums import RequestEncodingType
from litestar.params import Body
from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from socialsim4.core.llm import create_llm_client
from socialsim4.core.llm_config import LLMConfig, guess_supports_vision
from socialsim4.core.search_config import SearchConfig
from socialsim4.core.simtree import SimTree
from socialsim4.core.tools.web.search import create_search_client

from ...core.database import get_session
from ...dependencies import extract_bearer_token, resolve_current_user, settings
from ...models.simulation import Simulation, SimulationLog, SimulationSnapshot
from ...models.user import ProviderConfig, SearchProviderConfig, User
from ...schemas.common import Message
from ...schemas.simtree import (
    SimulationTreeAdvanceChainPayload,
    SimulationTreeAdvanceFrontierPayload,
    SimulationTreeAdvanceMultiPayload,
    SimulationTreeBranchPayload,
)
from ...schemas.simulation import (
    SimulationBase,
    SimulationCreate,
    SimulationLogEntry,
    SimulationUpdate,
    SnapshotBase,
    SnapshotCreate,
)
from ...services.simtree_runtime import SIM_TREE_REGISTRY, SimTreeRecord
from ...services.simulations import generate_simulation_id, generate_simulation_name
from ...services.documents import process_document, composite_rag_retrieval, format_rag_context, generate_embedding


logger = logging.getLogger(__name__)


async def _get_simulation_for_owner(
    session: AsyncSession,
    owner_id: int,
    simulation_id: str,
) -> Simulation:
    result = await session.execute(
        select(Simulation).where(
            Simulation.owner_id == owner_id, Simulation.id == simulation_id.upper()
        )
    )
    return result.scalar_one()


async def _get_tree_record(
    sim: Simulation, session: AsyncSession, user_id: int
) -> SimTreeRecord:
    # 根据 user_id（也就是 sim.owner_id）加载对应的 LLM Provider
    result = await session.execute(
        select(ProviderConfig).where(ProviderConfig.user_id == user_id)
    )
    items = result.scalars().all()
    active = [p for p in items if (p.config or {}).get("active")]
    if len(active) != 1:
        raise HTTPException(status_code=400, detail="LLM provider not configured (need exactly one active)")
    provider = active[0]
    dialect = (provider.provider or "").lower()
    if dialect not in {"openai", "gemini", "mock", "ollama"}:
        raise HTTPException(status_code=400, detail="Invalid LLM provider dialect")
    if dialect in {"openai", "gemini"} and not provider.api_key:
        raise HTTPException(status_code=400, detail="LLM API key required")
    if not provider.model:
        raise HTTPException(status_code=400, detail="LLM model required")

    cfg = LLMConfig(
        dialect=dialect,
        api_key=provider.api_key or "",
        model=provider.model,
        base_url=provider.base_url or ("http://127.0.0.1:11434" if dialect == "ollama" else None),
        temperature=0.7,
        top_p=1.0,
        frequency_penalty=0.0,
        presence_penalty=0.0,
        max_tokens=1024,
        supports_vision=guess_supports_vision(provider.model),
    )
    llm_client = create_llm_client(cfg)

    # 搜索 Provider
    result_s = await session.execute(
        select(SearchProviderConfig).where(SearchProviderConfig.user_id == user_id)
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
    clients = {"chat": llm_client, "default": llm_client, "search": search_client}
    return await SIM_TREE_REGISTRY.get_or_create_from_sim(sim, clients)


async def _get_simulation_and_tree(
    session: AsyncSession,
    owner_id: int,
    simulation_id: str,
) -> tuple[Simulation, SimTreeRecord]:
    sim = await _get_simulation_for_owner(session, owner_id, simulation_id)
    record = await _get_tree_record(sim, session, owner_id)
    return sim, record


# ✅ 新增：不依赖当前登录用户，而是直接按 simulation_id + sim.owner_id 找树
async def _get_simulation_and_tree_any(
    session: AsyncSession,
    simulation_id: str,
) -> tuple[Simulation, SimTreeRecord]:
    sim = await session.get(Simulation, simulation_id.upper())
    if sim is None:
        raise HTTPException(status_code=404, detail="Simulation not found")
    record = await _get_tree_record(sim, session, sim.owner_id)
    return sim, record


async def _resolve_user_from_token(token: str, session: AsyncSession) -> User | None:
    if not token:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.jwt_signing_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return None
    subject = payload.get("sub")
    if subject is None:
        return None
    user = await session.get(User, int(subject))
    if user is None or not user.is_active:
        return None
    return user


def _broadcast(record: SimTreeRecord, event: dict) -> None:
    # 树级广播：仅用于 HTTP 触发的 run_start / run_finish / attached 等事件
    for queue in list(record.subs):
        try:
            queue.put_nowait(event)
        except Exception:
            logger.exception("failed to enqueue tree-level broadcast event")


# -------------------------------------------------------------------
# 基本 Simulation CRUD（仍然需要鉴权）
# -------------------------------------------------------------------


@get("/")
async def list_simulations(request: Request) -> list[SimulationBase]:
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
async def create_simulation(request: Request, data: SimulationCreate) -> SimulationBase:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        result = await session.execute(
            select(ProviderConfig).where(ProviderConfig.user_id == current_user.id)
        )
        provider = result.scalars().first()
        if provider is None:
            raise RuntimeError("LLM provider not configured")
        dialect = (provider.provider or "").lower()
        if dialect not in {"openai", "gemini", "mock", "ollama"}:
            raise RuntimeError("Invalid LLM provider dialect")
        if dialect in {"openai", "gemini"} and not provider.api_key:
            raise RuntimeError("LLM API key required")
        if not provider.model:
            raise RuntimeError("LLM model required")

        sim_id = generate_simulation_id()
        name = data.name or generate_simulation_name(sim_id)
        sim = Simulation(
            id=sim_id,
            owner_id=current_user.id,
            name=name,
            scene_type=data.scene_type,
            scene_config=data.scene_config,
            agent_config=data.agent_config,
            status="draft",
        )
        session.add(sim)
        await session.commit()
        await session.refresh(sim)
        return SimulationBase.model_validate(sim)


@get("/{simulation_id:str}")
async def read_simulation(request: Request, simulation_id: str) -> SimulationBase:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)
        return SimulationBase.model_validate(sim)


@patch("/{simulation_id:str}")
async def update_simulation(
    request: Request, simulation_id: str, data: SimulationUpdate
) -> SimulationBase:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)

        if data.name is not None:
            sim.name = data.name
        if data.status is not None:
            sim.status = data.status
        if data.notes is not None:
            sim.notes = data.notes
        if data.agent_config is not None:
            print(f"[KB-DEBUG] update_simulation: Received agent_config update for sim {simulation_id}")

            # IMPORTANT: Merge the incoming agent_config with existing config to preserve documents
            # The frontend may only send updated fields (e.g., new KB items), so we need to merge
            # rather than replace to avoid losing documents, knowledgeBase, and other agent fields
            existing_agent_config = copy.deepcopy(sim.agent_config) if sim.agent_config else {"agents": []}
            incoming_agents = data.agent_config.get("agents", [])
            existing_agents = existing_agent_config.get("agents", [])

            # Create a map of existing agents by name for quick lookup
            existing_by_name = {agent.get("name"): agent for agent in existing_agents}

            # Merge incoming agents with existing agents
            merged_agents = []
            for incoming_agent in incoming_agents:
                agent_name = incoming_agent.get("name")
                if agent_name in existing_by_name:
                    # Merge: keep existing documents and other fields, update with incoming data
                    merged_agent = copy.deepcopy(existing_by_name[agent_name])
                    # Update only the fields that were explicitly provided in incoming data
                    for key, value in incoming_agent.items():
                        merged_agent[key] = value
                    merged_agents.append(merged_agent)
                else:
                    # New agent, use as-is
                    merged_agents.append(incoming_agent)

            # Keep any agents that were in existing but not in incoming
            for existing_agent in existing_agents:
                agent_name = existing_agent.get("name")
                if agent_name not in {a.get("name") for a in incoming_agents}:
                    merged_agents.append(copy.deepcopy(existing_agent))

            merged_config = copy.deepcopy(data.agent_config)
            merged_config["agents"] = merged_agents

            agents_in_config = merged_config.get("agents", [])
            for i, agent in enumerate(agents_in_config):
                kb = agent.get("knowledgeBase", [])
                docs = agent.get("documents", {})
                print(f"[KB-DEBUG]   Agent {i} '{agent.get('name', 'unknown')}': {len(kb)} knowledge items, {len(docs)} documents")
                for j, item in enumerate(kb):
                    print(f"[KB-DEBUG]     KB Item {j}: id={item.get('id')}, title='{item.get('title', '')[:50]}', enabled={item.get('enabled')}")
                for j, (doc_id, doc) in enumerate(docs.items()):
                    print(f"[KB-DEBUG]     Doc Item {j}: id={doc_id}, filename='{doc.get('filename', 'unknown')}'")

            sim.agent_config = merged_config
            # Explicitly mark as modified for SQLAlchemy to detect the change
            flag_modified(sim, "agent_config")

            # CRITICAL: Update the agent knowledge bases in the cached SimTree
            # The tree is cached in memory and won't see database changes unless we update it
            # Use update_agent_knowledge to preserve existing simulation state while updating knowledge
            updated = SIM_TREE_REGISTRY.update_agent_knowledge(simulation_id, merged_config)
            if not updated:
                # No cached tree exists - it will be built fresh on next access with the new config
                print(f"[KB-DEBUG] update_simulation: No cached tree to update for sim {simulation_id}")

        if data.scene_config is not None:
            # Merge scene_config with existing to preserve other settings
            existing_scene_config = sim.scene_config or {}
            merged_scene_config = {**existing_scene_config, **data.scene_config}
            sim.scene_config = merged_scene_config
            flag_modified(sim, "scene_config")
            print(f"[ENV-DEBUG] update_simulation: Updated scene_config for sim {simulation_id}, environment_enabled={merged_scene_config.get('environment_enabled')}, social_network={merged_scene_config.get('social_network', {})}")

        await session.commit()
        await session.refresh(sim)
        return SimulationBase.model_validate(sim)


@delete("/{simulation_id:str}", status_code=204)
async def delete_simulation(request: Request, simulation_id: str) -> None:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)
        await session.delete(sim)
        await session.commit()
        SIM_TREE_REGISTRY.remove(simulation_id)


@post("/{simulation_id:str}/reset")
async def reset_simulation(request: Request, simulation_id: str) -> Message:
    """重新构建仿真树，清空日志/快照并返回成功消息。"""
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)

        # 清空日志与快照，移除运行态树
        await session.execute(sa_delete(SimulationLog).where(SimulationLog.simulation_id == sim.id))
        await session.execute(sa_delete(SimulationSnapshot).where(SimulationSnapshot.simulation_id == sim.id))
        sim.latest_state = None
        await session.commit()
        SIM_TREE_REGISTRY.remove(sim.id)

        # 重新创建树并登记
        await _get_tree_record(sim, session, current_user.id)

        return Message(message="Simulation reset and tree rebuilt")


@post("/{simulation_id:str}/save", status_code=201)
async def create_snapshot(
    request: Request, simulation_id: str, data: SnapshotCreate
) -> SnapshotBase:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)
        record = SIM_TREE_REGISTRY.get(simulation_id)
        if record is None:
            record = await _get_tree_record(sim, session, current_user.id)
        tree_state = record.tree.serialize()
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
        # 同步更新 simulation.latest_state，方便重启后恢复
        sim.latest_state = tree_state
        await session.commit()
        await session.refresh(snapshot)
        return SnapshotBase.model_validate(snapshot)


@get("/{simulation_id:str}/snapshots")
async def list_snapshots(request: Request, simulation_id: str) -> list[SnapshotBase]:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)
        result = await session.execute(
            select(SimulationSnapshot)
            .where(SimulationSnapshot.simulation_id == sim.id)
            .order_by(SimulationSnapshot.created_at.desc())
        )
        snapshots = result.scalars().all()
        return [SnapshotBase.model_validate(s) for s in snapshots]


@get("/{simulation_id:str}/logs")
async def list_logs(
    request: Request, simulation_id: str, limit: int = 200
) -> list[SimulationLogEntry]:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)
        result = await session.execute(
            select(SimulationLog)
            .where(SimulationLog.simulation_id == sim.id)
            .order_by(SimulationLog.sequence.desc())
            .limit(limit)
        )
        logs = list(reversed(result.scalars().all()))
        return [SimulationLogEntry.model_validate(log) for log in logs]


@post("/{simulation_id:str}/start")
async def start_simulation(request: Request, simulation_id: str) -> Message:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)
        sim.status = "running"
        sim.updated_at = datetime.now(timezone.utc)
        await session.commit()
        return Message(message="Simulation start enqueued")


@post("/{simulation_id:str}/resume")
async def resume_simulation(
    request: Request, simulation_id: str, snapshot_id: int | None = None
) -> Message:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)
        record = await _get_tree_record(sim, session, current_user.id)

        if snapshot_id is not None:
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
        return Message(message="Simulation resume enqueued")


@post("/{simulation_id:str}/copy", status_code=201)
async def copy_simulation(request: Request, simulation_id: str) -> SimulationBase:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)

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


# -------------------------------------------------------------------
# SimTree HTTP 接口（✅ 改成不再依赖当前登录用户，直接按 simulation_id + owner_id）
# -------------------------------------------------------------------


@get("/{simulation_id:str}/tree/graph")
async def simulation_tree_graph(request: Request, simulation_id: str) -> dict:
    async with get_session() as session:
        # ✅ 不再强制 extract_bearer_token，直接按 simulation_id 找 sim + tree
        sim, record = await _get_simulation_and_tree_any(session, simulation_id)
        tree = record.tree

        attached_ids = {
            int(nid)
            for nid, node in tree.nodes.items()
            if node.get("depth") is not None
        }
        nodes = [
            {"id": int(node["id"]), "depth": int(node["depth"])}
            for node in tree.nodes.values()
            if node.get("depth") is not None
        ]
        edges = []
        for pid, children in tree.children.items():
            if pid not in attached_ids:
                continue
            for cid in children:
                if cid not in attached_ids:
                    continue
                et = tree.nodes[cid]["edge_type"]
                edges.append({"from": int(pid), "to": int(cid), "type": et})

        depth_map = {
            int(node["id"]): int(node["depth"])
            for node in tree.nodes.values()
            if node.get("depth") is not None
        }
        outdeg = {i: 0 for i in depth_map}
        for edge in edges:
            outdeg[edge["from"]] = outdeg.get(edge["from"], 0) + 1
        leaves = [i for i, degree in outdeg.items() if degree == 0]
        max_depth = max(depth_map.values()) if depth_map else 0
        frontier = [i for i in leaves if depth_map.get(i) == max_depth]

        return {
            "root": int(tree.root) if tree.root is not None else None,
            "frontier": frontier,
            "running": [int(n) for n in record.running],
            "nodes": nodes,
            "edges": edges,
        }


@post("/{simulation_id:str}/tree/advance_frontier")
async def simulation_tree_advance_frontier(
    request: Request,
    simulation_id: str,
    data: SimulationTreeAdvanceFrontierPayload,
) -> dict:
    async with get_session() as session:
        sim, record = await _get_simulation_and_tree_any(session, simulation_id)
        tree = record.tree
        parents = tree.frontier(True) if data.only_max_depth else tree.leaves()
        turns = int(data.turns)
        allocations = {pid: tree.copy_sim(pid) for pid in parents}
        for pid, cid in allocations.items():
            tree.attach(pid, [{"op": "advance", "turns": turns}], cid)
            node = tree.nodes[cid]
            _broadcast(
                record,
                {
                    "type": "attached",
                    "data": {
                        "node": int(cid),
                        "parent": int(pid),
                        "depth": int(node["depth"]),
                        "edge_type": node["edge_type"],
                        "ops": node["ops"],
                    },
                },
            )
            record.running.add(cid)
            _broadcast(record, {"type": "run_start", "data": {"node": int(cid)}})
        await asyncio.sleep(0)

        async def _run(parent_id: int) -> tuple[int, int, bool]:
            child_id = allocations[parent_id]
            simulator = tree.nodes[child_id]["sim"]
            # Ensure one advance step covers all agents once
            total_turns = max(1, turns) * max(1, len(simulator.agents))
            await asyncio.to_thread(simulator.run, max_turns=total_turns)
            return parent_id, child_id, False

        results = await asyncio.gather(*[_run(pid) for pid in parents])
        produced: list[int] = []
        for *_pid, cid, _err in results:
            produced.append(cid)
            if cid in record.running:
                record.running.remove(cid)
            _broadcast(record, {"type": "run_finish", "data": {"node": int(cid)}})
        # 持久化最新树状态，便于重启后恢复
        sim.latest_state = tree.serialize()
        await session.commit()
        return {"children": [int(c) for c in produced]}


@post("/{simulation_id:str}/tree/advance_multi")
async def simulation_tree_advance_multi(
    request: Request,
    simulation_id: str,
    data: SimulationTreeAdvanceMultiPayload,
) -> dict:
    async with get_session() as session:
        sim, record = await _get_simulation_and_tree_any(session, simulation_id)
        tree = record.tree
        parent = int(data.parent)
        count = int(data.count)
        if count <= 0:
            return {"children": []}
        turns = int(data.turns)
        children = [tree.copy_sim(parent) for _ in range(count)]
        for cid in children:
            tree.attach(parent, [{"op": "advance", "turns": turns}], cid)
            node = tree.nodes[cid]
            _broadcast(
                record,
                {
                    "type": "attached",
                    "data": {
                        "node": int(cid),
                        "parent": int(parent),
                        "depth": int(node["depth"]),
                        "edge_type": node["edge_type"],
                        "ops": node["ops"],
                    },
                },
            )
            record.running.add(cid)
            _broadcast(record, {"type": "run_start", "data": {"node": int(cid)}})
        await asyncio.sleep(0)

        async def _run(child_id: int) -> tuple[int, bool]:
            simulator = tree.nodes[child_id]["sim"]
            total_turns = max(1, turns) * max(1, len(simulator.agents))
            await asyncio.to_thread(simulator.run, max_turns=total_turns)
            return child_id, False

        finished = await asyncio.gather(*[_run(cid) for cid in children])
        result_children: list[int] = []
        for cid, _err in finished:
            result_children.append(cid)
            if cid in record.running:
                record.running.remove(cid)
            _broadcast(record, {"type": "run_finish", "data": {"node": int(cid)}})
        sim.latest_state = tree.serialize()
        await session.commit()
        return {"children": [int(c) for c in result_children]}


@post("/{simulation_id:str}/tree/advance_chain")
async def simulation_tree_advance_chain(
    request: Request,
    simulation_id: str,
    data: SimulationTreeAdvanceChainPayload,
) -> dict:
    async with get_session() as session:
        sim, record = await _get_simulation_and_tree_any(session, simulation_id)
        tree = record.tree
        parent = int(data.parent)
        steps = max(1, int(data.turns))
        last = parent
        for _ in range(steps):
            cid = tree.copy_sim(last)
            tree.attach(last, [{"op": "advance", "turns": 1}], cid)
            node = tree.nodes[cid]
            _broadcast(
                record,
                {
                    "type": "attached",
                    "data": {
                        "node": int(cid),
                        "parent": int(last),
                        "depth": int(node["depth"]),
                        "edge_type": node["edge_type"],
                        "ops": node["ops"],
                    },
                },
            )
            record.running.add(cid)
            _broadcast(record, {"type": "run_start", "data": {"node": int(cid)}})
            await asyncio.sleep(0)

            simulator = tree.nodes[cid]["sim"]
            total_turns = 1 * max(1, len(simulator.agents))
            await asyncio.to_thread(simulator.run, max_turns=total_turns)

            if cid in record.running:
                record.running.remove(cid)
            _broadcast(record, {"type": "run_finish", "data": {"node": int(cid)}})
            last = cid
        sim.latest_state = tree.serialize()
        await session.commit()
        return {"child": int(last)}


@post("/{simulation_id:str}/tree/branch")
async def simulation_tree_branch(
    request: Request,
    simulation_id: str,
    data: SimulationTreeBranchPayload,
) -> dict:
    async with get_session() as session:
        sim, record = await _get_simulation_and_tree_any(session, simulation_id)
        tree = record.tree
        cid = tree.branch(int(data.parent), [dict(op) for op in data.ops])
        node = tree.nodes[cid]
        _broadcast(
            record,
            {
                "type": "attached",
                "data": {
                    "node": int(cid),
                    "parent": int(node["parent"]),
                    "depth": int(node["depth"]),
                    "edge_type": node["edge_type"],
                    "ops": node["ops"],
                },
            },
        )
        sim.latest_state = tree.serialize()
        await session.commit()
        return {"child": int(cid)}


@delete("/{simulation_id:str}/tree/node/{node_id:int}")
async def simulation_tree_delete_subtree(
    request: Request,
    simulation_id: str,
    node_id: int,
) -> None:
    async with get_session() as session:
        _, record = await _get_simulation_and_tree_any(session, simulation_id)
        record.tree.delete_subtree(int(node_id))
        _broadcast(record, {"type": "deleted", "data": {"node": int(node_id)}})


@get("/{simulation_id:str}/tree/sim/{node_id:int}/events")
async def simulation_tree_events(
    request: Request, simulation_id: str, node_id: int
) -> list:
    async with get_session() as session:
        _, record = await _get_simulation_and_tree_any(session, simulation_id)
        node = record.tree.nodes.get(int(node_id))
        if node is None:
            raise HTTPException(status_code=404, detail="Tree node not found")
        return node.get("logs", [])


@get("/{simulation_id:str}/tree/sim/{node_id:int}/state")
async def simulation_tree_state(
    request: Request, simulation_id: str, node_id: int
) -> dict:
    print(f"[KB-DEBUG] simulation_tree_state: Fetching state for sim={simulation_id}, node={node_id}")
    async with get_session() as session:
        sim, record = await _get_simulation_and_tree_any(session, simulation_id)
        node = record.tree.nodes.get(int(node_id))
        if node is None:
            raise HTTPException(status_code=404, detail="Tree node not found")
        simulator = node["sim"]
        agents = []
        for name, agent in simulator.agents.items():
            props = dict(agent.properties)
            role = props.get("role") or getattr(agent, "role_prompt", "") or ""
            if role and "role" not in props:
                props["role"] = role
            profile = agent.user_profile or props.get("profile") or props.get("description") or ""
            kb = getattr(agent, "knowledge_base", [])
            docs = getattr(agent, "documents", {})
            print(f"[KB-DEBUG] simulation_tree_state: Agent '{name}' has {len(kb)} KB items, {len(docs)} documents")
            for i, item in enumerate(kb):
                print(f"[KB-DEBUG]   KB[{i}]: id={item.get('id')}, title='{item.get('title', '')[:40]}', enabled={item.get('enabled')}")
            for doc_id, doc in docs.items():
                print(f"[KB-DEBUG]   Doc: id={doc_id}, filename='{doc.get('filename', 'unknown')}'")
            agents.append(
                {
                    "name": name,
                    "profile": profile,
                    "role": role,
                    "properties": props,
                    "emotion": agent.emotion,
                    "plan_state": agent.plan_state,
                    "short_memory": agent.short_memory.get_all(),
                    "knowledgeBase": kb,
                    "documents": docs,
                }
            )
        # Include scene_config from the simulation record so frontend can access social_network
        scene_config = sim.scene_config or {}
        social_network = scene_config.get("social_network", {})
        print(f"[NETWORK-DEBUG] simulation_tree_state: returning scene_config with social_network: {social_network}")
        return {"turns": simulator.turns, "agents": agents, "scene_config": scene_config}


@get("/{simulation_id:str}/tree/sim/{node_id:int}/test-knowledge")
async def test_agent_knowledge(
    request: Request, simulation_id: str, node_id: int
) -> dict:
    """
    Test endpoint to verify agent knowledge bases are working.

    Query params:
        agent_name: Optional specific agent name to test (tests all if not provided)
        query: Optional search query to test knowledge retrieval

    Returns:
        Dict with agent knowledge details and query results
    """
    # Extract query params from request
    agent_name = request.query_params.get("agent_name")
    query = request.query_params.get("query")
    print(f"[KB-DEBUG] test_agent_knowledge: sim={simulation_id}, node={node_id}, agent={agent_name}, query={query}")
    async with get_session() as session:
        _, record = await _get_simulation_and_tree_any(session, simulation_id)
        node = record.tree.nodes.get(int(node_id))
        if node is None:
            raise HTTPException(status_code=404, detail="Tree node not found")
        simulator = node["sim"]

        results = []
        for name, agent in simulator.agents.items():
            if agent_name and name != agent_name:
                continue

            kb = getattr(agent, "knowledge_base", [])
            enabled_kb = [item for item in kb if item.get("enabled", True)]

            agent_result = {
                "name": name,
                "total_knowledge_items": len(kb),
                "enabled_knowledge_items": len(enabled_kb),
                "knowledge_base": kb,
            }

            # If a query is provided, test the query_knowledge method
            if query and hasattr(agent, "query_knowledge"):
                query_results = agent.query_knowledge(query, top_k=5)
                agent_result["query"] = query
                agent_result["query_results"] = query_results

            # Also get the knowledge context that would be included in prompts
            if hasattr(agent, "get_knowledge_context"):
                context = agent.get_knowledge_context(query or "test")
                agent_result["knowledge_context_preview"] = context[:500] if context else ""

            results.append(agent_result)

        return {
            "simulation_id": simulation_id,
            "node_id": node_id,
            "agent_count": len(simulator.agents),
            "agents": results
        }


@post("/{simulation_id:str}/tree/sim/{node_id:int}/ask-agents")
async def ask_agents_question(
    request: Request, simulation_id: str, node_id: int, data: dict
) -> dict:
    """
    Ask all agents a question and get their responses based on their knowledge.
    This proves each agent uses their individual RAG knowledge.

    POST body: {"question": "What is the village budget?", "agent_name": "optional"}

    Returns each agent's response showing they use their specific knowledge.
    """
    question = data.get("question", "What do you know?")
    target_agent = data.get("agent_name")

    print(f"\n{'='*60}")
    print(f"[KB-DEBUG] ask_agents_question: sim={simulation_id}, node={node_id}")
    print(f"[KB-DEBUG] Question: '{question}'")
    print(f"[KB-DEBUG] Target agent: {target_agent or 'ALL'}")
    print(f"{'='*60}")

    async with get_session() as session:
        sim, record = await _get_simulation_and_tree_any(session, simulation_id)
        node = record.tree.nodes.get(int(node_id))
        if node is None:
            raise HTTPException(status_code=404, detail="Tree node not found")
        simulator = node["sim"]

        # Get the LLM client from simulator
        llm_client = simulator.clients.get("chat") or simulator.clients.get("default")
        if llm_client is None:
            raise HTTPException(status_code=500, detail="No LLM client available")

        # Get global knowledge from the scene_config
        scene_config = sim.scene_config or {}
        global_knowledge = scene_config.get("global_knowledge", {})

        results = []
        for name, agent in simulator.agents.items():
            if target_agent and name != target_agent:
                continue

            # Gather all knowledge sources for this agent
            kb_items = getattr(agent, "knowledge_base", [])
            enabled_kb = [item for item in kb_items if item.get("enabled", True)]
            documents = getattr(agent, "documents", {})
            agent_config = sim.agent_config or {}
            agents_list = agent_config.get("agents", [])
            agent_cfg = next((a for a in agents_list if a.get("name") == name), {})
            cfg_documents = agent_cfg.get("documents", {})

            print(f"\n[KB-DEBUG] --- Agent: {name} ---")
            print(f"[KB-DEBUG] Free-text KB items: {len(enabled_kb)}")
            print(f"[KB-DEBUG] Private documents: {len(cfg_documents)}")
            print(f"[KB-DEBUG] Global knowledge items: {len(global_knowledge)}")

            # Build knowledge context using composite_rag_retrieval
            knowledge_context = ""
            knowledge_sources = []

            # 1. Add free-text knowledge base items
            if enabled_kb:
                kb_items_list = []
                for i, item in enumerate(enabled_kb, 1):
                    title = item.get("title", "Untitled")
                    content = item.get("content", "")
                    kb_items_list.append(f"[KB-{i}] {title}:\n{content}")
                    knowledge_sources.append(title)
                    print(f"[KB-DEBUG]   Free-text KB: '{title}'")
                knowledge_context += "\n\n### Your Free-text Knowledge:\n" + "\n\n".join(kb_items_list)

            # 2. Use composite_rag_retrieval to get relevant chunks from documents and global knowledge
            # Note: composite_rag_retrieval returns list[dict], not dict with "chunks" key
            retrieval_result = await asyncio.to_thread(
                composite_rag_retrieval,
                question,
                agent_documents=cfg_documents,  # Agent's private documents
                global_knowledge=global_knowledge,  # Global knowledge shared with all agents
                top_k=5
            )

            if retrieval_result:
                formatted_context = await asyncio.to_thread(
                    format_rag_context,
                    retrieval_result
                )
                if formatted_context:
                    knowledge_context += "\n\n### Retrieved Knowledge:\n" + formatted_context
                    for chunk in retrieval_result:
                        source = chunk.get("source", "Unknown")
                        if source not in knowledge_sources:
                            knowledge_sources.append(source)
                    print(f"[KB-DEBUG]   Retrieved {len(retrieval_result)} chunks from documents")

            # Build a prompt asking the question with all knowledge
            if knowledge_context:
                prompt = f"""You are {name}. {agent.user_profile}

{knowledge_context}

Based on your knowledge above, please answer this question concisely:
{question}

If you have specific information in your knowledge base about this, use it. If not, say you don't have that information."""
            else:
                prompt = f"""You are {name}. {agent.user_profile}

Based on your knowledge (if any), please answer this question concisely:
{question}

If you don't have specific information about this, say so."""

            print(f"[KB-DEBUG] Knowledge sources: {knowledge_sources}")
            print(f"[KB-DEBUG] Sending prompt to LLM...")
            print(f"[KB-DEBUG] Prompt includes knowledge: {bool(knowledge_context)}")

            try:
                # Call the LLM using the chat method
                messages = [{"role": "user", "content": prompt}]
                response = await asyncio.to_thread(
                    llm_client.chat,
                    messages
                )

                # Extract response text - the chat method returns the content directly
                if isinstance(response, str):
                    answer = response
                elif hasattr(response, 'choices') and response.choices:
                    answer = response.choices[0].message.content
                elif isinstance(response, dict):
                    answer = response.get("choices", [{}])[0].get("message", {}).get("content", str(response))
                else:
                    answer = str(response)

                print(f"[KB-DEBUG] Response from {name}:")
                print(f"[KB-DEBUG] >>> {answer[:200]}{'...' if len(answer) > 200 else ''}")

                results.append({
                    "agent_name": name,
                    "knowledge_count": len(enabled_kb) + len(cfg_documents) + len(global_knowledge),
                    "knowledge_sources": knowledge_sources,
                    "question": question,
                    "answer": answer,
                    "success": True
                })

            except Exception as e:
                print(f"[KB-DEBUG] ERROR for {name}: {e}")
                results.append({
                    "agent_name": name,
                    "knowledge_count": len(enabled_kb) + len(cfg_documents),
                    "question": question,
                    "answer": f"Error: {str(e)}",
                    "success": False
                })

        print(f"\n{'='*60}")
        print(f"[KB-DEBUG] Completed asking {len(results)} agents")
        print(f"{'='*60}\n")

        return {
            "simulation_id": simulation_id,
            "node_id": node_id,
            "question": question,
            "responses": results
        }


# -------------------------------------------------------------------
# WebSocket：仍然沿用 token 鉴权（给后台 DevUI 用）
# -------------------------------------------------------------------


@websocket("/{simulation_id:str}/tree/events")
async def simulation_tree_events_ws(socket: WebSocket, simulation_id: str) -> None:
    token = socket.query_params.get("token")
    async with get_session() as session:
        user = await _resolve_user_from_token(token or "", session)
        if user is None:
            await socket.close(code=1008)
            return
        sim = await _get_simulation_for_owner(session, user.id, simulation_id)
        record = await _get_tree_record(sim, session, user.id)

    await socket.accept()
    queue: asyncio.Queue = asyncio.Queue()
    record.subs.append(queue)
    logger.debug("WS tree events subscribed: sim=%s", simulation_id)
    try:
        while True:
            event = await queue.get()
            try:
                await socket.send_json(event)
            except WebSocketDisconnect as e:
                logger.info(
                    "WebSocket disconnected (tree events) for sim %s: %s",
                    simulation_id,
                    e,
                )
                break
            except Exception:
                logger.exception("WS send_json failed for sim %s (tree events)", simulation_id)
                break
    finally:
        if queue in record.subs:
            record.subs.remove(queue)
        logger.debug("WS tree events unsubscribed: sim=%s", simulation_id)


@websocket("/{simulation_id:str}/tree/{node_id:int}/events")
async def simulation_tree_node_events_ws(
    socket: WebSocket,
    simulation_id: str,
    node_id: int,
) -> None:
    # Accept token from query param, Authorization header, or cookie (dev-friendly fallback)
    token = socket.query_params.get("token")
    if not token:
        auth_header = None
        try:
            auth_header = socket.headers.get("authorization") or socket.headers.get("Authorization")
        except Exception:
            auth_header = None
        if auth_header and isinstance(auth_header, str) and auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()

    if not token:
        try:
            token = socket.cookies.get("socialsim4.access")
        except Exception:
            token = None

    async with get_session() as session:
        user = await _resolve_user_from_token(token or "", session)
        if user is None:
            await socket.close(code=1008)
            return
        sim = await _get_simulation_for_owner(session, user.id, simulation_id)
        record = await _get_tree_record(sim, session, user.id)

        if int(node_id) not in record.tree.nodes:
            await socket.close(code=1008)
            return

    await socket.accept()
    queue: asyncio.Queue = asyncio.Queue()
    record.tree.add_node_sub(int(node_id), queue)
    logger.debug("WS node events subscribed: sim=%s node=%s", simulation_id, node_id)
    try:
        while True:
            event = await queue.get()
            try:
                await socket.send_json(event)
            except WebSocketDisconnect as e:
                logger.info(
                    "WebSocket disconnected (node events) for sim %s node %s: %s",
                    simulation_id,
                    node_id,
                    e,
                )
                break
            except Exception:
                logger.exception(
                    "WS send_json failed for sim %s node %s (node events)",
                    simulation_id,
                    node_id,
                )
                break
    finally:
        record.tree.remove_node_sub(int(node_id), queue)
        logger.debug("WS node events unsubscribed: sim=%s node=%s", simulation_id, node_id)


# -------------------------------------------------------------------
# Document Upload Endpoints (Per-Agent Private Knowledge)
# -------------------------------------------------------------------

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx", ".md"}


@post("/{simulation_id:str}/agents/{agent_name:str}/documents")
async def upload_agent_document(
    request: Request,
    simulation_id: str,
    agent_name: str,
    data: UploadFile = Body(media_type=RequestEncodingType.MULTI_PART),
) -> dict:
    """
    Upload a document to an agent's private knowledge base.

    Accepts: PDF, TXT, DOCX, MD files (max 10MB)
    Returns: {success: true, doc_id: str, chunks_count: int, agent_name: str}
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)

        filename = data.filename
        file_content = await data.read()
        file_size = len(file_content)

        logger.info(f"File upload initiated - sim_id={simulation_id}, agent={agent_name}, file={filename}, size={file_size}")

        # Validate file extension
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            logger.error(f"Upload failed - sim_id={simulation_id}, agent={agent_name}, reason=Invalid file type {ext}")
            raise HTTPException(status_code=400, detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

        # Validate file size
        if file_size > MAX_FILE_SIZE:
            logger.error(f"Upload failed - sim_id={simulation_id}, agent={agent_name}, reason=File too large ({file_size} bytes)")
            raise HTTPException(status_code=400, detail=f"File too large. Max size: {MAX_FILE_SIZE // (1024*1024)}MB")

        logger.debug(f"File validation - type={ext}, size_ok={file_size <= MAX_FILE_SIZE}")

        # Process document (extract, chunk, embed using MiniLM)
        try:
            document = await asyncio.to_thread(
                process_document,
                file_content,
                filename,
                file_size,
            )
        except ImportError as e:
            logger.error(f"Upload failed - sim_id={simulation_id}, agent={agent_name}, reason=Missing dependency: {e}")
            raise HTTPException(
                status_code=500,
                detail="Document processing requires 'sentence-transformers' package. Please install it: pip install sentence-transformers"
            )
        except Exception as e:
            logger.exception(f"Upload failed - sim_id={simulation_id}, agent={agent_name}, reason={e}")
            raise HTTPException(
                status_code=500,
                detail=f"Document processing failed: {str(e)}"
            )

        # Update simulation agent_config with the new document
        # Use deep copy to ensure SQLAlchemy detects the change
        agent_config = copy.deepcopy(sim.agent_config) if sim.agent_config else {}
        agents = agent_config.get("agents", [])

        # Find the target agent
        agent_found = False
        for agent in agents:
            if agent.get("name") == agent_name:
                agent_found = True
                # Initialize documents dict if not present
                if "documents" not in agent:
                    agent["documents"] = {}
                agent["documents"][document["id"]] = document
                break

        if not agent_found:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

        agent_config["agents"] = agents
        sim.agent_config = agent_config
        # Explicitly mark JSON column as modified to ensure SQLAlchemy persists it
        flag_modified(sim, "agent_config")

        await session.commit()

        # Update cached tree if exists
        SIM_TREE_REGISTRY.update_agent_knowledge(simulation_id, agent_config)

        logger.info(f"Document stored - doc_id={document['id']}, chunks={len(document['chunks'])}")

        return {
            "success": True,
            "doc_id": document["id"],
            "chunks_count": len(document["chunks"]),
            "agent_name": agent_name,
            "filename": filename,
        }


@get("/{simulation_id:str}/agents/{agent_name:str}/documents")
async def list_agent_documents(
    request: Request,
    simulation_id: str,
    agent_name: str,
) -> list[dict]:
    """
    List all documents uploaded to an agent's private knowledge base.

    Query params:
        node_id: Optional node ID to fetch documents from in-memory tree.
                 If provided, fetches from the tree node's agent.
                 If not provided, fetches from database config.
    """
    # URL-decode the agent_name to handle spaces and special characters
    agent_name = unquote(agent_name)

    token = extract_bearer_token(request)
    node_id_param = request.query_params.get("node_id")

    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)

        # If node_id is provided, try to fetch from in-memory tree first
        if node_id_param is not None:
            try:
                node_id = int(node_id_param)
                record = SIM_TREE_REGISTRY.get(simulation_id)
                if record is not None:
                    node = record.tree.nodes.get(node_id)
                    if node is not None:
                        simulator = node["sim"]
                        agent = simulator.agents.get(agent_name)
                        if agent is not None:
                            documents = getattr(agent, "documents", {})
                            return [
                                {
                                    "id": doc["id"],
                                    "filename": doc["filename"],
                                    "file_size": doc["file_size"],
                                    "uploaded_at": doc["uploaded_at"],
                                    "chunks_count": len(doc.get("chunks", [])),
                                }
                                for doc in documents.values()
                            ]
            except (ValueError, KeyError):
                pass  # Fall through to database lookup

        # Fall back to database config
        agent_config = sim.agent_config or {}
        agents = agent_config.get("agents", [])

        for agent in agents:
            if agent.get("name") == agent_name:
                documents = agent.get("documents", {})
                return [
                    {
                        "id": doc["id"],
                        "filename": doc["filename"],
                        "file_size": doc["file_size"],
                        "uploaded_at": doc["uploaded_at"],
                        "chunks_count": len(doc.get("chunks", [])),
                    }
                    for doc in documents.values()
                ]

        # Return empty list instead of 404 when agent has no documents
        # This handles newly created agents that don't have documents yet
        return []


@delete("/{simulation_id:str}/agents/{agent_name:str}/documents/{doc_id:str}", status_code=200)
async def delete_agent_document(
    request: Request,
    simulation_id: str,
    agent_name: str,
    doc_id: str,
) -> dict:
    """
    Delete a document from an agent's private knowledge base.
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)

        agent_config = copy.deepcopy(sim.agent_config) if sim.agent_config else {}
        agents = agent_config.get("agents", [])

        for agent in agents:
            if agent.get("name") == agent_name:
                documents = agent.get("documents", {})
                if doc_id not in documents:
                    raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")

                del documents[doc_id]
                agent["documents"] = documents
                agent_config["agents"] = agents
                sim.agent_config = agent_config
                flag_modified(sim, "agent_config")

                await session.commit()

                # Update cached tree if exists
                SIM_TREE_REGISTRY.update_agent_knowledge(simulation_id, agent_config)

                logger.info(f"Document deleted - doc_id={doc_id}, agent={agent_name}, sim={simulation_id}")

                return {"success": True, "deleted_doc_id": doc_id}

        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")


# -------------------------------------------------------------------
# Global Knowledge Base Endpoints
# -------------------------------------------------------------------

@post("/{simulation_id:str}/global-knowledge")
async def add_global_knowledge(
    request: Request,
    simulation_id: str,
    data: dict,
) -> dict:
    """
    Add text content to the global knowledge base.

    Body: {content: str, title?: str}
    Returns: {success: true, kw_id: str}
    """
    import uuid

    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)

        content = data.get("content")
        title = data.get("title", "")

        if not content:
            raise HTTPException(status_code=400, detail="Content is required")

        logger.info(f"Global knowledge add initiated - sim_id={simulation_id}, source=manual_text")

        # Generate embedding using MiniLM
        logger.debug("Generating embedding for global knowledge using MiniLM")
        embedding = await asyncio.to_thread(generate_embedding, content)
        logger.info(f"Embedding generated - sim_id={simulation_id}")

        kw_id = f"gk_{uuid.uuid4().hex[:8]}"

        # Get or create global_knowledge in scene_config
        # Use deep copy to ensure SQLAlchemy detects the change
        scene_config = copy.deepcopy(sim.scene_config) if sim.scene_config else {}
        global_knowledge = scene_config.get("global_knowledge", {})

        global_knowledge[kw_id] = {
            "id": kw_id,
            "title": title,
            "content": content,
            "source_type": "manual_text",
            "filename": None,
            "created_by": str(current_user.id),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "embedding": embedding,
        }

        scene_config["global_knowledge"] = global_knowledge
        sim.scene_config = scene_config
        flag_modified(sim, "scene_config")

        await session.commit()

        # Update global knowledge in cached tree if exists
        SIM_TREE_REGISTRY.update_global_knowledge(simulation_id, global_knowledge)

        logger.info(f"Global knowledge stored - kw_id={kw_id}")

        return {"success": True, "kw_id": kw_id}


@post("/{simulation_id:str}/global-knowledge/documents")
async def upload_global_document(
    request: Request,
    simulation_id: str,
    data: UploadFile = Body(media_type=RequestEncodingType.MULTI_PART),
) -> dict:
    """
    Upload a document to the global knowledge base.

    Accepts: PDF, TXT, DOCX, MD files (max 10MB)
    Returns: {success: true, kw_id: str, chunks_count: int}
    """
    import uuid

    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)

        filename = data.filename
        file_content = await data.read()
        file_size = len(file_content)

        logger.info(f"Global document upload initiated - sim_id={simulation_id}, file={filename}, size={file_size}")

        # Validate file extension
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

        # Validate file size
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"File too large. Max size: {MAX_FILE_SIZE // (1024*1024)}MB")

        # Process document (extract, chunk, embed using MiniLM)
        try:
            document = await asyncio.to_thread(
                process_document,
                file_content,
                filename,
                file_size,
            )
        except ImportError as e:
            logger.error(f"Global upload failed - sim_id={simulation_id}, reason=Missing dependency: {e}")
            raise HTTPException(
                status_code=500,
                detail="Document processing requires 'sentence-transformers' package. Please install it: pip install sentence-transformers"
            )
        except Exception as e:
            logger.exception(f"Global upload failed - sim_id={simulation_id}, reason={e}")
            raise HTTPException(
                status_code=500,
                detail=f"Document processing failed: {str(e)}"
            )

        kw_id = f"gk_{uuid.uuid4().hex[:8]}"

        # Get or create global_knowledge in scene_config
        # Use deep copy to ensure SQLAlchemy detects the change
        scene_config = copy.deepcopy(sim.scene_config) if sim.scene_config else {}
        global_knowledge = scene_config.get("global_knowledge", {})

        global_knowledge[kw_id] = {
            "id": kw_id,
            "content": f"Document: {filename}",
            "source_type": "document",
            "filename": filename,
            "file_size": file_size,
            "created_by": str(current_user.id),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "chunks": document["chunks"],
            "embeddings": document["embeddings"],
        }

        scene_config["global_knowledge"] = global_knowledge
        sim.scene_config = scene_config
        flag_modified(sim, "scene_config")

        await session.commit()

        # Update global knowledge in cached tree if exists
        SIM_TREE_REGISTRY.update_global_knowledge(simulation_id, global_knowledge)

        logger.info(f"Global document stored - kw_id={kw_id}, chunks={len(document['chunks'])}")

        return {
            "success": True,
            "kw_id": kw_id,
            "chunks_count": len(document["chunks"]),
            "filename": filename,
        }


@get("/{simulation_id:str}/global-knowledge")
async def list_global_knowledge(
    request: Request,
    simulation_id: str,
) -> list[dict]:
    """
    List all items in the global knowledge base.
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)

        scene_config = sim.scene_config or {}
        global_knowledge = scene_config.get("global_knowledge", {})

        return [
            {
                "id": kw["id"],
                "title": kw.get("title", kw.get("filename", "Untitled")),
                "content_preview": kw.get("content", "")[:200],
                "source_type": kw.get("source_type", "unknown"),
                "filename": kw.get("filename"),
                "created_at": kw.get("created_at"),
                "chunks_count": len(kw.get("chunks", [])) if "chunks" in kw else 0,
            }
            for kw in global_knowledge.values()
        ]


@delete("/{simulation_id:str}/global-knowledge/{kw_id:str}", status_code=200)
async def delete_global_knowledge(
    request: Request,
    simulation_id: str,
    kw_id: str,
) -> dict:
    """
    Delete an item from the global knowledge base.
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)

        scene_config = copy.deepcopy(sim.scene_config) if sim.scene_config else {}
        global_knowledge = scene_config.get("global_knowledge", {})

        if kw_id not in global_knowledge:
            raise HTTPException(status_code=404, detail=f"Global knowledge item '{kw_id}' not found")

        del global_knowledge[kw_id]
        scene_config["global_knowledge"] = global_knowledge
        sim.scene_config = scene_config
        flag_modified(sim, "scene_config")

        await session.commit()

        # Update global knowledge in cached tree if exists
        SIM_TREE_REGISTRY.update_global_knowledge(simulation_id, global_knowledge)

        logger.info(f"Global knowledge deleted - kw_id={kw_id}, sim={simulation_id}")

        return {"success": True, "deleted_kw_id": kw_id}


@get("/{simulation_id:str}/agents/{agent_name:str}/memory")
async def get_agent_memory(
    request: Request,
    simulation_id: str,
    agent_name: str,
) -> dict:
    """
    Get an agent's memory to see what messages they have received.

    This helps verify that social network filtering is working correctly -
    agents should only have messages from agents they share an edge with.

    Query params:
        node_id: Optional node ID to fetch from in-memory tree.
                 If not provided, fetches from latest database snapshot.
    """
    # URL-decode the agent_name to handle spaces and special characters
    agent_name = unquote(agent_name)

    token = extract_bearer_token(request)
    node_id_param = request.query_params.get("node_id")

    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await _get_simulation_for_owner(session, current_user.id, simulation_id)

        agent_data = None

        # If node_id is provided, try to fetch from in-memory tree
        if node_id_param is not None:
            try:
                node_id = int(node_id_param)
                record = SIM_TREE_REGISTRY.get(simulation_id)
                if record is not None:
                    node = record.tree.nodes.get(node_id)
                    if node is not None:
                        simulator = node["sim"]
                        agent = simulator.agents.get(agent_name)
                        if agent is not None:
                            # Extract message sources from env_feedback
                            env_feedback = getattr(agent, "env_feedback", [])
                            seen_messages_from = _extract_senders_from_feedback(env_feedback)

                            # Get connections from social network
                            scene = simulator.scene
                            social_network = scene.state.get("social_network", {})
                            connections = social_network.get(agent_name, [])

                            agent_data = {
                                "name": agent_name,
                                "node_id": node_id,
                                "env_feedback_count": len(env_feedback),
                                "env_feedback_preview": env_feedback[-10:] if env_feedback else [],
                                "seen_messages_from": seen_messages_from,
                                "social_network_connections": connections,
                                "total_agents": len(simulator.agents),
                            }
            except (ValueError, KeyError):
                pass  # Fall through to database lookup

        # If no agent_data from tree, or no node_id, we can't get live data
        # Return a message indicating this requires a running simulation
        if agent_data is None:
            return {
                "name": agent_name,
                "error": "Agent memory not available. Provide a valid node_id from a running simulation.",
                "hint": "Use /tree/graph to get available nodes, then query with ?node_id=<node>",
            }

        return agent_data


def _extract_senders_from_feedback(env_feedback: list) -> dict:
    """Extract unique senders from environment feedback messages."""
    seen_from = {}
    for feedback in env_feedback:
        # Try to extract sender name from feedback string
        # Format is typically: "[HH:MM] SenderName: message"
        feedback_str = str(feedback)
        parts = feedback_str.split(":", 1)
        if len(parts) >= 2:
            # Extract name from the first part (after time stamp if present)
            first_part = parts[0].strip()
            # Remove [HH:MM] timestamp if present
            if "] " in first_part:
                first_part = first_part.split("] ", 1)[1] if "] " in first_part else first_part
            if first_part and first_part not in seen_from:
                seen_from[first_part] = seen_from.get(first_part, 0) + 1
            # Count all messages from this sender
            seen_from[first_part] = seen_from.get(first_part, 0) + 1
    return seen_from


router = Router(
    path="/simulations",
    route_handlers=[
        list_simulations,
        create_simulation,
        read_simulation,
        update_simulation,
        delete_simulation,
        reset_simulation,
        create_snapshot,
        list_snapshots,
        list_logs,
        start_simulation,
        resume_simulation,
        copy_simulation,
        simulation_tree_graph,
        simulation_tree_advance_frontier,
        simulation_tree_advance_multi,
        simulation_tree_advance_chain,
        simulation_tree_branch,
        simulation_tree_delete_subtree,
        simulation_tree_events,
        simulation_tree_state,
        test_agent_knowledge,
        ask_agents_question,
        simulation_tree_events_ws,
        simulation_tree_node_events_ws,
        # Document upload endpoints
        upload_agent_document,
        list_agent_documents,
        delete_agent_document,
        # Agent memory endpoint (for testing social network)
        get_agent_memory,
        # Global knowledge endpoints
        add_global_knowledge,
        upload_global_document,
        list_global_knowledge,
        delete_global_knowledge,
    ],
)