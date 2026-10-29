"""
Coverage tests for ExperimentRunner — prompt building, JSON parsing,
turn loop, follow-up modes, and round result contents.

Focuses on paths NOT already covered by test_runner.py.

Contains: TestRunnerCoverage (~16 tests)
"""

import asyncio
from typing import Literal

import pytest
from unittest.mock import Mock

from fos.core.experiment.runner import ExperimentRunner
from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import GameConfig, PRISONERS_DILEMMA
from fos.core.experiment.information_model import InformationModel
from fos.core.experiment.controller import ActionResult
from fos.core.llm_config import LLMConfig


# --- Helpers ---


def _mock_llm_client(response='{"action": "cooperate"}'):
    """Create a mock LLM client with configurable response."""
    client = Mock()
    client.chat = Mock(return_value=response)
    return client


def _make_agents(names=("Alice", "Bob")):
    """Create test agents."""
    return [
        ExperimentAgent(name=n, properties={}, llm_config=LLMConfig(dialect="mock"))
        for n in names
    ]


def _make_runner(
    agents=None,
    game_config=None,
    llm_client=None,
    round_visibility: Literal["simultaneous", "sequential", "random", "paired"] = "simultaneous",
    information_model=None,
    **kwargs,
):
    """Create an ExperimentRunner with sensible defaults."""
    return ExperimentRunner(
        agents=agents or _make_agents(),
        game_config=game_config or PRISONERS_DILEMMA,
        llm_client=llm_client or _mock_llm_client(),
        round_visibility=round_visibility,
        information_model=information_model or InformationModel(scope_type="all"),
        **kwargs,
    )


def _make_non_pairwise_game_config() -> GameConfig:
    """Create a simple game where every agent should act each round."""
    return GameConfig(
        name="group_test_game",
        description="A simple test game for turn order checks.",
        action_type="discrete",
        actions=["cooperate", "defect"],
        action_descriptions={"cooperate": "Cooperate", "defect": "Defect"},
        grouping_mode="group",
        payoff_type="none",
    )


# --- Prompt Building ---


class TestPromptBuilding:
    """Verify prompt content includes agent and game data."""

    def test_agent_name_appears_in_prompt(self):
        """The prompt sent to the LLM contains the agent's name."""
        agents = _make_agents()
        client = _mock_llm_client()
        runner = _make_runner(agents=agents, llm_client=client)

        asyncio.run(runner._prompt_agent(agents[0], round_num=1))

        # Check the chat call was made and prompt contains agent name
        call_args = client.chat.call_args
        messages = call_args[0][0]
        prompt_text = messages[0]["content"]
        assert "Alice" in prompt_text

    def test_action_list_appears_in_prompt(self):
        """The prompt contains the available actions."""
        agents = _make_agents()
        client = _mock_llm_client()
        runner = _make_runner(agents=agents, llm_client=client)

        asyncio.run(runner._prompt_agent(agents[0], round_num=1))

        call_args = client.chat.call_args
        messages = call_args[0][0]
        prompt_text = messages[0]["content"]
        assert "cooperate" in prompt_text
        assert "defect" in prompt_text

    def test_history_included_in_prompt_after_first_round(self):
        """After round 1, round 2 prompts include history context."""
        agents = _make_agents()
        client = _mock_llm_client()
        runner = _make_runner(agents=agents, llm_client=client)

        # Run round 1
        asyncio.run(runner.run(max_rounds=1))

        # Reset mock to track the next call
        client.chat.reset_mock()

        # Run round 2
        asyncio.run(runner._prompt_agent(agents[0], round_num=2))

        call_args = client.chat.call_args
        prompt_text = call_args[0][0][0]["content"]
        # Round 2 context should reference the previous round
        assert "cooperate" in prompt_text or "Round" in prompt_text


# --- JSON Parsing ---


class TestJsonParsing:
    """Verify LLM response parsing and fallback behavior."""

    def test_valid_json_action_parsed_correctly(self):
        """Valid JSON with a known action is parsed to the correct action_name."""
        agents = _make_agents(["Solo"])
        client = _mock_llm_client('{"reasoning": "trust", "action": "cooperate"}')
        runner = _make_runner(agents=agents, llm_client=client)

        result = asyncio.run(runner._prompt_agent(agents[0], round_num=1))
        assert result.success is True
        assert result.action_name == "cooperate"

    def test_malformed_json_falls_back_gracefully(self):
        """Non-JSON response results in skipped action, not a crash."""
        agents = _make_agents(["Solo"])
        client = _mock_llm_client("I choose to cooperate!")
        runner = _make_runner(agents=agents, llm_client=client)

        result = asyncio.run(runner._prompt_agent(agents[0], round_num=1))
        assert result.success is False
        assert result.skipped is True

    def test_action_not_in_list_falls_back_to_default(self):
        """Valid JSON with unknown action results in skipped action."""
        agents = _make_agents(["Solo"])
        client = _mock_llm_client('{"action": "surrender"}')
        runner = _make_runner(agents=agents, llm_client=client)

        result = asyncio.run(runner._prompt_agent(agents[0], round_num=1))
        assert result.success is False
        assert result.skipped is True

    def test_empty_llm_response_produces_skipped_result(self):
        """Empty string from LLM produces a skipped ActionResult."""
        agents = _make_agents(["Solo"])
        client = _mock_llm_client("")
        runner = _make_runner(agents=agents, llm_client=client)

        result = asyncio.run(runner._prompt_agent(agents[0], round_num=1))
        assert result.success is False
        assert result.skipped is True


# --- Turn Loop ---


class TestTurnLoop:
    """Verify agent execution order and failure handling."""

    @pytest.mark.asyncio
    async def test_all_agents_called_in_simultaneous_mode(self):
        """In simultaneous mode, all agents are prompted."""
        agents = _make_agents(("A", "B", "C"))
        client = _mock_llm_client()
        runner = _make_runner(
            agents=agents,
            game_config=_make_non_pairwise_game_config(),
            llm_client=client,
        )

        result = await runner._run_simultaneous_round(round_num=1)

        assert len(result.actions) == 3
        names = {a.agent_name for a in result.actions}
        assert names == {"A", "B", "C"}

    @pytest.mark.asyncio
    async def test_all_agents_called_in_correct_order_sequential(self):
        """In sequential mode, agents act in config order."""
        agents = _make_agents(("First", "Second", "Third"))
        client = _mock_llm_client()
        runner = _make_runner(
            agents=agents,
            game_config=_make_non_pairwise_game_config(),
            llm_client=client,
            round_visibility="sequential",
        )

        result = await runner._run_sequential_round(round_num=1)

        names = [a.agent_name for a in result.actions]
        assert names == ["First", "Second", "Third"]

    @pytest.mark.asyncio
    async def test_failed_llm_call_produces_skipped_action(self):
        """An exception during LLM call results in skipped ActionResult."""
        agents = _make_agents(("Alice",))
        client = _mock_llm_client()
        client.chat = Mock(side_effect=RuntimeError("Connection refused"))
        runner = _make_runner(agents=agents, llm_client=client)

        result = await runner._run_simultaneous_round(round_num=1)
        assert len(result.actions) == 1
        assert result.actions[0].skipped is True
        assert result.actions[0].success is False

    @pytest.mark.asyncio
    async def test_max_concurrent_agents_respected(self):
        """Simultaneous mode respects the concurrency semaphore."""
        agents = _make_agents([f"A{i}" for i in range(6)])
        client = _mock_llm_client()
        runner = _make_runner(agents=agents, llm_client=client)

        result = await runner._run_simultaneous_round(round_num=1)
        assert len(result.actions) == 6


# --- Follow-up Modes ---


class TestFollowUpModes:
    """Verify follow-up prompt behavior."""

    def test_followup_modes_from_game_config(self):
        """Runner passes action_followup_modes from game_config to controller."""
        game_config = GameConfig(
            name="Council",
            description="Discuss",
            action_type="discrete",
            actions=["speak", "abstain"],
            payoff_type="none",
            action_followup_modes={"speak": "plain_text"},
        )
        agents = _make_agents(("A",))
        client = _mock_llm_client()
        runner = _make_runner(
            agents=agents, game_config=game_config, llm_client=client,
        )

        assert runner.game_config.action_followup_modes == {"speak": "plain_text"}


# --- Round Result ---


class TestRoundResult:
    """Verify RoundResult dataclass contents."""

    @pytest.mark.asyncio
    async def test_round_result_contains_correct_agent_names(self):
        """RoundResult.actions contains entries for each agent."""
        agents = _make_agents(("X", "Y"))
        client = _mock_llm_client()
        runner = _make_runner(agents=agents, llm_client=client)

        result = await runner._run_simultaneous_round(round_num=5)

        assert result.round_num == 5
        names = {a.agent_name for a in result.actions}
        assert names == {"X", "Y"}

    @pytest.mark.asyncio
    async def test_round_result_completed_flag_true_when_all_done(self):
        """completed=True when all agents produced results."""
        agents = _make_agents(("P", "Q"))
        client = _mock_llm_client()
        runner = _make_runner(agents=agents, llm_client=client)

        result = await runner._run_simultaneous_round(round_num=1)
        assert result.completed is True

    @pytest.mark.asyncio
    async def test_round_result_has_payoffs_for_matrix_game(self):
        """Matrix game rounds produce payoff dict."""
        agents = _make_agents(("A", "B"))
        client = _mock_llm_client('{"action": "cooperate"}')
        runner = _make_runner(agents=agents, llm_client=client)

        result = await runner._run_simultaneous_round(round_num=1)
        assert result.payoffs is not None
        assert "A" in result.payoffs
        assert "B" in result.payoffs

    def test_record_action_to_agent_stores_in_history(self):
        """_record_action_to_agent appends to agent.action_history."""
        agents = _make_agents(("Alice",))
        runner = _make_runner(agents=agents)
        action_result = ActionResult(
            success=True,
            action_name="cooperate",
            parameters={},
            summary="Alice cooperated",
            agent_name="Alice",
            round_num=1,
        )

        runner._record_action_to_agent(action_result)

        assert len(agents[0].action_history) == 1
        entry = agents[0].action_history[0]
        assert entry["action"] == "cooperate"
        assert entry["round"] == 1

    def test_get_agent_llm_client_uses_per_agent_client(self):
        """Per-agent LLM client is used when available."""
        agents = _make_agents(("Alice",))
        default_client = _mock_llm_client()
        per_agent_client = _mock_llm_client()
        runner = _make_runner(
            agents=agents,
            llm_client=default_client,
            agent_llm_clients={"Alice": per_agent_client},
        )

        result = runner.get_agent_llm_client(agents[0])
        assert result is per_agent_client

    def test_get_agent_llm_client_falls_back_to_default(self):
        """Default LLM client is used when no per-agent client exists."""
        agents = _make_agents(("Alice",))
        default_client = _mock_llm_client()
        runner = _make_runner(agents=agents, llm_client=default_client)

        result = runner.get_agent_llm_client(agents[0])
        assert result is default_client
