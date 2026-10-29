"""
Smoke tests for Werewolf scenario with real Ollama LLM.

NOTE: Werewolf is currently unsupported/inactive. These tests are skipped
because the scenario requires a dedicated role/phase runtime.
Do not remove — they serve as a regression baseline for future re-enablement.
"""

import pytest

pytestmark = pytest.mark.skip(
    reason="Werewolf is currently unsupported/inactive — requires dedicated role/phase runtime"
)

from fos.core.llm_config import LLMConfig  # noqa: E402
from fos.core.experiment.game_configs import GameConfig  # noqa: E402
from fos.core.experiment.runner import ExperimentRunner  # noqa: E402
from fos.core.experiment.kernel import ExperimentKernel, SpeakAction, VoteAction  # noqa: E402

from tests.smoke_tests.utils import (  # noqa: E402
    SmokeTestOutput,
    build_experiment_agent,
)


def build_werewolf_config() -> GameConfig:
    """Build Werewolf game config."""
    return GameConfig(
        name="werewolf",
        description=(
            "A social deduction game where villagers try to identify werewolves among them "
            "while werewolves try to eliminate villagers at night.\n\n"
            "It is day. You must discuss and vote to eliminate a suspect.\n"
            "Available actions:\n"
            "- speak: Share your thoughts with the group\n"
            "- vote: Vote to eliminate a suspect"
        ),
        action_type="discrete",
        actions=["speak", "vote"],
        action_descriptions={
            "speak": "Share your thoughts",
            "vote": "Vote to eliminate a suspect",
        },
        payoff_summary="",
        payoff_type="none",
        grouping_mode="role_based",
        payoff_config={},
    )


# =============================================================================
# Werewolf Tests
# =============================================================================

@pytest.mark.asyncio
async def test_werewolf_voting(default_llm_client, output_dir):
    """Test Werewolf with voting and speaking actions."""
    game_config = build_werewolf_config()
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("Villager1", llm_config, role_prompt="You are a villager trying to find the werewolf."),
        build_experiment_agent("Villager2", llm_config, role_prompt="You are a villager who is suspicious of everyone."),
        build_experiment_agent("Werewolf1", llm_config, role_prompt="You are a werewolf pretending to be a villager."),
        build_experiment_agent("Seer", llm_config, role_prompt="You are the seer. You know Werewolf1 is a werewolf."),
        build_experiment_agent("Villager3", llm_config, role_prompt="You are a villager who wants to hear more discussion."),
    ]

    # Create kernel with speak and vote actions
    kernel = ExperimentKernel()
    kernel.register("speak", SpeakAction)
    kernel.register("vote", VoteAction)

    filename = "werewolf_phi4-mini_voting.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "werewolf", "phi4-mini", "voting") as out:
        out.write_config({
            "grouping_mode": "role_based",
            "payoff_type": "none",
            "agents": ["Villager1", "Villager2", "Werewolf1", "Seer", "Villager3"],
            "actions": ["speak", "vote"],
            "roles": {"Werewolf1": "werewolf", "Seer": "seer"},
        })

        runner = ExperimentRunner(
            agents=agents,
            game_config=game_config,
            llm_client=default_llm_client,
            round_visibility="sequential",  # Sequential for day discussion
            kernel=kernel,
        )

        round_results = await runner.run(max_rounds=1)

        out.write_round_header(1)
        for action in round_results[0].actions:
            out.write_action_summary(action.agent_name, action.action_name, action.parameters, None)

        final_scores = {agent.name: agent.score for agent in agents}
        errors = [a.error for a in round_results[0].actions if a.error]

        out.write_summary(final_scores, errors)

    assert len(round_results) == 1
    assert len(round_results[0].actions) == 5
    valid_actions = ["speak", "vote", "skip"]
    for action in round_results[0].actions:
        assert action.action_name in valid_actions


@pytest.mark.asyncio
async def test_werewolf_two_rounds(default_llm_client, output_dir):
    """Test Werewolf over two rounds to verify context building."""
    game_config = build_werewolf_config()
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("Villager1", llm_config, role_prompt="You are a villager."),
        build_experiment_agent("Villager2", llm_config, role_prompt="You are a villager."),
        build_experiment_agent("Werewolf", llm_config, role_prompt="You are a werewolf pretending to be a villager."),
    ]

    kernel = ExperimentKernel()
    kernel.register("speak", SpeakAction)
    kernel.register("vote", VoteAction)

    filename = "werewolf_phi4-mini_two_rounds.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "werewolf", "phi4-mini", "two_rounds") as out:
        out.write_config({
            "grouping_mode": "role_based",
            "payoff_type": "none",
            "agents": ["Villager1", "Villager2", "Werewolf"],
            "actions": ["speak", "vote"],
            "rounds": 2,
        })

        runner = ExperimentRunner(
            agents=agents,
            game_config=game_config,
            llm_client=default_llm_client,
            round_visibility="sequential",
            kernel=kernel,
        )

        round_results = await runner.run(max_rounds=2)

        for round_result in round_results:
            out.write_round_header(round_result.round_num)
            for action in round_result.actions:
                out.write_action_summary(action.agent_name, action.action_name, action.parameters, None)

        final_scores = {agent.name: agent.score for agent in agents}
        errors = []
        for rr in round_results:
            errors.extend([a.error for a in rr.actions if a.error])

        out.write_summary(final_scores, errors)

    assert len(round_results) == 2
