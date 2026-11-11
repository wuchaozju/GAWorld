"""Context-scoped, bounded timing samples for one simulation.

Totals cover the collector's lifetime; percentiles describe only the most
recent samples per operation. Timings are inclusive (a stage includes its
model and memory work), so totals across categories must not be added.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, ParamSpec, TypeVar


@dataclass
class _Timing:
    calls: int = 0
    failures: int = 0
    total_ms: float = 0
    max_ms: float = 0
    samples: deque[float] = field(default_factory=deque)


class TimingCollector:
    """Thread-safe totals and a fixed-size recent sample window per label."""

    def __init__(self, sample_limit: int = 512) -> None:
        self.sample_limit = max(1, min(4096, int(sample_limit)))
        self._lock = threading.Lock()
        self._operations: dict[str, _Timing] = {}
        self._started = time.perf_counter()

    def record(self, operation: str, elapsed_ms: float, *, failed: bool = False) -> None:
        elapsed_ms = max(0.0, float(elapsed_ms))
        with self._lock:
            row = self._operations.get(operation)
            if row is None:
                row = _Timing(samples=deque(maxlen=self.sample_limit))
                self._operations[operation] = row
            row.calls += 1
            row.failures += int(failed)
            row.total_ms += elapsed_ms
            row.max_ms = max(row.max_ms, elapsed_ms)
            row.samples.append(elapsed_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            operations = {}
            for name, row in self._operations.items():
                values = sorted(row.samples)
                operations[name] = {
                    "calls": row.calls,
                    "failures": row.failures,
                    "total_ms": row.total_ms,
                    "max_ms": row.max_ms,
                    "sample_count": len(values),
                    "p50_ms": values[math.ceil(len(values) * 0.5) - 1],
                    "p95_ms": values[math.ceil(len(values) * 0.95) - 1],
                }
            return {
                "cumulative": True,
                "elapsed_ms": (time.perf_counter() - self._started) * 1000,
                "percentile_scope": "last_samples",
                "sample_limit": self.sample_limit,
                "operations": operations,
            }


ACTIVE_TIMINGS: ContextVar[TimingCollector | None] = ContextVar("gaworld_timings", default=None)


def record_timing(operation: str, elapsed_ms: float, *, failed: bool = False) -> None:
    collector = ACTIVE_TIMINGS.get()
    if collector is not None:
        collector.record(operation, elapsed_ms, failed=failed)


@contextmanager
def measure(operation: str) -> Iterator[None]:
    collector = ACTIVE_TIMINGS.get()
    if collector is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    except BaseException:
        collector.record(operation, (time.perf_counter() - started) * 1000, failed=True)
        raise
    else:
        collector.record(operation, (time.perf_counter() - started) * 1000)


_P = ParamSpec("_P")
_R = TypeVar("_R")


def isolate_timings(fn: Callable[_P, _R]) -> Callable[_P, _R]:
    """Isolate run entry/exit even when failure skips normal plugin teardown."""

    @wraps(fn)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        token = ACTIVE_TIMINGS.set(None)
        try:
            return fn(*args, **kwargs)
        finally:
            ACTIVE_TIMINGS.reset(token)

    return wrapped


def timed(operation: str) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    def decorate(fn: Callable[_P, _R]) -> Callable[_P, _R]:
        @wraps(fn)
        def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            with measure(operation):
                return fn(*args, **kwargs)

        return wrapped

    return decorate
