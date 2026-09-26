"""Channel adapters: fetch one source and normalise it into ``InfoItem`` rows.

Each parser is a pure function of the response text, so the whole module is
testable from fixture strings; :func:`fetch_source` is the only thing that
touches the network, and it goes through :mod:`gaworld.io.http_guard` so the
per-host rate limit, User-Agent rotation and failure cache that protect the
news pipeline protect these fetches too.

Why these channels and not a headless browser: every one of them is a public,
unauthenticated endpoint that returns structured text — RSS/Atom for news and
professional sites (including the arXiv API), Reddit's ``.json`` views, the
Hacker News search API, and the JSON behind Weibo / Baidu / Bilibili hot lists.
That is the difference between "social media" meaning a login wall and it
meaning what people are actually talking about today.

Nothing here raises: a dead feed is logged and yields ``[]``.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import requests

from gaworld.infosources.schema import InfoItem, Source
from gaworld.io.http_guard import GuardedSession, get_default_session
from gaworld.io.web_scrape import extract_news_main_content, extract_title, normalize_text, strip_html
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.infosources.channels")

#: Response bodies past this are truncated before parsing — a feed is a few
#: hundred KB, and ``xml.etree`` has no other guard against a hostile payload.
MAX_BYTES = 2_000_000
EXCERPT_CHARS = 400

#: Reddit rejects the browser-looking User-Agents the rotator hands out with a
#: 429 unless the UA identifies the client; a descriptive one is what they ask for.
REDDIT_USER_AGENT = "GAWorld/1.0 (generative-agent research simulation)"


def _stamp(now: datetime | None) -> str:
    return (now or datetime.now(UTC)).isoformat(timespec="seconds")


def _clip(text: str, limit: int = EXCERPT_CHARS) -> str:
    text = normalize_text(strip_html(str(text or "")))
    return text[:limit]


def _local(tag: str) -> str:
    """``{ns}name`` → ``name``."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _from_epoch(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value), tz=UTC).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


# ---------------------------------------------------------------------------
# RSS 2.0 / RSS 1.0 / Atom
# ---------------------------------------------------------------------------

def _entry_link(entry: ET.Element) -> str:
    """RSS ``<link>text</link>`` or Atom ``<link href=… rel="alternate"/>``."""
    fallback = ""
    for child in entry:
        if _local(child.tag) != "link":
            continue
        href = str(child.attrib.get("href", "")).strip()
        text = (child.text or "").strip()
        rel = str(child.attrib.get("rel", "alternate")).strip()
        if href and rel == "alternate":
            return href
        if href and not fallback:
            fallback = href
        if text.startswith("http"):
            return text
    return fallback


def _entry_field(entry: ET.Element, *names: str) -> str:
    for name in names:
        for child in entry:
            if _local(child.tag) == name and (child.text or "").strip():
                return (child.text or "").strip()
    return ""


def parse_rss(text: str, source: Source, *, fetched_at: str = "", limit: int = 15) -> list[InfoItem]:
    """RSS 2.0 ``<item>``, RSS 1.0 (RDF) ``<item>`` and Atom ``<entry>``."""
    body = str(text or "")[:MAX_BYTES].strip()
    if not body:
        return []
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        _LOG.warning("feed %s: not XML (%s)", source.id, exc)
        return []
    items: list[InfoItem] = []
    for entry in root.iter():
        if _local(entry.tag) not in ("item", "entry"):
            continue
        title = _clip(_entry_field(entry, "title"), 200)
        if not title:
            continue
        items.append(
            InfoItem(
                source_id=source.id,
                kind=source.kind,
                title=title,
                url=_entry_link(entry),
                excerpt=_clip(_entry_field(entry, "description", "summary", "encoded", "content")),
                published_at=_entry_field(entry, "pubDate", "published", "updated", "date"),
                fetched_at=fetched_at,
            )
        )
        if len(items) >= max(1, int(limit)):
            break
    return items


# ---------------------------------------------------------------------------
# JSON channels
# ---------------------------------------------------------------------------

def _json(text: str, source: Source) -> Any:
    try:
        return json.loads(str(text or "")[:MAX_BYTES])
    except json.JSONDecodeError as exc:
        _LOG.warning("feed %s: not JSON (%s)", source.id, exc)
        return None


def parse_reddit(text: str, source: Source, *, fetched_at: str = "", limit: int = 15) -> list[InfoItem]:
    payload = _json(text, source)
    children = (payload or {}).get("data", {}).get("children") if isinstance(payload, dict) else None
    if not isinstance(children, list):
        return []
    items: list[InfoItem] = []
    for child in children:
        post = child.get("data") if isinstance(child, dict) else None
        if not isinstance(post, dict):
            continue
        title = _clip(post.get("title", ""), 200)
        if not title or post.get("stickied"):
            continue
        permalink = str(post.get("permalink") or "").strip()
        outbound = str(post.get("url") or "").strip()
        excerpt = _clip(post.get("selftext", ""))
        if not excerpt:
            score = post.get("score")
            bits = [f"r/{post.get('subreddit', '')}".rstrip("/")]
            if isinstance(score, (int, float)):
                bits.append(f"{int(score)} 赞")
            if outbound and not outbound.startswith("https://www.reddit.com"):
                bits.append(outbound)
            excerpt = " · ".join(b for b in bits if b)
        items.append(
            InfoItem(
                source_id=source.id,
                kind=source.kind,
                title=title,
                url=f"https://www.reddit.com{permalink}" if permalink else outbound,
                excerpt=excerpt,
                published_at=_from_epoch(post.get("created_utc")),
                fetched_at=fetched_at,
            )
        )
        if len(items) >= max(1, int(limit)):
            break
    return items


def parse_hackernews(text: str, source: Source, *, fetched_at: str = "", limit: int = 15) -> list[InfoItem]:
    payload = _json(text, source)
    hits = payload.get("hits") if isinstance(payload, dict) else None
    if not isinstance(hits, list):
        return []
    items: list[InfoItem] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        title = _clip(hit.get("title", ""), 200)
        if not title:
            continue
        object_id = str(hit.get("objectID") or "").strip()
        url = str(hit.get("url") or "").strip() or (
            f"https://news.ycombinator.com/item?id={object_id}" if object_id else ""
        )
        excerpt = _clip(hit.get("story_text", ""))
        if not excerpt:
            points = hit.get("points")
            comments = hit.get("num_comments")
            bits = []
            if isinstance(points, (int, float)):
                bits.append(f"{int(points)} points")
            if isinstance(comments, (int, float)):
                bits.append(f"{int(comments)} comments")
            excerpt = "Hacker News · " + " · ".join(bits) if bits else "Hacker News"
        items.append(
            InfoItem(
                source_id=source.id,
                kind=source.kind,
                title=title,
                url=url,
                excerpt=excerpt,
                published_at=str(hit.get("created_at", "")).strip(),
                fetched_at=fetched_at,
            )
        )
        if len(items) >= max(1, int(limit)):
            break
    return items


def parse_weibo_hot(text: str, source: Source, *, fetched_at: str = "", limit: int = 15) -> list[InfoItem]:
    payload = _json(text, source)
    entries = (payload or {}).get("data", {}).get("realtime") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []
    items: list[InfoItem] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("is_ad"):
            continue
        word = _clip(entry.get("word", ""), 120)
        if not word:
            continue
        note = _clip(entry.get("note", ""), 120)
        heat = entry.get("num")
        bits = ["微博热搜"]
        if isinstance(heat, (int, float)):
            bits.append(f"热度 {int(heat)}")
        if note and note != word:
            bits.append(note)
        items.append(
            InfoItem(
                source_id=source.id,
                kind=source.kind,
                title=word,
                url=f"https://s.weibo.com/weibo?q={quote('#' + word + '#')}",
                excerpt=" · ".join(bits),
                fetched_at=fetched_at,
                meta={"heat": heat} if isinstance(heat, (int, float)) else {},
            )
        )
        if len(items) >= max(1, int(limit)):
            break
    return items


def parse_baidu_hot(text: str, source: Source, *, fetched_at: str = "", limit: int = 15) -> list[InfoItem]:
    payload = _json(text, source)
    cards = (payload or {}).get("data", {}).get("cards") if isinstance(payload, dict) else None
    if not isinstance(cards, list):
        return []
    items: list[InfoItem] = []
    for card in cards:
        content = card.get("content") if isinstance(card, dict) else None
        if not isinstance(content, list):
            continue
        for entry in content:
            if not isinstance(entry, dict):
                continue
            word = _clip(entry.get("word", ""), 120)
            if not word:
                continue
            desc = _clip(entry.get("desc", ""))
            items.append(
                InfoItem(
                    source_id=source.id,
                    kind=source.kind,
                    title=word,
                    url=str(entry.get("url") or "").strip() or f"https://www.baidu.com/s?wd={quote(word)}",
                    excerpt=desc or "百度热搜",
                    fetched_at=fetched_at,
                    meta={"heat": entry.get("hotScore")} if entry.get("hotScore") else {},
                )
            )
            if len(items) >= max(1, int(limit)):
                return items
    return items


def parse_bilibili_popular(
    text: str, source: Source, *, fetched_at: str = "", limit: int = 15
) -> list[InfoItem]:
    payload = _json(text, source)
    videos = (payload or {}).get("data", {}).get("list") if isinstance(payload, dict) else None
    if not isinstance(videos, list):
        return []
    items: list[InfoItem] = []
    for video in videos:
        if not isinstance(video, dict):
            continue
        title = _clip(video.get("title", ""), 200)
        if not title:
            continue
        bvid = str(video.get("bvid") or "").strip()
        owner = video.get("owner") if isinstance(video.get("owner"), dict) else {}
        desc = _clip(video.get("desc", ""))
        up_name = _clip(owner.get("name", ""), 60)
        excerpt = " · ".join(b for b in [f"UP主 {up_name}" if up_name else "", desc] if b) or "B站热门"
        items.append(
            InfoItem(
                source_id=source.id,
                kind=source.kind,
                title=title,
                url=str(video.get("short_link_v2") or "").strip()
                or (f"https://www.bilibili.com/video/{bvid}" if bvid else ""),
                excerpt=excerpt,
                published_at=_from_epoch(video.get("pubdate")),
                fetched_at=fetched_at,
            )
        )
        if len(items) >= max(1, int(limit)):
            break
    return items


def parse_page(text: str, source: Source, *, fetched_at: str = "", limit: int = 1) -> list[InfoItem]:
    """A plain HTML page as a single item: its title and the start of its body."""
    html = str(text or "")[:MAX_BYTES]
    title = extract_title(html) or source.name
    content = extract_news_main_content(html)
    excerpt = _clip(content, 600)
    if not excerpt:
        return []
    return [
        InfoItem(
            source_id=source.id,
            kind=source.kind,
            title=title[:200],
            url=source.url,
            excerpt=excerpt,
            fetched_at=fetched_at,
        )
    ]


Parser = Callable[..., list[InfoItem]]

PARSERS: dict[str, Parser] = {
    "rss": parse_rss,
    "reddit": parse_reddit,
    "hackernews": parse_hackernews,
    "weibo_hot": parse_weibo_hot,
    "baidu_hot": parse_baidu_hot,
    "bilibili_popular": parse_bilibili_popular,
    "page": parse_page,
}

_ACCEPT = (
    "application/json, application/rss+xml, application/atom+xml, application/xml, "
    "text/xml;q=0.9, text/html;q=0.8, */*;q=0.5"
)


def fetch_source(
    source: Source,
    *,
    session: GuardedSession | None = None,
    timeout: int | float = 10,
    limit: int = 15,
    now: datetime | None = None,
) -> list[InfoItem]:
    """GET the source and parse it. Never raises; failures log and yield ``[]``."""
    parser = PARSERS.get(source.channel)
    if parser is None:
        _LOG.warning("feed %s: unknown channel %r", source.id, source.channel)
        return []
    headers = {"Accept": _ACCEPT}
    if source.channel == "reddit":
        headers["User-Agent"] = REDDIT_USER_AGENT
    sess = session or get_default_session()
    try:
        resp = sess.get(source.url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        if not resp.encoding:
            resp.encoding = resp.apparent_encoding
        text = resp.text or ""
    except requests.RequestException as exc:
        _LOG.warning("feed %s: fetch failed (%s)", source.id, exc)
        return []
    try:
        return parser(text, source, fetched_at=_stamp(now), limit=limit)
    except Exception as exc:  # a feed is enrichment, never critical
        _LOG.warning("feed %s: parse failed (%s)", source.id, exc)
        return []


__all__ = [
    "MAX_BYTES",
    "PARSERS",
    "REDDIT_USER_AGENT",
    "fetch_source",
    "parse_baidu_hot",
    "parse_bilibili_popular",
    "parse_hackernews",
    "parse_page",
    "parse_reddit",
    "parse_rss",
    "parse_weibo_hot",
]
