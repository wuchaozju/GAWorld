from __future__ import annotations

from sqlalchemy import Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from ..db.mixins import TimestampMixin
from .simulation import JsonType


class Experiment(TimestampMixin, Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    simulation_id: Mapped[str] = mapped_column(String(16), nullable=False)
    base_node: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    model_meta: Mapped[dict | None] = mapped_column(JsonType, default=dict)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    git_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="created")

    variants: Mapped[list["ExperimentVariant"]] = relationship(
        back_populates="experiment",
        cascade="all, delete-orphan",
    )
    runs: Mapped[list["ExperimentRun"]] = relationship(
        back_populates="experiment",
        cascade="all, delete-orphan",
    )


class ExperimentVariant(TimestampMixin, Base):
    __tablename__ = "experiment_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        String(48),
        ForeignKey("experiments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    ops: Mapped[dict] = mapped_column(JsonType, default=dict)
    node_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    experiment: Mapped[Experiment] = relationship(
        back_populates="variants",
    )


class ExperimentRun(TimestampMixin, Base):
    __tablename__ = "experiment_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        String(48), ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    turns: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="created")
    result_meta: Mapped[dict | None] = mapped_column(JsonType, default=dict)
    task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    run_tags: Mapped[dict | None] = mapped_column(JsonType, default=dict)

    experiment: Mapped[Experiment] = relationship(
        back_populates="runs",
    )
