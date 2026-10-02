"""Model-call usage per user, for the classroom's soft quota (proposal 2026-10-01, P3).

Every ``call_llm`` appends one line to ``usage.jsonl`` beside the account
database -- who (user id), where (world id) and what (task). The unit is the
call: the providers do not report tokens uniformly, and a call is what a
teacher can reason about ("about 200 per interview round").

Writers are the dashboard itself (request threads and their jobs, which carry
the user in :mod:`gaworld.accounts.context`) and its child processes (the
simulator, interview workers), which get the user through the environment --
see :func:`child_env`. A short ``O_APPEND`` write is atomic, so they need no
lock. Nothing is written in single-user mode (no account database).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from .context import USER, WORLD

ENV_USER = "GAWORLD_USER_ID"
ENV_WORLD = "GAWORLD_WORLD_ID"

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])


def usage_path() -> str | None:
    """The log beside the account database, or None when accounts are off."""
    from . import db_path

    db = db_path(_PROJECT_ROOT)
    return os.path.join(os.path.dirname(db), "usage.jsonl") if os.path.exists(db) else None


def _who() -> tuple[Any, Any]:
    user, world = USER.get(), WORLD.get()
    user_id = user.get("id") if user else _env_int(ENV_USER)
    world_id = world.get("id") if world else (os.environ.get(ENV_WORLD) or None)
    return user_id, world_id


def _env_int(name: str) -> int | None:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return None


def record(task: Any = None) -> None:
    """Append one model call. Never raises: accounting must not break a call."""
    try:
        path = usage_path()
        if path is None:
            return
        user_id, world_id = _who()
        line = json.dumps({"t": time.time(), "user": user_id, "world": world_id, "task": str(task or "")})
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        return


def child_env(env: dict[str, str]) -> dict[str, str]:
    """Copy the caller's user and world into a child process's environment."""
    user_id, world_id = _who()
    if user_id is not None:
        env[ENV_USER] = str(user_id)
    if world_id:
        env[ENV_WORLD] = str(world_id)
    return env


class Tally:
    """Calls per (local date, user), read incrementally from the log."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path: str | None = None
        self._offset = 0
        self._by_day: dict[str, dict[Any, int]] = {}
        self._by_day_world: dict[str, dict[Any, int]] = {}
        self._total: dict[Any, int] = {}

    def _refresh(self, path: str) -> None:
        if path != self._path:
            self._path, self._offset, self._by_day, self._by_day_world, self._total = path, 0, {}, {}, {}
        try:
            with open(path, "rb") as handle:
                handle.seek(self._offset)
                chunk = handle.read()
        except OSError:
            return
        # A writer may be mid-line; leave the tail for the next read.
        complete = chunk[: chunk.rfind(b"\n") + 1]
        self._offset += len(complete)
        for raw in complete.splitlines():
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            day = time.strftime("%Y-%m-%d", time.localtime(float(row.get("t") or 0)))
            user = row.get("user")
            per_day = self._by_day.setdefault(day, {})
            per_day[user] = per_day.get(user, 0) + 1
            self._total[user] = self._total.get(user, 0) + 1
            world = row.get("world")
            per_world = self._by_day_world.setdefault(day, {})
            per_world[world] = per_world.get(world, 0) + 1

    def snapshot(self) -> dict[str, Any]:
        """``{"today": {user: n}, "total": {user: n}, "worlds_today": {world: n}}`` as of now."""
        path = usage_path()
        with self._lock:
            if path is None:
                return {"today": {}, "total": {}, "worlds_today": {}}
            self._refresh(path)
            today = time.strftime("%Y-%m-%d")
            return {
                "today": dict(self._by_day.get(today, {})),
                "total": dict(self._total),
                "worlds_today": dict(self._by_day_world.get(today, {})),
            }

    def today(self, user_id: Any) -> int:
        return int(self.snapshot()["today"].get(user_id, 0))


TALLY = Tally()

__all__ = ["ENV_USER", "ENV_WORLD", "TALLY", "Tally", "child_env", "record", "usage_path"]
