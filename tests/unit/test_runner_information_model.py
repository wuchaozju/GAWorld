"""
Unit tests for ExperimentRunner with InformationModel integration.
"""
import asyncio
from unittest.mock import Mock

from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import PRISONERS_DILEMMA
from fos.core.experiment.runner import ExperimentRunner
from fos.core.experiment.information_model import InformationModel
from fos.core.llm_config import LLMConfig


def run(coro):
    return asyncio.run(coro)


def make_agents(names):
    llm_config = LLMConfig(dialect="openai", api_key="test")
    return [ExperimentAgent(name=n, properties={}, llm_config=llm_config) for n in names]


def make_mock_llm():
    m = Mock()
    m.chat.return_value = '{"action": "cooperate"}'
    return m


def test_runner_accepts_information_model_param():
    agents = make_agents(["Alice", "Bob"])
    info_model = InformationModel(scope_type="all")
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=make_mock_llm(),
        information_model=info_model,
    )
    assert runner.information_model is info_model
    assert runner.context_manager.information_model is info_model
    assert runner.context_manager.all_agent_names == ["Alice", "Bob"]


def test_runner_without_information_model_still_works():
    agents = make_agents(["Alice", "Bob"])
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=make_mock_llm(),
    )
    assert runner.information_model is None
    results = run(runner.run(max_rounds=1))
    assert len(results) == 1


def test_runner_records_events_with_all_scope_simultaneous():
    agents = make_agents(["Alice", "Bob"])
    info_model = InformationModel(scope_type="all", recent_window=3, primacy_keep=False)
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=make_mock_llm(),
        round_visibility="simultaneous",
        information_model=info_model,
    )
    run(runner.run(max_rounds=1))

    events = runner.context_manager._round_events
    assert len(events) == 2
    for e in events:
        assert set(e.observed_by) == {"Alice", "Bob"}


def test_runner_pair_scope_no_knowledge_leak_simultaneous():
    agents = make_agents(["Alice", "Bob", "Charlie", "David"])
    fixed = [("Alice", "Bob"), ("Charlie", "David")]
    info_model = InformationModel(
        scope_type="pair",
        pairing_fn=lambda a, r: fixed,
        recent_window=3,
        primacy_keep=False,
    )
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=make_mock_llm(),
        round_visibility="simultaneous",
        information_model=info_model,
    )
    run(runner.run(max_rounds=1))

    alice_ctx = runner.context_manager.get_context_for_agent("Alice")
    assert "Bob" in alice_ctx
    assert "Charlie" not in alice_ctx
    assert "David" not in alice_ctx

    charlie_ctx = runner.context_manager.get_context_for_agent("Charlie")
    assert "David" in charlie_ctx
    assert "Alice" not in charlie_ctx
    assert "Bob" not in charlie_ctx


def test_runner_sequential_records_immediately():
    """In sequential mode each agent's action is recorded before the next prompt."""
    agents = make_agents(["Alice", "Bob"])
    info_model = InformationModel(scope_type="all", recent_window=3, primacy_keep=False)
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=make_mock_llm(),
        round_visibility="sequential",
        information_model=info_model,
    )
    run(runner.run(max_rounds=1))

    events = runner.context_manager._round_events
    assert len(events) == 2
    # Both events should be visible to all (all scope)
    for e in events:
        assert set(e.observed_by) == {"Alice", "Bob"}
