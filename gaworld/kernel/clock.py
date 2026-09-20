"""Deterministic simulation clock (Agent-Kernel "Timer" counterpart).

The main loop is the only writer; plugins and cognition stages read the
current day / time from here instead of threading ``day``/``time_str``
arguments through every call.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Clock:
    """Current simulation time. Advanced exclusively by the main loop."""

    day: int = 0
    time_str: str = ""
    tick_index: int = -1
    minutes_per_tick: int | None = None

    def start_day(self, day: int) -> None:
        self.day = int(day)
        self.tick_index = -1
        self.time_str = ""

    def advance(self, time_str: str, tick_index: int) -> None:
        self.time_str = str(time_str)
        self.tick_index = int(tick_index)

    def snapshot(self) -> dict:
        return {
            "day": self.day,
            "time_str": self.time_str,
            "tick_index": self.tick_index,
        }
