"""Deployment must not become anonymous when its account database goes missing."""

import http.client
import io
import json
import threading
from email.message import Message
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gaworld import accounts
from gaworld.accounts import __main__ as accounts_cli
from gaworld.apps import dashboard_server, deploy_services, world_paths


@pytest.fixture
def account_db(monkeypatch, tmp_path):
    path = tmp_path / "accounts.sqlite"
    monkeypatch.setenv("GAWORLD_ACCOUNTS_DB", str(path))
    monkeypatch.delenv("GAWORLD_REQUIRE_ACCOUNTS", raising=False)
    monkeypatch.delenv("GAWORLD_DASHBOARD_TOKEN", raising=False)
    monkeypatch.setattr(world_paths, "REPO_ROOT", str(tmp_path))
    return path


@pytest.fixture
def dashboard(account_db):
    server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard_server.DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request(port, path, method="GET", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def initialize(path):
    store = accounts.AccountStore(str(path))
    store.init_schema()
    store.create_user("review-admin", "test-only-password", role="admin")
    return store


def test_single_user_remains_opt_in(account_db):
    assert accounts.enabled_store(str(account_db.parent)) is None


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_required_mode_refuses_missing_database(account_db, monkeypatch, value):
    monkeypatch.setenv("GAWORLD_REQUIRE_ACCOUNTS", value)
    with pytest.raises(accounts.AccountConfigurationError, match="missing"):
        accounts.enabled_store(str(account_db.parent))
    assert not account_db.exists()


def test_required_mode_needs_an_admin(account_db, monkeypatch):
    monkeypatch.setenv("GAWORLD_REQUIRE_ACCOUNTS", "1")
    store = accounts.AccountStore(str(account_db))
    store.init_schema()
    store.create_user("member", "test-only-password")
    with pytest.raises(accounts.AccountConfigurationError, match="administrator"):
        accounts.enabled_store(str(account_db.parent))
    store.create_user("admin", "test-only-password", role="admin")
    assert accounts.enabled_store(str(account_db.parent)).has_admin()


def test_failed_password_validation_does_not_enable_accounts(account_db, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert accounts_cli.main(["init", "--admin", "admin", "--password-stdin"]) == 1
    assert not account_db.exists()


@pytest.mark.parametrize("mode", ["single", "token", "accounts", "required"])
def test_health_is_public_and_works_with_deploy_cli(dashboard, account_db, monkeypatch, mode):
    if mode in {"accounts", "required"}:
        initialize(account_db)
    if mode == "required":
        monkeypatch.setenv("GAWORLD_REQUIRE_ACCOUNTS", "1")
    if mode == "token":
        monkeypatch.setenv("GAWORLD_DASHBOARD_TOKEN", "operator-test-token")
    status, body = request(dashboard, "/api/health")
    assert status == 200
    payload = json.loads(body)
    assert payload == {
        "ok": True,
        "service": "gaworld-dashboard",
        "accounts": mode in {"accounts", "required"},
        "accounts_required": mode == "required",
    }
    assert request(dashboard, "/api/health", method="HEAD") == (200, b"")
    assert deploy_services._health_ok(f"http://127.0.0.1:{dashboard}/api/health")
    if mode != "single":
        assert request(dashboard, "/api/config")[0] == 401


def test_database_loss_is_fail_closed_even_for_operator(dashboard, account_db, monkeypatch):
    initialize(account_db)
    monkeypatch.setenv("GAWORLD_REQUIRE_ACCOUNTS", "1")
    monkeypatch.setenv("GAWORLD_DASHBOARD_TOKEN", "operator-test-token")
    assert request(dashboard, "/api/health")[0] == 200
    account_db.unlink()
    for path in ("/api/config", "/api/auth/me", "/login", "/api/cluster/node/bundle"):
        assert request(dashboard, path, headers={"Authorization": "Bearer operator-test-token"})[0] == 503
    assert request(dashboard, "/api/health")[0] == 503
    assert not deploy_services._health_ok(f"http://127.0.0.1:{dashboard}/api/health")


def test_corrupt_store_gives_503_not_an_open_console(dashboard, account_db, monkeypatch):
    monkeypatch.setenv("GAWORLD_REQUIRE_ACCOUNTS", "1")
    account_db.write_bytes(b"not a sqlite database")
    assert request(dashboard, "/api/health")[0] == 503
    assert request(dashboard, "/api/config")[0] == 503


@pytest.mark.parametrize(
    "body,content_type",
    [
        (b"<!doctype html><html>login</html>", "text/html"),
        (b'{"ok": true}', "application/json"),
        (b'{"ok": false, "service": "gaworld-dashboard"}', "application/json"),
        (b"[]", "application/json"),
        (b"broken", "application/json"),
    ],
)
def test_health_rejects_wrong_upstream(monkeypatch, body, content_type):
    response = io.BytesIO(body)
    response.status = 200
    response.headers = Message()
    response.headers["Content-Type"] = content_type
    monkeypatch.setattr(deploy_services, "urlopen", lambda *args, **kwargs: response)
    assert not deploy_services._health_ok("http://127.0.0.1:8766/api/health")


def test_gateway_routes_include_multi_user_entries():
    root = Path(__file__).resolve().parents[1]
    caddy = (root / "deployment/public/Caddyfile").read_text()
    for route in ("/login", "/join", "/reset", "/play/*", "/site/*", "/api/*"):
        assert route in caddy
    dropin = (root / "deployment/multi-user/gaworld-dashboard.conf").read_text()
    assert "GAWORLD_REQUIRE_ACCOUNTS=1" in dropin
    assert "GAWORLD_ACCOUNTS_DB=%h/.local/share/gaworld/accounts.sqlite" in dropin
