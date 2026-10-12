"""Lifecycle helpers for cached SimTree records."""

from __future__ import annotations

import asyncio
import logging
import time

from fos.core.simtree import SimTree


class SimTreeRecord:
    def __init__(self, tree: SimTree):
        self.tree = tree
        now = time.monotonic()
        self.created_at = now
        self.last_accessed_at = now
        self.subs: list[asyncio.Queue] = []
        self.running: set[int] = set()
        self._suggestions_viewed_intervals: set[int] = set()
        self._advance_lock: asyncio.Lock = asyncio.Lock()

    def replace_tree(self, tree: SimTree) -> None:
        self.cleanup_runtime_resources()
        self.tree = tree
        self.touch()

    def touch(self) -> None:
        self.last_accessed_at = time.monotonic()

    def is_idle(self, idle_ttl_seconds: float, now: float | None = None) -> bool:
        current_time = now if now is not None else time.monotonic()
        return (
            not self.running
            and not self.subs
            and current_time - self.last_accessed_at >= idle_ttl_seconds
        )

    def cleanup_runtime_resources(self) -> None:
        cleanup = getattr(self.tree, "cleanup_runtime_resources", None)
        if cleanup is not None:
            cleanup()


def wire_tree_broadcast(
    record: SimTreeRecord,
    tree: SimTree,
    loop: asyncio.AbstractEventLoop,
    logger: logging.Logger,
) -> None:
    """Attach event-loop fanout for running-node tree events."""
    tree.attach_event_loop(loop)

    def _fanout(event: dict) -> None:
        if int(event.get("node", -1)) not in record.running:
            return
        for q in list(record.subs):
            try:
                loop.call_soon_threadsafe(q.put_nowait, event)
            except Exception:
                logger.exception("failed to fanout event to tree subscriber")

    tree.set_tree_broadcast(_fanout)
