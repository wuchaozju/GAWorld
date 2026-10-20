"""Frozen organization-intelligence studies with explicit launch and audit trails."""

from __future__ import annotations

import copy
import csv
import fcntl
import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path

from gaworld.accounts import ownership, usage
from gaworld.apps import research_api, world_paths
from gaworld.llm.run_state import RunLedger, ledger_context
from gaworld.research import workspaces
from gaworld.research.organization_intelligence import analysis, experiment, protocol, store
from gaworld.research.progress import RunTiming
from gaworld.research.run_logs import configured_secrets, redact

PREFIX = "/api/research/organization-intelligence"
_ACTIVE = {}
_LOCK = threading.RLock()


class Stopped(Exception):
    """Cooperative stop between requests, including immediately after a response."""


def population():
    from gaworld.interview.roster import _jobs_by_id

    jobs = _jobs_by_id(Path(world_paths.profile_path()))
    people = []
    with open(world_paths.state_csv_path(), encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                identifier = int(row.get("id") or row.get("agent_id") or "")
                age = int(float(row.get("age") or 0))
            except ValueError:
                continue
            people.append(
                {
                    "id": identifier,
                    "name": row.get("name", ""),
                    "age": age,
                    "gender": row.get("gender", ""),
                    "job": jobs.get(identifier, "")[:500],
                }
            )
    return people


def model_info(name=""):
    config = research_api._base_config()
    llm = config.get("llm") or {}
    name = name or (llm.get("routing") or {}).get("default", "")
    settings = (llm.get("providers") or {}).get(name)
    if not isinstance(settings, dict) or not settings.get("model"):
        raise ValueError("选择的模型不存在或未配置；不会自动切换模型")
    # Hash safe generation and endpoint settings, never persist credentials or headers.
    safe = {
        k: v
        for k, v in settings.items()
        if k
        in {
            "type",
            "model",
            "base_url",
            "url",
            "temperature",
            "top_p",
            "top_k",
            "seed",
            "max_tokens",
            "num_ctx",
            "think",
            "thinking",
            "reasoning_effort",
            "system",
            "stream",
            "timeout",
        }
    }
    return {
        "name": name,
        "type": settings.get("type"),
        "model": settings["model"],
        "fingerprint": protocol.digest(safe),
    }


def code_hashes():
    paths = [Path(module.__file__) for module in (protocol, experiment, analysis)] + [Path(__file__)]
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def make_caller(spec):
    from gaworld.llm.providers import LLMRouter

    name = spec["model"]["name"]
    if model_info(name) != spec["model"]:
        raise ValueError("模型配置与冻结协议不同，请创建新研究")
    settings = copy.deepcopy(research_api._base_config()["llm"]["providers"][name])
    settings["authorization_retry_schemes"] = []
    router = LLMRouter({"llm": {"providers": {name: settings}, "routing": {"default": name}}})
    router.providers[name].attempts = 1

    def call(prompt):
        try:
            return router.call(
                prompt,
                task="research.organization_intelligence",
                provider=name,
                allow_fallback=False,
                temperature=spec["temperature"],
                max_tokens=spec["max_tokens"],
            )
        finally:
            usage.record("research.organization_intelligence")

    return call


def create(payload):
    payload = dict(payload)
    payload["city"] = str(research_api._base_config().get("city") or "")
    spec = protocol.freeze(payload, population(), model_info(str(payload.get("provider") or "")))
    record = {
        "id": "OI" + uuid.uuid4().hex[:24],
        "status": "draft",
        "created_at": time.time(),
        "protocol": spec,
        "protocol_hash": protocol.digest(spec),
        "code_hashes": code_hashes(),
        "rows": [],
        "archives": [],
        "calls_completed": 0,
        "calls_started": 0,
        "input_chars": 0,
        "output_chars": 0,
        **workspaces.stamp(),
    }
    store.save(record)
    store.atomic(
        store.directory(record["id"]) / "protocol.json", json.dumps(spec, ensure_ascii=False, indent=2)
    )
    return record


def heal(record):
    if record["status"] == "running" and (store.directory(record["id"]) / "stop.request").exists():
        record = {**record, "status": "stopping"}
    if record["status"] not in {"running", "stopping"} or record["id"] in _ACTIVE:
        return record
    pid = record.get("runner_pid")
    try:
        if not pid or pid == os.getpid():
            raise ProcessLookupError
        os.kill(pid, 0)
    except ProcessLookupError:
        record.update(status="interrupted", error="执行进程已结束；保留已有证据，需新建研究后重新运行")
        store.save(record)
    except PermissionError:
        pass
    return record


def launch(record):
    with _LOCK:
        record = store.load(record["id"])
        if record["status"] != "draft":
            raise ValueError("仅可启动未运行的冻结协议；重做研究请新建记录")
        spec = record["protocol"]
        frozen = json.loads((store.directory(record["id"]) / "protocol.json").read_text(encoding="utf-8"))
        if protocol.digest(spec) != record["protocol_hash"] or frozen != spec:
            raise ValueError("冻结协议校验失败")
        if model_info(spec["model"]["name"]) != spec["model"]:
            raise ValueError("模型配置已变化，请创建新研究")
        if code_hashes() != record["code_hashes"]:
            raise ValueError("实验代码已变化，请创建新研究")
        if len(_ACTIVE) >= 2:
            raise ValueError("最多同时执行两项组织智能研究")
        caller = make_caller(spec)
        lock = (store.directory(record["id"]) / "run.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lock.close()
            raise ValueError("研究已由另一个进程启动") from exc
        if store.load(record["id"])["status"] != "draft":
            lock.close()
            raise ValueError("研究已由另一个进程启动或完成")
        handle = {"stop": threading.Event(), "timing": RunTiming(), "lock": lock}
        _ACTIVE[record["id"]] = handle
        record.update(status="running", runner_pid=os.getpid(), started_at=time.time())
        try:
            store.save(record)
            ownership.spawn(execute, record, handle, caller, name=f"organization-{record['id']}")
        except Exception:
            _ACTIVE.pop(record["id"], None)
            lock.close()
            record.update(status="failed", error="无法创建执行线程")
            store.save(record)
            raise
        return {"id": record["id"], "status": "running"}


def execute(record, handle, caller):
    try:
        _execute(record, handle, caller)
    except Exception as exc:
        # This outer guard also covers ledger initialization and final artifact IO.
        record.update(
            status="failed", error=f"记录初始化或保存失败：{type(exc).__name__}", finished_at=time.time()
        )
        handle["timing"].finish()
        try:
            store.save(record)
        except OSError:
            pass  # A later read heals the orphan if the filesystem recovers.
    finally:
        handle["lock"].close()
        with _LOCK:
            _ACTIVE.pop(record["id"], None)


def _execute(record, handle, caller):
    identifier = record["id"]
    directory = store.directory(identifier)
    ledger = RunLedger(str(directory / "providers.sqlite"))
    secrets = configured_secrets(research_api._base_config())

    def checkpoint():
        if handle["stop"].is_set() or (directory / "stop.request").exists():
            raise Stopped

    def persist():
        fraction = record["calls_completed"] / record["protocol"]["budget"]["requests"]
        record.update(handle["timing"].snapshot(fraction), progress=fraction, telemetry=ledger.snapshot())
        record["updated_at"] = time.time()
        store.save(record)

    def before(event):
        checkpoint()
        record["calls_started"] = event["number"]
        record["current"] = {k: event["request"][k] for k in ("block", "arm", "phase", "step")}
        store.event(identifier, {"kind": "request", **event})
        persist()

    def after(event):
        # Model errors never put credentials into user-facing logs.
        if "error" in event:
            event["error"] = redact(event["error"], secrets)
        store.event(identifier, {"kind": "response", **event})
        record["calls_completed"] = event["number"]
        record["input_chars"] += len(event["prompt"])
        record["output_chars"] += len(event.get("raw", ""))
        record["last_call_status"] = event["status"]
        persist()
        checkpoint()

    def row(value):
        record["rows"].append(value)
        persist()

    def state(value):
        record["archives"].append(value)
        persist()

    try:
        with ledger_context(str(directory / "providers.sqlite")):
            experiment.run(record["protocol"], caller, after, row, state, before)
        record["status"] = "completed"
    except Stopped:
        record["status"] = "stopped"
    except Exception as exc:
        record.update(status="failed", error=redact(f"{type(exc).__name__}: {exc}", secrets))
    finally:
        handle["timing"].finish()
        record["finished_at"] = time.time()
        record["analysis"] = analysis.evaluate(record["rows"], record["protocol"]["repeats"])
        persist()
        store.atomic(directory / "report.md", analysis.report(record))


def handle_get(path, query=None):
    parts = [p for p in path[len(PREFIX) :].split("/") if p]
    try:
        if not parts:
            records = workspaces.owned(store.records())
            summaries = [
                {k: heal(r).get(k) for k in ("id", "status", "created_at", "calls_completed", "progress")}
                for r in records
            ]
            config = research_api._base_config()
            names = (config.get("llm") or {}).get("providers") or {}
            providers = [model_info(n) for n in names]
            return {
                "title": protocol.TITLE,
                "studies": summaries,
                "providers": providers,
                "default_provider": (config.get("llm") or {}).get("routing", {}).get("default", ""),
                "city": config.get("city") or "当前世界",
                "planned_calls": 327,
            }, 200
        record = store.load(parts[0])
        if not workspaces.visible(record):
            return {"error": "找不到研究"}, 404
        record = heal(record)
        if len(parts) == 1:
            handle = _ACTIVE.get(record["id"])
            if handle:
                record.update(handle["timing"].snapshot(record.get("progress", 0)))
            return record, 200
        if parts[1:] == ["export"]:
            return {"filename": f"{record['id']}.md", "markdown": analysis.report(record)}, 200
        if parts[1:] == ["logs"]:
            offset = (query or {}).get("offset", [0])
            offset = int(offset[0] if isinstance(offset, list) else offset)
            return store.log_chunk(record["id"], max(0, offset)), 200
    except (ValueError, OSError) as exc:
        return {"error": redact(str(exc))}, 400
    return {"error": "Unknown endpoint"}, 404


def handle_post(path, payload):
    parts = [p for p in path[len(PREFIX) :].split("/") if p]
    try:
        if not isinstance(payload, dict):
            raise ValueError("需要JSON对象")
        if not parts:
            return create(payload), 201
        record = store.load(parts[0])
        if not workspaces.visible(record):
            return {"error": "找不到研究"}, 404
        if parts[1:] == ["run"]:
            return launch(record), 202
        if parts[1:] == ["stop"]:
            if record["status"] not in {"running", "stopping"}:
                raise ValueError("研究没有正在运行的请求")
            store.atomic(store.directory(record["id"]) / "stop.request", "stop\n")
            with _LOCK:
                if record["id"] in _ACTIVE:
                    _ACTIVE[record["id"]]["stop"].set()
            return {"id": record["id"], "status": "stopping"}, 200
    except (ValueError, OSError) as exc:
        return {"error": redact(str(exc), configured_secrets(research_api._base_config()))}, 400
    return {"error": "Unknown endpoint"}, 404
