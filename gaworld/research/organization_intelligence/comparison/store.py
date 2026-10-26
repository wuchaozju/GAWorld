"""Atomic workspace-scoped records with process-safe read/modify/write."""

from __future__ import annotations

import fcntl
import json
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from gaworld.research import workspaces


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
        try:
            record = json.loads((self.directory(identifier) / "record.json").read_text())
        except FileNotFoundError:
            raise LookupError("找不到记录") from None
        if not workspaces.visible(record):
            raise LookupError("找不到记录")
        return record

    def write(self, record):
        folder = self.directory(record["id"])
        self.atomic(folder / "record.json", record)

    @staticmethod
    def atomic(path, value):
        temporary = path.with_name(uuid.uuid4().hex + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temporary.replace(path)

    def state_path(self, identifier, cell):
        if not re.fullmatch(r"[0-9]+:[0-9]+:(candidate|baseline)", cell):
            raise ValueError("实验单元编号不合法")
        return self.directory(identifier) / "cells" / (cell.replace(":", "-") + ".json")

    def save_state(self, identifier, cell, value):
        self.get(identifier)
        path = self.state_path(identifier, cell)
        path.parent.mkdir(exist_ok=True)
        self.atomic(path, value)

    def load_state(self, identifier, cell):
        record = self.get(identifier)
        path = self.state_path(identifier, cell)
        if path.exists():
            return json.loads(path.read_text())
        # Readable audit compatibility with early local comparisons.
        old = record.get("states", {}).get(cell, {})
        return old if "calls" in old else {}

    def audit(self, identifier):
        record = self.get(identifier)
        record["states"] = {cell: self.load_state(identifier, cell) for cell in record.get("states", {})}
        return record

    def create(self, prefix, payload):
        identifier = prefix + uuid.uuid4().hex[:24]
        self.directory(identifier).mkdir(parents=True)
        record = {**payload, "id": identifier, "created_at": time.time(), **workspaces.stamp()}
        self.write(record)
        return record

    def update(self, identifier, mutation):
        with self.guard(identifier):
            record = self.get(identifier)
            mutation(record)
            self.write(record)
            return record

    def list(self, prefix):
        records = []
        for path in self.root.glob(prefix + "*/record.json"):
            try:
                records.append(self.get(path.parent.name))
            except (LookupError, ValueError, OSError):
                continue
        return sorted(records, key=lambda r: r["created_at"], reverse=True)
