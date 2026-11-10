"""A per-call seed reaches the provider that can honour it.

The replication tab lets a researcher pin a seed and expects the same study to
come out the same way. The seed controls *who* answers and *how the answers are
grouped*; whether the model's own sampling is reproducible depends on the
provider. An OpenAI-compatible endpoint and an Ollama server both accept a
seed in the request body, so the runner forwards one. The Anthropic Messages
API has no such parameter, so there the seed stays out of the request and the
run says so instead of pretending.

What we defend:

* ``call_llm(seed=...)`` reaches the provider payload (OpenAI-compatible and
  Ollama), and is omitted entirely when no seed is given;
* the Anthropic backend does not invent a parameter the API does not accept;
* a provider-shaped object whose ``call`` takes only the prompt still works —
  a seed must not break the test doubles that stand in for a model.
"""

from __future__ import annotations

import json

import pytest

from gaworld.llm import providers


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = json.dumps(payload)
        self.content = self.text.encode()

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def clean_connections():
    from gaworld.llm.http_transport import close_connections

    yield
    close_connections()


def test_openai_puts_the_seed_in_the_payload(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        captured["payload"] = json
        return _Response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(providers, "http_post", fake_post)
    provider = providers.OpenAIProvider("http://x/v1", "gpt-4o", api_key="k", attempts=1)
    provider.call("纯文本", seed=146)
    assert captured["payload"]["seed"] == 146


def test_openai_without_a_seed_sends_no_seed(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        captured["payload"] = json
        return _Response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(providers, "http_post", fake_post)
    provider = providers.OpenAIProvider("http://x/v1", "gpt-4o", api_key="k", attempts=1)
    provider.call("纯文本")
    assert "seed" not in captured["payload"]


def test_ollama_puts_the_seed_in_the_options(monkeypatch):
    captured = {}

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode=False):
            yield json.dumps({"response": "ok", "done": True})

    def fake_post(url, json=None, timeout=None, stream=None, **kwargs):
        captured["payload"] = json
        return _Stream()

    monkeypatch.setattr(providers, "http_post", fake_post)
    provider = providers.OllamaProvider("http://x/api/generate", "gemma3:4b", attempts=1)
    provider.call("纯文本", seed=146)
    assert captured["payload"]["options"]["seed"] == 146


def test_anthropic_does_not_invent_a_seed_parameter(monkeypatch):
    """The Anthropic Messages API accepts no seed; sending one would be a
    rejected request, not a reproducible one."""
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        captured["payload"] = json
        return _Response({"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"})

    monkeypatch.setattr(providers, "http_post", fake_post)
    provider = providers.AnthropicProvider("http://x", "claude-sonnet-5", api_key="k", attempts=1)
    provider.call("纯文本", seed=146)
    assert "seed" not in captured["payload"]


def test_a_provider_that_takes_only_the_prompt_still_works(monkeypatch):
    """A model stand-in whose ``call`` takes the prompt alone must not be broken
    by a seed it cannot accept."""

    class Bare:
        def call(self, prompt):
            return "ok"

    router = providers.LLM_ROUTER
    monkeypatch.setitem(router.providers, "bare", Bare())
    monkeypatch.setattr(router, "_resolve_chain", lambda **kwargs: ["bare"])
    assert router.call("问题", seed=146) == "ok"


def test_call_llm_forwards_the_seed(monkeypatch):
    captured = {}

    def fake_call(prompt, **kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(providers.LLM_ROUTER, "call", fake_call)
    providers.call_llm("问题", task="research.replication.answer", seed=146)
    assert captured["seed"] == 146


def test_call_llm_without_a_seed_does_not_forward_one(monkeypatch):
    captured = {}

    def fake_call(prompt, **kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(providers.LLM_ROUTER, "call", fake_call)
    providers.call_llm("问题", task="research.replication.answer")
    assert "seed" not in captured
