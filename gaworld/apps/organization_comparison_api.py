"""Private six-step organization comparison endpoints."""

from __future__ import annotations

import csv
import fcntl
import io
from pathlib import Path

from gaworld.accounts import ownership
from gaworld.apps import research_api, world_paths
from gaworld.collaboration.organization_engine import execution_metrics
from gaworld.collaboration.organization_methods import KINDS, digest
from gaworld.research.organization_intelligence import common
from gaworld.research.organization_intelligence.comparison import (
    analysis,
    benchmarks,
    execution,
    material,
    protocol,
    recovery,
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
    value["title"] = record["protocol"]["title"]
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
    value["resume_requires_recovery"] = (
        record["status"] in {"draft", "paused", "interrupted", "rate_limited"}
        and record["protocol"].get("runtime_fingerprint") != protocol.runtime_fingerprint()
    )
    return value


class CooldownPending(ValueError):
    def __init__(self, info):
        self.info = info
        super().__init__(info["message"] + " 请等待页面显示的最早重试时间。")


def _running(db):
    """Studies that hold a runner lease right now."""
    active = []
    for record in db.list("C"):
        if record["status"] != "running":
            continue
        try:
            with (db.directory(record["id"]) / "runner.lock").open("a") as lease:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            active.append(record)
        else:
            continue
    return active


def _guard_capacity(db, record):
    """Two studies at a time, and never two on the same model."""
    active = _running(db)
    if len(active) >= 2:
        raise ValueError("最多同时执行两项组织智能研究")
    model = record["protocol"]["model"]["name"]
    if any(r["protocol"]["model"]["name"] == model for r in active):
        raise ValueError("该模型已有组织智能研究运行，请先等待或停止，避免并发触发限流")


def launch(db, record):
    spec = record["protocol"]
    if record["status"] not in {"draft", "paused", "interrupted", "rate_limited"}:
        raise ValueError("此实验已结束；可以复制设置另建一次")
    if record.get("retry_blocked_reason"):
        raise ValueError(record["retry_blocked_reason"])
    info = record.get("error_info") or {}
    if (info.get("retry_at") or 0) > execution.now():
        raise CooldownPending(info)
    if digest(spec) != record["protocol_hash"]:
        raise ValueError("实验设置校验失败")
    if spec.get("runtime_fingerprint") != protocol.runtime_fingerprint():
        raise ValueError("实验的执行语义已改变；请用「重新运行（保留进度）」核对已保存的回答，或创建新实验")
    if common.model_info(spec["model"]["name"]) != spec["model"]:
        raise ValueError("模型配置已改变，请恢复配置或创建新实验")
    _guard_capacity(db, record)
    raw_caller = common.make_caller(spec)
    lease = (db.directory(record["id"]) / "runner.lock").open("a")
    try:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lease.close()
        raise ValueError("此实验正在运行") from None
    db.update(record["id"], lambda r: r.update(status="running", error=""))
    db.touch(record["id"], control="")

    def work():
        try:
            runner.run(
                db,
                record["id"],
                lambda prompt, **kw: raw_caller(prompt, agent_id=kw.get("agent_id")),
            )
        finally:
            lease.close()

    try:
        ownership.spawn(work, name="organization-comparison-" + record["id"])
    except Exception:
        lease.close()
        db.update(record["id"], lambda r: r.update(status="interrupted", error="后台任务未能启动"))
        raise


def summary(db):
    """Every comparison of this world in one table, with what it cost.

    The numbers are what was measured: the actual calls, the characters that
    went in and out, and the seconds the calls took. The money amount is not
    estimated: the configuration carries no price, and a character is not a
    token. The verdict of each study is repeated here so a reader can see the
    studies behind a claim without opening them one by one.
    """
    studies = []
    totals = {"studies": 0, "completed": 0, "calls": 0, "input_chars": 0, "output_chars": 0, "elapsed": 0.0}
    verdicts = {"better": 0, "worse": 0, "uncertain": 0, "incomplete": 0}
    for record in db.list("C"):
        value = present(record)
        analysis = value.get("analysis") or {}
        verdict = analysis.get("verdict") or "incomplete"
        metrics = value.get("metrics") or {}
        arms = [arm.get("label") or arm.get("id") for arm in value["protocol"].get("arms", [])]
        studies.append(
            {
                "id": value["id"],
                "title": value["title"],
                "status": value["status"],
                "created_at": value.get("created_at"),
                "verdict": verdict,
                "conclusion": analysis.get("conclusion") or "",
                "independent_tasks": analysis.get("independent_tasks") or 0,
                "arms": arms,
                "model": value["protocol"]["model"]["model"],
                "questions": len(value["protocol"]["benchmark"]["tasks"]),
                "repeats": value["protocol"].get("repeats"),
                "cells": len(value.get("rows") or []),
                "expected": value["protocol"].get("expected"),
                "calls": metrics.get("calls", 0),
                "input_chars": metrics.get("input_chars", 0),
                "output_chars": metrics.get("output_chars", 0),
                "elapsed": sum(
                    (state.get("metrics") or {}).get("elapsed", 0)
                    for state in (record.get("states") or {}).values()
                ),
                "tokens": metrics.get("tokens"),
            }
        )
        totals["studies"] += 1
        totals["completed"] += 1 if value["status"] == "completed" else 0
        totals["calls"] += metrics.get("calls", 0) or 0
        totals["input_chars"] += metrics.get("input_chars", 0) or 0
        totals["output_chars"] += metrics.get("output_chars", 0) or 0
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
    totals["elapsed"] = sum(study["elapsed"] for study in studies)
    totals["calls_per_study"] = round(totals["calls"] / totals["studies"], 1) if totals["studies"] else 0
    return {"studies": studies, "totals": totals, "verdicts": verdicts, "money": None}


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
        if parts == ["summary"]:
            return summary(db), 200
        if parts == ["context"]:
            return {
                "providers": research_api._providers(),
                "default_provider": ((research_api._base_config().get("llm") or {}).get("routing") or {}).get(
                    "default", ""
                ),
                "members": common.population(),
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
        record = db.merged(record["id"])
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
                fieldnames=[
                    "task_id",
                    "repeat",
                    "arm",
                    "score",
                    "valid",
                    "measured",
                    "invalid_reason",
                    "error",
                ],
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
            model = common.model_info(str(payload.get("provider") or ""))
            caller = common.make_caller({"model": model, "temperature": 0.3, "max_tokens": 4096})
            return material.extract(
                payload.get("text"), str(payload.get("title", "")), caller, slots=payload.get("slots")
            ), 200
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
            people = {p["id"]: p for p in common.population()}
            selected = payload.get("agent_ids", [])
            if not isinstance(selected, list) or any(type(x) is not int or x not in people for x in selected):
                raise ValueError("请选择当前世界中的有效居民")
            spec = protocol.freeze(
                payload, [people[i] for i in selected], common.model_info(str(payload.get("provider") or ""))
            )
            if not spec["plan"]["sufficient"]:
                raise ValueError("；".join(spec["plan"]["warnings"]) or "本次设置不足以完成一次实验单元")
            record = db.create(
                "C",
                {
                    "status": "draft",
                    "protocol": spec,
                    "protocol_hash": digest(spec),
                    "rows": [],
                    "analysis": analysis.analyze(
                        [],
                        expected=spec["expected"],
                        arms=[arm["id"] for arm in protocol.arms_of(spec)],
                    ),
                },
            )
            return present(record), 201
        if parts == ["plan"]:
            people = {p["id"]: p for p in common.population()}
            selected = payload.get("agent_ids", [])
            if not isinstance(selected, list) or any(type(x) is not int or x not in people for x in selected):
                raise ValueError("请选择当前世界中的有效居民")
            prepared = protocol.prepare(payload, [people[i] for i in selected])
            return {
                "plan": prepared["plan"],
                "scope_factors": prepared["changed"],
                "arms": [
                    {
                        "id": arm["id"],
                        "label": arm["label"],
                        "is_control": arm["is_control"],
                        "scope": prepared["changed_by_arm"].get(arm["id"], []),
                    }
                    for arm in prepared["arms"]
                ],
            }, 200
        record = db.get(parts[0])
        if parts[1:] in (["run"], ["resume"]):
            launch(db, record)
            return {"id": record["id"], "status": "running"}, 202
        if parts[1:] == ["recover"]:
            if common.model_info(record["protocol"]["model"]["name"]) != record["protocol"]["model"]:
                raise ValueError("模型配置已变化，不能把其他模型的回答接入原实验")
            return present(recovery.prepare(db, record)), 201
        if parts[1:] == ["duplicate"]:
            source = db.get(parts[0])
            spec = source["protocol"]
            copy = db.create(
                "C",
                {
                    "status": "draft",
                    "protocol": {
                        **spec,
                        "runtime_fingerprint": protocol.runtime_fingerprint(),
                        "title": (spec.get("title") or "组织对照实验") + " · 副本",
                    },
                    "protocol_hash": "",
                    "rows": [],
                    "analysis": analysis.analyze(
                        [],
                        expected=spec["expected"],
                        arms=[arm["id"] for arm in protocol.arms_of(spec)],
                    ),
                },
            )
            copy["protocol_hash"] = digest(copy["protocol"])
            db.update(copy["id"], lambda r: r.update(protocol_hash=copy["protocol_hash"]))
            return present(db.merged(copy["id"])), 201
        if parts[1:] == ["delete"]:
            target = db.get(parts[0])
            if target["status"] == "running":
                raise ValueError("实验正在运行，请先停止")
            db.delete(parts[0])
            return {"id": parts[0], "deleted": True}, 200
        if parts[1:] in (["pause"], ["stop"]):
            if record["status"] not in {"running", "paused", "interrupted", "rate_limited"}:
                raise ValueError("此实验当前不能暂停或终止")
            action = parts[1]
            db.touch(record["id"], control=action)
            if action == "stop" and record["status"] != "running":
                db.update(record["id"], lambda r: r.update(status="stopped"))
            return present(db.merged(record["id"])), 200
        if parts[1:] == ["save-method"]:
            from gaworld.apps import organization_methods_api

            return organization_methods_api.save_study(record, payload), 201
    except LookupError as exc:
        return {"error": str(exc)}, 404
    except CooldownPending as exc:
        return {"error": str(exc), "error_info": exc.info}, 429
    except (ValueError, TypeError, KeyError) as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown endpoint"}, 404
