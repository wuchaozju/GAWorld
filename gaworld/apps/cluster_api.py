"""``/api/cluster``: distributed worlds (proposal 2026-10-02-distributed-worlds).

Two audiences:

- **the world's owner** (session cookie, the console's active world):
  ``GET /api/cluster`` lists the nodes with their live status;
  ``POST /api/cluster/nodes`` adds one and answers its token once;
  ``POST /api/cluster/nodes/<id>/agents`` reassigns residents;
  ``POST /api/cluster/nodes/<id>/delete`` revokes it.
- **nodes** (``Authorization: Bearer <world>.<node>.<secret>``), only ever
  about their own world: ``/api/cluster/node`` (who am I, should I run),
  ``/heartbeat``, ``/bundle``, ``/interventions``, ``/records``, ``/sync``, and
  the relay protocol under ``/api/cluster/relay/`` (the same requests the
  stand-alone relay server answers, with cluster and node taken from the token).

The hub's own simulator is a node too (id ``hub``, a token minted per run).
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator
from typing import Any

from gaworld import worlds
from gaworld.apps import residents, runs, world_paths
from gaworld.city.config import AGENT_FILES
from gaworld.cluster import bundle, hub, nodes
from gaworld.cluster.nodes import HUB

#: Largest request body a node may send (records uploads).
MAX_BODY = 1024 * 1024


def _ds() -> Any:
    from gaworld.apps import dashboard_server

    return dashboard_server


@contextlib.contextmanager
def _inside(world: dict[str, Any]) -> Iterator[None]:
    token = _ds()._WORLD.set(world)
    try:
        yield
    finally:
        _ds()._WORLD.reset(token)


def _int_list(values: Any) -> list[int]:
    if isinstance(values, str):
        values = values.replace("，", ",").replace(" ", ",").split(",")
    out = []
    for raw in values or []:
        text = str(raw).strip()
        if not text:
            continue
        if "-" in text.strip("-"):
            low, high = (int(part) for part in text.split("-", 1))
            out.extend(range(low, high + 1))
        else:
            out.append(int(text))
    return out


# -- facts about the active world (call inside the world) --------------------


def _repo() -> str:
    return world_paths.REPO_ROOT


def _residents() -> set[int]:
    return {int(row["id"]) for row in residents.agents_summary()}


def _world_agent_ids() -> list[int]:
    ids = [int(aid) for aid in world_paths.effective_config().get("agent_ids", []) or []]
    return ids or sorted(_residents())


def _run(world_id: str) -> tuple[bool, str]:
    """Is the world's hub run alive, and its run id."""
    state = runs.WORLD_RUNS.get(world_id) or {}
    proc = state.get("process")
    alive = bool(proc and proc.poll() is None)
    return alive, (state.get("run_id") or "") if alive else ""


def placement(world_id: str) -> dict[str, list[int]]:
    """Who runs which of the world's residents: node id -> ids, ``hub`` included.

    While the world runs this is the split it was started with -- reassigning
    residents applies from the next run, so routing follows the running sims.
    """
    snapshot = hub.get(world_id).plan
    if snapshot and _run(world_id)[0]:
        return {key: list(value) for key, value in snapshot.items()}
    world_ids = _world_agent_ids()
    owner = nodes.assigned(_repo(), world_id)
    plan: dict[str, list[int]] = {HUB: []}
    for node in nodes.load(_repo(), world_id):
        plan[node["id"]] = []
    for aid in world_ids:
        plan.setdefault(owner.get(aid, HUB), []).append(aid)
    return plan


def hub_overrides(world_id: str, base_url: str) -> dict[str, Any]:
    """Config the hub's own simulator runs with in a world that has nodes.

    Empty for a world without nodes: such a run is exactly what it was before.
    Starting one also starts a new run of the world's hub state.
    """
    if not nodes.load(_repo(), world_id):
        return {}
    plan = placement(world_id)
    if not plan[HUB]:
        raise ValueError(
            "枢纽至少要留一位居民：所有参与的居民都分给了节点。到「管理世界 → 分布式节点」里调整"
        )
    run_id = uuid.uuid4().hex[:12]
    token = nodes.hub_token(world_id)
    hub.get(world_id).start_run(run_id, plan)
    timeout = (world_paths.effective_config().get("cluster") or {}).get("sync_timeout_seconds", 60)
    return {
        "distributed": {
            "enabled": True,
            "cluster": world_id,
            "node_id": HUB,
            "local_agent_ids": plan[HUB],
            "relay": {"base_url": f"{base_url}/api/cluster/relay", "token": token},
        },
        "cluster": {
            "enabled": True,
            "hub_url": base_url,
            "token": token,
            "run_id": run_id,
            "node_id": HUB,
            "sync_timeout_seconds": timeout,
        },
    }


def route(world_id: str, agent_id: int, name: str, kwargs: dict[str, Any]) -> bool | None:
    """Send an intervention to the node running *agent_id*.

    None when the resident runs on the hub (the caller uses the local queue),
    else whether the node is running this run.
    """
    node_id = node_of(world_id, agent_id)
    if node_id == HUB:
        return None
    world_hub = hub.get(world_id)
    if not world_hub.running_here(node_id):
        return False
    world_hub.push(node_id, name, kwargs)
    return True


def node_of(world_id: str, agent_id: int) -> str:
    """Where *agent_id* runs (``hub`` unless assigned to a node)."""
    return next((nid for nid, ids in placement(world_id).items() if int(agent_id) in ids), HUB)


def broadcast(world_id: str, name: str, kwargs: dict[str, Any]) -> int:
    """Queue an intervention on every node running this run; returns how many."""
    world_hub = hub.get(world_id)
    sent = 0
    for node_id in placement(world_id):
        if node_id != HUB and world_hub.running_here(node_id):
            world_hub.push(node_id, name, kwargs)
            sent += 1
    return sent


# -- the owner's side ---------------------------------------------------------


def _owned_world(user: dict[str, Any]) -> dict[str, Any]:
    world = world_paths.current_world()
    if world is None:
        raise PermissionError("分布式节点属于某个世界：先在顶栏选择你的世界")
    if user.get("role") != "admin" and world["owner_id"] != user.get("id"):
        raise PermissionError("只有世界的创建者能管理它的节点")
    return world


def overview(user: dict[str, Any]) -> dict[str, Any]:
    world = _owned_world(user)
    plan = placement(world["id"])
    alive, run_id = _run(world["id"])
    world_hub = hub.get(world["id"])
    listed = []
    for node in nodes.load(_repo(), world["id"]):
        public = nodes.public(node)
        public["running_agent_ids"] = plan.get(node["id"], [])
        public.update(world_hub.view(node["id"]))
        listed.append(public)
    cfg = world_paths.effective_config()
    return {
        "world": {"id": world["id"], "name": world["name"]},
        "running": alive,
        "run_id": run_id,
        "hub": {"agent_ids": plan[HUB], **world_hub.view(HUB)},
        "nodes": listed,
        "sync_timeout_seconds": (cfg.get("cluster") or {}).get("sync_timeout_seconds", 60),
    }


def _owner_post(user: dict[str, Any], path: str, payload: dict[str, Any], store: Any) -> dict[str, Any]:
    world = _owned_world(user)
    if path == "/api/cluster/nodes":
        node, token = nodes.add(
            _repo(),
            world["id"],
            payload.get("name", ""),
            _int_list(payload.get("agent_ids")),
            _residents(),
            created_by=str(user.get("nickname") or ""),
        )
        if store is not None:
            store.audit(user, "cluster_node_add", f"{world['id']} {node['id']} agents={node['agent_ids']}")
        return {"node": node, "token": token, "applies": "next run"}
    parts = path.strip("/").split("/")  # api cluster nodes <id> <what>
    if len(parts) == 5 and parts[2] == "nodes":
        node_id, what = parts[3], parts[4]
        if what == "agents":
            node = nodes.set_agents(
                _repo(), world["id"], node_id, _int_list(payload.get("agent_ids")), _residents()
            )
            return {"node": node, "applies": "next run"}
        if what == "delete":
            nodes.remove(_repo(), world["id"], node_id)
            if store is not None:
                store.audit(user, "cluster_node_remove", f"{world['id']} {node_id}")
            return {"removed": node_id}
    raise LookupError("Unknown endpoint")


def handle_get(user: dict[str, Any] | None, path: str) -> tuple[dict[str, Any], int]:
    if user is None:
        return {"error": "分布式世界需要开启账号功能"}, 404
    if path.rstrip("/") != "/api/cluster":
        return {"error": "Unknown endpoint"}, 404
    try:
        return overview(user), 200
    except PermissionError as exc:
        return {"error": str(exc)}, 403


def handle_post(
    user: dict[str, Any] | None, path: str, payload: dict[str, Any], store: Any = None
) -> tuple[dict[str, Any], int]:
    if user is None:
        return {"error": "分布式世界需要开启账号功能"}, 404
    try:
        return _owner_post(user, path.rstrip("/"), payload, store), 200
    except PermissionError as exc:
        return {"error": str(exc)}, 403
    except LookupError as exc:
        return {"error": str(exc)}, 404
    except (TypeError, ValueError) as exc:
        return {"error": str(exc) or "参数不对"}, 400


# -- the nodes' side ----------------------------------------------------------


def is_node_path(path: str) -> bool:
    path = path.rstrip("/")
    return path == "/api/cluster/node" or path.startswith(("/api/cluster/node/", "/api/cluster/relay/"))


def authenticate(token: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """``(world, node)`` for a node token whose world still exists."""
    found = nodes.authenticate(_repo(), token)
    if found is None:
        return None
    store = _ds().accounts.enabled_store(_repo())
    world = store.get_world(found[0]) if store is not None else None
    return (world, found[1]) if world is not None else None


def _whoami(world: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    alive, run_id = _run(world["id"])
    plan = placement(world["id"])
    cfg = world_paths.effective_config()
    return {
        "world": {"id": world["id"], "name": world["name"]},
        "node": {"id": node["id"], "name": node["name"]},
        "agent_ids": plan.get(node["id"], []),
        "running": alive,
        "run_id": run_id,
        "sync_timeout_seconds": (cfg.get("cluster") or {}).get("sync_timeout_seconds", 60),
    }


def world_bundle(world: dict[str, Any]) -> bytes:
    from gaworld.city.bundle import resolve_city

    repo = _repo()
    settings = bundle.settings_for_node([world_paths.dashboard_config(), worlds.read_config(repo, world["id"])])
    city_dir = None
    ref = str(world_paths.effective_config().get("city") or "").strip()
    if ref:
        try:
            city_dir = str(resolve_city(ref, root=repo).directory)
        except Exception:
            city_dir = None  # a deleted city: the node falls back to the default map
    csv_rel, md_rel = worlds.seed_paths(world["id"])
    seed_dir = os.path.dirname(os.path.join(repo, csv_rel))
    seed_files = {
        name: os.path.join(seed_dir, name)
        for name in (AGENT_FILES[path] for path in worlds.COPIED_AGENT_FILES)
        if os.path.isfile(os.path.join(seed_dir, name))
    }
    return bundle.build(
        settings, os.path.join(repo, csv_rel), os.path.join(repo, md_rel), city_dir, seed_files
    )


def _relay(world_id: str, node: dict[str, Any], path: str, payload: dict[str, Any], query: dict) -> dict:
    backend = hub.get(world_id).relay
    mine = set(placement(world_id).get(node["id"], []))
    if path == "/api/cluster/relay/register":
        agents = [
            a for a in payload.get("agents", []) or [] if isinstance(a, dict) and int(a.get("id", 0)) in mine
        ]
        return backend.register_agents(world_id, node["id"], agents)
    if path == "/api/cluster/relay/directory":
        return backend.get_directory(world_id)
    if path == "/api/cluster/relay/message/send":
        message = dict(payload.get("message") or {})
        if int(message.get("from_agent") or 0) not in mine:
            raise PermissionError("只能以本节点的居民身份发消息")
        return backend.send_message(world_id, node["id"], message)
    if path == "/api/cluster/relay/message/poll":
        wanted = [aid for aid in payload.get("recipient_ids", []) or [] if int(aid) in mine]
        return backend.poll_messages(world_id, wanted, payload.get("since", {}), payload.get("limit", 100))
    raise LookupError("Unknown endpoint")


def handle_node(
    world: dict[str, Any], node: dict[str, Any], method: str, path: str, payload: dict[str, Any], query: dict
) -> tuple[Any, int]:
    """A node's request. Returns ``(payload, status)``; the bundle is ``bytes``."""
    path = path.rstrip("/")
    world_hub = hub.get(world["id"])
    try:
        with _inside(world):
            if path.startswith("/api/cluster/relay/"):
                return _relay(world["id"], node, path, payload, query), 200
            if path == "/api/cluster/node" and method == "GET":
                return _whoami(world, node), 200
            if path == "/api/cluster/node/heartbeat" and method == "POST":
                world_hub.heartbeat(node["id"], payload)
                return _whoami(world, node), 200
            if path == "/api/cluster/node/bundle" and method == "GET":
                return world_bundle(world), 200
            if path == "/api/cluster/node/interventions" and method == "GET":
                return {"items": world_hub.take(node["id"])}, 200
            if path == "/api/cluster/node/records" and method == "POST":
                written = world_hub.append_records(
                    world_paths.records_dir(), node["id"], payload.get("tables") or {}
                )
                return {"written": written}, 200
            if path == "/api/cluster/node/sync" and method == "POST":
                alive, _ = _run(world["id"])
                if node["id"] == HUB:
                    world_hub.heartbeat(HUB, {"state": "running", "run_id": world_hub.run_id})
                return world_hub.sync(
                    node["id"],
                    str(payload.get("run_id") or ""),
                    payload.get("day"),
                    payload.get("time"),
                    alive,
                ), 200
    except PermissionError as exc:
        return {"error": str(exc)}, 403
    except LookupError as exc:
        return {"error": str(exc)}, 404
    except (TypeError, ValueError) as exc:
        return {"error": str(exc) or "参数不对"}, 400
    return {"error": "Unknown endpoint"}, 404


__all__ = [
    "MAX_BODY",
    "authenticate",
    "broadcast",
    "handle_get",
    "handle_node",
    "handle_post",
    "hub_overrides",
    "is_node_path",
    "node_of",
    "placement",
    "route",
    "world_bundle",
]
