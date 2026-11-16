"""
Test fixtures for core experiment tests.

Provides reusable fixtures for:
- Mock LLM client with configurable responses
- Agent factory for creating test agents
- Paired history builder for paired mode tests
"""

import pytest
from unittest.mock import Mock

from fos.core.experiment.agent import ExperimentAgent
from fos.core.llm_config import LLMConfig


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client with configurable JSON responses.

    Returns:
        Mock client with chat() method that returns valid JSON by default.
    """
    client = Mock()
    client.chat = Mock(return_value='{"reasoning": "I choose to cooperate", "action": "cooperate"}')
    client.config = LLMConfig(dialect="mock")
    return client


@pytest.fixture
def make_agent():
    """Factory function for creating test agents.

    Returns:
        Function that creates ExperimentAgent instances with defaults.
    """
    def _agent(
        name: str = "TestAgent",
        properties: dict | None = None,
        role_prompt: str | None = None,
        llm_config: LLMConfig | None = None
    ) -> ExperimentAgent:
        """Create a test agent with sensible defaults.

        Args:
            name: Agent display name
            properties: Demographic properties (defaults to adult person)
            role_prompt: Optional role-specific prompt
            llm_config: LLM configuration (defaults to mock)

        Returns:
            ExperimentAgent instance
        """
        if properties is None:
            properties = {"age_group": "adult", "profession": "person"}
        if llm_config is None:
            llm_config = LLMConfig(dialect="mock")

        return ExperimentAgent(
            name=name,
            properties=properties,
            llm_config=llm_config,
            role_prompt=role_prompt
        )

    return _agent


@pytest.fixture
def make_paired_history():
    """Factory function for creating paired round history.

    Returns:
        Function that creates mock round history for paired mode testing.
    """
    def _history(
        agent_pairs: list[tuple[str, str]],
        rounds: int = 3,
        actions: list[str] | None = None
    ) -> list[dict]:
        """Create mock round history for paired mode.

        Args:
            agent_pairs: List of (agent1, agent2) tuples for each pair
            rounds: Number of rounds to generate
            actions: List of action names to cycle through (default: cooperate, defect)

        Returns:
            List of round dicts with 'round' and 'actions' keys
        """
        if actions is None:
            actions = ["cooperate", "defect"]

        history = []
        action_idx = 0

        for round_num in range(1, rounds + 1):
            round_actions = []
            for agent1, agent2 in agent_pairs:
                # Each agent in the pair takes an action
                round_actions.append({
                    "agent": agent1,
                    "action": actions[action_idx % len(actions)]
                })
                round_actions.append({
                    "agent": agent2,
                    "action": actions[(action_idx + 1) % len(actions)]
                })
                action_idx += 1

            history.append({
                "round": round_num,
                "actions": round_actions
            })

        return history

    return _history
