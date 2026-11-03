"""Ownership, cached inputs, output paths and model calls for Population Studio."""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from typing import Any

from gaworld.accounts import ownership
from gaworld.accounts.context import USER
from gaworld.apps import world_paths

_CACHE: OrderedDict[tuple[int | None, str | None], dict[str, Any]] = OrderedDict()
_LOCK = threading.Lock()
_MAX_SCOPES = 32


def can_write() -> bool:
    user, world = USER.get(), world_paths.current_world()
    return (
        user is None or user.get("role") == "admin" or bool(world and world.get("owner_id") == user.get("id"))
    )


def require_write(size: int | None = None) -> None:
    if not can_write():
        raise PermissionError("请先切换到自己的世界，再生成或运行人口实验。")
    user = USER.get()
    if user and user.get("role") != "admin" and size is not None and size > 5000:
        raise ValueError("普通用户每次最多生成 5000 位居民。")


def tag() -> dict[str, Any]:
    return {**ownership.stamp(), "world_id": (world_paths.current_world() or {}).get("id")}


def visible(record: dict[str, Any]) -> bool:
    user = USER.get()
    return ownership.visible(record) and (
        user is None or user.get("role") == "admin" or record.get("world_id") == tag()["world_id"]
    )


def _key() -> tuple[int | None, str | None] | None:
    user, world = USER.get(), world_paths.current_world()
    if world is None and (user is None or user.get("role") == "admin"):
        return None  # Preserve the legacy single-user/admin workspace.
    return (user.get("id") if user else None, world.get("id") if world else None)


def current(legacy: dict[str, Any]) -> dict[str, Any]:
    key = _key()
    with _LOCK:
        return dict(legacy if key is None else _CACHE.get(key, {}))


def remember(legacy: dict[str, Any], entry: dict[str, Any]) -> None:
    key = _key()
    with _LOCK:
        if key is None:
            legacy.clear()
            legacy.update(entry)
        else:
            _CACHE[key] = entry
            _CACHE.move_to_end(key)
            while len(_CACHE) > _MAX_SCOPES:
                _CACHE.popitem(last=False)


def output_dir(payload: dict[str, Any]) -> str:
    root = os.path.realpath(world_paths.REPO_ROOT)
    world = world_paths.current_world()
    default = f"output/worlds/{world['id']}/population" if world else "output/population"
    target = os.path.realpath(os.path.join(root, str(payload.get("out_dir") or default)))
    if os.path.commonpath([root, target]) != root:
        raise ValueError("out_dir 必须位于仓库目录内")
    user = USER.get()
    if user and user.get("role") != "admin":
        require_write()
        base = os.path.join(root, default)
        if os.path.commonpath([base, target]) != base:
            raise ValueError("人口文件只能写入当前世界的 population 目录。")
    return target


def model_call(provider: str | None):
    """Use this world's routing and the current account's credentials and quota."""
    from gaworld.accounts import usage
    from gaworld.accounts.community import begin_model_call, settle_call
    from gaworld.llm.credentials import validate_launch
    from gaworld.llm.providers import LLMRouter

    config = world_paths.effective_config()
    if provider:
        if provider not in config.get("llm", {}).get("providers", {}):
            raise ValueError("所选模型后端不存在。")
        config["llm"]["routing"] = {"default": provider}
    validate_launch(config)
    router = LLMRouter(config)

    def call(prompt: str, task: str | None = None, agent_id: Any = None) -> str:
        reservation = begin_model_call()
        try:
            return str(
                router.call(prompt, task=task, agent_id=agent_id, provider=provider, allow_fallback=False)
            )
        finally:
            if reservation is not None:
                settle_call(*reservation)
            usage.record(task)

    return call
