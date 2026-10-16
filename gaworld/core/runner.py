"""Concurrency primitives for the simulator.

Why this exists
---------------
Many per-agent stages of the main loop are pure-IO (LLM calls or
network requests) and therefore embarrassingly parallel within a
single tick. The main file currently runs them serially, so a daily
schedule generation across N agents does N round-trips back-to-back.

This module provides a tiny, opt-in concurrency primitive:

* :func:`parallel_map` runs ``fn(item)`` over a sequence and returns
  the results **in the original input order**. With
  ``max_workers <= 1`` it falls back to a serial loop and never spawns
  a thread pool — important because:

  - the legacy code is full of ``random.random()`` calls, and
    introducing a pool by default would silently break experiment
    reproducibility under ``random_seed``;
  - it makes the migration risk-free: callers that opt in get
    concurrency, others see exactly the old behaviour.

* :func:`resolve_max_workers` reads ``CONFIG["concurrency"]`` so all
  callers consult the same place.

Reproducibility
---------------
When ``max_workers > 1`` the global :mod:`random` state can be
consumed in a non-deterministic order. Tests that need determinism
should either keep the default ``max_workers=1`` or use a per-thread
:class:`random.Random` instance.

Failure semantics
-----------------
``parallel_map`` re-raises the first exception observed. Already
running tasks are allowed to finish (they cannot be cancelled cleanly
once they're inside :mod:`requests`), but their results are dropped.
"""

from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable, Mapping, Sequence, TypeVar

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.core.runner")

T = TypeVar("T")
R = TypeVar("R")


def parallel_map(
    fn: Callable[[T], R],
    items: Sequence[T] | Iterable[T],
    *,
    max_workers: int = 1,
    label: str = "",
) -> list[R]:
    """Apply ``fn`` to each element of ``items`` and return results in order.

    Parameters
    ----------
    fn:
        Callable that accepts one item and returns a result. Must be
        thread-safe with respect to whatever shared state it touches —
        the caller is responsible for making sure ``fn`` only writes
        to per-item slots.
    items:
        Sequence of inputs. Iterables are materialised into a list so
        we can index by position when reordering results.
    max_workers:
        Maximum number of worker threads. Values ``<= 1`` short-circuit
        to a serial loop with no executor created — this keeps the
        legacy ``random``-driven code paths fully deterministic.
    label:
        Optional human-readable tag for log lines (e.g. ``"day_routine"``).
    """
    materialised = list(items)
    n = len(materialised)
    if n == 0:
        return []
    if max_workers <= 1 or n == 1:
        if label:
            _LOG.debug("parallel_map(%s) serial n=%d", label, n)
        return [fn(item) for item in materialised]

    workers = min(max_workers, n)
    if label:
        _LOG.info("parallel_map(%s) parallel n=%d workers=%d", label, n, workers)

    results: list[R | None] = [None] * n
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(contextvars.copy_context().run, fn, item): index
                   for index, item in enumerate(materialised)}
        for future in futures:
            index = futures[future]
            # ``result()`` re-raises whatever fn raised; the executor's
            # context manager will then drain the remaining futures.
            results[index] = future.result()
    # mypy: at this point every slot has been written.
    return [r for r in results]  # type: ignore[misc]


def resolve_max_workers(
    cfg: Mapping[str, Any] | None,
    *,
    key: str,
    default: int = 1,
) -> int:
    """Read ``cfg["concurrency"][key]`` with safe defaults.

    Returns ``1`` when concurrency is disabled, the key is missing, or
    the value cannot be coerced. Negative values are clamped to ``1``.
    """
    if not isinstance(cfg, Mapping):
        return max(1, int(default))
    block = cfg.get("concurrency")
    if not isinstance(block, Mapping):
        return max(1, int(default))
    if not bool(block.get("enabled", True)):
        return 1
    raw = block.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return max(1, int(default))
    return max(1, value)


__all__ = ["parallel_map", "resolve_max_workers"]
