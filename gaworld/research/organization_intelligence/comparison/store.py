"""Atomic workspace-scoped records with process-safe read/modify/write.

A study keeps three kinds of file:

``record.json``   the frozen protocol, the rows and the status — written when
                  a cell finishes or the status changes.
``live.json``     the fields that change on every request (waiting, the last
                  request time, the control flag, the per-cell state index) —
                  written often, but small and cheap to rewrite.
``events.jsonl``  an append-only log of requests and responses.

Splitting them keeps a long run from rewriting the whole study on every
model call.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from gaworld.research import workspaces

#: Fields that live in ``live.json`` rather than in ``record.json``.
LIVE_FIELDS = ("control", "waiting", "last_request_at", "states", "progress")


class Store:
    def __init__(self, root):
        self.root = Path(root)

    def directory(self, identifier):
        if not re.fullmatch(r"[CM][a-f0-9]{24}", identifier):
            raise LookupError("找不到记录")
        return self.root / identifier

    @contextmanager
    def guard(self, identifier):
        folder = self.directory(identifier)
        if not folder.is_dir():
            raise LookupError("找不到记录")
        with (folder / "record.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def get(self, identifier):
        """The study as one record: ``record.json`` plus the live fields."""
        record = self._raw(identifier)
        live = self.live(identifier)
        for key in LIVE_FIELDS:
            record[key] = live.get(key, {} if key == "states" else ("" if key == "control" else None))
        if record["states"] is None:
            record["states"] = {}
        return record

    def _raw(self, identifier):
        """``record.json`` on its own, without the live fields."""
        try:
            record = json.loads((self.directory(identifier) / "record.json").read_text())
        except FileNotFoundError:
            raise LookupError("找不到记录") from None
        if not workspaces.visible(record):
            raise LookupError("找不到记录")
        return record

    def live(self, identifier):
        """The transient fields. Callers have already checked ownership."""
        try:
            value = json.loads((self.directory(identifier) / "live.json").read_text())
        except (FileNotFoundError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def merged(self, identifier):
        return self.get(identifier)

    def write(self, record):
        folder = self.directory(record["id"])
        self.atomic(folder / "record.json", record)

    @staticmethod
    def atomic(path, value):
        temporary = path.with_name(uuid.uuid4().hex + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temporary.replace(path)

    def state_path(self, identifier, cell):
        if not re.fullmatch(r"[0-9]+:[0-9]+:(candidate(-[0-9]+)?|baseline)", cell):
            raise ValueError("实验单元编号不合法")
        return self.directory(identifier) / "cells" / (cell.replace(":", "-") + ".json")

    def save_state(self, identifier, cell, value):
        self.get(identifier)
        path = self.state_path(identifier, cell)
        path.parent.mkdir(exist_ok=True)
        self.atomic(path, value)

    def load_state(self, identifier, cell):
        record = self.merged(identifier)
        path = self.state_path(identifier, cell)
        if path.exists():
            return json.loads(path.read_text())
        # Readable audit compatibility with early local comparisons.
        old = record.get("states", {}).get(cell, {})
        return old if "calls" in old else {}

    def delete(self, identifier):
        """Remove a study and everything it wrote."""
        folder = self.directory(identifier)
        self.get(identifier)  # ownership check before anything is removed
        for child in sorted(folder.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        folder.rmdir()

    def append_event(self, identifier, event):
        """One append-only line. Never rewrites earlier evidence."""
        path = self.directory(identifier) / "events.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def events(self, identifier, offset=0):
        path = self.directory(identifier) / "events.jsonl"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[offset:] if line.strip()]

    def audit(self, identifier):
        record = self.merged(identifier)
        record["states"] = {cell: self.load_state(identifier, cell) for cell in record.get("states", {})}
        record["events"] = self.events(identifier)
        return record

    def create(self, prefix, payload):
        identifier = prefix + uuid.uuid4().hex[:24]
        self.directory(identifier).mkdir(parents=True)
        record = {**payload, "id": identifier, "created_at": time.time(), **workspaces.stamp()}
        for key in LIVE_FIELDS:
            record.pop(key, None)
        self.write(record)
        live = {key: payload.get(key) for key in LIVE_FIELDS if key in payload}
        live.setdefault("states", {})
        live.setdefault("control", "")
        self.write_live(identifier, live)
        return record

    def write_live(self, identifier, value):
        self.atomic(self.directory(identifier) / "live.json", value)

    def update(self, identifier, mutation):
        """Change ``record.json``. The live fields keep their own file."""
        with self.guard(identifier):
            record = self._raw(identifier)
            mutation(record)
            for key in LIVE_FIELDS:
                record.pop(key, None)
            self.write(record)
            return self.get(identifier)

    def touch(self, identifier, **fields):
        """Replace live fields. The live file stays small, so this is cheap."""
        with self.guard(identifier):
            live = self.live(identifier)
            live.update(fields)
            self.write_live(identifier, live)
            return live

    def set_state(self, identifier, cell, summary):
        """Record one cell's metrics in the live index."""
        with self.guard(identifier):
            live = self.live(identifier)
            states = live.get("states")
            if not isinstance(states, dict):
                states = {}
            states[cell] = summary
            live["states"] = states
            self.write_live(identifier, live)
            return live

    def list(self, prefix):
        records = []
        for path in self.root.glob(prefix + "*/record.json"):
            try:
                records.append(self.get(path.parent.name))
            except (LookupError, ValueError, OSError):
                continue
        return sorted(records, key=lambda r: r["created_at"], reverse=True)
