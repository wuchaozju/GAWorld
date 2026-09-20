"""Dashboard backend for the Parallel Worlds panel.

A delegate module in the same spirit as ``population_api`` and
``external_systems_api``: ``dashboard_server`` gains six lines of forwarding
and everything else lives here.

Three points worth stating, because each was a trap:

**Path constants are read from ``dashboard_server`` at call time.** The
dashboard tests monkeypatch ``ds.REPO_ROOT`` onto a temp tree, and an
import-time binding would capture the real repo and write experiments into the
user's ``output/``.

**One experiment runs at a time.** A world is a full simulation; letting the
console start a second experiment while the first is still forking eight of
them would oversubscribe the machine and the LLM provider both. The panel gets
a clear 409 instead of a silently thrashing box.

**Legacy ``compare-event`` runs are adapted, not migrated.** Every existing
``output/comparisons/<ts>_<slug>/{without_event,with_event}`` tree is presented
as a two-world experiment built on the fly, so years of old counterfactuals
open in the new visualiser without anybody rewriting them on disk.
"""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
import uuid
from typing import Any

from gaworld.logging_setup import get_logger
from gaworld.parallel import runner as prunner
from gaworld.parallel.spec import ExperimentSpec, WorldSpec, normalize_experiment

_LOG = get_logger("gaworld.dashboard.parallel")

#: job id → record. One experiment runs at a time, but finished jobs are kept
#: so the panel can still show why the last one failed after it ended.
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 10
_ACTIVE: dict[str, Any] = {"job_id": None, "runner": None}

#: Starting points offered in the panel, so a first-time user has something to
#: press instead of an empty event form.
PRESETS: list[dict[str, Any]] = [
    {
        "id": "layoff",
        "name": "裁员冲击",
        "note": "同一批居民，一个世界里工厂裁员，另一个照常。",
        "worlds": [
            {"label": "基准世界", "events": []},
            {
                "label": "裁员世界",
                "events": [{
                    "day": 2,
                    "time": "09:00",
                    "name": "大规模裁员",
                    "description": "本地主要雇主宣布裁员 20%，多个家庭收入中断。",
                }],
            },
        ],
    },
    {
        "id": "traffic",
        "name": "交通限行强度",
        "note": "同一个事件的两种强度，看剂量差别。",
        "worlds": [
            {"label": "基准世界", "events": []},
            {
                "label": "轻度限行",
                "events": [{
                    "day": 2, "time": "07:00", "name": "临时交通限行",
                    "description": "早晚高峰单双号限行，通勤时间小幅增加。",
                }],
            },
            {
                "label": "重度限行",
                "events": [{
                    "day": 2, "time": "07:00", "name": "全面交通管制",
                    "description": "主干道全面管制，通勤时间显著增加，部分人无法到岗。",
                }],
            },
        ],
    },
    {
        "id": "placebo",
        "name": "安慰剂对照",
        "note": "一个无实质影响的事件，用来量化仿真本身的噪声底噪。",
        "worlds": [
            {"label": "基准世界", "events": []},
            {
                "label": "安慰剂世界",
                "events": [{
                    "day": 2, "time": "10:00", "name": "市政通告",
                    "description": "市政部门发布一则例行通告，不涉及任何居民的实际生活。",
                }],
            },
        ],
    },
]


# ---------------------------------------------------------------------------
# Repo / config access (late-bound; see module docstring)
# ---------------------------------------------------------------------------


def _repo_root() -> str:
    from gaworld.apps import dashboard_server as ds

    return ds.REPO_ROOT


def _config() -> dict[str, Any]:
    from gaworld.apps import dashboard_server as ds

    return ds._effective_config()


def _experiments_root() -> str:
    return os.path.join(_repo_root(), prunner.DEFAULT_OUTPUT_ROOT)


def _comparisons_root() -> str:
    return os.path.join(_repo_root(), "output", "comparisons")


# ---------------------------------------------------------------------------
# Job plumbing
# ---------------------------------------------------------------------------


def _new_job(manifest: dict[str, Any]) -> str:
    job_id = f"pw-{uuid.uuid4().hex[:8]}"
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "status": "running",
            "progress": 0.0,
            "message": "启动中…",
            "experiment": manifest.get("root"),
            "experiment_id": manifest.get("id"),
            "name": manifest.get("spec", {}).get("name"),
            "started_at": time.time(),
            "finished_at": None,
            "error": None,
        }
        finished = sorted(
            (record["started_at"], key)
            for key, record in _JOBS.items()
            if record["status"] != "running"
        )
        while len(_JOBS) > _MAX_JOBS and finished:
            _, oldest = finished.pop(0)
            _JOBS.pop(oldest, None)
    return job_id


def _update_job(job_id: str, **fields: Any) -> None:
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        if record is not None:
            record.update(fields)


def job_status(job_id: str | None = None) -> dict[str, Any] | None:
    """Job record plus the live per-world snapshot when it is still running."""
    with _JOBS_LOCK:
        target = job_id or _ACTIVE.get("job_id")
        record = dict(_JOBS[target]) if target in _JOBS else None
        runner = _ACTIVE.get("runner") if target == _ACTIVE.get("job_id") else None
    if record is None:
        return None
    if runner is not None:
        record["snapshot"] = runner.snapshot()
    return _wire_safe(record)


def _wire_safe(payload: Any) -> Any:
    """NaN/Infinity become null — ``JSON.parse`` rejects the bare tokens."""
    return json.loads(json.dumps(payload, ensure_ascii=False), parse_constant=lambda _: None)


# ---------------------------------------------------------------------------
# Experiment discovery
# ---------------------------------------------------------------------------


def _legacy_manifest(directory: str) -> dict[str, Any] | None:
    """Present an old ``compare-event`` output tree as a two-world experiment."""
    name = os.path.basename(directory)
    without = os.path.join(directory, "without_event")
    with_event = os.path.join(directory, "with_event")
    if not (os.path.isdir(without) and os.path.isdir(with_event)):
        return None

    meta: dict[str, Any] = {}
    meta_path = os.path.join(directory, "run_meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as handle:
                loaded = json.load(handle)
            meta = loaded if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            meta = {}

    # `20260624_012634_临时交通限行` → event name when run_meta is absent.
    parts = name.split("_", 2)
    event_name = meta.get("event_name") or (parts[2] if len(parts) > 2 else name)
    root_rel = os.path.relpath(directory, _repo_root())

    def world_entry(world_id: str) -> dict[str, Any]:
        world_rel = os.path.join(root_rel, world_id)
        return {
            "dir": world_rel,
            "overrides": {},
            "run_log": os.path.join(world_rel, "run.log"),
            "reset_log": os.path.join(world_rel, "reset.log"),
            "state_csv": os.path.join(world_rel, "state", "agent_state_history.csv"),
            "trace": os.path.join(world_rel, "visualization", "simulation_trace.json"),
        }

    return {
        "id": name,
        "root": root_rel,
        "legacy": True,
        "created_at": time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(directory))
        ),
        "status": "done",
        "spec": {
            "name": f"{event_name}（compare-event）",
            "sim_days": meta.get("sim_days"),
            "seed": meta.get("seed"),
            "llm_provider": meta.get("llm_provider"),
            "fast": bool(meta.get("fast")),
            "agent_ids": [],
            "baseline_id": "without_event",
            "worlds": [
                {"id": "without_event", "label": "无事件（基准）", "events": [], "config": {}},
                {
                    "id": "with_event",
                    "label": f"有事件 · {event_name}",
                    "events": [{
                        "day": 0, "time": "", "name": str(event_name), "description": "",
                    }],
                    "config": {},
                },
            ],
        },
        "worlds": {
            "without_event": world_entry("without_event"),
            "with_event": world_entry("with_event"),
        },
    }


def _load_any_manifest(root_rel: str) -> dict[str, Any] | None:
    """Manifest for a native experiment, or an adapter for a legacy tree."""
    repo_root = _repo_root()
    directory = os.path.join(repo_root, root_rel)
    if not os.path.isdir(directory):
        return None
    manifest = prunner.load_manifest(repo_root, root_rel)
    if manifest:
        return manifest
    return _legacy_manifest(directory)


def _list_dir(path: str) -> list[str]:
    if not os.path.isdir(path):
        return []
    return sorted(
        (os.path.join(path, name) for name in os.listdir(path)),
        key=lambda item: os.path.getmtime(item),
        reverse=True,
    )


def _has_data(repo_root: str, manifest: dict[str, Any]) -> bool:
    """True when at least two worlds actually produced a state history.

    Worth the stat() calls: ``output/comparisons`` accumulates the shells of
    runs that died before writing anything, and without this flag the panel
    opens on the newest one and shows an empty chart.
    """
    found = sum(
        1
        for entry in manifest.get("worlds", {}).values()
        if os.path.exists(os.path.join(repo_root, entry["state_csv"]))
    )
    return found >= 2


def list_experiments() -> list[dict[str, Any]]:
    """Every runnable-and-readable experiment: native first, then legacy."""
    repo_root = _repo_root()
    items: list[dict[str, Any]] = []

    for directory in _list_dir(_experiments_root()):
        if not os.path.isdir(directory):
            continue
        manifest = prunner.load_manifest(repo_root, os.path.relpath(directory, repo_root))
        if not manifest:
            continue
        spec = manifest.get("spec", {})
        items.append({
            "id": manifest.get("id"),
            "root": manifest.get("root"),
            "name": spec.get("name"),
            "created_at": manifest.get("created_at"),
            "status": manifest.get("status", "unknown"),
            "worlds": len(spec.get("worlds", [])),
            "sim_days": spec.get("sim_days"),
            "seed": spec.get("seed"),
            "has_data": _has_data(repo_root, manifest),
            "legacy": False,
        })

    for directory in _list_dir(_comparisons_root()):
        manifest = _legacy_manifest(directory) if os.path.isdir(directory) else None
        if not manifest:
            continue
        items.append({
            "id": manifest["id"],
            "root": manifest["root"],
            "name": manifest["spec"]["name"],
            "created_at": manifest["created_at"],
            "status": "done",
            "worlds": 2,
            "sim_days": manifest["spec"].get("sim_days"),
            "seed": manifest["spec"].get("seed"),
            "has_data": _has_data(repo_root, manifest),
            "legacy": True,
        })
    return items


def experiment_report(root_rel: str) -> dict[str, Any]:
    """Full divergence report for one experiment, computed from disk."""
    manifest = _load_any_manifest(root_rel)
    if manifest is None:
        raise ValueError(f"找不到实验：{root_rel}")
    report = prunner.analyze_experiment(_repo_root(), manifest)
    report["legacy"] = bool(manifest.get("legacy"))
    report["status"] = manifest.get("status", "done")
    report["spec"] = manifest.get("spec", {})
    status_map = manifest.get("world_status", {})
    for world in report.get("worlds", []):
        world.setdefault("status", status_map.get(world["id"], "done"))
    return report


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def overview() -> dict[str, Any]:
    config = _config()
    providers = sorted(config.get("llm", {}).get("providers", {}).keys())
    from gaworld.apps import dashboard_server as ds

    return {
        "defaults": {
            "sim_days": config.get("sim_days"),
            "agent_ids": list(config.get("agent_ids", [])),
            "seed": 42,
            "max_parallel": 2,
            "llm_provider": config.get("llm", {}).get("routing", {}).get("default"),
        },
        "providers": providers,
        "agents": ds._agents_summary(),
        "presets": PRESETS,
        "experiments": list_experiments(),
        "job": job_status(),
        "metric_labels": _metric_labels(),
    }


def _metric_labels() -> dict[str, str]:
    from gaworld.parallel.analysis import METRIC_LABELS

    return dict(METRIC_LABELS)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def preview(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a spec without running anything, and describe what it will do."""
    spec = normalize_experiment(payload)
    return {"spec": spec.to_dict(), "plan": _plan(spec)}


def _plan(spec: ExperimentSpec) -> list[dict[str, Any]]:
    def describe(world: WorldSpec) -> str:
        if not world.events and not world.config:
            return "无干预（基准）"
        bits = [f"Day {item['day']} {item['time']} {item['name']}" for item in world.events]
        if world.config:
            bits.append(f"配置改动 {len(world.config)} 项")
        return "；".join(bits)

    return [
        {
            "id": world.id,
            "label": world.label,
            "is_baseline": world.id == spec.baseline_id,
            "summary": describe(world),
            "events": len(world.events),
        }
        for world in spec.worlds
    ]


def start(payload: dict[str, Any]) -> dict[str, Any]:
    """Prepare the tree and fork the worlds in a background job."""
    with _JOBS_LOCK:
        active = _ACTIVE.get("job_id")
        busy = active is not None and _JOBS.get(active, {}).get("status") == "running"
    if busy:
        raise RuntimeError("已有平行世界实验在运行，请先等待它结束或停止它")

    spec = normalize_experiment(payload)
    repo_root = _repo_root()
    manifest = prunner.prepare_experiment(spec, repo_root, base_config=_config())
    runner = prunner.ExperimentRunner(
        manifest,
        repo_root,
        max_parallel=spec.max_parallel,
        reset=payload.get("reset", True),
    )
    job_id = _new_job(manifest)
    with _JOBS_LOCK:
        _ACTIVE["job_id"] = job_id
        _ACTIVE["runner"] = runner

    def work() -> None:
        try:
            report = runner.run(
                on_progress=lambda progress, message: _update_job(
                    job_id, progress=progress, message=message
                )
            )
            failed = [w for w in report.get("worlds", []) if w.get("status") == "error"]
            _update_job(
                job_id,
                status="error" if failed else "done",
                progress=1.0,
                message=(
                    f"{len(failed)} 个世界运行失败" if failed else "全部世界完成"
                ),
                error=(failed[0].get("error") if failed else None),
                finished_at=time.time(),
            )
        except Exception as exc:  # noqa: BLE001 — HTTP job boundary
            _LOG.exception("parallel-worlds job %s failed", job_id)
            _update_job(
                job_id,
                status="error",
                message=str(exc),
                error=traceback.format_exc(limit=5),
                finished_at=time.time(),
            )

    threading.Thread(target=work, name=f"job-{job_id}", daemon=True).start()
    return {
        "job_id": job_id,
        "experiment": manifest["root"],
        "spec": manifest["spec"],
        "job": job_status(job_id),
    }


def stop() -> dict[str, Any]:
    with _JOBS_LOCK:
        job_id = _ACTIVE.get("job_id")
        runner = _ACTIVE.get("runner")
    if runner is None or job_id is None:
        return {"stopped": False, "job": None}
    runner.stop()
    _update_job(job_id, status="stopped", message="已手动停止", finished_at=time.time())
    return {"stopped": True, "job": job_status(job_id)}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    query = query or {}

    def first(name: str) -> str:
        values = query.get(name) or []
        return str(values[0]) if values else ""

    if path == "/api/parallel-worlds/overview":
        return _wire_safe(overview()), 200
    if path == "/api/parallel-worlds/experiments":
        return {"experiments": list_experiments()}, 200
    if path == "/api/parallel-worlds/experiment":
        root = first("root")
        if not root:
            return {"error": "缺少 root 参数"}, 400
        try:
            return _wire_safe(experiment_report(root)), 200
        except ValueError as exc:
            return {"error": str(exc)}, 404
    if path == "/api/parallel-worlds/job":
        record = job_status(first("id") or None)
        if record is None:
            return {"job": None}, 200
        return {"job": record}, 200
    return {"error": "Unknown parallel-worlds endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/parallel-worlds/preview":
            return _wire_safe(preview(payload)), 200
        if path == "/api/parallel-worlds/start":
            return _wire_safe(start(payload)), 200
        if path == "/api/parallel-worlds/stop":
            return _wire_safe(stop()), 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except RuntimeError as exc:
        return {"error": str(exc)}, 409
    return {"error": "Unknown parallel-worlds endpoint"}, 404


def _reset_for_tests() -> None:
    with _JOBS_LOCK:
        _JOBS.clear()
        _ACTIVE["job_id"] = None
        _ACTIVE["runner"] = None


__all__ = [
    "PRESETS",
    "experiment_report",
    "handle_get",
    "handle_post",
    "job_status",
    "list_experiments",
    "overview",
    "preview",
    "start",
    "stop",
]
