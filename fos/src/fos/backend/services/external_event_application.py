"""
This file handles saved external event records.

Each function here does one clear job:
- `ExternalEventCreateInput.from_payload` turns request data into clean values.
- `create_external_event_record` saves one new event row.
- `apply_external_event_record` applies one saved event to a simulation and marks it used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fos.backend.models.external_event_record import ExternalEventRecord
from fos.backend.models.simulation import Simulation
from fos.backend.services.environment_suggestion_service import broadcast_environment_event
from fos.i18n import T


@dataclass(slots=True)
class ExternalEventCreateInput:
    """Hold the clean values needed to save one external event record."""

    event_type: str
    source: str
    title: str
    content: str
    severity: str
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    url: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ExternalEventCreateInput":
        """Build one clean input object from a route payload."""
        raw_timestamp = payload.get("timestamp")
        timestamp = (
            datetime.fromisoformat(str(raw_timestamp))
            if raw_timestamp
            else datetime.now(UTC)
        )
        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError(T("api.errors.invalid_event_metadata"))
        return cls(
            event_type=str(payload.get("event_type") or "manual"),
            source=str(payload.get("source") or "manual"),
            title=str(payload.get("title") or "").strip(),
            content=str(payload.get("content") or "").strip(),
            severity=str(payload.get("severity") or "medium"),
            url=str(payload.get("url")).strip() if payload.get("url") else None,
            metadata=metadata,
            timestamp=timestamp,
        )


async def create_external_event_record(
    db: AsyncSession,
    *,
    simulation_id: str | None,
    payload: dict[str, Any],
) -> ExternalEventRecord:
    """Save one new external event record and return it."""
    event_input = ExternalEventCreateInput.from_payload(payload)
    record = ExternalEventRecord(
        simulation_id=simulation_id,
        event_type=event_input.event_type,
        source=event_input.source,
        title=event_input.title,
        content=event_input.content,
        severity=event_input.severity,
        url=event_input.url,
        raw_data=event_input.metadata,
        event_timestamp=event_input.timestamp,
        status="pending",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def apply_external_event_record(
    simulation_id: str,
    event_id: str,
    *,
    db: AsyncSession,
    user_id: int,
    node_id: int | None = None,
) -> dict[str, Any]:
    """Apply one saved event record to the selected simulation node."""
    simulation_result = await db.execute(
        select(Simulation).where(
            Simulation.id == simulation_id.upper(),
            Simulation.owner_id == user_id,
        )
    )
    simulation = simulation_result.scalar_one_or_none()
    if simulation is None:
        raise ValueError(T("api.errors.simulation_not_found"))

    event_result = await db.execute(
        select(ExternalEventRecord).where(ExternalEventRecord.id == event_id)
    )
    record = event_result.scalar_one_or_none()
    if record is None:
        raise ValueError(T("api.errors.external_event_not_found"))

    if record.simulation_id and record.simulation_id.upper() != simulation_id.upper():
        raise ValueError(T("api.errors.external_event_wrong_simulation"))

    description = _build_event_description(record)
    await broadcast_environment_event(
        simulation_id,
        {
            "event_type": record.event_type,
            "description": description,
            "severity": record.severity,
            "node_id": node_id,
        },
        db,
        user_id,
    )
    record.status = "applied"
    await db.commit()

    return {
        "success": True,
        "event_id": record.id,
        "status": record.status,
        "description": description,
    }


def _build_event_description(record: ExternalEventRecord) -> str:
    """Turn one saved event row into the text shown to the next round."""
    title = str(record.title or "").strip()
    content = str(record.content or "").strip()
    if title and content:
        return f"{title}: {content}"
    return title or content
