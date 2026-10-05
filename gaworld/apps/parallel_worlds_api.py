"""Dashboard backend for the Parallel Worlds panel.

A delegate module in the same spirit as ``population_api`` and
``external_systems_api``: ``dashboard_server`` gains six lines of forwarding
and everything else lives here.

Three points worth stating, because each was a trap:

**Path constants are read from ``world_paths`` at call time.** The
dashboard tests monkeypatch ``world_paths.REPO_ROOT`` onto a temp tree, and an
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

**Replicates are sibling experiments, not a new tree shape.** A run with
several seeds forks one ordinary experiment per seed and stamps them with a
shared ``group``; the report of any one of them pools the group. Research
studies already ran one experiment per seed (``study_<id>_s<seed>``), so
those are grouped by their id and pool the same way.

The panel itself lives in the research workbench (平行世界 tab); the
``/api/parallel-worlds/*`` routes are unchanged.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import os
import re
import threading
import time
import traceback
import uuid
from typing import Any

from gaworld.accounts import ownership
from gaworld.apps import residents, world_paths
from gaworld.logging_setup import get_logger
from gaworld.parallel import causal
from gaworld.parallel import interpret as pinterpret
from gaworld.parallel import runner as prunner
from gaworld.parallel import sweep as psweep
from gaworld.parallel.analysis import read_state_series
from gaworld.parallel.spec import ExperimentSpec, WorldSpec, normalize_experiment

_LOG = get_logger("gaworld.dashboard.parallel")

#: job id → record. One experiment runs at a time, but finished jobs are kept
#: so the panel can still show why the last one failed after it ended.
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 10
_ACTIVE: dict[str, Any] = {"job_id": None, "runner": None, "stop": None}
#: Seeds one run may replicate over; each seed is a full set of worlds.
MAX_SEEDS = 6
_STUDY_SEED_RE = re.compile(r"^(study_.+)_s(-?\d+)$")

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
                "role": "treatment",
                "dose": 1,
                "events": [{
                    "day": 2, "time": "07:00", "name": "临时交通限行",
                    "description": "早晚高峰单双号限行，通勤时间小幅增加。",
                }],
            },
            {
                "label": "重度限行",
                "role": "treatment",
                "dose": 2,
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
                "role": "placebo",
                "events": [{
                    "day": 2, "time": "10:00", "name": "市政通告",
                    "description": "市政部门发布一则例行通告，不涉及任何居民的实际生活。",
                }],
            },
        ],
    },
    {
        "id": "causal",
        "name": "严谨对照（处理 + 安慰剂 × 3 种子）",
        "note": "基准、处理、安慰剂三个世界，各跑 3 个种子：安慰剂给出噪声底线，种子给出可重复性。",
        "replicates": 3,
        "worlds": [
            {"label": "基准世界", "events": []},
            {
                "label": "裁员世界",
                "role": "treatment",
                "events": [{
                    "day": 2, "time": "09:00", "name": "大规模裁员",
                    "description": "本地主要雇主宣布裁员 20%，多个家庭收入中断。",
                }],
            },
            {
                "label": "安慰剂世界",
                "role": "placebo",
                "events": [{
                    "day": 2, "time": "09:00", "name": "市政通告",
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

    return world_paths.REPO_ROOT


def _config() -> dict[str, Any]:

    return world_paths.effective_config()


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
        "comparability_epoch": meta.get("comparability_epoch"),
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


def group_of(manifest: dict[str, Any]) -> str | None:
    """The replicate group an experiment belongs to, if any."""
    if manifest.get("group"):
        return str(manifest["group"])
    match = _STUDY_SEED_RE.match(str(manifest.get("id") or ""))
    return match.group(1) if match else None


def _siblings(group: str) -> list[dict[str, Any]]:
    """Every native manifest in ``group``, ordered by seed."""
    repo_root = _repo_root()
    found = []
    for directory in _list_dir(_experiments_root()):
        if not os.path.isdir(directory):
            continue
        manifest = prunner.load_manifest(repo_root, os.path.relpath(directory, repo_root))
        if manifest and group_of(manifest) == group:
            found.append(manifest)
    found.sort(key=lambda item: int(item.get("spec", {}).get("seed") or 0))
    return found


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
            "group": group_of(manifest),
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


def _rebased(manifest: dict[str, Any], baseline: str | None) -> dict[str, Any]:
    """The manifest with another world as the comparison, without touching disk.

    Comparing two treatments with each other (mild vs severe) is the same
    analysis with a different control; nothing has to be re-run for it.
    """
    if not baseline:
        return manifest
    spec = manifest.get("spec", {})
    if baseline not in {world.get("id") for world in spec.get("worlds", [])}:
        raise ValueError(f"对照世界 {baseline} 不在这个实验里")
    copy = dict(manifest)
    # The design's own baseline stays the reference a placebo measures noise
    # against; only the comparison moves.
    copy["spec"] = {**spec, "baseline_id": baseline, "reference_id": spec.get("baseline_id")}
    return copy


def _seed_causal(manifest: dict[str, Any], baseline: str | None) -> dict[str, Any] | None:
    """One replicate's estimates: the saved ones when they answer the same
    question, recomputed otherwise (another comparison world, or a report
    written before the estimates existed)."""
    repo_root = _repo_root()
    if not baseline:
        saved = _saved_report(repo_root, manifest["root"])
        if saved and saved.get("causal"):
            return saved["causal"]
    if not _has_data(repo_root, manifest):
        return None
    return prunner.analyze_experiment(repo_root, _rebased(manifest, baseline)).get("causal")


def _saved_report(repo_root: str, root_rel: str) -> dict[str, Any] | None:
    path = os.path.join(repo_root, root_rel, "report.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def replication(manifest: dict[str, Any], baseline: str | None = None) -> dict[str, Any] | None:
    """Pool every seed of this experiment's group, or ``None`` without one.

    Only seeds produced by the same code epoch as this experiment are pooled
    (``gaworld/core/comparability.py``): a seed run before, say, the income
    re-anchoring and one run after differ by the code change, not by chance,
    and a between-seed spread would silently absorb that. The seeds left out
    are listed in ``excluded`` so the panel can say why.
    """
    group = group_of(manifest)
    if not group:
        return None
    epoch = manifest.get("comparability_epoch")
    runs, excluded = [], []
    for sibling in _siblings(group):
        if baseline and baseline not in {w.get("id") for w in sibling.get("spec", {}).get("worlds", [])}:
            continue
        seed = sibling.get("spec", {}).get("seed")
        if sibling.get("comparability_epoch") != epoch:
            excluded.append({"seed": seed, "root": sibling["root"],
                             "comparability_epoch": sibling.get("comparability_epoch")})
            continue
        estimates = _seed_causal(sibling, baseline)
        if estimates:
            runs.append({"seed": seed, "root": sibling["root"], "causal": estimates})
    if len(runs) < 2:
        return {"group": group, "rows": [], "seeds": [], "excluded": excluded} if excluded else None
    pooled = causal.pool_replicates(runs)
    pooled["group"] = group
    if excluded:
        pooled["excluded"] = excluded
    return pooled


def experiment_report(root_rel: str, baseline: str | None = None) -> dict[str, Any]:
    """Full divergence report for one experiment, computed from disk.

    ``baseline`` re-reads the same worlds against another comparison world.
    """
    manifest = _load_any_manifest(root_rel)
    if manifest is None:
        raise ValueError(f"找不到实验：{root_rel}")
    report = prunner.analyze_experiment(_repo_root(), _rebased(manifest, baseline))
    report["legacy"] = bool(manifest.get("legacy"))
    report["status"] = manifest.get("status", "done")
    report["spec"] = manifest.get("spec", {})
    report["group"] = group_of(manifest)
    report["replication"] = None if manifest.get("legacy") else replication(manifest, baseline)
    status_map = manifest.get("world_status", {})
    for world in report.get("worlds", []):
        world.setdefault("status", status_map.get(world["id"], "done"))
    return report


def resident_attributes() -> dict[str, dict[str, str]]:
    """Groupings for the heterogeneity view, from the active world's seed CSV.

    Agent ids are only meaningful against the city the worlds ran in; this
    reads the current one, which is the one the panel just ran.
    """

    path = world_paths.state_csv_path()
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, csv.Error, UnicodeDecodeError):
        return {}
    return causal.resident_attributes(rows)


def heterogeneity(root_rel: str, world_id: str, metric: str, baseline: str | None = None) -> dict[str, Any]:
    """Conditional effects of one world on one metric, by resident attribute."""
    manifest = _load_any_manifest(root_rel)
    if manifest is None:
        raise ValueError(f"找不到实验：{root_rel}")
    manifest = _rebased(manifest, baseline)
    spec = manifest.get("spec", {})
    baseline_id = spec.get("baseline_id")
    world = next((item for item in spec.get("worlds", []) if item.get("id") == world_id), None)
    if world is None or world_id == baseline_id:
        raise ValueError(f"世界 {world_id} 不在这个实验里，或者它就是对照世界")
    repo_root = _repo_root()
    entries = manifest.get("worlds", {})
    treated = read_state_series(os.path.join(repo_root, entries[world_id]["state_csv"]), panel=True)
    control = read_state_series(os.path.join(repo_root, entries[baseline_id]["state_csv"]), panel=True)
    if not treated.get("panel") or not control.get("panel"):
        raise ValueError("这两个世界还没有状态数据")
    steps = max(treated["steps"], control["steps"])
    sim_days = spec.get("sim_days")
    t0 = causal.event_step(world, (steps / sim_days) if sim_days and steps else None, steps)
    result = causal.heterogeneity(treated["panel"], control["panel"], metric, t0, resident_attributes())
    result.update(world_id=world_id, baseline_id=baseline_id, event_step=t0)
    return result


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def overview() -> dict[str, Any]:
    config = _config()
    providers = sorted(config.get("llm", {}).get("providers", {}).keys())

    return {
        "defaults": {
            "sim_days": config.get("sim_days"),
            "agent_ids": list(config.get("agent_ids", [])),
            "seed": 42,
            "max_parallel": 2,
            "replicates": 1,
            "max_seeds": MAX_SEEDS,
            "llm_provider": config.get("llm", {}).get("routing", {}).get("default"),
        },
        "providers": providers,
        "agents": residents.agents_summary(),
        "presets": PRESETS,
        # Numeric settings a parameter sweep may vary, with their current values.
        "tunables": psweep.tunables(config),
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


def sweep(payload: dict[str, Any]) -> dict[str, Any]:
    """Expand a parameter sweep into worlds for the design form (runs nothing).

    ``{path, values, placebo, events}`` → the worlds, plus what was dropped.
    The panel puts them in the form, so the user still reviews and starts
    the experiment the usual way.
    """
    return psweep.sweep_worlds(
        _config(),
        str(payload.get("path") or ""),
        payload.get("values"),
        events=payload.get("events") if isinstance(payload.get("events"), list) else None,
        placebo=bool(payload.get("placebo")),
    )


def _plan(spec: ExperimentSpec) -> list[dict[str, Any]]:
    def describe(world: WorldSpec) -> str:
        if not world.events and not world.config:
            return "无干预（基准）"
        bits = [f"Day {item['day']} {item['time']} {item['name']}" for item in world.events]
        if world.config:
            bits.append("配置 " + "、".join(psweep.describe_patch(world.config)))
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


# ---------------------------------------------------------------------------
# Model interpretation
# ---------------------------------------------------------------------------

_INTERPRETATION_FILE = "interpretation.json"


def _interpretation_path(root_rel: str) -> str:
    return os.path.join(_repo_root(), root_rel, _INTERPRETATION_FILE)


def _read_interpretations(root_rel: str) -> dict[str, Any]:
    path = _interpretation_path(root_rel)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def saved_interpretation(root_rel: str, baseline: str | None = None) -> dict[str, Any] | None:
    """The last reading for this experiment against this comparison world.

    Keyed by comparison world because "harsh vs mild" and "harsh vs baseline"
    are different tables and deserve different paragraphs.
    """
    manifest = _load_any_manifest(root_rel)
    if manifest is None:
        raise ValueError(f"找不到实验：{root_rel}")
    key = baseline or manifest.get("spec", {}).get("baseline_id") or ""
    record = _read_interpretations(root_rel).get(key)
    return record if isinstance(record, dict) else None


def interpret_experiment(payload: dict[str, Any], llm_fn: Any = None) -> dict[str, Any]:
    """One model call over the experiment's estimates; the result is cached
    beside the experiment so reopening it does not spend another call."""
    root = str(payload.get("root") or "").strip()
    if not root:
        raise ValueError("缺少 root")
    baseline = str(payload.get("baseline") or "").strip() or None
    provider = str(payload.get("provider") or "").strip() or None
    language = "en" if str(payload.get("language") or "").startswith("en") else "zh-CN"
    report = experiment_report(root, baseline)
    if llm_fn is None:
        from gaworld.llm.providers import call_llm

        def llm_fn(prompt: str) -> str:
            return call_llm(prompt, task="research", provider=provider, max_tokens=pinterpret.INTERPRET_MAX_TOKENS)

    result = pinterpret.interpret(report, llm_fn=llm_fn, language=language)
    result.update(
        baseline_id=report["baseline_id"],
        provider=provider or "",
        language=language,
        created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    stored = _read_interpretations(root)
    stored[report["baseline_id"]] = result
    path = _interpretation_path(root)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(stored, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return result


def replicate_seeds(payload: dict[str, Any], seed: int) -> list[int]:
    """The seeds a run replicates over: ``seeds`` if given, else ``seed`` alone."""
    raw = payload.get("seeds")
    if raw in (None, "", []):
        return [seed]
    if not isinstance(raw, list):
        raise ValueError("seeds 必须是整数列表")
    seeds: list[int] = []
    for value in raw:
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError("seeds 中的元素必须是整数") from None
        if number not in seeds:
            seeds.append(number)
    if len(seeds) > MAX_SEEDS:
        raise ValueError(f"一次最多重复 {MAX_SEEDS} 个种子")
    return seeds or [seed]


def start(payload: dict[str, Any]) -> dict[str, Any]:
    """Prepare the tree and fork the worlds in a background job.

    With several ``seeds`` the job runs the same design once per seed, one
    after another (a seed is already ``max_parallel`` simulations), each as
    its own experiment in a shared replicate group.
    """
    with _JOBS_LOCK:
        active = _ACTIVE.get("job_id")
        busy = active is not None and _JOBS.get(active, {}).get("status") == "running"
    if busy:
        raise RuntimeError("已有平行世界实验在运行，请先等待它结束或停止它")

    spec = normalize_experiment(payload)
    seeds = replicate_seeds(payload, spec.seed)
    repo_root = _repo_root()
    group = f"{time.strftime('%Y%m%d_%H%M%S')}_{spec.slug}" if len(seeds) > 1 else None

    def prepare(seed: int) -> dict[str, Any]:
        return prunner.prepare_experiment(
            dataclasses.replace(spec, seed=seed),
            repo_root,
            base_config=_config(),
            experiment_id=f"{group}_s{seed}" if group else None,
            group=group,
        )

    def make_runner(manifest: dict[str, Any]) -> prunner.ExperimentRunner:
        return prunner.ExperimentRunner(
            manifest,
            repo_root,
            max_parallel=spec.max_parallel,
            reset=payload.get("reset", True),
        )

    manifest = prepare(seeds[0])
    runner = make_runner(manifest)
    stop_event = threading.Event()
    job_id = _new_job(manifest)
    _update_job(job_id, seeds=seeds, group=group, experiments=[manifest["root"]])
    with _JOBS_LOCK:
        _ACTIVE["job_id"] = job_id
        _ACTIVE["runner"] = runner
        _ACTIVE["stop"] = stop_event

    def run_all() -> dict[str, Any]:
        share = 1.0 / len(seeds)
        failed: list[dict[str, Any]] = []
        current, live = manifest, runner
        for index, seed in enumerate(seeds):
            if stop_event.is_set():
                break
            if index:
                current = prepare(seed)
                live = make_runner(current)
                with _JOBS_LOCK:
                    _ACTIVE["runner"] = live
                    record = _JOBS.get(job_id)
                    if record is not None:
                        record["experiments"] = [*record.get("experiments", []), current["root"]]
            prefix = f"种子 {seed}（{index + 1}/{len(seeds)}）：" if len(seeds) > 1 else ""

            def on_progress(progress: float, message: str, base: float = index * share, tag: str = prefix) -> None:
                _update_job(job_id, progress=base + progress * share, message=tag + message)

            report = live.run(on_progress=on_progress)
            failed += [w for w in report.get("worlds", []) if w.get("status") == "error"]
        return {"worlds": failed}

    def work() -> None:
        try:
            report = run_all()
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

    # In the caller's context: seeds after the first are prepared on this
    # thread and must resolve the same world's config as the first one.
    ownership.spawn(work, name=f"job-{job_id}")
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
        stop_event = _ACTIVE.get("stop")
    if runner is None or job_id is None:
        return {"stopped": False, "job": None}
    if stop_event is not None:
        stop_event.set()  # the seeds still queued never start
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
            return _wire_safe(experiment_report(root, first("baseline") or None)), 200
        except ValueError as exc:
            return {"error": str(exc)}, 404
    if path == "/api/parallel-worlds/heterogeneity":
        root, world, metric = first("root"), first("world"), first("metric")
        if not (root and world and metric):
            return {"error": "缺少 root / world / metric 参数"}, 400
        try:
            return _wire_safe(heterogeneity(root, world, metric, first("baseline") or None)), 200
        except ValueError as exc:
            return {"error": str(exc)}, 404
    if path == "/api/parallel-worlds/interpretation":
        root = first("root")
        if not root:
            return {"error": "缺少 root 参数"}, 400
        try:
            return _wire_safe({"interpretation": saved_interpretation(root, first("baseline") or None)}), 200
        except ValueError as exc:
            return {"error": str(exc)}, 404
    if path == "/api/parallel-worlds/job":
        record = job_status(first("id") or None)
        if record is None:
            return {"job": None}, 200
        return {"job": record}, 200
    return {"error": "Unknown endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/parallel-worlds/preview":
            return _wire_safe(preview(payload)), 200
        if path == "/api/parallel-worlds/sweep":
            return _wire_safe(sweep(payload)), 200
        if path == "/api/parallel-worlds/start":
            return _wire_safe(start(payload)), 202
        if path == "/api/parallel-worlds/stop":
            return _wire_safe(stop()), 200
        if path == "/api/parallel-worlds/interpret":
            return _wire_safe({"interpretation": interpret_experiment(payload)}), 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except RuntimeError as exc:
        return {"error": str(exc)}, 409
    return {"error": "Unknown endpoint"}, 404


def _reset_for_tests() -> None:
    with _JOBS_LOCK:
        _JOBS.clear()
        _ACTIVE["job_id"] = None
        _ACTIVE["runner"] = None
        _ACTIVE["stop"] = None


__all__ = [
    "MAX_SEEDS",
    "PRESETS",
    "experiment_report",
    "group_of",
    "handle_get",
    "handle_post",
    "heterogeneity",
    "interpret_experiment",
    "job_status",
    "list_experiments",
    "overview",
    "preview",
    "replicate_seeds",
    "replication",
    "saved_interpretation",
    "start",
    "stop",
    "sweep",
]
