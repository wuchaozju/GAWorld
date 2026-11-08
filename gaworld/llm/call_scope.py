"""Opt-in waiting budgets for research document calls, isolated by context."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from typing import Any

_DEADLINE: ContextVar[float | None] = ContextVar("model_wait_deadline", default=None)
# At most four document I/O workers may outlive their caller. A remote request
# cannot always be cancelled; expired workers cannot retry, publish or save.
_SLOTS = threading.BoundedSemaphore(4)


class ModelWaitTimeout(RuntimeError):
    """The document call exceeded its waiting budget; do not retry it."""


def check() -> float | None:
    deadline = _DEADLINE.get()
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ModelWaitTimeout("模型等待超时；已保存的方案和统计结果仍保留，可稍后重试。")
    return remaining


def request_timeout(configured: Any) -> Any:
    remaining = check()
    if remaining is None:
        return configured
    connect, read = configured if isinstance(configured, tuple) else (10, configured)
    return (min(float(connect or 10), remaining), min(float(read or remaining), remaining))


def bounded_call(call: Callable[[], Any]) -> Any:
    """Bound the caller's wall time even when a server trickles response bytes.

    Only pure model I/O runs here. Persistence stays on the caller, so a late
    answer is discarded after timeout. Request/user/ledger context is copied.
    Workers are bounded because closing a requests body from another thread
    does not reliably interrupt an in-flight socket read.
    """
    remaining = check()
    if remaining is None:
        return call()
    if not _SLOTS.acquire(timeout=remaining):
        raise ModelWaitTimeout("模型等待超时；其他模型请求尚未结束，请稍后重试。")
    context = copy_context()
    future: Future[Any] = Future()

    def worker() -> None:
        try:
            result = context.run(call)
            future.set_result(result)
        except BaseException as exc:
            future.set_exception(exc)
        finally:
            _SLOTS.release()

    thread = threading.Thread(target=worker, name="research-model-io", daemon=True)
    try:
        check()
        thread.start()
    except BaseException:
        _SLOTS.release()
        raise
    try:
        return future.result(timeout=check())
    except FutureTimeout as exc:
        raise ModelWaitTimeout("模型等待超时；已有统计结果仍保留，迟到的回答不会覆盖结果。") from exc


@contextmanager
def limit(seconds: float) -> Iterator[None]:
    deadline = time.monotonic() + seconds
    parent = _DEADLINE.get()
    token = _DEADLINE.set(min(deadline, parent) if parent is not None else deadline)
    try:
        yield
        check()
    finally:
        _DEADLINE.reset(token)
