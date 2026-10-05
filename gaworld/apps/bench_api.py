"""HTTP surface for the benchmark harnesses in ``benchmark/``.

Both harnesses are CLIs that write fixed result files, so a run is a
subprocess job, one at a time: ``gaworld_bench.py`` always writes
``benchmark/results/scorecard.json``, and two concurrent runs would overwrite
each other's scorecard. When a job finishes its scorecard is copied into the
job record, so the result of *this* job survives the next run.

A ``--synthetic`` run writes under ``benchmark/results/synthetic/`` instead, so
the headline card (``/api/bench/scorecard``) and the report list only ever
show runs over real simulator output.

Only whitelisted options are forwarded, and path options must stay inside the
repo: the payload becomes a command line.

Track R's human anchor calibration (``benchmark/rubric/calibration.py``) is
the one part served in-process: building a set, storing labels and computing
the agreement are file reads and arithmetic, and the annotation page needs
them one task at a time. Judging a set spends model calls, so it is a job like
the others (``kind="calibration"``). The task list never carries the key —
which samples were corrupted, what the rule scored — so annotators stay blind.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from gaworld.accounts import ownership
from gaworld.apps import world_paths

_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_MAX_JOBS = 20
_LOG_TAIL = 4000

#: kind -> (script, results file, {payload key: (flag, type)}). ``bool`` keys
#: become bare flags; ``"path"`` keys are resolved against the repo root.
HARNESSES: dict[str, tuple[str, str, dict[str, tuple[str, Any]]]] = {
    "bench": (
        "gaworld_bench.py",
        "scorecard.json",
        {
            "track": ("--track", str),
            "all": ("--all", bool),
            "synthetic": ("--synthetic", bool),
            "output_dir": ("--output-dir", "path"),
            "games_dir": ("--games-dir", "path"),
            "comparisons_root": ("--comparisons-root", "path"),
            "run": ("--run", bool),
            "days": ("--days", int),
            "seed": ("--seed", int),
            "seeds": ("--seeds", str),
            "resume": ("--continue", bool),
            "fast": ("--fast", bool),
            "llm_provider": ("--llm-provider", str),
        },
    ),
    "rubric": (
        "rubric_bench.py",
        "rubric_scorecard.json",
        {
            "output_dir": ("--output-dir", "path"),
            "synthetic": ("--synthetic", bool),
            "synthetic_mode": ("--synthetic-mode", str),
            "judges": ("--judges", str),
            "samples_per_judge": ("--samples-per-judge", int),
            "min_days": ("--min-days", int),
            "ablate": ("--ablate", str),
            "dim": ("--dim", str),
        },
    ),
    # Judging a calibration set: the one calibration step that spends model calls.
    "calibration": (
        "rubric_calibrate.py",
        "",
        {
            "judge": ("--judge", bool),
            "set": ("--set", str),
            "judges": ("--judges", str),
            "samples_per_judge": ("--samples-per-judge", int),
        },
    ),
}


def _bench_dir() -> str:
    return os.path.join(world_paths.REPO_ROOT, "benchmark")


def _results_dir(synthetic: bool = False) -> str:
    base = os.path.join(_bench_dir(), "results")
    return os.path.join(base, "synthetic") if synthetic else base


def _repo_path(value: Any) -> str:
    root = os.path.realpath(world_paths.REPO_ROOT)
    path = os.path.realpath(os.path.join(root, str(value)))
    if path != root and not path.startswith(root + os.sep):
        raise ValueError(f"path must stay inside the repository: {value!r}")
    return path


def build_argv(kind: str, payload: dict[str, Any]) -> list[str]:
    if kind not in HARNESSES:
        raise ValueError(f"unknown harness `{kind}`; expected one of {sorted(HARNESSES)}")
    script, _, options = HARNESSES[kind]
    unknown = sorted(set(payload) - set(options) - {"kind"})
    if unknown:
        raise ValueError(f"unsupported option(s) for {kind}: {unknown}")
    argv = [sys.executable, script]
    for key, (flag, typ) in options.items():
        if key not in payload or payload[key] in (None, "", False):
            continue
        value = payload[key]
        if typ is bool:
            argv.append(flag)
        elif typ == "path":
            argv += [flag, _repo_path(value)]
        else:
            try:
                argv += [flag, str(typ(value))]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key}: expected {typ.__name__}") from exc
    return argv


def _public(job: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in job.items() if k not in ("log_path", "argv")}
    out["command"] = " ".join(job["argv"][1:])
    try:
        with open(job["log_path"], "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - _LOG_TAIL))
            out["log_tail"] = f.read().decode("utf-8", "replace")
    except OSError:
        out["log_tail"] = ""
    return out


def _running() -> dict[str, Any] | None:
    return next((j for j in _JOBS.values() if j["status"] == "running"), None)


def start(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    kind = str(payload.get("kind", "bench"))
    argv = build_argv(kind, payload)
    if kind == "bench" and not payload.get("output_dir") and not payload.get("synthetic"):
        # Score the active world's / city's runs, not whatever is in output/:
        # the harness subprocess cannot see which world this request is in.
        argv += ["--output-dir", world_paths.run_root()]
    job_id = uuid.uuid4().hex[:12]
    log_dir = os.path.join(world_paths.REPO_ROOT, "output", "bench", "jobs")
    os.makedirs(log_dir, exist_ok=True)
    with _LOCK:
        busy = _running()
        if busy is not None:
            return {"error": "a benchmark job is already running", "job": _public(busy)}, 409
        job = {
            "id": job_id,
            "kind": kind,
            "argv": argv,
            "status": "running",
            "started_at": time.time(),
            "finished_at": None,
            "returncode": None,
            "scorecard": None,
            "log_path": os.path.join(log_dir, f"{job_id}.log"),
        }
        _JOBS[job_id] = job
        finished = sorted((j["started_at"], k) for k, j in _JOBS.items() if j["status"] != "running")
        while len(_JOBS) > _MAX_JOBS and finished:
            _JOBS.pop(finished.pop(0)[1], None)
    ownership.spawn(_run, job, name=f"bench-{job_id}")
    return _public(job), 202


def _run(job: dict[str, Any]) -> None:
    script, results_file, _ = HARNESSES[job["kind"]]
    try:
        with open(job["log_path"], "w", encoding="utf-8") as log:
            code = subprocess.call(
                job["argv"], cwd=_bench_dir(), stdout=log, stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
    except OSError as exc:
        code = -1
        with open(job["log_path"], "a", encoding="utf-8") as log:
            log.write(f"\n[bench_api] could not start {script}: {exc}\n")
    scorecard = None
    if code == 0 and results_file:
        try:
            synthetic = "--synthetic" in job["argv"]
            with open(os.path.join(_results_dir(synthetic), results_file), "r", encoding="utf-8") as f:
                scorecard = json.load(f)
        except (OSError, ValueError):
            scorecard = None
    with _LOCK:
        job.update(
            status="done" if code == 0 else "failed",
            returncode=code,
            finished_at=time.time(),
            scorecard=scorecard,
        )


def latest() -> dict[str, Any]:
    out = {}
    for kind, (_, results_file, _) in HARNESSES.items():
        if not results_file:
            continue
        path = os.path.join(_results_dir(), results_file)
        try:
            with open(path, "r", encoding="utf-8") as f:
                out[kind] = {"updated_at": os.path.getmtime(path), "scorecard": json.load(f)}
        except (OSError, ValueError):
            out[kind] = None
    return out


def reports() -> list[str]:
    try:
        names = os.listdir(os.path.join(_results_dir(), "reports"))
    except OSError:
        return []
    return sorted((n for n in names if n.endswith(".md")), reverse=True)


# ── Track R human calibration ──────────────────────────────────────────────


def _calibration():
    """``benchmark/rubric/calibration.py``.

    Imported from the code tree this module ships in, not from
    ``world_paths.REPO_ROOT``: the root is where results live and can move
    (tests point it at a temp copy), while an imported module stays cached
    and must not keep paths into a tree that is gone.
    """
    bench = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "benchmark")
    if bench not in sys.path:
        sys.path.insert(0, bench)
    from rubric import calibration

    return calibration


def _calibration_root() -> str:
    return os.path.join(_results_dir(), "rubric_calibration")


def calibration_sets() -> dict[str, Any]:
    return {"sets": _calibration().list_sets(_calibration_root())}


def calibration_tasks(set_id: str, annotator: str = "") -> dict[str, Any]:
    """The set as annotators see it, plus this annotator's own labels only."""
    calib = _calibration()
    set_doc, _key = calib.load_set(set_id, _calibration_root())
    mine = calib.load_labels(set_id, _calibration_root()).get(annotator.strip(), {}) if annotator.strip() else {}
    return {"set": set_doc, "labels": mine}


def calibration_build(payload: dict[str, Any]) -> dict[str, Any]:
    calib = _calibration()
    from rubric import loader, runner

    output_dir = _repo_path(payload["output_dir"]) if payload.get("output_dir") else world_paths.run_root()
    n = int(payload.get("n") or calib.DEFAULT_N)
    if not 5 <= n <= 100:
        raise ValueError("n 取 5–100")
    set_doc, key_doc = calib.build_set(loader.load_all(Path(output_dir)), runner.load_rubric(), n=n,
                                       seed=int(payload.get("seed") or 7),
                                       source=os.path.relpath(output_dir, world_paths.REPO_ROOT))
    if not set_doc["tasks"]:
        raise ValueError("这次运行里没有任何 rubric 条目可评（缺 episodes / 轨迹 / 社交数据）")
    calib.save_set(set_doc, key_doc, _calibration_root())
    return {k: v for k, v in set_doc.items() if k != "tasks"}


def calibration_label(set_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    score = payload.get("score")
    if score is not None:
        try:
            score = int(score)
        except (TypeError, ValueError):
            raise ValueError("score 只能是 0 / 1 / 2 或 null") from None
    doc = _calibration().save_label(set_id, str(payload.get("annotator") or ""), str(payload.get("task_id") or ""),
                                    score, str(payload.get("note") or ""), _calibration_root())
    return {"annotator": doc["annotator"], "labelled": len(doc.get("labels") or {})}


def calibration_analyze(set_id: str) -> dict[str, Any]:
    return _calibration().run_analysis(set_id, _calibration_root())


def _calibration_route(route: str) -> tuple[str, str]:
    """``/api/bench/calibration/<set>[/<action>]`` → ``(set_id, action)``."""
    parts = route[len("/api/bench/calibration/"):].split("/")
    return parts[0], (parts[1] if len(parts) > 1 else "")


def handle_get(path: str, query: dict) -> tuple[dict[str, Any], int]:
    route = path.rstrip("/")
    if route == "/api/bench/calibration":
        return calibration_sets(), 200
    if route.startswith("/api/bench/calibration/"):
        set_id, action = _calibration_route(route)
        if action:
            return {"error": "Unknown endpoint"}, 404
        annotator = (query.get("annotator") or [""])[0] if isinstance(query.get("annotator"), list) \
            else str(query.get("annotator") or "")
        try:
            return calibration_tasks(set_id, annotator), 200
        except (FileNotFoundError, ValueError) as exc:
            return {"error": str(exc)}, 404
    if route == "/api/bench/scorecard":
        return latest(), 200
    if route == "/api/bench/jobs":
        with _LOCK:
            jobs = sorted(_JOBS.values(), key=lambda j: j["started_at"], reverse=True)
            return {"jobs": [_public(j) for j in jobs]}, 200
    if route.startswith("/api/bench/jobs/"):
        with _LOCK:
            job = _JOBS.get(route.rsplit("/", 1)[1])
            if job is None:
                return {"error": "unknown job"}, 404
            return _public(job), 200
    if route == "/api/bench/reports":
        return {"reports": reports()}, 200
    if route.startswith("/api/bench/reports/"):
        name = route.rsplit("/", 1)[1]
        if name not in reports():
            return {"error": "unknown report"}, 404
        with open(os.path.join(_results_dir(), "reports", name), "r", encoding="utf-8") as f:
            return {"name": name, "markdown": f.read()}, 200
    return {"error": "Unknown endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    route = path.rstrip("/")
    if route == "/api/bench/run":
        return start(payload)
    try:
        if route == "/api/bench/calibration/build":
            return calibration_build(payload), 201
        if route.startswith("/api/bench/calibration/"):
            set_id, action = _calibration_route(route)
            if action == "label":
                return calibration_label(set_id, payload), 200
            if action == "analyze":
                return calibration_analyze(set_id), 200
    except FileNotFoundError as exc:
        return {"error": str(exc)}, 404
    except ValueError as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown endpoint"}, 404
