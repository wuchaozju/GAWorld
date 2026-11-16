"""Event fetcher for polling external APIs.

Provides a base class and implementations for polling various external
data sources (policy, market, news, custom APIs).

Supports:
- Policy data from government open data platforms
- Market data from Yahoo Finance
- News from RSS feeds and public APIs
- Custom user-defined API endpoints
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional
import urllib.request

from fos.core.external_event import (
    ExternalEvent,
    ExternalEventType,
    EventSource,
    Severity,
)

logger = logging.getLogger(__name__)


class BaseEventFetcher(ABC):
    """Abstract base class for event fetchers."""

    def __init__(
        self,
        poll_interval_minutes: int = 10,
        enabled: bool = True,
    ) -> None:
        """Initialize the fetcher.

        Args:
            poll_interval_minutes: How often to poll (minutes).
            enabled: Whether fetching is enabled.
        """
        self.poll_interval = poll_interval_minutes * 60
        self.enabled = enabled
        self._last_poll: Optional[datetime] = None
        self._running = False

    @property
    @abstractmethod
    def source(self) -> EventSource:
        """Return the event source identifier."""
        pass

    @property
    @abstractmethod
    def event_type(self) -> ExternalEventType:
        """Return the event type for this source."""
        pass

    @abstractmethod
    async def fetch(self) -> list[ExternalEvent]:
        """Fetch events from the data source.

        Returns:
            List of ExternalEvents fetched from the source.
        """
        pass

    async def poll(self) -> list[ExternalEvent]:
        """Poll the data source and return new events.

        Returns:
            List of new ExternalEvents since last poll.
        """
        if not self.enabled:
            return []

        try:
            events = await self.fetch()
            self._last_poll = datetime.now()
            logger.info(
                f"Polled {self.source.value}: {len(events)} events"
            )
            return events
        except Exception as e:
            logger.error(f"Error polling {self.source.value}: {e}")
            return []

    async def run(self, queue, interval_seconds: Optional[int] = None):
        """Run continuous polling.

        Args:
            queue: EventQueue to add events to.
            interval_seconds: Override default poll interval.
        """
        self._running = True
        interval = interval_seconds or self.poll_interval

        while self._running:
            events = await self.poll()
            for event in events:
                queue.enqueue(event)
            await asyncio.sleep(interval)

    def stop(self):
        """Stop the polling loop."""
        self._running = False


class PolicyEventFetcher(BaseEventFetcher):
    """Fetcher for government policy data.

    Uses Chinese government open data APIs and RSS feeds.
    Sources:
    - National Bureau of Statistics (stats.gov.cn)
    - Government RSS feeds
    """

    @property
    def source(self) -> EventSource:
        return EventSource.NATIONAL_BUREAU

    @property
    def event_type(self) -> ExternalEventType:
        return ExternalEventType.POLICY

    async def fetch(self) -> list[ExternalEvent]:
        """Fetch policy events from Chinese government data sources."""
        events: list[ExternalEvent] = []

        # Try fetching from National Bureau of Statistics API
        stats_events = await self._fetch_stats_data()
        events.extend(stats_events)

        # Fetch from government RSS feeds
        rss_events = await self._fetch_gov_rss()
        events.extend(rss_events)

        return events

    async def _fetch_stats_data(self) -> list[ExternalEvent]:
        """Fetch data from National Bureau of Statistics."""
        try:
            # National Bureau of Statistics open data API
            url = "http://www.stats.gov.cn/english/"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                content = response.read().decode("utf-8", errors="ignore")

            # Parse for policy announcements
            events = []
            # Simplified parsing - in production would parse HTML properly
            if "release" in content.lower():
                events.append(ExternalEvent.create(
                    event_type=ExternalEventType.POLICY,
                    source=EventSource.NATIONAL_BUREAU,
                    title="National Statistics Release",
                    content="New statistical data released by National Bureau of Statistics",
                    severity=Severity.MEDIUM,
                    metadata={"source_url": url},
                ))
            return events
        except Exception as e:
            logger.debug(f"Stats.gov.cn fetch failed: {e}")
            return []

    async def _fetch_gov_rss(self) -> list[ExternalEvent]:
        """Fetch from government RSS feeds."""
        # Chinese government RSS sources
        rss_urls = [
            ("gov.cn", "http://www.gov.cn/rss/sygz.htm"),
            ("chinanews", "https://www.chinanews.com/rss/scroll.xml"),
        ]

        events = []
        for name, url in rss_urls:
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                with urllib.request.urlopen(req, timeout=10) as response:
                    content = response.read().decode("utf-8", errors="ignore")

                # Parse RSS items (simplified)
                if "<item>" in content.lower():
                    # Extract title from RSS item
                    import re
                    titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", content)
                    for title in titles[:3]:  # Limit to 3 items per source
                        if title and len(title) > 5:
                            events.append(ExternalEvent.create(
                                event_type=ExternalEventType.POLICY,
                                source=EventSource.GOVERNMENT_OPEN_DATA,
                                title=f"Government Update: {title[:50]}",
                                content=title,
                                severity=Severity.MEDIUM,
                                metadata={"feed": name},
                            ))
                break  # Successfully fetched, no need to try others
            except Exception as e:
                logger.debug(f"RSS fetch failed for {name}: {e}")
                continue

        return events


class MarketEventFetcher(BaseEventFetcher):
    """Fetcher for market/economic data."""

    @property
    def source(self) -> EventSource:
        return EventSource.YAHOO_FINANCE

    @property
    def event_type(self) -> ExternalEventType:
        return ExternalEventType.MARKET

    async def fetch(self) -> list[ExternalEvent]:
        """Fetch market events from Yahoo Finance."""
        # TODO: Implement using yfinance library
        # Example implementation:
        # import yfinance as yf
        # ticker = yf.Ticker("^GSPC")
        # data = ticker.history(period="1d")
        return []


class NewsEventFetcher(BaseEventFetcher):
    """Fetcher for news and public opinion.

    Uses RSS feeds and public news APIs to fetch relevant news events.
    Supports sentiment analysis on fetched news.
    """

    @property
    def source(self) -> EventSource:
        return EventSource.NEWS_API

    @property
    def event_type(self) -> ExternalEventType:
        return ExternalEventType.NEWS

    async def fetch(self) -> list[ExternalEvent]:
        """Fetch news events from RSS feeds and public APIs."""
        events: list[ExternalEvent] = []

        # Fetch from RSS feeds
        rss_events = await self._fetch_news_rss()
        events.extend(rss_events)

        # Analyze sentiment of news
        for event in events:
            event.metadata["sentiment"] = self._analyze_sentiment(event.content)

        return events

    async def _fetch_news_rss(self) -> list[ExternalEvent]:
        """Fetch from news RSS feeds."""
        # Public news RSS sources (no API key required)
        rss_sources = [
            ("reuters", "http://feeds.reuters.com/reuters/topNews"),
            ("bbc", "http://feeds.bbci.co.uk/news/rss.xml"),
            ("techcrunch", "https://techcrunch.com/feed/"),
        ]

        events = []
        for name, url in rss_sources:
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                with urllib.request.urlopen(req, timeout=10) as response:
                    content = response.read().decode("utf-8", errors="ignore")

                if "<item>" in content.lower():
                    import re
                    items = re.findall(
                        r"<item>(.*?)</item>",
                        content,
                        re.DOTALL | re.IGNORECASE
                    )

                    for item in items[:5]:  # Limit to 5 items per source
                        title_match = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", item)
                        desc_match = re.search(r"<description><!\[CDATA\[(.*?)\]\]></description>", item)

                        if title_match:
                            title = title_match.group(1).strip()
                            description = desc_match.group(1).strip() if desc_match else ""

                            if title and len(title) > 5:
                                events.append(ExternalEvent.create(
                                    event_type=ExternalEventType.NEWS,
                                    source=EventSource.RSS,
                                    title=title[:100],
                                    content=description[:500] if description else title,
                                    severity=self._estimate_severity(title + " " + description),
                                    metadata={
                                        "feed": name,
                                        "url": url,
                                    },
                                ))
                    break  # Successfully fetched, stop trying other sources
            except Exception as e:
                logger.debug(f"News RSS fetch failed for {name}: {e}")
                continue

        return events

    def _analyze_sentiment(self, text: str) -> str:
        """Simple rule-based sentiment analysis."""
        if not text:
            return "neutral"

        positive_words = ["growth", "rise", "increase", "positive", "gain", "profit", "up"]
        negative_words = ["decline", "fall", "drop", "negative", "loss", "down", "crisis"]

        text_lower = text.lower()
        pos_count = sum(1 for word in positive_words if word in text_lower)
        neg_count = sum(1 for word in negative_words if word in text_lower)

        if pos_count > neg_count:
            return "positive"
        elif neg_count > pos_count:
            return "negative"
        return "neutral"

    def _estimate_severity(self, text: str) -> Severity:
        """Estimate event severity based on content."""
        critical_words = ["crisis", "emergency", "disaster", "crash", "collapse"]
        high_words = ["recession", "inflation", "war", "conflict", "strike"]
        medium_words = ["change", "reform", "policy", "report", "data"]

        text_lower = text.lower()

        if any(word in text_lower for word in critical_words):
            return Severity.CRITICAL
        if any(word in text_lower for word in high_words):
            return Severity.HIGH
        if any(word in text_lower for word in medium_words):
            return Severity.MEDIUM
        return Severity.LOW


class CustomEventFetcher(BaseEventFetcher):
    """Fetcher for custom user-defined APIs.

    Supports REST APIs with optional authentication and custom field mapping.
    """

    def __init__(
        self,
        api_url: str,
        auth_token: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        poll_interval_minutes: int = 10,
        enabled: bool = True,
        field_mapping: Optional[Dict[str, str]] = None,
    ) -> None:
        """Initialize the custom API fetcher.

        Args:
            api_url: The REST API endpoint URL.
            auth_token: Optional authentication token (Bearer, API Key, etc).
            headers: Custom HTTP headers to include in requests.
            poll_interval_minutes: How often to poll (minutes).
            enabled: Whether fetching is enabled.
            field_mapping: Mapping from standard fields to API response fields.
                e.g., {"title": "name", "content": "description", "timestamp": "created_at"}
        """
        super().__init__(poll_interval_minutes, enabled)
        self.api_url = api_url
        self.auth_token = auth_token
        self.headers = headers or {}
        self.field_mapping = field_mapping or {
            "title": "title",
            "content": "content",
            "timestamp": "timestamp",
            "severity": "severity",
        }

    @property
    def source(self) -> EventSource:
        return EventSource.CUSTOM_API

    @property
    def event_type(self) -> ExternalEventType:
        return ExternalEventType.CUSTOM

    async def fetch(self) -> list[ExternalEvent]:
        """Fetch events from custom API endpoint."""
        events = []

        try:
            req = urllib.request.Request(
                self.api_url,
                headers=self._build_headers(),
            )

            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))

            # Handle both array and object responses
            items = data if isinstance(data, list) else data.get("data", data.get("items"))

            # If single object (no items key and not a list), treat as single item
            if items is None:
                items = [data] if isinstance(data, dict) else []
            elif not isinstance(items, list):
                items = [items]

            for item in items:
                # Skip if not a dict (shouldn't happen but be safe)
                if not isinstance(item, dict):
                    continue
                # Skip if already processed (avoids double mapping)
                if "event_type" in item or "_mapped" in item:
                    continue
                mapped = self._map_fields(item)
                if mapped:
                    events.append(ExternalEvent.create(
                        event_type=ExternalEventType.CUSTOM,
                        source=EventSource.CUSTOM_API,
                        title=mapped.get("title", "Custom Event"),
                        content=mapped.get("content", ""),
                        severity=self._parse_severity(mapped.get("severity", "medium")),
                        metadata=item,
                    ))
        except Exception as e:
            logger.error(f"Custom API fetch failed: {e}")

        return events

    def _build_headers(self) -> Dict[str, str]:
        """Build request headers including authentication."""
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        }
        headers.update(self.headers)

        if self.auth_token:
            if self.auth_token.startswith("Bearer "):
                headers["Authorization"] = self.auth_token
            elif self.auth_token.startswith("ApiKey "):
                headers["X-API-Key"] = self.auth_token.replace("ApiKey ", "")
            else:
                headers["Authorization"] = f"Bearer {self.auth_token}"

        return headers

    def _map_fields(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Map custom API fields to standard event fields."""
        mapped = {}
        for standard_field, api_field in self.field_mapping.items():
            if api_field in item:
                mapped[standard_field] = item[api_field]
        return mapped

    def _parse_severity(self, severity_str: str) -> Severity:
        """Parse severity string to Severity enum."""
        severity_lower = severity_str.lower() if isinstance(severity_str, str) else "medium"
        severity_map = {
            "critical": Severity.CRITICAL,
            "high": Severity.HIGH,
            "medium": Severity.MEDIUM,
            "low": Severity.LOW,
        }
        return severity_map.get(severity_lower, Severity.MEDIUM)


class EventFetcherRegistry:
    """Registry for all event fetchers."""

    def __init__(self) -> None:
        self._fetchers: dict[str, BaseEventFetcher] = {}

    def register(self, name: str, fetcher: BaseEventFetcher) -> None:
        """Register a fetcher.

        Args:
            name: Unique identifier for the fetcher.
            fetcher: The fetcher instance.
        """
        self._fetchers[name] = fetcher

    def get(self, name: str) -> Optional[BaseEventFetcher]:
        """Get a fetcher by name."""
        return self._fetchers.get(name)

    def get_all(self) -> dict[str, BaseEventFetcher]:
        """Get all registered fetchers."""
        return dict(self._fetchers)

    def get_enabled(self) -> dict[str, BaseEventFetcher]:
        """Get all enabled fetchers."""
        return {k: v for k, v in self._fetchers.items() if v.enabled}
