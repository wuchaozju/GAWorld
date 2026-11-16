"""Experiment Template database model.

Stores researcher-defined experiment scenarios that can be
loaded and run via the GUI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from ..db.mixins import TimestampMixin
from .simulation import JsonType

if TYPE_CHECKING:
    from fos.backend.models.user import User


class ExperimentTemplate(TimestampMixin, Base):
    """Database model for experiment templates.

    Researchers define experiments through the GUI:
    - Scenario description (free text)
    - Available actions (name, description, parameters)
    - Round settings (simultaneous/sequential, max rounds)

    Templates can be saved, loaded, and shared.
    """

    __tablename__ = "experiment_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)  # Scenario text for prompt
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Actions as JSON: [{"name": "cooperate", "description": "...", "parameters": {...}}]
    actions: Mapped[list] = mapped_column(JsonType, nullable=False, default=list)

    # Settings as JSON:
    # {"round_visibility": "simultaneous"|"sequential", "max_rounds": int}
    settings: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)

    # Relationship to user
    creator: Mapped["User"] = relationship(back_populates="experiment_templates")
