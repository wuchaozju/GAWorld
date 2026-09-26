"""Search providers beyond scraping result pages.

``gaworld.sim._news.web_search`` used to know three engines, all of them regex
over Google / Baidu / Bing HTML — pages that are rendered for browsers, change
without notice and answer a bare ``requests`` client with a consent wall or a
captcha more often than with results. These providers return structured data:

``ddg``
    DuckDuckGo's HTML endpoint. No key, tolerant of plain HTTP clients, and its
    markup is stable enough to parse. The keyless default.
``brave``
    Brave Search API (``BRAVE_SEARCH_API_KEY``). JSON, generous free tier.
``tavily``
    Tavily (``TAVILY_API_KEY``). JSON, built for LLM agents, returns page
    content alongside the snippet so a fetch can often be skipped.

Every provider returns the ``[{url, title, snippet}]`` shape the news pipeline
already consumes, and an unconfigured key means ``[]`` — the engine chain then
falls through, exactly like the ``x`` engine.
"""

from __future__ import annotations

import os
import re
from html import unescape
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse

import requests

from gaworld.env_loader import load_env_file
from gaworld.io.http_guard import GuardedSession, get_default_session
from gaworld.io.web_scrape import normalize_text, strip_html
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.infosources.search")

DDG_URL = "https://html.duckduckgo.com/html/"
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
TAVILY_URL = "https://api.tavily.com/search"

DEFAULT_BRAVE_KEY_ENV = "BRAVE_SEARCH_API_KEY"
DEFAULT_TAVILY_KEY_ENV = "TAVILY_API_KEY"

API_ENGINES: tuple[str, ...] = ("ddg", "duckduckgo", "brave", "tavily")

_DDG_RESULT = re.compile(r'(?is)<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>')
_DDG_SNIPPET = re.compile(r'(?is)<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>')


def _ddg_target(href: str) -> str:
    """``//duckduckgo.com/l/?uddg=<url>&rut=…`` → ``<url>``; direct links pass through."""
    href = str(href or "").strip()
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in (parsed.netloc or "") and parsed.path.startswith("/l/"):
        # parse_qs percent-decodes the value once; decoding it again would
        # corrupt targets that carry their own encoded query strings.
        return (parse_qs(parsed.query).get("uddg") or [""])[0].strip()
    return href if href.startswith("http") else ""


def parse_ddg_results(html_text: str, max_results: int = 5) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    snippets = [normalize_text(strip_html(s)) for s in _DDG_SNIPPET.findall(html_text or "")]
    for index, (href, anchor) in enumerate(_DDG_RESULT.findall(html_text or "")):
        url = _ddg_target(unescape(href))
        title = normalize_text(strip_html(anchor))
        if not url or len(title) < 4:
            continue
        snippet = snippets[index] if index < len(snippets) else ""
        results.append({"url": url, "title": title, "snippet": snippet})
        if len(results) >= max(1, int(max_results)):
            break
    return results


def ddg_search(
    query: str, *, max_results: int = 5, timeout: int | float = 8, session: GuardedSession | None = None
) -> list[dict[str, str]]:
    sess = session or get_default_session()
    url = f"{DDG_URL}?q={quote_plus(query)}&kl=cn-zh"
    try:
        resp = sess.get(url, timeout=timeout, headers={"Accept": "text/html"})
        resp.raise_for_status()
        return parse_ddg_results(resp.text or "", max_results=max_results)
    except requests.RequestException as exc:
        _LOG.warning("ddg search failed for %r: %s", query, exc)
        return []


def _key_from_env(cfg: dict[str, Any], key_name: str, default_env: str) -> str:
    load_env_file(".env")
    env_name = str(cfg.get(key_name, "") or default_env)
    return os.getenv(env_name, "").strip()


def brave_search(
    query: str,
    *,
    api_key: str,
    max_results: int = 5,
    timeout: int | float = 8,
    session: GuardedSession | None = None,
) -> list[dict[str, str]]:
    if not api_key:
        return []
    sess = session or get_default_session()
    url = f"{BRAVE_URL}?q={quote_plus(query)}&count={max(1, int(max_results))}"
    try:
        resp = sess.get(
            url,
            timeout=timeout,
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        _LOG.warning("brave search failed for %r: %s", query, exc)
        return []
    rows = (payload.get("web") or {}).get("results") if isinstance(payload, dict) else None
    results: list[dict[str, str]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url", "")).strip()
        title = normalize_text(strip_html(str(row.get("title", ""))))
        if not url.startswith("http") or not title:
            continue
        snippet = normalize_text(strip_html(str(row.get("description", ""))))
        results.append({"url": url, "title": title, "snippet": snippet})
        if len(results) >= max(1, int(max_results)):
            break
    return results


def tavily_search(
    query: str, *, api_key: str, max_results: int = 5, timeout: int | float = 8
) -> list[dict[str, str]]:
    if not api_key:
        return []
    body = {
        "api_key": api_key,
        "query": query,
        "max_results": max(1, int(max_results)),
        "search_depth": "basic",
    }
    try:
        resp = requests.post(
            TAVILY_URL,
            json=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        _LOG.warning("tavily search failed for %r: %s", query, exc)
        return []
    rows = payload.get("results") if isinstance(payload, dict) else None
    results: list[dict[str, str]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url", "")).strip()
        title = normalize_text(strip_html(str(row.get("title", ""))))
        if not url.startswith("http") or not title:
            continue
        snippet = normalize_text(strip_html(str(row.get("content", ""))))[:2000]
        results.append({"url": url, "title": title, "snippet": snippet})
        if len(results) >= max(1, int(max_results)):
            break
    return results


def api_search(engine: str, query: str, *, config: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Dispatch one of :data:`API_ENGINES` using the ``info_seek`` config block."""
    cfg = config or {}
    api_cfg = cfg.get("search_api") or {}
    max_results = int(cfg.get("max_results", 4))
    timeout = int(cfg.get("timeout", 8))
    name = str(engine or "").lower()
    if name in ("ddg", "duckduckgo"):
        return ddg_search(query, max_results=max_results, timeout=timeout)
    if name == "brave":
        key = _key_from_env(api_cfg, "brave_api_key_env", DEFAULT_BRAVE_KEY_ENV)
        return brave_search(query, api_key=key, max_results=max_results, timeout=timeout)
    if name == "tavily":
        key = _key_from_env(api_cfg, "tavily_api_key_env", DEFAULT_TAVILY_KEY_ENV)
        return tavily_search(query, api_key=key, max_results=max_results, timeout=timeout)
    return []


__all__ = [
    "API_ENGINES",
    "BRAVE_URL",
    "DDG_URL",
    "TAVILY_URL",
    "api_search",
    "brave_search",
    "ddg_search",
    "parse_ddg_results",
    "tavily_search",
]
