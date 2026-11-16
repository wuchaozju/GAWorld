"""
Smoke tests for Grid World scenario with real Ollama LLM.

Tests movement, gathering, and rest actions in a grid environment.
"""

import pytest

from fos.core.llm_config import LLMConfig
from fos.core.experiment.game_configs import GameConfig
from fos.core.experiment.runner import ExperimentRunner

from tests.smoke_tests.utils import (
    SmokeTestOutput,
    build_experiment_agent,
)


def build_grid_world_config() -> GameConfig:
    """Build Grid World game config."""
    return GameConfig(
        name="grid_world",
        description=(
            "You are on a 10x10 grid. You can move, look around, gather resources, or rest.\n"
            "Resources are scattered across the grid. Your goal is to explore and gather.\n\n"
            "Available actions:\n"
            "- move_to_location: Move to a specific location\n"
            "- look_around: Observe your surroundings\n"
            "- gather_resource: Collect a resource at your location\n"
            "- rest: Skip your turn"
        ),
        action_type="discrete",
        actions=["move_to_location", "look_around", "gather_resource", "rest"],
        action_descriptions={
            "move_to_location": "Move to a location",
            "look_around": "Observe surroundings",
            "gather_resource": "Collect a resource",
            "rest": "Do nothing this turn",
        },
        payoff_summary="",
        payoff_type="none",
        grouping_mode="neighbor",
        payoff_config={},
    )


# =============================================================================
# Grid World Tests
# =============================================================================

@pytest.mark.asyncio
async def test_grid_world_movement(default_llm_client, output_dir):
    """Test Grid World with movement and gathering actions."""
    game_config = build_grid_world_config()
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("Explorer1", llm_config, role_prompt="You are an explorer who likes to discover new areas."),
        build_experiment_agent("Explorer2", llm_config, role_prompt="You are a gatherer who focuses on collecting resources."),
    ]

    filename = "grid_world_phi4-mini_movement.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "grid_world", "phi4-mini", "movement") as out:
        out.write_config({
            "grouping_mode": "neighbor",
            "payoff_type": "none",
            "agents": ["Explorer1", "Explorer2"],
            "actions": ["move_to_location", "look_around", "gather_resource", "rest"],
            "grid_size": "10x10",
        })

        runner = ExperimentRunner(
            agents=agents,
            game_config=game_config,
            llm_client=default_llm_client,
            round_visibility="simultaneous",
        )

        # Set initial scene state
        runner.set_scene_state({
            "grid_size": 10,
            "resources": [(3, 3), (5, 7), (8, 2)],
        })

        round_results = await runner.run(max_rounds=1)

        out.write_round_header(1)
        for action in round_results[0].actions:
            out.write_action_summary(action.agent_name, action.action_name, action.parameters, None)

        final_scores = {agent.name: agent.score for agent in agents}
        errors = [a.error for a in round_results[0].actions if a.error]

        out.write_summary(final_scores, errors)

    assert len(round_results) == 1
    assert len(round_results[0].actions) == 2
    valid_actions = ["move_to_location", "look_around", "gather_resource", "rest", "skip"]
    for action in round_results[0].actions:
        assert action.action_name in valid_actions


@pytest.mark.asyncio
async def test_grid_world_no_scores(default_llm_client, output_dir):
    """Verify that Grid World has NO score in context."""
    game_config = build_grid_world_config()
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("Agent1", llm_config, role_prompt="You are Agent 1."),
        build_experiment_agent("Agent2", llm_config, role_prompt="You are Agent 2."),
    ]

    filename = "grid_world_phi4-mini_no_scores.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "grid_world", "phi4-mini", "no_scores") as out:
        out.write_config({
            "grouping_mode": "neighbor",
            "payoff_type": "none",
            "agents": ["Agent1", "Agent2"],
            "actions": ["move_to_location", "look_around", "gather_resource", "rest"],
            "verify": "NO SCORE should appear in context",
        })

        runner = ExperimentRunner(
            agents=agents,
            game_config=game_config,
            llm_client=default_llm_client,
            round_visibility="simultaneous",
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
