"""
Database configuration and session management.

Provides async SQLAlchemy engine and session factory for the application.
Engine parameters can be tuned via application settings.

Contains:
    - engine: Async SQLAlchemy engine
    - SessionLocal: Async session factory
    - get_session: Context manager for database sessions
"""

import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import get_settings


settings = get_settings()

# Configure engine with optional pool tuning from settings. Only include values
# explicitly provided to avoid passing unsupported args for some dialects.
engine_kwargs: dict = {"echo": settings.debug}

if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"timeout": 60}
    if settings.db_pool_size is None:
        engine_kwargs["pool_size"] = 20
    if settings.db_max_overflow is None:
        engine_kwargs["max_overflow"] = 10
    if settings.db_pool_timeout is None:
        engine_kwargs["pool_timeout"] = 60
else:
    if settings.db_pool_size is None:
        engine_kwargs["pool_size"] = 20
    if settings.db_max_overflow is None:
        engine_kwargs["max_overflow"] = 20
    if settings.db_pool_timeout is None:
        engine_kwargs["pool_timeout"] = 60
    if settings.db_pool_pre_ping is None:
        engine_kwargs["pool_pre_ping"] = True
    if settings.db_pool_recycle is None:
        engine_kwargs["pool_recycle"] = 3600

if settings.db_pool_size is not None:
    engine_kwargs["pool_size"] = settings.db_pool_size
if settings.db_max_overflow is not None:
    engine_kwargs["max_overflow"] = settings.db_max_overflow
if settings.db_pool_timeout is not None:
    engine_kwargs["pool_timeout"] = settings.db_pool_timeout
if settings.db_pool_recycle is not None:
    engine_kwargs["pool_recycle"] = settings.db_pool_recycle
if settings.db_pool_pre_ping is not None:
    engine_kwargs["pool_pre_ping"] = settings.db_pool_pre_ping

engine = create_async_engine(settings.database_url, **engine_kwargs)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


# Enable WAL mode for SQLite — allows concurrent reads during writes.
if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


# Slow query logging
_db_logger = logging.getLogger("fos.timing")
_SLOW_QUERY_THRESHOLD_MS = 500


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault("query_start_time", []).append(time.monotonic())


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    start = conn.info["query_start_time"].pop()
    duration_ms = int((time.monotonic() - start) * 1000)
    if duration_ms >= _SLOW_QUERY_THRESHOLD_MS:
        stmt_short = statement[:120].replace("\n", " ")
        _db_logger.warning("[DB] slow_query duration_ms=%d query=%s", duration_ms, stmt_short)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
