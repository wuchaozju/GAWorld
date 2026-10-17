"""Workspace-private model/city/repetition batches; no global city switching."""

from __future__ import annotations

import copy
import shutil
import threading
from typing import Any

from gaworld.city.bundle import list_cities, resolve_city
from gaworld.city.config import city_overrides
from gaworld.core.comparability import CURRENT_EPOCH
from gaworld.research import batch_compare, batch_inputs, batches, workspaces
from gaworld.research.editing import protocol_edit
from gaworld.research.protocol import DEFAULT_CALL_BUDGET, Protocol
from gaworld.settings.overrides import deep_update

_LOCK = threading.RLock()
_ACTIVE: dict[str, dict[str, Any]] = {}
PREFIX = "/api/research/batches"


def _research() -> Any:
    from gaworld.apps import research_api

    return research_api


def read(batch_id: str) -> dict[str, Any]:
    record = batches.load(batch_id)
    if not workspaces.visible(record):
        raise LookupError("找不到此批次")
    if record["status"] in {"running", "paused", "stopping"} and batch_id not in _ACTIVE:
        record["status"] = "interrupted"
        for cell in record["cells"]:
            if cell["status"] in {"running", "queued"}:
                cell.update(status="interrupted", error="服务重启或批次执行中断，保留原子研究")
        batches.save(record)
    return record


def cell_protocol(record: dict[str, Any], cell: dict[str, Any]) -> Protocol:
    data = copy.deepcopy(record["protocol"])
    entry = record["inputs"][cell["city"]]
    data["sim_provider"] = cell["provider"]
    data.setdefault("validity", {})["seeds"] = [cell["seed"]]
    data["sample"] = {
        "city": entry["city"],
        "agent_ids": entry["agent_ids"],
        "seed_identity": {"city": entry["city"], "sha256": entry["assets"]["csv_path"]["sha256"]},
    }
    return Protocol.from_dict(data)


def cell_config(record: dict[str, Any], cell: dict[str, Any]) -> dict[str, Any]:
    config = batch_inputs.materialize(_research()._base_config(), record["inputs"][cell["city"]])
    provider = (config.get("llm", {}).get("providers") or {}).get(cell["provider"])
    if (
        not provider
        or batch_inputs.public_model(provider) != record["models"][cell["provider"]]
        or batch_inputs.model_fingerprint(provider) != record["model_fingerprints"][cell["provider"]]
    ):
        raise ValueError("模型配置已变化或本机缺少对应模型，请恢复配置或创建新批次")
    return config


def preflight(record: dict[str, Any]) -> dict[str, Any]:
    from gaworld.research.provider_check import inspect_provider

    errors, warnings, checks = [], [], []
    provider_checks = {}
    total = 0
    if record["epoch"] != CURRENT_EPOCH:
        errors.append("实验包的代码可比性版本与本机不同，请使用对应版本的 GAWorld")
    base = _research()._base_config()
    for provider in record["matrix"]["providers"]:
        result = inspect_provider(base, provider, local=True)
        provider_checks[provider] = result
        if result["status"] in {"unconfigured", "missing_key", "connection_failed", "model_missing"}:
            errors.append(f"模型 {provider}: {result['status']}")
    if any((base.get(key) or {}).get("enabled") for key in ("news", "city_news", "real_work")):
        warnings.append("外部新闻、网络及真实工作数据可能随时间变化；冻结配置不能保证外部数据完全复现。")
    for cell in record["cells"]:
        try:
            config = cell_config(record, cell)
            protocol = cell_protocol(record, cell)
            _research()._check_runtime_compatibility(
                type("Candidate", (), {"protocol": protocol.to_dict()})(), config
            )
            check = _research()._preflight(protocol, base_config=config)
            total += check["budget"]["estimated_calls"]
            errors.extend(f"{cell['id']}: {error}" for error in check["errors"])
            warnings.extend(check["warnings"])
            checks.append({"cell_id": cell["id"], **check})
        except (ValueError, OSError) as exc:
            errors.append(f"{cell['id']}: {exc}")
    limit = int(
        (_research()._base_config().get("research_workbench") or {}).get(
            "batch_call_budget", DEFAULT_CALL_BUDGET
        )
    )
    if total > limit:
        errors.append(f"批次估算调用量 {total:,} 超过上限 {limit:,}，请减少重复次数、样本或天数")
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": list(dict.fromkeys(warnings)),
        "estimated_calls": total,
        "limit": limit,
        "tasks": len(record["cells"]),
        "worlds": len(record["cells"]) * len(record["protocol"]["conditions"]),
        "checks": checks,
        "provider_checks": provider_checks,
    }


def create(payload: dict[str, Any]) -> dict[str, Any]:
    source = _research()._load_study(str(payload.get("study_id") or ""))
    protocol = protocol_edit(Protocol.from_dict(source.protocol).to_dict(), {}).to_dict()
    batch_inputs.validate_portable_protocol(protocol)
    record = batches.new(protocol, payload, source_id=source.id)
    config = _research()._base_config()
    providers = (config.get("llm") or {}).get("providers") or {}
    if any(name not in providers for name in record["matrix"]["providers"]):
        raise ValueError("批次包含未配置的模型")
    record["models"] = {
        name: batch_inputs.public_model(providers[name]) for name in record["matrix"]["providers"]
    }
    record["model_fingerprints"] = {
        name: batch_inputs.model_fingerprint(providers[name]) for name in record["matrix"]["providers"]
    }
    record["epoch"] = CURRENT_EPOCH
    record["sample_size"] = payload.get("sample_size", len(protocol["sample"].get("agent_ids") or []))
    if type(record["sample_size"]) is not int or not 0 <= record["sample_size"] <= 100_000:
        raise ValueError("每城样本数须为 0–100000 的整数（0 表示全体）")
    try:
        for index, city in enumerate(record["matrix"]["cities"]):
            selected_config = copy.deepcopy(config)
            if city:
                try:
                    bundle = resolve_city(city, _research()._repo_root())
                except LookupError as exc:
                    raise ValueError("所选城市不存在") from exc
                if not bundle.state_csv_path.is_file():
                    raise ValueError("所选城市没有居民 CSV")
                deep_update(selected_config, city_overrides(bundle.slug, _research()._repo_root()))
                selected_config["agent_ids"] = []
            record["inputs"][city] = batch_inputs.snapshot(
                selected_config,
                record["id"],
                city,
                index,
                _research()._repo_root(),
                agent_ids=protocol["sample"].get("agent_ids")
                if not city and "sample_size" not in payload
                else None,
                sample_size=record["sample_size"],
                seed=record["matrix"]["seed"],
            )
        record["preflight"] = preflight(record)
        batches.save(record)
    except Exception:
        shutil.rmtree(batches.directory(record["id"]), ignore_errors=True)
        raise
    return record


def detail(record: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(record)
    active = _ACTIVE.get(record["id"])
    completed = sum(c["status"] in {"done", "failed", "interrupted", "stopped"} for c in record["cells"])
    progress = completed / len(record["cells"])
    if active:
        current = next((c for c in result["cells"] if c["status"] == "running"), None)
        if current and current.get("job_id"):
            job = _research().job_status(current["job_id"]) or {}
            current["run_status"] = job
            progress += float(job.get("progress") or 0) / len(record["cells"])
        result["timing"] = active["timing"].snapshot(progress)
    result["progress"] = progress
    result["comparison"] = batch_compare.compare(record)
    return result


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    try:
        with _LOCK:
            if path == PREFIX:
                return {"batches": batches.listing()}, 200
            if path == PREFIX + "/context":
                return {
                    "providers": _research()._providers(),
                    "cities": [c.summary() for c in list_cities(_research()._repo_root())],
                    "max_cells": batches.MAX_CELLS,
                    "max_repeats": batches.MAX_REPEATS,
                }, 200
            parts = path[len(PREFIX) :].strip("/").split("/")
            record = read(parts[0])
            if len(parts) == 1:
                return detail(record), 200
            if parts[1:] == ["report"]:
                comparison = batch_compare.compare(record)
                return {
                    "filename": record["id"] + "-report.md",
                    "markdown": batch_compare.markdown(record, comparison),
                }, 200
            if parts[1:] == ["export"]:
                from gaworld.research.batch_export import export_zip

                return export_zip(record), 200
    except (LookupError, _research().StudyNotFound):
        return {"error": "Unknown batch"}, 404
    except (ValueError, OSError) as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    from gaworld.research import batch_execution

    if not isinstance(payload, dict):
        return {"error": "请求内容须为对象"}, 400
    try:
        with _LOCK:
            if path == PREFIX:
                return create(payload), 201
            if path == PREFIX + "/import":
                from gaworld.research.batch_export import import_bundle

                return import_bundle(payload), 201
            parts = path[len(PREFIX) :].strip("/").split("/")
            record = read(parts[0])
            if parts[1:] == ["compare"]:
                return batch_compare.compare(record, payload.get("cells")), 200
            if parts[1:] == ["run"]:
                return batch_execution.start(record, payload), 202
            if len(parts) == 2 and parts[1] in {"pause", "resume", "stop"}:
                return batch_execution.control(record, parts[1]), 200
    except (LookupError, _research().StudyNotFound):
        return {"error": "Unknown batch or study"}, 404
    except _research().StudyBusy as exc:
        return {"error": str(exc)}, 409
    except PermissionError as exc:
        return {"error": str(exc)}, 403
    except (ValueError, OSError) as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown endpoint"}, 404
