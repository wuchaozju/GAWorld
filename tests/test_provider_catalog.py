"""Cloud presets and local inference options, without real API requests."""

import json
from unittest import mock

import pytest

from gaworld.accounts.context import USER
from gaworld.apps import settings_api
from gaworld.llm import credentials
from gaworld.llm.providers import build_provider, probe_provider
from gaworld.settings.llm import llm_settings


@pytest.mark.parametrize("name", ["deepseek_flash", "deepseek_pro", "glm_5"])
@pytest.mark.parametrize("stream", [False, True])
def test_cloud_presets_use_private_key_and_compatible_payload(tmp_path, monkeypatch, name, stream):
    monkeypatch.setenv(credentials.ENV_PATH, str(tmp_path / "private" / "keys.json"))
    cfg = dict(llm_settings()["llm"]["providers"][name], stream=stream)
    assert credentials.supported(cfg)
    token = USER.set({"id": 1, "role": "member"})
    try:
        credentials.save(cfg, "private-test-key")
        provider = build_provider(cfg, attempts=1)
        response = mock.MagicMock()
        response.json.return_value = {"choices": [{"message": {"content": "OK"}}]}
        response.__enter__.return_value = response
        response.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"content":"OK"}}]}', "data: [DONE]",
        ]
        with mock.patch("gaworld.llm.providers.requests.post", return_value=response) as post:
            assert provider.call("hi", temperature=0.6, max_tokens=123) == "OK"
        args, kwargs = post.call_args
        assert args[0] == cfg["base_url"] + "/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer private-test-key"
        assert kwargs["allow_redirects"] is False
        assert kwargs["json"]["thinking"] == {"type": "disabled"}
        assert kwargs["json"]["model"] == cfg["model"]
        assert kwargs["json"]["temperature"] == 0.6
        assert kwargs["json"]["max_tokens"] == 123
        USER.set({"id": 2, "role": "member"})
        # Even the previously constructed provider cannot carry another user's key.
        assert provider.api_key is None
        with mock.patch("gaworld.llm.providers.requests.post") as post:
            assert probe_provider(cfg)["ok"] is False
            post.assert_not_called()
    finally:
        USER.reset(token)


@pytest.mark.parametrize("think", [None, False, True])
def test_ollama_context_and_thinking_are_opt_in(think):
    cfg = {"type": "ollama", "model": "qwen", "think": think}
    if think is not None:
        cfg["num_ctx"] = 65536
    provider = build_provider(cfg, attempts=1)
    response = mock.MagicMock()
    response.__enter__.return_value = response
    response.iter_lines.return_value = [json.dumps({"response": "OK", "done": True})]
    with mock.patch("gaworld.llm.providers.requests.post", return_value=response) as post:
        assert provider.call("hi", temperature=0.6, max_tokens=123) == "OK"
    payload = post.call_args.kwargs["json"]
    assert payload["options"]["num_predict"] == 123
    assert payload["options"]["temperature"] == 0.6
    if think is None:
        assert "think" not in payload
        assert "num_ctx" not in payload["options"]
    else:
        assert payload["think"] is think
        assert payload["options"]["num_ctx"] == 65536


def test_old_openai_configuration_does_not_send_thinking(monkeypatch):
    monkeypatch.delenv(credentials.ENV_PATH, raising=False)
    provider = build_provider({"type": "openai", "model": "old", "api_key": "test"})
    response = mock.Mock()
    response.json.return_value = {"choices": [{"message": {"content": "OK"}}]}
    with mock.patch("gaworld.llm.providers.requests.post", return_value=response) as post:
        assert provider.call("hi") == "OK"
    assert "thinking" not in post.call_args.kwargs["json"]


@pytest.mark.parametrize("value", ["", "  ", None])
def test_empty_probe_is_not_reported_as_success(value):
    with mock.patch("gaworld.llm.providers.OllamaProvider.call", return_value=value):
        result = probe_provider({"type": "ollama", "model": "test"})
    assert result["ok"] is False
    assert "error" in result


def test_settings_preserves_new_provider_options():
    _, cfg = settings_api._clean_provider({"name": "local", "config": {
        "type": "ollama", "url": "http://localhost:11436/api/generate", "model": "qwen",
        "think": False, "num_ctx": 65536,
    }})
    assert cfg["think"] is False
    assert cfg["num_ctx"] == 65536
    cloud = llm_settings()["llm"]["providers"]["glm_5"]
    _, cfg = settings_api._clean_provider({"name": "cloud", "config": cloud})
    assert cfg["thinking"] == "disabled"
    for patch in ({"thinking": "typo"}, {"num_ctx": 0}, {"num_ctx": -1}):
        base = cloud if "thinking" in patch else {
            "type": "ollama", "url": "http://localhost/api/generate", "model": "qwen",
        }
        with pytest.raises(ValueError):
            settings_api._clean_provider({"name": "bad", "config": dict(base, **patch)})
