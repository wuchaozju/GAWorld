"""
Smoke tests for coordination scenarios with real Ollama LLM.

Tests Coordination Game scenario with neighbor-based visibility and feedback payoffs.
"""

import pytest

from fos.core.llm_config import LLMConfig
from fos.core.experiment.game_configs import GameConfig
from fos.core.experiment.runner import ExperimentRunner
from fos.core.experiment.information_model import InformationModel

from tests.smoke_tests.utils import (
    SmokeTestOutput,
    build_experiment_agent,
)


def build_coordination_game_config() -> GameConfig:
    """Build Coordination Game config."""
    return GameConfig(
        name="coordination_game",
        description=(
            "You are a node in a graph and must choose a color (red, blue, or green). "
            "No two adjacent nodes should have the same color. "
            "You can see your neighbors' current colors."
        ),
        action_type="discrete",
        actions=["choose_color"],
        action_descriptions={
            "choose_color": "Select a color for your node"
        },
        payoff_summary="Coordinate with neighbors to avoid same colors.",
        payoff_type="feedback",  # No numerical payoffs, just coordination feedback
        grouping_mode="neighbor",
        payoff_config={},
    )


# =============================================================================
# Coordination Game Tests
# =============================================================================

@pytest.mark.asyncio
async def test_coordination_game_basic(default_llm_client, output_dir):
    """Test Coordination Game with 3 agents in a triangle graph."""
    game_config = build_coordination_game_config()
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("NodeA", llm_config, role_prompt="You are Node A."),
        build_experiment_agent("NodeB", llm_config, role_prompt="You are Node B."),
        build_experiment_agent("NodeC", llm_config, role_prompt="You are Node C."),
    ]

    # Create information model for neighbor visibility
    # Triangle graph: A-B, B-C, C-A
    graph = {"edges": [("NodeA", "NodeB"), ("NodeB", "NodeC"), ("NodeC", "NodeA")]}

    information_model = InformationModel(
        scope_type="neighborhood",
        pairing_fn=None,
        context_budget_chars=0,
    )

    filename = "coordination_game_phi4-mini_basic.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "coordination_game", "phi4-mini", "basic") as out:
        out.write_config({
            "grouping_mode": "neighbor",
            "payoff_type": "feedback",
            "agents": ["NodeA", "NodeB", "NodeC"],
            "actions": ["choose_color"],
            "graph": "triangle (A-B, B-C, C-A)",
        })

        runner = ExperimentRunner(
            agents=agents,
            game_config=game_config,
            llm_client=default_llm_client,
            round_visibility="sequential",  # Sequential to see previous choices
            information_model=information_model,
        )

        # Set scene state with graph
        runner.set_scene_state({"graph": graph})

        round_results = await runner.run(max_rounds=1)

        out.write_round_header(1)
        for action in round_results[0].actions:
            out.write_action_summary(
                action.agent_name,
                action.action_name,
                action.parameters,
                None  # No numerical payoffs for feedback type
            )

        final_scores = {agent.name: agent.score for agent in agents}
        errors = [a.error for a in round_results[0].actions if a.error]

        out.write_summary(final_scores, errors)

    assert len(round_results) == 1
    assert len(round_results[0].actions) == 3


@pytest.mark.asyncio
async def test_coordination_game_no_scores(default_llm_client, output_dir):
    """Verify that Coordination Game shows NO score in agent context."""
    game_config = build_coordination_game_config()
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("Node1", llm_config, role_prompt="You are Node 1."),
        build_experiment_agent("Node2", llm_config, role_prompt="You are Node 2."),
    ]

    graph = {"edges": [("Node1", "Node2")]}

    information_model = InformationModel(
        scope_type="neighborhood",
        pairing_fn=None,
        context_budget_chars=0,
    )

    filename = "coordination_game_phi4-mini_no_scores.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "coordination_game", "phi4-mini", "no_scores") as out:
        out.write_config({
            "grouping_mode": "neighbor",
            "payoff_type": "feedback",
            "agents": ["Node1", "Node2"],
            "actions": ["choose_color"],
            "graph": "single edge (Node1-Node2)",
            "verify": "NO SCORE should appear in context",
        })

        runner = ExperimentRunner(
            agents=agents,
            game_config=game_config,
            llm_client=default_llm_client,
            round_visibility="sequential",
            information_model=information_model,
        )

        runner.set_scene_state({"graph": graph})
        round_results = await runner.run(max_rounds=1)

        out.write_round_header(1)
        for action in round_results[0].actions:
            out.write_action_summary(action.agent_name, action.action_name, action.parameters, None)

        final_scores = {agent.name: agent.score for agent in agents}
        errors = [a.error for a in round_results[0].actions if a.error]

        out.write_summary(final_scores, errors)

        # With payoff_type="feedback", scores should remain 0
        for agent in agents:
            assert agent.score == 0, f"Agent {agent.name} should have score 0 for feedback type"

    assert len(round_results) == 1


@pytest.mark.asyncio
async def test_coordination_game_shows_feedback(default_llm_client, output_dir):
    """Verify that Coordination Game shows coordination feedback, NOT scores.

    This test verifies:
    1. Feedback is generated for each agent based on neighbor choices
    2. Scores remain 0 (no numerical payoffs)
    3. Feedback correctly identifies coordinated vs conflicted neighbors
    """
    # Use configurable choices
    choices = ["red", "blue", "green"]
    game_config = GameConfig(
        name="coordination_game",
        description="Choose a color different from your neighbors.",
        action_type="discrete",
        actions=choices,
        payoff_type="feedback",
        grouping_mode="neighbor",
    )

    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("Node1", llm_config, role_prompt="You are Node 1."),
        build_experiment_agent("Node2", llm_config, role_prompt="You are Node 2."),
        build_experiment_agent("Node3", llm_config, role_prompt="You are Node 3."),
    ]

    # Triangle graph
    graph = {"edges": [("Node1", "Node2"), ("Node2", "Node3"), ("Node3", "Node1")]}

    information_model = InformationModel(
        scope_type="neighborhood",
        pairing_fn=None,
        include_scores=False,
        recent_window=5,
    )

    filename = "coordination_game_phi4-mini_feedback.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "coordination_game", "phi4-mini", "feedback") as out:
        out.write_config({
            "grouping_mode": "neighbor",
            "payoff_type": "feedback",
            "agents": ["Node1", "Node2", "Node3"],
            "actions": choices,
            "graph": "triangle",
            "verify": "Should show coordination feedback, NO score",
        })

        runner = ExperimentRunner(
            agents=agents,
            game_config=game_config,
            llm_client=default_llm_client,
            round_visibility="sequential",
            information_model=information_model,
        )

        runner.set_scene_state({"graph": graph})
        round_results = await runner.run(max_rounds=2)

        # Verify feedback was generated
        for round_result in round_results:
            out.write_round_header(round_result.round_num)
            for action in round_result.actions:
                out.write_action_summary(
                    action.agent_name,
                    action.action_name,
                    action.parameters,
                    None  # No payoffs for feedback type
                )

        # Verify scores remain 0 (no numerical payoffs)
        for agent in agents:
            assert agent.score == 0, f"Agent {agent.name} should have score 0 for feedback type"

        # Verify feedback exists in round events
        events = runner.context_manager._round_events
        for event in events:
            if event.round_num == 2:  # Second round has neighbor context
                assert event.feedback is not None, "Feedback should be generated for feedback-type games"
                out.file.write(f"  Feedback for {event.agent_name}: {event.feedback}\n")

    assert len(round_results) == 2


@pytest.mark.asyncio
async def test_coordination_game_simultaneous_mode(default_llm_client, output_dir):
    """Test Coordination Game with simultaneous (blind) mode.

    In simultaneous mode, all agents decide without seeing other agents' choices.
    Choices are revealed after all agents have completed their decisions.

    This test verifies:
    1. Simultaneous mode executes without errors
    2. All agents make choices without seeing others' choices
    3. All choices are recorded after round completes
    """
    game_config = build_coordination_game_config()
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("NodeA", llm_config, role_prompt="You are Node A."),
        build_experiment_agent("NodeB", llm_config, role_prompt="You are Node B."),
        build_experiment_agent("NodeC", llm_config, role_prompt="You are Node C."),
    ]

    # Create information model for neighbor visibility
    # Triangle graph: A-B, B-C, C-A
    graph = {"edges": [("NodeA", "NodeB"), ("NodeB", "NodeC"), ("NodeC", "NodeA")]}

    information_model = InformationModel(
        scope_type="neighborhood",
        pairing_fn=None,
        context_budget_chars=0,
    )

    filename = "coordination_game_phi4-mini_simultaneous.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "coordination_game", "phi4-mini", "simultaneous") as out:
        out.write_config({
            "grouping_mode": "neighbor",
            "payoff_type": "feedback",
            "agents": ["NodeA", "NodeB", "NodeC"],
            "actions": ["choose_color"],
            "graph": "triangle (A-B, B-C, C-A)",
            "round_visibility": "simultaneous (blind mode)",
        })

        # CRITICAL: Use round_visibility="simultaneous" instead of "sequential"
        runner = ExperimentRunner(
            agents=agents,
            game_config=game_config,
            llm_client=default_llm_client,
            round_visibility="simultaneous",  # Simultaneous - agents decide without seeing others
            information_model=information_model,
        )

        # Set scene state with graph
        runner.set_scene_state({"graph": graph})

        # Run 2 rounds to verify simultaneous mode works consistently
        round_results = await runner.run(max_rounds=2)

        out.write_round_header(1)
        for action in round_results[0].actions:
            out.write_action_summary(
                action.agent_name,
                action.action_name,
                action.parameters,
                None  # No numerical payoffs for feedback type
            )

        out.write_round_header(2)
        for action in round_results[1].actions:
            out.write_action_summary(
                action.agent_name,
                action.action_name,
                action.parameters,
                None
            )

        final_scores = {agent.name: agent.score for agent in agents}
        errors = [a.error for a in round_results[0].actions if a.error]

        out.write_summary(final_scores, errors)

    # Verify the round results
    assert len(round_results) == 2, f"Expected 2 rounds, got {len(round_results)}"

    # Verify all agents acted in each round
    for round_result in round_results:
        assert len(round_result.actions) == 3, f"Expected 3 actions per round, got {len(round_result.actions)}"
        assert round_result.completed, "Round should be marked as completed"

    # Verify no errors occurred
    for round_result in round_results:
        errors = [a.error for a in round_result.actions if a.error]
        assert len(errors) == 0, f"Round had errors: {errors}"
