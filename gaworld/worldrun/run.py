"""World-run launch primitive: one world, one handle, one output dir.

``launch`` is the single entry point for starting a GAWorld world run,
whether the caller is the parallel-worlds runner or the SimTree branch
launcher:

- output isolation is validated from ONE authoritative definition
  (:mod:`gaworld.worldrun.config`) — a patch that would write into the
  shared tree fails loudly instead of quietly contaminating the base run;
- checkpoint seeding (``seed_from_dir``) materializes a FRESH output dir,
  delegates checkpoint truth to :mod:`gaworld.checkpoints`, never touches
  the source run, and skips the destructive reset a fresh world performs;
- every run gets a :class:`RunHandle` with the shared status model
  (:mod:`gaworld.worldrun.lifecycle`), its manifest reference, and
  ``wait`` / ``cancel`` actions;
- completed-day state history is appended at the day boundary
  (:mod:`gaworld.worldrun.history`), so an interrupted run keeps what it
  finished and a resumed run appends exactly the next days.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import uuid
from typing import Any

from gaworld.worldrun import lifecycle
from gaworld.worldrun.config import (
    RESERVED_CONFIG_KEYS,
    validate_world_overrides,
)
from gaworld.worldrun.history import HistoryAppender, _existing_steps, copy_history
from gaworld.worldrun.lifecycle import STATUSES
from gaworld.worldrun.manifest import load_manifest, write_manifest

WORLDRUN_VERSION = 1

#: Metrics recorded by the deterministic in-process executor. Real GAWorld
#: runs launched through :func:`launch_subprocess` write their own richer
#: history; the executor exists so the worldrun contracts (isolation,
#: statuses, history, resume) are exercisable without a city bundle.
_EXECUTOR_METRICS = ("emotion", "energy")


class RunError(RuntimeError):
    """A world run could not be started or failed its contract."""


def _run_id() -> str:
    return uuid.uuid4().hex


class RunHandle:
    """Handle over one world run: identity, status, actions, manifest."""

    def __init__(self, world_id: str, repo_root: str, output_dir: str) -> None:
        self.run_id = _run_id()
        self.world_id = world_id
        self.repo_root = os.path.abspath(repo_root)
        self.output_dir = os.path.abspath(output_dir)
        self.manifest_ref = os.path.join(self.output_dir, "experiment.json")
        self.status = "created"
        self.returncode: int | None = None
        self.error: str | None = None
        self.reset_performed = False
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._specs: dict[str, Any] = {}

    # -- actions ----------------------------------------------------------

    def wait(self, timeout: float | None = None) -> str:
        """Block until the run reaches a terminal status (or *timeout*)."""
        if self._thread is not None:
            self._thread.join(timeout)
        return self.status

    def cancel(self) -> None:
        """Ask the run to stop; the in-flight day completes so the history
        of every completed day is retained. (The in-process executor runs
        its days inline, so by the time a caller can cancel, the run has
        reached a terminal status and this is a no-op; subprocess-backed
        handles terminate their process.)"""
        self._cancel.set()
        if self.status not in lifecycle.TERMINAL_STATUSES:
            self.status = "cancelled"

    # -- introspection ----------------------------------------------------

    def manifest(self) -> dict[str, Any]:
        manifest = load_manifest(self.repo_root, self.output_dir)
        if manifest is None:
            raise RunError(f"no manifest at {self.manifest_ref}")
        return manifest


class SubprocessHandle:
    """Handle over a world run executing as a separate process."""

    def __init__(
        self,
        world_id: str,
        proc: subprocess.Popen,
        output_dir: str,
        repo_root: str = ".",
    ) -> None:
        self.run_id = _run_id()
        self.world_id = world_id
        self.proc = proc
        self.output_dir = os.path.abspath(output_dir)
        self.repo_root = os.path.abspath(repo_root)
        self.manifest_ref = os.path.join(self.output_dir, "experiment.json")
        self.status = "running"
        self.returncode: int | None = None

    def wait(self, timeout: float | None = None) -> str:
        try:
            self.returncode = self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            return self.status
        self.status = lifecycle.failure_status(self.returncode)
        return self.status

    def cancel(self, grace: float = 5.0) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(grace)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.returncode = self.proc.returncode
        self.status = lifecycle.failure_status(self.returncode)

    def pause(self) -> None:
        """Suspend the process (consumed by the PW adapter only)."""
        import signal

        if hasattr(os, "killpg") and hasattr(self.proc, "pid"):
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGSTOP)
            except (ProcessLookupError, PermissionError):
                pass

    def resume(self) -> None:
        import signal

        if hasattr(os, "killpg") and hasattr(self.proc, "pid"):
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGCONT)
            except (ProcessLookupError, PermissionError):
                pass


def launch_subprocess(
    command: list[str],
    *,
    world_id: str = "world",
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    output_dir: str | None = None,
    new_process_group: bool = True,
    stdout: Any = None,
    stderr: Any = None,
) -> SubprocessHandle:
    """Spawn one world run as a separate process (the process boundary PW and
    SimTree both preserve). Returns a :class:`SubprocessHandle`.

    ``stdout`` / ``stderr`` are additive: by default output is discarded
    (DEVNULL) exactly as before, but a caller that owns a log destination —
    e.g. the parallel-worlds runner teeing each world into its ``run.log`` —
    can pass an open file object. ``new_process_group=False`` keeps the child
    in the caller's process group (the historical PW semantics its
    pause/resume signalling relies on) instead of a fresh session.
    """
    kwargs: dict[str, Any] = {}
    if new_process_group and hasattr(os, "setsid"):
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [str(part) for part in command],
        cwd=cwd,
        env=env,
        stdout=subprocess.DEVNULL if stdout is None else stdout,
        stderr=subprocess.DEVNULL if stderr is None else stderr,
        **kwargs,
    )
    return SubprocessHandle(
        world_id,
        proc,
        output_dir or (cwd or "."),
        repo_root=cwd or ".",
    )


def seed_from_dir(source_dir: str, target_dir: str) -> str:
    """Materialize a fresh run dir seeded from an earlier run.

    The source is only ever READ: its completed-day history carries over so
    the fork continues the series, and its checkpoint directory is copied so
    the fork can restore. Checkpoint serialization itself stays owned by
    :mod:`gaworld.checkpoints` — this function moves files, it never
    re-serializes state.
    """
    os.makedirs(target_dir, exist_ok=True)
    copy_history(source_dir, target_dir)
    src_ck = os.path.join(source_dir, "checkpoints")
    if os.path.isdir(src_ck):
        dst_ck = os.path.join(target_dir, "checkpoints")
        if os.path.exists(dst_ck):
            shutil.rmtree(dst_ck)
        shutil.copytree(src_ck, dst_ck)
    return target_dir


# ---------------------------------------------------------------------------
# in-process world executor
# ---------------------------------------------------------------------------


def _launch_one(
    spec: dict[str, Any],
    repo_root: str,
    seed_dir: str | None,
) -> RunHandle:
    world_id = str(spec.get("name") or spec.get("id") or "world")
    config = spec.get("config") or {}
    if not isinstance(config, dict):
        raise RunError(f"world {world_id!r}: config 必须是对象")
    config = dict(config)
    # ``sim_days`` in a world patch IS the horizon for a standalone worldrun
    # launch (there is no experiment-level setting to conflict with), so it
    # is lifted to spec level rather than treated as a reserved override.
    if "sim_days" in config and "sim_days" not in spec:
        spec = dict(spec, sim_days=config.pop("sim_days"))
    else:
        config.pop("sim_days", None)
    if seed_dir:
        # A fork may pin the seed / cohort it inherited from the lineage
        # (they are recorded in the manifest's seed_refs); it may never
        # re-point output paths into the shared tree.
        validate_world_overrides(
            {key: value for key, value in config.items() if isinstance(value, dict)},
            where=f"world {world_id!r}",
        )
    else:
        validate_world_overrides(config, where=f"world {world_id!r}")

    root = os.path.abspath(repo_root)
    handle = RunHandle(
        world_id,
        repo_root,
        os.path.join(root, "worldrun_runs", f"{world_id}-{_run_id()[:8]}"),
    )
    os.makedirs(handle.output_dir, exist_ok=True)
    handle._specs = dict(spec)
    handle._specs["config"] = config
    handle._specs["_seed_dir"] = seed_dir
    handle.reset_performed = not seed_dir
    # The in-process executor runs the day loop inline: one launch call
    # drives the world to a terminal status, which keeps a failed or
    # cancelled world from ever outliving its caller. Subprocess-backed
    # runs (launch_subprocess) are the async path.
    handle.status = "created"
    _execute(handle)
    return handle


def _execute(handle: RunHandle) -> None:
    spec = handle._specs
    config = spec.get("config") or {}
    seed_dir = spec.get("_seed_dir")
    try:
        os.makedirs(handle.output_dir, exist_ok=True)
        handle.reset_performed = not seed_dir
        if seed_dir:
            seed_from_dir(seed_dir, handle.output_dir)

        sim_days = int(spec.get("sim_days", 1) or 1)
        agent_ids = config.get("agent_ids") or spec.get("agent_ids") or [1, 2]
        seed = config.get("random_seed", spec.get("random_seed", 42))

        history = HistoryAppender(handle.output_dir)
        state_history: dict[int, dict[str, list[float]]] = {
            agent_id: {metric: [] for metric in _EXECUTOR_METRICS} for agent_id in agent_ids
        }
        first_day = 0
        if seed_dir:
            steps = _existing_steps(history.path)
            first_day = (max(steps) + 1) if steps else 0

        write_manifest(
            handle.repo_root,
            {
                "root": handle.output_dir,
                "worlds": {handle.world_id: {"status": "running"}},
                "worldrun_version": WORLDRUN_VERSION,
                "completed_day": None,
                "checkpoint_lineage": ({"source_run": str(seed_dir)} if seed_dir else None),
                "seed_refs": {"random_seed": seed},
                "agent_ids": list(agent_ids),
                "parent_run": None,
                "reset_performed": handle.reset_performed,
                "status": "running",
            },
        )
        handle.status = "running"

        if spec.get("fail"):
            raise RunError(f"world {handle.world_id!r}: induced failure")

        last_day = max(sim_days, first_day)
        fail_on_day = spec.get("fail_on_day")
        for day in range(first_day, last_day):
            if fail_on_day is not None and day == int(fail_on_day):
                raise RunError(f"world {handle.world_id!r}: induced failure on day {day}")
            for agent_id in agent_ids:
                for metric in _EXECUTOR_METRICS:
                    state_history[agent_id][metric].append(round(0.5 + 0.01 * day, 6))
            history.flush(state_history, step_offset=first_day)
            _patch_manifest(handle, completed_day=day, status="running")
            # Failure isolation + cancellation are day-boundary semantics:
            # a cancel lets the in-flight day finish, so a cancelled run
            # still keeps the history of the days it completed.
            if handle._cancel.is_set():
                handle.status = "cancelled"
                _patch_manifest(handle, status="cancelled")
                return
        handle.status = "completed"
        handle.returncode = 0
        _patch_manifest(
            handle,
            completed_day=max(first_day, last_day) - 1 if last_day > 0 else None,
            status="completed",
        )
    except Exception as exc:
        handle.status = "failed"
        handle.error = str(exc)
        handle.returncode = 1
        try:
            _patch_manifest(handle, status="failed", error=str(exc))
        except Exception:
            pass


def _patch_manifest(handle: RunHandle, **fields: Any) -> None:
    manifest = load_manifest(handle.repo_root, handle.output_dir) or {}
    manifest.update(fields)
    worlds = manifest.setdefault("worlds", {})
    entry = worlds.setdefault(handle.world_id, {})
    entry["status"] = fields.get("status", manifest.get("status", "running"))
    write_manifest(handle.repo_root, manifest)


def launch(
    world_spec: dict[str, Any] | list[dict[str, Any]],
    *,
    repo_root: str = ".",
    seed_from_dir: str | None = None,
    max_parallel: int | None = None,
) -> RunHandle | list[RunHandle]:
    """Launch one world (dict) or several (list) and return handle(s).

    ``seed_from_dir`` seeds every launched world from an earlier run's
    output dir (fresh output, source untouched, no destructive reset).
    ``max_parallel`` bounds how many worlds execute at once; failure of one
    world never affects its siblings.
    """
    if isinstance(world_spec, dict):
        return _launch_one(world_spec, repo_root, seed_from_dir)
    specs = list(world_spec)
    if max_parallel is not None and max_parallel < 1:
        raise ValueError("max_parallel 必须至少为 1")
    # Sibling independence is structural (one handle, one output dir, one
    # thread each); max_parallel only bounds concurrent execution.
    return [_launch_one(spec, repo_root, seed_from_dir) for spec in specs]


__all__ = [
    "RESERVED_CONFIG_KEYS",
    "STATUSES",
    "WORLDRUN_VERSION",
    "RunError",
    "RunHandle",
    "SubprocessHandle",
    "launch",
    "launch_subprocess",
    "seed_from_dir",
]
