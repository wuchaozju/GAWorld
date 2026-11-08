"""Research waiting budgets never mutate shared provider configurations."""

import pytest


def test_model_waiting_scope_limits_transport_and_resets():
    from gaworld.llm import call_scope

    assert call_scope.request_timeout(600) == 600
    with call_scope.limit(20):
        connect, read = call_scope.request_timeout((10, 600))
        assert 0 < connect <= 10
        assert 0 < read <= 20
    assert call_scope.request_timeout(600) == 600


def test_expired_scope_prevents_retry_or_fallback(monkeypatch):
    from gaworld.llm import call_scope, providers

    now = [0.0]
    monkeypatch.setattr(call_scope.time, "monotonic", lambda: now[0])
    submitted = []
    with pytest.raises(call_scope.ModelWaitTimeout), call_scope.limit(1):
        now[0] = 2
        providers._retrying(lambda: submitted.append(True))
    assert submitted == []


def test_streaming_heartbeats_cannot_keep_a_call_alive_forever(monkeypatch):
    from gaworld.llm import call_scope, providers

    now = [0.0]
    monkeypatch.setattr(call_scope.time, "monotonic", lambda: now[0])

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_lines(self, **kwargs):
            now[0] = 5
            yield ""

    monkeypatch.setattr(providers, "_post", lambda *a, **kw: Response())
    with pytest.raises(call_scope.ModelWaitTimeout), call_scope.limit(1):
        providers.OllamaProvider("http://example.test", "stub").call("prompt")


def test_wait_budget_returns_even_if_provider_never_finishes_reading():
    import threading
    import time

    from gaworld.llm import call_scope

    started, release = threading.Event(), threading.Event()
    before = time.monotonic()
    try:
        with pytest.raises(call_scope.ModelWaitTimeout), call_scope.limit(0.05):
            call_scope.bounded_call(lambda: (started.set(), release.wait(5)))
        assert started.is_set()
        assert time.monotonic() - before < 1
    finally:
        release.set()


def test_bounded_model_worker_preserves_request_context():
    from contextvars import ContextVar

    from gaworld.llm import call_scope

    owner = ContextVar("test_owner", default="missing")
    token = owner.set("research-owner")
    try:
        with call_scope.limit(1):
            assert call_scope.bounded_call(owner.get) == "research-owner"
    finally:
        owner.reset(token)
