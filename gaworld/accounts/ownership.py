"""Results belong to whoever made them (proposal 2026-10-01-multi-user, P3).

Interview sessions, research plans, distilled personas, game runs: each is
stamped with its creator when it is made, listed and read only by that creator
(and admins), and deleted only by them. Records made before accounts existed,
or by the operator token, carry no member's id and so are visible to admins
only — the safe default for a shared server.

In single-user mode there is no user in the context and everything stays
visible, exactly as before.
"""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Callable, Iterable
from typing import Any

from .context import USER


def stamp() -> dict[str, Any]:
    """Fields to merge into a new record: its creator, or nothing in single-user mode."""
    user = USER.get()
    if user is None:
        return {}
    return {"owner_id": user.get("id"), "owner": user.get("nickname", "")}


def visible(record: dict[str, Any] | None) -> bool:
    """May the current user read (and delete) *record*?"""
    if record is None:
        return False
    user = USER.get()
    if user is None or user.get("role") == "admin":
        return True
    return record.get("owner_id") == user.get("id")


def sees_unowned() -> bool:
    """Records nobody owns (pre-accounts, operator-made, admin-only kinds)."""
    return visible({})


def owned(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if visible(record)]


def spawn(target: Callable[..., Any], *args: Any, name: str) -> threading.Thread:
    """Start a daemon thread that runs in a copy of the caller's context.

    A new thread starts with an empty context, so without this a background
    job would forget who asked for it and which world they were in.
    """
    thread = threading.Thread(
        target=contextvars.copy_context().run, args=(target, *args), name=name, daemon=True
    )
    thread.start()
    return thread


__all__ = ["owned", "sees_unowned", "spawn", "stamp", "visible"]
