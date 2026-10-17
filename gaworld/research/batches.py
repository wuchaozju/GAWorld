"""Immutable experiment matrices and atomic, workspace-owned batch records."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from gaworld.city.knowledge import _utcnow
from gaworld.research import workbench, workspaces

MAX_CELLS = 200
MAX_REPEATS = 100
SAFE_ID = re.compile(r"^B[a-f0-9]{24}$")


def root() -> Path:
    return workbench.plans_root() / "batches"


def directory(batch_id: str) -> Path:
    if not SAFE_ID.fullmatch(str(batch_id)):
        raise ValueError("非法的批次 ID")
    return root() / batch_id


def matrix(payload: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for key, maximum in (("providers", 10), ("cities", 20)):
        values = payload.get(key)
        if (
            not isinstance(values, list)
            or not 1 <= len(values) <= maximum
            or any(not isinstance(v, str) or len(v) > 200 or (key == "providers" and not v) for v in values)
            or len(set(values)) != len(values)
        ):
            raise ValueError(f"{key} 须为非空、不重复的选择列表（最多 {maximum} 项）")
        out[key] = list(values)
    for key, default, low, high in (("repeats", 3, 1, MAX_REPEATS), ("seed", 42, 0, 2**31 - MAX_REPEATS)):
        value = payload.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{key} 须为 {low}–{high} 的整数")
        out[key] = value
    strategy = payload.get("seed_strategy", "vary")
    if strategy not in {"vary", "fixed"}:
        raise ValueError("种子策略须为 vary 或 fixed")
    out["seed_strategy"] = strategy
    if len(out["providers"]) * len(out["cities"]) * out["repeats"] > MAX_CELLS:
        raise ValueError(f"一个批次最多 {MAX_CELLS} 次独立运行")
    return out


def cells(settings: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"m{mi}-c{ci}-r{ri + 1}",
            "provider": provider,
            "city": city,
            "repeat": ri + 1,
            "seed": settings["seed"] + (ri if settings["seed_strategy"] == "vary" else 0),
            "status": "pending",
            "study_id": "",
            "history": [],
        }
        for mi, provider in enumerate(settings["providers"])
        for ci, city in enumerate(settings["cities"])
        for ri in range(settings["repeats"])
    ]


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def protocol_hash(protocol: dict[str, Any]) -> str:
    data = copy.deepcopy(protocol)
    for key in ("sim_provider", "budget", "plan_id", "title"):
        data.pop(key, None)
    data.setdefault("validity", {}).pop("seeds", None)
    for key in ("city", "seed_identity", "agent_ids", "note"):
        data.setdefault("sample", {}).pop(key, None)
    return digest(data)


def new(protocol: dict[str, Any], settings: dict[str, Any], *, source_id: str = "") -> dict[str, Any]:
    settings = matrix(settings)
    return {
        "id": "B" + uuid.uuid4().hex[:24],
        "title": protocol["title"],
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
        "status": "draft",
        "source_study_id": source_id,
        "protocol": copy.deepcopy(protocol),
        "protocol_hash": protocol_hash(protocol),
        "matrix": settings,
        "cells": cells(settings),
        "inputs": {},
        "preflight": {},
        **workspaces.stamp(),
    }


def save(record: dict[str, Any]) -> None:
    target = directory(record["id"])
    target.mkdir(parents=True, exist_ok=True)
    record["updated_at"] = _utcnow()
    temp = target / f"batch-{uuid.uuid4().hex}.tmp"
    temp.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(target / "batch.json")


def load(batch_id: str) -> dict[str, Any] | None:
    path = directory(batch_id) / "batch.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def listing() -> list[dict[str, Any]]:
    if not root().exists():
        return []
    records = [load(p.name) for p in root().iterdir() if p.is_dir() and SAFE_ID.fullmatch(p.name)]
    return sorted(
        [
            {k: r[k] for k in ("id", "title", "status", "created_at", "matrix", "source_study_id")}
            for r in records
            if workspaces.visible(r)
        ],
        key=lambda r: r["created_at"],
        reverse=True,
    )
