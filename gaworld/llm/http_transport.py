"""Thread-owned connection pools with fresh request/session state.

Only HTTPAdapters survive a request. Cookies, auth, headers, proxies and
environment settings are prepared by a new requests Session every time, just
like requests.post. The provider remains responsible for inference retries.
"""

from __future__ import annotations

import atexit
import os
import threading
import weakref
from typing import Any

import requests
from requests.adapters import HTTPAdapter

_LOCAL = threading.local()
_POOLS: weakref.WeakSet[_ThreadPool] = weakref.WeakSet()
_LOCK = threading.Lock()


class _ThreadPool:
    def __init__(self) -> None:
        self.pid = os.getpid()
        self.closed = False
        self._policy: tuple[Any, Any, str | None] = (True, None, None)
        self.adapter = self._new_adapter()
        with _LOCK:
            _POOLS.add(self)

    @staticmethod
    def _new_adapter() -> HTTPAdapter:
        return HTTPAdapter(pool_connections=8, pool_maxsize=2, max_retries=0)

    def adapter_for(self, verify: Any, cert: Any, proxy: str | None) -> HTTPAdapter:
        policy = (verify, tuple(cert) if isinstance(cert, (list, tuple)) else cert, proxy)
        if policy != self._policy:
            # requests >=2.28 is supported. Older adapters may mutate TLS
            # settings on an existing origin pool rather than key them, so
            # never reuse their idle connections across security policies.
            # A proxy URL may carry auth; switching it must also discard the
            # adapter's otherwise-unbounded proxy_manager cache.
            self.adapter.close()
            self.adapter = self._new_adapter()
            self._policy = policy
        return self.adapter

    def close(self) -> None:
        if not self.closed and self.pid == os.getpid():
            self.closed = True
            self.adapter.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            # Interpreter/thread shutdown may already have torn down globals.
            pass


def _thread_pool() -> _ThreadPool:
    pool = getattr(_LOCAL, "pool", None)
    if pool is None or pool.closed or pool.pid != os.getpid():
        pool = _ThreadPool()
        _LOCAL.pool = pool
    return pool


class _RequestSession(requests.Session):
    def __init__(self, pool: _ThreadPool) -> None:
        super().__init__()
        # Dispose of the unused default adapters; this session does not own
        # the thread pool and must not close it on context-manager exit.
        super().close()
        self.adapters.clear()
        self._pool = pool

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        # Session.request has merged REQUESTS_CA_BUNDLE / cert / proxies by
        # this point. Redirects also pass through send with their own kwargs.
        if "proxies" not in kwargs:
            kwargs["proxies"] = requests.utils.resolve_proxies(request, self.proxies, self.trust_env)
        proxy = requests.utils.select_proxy(request.url, kwargs["proxies"])
        adapter = self._pool.adapter_for(
            kwargs.get("verify", self.verify), kwargs.get("cert", self.cert), proxy
        )
        self.mount("https://", adapter)
        self.mount("http://", adapter)
        return super().send(request, **kwargs)

    def close(self) -> None:
        self.adapters.clear()


def post(url: str, **kwargs: Any) -> requests.Response:
    """Submit a model POST using this thread's reusable adapter."""
    with _RequestSession(_thread_pool()) as session:
        return session.post(url, **kwargs)


def close_connections() -> None:
    """Release idle pools at shutdown, after request workers have stopped."""
    with _LOCK:
        pools = list(_POOLS)
    for pool in pools:
        pool.close()


def _after_fork() -> None:
    # Neither parent connections nor a mutex held by a vanished thread may
    # be used in the child. Its first request creates a new owner and lock.
    global _LOCAL, _POOLS, _LOCK
    _LOCAL = threading.local()
    _POOLS = weakref.WeakSet()
    _LOCK = threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)
atexit.register(close_connections)
