"""Minimal MCP client for the hosted X API MCP server (App-only Bearer).

X exposes a Streamable HTTP MCP server at ``https://api.x.com/mcp``
(see https://docs.x.com/tools/mcp). The "Simple — App-only Bearer"
route POSTs JSON-RPC directly to that URL with an ``Authorization:
Bearer`` header — read-only endpoints, no user context, no local xurl
bridge.

This gives simulation agents real-time access to X: :func:`x_mcp_search`
is wired into ``gaworld.sim._news.web_search`` as the ``"x"`` engine, so
both scheduled info-seeks and event-driven curiosity seeks can pull live
posts matched to each agent's interests.

Guardrails (app-only X API quotas are small, the sim loop is chatty):

* minimum interval between server calls — callers past the throttle get
  ``[]`` immediately (non-blocking) and the engine chain falls through
  to baidu/google/bing;
* per-query result cache with TTL;
* cooldown on HTTP 429, short cooldown on transport errors, hard
  disable on 401/403 (bad token) and when no search tool is found.

The server's tool names / argument schemas are discovered at runtime
via ``tools/list`` rather than hardcoded, so upstream renames degrade
to a logged disable instead of a crash.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

import requests

from gaworld.env_loader import load_env_file
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.io.x_mcp")

DEFAULT_URL = "https://api.x.com/mcp"
PROTOCOL_VERSION = "2025-06-18"
DEFAULT_BEARER_TOKEN_ENV = "X_BEARER_TOKEN"

_QUERY_ARG_KEYS = ("query", "q", "keywords", "text")
_LIMIT_ARG_KEYS = ("max_results", "maxResults", "limit", "count", "page_size", "pageSize")


class XMCPError(RuntimeError):
    """Generic MCP transport / protocol failure."""


class XMCPAuthError(XMCPError):
    """401/403 — the bearer token is missing scopes or invalid."""


class XMCPRateLimited(XMCPError):
    """429 — app-only quota exhausted."""


class XMCPClient:
    """JSON-RPC over Streamable HTTP against one X MCP endpoint."""

    def __init__(
        self,
        url: str = DEFAULT_URL,
        bearer_token: str = "",
        *,
        timeout: int = 8,
        min_interval_seconds: float = 5.0,
        cooldown_on_429_seconds: float = 900.0,
        cache_ttl_seconds: float = 900.0,
    ) -> None:
        self.url = url
        self.bearer_token = bearer_token
        self.timeout = int(timeout)
        self.min_interval = max(0.0, float(min_interval_seconds))
        self.cooldown_on_429 = max(0.0, float(cooldown_on_429_seconds))
        self.cache_ttl = max(0.0, float(cache_ttl_seconds))
        self._session = requests.Session()
        self._lock = threading.RLock()
        self._request_id = 0
        self._session_id = ""
        self._initialized = False
        self._disabled = False
        self._cooldown_until = 0.0
        self._last_call = 0.0
        self._search_tool: dict[str, Any] | None = None
        self._cache: dict[str, tuple[float, list[dict[str, str]]]] = {}

    # -- transport ----------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.bearer_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._initialized:
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        notification: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notification:
            self._request_id += 1
            payload["id"] = self._request_id
        resp = self._session.post(
            self.url, json=payload, headers=self._headers(), timeout=self.timeout
        )
        if resp.status_code in (401, 403):
            raise XMCPAuthError(f"{method}: HTTP {resp.status_code}")
        if resp.status_code == 429:
            raise XMCPRateLimited(f"{method}: HTTP 429")
        if resp.status_code >= 400:
            raise XMCPError(f"{method}: HTTP {resp.status_code}")
        session_id = resp.headers.get("Mcp-Session-Id", "")
        if session_id:
            self._session_id = session_id
        if notification:
            return {}
        content_type = resp.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            message = _parse_sse_message(resp.text, payload.get("id"))
        else:
            try:
                message = resp.json()
            except ValueError as exc:
                raise XMCPError(f"{method}: non-JSON response") from exc
        if not isinstance(message, dict):
            raise XMCPError(f"{method}: malformed response")
        if message.get("error"):
            raise XMCPError(f"{method}: {message['error']}")
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    # -- handshake ----------------------------------------------------

    def _ensure_ready(self) -> bool:
        if self._search_tool is not None:
            return True
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "gaworld", "version": "1.0"},
            },
        )
        self._initialized = True
        try:
            self._rpc("notifications/initialized", notification=True)
        except XMCPError:
            pass  # some servers reject the optional notification; not fatal
        tools = self._rpc("tools/list", {}).get("tools", [])
        self._search_tool = _pick_search_tool(tools)
        if self._search_tool is None:
            self._disabled = True
            _LOG.warning(
                "x_mcp: no post-search tool found on %s (server=%s, %d tools)",
                self.url,
                (result.get("serverInfo") or {}).get("name", "?"),
                len(tools) if isinstance(tools, list) else 0,
            )
            return False
        return True

    # -- public -------------------------------------------------------

    def search_posts(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        """Search recent posts; returns ``[{url, title, snippet}]``.

        Never raises and never blocks on the throttle — quota-guard
        misses return ``[]`` so the caller's engine chain can fall
        through to a regular web engine.
        """
        query = str(query or "").strip()
        if not query:
            return []
        now = time.monotonic()
        with self._lock:
            if self._disabled or now < self._cooldown_until:
                return []
            cached = self._cache.get(query)
            if cached and now - cached[0] < self.cache_ttl:
                return list(cached[1])
            if now - self._last_call < self.min_interval:
                return []
            # Claim the slot before the network call so concurrent
            # callers hit the throttle instead of double-spending quota.
            self._last_call = now
            try:
                if not self._ensure_ready():
                    return []
                assert self._search_tool is not None
                result = self._rpc(
                    "tools/call",
                    {
                        "name": self._search_tool.get("name", ""),
                        "arguments": self._build_arguments(query, max_results),
                    },
                )
            except XMCPAuthError as exc:
                # Live-observed: the X gateway intermittently returns 401 for
                # a token that authenticates fine minutes later, so a long
                # cooldown beats a permanent disable.
                self._cooldown_until = time.monotonic() + 3600.0
                _LOG.warning("x_mcp: auth rejected (%s), 1h cooldown", exc)
                return []
            except XMCPRateLimited:
                self._cooldown_until = time.monotonic() + self.cooldown_on_429
                _LOG.info("x_mcp: rate limited, cooling down %.0fs", self.cooldown_on_429)
                return []
            except (requests.RequestException, XMCPError) as exc:
                self._cooldown_until = time.monotonic() + 60.0
                _LOG.warning("x_mcp: call failed (%s), 60s cooldown", exc)
                return []
            # Quota errors surface inside a successful JSON-RPC response
            # (isError result with an X API problem body), e.g. 402
            # "credits depleted" — treat like a 429.
            error_status = _error_status(result)
            if error_status in (402, 429):
                self._cooldown_until = time.monotonic() + self.cooldown_on_429
                _LOG.warning(
                    "x_mcp: server reported %d (quota/credits), cooling down %.0fs",
                    error_status,
                    self.cooldown_on_429,
                )
                return []
            items = _normalize_posts(result, query=query, max_results=max_results)
            self._cache[query] = (time.monotonic(), items)
        return list(items)

    def _build_arguments(self, query: str, max_results: int) -> dict[str, Any]:
        schema = (self._search_tool or {}).get("inputSchema") or {}
        props = schema.get("properties") or {}
        query_key = next((k for k in _QUERY_ARG_KEYS if k in props), "query")
        args: dict[str, Any] = {query_key: query}
        limit_key = next((k for k in _LIMIT_ARG_KEYS if k in props), None)
        if limit_key:
            args[limit_key] = int(max_results)
        return args


# ---------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------

def _parse_sse_message(text: str, want_id: Any) -> dict[str, Any]:
    """Pick the JSON-RPC response for ``want_id`` out of an SSE body."""
    picked: dict[str, Any] = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        blob = line[len("data:"):].strip()
        if not blob:
            continue
        try:
            message = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        if want_id is None or message.get("id") == want_id:
            picked = message
    return picked


def _error_status(result: dict[str, Any]) -> int:
    """HTTP-ish status embedded in an ``isError`` tool result, or 0."""
    if not result.get("isError"):
        return 0
    parts = result.get("content")
    text = ""
    if isinstance(parts, list):
        text = "".join(
            str(part.get("text", "")) for part in parts if isinstance(part, dict)
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        return int(payload.get("status", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _pick_search_tool(tools: Any) -> dict[str, Any] | None:
    """Choose the post-search tool from ``tools/list`` output by name."""
    if not isinstance(tools, list):
        return None
    ranked: list[tuple[int, dict[str, Any]]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name", "")).lower()
        if "search" not in name:
            continue
        score = 0
        if "post" in name or "tweet" in name:
            score += 2
        if "recent" in name:
            score += 1
        if "user" in name or "doc" in name or "news" in name:
            score -= 2
        ranked.append((score, tool))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1] if ranked[0][0] > 0 else None


def _normalize_posts(
    result: dict[str, Any], *, query: str, max_results: int
) -> list[dict[str, str]]:
    """Map an MCP tool result onto the ``web_search`` result shape."""
    if result.get("isError"):
        return []
    payload = result.get("structuredContent")
    text = ""
    if not isinstance(payload, dict):
        parts = result.get("content")
        if isinstance(parts, list):
            text = "".join(
                str(part.get("text", ""))
                for part in parts
                if isinstance(part, dict) and part.get("type") == "text"
            ).strip()
        try:
            payload = json.loads(text) if text else None
        except json.JSONDecodeError:
            payload = None
    items: list[dict[str, str]] = []
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        for post in data:
            if not isinstance(post, dict):
                continue
            post_id = str(post.get("id", "")).strip()
            post_text = str(post.get("text", "")).strip()
            if not post_id or not post_text:
                continue
            items.append(
                {
                    "url": f"https://x.com/i/status/{post_id}",
                    "title": post_text[:80],
                    "snippet": post_text,
                }
            )
            if len(items) >= max(1, int(max_results)):
                break
    if not items and text:
        # Server answered with prose instead of raw API JSON — still usable.
        items.append(
            {
                "url": f"https://x.com/search?q={requests.utils.quote(query)}",
                "title": text[:80],
                "snippet": text[:2000],
            }
        )
    return items


# ---------------------------------------------------------------------
# Module-level entry point used by gaworld.sim._news.web_search
# ---------------------------------------------------------------------

_clients_lock = threading.RLock()
_clients: dict[tuple[str, str], XMCPClient] = {}


def _strip_web_operators(query: str) -> str:
    """Drop web-engine operators (``site:``…) that X search treats as noise."""
    return " ".join(
        token
        for token in str(query or "").split()
        if not token.lower().startswith("site:")
    ).strip()


def x_mcp_search(
    query: str, config: dict[str, Any] | None = None
) -> list[dict[str, str]]:
    """Search X via MCP using the ``x_mcp`` block of the info_seek config.

    Returns ``[]`` (quietly) when disabled, unconfigured, throttled, or
    on any server-side failure.
    """
    cfg = (config or {}).get("x_mcp") or {}
    if not cfg.get("enabled", True):
        return []
    token = str(cfg.get("bearer_token", "")).strip()
    if not token:
        load_env_file(".env")
        env_name = str(cfg.get("bearer_token_env", "") or DEFAULT_BEARER_TOKEN_ENV)
        token = os.getenv(env_name, "").strip()
    if not token:
        return []
    cleaned = _strip_web_operators(query)
    if not cleaned:
        return []
    url = str(cfg.get("url", "") or DEFAULT_URL)
    key = (url, token)
    with _clients_lock:
        client = _clients.get(key)
        if client is None:
            client = XMCPClient(
                url,
                token,
                timeout=int(cfg.get("timeout", 8)),
                min_interval_seconds=float(cfg.get("min_interval_seconds", 5.0)),
                cooldown_on_429_seconds=float(cfg.get("cooldown_on_429_seconds", 900.0)),
                cache_ttl_seconds=float(cfg.get("cache_ttl_seconds", 900.0)),
            )
            _clients[key] = client
    return client.search_posts(cleaned, max_results=int(cfg.get("max_results", 5)))


__all__ = [
    "DEFAULT_URL",
    "XMCPClient",
    "XMCPError",
    "XMCPAuthError",
    "XMCPRateLimited",
    "x_mcp_search",
]
