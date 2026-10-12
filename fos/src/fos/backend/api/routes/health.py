"""
Health check and monitoring endpoints for the Docker app.

- set_app_start_time remembers when the app started.
- health_check returns useful runtime metrics for people watching the demo.
- liveness_check returns only whether the Python process can answer.
- readiness_check checks whether the app can serve real traffic.
- readiness_route returns a failing HTTP status when readiness is unhealthy.
"""

from __future__ import annotations

import os
import time
import tracemalloc
from typing import Any

import httpx
from litestar import Router, get
from litestar.response import Response
from sqlalchemy import text

from fos.backend.core.database import engine


_app_start_time: float = 0.0


def set_app_start_time() -> None:
    """Record app start time for uptime calculation."""
    global _app_start_time
    _app_start_time = time.monotonic()
    if not tracemalloc.is_tracing():
        tracemalloc.start()


def _memory_metrics() -> dict[str, Any]:
    """Return memory counters that work without extra packages."""
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    return {
        "tracemalloc_current_mb": round(current_bytes / 1024 / 1024, 2),
        "tracemalloc_peak_mb": round(peak_bytes / 1024 / 1024, 2),
    }


def _db_pool_metrics() -> dict[str, int]:
    """Return database pool counters."""
    db_pool = engine.pool
    return {
        "pool_size": db_pool.size(),
        "checked_out": db_pool.checkedout(),
        "overflow": db_pool.overflow(),
        "checked_in": db_pool.checkedin(),
    }


def _running_experiment_task_count() -> int:
    """Return the number of unfinished background experiment tasks."""
    try:
        from fos.backend.services.experiment_runner import _RUN_TASKS
    except ImportError:
        return 0
    return sum(1 for task in _RUN_TASKS.values() if not task.done())


def _runtime_task_metrics() -> dict[str, Any]:
    """Return recent long-task state for operator-visible debugging."""
    try:
        from fos.backend.services.runtime_tasks import RUNTIME_TASKS
    except ImportError:
        return {"active": 0, "recent": []}
    return RUNTIME_TASKS.snapshot(limit=20)


async def _check_database() -> dict[str, Any]:
    """Check whether the database accepts a simple query."""
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as error:
        return {"status": "unhealthy", "error": str(error)}
    return {"status": "ok"}


async def _check_ollama() -> dict[str, Any]:
    """Check whether Ollama is reachable when configured."""
    base_url = os.getenv("OLLAMA_BASE_URL", "").strip()
    if not base_url:
        return {"status": "skipped"}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
    except Exception as error:
        return {"status": "unhealthy", "error": str(error)}
    return {"status": "ok"}


async def health_check() -> dict[str, Any]:
    """Return application health status and useful runtime metrics."""
    from fos.backend.services.simtree_runtime import SIM_TREE_REGISTRY

    registry_metrics = SIM_TREE_REGISTRY.metrics()
    runtime_tasks = _runtime_task_metrics()
    return {
        "status": "ok",
        "uptime_seconds": int(time.monotonic() - _app_start_time) if _app_start_time else 0,
        **registry_metrics,
        "running_experiment_tasks": _running_experiment_task_count(),
        "runtime_tasks": runtime_tasks,
        "gaworld_subprocesses": registry_metrics["gaworld_subprocesses"],
        "db_pool": _db_pool_metrics(),
        "memory": _memory_metrics(),
    }


async def liveness_check() -> dict[str, str]:
    """Return a minimal response if the Python process can answer."""
    return {"status": "ok"}


async def readiness_check() -> dict[str, Any]:
    """Return whether dependencies needed for real traffic are healthy."""
    from fos.backend.services.simtree_runtime import SIM_TREE_REGISTRY

    checks = {
        "database": await _check_database(),
        "ollama": await _check_ollama(),
    }
    registry_metrics = SIM_TREE_REGISTRY.metrics()
    runtime_tasks = _runtime_task_metrics()
    unhealthy = [
        name for name, check in checks.items()
        if check.get("status") == "unhealthy"
    ]
    return {
        "status": "unhealthy" if unhealthy else "ok",
        "checks": checks,
        **registry_metrics,
        "running_experiment_tasks": _running_experiment_task_count(),
        "runtime_tasks": runtime_tasks,
        "memory": _memory_metrics(),
    }


async def readiness_route() -> Response[dict[str, Any]]:
    """Return readiness with HTTP 503 when Docker should treat the app as unhealthy."""
    payload = await readiness_check()
    status_code = 200 if payload["status"] == "ok" else 503
    return Response(content=payload, status_code=status_code)


router = Router(
    path="",
    route_handlers=[
        get("/health")(health_check),
        get("/health/live")(liveness_check),
        get("/health/ready")(readiness_route),
    ],
)
