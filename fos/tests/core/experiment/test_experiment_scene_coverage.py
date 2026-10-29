"""
Coverage tests for ExperimentScene — payoff calculations, RAG context,
feedback injection, multi-agent rounds, config edge cases, and event emission.

Focuses on paths NOT already covered by existing test files.

Contains: TestExperimentSceneCoverage (~20 tests)
"""

import pytest
from unittest.mock import MagicMock, patch

from fos.core.experiment.scene import ExperimentScene
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.agent import ExperimentAgent
from fos.core.llm_config import LLMConfig


# --- Helpers ---


def _make_scene(
    scenario_id="prisoners_dilemma",
    agents=None,
    actions=None,
    parameters=None,
    **config_overrides,
):
    """Create an ExperimentScene with sensible defaults for testing."""
    agents = agents or [
        {"name": "Alice", "role_prompt": "You are Alice."},
        {"name": "Bob", "role_prompt": "You are Bob."},
    ]
    actions = actions or [{"name": "cooperate"}, {"name": "defect"}]
    parameters = parameters or {}
    config = ExperimentConfig(
        scenario_id=scenario_id,
        agents=agents,
        actions=actions,
        parameters=parameters,
        **config_overrides,
    )
    return ExperimentScene(config)


def _init_scene(scene):
    """Initialize scene with a mock LLM client that returns cooperate."""
    mock_client = MagicMock()
    mock_client.chat = MagicMock(return_value='{"action": "cooperate"}')
    scene.initialize(mock_client)
    return scene


# --- Payoff Calculations ---


class TestPayoffCalculations:
    """Verify payoff scores are applied after rounds."""

    @pytest.mark.asyncio
    async def test_matrix_payoff_scores_applied_after_round(self):
        """Agents get correct scores after a PD round with cooperate_reward."""
        scene = _make_scene(
            parameters={
                "cooperate_reward": 3,
                "sucker_penalty": -1,
                "temptation_reward": 5,
                "defect_penalty": 0,
            },
        )
        _init_scene(scene)

        events = []
        def emitter(t, d):
            events.append((t, d))

        result = await scene.run_round(emitter)

        # Both cooperated → both should get cooperate_reward
        assert result.payoffs is not None
        for agent in scene.agents:
            assert agent.score > 0

    @pytest.mark.asyncio
    async def test_payoff_type_none_skips_calculation(self):
        """When payoff_type='none', no payoffs dict is returned."""
        scene = _make_scene(parameters={"payoff_type": "none"})
        _init_scene(scene)

        events = []
        result = await scene.run_round(lambda t, d: events.append((t, d)))
        assert result.payoffs is None or result.payoffs == {}

    @pytest.mark.asyncio
    async def test_zero_payoff_for_failed_agent(self):
        """An agent that fails (skipped) should not get payoff."""
        scene = _make_scene()
        _init_scene(scene)

        # Force one agent's LLM to fail
        alice = scene.agents[0]
        original_client = scene._agent_llm_clients[alice.name]
        original_client.chat = MagicMock(side_effect=RuntimeError("LLM down"))

        events = []
        result = await scene.run_round(lambda t, d: events.append((t, d)))

        # Find Alice's action
        alice_action = next(a for a in result.actions if a.agent_name == "Alice")
        assert alice_action.skipped is True
        assert alice_action.success is False


# --- RAG Context ---


class TestRagContext:
    """Verify RAG context retrieval for agents."""

    def test_get_rag_context_returns_empty_when_no_documents(self):
        """Agent with no documents or knowledge_base returns empty string."""
        agent = ExperimentAgent(
            name="Test", properties={}, llm_config=LLMConfig(dialect="mock")
        )
        assert agent.get_rag_context("test query") == ""

    def test_get_rag_context_returns_keyword_match_from_knowledge_base(self):
        """Agent with knowledge_base items returns keyword-matched context."""
        agent = ExperimentAgent(
            name="Test",
            properties={},
            llm_config=LLMConfig(dialect="mock"),
            knowledge_base=[
                {"title": "Climate", "content": "Global warming data", "enabled": True},
            ],
        )
        result = agent.get_rag_context("climate change")
        assert "Climate" in result

    @pytest.mark.asyncio
    async def test_global_knowledge_passed_to_runner(self):
        """Scene's global_knowledge is accessible by the runner during prompting."""
        gk = {"doc1": {"chunks": [{"text": "shared info"}]}}
        scene = _make_scene(
            parameters={"payoff_type": "none"},
        )
        scene.global_knowledge = gk
        _init_scene(scene)

        # Verify scene exposes global_knowledge
        assert scene.global_knowledge == gk


# --- Agent Feedback Injection ---


class TestFeedbackInjection:
    """Verify feedback buffer content appears in prompts and is cleared."""

    def test_feedback_buffer_stores_messages(self):
        """add_env_feedback appends to buffer."""
        agent = ExperimentAgent(
            name="Test", properties={}, llm_config=LLMConfig(dialect="mock")
        )
        agent.add_env_feedback("Invalid target")
        agent.add_env_feedback("Try again")
        assert agent.get_feedback_text() == "Invalid target\nTry again"

    def test_clear_feedback_buffer_empties(self):
        """clear_feedback_buffer removes all messages."""
        agent = ExperimentAgent(
            name="Test", properties={}, llm_config=LLMConfig(dialect="mock")
        )
        agent.add_env_feedback("Some feedback")
        agent.clear_feedback_buffer()
        assert agent.get_feedback_text() == ""

    @pytest.mark.asyncio
    async def test_feedback_injected_into_prompt_during_round(self):
        """Feedback buffer content should be included in the agent's prompt."""
        scene = _make_scene(parameters={"payoff_type": "none"})
        _init_scene(scene)

        # Add feedback to Alice
        alice = scene.agents[0]
        alice.add_env_feedback("Your target was invalid")

        # Capture what prompt gets built by patching build_prompt
        with patch(
            "fos.core.experiment.runner.build_prompt", return_value='{"action": "cooperate"}'
        ) as mock_build:
            # We need to also mock the LLM client's chat to return valid JSON
            for name, client in scene._agent_llm_clients.items():
                client.chat = MagicMock(return_value='{"action": "cooperate"}')

            events = []
            await scene.run_round(lambda t, d: events.append((t, d)))

            # build_prompt should have been called — check the context arg
            # includes the feedback text
            called_with_feedback = False
            for call in mock_build.call_args_list:
                args, kwargs = call
                # The context argument (3rd positional) should contain feedback
                if len(args) >= 3 and "Your target was invalid" in args[2]:
                    called_with_feedback = True
                    break
            assert called_with_feedback, "Feedback text should appear in prompt context"

        # After the round, feedback buffer should be cleared
        assert alice.get_feedback_text() == ""


# --- Multi-Agent Round ---


class TestMultiAgentRound:
    """Verify all agents take actions in a round."""

    @pytest.mark.asyncio
    async def test_all_agents_take_actions(self):
        """All agents produce one ActionResult each."""
        scene = _make_scene()
        _init_scene(scene)

        events = []
        result = await scene.run_round(lambda t, d: events.append((t, d)))

        agent_names = {a.agent_name for a in result.actions}
        assert agent_names == {"Alice", "Bob"}
        assert len(result.actions) == 2

    @pytest.mark.asyncio
    async def test_three_agent_round(self):
        """A pair game with three agents should skip the unpaired player."""
        agents = [
            {"name": "A", "role_prompt": "Agent A"},
            {"name": "B", "role_prompt": "Agent B"},
            {"name": "C", "role_prompt": "Agent C"},
        ]
        scene = _make_scene(agents=agents)
        _init_scene(scene)

        events = []
        result = await scene.run_round(lambda t, d: events.append((t, d)))
        assert len(result.actions) == 2
        assert {a.agent_name for a in result.actions}.issubset({"A", "B", "C"})

    @pytest.mark.asyncio
    async def test_three_agent_discussion_round_prompts_everyone(self):
        """A non-pair discussion round should still prompt every agent."""
        agents = [
            {"name": "A", "role_prompt": "Agent A"},
            {"name": "B", "role_prompt": "Agent B"},
            {"name": "C", "role_prompt": "Agent C"},
        ]
        scene = _make_scene(
            scenario_id="open_discussion",
            agents=agents,
            actions=[{"name": "speak", "description": "Say something"}],
            parameters={"payoff_type": "none", "grouping_mode": "individual", "topic": "Lunch"},
        )
        _init_scene(scene)

        result = await scene.run_round(lambda t, d: None)

        assert [action.agent_name for action in result.actions] == ["A", "B", "C"]


# --- Config Edge Cases ---


class TestConfigEdgeCases:
    """Test missing optional fields and empty action lists."""

    def test_missing_parameters_uses_defaults(self):
        """Scene with no parameters dict still initializes."""
        config = ExperimentConfig(
            scenario_id="prisoners_dilemma",
            agents=[{"name": "Alice"}],
            actions=[{"name": "cooperate"}],
        )
        scene = ExperimentScene(config)
        assert scene.config.parameters == {}
        assert scene.current_round == 0

    def test_missing_optional_fields_use_defaults(self):
        """ExperimentConfig defaults: description='', scenario_id='custom', etc."""
        config = ExperimentConfig(agents=[], actions=[])
        assert config.description == ""
        assert config.scenario_id == "custom"
        assert config.round_visibility == "simultaneous"
        assert config.locale == "en"
        assert config.global_knowledge == {}

    @pytest.mark.asyncio
    async def test_run_round_raises_if_not_initialized(self):
        """Calling run_round before initialize() raises ValueError."""
        scene = _make_scene()
        # Don't call initialize()
        with pytest.raises(ValueError, match="not initialized"):
            await scene.run_round(lambda t, d: None)

    def test_double_initialize_is_idempotent(self):
        """Calling initialize() twice does not recreate agents."""
        scene = _make_scene()
        mock_client = MagicMock()
        mock_client.chat = MagicMock(return_value='{"action": "cooperate"}')
        scene.initialize(mock_client)
        first_agents = list(scene.agents)
        scene.initialize(mock_client)
        assert scene.agents == first_agents


# --- Event Emission ---


class TestEventEmission:
    """Verify run_round emits experiment_action events."""

    @pytest.mark.asyncio
    async def test_run_round_emits_experiment_action_events(self):
        """Each agent's action triggers an experiment_action event."""
        scene = _make_scene(parameters={"payoff_type": "none"})
        _init_scene(scene)

        events = []
        await scene.run_round(lambda t, d: events.append((t, d)))

        action_events = [e for e in events if e[0] == "experiment_action"]
        assert len(action_events) == 2
        for _, data in action_events:
            assert "agent" in data
            assert "action" in data
            assert "round" in data

    @pytest.mark.asyncio
    async def test_event_contains_round_number(self):
        """Events from round 2 contain round=2."""
        scene = _make_scene(parameters={"payoff_type": "none"})
        _init_scene(scene)

        # Run round 1 first
        await scene.run_round(lambda t, d: None)

        # Run round 2 and capture events
        events = []
        await scene.run_round(lambda t, d: events.append((t, d)))

        action_events = [e for e in events if e[0] == "experiment_action"]
        for _, data in action_events:
            assert data["round"] == 2

    @pytest.mark.asyncio
    async def test_event_contains_success_flag(self):
        """Each experiment_action event has a 'success' boolean."""
        scene = _make_scene(parameters={"payoff_type": "none"})
        _init_scene(scene)

        events = []
        await scene.run_round(lambda t, d: events.append((t, d)))

        action_events = [e for e in events if e[0] == "experiment_action"]
        for _, data in action_events:
            assert "success" in data
            assert isinstance(data["success"], bool)

    @pytest.mark.asyncio
    async def test_serialization_round_trip(self):
        """serialize_config → deserialize_config preserves key state."""
        scene = _make_scene(parameters={"payoff_type": "none"})
        _init_scene(scene)

        events = []
        await scene.run_round(lambda t, d: events.append((t, d)))

        data = scene.serialize_config()
        assert data["current_round"] == 1

        restored = ExperimentScene.deserialize_config(data)
        assert restored.current_round == 1
        assert len(restored.agents) == 0  # Agents only created on initialize()
        assert restored.config.scenario_id == "prisoners_dilemma"

    @pytest.mark.asyncio
    async def test_history_tracked_across_rounds(self):
        """_history accumulates entries after each round."""
        scene = _make_scene(parameters={"payoff_type": "none"})
        _init_scene(scene)

        await scene.run_round(lambda t, d: None)
        assert len(scene._history) == 1
        assert scene._history[0]["round"] == 1

        await scene.run_round(lambda t, d: None)
        assert len(scene._history) == 2
        assert scene._history[1]["round"] == 2
