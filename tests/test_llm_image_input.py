"""Image input across the three provider wire formats.

Each provider encodes images differently, and getting it wrong fails at the
endpoint rather than here — so the payload shape is asserted directly. The
requests layer is stubbed; nothing in this file talks to a network.
"""

from __future__ import annotations

import json

import pytest

from gaworld.llm import providers


@pytest.fixture
def image():
    # "hello" in base64 — content is irrelevant, only the plumbing is tested.
    return [{"media_type": "image/png", "data": "aGVsbG8="}]


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.headers = {"content-type": "application/json"}
        self.text = json.dumps(payload)

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_openai_sends_a_data_url_image_part(monkeypatch, image):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        captured["payload"] = json
        return _Response({"choices": [{"message": {"content": "看到了"}}]})

    monkeypatch.setattr(providers.requests, "post", fake_post)
    provider = providers.OpenAIProvider("http://x/v1", "gpt-4o", api_key="k", attempts=1)
    assert provider.call("这是什么", images=image) == "看到了"

    content = captured["payload"]["messages"][-1]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "这是什么"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == "data:image/png;base64,aGVsbG8="


def test_openai_without_images_keeps_the_plain_string_content(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        captured["payload"] = json
        return _Response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(providers.requests, "post", fake_post)
    provider = providers.OpenAIProvider("http://x/v1", "gpt-4o", api_key="k", attempts=1)
    provider.call("纯文本")
    assert captured["payload"]["messages"][-1]["content"] == "纯文本"


def test_anthropic_puts_the_image_block_before_the_text(monkeypatch, image):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        captured["payload"] = json
        return _Response({"content": [{"type": "text", "text": "看到了"}], "stop_reason": "end_turn"})

    monkeypatch.setattr(providers.requests, "post", fake_post)
    provider = providers.AnthropicProvider("http://x", "claude-sonnet-5", api_key="k", attempts=1)
    assert provider.call("这是什么", images=image) == "看到了"

    content = captured["payload"]["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"] == {
        "type": "base64",
        "media_type": "image/png",
        "data": "aGVsbG8=",
    }
    assert content[-1] == {"type": "text", "text": "这是什么"}


def test_ollama_sends_bare_base64_without_the_data_url_prefix(monkeypatch, image):
    captured = {}

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode=False):
            yield json.dumps({"response": "看到了", "done": True})

    def fake_post(url, json=None, timeout=None, stream=None, **kwargs):
        captured["payload"] = json
        return _Stream()

    monkeypatch.setattr(providers.requests, "post", fake_post)
    provider = providers.OllamaProvider("http://x/api/generate", "gemma3:4b", attempts=1)
    assert provider.call("这是什么", images=image) == "看到了"
    assert captured["payload"]["images"] == ["aGVsbG8="]


def test_malformed_image_entries_are_dropped_not_forwarded(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        captured["payload"] = json
        return _Response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(providers.requests, "post", fake_post)
    provider = providers.OpenAIProvider("http://x/v1", "gpt-4o", api_key="k", attempts=1)
    provider.call("q", images=[{"media_type": "image/png"}, "not-a-dict", {"data": ""}])
    # Nothing usable survived, so the content must stay a plain string rather
    # than becoming a one-element list with no image in it.
    assert captured["payload"]["messages"][-1]["content"] == "q"


def test_vision_capability_follows_the_explicit_config_flag():
    assert providers.OpenAIProvider("http://x/v1", "some-text-model", vision=True).supports_images
    assert not providers.OpenAIProvider("http://x/v1", "gpt-4o", vision=False).supports_images


def test_vision_capability_falls_back_to_the_model_name():
    assert providers.OpenAIProvider("http://x/v1", "gpt-4o").supports_images
    assert providers.AnthropicProvider("http://x", "claude-opus-5").supports_images
    assert providers.OllamaProvider("http://x", "qwen2.5-vl:7b").supports_images
    assert not providers.OllamaProvider("http://x", "qwen3.5:9b").supports_images


def test_router_forwards_images_only_when_present():
    class Recorder:
        def __init__(self):
            self.kwargs = None

        def call(self, prompt, **kwargs):
            self.kwargs = kwargs
            return "ok"

    recorder = Recorder()
    router = providers.LLMRouter.__new__(providers.LLMRouter)
    router.providers = {"r": recorder}
    router.routing = {"default": "r"}
    router.config = {}

    router.call("q")
    assert recorder.kwargs == {}

    router.call("q", images=[{"media_type": "image/png", "data": "aGVsbG8="}])
    assert recorder.kwargs["images"] == [{"media_type": "image/png", "data": "aGVsbG8="}]


def test_provider_shaped_double_without_images_kwarg_still_works():
    """A test double whose ``call`` takes the prompt alone must keep working."""

    class Legacy:
        def call(self, prompt):
            return "ok"

    router = providers.LLMRouter.__new__(providers.LLMRouter)
    router.providers = {"r": Legacy()}
    router.routing = {"default": "r"}
    router.config = {}
    assert router.call("q") == "ok"
