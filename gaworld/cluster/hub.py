"""The hub's in-memory state for each distributed world.

Everything here is about the current run and is rebuilt when the world starts
again: the relay (residents' cross-machine messages), each node's intervention
outbox, the nodes' heartbeats and the tick-sync table. The node list itself is
on disk (:mod:`gaworld.cluster.nodes`).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

from gaworld.apps.distributed_comm_server import DistributedRelayBackend
from gaworld.cluster.nodes import HUB

#: A node whose process has not sent a heartbeat for this long is offline:
#: tick sync stops waiting for it.
LIVE_SECONDS = 30.0
MAX_MESSAGES = 5000
_TABLE_RE = re.compile(r"[^A-Za-z0-9._-]+")
#: Tables only the hub writes; a node cannot add rows to them.
HUB_TABLES = ("multiplayer.presence",)


def _minutes(time_str: Any) -> int:
    try:
        hours, minutes = str(time_str).split(":", 1)
        return int(hours) * 60 + int(minutes[:2])
    except (TypeError, ValueError):
        return 0


class WorldHub:
    def __init__(self, world_id: str):
        self.world_id = world_id
        self.lock = threading.RLock()
        self.run_id = ""
        #: node id -> resident ids, as split when the current run started
        self.plan: dict[str, list[int]] = {}
        self.relay = DistributedRelayBackend(state_path="", max_messages=MAX_MESSAGES)
        self.outbox: dict[str, list[dict[str, Any]]] = {}
        self.status: dict[str, dict[str, Any]] = {}
        self.progress: dict[str, tuple[int, int, str]] = {}

    # -- runs ---------------------------------------------------------------

    def start_run(self, run_id: str, plan: dict[str, list[int]] | None = None) -> None:
        """A new run of the world: forget the last one's messages, actions and clock."""
        with self.lock:
            self.run_id = run_id
            self.plan = {key: list(value) for key, value in (plan or {}).items()}
            self.relay = DistributedRelayBackend(state_path="", max_messages=MAX_MESSAGES)
            self.outbox = {}
            self.progress = {}

    def end_run(self) -> None:
        with self.lock:
            self.run_id = ""
            self.plan = {}
            self.outbox = {}
            self.progress = {}

    # -- nodes --------------------------------------------------------------

    def heartbeat(self, node_id: str, payload: dict[str, Any]) -> None:
        with self.lock:
            self.status[node_id] = {
                "state": str(payload.get("state") or "idle")[:20],
                "run_id": str(payload.get("run_id") or ""),
                "error": str(payload.get("error") or "")[:500],
                "log_tail": str(payload.get("log_tail") or "")[-2000:],
                "seen": time.time(),
            }

    def running_here(self, node_id: str) -> bool:
        """The node's process says it is running this run, and said so recently."""
        with self.lock:
            status = self.status.get(node_id)
            return bool(
                self.run_id
                and status
                and status["state"] == "running"
                and status["run_id"] == self.run_id
                and time.time() - status["seen"] < LIVE_SECONDS
            )

    def view(self, node_id: str) -> dict[str, Any]:
        """A node's status for the owner's panel."""
        with self.lock:
            status = dict(self.status.get(node_id) or {})
            position = self.progress.get(node_id)
        seen = status.get("seen")
        return {
            "online": bool(seen and time.time() - seen < LIVE_SECONDS),
            "state": status.get("state", "offline"),
            "error": status.get("error", ""),
            "log_tail": status.get("log_tail", ""),
            "seen": seen,
            "sim_day": position[0] if position else None,
            "sim_time": position[2] if position else None,
        }

    # -- interventions -----------------------------------------------------

    def push(self, node_id: str, name: str, kwargs: dict[str, Any]) -> None:
        with self.lock:
            self.outbox.setdefault(node_id, []).append(
                {"name": name, "kwargs": dict(kwargs), "at": time.time()}
            )

    def take(self, node_id: str) -> list[dict[str, Any]]:
        with self.lock:
            return self.outbox.pop(node_id, [])

    # -- tick sync ---------------------------------------------------------

    def sync(self, node_id: str, run_id: str, day: Any, time_str: Any, hub_alive: bool) -> dict[str, Any]:
        """Record where *node_id* is; ``go`` once no live participant is behind it.

        Participants are the hub (while its run is alive) and every node whose
        process is running this run. One that has not reported a position yet
        is still starting up and counts as behind; the caller's timeout keeps
        a slow or vanished machine from holding the world.
        """
        try:
            mine = (int(day), _minutes(time_str))
        except (TypeError, ValueError):
            raise ValueError("day / time 不对") from None
        with self.lock:
            if not self.run_id or run_id != self.run_id:
                return {"go": True, "waiting_for": [], "stale": True}
            self.progress[node_id] = (mine[0], mine[1], str(time_str))
            others = {nid for nid in self.status if nid not in (node_id, HUB) and self.running_here(nid)}
            if hub_alive and node_id != HUB:
                others.add(HUB)
            behind = []
            for nid in others:
                position = self.progress.get(nid)
                if position is None or (position[0], position[1]) < mine:
                    behind.append(nid)
        return {"go": not behind, "waiting_for": sorted(behind)}

    # -- records ------------------------------------------------------------

    def append_records(self, records_dir: str, node_id: str, tables: dict[str, Any]) -> int:
        """Append a node's Recorder rows to the world's stream, tagged with the node."""
        written = 0
        os.makedirs(records_dir, exist_ok=True)
        for table, rows in (tables or {}).items():
            name = _TABLE_RE.sub("_", str(table)).strip("._")
            if not name or name.startswith(HUB_TABLES) or not isinstance(rows, list):
                continue
            lines = []
            for row in rows:
                if isinstance(row, dict):
                    lines.append(json.dumps({**row, "_node": node_id}, ensure_ascii=False, default=str))
            if not lines:
                continue
            with self.lock, open(os.path.join(records_dir, f"{name}.jsonl"), "a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
            written += len(lines)
        return written


_HUBS: dict[str, WorldHub] = {}
_HUBS_LOCK = threading.Lock()


def get(world_id: str) -> WorldHub:
    with _HUBS_LOCK:
        hub = _HUBS.get(world_id)
        if hub is None:
            hub = _HUBS[world_id] = WorldHub(world_id)
        return hub


def reset() -> None:
    """Forget every world's hub state. Used by tests."""
    with _HUBS_LOCK:
        _HUBS.clear()


__all__ = ["HUB_TABLES", "LIVE_SECONDS", "WorldHub", "get", "reset"]
