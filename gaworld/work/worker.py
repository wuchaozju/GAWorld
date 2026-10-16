"""WorkerPool — drains the WorkQueue in a background daemon thread.

A single foreground thread polls the queue at ``poll_interval`` and
dispatches each pending brief to the adapter pool. Adapters run on a
``ThreadPoolExecutor`` so multiple in-flight LLM calls are possible.

Determinism note
----------------
Adapters MUST NOT touch the global ``random`` state — see
``gaworld/core/runner.py`` rationale. The router/market layer use
local ``random.Random`` instances seeded by (agent_id, sim_day).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Optional

from gaworld.logging_setup import get_logger
from gaworld.work.adapters.base import AdapterContext, WorkAdapter, make_failed
from gaworld.work.queue import WorkQueue
from gaworld.work.schemas import WorkBrief, WorkResult

_LOG = get_logger("gaworld.work.worker")


class WorkerPool:
    """Owns the background drain loop + adapter executor."""

    def __init__(
        self,
        *,
        queue: WorkQueue,
        adapters: dict[str, WorkAdapter],
        ctx_factory,  # callable(adapter_name) -> AdapterContext
        max_workers: int = 2,
        task_timeout_seconds: int = 600,
        poll_interval: float = 1.0,
        brief_hook: Callable[[WorkBrief], WorkBrief] | None = None,
    ) -> None:
        self.queue = queue
        # Runs on the adapter thread right before ``adapter.run`` (e.g. the
        # online skill lookup), so slow preparation never blocks a tick.
        self.brief_hook = brief_hook
        self.adapters = adapters
        self.ctx_factory = ctx_factory
        self.max_workers = max(1, int(max_workers))
        self.task_timeout = max(10, int(task_timeout_seconds))
        self.poll_interval = max(0.05, float(poll_interval))

        self._stop = threading.Event()
        self._drain_thread: Optional[threading.Thread] = None
        self._executor: Optional[ThreadPoolExecutor] = None
        self._inflight: dict[str, Future] = {}
        self._inflight_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._drain_thread and self._drain_thread.is_alive():
            return
        self._stop.clear()
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="real_work_adapter",
        )
        self._drain_thread = threading.Thread(
            target=self._drain_loop,
            name="real_work_drain",
            daemon=True,
        )
        self._drain_thread.start()
        _LOG.info("WorkerPool started (workers=%d, timeout=%ds)", self.max_workers, self.task_timeout)

    def stop(self, wait: bool = True) -> None:
        self._stop.set()
        if self._drain_thread is not None:
            self._drain_thread.join(timeout=5.0 if wait else 0.1)
        if self._executor is not None:
            self._executor.shutdown(wait=wait, cancel_futures=True)
            self._executor = None
        self._drain_thread = None

    # ------------------------------------------------------------------
    # Drain loop
    # ------------------------------------------------------------------
    def _drain_loop(self) -> None:
        while not self._stop.is_set():
            try:
                brief = self.queue.claim_next()
            except Exception as exc:  # noqa: BLE001
                _LOG.exception("queue claim failed: %s", exc)
                self._stop.wait(self.poll_interval)
                continue
            if brief is None:
                self._stop.wait(self.poll_interval)
                self._reap_finished()
                continue
            self._dispatch(brief)
            # After dispatching, also reap any finished work.
            self._reap_finished()

    def _dispatch(self, brief: WorkBrief) -> None:
        adapter = self.adapters.get(brief.adapter)
        if adapter is None:
            self.queue.record_result(make_failed(brief, f"no adapter named {brief.adapter}", time.time()))
            return
        if self._executor is None:
            self.queue.record_result(make_failed(brief, "executor not running", time.time()))
            return
        ctx = self.ctx_factory(brief.adapter)
        fut = self._executor.submit(self._run_adapter, adapter, brief, ctx)
        with self._inflight_lock:
            self._inflight[brief.task_id] = fut

    def _prepare(self, brief: WorkBrief) -> WorkBrief:
        if self.brief_hook is None:
            return brief
        try:
            return self.brief_hook(brief)
        except Exception:  # a failed hook must not cost the work
            _LOG.exception("brief hook failed for task %s", brief.task_id)
            return brief

    def _run_adapter(self, adapter: WorkAdapter, brief: WorkBrief, ctx: AdapterContext) -> WorkResult:
        try:
            return adapter.run(self._prepare(brief), ctx)
        except Exception as exc:  # noqa: BLE001
            _LOG.exception("adapter %s crashed for task %s", adapter.name, brief.task_id)
            return make_failed(brief, f"adapter exception: {exc}", time.time())

    def _reap_finished(self) -> None:
        with self._inflight_lock:
            done_keys: list[str] = []
            for task_id, fut in self._inflight.items():
                if fut.done():
                    done_keys.append(task_id)
            for task_id in done_keys:
                fut = self._inflight.pop(task_id)
                self._consume_future(task_id, fut, timeout=False)
        # Separately, check for futures that have run too long.
        self._enforce_timeouts()

    def _enforce_timeouts(self) -> None:
        now = time.time()
        with self._inflight_lock:
            stale: list[str] = []
            for task_id, fut in self._inflight.items():
                # ThreadPoolExecutor doesn't expose a start time per future,
                # so we rely on the queue's claim timestamp for an upper bound.
                # If the future has been running > timeout, mark it.
                started = fut._claimed_ts if hasattr(fut, "_claimed_ts") else now  # type: ignore[attr-defined]
                if now - started > self.task_timeout:
                    stale.append(task_id)
            for task_id in stale:
                fut = self._inflight.pop(task_id)
                self._consume_future(task_id, fut, timeout=True)

    def _consume_future(self, task_id: str, fut: Future, *, timeout: bool) -> None:
        try:
            if timeout:
                # We can't actually cancel a thread mid-LLM, but we can stop
                # waiting and record a timeout result.
                try:
                    result = fut.result(timeout=0.001)
                except FutureTimeout:
                    self.queue.record_result(WorkResult(
                        task_id=task_id,
                        agent_id=0,  # filled below if possible
                        status="timeout",
                        artifact_paths=[],
                        summary="",
                        error=f"task exceeded {self.task_timeout}s",
                        finished_at=time.time(),
                        duration_seconds=float(self.task_timeout),
                    ))
                    return
            else:
                result = fut.result(timeout=0.001)
        except FutureTimeout:
            return
        except Exception as exc:  # noqa: BLE001
            _LOG.exception("future for %s raised", task_id)
            self.queue.record_result(WorkResult(
                task_id=task_id,
                agent_id=0,
                status="failed",
                artifact_paths=[],
                summary="",
                error=f"future raised: {exc}",
                finished_at=time.time(),
                duration_seconds=0.0,
            ))
            return
        self.queue.record_result(result)

    # ------------------------------------------------------------------
    # Synchronous fallback (used by tests / non-threaded mode)
    # ------------------------------------------------------------------
    def drain_sync(self, max_iterations: int = 64) -> int:
        """Drain pending tasks inline; used in tests and as a sync alternative.

        Returns number of tasks executed.
        """

        executed = 0
        for _ in range(max_iterations):
            brief = self.queue.claim_next()
            if brief is None:
                break
            adapter = self.adapters.get(brief.adapter)
            if adapter is None:
                self.queue.record_result(make_failed(brief, f"no adapter named {brief.adapter}", time.time()))
                executed += 1
                continue
            ctx = self.ctx_factory(brief.adapter)
            try:
                result = adapter.run(self._prepare(brief), ctx)
            except Exception as exc:  # noqa: BLE001
                result = make_failed(brief, f"adapter exception: {exc}", time.time())
            self.queue.record_result(result)
            executed += 1
        return executed


__all__ = ["WorkerPool"]
