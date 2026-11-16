"""
This file checks that the provider test endpoint creates LLM configs with enough tokens.

Each test verifies one thing:
- test_provider_test_gives_reasoning_models_enough_tokens: max_tokens is large enough that
  a reasoning model can finish thinking and still produce visible output.
- test_provider_test_config_matches_expected_dialect: the dialect is correctly normalized.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from fos.backend.api.routes import providers as route_module
from fos.core.llm_config import LLMConfig
import os
pytestmark = pytest.mark.skipif(\
    not os.environ.get("FOS_TEST_LIVE_PROVIDER"),\
    reason="requires running LLM provider (set FOS_TEST_LIVE_PROVIDER=1 to enable)"\
)


class _FakeSession:
    """Fake async session that returns a provider owned by user 1."""

    def __init__(self, provider) -> None:
        self._provider = provider

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, model_cls, pk):
        return self._provider

    async def commit(self):
        pass


def _make_provider(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=1,
        user_id=1,
        provider="openai",
        api_key="test-key",
        model="deepseek-v4-flash",
        base_url="https://api.example.com/v1",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_provider_test_gives_reasoning_models_enough_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_configs: list[LLMConfig] = []

    def _capture_config(cfg: LLMConfig):
        captured_configs.append(cfg)
        mock_client = MagicMock()
        mock_client.chat.return_value = "pong"
        return mock_client

    provider = _make_provider()
    fake_session = _FakeSession(provider)

    async def _fake_user(session, token):
        return SimpleNamespace(id=1)

    monkeypatch.setattr(route_module, "extract_bearer_token", lambda request: "token")
    monkeypatch.setattr(route_module, "resolve_current_user", _fake_user)
    monkeypatch.setattr(route_module, "get_session", lambda: fake_session)
    monkeypatch.setattr(route_module, "create_llm_client", _capture_config)

    request = SimpleNamespace(headers={})
    await route_module.test_provider.fn(request, provider_id=1)

    assert len(captured_configs) == 1, "Expected exactly one LLMConfig to be created"
    cfg = captured_configs[0]
    assert cfg.max_tokens >= 512, (
        f"max_tokens={cfg.max_tokens} is too low — reasoning models need headroom after "
        "their chain-of-thought to produce visible output"
    )


@pytest.mark.asyncio
async def test_provider_test_config_matches_expected_dialect(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_configs: list[LLMConfig] = []

    def _capture_config(cfg: LLMConfig):
        captured_configs.append(cfg)
        mock_client = MagicMock()
        mock_client.chat.return_value = "ok"
        return mock_client

    provider = _make_provider(provider="ollama", base_url="http://localhost:11434")
    fake_session = _FakeSession(provider)

    async def _fake_user(session, token):
        return SimpleNamespace(id=1)

    monkeypatch.setattr(route_module, "extract_bearer_token", lambda request: "token")
    monkeypatch.setattr(route_module, "resolve_current_user", _fake_user)
    monkeypatch.setattr(route_module, "get_session", lambda: fake_session)
    monkeypatch.setattr(route_module, "create_llm_client", _capture_config)

    request = SimpleNamespace(headers={})
    await route_module.test_provider.fn(request, provider_id=1)

    assert len(captured_configs) == 1
    assert captured_configs[0].dialect == "ollama"
