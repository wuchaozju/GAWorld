"""Recent local news for a city, cached on *real* time and served on *sim* time.

The two clocks are the whole problem this module exists to solve. A 365-day
simulation can finish in an afternoon, so "fetch today's news each sim-day"
would mean 365 live searches for a single wall-clock day during which the news
did not meaningfully change. Instead:

* **fetching** is gated on real elapsed time (``ttl_hours``) — one fetch per
  window no matter how fast the simulation runs;
* **serving** is gated on sim time — each sim-day draws a small, rotating slice
  of the cache, so agents see the city's news drip in rather than all at once.

Everything degrades to "no news" rather than failing: a city with no network is
still perfectly simulable, just without current events.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.city.news")

#: How long a fetched batch stays fresh, in real hours.
DEFAULT_TTL_HOURS = 6.0
#: How many items each sim-day serves to the simulation.
DEFAULT_PER_DAY = 2
#: Cap on the stored cache, oldest evicted first.
MAX_ITEMS = 60


@dataclass
class NewsItem:
    title: str
    excerpt: str = ""
    url: str = ""
    fetched_at: str = ""

    def text(self, *, max_chars: int = 160) -> str:
        body = f"{self.title}：{self.excerpt}" if self.excerpt else self.title
        return body[:max_chars]


@dataclass
class NewsCache:
    city: str = ""
    items: list[NewsItem] = field(default_factory=list)
    last_fetch: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"city": self.city, "last_fetch": self.last_fetch,
                "items": [asdict(item) for item in self.items]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NewsCache":
        raw = data or {}
        items = [
            NewsItem(
                title=str(i.get("title", "")).strip(),
                excerpt=str(i.get("excerpt", "")).strip(),
                url=str(i.get("url", "")).strip(),
                fetched_at=str(i.get("fetched_at", "")),
            )
            for i in raw.get("items", []) or []
            if isinstance(i, dict) and str(i.get("title", "")).strip()
        ]
        return cls(city=str(raw.get("city", "")), items=items, last_fetch=str(raw.get("last_fetch", "")))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load(path: Any) -> NewsCache:
    from pathlib import Path

    target = Path(path)
    if not target.exists():
        return NewsCache()
    try:
        return NewsCache.from_dict(json.loads(target.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        # A corrupt cache is not worth failing a run over; start a fresh one.
        return NewsCache()


def save(path: Any, cache: NewsCache) -> None:
    from pathlib import Path

    Path(path).write_text(
        json.dumps(cache.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def is_stale(cache: NewsCache, *, ttl_hours: float = DEFAULT_TTL_HOURS, now: datetime | None = None) -> bool:
    """Whether the real-time window has elapsed since the last fetch."""
    if not cache.last_fetch:
        return True
    try:
        last = datetime.fromisoformat(cache.last_fetch)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed = (now or _utcnow()) - last
    return elapsed.total_seconds() >= max(0.0, float(ttl_hours)) * 3600.0


def news_queries(city_name: str) -> list[str]:
    return [f"{city_name} 最新新闻", f"{city_name} 经济 产业 动态"]


def refresh(
    path: Any,
    city_name: str,
    *,
    search_fn: Callable[[str], list[dict[str, str]]],
    ttl_hours: float = DEFAULT_TTL_HOURS,
    now: datetime | None = None,
    force: bool = False,
) -> NewsCache:
    """Fetch fresh news when the real-time TTL has expired, else reuse the cache.

    Returns the cache either way, so callers need not distinguish "fetched" from
    "still fresh".
    """
    cache = load(path)
    if not (force or is_stale(cache, ttl_hours=ttl_hours, now=now)):
        return cache

    stamp = (now or _utcnow()).isoformat(timespec="seconds")
    seen = {item.url for item in cache.items if item.url}
    seen_titles = {item.title for item in cache.items}
    fresh: list[NewsItem] = []
    for query in news_queries(city_name):
        try:
            hits = search_fn(query) or []
        except Exception as exc:  # noqa: BLE001 - news is enrichment, never critical
            _LOG.warning("news search failed for %r: %s", query, exc)
            continue
        for hit in hits:
            title = str(hit.get("title", "")).strip()
            url = str(hit.get("url", "")).strip()
            if not title or title in seen_titles or (url and url in seen):
                continue
            seen_titles.add(title)
            if url:
                seen.add(url)
            fresh.append(
                NewsItem(
                    title=title[:160],
                    excerpt=str(hit.get("excerpt") or hit.get("content") or "").strip()[:280],
                    url=url,
                    fetched_at=stamp,
                )
            )

    if not fresh and cache.items:
        # Nothing new, but the window did elapse — record the attempt so a dead
        # network does not re-trigger a fetch on every single sim-day.
        cache.last_fetch = stamp
        save(path, cache)
        return cache

    cache.city = city_name or cache.city
    cache.items = (cache.items + fresh)[-MAX_ITEMS:]
    cache.last_fetch = stamp
    save(path, cache)
    _LOG.info("city news refreshed for %s: +%d (total %d)", city_name, len(fresh), len(cache.items))
    return cache


def for_sim_day(cache: NewsCache, sim_day: int, *, per_day: int = DEFAULT_PER_DAY) -> list[NewsItem]:
    """The slice of the cache this sim-day should surface.

    Rotates through the cache by day so a long run keeps encountering different
    stories instead of replaying the same headline every morning.
    """
    items = cache.items
    if not items or per_day <= 0:
        return []
    count = min(per_day, len(items))
    start = (max(0, int(sim_day)) * count) % len(items)
    return [items[(start + offset) % len(items)] for offset in range(count)]


def prompt_block(items: list[NewsItem], *, max_chars: int = 240) -> str:
    if not items:
        return ""
    return "；".join(item.text() for item in items)[:max_chars]


__all__ = [
    "DEFAULT_PER_DAY",
    "DEFAULT_TTL_HOURS",
    "NewsCache",
    "NewsItem",
    "for_sim_day",
    "is_stale",
    "load",
    "news_queries",
    "prompt_block",
    "refresh",
    "save",
]
