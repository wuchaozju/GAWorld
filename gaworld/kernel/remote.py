"""Cross-process intervention queue: dashboard → running simulator.

The dashboard launches the simulator as a subprocess, so it cannot call
``ctx.controller.intervene`` directly. This module is the one channel:

- the simulator :func:`publish`\\ es a manifest at start (pid + the names of
  every intervention the kernel and plugins registered), so the HTTP side can
  validate a name without importing a single plugin;
- the HTTP side :func:`enqueue`\\ s requests;
- the simulator :func:`drain`\\ s them at every day boundary and every tick,
  through ``controller.intervene`` — so each one is audited to the
  ``controller.intervention`` record table exactly like an in-process call.

Every read-modify-write holds an ``fcntl`` lock on a sidecar file: both
processes rewrite the same JSON, and without the lock an enqueue landing
between the simulator's read and write would be silently dropped.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import time
import uuid
from typing import Any

DEFAULT_PATH = os.path.join("output", "kernel", "interventions.json")
_APPLIED_KEEP = 100


def path_for(config: dict | None) -> str:
    """Queue file for a run. Parallel worlds override it per world, otherwise
    concurrent worlds would overwrite each other's manifest."""
    return str(((config or {}).get("kernel") or {}).get("interventions_path") or DEFAULT_PATH)


@contextlib.contextmanager
def _locked(path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def read(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("registered", [])
    data.setdefault("pending", [])
    data.setdefault("applied", [])
    return data


def _write(path: str, data: dict[str, Any]) -> None:
    data["applied"] = list(data.get("applied", []))[-_APPLIED_KEEP:]
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)


def is_running(data: dict[str, Any]) -> bool:
    """A manifest is live only while its simulator process still exists.

    Checking the pid (not just the ``active`` flag) keeps a crashed run from
    accepting requests that nothing will ever apply.
    """
    pid = data.get("pid")
    if not data.get("active") or not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# -- simulator side ----------------------------------------------------------


def publish(ctx, path: str | None = None) -> None:
    """Announce a new run. Pending requests left by an earlier run are dropped:
    they were aimed at a different population and clock."""
    path = path or path_for(ctx.config)
    with _locked(path):
        data = read(path)
        data.update(
            active=True,
            pid=os.getpid(),
            started_at=time.time(),
            registered=ctx.controller.intervention_names(),
            pending=[],
        )
        _write(path, data)


def close(ctx, path: str | None = None) -> None:
    path = path or path_for(ctx.config)
    with _locked(path):
        data = read(path)
        data["active"] = False
        _write(path, data)


def drain(ctx, path: str | None = None) -> int:
    """Apply every queued request; returns how many were taken.

    Called every tick, so it only takes the lock when there is work: a pending
    request, or an intervention a plugin registered after :func:`publish`
    (some, like the twin's, register lazily on their first tick). An unlocked
    peek is safe — a request enqueued right after it is caught next tick. The
    file's mtime is not used as the signal: on coarse-timestamp filesystems an
    enqueue can land within the same tick as the previous write.
    """
    path = path or path_for(ctx.config)
    names = ctx.controller.intervention_names()
    peek = read(path)
    if not peek.get("pending") and names == peek.get("registered"):
        return 0
    with _locked(path):
        data = read(path)
        data["registered"] = names
        pending = data.get("pending", [])
        applied = []
        for item in pending:
            entry = dict(item)
            entry["applied_at"] = {"day": ctx.clock.day, "time": ctx.clock.time_str}
            try:
                entry["result"] = ctx.controller.intervene(
                    item.get("name", ""), ctx, **(item.get("kwargs") or {})
                )
                entry["status"] = "applied"
            except Exception as exc:  # noqa: BLE001 — caller-supplied kwargs
                entry["status"] = "failed"
                entry["error"] = f"{type(exc).__name__}: {exc}"
                if ctx.recorder is not None:
                    ctx.recorder.record(
                        "controller.intervention_failed",
                        {"id": item.get("id"), "name": item.get("name"), "error": entry["error"]},
                    )
            applied.append(entry)
        data["pending"] = []
        data["applied"] = list(data.get("applied", [])) + applied
        _write(path, data)
    return len(applied)


# -- HTTP side ---------------------------------------------------------------


def enqueue(path: str, name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Queue one request. Raises ``LookupError`` (no live run) or
    ``KeyError`` (name not registered by the live run)."""
    with _locked(path):
        data = read(path)
        if not is_running(data):
            raise LookupError("no simulation is running")
        if name not in data.get("registered", []):
            raise KeyError(name)
        item = {
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "kwargs": kwargs,
            "queued_at": time.time(),
            "status": "pending",
        }
        data["pending"].append(item)
        _write(path, data)
    return item


def lookup(path: str, item_id: str) -> dict[str, Any] | None:
    data = read(path)
    for bucket in ("pending", "applied"):
        for item in data.get(bucket, []):
            if item.get("id") == item_id:
                return item
    return None
