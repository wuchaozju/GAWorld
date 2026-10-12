from __future__ import annotations

import asyncio
from typing import Sequence

from sqlalchemy import delete, or_, select

from fos.backend.core.database import engine, get_session
from fos.backend.db.base import Base
from fos.backend.models.user import ProviderConfig, SearchProviderConfig


async def migrate() -> int:
    # Ensure all tables exist (creates search_provider_configs if missing)
    import fos.backend.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with get_session() as session:
        cond = or_(ProviderConfig.name == "search", ProviderConfig.model == "search")
        result = await session.execute(select(ProviderConfig).where(cond))
        legacy: Sequence[ProviderConfig] = result.scalars().all()

        migrated_user_ids: list[int] = []
        for row in legacy:
            existing = await session.execute(
                select(SearchProviderConfig).where(SearchProviderConfig.user_id == row.user_id)
            )
            if existing.scalars().first() is None:
                sp = SearchProviderConfig(
                    user_id=row.user_id,
                    provider=row.provider,
                    base_url=row.base_url,
                    api_key=row.api_key,
                    config=row.config or {},
                )
                session.add(sp)
                migrated_user_ids.append(int(row.user_id))

        await session.flush()

        if migrated_user_ids:
            await session.execute(
                delete(ProviderConfig).where(
                    cond, ProviderConfig.user_id.in_(migrated_user_ids)
                )
            )

        await session.commit()
        return len(migrated_user_ids)


async def _main() -> None:
    count = await migrate()
    print(f"migrated {count} search provider(s)")


if __name__ == "__main__":
    asyncio.run(_main())

