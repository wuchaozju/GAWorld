"""Monotonic active time and a deliberately approximate progress-based ETA.

The job owner's lock protects this object. Paused time never changes the
estimate, and terminal jobs retain their elapsed time without an ETA.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class RunTiming:
    def __init__(
        self, *, clock: Callable[[], float] = time.monotonic, wall_clock: Callable[[], float] = time.time
    ) -> None:
        self._clock = clock
        self._wall_clock = wall_clock
        self._wall_started = wall_clock()
        self._wall_finished: float | None = None
        self._started = clock()
        self._paused_at: float | None = None
        self._paused_seconds = 0.0
        self._finished_at: float | None = None

    def set_paused(self, paused: bool) -> None:
        if self._finished_at is not None:
            return
        if paused and self._paused_at is None:
            self._paused_at = self._clock()
        elif not paused and self._paused_at is not None:
            self._paused_seconds += self._clock() - self._paused_at
            self._paused_at = None

    def finish(self) -> None:
        if self._finished_at is None:
            self.set_paused(False)
            self._finished_at = self._clock()
            self._wall_finished = self._wall_clock()

    def snapshot(self, progress: float) -> dict[str, float | None]:
        now = self._finished_at if self._finished_at is not None else self._clock()
        held = now - self._paused_at if self._paused_at is not None else 0.0
        elapsed = max(0.0, now - self._started - self._paused_seconds - held)
        remaining = None
        if self._finished_at is None and elapsed >= 5 and 0.01 <= progress < 1:
            remaining = elapsed * (1 - progress) / progress
        return {
            "elapsed_seconds": elapsed,
            "remaining_seconds": remaining,
            "paused_seconds": self._paused_seconds + held,
            "wall_seconds": max(
                0.0,
                (self._wall_finished if self._wall_finished is not None else self._wall_clock())
                - self._wall_started,
            ),
        }
