"""Regression tests for the integration/fos × origin/Dev merge resolutions.

Covers the agreed FOS single-user/multi-user gating decision and the union
resolutions (Caddyfile path matcher, dashboard locales).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gaworld import accounts
from gaworld.apps import dashboard_server

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Multi-user mode refuses to serve without an initialized account DB."""
    monkeypatch.setenv("GAWORLD_ACCOUNTS_DB", str(tmp_path / "accounts.sqlite"))
    instance = accounts.AccountStore(str(tmp_path / "accounts.sqlite"))
    instance.init_schema()
    instance.create_user("admin", "correct horse", role="admin")
    return instance


class _DummyServer:
    def __init__(self, addr, handler):
        self.server_close = MagicMock()

    def serve_forever(self):
        raise KeyboardInterrupt()


def _run_server(monkeypatch, multi_user, fos_opt_in=False):
    ensure = MagicMock(return_value=None)
    shutdown = MagicMock()
    monkeypatch.setattr(dashboard_server, "_ensure_fos_backend", ensure)
    monkeypatch.setattr(dashboard_server, "_shutdown_fos_backend", shutdown)
    monkeypatch.setattr(dashboard_server, "ThreadingHTTPServer", _DummyServer)
    monkeypatch.delenv("FOS_BACKEND_URL", raising=False)
    monkeypatch.delenv("GAWORLD_FOS_BACKEND", raising=False)
    if fos_opt_in:
        monkeypatch.setenv("GAWORLD_FOS_BACKEND", "1")
    dashboard_server.run_server(port=0, multi_user=multi_user)
    return ensure, shutdown


def test_multi_user_disables_fos_backend_by_default(monkeypatch, store):
    """The loginless FOS backend must not start in multi-user mode."""
    ensure, shutdown = _run_server(monkeypatch, multi_user=True)
    ensure.assert_not_called()
    shutdown.assert_called_once_with(None)


def test_multi_user_fos_backend_requires_explicit_opt_in(monkeypatch, store):
    """GAWORLD_FOS_BACKEND=1 is the explicit operator opt-in."""
    monkeypatch.setenv("GAWORLD_FOS_BACKEND", "1")
    ensure, shutdown = _run_server(monkeypatch, multi_user=True, fos_opt_in=True)
    ensure.assert_called_once()
    shutdown.assert_called_once()


def test_single_user_starts_fos_backend(monkeypatch):
    ensure, shutdown = _run_server(monkeypatch, multi_user=False)
    ensure.assert_called_once()
    shutdown.assert_called_once()


def test_single_user_degrades_gracefully_without_fos_build(monkeypatch):
    """A plain GAWorld install (no fos/frontend/dist) still boots the console."""
    from gaworld.apps.fos_supervisor import FosBackendError

    def _fail():
        raise FosBackendError("No FOS frontend build found.")

    shutdown = MagicMock()
    monkeypatch.setattr(dashboard_server, "_ensure_fos_backend", _fail)
    monkeypatch.setattr(dashboard_server, "_shutdown_fos_backend", shutdown)
    monkeypatch.setattr(dashboard_server, "ThreadingHTTPServer", _DummyServer)
    monkeypatch.delenv("GAWORLD_FOS_BACKEND", raising=False)
    dashboard_server.run_server(port=0, multi_user=False)  # must not raise SystemExit
    shutdown.assert_called_once_with(None)


def test_caddyfile_unions_multi_user_and_fos_paths():
    """@app basic-auth matcher keeps both the community paths and /fos/*."""
    text = (REPO_ROOT / "deployment" / "public" / "Caddyfile").read_text(encoding="utf-8")
    app_lines = [line for line in text.splitlines() if "@app path" in line]
    assert len(app_lines) == 1, "exactly one @app matcher expected"
    paths = set(app_lines[0].split())
    for required in (
        "/fos",
        "/fos/*",
        "/register",
        "/verify",
        "/recover",
        "/workspace",
        "/workspace/",
        "/explore",
        "/plaza",
        "/publications/*",
        "/people/*",
        "/posts/*",
        "/read.doc",
    ):
        assert required in paths, f"{required} missing from the Caddyfile @app matcher"


@pytest.mark.parametrize("locale", ["en", "zh-CN"])
def test_locale_key_union(locale):
    """Both locales carry the FOS keys and the multi-user/community keys."""
    data = json.loads(
        (REPO_ROOT / "site" / "dashboard" / "locales" / f"{locale}.json").read_text(encoding="utf-8")
    )
    for key in (
        "nav.fos",
        "studio.generate",
        "studio.cancel",
        "nav.group_workspace",
        "nav.group_community",
        "nav.plaza",
        "oi3.tab",
    ):
        assert key in data, f"{key} missing from {locale}.json"
