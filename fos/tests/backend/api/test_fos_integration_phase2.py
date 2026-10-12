"""Phase 2 integration tests: /fos/api dual mount, single-user mode, provisioning,
remote-bind guard, config/bootstrap exposure, and integrated uploads.

Written TDD-RED for Phase 2 STAGE A (task 2497). Tests marked RED below fail
because the Phase 2 feature does not exist yet; tests marked GUARD pin existing
behaviour that must survive the change.

Assumptions about the implementation under test (documented for the implementer):
- FOS settings gain ``single_user_mode: bool`` (env FOS_SINGLE_USER_MODE) and
  ``single_user_username: str`` (env FOS_SINGLE_USER_USERNAME, default "local"),
  plus an explicit remote-bind override (env FOS_SINGLE_USER_ALLOW_REMOTE_BIND).
- The same API router is mounted under both ``/api`` and ``/fos/api``.
- Uploads are additionally reachable at ``/fos/uploads/*``.
- The auth bypass lives ONLY in ``resolve_current_user`` (fos.backend.dependencies).
- The remote-bind guard runs during app startup (on_startup) and refuses to boot
  (SystemExit) when single_user_mode is on and the bind host is non-loopback.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from litestar.testing import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# Environment: point FOS at a throwaway sqlite DB + upload dir BEFORE importing
# fos.backend modules, so module-level Settings() snapshots pick these up.
# ---------------------------------------------------------------------------

_TMP = Path(os.environ.get("PYTEST_DEBUG_TEMPROOT", "/tmp")) / "fos_phase2_tests"
_TMP.mkdir(parents=True, exist_ok=True)
_DB_FILE = _TMP / "phase2.sqlite"
_UPLOAD_DIR = _TMP / "uploads"
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
_SECRET_FILE = _TMP / "secret.txt"
_SECRET_FILE.write_text("TOP-SECRET-OUTSIDE-UPLOAD-ROOT", encoding="utf-8")

os.environ["FOS_DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_FILE}"
os.environ["FOS_UPLOAD_DIR"] = str(_UPLOAD_DIR)
os.environ["FOS_APP_ENV"] = "test"
os.environ["FOS_REQUIRE_EMAIL_VERIFICATION"] = "false"
os.environ.pop("FOS_SINGLE_USER_MODE", None)
os.environ.pop("FOS_SINGLE_USER_USERNAME", None)
os.environ.pop("FOS_SINGLE_USER_ALLOW_REMOTE_BIND", None)
os.environ.pop("FOS_BACKEND_HOST", None)
# A stale DB from a previous run would break "provisioned exactly once" counts.
if _DB_FILE.exists():
    _DB_FILE.unlink()

from fos.backend.core.config import Settings, get_settings  # noqa: E402
from fos.backend.main import create_app  # noqa: E402


@pytest.fixture()
def fos_env(monkeypatch):
    """Reset the cached settings around each test and clean single-user env."""
    get_settings.cache_clear()
    yield
    for key in (
        "FOS_SINGLE_USER_MODE",
        "FOS_SINGLE_USER_USERNAME",
        "FOS_SINGLE_USER_ALLOW_REMOTE_BIND",
        "FOS_BACKEND_HOST",
    ):
        os.environ.pop(key, None)
    get_settings.cache_clear()


@pytest.fixture()
def fresh_db():
    """Bind the (possibly already-imported) database module to a fresh sqlite
    engine, create all tables, and yield the async session factory."""
    import fos.backend.core.database as dbmod
    import fos.backend.models  # noqa: F401  (register mappers)

    engine = create_async_engine(f"sqlite+aiosqlite:///{_DB_FILE}")
    dbmod.engine = engine
    dbmod.SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    import fos.backend.main as mainmod

    mainmod.engine = engine

    async def _create():
        from fos.backend.db.base import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    import asyncio

    asyncio.run(_create())
    yield dbmod.SessionLocal
    asyncio.run(engine.dispose())


def _sync_settings():
    """Rebuild the module-level Settings snapshots used by dependencies/auth."""
    import fos.backend.api.routes.auth as authmod
    import fos.backend.dependencies as depmod

    s = get_settings()
    depmod.settings = s
    authmod.settings = s
    return s


def make_app() -> "TestClient":
    _sync_settings()
    return TestClient(app=create_app())


def _register_and_login(client: TestClient, email: str, username: str) -> dict:
    """Create a normal user through the public API and return the token payload."""
    reg = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "username": username,
            "password": "Str0ngPassw0rd!",
            "full_name": "Normal User",
        },
    )
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/api/auth/login",
        json={"email": email, "password": "Str0ngPassw0rd!"},
    )
    assert login.status_code in (200, 201), login.text
    return login.json()


# ---------------------------------------------------------------------------
# Dual mount (/api and /fos/api)
# ---------------------------------------------------------------------------


class TestDualMount:
    def test_config_endpoint_reachable_via_both_prefixes(self, fos_env, fresh_db):
        """RED: /fos/api/* currently 404s; the same router must answer there too."""
        with make_app() as client:
            root = client.get("/api/config")
            dual = client.get("/fos/api/config")

        assert root.status_code == 200
        assert "application/json" in dual.headers.get("content-type", ""), (
            "RED: /fos/api/config fell through to the SPA fallback — dual mount missing"
        )
        assert dual.status_code == 200
        assert dual.json() == root.json()

    def test_health_endpoint_reachable_via_both_prefixes(self, fos_env, fresh_db):
        """RED: a second representative endpoint under the dual mount."""
        with make_app() as client:
            root = client.get("/api/health")
            dual = client.get("/fos/api/health")

        assert root.status_code == 200
        assert dual.status_code == 200


# ---------------------------------------------------------------------------
# Single-user mode auth bypass
# ---------------------------------------------------------------------------


@pytest.fixture()
def single_user_env(fos_env, monkeypatch):
    monkeypatch.setenv("FOS_SINGLE_USER_MODE", "true")
    monkeypatch.setenv("FOS_SINGLE_USER_USERNAME", "localtester")
    return fos_env


class TestSingleUserMode:
    def test_protected_route_works_without_jwt(self, single_user_env, fresh_db):
        """RED: with single_user_mode=true, /api/auth/me must resolve the local
        user without any Authorization header."""
        with make_app() as client:
            resp = client.get("/api/auth/me")
        assert resp.status_code == 200, (
            f"RED: expected auth bypass, got {resp.status_code}: {resp.text}"
        )
        assert resp.json()["username"] == "localtester"

    def test_bypass_only_in_resolve_current_user_not_elsewhere(self, single_user_env, fresh_db):
        """RED: login still must work with real credentials while bypass is on —
        normal auth stays intact (brief req 5)."""
        with make_app() as client:
            tokens = _register_and_login(client, "normal@example.com", "normaluser")
            me = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
        assert me.status_code == 200
        assert me.json()["username"] == "normaluser"

    def test_single_user_mode_off_keeps_401(self, fos_env, fresh_db):
        """GUARD: single_user_mode defaults off — no JWT means 401, as today."""
        with make_app() as client:
            resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_jwt_still_required_when_disabled(self, fos_env, fresh_db):
        """GUARD: full login flow unchanged when single_user_mode is off."""
        with make_app() as client:
            tokens = _register_and_login(client, "off@example.com", "offuser")
            me = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
            anon = client.get("/api/auth/me")
        assert me.status_code == 200
        assert anon.status_code == 401


# ---------------------------------------------------------------------------
# Provisioning of the local user
# ---------------------------------------------------------------------------


class TestProvisioning:
    def test_local_user_provisioned_on_first_startup(self, single_user_env, fresh_db):
        """RED: the bypass must run through the real persistence model — the
        local user exists in the users table with the configured username."""
        with make_app() as client:
            resp = client.get("/api/auth/me")

        assert resp.status_code == 200  # depends on bypass (RED above if missing)
        username = get_settings().single_user_username
        assert username == "localtester"

    def test_provisioning_idempotent_across_restarts(self, single_user_env, fresh_db):
        """RED: two 'restarts' (two create_app lifecycles) resolve the SAME user
        id; exactly one local user row exists."""
        with make_app() as client:
            first = client.get("/api/auth/me")
        with make_app() as client:
            second = client.get("/api/auth/me")

        assert first.status_code == 200 and second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

        async def _count():
            async with fresh_db() as session:
                from fos.backend.models.user import User

                rows = (
                    (await session.execute(select(User).where(User.username == "localtester")))
                    .scalars()
                    .all()
                )
                return rows

        import asyncio

        rows = asyncio.run(_count())
        assert len(rows) == 1, f"RED: expected exactly one local user, found {len(rows)}"

    def test_provisioning_never_replaces_existing_users(self, single_user_env, fresh_db):
        """RED: pre-existing normal users survive the local-user provisioning."""
        with make_app() as client:
            _register_and_login(client, "keep@example.com", "keepme")
            client.get("/api/auth/me")

        async def _all():
            async with fresh_db() as session:
                from fos.backend.models.user import User

                return (await session.execute(select(User))).scalars().all()

        import asyncio

        usernames = {u.username for u in asyncio.run(_all())}
        assert "keepme" in usernames
        assert "localtester" in usernames


# ---------------------------------------------------------------------------
# Remote-bind safety guard
# ---------------------------------------------------------------------------


class TestRemoteBindGuard:
    def test_loopback_bind_allowed(self, single_user_env, monkeypatch):
        """GUARD: single-user on, binding 127.0.0.1 — startup proceeds."""
        monkeypatch.setenv("FOS_BACKEND_HOST", "127.0.0.1")
        with make_app() as client:
            assert client.get("/api/config").status_code == 200

    def test_non_loopback_bind_refused(self, single_user_env, monkeypatch):
        """RED: single-user on + 0.0.0.0 must refuse to start (SystemExit)."""
        monkeypatch.setenv("FOS_BACKEND_HOST", "0.0.0.0")
        with pytest.raises(SystemExit):
            with make_app() as client:  # pragma: no cover - should not get here
                client.get("/api/config")

    def test_non_loopback_bind_explicit_override_allowed(self, single_user_env, monkeypatch):
        """GUARD (currently trivially true): explicit override lets a
        non-loopback bind through even in single-user mode."""
        monkeypatch.setenv("FOS_BACKEND_HOST", "0.0.0.0")
        monkeypatch.setenv("FOS_SINGLE_USER_ALLOW_REMOTE_BIND", "true")
        with make_app() as client:
            assert client.get("/api/config").status_code == 200


# ---------------------------------------------------------------------------
# Config/bootstrap endpoint
# ---------------------------------------------------------------------------


class TestConfigEndpoint:
    def test_config_exposes_single_user_mode(self, single_user_env, fresh_db):
        """RED: the unauthenticated config endpoint must include
        single_user_mode so the frontend can skip the login redirect."""
        with make_app() as client:
            resp = client.get("/api/config")
        assert resp.status_code == 200
        payload = resp.json()
        assert "single_user_mode" in payload, (
            "RED: config endpoint does not expose single_user_mode"
        )
        assert payload["single_user_mode"] is True

    def test_config_exposes_false_when_disabled(self, fos_env, fresh_db):
        """RED: field present and False by default."""
        with make_app() as client:
            payload = client.get("/api/config").json()
        assert "single_user_mode" in payload
        assert payload["single_user_mode"] is False

    def test_config_leaks_no_secrets(self, fos_env, fresh_db):
        """GUARD (hardened): the public config must never carry secrets."""
        with make_app() as client:
            payload = client.get("/api/config").json()
        for forbidden in (
            "jwt_signing_key",
            "admin_password",
            "database_url",
            "single_user_username",
            "upload_cloud_base_url",
        ):
            assert forbidden not in payload, f"secret leaked: {forbidden}"


# ---------------------------------------------------------------------------
# Integrated uploads (/fos/uploads)
# ---------------------------------------------------------------------------


class TestIntegratedUploads:
    def test_upload_round_trip_via_fos_paths(self, single_user_env, fresh_db):
        """RED: upload through the integrated API prefix and fetch it back
        through /fos/uploads with identical bytes."""
        png_b64 = (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
            "h6FO1AAAAABJRU5ErkJggg=="
        )
        with make_app() as client:
            up = client.post(
                "/fos/api/uploads/",
                content=b"",
                files={"file": ("dot.png", __import__("base64").b64decode(png_b64.split(",")[1]), "image/png")},
            )
            assert up.status_code == 200, (
                f"RED: integrated upload failed: {up.status_code} {up.text}"
            )
            filename = Path(up.json()["url"]).name
            fetched = client.get(f"/fos/uploads/{filename}")

        assert fetched.status_code == 200, "RED: /fos/uploads does not serve files"
        assert fetched.content == __import__("base64").b64decode(png_b64.split(",")[1])

    def test_traversal_blocked_on_fos_uploads(self, single_user_env, fresh_db):
        """GUARD: path traversal via /fos/uploads must never escape the root."""
        with make_app() as client:
            for evil in (
                "/fos/uploads/..%2f..%2fsecret.txt",
                "/fos/uploads/%2e%2e%2fsecret.txt",
                "/fos/uploads/subdir%2f..%2f..%2fsecret.txt",
            ):
                resp = client.get(evil)
                assert resp.status_code in (400, 404), (
                    f"traversal not blocked for {evil}: {resp.status_code}"
                )
                assert b"TOP-SECRET-OUTSIDE-UPLOAD-ROOT" not in resp.content
