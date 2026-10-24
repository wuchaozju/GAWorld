"""World-owned zero-provider studies with frozen, independently loaded workers."""

import json
import os
import re
import subprocess
import threading
import uuid

from gaworld.accounts.ownership import spawn
from gaworld.research import workspaces
from gaworld.research.organization_intelligence import store
from gaworld.research.organization_intelligence.v2 import build, queue

PREFIX = "/api/research/organization-intelligence/v2"
_ACTIVE = set()
_LOCK = threading.Lock()


def root():
    return store.root() / "v2"


def directory(identifier):
    if not re.fullmatch(r"OI2[a-f0-9]{24}", identifier):
        raise ValueError("无效研究编号")
    return root() / identifier


def load(identifier):
    path = directory(identifier) / "tasks.sqlite"
    if not path.exists():
        return None
    record = queue.snapshot(path)
    if not all((path.parent / name).exists() for name in ("results.json", "report.md")):
        record["artifacts_published"] = False
    return record


def worker(identifier, folder):
    database = folder / "tasks.sqlite"
    try:
        with (folder / "worker.log").open("ab") as log:
            process = subprocess.Popen(
                build.command(folder / "bundle", database), stdout=log, stderr=log, start_new_session=True
            )
            process.wait()
        if process.returncode:
            with queue.connect(database) as db:
                queue.set_meta(db, "status", "blocked")
                queue.set_meta(db, "error", "冻结执行器校验或执行异常；已提交证据保留，详见worker.log")
    except Exception as exc:
        with queue.connect(database) as db:
            queue.set_meta(db, "status", "blocked")
            queue.set_meta(db, "error", f"无法启动冻结执行器：{type(exc).__name__}")
    finally:
        with _LOCK:
            _ACTIVE.discard(identifier)


def launch(record, explicit=False):
    identifier = record["id"]
    database = directory(identifier) / "tasks.sqlite"
    with queue.connect(database) as db:
        db.execute("BEGIN IMMEDIATE")
        status = queue.metadata(db)["status"]
        if explicit and status != "completed":
            queue.set_meta(db, "status", "running")
        elif not explicit and status not in {"running", "completed"}:
            return
    with _LOCK:
        if identifier in _ACTIVE or (status == "completed" and record.get("artifacts_published")):
            return
        _ACTIVE.add(identifier)
    try:
        spawn(worker, identifier, directory(identifier), name=f"organization-v2-{identifier}")
    except Exception:
        with _LOCK:
            _ACTIVE.discard(identifier)
        raise


def visible(identifier, recover=True):
    record = load(identifier)
    if not workspaces.visible(record):
        return None
    # A running intention survives server restart. flock prevents duplicate local workers.
    if recover and (
        record["status"] == "running"
        or (record["status"] == "completed" and not record.get("artifacts_published"))
    ):
        launch(record)
    if record["status"] == "completed" and not record.get("artifacts_published"):
        record["status"] = "finalizing"
    return record


def handshake(payload, expected):
    return payload.get("expected_build") == expected


def handle_get(path, query=None):
    parts = [p for p in path[len(PREFIX) :].split("/") if p]
    try:
        if not parts:
            records = []
            for item in root().glob("OI2*/tasks.sqlite"):
                record = visible(item.parent.name)
                if record:
                    records.append(
                        {
                            k: record[k]
                            for k in ("id", "status", "created_at", "committed", "total", "build_id")
                        }
                    )
            return {
                "engine": {**build.identity(), "pid": os.getpid()},
                "studies": sorted(records, key=lambda r: r["created_at"], reverse=True),
            }, 200
        record = visible(parts[0])
        if record is None:
            return {"error": "找不到研究"}, 404
        folder = directory(parts[0])
        if len(parts) == 1:
            return record, 200
        if parts[1:] == ["protocol"]:
            return {
                "filename": f"{record['id']}-protocol.json",
                "protocol": record["protocol"],
                "protocol_hash": record["protocol_hash"],
                "build_id": record["build_id"],
            }, 200
        if parts[1:] == ["results"]:
            output = folder / "results.json"
            if output.exists():
                return json.loads(output.read_text(encoding="utf-8")), 200
            return {"analysis": {"complete": False, "contrasts": [], "cells": []}, "rows": []}, 200
        if parts[1:] == ["export"]:
            report = folder / "report.md"
            text = (
                report.read_text(encoding="utf-8")
                if report.exists()
                else f"# {record['id']}\n\n任务 {record['committed']}/{record['total']}；数据尚不完整，暂无处理效应结论。外部模型请求 0。"
            )
            return {"filename": f"{record['id']}.md", "markdown": text}, 200
    except (ValueError, OSError) as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown endpoint"}, 404


def handle_post(path, payload):
    parts = [p for p in path[len(PREFIX) :].split("/") if p]
    try:
        if not isinstance(payload, dict):
            raise ValueError("需要JSON对象")
        if not parts:
            identity = build.identity()
            if not identity["workspace_matches"] or not handshake(payload, identity["build_id"]):
                return {"error": "引擎版本握手失败或工作区已变化，请重启服务并刷新页面"}, 409
            identifier = "OI2" + uuid.uuid4().hex[:24]
            folder = directory(identifier)
            build.freeze(folder / "bundle")
            values = {k: v for k, v in payload.items() if k != "expected_build"}
            record = {"id": identifier, **workspaces.stamp()}
            result = subprocess.run(
                build.command(
                    folder / "bundle",
                    folder / "tasks.sqlite",
                    "create",
                    json.dumps(values),
                    json.dumps(record),
                ),
                capture_output=True,
                timeout=15,
            )
            if result.returncode:
                raise ValueError("冻结失败：仅支持1–100个种子、合法整数seed的零调用协议")
            return load(identifier), 201
        record = visible(parts[0], recover=False)
        if record is None:
            return {"error": "找不到研究"}, 404
        if parts[1:] == ["run"]:
            if not handshake(payload, record["build_id"]):
                return {"error": "页面与冻结构建不一致，请重新读取该研究"}, 409
            launch(record, explicit=True)
            return {
                "id": record["id"],
                "status": "running" if record["status"] != "completed" else "completed",
            }, 202
        if parts[1:] == ["pause"]:
            queue.pause(directory(record["id"]) / "tasks.sqlite")
            return load(record["id"]), 200
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown endpoint"}, 404
