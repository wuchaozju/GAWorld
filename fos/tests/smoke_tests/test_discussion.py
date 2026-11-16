"""
Smoke tests for discussion scenarios with real Ollama LLM.

Tests Open Discussion scenario with free-form conversation.
"""

import pytest

from fos.core.llm_config import LLMConfig
from fos.core.experiment.game_configs import GameConfig
from fos.core.experiment.runner import ExperimentRunner
from fos.core.experiment.kernel import ExperimentKernel, SpeakAction

from tests.smoke_tests.utils import (
    SmokeTestOutput,
    build_experiment_agent,
)


def build_open_discussion_config(topic: str = "What should we have for lunch?") -> GameConfig:
    """Build Open Discussion game config."""
    return GameConfig(
        name="open_discussion",
        description=(
            f"You are participating in an open discussion.\n"
            f"Topic: {topic}\n\n"
            "Share your thoughts and respond to others freely."
        ),
        action_type="discrete",
        actions=["speak"],
        action_descriptions={
            "speak": "Say something to the group"
        },
        payoff_summary="",  # No payoffs in discussion
        payoff_type="none",
        grouping_mode="individual",
        payoff_config={},
    )


# =============================================================================
# Open Discussion Tests
# =============================================================================

@pytest.mark.asyncio
async def test_open_discussion_basic(default_llm_client, output_dir):
    """Test Open Discussion with 3 agents speaking."""
    topic = "What is the most important quality in a friend?"
    game_config = build_open_discussion_config(topic)
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("Alice", llm_config, role_prompt="You are Alice, a thoughtful person."),
        build_experiment_agent("Bob", llm_config, role_prompt="You are Bob, a practical person."),
        build_experiment_agent("Carol", llm_config, role_prompt="You are Carol, an empathetic person."),
    ]

    # Register speak action and create kernel instance
    ExperimentKernel.register("speak", SpeakAction)
    kernel = ExperimentKernel()

    filename = "open_discussion_phi4-mini_basic.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "open_discussion", "phi4-mini", "basic") as out:
        out.write_config({
            "grouping_mode": "individual",
            "payoff_type": "none",
            "agents": ["Alice", "Bob", "Carol"],
            "actions": ["speak"],
            "topic": topic,
        })

        runner = ExperimentRunner(
            agents=agents,
            game_config=game_config,
            llm_client=default_llm_client,
            round_visibility="sequential",  # Sequential so agents see previous messages
            kernel=kernel,
        )

        round_results = await runner.run(max_rounds=1)

        out.write_round_header(1)
        for action in round_results[0].actions:
            out.write_action_summary(
                action.agent_name,
                action.action_name,
                action.parameters,
                None
            )

        final_scores = {agent.name: agent.score for agent in agents}
        errors = [a.error for a in round_results[0].actions if a.error]

        out.write_summary(final_scores, errors)

    assert len(round_results) == 1
    assert len(round_results[0].actions) == 3


@pytest.mark.asyncio
async def test_open_discussion_no_scores(default_llm_client, output_dir):
    """Verify that Open Discussion has NO score in context."""
    topic = "Should we adopt a new technology?"
    game_config = build_open_discussion_config(topic)
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("Tech1", llm_config, role_prompt="You are optimistic about technology."),
        build_experiment_agent("Tech2", llm_config, role_prompt="You are skeptical about technology."),
    ]

    ExperimentKernel.register("speak", SpeakAction)
    kernel = ExperimentKernel()

    filename = "open_discussion_phi4-mini_no_scores.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "open_discussion", "phi4-mini", "no_scores") as out:
        out.write_config({
            "grouping_mode": "individual",
            "payoff_type": "none",
            "agents": ["Tech1", "Tech2"],
            "actions": ["speak"],
            "topic": topic,
            "verify": "NO SCORE should appear in context",
        })

        runner = ExperimentRunner(
            agents=agents,
            game_config=game_config,
            llm_client=default_llm_client,
            round_visibility="sequential",
            kernel=kernel,
        )

        round_results = await runner.run(max_rounds=1)

        out.write_round_header(1)
        for action in round_results[0].actions:
            out.write_action_summary(action.agent_name, action.action_name, action.parameters, None)

        final_scores = {agent.name: agent.score for agent in agents}
        errors = [a.error for a in round_results[0].actions if a.error]

        out.write_summary(final_scores, errors)

        # With payoff_type="none", scores should remain 0
        for agent in agents:
            assert agent.score == 0, f"Agent {agent.name} should have score 0 for none type"

    assert len(round_results) == 1
