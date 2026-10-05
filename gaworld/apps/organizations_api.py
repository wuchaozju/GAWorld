"""World-scoped organization reads and persistent command submission.

The dashboard is a queue writer. It never executes an organization command or
changes the economy: the world's simulator applies commands at a day boundary.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from gaworld.accounts import context, ownership, policy
from gaworld.apps import world_paths
from gaworld.organizations.exports import ExportInvalid, ExportUnavailable, read_metrics
from gaworld.organizations.schemas import identifier
from gaworld.organizations.store import OrganizationStore


def _store(generation_id=None) -> OrganizationStore:
    return OrganizationStore(
        os.path.join(world_paths.memory_base_dir(), "organizations.sqlite"), generation_id=generation_id
    )


def _can_write() -> bool:
    user = context.USER.get()
    return user is None or policy.allows(user, "world", world_paths.current_world())


def _metrics(query: dict[str, Any]) -> tuple[dict[str, Any], int]:
    if set(query) - {"generation_id", "day"}:
        return {"error": "Organization exports use the active world; unsupported query parameter"}, 400
    try:
        values = {}
        for key, raw in query.items():
            if isinstance(raw, list):
                if len(raw) != 1:
                    raise ValueError("Each export parameter must occur exactly once")
                raw = raw[0]
            if not isinstance(raw, str):
                raise ValueError("Invalid export query parameter")
            values[key] = raw
        generation = identifier(values["generation_id"]) if "generation_id" in values else None
        raw_day = values.get("day")
        if raw_day is not None and (not raw_day.isascii() or not raw_day.isdecimal()):
            raise ValueError("day must be a positive integer")
        day = int(raw_day) if raw_day is not None else None
        if day is not None and not 1 <= day <= 10**9:
            raise ValueError("day must be a positive integer up to 1000000000")
    except (ValueError, TypeError):
        return {"error": "Invalid generation_id or day; each parameter must occur exactly once"}, 400
    config = world_paths.effective_config()
    output = (config.get("organizations") or {}).get("output_dir", "output/organizations")
    memory = config.get("memory_dir", "output/memory")
    try:
        return read_metrics(
            Path(world_paths.REPO_ROOT) / output,
            Path(world_paths.REPO_ROOT) / memory,
            generation_id=generation,
            day=day,
        ), 200
    except ExportUnavailable as exc:
        return {"error": str(exc)}, 404
    except ExportInvalid as exc:
        return {"error": str(exc)}, 409


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    query = query or {}
    if path.rstrip("/") == "/api/organizations/exports/metrics":
        return _metrics(query)
    parts = path.rstrip("/").split("/")[3:]
    history = len(parts) == 2 and parts[1] == "history"
    allowed = {"limit"} if history else set()
    if not parts or parts[0] != "commands":
        allowed.add("generation_id")
    if set(query) - allowed:
        return {"error": "Organization paths use the active world; unsupported query parameter"}, 400
    limit = 100
    if history:
        raw_limit = query.get("limit", ["100"])
        try:
            limit = int(raw_limit[0] if isinstance(raw_limit, list) else raw_limit)
        except (ValueError, TypeError, IndexError):
            return {"error": "limit must be an integer from 1 to 1000"}, 400
        if not 1 <= limit <= 1000:
            return {"error": "limit must be an integer from 1 to 1000"}, 400
    raw_generation = query.get("generation_id")
    try:
        generation = (
            identifier(raw_generation[0] if isinstance(raw_generation, list) else raw_generation)
            if raw_generation is not None
            else None
        )
    except (ValueError, IndexError):
        return {"error": "Invalid generation_id"}, 400
    store = _store(generation)
    try:
        if not parts:
            config = world_paths.effective_config().get("organizations", {}) or {}
            return {
                "organizations": store.list_organizations(),
                "enabled": bool(config.get("enabled", False)),
                "governance_enabled": bool(config.get("enabled", False) and (config.get("governance") or {}).get("enabled", False)),
                "can_write": _can_write() and generation is None,
                "execution": "next_day_boundary" if generation is None else "historical_read_only",
                "meta": store.generation_meta(),
            }, 200
        if parts == ["commands"]:
            return {"commands": store.commands()}, 200
        if len(parts) == 2 and parts[0] == "commands":
            command = store.command(parts[1])
            return (command, 200) if command is not None else ({"error": "Unknown organization command"}, 404)
        if len(parts) == 1 or history:
            organization = store.detail(parts[0])
            if organization is None:
                return {"error": "Unknown organization"}, 404
            return (
                ({"history": store.history(parts[0], limit=limit)}, 200) if history else (organization, 200)
            )
        return {"error": "Unknown endpoint"}, 404
    finally:
        store.close()


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    if path.rstrip("/") != "/api/organizations/commands":
        return {"error": "Unknown endpoint"}, 404
    if not _can_write():
        return {
            "error": "Only the active world's owner or an administrator may submit organization commands"
        }, 403
    try:
        store = _store()
        try:
            command = store.enqueue(payload, actor=ownership.stamp())
        finally:
            store.close()
    except ValueError as exc:
        return {"error": str(exc)}, 400
    return command, 202
