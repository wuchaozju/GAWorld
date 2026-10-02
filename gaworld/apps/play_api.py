"""``/api/play``: people playing residents of an open world (proposal 2026-10-01, P4).

Who plays whom is a lease kept here, in memory: claiming a resident holds it
for :data:`LEASE_SECONDS`, and the player's page renews it every 30 s, so a
closed tab hands the resident back to the model within two minutes. Every
renewal is also sent to the running simulator (``player_claim``), so a run
started after people joined learns who plays whom at the next heartbeat.

Actions travel through the world's kernel intervention queue and land at the
simulator's next tick (``gaworld.multiplayer``). Joining, claiming and letting
go are written straight into the world's record stream, so everybody watching
sees them live even while the simulation is stopped.

Playable: a world whose visibility is ``open`` -- for its owner and admins,
any world of theirs. Handlers return ``(payload, status)``.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

LEASE_SECONDS = 120

#: world id -> agent id -> {"user_id", "player", "until"}
_CLAIMS: dict[str, dict[int, dict[str, Any]]] = {}
_LOCK = threading.Lock()


class Conflict(Exception):
    """Answered with 409."""


def _ds() -> Any:
    from gaworld.apps import dashboard_server

    return dashboard_server


def _world(user: dict[str, Any]) -> dict[str, Any]:
    world = _ds()._current_world()
    if world is None:
        raise PermissionError("先在顶栏选择一个开放的世界（共享的默认世界不能多人共玩）")
    owner_or_admin = user.get("role") == "admin" or world["owner_id"] == user.get("id")
    if world["visibility"] != "open" and not owner_or_admin:
        raise PermissionError("这个世界没有开放多人进入")
    return world


def _residents() -> dict[int, str]:
    return {int(row["id"]): row["name"] for row in _ds()._agents_summary()}


def _running() -> bool:
    return bool(_ds()._run_status().get("running"))


def _send(name: str, **kwargs: Any) -> bool:
    """Queue an intervention for the world's running simulator; False if none."""
    from gaworld.apps import kernel_api
    from gaworld.kernel import remote

    try:
        remote.enqueue(kernel_api._queue_path(), name, kwargs)
    except LookupError:  # includes KeyError: no live run, or one without the plugin
        return False
    return True


def _presence(event: str, agent_id: int, player: str) -> None:
    """One row in the world's record stream, so every watcher sees it live."""
    records = _ds()._records_dir()
    os.makedirs(records, exist_ok=True)
    row = {"_wall": time.time(), "event": event, "agent_id": agent_id, "player": player}
    with open(os.path.join(records, "multiplayer.presence.jsonl"), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _live(world_id: str) -> dict[int, dict[str, Any]]:
    """The world's claims, with lapsed ones handed back (and announced)."""
    now = time.time()
    with _LOCK:
        claims = _CLAIMS.setdefault(world_id, {})
        lapsed = [(aid, claim) for aid, claim in claims.items() if claim["until"] <= now]
        for aid, _ in lapsed:
            claims.pop(aid, None)
        live = dict(claims)
    for aid, claim in lapsed:
        _presence("lapse", aid, claim["player"])
        _send("player_release", agent_id=aid)
    return live


def _mine(world_id: str, user: dict[str, Any]) -> int | None:
    for aid, claim in _live(world_id).items():
        if claim["user_id"] == user.get("id"):
            return aid
    return None


def state(user: dict[str, Any]) -> dict[str, Any]:
    world = _world(user)
    live = _live(world["id"])
    return {
        "world": {"id": world["id"], "name": world["name"], "visibility": world["visibility"]},
        "running": _running(),
        "lease_seconds": LEASE_SECONDS,
        "claims": [
            {"agent_id": aid, "player": claim["player"], "mine": claim["user_id"] == user.get("id")}
            for aid, claim in sorted(live.items())
        ],
        "mine": _mine(world["id"], user),
    }


def claim(user: dict[str, Any], payload: dict[str, Any], store: Any = None) -> dict[str, Any]:
    """Claim a resident, or renew the lease on the one already held."""
    world = _world(user)
    agent_id = int(payload["agent_id"])
    residents = _residents()
    if agent_id not in residents:
        raise LookupError(f"这个世界没有 #{agent_id} 号居民")
    player = str(user.get("nickname") or "")
    until = time.time() + LEASE_SECONDS
    live = _live(world["id"])
    holder = live.get(agent_id)
    if holder and holder["user_id"] != user.get("id"):
        raise Conflict(f"{residents[agent_id]} 正由 {holder['player']} 扮演")
    previous = _mine(world["id"], user)
    if previous is not None and previous != agent_id:
        release(user)
    with _LOCK:
        _CLAIMS.setdefault(world["id"], {})[agent_id] = {
            "user_id": user.get("id"),
            "player": player,
            "until": until,
        }
    if holder is None:
        _presence("claim", agent_id, player)
        if store is not None:
            store.audit(user, "play_claim", f"{world['id']} agent={agent_id}")
    _send("player_claim", agent_id=agent_id, player=player, until=until)
    return {"agent_id": agent_id, "name": residents[agent_id], "until": until}


def release(user: dict[str, Any]) -> dict[str, Any]:
    world = _world(user)
    agent_id = _mine(world["id"], user)
    if agent_id is None:
        return {"released": None}
    with _LOCK:
        _CLAIMS.get(world["id"], {}).pop(agent_id, None)
    _presence("release", agent_id, str(user.get("nickname") or ""))
    _send("player_release", agent_id=agent_id)
    return {"released": agent_id}


def _held(user: dict[str, Any]) -> int:
    world = _world(user)
    agent_id = _mine(world["id"], user)
    if agent_id is None:
        raise Conflict("你还没有认领居民")
    if not _running():
        raise Conflict("仿真没有在运行：行动要在运行中的世界里才会生效")
    return agent_id


def act(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    agent_id = _held(user)
    text = str(payload.get("text") or "").strip()
    if not text:
        raise ValueError("写下这一步要做什么")
    if not _send("player_act", agent_id=agent_id, text=text):
        raise Conflict("仿真没有在运行，或这次运行还不支持多人共玩（重新启动仿真即可）")
    return {"agent_id": agent_id, "applies": "next tick"}


def say(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    agent_id = _held(user)
    target_id = int(payload["target_id"])
    if target_id not in _residents() or target_id == agent_id:
        raise LookupError("选一位别的居民")
    text = str(payload.get("text") or "").strip()
    if not text:
        raise ValueError("写下要说的话")
    if not _send("player_say", agent_id=agent_id, target_id=target_id, text=text):
        raise Conflict("仿真没有在运行，或这次运行还不支持多人共玩（重新启动仿真即可）")
    return {"agent_id": agent_id, "target_id": target_id, "applies": "next tick"}


def handle_get(user: dict[str, Any] | None, path: str) -> tuple[dict[str, Any], int]:
    if user is None:
        return {"error": "账号功能未开启"}, 404
    if path.rstrip("/") != "/api/play":
        return {"error": f"unknown endpoint: {path}"}, 404
    try:
        return state(user), 200
    except PermissionError as exc:
        return {"error": str(exc)}, 403


def handle_post(
    user: dict[str, Any] | None, path: str, payload: dict[str, Any], store: Any = None
) -> tuple[dict[str, Any], int]:
    if user is None:
        return {"error": "账号功能未开启"}, 404
    routes = {
        "/api/play/claim": lambda: claim(user, payload, store),
        "/api/play/release": lambda: release(user),
        "/api/play/act": lambda: act(user, payload),
        "/api/play/say": lambda: say(user, payload),
    }
    route = routes.get(path.rstrip("/"))
    if route is None:
        return {"error": f"unknown endpoint: {path}"}, 404
    try:
        return route(), 200
    except PermissionError as exc:
        return {"error": str(exc)}, 403
    except Conflict as exc:
        return {"error": str(exc)}, 409
    except KeyError as exc:  # before LookupError, its base class
        return {"error": f"缺少参数 {exc}"}, 400
    except LookupError as exc:
        return {"error": str(exc)}, 404
    except (TypeError, ValueError) as exc:
        return {"error": str(exc) or "参数不对"}, 400


def reset() -> None:
    """Drop every lease. Used by tests; production code never calls it."""
    with _LOCK:
        _CLAIMS.clear()


__all__ = ["LEASE_SECONDS", "handle_get", "handle_post", "reset"]
