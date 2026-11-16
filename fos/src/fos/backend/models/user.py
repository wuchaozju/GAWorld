from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from ..db.mixins import TimestampMixin

if TYPE_CHECKING:
    from fos.backend.models.experiment_template import ExperimentTemplate
    from fos.backend.models.simulation import Simulation
    from fos.backend.models.token import VerificationToken

# 在本文件内定义一个通用 JSON 类型：
# - PostgreSQL 下为 JSONB
# - 其他数据库为 JSON
JsonType = JSON().with_variant(JSONB, "postgresql")


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    phone_number: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config: Mapped[dict | None] = mapped_column(JsonType, default=dict, nullable=True)

    providers: Mapped[list["ProviderConfig"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    search_providers: Mapped[list["SearchProviderConfig"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    simulations: Mapped[list["Simulation"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    verification_tokens: Mapped[list["VerificationToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    experiment_templates: Mapped[list["ExperimentTemplate"]] = relationship(
        back_populates="creator", cascade="all, delete-orphan"
    )


class ProviderConfig(TimestampMixin, Base):
    """LLM provider configuration for a user.

    TODO: For hosted multi-user deployments, encrypt provider API keys at rest.
    Currently stored as plaintext in the database.
    """
    __tablename__ = "provider_configs"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_provider_user_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config: Mapped[dict] = mapped_column(JsonType, default=dict)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_status: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(String(512))

    user: Mapped["User"] = relationship(back_populates="providers")


class SearchProviderConfig(TimestampMixin, Base):
    __tablename__ = "search_provider_configs"
    __table_args__ = (UniqueConstraint("user_id", name="uq_search_provider_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config: Mapped[dict] = mapped_column(JsonType, default=dict)

    user: Mapped["User"] = relationship(back_populates="search_providers")
