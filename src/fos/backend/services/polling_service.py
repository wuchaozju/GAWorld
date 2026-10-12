"""PollingService — APScheduler-based poll job manager for data sources."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler

if TYPE_CHECKING:
    from fos.backend.models.data_source import DataSource

logger = logging.getLogger(__name__)


class PollingService:
    """Singleton scheduler that manages APScheduler interval jobs per DataSource."""

    _instance: PollingService | None = None
    _scheduler: AsyncIOScheduler

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()

    @classmethod
    def get_instance(cls) -> PollingService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start(self) -> None:
        """Start scheduler and register jobs for all enabled data sources.

        Must be called when an event loop is already running (e.g., from Litestar lifespan).
        """
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("PollingService started")

        await self._load_enabled_sources()

    async def _load_enabled_sources(self) -> None:
        """Load enabled sources and register poll jobs."""
        from fos.backend.core.database import get_session
        from sqlalchemy import select
        from fos.backend.models.data_source import DataSource

        async with get_session() as session:
            stmt = select(DataSource).where(DataSource.is_enabled.is_(True))
            result = await session.execute(stmt)
            sources = result.scalars().all()

        for source in sources:
            from fos.backend.services.external_event_service import poll_data_source
            self.add_job(source, poll_data_source)

        logger.info(f"Loaded {len(sources)} enabled data sources")

    def add_job(self, source: DataSource, poll_fn) -> None:
        """Register or update a polling job for a data source.

        Args:
            source: DataSource instance with poll_interval_seconds, id, etc.
            poll_fn: Async function to call — receives (source_id,).
                     Signature: async def poll_fn(source_id: str) -> None
        """
        job_id = source.id
        # Remove existing job if present (safe even if not exists)
        self.remove_job(job_id)

        self._scheduler.add_job(
            poll_fn,
            trigger="interval",
            seconds=int(source.poll_interval_seconds),
            id=job_id,
            kwargs={"source_id": source.id},
            name=f"poll_{source.name}",
            replace_existing=True,
        )
        logger.info(f"Job added: {job_id} interval={source.poll_interval_seconds}s")

    def remove_job(self, source_id: str) -> None:
        """Remove a polling job by data source ID."""
        try:
            self._scheduler.remove_job(source_id)
            logger.info(f"Job removed: {source_id}")
        except Exception as e:
            from apscheduler.jobstores.base import JobLookupError
            if isinstance(e, JobLookupError):
                logger.debug(f"Job not found (already removed): {source_id}")
            else:
                logger.warning(f"Failed to remove job {source_id}: {e}")

    def pause_job(self, source_id: str) -> None:
        """Pause (not remove) a job — can be resumed."""
        try:
            self._scheduler.pause_job(source_id)
            logger.info(f"Job paused: {source_id}")
        except Exception as error:
            logger.warning(f"Failed to pause job {source_id}: {error}")

    def resume_job(self, source_id: str) -> None:
        """Resume a paused job."""
        try:
            self._scheduler.resume_job(source_id)
            logger.info(f"Job resumed: {source_id}")
        except Exception as error:
            logger.warning(f"Failed to resume job {source_id}: {error}")

    def shutdown(self) -> None:
        """Stop the scheduler gracefully."""
        self._scheduler.shutdown(wait=False)
        logger.info("PollingService shutdown")
