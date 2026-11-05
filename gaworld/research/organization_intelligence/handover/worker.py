"""Isolated CLI entry point: freeze a protocol or resume the persisted graph."""

import fcntl
import json
import os
from pathlib import Path

from . import protocol, queue, report


def atomic(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def main(database, build_id, args):
    if args and args[0] == "create":
        payload, record = json.loads(args[1]), json.loads(args[2])
        spec = protocol.freeze(payload)
        queue.create(database, spec, {**record, "build_id": build_id})
        atomic(database.parent / "protocol.json", protocol.canonical(spec))
        return
    # The outer lock includes identity publication and exports, not just episode commits.
    with database.with_suffix(".worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        execute(database, build_id)


def execute(database, build_id):
    record = queue.snapshot(database)
    spec = record["protocol"]
    if record.get("build_id", build_id) != build_id:
        raise ValueError("database frozen build mismatch")
    if protocol.digest(spec) != record["protocol_hash"]:
        raise ValueError("protocol hash mismatch")
    frozen = database.parent / "protocol.json"
    if frozen.exists() and json.loads(frozen.read_text(encoding="utf-8")) != spec:
        raise ValueError("frozen protocol mismatch")
    if record["status"] not in {"running", "completed"}:
        return
    with queue.connect(database) as db:
        queue.set_meta(db, "worker_pid", os.getpid())
    if not queue.run(database, worker_build=build_id, respect_intent=True):
        return
    rows = queue.results(database)
    analysis = report.evaluate(spec, rows)
    atomic(database.parent / "results.json", protocol.canonical({"analysis": analysis, "rows": rows}))
    atomic(database.parent / "report.md", report.markdown(queue.snapshot(database), analysis))
    with queue.connect(database) as db:
        queue.set_meta(db, "artifacts_published", analysis["complete"])
