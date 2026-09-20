"""Periodic memory consolidation.

Episodic memories (everyday entries: ``memory``, ``diary``, ``news``,
``info_seek``, ``web_search``) accumulate quickly. Without periodic
distillation, retrieval drowns in same-day chatter and the agent never
forms longer-lived "心得" — the bit a real person would actually carry
around weeks later.

:func:`consolidate_recent` asks the LLM to summarise the last few days'
salient episodic entries into 1–N ``semantic`` rows, written back to
the same vector DB. The new rows start with elevated salience so
future retrieval prefers them over the raw incidents they came from.

This module is deliberately decoupled from the simulator loop. The
caller (task #8: day-tick hook in ``generative_city_sim.py``) decides
*when* to invoke it; this file only knows *how*.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from gaworld.settings import CONFIG
from gaworld.logging_setup import get_logger
from gaworld.memory.store import (
    _init_vector_db,
    _vector_db_connect,
    vector_db_add_entry,
)

_LOG = get_logger("gaworld.memory.consolidation")

# Entry types considered "episodic" for the purpose of consolidation.
# We exclude `semantic` (already consolidated) and `external_info`
# (background knowledge that does not need re-summarising).
_EPISODIC_TYPES = ("memory", "diary", "news", "info_seek", "web_search")

_PROMPT = """你是城市模拟器的记忆整合器。请把下列同一个角色最近的若干条
情景记忆，合并成 {max_outputs} 条以内的"长期心得 / 经验总结"。

要求：
1) 每条 30-90 字中文，凝练但保留为什么对该角色重要。
2) 不要照抄原文；要提炼模式、情绪基调、对未来选择的提示。
3) 仅输出 JSON 数组，每项一个字符串。不要其他文字。

最近的情景记忆：
{episodes}
"""


def _consolidation_config() -> dict[str, Any]:
    return (CONFIG.get("memory", {}) or {}).get("consolidation", {}) or {}


def fetch_recent_episodes(
    agent_id: int,
    *,
    lookback_days: int = 3,
    today: int | None = None,
    max_rows: int = 20,
) -> list[dict[str, Any]]:
    """Return recent episodic entries for an agent, newest first.

    ``today`` is the simulator's current ``sim_day``; entries older
    than ``today - lookback_days`` are excluded. When ``today`` is
    None, falls back to a recency cap via ``ORDER BY created_at``.
    Only entries with the episodic ``entry_type`` set are returned.
    """
    _init_vector_db()
    conn = _vector_db_connect()
    placeholders = ", ".join(["?"] * len(_EPISODIC_TYPES))
    params: list[Any] = [int(agent_id), *_EPISODIC_TYPES]
    where = f"agent_id = ? AND entry_type IN ({placeholders})"
    if today is not None:
        where += " AND (sim_day IS NULL OR sim_day >= ?)"
        params.append(int(today) - max(0, int(lookback_days)))
    sql = (
        "SELECT id, entry_type, text, sim_day, sim_time, salience, recall_count "
        f"FROM memory_entries WHERE {where} "
        "ORDER BY COALESCE(sim_day, -1) DESC, created_at DESC "
        "LIMIT ?"
    )
    params.append(int(max_rows))
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "id": r[0],
            "entry_type": r[1],
            "text": r[2],
            "sim_day": r[3],
            "sim_time": r[4],
            "salience": float(r[5] or 0.5),
            "recall_count": int(r[6] or 0),
        }
        for r in rows
    ]


def _parse_consolidation_response(text: str, max_outputs: int) -> list[str]:
    if not isinstance(text, str):
        return []
    cleaned = text.strip()
    if not cleaned:
        return []
    # Find first JSON array in the response (LLMs sometimes wrap it).
    match = re.search(r"\[.*\]", cleaned, re.S)
    if match:
        cleaned = match.group(0)
    try:
        raw = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            line = item.strip()
        elif isinstance(item, dict):
            line = ""
            for key in ("text", "memory", "summary", "content"):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    line = val.strip()
                    break
        else:
            line = ""
        if line:
            out.append(line)
        if len(out) >= max(1, int(max_outputs)):
            break
    return out


def consolidate_recent(
    agent: dict[str, Any],
    *,
    llm: Callable[[str], str],
    today: int | None = None,
    lookback_days: int | None = None,
    max_outputs: int | None = None,
    sim_time: str | None = "consolidation",
) -> list[str]:
    """Distill recent episodic memories into a few ``semantic`` rows.

    Returns the list of consolidated strings actually written. The
    function is a no-op (returns ``[]``) when consolidation is
    disabled, when there are too few episodes to consolidate, or when
    the LLM returns no parseable output.

    Behavior is intentionally gentle: each new ``semantic`` row enters
    the DB with elevated salience (0.80) so it ranks above the raw
    incidents that produced it on the next recall pass.
    """
    cfg = _consolidation_config()
    if not cfg.get("enabled", False):
        return []
    if not isinstance(agent, dict):
        return []
    agent_id = int(agent.get("id", 0) or 0)
    if not agent_id:
        return []

    lookback = int(lookback_days if lookback_days is not None else cfg.get("lookback_days", 3))
    max_out = int(max_outputs if max_outputs is not None else cfg.get("max_outputs", 3))
    episodes = fetch_recent_episodes(
        agent_id, lookback_days=lookback, today=today, max_rows=max(8, max_out * 5)
    )
    if len(episodes) < 3:
        # Not enough material to be worth consolidating.
        return []

    bullets = []
    for ep in episodes:
        sim_day = ep.get("sim_day")
        sim_time_str = ep.get("sim_time") or ""
        prefix = f"(D{sim_day} {sim_time_str})" if sim_day is not None else f"({sim_time_str})"
        bullets.append(f"- {prefix} {ep['text']}")
    prompt = _PROMPT.format(max_outputs=max_out, episodes="\n".join(bullets))

    try:
        raw = llm(prompt)
    except Exception as exc:
        _LOG.warning("consolidate_recent LLM call failed for agent %s: %s", agent_id, exc)
        return []
    summaries = _parse_consolidation_response(raw, max_outputs=max_out)
    if not summaries:
        return []

    written: list[str] = []
    for line in summaries:
        vector_db_add_entry(
            agent_id,
            "semantic",
            line,
            sim_day=today,
            sim_time=sim_time,
            salience=0.80,
        )
        written.append(line)
    _LOG.info("consolidated %d semantic memories for agent %s", len(written), agent_id)
    return written


__all__ = [
    "consolidate_recent",
    "fetch_recent_episodes",
]
