"""A tiny background-job store, shared by the playground games that need one.

A game whose round costs dozens of model calls cannot answer a request
inline, so it opens a job, reports progress, and hands the result back when
the caller polls. Disaster mode, the rumor game and the referendum all do
exactly that, and all three had the same forty lines copied into them.

One :class:`JobStore` per game, not one global one: ids are namespaced by
kind, but a shared dict would also mean ``/api/games/disaster/jobs/<id>``
could answer for a rumor job. Separate stores make that impossible rather
than merely unlikely.

:mod:`gaworld.apps.arena_api` keeps its own copy — its jobs carry extra
retain/refill semantics, and rewriting a working panel is not worth the
diff.

A store opened with ``archive=True`` also writes each finished result to
disk (:mod:`gaworld.apps.game_archive`), so the games GAWorld-Bench counts
outlive the process.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from gaworld.accounts import ownership
from gaworld.apps import game_archive
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.game_jobs")

#: Jobs kept per store. Finished ones are dropped first, oldest first, so a
#: long session never grows without bound and a running job is never evicted.
DEFAULT_MAX_JOBS = 20


class JobStore:
    """Jobs for one game: open, update, run in a thread, read back."""

    def __init__(self, kind: str, *, max_jobs: int = DEFAULT_MAX_JOBS, archive: bool = False) -> None:
        self.kind = kind
        self.max_jobs = max_jobs
        self.archive = archive
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def new(self) -> str:
        job_id = f"{self.kind}-{uuid.uuid4().hex[:8]}"
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "kind": self.kind,
                "status": "running",
                "progress": 0.0,
                "message": "启动中…",
                "started_at": time.time(),
                "finished_at": None,
                "result": None,
                "error": None,
                **ownership.stamp(),
            }
            finished = [
                (record["started_at"], key)
                for key, record in self._jobs.items()
                if record["status"] != "running"
            ]
            while len(self._jobs) > self.max_jobs and finished:
                finished.sort()
                _, oldest = finished.pop(0)
                self._jobs.pop(oldest, None)
        return job_id

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is not None:
                record.update(fields)

    def status(self, job_id: str) -> dict[str, Any] | None:
        """The job, or None when it does not exist or is someone else's."""
        with self._lock:
            record = self._jobs.get(job_id)
            return dict(record) if record is not None and ownership.visible(record) else None

    def results(self) -> list[dict[str, Any]]:
        """Every finished job's result, newest first."""
        with self._lock:
            records = [dict(r) for r in self._jobs.values() if ownership.visible(r)]
        rows = [
            (record["id"], record["result"])
            for record in records
            if record["status"] == "done" and record["result"]
        ]
        rows.sort(key=lambda row: -((row[1] or {}).get("created_at") or 0))
        return [{"job_id": job_id, "result": result} for job_id, result in rows]

    def run(self, work: Callable[[Callable[[float, str], None]], Any]) -> str:
        """Open a job and run *work* on a daemon thread.

        *work* is handed a ``progress(fraction, message)`` callback; whatever
        it returns becomes the job's result, and any exception becomes its
        error rather than a dead thread with no trace.
        """
        job_id = self.new()

        def runner() -> None:
            try:
                result = work(lambda p, m: self.update(job_id, progress=p, message=m))
                if self.archive and result:
                    # Before "done", so whoever sees the job finish can find its file.
                    game_archive.save(self.kind, job_id, result)
                self.update(job_id, status="done", progress=1.0, finished_at=time.time(), result=result)
            except Exception as exc:  # pragma: no cover - surfaced via the API
                self.update(
                    job_id,
                    status="failed",
                    finished_at=time.time(),
                    error=f"{type(exc).__name__}: {exc}",
                )
                _LOG.exception("%s job %s failed", self.kind, job_id)

        ownership.spawn(runner, name=f"{self.kind}-{job_id}")
        return job_id

    def reset(self) -> None:
        """Drop every job. Used by tests; production code never calls it."""
        with self._lock:
            self._jobs.clear()


__all__ = ["DEFAULT_MAX_JOBS", "JobStore"]
