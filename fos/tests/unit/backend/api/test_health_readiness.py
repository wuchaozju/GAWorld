"""
This file checks the health endpoints used by Docker and presentation monitoring.

Each test verifies one thing:
- test_liveness_check_stays_lightweight checks the liveness endpoint stays simple.
- test_readiness_check_reports_database_failure checks readiness fails when the database fails.
- test_health_check_includes_runtime_metrics checks health output includes demo stability metrics.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from fos.backend.api.routes import health
from fos.backend.services.runtime_tasks import RUNTIME_TASKS


@pytest.mark.asyncio
async def test_liveness_check_stays_lightweight() -> None:
    assert await health.liveness_check() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readiness_check_reports_database_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenEngine:
        def begin(self) -> object:
            raise OSError("database unavailable")

    monkeypatch.setattr(health, "engine", BrokenEngine())

    result = await health.readiness_check()

    assert result["status"] == "unhealthy"
    assert result["checks"]["database"]["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_health_check_includes_runtime_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    RUNTIME_TASKS.clear()
    RUNTIME_TASKS.start("ai_analysis", "AI analysis", task_id="ai:test")
    fake_pool = SimpleNamespace(
        size=lambda: 5,
        checkedout=lambda: 1,
        overflow=lambda: 0,
        checkedin=lambda: 4,
    )
    monkeypatch.setattr(health, "engine", SimpleNamespace(pool=fake_pool))

    result = await health.health_check()

    assert "memory" in result
    assert "running_experiment_tasks" in result
    assert result["runtime_tasks"]["active"] == 1
    assert result["runtime_tasks"]["recent"][0]["id"] == "ai:test"
    assert "gaworld_subprocesses" in result
    assert "tree_nodes" in result
    RUNTIME_TASKS.clear()
