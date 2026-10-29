"""
This file checks that the AI scientist analyze endpoint gives the LLM enough tokens
for a two-pass extraction (Pass A + Pass B) when using reasoning models.

Each test verifies one thing:
- test_analyze_provider_mode_has_enough_tokens_for_two_passes: max_tokens is large enough
  that a reasoning model can finish its chain-of-thought and still produce structured JSON
  output for both Pass A and Pass B without returning empty.
- test_analyze_deterministic_mode_does_not_call_llm: without a provider, no LLM call is made.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from fos.backend.api.routes import ai_scientist as route_module
from fos.core.llm_config import LLMConfig


class _FakeSessionContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeClient:
    """Fake LLM client that returns valid JSON for both passes."""

    def __init__(self) -> None:
        self.call_count = 0

    def chat(self, messages, json_mode=True) -> str:
        self.call_count += 1
        return json.dumps({
            "scenario_description": "A test scenario",
            "scenario_summary": "Test",
            "recommended_scenario_id": "public_goods",
            "recommended_scenario_reason": "test",
            "settings": [],
            "actions": [],
            "agents": [],
            "key_variables": [],
        })


@pytest.mark.asyncio
async def test_analyze_provider_mode_has_enough_tokens_for_two_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_configs: list[LLMConfig] = []

    def _capture_config(cfg: LLMConfig):
        captured_configs.append(cfg)
        return _FakeClient()

    fake_provider = SimpleNamespace(
        id=1,
        user_id=1,
        provider="openai",
        api_key="test-key",
        model="deepseek-v4-flash",
        base_url="https://api.example.com/v1",
    )

    async def _fake_user(session, token):
        return SimpleNamespace(id=1)

    async def _fake_provider(session, user_id, provider_id):
        return fake_provider

    monkeypatch.setattr(route_module, "extract_bearer_token", lambda request: "token")
    monkeypatch.setattr(route_module, "resolve_current_user", _fake_user)
    monkeypatch.setattr(route_module, "_select_provider_optional", _fake_provider)
    monkeypatch.setattr(route_module, "get_session", lambda: _FakeSessionContext())
    monkeypatch.setattr(route_module, "create_llm_client", _capture_config)

    request = SimpleNamespace(headers={})
    data = route_module.AnalyzeRequest(
        text="Participants decide whether to contribute or keep resources in a shared pool.",
        recognition_mode="provider",
    )

    result = await route_module.analyze_research_text.fn(request, data)

    assert result.used_llm is True
    assert len(captured_configs) == 1, "Expected one LLMConfig for the provider-mode analyze call"
    cfg = captured_configs[0]
    assert cfg.max_tokens >= 4096, (
        f"max_tokens={cfg.max_tokens} is too low for a two-pass LLM extraction — "
        "reasoning models need enough room for chain-of-thought plus structured JSON "
        "output in both Pass A and Pass B"
    )


@pytest.mark.asyncio
async def test_analyze_deterministic_mode_does_not_call_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_user(session, token):
        return SimpleNamespace(id=1)

    async def _fake_provider(session, user_id, provider_id):
        return None

    monkeypatch.setattr(route_module, "extract_bearer_token", lambda request: "token")
    monkeypatch.setattr(route_module, "resolve_current_user", _fake_user)
    monkeypatch.setattr(route_module, "_select_provider_optional", _fake_provider)
    monkeypatch.setattr(route_module, "get_session", lambda: _FakeSessionContext())

    request = SimpleNamespace(headers={})
    data = route_module.AnalyzeRequest(
        text="Participants decide whether to contribute or keep resources in a shared pool.",
        recognition_mode="deterministic",
    )

    result = await route_module.analyze_research_text.fn(request, data)

    assert result.used_llm is False
