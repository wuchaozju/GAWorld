"""Sequential batch coordinator reusing ordinary study admission and controls."""

from __future__ import annotations

import copy
import threading
import time
from typing import Any

from gaworld.accounts import ownership
from gaworld.research import batches, study
from gaworld.research.progress import RunTiming


def _api() -> Any:
    from gaworld.apps import research_batches_api

    return research_batches_api


def _safe_error(exc: Exception) -> str:
    from gaworld.research.run_logs import configured_secrets, redact

    return redact(str(exc), configured_secrets(_api()._research()._base_config()))


def capture(record: dict[str, Any], cell: dict[str, Any], child: study.Study) -> dict[str, Any]:
    runtime = child.runtime or {}
    epochs = set((child.evaluation.get("comparability", {}).get("epochs") or {}).values())
    entry = record["inputs"][cell["city"]]
    sample_hash = batches.digest(
        {
            "csv": runtime.get("seed_identity", {}).get("sha256"),
            "agent_ids": sorted(runtime.get("actual_agent_ids") or []),
        }
    )
    complete = bool(child.runs) and all(
        run.get("status") == "done"
        and set(run.get("world_status") or {}) == {c["id"] for c in child.protocol["conditions"]}
        and all(value == "done" for value in (run.get("world_status") or {}).values())
        for run in child.runs
    )
    comparability = child.evaluation.get("comparability") or {}
    complete = complete and not comparability.get("mixed") and not comparability.get("mixed_runtime")
    if child.protocol.get("kind") == "composite":
        from gaworld.research.survey import survey_measures

        required = set(survey_measures(child.protocol.get("survey") or {}))
        expected = len(child.protocol.get("sample", {}).get("agent_ids") or [])
        for run in child.runs:
            answers = run.get("survey") or {}
            for condition in child.protocol["conditions"]:
                block = answers.get(condition["id"]) or {}
                scores = block.get("scores") or {}
                complete = complete and bool(scores) and not block.get("error") and required <= scores.keys()
                complete = complete and all(
                    score.get("n") == expected and not score.get("unparsed") for score in scores.values()
                )
    return {
        "protocol_hash": batches.protocol_hash(child.protocol),
        "provider": runtime.get("actual_provider"),
        "model": runtime.get("actual_model"),
        "mode": child.evaluation.get("execution_mode"),
        "epoch": next(iter(epochs)) if len(epochs) == 1 else None,
        "sample_hash": sample_hash,
        "model_config_hash": record["model_fingerprints"][cell["provider"]],
        "valid": child.stage == "reported" and complete and sample_hash == entry["sample_hash"],
        "hypotheses": copy.deepcopy(child.evaluation.get("hypotheses") or []),
        "telemetry": runtime.get("telemetry") or {},
    }


def start(record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    api = _api()
    batch_id = record["id"]
    if batch_id in api._ACTIVE:
        raise ValueError("批次已在运行")
    mine = sum(handle["owner_id"] == record.get("owner_id") for handle in api._ACTIVE.values())
    if len(api._ACTIVE) >= 4 or mine >= 2:
        raise api._research().StudyBusy("批次并发上限已达到，请等待或停止一项批次")
    check = api.preflight(record)
    record["preflight"] = check
    if not check["ok"]:
        batches.save(record)
        raise ValueError("跑前检查没有通过：" + "；".join(check["errors"]))
    for cell in record["cells"]:
        if cell["status"] in {"cancelled", "queued"}:
            cell["status"] = "pending"
        if payload.get("retry_failed") is True and cell["status"] in {"failed", "interrupted", "stopped"}:
            if cell.get("study_id"):
                cell["history"].append(cell["study_id"])
            for key in ("result", "job_id", "error", "study_id"):
                cell.pop(key, None)
            cell["status"] = "pending"
    if not any(c["status"] == "pending" for c in record["cells"]):
        raise ValueError("没有待运行任务；如需重试失败任务，请明确选择 retry_failed")
    handle = {
        "stop": threading.Event(),
        "pause": threading.Event(),
        "timing": RunTiming(),
        "owner_id": record.get("owner_id"),
        "current_study": "",
    }
    api._ACTIVE[batch_id] = handle
    record["status"] = "running"
    batches.save(record)
    ownership.spawn(run, batch_id, handle, name=f"research-batch-{batch_id}")
    return {"batch_id": batch_id, "status": "running"}


def control(record: dict[str, Any], action: str) -> dict[str, Any]:
    api = _api()
    handle = api._ACTIVE.get(record["id"])
    if not handle:
        raise ValueError("批次没有正在运行的任务")
    if action == "pause":
        handle["pause"].set()
        handle["timing"].set_paused(True)
        record["status"] = "paused"
    elif action == "resume":
        if handle["stop"].is_set():
            raise ValueError("批次正在停止，不能继续")
        handle["pause"].clear()
        handle["timing"].set_paused(False)
        record["status"] = "running"
    else:
        handle["stop"].set()
        handle["pause"].clear()
        handle["timing"].set_paused(False)
        record["status"] = "stopping"
    current = handle["current_study"]
    if current:
        try:
            {
                "pause": api._research().pause_study,
                "resume": api._research().resume_study,
                "stop": api._research().stop_study,
            }[action](current)
        except ValueError:
            # It may have finished between the control click and this boundary.
            if api._research()._is_live(current):
                raise
    batches.save(record)
    return {"batch_id": record["id"], "status": record["status"]}


def run(batch_id: str, handle: dict[str, Any]) -> None:
    api = _api()
    research = api._research()
    try:
        while not handle["stop"].is_set():
            if handle["pause"].is_set():
                handle["stop"].wait(0.2)
                continue
            with api._LOCK:
                record = batches.load(batch_id)
                cell = next((c for c in record["cells"] if c["status"] == "pending"), None)
                if not cell:
                    break
                cell_id = cell["id"]
                try:
                    config = api.cell_config(record, cell)
                    protocol = api.cell_protocol(record, cell)
                    child = study.new_study(
                        {"id": record["protocol"].get("plan_id", ""), "title": record["title"]},
                        protocol.to_dict(),
                        {},
                        provider=cell["provider"],
                    )
                    child.owner_id = record.get("owner_id")
                    child.owner = record.get("owner", "")
                    child.world_id = record.get("world_id")
                    child.parent_study_id = record["source_study_id"]
                    child.protocol_changes = {"batch_id": batch_id, "cell_id": cell_id}
                    child.preflight = research._preflight(protocol, base_config=config)
                    if not child.preflight["ok"]:
                        raise ValueError("；".join(child.preflight["errors"]))
                    child.set_stage("approved")
                    study.save_study(child)
                    if cell.get("study_id"):
                        cell["history"].append(cell["study_id"])
                    cell.update(study_id=child.id, status="queued")
                    batches.save(record)
                except Exception as exc:
                    cell.update(status="failed", error=_safe_error(exc))
                    batches.save(record)
                    continue
            job_id = ""
            while not handle["stop"].is_set():
                with api._LOCK:
                    if not handle["pause"].is_set():
                        try:
                            job_id = research._launch_run(child.id, base_config=config)
                            handle["current_study"] = child.id
                            record = batches.load(batch_id)
                            next(c for c in record["cells"] if c["id"] == cell_id).update(
                                status="running", job_id=job_id
                            )
                            batches.save(record)
                            break
                        except research.StudyBusy:
                            pass
                        except Exception as exc:
                            record = batches.load(batch_id)
                            next(c for c in record["cells"] if c["id"] == cell_id).update(
                                status="failed", error=_safe_error(exc)
                            )
                            batches.save(record)
                            break
                handle["stop"].wait(0.3)
            if not job_id:
                continue
            while True:
                job = research.job_status(job_id) or {}
                if job.get("status") != "running":
                    break
                time.sleep(0.2)
            with api._LOCK:
                handle["current_study"] = ""
                record = batches.load(batch_id)
                cell = next(c for c in record["cells"] if c["id"] == cell_id)
                finished = study.load_study(child.id)
                cell.update(
                    status="done"
                    if finished.stage == "reported"
                    else "stopped"
                    if handle["stop"].is_set()
                    else "failed",
                    result=capture(record, cell, finished),
                    error=finished.error,
                )
                if not cell["result"]["valid"] and cell["status"] == "done":
                    cell.update(
                        status="failed", error="运行不完整或输入身份不一致，保留结果但不纳入稳健性统计"
                    )
                batches.save(record)
    except Exception as exc:
        with api._LOCK:
            record = batches.load(batch_id)
            record["error"] = _safe_error(exc)
            batches.save(record)
    finally:
        with api._LOCK:
            record = batches.load(batch_id)
            for cell in record["cells"]:
                if cell["status"] in {"pending", "queued"} and handle["stop"].is_set():
                    cell["status"] = "cancelled"
                elif cell["status"] in {"running", "queued"}:
                    cell.update(status="interrupted", error="批次执行中断")
            record["status"] = (
                "stopped"
                if handle["stop"].is_set()
                else "done"
                if all(c["status"] == "done" for c in record["cells"])
                else "partial"
            )
            handle["timing"].finish()
            completed = sum(c["status"] == "done" for c in record["cells"])
            record["timing"] = handle["timing"].snapshot(completed / len(record["cells"]))
            batches.save(record)
            api._ACTIVE.pop(batch_id, None)
