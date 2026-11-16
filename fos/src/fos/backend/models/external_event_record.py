# This file stores event records that come from external data sources.
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, Text, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fos.backend.db.base import Base

if TYPE_CHECKING:
    from fos.backend.models.data_source import DataSource


class ExternalEventRecord(Base):
    __tablename__ = "external_event_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    data_source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    data_source: Mapped[DataSource | None] = relationship(
        "DataSource", back_populates="event_records"
    )
    simulation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    status: Mapped[str] = mapped_column(String(20), default="pending")
