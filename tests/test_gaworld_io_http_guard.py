"""Tests for the HTTP guardrails in :mod:`gaworld.io.http_guard`."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

import requests

from gaworld.io.http_guard import (
    FailureCache,
    GuardedSession,
    HostRateLimiter,
    TRANSPORT_STATUS,
    UserAgentRotator,
    get_default_session,
    reset_default_session,
)


class TestHostRateLimiter(unittest.TestCase):
    def test_first_call_does_not_block(self):
        limiter = HostRateLimiter(min_interval=0.5, jitter=0.0)
        slept = limiter.wait("example.com")
        self.assertEqual(0.0, slept)

    def test_second_call_blocks(self):
        limiter = HostRateLimiter(min_interval=0.05, jitter=0.0)
        limiter.wait("a.example")
        start = time.monotonic()
        limiter.wait("a.example")
        elapsed = time.monotonic() - start
        # Allow generous wiggle for slow CI; should be at least near min_interval.
        self.assertGreaterEqual(elapsed, 0.03)

    def test_different_hosts_independent(self):
        limiter = HostRateLimiter(min_interval=10, jitter=0.0)
        limiter.wait("a.example")
        start = time.monotonic()
        limiter.wait("b.example")  # different host should not block
        self.assertLess(time.monotonic() - start, 0.05)


class TestUserAgentRotator(unittest.TestCase):
    def test_round_robin(self):
        pool = ["UA-1", "UA-2", "UA-3"]
        r = UserAgentRotator(pool)
        seen = [r.next() for _ in range(6)]
        self.assertEqual(["UA-1", "UA-2", "UA-3", "UA-1", "UA-2", "UA-3"], seen)

    def test_default_pool_used_when_empty(self):
        r = UserAgentRotator([])
        ua = r.next()
        self.assertTrue(isinstance(ua, str) and ua)


class TestFailureCache(unittest.TestCase):
    def test_remembers_within_ttl(self):
        cache = FailureCache(default_ttl=10, permanent_ttl=10, transient_ttl=10)
        cache.remember("https://x", 404, reason="Not Found")
        rec = cache.is_blocked("https://x")
        self.assertIsNotNone(rec)
        self.assertEqual(404, rec.status)
        self.assertIn("Not Found", rec.reason)

    def test_forgets_after_ttl(self):
        cache = FailureCache(default_ttl=0.05, permanent_ttl=0.05, transient_ttl=0.05)
        cache.remember("https://y", 503)
        time.sleep(0.08)
        self.assertIsNone(cache.is_blocked("https://y"))

    def test_classification_chooses_ttl(self):
        cache = FailureCache(default_ttl=1, permanent_ttl=10, transient_ttl=2)
        cache.remember("https://a", 404)
        cache.remember("https://b", 429)
        cache.remember("https://c", 418)
        rec_a = cache.is_blocked("https://a")
        rec_b = cache.is_blocked("https://b")
        rec_c = cache.is_blocked("https://c")
        self.assertGreater(rec_a.expires_at, rec_b.expires_at)
        self.assertGreaterEqual(rec_b.expires_at, rec_c.expires_at - 0.5)

    def test_transport_failure_backs_off_longer_than_default(self):
        cache = FailureCache(default_ttl=1, transport_ttl=30)
        cache.remember("https://unreachable", TRANSPORT_STATUS)
        cache.remember("https://teapot", 418)
        rec_transport = cache.is_blocked("https://unreachable")
        rec_default = cache.is_blocked("https://teapot")
        self.assertGreater(rec_transport.expires_at, rec_default.expires_at)


class TestGuardedSession(unittest.TestCase):
    def setUp(self):
        reset_default_session()

    def tearDown(self):
        reset_default_session()

    def _make_response(self, status=200, body="ok", headers=None):
        resp = requests.Response()
        resp.status_code = status
        resp._content = body.encode("utf-8")
        resp.headers["content-type"] = (headers or {}).get("content-type", "text/plain")
        resp.url = "https://example.com/x"
        resp.encoding = "utf-8"
        return resp

    def test_short_circuits_cached_failure(self):
        cache = FailureCache(default_ttl=10, permanent_ttl=10, transient_ttl=10)
        cache.remember("https://x.example/", 404)
        sess = GuardedSession(failure_cache=cache, session=MagicMock())
        with self.assertRaises(requests.HTTPError) as ctx:
            sess.get("https://x.example/")
        self.assertEqual(404, ctx.exception.response.status_code)
        sess.session.get.assert_not_called()

    def test_records_failure_on_4xx(self):
        cache = FailureCache(default_ttl=10, permanent_ttl=10, transient_ttl=10)
        mock_session = MagicMock()
        mock_session.get.return_value = self._make_response(status=403, body="Forbidden")
        sess = GuardedSession(
            failure_cache=cache,
            session=mock_session,
            rate_limiter=HostRateLimiter(min_interval=0, jitter=0),
        )
        resp = sess.get("https://y.example/x")
        self.assertEqual(403, resp.status_code)
        self.assertIsNotNone(cache.is_blocked("https://y.example/x"))

    def test_records_transport_failure(self):
        cache = FailureCache(default_ttl=10, permanent_ttl=10, transient_ttl=10)
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.ConnectionError("boom")
        sess = GuardedSession(
            failure_cache=cache,
            session=mock_session,
            rate_limiter=HostRateLimiter(min_interval=0, jitter=0),
        )
        with self.assertRaises(requests.ConnectionError):
            sess.get("https://z.example/x")
        rec = cache.is_blocked("https://z.example/x")
        self.assertIsNotNone(rec)
        self.assertEqual(599, rec.status)

    def test_get_default_session_is_singleton(self):
        a = get_default_session()
        b = get_default_session()
        self.assertIs(a, b)
        reset_default_session()
        c = get_default_session()
        self.assertIsNot(a, c)


if __name__ == "__main__":
    unittest.main()
