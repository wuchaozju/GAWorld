"""Model selection inside an owned world, with shared endpoints kept read-only."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from gaworld import worlds
from gaworld.accounts.context import USER
from gaworld.apps import world_paths


def can_edit() -> bool:
    """Only the active world's owner or an administrator can change its routing."""
    user, world = USER.get(), world_paths.current_world()
    return bool(user and world and (user.get("role") == "admin" or world.get("owner_id") == user.get("id")))


def _validated(payload: Any, providers: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"routing"}:
        raise ValueError("Only routing is accepted; select the world using the world picker.")
    patch = payload["routing"]
    if not isinstance(patch, dict) or not patch or set(patch) - {"default", "tasks", "agents", "fallback"}:
        raise ValueError("Routing accepts default, tasks, agents and fallback only.")

    def check(name: Any) -> None:
        if not isinstance(name, str) or name not in providers:
            raise ValueError("Select an existing model backend; provider endpoints cannot be changed here.")

    if "default" in patch:
        check(patch["default"])
    if "fallback" in patch:
        if not isinstance(patch["fallback"], list):
            raise ValueError("fallback must be a list of model backend names.")
        for name in patch["fallback"]:
            check(name)
    for key in ("tasks", "agents"):
        if key not in patch:
            continue
        if not isinstance(patch[key], dict):
            raise ValueError(f"{key} must map task or resident identifiers to model backends.")
        for identifier, name in patch[key].items():
            if (
                not isinstance(identifier, str)
                or not identifier
                or (key == "agents" and not identifier.isascii())
            ):
                raise ValueError("Invalid routing identifier.")
            if key == "agents" and not identifier.isdecimal():
                raise ValueError("Resident identifiers must be non-negative integers.")
            check(name)
    return deepcopy(patch)


def save(payload: Any) -> dict[str, Any]:
    """Persist only routing to the selected world, never to the global config."""
    if not can_edit():
        raise PermissionError("Select a world you own before changing its model routing.")
    effective = world_paths.effective_config()
    llm = effective.get("llm") or {}
    patch = _validated(payload, llm.get("providers") or {})
    old = llm.get("routing") or {}
    if "default" in patch and patch["default"] != old.get("default"):
        # Existing tasks using the old default should follow the new selection;
        # independently chosen models and explicit task edits remain intact.
        for task, name in (old.get("tasks") or {}).items():
            if name == old.get("default") and task not in patch.get("tasks", {}):
                patch.setdefault("tasks", {})[task] = patch["default"]
    world = world_paths.current_world()
    assert world is not None
    current = worlds.read_config(world_paths.REPO_ROOT, world["id"])
    world_paths.deep_update(current, {"llm": {"routing": patch}})
    world_paths.atomic_write_json(world_paths.config_path(), current)
    from gaworld.apps import settings_api

    return {
        "saved": True,
        "applied": sorted(settings_api._flatten(patch, "llm.routing")),
        "dropped": [],
        "blocked": [],
        **settings_api.overview(),
    }
