"""The feed cache: every registered source's recent items, on real-time TTL.

Same two-clock problem as :mod:`gaworld.city.news`, same answer. A 365-day run
can finish in an afternoon, so fetching "today's" feeds each sim-day would mean
hundreds of live requests per source for one wall-clock day during which the
feeds did not change. Fetching is gated on real elapsed time per source; what a
resident sees on a given sim-day is chosen by :mod:`gaworld.infosources.diet`.

The cache lives under ``output/infosources/`` (Database-per-Plugin) and the
running simulation reaches it through :func:`runtime` — a process-wide holder
set by the plugin, so the news pipeline needs no new parameter threaded through
the simulator's three call sites.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from gaworld.infosources.schema import InfoItem, Source
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.infosources.feed")

DEFAULT_TTL_HOURS = 6.0
DEFAULT_PER_SOURCE_LIMIT = 15


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class FeedCache:
    items: dict[str, list[InfoItem]] = field(default_factory=dict)
    last_fetch: dict[str, str] = field(default_factory=dict)

    def items_for(self, source_id: str) -> list[InfoItem]:
        return list(self.items.get(source_id, []))

    def all_items(self) -> list[InfoItem]:
        return [item for rows in self.items.values() for item in rows]

    def counts(self) -> dict[str, int]:
        return {source_id: len(rows) for source_id, rows in self.items.items()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_fetch": dict(self.last_fetch),
            "items": {sid: [item.to_dict() for item in rows] for sid, rows in self.items.items()},
        }

    @classmethod
    def from_dict(cls, data: Any) -> FeedCache:
        raw = data if isinstance(data, dict) else {}
        items: dict[str, list[InfoItem]] = {}
        for source_id, rows in (raw.get("items") or {}).items():
            if not isinstance(rows, list):
                continue
            parsed = [it for it in (InfoItem.from_dict(r) for r in rows) if it is not None]
            if parsed:
                items[str(source_id)] = parsed
        last_fetch = {str(k): str(v) for k, v in (raw.get("last_fetch") or {}).items()}
        return cls(items=items, last_fetch=last_fetch)


def load(path: Any) -> FeedCache:
    target = Path(str(path))
    if not target.exists():
        return FeedCache()
    try:
        return FeedCache.from_dict(json.loads(target.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        # A corrupt cache is not worth failing a run over; start a fresh one.
        return FeedCache()


def save(path: Any, cache: FeedCache) -> None:
    target = Path(str(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cache.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_stale(
    cache: FeedCache, source_id: str, *, ttl_hours: float = DEFAULT_TTL_HOURS, now: datetime | None = None
) -> bool:
    stamp = cache.last_fetch.get(source_id, "")
    if not stamp:
        return True
    try:
        last = datetime.fromisoformat(stamp)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    elapsed = (now or _utcnow()) - last
    return elapsed.total_seconds() >= max(0.0, float(ttl_hours)) * 3600.0


def refresh(
    sources: list[Source],
    path: Any,
    *,
    fetch_fn: Callable[[Source], list[InfoItem]],
    ttl_hours: float = DEFAULT_TTL_HOURS,
    per_source_limit: int = DEFAULT_PER_SOURCE_LIMIT,
    now: datetime | None = None,
    force: bool = False,
) -> FeedCache:
    """Fetch every enabled source whose TTL has elapsed; return the merged cache.

    New items go in front of what was already cached for that source, deduped
    by URL (or title), and the per-source list is capped. A fetch that yields
    nothing still stamps ``last_fetch`` so a dead source is retried once per
    window rather than on every sim-day.
    """
    cache = load(path)
    stamp = (now or _utcnow()).isoformat(timespec="seconds")
    attempted = 0
    added = 0
    for source in sources:
        if not source.enabled:
            continue
        if not force and not is_stale(cache, source.id, ttl_hours=ttl_hours, now=now):
            continue
        attempted += 1
        try:
            fresh = list(fetch_fn(source) or [])
        except Exception as exc:  # one dead feed must not end the refresh
            _LOG.warning("feed %s: fetch raised %s", source.id, exc)
            fresh = []
        cache.last_fetch[source.id] = stamp
        if not fresh:
            continue
        merged: list[InfoItem] = []
        seen: set[str] = set()
        for item in fresh + cache.items.get(source.id, []):
            if not item.title or item.key in seen:
                continue
            seen.add(item.key)
            merged.append(item)
            if len(merged) >= max(1, int(per_source_limit)):
                break
        added += sum(1 for item in fresh if item.key in seen)
        cache.items[source.id] = merged
    if attempted:
        try:
            save(path, cache)
        except OSError as exc:
            _LOG.warning("feed cache not saved (%s): %s", path, exc)
        _LOG.info("info feed refreshed: %d source(s) fetched, +%d item(s)", attempted, added)
    return cache


# ---------------------------------------------------------------------------
# Process-wide runtime (set by InfoSourcesPlugin, read by gaworld.sim._news)
# ---------------------------------------------------------------------------

@dataclass
class FeedRuntime:
    cache: FeedCache
    sources: dict[str, Source]
    settings: dict[str, Any] = field(default_factory=dict)
    #: The kernel Recorder, so ``gaworld.sim._news`` can log who read what
    #: (``infosources.read``) without a ctx threaded through its call sites.
    recorder: Any = None


_RUNTIME: FeedRuntime | None = None


def set_runtime(rt: FeedRuntime | None) -> None:
    global _RUNTIME
    _RUNTIME = rt


def runtime() -> FeedRuntime | None:
    return _RUNTIME


__all__ = [
    "DEFAULT_PER_SOURCE_LIMIT",
    "DEFAULT_TTL_HOURS",
    "FeedCache",
    "FeedRuntime",
    "is_stale",
    "load",
    "refresh",
    "runtime",
    "save",
    "set_runtime",
]
