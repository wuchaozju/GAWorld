"""Kernel-level HTTP surface: generic interventions + live record stream.

``/api/interventions`` exposes every intervention the running simulator's
Controller has registered (kernel standard ones and any plugin's), so a new
plugin gets an HTTP entry point without a new route. Requests travel through
the file queue in :mod:`gaworld.kernel.remote` and are applied at the next
tick; the response is ``202`` with an id to poll.

``/api/events/stream`` is a Server-Sent Events feed of the kernel Recorder:
every new row appended to ``output/records/<table>.jsonl`` is pushed as one
event named after its table. The Recorder is already the one time-aligned
stream all plugins write to, so tailing it needs no hook in the simulator.
"""

from __future__ import annotations

import glob
import json
import os
import time
from typing import Any, Callable

from gaworld.kernel import remote

#: How often the stream polls the records directory, and how long it may go
#: silent before a keep-alive comment (proxies drop idle connections ~30-60 s).
POLL_SECONDS = 0.5
HEARTBEAT_SECONDS = 15.0


def _ds():
    from gaworld.apps import dashboard_server

    return dashboard_server


def _queue_path() -> str:
    ds = _ds()
    return os.path.join(ds.REPO_ROOT, remote.path_for(ds.CONFIG))


def handle_get(path: str, query: dict) -> tuple[dict[str, Any], int]:
    qpath = _queue_path()
    if path.rstrip("/") == "/api/interventions":
        data = remote.read(qpath)
        return {
            "running": remote.is_running(data),
            "registered": data.get("registered", []),
            "pending": data.get("pending", []),
            "applied": list(reversed(data.get("applied", []))),
        }, 200
    item_id = path[len("/api/interventions/"):].strip("/")
    if item_id:
        item = remote.lookup(qpath, item_id)
        if item is None:
            return {"error": f"unknown intervention request `{item_id}`"}, 404
        return item, 200
    return {"error": "Unknown endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    name = path[len("/api/interventions/"):].strip("/")
    if not name or "/" in name:
        return {"error": "POST /api/interventions/{name} with the kwargs as the JSON body"}, 404
    try:
        item = remote.enqueue(_queue_path(), name, payload)
    except KeyError:  # before LookupError, its base class
        registered = remote.read(_queue_path()).get("registered", [])
        return {"error": f"unknown intervention `{name}`", "registered": registered}, 404
    except LookupError as exc:
        return {"error": str(exc)}, 409
    return item, 202


# -- /api/events/stream --------------------------------------------------------


def _parse_tables(query: dict) -> set[str] | None:
    raw = ",".join(query.get("tables", []))
    names = {t.strip() for t in raw.split(",") if t.strip()}
    return names or None


def stream_records(
    records_dir: str,
    write: Callable[[bytes], None],
    *,
    tables: set[str] | None = None,
    should_stop: Callable[[], bool] = lambda: False,
) -> None:
    """Push new Recorder rows to ``write`` as SSE frames until it raises.

    Files present at connect time are tailed from their current end (a client
    wants what happens next, not the whole history); files created later are
    read from the start. A file that shrinks was truncated by a reset, so its
    offset restarts at 0. Only complete lines are sent — the Recorder flushes
    per row, but a reader can still catch one mid-write.
    """
    offsets: dict[str, int] = {}
    for p in glob.glob(os.path.join(records_dir, "*.jsonl")):
        try:
            offsets[p] = os.path.getsize(p)
        except OSError:
            pass
    write(b": connected\n\n")
    last_sent = time.monotonic()
    while not should_stop():
        sent = False
        for p in sorted(glob.glob(os.path.join(records_dir, "*.jsonl"))):
            table = os.path.basename(p)[: -len(".jsonl")]
            if tables is not None and table not in tables:
                continue
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            start = offsets.get(p, 0)
            if size < start:
                start = 0
            if size == start:
                offsets[p] = start
                continue
            with open(p, "rb") as f:
                f.seek(start)
                chunk = f.read(size - start)
            end = chunk.rfind(b"\n")
            if end < 0:
                offsets[p] = start
                continue
            offsets[p] = start + end + 1
            for line in chunk[: end + 1].splitlines():
                if not line.strip():
                    continue
                try:
                    data = json.dumps(json.loads(line), ensure_ascii=False)
                except ValueError:
                    continue
                write(f"event: {table}\ndata: {data}\n\n".encode("utf-8"))
                sent = True
        now = time.monotonic()
        if sent:
            last_sent = now
        elif now - last_sent >= HEARTBEAT_SECONDS:
            write(b": keep-alive\n\n")
            last_sent = now
        time.sleep(POLL_SECONDS)


def serve_stream(handler, query: dict) -> None:
    """Hold the request open and stream; returns when the client disconnects."""
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("X-Accel-Buffering", "no")
    handler.send_header("Connection", "keep-alive")
    handler.end_headers()
    handler.close_connection = True

    def write(data: bytes) -> None:
        handler.wfile.write(data)
        handler.wfile.flush()

    try:
        stream_records(_ds().RECORDS_DIR, write, tables=_parse_tables(query))
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        pass
