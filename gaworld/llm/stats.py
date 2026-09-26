"""Thread-safe LLM call statistics collector.

Purpose
-------
The router in :mod:`gaworld.llm.providers` already logs each call in
detail. That's great for postmortems but no good for run-level
summaries — grepping 200k log lines to answer "how many calls did
this run make?" is the opposite of what a manifest should require.

:class:`LLMCallStats` maintains rolling counters that the run manifest
folds in at end-of-run. It is intentionally minimal:

* zero external dependencies,
* zero cost when nothing is asking,
* thread-safe (the same lock protects every field),
* resettable so long-running processes can bracket sub-runs.

The global instance :data:`GLOBAL_STATS` is what the router uses; tests
that want isolation should instantiate their own :class:`LLMCallStats`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Bucket:
    calls: int = 0
    failures: int = 0
    total_latency_ms: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "failures": self.failures,
            "total_latency_ms": self.total_latency_ms,
        }


class LLMCallStats:
    """Rolling counters aggregated by task and provider."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._call_count = 0
        self._failure_count = 0
        self._total_latency_ms = 0
        self._by_task: dict[str, _Bucket] = {}
        self._by_provider: dict[str, _Bucket] = {}
        # Task boundary — set when the enclosing run/experiment starts,
        # so the manifest can distinguish a run's calls from any that
        # occurred before it (rare, but possible with dashboard).
        self._started_at_call: int = 0

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        *,
        task: str,
        provider: str,
        latency_ms: int,
        ok: bool,
    ) -> None:
        with self._lock:
            self._call_count += 1
            self._total_latency_ms += max(0, int(latency_ms))
            if not ok:
                self._failure_count += 1
            self._bucket(self._by_task, task or "").calls += 1
            if not ok:
                self._bucket(self._by_task, task or "").failures += 1
            self._bucket(self._by_task, task or "").total_latency_ms += max(0, int(latency_ms))
            self._bucket(self._by_provider, provider or "").calls += 1
            if not ok:
                self._bucket(self._by_provider, provider or "").failures += 1
            self._bucket(self._by_provider, provider or "").total_latency_ms += max(0, int(latency_ms))

    @staticmethod
    def _bucket(store: dict[str, _Bucket], key: str) -> _Bucket:
        if key not in store:
            store[key] = _Bucket()
        return store[key]

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe view of the current counters."""
        with self._lock:
            calls_in_run = self._call_count - self._started_at_call
            return {
                "call_count": self._call_count,
                "calls_in_run": max(0, calls_in_run),
                "failure_count": self._failure_count,
                "total_latency_ms": self._total_latency_ms,
                "avg_latency_ms": int(
                    self._total_latency_ms / self._call_count
                ) if self._call_count else 0,
                "by_task": {k: v.to_dict() for k, v in self._by_task.items()},
                "by_provider": {k: v.to_dict() for k, v in self._by_provider.items()},
            }

    def mark_run_start(self) -> None:
        """Remember the current call count as the run's baseline.

        Useful when the process has already made calls (e.g. a
        dashboard warmup) before the run begins.
        """
        with self._lock:
            self._started_at_call = self._call_count

    def reset(self) -> None:
        with self._lock:
            self._call_count = 0
            self._failure_count = 0
            self._total_latency_ms = 0
            self._by_task.clear()
            self._by_provider.clear()
            self._started_at_call = 0


# Process-wide instance the router uses. Tests should build their own.
GLOBAL_STATS = LLMCallStats()


__all__ = ["GLOBAL_STATS", "LLMCallStats"]
