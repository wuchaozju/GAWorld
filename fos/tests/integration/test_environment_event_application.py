"""
This file checks that applying one saved external event reaches the next round.

Each helper here does one small job:
- `_make_session_factory` builds a temporary database session factory.
- `_make_test_simulation` builds one experiment simulation row.
- `_make_clients` builds a tiny fake client bundle for the runtime tree.
- `_seed_user` adds one active user.
- `_seed_event` adds one pending external event row.
- `test_apply_external_event_record_marks_row_and_queues_next_round_message` checks the full apply path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fos.backend.db.base import Base
from fos.backend.models.external_event_record import ExternalEventRecord
from fos.backend.models.simulation import Simulation
from fos.backend.models.user import User
from fos.backend.services.external_event_application import apply_external_event_record
from fos.backend.services.simtree_runtime import SIM_TREE_REGISTRY


async def _make_session_factory(tmp_path: Path) -> async_sessionmaker[AsyncSession]:
    """Build a temporary async session factory backed by SQLite."""
    database_path = tmp_path / "environment-event-application.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return session_factory


def _make_test_simulation(owner_id: int) -> Simulation:
    """Build one experiment simulation row with two agents."""
    return Simulation(
        id="SIM456",
        owner_id=owner_id,
        name="Apply Event Test",
        scene_type="experiment_template",
        scene_config={
            "scenario_id": "custom",
            "description": "Test simulation",
            "environment_enabled": True,
            "actions": [{"name": "cooperate", "description": "Work together"}],
            "round_visibility": "simultaneous",
        },
        agent_config={
            "agents": [
                {
                    "name": "Alice",
                    "properties": {"role": "Citizen"},
                    "llmConfig": {"dialect": "mock", "model": "default"},
                },
                {
                    "name": "Bob",
                    "properties": {"role": "Citizen"},
                    "llmConfig": {"dialect": "mock", "model": "default"},
                },
            ]
        },
        status="active",
    )


def _make_clients() -> dict:
    """Build a tiny fake client bundle for the runtime tree."""
    return {"chat": object(), "default": object(), "providers": {}}


async def _seed_user(session: AsyncSession) -> User:
    """Add one active user and return it."""
    user = User(
        id=1,
        email="owner@example.com",
        username="owner",
        hashed_password="hashed",
        is_active=True,
        is_verified=True,
    )
    session.add(user)
    await session.commit()
    return user


async def _seed_event(session: AsyncSession) -> ExternalEventRecord:
    """Add one pending external event row."""
    event = ExternalEventRecord(
        id="evt-apply-1",
        simulation_id="SIM456",
        event_type="news",
        source="news-feed",
        title="Supply Shock",
        content="A sudden supply shock changes tomorrow's conditions.",
        severity="high",
        status="pending",
        event_timestamp=__import__("datetime").datetime(2026, 1, 4, 10, 0, 0),
    )
    session.add(event)
    await session.commit()
    return event


@pytest.mark.asyncio
async def test_apply_external_event_record_marks_row_and_queues_next_round_message(
    tmp_path: Path,
) -> None:
    """Applying a saved event should mark it applied and queue a host message."""
    session_factory = await _make_session_factory(tmp_path)

    async with session_factory() as session:
        await _seed_user(session)
        simulation = _make_test_simulation(owner_id=1)
        session.add(simulation)
        await session.commit()
        await _seed_event(session)

        SIM_TREE_REGISTRY.remove("SIM456")
        record = await SIM_TREE_REGISTRY.get_or_create_from_sim(simulation, _make_clients())

        applied = await apply_external_event_record(
            simulation_id="SIM456",
            event_id="evt-apply-1",
            db=session,
            user_id=1,
            node_id=record.tree.leaves()[0],
        )

        assert applied["success"] is True
        refreshed = await session.get(ExternalEventRecord, "evt-apply-1")
        assert refreshed is not None
        assert refreshed.status == "applied"

        latest_leaf = record.tree.leaves()[0]
        simulator = record.tree.nodes[latest_leaf]["sim"]
        pending_messages = getattr(simulator.scene, "_pending_host_messages", [])
        assert pending_messages
        assert "Supply Shock" in pending_messages[-1]
        assert "sudden supply shock" in pending_messages[-1]

        assert simulation.latest_state is not None
        SIM_TREE_REGISTRY.remove("SIM456")
