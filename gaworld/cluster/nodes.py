"""A world's nodes and their tokens.

The list lives next to the world (``output/worlds/<id>/cluster/nodes.json``), so
deleting the world deletes its nodes and the account database keeps its schema.

A token is ``<world_id>.<node_id>.<secret>``: the first two parts say where to
look, only a SHA-256 of the secret is stored (the same as session tokens -- the
secret is random, so a slow hash buys nothing on a request made every second).
The hub's own simulator authenticates the same way with node id ``hub``, whose
secret is minted per run and kept in memory (:func:`hub_token`).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from typing import Any

from gaworld import worlds

HUB = "hub"
_LOCK = threading.RLock()
#: world id -> the hub simulator's secret for the current run
_HUB_SECRETS: dict[str, str] = {}


def _path(repo_root: str, world_id: str) -> str:
    return os.path.join(repo_root, worlds.root(world_id), "cluster", "nodes.json")


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def load(repo_root: str, world_id: str) -> list[dict[str, Any]]:
    try:
        with open(_path(repo_root, world_id), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    return [node for node in data if isinstance(node, dict)] if isinstance(data, list) else []


def _save(repo_root: str, world_id: str, nodes: list[dict[str, Any]]) -> None:
    path = _path(repo_root, world_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(nodes, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def public(node: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in node.items() if key != "token_hash"}


def assigned(repo_root: str, world_id: str) -> dict[int, str]:
    """Resident id -> the node running it. Residents not listed run on the hub."""
    return {int(aid): node["id"] for node in load(repo_root, world_id) for aid in node.get("agent_ids", [])}


def _check_agents(
    nodes: list[dict[str, Any]], agent_ids: list[int], residents: set[int], skip: str = ""
) -> list[int]:
    ids = sorted({int(aid) for aid in agent_ids})
    if not ids:
        raise ValueError("给节点分配至少一位居民")
    unknown = [aid for aid in ids if aid not in residents]
    if unknown:
        raise LookupError(f"这个世界没有这些居民：{unknown}")
    for node in nodes:
        if node["id"] == skip:
            continue
        taken = sorted(set(ids) & set(node.get("agent_ids", [])))
        if taken:
            raise ValueError(f"居民 {taken} 已经分给了节点「{node['name']}」")
    return ids


def add(
    repo_root: str, world_id: str, name: str, agent_ids: list[int], residents: set[int], created_by: str = ""
) -> tuple[dict[str, Any], str]:
    """Add a node; returns ``(node, token)``. The token is never shown again."""
    name = " ".join(str(name or "").split())[:64]
    if not name:
        raise ValueError("给节点起个名字，例如「302 机房 7 号机」")
    with _LOCK:
        nodes = load(repo_root, world_id)
        ids = _check_agents(nodes, agent_ids, residents)
        number = 1 + max((int(n["id"][1:]) for n in nodes if n["id"][1:].isdigit()), default=0)
        secret = secrets.token_urlsafe(24)
        node = {
            "id": f"n{number}",
            "name": name,
            "agent_ids": ids,
            "token_hash": _digest(secret),
            "created_at": time.time(),
            "created_by": str(created_by or ""),
        }
        nodes.append(node)
        _save(repo_root, world_id, nodes)
    return public(node), f"{world_id}.{node['id']}.{secret}"


def set_agents(
    repo_root: str, world_id: str, node_id: str, agent_ids: list[int], residents: set[int]
) -> dict[str, Any]:
    with _LOCK:
        nodes = load(repo_root, world_id)
        node = next((n for n in nodes if n["id"] == node_id), None)
        if node is None:
            raise LookupError(f"没有节点 {node_id}")
        node["agent_ids"] = _check_agents(nodes, agent_ids, residents, skip=node_id)
        _save(repo_root, world_id, nodes)
    return public(node)


def remove(repo_root: str, world_id: str, node_id: str) -> None:
    """Revoke a node: its token stops working and its residents go back to the hub."""
    with _LOCK:
        nodes = load(repo_root, world_id)
        kept = [n for n in nodes if n["id"] != node_id]
        if len(kept) == len(nodes):
            raise LookupError(f"没有节点 {node_id}")
        _save(repo_root, world_id, kept)


def hub_token(world_id: str) -> str:
    """A fresh token for the hub's own simulator (one per run)."""
    secret = secrets.token_urlsafe(24)
    with _LOCK:
        _HUB_SECRETS[world_id] = secret
    return f"{world_id}.{HUB}.{secret}"


def authenticate(repo_root: str, token: str) -> tuple[str, dict[str, Any]] | None:
    """``(world_id, node)`` for a valid token, else None."""
    parts = str(token or "").strip().split(".", 2)
    if len(parts) != 3 or not worlds.valid_id(parts[0]):
        return None
    world_id, node_id, secret = parts
    if node_id == HUB:
        with _LOCK:
            expected = _HUB_SECRETS.get(world_id)
        if expected and hmac.compare_digest(expected, secret):
            return world_id, {"id": HUB, "name": "枢纽", "agent_ids": []}
        return None
    for node in load(repo_root, world_id):
        if node["id"] == node_id and hmac.compare_digest(node["token_hash"], _digest(secret)):
            return world_id, public(node)
    return None


__all__ = ["HUB", "add", "assigned", "authenticate", "hub_token", "load", "public", "remove", "set_agents"]
