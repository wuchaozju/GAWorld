"""Periodic memory decay / forgetting.

Without forgetting, the vector DB grows unboundedly and old, never-
recalled trivia competes with today's relevant memory. A real person
forgets the boring bits faster than the surprising or emotionally-
charged ones; we approximate that here.

:func:`decay_pass` walks an agent's episodic rows and either:

* lowers ``salience`` for rows that haven't been recalled in a while
  (slow fade), or
* deletes rows whose salience already sits below the configured floor
  AND that are old enough to be safely dropped.

``semantic`` and ``external_info`` rows are spared — they encode the
agent's distilled knowledge and external background and shouldn't
silently disappear.
"""

from __future__ import annotations

import time
from typing import Any

from gaworld.settings import CONFIG
from gaworld.logging_setup import get_logger
from gaworld.memory.store import _init_vector_db, _vector_db_connect

_LOG = get_logger("gaworld.memory.decay")

_PROTECTED_TYPES = ("semantic", "external_info", "procedural")
# Rows we WILL decay — anything an agent could plausibly forget.
_DECAYABLE_TYPES = ("memory", "diary", "news", "info_seek", "web_search")


def _decay_config() -> dict[str, Any]:
    return (CONFIG.get("memory", {}) or {}).get("decay", {}) or {}


def decay_pass(
    agent_id: int,
    *,
    today: int | None = None,
    min_age_days: int | None = None,
    salience_floor: float | None = None,
    salience_step: float = 0.05,
) -> dict[str, int]:
    """One round of forgetting for ``agent_id``.

    Returns a small summary dict::

        {"decayed": N, "deleted": M}

    so callers can log activity. A no-op (zeros) when decay is
    disabled. Rows protected by ``_PROTECTED_TYPES`` are never touched.
    """
    cfg = _decay_config()
    if not cfg.get("enabled", False):
        return {"decayed": 0, "deleted": 0}
    min_age = int(min_age_days if min_age_days is not None else cfg.get("min_age_days", 30))
    floor = float(salience_floor if salience_floor is not None else cfg.get("salience_floor", 0.20))

    _init_vector_db()
    conn = _vector_db_connect()
    now = time.time()
    placeholders = ", ".join(["?"] * len(_DECAYABLE_TYPES))
    # Stage 1: fade rows not recalled in `min_age` days. Approximate
    # age via created_at when last_recall_at is 0 (never recalled).
    age_cutoff_seconds = max(0, int(min_age)) * 86400
    fade_sql = (
        f"SELECT id, salience, last_recall_at, created_at FROM memory_entries "
        f"WHERE agent_id = ? AND entry_type IN ({placeholders})"
    )
    rows = conn.execute(fade_sql, [int(agent_id), *_DECAYABLE_TYPES]).fetchall()
    to_fade: list[tuple[float, int]] = []
    to_delete: list[int] = []
    for row_id, salience, last_recall, created_at in rows:
        salience = float(salience or 0.5)
        last_seen = float(last_recall or 0) or float(created_at or now)
        seconds_since_use = max(0.0, now - last_seen)
        if seconds_since_use < age_cutoff_seconds:
            continue
        if salience <= floor:
            to_delete.append(int(row_id))
        else:
            new_salience = max(0.0, salience - max(0.0, float(salience_step)))
            to_fade.append((new_salience, int(row_id)))

    with conn:
        if to_fade:
            conn.executemany(
                "UPDATE memory_entries SET salience = ? WHERE id = ?",
                to_fade,
            )
        if to_delete:
            placeholders_del = ", ".join(["?"] * len(to_delete))
            conn.execute(
                f"DELETE FROM memory_entries WHERE id IN ({placeholders_del})",
                to_delete,
            )
    if to_fade or to_delete:
        _LOG.info(
            "decay_pass agent=%s decayed=%d deleted=%d",
            int(agent_id), len(to_fade), len(to_delete),
        )
    return {"decayed": len(to_fade), "deleted": len(to_delete)}


__all__ = ["decay_pass"]
