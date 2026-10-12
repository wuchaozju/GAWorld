# DataSource model for external data source configuration
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, Integer, Boolean, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fos.backend.db.base import Base
from fos.backend.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from fos.backend.models.external_event_record import ExternalEventRecord


class DataSource(Base, TimestampMixin):
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    api_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(20), default="none")
    auth_token: Mapped[str] = mapped_column(String(500), nullable=True)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    event_type: Mapped[str] = mapped_column(String(20), default="market")
    is_global: Mapped[bool] = mapped_column(Boolean, default=True)
    simulation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    field_mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    event_records: Mapped[list[ExternalEventRecord]] = relationship(
        "ExternalEventRecord", back_populates="data_source", cascade="all, delete-orphan"
    )