# This file polls data sources, turns their data into events, and saves those events.

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from dateutil.parser import parse as parse_dt

from fos.backend.models.data_source import DataSource
from fos.backend.models.external_event_record import ExternalEventRecord
from fos.core.external_event import ExternalEventType, Severity

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(UTC)


# Keyword-based rule engine for ExternalEventService
def _evaluate_event_type(title: str, content: str) -> str:
    """Infer event_type from title/content keywords."""
    text = f"{title} {content}".lower()
    if any(kw in text for kw in ["政策", "regulation", "监管", "government", "official"]):
        return ExternalEventType.POLICY.value
    if any(kw in text for kw in ["新闻", "news", "报道", "announcement"]):
        return ExternalEventType.NEWS.value
    return ExternalEventType.MARKET.value


def _evaluate_severity(title: str, content: str) -> str:
    """Infer severity from title/content keywords."""
    text = f"{title} {content}".lower()
    if any(kw in text for kw in ["紧急", "critical", "crisis", "重大", "breaking", "alert"]):
        return Severity.CRITICAL.value
    if any(kw in text for kw in ["警告", "warning", "high", "风险", "danger"]):
        return Severity.HIGH.value
    if any(kw in text for kw in ["暴跌", "surge", "spike", "plunge", "soar"]):
        return Severity.HIGH.value
    return Severity.MEDIUM.value


class ExternalEventService:
    """Handles polling a single data source and writing events to DB."""

    async def poll_source(self, source: DataSource) -> int:
        """Poll one data source, evaluate events, persist to DB.

        Returns:
            Number of events created (0 if none or error).
        """
        from fos.backend.core.database import get_session

        logger.info(f"Polling source: {source.name} ({source.id})")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = self._build_auth_headers(source)
                response = await client.get(source.api_url, headers=headers)
                response.raise_for_status()
                data = response.json()

            events = self._parse_response(data, source.field_mapping or {})
            count = 0
            async with get_session() as session:
                for event_dict in events:
                    record = ExternalEventRecord(
                        data_source_id=source.id,
                        simulation_id=source.simulation_id,
                        event_type=event_dict["event_type"],
                        source=source.name,
                        title=event_dict["title"],
                        content=event_dict["content"],
                        severity=event_dict["severity"],
                        url=event_dict.get("url"),
                        raw_data=event_dict.get("raw_data"),
                        event_timestamp=event_dict["event_timestamp"],
                        status="pending",
                    )
                    session.add(record)
                    count += 1
                await session.commit()

                # Update last_poll_at
                source.last_poll_at = _utc_now()
                source.last_error = None
                await session.commit()

            logger.info(f"Source {source.id}: created {count} events")
            return count

        except Exception as e:
            logger.error(f"Source {source.id} poll error: {e}", exc_info=True)
            # Update last_error on source
            try:
                async with get_session() as session:
                    from sqlalchemy import select

                    stmt = select(DataSource).where(DataSource.id == source.id)
                    db_source = (await session.execute(stmt)).scalar_one_or_none()
                    if db_source:
                        db_source.last_error = str(e)[:500]
                        await session.commit()
            except Exception:
                pass
            return 0

    def _build_auth_headers(self, source: DataSource) -> dict[str, str]:
        """Build request headers from auth config."""
        headers = {}
        if source.auth_type == "bearer":
            headers["Authorization"] = f"Bearer {source.auth_token}"
        elif source.auth_type == "api_key":
            headers["X-API-Key"] = source.auth_token
        else:
            # "none" is valid — no auth needed. Log for unknown types only.
            if source.auth_type and source.auth_type not in ("none", ""):
                logger.warning(f"Unknown auth_type '{source.auth_type}' for source {source.id} — proceeding without auth")
        return headers

    def _parse_response(
        self, data: Any, field_mapping: dict
    ) -> list[dict]:
        """Parse API response using field_mapping config.

        Supports nested paths like "data.items[0].title".
        """
        if not field_mapping:
            # Fallback: try to extract from common structure
            return self._parse_auto(data)
        if not isinstance(data, dict):
            return []

        results = []
        items = self._get_nested(data, field_mapping.get("items_path", "data"))
        if not isinstance(items, list):
            items = [data]

        for item in items:
            title = self._get_nested(item, field_mapping.get("title_path", "title"))
            content = self._get_nested(item, field_mapping.get("content_path", "content"))
            timestamp_str = self._get_nested(item, field_mapping.get("timestamp_path", "timestamp"))
            url = self._get_nested(item, field_mapping.get("url_path", "url"))

            if not title or not content:
                continue

            try:
                ts = parse_dt(timestamp_str) if timestamp_str else _utc_now()
            except Exception:
                ts = _utc_now()

            results.append({
                "event_type": _evaluate_event_type(str(title), str(content)),
                "severity": _evaluate_severity(str(title), str(content)),
                "title": str(title),
                "content": str(content),
                "event_timestamp": ts,
                "url": str(url) if url else None,
                "raw_data": item,
            })
        return results

    def _parse_auto(self, data: Any) -> list[dict]:
        """Auto-parse when no field_mapping provided — for simple JSON arrays."""
        results = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    title = item.get("title") or item.get("name") or item.get("heading")
                    content = item.get("content") or item.get("description") or item.get("summary") or str(item)
                    if title:
                        ts_str = item.get("timestamp") or item.get("published_at")
                        try:
                            ts = parse_dt(ts_str) if ts_str else _utc_now()
                        except Exception:
                            ts = _utc_now()
                        results.append({
                            "event_type": _evaluate_event_type(str(title), str(content)),
                            "severity": _evaluate_severity(str(title), str(content)),
                            "title": str(title),
                            "content": str(content),
                            "event_timestamp": ts,
                            "url": item.get("url") or item.get("link"),
                            "raw_data": item,
                        })
        elif isinstance(data, dict):
            # Try to find items inside common keys
            for key in ("data", "results", "items", "articles"):
                if key in data and isinstance(data[key], list):
                    return self._parse_auto(data[key])
        return results

    def _get_nested(self, obj: Any, path: str) -> Any:
        """Get nested value from dict using dot-notation path like 'data.items[0].title'."""
        if not path or not isinstance(obj, dict):
            return obj
        parts = path.replace("[", ".[").split(".")
        current = obj
        for part in parts:
            if "[" in part:
                key, idx_str = part.split("[", 1)
                idx = int(idx_str.rstrip("]"))
                current = current.get(key, [])
                if isinstance(current, list) and idx < len(current):
                    current = current[idx]
                else:
                    return None
            else:
                current = current.get(part)
                if current is None:
                    return None
        return current


async def poll_data_source(source_id: str) -> None:
    """Top-level async function for APScheduler job — resolves source from DB and polls.

    This is the function passed to PollingService.add_job() as poll_fn.
    """
    from fos.backend.core.database import get_session
    from sqlalchemy import select

    async with get_session() as session:
        stmt = select(DataSource).where(DataSource.id == source_id)
        source = (await session.execute(stmt)).scalar_one_or_none()

    if source is None:
        logger.warning(f"DataSource {source_id} not found, skipping poll")
        return

    if not source.is_enabled:
        logger.info(f"DataSource {source_id} is disabled, skipping poll")
        return

    service = ExternalEventService()
    await service.poll_source(source)
