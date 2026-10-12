"""
Smoke tests for game theory scenarios with real Ollama LLM.

Tests the following scenarios:
- Prisoner's Dilemma (pairwise, matrix)
- Battle of the Sexes (pairwise, matrix)
- Stag Hunt (group, matrix with threshold)
- Public Goods (group, pool)
"""

import pytest
from typing import Dict, Any, List

from fos.core.llm_config import LLMConfig
from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import GameConfig
from fos.core.experiment.runner import ExperimentRunner

from tests.smoke_tests.utils import (
    SmokeTestOutput,
    build_experiment_agent,
)


# =============================================================================
# Test Configuration Builders
# =============================================================================

def build_pd_config() -> GameConfig:
    """Build Prisoner's Dilemma game config."""
    return GameConfig(
        name="prisoners_dilemma",
        description=(
            "Two suspects are arrested and held separately. Each must decide "
            "whether to betray the other or remain silent.\n"
            "Payoffs: If both cooperate (remain silent), both get 3 points. "
            "If one defects (betrays) and other cooperates, defector gets 5 points, "
            "cooperator gets 0 points. If both defect, both get 1 point."
        ),
        action_type="discrete",
        actions=["cooperate", "defect"],
        action_descriptions={
            "cooperate": "Remain silent and cooperate with your partner",
            "defect": "Betray your partner and testify against them"
        },
        payoff_summary="Your payoff depends on both your choice and your partner's choice.",
        payoff_type="matrix",
        grouping_mode="pairwise",
        payoff_config={
            "matrix": {
                "cooperate_cooperate": {"value": 3},
                "cooperate_defect": {"row": 0, "col": 5},
                "defect_cooperate": {"row": 5, "col": 0},
                "defect_defect": {"value": 1},
            }
        }
    )


def build_bos_config() -> GameConfig:
    """Build Battle of the Sexes game config."""
    return GameConfig(
        name="battle_of_the_sexes",
        description=(
            "A couple wants to coordinate on an evening activity. "
            "One prefers opera, the other prefers football. "
            "They get positive payoff if they coordinate, but each prefers their own activity."
        ),
        action_type="discrete",
        actions=["opera", "football"],
        action_descriptions={
            "opera": "Go to the opera",
            "football": "Go to the football game"
        },
        payoff_summary="Coordinate on the same activity for positive payoff.",
        payoff_type="matrix",
        grouping_mode="pairwise",
        payoff_config={
            "matrix": {
                "opera_opera": {"row": 3, "col": 1},
                "opera_football": {"row": 0, "col": 0},
                "football_opera": {"row": 0, "col": 0},
                "football_football": {"row": 1, "col": 3},
            }
        }
    )


def build_stag_hunt_config() -> GameConfig:
    """Build Stag Hunt game config."""
    return GameConfig(
        name="stag_hunt",
        description=(
            "Hunters must all choose stag (high reward) or hare (safe but low reward). "
            "Stag requires everyone to cooperate. If even one person chooses hare, "
            "the stag escapes and stag hunters get nothing."
        ),
        action_type="discrete",
        actions=["stag", "hare"],
        action_descriptions={
            "stag": "Hunt the stag (requires all to cooperate)",
            "hare": "Hunt the hare (safe but lower reward)"
        },
        payoff_summary="Stag pays 5 if ALL choose it, else 0. Hare always pays 1.",
        payoff_type="matrix",
        grouping_mode="group",
        payoff_config={
            "group_payoff_mode": "threshold",
            "threshold_action": "stag",
            "threshold_reward": 5,
            "threshold_failure": 0,
            "safe_reward": 1,
        }
    )


def build_public_goods_config() -> GameConfig:
    """Build Public Goods game config."""
    return GameConfig(
        name="public_goods",
        description=(
            "Each agent has 20 tokens and decides how much to contribute to a shared pool. "
            "The pool is multiplied by 1.5 and distributed equally among all agents, "
            "regardless of contribution."
        ),
        action_type="discrete",
        actions=["contribute"],
        action_descriptions={
            "contribute": "Contribute some tokens to the pool"
        },
        payoff_summary="Payoff = (initial_tokens - contribution) + (total_pool * 1.5 / n)",
        payoff_type="pool",
        grouping_mode="group",
        payoff_config={
            "multiplier": 1.5,
            "initial_tokens": 20,
        }
    )


# =============================================================================
# Test Helpers
# =============================================================================

async def run_scenario_test(
    game_config: GameConfig,
    agents: List[ExperimentAgent],
    llm_client,
    max_rounds: int = 1,
    round_visibility: str = "simultaneous",
) -> Dict[str, Any]:
    """Run a scenario test and return results.

    Args:
        game_config: Game configuration
        agents: List of experiment agents
        llm_client: LLM client for prompts
        max_rounds: Number of rounds to run
        round_visibility: Visibility mode

    Returns:
        Dict with round_results, final_scores, errors
    """
    runner = ExperimentRunner(
        agents=agents,
        game_config=game_config,
        llm_client=llm_client,
        round_visibility=round_visibility,
    )

    round_results = await runner.run(max_rounds)

    final_scores = {agent.name: agent.score for agent in agents}
    errors = []

    for result in round_results:
        for action in result.actions:
            if action.error:
                errors.append(f"Round {result.round_num} - {action.agent_name}: {action.error}")

    return {
        "round_results": round_results,
        "final_scores": final_scores,
        "errors": errors,
    }


# =============================================================================
# Prisoner's Dilemma Tests
# =============================================================================

@pytest.mark.asyncio
async def test_pd_two_agents(default_llm_client, output_dir):
    """Test Prisoner's Dilemma with two agents making simultaneous choices."""
    game_config = build_pd_config()
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("Alice", llm_config, role_prompt="You are Alice, a cooperative person who values trust."),
        build_experiment_agent("Bob", llm_config, role_prompt="You are Bob, a pragmatic person who considers outcomes carefully."),
    ]

    # Create output file
    filename = "prisoners_dilemma_phi4-mini_two_agents.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "prisoners_dilemma", "phi4-mini", "two_agents") as out:
        out.write_config({
            "grouping_mode": "pairwise",
            "payoff_type": "matrix",
            "agents": ["Alice", "Bob"],
            "actions": ["cooperate", "defect"],
        })

        # Run the test
        result = await run_scenario_test(game_config, agents, default_llm_client, max_rounds=1)

        out.write_round_header(1)
        for action in result["round_results"][0].actions:
            out.write_action_summary(
                action.agent_name,
                action.action_name,
                action.parameters,
                result["round_results"][0].payoffs.get(action.agent_name) if result["round_results"][0].payoffs else None
            )

        out.write_summary(result["final_scores"], result["errors"])

    # Verify results
    assert len(result["round_results"]) == 1
    assert len(result["round_results"][0].actions) == 2
    for action in result["round_results"][0].actions:
        assert action.action_name in ["cooperate", "defect", "skip"]


@pytest.mark.asyncio
async def test_pd_four_agents_paired(default_llm_client, output_dir):
    """Test Prisoner's Dilemma with four agents in pairs."""
    game_config = build_pd_config()
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("Alice", llm_config, role_prompt="You are Alice."),
        build_experiment_agent("Bob", llm_config, role_prompt="You are Bob."),
        build_experiment_agent("Carol", llm_config, role_prompt="You are Carol."),
        build_experiment_agent("Dave", llm_config, role_prompt="You are Dave."),
    ]

    filename = "prisoners_dilemma_phi4-mini_four_agents.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "prisoners_dilemma", "phi4-mini", "four_agents") as out:
        out.write_config({
            "grouping_mode": "pairwise",
            "payoff_type": "matrix",
            "agents": ["Alice", "Bob", "Carol", "Dave"],
            "actions": ["cooperate", "defect"],
        })

        result = await run_scenario_test(game_config, agents, default_llm_client, max_rounds=1)

        out.write_round_header(1)
        for action in result["round_results"][0].actions:
            out.write_action_summary(
                action.agent_name,
                action.action_name,
                action.parameters,
                result["round_results"][0].payoffs.get(action.agent_name) if result["round_results"][0].payoffs else None
            )

        out.write_summary(result["final_scores"], result["errors"])

    assert len(result["round_results"]) == 1
    assert len(result["round_results"][0].actions) == 4


# =============================================================================
# Battle of the Sexes Tests
# =============================================================================

@pytest.mark.asyncio
async def test_bos_coordination(default_llm_client, output_dir):
    """Test Battle of the Sexes coordination game."""
    game_config = build_bos_config()
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("Partner1", llm_config, role_prompt="You prefer opera."),
        build_experiment_agent("Partner2", llm_config, role_prompt="You prefer football."),
    ]

    filename = "battle_of_sexes_phi4-mini_coordination.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "battle_of_sexes", "phi4-mini", "coordination") as out:
        out.write_config({
            "grouping_mode": "pairwise",
            "payoff_type": "matrix",
            "agents": ["Partner1", "Partner2"],
            "actions": ["opera", "football"],
        })

        result = await run_scenario_test(game_config, agents, default_llm_client, max_rounds=1)

        out.write_round_header(1)
        for action in result["round_results"][0].actions:
            out.write_action_summary(
                action.agent_name,
                action.action_name,
                action.parameters,
                result["round_results"][0].payoffs.get(action.agent_name) if result["round_results"][0].payoffs else None
            )

        out.write_summary(result["final_scores"], result["errors"])

    assert len(result["round_results"]) == 1
    assert len(result["round_results"][0].actions) == 2
    for action in result["round_results"][0].actions:
        assert action.action_name in ["opera", "football", "skip"]


# =============================================================================
# Stag Hunt Tests
# =============================================================================

@pytest.mark.asyncio
async def test_stag_hunt_group(default_llm_client, output_dir):
    """Test Stag Hunt with group threshold payoff."""
    game_config = build_stag_hunt_config()
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("Hunter1", llm_config, role_prompt="You are Hunter1."),
        build_experiment_agent("Hunter2", llm_config, role_prompt="You are Hunter2."),
        build_experiment_agent("Hunter3", llm_config, role_prompt="You are Hunter3."),
    ]

    filename = "stag_hunt_phi4-mini_group.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "stag_hunt", "phi4-mini", "group") as out:
        out.write_config({
            "grouping_mode": "group",
            "payoff_type": "matrix",
            "agents": ["Hunter1", "Hunter2", "Hunter3"],
            "actions": ["stag", "hare"],
        })

        result = await run_scenario_test(game_config, agents, default_llm_client, max_rounds=1)

        out.write_round_header(1)
        for action in result["round_results"][0].actions:
            out.write_action_summary(
                action.agent_name,
                action.action_name,
                action.parameters,
                result["round_results"][0].payoffs.get(action.agent_name) if result["round_results"][0].payoffs else None
            )

        out.write_summary(result["final_scores"], result["errors"])

    assert len(result["round_results"]) == 1
    assert len(result["round_results"][0].actions) == 3
    for action in result["round_results"][0].actions:
        assert action.action_name in ["stag", "hare", "skip"]


# =============================================================================
# Public Goods Tests
# =============================================================================

@pytest.mark.asyncio
async def test_public_goods_pool(default_llm_client, output_dir):
    """Test Public Goods with pool payoff calculation."""
    game_config = build_public_goods_config()
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("Player1", llm_config, role_prompt="You are Player1 with 20 tokens."),
        build_experiment_agent("Player2", llm_config, role_prompt="You are Player2 with 20 tokens."),
        build_experiment_agent("Player3", llm_config, role_prompt="You are Player3 with 20 tokens."),
    ]

    filename = "public_goods_phi4-mini_pool.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "public_goods", "phi4-mini", "pool") as out:
        out.write_config({
            "grouping_mode": "group",
            "payoff_type": "pool",
            "agents": ["Player1", "Player2", "Player3"],
            "actions": ["contribute"],
            "initial_tokens": 20,
            "multiplier": 1.5,
        })

        result = await run_scenario_test(game_config, agents, default_llm_client, max_rounds=1)

        out.write_round_header(1)
        for action in result["round_results"][0].actions:
            out.write_action_summary(
                action.agent_name,
                action.action_name,
                action.parameters,
                result["round_results"][0].payoffs.get(action.agent_name) if result["round_results"][0].payoffs else None
            )

        out.write_summary(result["final_scores"], result["errors"])

    assert len(result["round_results"]) == 1
    assert len(result["round_results"][0].actions) == 3


# =============================================================================
# Multi-round Tests
# =============================================================================

@pytest.mark.asyncio
async def test_pd_two_rounds(default_llm_client, output_dir):
    """Test Prisoner's Dilemma over two rounds to verify context building."""
    game_config = build_pd_config()
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("Alice", llm_config, role_prompt="You are Alice."),
        build_experiment_agent("Bob", llm_config, role_prompt="You are Bob."),
    ]

    filename = "prisoners_dilemma_phi4-mini_two_rounds.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "prisoners_dilemma", "phi4-mini", "two_rounds") as out:
        out.write_config({
            "grouping_mode": "pairwise",
            "payoff_type": "matrix",
            "agents": ["Alice", "Bob"],
            "actions": ["cooperate", "defect"],
            "rounds": 2,
        })

        result = await run_scenario_test(game_config, agents, default_llm_client, max_rounds=2)

        for round_result in result["round_results"]:
            out.write_round_header(round_result.round_num)
            for action in round_result.actions:
                out.write_action_summary(
                    action.agent_name,
                    action.action_name,
                    action.parameters,
                    round_result.payoffs.get(action.agent_name) if round_result.payoffs else None
                )

        out.write_summary(result["final_scores"], result["errors"])

    assert len(result["round_results"]) == 2
