from __future__ import annotations

from sqlalchemy import Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from ..db.mixins import TimestampMixin


class LLMUsage(TimestampMixin, Base):
    __tablename__ = "llm_usages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[int] = mapped_column(Integer, ForeignKey("provider_configs.id", ondelete="CASCADE"), index=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    tokens_reserved: Mapped[int] = mapped_column(Integer, default=0)

    # relationships (optional)
    # user: Mapped["User"] = relationship(back_populates="llm_usages")
    # provider: Mapped["ProviderConfig"] = relationship()
