"""User/world boundaries shared by all workbench records and jobs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from gaworld.accounts import ownership
from gaworld.accounts.context import WORLD


def visible(record: dict[str, Any] | None) -> bool:
    if not ownership.visible(record):
        return False
    return str((record or {}).get("world_id") or "") == str((WORLD.get() or {}).get("id") or "")


def stamp() -> dict[str, Any]:
    return {**ownership.stamp(), "world_id": str((WORLD.get() or {}).get("id") or "")}


def owned(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if visible(record)]


def artifact_visible(value: str, repo_root: str) -> bool:
    """Authorize every file/archive beneath a parallel experiment manifest."""
    root = Path(repo_root).resolve()
    decoded = unquote(str(value)).replace("\\", "/")
    candidate = Path(decoded) if decoded.startswith(str(root) + "/") else root / decoded.lstrip("/")
    try:
        parts = candidate.resolve().relative_to(root).parts
        lexical_parts = candidate.absolute().relative_to(root).parts
    except ValueError:
        return False
    if lexical_parts[:2] == ("output", "parallel_worlds") and parts[:2] != lexical_parts[:2]:
        return False
    if parts[:2] != ("output", "parallel_worlds"):
        return True
    if len(parts) < 3:
        return False
    path = root.joinpath(*parts[:3], "experiment.json")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(manifest, dict) and visible(manifest)
