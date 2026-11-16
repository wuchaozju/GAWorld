from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from litestar.exceptions import HTTPException

from fos.backend.api.routes import ai_scientist as route_module
from fos.backend.services.runtime_tasks import RUNTIME_TASKS


class _FakeSessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeClient:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self._payloads = payloads
        self._index = 0

    def chat(self, messages: list[dict[str, str]], json_mode: bool = True) -> str:
        assert json_mode is True
        payload = self._payloads[self._index]
        self._index += 1
        return json.dumps(payload)


@pytest.mark.asyncio
async def test_ai_scientist_route_allows_deterministic_mode_without_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    RUNTIME_TASKS.clear()

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
        text="Participants decide whether to contribute or keep resources in a shared pool."
    )

    result = await route_module.analyze_research_text.fn(request, data)

    assert result.used_llm is False
    assert result.model_used is None
    assert result.recommended_scenario_id in {"public_goods", "custom"}
    assert any("deterministic" in item.lower() for item in result.warnings)
    snapshot = RUNTIME_TASKS.snapshot()
    assert snapshot["active"] == 0
    assert snapshot["recent"][0]["kind"] == "ai_scientist_analysis"
    assert snapshot["recent"][0]["status"] == "finished"
    RUNTIME_TASKS.clear()


@pytest.mark.asyncio
async def test_ai_scientist_route_provider_mode_requires_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    RUNTIME_TASKS.clear()

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
        recognition_mode="provider",
    )

    with pytest.raises(HTTPException) as exc:
        await route_module.analyze_research_text.fn(request, data)

    assert exc.value.status_code == 400
    assert "Configure an LLM provider" in str(exc.value.detail)
    snapshot = RUNTIME_TASKS.snapshot()
    assert snapshot["active"] == 0
    assert snapshot["recent"][0]["kind"] == "ai_scientist_analysis"
    assert snapshot["recent"][0]["status"] == "error"
    RUNTIME_TASKS.clear()


@pytest.mark.asyncio
async def test_ai_scientist_route_uses_multi_pass_model_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_user(session, token):
        return SimpleNamespace(id=1)

    async def _fake_provider(session, user_id, provider_id):
        assert provider_id == 99
        return SimpleNamespace(
            provider="openai",
            api_key="test-key",
            model="mock-gpt",
            base_url="https://example.invalid",
            config={"active": True},
        )

    monkeypatch.setattr(route_module, "extract_bearer_token", lambda request: "token")
    monkeypatch.setattr(route_module, "resolve_current_user", _fake_user)
    monkeypatch.setattr(route_module, "_select_provider_optional", _fake_provider)
    monkeypatch.setattr(route_module, "get_session", lambda: _FakeSessionContext())
    monkeypatch.setattr(
        route_module,
        "create_llm_client",
        lambda cfg: _FakeClient(
            [
                {
                    "scenario_summary": "A repeated contribution study with a shared pool.",
                    "participants": [{"label": "participants", "description": "Group members", "count": 4}],
                    "actions": [{"name": "contribute", "description": "Put tokens into the shared pool."}],
                    "setting_candidates": [{"key": "tokens_per_round", "value": "20", "reason": "stated directly"}],
                    "key_variables": ["contribution level"],
                    "interaction_structure_hint": "shared_target_threshold",
                    "payoff_rules": ["Each participant receives 20 tokens and the shared pool is multiplied."],
                    "constraints": [],
                    "information_structure": [],
                    "interaction_topology": [],
                    "assumptions": [],
                    "missing_information": [],
                    "evidence_by_field": {
                        "participants": ["four participants received 20 tokens each round"],
                        "actions": ["participants decide whether to contribute or keep tokens"],
                    },
                    "candidate_template_judgment": [{"id": "public_goods", "fit": 0.88, "reason": "shared pool contribution structure"}],
                },
                {
                    "scenario_description": "A repeated public-pool contribution game.",
                    "settings": [{"key": "tokens_per_round", "value": "20", "reason": "explicit in the source"}],
                    "actions": [{"name": "1 Introduction", "description": "noise from the document header"}],
                    "agents": [{"label": "Smith et al. 2020 Journal of Something", "description": "noise", "count": 1}],
                    "key_variables": ["contribution level"],
                    "assumptions": [],
                    "missing_information": [],
                    "evidence": [],
                    "evidence_by_field": {"actions": ["participants decide whether to contribute or keep tokens"]},
                    "recommended_scenario_id": "public_goods",
                    "recommended_scenario_reason": "The source describes a repeated shared-pool contribution game.",
                    "recommendation_confidence": 0.78,
                    "review_required": False,
                    "recommended_params": {"tokens_per_round": 20},
                    "source_sections": [{"id": "abstract", "title": "Abstract", "excerpt": "Participants decide whether to contribute or keep tokens.", "page": 1}],
                },
                {
                    "scenario_description": "A repeated public-pool contribution game.",
                    "settings": [{"key": "tokens_per_round", "value": "20", "reason": "explicit in the source"}],
                    "actions": [{"name": "contribute", "description": "Put tokens into the shared pool."}],
                    "agents": [{"label": "participants", "description": "Group members", "count": 4}],
                    "key_variables": ["contribution level"],
                    "assumptions": [],
                    "missing_information": [],
                    "evidence": [{"label": "Action", "snippet": "participants decide whether to contribute or keep tokens", "section": "Abstract"}],
                    "evidence_by_field": {
                        "actions": ["participants decide whether to contribute or keep tokens"],
                        "participants": ["four participants received 20 tokens each round"],
                    },
                    "recommended_scenario_id": "public_goods",
                    "recommended_scenario_reason": "The source explicitly describes a shared contribution pool.",
                    "recommendation_confidence": 0.84,
                    "review_required": False,
                    "recommended_params": {"tokens_per_round": 20},
                    "source_sections": [{"id": "abstract", "title": "Abstract", "excerpt": "Participants decide whether to contribute or keep tokens.", "page": 1}],
                },
            ]
        ),
    )

    request = SimpleNamespace(headers={})
    data = route_module.AnalyzeRequest(
        text=(
            "Abstract\nParticipants receive 20 tokens each round and decide whether to contribute to a shared pool "
            "or keep tokens in a private account."
        ),
        recognition_mode="provider",
        provider_id=99,
    )

    result = await route_module.analyze_research_text.fn(request, data)

    assert result.used_llm is True
    assert result.model_used == "mock-gpt"
    assert result.recommended_scenario_id == "public_goods"
    assert result.actions[0].name == "Contribute"
    assert result.agents[0].label == "participants"
    assert result.evidence_by_field["actions"]
    assert any("repair pass" in item.lower() for item in result.warnings)


@pytest.mark.asyncio
async def test_ai_scientist_route_reextracts_single_field_deterministically(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(route_module, "extract_bearer_token", lambda request: "token")

    request = SimpleNamespace(headers={})
    data = route_module.ReextractFieldRequest(
        text=(
            "Abstract\nParticipants receive 20 tokens each round and decide whether to contribute to a shared pool "
            "or keep tokens in a private account."
        ),
        field="actions",
        language="en",
    )

    result = await route_module.reextract_research_field.fn(request, data)

    assert result.field == "actions"
    assert result.actions
    assert result.actions[0].name in {"Contribute", "Keep"}
    assert result.evidence
