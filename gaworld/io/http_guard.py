"""HTTP guardrails: per-host rate limit, UA rotation, failure cache.

Why this exists
---------------
The simulator's news / RAG pipeline issues many outbound HTTP requests
to a small set of hosts (Baidu, Bing, Google, Weibo, news portals…).
Without guardrails this:

* hammers a single host hundreds of times per simulated day,
* trips rate-limiters / WAFs and gets the IP banned,
* keeps retrying URLs that already returned 403 / 404 / 410 / 451
  (wasting wall-clock time on every step).

This module provides a small, dependency-free middleware layer that
sits between callers and :mod:`requests`.

Public surface
--------------

* :class:`HostRateLimiter` – minimum interval between requests to the
  same hostname.
* :class:`UserAgentRotator` – round-robin over a configurable pool.
* :class:`FailureCache` – sliding window per (URL → status) so we
  short-circuit recently-failed URLs.
* :class:`GuardedSession` – combines the above on top of
  :class:`requests.Session`.

Threading: the limiter / rotator / cache use a single :class:`RLock`
each. They are safe to share across threads (this matters when the
agent loop becomes concurrent in S3+).
"""

from __future__ import annotations

import itertools
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable, Mapping
from urllib.parse import urlparse

import requests

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.io.http_guard")


# ---------------------------------------------------------------------
# Rate limit (token-bucket-lite: minimum interval per host)
# ---------------------------------------------------------------------

class HostRateLimiter:
    """Enforce a minimum interval between requests to the same host."""

    def __init__(self, min_interval: float = 1.0, jitter: float = 0.25) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self.jitter = max(0.0, float(jitter))
        self._last: dict[str, float] = {}
        self._lock = threading.RLock()

    def wait(self, host: str) -> float:
        """Block until ``host`` is eligible for another request.

        Returns the number of seconds slept.
        """
        if not host or self.min_interval <= 0:
            return 0.0
        with self._lock:
            now = time.monotonic()
            previous = self._last.get(host)
            wait_for = 0.0
            if previous is not None:
                elapsed = now - previous
                wait_for = max(0.0, self.min_interval - elapsed)
            if self.jitter:
                wait_for += random.uniform(0.0, self.jitter)
            self._last[host] = now + wait_for
        if wait_for > 0:
            time.sleep(wait_for)
        return wait_for

    def record(self, host: str) -> None:
        """Manually mark ``host`` as just-used (for callers bypassing :meth:`wait`)."""
        if not host:
            return
        with self._lock:
            self._last[host] = time.monotonic()


# ---------------------------------------------------------------------
# UA rotation
# ---------------------------------------------------------------------

DEFAULT_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "GAWorld/1.0 (+research; contact: ops@example.com)",
)


class UserAgentRotator:
    """Round-robin over a pool of UAs to spread fingerprints across hosts."""

    def __init__(self, pool: Iterable[str] | None = None) -> None:
        agents = tuple(pool) if pool else DEFAULT_USER_AGENTS
        if not agents:
            agents = DEFAULT_USER_AGENTS
        self._cycle = itertools.cycle(agents)
        self._lock = threading.RLock()

    def next(self) -> str:
        with self._lock:
            return next(self._cycle)


# ---------------------------------------------------------------------
# Failure cache
# ---------------------------------------------------------------------

#: Synthetic status for a transport-level failure (DNS, TLS, connect, timeout).
TRANSPORT_STATUS = 599


@dataclass
class _FailureRecord:
    status: int
    expires_at: float
    reason: str = ""


@dataclass
class FailureCache:
    """Remember recently-failed URLs so we short-circuit retries.

    Different status classes have different cooldowns so e.g. a 429
    backs off briefly while a permanent 404 sits in the cache for an
    hour. A transport failure (``TRANSPORT_STATUS``) usually means the
    host is unreachable from this network — DNS hijack, blocked TLS,
    no route — which rarely clears within a minute, so it backs off for
    ten rather than re-warning on every tick.
    """

    default_ttl: float = 60.0
    permanent_ttl: float = 3600.0
    transient_ttl: float = 30.0
    transport_ttl: float = 600.0
    permanent_statuses: frozenset[int] = field(default_factory=lambda: frozenset({401, 403, 404, 410, 451}))
    transient_statuses: frozenset[int] = field(default_factory=lambda: frozenset({408, 425, 429, 500, 502, 503, 504}))
    _records: dict[str, _FailureRecord] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def is_blocked(self, url: str) -> _FailureRecord | None:
        if not url:
            return None
        with self._lock:
            record = self._records.get(url)
            if record is None:
                return None
            if record.expires_at <= time.monotonic():
                del self._records[url]
                return None
            return record

    def remember(self, url: str, status: int, reason: str = "") -> None:
        if not url:
            return
        if status in self.permanent_statuses:
            ttl = self.permanent_ttl
        elif status in self.transient_statuses:
            ttl = self.transient_ttl
        elif status == TRANSPORT_STATUS:
            ttl = self.transport_ttl
        else:
            ttl = self.default_ttl
        ttl = max(0.0, float(ttl))
        with self._lock:
            self._records[url] = _FailureRecord(
                status=int(status),
                expires_at=time.monotonic() + ttl,
                reason=reason or "",
            )

    def forget(self, url: str) -> None:
        with self._lock:
            self._records.pop(url, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)


# ---------------------------------------------------------------------
# Combined session
# ---------------------------------------------------------------------

#: host → CA bundle path, for servers that send an incomplete certificate
#: chain. Browsers and curl recover by chasing the issuer URL in the leaf;
#: ``requests`` does not, and the fetch dies with "unable to get local issuer
#: certificate". Registering a bundle that contains the missing intermediate
#: *completes* the chain — verification stays on, which is the whole point of
#: doing it this way instead of passing ``verify=False`` at the callsite.
_HOST_CA_BUNDLES: dict[str, str] = {}


def register_ca_bundle(host: str, bundle: str) -> None:
    """Use *bundle* to verify TLS for *host* on every guarded request."""
    _HOST_CA_BUNDLES[str(host or "").lower()] = str(bundle)


class GuardedSession:
    """Thin wrapper around :class:`requests.Session` enforcing the guards."""

    def __init__(
        self,
        *,
        rate_limiter: HostRateLimiter | None = None,
        ua_rotator: UserAgentRotator | None = None,
        failure_cache: FailureCache | None = None,
        session: requests.Session | None = None,
    ) -> None:
        # Use explicit `is not None` checks because :class:`FailureCache`
        # defines ``__len__``; an empty user-supplied cache would be
        # falsy under ``a or b`` and silently discarded.
        self.rate_limiter = rate_limiter if rate_limiter is not None else HostRateLimiter()
        self.ua_rotator = ua_rotator if ua_rotator is not None else UserAgentRotator()
        self.failure_cache = failure_cache if failure_cache is not None else FailureCache()
        self.session = session if session is not None else requests.Session()

    @staticmethod
    def _host(url: str) -> str:
        try:
            return (urlparse(url).hostname or "").lower()
        except (ValueError, TypeError):
            return ""

    def _merge_headers(self, headers: Mapping[str, str] | None) -> dict[str, str]:
        merged: dict[str, str] = {"User-Agent": self.ua_rotator.next()}
        if headers:
            for k, v in headers.items():
                merged[str(k)] = str(v)
        return merged

    def get(self, url: str, *, timeout: int | float = 8,
            headers: Mapping[str, str] | None = None,
            allow_redirects: bool = True) -> requests.Response:
        """Issue a GET, honouring the failure cache + rate limit + UA rotation.

        Raises :class:`requests.HTTPError` for cached failures so callers
        can tell a guard-rejection apart from a fresh transport error
        only by inspecting :attr:`requests.HTTPError.response.status_code`.
        """
        if not url:
            raise ValueError("url must be non-empty")

        # 1. Failure cache short-circuit
        blocked = self.failure_cache.is_blocked(url)
        if blocked is not None:
            _LOG.info(
                "http_guard skip url=%s status=%s reason=%s",
                url, blocked.status, blocked.reason,
            )
            resp = requests.Response()
            resp.status_code = blocked.status
            resp.url = url
            err = requests.HTTPError(
                f"http_guard cached failure: {blocked.status}", response=resp,
            )
            raise err

        # 2. Rate limit per host
        host = self._host(url)
        slept = self.rate_limiter.wait(host)
        if slept > 0.05:
            _LOG.debug("http_guard sleep host=%s slept_ms=%d", host, int(slept * 1000))

        # 3. Issue request
        merged_headers = self._merge_headers(headers)
        try:
            response = self.session.get(
                url,
                headers=merged_headers,
                timeout=timeout,
                allow_redirects=allow_redirects,
                verify=_HOST_CA_BUNDLES.get(host, True),
            )
        except requests.RequestException as exc:
            self.failure_cache.remember(url, TRANSPORT_STATUS, reason=str(exc)[:160])
            raise

        # 4. Cache failures
        if response.status_code >= 400:
            self.failure_cache.remember(
                url,
                response.status_code,
                reason=response.reason or "",
            )
        return response


# ---------------------------------------------------------------------
# Module-level shared session (lazy)
# ---------------------------------------------------------------------

_DEFAULT_SESSION_LOCK = threading.RLock()
_DEFAULT_SESSION: GuardedSession | None = None


def get_default_session() -> GuardedSession:
    """Return a process-wide :class:`GuardedSession`.

    Tests that need an isolated session should construct one directly
    rather than mutate the default.
    """
    global _DEFAULT_SESSION
    if _DEFAULT_SESSION is not None:
        return _DEFAULT_SESSION
    with _DEFAULT_SESSION_LOCK:
        if _DEFAULT_SESSION is None:
            _DEFAULT_SESSION = GuardedSession()
        return _DEFAULT_SESSION


def reset_default_session() -> None:
    """For tests: drop the shared session so the next call recreates it."""
    global _DEFAULT_SESSION
    with _DEFAULT_SESSION_LOCK:
        _DEFAULT_SESSION = None


__all__ = [
    "DEFAULT_USER_AGENTS",
    "FailureCache",
    "GuardedSession",
    "HostRateLimiter",
    "TRANSPORT_STATUS",
    "UserAgentRotator",
    "get_default_session",
    "reset_default_session",
]
