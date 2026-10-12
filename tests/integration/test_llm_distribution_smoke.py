"""
Smoke tests for per-agent LLM client routing.

Verifies that ExperimentScene creates distinct LLM clients per agent
based on llm_config, and that ExperimentRunner routes calls correctly.

Contains:
    - test_llm_distribution_runtime: end-to-end round with mock dialect
    - test_llm_client_selection: verifies per-agent client routing via llm_config
    - test_llm_client_selection_via_provider_clients: verifies provider_clients priority
"""
import pytest
from fos.core.llm.client import LLMClient
from fos.core.llm_config import LLMConfig
from fos.core.experiment.scene import ExperimentScene
from fos.core.experiment.config import ExperimentConfig


@pytest.mark.asyncio
async def test_llm_distribution_runtime():
    """End-to-end round completes with per-agent mock dialect clients.

    Each agent has llm_config.dialect="mock", so the scene creates
    separate mock clients. Verifies the round completes with valid
    actions — no real API calls needed.
    """
    scene = ExperimentScene(
        ExperimentConfig(
            scenario_id="test",
            agents=[
                {"name": "Agent1", "properties": {"provider_id": 1}, "llm_config": {"dialect": "mock"}},
                {"name": "Agent2", "properties": {"provider_id": 2}, "llm_config": {"dialect": "mock"}},
            ],
            actions=[
                {"name": "cooperate", "description": "Cooperate action"},
                {"name": "defect", "description": "Defect action"},
            ],
        )
    )

    mock_client = LLMClient(LLMConfig(dialect="mock"))
    scene.initialize(mock_client)

    result = await scene.run_round(lambda event_type, data: None)

    assert result is not None
    assert result.round_num == 1
    assert len(result.actions) == 2
    for action_result in result.actions:
        assert action_result.success
        assert action_result.action_name in ["cooperate", "defect"]


@pytest.mark.asyncio
async def test_llm_client_selection():
    """Per-agent llm_config creates distinct LLM clients.

    When agents have different llm_config values, initialize() should
    create separate LLMClient instances per agent and the runner should
    route calls to the correct client.

    Routing path: scene.py lines 108-145 (llm_config fallback).
    """
    scene = ExperimentScene(
        ExperimentConfig(
            scenario_id="test",
            agents=[
                {"name": "Agent1", "properties": {}, "llm_config": {"dialect": "mock", "model": "mock-a"}},
                {"name": "Agent2", "properties": {}, "llm_config": {"dialect": "mock", "model": "mock-b"}},
            ],
            actions=[
                {"name": "cooperate", "description": "Cooperate action"},
                {"name": "defect", "description": "Defect action"},
            ],
        )
    )

    # Use a real LLMClient so _is_stub=False, triggering per-agent creation
    default_client = LLMClient(LLMConfig(dialect="mock"))
    scene.initialize(default_client)

    # Each agent gets its own client (not the default)
    assert len(scene._agent_llm_clients) == 2
    agent1_client = scene._agent_llm_clients["Agent1"]
    agent2_client = scene._agent_llm_clients["Agent2"]
    assert agent1_client is not default_client
    assert agent2_client is not default_client
    assert agent1_client is not agent2_client

    # Runner routes to the correct client per agent
    assert scene.runner.get_agent_llm_client(scene.agents[0]) is agent1_client
    assert scene.runner.get_agent_llm_client(scene.agents[1]) is agent2_client


@pytest.mark.asyncio
async def test_llm_client_selection_via_provider_clients():
    """provider_clients dict takes priority over llm_config for routing.

    When initialize() receives a provider_clients mapping, agents with
    matching provider_id values should use those clients instead of
    creating new ones from llm_config.

    Routing path: scene.py lines 97-106 (provider_clients priority).
    """
    client_a = LLMClient(LLMConfig(dialect="mock"))
    client_b = LLMClient(LLMConfig(dialect="mock"))

    scene = ExperimentScene(
        ExperimentConfig(
            scenario_id="test",
            agents=[
                {"name": "Agent1", "properties": {}, "provider_id": "provider_a", "llm_config": {"dialect": "mock"}},
                {"name": "Agent2", "properties": {}, "provider_id": "provider_b", "llm_config": {"dialect": "mock"}},
            ],
            actions=[
                {"name": "cooperate", "description": "Cooperate action"},
                {"name": "defect", "description": "Defect action"},
            ],
        )
    )

    default_client = LLMClient(LLMConfig(dialect="mock"))
    scene.initialize(
        default_client,
        provider_clients={"provider_a": client_a, "provider_b": client_b},
    )

    # provider_clients entries are used directly (not re-created)
    assert scene._agent_llm_clients["Agent1"] is client_a
    assert scene._agent_llm_clients["Agent2"] is client_b

    # Not the default
    assert scene._agent_llm_clients["Agent1"] is not default_client
    assert scene._agent_llm_clients["Agent2"] is not default_client
