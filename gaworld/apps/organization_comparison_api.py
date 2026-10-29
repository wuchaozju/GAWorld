"""Private six-step organization comparison endpoints."""

from __future__ import annotations

import csv
import fcntl
import io
from pathlib import Path

from gaworld.accounts import ownership
from gaworld.apps import organization_intelligence_api as legacy
from gaworld.apps import research_api, world_paths
from gaworld.collaboration.organization_engine import execution_metrics
from gaworld.collaboration.organization_methods import KINDS, digest
from gaworld.research.organization_intelligence.comparison import (
    analysis,
    benchmarks,
    material,
    protocol,
    runner,
)
from gaworld.research.organization_intelligence.comparison.store import Store

PREFIX = "/api/research/organization-intelligence/comparisons"


def root():
    if world_paths.current_world():
        return Path(world_paths.world_file("research", "organization_comparisons"))
    cfg = world_paths.effective_config()
    return (
        Path(world_paths.REPO_ROOT)
        / (cfg.get("run_output_dir") or "output")
        / "research"
        / "organization_comparisons"
    )


def database():
    return Store(root() / "studies")


def present(record):
    value = {key: v for key, v in record.items() if key != "states"}
    values = [
        state.get("metrics") or execution_metrics(state, include_scoring=True)
        for state in record.get("states", {}).values()
    ]
    value["metrics"] = {
        "calls": sum(c["calls"] for c in values),
        "input_chars": sum(c["input_chars"] for c in values),
        "output_chars": sum(c["output_chars"] for c in values),
        "tokens": None,
    }
    return value


def launch(db, record):
    spec = record["protocol"]
    if record["status"] in {"completed", "stopped"}:
        raise ValueError("此实验已结束；可以复制设置另建一次")
    if digest(spec) != record["protocol_hash"]:
        raise ValueError("实验设置校验失败")
    if spec.get("runtime_fingerprint") != protocol.runtime_fingerprint():
        raise ValueError("实验执行代码已改变；请使用原版本或创建新实验")
    if legacy.model_info(spec["model"]["name"]) != spec["model"]:
        raise ValueError("模型配置已改变，请恢复配置或创建新实验")
    raw_caller = legacy.make_caller(spec)
    lease = (db.directory(record["id"]) / "runner.lock").open("a")
    try:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lease.close()
        raise ValueError("此实验正在运行") from None
    db.update(record["id"], lambda r: r.update(status="running", control="", error=""))

    def work():
        try:
            runner.run(db, record["id"], lambda prompt, **kw: raw_caller(prompt))
        finally:
            lease.close()

    try:
        ownership.spawn(work, name="organization-comparison-" + record["id"])
    except Exception:
        lease.close()
        db.update(record["id"], lambda r: r.update(status="interrupted", error="后台任务未能启动"))
        raise


def handle_get(path, query=None):
    parts = path[len(PREFIX) :].strip("/").split("/") if path.rstrip("/") != PREFIX else []
    db = database()
    try:
        if not parts:
            return {
                "studies": [
                    {k: r[k] for k in ("id", "status", "created_at", "analysis")}
                    | {"title": r["protocol"]["title"]}
                    for r in db.list("C")
                ]
            }, 200
        if parts == ["context"]:
            return {
                "providers": research_api._providers(),
                "default_provider": ((research_api._base_config().get("llm") or {}).get("routing") or {}).get(
                    "default", ""
                ),
                "members": legacy.population(),
                "baselines": [{"id": k, "name": v} for k, v in KINDS.items()],
                "problems": [
                    {"id": "information", "name": "分散信息整合"},
                    {"id": "allocation", "name": "约束资源分配"},
                ],
            }, 200
        record = db.get(parts[0])
        if record["status"] == "running":
            with (db.directory(record["id"]) / "runner.lock").open("a") as lease:
                try:
                    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    record = db.update(record["id"], lambda r: r.update(status="interrupted"))
        if len(parts) == 1:
            return present(record), 200
        if parts[1:] == ["results"]:
            return {"rows": record["rows"], "analysis": record["analysis"]}, 200
        if parts[1:] == ["export"]:
            return {"filename": record["id"] + ".md", "markdown": analysis.report(record)}, 200
        if parts[1:] == ["protocol"]:
            return {
                "filename": record["id"] + "-settings.json",
                "protocol": record["protocol"],
                "protocol_hash": record["protocol_hash"],
            }, 200
        if parts[1:] == ["audit"]:
            return {"filename": record["id"] + "-audit.json", "record": db.audit(record["id"])}, 200
        if parts[1:] == ["csv"]:
            handle = io.StringIO()
            writer = csv.DictWriter(
                handle,
                fieldnames=["task_id", "repeat", "arm", "score", "valid", "error"],
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(record["rows"])
            return {"filename": record["id"] + ".csv", "csv": handle.getvalue()}, 200
    except LookupError as exc:
        return {"error": str(exc)}, 404
    except (ValueError, OSError) as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown endpoint"}, 404


def handle_post(path, payload):
    db = database()
    parts = path[len(PREFIX) :].strip("/").split("/") if path.rstrip("/") != PREFIX else []
    try:
        if not isinstance(payload, dict):
            raise ValueError("请求需要JSON对象")
        if parts == ["analyze"]:
            model = legacy.model_info(str(payload.get("provider") or ""))
            caller = legacy.make_caller({"model": model, "temperature": 0.3, "max_tokens": 4096})
            return material.extract(payload.get("text"), str(payload.get("title", "")), caller), 200
        if parts == ["benchmark"]:
            if "text" in payload:
                bank = benchmarks.import_data(
                    payload["text"],
                    payload.get("format", "jsonl"),
                    payload.get("mapping"),
                    name=payload.get("name", "导入题库"),
                    scorer=payload.get("scorer", "exact"),
                )
            else:
                bank = benchmarks.builtin(
                    payload.get("problem", "information"),
                    payload.get("count", 30),
                    payload.get("slots", 3),
                    payload.get("seed", 20261026),
                )
            return {"benchmark": bank, "count": len(bank["tasks"])}, 200
        if not parts:
            people = {p["id"]: p for p in legacy.population()}
            selected = payload.get("agent_ids", [])
            if not isinstance(selected, list) or any(type(x) is not int or x not in people for x in selected):
                raise ValueError("请选择当前世界中的有效居民")
            spec = protocol.freeze(
                payload, [people[i] for i in selected], legacy.model_info(str(payload.get("provider") or ""))
            )
            record = db.create(
                "C",
                {
                    "status": "draft",
                    "protocol": spec,
                    "protocol_hash": digest(spec),
                    "rows": [],
                    "states": {},
                    "control": "",
                    "analysis": analysis.analyze([], expected=spec["expected"]),
                },
            )
            return present(record), 201
        record = db.get(parts[0])
        if parts[1:] in (["run"], ["resume"]):
            launch(db, record)
            return {"id": record["id"], "status": "running"}, 202
        if parts[1:] in (["pause"], ["stop"]):
            if record["status"] not in {"running", "paused", "interrupted"}:
                raise ValueError("此实验当前不能暂停或终止")
            action = parts[1]
            updated = db.update(
                record["id"],
                lambda r: r.update(
                    control=action,
                    **({"status": "stopped"} if action == "stop" and r["status"] != "running" else {}),
                ),
            )
            return present(updated), 200
        if parts[1:] == ["save-method"]:
            from gaworld.apps import organization_methods_api

            return organization_methods_api.save_study(record, payload), 201
    except LookupError as exc:
        return {"error": str(exc)}, 404
    except (ValueError, TypeError, KeyError) as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown endpoint"}, 404
