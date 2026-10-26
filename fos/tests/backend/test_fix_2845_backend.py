"""Regression tests for task 2845 (FOS backend defects E, L, I, D-backend).

Written TDD-RED before any fix. Each class pins one defect:

- E  — params.agent_ids must NOT override the explicitly selected roster;
       final ids validated against the GAWorld agent source (unknown id → error).
- L  — simulations stuck in status "running" with no live registry entry are
       reconciled to a terminal/interrupted status at startup.
- I  — GET /scenarios/gaworld returns the gaworld scenario descriptor (200),
       while an unknown scenario still 404s and the /gaworld/* statics survive.
- D  — backend exposes gaworld_wait_status.json for a running GAWorld node
       (read-only; null/absent when the file is missing).
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest
from litestar import Litestar
from litestar.exceptions import HTTPException
from litestar.testing import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from unittest.mock import patch

# ---------------------------------------------------------------------------
# E — authoritative roster (resolve_gaworld_agent_ids)
# ---------------------------------------------------------------------------


class TestERosterPriority:
    def _call(self, params, agents, known_ids=None):
        from fos.backend.services.simtree_gaworld import resolve_gaworld_agent_ids

        if known_ids is None:
            return resolve_gaworld_agent_ids(params, agents)
        return resolve_gaworld_agent_ids(params, agents, known_ids=known_ids)

    def test_roster_wins_over_params(self):
        params = {"agent_ids": [str(i) for i in range(1, 11)]}
        roster = [{"id": 1}, {"id": 2}]
        assert self._call(params, roster, known_ids={"1", "2"}) == ["1", "2"]

    def test_params_used_only_when_roster_empty(self):
        assert self._call({"agent_ids": ["3", "4"]}, [], known_ids={"3", "4"}) == [
            "3",
            "4",
        ]

    def test_no_ids_at_all_returns_empty(self):
        assert self._call({}, []) == []

    def test_unknown_roster_id_raises_loudly(self):
        roster = [{"id": 1}, {"id": 99999}]
        with pytest.raises(ValueError, match="99999"):
            self._call({}, roster, known_ids={"1", "2"})

    def test_validation_against_live_gaworld_source(self, monkeypatch):
        """Without an explicit known_ids, the live GAWorld population is the
        validation source (fetched through gaworld_agents.get_agents)."""
        from fos.backend.services import gaworld_agents as svc

        def fake_get_agents(city="", limit=200, offset=0):
            return {
                "agents": [{"id": 1}, {"id": 2}],
                "total": 2,
            }

        monkeypatch.setattr(svc, "get_agents", fake_get_agents)
        assert self._call({}, [{"id": 1}, {"id": 2}]) == ["1", "2"]
        with pytest.raises(ValueError, match="404"):
            self._call({}, [{"id": 404}])


# ---------------------------------------------------------------------------
# L — stale "running" simulation reconciliation
# ---------------------------------------------------------------------------


async def _make_db_with_sims(statuses: dict[str, str]):
    """Create an in-memory sqlite DB with a user and simulations."""
    from fos.backend.db.base import Base
    from fos.backend.models.simulation import Simulation
    from fos.backend.models.user import User

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session = factory()
    session.add(User(id=1, username="u", email="u@example.com", hashed_password="x"))
    for sim_id, status in statuses.items():
        session.add(
            Simulation(
                id=sim_id,
                owner_id=1,
                name=sim_id,
                scene_type="gaworld",
                status=status,
            )
        )
    await session.commit()
    return engine, session


class TestLStaleRunningReconciliation:
    async def test_stale_running_marked_interrupted(self):
        from fos.backend.services.simulation_reconcile import (
            reconcile_stale_running_simulations,
        )
        from fos.backend.services.simtree_runtime import SIM_TREE_REGISTRY

        engine, session = await _make_db_with_sims(
            {"simA": "running", "simB": "completed", "simC": "running"}
        )
        try:
            # simC has a live in-memory record; simA has nothing → stale.
            with patch.object(
                SIM_TREE_REGISTRY, "is_live", create=True, side_effect=lambda sid: sid == "SIMC"
            ):
                reconciled = await reconcile_stale_running_simulations(session)
            await session.expire_all()
            from fos.backend.models.simulation import Simulation

            sima = (
                await session.get(Simulation, "simA")
            )
            simb = await session.get(Simulation, "simB")
            simc = await session.get(Simulation, "simC")
            assert sima.status == "interrupted"
            assert "not live" in (sima.notes or "").lower() or "reconcil" in (
                sima.notes or ""
            ).lower()
            assert simb.status == "completed"  # terminal statuses untouched
            assert simc.status == "running"  # live record untouched
            assert reconciled == ["simA"]
        finally:
            await session.close()
            await engine.dispose()

    def test_startup_hooks_include_reconciliation(self):
        """main.create_app registers a startup hook that reconciles stale rows."""
        from fos.backend.main import create_app

        app = create_app()
        names = [getattr(fn, "__name__", "") for fn in app.on_startup]
        assert any("reconcile" in n for n in names), names


# ---------------------------------------------------------------------------
# I — /scenarios/gaworld exact route
# ---------------------------------------------------------------------------


def _scenarios_app():
    from fos.backend.api.routes.scenarios import router

    return Litestar(route_handlers=[router])


@pytest.fixture()
def gaworld_service_mock(monkeypatch):
    from fos.backend.services import gaworld_agents as svc

    monkeypatch.setattr(
        svc,
        "get_agents",
        lambda city="", limit=200, offset=0: {"agents": [{"id": 1}], "total": 1},
    )
    monkeypatch.setattr(
        svc, "to_fos_agent", lambda agent: {"name": "a", "properties": {}}
    )
    return svc


class TestIScenariosGaworldRoute:
    def test_exact_route_returns_200(self, gaworld_service_mock):
        with TestClient(app=_scenarios_app()) as client:
            resp = client.get("/scenarios/gaworld")
            assert resp.status_code == 200
            body = resp.json()
            assert body["id"] == "gaworld"

    def test_gaworld_statics_still_work(self, gaworld_service_mock):
        with TestClient(app=_scenarios_app()) as client:
            assert client.get("/scenarios/gaworld/agents").status_code == 200
            assert client.get("/scenarios/gaworld/populations").status_code == 200

    def test_unknown_scenario_still_404(self, gaworld_service_mock):
        with TestClient(app=_scenarios_app()) as client:
            assert client.get("/scenarios/does-not-exist").status_code == 404


# ---------------------------------------------------------------------------
# D (backend) — expose GAWorld wait-status
# ---------------------------------------------------------------------------


def _node_with_manager(output_dir):
    manager = SimpleNamespace(output_dir=output_dir)
    scene = SimpleNamespace(_subprocess_manager=manager)
    return {"sim": SimpleNamespace(scene=scene)}


class TestDGaworldWaitStatusEndpoint:
    async def test_returns_snapshot_fields(self, tmp_path):
        from fos.backend.api.routes.simulations.tree_operations import (
            simulation_tree_gaworld_wait_status as _route,
        )

        snapshot = {
            "status": "waiting",
            "target_day": 3,
            "elapsed_s": 42.0,
            "last_day": 2,
            "schedule_tick_count": 7,
            "agent_schedule_count": 5,
            "observed_file_change": True,
        }
        (tmp_path / "gaworld_wait_status.json").write_text(json.dumps(snapshot))

        route = _route.fn if hasattr(_route, "fn") else _route
        result = await route(
            simulation_id="sim1",
            node_id=1,
            sim_record=SimpleNamespace(id="sim1"),
            record=SimpleNamespace(tree=SimpleNamespace(nodes={1: _node_with_manager(tmp_path)})),
        )
        assert result["available"] is True
        assert result["wait_status"]["last_day"] == 2
        assert result["wait_status"]["elapsed_s"] == 42.0
        assert result["wait_status"]["schedule_tick_count"] == 7
        assert result["age_seconds"] is not None and result["age_seconds"] < 60

    async def test_missing_file_returns_null(self, tmp_path):
        from fos.backend.api.routes.simulations.tree_operations import (
            simulation_tree_gaworld_wait_status as _route,
        )

        route = _route.fn if hasattr(_route, "fn") else _route
        result = await route(
            simulation_id="sim1",
            node_id=1,
            sim_record=SimpleNamespace(id="sim1"),
            record=SimpleNamespace(tree=SimpleNamespace(nodes={1: _node_with_manager(tmp_path)})),
        )
        assert result["available"] is False
        assert result["wait_status"] is None
        assert result["age_seconds"] is None

    async def test_unknown_node_404(self, tmp_path):
        from fos.backend.api.routes.simulations.tree_operations import (
            simulation_tree_gaworld_wait_status as _route,
        )

        route = _route.fn if hasattr(_route, "fn") else _route
        with pytest.raises(HTTPException) as excinfo:
            await route(
                simulation_id="sim1",
                node_id=99,
                sim_record=SimpleNamespace(id="sim1"),
                record=SimpleNamespace(tree=SimpleNamespace(nodes={1: _node_with_manager(tmp_path)})),
            )
        assert excinfo.value.status_code == 404
