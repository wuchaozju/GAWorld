"""Fork an experiment into worlds and run them as isolated subprocesses.

Each world is a full simulation with its own memory, logs and state tree, so
it has to be a separate process: the simulator keeps module-level config and
a vector DB handle, and two worlds in one interpreter would share both. The
existing ``compare-event`` command already worked this way for two worlds;
what changes here is that N worlds are scheduled through a small pool instead
of all being launched at once — eight concurrent LLM-driven simulations will
starve a laptop and rate-limit a provider, and a run that thrashes is worse
than a run that queues.

Progress is read back out of each world's ``run.log``. The simulator writes
the per-agent state history only at the very end of a run, so the log's day
banner is the only live signal available; parsing it is what lets the console
show eight worlds advancing instead of a spinner.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from typing import Any, Callable

from gaworld.logging_setup import get_logger
from gaworld.parallel.analysis import build_report, read_state_series, summarize_report
from gaworld.parallel.spec import ExperimentSpec, world_overrides

_LOG = get_logger("gaworld.parallel.runner")

#: The intra-day banner (``===== Day 3 (…)``), the coarse month/year banner
#: (``===== Month 3 · Day 90 (…)``, whose day number is the step's *last*
#: sim day) and the fast-forward line (``[FastForward Day 3] …``). Anchored
#: on purpose: a bare ``Day (\d+)`` also matches agent goal text like
#: "目标 Day 14", which reported a one-day run as being on day 14.
_DAY_RE = re.compile(
    r"^=+ Day (\d+)|^=+ (?:Month|Year) \d+ · Day (\d+)|^\[FastForward Day (\d+)",
    re.MULTILINE,
)

#: How much of a run log to read when sampling progress.
_LOG_TAIL_BYTES = 8192

DEFAULT_OUTPUT_ROOT = os.path.join("output", "parallel_worlds")


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def prepare_experiment(
    spec: ExperimentSpec,
    repo_root: str,
    *,
    output_root: str = DEFAULT_OUTPUT_ROOT,
    base_config: dict[str, Any] | None = None,
    experiment_id: str | None = None,
) -> dict[str, Any]:
    """Create the on-disk tree for an experiment and write its manifest.

    Paths in the manifest are relative to ``repo_root`` because the worlds run
    with the repo as their working directory and the manifest is meant to stay
    readable after the tree is moved or shared.
    """
    stamp = time.strftime("%Y%m%d_%H%M%S")
    exp_id = experiment_id or f"{stamp}_{spec.slug}"
    root_rel = os.path.join(output_root, exp_id)
    root_abs = os.path.join(repo_root, root_rel)
    os.makedirs(root_abs, exist_ok=True)

    worlds: dict[str, Any] = {}
    for world in spec.worlds:
        world_rel = os.path.join(root_rel, "worlds", world.id)
        os.makedirs(os.path.join(repo_root, world_rel), exist_ok=True)
        worlds[world.id] = {
            "dir": world_rel,
            "overrides": world_overrides(spec, world, world_rel, base_config=base_config),
            "run_log": os.path.join(world_rel, "run.log"),
            "reset_log": os.path.join(world_rel, "reset.log"),
            "state_csv": os.path.join(world_rel, "state", "agent_state_history.csv"),
            "trace": os.path.join(world_rel, "visualization", "simulation_trace.json"),
        }

    manifest = {
        "id": exp_id,
        "root": root_rel,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "spec": spec.to_dict(),
        "worlds": worlds,
        "status": "prepared",
    }
    write_manifest(repo_root, manifest)
    return manifest


def manifest_path(repo_root: str, root_rel: str) -> str:
    return os.path.join(repo_root, root_rel, "experiment.json")


def write_manifest(repo_root: str, manifest: dict[str, Any]) -> None:
    path = manifest_path(repo_root, manifest["root"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_manifest(repo_root: str, root_rel: str) -> dict[str, Any] | None:
    path = manifest_path(repo_root, root_rel)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


# ---------------------------------------------------------------------------
# Log sampling
# ---------------------------------------------------------------------------


def latest_day(log_path: str) -> int | None:
    """Highest day number mentioned near the end of a run log."""
    if not log_path or not os.path.exists(log_path):
        return None
    try:
        size = os.path.getsize(log_path)
        with open(log_path, "rb") as handle:
            if size > _LOG_TAIL_BYTES:
                handle.seek(size - _LOG_TAIL_BYTES)
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    days = [
        int(value)
        for match in _DAY_RE.findall(tail)
        for value in match
        if value
    ]
    return max(days) if days else None


def log_tail(log_path: str, max_chars: int = 4000) -> str:
    if not log_path or not os.path.exists(log_path):
        return ""
    try:
        size = os.path.getsize(log_path)
        with open(log_path, "rb") as handle:
            if size > max_chars:
                handle.seek(size - max_chars)
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def failure_hint(log_path: str, max_lines: int = 12) -> str:
    """The part of a failed world's log worth putting in front of a user."""
    text = log_tail(log_path, max_chars=16000)
    if not text:
        return "日志为空或不存在"
    lines = [line for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if line.startswith("Traceback (most recent call last):"):
            return "\n".join(lines[index:][-max_lines:])
    markers = ("Error", "error", "Exception", "failed", "refused")
    for line in reversed(lines):
        if any(marker in line for marker in markers):
            return line
    return "\n".join(lines[-max_lines:])


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class ExperimentRunner:
    """Runs every world in a manifest, at most ``max_parallel`` at a time."""

    def __init__(
        self,
        manifest: dict[str, Any],
        repo_root: str,
        *,
        max_parallel: int = 2,
        python_bin: str | None = None,
        script_path: str | None = None,
        reset: bool = True,
    ) -> None:
        self.manifest = manifest
        self.repo_root = repo_root
        self.max_parallel = max(1, int(max_parallel))
        self.python_bin = python_bin or sys.executable
        self.script_path = script_path or os.path.join(repo_root, "generative_city_sim.py")
        self.reset = reset
        self._lock = threading.Lock()
        self._procs: dict[str, subprocess.Popen] = {}
        self._stop = threading.Event()
        self._states: dict[str, dict[str, Any]] = {
            world_id: {
                "id": world_id,
                "label": self._label(world_id),
                "status": "pending",
                "day": 0,
                "returncode": None,
                "started_at": None,
                "finished_at": None,
                "error": None,
            }
            for world_id in manifest.get("worlds", {})
        }

    # -- helpers ---------------------------------------------------------

    def _label(self, world_id: str) -> str:
        for world in self.manifest.get("spec", {}).get("worlds", []):
            if world.get("id") == world_id:
                return world.get("label", world_id)
        return world_id

    def _set(self, world_id: str, **fields: Any) -> None:
        with self._lock:
            self._states[world_id].update(fields)

    def _abs(self, rel: str) -> str:
        return os.path.join(self.repo_root, rel)

    def _env(self, world_id: str) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["GAWORLD_CONFIG_OVERRIDES"] = json.dumps(
            self.manifest["worlds"][world_id]["overrides"], ensure_ascii=False
        )
        # A parallel-worlds run must not inherit the operator's dashboard
        # settings file on top of its own overrides for the paths it isolates;
        # the env override already wins, but marking the run keeps logs honest.
        env["GAWORLD_PARALLEL_WORLD"] = world_id
        return env

    @property
    def sim_days(self) -> int:
        days = self.manifest.get("spec", {}).get("sim_days")
        try:
            return max(1, int(days))
        except (TypeError, ValueError):
            return 1

    # -- world lifecycle -------------------------------------------------

    def _run_world(self, world_id: str) -> None:
        entry = self.manifest["worlds"][world_id]
        env = self._env(world_id)
        self._set(world_id, status="running", started_at=time.time())

        if self.reset:
            reset_log = self._abs(entry["reset_log"])
            os.makedirs(os.path.dirname(reset_log), exist_ok=True)
            with open(reset_log, "w", encoding="utf-8") as handle:
                code = subprocess.run(
                    [self.python_bin, self.script_path, "reset"],
                    cwd=self.repo_root,
                    env=env,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                ).returncode
            if code != 0:
                self._set(
                    world_id,
                    status="error",
                    returncode=code,
                    error=f"reset 失败：{failure_hint(reset_log)}",
                    finished_at=time.time(),
                )
                return

        if self._stop.is_set():
            self._set(world_id, status="stopped", finished_at=time.time())
            return

        run_log = self._abs(entry["run_log"])
        os.makedirs(os.path.dirname(run_log), exist_ok=True)
        handle = open(run_log, "w", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                [self.python_bin, self.script_path, "run"],
                cwd=self.repo_root,
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
            with self._lock:
                self._procs[world_id] = proc
            code = proc.wait()
        finally:
            handle.close()
            with self._lock:
                self._procs.pop(world_id, None)

        if self._stop.is_set() and code != 0:
            self._set(world_id, status="stopped", returncode=code, finished_at=time.time())
            return
        if code != 0:
            self._set(
                world_id,
                status="error",
                returncode=code,
                error=failure_hint(run_log),
                finished_at=time.time(),
            )
            return
        self._set(
            world_id,
            status="done",
            returncode=0,
            day=self.sim_days,
            finished_at=time.time(),
        )

    # -- public API ------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            states = [dict(state) for state in self._states.values()]
        total = self.sim_days * max(1, len(states))
        advanced = 0
        for state in states:
            if state["status"] == "done":
                advanced += self.sim_days
            else:
                advanced += min(self.sim_days, state.get("day") or 0)
        return {
            "worlds": states,
            "progress": min(1.0, advanced / total) if total else 0.0,
            "running": any(state["status"] == "running" for state in states),
            "sim_days": self.sim_days,
        }

    def _sample_logs(self) -> None:
        for world_id, entry in self.manifest.get("worlds", {}).items():
            with self._lock:
                if self._states[world_id]["status"] != "running":
                    continue
            day = latest_day(self._abs(entry["run_log"]))
            if day is not None:
                self._set(world_id, day=day)

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            procs = list(self._procs.items())
        for world_id, proc in procs:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
            self._set(world_id, status="stopped")
        with self._lock:
            for state in self._states.values():
                if state["status"] == "pending":
                    state["status"] = "stopped"

    def run(self, on_progress: Callable[[float, str], None] | None = None) -> dict[str, Any]:
        """Run every world, then build and persist the comparison report."""
        pending = list(self.manifest.get("worlds", {}))
        cursor = threading.Lock()
        queue = iter(pending)

        def worker() -> None:
            while not self._stop.is_set():
                with cursor:
                    world_id = next(queue, None)
                if world_id is None:
                    return
                try:
                    self._run_world(world_id)
                except Exception as exc:  # noqa: BLE001 — one world must not kill the rest
                    _LOG.exception("world %s crashed", world_id)
                    self._set(
                        world_id, status="error", error=str(exc), finished_at=time.time()
                    )

        threads = [
            threading.Thread(target=worker, name=f"world-{index}", daemon=True)
            for index in range(min(self.max_parallel, max(1, len(pending))))
        ]
        for thread in threads:
            thread.start()

        while any(thread.is_alive() for thread in threads):
            self._sample_logs()
            if on_progress:
                snap = self.snapshot()
                done = sum(1 for w in snap["worlds"] if w["status"] in {"done", "error", "stopped"})
                on_progress(
                    snap["progress"] * 0.95,
                    f"已完成 {done}/{len(snap['worlds'])} 个世界",
                )
            time.sleep(1.0)
        for thread in threads:
            thread.join(timeout=5)

        if on_progress:
            on_progress(0.96, "正在比较各世界的走向…")
        return self.finish()

    def finish(self) -> dict[str, Any]:
        """Read every world's state artifacts and write the report."""
        report = analyze_experiment(self.repo_root, self.manifest)
        with self._lock:
            states = [dict(state) for state in self._states.values()]
        status_by_id = {state["id"]: state for state in states}
        for world in report.get("worlds", []):
            state = status_by_id.get(world["id"], {})
            world["status"] = state.get("status", "unknown")
            world["error"] = state.get("error")

        self.manifest["status"] = (
            "stopped"
            if any(state["status"] == "stopped" for state in states)
            else "error"
            if any(state["status"] == "error" for state in states)
            else "done"
        )
        self.manifest["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.manifest["world_status"] = {
            state["id"]: state["status"] for state in states
        }
        write_manifest(self.repo_root, self.manifest)
        write_report(self.repo_root, self.manifest, report)
        return report


# ---------------------------------------------------------------------------
# Analysis / persistence
# ---------------------------------------------------------------------------


def analyze_experiment(repo_root: str, manifest: dict[str, Any]) -> dict[str, Any]:
    """Build the divergence report for a manifest from artifacts on disk."""
    series = {
        world_id: read_state_series(os.path.join(repo_root, entry["state_csv"]))
        for world_id, entry in manifest.get("worlds", {}).items()
    }
    report = build_report(manifest, series)
    report["experiment_id"] = manifest.get("id")
    report["root"] = manifest.get("root")
    report["name"] = manifest.get("spec", {}).get("name")
    report["created_at"] = manifest.get("created_at")
    report["summary"] = summarize_report(report)
    for world in report.get("worlds", []):
        entry = manifest.get("worlds", {}).get(world["id"], {})
        world["trace"] = entry.get("trace")
        world["dir"] = entry.get("dir")
    return report


def write_report(repo_root: str, manifest: dict[str, Any], report: dict[str, Any]) -> str:
    """Persist ``report.json``, a flat CSV and a readable Markdown summary."""
    import csv

    root = os.path.join(repo_root, manifest["root"])
    os.makedirs(root, exist_ok=True)

    json_path = os.path.join(root, "report.json")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    csv_path = os.path.join(root, "divergence_metrics.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "world_id", "world_label", "metric", "baseline_final", "final",
            "delta_final", "baseline_mean", "mean", "delta_mean",
        ])
        labels = {world["id"]: world["label"] for world in report.get("worlds", [])}
        for row in report.get("deltas", []):
            writer.writerow([
                row["world_id"], labels.get(row["world_id"], row["world_id"]),
                row["metric"], f"{row['baseline_final']:.6f}", f"{row['final']:.6f}",
                f"{row['delta_final']:.6f}", f"{row['baseline_mean']:.6f}",
                f"{row['mean']:.6f}", f"{row['delta_mean']:.6f}",
            ])

    md_path = os.path.join(root, "divergence_summary.md")
    spec = manifest.get("spec", {})
    lines = [
        f"# 平行世界实验：{spec.get('name', manifest.get('id'))}",
        "",
        f"- 实验目录：`{manifest.get('root')}`",
        f"- 世界数：{len(spec.get('worlds', []))}｜种子：{spec.get('seed')}"
        f"｜天数：{spec.get('sim_days') or '默认'}",
        "",
        "## 各世界",
        "",
    ]
    for world in report.get("worlds", []):
        events = "；".join(
            f"Day {item['day']} {item['time']} {item['name']}"
            for item in world.get("events", [])
        ) or "（无事件 · 基准）"
        lines.append(f"- **{world['label']}**：{events}")
    lines += ["", "## 结论", ""]
    lines += [f"- {line}" for line in report.get("summary", [])]
    lines += ["", "## 最大差异（按终值绝对差）", ""]
    labels = {world["id"]: world["label"] for world in report.get("worlds", [])}
    for row in report.get("deltas", [])[:12]:
        lines.append(
            f"- [{labels.get(row['world_id'], row['world_id'])}] `{row['metric']}`"
            f"（{row['label']}）: 基准={row['baseline_final']:.4f}, "
            f"本世界={row['final']:.4f}, Δ={row['delta_final']:+.4f}"
        )
    lines += ["", f"- 指标明细：`{os.path.relpath(csv_path, repo_root)}`", ""]
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return json_path


__all__ = [
    "DEFAULT_OUTPUT_ROOT",
    "ExperimentRunner",
    "analyze_experiment",
    "failure_hint",
    "latest_day",
    "load_manifest",
    "log_tail",
    "manifest_path",
    "prepare_experiment",
    "write_manifest",
    "write_report",
]
