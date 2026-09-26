"""Collect what the open web says about one person.

Two entry shapes, one output:

``name``  four facet queries (履历 / 观点 / 决策 / 近况) go to the search engine,
          the top hits are opened and read in full.
``URL``   the page is read first; its title supplies the name, and the same
          facet queries then run on that name so a single homepage or profile
          page is not the only evidence.

Why read the pages instead of trusting snippets: a search snippet is ~120
characters chosen by the engine to match the query, which is enough to tell you
a page exists and nowhere near enough to distil how somebody thinks. Fetching
costs a few seconds per page and goes through :mod:`gaworld.io.http_guard`, so
the rate limiting and failure caching that protect the news pipeline protect
this too.

Nothing here talks to a model. :func:`research` takes ``search_fn`` and
``fetch_fn`` as parameters — the caller wires in the real ones, tests wire in
fakes, and an offline run degrades to whatever the callables could return
rather than raising.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from collections.abc import Sequence
from typing import Any, Callable
from urllib.parse import urlparse

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.persona.research")

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

#: Click-tracking wrappers a scraped result page is full of. Bing's ``/ck/a``
#: links in particular come back with plausible titles attached to whatever the
#: page's chrome was advertising — a query for a Chinese author returned four
#: Microsoft product pages and, on a second run, four dance videos. Handing
#: those to the model produced the worst possible outcome: it correctly judged
#: the material unrelated to the subject and the panel reported "the material
#: is about someone else", which blames the query for a broken scrape.
#:
#: Baidu's ``link?url=`` is deliberately **not** here: it is a real result, and
#: following the redirect lands on the real page. Those hits arrive with an
#: empty snippet, so they are only worth anything once read in full.
_JUNK_URL_PATTERNS: tuple[str, ...] = (
    "bing.com/ck/",
    "google.com/url?",
    "duckduckgo.com/l/",
    "r.search.yahoo.com",
    "so.com/link?",
)

#: Wikipedia, queried through its API rather than scraped. It is the one
#: key-free source that reliably answers "who is this person" with prose
#: instead of a result page, which is exactly what this pipeline needs before
#: it can distil anything. Tried in order; an unreachable host is skipped.
WIKI_HOSTS: tuple[str, ...] = ("zh.wikipedia.org", "en.wikipedia.org")

#: One query per facet, in the order they matter for a *resident*: who they are
#: comes before what they think, because a persona with no biography cannot be
#: placed in a city. Four is a deliberate ceiling — each is a live search and
#: distillation is already an interactive 30-90s operation.
SEARCH_FACETS: tuple[str, ...] = (
    "{name} 简历 经历 背景",
    "{name} 观点 主张 访谈",
    "{name} 决策 争议 事件",
    "{name} 最新 近况",
)

#: Titles come back with the site name glued on ("张三 - 维基百科, 自由的百科全书").
#: Cutting at the first separator recovers the subject often enough to be worth
#: the three lines; when it does not, the operator can type the name instead.
_TITLE_SPLIT = re.compile(r"\s*[|｜\-–—_·]\s+|\s+[-–—]\s+")


def is_url(subject: str) -> bool:
    return bool(_URL_RE.match(str(subject or "").strip()))


def name_from_title(title: str) -> str:
    """Best-effort subject name out of an HTML ``<title>``."""
    head = _TITLE_SPLIT.split(str(title or "").strip(), maxsplit=1)[0]
    return head.strip()[:40]


@dataclass
class Document:
    """One piece of evidence: a page that was read, or a snippet that was not."""

    title: str
    url: str
    text: str
    kind: str = "snippet"  # page | snippet
    query: str = ""

    def as_source(self) -> dict[str, str]:
        return {"title": self.title[:120], "url": self.url, "kind": self.kind}


@dataclass
class Dossier:
    """Everything the research pass found, before any model has seen it."""

    subject: str
    name: str
    mode: str = "name"  # name | url
    documents: list[Document] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not any(doc.text.strip() for doc in self.documents)

    @property
    def page_count(self) -> int:
        return sum(1 for doc in self.documents if doc.kind == "page")

    def sources(self, limit: int = 12) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for doc in self.documents:
            if not doc.url or any(s["url"] == doc.url for s in out):
                continue
            out.append(doc.as_source())
            if len(out) >= limit:
                break
        return out

    def brief(self, *, max_docs: int = 12, total_chars: int = 9000, max_per_doc: int = 6000) -> str:
        """The evidence block handed to the model.

        Pages are listed before snippets regardless of the order they were
        found in: the prompt's budget is spent on the sources that actually
        carry reasoning.

        The budget is a **total**, split across whatever was found, rather than
        a fixed cap per document. With a flat per-document cap, the common case
        — one good encyclopedia article and nothing else — reached the model as
        its opening paragraph, which is biography. The distillation then had
        nothing to build a mental model out of and correctly returned none.
        """
        ordered = sorted(self.documents, key=lambda d: 0 if d.kind == "page" else 1)
        usable = [doc for doc in ordered[:max_docs] if doc.title or doc.text.strip()]
        if not usable:
            return ""
        per_doc = min(max_per_doc, max(600, total_chars // len(usable)))
        lines: list[str] = []
        for index, doc in enumerate(usable, start=1):
            body = re.sub(r"\s+", " ", doc.text).strip()
            lines.append(f"[{index}] {doc.title}（{doc.url}）\n{body[:per_doc]}")
        return "\n\n".join(lines)

    def to_markdown(self) -> str:
        """The archived research file — one section per document, verbatim."""
        head = f"# {self.name} · 调研素材\n\n- 输入：{self.subject}\n- 模式：{self.mode}\n"
        if self.queries:
            head += "- 检索式：\n" + "".join(f"  - {q}\n" for q in self.queries)
        blocks = []
        for doc in self.documents:
            blocks.append(
                f"\n## {doc.title or '(无标题)'}\n\n"
                f"- 来源：{doc.url}\n- 类型：{'全文' if doc.kind == 'page' else '摘要'}\n\n"
                f"{doc.text.strip()}\n"
            )
        return head + "".join(blocks)


def is_junk_url(url: str) -> bool:
    """True for a search engine's own click-tracking / chrome links."""
    lowered = str(url or "").lower()
    return any(pattern in lowered for pattern in _JUNK_URL_PATTERNS)


def _is_relevant(doc: Document, keywords: Sequence[str]) -> bool:
    """True when *doc* mentions at least one of *keywords*.

    Deliberately an OR over title and body rather than a score: the documents
    this is meant to remove do not mention the subject's domain *at all*, so
    anything cleverer would only add ways to drop a real source.
    """
    haystack = f"{doc.title}\n{doc.text}"
    return any(word and word in haystack for word in keywords)


def _dedupe(hits: list[dict[str, Any]], seen: set[str]) -> list[dict[str, Any]]:
    out = []
    for hit in hits:
        url = str(hit.get("url", "")).strip()
        if not url or url in seen:
            continue
        if is_junk_url(url):
            _LOG.debug("persona research: dropping engine chrome %s", url[:80])
            continue
        seen.add(url)
        out.append(hit)
    return out


def research(
    subject: str,
    *,
    search_fn: Callable[[str], list[dict[str, Any]]],
    fetch_fn: Callable[[str], tuple[str, str]],
    wiki_fn: Callable[[str], Document | None] | None = None,
    keywords: Sequence[str] | None = None,
    max_queries: int = 4,
    max_pages: int = 4,
    progress: Callable[[float, str], None] | None = None,
) -> Dossier:
    """Search for *subject* and read the best hits.

    A failing search or an unreachable page is logged and skipped: a partial
    dossier still distils (into a low-confidence persona that says so), and a
    raise here would lose the documents already collected.

    ``wiki_fn`` is consulted first when given. The engines are scraped HTML and
    degrade badly — blocked, empty, or answering with their own chrome — so the
    pipeline should not depend on them for the one thing it cannot proceed
    without: prose about the subject.

    ``keywords`` is an optional relevance gate: a document is kept only if one
    of them appears in its title or body. :data:`_JUNK_URL_PATTERNS` catches an
    engine's *click wrappers*, but not its ad slots — a search for one Hong
    Kong legislator came back with four 4399 flash-game pages and three video
    portals, all fetched successfully, all counted as full-text evidence. They
    cost three things at once: the ``brief`` budget that should have gone to
    the encyclopedia article, an ``evidence_pages`` count that promoted the
    persona to "high confidence", and seven pages of noise in the prompt.
    Default ``None`` keeps the old behaviour, because a general subject has no
    term every genuine source must contain — the caller who knows one says so.
    """
    subject = str(subject or "").strip()
    if not subject:
        raise ValueError("a name or URL is required")

    def note(fraction: float, message: str) -> None:
        if progress:
            progress(fraction, message)

    url_mode = is_url(subject)
    dossier = Dossier(subject=subject, name="" if url_mode else subject, mode="url" if url_mode else "name")
    seen: set[str] = set()
    pages_left = max(0, int(max_pages))

    if url_mode:
        note(0.05, "读取页面…")
        seen.add(subject)
        title, text = _read(fetch_fn, subject)
        if text or title:
            dossier.documents.append(Document(title=title, url=subject, text=text, kind="page"))
            pages_left -= 1
        dossier.name = name_from_title(title) or subject
        _LOG.info("persona research: %s → subject %r", subject, dossier.name)

    if dossier.name and wiki_fn is not None:
        note(0.08, "查百科…")
        try:
            entry = wiki_fn(dossier.name)
        except Exception as exc:  # noqa: BLE001 — an unreachable encyclopedia is not fatal
            _LOG.warning("persona wiki lookup failed for %r: %s", dossier.name, exc)
            entry = None
        if entry is not None and entry.url not in seen:
            seen.add(entry.url)
            dossier.documents.append(entry)

    if dossier.name:
        queries = [facet.format(name=dossier.name) for facet in SEARCH_FACETS[:max_queries]]
        for index, query in enumerate(queries):
            note(0.1 + 0.4 * (index / max(1, len(queries))), f"检索：{query}")
            try:
                hits = search_fn(query) or []
            except Exception as exc:  # noqa: BLE001 — one dead engine must not end the run
                _LOG.warning("persona search failed for %r: %s", query, exc)
                continue
            dossier.queries.append(query)
            for hit in _dedupe(list(hits), seen):
                dossier.documents.append(
                    Document(
                        title=str(hit.get("title", "")).strip(),
                        url=str(hit.get("url", "")).strip(),
                        text=str(hit.get("snippet") or hit.get("excerpt") or "").strip(),
                        kind="snippet",
                        query=query,
                    )
                )

    # Read the most promising snippets in full, newest facet last so the budget
    # is not spent entirely on the biography query.
    candidates = [doc for doc in dossier.documents if doc.kind == "snippet" and doc.url]
    if keywords:
        # A stable partition, not a drop: a title that names the subject's
        # domain is worth a fetch before one that does not, but a genuine page
        # titled with nothing but the person's name must still get its turn.
        # Without this the four-page budget is spent on the ad slots that sit
        # above the real results, and the filter below then discards all four.
        candidates.sort(key=lambda doc: 0 if _is_relevant(doc, keywords) else 1)
    for index, doc in enumerate(candidates[: max(0, pages_left)]):
        note(0.5 + 0.35 * (index / max(1, min(len(candidates), pages_left))), f"阅读：{doc.title[:24] or doc.url}")
        title, text = _read(fetch_fn, doc.url)
        if not text:
            continue
        doc.kind = "page"
        doc.text = text
        if title and not doc.title:
            doc.title = title

    # A hit whose snippet was empty and whose page would not load carries a
    # title and nothing else. Keeping it would inflate the evidence count the
    # panel shows and put a bare headline in front of the model as if it were
    # material. (Baidu returns its results as redirect links with no snippet,
    # so this is the common case, not an edge one.)
    dossier.documents = [doc for doc in dossier.documents if doc.text.strip()]

    if keywords:
        kept = [doc for doc in dossier.documents if _is_relevant(doc, keywords)]
        dropped = len(dossier.documents) - len(kept)
        if dropped:
            _LOG.info("persona research: dropped %d off-topic document(s) for %r", dropped, dossier.name)
        dossier.documents = kept

    note(0.9, f"素材 {len(dossier.documents)} 条（全文 {dossier.page_count} 篇）")
    return dossier


def _read(fetch_fn: Callable[[str], tuple[str, str]], url: str) -> tuple[str, str]:
    try:
        title, text = fetch_fn(url)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("persona fetch failed for %s: %s", url, exc)
        return "", ""
    return str(title or "").strip(), str(text or "").strip()


# ---------------------------------------------------------------------------
# Default wiring (the simulator's own search + scraper)
# ---------------------------------------------------------------------------

def default_search_fn(config: dict[str, Any] | None = None) -> Callable[[str], list[dict[str, Any]]]:
    """``web_search`` from the news pipeline, bound to the news config."""
    from gaworld.sim._news import web_search

    def search(query: str) -> list[dict[str, Any]]:
        _engine, results = web_search(query, config=config or {})
        return results

    return search


def default_wiki_fn(*, max_chars: int = 6000, timeout: int = 10) -> Callable[[str], Document | None]:
    """Look *name* up in Wikipedia and return its article as one document.

    Uses the MediaWiki API, not the rendered page: it resolves a free-form name
    to an article, follows redirects, and hands back plain text — no scraping,
    no key, and a clean miss (empty search result) for somebody who has no
    article, which is information in itself.
    """
    import json as _json
    from urllib.parse import urlencode

    import requests

    from gaworld.io.http_guard import get_default_session

    def _api_url(host: str, **params: Any) -> str:
        # GuardedSession.get takes a URL, not `params` — the query string is
        # built here so the call still goes through the rate limit, the UA
        # rotation and the failure cache.
        return f"https://{host}/w/api.php?" + urlencode({"format": "json", **params})

    def lookup(name: str) -> Document | None:
        session = get_default_session()
        query = str(name or "").strip()
        if not query:
            return None
        for host in WIKI_HOSTS:
            try:
                found = session.get(
                    _api_url(host, action="query", list="search", srsearch=query, srlimit=1),
                    timeout=timeout,
                ).json()
                hits = (found.get("query") or {}).get("search") or []
                if not hits:
                    _LOG.info("no %s article for %r", host, query)
                    continue
                title = hits[0]["title"]
                page = session.get(
                    _api_url(host, action="query", prop="extracts", explaintext=1,
                             redirects=1, titles=title),
                    timeout=timeout,
                ).json()
                pages = (page.get("query") or {}).get("pages") or {}
                extract = next(iter(pages.values()), {}).get("extract") or ""
            # Narrow on purpose: a blocked host or a changed payload is a
            # normal "try the next language", but a TypeError here is a bug in
            # this function and must not be reported to the operator as "this
            # person has no article" — which is exactly what a bare `except
            # Exception` did when the call signature was wrong.
            except (requests.RequestException, _json.JSONDecodeError, KeyError, AttributeError) as exc:
                _LOG.warning("wiki lookup on %s failed for %r: %s", host, query, exc)
                continue
            if not extract.strip():
                continue
            return Document(
                title=f"{title}（{host}）",
                url=f"https://{host}/wiki/{title.replace(' ', '_')}",
                text=extract[:max_chars],
                kind="page",
                query="wikipedia",
            )
        return None

    return lookup


def default_fetch_fn(*, max_chars: int = 6000) -> Callable[[str], tuple[str, str]]:
    """``fetch_news_excerpt`` — guarded session, cleaned article body."""
    from gaworld.io.web_scrape import fetch_news_excerpt

    def fetch(url: str) -> tuple[str, str]:
        text, title = fetch_news_excerpt(url, max_chars=max_chars, return_title=True)
        return title, text

    return fetch
