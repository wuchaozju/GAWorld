"""Utilities for managing email verification tokens."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..models.token import VerificationToken
from ..models.user import User


async def issue_verification_token(session: AsyncSession, user: User) -> VerificationToken:
    settings = get_settings()
    await session.execute(
        delete(VerificationToken).where(VerificationToken.user_id == user.id)
    )

    token_value = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.verification_token_exp_minutes
    )

    token = VerificationToken(
        user_id=user.id,
        token=token_value,
        sent_to=user.email,
        expires_at=expires_at,
    )
    session.add(token)
    await session.commit()
    await session.refresh(token)
    return token


async def get_verification_token(session: AsyncSession, token_value: str) -> VerificationToken | None:
    query = await session.execute(
        select(VerificationToken).where(VerificationToken.token == token_value)
    )
    return query.scalar_one_or_none()
