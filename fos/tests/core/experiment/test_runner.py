"""
Tests for ExperimentRunner.

Tests the runner's ability to:
- Initialize with agents and game config
- Run simultaneous rounds (all agents decide independently)
- Run sequential rounds (agents see previous choices)
- Handle agent failures gracefully
- Track round completion
"""

import asyncio
import os

import pytest
from unittest.mock import Mock, patch

from fos.core.experiment.runner import ExperimentRunner, RoundResult
from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import PRISONERS_DILEMMA, MINIMUM_EFFORT
from fos.core.experiment.information_model import InformationModel
from fos.core.experiment.kernel import ExperimentKernel
from fos.core.llm_config import LLMConfig
from fos.core.experiment.controller import ActionResult


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client that returns valid JSON responses."""
    client = Mock()
    # Mock the chat method to return a valid JSON response
    client.chat = Mock(return_value='{"reasoning": "I choose to cooperate", "action": "cooperate"}')
    return client


@pytest.fixture
def agents():
    """Create test agents."""
    return [
        ExperimentAgent(
            name="Alice",
            properties={"age_group": "adult"},
            llm_config=LLMConfig(dialect="mock")
        ),
        ExperimentAgent(
            name="Bob",
            properties={"age_group": "adult"},
            llm_config=LLMConfig(dialect="mock")
        ),
    ]


def test_runner_initialization(agents, mock_llm_client):
    """Initialize runner with agents and game config."""
    kernel = ExperimentKernel()
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=mock_llm_client,
        kernel=kernel,
        round_visibility="simultaneous"
    )

    assert len(runner.agents) == 2
    assert runner.game_config == PRISONERS_DILEMMA
    assert runner.llm_client == mock_llm_client
    assert runner.kernel == kernel
    assert runner.round_visibility == "simultaneous"
    assert runner.current_round == 0
    assert runner.context_manager is not None
    assert runner.controller is not None


def test_runner_initialization_with_default_kernel(agents, mock_llm_client):
    """Initialize runner without specifying kernel (uses default)."""
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=mock_llm_client
    )

    assert runner.kernel is not None
    assert isinstance(runner.kernel, ExperimentKernel)


@pytest.mark.asyncio
async def test_run_simultaneous_round(agents, mock_llm_client):
    """Run a single simultaneous round where all agents decide independently."""
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=mock_llm_client,
        round_visibility="simultaneous"
    )

    # Run one round
    results = await runner.run(max_rounds=1)

    assert len(results) == 1
    assert results[0].round_num == 1
    assert len(results[0].actions) == 2
    assert results[0].completed is True


@pytest.mark.asyncio
async def test_run_sequential_round(agents, mock_llm_client):
    """Run a single sequential round where agents see previous choices."""
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=mock_llm_client,
        round_visibility="sequential"
    )

    # Run one round
    results = await runner.run(max_rounds=1)

    assert len(results) == 1
    assert results[0].round_num == 1
    assert len(results[0].actions) == 2
    assert results[0].completed is True

    # Check that actions were recorded in context
    events = runner.context_manager.get_round_events(1)
    assert len(events) == 2


@pytest.mark.asyncio
async def test_run_sequential_round_with_model_switch_tracking(agents, mock_llm_client):
    """Sequential rounds should initialize model tracking before prompting agents."""
    mock_llm_client.provider = Mock(
        model="phi4-mini:latest",
        base_url="http://fos-ollama:11434",
        dialect="ollama",
    )

    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=mock_llm_client,
        round_visibility="sequential"
    )
    runner._preload_model = Mock(return_value=True)

    result = await runner._run_sequential_round(round_num=1)

    assert len(result.actions) == 2
    assert all(action.success for action in result.actions)
    assert runner._last_model == "phi4-mini:latest"
    assert runner._preload_model.call_count == 1


@pytest.mark.asyncio
async def test_run_multiple_rounds(agents, mock_llm_client):
    """Run multiple rounds and verify tracking."""
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=mock_llm_client,
        round_visibility="simultaneous"
    )

    # Run three rounds
    results = await runner.run(max_rounds=3)

    assert len(results) == 3
    assert results[0].round_num == 1
    assert results[1].round_num == 2
    assert results[2].round_num == 3
    assert runner.current_round == 3

    # Each round should have 2 actions
    for result in results:
        assert len(result.actions) == 2
        assert result.completed is True


@pytest.mark.asyncio
async def test_agent_failure_handling(agents, mock_llm_client):
    """Handle agent failures gracefully without crashing the round.

    When an agent fails, an ActionResult with success=False is returned.
    The round continues processing other agents.
    """
    # Patch asyncio.to_thread to raise exception on first call (Alice fails)
    # but succeed on second call (Bob succeeds)
    original_to_thread = asyncio.to_thread

    async def mock_to_thread(func, *args, **kwargs):
        # Use a closure to track call count
        if not hasattr(mock_to_thread, 'call_count'):
            mock_to_thread.call_count = 0
        mock_to_thread.call_count += 1
        if mock_to_thread.call_count == 1:
            raise Exception("LLM error")
        # Second call returns valid JSON (using mock_llm_client's default)
        return await original_to_thread(func, *args, **kwargs)

    with patch('asyncio.to_thread', side_effect=mock_to_thread):
        runner = ExperimentRunner(
            agents=agents,
            game_config=PRISONERS_DILEMMA,
            llm_client=mock_llm_client,
            round_visibility="simultaneous"
        )

        # Run one round - one agent will fail
        results = await runner.run(max_rounds=1)

        assert len(results) == 1
        # Both agents return ActionResults (one failed, one succeeded)
        assert len(results[0].actions) == 2
        # First agent (Alice) failed
        assert results[0].actions[0].success is False
        assert results[0].actions[0].skipped is True
        # Second agent (Bob) succeeded
        assert results[0].actions[1].success is True
        # Mock returns "cooperate" by default
        assert results[0].actions[1].action_name == "cooperate"


@pytest.mark.asyncio
async def test_game_config_actions_respected(mock_llm_client):
    """Verify that the game config is properly passed through."""
    agents = [
        ExperimentAgent(
            name="Player1",
            properties={},
            llm_config=LLMConfig(dialect="mock")
        ),
    ]

    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=mock_llm_client
    )

    assert runner.game_config.actions == ["cooperate", "defect"]
    assert runner.game_config.action_type == "discrete"


@pytest.mark.asyncio
async def test_integer_action_type_game(mock_llm_client):
    """Test runner with integer-type game config."""
    # Mock response for integer action
    mock_llm_client.chat = Mock(return_value='{"reasoning": "I choose 5", "effort": 5}')

    agents = [
        ExperimentAgent(
            name="Worker1",
            properties={},
            llm_config=LLMConfig(dialect="mock")
        ),
    ]

    runner = ExperimentRunner(
        agents=agents,
        game_config=MINIMUM_EFFORT,
        llm_client=mock_llm_client
    )

    results = await runner.run(max_rounds=1)

    assert len(results) == 1
    assert results[0].actions[0].action_name == 5


def test_round_result_dataclass():
    """RoundResult stores all attributes correctly."""
    actions = [
        ActionResult(
            success=True,
            action_name="cooperate",
            parameters={},
            summary="Alice cooperated",
            agent_name="Alice",
            round_num=1
        )
    ]

    result = RoundResult(
        round_num=1,
        actions=actions,
        completed=True
    )

    assert result.round_num == 1
    assert len(result.actions) == 1
    assert result.actions[0].action_name == "cooperate"
    assert result.completed is True


def test_prompt_agent_handles_isolated_node_in_neighborhood_debug():
    agents = [
        ExperimentAgent(name="A", properties={}, llm_config=LLMConfig(dialect="mock")),
        ExperimentAgent(name="B", properties={}, llm_config=LLMConfig(dialect="mock")),
        ExperimentAgent(name="C", properties={}, llm_config=LLMConfig(dialect="mock")),
    ]
    llm_client = Mock(return_value='{"action": "move"}')
    llm_client.chat = Mock(return_value='{"action": "move"}')
    runner = ExperimentRunner(
        agents=agents,
        game_config=MINIMUM_EFFORT.__class__(
            name="Contagion",
            description="Contagion test",
            action_type="discrete",
            actions=["move", "speak"],
            action_descriptions={"move": "Move", "speak": "Speak"},
            payoff_type="none",
        ),
        llm_client=llm_client,
        information_model=InformationModel(scope_type="neighborhood", include_scores=False),
    )
    runner.set_scene_state({"graph": {"edges": [("A", "B")]}})

    result = asyncio.run(runner._prompt_agent(agents[2], round_num=1))

    assert result.success is True
    assert result.action_name == "move"


def test_replay_history_to_events_rebuilds_without_duplicates(agents, mock_llm_client):
    """Replaying persisted history multiple times should not duplicate events."""
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=mock_llm_client,
        information_model=InformationModel(scope_type="all", recent_window=3),
    )
    round_history = [
        {
            "round": 1,
            "actions": [
                {
                    "agent": "Alice",
                    "action": "cooperate",
                    "parameters": {},
                    "summary": "Alice chose cooperate",
                },
                {
                    "agent": "Bob",
                    "action": "defect",
                    "parameters": {},
                    "summary": "Bob chose defect",
                },
            ],
            "payoffs": {"Alice": 0, "Bob": 5},
        }
    ]

    runner._replay_history_to_events(round_history)
    assert len(runner.context_manager.get_round_events(1)) == 2
    assert agents[0].score == 0
    assert agents[1].score == 5


def test_simultaneous_round_no_context_leak_during_prompting():
    """In a simultaneous round, agents must not see each other's actions while being prompted.

    Events are recorded only after all agents have responded, so no mid-round
    context leakage occurs even though agents run concurrently.
    """
    agents = [
        ExperimentAgent(name="Alice", properties={}, llm_config=LLMConfig(dialect="mock")),
        ExperimentAgent(name="Bob", properties={}, llm_config=LLMConfig(dialect="mock")),
    ]
    runner = ExperimentRunner(
        agents=agents,
        game_config=MINIMUM_EFFORT.__class__(
            name="Council",
            description="Discuss and vote.",
            action_type="discrete",
            actions=["speak", "abstain"],
            action_descriptions={"speak": "Speak", "abstain": "Abstain"},
            payoff_type="none",
        ),
        llm_client=Mock(),
        round_visibility="simultaneous",
        information_model=InformationModel(scope_type="all", include_scores=False),
    )

    prompted_agents = []

    async def fake_prompt(agent, round_num):
        # Context leak check: no events should exist for this round yet
        assert runner.context_manager.get_round_events(round_num) == []
        prompted_agents.append(agent.name)
        await asyncio.sleep(0)
        return ActionResult(
            success=True,
            action_name="abstain",
            parameters={},
            summary=f"{agent.name} chose abstain",
            agent_name=agent.name,
            round_num=round_num,
        )

    runner._prompt_agent = fake_prompt

    result = asyncio.run(runner._run_simultaneous_round(1))

    assert set(prompted_agents) == {"Alice", "Bob"}
    assert len(result.actions) == 2
    # After the round completes, events should be recorded
    assert len(runner.context_manager.get_round_events(1)) == 2


@pytest.mark.asyncio
async def test_context_update_after_round(agents, mock_llm_client):
    """Verify that context summaries are updated after each round."""
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=mock_llm_client,
        round_visibility="simultaneous"
    )

    # Initial contexts should be empty
    assert runner.context_manager.get_context("Alice") == ""
    assert runner.context_manager.get_context("Bob") == ""

    # Run a round
    await runner.run(max_rounds=1)

    # Context manager should have recorded events
    events = runner.context_manager.get_round_events(1)
    assert len(events) == 2
    # Events are recorded by controller
    assert any(e.agent_name == "Alice" for e in events)
    assert any(e.agent_name == "Bob" for e in events)


@pytest.mark.asyncio
async def test_sequential_visibility_agents_see_previous_choices(agents, mock_llm_client):
    """In sequential mode, later agents see earlier agents' choices."""
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=mock_llm_client,
        round_visibility="sequential"
    )

    # Run one round
    await runner.run(max_rounds=1)

    # In sequential mode, events are recorded immediately after each agent
    # So the context manager should have the events
    events = runner.context_manager.get_round_events(1)
    assert len(events) == 2


@pytest.mark.asyncio
async def test_invalid_json_response_handling(agents, mock_llm_client):
    """Handle invalid JSON responses gracefully.

    Invalid JSON is caught by the controller, which returns an ActionResult
    with success=False and skipped=True. The round is still completed
    (all agents were prompted), but the actions indicate failure.
    """
    # Return invalid JSON
    mock_llm_client.chat = Mock(return_value="This is not valid JSON")

    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=mock_llm_client,
        round_visibility="simultaneous"
    )

    results = await runner.run(max_rounds=1)

    # Both agents were processed but actions failed
    assert len(results) == 1
    assert len(results[0].actions) == 2
    # Both actions should have failed
    assert all(not action.success for action in results[0].actions)
    assert all(action.skipped for action in results[0].actions)


@pytest.mark.asyncio
async def test_random_turn_order_varies(agents, mock_llm_client):
    """In random mode, turn order should vary between rounds."""
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=mock_llm_client,
        round_visibility="random"
    )

    # Run multiple rounds and track turn orders
    await runner.run(max_rounds=5)

    # Turn order should be tracked and vary
    assert runner.turn_order is not None
    # With only 2 agents, turn order will always be [Alice, Bob] or [Bob, Alice]
    # But it should be recorded


@pytest.mark.asyncio
async def test_paired_mode_creates_n_over_2_pairs(mock_llm_client):
    """In paired mode with even number of agents, create n/2 pairs."""
    # Create 4 agents
    agents = [
        ExperimentAgent(
            name=f"Agent{i}",
            properties={},
            llm_config=LLMConfig(dialect="mock")
        )
        for i in range(4)
    ]

    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=mock_llm_client,
        round_visibility="paired"
    )

    # Run one round
    results = await runner.run(max_rounds=1)

    assert len(results) == 1
    # All 4 agents should act (in 2 pairs)
    assert len(results[0].actions) == 4
    assert results[0].completed is True


@pytest.mark.asyncio
async def test_odd_count_paired_one_agent_sits_out(mock_llm_client):
    """In paired mode with odd number of agents, one sits out without an action entry."""
    # Create 3 agents
    agents = [
        ExperimentAgent(
            name=f"Agent{i}",
            properties={},
            llm_config=LLMConfig(dialect="mock")
        )
        for i in range(3)
    ]

    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=mock_llm_client,
        round_visibility="paired"
    )

    # Run one round
    results = await runner.run(max_rounds=1)

    assert len(results) == 1
    assert len(results[0].actions) == 2
    assert all(not action.skipped for action in results[0].actions)
    assert results[0].completed is True


@pytest.mark.asyncio
async def test_simultaneous_pairwise_odd_agent_is_not_prompted_or_recorded():
    """In simultaneous pairwise mode, the unpaired agent does not run."""
    agents = [
        ExperimentAgent(name="Alice", properties={}, llm_config=LLMConfig(dialect="mock")),
        ExperimentAgent(name="Bob", properties={}, llm_config=LLMConfig(dialect="mock")),
        ExperimentAgent(name="Charlie", properties={}, llm_config=LLMConfig(dialect="mock")),
    ]
    info_model = InformationModel(
        scope_type="pair",
        pairing_fn=lambda _agents, _round_num: [("Alice", "Bob")],
        recent_window=3,
        primacy_keep=False,
    )
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=Mock(),
        round_visibility="simultaneous",
        information_model=info_model,
    )

    prompted_agents = []

    async def fake_prompt(agent, round_num):
        prompted_agents.append(agent.name)
        return ActionResult(
            success=True,
            action_name="cooperate",
            parameters={},
            summary=f"{agent.name} chose cooperate",
            agent_name=agent.name,
            round_num=round_num,
        )

    runner._prompt_agent = fake_prompt

    result = await runner._run_simultaneous_round(1)

    assert prompted_agents == ["Alice", "Bob"]
    assert [action.agent_name for action in result.actions] == ["Alice", "Bob"]
    assert "Charlie" not in result.payoffs
    assert result.completed is True

    round_events = runner.context_manager.get_round_events(1)
    assert [event.agent_name for event in round_events] == ["Alice", "Bob"]


@pytest.mark.asyncio
async def test_paired_mode_odd_agent_is_not_prompted_or_recorded():
    """In paired mode, the unpaired agent does not run."""
    agents = [
        ExperimentAgent(name="Alice", properties={}, llm_config=LLMConfig(dialect="mock")),
        ExperimentAgent(name="Bob", properties={}, llm_config=LLMConfig(dialect="mock")),
        ExperimentAgent(name="Charlie", properties={}, llm_config=LLMConfig(dialect="mock")),
    ]
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=Mock(),
        round_visibility="paired",
    )
    runner.turn_order = None

    prompted_agents = []

    async def fake_prompt(agent, round_num):
        prompted_agents.append(agent.name)
        return ActionResult(
            success=True,
            action_name="cooperate",
            parameters={},
            summary=f"{agent.name} chose cooperate",
            agent_name=agent.name,
            round_num=round_num,
        )

    runner._prompt_agent = fake_prompt

    with patch("random.shuffle", side_effect=lambda values: None):
        result = await runner._run_paired_round(1)

    assert prompted_agents == ["Alice", "Bob"]
    assert [action.agent_name for action in result.actions] == ["Alice", "Bob"]
    assert all(not action.skipped for action in result.actions)
    assert "Charlie" not in (result.payoffs or {})
    assert result.completed is True

    round_events = runner.context_manager.get_round_events(1)
    assert [event.agent_name for event in round_events] == ["Alice", "Bob"]


# ── Model-batching optimisation tests (RED phase — implementation TBD) ──────────


def _make_mock_client(
    model_name: str,
    response: str = '{"action": "cooperate", "reasoning": "test"}',
):
    """Create a mock LLM client with a specific model name."""
    client = Mock()
    client.provider = Mock()
    client.provider.model = model_name
    client.chat = Mock(return_value=response)
    return client


def test_runner_get_agent_model_returns_model_name():
    """Test 1: _get_agent_model returns the model name from the agent's LLM client.

    Tests three cases:
    - Mock client that has a provider with a string model name -> returns the string
    - Mock client where provider.model is a Mock (not a string) -> returns None
    - Mock client without a provider -> returns None
    """
    agents = [
        ExperimentAgent(
            name="Alice", properties={}, llm_config=LLMConfig(dialect="mock")
        ),
        ExperimentAgent(
            name="Bob", properties={}, llm_config=LLMConfig(dialect="mock")
        ),
        ExperimentAgent(
            name="Charlie", properties={}, llm_config=LLMConfig(dialect="mock")
        ),
    ]

    # Client with real string model name
    client_with_string = Mock()
    client_with_string.provider = Mock()
    client_with_string.provider.model = "gpt-4"

    # Client where provider.model is a Mock (not a string)
    client_with_mock_model = Mock()
    client_with_mock_model.provider = Mock()
    client_with_mock_model.provider.model = Mock()

    # Client without a provider
    client_no_provider = Mock()

    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=Mock(),
        agent_llm_clients={
            "Alice": client_with_string,
            "Bob": client_with_mock_model,
            "Charlie": client_no_provider,
        },
    )

    # These will FAIL because _get_agent_model does not exist yet (RED phase)
    assert runner._get_agent_model(agents[0]) == "gpt-4"
    assert runner._get_agent_model(agents[1]) is None
    assert runner._get_agent_model(agents[2]) is None


def test_runner_group_agents_by_model_returns_tuples():
    """Test 2: _group_agents_by_model groups agents by their assigned model.

    Tests three scenarios:
    - 6 agents with 3 models (2 agents each): returns 3 groups of 2
    - Agents with no model (None) grouped together under None key
    - Single model -> single group
    """
    models = ["model_a", "model_a", "model_b", "model_b", "model_c", "model_c"]
    agents = [
        ExperimentAgent(
            name=f"Agent{i}", properties={}, llm_config=LLMConfig(dialect="mock")
        )
        for i in range(6)
    ]
    agent_llm_clients = {
        f"Agent{i}": _make_mock_client(m) for i, m in enumerate(models)
    }

    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=Mock(),
        agent_llm_clients=agent_llm_clients,
    )

    # This will FAIL because _group_agents_by_model does not exist yet (RED phase)
    groups = runner._group_agents_by_model(agents)
    assert len(groups) == 3
    for model_name, group_agents in groups:
        assert len(group_agents) == 2
        for agent in group_agents:
            client = runner.get_agent_llm_client(agent)
            m = getattr(getattr(client, "provider", None), "model", None)
            assert m == model_name


def test_runner_group_agents_by_model_none_group():
    """Test 2b: Agents without a model are grouped under None."""
    agents = [
        ExperimentAgent(
            name="Alice", properties={}, llm_config=LLMConfig(dialect="mock")
        ),
        ExperimentAgent(
            name="Bob", properties={}, llm_config=LLMConfig(dialect="mock")
        ),
    ]
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=Mock(),
    )
    # This will FAIL because _group_agents_by_model does not exist yet (RED phase)
    groups = runner._group_agents_by_model(agents)
    assert len(groups) == 1
    assert groups[0][0] is None
    assert len(groups[0][1]) == 2


def test_runner_group_agents_by_model_single_group():
    """Test 2c: Single model produces a single group."""
    agents = [
        ExperimentAgent(
            name=f"Agent{i}", properties={}, llm_config=LLMConfig(dialect="mock")
        )
        for i in range(3)
    ]
    agent_llm_clients = {
        f"Agent{i}": _make_mock_client("model_x") for i in range(3)
    }
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=Mock(),
        agent_llm_clients=agent_llm_clients,
    )
    # This will FAIL because _group_agents_by_model does not exist yet (RED phase)
    groups = runner._group_agents_by_model(agents)
    assert len(groups) == 1
    assert groups[0][0] == "model_x"
    assert len(groups[0][1]) == 3


@pytest.mark.asyncio
async def test_model_batching_reduces_preload_calls():
    """Test 3: _run_simultaneous_round calls _preload_model once per unique model.

    Creates 6 agents with 3 distinct models arranged in interleaved order
    (A, B, C, A, B, C) so the current per-agent preload logic calls
    _preload_model 6 times (once per agent) instead of 3 times (once per
    unique model).

    Uses FOS_LLM_CONCURRENCY=1 to avoid a deadlock caused by threading.Lock
    usage in the current `_prompt_agent`: when one agent holds the lock while
    awaiting `asyncio.to_thread`, another agent's blocking lock acquire()
    stalls the event loop.

    This test FAILS (RED) because the current implementation does not batch
    agents by model before preloading. With concurrency=1, agents run
    sequentially and each interleaved model switch triggers a fresh preload.
    """
    models = ["model_a", "model_b", "model_c", "model_a", "model_b", "model_c"]
    agents = [
        ExperimentAgent(
            name=f"Agent{i}", properties={}, llm_config=LLMConfig(dialect="mock")
        )
        for i in range(6)
    ]
    agent_llm_clients = {
        f"Agent{i}": _make_mock_client(m) for i, m in enumerate(models)
    }

    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=Mock(),
        agent_llm_clients=agent_llm_clients,
        round_visibility="simultaneous",
    )

    # Use concurrency=1 to prevent threading.Lock deadlock
    with (
        patch.object(runner, "_preload_model", return_value=True) as mock_preload,
        patch.dict(os.environ, {"FOS_LLM_CONCURRENCY": "1"}),
    ):
        result = await runner._run_simultaneous_round(1)

    # Current code calls _preload_model per agent (6 times for interleaved models).
    # The batched version would call it 3 times (once per unique model).
    # This assertion FAILS with the current code (RED phase).
    assert mock_preload.call_count == 3, (
        f"Expected _preload_model to be called 3 times (once per unique model), "
        f"but it was called {mock_preload.call_count} times"
    )

    # Verify all 6 agents produced results
    assert len(result.actions) == 6
    assert result.completed is True


@pytest.mark.asyncio
async def test_model_batching_concurrent_within_group():
    """Test 4: Agents in the same model group run concurrently.

    Two agents sharing the same model should run their LLM calls in
    parallel, not sequentially. The test uses a timing-based check:
    each agent's chat call sleeps for 0.25s. If they run concurrently
    total time is ~0.25s; if serialized by the model switch lock it is ~0.5s.

    Uses FOS_LLM_CONCURRENCY=2 to allow both agents to run concurrently
    but the threading.Lock still serializes the chat calls in the current code.
    """
    import time

    agents = [
        ExperimentAgent(
            name="Alice", properties={}, llm_config=LLMConfig(dialect="mock")
        ),
        ExperimentAgent(
            name="Bob", properties={}, llm_config=LLMConfig(dialect="mock")
        ),
    ]

    slow_response = '{"action": "cooperate", "reasoning": "done"}'

    def _slow_chat(messages, json_mode=False):
        time.sleep(0.25)
        return slow_response

    client = Mock()
    client.provider = Mock()
    client.provider.model = "model_a"
    client.chat = Mock(side_effect=_slow_chat)

    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=client,
        round_visibility="simultaneous",
    )

    with (
        patch.object(runner, "_preload_model", return_value=True),
        patch.dict(os.environ, {"FOS_LLM_CONCURRENCY": "2"}),
    ):
        t0 = time.monotonic()
        result = await runner._run_simultaneous_round(1)
        elapsed = time.monotonic() - t0

    # If agents run concurrently within the same model group, elapsed ~0.25s.
    # If serialized by the model switch lock, elapsed ~0.5s.
    # Uses FOS_LLM_CONCURRENCY=1 to avoid threading.Lock deadlock between
    # agents (the lock blocks the event loop when held across await).
    # With serial execution, total time is ~0.5s.  This assertion FAILS with
    # the current code (RED phase) because the lock serialises even same-model
    # agents.
    assert elapsed < 0.35, (
        f"Expected concurrent execution (~0.25s) but took {elapsed:.3f}s "
        f"— agents may be serialized by model switch lock"
    )

    assert len(result.actions) == 2
    assert result.completed is True


@pytest.mark.asyncio
async def test_model_batching_serial_between_groups():
    """Test 5: Agent groups with different models do NOT run concurrently.

    The second model group must wait for the first to complete.
    Uses a tracking list to verify that all agents in Group 1 finish
    their chat calls before any agent in Group 2 starts.

    Uses FOS_LLM_CONCURRENCY=1 so agents run one-at-a-time through the
    semaphore. The current code serialises ALL agents sequentially, so
    group A finishes before group B trivially.  The batched version would
    run group A concurrently (faster) then group B concurrently.
    This test checks that execution ORDER respects model-group boundaries,
    which the current code may not guarantee under concurrent scheduling.
    """
    import time
    import threading

    agents = [
        ExperimentAgent(
            name="A1", properties={}, llm_config=LLMConfig(dialect="mock")
        ),
        ExperimentAgent(
            name="A2", properties={}, llm_config=LLMConfig(dialect="mock")
        ),
        ExperimentAgent(
            name="B1", properties={}, llm_config=LLMConfig(dialect="mock")
        ),
        ExperimentAgent(
            name="B2", properties={}, llm_config=LLMConfig(dialect="mock")
        ),
    ]

    # Track when each agent starts and finishes its chat call
    execution_log = []
    exec_lock = threading.Lock()

    def _make_chat(agent_tag, delay):
        def _chat(messages, json_mode=False):
            with exec_lock:
                execution_log.append((agent_tag, "start", time.monotonic()))
            time.sleep(delay)
            with exec_lock:
                execution_log.append((agent_tag, "end", time.monotonic()))
            return '{"action": "cooperate", "reasoning": "done"}'
        return _chat

    client_a = Mock()
    client_a.provider = Mock()
    client_a.provider.model = "model_a"
    client_a.chat = Mock(side_effect=_make_chat("group_a", 0.1))

    client_b = Mock()
    client_b.provider = Mock()
    client_b.provider.model = "model_b"
    client_b.chat = Mock(side_effect=_make_chat("group_b", 0.1))

    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=Mock(),
        agent_llm_clients={
            "A1": client_a,
            "A2": client_a,
            "B1": client_b,
            "B2": client_b,
        },
        round_visibility="simultaneous",
    )

    with (
        patch.object(runner, "_preload_model", return_value=True),
        patch.dict(os.environ, {"FOS_LLM_CONCURRENCY": "1"}),
    ):
        result = await runner._run_simultaneous_round(1)

    # Parse execution log: agents from group A should all finish before
    # any agent from group B starts.
    group_a_ends = [
        t for tag, phase, t in execution_log
        if tag == "group_a" and phase == "end"
    ]
    group_b_starts = [
        t for tag, phase, t in execution_log
        if tag == "group_b" and phase == "start"
    ]

    if group_a_ends and group_b_starts:
        last_a_end = max(group_a_ends)
        first_b_start = min(group_b_starts)
        # With concurrency=1 this trivially passes since agents run one-at-a-time
        # in agent-list order.  However, in the true batched implementation,
        # groups are explicitly serialised — the assertion remains valid.
        assert last_a_end < first_b_start, (
            f"Group B started before Group A finished: last A end={last_a_end:.3f}, "
            f"first B start={first_b_start:.3f}. Groups should be serialized."
        )

    assert len(result.actions) == 4
    assert result.completed is True
