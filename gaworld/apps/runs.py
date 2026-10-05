"""Simulation runs started from the dashboard: one per world.

The run table (``RUN_STATE`` for the shared default world, ``WORLD_RUNS`` per
world), the FIFO queue and the admin-tunable limits that gate it, launching and
stopping the simulator subprocess, scheduled starts, the run log the panel
tails, and the simulators this process did not start (left by a crashed
dashboard, or run from the command line). Experiment worlds of
``gaworld.parallel.runner`` are admitted under the same cap.

Split out of ``dashboard_server``; its old names (``ds._start_simulation``,
``ds.RUN_QUEUE`` …) raise, pointing here.
"""

from __future__ import annotations

import contextvars
import datetime
import json
import os
import signal
import subprocess
import sys
import threading
import time

from gaworld import accounts, worlds
from gaworld.accounts import context as request_context
from gaworld.apps import world_paths as paths
from gaworld.logging_setup import get_logger
from gaworld.parallel import runner as parallel_runner

_LOG = get_logger("gaworld.dashboard")


def _ds():
    # Saving the config a start request carries is the config panel's job.
    from gaworld.apps import dashboard_server

    return dashboard_server


class RunConflict(RuntimeError):
    """A run is already going (or queued) in this world; the API answers 409."""


#: Upper bound for the first (non-incremental) run-log read. Later polls only
#: ship the bytes appended since the client's offset, so this only caps how far
#: back a freshly opened page starts; the Markdown export is never truncated.
RUN_LOG_VIEW_MAX_BYTES = 8 * 1024 * 1024


RUN_STATE = {
    "process": None,
    "started_at": None,
    "log_path": paths.RUN_LOG_PATH,
    # Pending "定时运行": the timer thread that will start the run, the wall
    # clock it fires at, the payload to start with, and the error a fired
    # timer left behind (so a failed auto-start is visible in the panel).
    "schedule": None,
}


_SCHEDULE_LOCK = threading.Lock()


def decode_log_bytes(data, aligned):
    """Decode a run-log slice without splitting a multi-byte UTF-8 character.

    Returns ``(text, consumed)``: `consumed` counts the bytes the text covers
    (including any dropped leading fragment) so the caller can keep the next
    read starting on a character boundary. `aligned` says the slice already
    starts on one, which is true for every incremental read.
    """
    skipped = 0
    if not aligned:
        while skipped < len(data) and 0x80 <= data[skipped] < 0xC0:
            skipped += 1
        data = data[skipped:]
    pending = 0
    for back in range(1, min(4, len(data)) + 1):
        byte = data[-back]
        if byte < 0x80:
            break
        if byte >= 0xC0:
            width = 2 if byte < 0xE0 else 3 if byte < 0xF0 else 4
            if back < width:
                pending = back
            break
    if pending:
        data = data[:-pending]
    return data.decode("utf-8", errors="replace"), skipped + len(data)


def run_log_slice(path, offset=None):
    """Read the run log from `offset`, or its tail when `offset` is unusable.

    The browser polls status every couple of seconds, so it sends the offset it
    already has and only receives what was appended since — that is what lets
    the panel hold the entire log instead of a trailing window.
    """
    if not os.path.exists(path):
        return {"text": "", "append": False, "offset": 0, "size": 0, "skipped": 0}
    size = os.path.getsize(path)
    append = offset is not None and 0 <= offset <= size
    start = offset if append else max(0, size - RUN_LOG_VIEW_MAX_BYTES)
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read()
    text, consumed = decode_log_bytes(data, aligned=append or start == 0)
    return {
        "text": text,
        "append": append,
        "offset": start + consumed,
        "size": size,
        # Only a replacement read can drop the head of the log; on an append
        # `start` is just where the client left off, nothing was omitted.
        "skipped": 0 if append else start,
    }


#: Runs of the per-user worlds by world id; the default world keeps RUN_STATE.
WORLD_RUNS = {}


#: Starts waiting for a free slot, oldest first. Each entry carries a copy of
#: the requesting context, so it launches in the world it was asked for.
RUN_QUEUE = []


_RUNS_LOCK = threading.RLock()


_DISPATCHER = {"thread": None}


DISPATCH_SECONDS = 2.0


#: Admin-tunable classroom limits (account database `settings`), read on every
#: check. A daily model-call quota of 0 means unlimited.
LIMIT_DEFAULTS = {"max_concurrent_runs": 4, "max_runs_per_user": 1, "daily_llm_calls_per_user": 0}


def run_state():
    world = paths.current_world()
    if not world:
        return RUN_STATE
    with _RUNS_LOCK:
        return WORLD_RUNS.setdefault(
            world["id"],
            {"process": None, "started_at": None, "log_path": paths.run_log_path(), "schedule": None},
        )


def queue_key():
    world = paths.current_world()
    return world["id"] if world else ""


def queue_position():
    with _RUNS_LOCK:
        for index, entry in enumerate(RUN_QUEUE):
            if entry["world_id"] == queue_key():
                return index + 1
    return None


def limits(store):
    return {key: store.get_setting(key, default) for key, default in LIMIT_DEFAULTS.items()}


def limited_user_id():
    """Whose per-user quota a start counts against; admins have none."""
    user = request_context.USER.get()
    if not user or user.get("role") == "admin":
        return None
    return user.get("id")


def gate_open(store, user_id):
    """Room for one more run? Only a deployment with accounts has limits."""
    if store is None:
        return True
    caps = limits(store)
    with _RUNS_LOCK:
        # A run still in its reset counts: its slot was given out under the lock.
        running = [
            state
            for state in [RUN_STATE, *WORLD_RUNS.values()]
            if state.get("starting") or (state.get("process") and state["process"].poll() is None)
        ]
    # Worlds of parallel-world experiments and research studies share the cap.
    if len(running) + parallel_runner.live_simulations() >= caps["max_concurrent_runs"]:
        return False
    mine = sum(1 for state in running if user_id is not None and state.get("started_by") == user_id)
    return user_id is None or mine < caps["max_runs_per_user"]


def admit_experiment_world():
    """Admission for experiment worlds (``parallel.runner.set_admission``):
    with accounts on they wait for a slot under ``max_concurrent_runs``."""
    return gate_open(accounts.enabled_store(paths.REPO_ROOT), None)


parallel_runner.set_admission(admit_experiment_world)


def ensure_dispatcher():
    with _RUNS_LOCK:
        thread = _DISPATCHER["thread"]
        if thread is not None and thread.is_alive():
            return
        thread = threading.Thread(target=dispatch_queue, name="run-queue", daemon=True)
        _DISPATCHER["thread"] = thread
        thread.start()


def dispatch_queue():
    """Start queued runs, oldest first, whenever the gate lets one through.

    An entry blocked only by its owner's per-user limit does not hold up the
    entries behind it.
    """
    while True:
        time.sleep(DISPATCH_SECONDS)
        ready = []
        with _RUNS_LOCK:
            if not RUN_QUEUE:
                _DISPATCHER["thread"] = None
                return
            store = accounts.enabled_store(paths.REPO_ROOT)
            for entry in list(RUN_QUEUE):
                if not gate_open(store, entry["user_id"]):
                    continue
                RUN_QUEUE.remove(entry)
                entry["context"].run(reserve, entry["user_id"])
                ready.append(entry)
        # Outside the lock: a reset can take a while, and every status poll needs it.
        for entry in ready:
            entry["context"].run(launch_queued, entry)


def reserve(user_id):
    """Claim the active world's run slot. Call with ``_RUNS_LOCK`` held; the
    reset and the launch then happen outside it."""
    state = run_state()
    state["starting"] = True
    state["started_by"] = user_id
    return state


def launch_queued(entry):
    state = run_state()
    try:
        launch(state, entry["payload"])
    except Exception as exc:
        # Nobody is waiting on this call; park the failure where the panel looks.
        _LOG.exception("Queued run failed to start: %s", exc)
        state["start_error"] = str(exc)
    finally:
        state["starting"] = False


def run_status(log_offset=None):
    state = run_state()
    proc = state.get("process")
    running = bool(proc and proc.poll() is None)
    code = None if not proc else proc.poll()
    log_path = state.get("log_path") or paths.run_log_path()
    chunk = run_log_slice(log_path, log_offset)
    schedule = state.get("schedule") or {}
    return {
        "running": running,
        # Reserved and resetting: not running yet, but a second start is refused.
        "starting": bool(state.get("starting")),
        # A simulator in this world the dashboard did not start (see _foreign_simulator_pid).
        "foreign_pid": None if running else foreign_simulator_pid(),
        "returncode": code,
        "started_at": state.get("started_at"),
        "log_path": state.get("log_path"),
        # Only a schedule that still holds a live timer is pending; one whose
        # timer already fired lingers only to carry `schedule_error`.
        "scheduled_at": schedule.get("at") if schedule.get("timer") else None,
        "schedule_error": schedule.get("error"),
        # With accounts on, a start beyond the run limits waits its turn.
        "queued": queue_position(),
        "start_error": state.get("start_error"),
        # `log_append` tells the client whether to append `log_tail` to what it
        # already shows or replace it. Clients that send no offset always get a
        # replacement, so the field stays backwards compatible.
        "log_tail": chunk["text"],
        "log_append": chunk["append"],
        "log_offset": chunk["offset"],
        "log_size": chunk["size"],
        "log_skipped_bytes": chunk["skipped"],
    }


def check_agent_ids_against_city():
    """Fail fast when the configured agent_ids do not exist in the chosen city.

    ``agent_ids`` is per-city, so switching to a smaller city leaves ids that
    point at nobody. ``build_agent`` resolves them with ``.iloc[0]`` on an empty
    match, which surfaces minutes later as a bare pandas IndexError in the run
    log — long after the operator has stopped watching. Checking here turns that
    into a sentence they can act on.
    """
    config = paths.effective_config()
    ref = str(config.get("city") or "").strip()
    if not ref:
        return
    wanted = coerce_int_list(config.get("agent_ids", []))
    if not wanted:
        return
    try:
        from gaworld.city.bundle import resolve_city

        bundle = resolve_city(ref)
    except Exception:
        return  # a broken bundle is apply_city's problem, not this check's
    available = bundle.population_count
    if available <= 0:
        raise ValueError(
            f"城市「{bundle.display_name}」还没有居民，无法运行。"
            f"先到「城市」页签生成居民，或用 python -m gaworld.city add-agents {bundle.slug} --size 200"
        )
    missing = [item for item in wanted if item > available]
    if missing:
        raise ValueError(
            f"城市「{bundle.display_name}」只有 {available} 位居民，"
            f"但 Agent IDs 里有 {missing}。请改成 1–{available} 之间的编号。"
        )


def coerce_int_list(values):
    out = []
    for item in values or []:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def is_simulator_process(pid):
    """Whether *pid* is a live ``generative_city_sim.py`` process. A pid alone
    is not enough: after a crash the manifest can name a pid since reused."""
    try:
        result = subprocess.run(
            ["ps", "-p", str(int(pid)), "-o", "command="], capture_output=True, text=True, timeout=5
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and "generative_city_sim" in result.stdout


def foreign_simulator_pid():
    """Pid of a simulator writing the active world that this dashboard did not
    start — left over from before a restart, or run from the command line.
    Read from the intervention manifest every simulator publishes at start."""
    from gaworld.apps import kernel_api
    from gaworld.kernel import remote

    data = remote.read(kernel_api._queue_path())
    if not remote.is_running(data):
        return None
    pid = data["pid"]
    own = run_state().get("process")
    if own is not None and getattr(own, "pid", None) == pid:
        return None
    return pid if is_simulator_process(pid) else None


def start_simulation(payload):
    state = run_state()
    with _RUNS_LOCK:
        proc = state.get("process")
        if state.get("starting") or (proc and proc.poll() is None):
            raise RunConflict("Simulation is already running")
        foreign = foreign_simulator_pid()
        if foreign:
            raise RunConflict(
                f"这个世界已有一个不是本控制台启动的仿真进程（pid {foreign}，"
                "可能是控制台重启前留下的或命令行启动的）。先点「停止」或结束该进程。"
            )
        if queue_position() is not None:
            raise RunConflict("Simulation is already queued")
        if isinstance(payload.get("config"), dict):
            _ds()._save_config_patch(payload["config"])
        validate_launch_config(paths.effective_config(), reset=bool(payload.get("reset")))
        check_agent_ids_against_city()
        state["start_error"] = None
        user_id = limited_user_id()
        # First come, first served: a free slot goes to the queue's head.
        if RUN_QUEUE or not gate_open(accounts.enabled_store(paths.REPO_ROOT), user_id):
            RUN_QUEUE.append(
                {
                    "world_id": queue_key(),
                    "user_id": user_id,
                    "payload": {"reset": bool(payload.get("reset"))},
                    "context": contextvars.copy_context(),
                }
            )
            ensure_dispatcher()
            return run_status()
        reserve(user_id)
    try:
        launch(state, payload)
    finally:
        state["starting"] = False
    return run_status()


def simulation_env():
    from gaworld.accounts import usage

    env = usage.child_env(os.environ.copy())
    env["PYTHONUNBUFFERED"] = "1"
    world = paths.current_world()
    if world:
        from gaworld.apps import cluster_api
        from gaworld.settings.overrides import load_env_override

        # The simulator layers these over dashboard_config.json and applies them
        # again after the city, so the world's config and paths have the last
        # word -- the same layering _effective_config() shows the panels.
        patch = worlds.read_config(paths.REPO_ROOT, world["id"])
        paths.deep_update(patch, worlds.overrides(world["id"]))
        # A world with nodes: this run is the hub's share of its residents,
        # talking to the nodes through the relay inside this dashboard.
        port = LOCAL_PORT["port"] or 8766
        paths.deep_update(patch, cluster_api.hub_overrides(world["id"], f"http://127.0.0.1:{port}"))
        paths.deep_update(patch, load_env_override())
        env["GAWORLD_CONFIG_OVERRIDES"] = json.dumps(patch, ensure_ascii=False)
    return env


def validate_launch_config(config, *, reset=False):
    from gaworld.plugins import validate_runtime_config

    # Reset discards existing checkpoints. Unsupported runtime combinations
    # and malformed seed definitions must still fail before that mutation.
    validate_runtime_config({**config, "stateful": False} if reset else config)


def launch(state, payload):
    config = paths.effective_config()
    validate_launch_config(config, reset=bool(payload.get("reset")))
    env = simulation_env()
    # World-node overlays are written when launching; inspect their actual
    # runtime configuration before resetting or spawning a child process.
    overrides = json.loads(env.get("GAWORLD_CONFIG_OVERRIDES") or "{}")
    if overrides:
        import copy

        config = copy.deepcopy(config)
        paths.deep_update(config, overrides)
        validate_launch_config(config, reset=bool(payload.get("reset")))
    log_path = paths.run_log_path()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    if payload.get("reset"):
        with open(log_path, "w", encoding="utf-8") as log_file:
            log_file.write(f"[dashboard] reset at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            reset = subprocess.run(
                [sys.executable, os.path.join(paths.REPO_ROOT, "generative_city_sim.py"), "reset"],
                cwd=paths.REPO_ROOT,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if reset.returncode != 0:
                raise RuntimeError("Reset failed; check dashboard run log")
        validate_launch_config(config)
    log_mode = "a" if payload.get("reset") else "w"
    log_file = open(log_path, log_mode, encoding="utf-8")
    log_file.write(f"\n[dashboard] run at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    log_file.flush()
    proc = subprocess.Popen(
        [sys.executable, os.path.join(paths.REPO_ROOT, "generative_city_sim.py"), "run"],
        cwd=paths.REPO_ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    state["process"] = proc
    state["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    # A distributed world's run id: nodes start their share when they see it.
    overrides = json.loads(env.get("GAWORLD_CONFIG_OVERRIDES") or "{}")
    state["run_id"] = (overrides.get("cluster") or {}).get("run_id") or ""
    state["log_path"] = log_path
    state["started_by"] = limited_user_id()


def parse_schedule_time(raw):
    """Parse the ``datetime-local`` value the dashboard sends ("2026-08-30T21:30").

    Naive local time on purpose: the timer fires against the server's own clock,
    and the dashboard is a local console — browser and server share a machine.
    A value that does carry an offset is converted to local time first.
    """
    text = str(raw or "").strip().replace(" ", "T")
    if not text:
        raise ValueError("Scheduled time is required")
    try:
        when = datetime.datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"Invalid scheduled time: {raw}")
    if when.tzinfo is not None:
        when = when.astimezone().replace(tzinfo=None)
    return when


def schedule_simulation(payload):
    """Arm a timer that starts the simulation at the requested wall clock.

    The config from the form is kept with the schedule and applied when the
    timer fires, so a scheduled run behaves exactly like pressing 运行仿真 then.
    """
    when = parse_schedule_time(payload.get("at"))
    delay = (when - datetime.datetime.now()).total_seconds()
    if delay <= 0:
        raise ValueError("Scheduled time must be in the future")
    start_payload = {
        "reset": bool(payload.get("reset")),
        "config": payload.get("config"),
    }
    with _SCHEDULE_LOCK:
        state = run_state()
        previous = state.get("schedule") or {}
        if previous.get("timer"):
            previous["timer"].cancel()
        # The timer thread starts with an empty context; hand it this request's
        # world and user so the run starts where it was scheduled.
        timer = threading.Timer(delay, contextvars.copy_context().run, args=(fire_scheduled_simulation,))
        timer.daemon = True
        state["schedule"] = {
            "at": when.strftime("%Y-%m-%d %H:%M:%S"),
            "timer": timer,
            "payload": start_payload,
            "error": None,
        }
        timer.start()
    return run_status()


def cancel_scheduled_simulation():
    with _SCHEDULE_LOCK:
        state = run_state()
        schedule = state.get("schedule") or {}
        if schedule.get("timer"):
            schedule["timer"].cancel()
        state["schedule"] = None
    return run_status()


def fire_scheduled_simulation():
    with _SCHEDULE_LOCK:
        schedule = run_state().get("schedule")
        if not schedule:
            return
        # Drop the timer first: from here on the schedule is spent, and the
        # entry only survives long enough to report a failed start.
        schedule["timer"] = None
        start_payload = schedule.get("payload") or {}
    try:
        start_simulation(start_payload)
    except Exception as exc:
        # Nobody is waiting on this call, so a failure has to be parked where
        # /api/run/status can show it instead of raising into the timer thread.
        _LOG.exception("Scheduled run failed to start: %s", exc)
        with _SCHEDULE_LOCK:
            schedule = run_state().get("schedule")
            if schedule:
                schedule["error"] = str(exc)
    else:
        with _SCHEDULE_LOCK:
            run_state()["schedule"] = None


def stop_simulation():
    with _RUNS_LOCK:
        RUN_QUEUE[:] = [entry for entry in RUN_QUEUE if entry["world_id"] != queue_key()]
    proc = run_state().get("process")
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
    else:
        # Nothing of ours: stop the world's simulator this process lost track of.
        foreign = foreign_simulator_pid()
        if foreign:
            try:
                os.kill(foreign, signal.SIGTERM)
            except OSError as exc:
                _LOG.warning("could not stop simulator pid %s: %s", foreign, exc)
    return run_status()


def stop_all_simulations():
    """Server shutdown: no world's simulator outlives the dashboard."""
    with _RUNS_LOCK:
        RUN_QUEUE.clear()
        states = [RUN_STATE, *WORLD_RUNS.values()]
    for state in states:
        proc = state.get("process")
        if proc and proc.poll() is None:
            proc.terminate()
    for state in states:
        proc = state.get("process")
        if proc and proc.poll() is None:
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


#: The dashboard's own port, for the hub simulator of a distributed world
#: to reach the relay and tick sync (gaworld.cluster). Set by every request.
LOCAL_PORT = {"port": None}


#: Name in ``dashboard_server`` before the split -> name here; its guard
#: (``dashboard_server._MovedNamesGuard``) points stale uses at these.
DASHBOARD_ALIASES = {
    "RUN_STATE": "RUN_STATE",
    "WORLD_RUNS": "WORLD_RUNS",
    "RUN_QUEUE": "RUN_QUEUE",
    "_RUNS_LOCK": "_RUNS_LOCK",
    "_DISPATCHER": "_DISPATCHER",
    "DISPATCH_SECONDS": "DISPATCH_SECONDS",
    "LIMIT_DEFAULTS": "LIMIT_DEFAULTS",
    "_SCHEDULE_LOCK": "_SCHEDULE_LOCK",
    "LOCAL_PORT": "LOCAL_PORT",
    "RUN_LOG_VIEW_MAX_BYTES": "RUN_LOG_VIEW_MAX_BYTES",
    "limits": "limits",
    "_run_state": "run_state",
    "_queue_key": "queue_key",
    "_queue_position": "queue_position",
    "_limited_user_id": "limited_user_id",
    "_gate_open": "gate_open",
    "_admit_experiment_world": "admit_experiment_world",
    "_ensure_dispatcher": "ensure_dispatcher",
    "_dispatch_queue": "dispatch_queue",
    "_reserve": "reserve",
    "_launch_queued": "launch_queued",
    "_run_status": "run_status",
    "_check_agent_ids_against_city": "check_agent_ids_against_city",
    "_coerce_int_list": "coerce_int_list",
    "_is_simulator_process": "is_simulator_process",
    "_foreign_simulator_pid": "foreign_simulator_pid",
    "_start_simulation": "start_simulation",
    "_simulation_env": "simulation_env",
    "_launch": "launch",
    "_parse_schedule_time": "parse_schedule_time",
    "_schedule_simulation": "schedule_simulation",
    "_cancel_scheduled_simulation": "cancel_scheduled_simulation",
    "_fire_scheduled_simulation": "fire_scheduled_simulation",
    "_stop_simulation": "stop_simulation",
    "_stop_all_simulations": "stop_all_simulations",
    "_decode_log_bytes": "decode_log_bytes",
    "_run_log_slice": "run_log_slice",
}
