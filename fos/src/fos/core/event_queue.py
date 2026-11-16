"""Event queue for buffering and managing external events.

Provides thread-safe event storage with deduplication and filtering.
"""

from collections import deque
from datetime import datetime, timedelta
from typing import Optional

from fos.core.external_event import ExternalEvent, EventFilter


class EventQueue:
    """Thread-safe event queue with deduplication and filtering."""

    def __init__(self, max_size: int = 1000, dedup_window_hours: int = 24) -> None:
        """Initialize the event queue.

        Args:
            max_size: Maximum number of events to store.
            dedup_window_hours: Time window for deduplication (hours).
        """
        self._queue: deque[ExternalEvent] = deque()
        self._max_size = max_size
        self._seen_ids: set[str] = set()
        self._dedup_window = timedelta(hours=dedup_window_hours)

    def enqueue(self, event: ExternalEvent) -> bool:
        """Add an event to the queue.

        Args:
            event: The ExternalEvent to add.

        Returns:
            True if event was added, False if duplicate.
        """
        if event.id in self._seen_ids:
            return False

        # Remove oldest if at capacity
        while len(self._queue) >= self._max_size:
            oldest = self._queue.popleft()
            self._seen_ids.discard(oldest.id)

        self._queue.append(event)
        self._seen_ids.add(event.id)
        return True

    def dequeue(self) -> Optional[ExternalEvent]:
        """Remove and return the oldest event.

        Returns:
            The oldest event, or None if queue is empty.
        """
        if not self._queue:
            return None
        event = self._queue.popleft()
        self._seen_ids.discard(event.id)
        return event

    def peek(self) -> Optional[ExternalEvent]:
        """View the oldest event without removing it.

        Returns:
            The oldest event, or None if queue is empty.
        """
        if not self._queue:
            return None
        return self._queue[0]

    def get_pending(self, limit: Optional[int] = None) -> list[ExternalEvent]:
        """Get all pending events without removing them.

        Args:
            limit: Maximum number of events to return.

        Returns:
            List of pending events.
        """
        events = list(self._queue)
        if limit:
            return events[:limit]
        return events

    def get_by_filter(self, filter_def: EventFilter) -> list[ExternalEvent]:
        """Get events matching the given filter.

        Args:
            filter_def: EventFilter criteria.

        Returns:
            List of matching events.
        """
        return [e for e in self._queue if filter_def.matches(e)]

    def size(self) -> int:
        """Return the number of events in the queue."""
        return len(self._queue)

    def is_empty(self) -> bool:
        """Check if the queue is empty."""
        return len(self._queue) == 0

    def clear(self) -> None:
        """Remove all events from the queue."""
        self._queue.clear()
        self._seen_ids.clear()

    def cleanup_old_events(self, max_age_hours: int = 24) -> int:
        """Remove events older than max_age_hours.

        Args:
            max_age_hours: Maximum age of events to keep.

        Returns:
            Number of events removed.
        """
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        removed = 0

        while self._queue and self._queue[0].timestamp < cutoff:
            event = self._queue.popleft()
            self._seen_ids.discard(event.id)
            removed += 1

        return removed
