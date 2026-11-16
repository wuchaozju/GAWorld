"""
Round execution loop contract tests for ExperimentRunner.

Pins the round lifecycle contracts that the Environment Agent feature
and Results Tab data pipeline depend on. All tests use dialect="mock"
with no real LLM calls.

Contains: test_event_commit_timing, test_round_number_sequence,
    test_round_result_shape, test_post_round_state_independence,
    test_event_payload_shape
"""

import pytest

from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import GameConfig
from fos.core.experiment.runner import ExperimentRunner
from fos.core.llm.client import LLMClient
from fos.core.llm_config import LLMConfig


def _make_agents(n=2):
    """Create n mock-dialect agents for testing."""
    return [
        ExperimentAgent(
            name=f"Agent{i + 1}",
            properties={},
            llm_config=LLMConfig(dialect="mock"),
        )
        for i in range(n)
    ]


def _make_runner(agents, round_visibility="simultaneous"):
    """Create an ExperimentRunner with a mock LLM client and simple game config."""
    llm_client = LLMClient(LLMConfig(dialect="mock"))
    game_config = GameConfig(
        name="test_game",
        description="Test game for round contracts",
        action_type="discrete",
        actions=["cooperate", "defect"],
        action_descriptions={"cooperate": "Cooperate", "defect": "Defect"},
        payoff_type="none",
    )
    return ExperimentRunner(
        agents=agents,
        game_config=game_config,
        llm_client=llm_client,
        round_visibility=round_visibility,
    )


@pytest.mark.asyncio
async def test_event_commit_timing():
    """Events must not be visible to agents during the round they are produced in.

    If this fails, agents see each other's choices mid-round, breaking the
    simultaneous-round isolation guarantee.

    Environment Agent depends on this contract: it hooks into round end,
    so events must be committed only AFTER all prompting completes.
    """
    agents = _make_agents(2)
    runner = _make_runner(agents, round_visibility="simultaneous")
    events_during_prompting = []

    original_prompt = runner._prompt_agent

    async def intercepting_prompt(agent, round_num):
        # Snapshot the round's events while agent is being prompted
        events_during_prompting.append(
            list(runner.context_manager.get_round_events(round_num))
        )
        return await original_prompt(agent, round_num)

    runner._prompt_agent = intercepting_prompt

    await runner._run_simultaneous_round(1)

    # During prompting, no events should be visible for the current round
    for snapshot in events_during_prompting:
        assert snapshot == [], (
            f"Events leaked mid-round: {snapshot}. "
            "Agents must not see each other's actions during prompting."
        )

    # After the round completes, exactly 2 events must be recorded
    round_events = runner.context_manager.get_round_events(1)
    assert len(round_events) == 2, (
        f"Expected 2 events after round, got {len(round_events)}"
    )


@pytest.mark.asyncio
async def test_round_number_sequence():
    """Round numbers must increment by exactly 1, starting at 1.

    If this fails, round numbering is broken, which corrupts the event log
    and confuses any downstream consumer.

    Both Environment Agent and Results Tab depend on this contract.
    """
    agents = _make_agents(2)
    runner = _make_runner(agents)

    results = await runner.run(max_rounds=3)

    round_nums = [r.round_num for r in results]
    assert round_nums == [1, 2, 3], (
        f"Round numbers must be [1, 2, 3], got {round_nums}"
    )


@pytest.mark.asyncio
async def test_round_result_shape():
    """RoundResult must have a stable, predictable shape with all required fields.

    If this fails, any code consuming RoundResult will crash or misinterpret
    data. This is the exact shape the Environment Agent code will depend on.

    Both Environment Agent and Results Tab depend on this contract.
    """
    agents = _make_agents(2)
    runner = _make_runner(agents)

    result = await runner._run_simultaneous_round(1)

    # Top-level RoundResult shape
    assert isinstance(result.round_num, int), (
        f"round_num must be int, got {type(result.round_num)}"
    )
    assert isinstance(result.actions, list), (
        f"actions must be list, got {type(result.actions)}"
    )
    assert result.completed is True, (
        f"completed must be True for successful round, got {result.completed}"
    )

    # Each ActionResult must have the required fields with correct types
    configured_actions = {"cooperate", "defect"}
    for action in result.actions:
        assert isinstance(action.agent_name, str), (
            f"agent_name must be str, got {type(action.agent_name)}"
        )
        assert isinstance(action.action_name, str), (
            f"action_name must be str, got {type(action.action_name)}: {action.action_name!r}"
        )
        assert action.action_name in configured_actions, (
            f"action_name '{action.action_name}' not in configured set {configured_actions}"
        )
        assert isinstance(action.success, bool), (
            f"success must be bool, got {type(action.success)}"
        )


@pytest.mark.asyncio
async def test_post_round_state_independence():
    """Round 2 must not see round 1's events as current-round events.

    If this fails, events from previous rounds bleed into the current round's
    event list, corrupting the event log.

    Environment Agent depends on this contract: it processes events at
    round end and must see only the current round's events.
    """
    agents = _make_agents(2)
    runner = _make_runner(agents)

    await runner._run_simultaneous_round(1)
    await runner._run_simultaneous_round(2)

    round1_events = runner.context_manager.get_round_events(1)
    round2_events = runner.context_manager.get_round_events(2)

    # Round 2 must have exactly 2 events (not 4 from both rounds)
    assert len(round2_events) == 2, (
        f"Round 2 should have exactly 2 events, got {len(round2_events)}. "
        "Previous round's events leaked into current round."
    )

    # Every round-2 event must have round_num == 2
    for event in round2_events:
        assert event.round_num == 2, (
            f"Round 2 event has round_num={event.round_num}, expected 2. "
            "Events from previous rounds leaked into current round."
        )

    # Round 1 events are still intact
    assert len(round1_events) == 2


@pytest.mark.asyncio
async def test_event_payload_shape():
    """Each recorded event must have agent_name, action_name, round_num, and summary.

    If this fails, the Results Tab data pipeline will crash when rendering
    event history.

    Results Tab depends on this contract.
    """
    agents = _make_agents(2)
    runner = _make_runner(agents)

    await runner._run_simultaneous_round(1)

    events = runner.context_manager.get_round_events(1)
    assert len(events) == 2

    for event in events:
        assert isinstance(event.agent_name, str) and event.agent_name, (
            f"agent_name must be non-empty str, got: {event.agent_name!r}"
        )
        assert isinstance(event.action_name, str) and event.action_name, (
            f"action_name must be non-empty str, got: {event.action_name!r}"
        )
        assert isinstance(event.round_num, int), (
            f"round_num must be int, got {type(event.round_num)}"
        )
        assert isinstance(event.summary, str) and event.summary.strip(), (
            f"summary must be non-empty str, got: {event.summary!r}"
        )
