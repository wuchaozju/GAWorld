"""Atomic, world-aware artifacts for organization-intelligence experiments."""

from __future__ import annotations

import codecs
import fcntl
import json
import os
import re
import uuid
from pathlib import Path

from gaworld.apps import world_paths
from gaworld.research import workbench


def root():
    if world_paths.current_world():
        return Path(world_paths.world_file("research", "organization_intelligence"))
    return workbench.plans_root() / "organization_intelligence"


def directory(identifier):
    if not re.fullmatch(r"OI[a-f0-9]{24}", str(identifier)):
        raise ValueError("无效的组织智能研究编号")
    return root() / identifier


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save(record):
    atomic(directory(record["id"]) / "study.json", json.dumps(record, ensure_ascii=False, indent=2))


def load(identifier):
    try:
        return json.loads((directory(identifier) / "study.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def records():
    out = []
    for path in root().glob("OI*/study.json"):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda r: r["created_at"], reverse=True)


def event(identifier, value):
    with (directory(identifier) / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def log_chunk(identifier, offset):
    """Bounded UTF-8 chunks, including records longer than a network page."""
    path = directory(identifier) / "events.jsonl"
    if not path.exists():
        return {"text": "", "next_offset": 0, "size": 0}
    size = path.stat().st_size
    offset = min(max(0, offset), size)
    with path.open("rb") as handle:
        handle.seek(offset)
        raw = handle.read(64 * 1024)
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    text = decoder.decode(raw, final=False)
    pending = decoder.getstate()[0]
    return {"text": text, "next_offset": offset + len(raw) - len(pending), "size": size}


def provider_limit(key, info=None):
    """Share retry floors across OI jobs in this world, including fresh drafts."""
    root().mkdir(parents=True, exist_ok=True)
    with (root() / "provider-limits.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root() / "provider-limits.json"
        limits = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        existing = limits.get(key) or {}
        if info and info["retry_at"] > existing.get("retry_at", 0):
            limits[key] = info
            atomic(path, json.dumps(limits, ensure_ascii=False))
            existing = info
        return existing
