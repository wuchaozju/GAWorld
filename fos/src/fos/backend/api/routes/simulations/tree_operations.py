"""
Simulation tree manipulation API routes.

Handles operations on the branching timeline structure of simulations.
Includes graph queries, tree advancement, branching, and subtree deletion.

The tree structure allows for exploring alternate simulation paths
by creating branches at any node.

Contains:
    - simulation_tree_graph: Get tree structure visualization
    - simulation_tree_advance_frontier: Advance leaf nodes
    - simulation_tree_advance_multi: Batch advance multiple nodes
    - simulation_tree_advance_chain: Advance following parent chain
    - simulation_tree_branch: Create new branch from node
    - simulation_tree_delete_subtree: Delete branch from node
    - simulation_tree_events: Get events for node
    - simulation_tree_state: Get state at node
    - test_agent_knowledge: Test RAG retrieval for agent
    - ask_agents_question: Broadcast question to agents
"""

import asyncio
import logging

from litestar import get, post, delete
from litestar.connection import Request
from litestar.exceptions import HTTPException

from fos.backend.core.timing import log_time

from fos.backend.core.config import get_settings
from fos.backend.core.database import get_session
from fos.backend.models.simulation import Simulation
from fos.backend.schemas.simtree import (
    SimulationTreeAdvanceChainPayload,
    SimulationTreeAdvanceFrontierPayload,
    SimulationTreeAdvanceMultiPayload,
    SimulationTreeBranchPayload,
    SimulationTreeAgentOverridePayload,
)

from .helpers import (
    get_simulation_and_tree_for_owner,
    broadcast_tree_event,
)
from fos.backend.services.simtree_runtime import (
    get_runtime_agent_count,
    get_runtime_agent_map,
    get_runtime_agent_profile,
)
from fos.backend.services.simtree_advance import (
    get_advance_turn_count,
    record_advance_runtime_failure,
    run_simulator_for_advance,
)
from fos.backend.services.runtime_tasks import RUNTIME_TASKS
from fos.backend.services.documents import composite_rag_retrieval, format_rag_context
from fos.backend.dependencies import extract_bearer_token, resolve_current_user
from fos.i18n import T


logger = logging.getLogger(__name__)


def _node_advance_task_id(simulation_id: str, node_id: int) -> str:
    return f"node_advance:{simulation_id.upper()}:{int(node_id)}"


def _start_node_advance_task(
    simulation_id: str,
    *,
    node_id: int,
    parent_id: int,
    op: str,
    turns: int,
) -> str:
    task_id = _node_advance_task_id(simulation_id, node_id)
    RUNTIME_TASKS.start(
        "node_advance",
        f"Advance node {node_id}",
        task_id=task_id,
        status="running",
        metadata={
            "simulation_id": simulation_id.upper(),
            "node": int(node_id),
            "parent": int(parent_id),
            "op": op,
            "turns": int(turns),
        },
    )
    return task_id


@get("/{simulation_id:str}/tree/graph")
async def simulation_tree_graph(
    request: Request,
    simulation_id: str,
) -> dict:
    """
    Get the simulation tree structure for visualization.

    Returns nodes, edges, and metadata about the tree including
    the root node, frontier nodes (leaves at max depth), and
    currently running nodes.

    Args:
        request: Litestar request
        simulation_id: Simulation identifier

    Returns:
        Dictionary with tree structure:
        - root: Root node ID
        - frontier: Leaf nodes at maximum depth
        - running: Currently executing node IDs
        - nodes: List of all nodes with depth
        - edges: List of edges between nodes

    Raises:
        HTTPException: If simulation not found
    """
    try:
        token = extract_bearer_token(request)
        async with get_session() as session:
            current_user = await resolve_current_user(session, token)
            sim, record = await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
            tree = record.tree

            logger.debug(f"[TREE_GRAPH] sim={simulation_id} tree.root={tree.root} nodes.count={len(tree.nodes)}")

            # Get attached nodes (nodes with depth)
            attached_ids = {
                int(nid)
                for nid, node in tree.nodes.items()
                if node.get("depth") is not None
            }

            nodes = [
                {
                    "id": int(node["id"]),
                    "depth": int(node["depth"]),
                    "meta": node.get("meta", {}),
                }
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

            # Calculate depth map and find leaves
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

            result = {
                "root": int(tree.root) if tree.root is not None else None,
                "frontier": frontier,
                "running": [int(n) for n in record.running],
                "nodes": nodes,
                "edges": edges,
            }
            logger.debug(f"[TREE_GRAPH] returning root={result['root']} nodes={len(result['nodes'])} edges={len(result['edges'])}")
            return result
    except Exception as e:
        logger.exception(f"[TREE_GRAPH] Error building graph for sim {simulation_id}: {e}")
        raise


@post("/{simulation_id:str}/tree/advance_frontier")
async def simulation_tree_advance_frontier(
    request: Request,
    simulation_id: str,
    data: SimulationTreeAdvanceFrontierPayload,
) -> dict:
    """
    Advance the frontier (leaf nodes) of the simulation tree.

    Creates new child nodes from all frontier nodes (or just
    max-depth leaves if only_max_depth is True) and runs them
    for the specified number of turns.

    Args:
        request: Litestar request
        simulation_id: Simulation identifier
        data: Advance parameters (turns, only_max_depth)

    Returns:
        Dictionary with list of created child node IDs

    Raises:
        HTTPException: If simulation not found
    """
    async with get_session() as session:
        token = extract_bearer_token(request)
        current_user = await resolve_current_user(session, token)
        sim, record = await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        tree = record.tree

        parents = tree.frontier(True) if data.only_max_depth else tree.leaves()
        turns = int(data.turns)

        # Enforce runaway simulation controls
        settings = get_settings()
        if len(parents) > settings.max_frontier_nodes_per_request:
            raise HTTPException(
                status_code=400,
                detail=T("api.errors.too_many_frontier_nodes", count=len(parents), max=settings.max_frontier_nodes_per_request),
            )
        if turns > settings.max_advance_turns_per_request:
            raise HTTPException(
                status_code=400,
                detail=T("api.errors.too_many_turns", turns=turns, max=settings.max_advance_turns_per_request),
            )

        # Create copies for each parent
        allocations = {pid: tree.copy_sim(pid) for pid in parents}

        for pid, cid in allocations.items():
            tree.attach(pid, [{"op": "advance", "turns": turns}], cid)
            node = tree.nodes[cid]
            broadcast_tree_event(
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
            _start_node_advance_task(
                simulation_id,
                node_id=int(cid),
                parent_id=int(pid),
                op="advance_frontier",
                turns=turns,
            )
            broadcast_tree_event(record, {"type": "run_start", "data": {"node": int(cid)}})

        await asyncio.sleep(0)

        async def _run(
            parent_id: int,
        ) -> tuple[int, int, RuntimeError | FileNotFoundError | None]:
            child_id = allocations[parent_id]
            simulator = tree.nodes[child_id]["sim"]
            total_turns = get_advance_turn_count(simulator, turns)
            try:
                with log_time("SIM", sim_id=simulation_id, node=child_id, turns=total_turns, op="advance_frontier"):
                    run_error = await run_simulator_for_advance(simulator, max_turns=total_turns)
            except Exception as exc:
                RUNTIME_TASKS.fail(_node_advance_task_id(simulation_id, child_id), exc)
                raise
            return parent_id, child_id, run_error

        try:
            results = await asyncio.gather(*[_run(pid) for pid in parents])
        except Exception:
            for cid in allocations.values():
                if cid in record.running:
                    record.running.remove(cid)
                broadcast_tree_event(record, {"type": "run_finish", "data": {"node": int(cid)}})
            raise
        produced: list[int] = []

        for *_pid, cid, run_error in results:
            produced.append(cid)
            if run_error is not None:
                message = record_advance_runtime_failure(
                    tree.nodes[cid],
                    tree.nodes[cid]["sim"],
                    run_error,
                )
                broadcast_tree_event(
                    record,
                    {
                        "type": "run_failed",
                        "data": {"node": int(cid), "error": message},
                    },
                )
                RUNTIME_TASKS.fail(_node_advance_task_id(simulation_id, cid), message)
            else:
                RUNTIME_TASKS.finish(_node_advance_task_id(simulation_id, cid))
            if cid in record.running:
                record.running.remove(cid)
            broadcast_tree_event(record, {"type": "run_finish", "data": {"node": int(cid)}})

        # Persist latest tree state
        sim.latest_state = tree.serialize()
        await session.commit()

        return {"children": [int(c) for c in produced]}


@post("/{simulation_id:str}/tree/advance_multi")
async def simulation_tree_advance_multi(
    request: Request,
    simulation_id: str,
    data: SimulationTreeAdvanceMultiPayload,
) -> dict:
    """
    Advance multiple copies from a single parent node.

    Creates multiple child nodes from the same parent and runs
    them in parallel. Useful for exploring multiple what-if
    scenarios from the same starting point.

    Args:
        request: Litestar request
        simulation_id: Simulation identifier
        data: Advance parameters (parent, count, turns)

    Returns:
        Dictionary with list of created child node IDs

    Raises:
        HTTPException: If simulation not found
    """
    async with get_session() as session:
        token = extract_bearer_token(request)
        current_user = await resolve_current_user(session, token)
        sim, record = await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        tree = record.tree

        parent = int(data.parent)
        count = int(data.count)

        if count <= 0:
            return {"children": []}

        turns = int(data.turns)

        # Enforce runaway simulation controls
        settings = get_settings()
        if count > settings.max_advance_multi_count:
            raise HTTPException(
                status_code=400,
                detail=T("api.errors.too_many_parallel_advances", count=count, max=settings.max_advance_multi_count),
            )
        if turns > settings.max_advance_turns_per_request:
            raise HTTPException(
                status_code=400,
                detail=T("api.errors.too_many_turns", turns=turns, max=settings.max_advance_turns_per_request),
            )

        children = [tree.copy_sim(parent) for _ in range(count)]

        for cid in children:
            tree.attach(parent, [{"op": "advance", "turns": turns}], cid)
            node = tree.nodes[cid]
            broadcast_tree_event(
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
            _start_node_advance_task(
                simulation_id,
                node_id=int(cid),
                parent_id=int(parent),
                op="advance_multi",
                turns=turns,
            )
            broadcast_tree_event(record, {"type": "run_start", "data": {"node": int(cid)}})

        await asyncio.sleep(0)

        async def _run(
            child_id: int,
        ) -> tuple[int, RuntimeError | FileNotFoundError | None]:
            simulator = tree.nodes[child_id]["sim"]
            total_turns = get_advance_turn_count(simulator, turns)
            try:
                with log_time("SIM", sim_id=simulation_id, node=child_id, turns=total_turns, op="advance_multi"):
                    run_error = await run_simulator_for_advance(simulator, max_turns=total_turns)
            except Exception as exc:
                RUNTIME_TASKS.fail(_node_advance_task_id(simulation_id, child_id), exc)
                raise
            return child_id, run_error

        try:
            finished = await asyncio.gather(*[_run(cid) for cid in children])
        except Exception:
            for cid in children:
                if cid in record.running:
                    record.running.remove(cid)
                broadcast_tree_event(record, {"type": "run_finish", "data": {"node": int(cid)}})
            raise
        result_children: list[int] = []

        for cid, run_error in finished:
            result_children.append(cid)
            if run_error is not None:
                message = record_advance_runtime_failure(
                    tree.nodes[cid],
                    tree.nodes[cid]["sim"],
                    run_error,
                )
                broadcast_tree_event(
                    record,
                    {
                        "type": "run_failed",
                        "data": {"node": int(cid), "error": message},
                    },
                )
                RUNTIME_TASKS.fail(_node_advance_task_id(simulation_id, cid), message)
            else:
                RUNTIME_TASKS.finish(_node_advance_task_id(simulation_id, cid))
            if cid in record.running:
                record.running.remove(cid)
            broadcast_tree_event(record, {"type": "run_finish", "data": {"node": int(cid)}})

        sim.latest_state = tree.serialize()
        await session.commit()

        return {"children": [int(c) for c in result_children]}


@post("/{simulation_id:str}/tree/advance_chain")
async def simulation_tree_advance_chain(
    request: Request,
    simulation_id: str,
    data: SimulationTreeAdvanceChainPayload,
) -> dict:
    """
    Advance in a chain from a parent node.

    Creates a linear chain of nodes, each advancing one turn
    from the previous. Useful for sequential "what happens next"
    exploration.

    Args:
        request: Litestar request
        simulation_id: Simulation identifier
        data: Advance parameters (parent, turns)

    Returns:
        Dictionary with the final child node ID

    Raises:
        HTTPException: If simulation not found
    """
    try:
        # Phase 1: Load simulation and tree record (short DB session)
        token = extract_bearer_token(request)
        async with get_session() as session:
            current_user = await resolve_current_user(session, token)
            sim, record = await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        # DB session released — simulation and tree are in-memory objects.

        tree = record.tree

        parent = int(data.parent)
        steps = max(1, int(data.turns))

        # Enforce runaway simulation controls
        settings = get_settings()
        if steps > settings.max_advance_turns_per_request:
            raise HTTPException(
                status_code=400,
                detail=T("api.errors.too_many_chain_steps", steps=steps, max=settings.max_advance_turns_per_request),
            )

        last = parent

        async with record._advance_lock:
            for _ in range(steps):
                cid = tree.copy_sim(last)
                tree.attach(last, [{"op": "advance", "turns": 1}], cid)
                node = tree.nodes[cid]
                broadcast_tree_event(
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
                _start_node_advance_task(
                    simulation_id,
                    node_id=int(cid),
                    parent_id=int(last),
                    op="advance_chain",
                    turns=1,
                )
                broadcast_tree_event(record, {"type": "run_start", "data": {"node": int(cid)}})
                await asyncio.sleep(0)

                simulator = tree.nodes[cid]["sim"]
                total_turns = get_advance_turn_count(simulator, 1)
                run_error: RuntimeError | FileNotFoundError | None = None
                task_failed = False
                logger.info(f"[ADVANCE_CHAIN] Running simulator for node {cid}, max_turns={total_turns}")
                try:
                    with log_time("SIM", sim_id=simulation_id, node=cid, turns=total_turns, step=_, op="advance_chain"):
                        run_error = await run_simulator_for_advance(simulator, max_turns=total_turns)
                    if run_error is not None:
                        message = record_advance_runtime_failure(node, simulator, run_error)
                        broadcast_tree_event(
                            record,
                            {
                                "type": "run_failed",
                                "data": {"node": int(cid), "error": message},
                            },
                        )
                        RUNTIME_TASKS.fail(_node_advance_task_id(simulation_id, cid), message)
                        logger.warning(
                            "[ADVANCE_CHAIN] Simulator runtime failed for node %s; returning child for log hydration",
                            cid,
                        )
                        last = cid
                        break
                    logger.info(f"[ADVANCE_CHAIN] Simulator run complete for node {cid}")

                    from fos.backend.services.simtree_runtime import ExperimentRunnerAdapter

                    if isinstance(simulator, ExperimentRunnerAdapter):
                        new_events = len(simulator.events)
                        node_logs = len(node.get('logs', []))
                        logger.info(f"[ADVANCE_CHAIN] Adapter events count: {new_events}, node logs count: {node_logs}")
                        if new_events == 0:
                            logger.warning(f"[ADVANCE_CHAIN] Node {cid} produced ZERO events — simulation may have failed silently")
                except Exception as exc:
                    task_failed = True
                    RUNTIME_TASKS.fail(_node_advance_task_id(simulation_id, cid), exc)
                    raise
                finally:
                    if run_error is None and not task_failed:
                        RUNTIME_TASKS.finish(_node_advance_task_id(simulation_id, cid))
                    if cid in record.running:
                        record.running.remove(cid)
                    broadcast_tree_event(record, {"type": "run_finish", "data": {"node": int(cid)}})
                last = cid

        # Phase 2: Persist updated tree state (short DB session)
        try:
            serialized = tree.serialize()
            logger.debug(f"[ADVANCE_CHAIN] Serialized tree with {len(serialized.get('nodes', []))} nodes")
        except Exception as e:
            logger.exception(f"[ADVANCE_CHAIN] Failed to serialize tree: {e}")
            raise

        async with get_session() as session:
            sim = await session.get(Simulation, simulation_id.upper())
            if sim is not None:
                sim.latest_state = serialized
                await session.commit()

        return {"child": int(last)}
    except Exception as e:
        logger.exception(f"[ADVANCE_CHAIN] Unhandled exception: {e}")
        raise


@post("/{simulation_id:str}/tree/branch")
async def simulation_tree_branch(
    request: Request,
    simulation_id: str,
    data: SimulationTreeBranchPayload,
) -> dict:
    """
    Create a new branch from a node.

    Creates a child node with custom operations (not just advance).
    Allows for more complex tree manipulations.

    Args:
        request: Litestar request
        simulation_id: Simulation identifier
        data: Branch parameters (parent, ops)

    Returns:
        Dictionary with the created child node ID

    Raises:
        HTTPException: If simulation not found
    """
    async with get_session() as session:
        token = extract_bearer_token(request)
        current_user = await resolve_current_user(session, token)
        sim, record = await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        tree = record.tree

        try:
            cid = tree.branch(int(data.parent), [dict(op) for op in data.ops])
        except KeyError as e:
            logger.warning(f"Branch failed - node not found: {e}")
            raise HTTPException(status_code=404, detail=T("api.errors.tree_node_not_found"))
        except Exception as e:
            logger.exception(f"Branch failed with unexpected error: {e}")
            raise HTTPException(status_code=500, detail=T("api.errors.branch_operation_failed", error=str(e)))
        node = tree.nodes[cid]

        broadcast_tree_event(
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


@delete("/{simulation_id:str}/tree/node/{node_id:int}", status_code=200)
async def simulation_tree_delete_subtree(
    request: Request,
    simulation_id: str,
    node_id: int,
) -> dict:
    """
    Delete a subtree from a node.

    Removes the specified node and all its descendants from
    the tree structure.

    Args:
        request: Litestar request
        simulation_id: Simulation identifier
        node_id: ID of node to delete (root not allowed)

    Raises:
        HTTPException: If simulation not found or trying to delete root
    """
    async with get_session() as session:
        token = extract_bearer_token(request)
        current_user = await resolve_current_user(session, token)
        sim, record = await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        record.tree.delete_subtree(int(node_id))
        sim.latest_state = record.tree.serialize()
        await session.commit()
        broadcast_tree_event(record, {"type": "deleted", "data": {"node": int(node_id)}})
        return {"ok": True}


@get("/{simulation_id:str}/tree/sim/{node_id:int}/events")
async def simulation_tree_events(
    request: Request,
    simulation_id: str,
    node_id: int,
) -> list:
    """
    Get events for a specific tree node.

    Returns the event log for the simulator state at the
    specified node.

    Args:
        request: Litestar request
        simulation_id: Simulation identifier
        node_id: Tree node ID

    Returns:
        List of event dictionaries

    Raises:
        HTTPException: If simulation or node not found
    """
    async with get_session() as session:
        token = extract_bearer_token(request)
        current_user = await resolve_current_user(session, token)
        _, record = await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        node = record.tree.nodes.get(int(node_id))

        if node is None:
            raise HTTPException(status_code=404, detail=T("api.errors.tree_node_not_found"))

        # Collect logs from this node and all descendants
        all_logs = list(node.get("logs", []))

        def _collect_descendant_logs(nid: int) -> list:
            logs: list = []
            for child_id in record.tree.children.get(nid, []):
                child_node = record.tree.nodes.get(child_id)
                if child_node is not None:
                    logs.extend(child_node.get("logs", []))
                    logs.extend(_collect_descendant_logs(child_id))
            return logs

        all_logs.extend(_collect_descendant_logs(int(node_id)))
        return all_logs


@get("/{simulation_id:str}/tree/sim/{node_id:int}/state")
async def simulation_tree_state(
    request: Request,
    simulation_id: str,
    node_id: int,
) -> dict:
    """
    Get the simulator state at a specific tree node.

    Returns detailed information about the simulation state
    including all agents, their properties, memories, and
    knowledge bases.

    Args:
        request: Litestar request
        simulation_id: Simulation identifier
        node_id: Tree node ID

    Returns:
        Dictionary with simulation state:
        - turns: Number of turns executed
        - agents: List of agent states
        - scene_config: Scene configuration including social_network

    Raises:
        HTTPException: If simulation or node not found
    """
    logger.debug(f"simulation_tree_state: Fetching state for sim={simulation_id}, node={node_id}")

    async with get_session() as session:
        token = extract_bearer_token(request)
        current_user = await resolve_current_user(session, token)
        sim, record = await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        node = record.tree.nodes.get(int(node_id))

        if node is None:
            raise HTTPException(status_code=404, detail=T("api.errors.tree_node_not_found"))

        simulator = node["sim"]
        agents = []

        # Handle ExperimentRunnerAdapter differently - agents are in scene.agents
        from fos.backend.services.simtree_runtime import ExperimentRunnerAdapter
        if isinstance(simulator, ExperimentRunnerAdapter):
            for agent in simulator.scene.agents:
                props = dict(agent.properties)
                role = agent.role_prompt or props.get("role") or ""
                if role and "role" not in props:
                    props["role"] = role
                profile = props.get("profile") or props.get("description") or ""
                kb = getattr(agent, "knowledge_base", [])
                docs = getattr(agent, "documents", {})
                action_history = getattr(agent, "action_history", [])
                score = getattr(agent, "score", 0)

                logger.debug(f"Agent '{agent.name}' has {len(kb)} KB items, {len(docs)} documents, {len(action_history)} actions, score={score}")

                # Serialize LLM config from the agent attribute, not properties.
                # llm_config is a top-level attribute (LLMConfig dataclass), not stored in props.
                llm_cfg = getattr(agent, "llm_config", None)
                if llm_cfg and hasattr(llm_cfg, "dialect"):
                    llm_config_out = {"provider": llm_cfg.dialect, "model": llm_cfg.model}
                elif isinstance(llm_cfg, dict):
                    llm_config_out = llm_cfg
                else:
                    llm_config_out = {}

                agents.append({
                    "name": agent.name,
                    "profile": profile,
                    "role": role,
                    "properties": props,
                    "short_memory": action_history,  # Map action_history to short_memory for frontend
                    "knowledgeBase": kb,
                    "documents": docs,
                    "score": score,
                    "provider_id": getattr(agent, "provider_id", None),
                    "llmConfig": llm_config_out,
                })
            turns = simulator.scene.current_round
        else:
            for name, agent in simulator.agents.items():
                props = dict(agent.properties)
                role = props.get("role") or getattr(agent, "role_prompt", "") or ""
                if role and "role" not in props:
                    props["role"] = role
                profile = agent.user_profile or props.get("profile") or props.get("description") or ""
                kb = getattr(agent, "knowledge_base", [])
                docs = getattr(agent, "documents", {})

                logger.debug(f"Agent '{name}' has {len(kb)} KB items, {len(docs)} documents")

                # Serialize LLM config from the agent attribute, not properties.
                llm_cfg = getattr(agent, "llm_config", None)
                if llm_cfg and hasattr(llm_cfg, "dialect"):
                    llm_config_out = {"provider": llm_cfg.dialect, "model": llm_cfg.model}
                elif isinstance(llm_cfg, dict):
                    llm_config_out = llm_cfg
                else:
                    llm_config_out = {}

                agents.append(
                    {
                        "name": name,
                        "profile": profile,
                        "role": role,
                        "properties": props,
                        "short_memory": agent.short_memory.get_all(),
                        "knowledgeBase": kb,
                        "documents": docs,
                        "provider_id": getattr(agent, "provider_id", None),
                        "llmConfig": llm_config_out,
                    }
                )
            turns = simulator.turns

        # Include scene_config for social_network access
        scene_config = sim.scene_config or {}
        social_network = scene_config.get("social_network", {})

        logger.debug(f"returning scene_config with social_network: {social_network}")

        return {
            "turns": turns,
            "agents": agents,
            "scene_config": scene_config
        }


@post("/{simulation_id:str}/tree/sim/{node_id:int}/overrides")
async def simulation_tree_apply_overrides(
    request: Request,
    simulation_id: str,
    node_id: int,
    data: SimulationTreeAgentOverridePayload,
) -> dict:
    async with get_session() as session:
        token = extract_bearer_token(request)
        current_user = await resolve_current_user(session, token)
        sim, record = await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        tree = record.tree

        tree.apply_agent_overrides(int(node_id), [ov.model_dump() for ov in data.overrides])

        sim.latest_state = tree.serialize()
        await session.commit()

        return {"ok": True}


@get("/{simulation_id:str}/tree/sim/{node_id:int}/test-knowledge")
async def test_agent_knowledge(
    request: Request,
    simulation_id: str,
    node_id: int,
) -> dict:
    """
    Test endpoint to verify agent knowledge bases are working.

    Query params:
        agent_name: Optional specific agent name to test (tests all if not provided)
        query: Optional search query to test knowledge retrieval

    Returns:
        Dict with agent knowledge details and query results

    Raises:
        HTTPException: If simulation or node not found
    """
    agent_name = request.query_params.get("agent_name")
    query = request.query_params.get("query")

    logger.debug(f"test_agent_knowledge: sim={simulation_id}, node={node_id}, agent={agent_name}, query={query}")

    async with get_session() as session:
        token = extract_bearer_token(request)
        current_user = await resolve_current_user(session, token)
        _, record = await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        node = record.tree.nodes.get(int(node_id))

        if node is None:
            raise HTTPException(status_code=404, detail=T("api.errors.tree_node_not_found"))

        simulator = node["sim"]
        results = []

        runtime_agents = get_runtime_agent_map(simulator)
        for name, agent in runtime_agents.items():
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

            # Test query_knowledge method if query provided
            if query and hasattr(agent, "query_knowledge"):
                query_results = agent.query_knowledge(query, top_k=5)
                agent_result["query"] = query
                agent_result["query_results"] = query_results
            elif query and hasattr(agent, "get_rag_context"):
                agent_result["query"] = query
                agent_result["query_context_preview"] = agent.get_rag_context(
                    query=query,
                    global_knowledge=getattr(getattr(simulator, "scene", None), "global_knowledge", {}),
                    top_k=5,
                )[:500]

            # Get knowledge context preview
            if hasattr(agent, "get_knowledge_context"):
                context = agent.get_knowledge_context(query or "test")
                agent_result["knowledge_context_preview"] = context[:500] if context else ""

            results.append(agent_result)

        return {
            "simulation_id": simulation_id,
            "node_id": node_id,
            "agent_count": get_runtime_agent_count(simulator),
            "agents": results
        }


@post("/{simulation_id:str}/tree/sim/{node_id:int}/ask-agents")
async def ask_agents_question(
    request: Request,
    simulation_id: str,
    node_id: int,
    data: dict,
) -> dict:
    """
    Ask all agents a question and get their responses based on their knowledge.

    This demonstrates that each agent uses their individual RAG knowledge
    including documents and global knowledge.

    POST body: {"question": "What is the village budget?", "agent_name": "optional"}

    Returns each agent's response showing they use their specific knowledge.

    Raises:
        HTTPException: If simulation or node not found
    """
    question = data.get("question", "What do you know?")
    target_agent = data.get("agent_name")

    logger.debug(f"ask_agents_question: sim={simulation_id}, node={node_id}")
    logger.debug(f"Question: '{question}'")
    logger.debug(f"Target agent: {target_agent or 'ALL'}")

    async with get_session() as session:
        token = extract_bearer_token(request)
        current_user = await resolve_current_user(session, token)
        sim, record = await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        node = record.tree.nodes.get(int(node_id))

        if node is None:
            raise HTTPException(status_code=404, detail=T("api.errors.tree_node_not_found"))

        simulator = node["sim"]
        llm_client = simulator.clients.get("chat") or simulator.clients.get("default")

        if llm_client is None:
            raise HTTPException(status_code=500, detail=T("api.errors.no_llm_client_available"))

        # Get global knowledge from scene_config
        scene_config = sim.scene_config or {}
        global_knowledge = scene_config.get("global_knowledge", {})

        results = []

        runtime_agents = get_runtime_agent_map(simulator)
        scene_global_knowledge = getattr(getattr(simulator, "scene", None), "global_knowledge", None)
        for name, agent in runtime_agents.items():
            if target_agent and name != target_agent:
                continue

            # Gather all knowledge sources
            kb_items = getattr(agent, "knowledge_base", [])
            enabled_kb = [item for item in kb_items if item.get("enabled", True)]
            documents = getattr(agent, "documents", {})
            agent_config = sim.agent_config or {}
            agents_list = agent_config.get("agents", [])
            agent_cfg = next((a for a in agents_list if a.get("name") == name), {})
            cfg_documents = agent_cfg.get("documents", {})

            logger.debug(f"--- Agent: {name} ---")
            logger.debug(f"Free-text KB items: {len(enabled_kb)}")
            logger.debug(f"Private documents: {len(cfg_documents)}")
            logger.debug(f"Global knowledge items: {len(global_knowledge)}")

            # Build knowledge context
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
                knowledge_context += "\n\n### Your Free-text Knowledge:\n" + "\n\n".join(kb_items_list)

            # 2. Use composite_rag_retrieval for documents and global knowledge
            retrieval_result = await asyncio.to_thread(
                composite_rag_retrieval,
                question,
                agent_documents=documents or cfg_documents,
                global_knowledge=scene_global_knowledge or global_knowledge,
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

            # Build prompt with knowledge
            profile = get_runtime_agent_profile(agent)
            if knowledge_context:
                prompt = f"""You are {name}. {profile}

{knowledge_context}

Based on your knowledge above, please answer this question concisely:
{question}

If you have specific information in your knowledge base about this, use it. If not, say you don't have that information."""
            else:
                prompt = f"""You are {name}. {profile}

Based on your knowledge (if any), please answer this question concisely:
{question}

If you don't have specific information about this, say so."""

            logger.debug(f"Knowledge sources: {knowledge_sources}")

            try:
                messages = [{"role": "user", "content": prompt}]
                response = await asyncio.to_thread(llm_client.chat, messages)

                # Extract response text
                if isinstance(response, str):
                    answer = response
                elif hasattr(response, 'choices') and response.choices:
                    answer = response.choices[0].message.content
                elif isinstance(response, dict):
                    answer = response.get("choices", [{}])[0].get("message", {}).get("content", str(response))
                else:
                    answer = str(response)

                logger.debug(f"Response from {name}: {answer[:200]}")

                results.append({
                    "agent_name": name,
                    "knowledge_count": len(enabled_kb) + len(cfg_documents) + len(global_knowledge),
                    "knowledge_sources": knowledge_sources,
                    "question": question,
                    "answer": answer,
                    "success": True
                })

            except Exception as e:
                logger.error(f"ERROR for {name}: {e}")
                results.append({
                    "agent_name": name,
                    "knowledge_count": len(enabled_kb) + len(cfg_documents),
                    "question": question,
                    "answer": f"Error: {str(e)}",
                    "success": False
                })

        return {
            "simulation_id": simulation_id,
            "node_id": node_id,
            "question": question,
            "responses": results
        }


@post("/{simulation_id:str}/tree/sim/{node_id:int}/inject-message")
async def inject_host_message(
    request: Request,
    simulation_id: str,
    node_id: int,
    data: dict,
) -> dict:
    """
    Inject a host message into all agents' context for the next round.

    POST body: {"message": "ANNOUNCEMENT: Please reconsider your strategy."}

    The message is prepended to every agent's context when the next round runs.
    Only available for experiment_template simulations (ExperimentRunnerAdapter).

    Raises:
        HTTPException 400: if message is empty or simulation is not experiment type
        HTTPException 404: if node not found
    """
    message = data.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail=T("api.errors.message_required"))

    async with get_session() as session:
        token = extract_bearer_token(request)
        current_user = await resolve_current_user(session, token)
        _, record = await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        node = record.tree.nodes.get(int(node_id))

        if node is None:
            raise HTTPException(status_code=404, detail=T("api.errors.tree_node_not_found"))

        simulator = node["sim"]
        from fos.backend.services.simtree_runtime import ExperimentRunnerAdapter
        if not isinstance(simulator, ExperimentRunnerAdapter):
            raise HTTPException(status_code=400, detail=T("api.errors.inject_message_experiment_only"))

        simulator.inject_host_message(message)

    return {"status": "queued", "message": message}
