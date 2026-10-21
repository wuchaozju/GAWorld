"""GAWorld-managed FOS backend lifecycle (integrated mode).

Canonical startup is:

    gaworld dashboard

``dashboard_server.run_server`` calls :func:`ensure_backend` before serving
and :func:`shutdown_backend` in its finally block, so the user never runs
uvicorn or sets FOS_SINGLE_USER_MODE manually.

Semantics:

- explicit ``FOS_BACKEND_URL`` (set to anything) means the user configured an
  external backend: nothing is spawned or probed here;
- default target is ``http://127.0.0.1:8000``; if something already listens
  there it is probed via the unauthenticated ``/api/config``:
  * healthy AND ``single_user_mode == true`` -> reused, NOT owned (never killed);
  * ``single_user_mode == false`` (standalone authenticated FOS) -> hard error,
    the integrated UI would otherwise show a login screen;
  * anything else -> hard error, never kill unknown processes;
- a spawned backend uses ``sys.executable -m uvicorn fos.backend.main:app``,
  loopback only, in an additive environment copy with
  ``FOS_SINGLE_USER_MODE=true`` / ``FOS_SINGLE_USER_USERNAME=local`` (and
  ``FOS_SINGLE_USER_ALLOW_REMOTE_BIND`` removed if present);
- readiness is verified by bounded polling of ``/api/config``;
- shutdown terminates only the process GAWorld spawned.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FOS_SRC = os.path.join(REPO_ROOT, "fos", "src")
DEFAULT_FOS_PORT = 8000
DEFAULT_FOS_URL = "http://127.0.0.1:%d" % DEFAULT_FOS_PORT
POLL_INTERVAL_S = 0.25
DEFAULT_POLL_ATTEMPTS = 240  # ~60s at 0.25s


class FosBackendError(RuntimeError):
    """Raised when the integrated FOS backend cannot be provided."""


def backend_base_url() -> str:
    """Base URL of the FOS backend (explicit config wins)."""
    return os.environ.get("FOS_BACKEND_URL", DEFAULT_FOS_URL).rstrip("/")


def build_child_env(base=None):
    """Additive environment for the managed integrated FOS backend."""
    env = dict(os.environ if base is None else base)
    env["FOS_SINGLE_USER_MODE"] = "true"
    env["FOS_SINGLE_USER_USERNAME"] = "local"
    # Integrated mode is loopback-only; never inherit a remote-bind override.
    env.pop("FOS_SINGLE_USER_ALLOW_REMOTE_BIND", None)
    existing = env.get("PYTHONPATH", "")
    parts = [p for p in existing.split(os.pathsep) if p]
    if FOS_SRC not in parts:
        parts.insert(0, FOS_SRC)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _probe_config(base_url, timeout=3.0):
    """Fetch /api/config; None if unreachable or not a FOS backend."""
    try:
        with urllib.request.urlopen(base_url + "/api/config", timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _spawn_backend(port):
    """Start the managed FOS backend; returns the owned Popen."""
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "fos.backend.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    log = tempfile.NamedTemporaryFile(
        prefix="gaworld-fos-backend-", suffix=".log", delete=False
    )
    log_path = log.name
    log.close()
    handle = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        cmd,
        cwd=REPO_ROOT,
        env=build_child_env(),
        stdout=open(log_path, "ab"),
        stderr=subprocess.STDOUT,
    )
    handle._gaworld_fos_log = log_path  # type: ignore[attr-defined]
    return handle


def ensure_backend(port=DEFAULT_FOS_PORT, poll_attempts=DEFAULT_POLL_ATTEMPTS):
    """Provide a running integrated FOS backend.

    Returns a handle dict ({"owned": bool, "url": str, ...}) or None when an
    explicit external FOS_BACKEND_URL is configured. Raises FosBackendError
    with an actionable message when an integrated backend cannot be provided.
    """
    if os.environ.get("FOS_BACKEND_URL"):
        # Explicit external backend configuration: not ours to manage.
        return None
    base_url = "http://127.0.0.1:%d" % port

    existing = _probe_config(base_url)
    if existing is not None:
        if existing.get("single_user_mode") is True:
            print("FOS backend: reusing integrated backend at " + base_url)
            return {"owned": False, "url": base_url}
        raise FosBackendError(
            "Port %d is occupied by a standalone/authenticated FOS backend " % port
            + "(single_user_mode=false). Stop it and rerun `gaworld dashboard`, "
            "or explicitly configure an external backend via FOS_BACKEND_URL."
        )
    if _port_probe_responds(base_url):
        raise FosBackendError(
            "Port %d is occupied by an unrecognized process that is not a FOS " % port
            + "backend. Free the port and rerun `gaworld dashboard`."
        )

    popen = _spawn_backend(port)
    for _ in range(poll_attempts):
        if popen.poll() is not None:
            log_path = getattr(popen, "_gaworld_fos_log", "<unknown>")
            raise FosBackendError(
                ("The managed FOS backend exited during startup (exit code %s). "
                % popen.returncode)
                + "See its log: " + log_path
            )
        cfg = _probe_config(base_url, timeout=1.0)
        if cfg is not None:
            if cfg.get("single_user_mode") is True:
                print("FOS backend: ready at " + base_url + " (integrated mode)")
                return {"owned": True, "url": base_url, "_popen": popen}
            _terminate(popen)
            raise FosBackendError(
                "The managed FOS backend started WITHOUT integrated single-user "
                "mode; refusing to serve a FOS login screen. Check FOS_* "
                "environment overrides and rerun `gaworld dashboard`."
            )
        time.sleep(POLL_INTERVAL_S)
    _terminate(popen)
    raise FosBackendError(
        "The managed FOS backend did not become ready on " + base_url
        + " in time. See the backend log and rerun `gaworld dashboard`."
    )


def _port_probe_responds(base_url):
    """True if anything answers on / (FOS SPA or otherwise)."""
    try:
        with urllib.request.urlopen(base_url + "/", timeout=2.0) as resp:
            return resp.status < 500
    except (urllib.error.URLError, OSError):
        return False


def _terminate(popen):
    if popen.poll() is None:
        popen.terminate()
        try:
            popen.wait(timeout=10)
        except subprocess.TimeoutExpired:
            popen.kill()
            popen.wait(timeout=5)


def shutdown_backend(handle):
    """Terminate the backend only if GAWorld spawned it."""
    if not handle or not handle.get("owned"):
        return
    popen = handle.get("_popen")
    if popen is not None:
        _terminate(popen)
        print("FOS backend: stopped.")

