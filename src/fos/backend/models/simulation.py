from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from ..db.mixins import TimestampMixin
from .user import User

# 在本文件内定义一个通用 JSON 类型：
# - 在 PostgreSQL 下用 JSONB
# - 在其他数据库（如 SQLite）下用标准 JSON
JsonType = JSON().with_variant(JSONB, "postgresql")


class Simulation(TimestampMixin, Base):
    __tablename__ = "simulations"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    scene_type: Mapped[str] = mapped_column(String(64))
    scene_config: Mapped[dict] = mapped_column(JsonType, default=dict)
    agent_config: Mapped[dict] = mapped_column(JsonType, default=dict)
    latest_state: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    notes: Mapped[str | None] = mapped_column(Text())

    owner: Mapped["User"] = relationship(back_populates="simulations")
    snapshots: Mapped[list["SimulationSnapshot"]] = relationship(
        back_populates="simulation", cascade="all, delete-orphan"
    )
    logs: Mapped[list["SimulationLog"]] = relationship(
        back_populates="simulation", cascade="all, delete-orphan"
    )
    sync_logs: Mapped[list["SimulationSyncLog"]] = relationship(
        back_populates="simulation", cascade="all, delete-orphan"
    )
    tree_nodes: Mapped[list["SimTreeNode"]] = relationship(
        back_populates="simulation", cascade="all, delete-orphan"
    )


class SimulationSnapshot(TimestampMixin, Base):
    __tablename__ = "simulation_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    simulation_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("simulations.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(128))
    state: Mapped[dict] = mapped_column(JsonType)
    turns: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict] = mapped_column(JsonType, default=dict)

    simulation: Mapped[Simulation] = relationship(back_populates="snapshots")


class SimTreeNode(TimestampMixin, Base):
    __tablename__ = "sim_tree_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    simulation_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("simulations.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sim_tree_nodes.id", ondelete="CASCADE"))
    depth: Mapped[int] = mapped_column(Integer)
    edge_type: Mapped[str] = mapped_column(String(32))
    ops: Mapped[dict] = mapped_column(JsonType, default=dict)
    state: Mapped[dict] = mapped_column(JsonType)

    simulation: Mapped[Simulation] = relationship(back_populates="tree_nodes")
    parent: Mapped[SimTreeNode | None] = relationship(
        remote_side="SimTreeNode.id", backref="children"
    )


class SimulationLog(TimestampMixin, Base):
    __tablename__ = "simulation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    simulation_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("simulations.id", ondelete="CASCADE"), index=True
    )
    tree_node_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sim_tree_nodes.id", ondelete="SET NULL"))
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JsonType)

    simulation: Mapped[Simulation] = relationship(back_populates="logs")


class SimulationSyncLog(TimestampMixin, Base):
    __tablename__ = "simulation_sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    simulation_id: Mapped[str | None] = mapped_column(
        String(16), ForeignKey("simulations.id", ondelete="CASCADE"), index=True, nullable=True
    )
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict] = mapped_column(JsonType, default=list)

    simulation: Mapped[Simulation] = relationship(back_populates="sync_logs")
