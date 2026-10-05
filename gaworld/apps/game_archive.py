"""Finished playground games, kept on disk so they can be counted.

A game's :class:`~gaworld.apps.game_jobs.JobStore` lives in memory: restart
the server and every rumor tree, ballot and disaster board is gone. That is
fine for play and useless for measurement — Track B of GAWorld-Bench
(``benchmark/gaworld_bench.py``) pools finished games to check three
stylized facts, and will not judge one from fewer than five games.

So a store opened with ``archive=True`` also writes each finished result
here, one JSON file per game::

    output/games/<kind>/<YYYYmmdd-HHMMSS>-<job_id>.json

next to the provider the game's calls were routed to — games pooled across
two models are two populations, and the bench says so — and, on a shared
server, who played it.

Writing is best effort: a full disk costs the archive one game, never the
player their result.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from gaworld.accounts import ownership
from gaworld.apps import world_paths
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.game_archive")

#: Read at call time, so tests can point it at a temporary directory.
ARCHIVE_DIR = os.path.join(world_paths.REPO_ROOT, "output", "games")


def _provider(kind: str) -> str:
    """The provider a ``games.<kind>`` call routes to first (the games' own task names)."""
    try:
        from gaworld.llm.providers import resolve_provider

        return str(resolve_provider(task=f"games.{kind}"))
    except Exception:  # provenance is best effort; the game is not
        return ""


def save(kind: str, job_id: str, result: dict[str, Any]) -> str | None:
    """Write one finished game; its path, or None when it could not be written."""
    folder = os.path.join(ARCHIVE_DIR, kind)
    path = os.path.join(folder, f"{time.strftime('%Y%m%d-%H%M%S')}-{job_id}.json")
    try:
        record = {
            "kind": kind,
            "job_id": job_id,
            "archived_at": time.time(),
            "provider": _provider(kind),
            **ownership.stamp(),
            "result": result,
        }
        os.makedirs(folder, exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False)
        os.replace(path + ".tmp", path)
    except Exception as exc:  # best effort, see the module docstring
        _LOG.warning("could not archive %s game %s: %s", kind, job_id, exc)
        return None
    return path


__all__ = ["ARCHIVE_DIR", "save"]
