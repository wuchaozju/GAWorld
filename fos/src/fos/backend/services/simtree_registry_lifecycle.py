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
        # Per-parent in-flight advance claims (request-level idempotency):
        # a duplicate Advance on the same parent gets an immediate 409
        # instead of silently queueing on _advance_lock and creating a
        # duplicate sibling child. Independent parents advance in parallel.
        self.advancing_parents: set[int] = set()
        self.advance_claim_lock: asyncio.Lock = asyncio.Lock()

    async def claim_advance_parent(self, parent_id: int) -> bool:
        """Atomically claim an in-flight advance on ``parent_id``.

        The lock is held ONLY for the bookkeeping check-and-set — never
        during the simulation run itself. Returns False when the parent is
        already advancing (caller answers 409).
        """
        async with self.advance_claim_lock:
            if parent_id in self.advancing_parents:
                return False
            self.advancing_parents.add(parent_id)
            return True

    def release_advance_parent(self, parent_id: int) -> None:
        """Release a per-parent advance claim (idempotent). Must be called
        on every exit path: success, provider/subprocess failure, timeout,
        cancel, unexpected exception."""
        self.advancing_parents.discard(parent_id)

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
