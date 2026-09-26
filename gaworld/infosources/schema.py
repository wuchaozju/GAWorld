"""Typed information sources — what a resident can read from outside the city.

Before this package the outside world was one flat list of homepage URLs
(``data/news_source.md``): every resident drew from the same bag, a homepage
scrape was the only way in, and "social media" meant fetching ``x.com`` and
getting a "JavaScript is not available" page back. A source here carries three
things the flat list could not:

``kind``
    *news* / *social* / *professional* — the channel a resident would describe
    themselves as using ("刷微博" / "看新闻" / "读行业站"). It is what the memory
    entry records and what a media diet weighs.
``channel``
    How the bytes are obtained and parsed (RSS/Atom, Reddit's public JSON, the
    Hacker News API, Weibo's hot-search endpoint, a plain page…). Parsing lives
    in :mod:`gaworld.infosources.channels`; the registry only names it.
``topics``
    Chinese domain tags (科技 / 医疗 / 财经 / 教育 …) that
    :mod:`gaworld.infosources.diet` matches against a resident's job and
    interests. This is what makes a community doctor read WHO and a programmer
    read Hacker News without anyone hand-assigning sources to people.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

KINDS: tuple[str, ...] = ("news", "social", "professional")

KIND_LABELS_ZH: dict[str, str] = {
    "news": "新闻",
    "social": "社交媒体",
    "professional": "专业网站",
}

#: Parser names understood by :func:`gaworld.infosources.channels.fetch_source`.
CHANNELS: tuple[str, ...] = (
    "rss",  # RSS 2.0 / RSS 1.0 (RDF) / Atom — also the arXiv API
    "reddit",  # https://www.reddit.com/r/<sub>/hot.json
    "hackernews",  # https://hn.algolia.com/api/v1/search?tags=front_page
    "weibo_hot",  # https://weibo.com/ajax/side/hotSearch
    "baidu_hot",  # https://top.baidu.com/api/board?platform=wise&tab=realtime
    "bilibili_popular",  # https://api.bilibili.com/x/web-interface/popular
    "page",  # any HTML page: title + main content as one item
)


def _domain_of(url: str) -> str:
    try:
        host = (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


@dataclass(frozen=True)
class Source:
    """One place a resident may read from. Immutable: the registry is data."""

    id: str
    name: str
    kind: str
    channel: str
    url: str
    topics: tuple[str, ...] = ()
    lang: str = "zh"
    weight: float = 1.0
    enabled: bool = True

    @property
    def domain(self) -> str:
        return _domain_of(self.url)

    @property
    def kind_label(self) -> str:
        return KIND_LABELS_ZH.get(self.kind, self.kind)

    @classmethod
    def from_dict(cls, raw: Any) -> Source:
        """Build from one registry entry; raises ``ValueError`` on a bad one."""
        if not isinstance(raw, dict):
            raise ValueError("source entry must be an object")
        source_id = str(raw.get("id", "")).strip()
        url = str(raw.get("url", "")).strip()
        kind = str(raw.get("kind", "")).strip().lower()
        channel = str(raw.get("channel", "rss")).strip().lower()
        if not source_id:
            raise ValueError("source needs an id")
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"source {source_id!r}: url must be http(s)")
        if kind not in KINDS:
            raise ValueError(f"source {source_id!r}: kind must be one of {KINDS}")
        if channel not in CHANNELS:
            raise ValueError(f"source {source_id!r}: channel must be one of {CHANNELS}")
        topics_raw = raw.get("topics") or ()
        if isinstance(topics_raw, str):
            topics_raw = topics_raw.replace("，", ",").split(",")
        topics = tuple(str(t).strip() for t in topics_raw if str(t).strip())
        try:
            weight = float(raw.get("weight", 1.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"source {source_id!r}: weight must be a number") from exc
        return cls(
            id=source_id,
            name=str(raw.get("name", "") or source_id).strip(),
            kind=kind,
            channel=channel,
            url=url,
            topics=topics,
            lang=str(raw.get("lang", "zh") or "zh").strip().lower(),
            weight=max(0.0, weight),
            enabled=bool(raw.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "channel": self.channel,
            "url": self.url,
            "topics": list(self.topics),
            "lang": self.lang,
            "weight": self.weight,
            "enabled": self.enabled,
        }


@dataclass
class InfoItem:
    """One thing that was published somewhere: a headline, a post, a paper."""

    source_id: str
    kind: str
    title: str
    url: str = ""
    excerpt: str = ""
    published_at: str = ""
    fetched_at: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Dedupe key: the URL when there is one, else the title."""
        return self.url or f"title:{self.title}"

    def text(self, *, max_chars: int = 240) -> str:
        body = f"{self.title}：{self.excerpt}" if self.excerpt else self.title
        return body[: max(0, int(max_chars))]

    def to_dict(self) -> dict[str, Any]:
        out = {
            "source_id": self.source_id,
            "kind": self.kind,
            "title": self.title,
            "url": self.url,
            "excerpt": self.excerpt,
            "published_at": self.published_at,
            "fetched_at": self.fetched_at,
        }
        if self.meta:
            out["meta"] = dict(self.meta)
        return out

    @classmethod
    def from_dict(cls, raw: Any) -> InfoItem | None:
        if not isinstance(raw, dict):
            return None
        title = str(raw.get("title", "")).strip()
        if not title:
            return None
        meta = raw.get("meta")
        return cls(
            source_id=str(raw.get("source_id", "")).strip(),
            kind=str(raw.get("kind", "")).strip(),
            title=title,
            url=str(raw.get("url", "")).strip(),
            excerpt=str(raw.get("excerpt", "")).strip(),
            published_at=str(raw.get("published_at", "")).strip(),
            fetched_at=str(raw.get("fetched_at", "")).strip(),
            meta=dict(meta) if isinstance(meta, dict) else {},
        )


__all__ = ["CHANNELS", "KINDS", "KIND_LABELS_ZH", "InfoItem", "Source"]
