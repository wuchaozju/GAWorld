"""External event data structures for event injection system.

This module defines Event types used by the Environment Agent
for representing external events (policy, market, news, custom).

Contains: ExternalEvent, ExternalEventType, Severity, EventSource
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict
import uuid


class ExternalEventType(Enum):
    """Types of external events that can be injected into simulation."""

    POLICY = "policy"
    MARKET = "market"
    NEWS = "news"
    CUSTOM = "custom"
    MANUAL = "manual"


class Severity(Enum):
    """Severity level of an event."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EventSource(Enum):
    """Source of the event data."""

    NATIONAL_BUREAU = "national_bureau"
    GOVERNMENT_OPEN_DATA = "government_open_data"
    YAHOO_FINANCE = "yahoo_finance"
    EAST_MONEY = "east_money"
    NEWS_API = "news_api"
    RSS = "rss"
    CUSTOM_API = "custom_api"
    MANUAL = "manual"


@dataclass(frozen=True)
class ExternalEvent:
    """External event that can be injected into simulation.

    Events are immutable once created.
    """

    id: str
    event_type: ExternalEventType
    source: EventSource
    title: str
    content: str
    timestamp: datetime
    severity: Severity
    metadata: Dict[str, Any] = field(default_factory=dict)
    url: str | None = None
    raw_data: Dict[str, Any] | None = None

    @classmethod
    def create(
        cls,
        event_type: ExternalEventType,
        source: EventSource,
        title: str,
        content: str,
        severity: Severity = Severity.MEDIUM,
        metadata: Dict[str, Any] | None = None,
        url: str | None = None,
        raw_data: Dict[str, Any] | None = None,
    ) -> "ExternalEvent":
        """Factory method to create a new ExternalEvent with auto-generated ID."""
        return cls(
            id=str(uuid.uuid4()),
            event_type=event_type,
            source=source,
            title=title,
            content=content,
            timestamp=datetime.now(),
            severity=severity,
            metadata=metadata or {},
            url=url,
            raw_data=raw_data,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for serialization."""
        return {
            "id": self.id,
            "event_type": self.event_type.value,
            "source": self.source.value,
            "title": self.title,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "severity": self.severity.value,
            "metadata": self.metadata,
            "url": self.url,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExternalEvent":
        """Reconstruct ExternalEvent from dictionary."""
        return cls(
            id=data["id"],
            event_type=ExternalEventType(data["event_type"]),
            source=EventSource(data["source"]),
            title=data["title"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            severity=Severity(data["severity"]),
            metadata=data.get("metadata", {}),
            url=data.get("url"),
        )


@dataclass
class EventFilter:
    """Filter criteria for selecting events."""

    types: list[ExternalEventType] | None = None
    sources: list[EventSource] | None = None
    min_severity: Severity | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int | None = None

    def matches(self, event: ExternalEvent) -> bool:
        """Check if event matches filter criteria."""
        if self.types and event.event_type not in self.types:
            return False
        if self.sources and event.source not in self.sources:
            return False
        if self.min_severity:
            severity_order = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
            if severity_order.index(event.severity) < severity_order.index(self.min_severity):
                return False
        if self.since and event.timestamp < self.since:
            return False
        if self.until and event.timestamp > self.until:
            return False
        return True
