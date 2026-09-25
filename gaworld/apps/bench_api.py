"""HTTP surface for the benchmark harnesses in ``benchmark/``.

Both harnesses are CLIs that write fixed result files, so a run is a
subprocess job, one at a time: ``gaworld_bench.py`` always writes
``benchmark/results/scorecard.json``, and two concurrent runs would overwrite
each other's scorecard. When a job finishes its scorecard is copied into the
job record, so the result of *this* job survives the next run.

Only whitelisted options are forwarded, and path options must stay inside the
repo: the payload becomes a command line.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from typing import Any

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
}


def _ds():
    from gaworld.apps import dashboard_server

    return dashboard_server


def _bench_dir() -> str:
    return os.path.join(_ds().REPO_ROOT, "benchmark")


def _results_dir() -> str:
    return os.path.join(_bench_dir(), "results")


def _repo_path(value: Any) -> str:
    root = os.path.realpath(_ds().REPO_ROOT)
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
    job_id = uuid.uuid4().hex[:12]
    log_dir = os.path.join(_ds().REPO_ROOT, "output", "bench", "jobs")
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
    threading.Thread(target=_run, args=(job,), name=f"bench-{job_id}", daemon=True).start()
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
    if code == 0:
        try:
            with open(os.path.join(_results_dir(), results_file), "r", encoding="utf-8") as f:
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


def handle_get(path: str, query: dict) -> tuple[dict[str, Any], int]:
    route = path.rstrip("/")
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
    if path.rstrip("/") == "/api/bench/run":
        return start(payload)
    return {"error": "Unknown endpoint"}, 404
