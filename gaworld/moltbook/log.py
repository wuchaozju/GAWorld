"""The per-agent record of what a resident did on Moltbook.

``output/moltbook/agent_<id>/actions.jsonl``, append-only. One line per call
that reached Moltbook — or tried to: failures are rows too, with ``ok: false``,
because "the post was refused" is as much a part of the record as the post.

Row shape::

    {"ts": 1758000000.0, "agent_id": 2, "day": 3, "time": "23:30",
     "kind": "post", "ok": true, "summary": "第 3 天：…", "detail": {...}}

``kind`` is one of :data:`KINDS`. The workbench renders ``summary``; ``detail``
carries the ids and bodies for anyone reading the file directly.
"""

from __future__ import annotations

import json
import os
import threading
import time

DEFAULT_DIR = "output/moltbook"

KINDS = ("register", "status", "post", "comment", "upvote", "feed", "verify", "error")

_LOCK = threading.RLock()


def agent_dir(agent_id, root=DEFAULT_DIR):
    return os.path.join(str(root), f"agent_{int(agent_id)}")


def path_for(agent_id, root=DEFAULT_DIR):
    return os.path.join(agent_dir(agent_id, root=root), "actions.jsonl")


def append(agent_id, record, root=DEFAULT_DIR):
    row = dict(record)
    row["agent_id"] = int(agent_id)
    row.setdefault("ts", time.time())
    row.setdefault("ok", True)
    row.setdefault("detail", {})
    path = path_for(agent_id, root=root)
    with _LOCK:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return row


def load(agent_id, root=DEFAULT_DIR):
    """Every row in file order. A truncated line is skipped, not fatal."""
    path = path_for(agent_id, root=root)
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def recent(agent_id, limit=20, root=DEFAULT_DIR):
    """The newest ``limit`` rows, newest first."""
    rows = load(agent_id, root=root)
    tail = rows[-int(limit):] if limit else rows
    return list(reversed(tail))
