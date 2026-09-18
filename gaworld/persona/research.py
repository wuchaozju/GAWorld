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
from typing import Any, Callable

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.persona.research")

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

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

    def brief(self, *, max_docs: int = 12, max_chars: int = 1400) -> str:
        """The evidence block handed to the model.

        Pages are listed before snippets regardless of the order they were
        found in: the prompt's budget is spent on the sources that actually
        carry reasoning.
        """
        ordered = sorted(self.documents, key=lambda d: 0 if d.kind == "page" else 1)
        lines: list[str] = []
        for index, doc in enumerate(ordered[:max_docs], start=1):
            body = re.sub(r"\s+", " ", doc.text).strip()
            if not (doc.title or body):
                continue
            lines.append(f"[{index}] {doc.title}（{doc.url}）\n{body[:max_chars]}")
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


def _dedupe(hits: list[dict[str, Any]], seen: set[str]) -> list[dict[str, Any]]:
    out = []
    for hit in hits:
        url = str(hit.get("url", "")).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(hit)
    return out


def research(
    subject: str,
    *,
    search_fn: Callable[[str], list[dict[str, Any]]],
    fetch_fn: Callable[[str], tuple[str, str]],
    max_queries: int = 4,
    max_pages: int = 4,
    progress: Callable[[float, str], None] | None = None,
) -> Dossier:
    """Search for *subject* and read the best hits.

    A failing search or an unreachable page is logged and skipped: a partial
    dossier still distils (into a low-confidence persona that says so), and a
    raise here would lose the documents already collected.
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
    for index, doc in enumerate(candidates[: max(0, pages_left)]):
        note(0.5 + 0.35 * (index / max(1, min(len(candidates), pages_left))), f"阅读：{doc.title[:24] or doc.url}")
        title, text = _read(fetch_fn, doc.url)
        if not text:
            continue
        doc.kind = "page"
        doc.text = text
        if title and not doc.title:
            doc.title = title

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


def default_fetch_fn(*, max_chars: int = 6000) -> Callable[[str], tuple[str, str]]:
    """``fetch_news_excerpt`` — guarded session, cleaned article body."""
    from gaworld.io.web_scrape import fetch_news_excerpt

    def fetch(url: str) -> tuple[str, str]:
        text, title = fetch_news_excerpt(url, max_chars=max_chars, return_title=True)
        return title, text

    return fetch
