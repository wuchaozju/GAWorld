"""This file starts, watches, and stops GAWorld subprocess runs.

- _resolve_python_executable finds the right Python for the subprocess.
- _gaworld_package_dirs locates the gaworld package for PYTHONPATH setup.
- _read_log_tail reads the end of GAWorld's log for user-visible failures.
- GAWorldProcessError is raised when the GAWorld process exits before work is done.
- GAWorldTimeoutError is raised when waiting takes too long.
- GAWorldSubprocessManager stores run settings and controls one GAWorld subprocess.
- launch starts the GAWorld simulator process with config overrides in env.
- env_overrides lets the scene add needed environment values for the subprocess.
- wait_for_day keeps checking state output until a target day is reached.
- is_alive tells whether the subprocess is still running.
- kill stops the process and optionally removes run output.
- launch_comparative starts baseline and treatment runs and returns both managers.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class GAWorldProcessError(RuntimeError):
    """Raised when the GAWorld process exits unexpectedly."""


class GAWorldTimeoutError(RuntimeError):
    """Raised when waiting for GAWorld output reaches timeout."""


@dataclass(frozen=True)
class GAWorldWaitSnapshot:
    """Stores the latest visible signs of life while FOS waits for GAWorld."""

    status: str
    target_day: int
    elapsed_s: float
    output_dir: str
    log_path: str
    state_path: str
    state_file_exists: bool
    last_day: int | None
    observed_phases: dict[str, float]
    log_mtime: float | None
    log_age_s: float | None
    latest_agent_log_mtime: float | None
    latest_agent_log_age_s: float | None
    schedule_tick_count: int
    agent_schedule_count: int
    observed_file_change: bool
    paths: dict[str, dict[str, Any]]
    log_tail: str


def _resolve_python_executable() -> str:
    """Resolve the Python executable to use for the GAWorld subprocess.

    Uses sys.executable by default. Falls back to CONDA_PREFIX or
    sys.exec_prefix when sys.executable is unavailable or unreliable,
    such as when running inside a uvicorn worker on Windows.

    Returns:
        Absolute path to the Python executable.
    """
    # Primary: sys.executable should normally be correct
    if sys.executable and os.path.isabs(sys.executable) and os.path.isfile(sys.executable):
        return sys.executable

    # Fallback 1: CONDA_PREFIX (set when a conda environment is activated)
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        if os.name == "nt":
            candidate = os.path.join(conda_prefix, "python.exe")
        else:
            candidate = os.path.join(conda_prefix, "bin", "python")
        if os.path.isfile(candidate):
            logger.info("GAWorld: using CONDA_PREFIX Python: %s", candidate)
            return candidate

    # Fallback 2: sys.exec_prefix (works for virtualenvs and venvs)
    if os.name == "nt":
        candidate = os.path.join(sys.exec_prefix, "python.exe")
    else:
        candidate = os.path.join(sys.exec_prefix, "bin", "python")
    if os.path.isfile(candidate):
        logger.info("GAWorld: using exec_prefix Python: %s", candidate)
        return candidate

    # Fallback 3: PATH lookup
    which_python = shutil.which("python")
    if which_python:
        logger.info("GAWorld: using PATH-resolved Python: %s", which_python)
        return which_python

    # Last resort: return whatever sys.executable is, or "python"
    logger.warning("GAWorld: could not resolve a reliable Python, falling back")
    return sys.executable or "python"


def _gaworld_package_dirs() -> list[str]:
    """Find directories needed on PYTHONPATH for gaworld imports.

    Returns parent directories of the gaworld package so that
    ``import gaworld`` works in the subprocess regardless of which
    Python interpreter is used.
    """
    dirs: list[str] = []
    try:
        spec = importlib.util.find_spec("gaworld")
        if spec is not None:
            if spec.submodule_search_locations:
                parent = str(Path(spec.submodule_search_locations[0]).parent)
                dirs.append(parent)
            elif spec.origin:
                parent = str(Path(spec.origin).parent)
                dirs.append(parent)
    except (ModuleNotFoundError, ValueError):
        pass
    return dirs


def _read_log_tail(log_path: Path, max_lines: int = 20) -> str:
    """Read the last lines of a GAWorld log file if one exists."""
    if not log_path.exists():
        return ""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        logger.exception("GAWorld: failed to read log tail from %s", log_path)
        return ""
    return "\n".join(lines[-max_lines:]).strip()


def _parse_log_clock_seconds(line: str, launch_started_at: float) -> float | None:
    """Turns a log line clock time into seconds since launch."""
    parts = line.split("|", 1)
    if not parts:
        return None
    clock_text = parts[0].strip()
    try:
        log_clock = datetime.strptime(clock_text, "%H:%M:%S")
    except ValueError:
        return None

    launch_dt = datetime.fromtimestamp(launch_started_at)
    candidate = launch_dt.replace(
        hour=log_clock.hour,
        minute=log_clock.minute,
        second=log_clock.second,
        microsecond=0,
    )
    if candidate < launch_dt:
        candidate += timedelta(days=1)
    return (candidate - launch_dt).total_seconds()


def _observed_phase_offsets(log_path: Path, launch_started_at: float | None) -> dict[str, float]:
    """Finds rough GAWorld phase timings from known log markers."""
    if launch_started_at is None or not log_path.exists():
        return {}
    markers = {
        "first_rag_bootstrap_s": ("RAG 条目", "rag_seed_script bootstrap"),
        "first_schedule_ready_s": ("[BasicRoutine]", "[TodayRoutine Day"),
    }
    observed: dict[str, float] = {}
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        logger.exception("GAWorld: failed to read phase timings from %s", log_path)
        return {}

    for line in lines:
        for label, snippets in markers.items():
            if label in observed:
                continue
            if any(snippet in line for snippet in snippets):
                elapsed_s = _parse_log_clock_seconds(line, launch_started_at)
                if elapsed_s is not None:
                    observed[label] = round(elapsed_s, 3)
    return observed


def _read_last_day(state_path: Path) -> int | None:
    """Reads the latest saved GAWorld day number when the state file exists."""
    if not state_path.exists():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("GAWorld: failed to read state from %s", state_path)
        return None
    raw_last_day = state.get("last_day")
    if raw_last_day is None:
        return None
    try:
        return int(raw_last_day)
    except (TypeError, ValueError):
        logger.exception("GAWorld: invalid last_day in %s", state_path)
        return None


def _path_snapshot(path: Path) -> dict[str, Any]:
    """Summarizes one file or folder so wait snapshots can show freshness."""
    exists = path.exists()
    mtime = None
    age_s = None
    size = None
    if exists:
        try:
            stat_result = path.stat()
        except OSError:
            logger.exception("GAWorld: failed to stat %s", path)
        else:
            mtime = round(stat_result.st_mtime, 3)
            age_s = round(max(0.0, time.time() - stat_result.st_mtime), 3)
            if path.is_file():
                size = stat_result.st_size
    return {
        "path": str(path),
        "exists": exists,
        "mtime": mtime,
        "age_s": age_s,
        "size": size,
    }


def _agent_log_snapshots(logs_dir: Path) -> tuple[dict[str, dict[str, Any]], float | None, float | None]:
    """Summarizes agent log files and returns the freshest agent log time."""
    if not logs_dir.exists():
        return {}, None, None

    snapshots: dict[str, dict[str, Any]] = {}
    latest_mtime = None
    latest_age_s = None
    for log_path in sorted(logs_dir.glob("agent_*.log")):
        snapshot = _path_snapshot(log_path)
        snapshots[log_path.name] = snapshot
        mtime = snapshot["mtime"]
        if mtime is None:
            continue
        if latest_mtime is None or mtime > latest_mtime:
            latest_mtime = mtime
            latest_age_s = snapshot["age_s"]
    return snapshots, latest_mtime, latest_age_s


def _observed_path_snapshots(output_dir: Path, log_path: Path, state_path: Path) -> dict[str, dict[str, Any]]:
    """Collects the files and folders that matter when diagnosing GAWorld waits."""
    memory_dir = output_dir / "memory"
    logs_dir = output_dir / "logs"
    work_dir = output_dir / "work"
    return {
        "log_path": _path_snapshot(log_path),
        "state_path": _path_snapshot(state_path),
        "memory_dir": _path_snapshot(memory_dir),
        "logs_dir": _path_snapshot(logs_dir),
        "work_dir": _path_snapshot(work_dir),
        "real_work_queue": _path_snapshot(work_dir / "queue.jsonl"),
        "real_work_capabilities": _path_snapshot(work_dir / "capabilities.json"),
    }


def _schedule_tick_summary(memory_dir: Path) -> tuple[int, int]:
    """Counts unique scheduled times across saved per-agent schedules."""
    if not memory_dir.exists():
        return 0, 0

    schedule_paths = sorted(memory_dir.glob("agent_*_schedule.json"))
    unique_times: set[str] = set()
    schedule_count = 0
    for schedule_path in schedule_paths:
        try:
            raw_items = json.loads(schedule_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("GAWorld: failed to read schedule file %s", schedule_path)
            continue
        if not isinstance(raw_items, list):
            continue
        schedule_count += 1
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            raw_time = item.get("time")
            if raw_time is None:
                continue
            time_text = str(raw_time).strip()
            if time_text:
                unique_times.add(time_text)
    return len(unique_times), schedule_count


def _build_observed_signature(paths: dict[str, dict[str, Any]], agent_logs: dict[str, dict[str, Any]]) -> str:
    """Builds a compact signature so FOS can tell whether files changed."""
    payload = {
        "paths": {
            key: {
                "exists": value["exists"],
                "mtime": value["mtime"],
                "size": value["size"],
            }
            for key, value in paths.items()
            if isinstance(value, dict) and "exists" in value
        },
        "agent_logs": {
            key: {
                "exists": value["exists"],
                "mtime": value["mtime"],
                "size": value["size"],
            }
            for key, value in agent_logs.items()
        },
    }
    return json.dumps(payload, sort_keys=True)


def _build_wait_snapshot(
    output_dir: Path,
    log_path: Path,
    state_path: Path,
    target_day: int,
    launch_started_at: float | None,
    status: str,
    previous_signature: str | None = None,
) -> GAWorldWaitSnapshot:
    """Builds one diagnostic snapshot that can be logged or written to disk."""
    elapsed_s = 0.0 if launch_started_at is None else round(time.time() - launch_started_at, 3)
    paths = _observed_path_snapshots(output_dir, log_path, state_path)
    agent_logs, latest_agent_log_mtime, latest_agent_log_age_s = _agent_log_snapshots(output_dir / "logs")
    schedule_tick_count, agent_schedule_count = _schedule_tick_summary(output_dir / "memory")
    signature = _build_observed_signature(paths, agent_logs)
    return GAWorldWaitSnapshot(
        status=status,
        target_day=target_day,
        elapsed_s=elapsed_s,
        output_dir=str(output_dir),
        log_path=str(log_path),
        state_path=str(state_path),
        state_file_exists=state_path.exists(),
        last_day=_read_last_day(state_path),
        observed_phases=_observed_phase_offsets(log_path, launch_started_at),
        log_mtime=paths["log_path"]["mtime"],
        log_age_s=paths["log_path"]["age_s"],
        latest_agent_log_mtime=latest_agent_log_mtime,
        latest_agent_log_age_s=latest_agent_log_age_s,
        schedule_tick_count=schedule_tick_count,
        agent_schedule_count=agent_schedule_count,
        observed_file_change=previous_signature != signature,
        paths={**paths, "agent_logs": agent_logs},
        log_tail=_read_log_tail(log_path),
    )


def _write_wait_snapshot(snapshot_path: Path, snapshot: GAWorldWaitSnapshot) -> None:
    """Writes the latest wait snapshot to a JSON file for quick inspection."""
    try:
        snapshot_path.write_text(
            json.dumps(asdict(snapshot), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        logger.exception("GAWorld: failed to write wait snapshot to %s", snapshot_path)


def _format_timeout_detail(snapshot: GAWorldWaitSnapshot, snapshot_path: Path) -> str:
    """Builds a timeout message that points to the saved diagnostic snapshot."""
    detail = (
        "gaworld.error.wait_timeout\n"
        f"Snapshot: {snapshot_path}\n"
        f"Elapsed: {snapshot.elapsed_s}s\n"
        f"Last day: {snapshot.last_day}\n"
        f"Observed phases: {snapshot.observed_phases}"
    )
    if snapshot.log_tail:
        detail = f"{detail}\nGAWorld log tail:\n{snapshot.log_tail}"
    return detail


@dataclass
class GAWorldSubprocessManager:
    """Controls one GAWorld simulator process and its output folder."""

    gaworld_path: Path
    config_overrides: dict[str, Any]
    output_dir: Path
    preserve_output: bool = False
    env_overrides: dict[str, str] = field(default_factory=dict)
    env_removals: set[str] = field(default_factory=set)
    process: subprocess.Popen[str] | Any | None = field(default=None, init=False)
    launch_started_at: float | None = field(default=None, init=False)
    _last_wait_signature: str | None = field(default=None, init=False)

    def launch(self) -> None:
        """Starts the simulator process with config overrides in environment."""
        script_path = self.gaworld_path / "generative_city_sim.py"
        if not script_path.exists():
            raise FileNotFoundError("gaworld.error.script_not_found")

        self.launch_started_at = time.time()
        python_exe = _resolve_python_executable()
        command = [python_exe, str(script_path), "run"]
        env = os.environ.copy()
        for key in self.env_removals:
            env.pop(key, None)
        env.update({key: value for key, value in self.env_overrides.items() if value})
        env["GAWORLD_CONFIG_OVERRIDES"] = json.dumps(self.config_overrides)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        # Build PYTHONPATH: gaworld script dir + gaworld package dirs
        path_entries: list[str] = [str(self.gaworld_path)]
        for pkg_dir in _gaworld_package_dirs():
            if pkg_dir not in path_entries:
                path_entries.append(pkg_dir)

        existing_pythonpath = env.get("PYTHONPATH", "")
        new_pythonpath = os.pathsep.join(path_entries)
        env["PYTHONPATH"] = new_pythonpath + (
            os.pathsep + existing_pythonpath if existing_pythonpath else ""
        )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        log_file = self.output_dir / "gaworld.log"

        logger.info(
            "GAWorld launch: python=%s, prefix=%s, exec_prefix=%s, "
            "CONDA_PREFIX=%s, PYTHONPATH=%s",
            python_exe,
            sys.prefix,
            sys.exec_prefix,
            os.environ.get("CONDA_PREFIX"),
            env["PYTHONPATH"],
        )

        work_dir = self.output_dir / "workdir"
        work_dir.mkdir(parents=True, exist_ok=True)

        for child in self.gaworld_path.iterdir():
            link_target = work_dir / child.name
            if link_target.exists():
                continue
            if child.is_dir():
                link_target.symlink_to(child)
            elif child.is_file() and child.name != "generative_city_sim.py":
                link_target.symlink_to(child)

        with open(log_file, "w", encoding="utf-8") as file_obj:
            popen_kwargs: dict[str, Any] = {
                "env": env,
                "cwd": str(self.gaworld_path),
                "stdout": file_obj,
                "stderr": subprocess.STDOUT,
            }
            if os.name != "nt":
                popen_kwargs["preexec_fn"] = os.setsid
            self.process = subprocess.Popen(command, **popen_kwargs)

    def wait_for_day(
        self,
        day: int,
        timeout: float = 300,
        poll_interval: float = 3.0,
    ) -> dict[str, Any]:
        """Waits for sim_state.json to report last_day at or beyond target day."""
        deadline = time.time() + timeout
        state_path = self.output_dir / "memory" / "sim_state.json"
        log_path = self.output_dir / "gaworld.log"
        snapshot_path = self.output_dir / "gaworld_wait_status.json"
        next_progress_log_at = time.time()
        saw_change_during_wait = False

        while True:
            if self.process is not None:
                exit_code = self.process.poll()
                if exit_code is not None and exit_code != 0:
                    log_tail = _read_log_tail(self.output_dir / "gaworld.log")
                    detail = f"gaworld.error.exited_unexpectedly: exited unexpectedly with code {exit_code}"
                    if log_tail:
                        detail = f"{detail}\nGAWorld log tail:\n{log_tail}"
                    raise GAWorldProcessError(detail)

            if state_path.exists():
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if int(state.get("last_day", -1)) >= day:
                    if self.launch_started_at is not None:
                        logger.info(
                            "GAWorld wait_for_day reached day=%s in %.3fs with phases=%s",
                            day,
                            time.time() - self.launch_started_at,
                            _observed_phase_offsets(log_path, self.launch_started_at),
                        )
                    return state

            snapshot = _build_wait_snapshot(
                output_dir=self.output_dir,
                log_path=log_path,
                state_path=state_path,
                target_day=day,
                launch_started_at=self.launch_started_at,
                status="waiting",
                previous_signature=self._last_wait_signature,
            )
            _write_wait_snapshot(snapshot_path, snapshot)
            saw_change_during_wait = saw_change_during_wait or snapshot.observed_file_change
            self._last_wait_signature = _build_observed_signature(
                snapshot.paths,
                snapshot.paths.get("agent_logs", {}),
            )
            if time.time() >= next_progress_log_at:
                logger.info(
                    "GAWorld wait_for_day progress: day=%s elapsed=%.3fs last_day=%s phases=%s ticks=%s schedules=%s log_age=%s agent_log_age=%s changed=%s snapshot=%s",
                    day,
                    snapshot.elapsed_s,
                    snapshot.last_day,
                    snapshot.observed_phases,
                    snapshot.schedule_tick_count,
                    snapshot.agent_schedule_count,
                    snapshot.log_age_s,
                    snapshot.latest_agent_log_age_s,
                    snapshot.observed_file_change,
                    snapshot_path,
                )
                next_progress_log_at = time.time() + max(15.0, poll_interval)

            if time.time() > deadline:
                timeout_snapshot = _build_wait_snapshot(
                    output_dir=self.output_dir,
                    log_path=log_path,
                    state_path=state_path,
                    target_day=day,
                    launch_started_at=self.launch_started_at,
                    status="timed_out",
                    previous_signature=self._last_wait_signature,
                )
                if saw_change_during_wait and not timeout_snapshot.observed_file_change:
                    timeout_snapshot = replace(timeout_snapshot, observed_file_change=True)
                _write_wait_snapshot(snapshot_path, timeout_snapshot)
                self._last_wait_signature = _build_observed_signature(
                    timeout_snapshot.paths,
                    timeout_snapshot.paths.get("agent_logs", {}),
                )
                logger.warning(
                    "GAWorld wait_for_day timed out for day=%s after %.3fs with phases=%s ticks=%s schedules=%s log_age=%s agent_log_age=%s changed=%s snapshot=%s",
                    day,
                    timeout,
                    timeout_snapshot.observed_phases,
                    timeout_snapshot.schedule_tick_count,
                    timeout_snapshot.agent_schedule_count,
                    timeout_snapshot.log_age_s,
                    timeout_snapshot.latest_agent_log_age_s,
                    timeout_snapshot.observed_file_change,
                    snapshot_path,
                )
                raise GAWorldTimeoutError(_format_timeout_detail(timeout_snapshot, snapshot_path))

            time.sleep(poll_interval)

    def is_alive(self) -> bool:
        """Returns True only when a process exists and is still running."""
        return self.process is not None and self.process.poll() is None

    def kill(self) -> None:
        """Stops the process and removes output unless output preservation is enabled."""
        if self.process is not None and self.process.poll() is None:
            if os.name == "nt":
                self.process.terminate()
            else:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)

        if not self.preserve_output and self.output_dir.exists():
            shutil.rmtree(self.output_dir)

    @classmethod
    def launch_comparative(
        cls,
        gaworld_path: Path,
        event_config: dict[str, Any],
        base_output_dir: Path,
        config_overrides: dict[str, Any],
        env_overrides: dict[str, str] | None = None,
        env_removals: set[str] | None = None,
    ) -> tuple[GAWorldSubprocessManager, GAWorldSubprocessManager]:
        """Starts baseline and treatment runs and returns both managers."""
        baseline_overrides = {
            **config_overrides,
            "intervention": {"enabled": False},
        }
        treatment_overrides = {
            **config_overrides,
            "intervention": {"enabled": True, **event_config},
        }

        baseline = cls(
            gaworld_path,
            baseline_overrides,
            base_output_dir / "baseline",
            env_overrides=env_overrides or {},
            env_removals=env_removals or set(),
        )
        treatment = cls(
            gaworld_path,
            treatment_overrides,
            base_output_dir / "treatment",
            env_overrides=env_overrides or {},
            env_removals=env_removals or set(),
        )
        baseline.launch()
        treatment.launch()
        return baseline, treatment
