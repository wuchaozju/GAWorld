"""Who is asking, and in which world: per-request context for the dashboard.

Set by ``dashboard_server._guard`` on every request. Kept in this dependency-free
module so the API modules can read them without importing the dashboard, and
so a background job can carry them (see :func:`gaworld.accounts.ownership.spawn`).
"""

from __future__ import annotations

import contextvars
from typing import Any

#: The signed-in user (a user row, or the token admin); None in single-user mode.
USER: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("gaworld_user", default=None)

#: The request's active world (a world row); None for the shared default world.
WORLD: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("gaworld_world", default=None)
