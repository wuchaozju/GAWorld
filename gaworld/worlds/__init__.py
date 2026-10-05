"""Worlds: one user's isolated copy of a city (proposal 2026-10-01-multi-user, P2).

A world is a row in the account database (name, owner, city, visibility) plus a
directory ``output/worlds/<id>/`` holding three things:

- ``config.json`` -- the world's settings, layered over the global
  ``dashboard_config.json`` the way that file layers over the defaults;
- ``seed/`` -- copies of the city's state CSV and profile Markdown, so editing a
  resident edits this world only (copy-on-write against the shared bundle);
- every runtime output, at the same paths a city run uses under
  ``output/cities/<slug>/`` (``gaworld.city.config.RUN_PATHS``);
- ``seed/`` also holds the inputs keyed by agent id
  (``gaworld.city.config.AGENT_FILES``): the Big Five table and the family
  pins are copied from the city, Moltbook accounts start empty.

Nothing in the simulator knows about worlds: a run is started with the world's
config and paths in ``GAWORLD_CONFIG_OVERRIDES``, which has the last word.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from typing import Any

from gaworld.city.config import AGENT_FILES, agent_file_overrides, run_root_overrides
from gaworld.settings.overrides import deep_update

WORLDS_DIR = "output/worlds"
VISIBILITIES = ("private", "class", "open")

#: Agent-keyed inputs a new world copies from its city. Moltbook accounts are
#: not: they are live credentials of real accounts, and a copy would have the
#: world's residents post as the city's.
COPIED_AGENT_FILES = ("personality.profile_path", "family.overrides_path")

_ID_RE = re.compile(r"^w[0-9a-f]{8}$")


def valid_id(world_id: str) -> bool:
    return bool(_ID_RE.match(str(world_id or "")))


def root(world_id: str) -> str:
    """Repo-relative directory of a world."""
    if not valid_id(world_id):
        raise ValueError(f"invalid world id: {world_id!r}")
    return f"{WORLDS_DIR}/{world_id}"


def config_path(repo_root: str, world_id: str) -> str:
    return os.path.join(repo_root, root(world_id), "config.json")


def seed_paths(world_id: str) -> tuple[str, str]:
    """Repo-relative ``(state_csv, profiles_md)`` of the world's own residents."""
    base = root(world_id)
    return f"{base}/seed/agents.csv", f"{base}/seed/profiles.md"


def overrides(world_id: str) -> dict[str, Any]:
    """Config patch pinning every runtime path and the resident files to the world."""
    base = root(world_id)
    patch = run_root_overrides(base)
    deep_update(patch, agent_file_overrides(f"{base}/seed"))
    patch["csv_path"], patch["md_path"] = seed_paths(world_id)
    return patch


def read_config(repo_root: str, world_id: str) -> dict[str, Any]:
    try:
        with open(config_path(repo_root, world_id), encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def create_tree(
    repo_root: str,
    world_id: str,
    *,
    city: str,
    csv_src: str,
    md_src: str,
    agent_files: dict[str, str] | None = None,
) -> None:
    """Lay out a new world: its config and its own copy of the residents.

    *agent_files* maps a :data:`COPIED_AGENT_FILES` config path to the file the
    city keeps it in; absent entries leave the world without one.
    """
    base = os.path.join(repo_root, root(world_id))
    os.makedirs(os.path.join(base, "seed"), exist_ok=True)
    csv_dst, md_dst = (os.path.join(repo_root, path) for path in seed_paths(world_id))
    shutil.copyfile(csv_src, csv_dst)
    shutil.copyfile(md_src, md_dst)
    for path, src in (agent_files or {}).items():
        if path in COPIED_AGENT_FILES:
            shutil.copyfile(src, os.path.join(base, "seed", AGENT_FILES[path]))
    with open(config_path(repo_root, world_id), "w", encoding="utf-8") as handle:
        json.dump({"city": city}, handle, ensure_ascii=False, indent=2)


def remove_tree(repo_root: str, world_id: str) -> None:
    shutil.rmtree(os.path.join(repo_root, root(world_id)), ignore_errors=True)


__all__ = [
    "COPIED_AGENT_FILES",
    "VISIBILITIES",
    "WORLDS_DIR",
    "config_path",
    "create_tree",
    "overrides",
    "read_config",
    "remove_tree",
    "root",
    "seed_paths",
    "valid_id",
]
