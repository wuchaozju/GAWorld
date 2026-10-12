"""
This file checks the external event API helpers with a real test database.

Each helper here does one small job:
- `_make_session_factory` builds a temporary database session factory.
- `_make_request` builds a tiny fake request object.
- `_seed_user` adds one active user.
- `_seed_simulation` adds one simulation owned by that user.
- `_seed_event` adds one saved external event row.
- `test_get_external_events_returns_real_rows_and_filters_them` checks listing and filtering.
- `test_post_external_event_saves_a_pending_record` checks manual event creation.
"""

from __future__ import annotations

import importlib.util
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fos.backend.db.base import Base
from fos.backend.models.external_event_record import ExternalEventRecord
from fos.backend.models.simulation import Simulation
from fos.backend.models.user import User


def _load_environment_routes_module():
    """Load the environment route file without importing the whole router package."""
    module_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "fos"
        / "backend"
        / "api"
        / "routes"
        / "environment.py"
    )
    spec = importlib.util.spec_from_file_location("test_environment_routes", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _make_session_factory(tmp_path: Path) -> async_sessionmaker[AsyncSession]:
    """Build a temporary async session factory backed by SQLite."""
    database_path = tmp_path / "environment-events-api.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return session_factory


def _make_request() -> SimpleNamespace:
    """Build a tiny request object with the fields the route reads."""
    return SimpleNamespace(headers={"Authorization": "Bearer test-token"}, query_params={})


async def _seed_user(session: AsyncSession) -> User:
    """Add one active user and return it."""
    user = User(
        id=1,
        email="test@example.com",
        username="tester",
        hashed_password="hashed",
        is_active=True,
        is_verified=True,
    )
    session.add(user)
    await session.commit()
    return user


async def _seed_simulation(session: AsyncSession, owner_id: int) -> Simulation:
    """Add one simulation owned by the given user."""
    simulation = Simulation(
        id="SIM123",
        owner_id=owner_id,
        name="Environment Test",
        scene_type="experiment_template",
        scene_config={},
        agent_config={"agents": [{"name": "Alice"}, {"name": "Bob"}]},
        status="active",
    )
    session.add(simulation)
    await session.commit()
    return simulation


async def _seed_event(
    session: AsyncSession,
    simulation_id: str,
    *,
    event_id: str,
    title: str,
    severity: str,
    status: str,
    source: str,
    event_type: str,
) -> ExternalEventRecord:
    """Add one saved external event row."""
    event = ExternalEventRecord(
        id=event_id,
        simulation_id=simulation_id,
        event_type=event_type,
        source=source,
        title=title,
        content=f"{title} content",
        severity=severity,
        status=status,
        event_timestamp=__import__("datetime").datetime(2026, 1, 1, 12, 0, 0),
    )
    session.add(event)
    await session.commit()
    return event


@pytest.mark.asyncio
async def test_get_external_events_returns_real_rows_and_filters_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """List saved rows and make sure the filters keep the right ones."""
    environment_routes = _load_environment_routes_module()
    session_factory = await _make_session_factory(tmp_path)

    @asynccontextmanager
    async def _test_session():
        """Yield a real test session to the route code."""
        async with session_factory() as session:
            yield session

    async def _resolve_user(session: AsyncSession, token: str) -> SimpleNamespace:
        """Return the fixed test user for route auth."""
        return SimpleNamespace(id=1)

    monkeypatch.setattr(environment_routes, "get_session", _test_session)
    monkeypatch.setattr(environment_routes, "extract_bearer_token", lambda request: "test-token")
    monkeypatch.setattr(environment_routes, "resolve_current_user", _resolve_user)

    async with session_factory() as session:
        await _seed_user(session)
        simulation = await _seed_simulation(session, owner_id=1)
        await _seed_event(
            session,
            simulation.id,
            event_id="evt-1",
            title="Critical Policy Update",
            severity="critical",
            status="pending",
            source="policy-feed",
            event_type="policy",
        )
        await _seed_event(
            session,
            simulation.id,
            event_id="evt-2",
            title="Applied Market Notice",
            severity="medium",
            status="applied",
            source="market-feed",
            event_type="market",
        )

        response = await environment_routes.get_external_events.fn(
            request=_make_request(),
            simulation_id="SIM123",
            min_severity="high",
            status="pending",
        )

    assert response["total"] == 1
    assert response["events"][0]["id"] == "evt-1"
    assert response["events"][0]["title"] == "Critical Policy Update"
    assert response["events"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_post_external_event_saves_a_pending_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create a manual event and make sure the database row is real."""
    environment_routes = _load_environment_routes_module()
    session_factory = await _make_session_factory(tmp_path)

    @asynccontextmanager
    async def _test_session():
        """Yield a real test session to the route code."""
        async with session_factory() as session:
            yield session

    async def _resolve_user(session: AsyncSession, token: str) -> SimpleNamespace:
        """Return the fixed test user for route auth."""
        return SimpleNamespace(id=1)

    monkeypatch.setattr(environment_routes, "get_session", _test_session)
    monkeypatch.setattr(environment_routes, "extract_bearer_token", lambda request: "test-token")
    monkeypatch.setattr(environment_routes, "resolve_current_user", _resolve_user)

    async with session_factory() as session:
        await _seed_user(session)
        await _seed_simulation(session, owner_id=1)

    result = await environment_routes.add_external_event.fn(
        data={
            "event_type": "manual",
            "source": "manual",
            "title": "Host Notice",
            "content": "The host created this event.",
            "severity": "high",
            "timestamp": "2026-01-02T08:30:00",
            "metadata": {"kind": "host"},
        },
        request=_make_request(),
        simulation_id="SIM123",
    )

    assert result["success"] is True
    assert result["event_id"]

    async with session_factory() as session:
        saved = await session.get(ExternalEventRecord, result["event_id"])
        assert saved is not None
        assert saved.simulation_id == "SIM123"
        assert saved.title == "Host Notice"
        assert saved.status == "pending"
        assert saved.raw_data == {"kind": "host"}
