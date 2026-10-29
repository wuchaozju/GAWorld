"""Dashboard startup has an explicit opt-in multi-user boundary."""

import contextlib
import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest

from gaworld import accounts
from gaworld.apps import dashboard_server


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("GAWORLD_ACCOUNTS_DB", str(tmp_path / "accounts.sqlite"))
    monkeypatch.delenv("GAWORLD_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("GAWORLD_MULTI_USER", raising=False)
    instance = accounts.AccountStore(str(tmp_path / "accounts.sqlite"))
    instance.init_schema()
    instance.create_user("admin", "correct horse", role="admin")
    return instance


@contextlib.contextmanager
def http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard_server.DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def request(port, path, method="GET", body=None, cookie=""):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    data = None if body is None else json.dumps(body)
    conn.request(method, path, data, {"Content-Type": "application/json", "Cookie": cookie})
    response = conn.getresponse()
    raw = response.read()
    conn.close()
    return response, raw


@pytest.mark.parametrize(
    "arguments,enabled",
    [
        ([], False),
        (["--multi-user", "True"], True),
        (["--multi-user", "False"], False),
        (["--multi-user"], True),
    ],
)
def test_cli_boolean_switch(arguments, enabled, monkeypatch):
    from gaworld.apps.dashboard_cli import main

    launch = Mock()
    monkeypatch.setattr(dashboard_server, "run_server", launch)
    main(arguments)
    launch.assert_called_once_with(host="127.0.0.1", port=8766, multi_user=enabled)


def test_explicit_single_mode_ignores_existing_database_and_legacy_env(store, monkeypatch):
    monkeypatch.setenv("GAWORLD_MULTI_USER", "False")
    monkeypatch.setenv("GAWORLD_REGISTRATION", "open")
    monkeypatch.setenv("GAWORLD_REQUIRE_ACCOUNTS", "1")
    assert accounts.enabled_store(str(Path(store.path).parent)) is None
    assert accounts.required() is False
    from gaworld.accounts.usage import usage_path

    assert usage_path() is None
    with http_server() as port:
        assert json.loads(request(port, "/api/auth/me")[1]) == {"mode": "single"}
        for path in (
            "/console",
            "/dashboard",
            "/site/dashboard/research.html",
            "/site/dashboard/games.html",
            "/site/dashboard/studio.html",
            "/site/simviz/index.html",
            "/site/dashboard/settings.html",
        ):
            assert request(port, path)[0].status == 200, path
        assert request(port, "/api/interventions")[0].status == 200
        assert request(port, "/api/research/analyze", "POST", {})[0].status == 400


def test_multi_mode_gates_pages_and_api_and_allows_login(store, monkeypatch):
    monkeypatch.setenv("GAWORLD_MULTI_USER", "True")
    with http_server() as port:
        for method in ("GET", "HEAD"):
            for path in (
                "/console",
                "/dashboard",
                "/site/dashboard/research.html",
                "/site/dashboard/games.html",
                "/site/dashboard/studio.html",
                "/site/simviz/index.html",
                "/site/dashboard/settings.html",
            ):
                assert request(port, path, method)[0].status == 303, path
        for path in ("/api/config", "/api/interventions", "/api/research/context", "/api/run/status"):
            assert request(port, path)[0].status == 401, path
        assert request(port, "/api/research/analyze", "POST", {})[0].status == 401
        for path in (
            "/",
            "/login",
            "/register",
            "/explore",
            "/plaza",
            "/site/home/style.css",
            "/site/home/app.js",
        ):
            assert request(port, path)[0].status == 200, path
        response, _ = request(
            port, "/api/auth/login", "POST", {"nickname": "admin", "password": "correct horse"}
        )
        assert response.status == 200
        cookie = response.getheader("Set-Cookie").split(";")[0]
        assert request(port, "/console", cookie=cookie)[0].status == 200
        assert request(port, "/api/interventions", cookie=cookie)[0].status == 200


def test_run_server_default_and_true_set_process_mode_and_restore_it(store, monkeypatch):
    observations = []

    class Server:
        def __init__(self, *args):
            pass

        def serve_forever(self):
            observations.append(accounts.enabled_store(str(Path(store.path).parent)) is not None)

        def server_close(self):
            pass

    monkeypatch.setattr(dashboard_server, "ThreadingHTTPServer", Server)
    monkeypatch.setattr(dashboard_server.runs, "stop_all_simulations", lambda: None)
    monkeypatch.setattr(dashboard_server, "_reset_collaboration_service_for_tests", lambda: None)
    dashboard_server.run_server()
    dashboard_server.run_server(multi_user=True)
    assert observations == [False, True]
    import os

    assert "GAWORLD_MULTI_USER" not in os.environ


def test_multi_user_startup_rejects_missing_account_database(tmp_path, monkeypatch):
    monkeypatch.setenv("GAWORLD_ACCOUNTS_DB", str(tmp_path / "missing.sqlite"))
    with pytest.raises(accounts.AccountConfigurationError):
        dashboard_server.run_server(port=0, multi_user=True)
    assert not (tmp_path / "missing.sqlite").exists()


@pytest.mark.parametrize(
    "entry",
    [
        ["-m", "gaworld.apps.dashboard_server"],
        ["dashboard_server.py"],
        ["generative_city_sim.py", "dashboard"],
    ],
)
@pytest.mark.parametrize("enabled", [False, True])
def test_real_startup_entrypoints_select_mode(entry, enabled, store, monkeypatch):
    import os
    import socket
    import subprocess
    import sys
    import time

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, GAWORLD_REGISTRATION="open", GAWORLD_REQUIRE_ACCOUNTS="1")
    command = [sys.executable, *entry, "--port", str(port)]
    if enabled:
        command.extend(["--multi-user", "True"])
    process = subprocess.Popen(
        command,
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                response, raw = request(port, "/api/health")
                break
            except OSError:
                if process.poll() is not None or time.monotonic() > deadline:
                    pytest.fail(f"dashboard did not start: {command}")
                time.sleep(0.05)
        assert response.status == 200
        assert json.loads(raw)["accounts"] is enabled
        assert request(port, "/site/dashboard/research.html")[0].status == (303 if enabled else 200)
        assert request(port, "/api/interventions")[0].status == (401 if enabled else 200)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
