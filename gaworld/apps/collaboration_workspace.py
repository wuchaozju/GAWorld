"""Resolve collaboration storage and cache identity from request context."""

from __future__ import annotations

import copy
from pathlib import Path

from gaworld.accounts.context import USER, WORLD
from gaworld.apps import world_paths
from gaworld.collaboration.organization_methods import digest


def config():
    effective = world_paths.effective_config()
    result = copy.deepcopy(effective.get("collaboration") or {})
    user = USER.get() or {}
    base = Path(result.get("sessions_dir") or "output/collaboration/sessions")
    if WORLD.get():
        base = Path(world_paths.world_file("collaboration", "sessions"))
    if user.get("id"):
        base = base / ("user-" + digest(str(user["id"]))[:20])
    result["sessions_dir"] = str(base)
    return result


def key():
    return digest(
        {
            "user": (USER.get() or {}).get("id"),
            "world": (WORLD.get() or {}).get("id"),
            "config": config(),
            "memory": world_paths.effective_config().get("memory_dir"),
        }
    )
