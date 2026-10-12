"""
DataSource REST API routes for managing external data source configurations.

This module provides CRUD endpoints for data sources that can poll external APIs
and inject events into simulations.
"""
from __future__ import annotations

import logging
from typing import Dict, Any

import httpx
from litestar import Router, get, post, put, delete
from litestar.connection import Request
from litestar.exceptions import HTTPException
from sqlalchemy import select

from fos.backend.core.database import get_session
from fos.backend.dependencies import extract_bearer_token, resolve_current_user
from fos.backend.models.data_source import DataSource

from fos.i18n import T

logger = logging.getLogger(__name__)


@get("/")
async def list_data_sources(
    request: Request,
    simulation_id: str | None = None,
) -> Dict[str, Any]:
    """List all data sources, optionally filtered by simulation_id."""
    token = extract_bearer_token(request)
    async with get_session() as session:
        await resolve_current_user(session, token)

    async with get_session() as session:
        query = select(DataSource)
        if simulation_id:
            query = query.where(
                DataSource.is_global.is_(True) | (DataSource.simulation_id == simulation_id)
            )
        else:
            query = query.where(DataSource.is_global.is_(True))

        result = await session.execute(query)
        sources = result.scalars().all()

        return {
            "data_sources": [_source_to_dict(s) for s in sources],
            "total": len(sources),
        }


@post("/")
async def create_data_source(
    data: Dict[str, Any],
    request: Request,
) -> Dict[str, Any]:
    """Create a new data source."""
    token = extract_bearer_token(request)
    async with get_session() as session:
        await resolve_current_user(session, token)

    async with get_session() as session:
        source = DataSource(
            name=data["name"],
            api_url=data["api_url"],
            auth_type=data.get("auth_type", "none"),
            auth_token=data.get("auth_token"),
            poll_interval_seconds=data.get("poll_interval_seconds", 300),
            event_type=data.get("event_type", "market"),
            is_global=data.get("is_global", True),
            simulation_id=data.get("simulation_id"),
            field_mapping=data.get("field_mapping", {}),
            is_enabled=data.get("is_enabled", True),
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)

        return {"data_source": _source_to_dict(source), "created": True}


@get("/{source_id:str}")
async def get_data_source(
    source_id: str,
    request: Request,
) -> Dict[str, Any]:
    """Get a single data source by ID."""
    token = extract_bearer_token(request)
    async with get_session() as session:
        await resolve_current_user(session, token)

    async with get_session() as session:
        result = await session.execute(select(DataSource).where(DataSource.id == source_id))
        source = result.scalar_one_or_none()

        if not source:
            raise HTTPException(status_code=404, detail=T("api.errors.data_source_not_found"))

        return {"data_source": _source_to_dict(source)}


@put("/{source_id:str}")
async def update_data_source(
    source_id: str,
    data: Dict[str, Any],
    request: Request,
) -> Dict[str, Any]:
    """Update a data source."""
    token = extract_bearer_token(request)
    async with get_session() as session:
        await resolve_current_user(session, token)

    async with get_session() as session:
        result = await session.execute(select(DataSource).where(DataSource.id == source_id))
        source = result.scalar_one_or_none()

        if not source:
            raise HTTPException(status_code=404, detail=T("api.errors.data_source_not_found"))

        for key in [
            "name",
            "api_url",
            "auth_type",
            "auth_token",
            "poll_interval_seconds",
            "event_type",
            "is_global",
            "simulation_id",
            "field_mapping",
            "is_enabled",
        ]:
            if key in data:
                setattr(source, key, data[key])

        await session.commit()
        await session.refresh(source)

        return {"data_source": _source_to_dict(source), "updated": True}


@delete("/{source_id:str}", status_code=200)
async def delete_data_source(
    source_id: str,
    request: Request,
) -> Dict[str, Any]:
    """Delete a data source."""
    token = extract_bearer_token(request)
    async with get_session() as session:
        await resolve_current_user(session, token)

    async with get_session() as session:
        result = await session.execute(select(DataSource).where(DataSource.id == source_id))
        source = result.scalar_one_or_none()

        if not source:
            raise HTTPException(status_code=404, detail=T("api.errors.data_source_not_found"))

        await session.delete(source)
        await session.commit()

        return {"deleted": True, "id": source_id}


@post("/{source_id:str}/test")
async def test_data_source(
    source_id: str,
    request: Request,
) -> Dict[str, Any]:
    """Test connection to a data source API."""
    token = extract_bearer_token(request)
    async with get_session() as session:
        await resolve_current_user(session, token)

    async with get_session() as session:
        result = await session.execute(select(DataSource).where(DataSource.id == source_id))
        source = result.scalar_one_or_none()

        if not source:
            raise HTTPException(status_code=404, detail=T("api.errors.data_source_not_found"))

    # Perform actual HTTP test
    auth_headers = {}
    if source.auth_type == "bearer":
        auth_headers["Authorization"] = f"Bearer {source.auth_token}"
    elif source.auth_type == "api_key":
        auth_headers["X-API-Key"] = source.auth_token

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(source.api_url, headers=auth_headers)
            response.raise_for_status()

        return {"success": True, "status_code": response.status_code, "message": "Connection successful"}
    except httpx.HTTPError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"Test connection error: {e}", exc_info=True)
        return {"success": False, "error": f"Connection failed: {str(e)}"}


@post("/{source_id:str}/poll")
async def poll_data_source(
    source_id: str,
    request: Request,
) -> Dict[str, Any]:
    """Manually trigger a poll for a specific data source."""
    from fos.backend.services.external_event_service import ExternalEventService

    token = extract_bearer_token(request)
    async with get_session() as session:
        await resolve_current_user(session, token)

    async with get_session() as session:
        stmt = select(DataSource).where(DataSource.id == source_id)
        result = await session.execute(stmt)
        source = result.scalar_one_or_none()

        if not source:
            raise HTTPException(status_code=404, detail=T("api.errors.data_source_not_found"))

        # Call the polling service
        service = ExternalEventService()
        count = await service.poll_source(source)

    return {
        "message": "Poll completed",
        "source_id": source_id,
        "events_created": count,
    }


def _source_to_dict(source: DataSource) -> Dict[str, Any]:
    """Convert DataSource model to dict (without auth_token for security)."""
    return {
        "id": source.id,
        "name": source.name,
        "api_url": source.api_url,
        "auth_type": source.auth_type,
        "poll_interval_seconds": source.poll_interval_seconds,
        "event_type": source.event_type,
        "is_global": source.is_global,
        "simulation_id": source.simulation_id,
        "field_mapping": source.field_mapping,
        "is_enabled": source.is_enabled,
        "last_poll_at": source.last_poll_at.isoformat() if source.last_poll_at else None,
        "last_error": source.last_error,
        "created_at": source.created_at.isoformat() if source.created_at else None,
        "updated_at": source.updated_at.isoformat() if source.updated_at else None,
    }


router = Router(
    path="",
    route_handlers=[
        list_data_sources,
        create_data_source,
        get_data_source,
        update_data_source,
        delete_data_source,
        test_data_source,
        poll_data_source,
    ],
)
