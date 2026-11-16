from __future__ import annotations

import asyncio
import os

from sqlalchemy import select

from ..core.database import SessionLocal
from ..core.security import hash_password
from ..main import _prepare_database
from ..models.user import User


def _value_or_none(value: str) -> str | None:
    stripped = value.strip()
    return stripped if stripped else None


async def ensure_admin_user() -> None:
    await _prepare_database()
    email = os.environ["ADMIN_EMAIL"].strip()
    password = os.environ["ADMIN_PASSWORD"]
    username_src = os.environ.get("ADMIN_USERNAME", "").strip()
    full_name = _value_or_none(os.environ.get("ADMIN_FULL_NAME", ""))
    organization = _value_or_none(os.environ.get("ADMIN_ORGANIZATION", ""))

    username = username_src if username_src else email.split("@")[0]

    async with SessionLocal() as session:
        existing = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if existing is not None:
            existing.role = "admin"
            existing.full_name = full_name
            existing.organization = organization
            await session.commit()
            return

        user = User(
            organization=organization,
            email=email,
            username=username,
            full_name=full_name,
            phone_number=None,
            hashed_password=hash_password(password),
            is_active=True,
            is_verified=True,
            role="admin",
        )
        session.add(user)
        await session.commit()


def main() -> None:
    asyncio.run(ensure_admin_user())


if __name__ == "__main__":
    main()
