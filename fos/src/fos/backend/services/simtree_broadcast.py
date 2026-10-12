"""Tree event broadcasting helpers."""

from __future__ import annotations

import logging

from fos.backend.core.timing import log_event
from fos.backend.services.simtree_registry_lifecycle import SimTreeRecord


logger = logging.getLogger(__name__)


def broadcast_tree_event(
    record: SimTreeRecord,
    event: dict,
) -> None:
    """Broadcast an event to all tree-level subscribers."""
    event_type = event.get("type", "unknown")
    for queue in list(record.subs):
        try:
            queue.put_nowait(event)
        except Exception:
            logger.exception("failed to enqueue tree-level broadcast event")
    log_event("WS", event="broadcast", type=event_type, clients=len(record.subs))
