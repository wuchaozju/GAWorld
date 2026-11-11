"""Durable population job metadata, outcomes and idempotent submissions.

The application owns access checks. Paths are resolved for the active world
at call time; large outcomes and generated populations are written only once.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Any

_ID = re.compile(r"^[a-z][a-z0-9_-]{0,39}-[a-f0-9]{8}$")
_REQUEST = re.compile(r"^[A-Za-z0-9_-]{8,80}$")


def root() -> Path:
    from gaworld.apps import world_paths

    return Path(world_paths.run_root()) / "population" / "jobs"


def safe_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False), parse_constant=lambda _: None)


def _path(job_id: str, suffix: str = ".json") -> Path | None:
    return root() / (job_id + suffix) if _ID.fullmatch(job_id) else None


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(safe_json(value), ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read(path: Path | None) -> Any:
    if path is None or path.is_symlink():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(record: dict[str, Any]) -> None:
    job_id = str(record.get("id") or "")
    path = _path(job_id)
    if path is None:
        return
    metadata = {key: value for key, value in record.items() if not key.startswith("_") and key != "result"}
    metadata["result"] = None
    if record.get("result") is not None:
        result_path = _path(job_id, ".result.json")
        assert result_path is not None
        _write(result_path, record["result"])
        metadata["result_ready"] = True
    _write(path, metadata)


def load(job_id: str, *, result: bool = True) -> dict[str, Any] | None:
    record = _read(_path(job_id))
    if not isinstance(record, dict) or record.get("id") != job_id:
        return None
    if result and record.get("result_ready"):
        record["result"] = _read(_path(job_id, ".result.json"))
    return record


def validate_request_id(value: Any) -> str:
    request_id = str(value or "")
    if request_id and not _REQUEST.fullmatch(request_id):
        raise ValueError("非法的提交标识，请刷新页面后重试")
    return request_id


def fingerprint(kind: str, payload: dict[str, Any]) -> str:
    data = {key: value for key, value in payload.items() if key != "request_id"}
    encoded = json.dumps([kind, data], ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _connect() -> sqlite3.Connection:
    directory = root()
    directory.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(directory / "submissions.sqlite", timeout=10)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS submissions "
        "(scope TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, "
        "job_id TEXT NOT NULL, PRIMARY KEY(scope, request_id))"
    )
    return conn


def _scope(record: dict[str, Any]) -> str:
    return json.dumps([str(record.get("owner_id") or ""), str(record.get("world_id") or "")])


def reserve(record: dict[str, Any]) -> tuple[str, bool]:
    """Reserve once across concurrent request threads and server processes."""
    request_id = validate_request_id(record.get("request_id"))
    if not request_id:
        save(record)
        return record["id"], True
    with closing(_connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        prior = conn.execute(
            "SELECT fingerprint, job_id FROM submissions WHERE scope=? AND request_id=?",
            (_scope(record), request_id),
        ).fetchone()
        if prior:
            if prior[0] != record.get("fingerprint"):
                raise ValueError("此提交标识已用于不同内容，请创建新的提交")
            if load(prior[1], result=False) is None:
                raise ValueError("原提交记录不可用；为避免重复执行，请查看任务历史")
            return str(prior[1]), False
        save(record)
        conn.execute(
            "INSERT INTO submissions VALUES (?,?,?,?)",
            (_scope(record), request_id, record["fingerprint"], record["id"]),
        )
    return record["id"], True


def recover(request_id: str, stamp: dict[str, Any]) -> str | None:
    request_id = validate_request_id(request_id)
    if not request_id:
        return None
    with closing(_connect()) as conn, conn:
        prior = conn.execute(
            "SELECT job_id FROM submissions WHERE scope=? AND request_id=?", (_scope(stamp), request_id)
        ).fetchone()
    return str(prior[0]) if prior else None


def save_population(job_id: str, result: Any) -> None:
    path = _path(job_id, ".population.json")
    if path is not None:
        _write(path, asdict(result))


def load_population(job_id: str) -> Any:
    from gaworld.population.generate import GeneratedPopulation
    from gaworld.population.network import HouseholdRecord, WorkplaceRecord
    from gaworld.population.report import Finding
    from gaworld.population.schema import Issue, normalize_spec
    from gaworld.population.synth import Person

    data = _read(_path(job_id, ".population.json"))
    if not isinstance(data, dict):
        return None
    try:
        return GeneratedPopulation(
            spec=normalize_spec(data["spec"]),
            people=[Person(**person) for person in data["people"]],
            households=[HouseholdRecord(**household) for household in data["households"]],
            workplaces=[WorkplaceRecord(**workplace) for workplace in data["workplaces"]],
            neighbours={int(key): value for key, value in data["neighbours"].items()},
            report=data["report"],
            findings=[Finding(**finding) for finding in data.get("findings", [])],
            feasibility=[Issue(**issue) for issue in data.get("feasibility", [])],
        )
    except (KeyError, TypeError, ValueError):
        return None
