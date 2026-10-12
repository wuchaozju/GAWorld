"""
This file checks the data source poller with a real test database.

Each helper here does one small job:
- `_make_session_factory` builds a temporary database session factory.
- `_seed_source` adds one data source row.
- `_fake_async_client` pretends to be the remote API.
- `test_poll_source_creates_event_records_from_remote_data` checks that polling saves rows.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fos.backend.core import database as database_module
from fos.backend.db.base import Base
from fos.backend.models.data_source import DataSource
from fos.backend.models.external_event_record import ExternalEventRecord
from fos.backend.services.external_event_service import ExternalEventService


async def _make_session_factory(tmp_path: Path) -> async_sessionmaker[AsyncSession]:
    """Build a temporary async session factory backed by SQLite."""
    database_path = tmp_path / "external-event-service.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return session_factory


async def _seed_source(session: AsyncSession) -> DataSource:
    """Add one enabled data source row for polling."""
    source = DataSource(
        id="source-1",
        name="Policy Feed",
        api_url="https://example.test/events",
        auth_type="none",
        poll_interval_seconds=60,
        event_type="policy",
        is_global=False,
        simulation_id="SIM123",
        field_mapping={
            "items_path": "items",
            "title_path": "headline",
            "content_path": "body",
            "timestamp_path": "published_at",
            "url_path": "link",
        },
        is_enabled=True,
    )
    session.add(source)
    await session.commit()
    return source


def _fake_async_client(payload: dict) -> type:
    """Build a fake async client class that returns the given payload."""

    class _FakeResponse:
        """Return JSON data and behave like a successful HTTP response."""

        def raise_for_status(self) -> None:
            """Do nothing because the fake response always succeeds."""
            return None

        def json(self) -> dict:
            """Return the prepared payload."""
            return payload

    class _FakeClient:
        """Act like `httpx.AsyncClient` for this test."""

        def __init__(self, *args, **kwargs) -> None:
            """Accept any setup values the service passes in."""
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self) -> "_FakeClient":
            """Enter the async context manager."""
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            """Leave the async context manager."""
            return None

        async def get(self, url: str, headers: dict[str, str] | None = None) -> _FakeResponse:
            """Return the fake response for the requested URL."""
            return _FakeResponse()

    return _FakeClient


@pytest.mark.asyncio
async def test_poll_source_creates_event_records_from_remote_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Polling one data source should save parsed event rows in the database."""
    session_factory = await _make_session_factory(tmp_path)

    @asynccontextmanager
    async def _test_session():
        """Yield a real test session to the polling service."""
        async with session_factory() as session:
            yield session

    monkeypatch.setattr(database_module, "get_session", _test_session)
    monkeypatch.setattr(
        "fos.backend.services.external_event_service.httpx.AsyncClient",
        _fake_async_client(
            {
                "items": [
                    {
                        "headline": "Breaking policy warning",
                        "body": "Government warning triggers a major response.",
                        "published_at": "2026-01-03T09:15:00",
                        "link": "https://example.test/policy",
                    }
                ]
            }
        ),
    )

    async with session_factory() as session:
        source = await _seed_source(session)

    service = ExternalEventService()
    created = await service.poll_source(source)

    assert created == 1

    async with session_factory() as session:
        rows = (await session.execute(select(ExternalEventRecord))).scalars().all()
        assert len(rows) == 1
        assert rows[0].simulation_id == "SIM123"
        assert rows[0].data_source_id == "source-1"
        assert rows[0].event_type == "policy"
        assert rows[0].severity in {"high", "critical"}
        assert rows[0].status == "pending"
