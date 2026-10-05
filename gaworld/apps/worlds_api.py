"""``/api/worlds``: list, create, switch to, share and delete worlds; run limits.

The active world is a cookie (``gaworld_world``) rather than a header so that
every request the console makes -- fetches, iframes, the SSE stream, trace
files -- lands in the same world without each panel having to know. The
cookie is only a wish: ``_guard`` re-checks visibility on every request and
falls back to the shared default world.

Handlers return ``(payload, status, set_cookie)`` like ``accounts_api``.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from collections.abc import Iterator
from typing import Any

from gaworld import worlds
from gaworld.accounts import AccountError, AccountStore
from gaworld.apps import runs, world_paths

Result = tuple[dict[str, Any], int, str | None]


def _ds() -> Any:
    from gaworld.apps import dashboard_server

    return dashboard_server


def world_cookie(world_id: str) -> str:
    name = _ds().WORLD_COOKIE
    if not world_id:
        return f"{name}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
    return f"{name}={world_id}; Path=/; HttpOnly; SameSite=Strict"


@contextlib.contextmanager
def _inside(world: dict[str, Any] | None) -> Iterator[None]:
    """Act as a request in *world* (None = the shared default world)."""
    token = _ds()._WORLD.set(world)
    try:
        yield
    finally:
        _ds()._WORLD.reset(token)


def _public(
    world: dict[str, Any], user: dict[str, Any], calls_today: dict[Any, int] | None = None
) -> dict[str, Any]:
    state = runs.WORLD_RUNS.get(world["id"]) or {}
    proc = state.get("process")
    queued = next((i + 1 for i, entry in enumerate(runs.RUN_QUEUE) if entry["world_id"] == world["id"]), None)
    return {
        "id": world["id"],
        "name": world["name"],
        "owner": world["owner"],
        "city": world["city"],
        "visibility": world["visibility"],
        "created_at": world["created_at"],
        "mine": world["owner_id"] == user.get("id"),
        "can_write": user.get("role") == "admin" or world["owner_id"] == user.get("id"),
        "running": bool(proc and proc.poll() is None),
        "queued": queued,
        "calls_today": (calls_today or {}).get(world["id"], 0),
    }


def _owned(store: AccountStore, user: dict[str, Any], world_id: str) -> dict[str, Any]:
    world = store.get_world(world_id)
    if world is None or not _ds().world_readable(world, user):
        raise LookupError(f"没有编号为 {world_id} 的世界")
    if user.get("role") != "admin" and world["owner_id"] != user.get("id"):
        raise PermissionError("只有世界的创建者能修改它")
    return world


def handle_get(store: AccountStore | None, user: dict[str, Any] | None, path: str) -> Result:
    if store is None or user is None:
        return {"mode": "single"}, 200, None
    ds = _ds()
    path = path.rstrip("/")
    if path == "/api/worlds/settings":
        if user.get("role") != "admin":
            return {"error": "没有权限：该操作需要管理员"}, 403, None
        return {"limits": runs.limits(store)}, 200, None
    parts = path.split("/")  # ["", "api", "worlds", "<id>", "trail"]
    if len(parts) == 5 and parts[4] == "trail":
        world = store.get_world(parts[3])
        if world is None or not ds.world_readable(world, user):
            return {"error": f"没有编号为 {parts[3]} 的世界"}, 404, None
        return trail(world), 200, None
    if path != "/api/worlds":
        return {"error": "Unknown endpoint"}, 404, None
    from gaworld.accounts import usage

    calls = usage.TALLY.snapshot()["worlds_today"] if user.get("role") == "admin" else {}
    current = world_paths.current_world()
    visible = [w for w in store.list_worlds() if ds.world_readable(w, user)]
    return (
        {
            "mode": "accounts",
            "current": _public(current, user, calls) if current else None,
            "worlds": [_public(w, user, calls) for w in visible],
            "default_writable": user.get("role") == "admin",
        },
        200,
        None,
    )


TRAIL_TABLES = ("multiplayer.presence", "multiplayer.act", "multiplayer.say")


def _trail_line(table: str, row: dict[str, Any]) -> str:
    who = f"{row.get('player', '')}（{row.get('agent_name', '')}）"
    when = f"第 {row.get('_day')} 天 {row.get('_time', '')}"
    if table == "multiplayer.presence":
        stamp = time.strftime("%m-%d %H:%M:%S", time.localtime(float(row.get("_wall") or 0)))
        return f"- {stamp} {row.get('player', '')} {row.get('event', '')} #{row.get('agent_id')}"
    if table == "multiplayer.act":
        return f"- {when} {who}：{row.get('text', '')}"
    return f"- {when} {who}对 {row.get('target_name', '')}：{row.get('text', '')}"


def trail(world: dict[str, Any]) -> dict[str, Any]:
    """Everything people did in a world, as a Markdown document to download."""
    with _inside(world):
        records = world_paths.records_dir()
    lines = [
        f"# {world['name']} · 多人共玩记录",
        "",
        f"- 世界：`{world['id']}`（{world['owner']}）",
        f"- 导出时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    for table, heading in zip(TRAIL_TABLES, ("## 进出", "## 行动", "## 对话"), strict=True):
        rendered = []
        try:
            with open(os.path.join(records, f"{table}.jsonl"), encoding="utf-8") as handle:
                for line in handle:
                    try:
                        rendered.append(_trail_line(table, json.loads(line)))
                    except ValueError:
                        continue
        except OSError:
            pass
        lines += [heading, "", *(rendered or ["（无）"]), ""]
    return {"filename": f"{world['id']}-play.md", "markdown": "\n".join(lines)}


def handle_post(
    store: AccountStore | None, user: dict[str, Any] | None, path: str, payload: dict[str, Any]
) -> Result:
    if store is None or user is None:
        return {"error": "账号功能未开启"}, 404, None
    try:
        return _post(store, user, path.rstrip("/"), payload)
    except (AccountError, ValueError) as exc:
        return {"error": str(exc)}, 400, None
    except PermissionError as exc:
        return {"error": f"没有权限：{exc}"}, 403, None
    except LookupError as exc:
        return {"error": str(exc)}, 404, None


def _post(store: AccountStore, user: dict[str, Any], path: str, payload: dict[str, Any]) -> Result:
    ds = _ds()
    if path == "/api/worlds/settings":
        if user.get("role") != "admin":
            raise PermissionError("该操作需要管理员")
        for key in runs.LIMIT_DEFAULTS:
            if key in payload:
                value = int(payload[key])
                floor = 0 if key == "daily_llm_calls_per_user" else 1  # 0 = no quota
                if value < floor:
                    raise ValueError(f"{key} 至少为 {floor}")
                store.set_setting(key, value)
        store.audit(user, "limits", str(runs.limits(store)))
        return {"limits": runs.limits(store)}, 200, None
    if path == "/api/worlds/broadcast":
        if user.get("role") != "admin":
            raise PermissionError("该操作需要管理员")
        return broadcast(store, user, payload), 200, None
    if path == "/api/worlds/create":
        if not user.get("id"):
            raise PermissionError("该操作需要以账号登录")
        city, csv_src, md_src = ds._city_seed_files(str(payload.get("city") or "").strip())
        agent_files = ds._city_agent_files(city)
        world = store.create_world(user["id"], str(payload.get("name") or ""), city)
        try:
            worlds.create_tree(
                world_paths.REPO_ROOT, world["id"], city=city, csv_src=csv_src, md_src=md_src, agent_files=agent_files
            )
        except OSError:
            store.delete_world(world["id"])
            raise
        store.audit(user, "world_create", f"{world['id']} city={city}")
        return {"world": _public(world, user)}, 200, world_cookie(world["id"])
    if path == "/api/worlds/select":
        world_id = str(payload.get("id") or "")
        if world_id:
            chosen = store.get_world(world_id)
            if chosen is None or not ds.world_readable(chosen, user):
                raise LookupError(f"没有编号为 {world_id} 的世界")
        return {"ok": True, "id": world_id}, 200, world_cookie(world_id)
    parts = path.split("/")  # ["", "api", "worlds", "<id>", "<action>"]
    if len(parts) != 5:
        return {"error": "Unknown endpoint"}, 404, None
    world = _owned(store, user, parts[3])
    if parts[4] == "visibility":
        changed = store.set_world_visibility(world["id"], str(payload.get("visibility") or ""))
        store.audit(user, "world_visibility", f"{world['id']} {changed['visibility']}")
        return {"world": _public(changed, user)}, 200, None
    if parts[4] == "stop":
        with _inside(world):
            runs.stop_simulation()
        store.audit(user, "world_stop", world["id"])
        return {"world": _public(world, user)}, 200, None
    if parts[4] == "delete":
        state = runs.WORLD_RUNS.get(world["id"]) or {}
        proc = state.get("process")
        queued = any(entry["world_id"] == world["id"] for entry in runs.RUN_QUEUE)
        if (proc and proc.poll() is None) or queued:
            raise ValueError("先停止这个世界的仿真再删除")
        store.delete_world(world["id"])
        worlds.remove_tree(world_paths.REPO_ROOT, world["id"])
        runs.WORLD_RUNS.pop(world["id"], None)
        store.audit(user, "world_delete", world["id"])
        current = world_paths.current_world()
        cookie = world_cookie("") if current and current["id"] == world["id"] else None
        return {"ok": True}, 200, cookie
    return {"error": "Unknown endpoint"}, 404, None


def broadcast(store: AccountStore, user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Give every resident of the chosen worlds the same life event.

    Written to each world's own life-event queue, as an immediate event for
    everyone: a running world picks it up at its next tick, a stopped one at
    its next start. ``""`` in ``world_ids`` is the shared default world.
    """
    from gaworld.events.life import add_life_event

    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValueError("事件标题不能为空")
    event = {
        "title": title,
        "description": str(payload.get("description") or title).strip(),
        "severity": payload.get("severity", 0.6),
        "schedule_mode": "immediate",
        "created_by": f"broadcast:{user.get('nickname', '')}",
    }
    results = []
    for raw in payload.get("world_ids") or []:
        world_id = str(raw or "")
        world = store.get_world(world_id) if world_id else None
        if world_id and world is None:
            results.append({"id": world_id, "ok": False, "error": "没有这个世界"})
            continue
        with _inside(world):
            cfg = world_paths.effective_config()
            # Absolute, so the dashboard writes the very file the simulator
            # (cwd = repo root) reads, wherever the dashboard was started.
            life = dict(cfg.get("life_events") or {})
            life["event_dir"] = os.path.join(world_paths.REPO_ROOT, str(life.get("event_dir") or "output/life_events"))
            cfg["life_events"] = life
            add_life_event(event, cfg)
            running = bool(runs.run_status().get("running"))
        results.append(
            {"id": world_id, "name": world["name"] if world else "", "ok": True, "running": running}
        )
    store.audit(user, "broadcast", f"{title} -> {len(results)} worlds")
    return {"results": results}


__all__ = ["broadcast", "handle_get", "handle_post", "trail", "world_cookie"]
