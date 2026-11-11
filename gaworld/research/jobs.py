"""Durable outcomes for planning jobs; access checks belong to research_api."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from gaworld.research import workbench

_SAFE = re.compile(r"^(plan|digest|study)-[a-f0-9]{8}$")


def _path(job_id: str) -> Path | None:
    if not _SAFE.fullmatch(job_id):
        return None
    return workbench.plans_root() / "jobs" / f"{job_id}.json"


def save(record: dict[str, Any]) -> None:
    path = _path(str(record.get("id") or ""))
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    public = {key: value for key, value in record.items() if not key.startswith("_")}
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(public, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def load(job_id: str) -> dict[str, Any] | None:
    path = _path(job_id)
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def recent() -> list[dict[str, Any]]:
    root = workbench.plans_root() / "jobs"
    if not root.exists():
        return []
    return sorted(
        (record for path in root.glob("*.json") if (record := load(path.stem))),
        key=lambda record: record.get("started_at", 0),
        reverse=True,
    )
