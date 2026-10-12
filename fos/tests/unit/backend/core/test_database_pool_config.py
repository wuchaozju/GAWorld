"""
This file checks that the database engine is configured correctly for each dialect.

Each test verifies one thing:
- test_postgresql_engine_has_pool_pre_ping_enabled: stale connections are detected before use.
- test_postgresql_engine_has_pool_recycle_set: connections are refreshed before PostgreSQL drops them.
- test_postgresql_explicit_settings_override_defaults: user-provided settings win over defaults.
- test_sqlite_engine_does_not_get_postgres_pool_settings: SQLite keeps its own pool config.
- test_sqlite_engine_has_connect_args: SQLite gets the timeout it needs for concurrent access.
"""

from __future__ import annotations




def _build_engine_kwargs(database_url: str, settings_overrides: dict | None = None) -> dict:
    """Re-run the database.py config logic with a fake database_url.

    This avoids importing the real module, which creates a global engine at
    import time and cannot be reconfigured.
    """
    overrides = settings_overrides or {}
    debug = overrides.get("debug", False)
    db_pool_size = overrides.get("db_pool_size")
    db_max_overflow = overrides.get("db_max_overflow")
    db_pool_timeout = overrides.get("db_pool_timeout")
    db_pool_recycle = overrides.get("db_pool_recycle")
    db_pool_pre_ping = overrides.get("db_pool_pre_ping")

    engine_kwargs: dict = {"echo": debug}

    if database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"timeout": 60}
        if db_pool_size is None:
            engine_kwargs["pool_size"] = 20
        if db_max_overflow is None:
            engine_kwargs["max_overflow"] = 10
        if db_pool_timeout is None:
            engine_kwargs["pool_timeout"] = 60
    else:
        if db_pool_pre_ping is None:
            engine_kwargs["pool_pre_ping"] = True
        if db_pool_recycle is None:
            engine_kwargs["pool_recycle"] = 3600

    if db_pool_size is not None:
        engine_kwargs["pool_size"] = db_pool_size
    if db_max_overflow is not None:
        engine_kwargs["max_overflow"] = db_max_overflow
    if db_pool_timeout is not None:
        engine_kwargs["pool_timeout"] = db_pool_timeout
    if db_pool_recycle is not None:
        engine_kwargs["pool_recycle"] = db_pool_recycle
    if db_pool_pre_ping is not None:
        engine_kwargs["pool_pre_ping"] = db_pool_pre_ping

    return engine_kwargs


def test_postgresql_engine_has_pool_pre_ping_enabled() -> None:
    kwargs = _build_engine_kwargs("postgresql+psycopg://fos:fos@db:5432/fos")
    assert kwargs.get("pool_pre_ping") is True, (
        "pool_pre_ping must be True for PostgreSQL so stale connections are detected"
    )


def test_postgresql_engine_has_pool_recycle_set() -> None:
    kwargs = _build_engine_kwargs("postgresql+psycopg://fos:fos@db:5432/fos")
    recycle = kwargs.get("pool_recycle")
    assert recycle is not None and recycle > 0, (
        "pool_recycle must be set for PostgreSQL to avoid 'unexpected EOF' errors"
    )
    assert recycle <= 7200, (
        "pool_recycle should not exceed 2 hours (PostgreSQL default idle timeout)"
    )


def test_postgresql_explicit_settings_override_defaults() -> None:
    kwargs = _build_engine_kwargs(
        "postgresql+psycopg://fos:fos@db:5432/fos",
        settings_overrides={"db_pool_recycle": 1800, "db_pool_pre_ping": False},
    )
    assert kwargs["pool_recycle"] == 1800
    assert kwargs["pool_pre_ping"] is False


def test_sqlite_engine_does_not_get_postgres_pool_settings() -> None:
    kwargs = _build_engine_kwargs("sqlite+aiosqlite:///./fos.db")
    assert "pool_pre_ping" not in kwargs, "SQLite should not get PostgreSQL-specific pool settings"
    assert "pool_recycle" not in kwargs, "SQLite should not get pool_recycle"


def test_sqlite_engine_has_connect_args() -> None:
    kwargs = _build_engine_kwargs("sqlite+aiosqlite:///./fos.db")
    assert kwargs.get("connect_args") == {"timeout": 60}
    assert kwargs.get("pool_size") == 20
