"""
Integration test: InformationModel correctly scopes knowledge across a full run.
"""
import asyncio
from unittest.mock import Mock

from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import PRISONERS_DILEMMA
from fos.core.experiment.runner import ExperimentRunner
from fos.core.experiment.information_model import InformationModel
from fos.core.experiment.prompt_builder import build_prompt
from fos.core.llm_config import LLMConfig


def run(coro):
    return asyncio.run(coro)


def make_mock_llm(action="cooperate"):
    m = Mock()
    m.chat.return_value = f'{{"action": "{action}"}}'
    return m


def test_all_scope_agents_see_everyone():
    llm_config = LLMConfig(dialect="openai", api_key="test")
    agents = [ExperimentAgent(name=n, properties={}, llm_config=llm_config) for n in ["Alice", "Bob"]]
    info_model = InformationModel(scope_type="all", recent_window=3, primacy_keep=False)
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=make_mock_llm(),
        round_visibility="simultaneous",
        information_model=info_model,
    )
    run(runner.run(max_rounds=2))

    alice_ctx = runner.context_manager.get_context_for_agent("Alice", agent_score=0)
    bob_ctx = runner.context_manager.get_context_for_agent("Bob", agent_score=0)
    assert "Bob" in alice_ctx
    assert "Alice" in bob_ctx


def test_pair_scope_no_cross_pair_knowledge_leak():
    """Alice-Bob pair must not see Charlie-David's actions and vice versa."""
    llm_config = LLMConfig(dialect="openai", api_key="test")
    agents = [ExperimentAgent(name=n, properties={}, llm_config=llm_config) for n in
              ["Alice", "Bob", "Charlie", "David"]]
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

    alice_ctx = runner.context_manager.get_context_for_agent("Alice", agent_score=0)
    assert "Bob" in alice_ctx
    assert "Charlie" not in alice_ctx
    assert "David" not in alice_ctx

    charlie_ctx = runner.context_manager.get_context_for_agent("Charlie", agent_score=0)
    assert "David" in charlie_ctx
    assert "Alice" not in charlie_ctx
    assert "Bob" not in charlie_ctx


def test_self_scope_agents_see_only_own_history():
    llm_config = LLMConfig(dialect="openai", api_key="test")
    agents = [ExperimentAgent(name=n, properties={}, llm_config=llm_config) for n in ["Alice", "Bob"]]
    info_model = InformationModel(scope_type="self", recent_window=3, primacy_keep=False)
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=make_mock_llm(),
        round_visibility="simultaneous",
        information_model=info_model,
    )
    run(runner.run(max_rounds=1))

    alice_ctx = runner.context_manager.get_context_for_agent("Alice")
    assert "Bob" not in alice_ctx

    bob_ctx = runner.context_manager.get_context_for_agent("Bob")
    assert "Alice" not in bob_ctx


def test_context_budget_enforced_in_prompt():
    llm_config = LLMConfig(dialect="openai", api_key="test")
    agents = [ExperimentAgent(name=n, properties={}, llm_config=llm_config) for n in ["Alice", "Bob"]]
    info_model = InformationModel(
        scope_type="all",
        recent_window=10,
        primacy_keep=False,
        context_budget_chars=60,
    )
    runner = ExperimentRunner(
        agents=agents,
        game_config=PRISONERS_DILEMMA,
        llm_client=make_mock_llm(),
        round_visibility="simultaneous",
        information_model=info_model,
    )
    run(runner.run(max_rounds=5))

    # Build a prompt for Alice and check Section 4 is bounded
    alice_score = next(a.score for a in runner.agents if a.name == "Alice")
    context = runner.context_manager.get_context_for_agent("Alice", agent_score=alice_score)
    prompt = build_prompt(
        next(a for a in runner.agents if a.name == "Alice"),
        PRISONERS_DILEMMA,
        context,
        include_section_markers=True,
        information_model=info_model,
    )
    # Section 4 context should not contain 5 separate round lines (budget truncated it)
    section4_start = prompt.find("## Context\n") + len("## Context\n")
    section4_end = prompt.find("\n## ", section4_start)
    section4 = prompt[section4_start:section4_end] if section4_end > 0 else prompt[section4_start:]
    assert len(section4) <= 200  # well within budget + small overhead
