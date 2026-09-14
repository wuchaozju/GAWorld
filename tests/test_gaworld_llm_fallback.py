"""Tests for the LLM cross-provider fallback chain."""

from __future__ import annotations

import unittest

from gaworld.llm.providers import (
    AnthropicProvider,
    EmptyCompletionError,
    LLMRouter,
    OpenAIProvider,
)


class _StubProvider:
    def __init__(self, name: str, *, fail: bool = False, reply: str | None = None):
        self.name = name
        self.fail = fail
        self.reply = reply
        self.calls = 0

    def call(self, prompt: str) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"{self.name} simulated failure")
        if self.reply is not None:
            return self.reply
        return f"hello from {self.name}"


def _make_router(routing, providers):
    router = object.__new__(LLMRouter)
    router.providers = providers
    router.routing = routing
    router.config = {}
    return router


class TestFallbackChain(unittest.TestCase):
    def test_primary_succeeds_no_fallback_used(self):
        a = _StubProvider("a")
        b = _StubProvider("b")
        router = _make_router({"default": "a", "fallback": ["b"]}, {"a": a, "b": b})
        out = router.call("hi")
        self.assertEqual("hello from a", out)
        self.assertEqual(1, a.calls)
        self.assertEqual(0, b.calls)

    def test_primary_fails_fallback_succeeds(self):
        a = _StubProvider("a", fail=True)
        b = _StubProvider("b")
        router = _make_router({"default": "a", "fallback": ["b"]}, {"a": a, "b": b})
        out = router.call("hi")
        self.assertEqual("hello from b", out)
        self.assertEqual(1, a.calls)
        self.assertEqual(1, b.calls)

    def test_all_fail_raises_last_exception(self):
        a = _StubProvider("a", fail=True)
        b = _StubProvider("b", fail=True)
        router = _make_router({"default": "a", "fallback": ["b"]}, {"a": a, "b": b})
        with self.assertRaises(RuntimeError) as ctx:
            router.call("hi")
        self.assertIn("b simulated", str(ctx.exception))

    def test_fallback_string_value_is_normalized_to_list(self):
        a = _StubProvider("a", fail=True)
        b = _StubProvider("b")
        router = _make_router({"default": "a", "fallback": "b"}, {"a": a, "b": b})
        self.assertEqual("hello from b", router.call("hi"))

    def test_unknown_fallback_name_is_skipped(self):
        a = _StubProvider("a")
        router = _make_router({"default": "a", "fallback": ["nonexistent"]}, {"a": a})
        # Primary works; nonexistent silently dropped, no exception.
        self.assertEqual("hello from a", router.call("hi"))

    def test_task_routing_overrides_default(self):
        a = _StubProvider("a")
        b = _StubProvider("b")
        c = _StubProvider("c")
        router = _make_router(
            {"default": "a", "tasks": {"plan": "b"}, "fallback": ["c"]},
            {"a": a, "b": b, "c": c},
        )
        self.assertEqual("hello from b", router.call("hi", task="plan"))
        self.assertEqual(0, a.calls)
        self.assertEqual(1, b.calls)
        self.assertEqual(0, c.calls)


class _OverrideStub:
    """A provider that accepts the per-call overrides and records them."""

    def __init__(self):
        self.kwargs = None

    def call(self, prompt, system=None, temperature=None):
        self.kwargs = {"system": system, "temperature": temperature}
        return "ok"


class TestPerCallOverrides(unittest.TestCase):
    """``system`` / ``temperature`` reach the provider only when requested."""

    def test_overrides_are_forwarded(self):
        stub = _OverrideStub()
        router = _make_router({"default": "a"}, {"a": stub})
        router.call("hi", system="你是顾客", temperature=1.0)
        self.assertEqual({"system": "你是顾客", "temperature": 1.0}, stub.kwargs)

    def test_fallback_can_be_disabled_to_pin_one_model(self):
        # An experiment must fail a cell rather than answer it with a
        # different model than the neighbouring cells.
        a = _StubProvider("a", fail=True)
        b = _StubProvider("b")
        router = _make_router({"default": "a", "fallback": ["b"]}, {"a": a, "b": b})
        with self.assertRaises(RuntimeError):
            router.call("hi", allow_fallback=False)
        self.assertEqual(1, a.calls)
        self.assertEqual(0, b.calls)

    def test_no_overrides_means_the_prompt_alone(self):
        # Providers predating the override kwargs must keep working, so an
        # unset override may not be forwarded as an explicit ``None``.
        legacy = _StubProvider("legacy")
        router = _make_router({"default": "a"}, {"a": legacy})
        self.assertEqual("hello from legacy", router.call("hi"))


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class TestEmptyCompletionIsAnError(unittest.TestCase):
    """A blank completion must never reach callers as a successful result.

    Callers write the returned string straight into artifacts and JSON
    parsers, so a silent "" degrades into empty files and bogus defaults.
    """

    def test_empty_primary_falls_back_to_next_provider(self):
        a = _StubProvider("a", reply="   \n ")
        b = _StubProvider("b")
        router = _make_router({"default": "a", "fallback": ["b"]}, {"a": a, "b": b})
        self.assertEqual("hello from b", router.call("hi"))
        self.assertEqual(1, a.calls)
        self.assertEqual(1, b.calls)

    def test_all_providers_empty_raises(self):
        a = _StubProvider("a", reply="")
        b = _StubProvider("b", reply="")
        router = _make_router({"default": "a", "fallback": ["b"]}, {"a": a, "b": b})
        with self.assertRaises(EmptyCompletionError):
            router.call("hi")

    def test_reasoning_only_response_reports_exhausted_budget(self):
        provider = AnthropicProvider(
            "https://example.invalid",
            "MiniMax-M2.7",
            api_key="k",
            max_tokens=512,
        )
        payload = {
            "stop_reason": "max_tokens",
            "content": [{"type": "thinking", "thinking": "weighing the options"}],
        }
        import gaworld.llm.providers as providers

        original_post = providers.requests.post
        providers.requests.post = lambda *a, **kw: _FakeResponse(payload)
        try:
            with self.assertRaises(EmptyCompletionError) as ctx:
                provider.call("hi")
        finally:
            providers.requests.post = original_post
        message = str(ctx.exception)
        self.assertIn("max_tokens", message)
        self.assertIn("thinking", message)

    def test_text_block_is_returned_normally(self):
        provider = AnthropicProvider(
            "https://example.invalid",
            "MiniMax-M2.7",
            api_key="k",
            max_tokens=16384,
        )
        payload = {
            "stop_reason": "end_turn",
            "content": [
                {"type": "thinking", "thinking": "weighing the options"},
                {"type": "text", "text": "# 报告"},
            ],
        }
        import gaworld.llm.providers as providers

        original_post = providers.requests.post
        providers.requests.post = lambda *a, **kw: _FakeResponse(payload)
        try:
            self.assertEqual("# 报告", provider.call("hi"))
        finally:
            providers.requests.post = original_post


class TestOpenAIPayloadOverrides(unittest.TestCase):
    """The system message and temperature must reach the wire correctly."""

    def _capture(self, provider, **kwargs):
        import gaworld.llm.providers as providers

        captured = {}

        def _post(*_args, **request_kwargs):
            captured.update(request_kwargs["json"])
            return _FakeResponse(
                {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
            )

        original_post = providers.requests.post
        providers.requests.post = _post
        try:
            provider.call("hi", **kwargs)
        finally:
            providers.requests.post = original_post
        return captured

    def test_system_message_is_prepended(self):
        provider = OpenAIProvider("https://example.invalid/v1", "m", api_key="k")
        payload = self._capture(provider, system="你是顾客")
        self.assertEqual(
            [{"role": "system", "content": "你是顾客"}, {"role": "user", "content": "hi"}],
            payload["messages"],
        )

    def test_call_temperature_beats_the_provider_default(self):
        provider = OpenAIProvider("https://example.invalid/v1", "m", api_key="k", temperature=0.2)
        self.assertEqual(1.0, self._capture(provider, temperature=1.0)["temperature"])
        self.assertEqual(0.2, self._capture(provider)["temperature"])

    def test_without_a_system_message_the_payload_is_unchanged(self):
        provider = OpenAIProvider("https://example.invalid/v1", "m", api_key="k")
        payload = self._capture(provider)
        self.assertEqual([{"role": "user", "content": "hi"}], payload["messages"])
        self.assertNotIn("temperature", payload)


if __name__ == "__main__":
    unittest.main()
