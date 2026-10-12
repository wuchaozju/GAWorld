import json
import asyncio
import logging
from typing import Dict, List, Optional, TYPE_CHECKING
import os
from datetime import datetime

from fos.core.event import PublicEvent
from fos.i18n import T
try:
    from fos.core.simulator import Simulator  # Pipeline B — not present in fos
except ImportError:
    Simulator = None  # type: ignore[assignment,misc]
try:
    from fos.services.llm_client_pool import LLMClientPool  # Pipeline B — not present in fos
except ImportError:
    LLMClientPool = None  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SimCloneError(RuntimeError):
    """Raised when a cloned Simulator fails basic invariants."""
    pass


class SimTree:
    def __init__(
        self,
        clients: Dict[str, object],
        *,
        use_client_pool: bool = False,
        client_pool: Optional[LLMClientPool] = None,
    ):
        """
        :param clients: 作为“基准”的一份 clients dict（通常来自 make_clients_from_env）
        :param use_client_pool: 是否为这棵树启用 LLMClientPool
        :param client_pool: 外部注入的 pool（可选），如果提供则优先使用
        """
        # 原始基准 clients（可能被多个 clone 用作“模板”）
        self.clients = clients

        # 每棵树自己的 client 池：用于“每个分支拿到独立的 LLMClient 实例”
        if client_pool is not None:
            self._client_pool = client_pool
        elif use_client_pool:
            self._client_pool = LLMClientPool(clients)
        else:
            self._client_pool = None

        self.nodes: Dict[int, dict] = {}
        self.children: Dict[int, List[int]] = {}
        self.root: Optional[int] = None
        self._seq: int = 0

        # 节点级订阅：node_id -> [asyncio.Queue / SimpleQueue]
        self._node_subs: Dict[int, List[object]] = {}

        # Tree-level broadcast sink (wired by backend runtime to WS subscribers)
        self._tree_broadcast = lambda event: None

        # Event loop used for thread-safe fanout (set by backend runtime)
        self._loop: asyncio.AbstractEventLoop | None = None

        # 如果 <=0 则不启用定时 GC；默认 0（关闭），可以在部署时通过环境变量打开
        self._gc_interval_s: float = float(
            os.getenv("SIMTREE_NODE_SUB_GC_INTERVAL_S", "0")
        )
        self._gc_task: asyncio.Task | None = None

    # ---------- 基础设施 ----------

    def set_tree_broadcast(self, fn) -> None:
        self._tree_broadcast = fn

    def attach_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        # 尝试启动后台 GC 协程（如果配置打开）
        self._ensure_gc_task()

    def _ensure_gc_task(self) -> None:
        """根据 _gc_interval_s 启动一个定时 GC 任务（如果尚未启动）。"""
        # 没有 loop，直接不做
        if self._loop is None:
            return
        # 间隔 <= 0 视为关闭 GC
        if self._gc_interval_s <= 0:
            return
        # 已经有一个在跑的任务就不要重复建
        if self._gc_task is not None and not self._gc_task.done():
            return

        async def _gc_loop() -> None:
            try:
                while True:
                    await asyncio.sleep(self._gc_interval_s)
                    try:
                        self.gc_node_subs()
                    except Exception:
                        logger.exception("gc_node_subs() failed in background task")
            except asyncio.CancelledError:
                # 关闭时静默退出
                return

        # 在绑定的 loop 上启动后台任务
        self._gc_task = self._loop.create_task(_gc_loop())

    def cleanup_runtime_resources(self) -> None:
        """Stop background tasks and child processes owned by this tree."""
        if self._gc_task is not None and not self._gc_task.done():
            self._gc_task.cancel()
        self._gc_task = None
        for node in list(self.nodes.values()):
            sim = node.get("sim")
            if sim is None:
                continue
            cleanup = getattr(sim, "cleanup_runtime_resources", None)
            if cleanup is not None:
                cleanup()

    def _next_id(self) -> int:
        i = self._seq
        self._seq = i + 1
        return i

    # ---------- 构造根节点：集成 LLMClientPool ----------

    @classmethod
    def new(
        cls,
        sim: Simulator,
        clients: Dict[str, object],
    ):
        """
        使用给定的 live Simulator 构造一棵新的 SimTree：
        - 为这棵树启用 LLMClientPool，使后续每个分支拿到独立的 LLMClient 实例集合；
        - 根节点的 Simulator 通过 serialize -> deserialize 克隆得到（深拷贝语义）；
        - 在克隆点上强制 reset_event_queue()，并执行一次 _check_simulator_clone 自检。
        """
        tree = cls(clients, use_client_pool=False)

        root_id = tree._next_id()

        # 为“根分支”申请一份专属的 clients dict（如果未启用 pool，则退回共用 clients）
        if tree._client_pool is not None:
            root_clients = tree._client_pool.acquire(branch_id=f"root-{root_id}")
        else:
            root_clients = clients

        # 1) 通过 serialize -> deserialize 克隆 simulator
        snap = sim.serialize()
        # Lazy import to avoid circular dependency
        from fos.backend.services.simtree_runtime import ExperimentRunnerAdapter
        if isinstance(sim, ExperimentRunnerAdapter):
            sim_clone = ExperimentRunnerAdapter.deserialize(snap, root_clients, log_handler=None)
        else:
            sim_clone = Simulator.deserialize(snap, root_clients, log_handler=None)

        # 2) 克隆点的 event_queue 必须是“干净”的
        sim_clone.reset_event_queue()

        # 让克隆体的代理在新节点重新尝试发言：把 last_history_length 向前挪一步
        for agent in sim_clone.agents.values():
            agent.last_history_length = max(0, len(agent.short_memory) - 1)
            agent.consecutive_llm_errors = 0
            agent.is_offline = False

        # 3) 基础自检：检查 agents/scene/orderings 的独立性 + ordering 状态一致性 + queue 为空
        tree._check_simulator_clone(sim, sim_clone)

        # 4) 把通过自检的 clone 作为根节点挂到树上
        root_logs: List[dict] = []
        tree.nodes[root_id] = {
            "id": root_id,
            "parent": None,
            "depth": 0,
            "edge_type": "root",
            "ops": [],
            "sim": sim_clone,
            "logs": root_logs,
            "meta": {},
        }

        # Attach log handler so future events at root accumulate into root logs
        tree._attach_log_handler(root_id, sim_clone, root_logs)

        # 此时 event_queue 已在克隆点 reset 为空，这里 emit_remaining_events() 基本是 no-op
        sim_clone.emit_remaining_events()

        tree.children[root_id] = []
        tree.root = root_id
        return tree

    # ---------- 克隆相关辅助（每个分支独立 clients） ----------

    def _clone_simulator_from_node(self, node_id: int) -> Simulator:
        """Clone simulator from a node with invariants check and queue reset.

        关键点：
        - 如果启用了 LLMClientPool，则为本次 clone 申请一份全新的 clients dict；
        - 通过 base_sim.serialize() + Simulator.deserialize(..., branch_clients) 生成全新实例；
        - 在克隆点 reset_event_queue()，然后执行 _check_simulator_clone。
        """
        base_node = self.nodes[node_id]
        base_sim: Simulator = base_node["sim"]

        # 为这个 clone 申请一份专属 clients（如果有池）
        if self._client_pool is not None:
            branch_clients = self._client_pool.acquire(
                branch_id=f"node-{node_id}-clone-{self._seq}"
            )
        else:
            # 未启用池时，仍然回退到“共用 self.clients”的旧行为
            branch_clients = self.clients

        # Simulator.serialize 已经用 deepcopy 做了深拷贝，这里不再做 json roundtrip
        snap = base_sim.serialize()
        # Lazy import to avoid circular dependency
        from fos.backend.services.simtree_runtime import ExperimentRunnerAdapter
        if isinstance(base_sim, ExperimentRunnerAdapter):
            sim_copy = ExperimentRunnerAdapter.deserialize(snap, branch_clients, log_handler=None)
        else:
            sim_copy = Simulator.deserialize(snap, branch_clients, log_handler=None)

        # 先清空 clone 的 event_queue，再做一次完整自检
        sim_copy.reset_event_queue()

        # 轻量状态自检：确保没有错误的共享引用 & 关键状态一致
        self._check_simulator_clone(base_sim, sim_copy)

        # 让 clone 在新节点重新发言：把 last_history_length 向前挪一步
        for agent in sim_copy.agents.values():
            agent.last_history_length = max(0, len(agent.short_memory) - 1)
            agent.consecutive_llm_errors = 0
            agent.is_offline = False

        return sim_copy

    def _check_simulator_clone(self, base: Simulator, cloned: Simulator) -> None:
        """Basic sanity checks to ensure cloned simulator is independent and consistent.

        核心不变量：
        1）clone 必须有 agent；agent 数量 & 名称集合一致；
        2）agents / scene / event_queue / ordering 等顶层可变对象不能共享引用；
        3）每个 Agent 实例不能共享引用；
        4）ordering 类型一致，serialize 后的状态一致；
        5）**event_queue：对象不共享，且在克隆点必须为空**。
        """
        # Skip checks for ExperimentRunnerAdapter (different architecture)
        # Lazy import to avoid circular dependency
        from fos.backend.services.simtree_runtime import ExperimentRunnerAdapter
        if isinstance(cloned, ExperimentRunnerAdapter):
            return

        # --- 1. agent 基本信息 ---
        if not cloned.agents:
            raise SimCloneError("cloned simulator has no agents")

        base_names = set(base.agents.keys())
        clone_names = set(cloned.agents.keys())
        if base_names != clone_names:
            raise SimCloneError(
                f"cloned simulator agent set mismatch: base={sorted(base_names)}, "
                f"clone={sorted(clone_names)}"
            )

        if len(base.agents) != len(cloned.agents):
            raise SimCloneError(
                f"cloned simulator agent count mismatch: "
                f"base={len(base.agents)} clone={len(cloned.agents)}"
            )

        # --- 2. 顶层对象引用不得共享 ---
        if id(base.agents) == id(cloned.agents):
            raise SimCloneError("agents dict shared between base and clone")
        if id(base.scene) == id(cloned.scene):
            raise SimCloneError("scene shared between base and clone")
        if id(base.event_queue) == id(cloned.event_queue):
            raise SimCloneError("event_queue shared between base and clone")
        if id(base.ordering) == id(cloned.ordering):
            raise SimCloneError("ordering object shared between base and clone")

        # 场景类型至少要一致（不做完整 serialize 对比，避免过重）
        if type(base.scene) is not type(cloned.scene):
            raise SimCloneError(
                f"scene type mismatch: base={type(base.scene)} "
                f"clone={type(cloned.scene)}"
            )

        # --- 3. 每个 Agent 实例不得共享 ---
        for name, agent in base.agents.items():
            cloned_agent = cloned.agents.get(name)
            if cloned_agent is None:
                raise SimCloneError(f"cloned simulator missing agent: {name}")
            if id(agent) == id(cloned_agent):
                raise SimCloneError(
                    f"agent instance shared between base and clone: {name}"
                )

        # --- 4. ordering 存在 & 类型 + 状态一致 ---
        if cloned.ordering is None:
            raise SimCloneError("ordering is None on cloned simulator")
        if base.ordering is None:
            raise SimCloneError("ordering is None on base simulator")

        if type(base.ordering) is not type(cloned.ordering):
            raise SimCloneError(
                f"ordering type mismatch: base={type(base.ordering)} "
                f"clone={type(cloned.ordering)}"
            )

        try:
            base_state = base.ordering.serialize()
            clone_state = cloned.ordering.serialize()
            if base_state != clone_state:
                raise SimCloneError(
                    f"ordering state mismatch between base and clone: "
                    f"base={base_state} clone={clone_state}"
                )
        except Exception as e:
            # 这里理论上不该抛错，如果抛错说明 ordering 本身实现有问题
            logger.exception("failed to serialize ordering state for clone check")
            raise SimCloneError(f"ordering serialize error during clone check: {e}")

        # --- 5. event_queue：对象不共享 + 克隆点必须为空 ---
        try:
            # 上面已经检查过 id 不同，这里只关心“克隆点是否干净”
            if not cloned.event_queue.empty():
                raise SimCloneError(
                    "cloned event_queue is not empty at clone point"
                )
        except AttributeError:
            # 如果根本没有 event_queue 属性，那就是严重设计问题
            raise SimCloneError("cloned simulator has no event_queue attribute")

    # ---------- 对外克隆接口 ----------

    def copy_sim(self, node_id: int) -> int:
        # Clone the simulator by snapshotting the node's live sim
        sim_copy = self._clone_simulator_from_node(node_id)

        # Prepare a new node with inherited logs snapshot; parent/ops assigned later
        nid = self._next_id()
        parent_logs = list(self.nodes[node_id].get("logs", []))
        parent_meta = json.loads(json.dumps(self.nodes[node_id].get("meta", {})))
        # Deep copy parent's logs so child does not share dict references
        child_logs: List[dict] = json.loads(json.dumps(parent_logs))
        node = {
            "id": nid,
            "parent": None,
            "depth": None,
            "edge_type": None,
            "ops": [],
            "sim": sim_copy,
            "logs": child_logs,
            "meta": parent_meta,
        }

        self._attach_log_handler(nid, sim_copy, child_logs)
        self.nodes[nid] = node
        self.children[nid] = []
        return nid

    # ---------- 日志 / 事件处理 ----------

    def _attach_log_handler(self, node_id: int, sim: Simulator, logs: List[dict]) -> None:
        def _lh(kind, data):
            # 如果是 error 事件，把 node_id 写进 payload 里，方便日志和前端直接使用
            if kind == "error":
                try:
                    if isinstance(data, dict) and "node_id" not in data:
                        # 拷一份，避免修改 Simulator 内部可能复用的原始 dict
                        data = dict(data)
                        data["node_id"] = int(node_id)
                except Exception:
                    logger.exception("failed to inject node_id into error event payload")

            entry = {"type": kind, "data": data, "node": int(node_id), "timestamp": datetime.now().isoformat()}
            logs.append(entry)

            subs = self._node_subs.get(node_id) or []
            if self._loop is not None:
                for q in subs:
                    try:
                        self._loop.call_soon_threadsafe(q.put_nowait, entry)
                    except Exception:
                        logger.exception("failed to deliver node event to subscriber")
            else:
                for q in subs:
                    try:
                        q.put_nowait(entry)
                    except Exception:
                        logger.exception(
                            "failed to deliver node event to subscriber (no loop)"
                        )

            # Also fan out to tree-level broadcast (e.g., WS attached to the tree)
            try:
                self._tree_broadcast(entry)
            except Exception:
                logger.exception("tree-level broadcast failed")

        sim.log_event = _lh
        for a in sim.agents.values():
            a.log_event = _lh

    # ---------- 节点级订阅管理 ----------

    # Per-node subscription for delta streaming (used by DevUI WS)
    def add_node_sub(self, node_id: int, q: object) -> None:
        lst = self._node_subs.get(node_id)
        if lst is None:
            lst = []
            self._node_subs[node_id] = lst
        lst.append(q)

    def remove_node_sub(self, node_id: int, q: object) -> None:
        lst = self._node_subs.get(node_id)
        if lst is None:
            return
        if q in lst:
            lst.remove(q)
        # 如果该节点已经没有任何订阅，直接删除 key，防止僵尸列表堆积
        if not lst:
            self._node_subs.pop(node_id, None)

    def clear_node_subs(self, node_id: int) -> None:
        """Detach all subscribers from a given node."""
        self._node_subs.pop(node_id, None)

    def gc_node_subs(self) -> None:
        """Drop empty subscription lists; 可在高负载场景定期调用。"""
        empty = [nid for nid, subs in self._node_subs.items() if not subs]
        for nid in empty:
            self._node_subs.pop(nid, None)

    # ---------- 序列化 / 反序列化 ----------

    def serialize(self) -> dict:
        nodes: list[dict] = []
        for nid, node in self.nodes.items():
            sim: Simulator = node["sim"]
            nodes.append(
                {
                    "id": int(nid),
                    "parent": node["parent"],
                    "depth": int(node["depth"])
                    if node.get("depth") is not None
                    else None,
                    "edge_type": node.get("edge_type"),
                    "ops": node.get("ops", []),
                    "sim": sim.serialize(),
                    "logs": list(node.get("logs", [])),
                    "meta": node.get("meta", {}),
                }
            )
        return {
            "root": int(self.root) if self.root is not None else None,
            "seq": int(self._seq),
            "nodes": nodes,
        }

    @classmethod
    def deserialize(cls, data: dict, clients: Dict[str, object]):
        """
        反序列化一棵 SimTree。

        这里为了简单和兼容性，不启用 LLMClientPool（use_client_pool=False）：
        - 反序列化出来的所有 Simulator 共用传入的 clients；
        - 用于离线分析 / 回放时通常不涉及并发分支的 LLM 调用。
        """
        tree = cls(clients, use_client_pool=False)
        tree.root = data.get("root")
        tree._seq = int(data.get("seq", 0))
        tree.nodes = {}
        tree.children = {}
        items = data.get("nodes") or []
        for item in items:
            nid = int(item.get("id"))
            parent = item.get("parent")
            depth = item.get("depth")
            edge_type = item.get("edge_type")
            ops = item.get("ops") or []
            sim_data = item.get("sim") or {}
            scene_type = (sim_data.get("scene") or {}).get("type")
            if scene_type == "experiment_template":
                from fos.backend.services.simtree_runtime import ExperimentRunnerAdapter

                sim = ExperimentRunnerAdapter.deserialize(sim_data, clients, log_handler=None)
            else:
                sim = Simulator.deserialize(sim_data, clients, log_handler=None)
            logs = list(item.get("logs") or [])
            node = {
                "id": nid,
                "parent": parent,
                "depth": depth,
                "edge_type": edge_type,
                "ops": ops,
                "sim": sim,
                "logs": logs,
                "meta": item.get("meta", {}),
            }
            tree.nodes[nid] = node
            if parent is not None:
                tree.children.setdefault(parent, []).append(nid)
            tree.children.setdefault(nid, [])
        # Attach log handlers so future events append and fan out
        for nid, node in tree.nodes.items():
            tree._attach_log_handler(nid, node["sim"], node.get("logs") or [])
        return tree

    # ---------- 节点操作 ----------

    def attach(self, parent_id: int, ops: List[dict], cid: int) -> int:
        if parent_id not in self.nodes:
            raise KeyError(T("Parent node {parent_id} not found in tree", parent_id=parent_id))
        if cid not in self.nodes:
            raise KeyError(T("Child node {cid} not found in tree", cid=cid))
        parent = self.nodes[parent_id]
        node = self.nodes[cid]
        node["parent"] = parent_id
        node["depth"] = int(parent["depth"]) + 1
        node["ops"] = ops
        et = "multi"
        if ops and len(ops) == 1:
            m = ops[0]["op"]
            if m == "agent_ctx_append":
                et = "agent_ctx"
            elif m == "agent_plan_replace":
                et = "agent_plan"
            elif m == "agent_props_patch":
                et = "agent_props"
            elif m == "scene_state_patch":
                et = "scene_state"
            elif m == "config_params_patch":
                et = "config_params"
            elif m == "config_description_patch":
                et = "config_desc"
            elif m == "config_settings_patch":
                et = "config_settings"
            elif m == "network_replace":
                et = "network"
            elif m == "public_broadcast":
                et = "public_event"
            elif m == "environment_event":
                et = "environment_event"
            elif m == "advance":
                et = "advance"
        node["edge_type"] = et
        if parent_id not in self.children:
            self.children[parent_id] = []
        self.children[parent_id].append(cid)
        return cid

    def advance(self, parent_id: int, turns: int = 1) -> int:
        cid = self.copy_sim(parent_id)
        sim = self.nodes[cid]["sim"]
        sim.run(max_turns=int(turns))
        return self.attach(parent_id, [{"op": "advance", "turns": int(turns)}], cid)

    def branch(self, parent_id: int, ops: List[dict]) -> int:
        # For branching (what-if scenarios), we create a SIBLING node, not a child.
        # The new branch must therefore start from the shared parent state rather than
        # inheriting the selected sibling's already-mutated simulator state.
        if parent_id not in self.nodes:
            raise KeyError(T("Node {parent_id} not found in tree", parent_id=parent_id))
        actual_parent_id = self.nodes[parent_id]["parent"]

        # If the node has no parent (it's the root), we can't create a sibling
        # In this case, fall back to creating a child (original behavior)
        if actual_parent_id is None:
            actual_parent_id = parent_id

        cid = self.copy_sim(actual_parent_id)
        sim = self.nodes[cid]["sim"]
        for op in ops:
            name = op["op"]
            if name == "agent_ctx_append":
                ag = sim.agents[op["name"]]
                ag.short_memory.append(op["role"], op["content"])
            elif name == "agent_plan_replace":
                ag = sim.agents[op["name"]]
                ag.plan_state = op["plan_state"]
            elif name == "agent_props_patch":
                # Apply property updates to the cloned simulator's agent
                from fos.backend.services.simtree_runtime import ExperimentRunnerAdapter
                if isinstance(sim, ExperimentRunnerAdapter):
                    ag = sim._scene_agent_map()[op["name"]]
                else:
                    ag = sim.agents[op["name"]]
                updates = op["updates"]
                for k, v in updates.items():
                    ag.properties[k] = v
                if isinstance(sim, ExperimentRunnerAdapter):
                    config_agents = getattr(getattr(sim.scene, "config", None), "agents", None) or []
                    for agent_cfg in config_agents:
                        if str(agent_cfg.get("name", "")).strip() == str(op.get("name", "")).strip():
                            merged_props = dict(agent_cfg.get("properties") or {})
                            merged_props.update(updates)
                            agent_cfg["properties"] = merged_props
                            break
                try:
                    logger.debug("SimTree.branch applied agent_props_patch", extra={"parent": parent_id, "child": cid, "agent": op.get("name"), "updates": updates})
                except Exception:
                    # best-effort logging; do not fail branch on logging error
                    logger.exception("failed to log agent_props_patch application")
            elif name == "scene_state_patch":
                updates = op["updates"]
                for k, v in updates.items():
                    sim.scene.state[k] = v
            elif name == "config_params_patch":
                # Merge patch: only update specified keys; preserve all others.
                updates = op["updates"]
                if hasattr(sim.scene, 'config') and hasattr(sim.scene.config, 'parameters'):
                    merged = dict(sim.scene.config.parameters)  # copy base
                    merged.update(updates)                        # apply patch
                    sim.scene.config.parameters = merged
            elif name == "config_description_patch":
                # Update scenario description
                if hasattr(sim.scene, 'config'):
                    sim.scene.config.description = op["description"]
            elif name == "config_settings_patch":
                # Update scenario settings (e.g., round_visibility)
                settings = op["settings"]
                if hasattr(sim.scene, 'config'):
                    for k, v in settings.items():
                        if hasattr(sim.scene.config, k):
                            setattr(sim.scene.config, k, v)
            elif name == "network_replace":
                # Replace the network with a pre-computed concrete edge list.
                # The frontend generates and freezes the edge list at submit time.
                # The backend stores it as-is; it does NOT regenerate from preset name.
                #
                # NOTE: Only valid at branch creation (before any turns run).
                # Applying mid-simulation leaves agents with stale neighbor state.
                network_data = op["network"]

                if hasattr(sim.scene, 'config'):
                    sim.scene.config.social_network = network_data

                # Update runner's scene_state if runner exists (for ExperimentScene)
                if hasattr(sim.scene, 'runner') and sim.scene.runner is not None:
                    sim.scene.runner.set_scene_state({"graph": network_data})
            elif name == "public_broadcast":
                sim.broadcast(PublicEvent(op["text"]))
            elif name == "environment_event":
                description = op["text"]
                event_type = str(op.get("event_type") or "environment")
                is_policy_scene = getattr(sim.scene, "TYPE", "") == "policy_cascade_scene"
                notice_only = bool(op.get("notice_only")) if is_policy_scene else False
                if is_policy_scene and "notice_only" not in op:
                    notice_only = event_type != "broadcast"
                payload = {"description": description, "event_type": event_type}
                if is_policy_scene:
                    payload["notice_only"] = notice_only
                receivers = op.get("receivers")
                from fos.backend.services.simtree_runtime import ExperimentRunnerAdapter
                is_custom_experiment = (
                    isinstance(sim, ExperimentRunnerAdapter)
                    and getattr(getattr(sim.scene, "config", None), "scenario_id", "") == "custom"
                )
                if is_custom_experiment:
                    if event_type == "broadcast":
                        sim.broadcast(
                            PublicEvent(description, prefix="SYSTEM BROADCAST"),
                            receivers=receivers,
                        )
                    elif receivers:
                        agent_map = sim._scene_agent_map()
                        for receiver_name in receivers:
                            agent = agent_map.get(receiver_name)
                            if agent is None:
                                raise ValueError(T("Unknown environment_event receiver: {receiver_name}", receiver_name=receiver_name))
                            agent.add_env_feedback(description)
                        sim._emit_event(
                            "public_event",
                            {"message": description, "scoped": True, "recipients": receivers},
                        )
                    else:
                        sim.inject_host_message(description)
                        sim._emit_event(
                            "public_event",
                            {"message": description, "scoped": False, "recipients": []},
                        )
                    continue
                if receivers:
                    for receiver_name in receivers:
                        if receiver_name not in sim.agents:
                            raise ValueError(T("Unknown environment_event receiver: {receiver_name}", receiver_name=receiver_name))
                        sim.agents[receiver_name].add_env_feedback(description, images=[])
                    sim.scene.on_private_event(sim, "environment", payload, receivers)
                else:
                    for agent in sim.agents.values():
                        agent.add_env_feedback(description, images=[])
                    sim.scene.on_event(sim, "environment", payload)
            else:
                raise ValueError("Unknown op: " + name)

        # Flush any queued events to logs
        sim.emit_remaining_events()
        # Attach to actual_parent_id instead of parent_id to create a sibling relationship
        return self.attach(actual_parent_id, ops, cid)

    def apply_agent_overrides(self, node_id: int, overrides: List[dict]) -> None:
        if node_id not in self.nodes:
            raise KeyError(T("Node {node_id} not found in tree", node_id=node_id))

        node = self.nodes[node_id]
        sim: Simulator = node["sim"]
        meta = node.setdefault("meta", {})
        agent_overrides = meta.setdefault("agent_overrides", {})

        for item in overrides:
            name = item["name"]
            from fos.backend.services.simtree_runtime import ExperimentRunnerAdapter
            is_experiment_adapter = isinstance(sim, ExperimentRunnerAdapter)
            if is_experiment_adapter:
                agent = sim._scene_agent_map()[name]
            else:
                agent = sim.agents[name]

            current = dict(agent_overrides.get(name, {}))
            config_agent = None
            if is_experiment_adapter:
                for candidate in getattr(getattr(sim.scene, "config", None), "agents", None) or []:
                    if str(candidate.get("name", "")).strip() == str(name).strip():
                        config_agent = candidate
                        break

            if "language" in item:
                if hasattr(agent, "language"):
                    agent.language = item["language"]
                if config_agent is not None:
                    config_agent["language"] = item["language"]
                current["language"] = item["language"]

            if "llm_config" in item:
                llm_cfg = json.loads(json.dumps(item["llm_config"]))
                agent.properties["llm_config"] = llm_cfg
                if hasattr(agent, "llm_config"):
                    agent.llm_config = llm_cfg
                if config_agent is not None:
                    config_agent["llm_config"] = llm_cfg
                current["llm_config"] = llm_cfg

            if "provider_id" in item:
                provider_id = item["provider_id"]
                if hasattr(agent, "provider_id"):
                    agent.provider_id = provider_id
                agent.properties["provider_id"] = provider_id
                if config_agent is not None:
                    config_agent["provider_id"] = provider_id
                    config_properties = dict(config_agent.get("properties") or {})
                    config_properties["provider_id"] = provider_id
                    config_agent["properties"] = config_properties
                current["provider_id"] = provider_id

            if "knowledge_base" in item:
                kb = json.loads(json.dumps(item["knowledge_base"]))
                agent.knowledge_base = kb
                if config_agent is not None:
                    config_agent["knowledgeBase"] = kb
                current["knowledge_base"] = kb

            if "documents" in item:
                docs = json.loads(json.dumps(item["documents"]))
                agent.documents = docs
                if config_agent is not None:
                    config_agent["documents"] = docs
                current["documents"] = docs

            if "properties" in item:
                props = item["properties"]
                for k, v in props.items():
                    agent.properties[k] = v
                merged = dict(agent.properties)
                if config_agent is not None:
                    config_agent["properties"] = dict(merged)
                current["properties"] = merged

            if is_experiment_adapter and hasattr(sim.scene, "_agent_llm_clients"):
                target_provider_id = item.get("provider_id", getattr(agent, "provider_id", None))
                if target_provider_id is not None and getattr(sim, "_provider_clients", None):
                    client = sim._provider_clients.get(target_provider_id)
                    if client is not None:
                        sim.scene._agent_llm_clients[name] = client

            agent_overrides[name] = current

    def lca(self, a: int, b: int) -> int:
        da = int(self.nodes[a]["depth"])
        db = int(self.nodes[b]["depth"])
        na = a
        nb = b
        while da > db:
            na = self.nodes[na]["parent"]
            da -= 1
        while db > da:
            nb = self.nodes[nb]["parent"]
            db -= 1
        while na != nb:
            na = self.nodes[na]["parent"]
            nb = self.nodes[nb]["parent"]
        return na

    def summaries(self) -> List[dict]:
        items: List[dict] = []
        for nid, node in self.nodes.items():
            turns = int(node["sim"].turns)
            parent = node["parent"]
            edges = []
            for cid in self.children.get(nid, []):
                c = self.nodes[cid]
                edges.append(
                    {
                        "to": cid,
                        "type": c["edge_type"],
                        "ops": c["ops"],
                    }
                )
            items.append(
                {
                    "id": nid,
                    "turns": turns,
                    "parent": parent,
                    "edges": edges,
                }
            )
        items.sort(key=lambda x: int(x["id"]))
        return items

    def leaves(self) -> List[int]:
        res: List[int] = []
        for nid in self.nodes.keys():
            if len(self.children.get(nid, [])) == 0:
                res.append(nid)
        res.sort()
        return res

    def max_depth(self) -> int:
        m = 0
        for n in self.nodes.values():
            d = int(n["depth"])
            if d > m:
                m = d
        return m

    def frontier(self, only_max_depth: bool = True) -> List[int]:
        lf = self.leaves()
        if not only_max_depth:
            return lf
        md = self.max_depth()
        res: List[int] = []
        for nid in lf:
            if int(self.nodes[nid]["depth"]) == md:
                res.append(nid)
        return res

    def advance_frontier(
        self, turns: int = 1, only_max_depth: bool = True
    ) -> List[int]:
        res: List[int] = []
        for pid in self.frontier(only_max_depth=only_max_depth):
            cid = self.advance(pid, turns=int(turns))
            res.append(cid)
        return res

    def advance_selected(self, parent_ids: List[int], turns: int = 1) -> List[int]:
        res: List[int] = []
        for pid in parent_ids:
            cid = self.advance(int(pid), turns=int(turns))
            res.append(cid)
        return res

    def delete_subtree(self, node_id: int) -> None:
        if node_id == self.root:
            raise ValueError(T("Cannot delete root node"))
        root_parent = self.nodes[node_id]["parent"]
        stack = [node_id]
        to_del: List[int] = []
        while stack:
            nid = stack.pop()
            to_del.append(nid)
            for c in self.children.get(nid, []):
                stack.append(c)
        for nid in to_del:
            # 清理该子树上所有订阅，防止 WS 订阅泄漏
            self._node_subs.pop(nid, None)
            if nid in self.children:
                del self.children[nid]
            if nid in self.nodes:
                del self.nodes[nid]
        if root_parent is not None:
            ch = self.children.get(root_parent, [])
            if node_id in ch:
                ch.remove(node_id)
                self.children[root_parent] = ch
        # Root is not allowed to be deleted; no adjustment needed here
