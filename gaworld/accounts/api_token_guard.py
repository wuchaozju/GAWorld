"""Explicit Bearer authentication, with a fail-closed route allowlist."""

from __future__ import annotations

import hmac
import os

from . import api_tokens
from .context import USER, WORLD
from .request_security import check_world

READ_PATHS = frozenset(
    "/api/parallel-worlds/" + name
    for name in (
        "overview",
        "experiments",
        "experiment",
        "heterogeneity",
        "interpretation",
        "job",
    )
)
RUN_PATHS = frozenset(
    "/api/parallel-worlds/" + name
    for name in (
        "preview",
        "sweep",
        "start",
        "stop",
        "interpret",
    )
)


def scope_for(method, path):
    if method in {"GET", "HEAD"} and path in READ_PATHS:
        return "parallel:read"
    if method == "POST" and path in RUN_PATHS:
        return "parallel:run"
    return None


def guard(handler, path):
    """None delegates to legacy login; bool means this credential decided the request."""
    header = handler.headers.get("Authorization")
    if header is None:
        return None
    parts = header.split()
    secret = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else ""
    operator = os.environ.get("GAWORLD_DASHBOARD_TOKEN", "").strip()
    if secret and operator and hmac.compare_digest(secret.encode(), operator.encode()):
        return None  # Preserve the separately provisioned operator credential.
    found = api_tokens.authenticate(handler.accounts, secret) if handler.accounts else None
    if found is None:
        handler._deny(401, "Invalid, expired or revoked API token")
        return True
    user, world, token = found
    scope = scope_for(handler.command, path)
    metadata = handler.command in {"GET", "HEAD"} and path in {"/api/auth/me", "/api/openapi.json"}
    if not metadata and (scope is None or scope not in token["scopes"]):
        handler._deny(403, "API token does not grant this operation")
        return True
    if handler.command == "POST":
        try:
            length = int(handler.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 <= length <= 4 * 1024 * 1024:
            handler.close_connection = True
            handler._deny(400 if length < 0 else 413, "Invalid or oversized request body")
            return True
    handler.user = user
    USER.set(user)
    WORLD.set(world)
    refusal = check_world(handler)
    if refusal:
        handler._deny(refusal[1], refusal[0])
        return True
    api_tokens.touch(handler.accounts, token["id"])
    return False
