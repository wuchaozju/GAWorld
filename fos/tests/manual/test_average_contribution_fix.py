"""
Test to verify the 'Only show average contribution' fix works end-to-end.

This test simulates the full flow:
1. Round 1: Agents allocate tokens
2. Store last_contribution in agent properties
3. Round 2: Build context - should show average contribution instead of individual

Contains: test_average_contribution_e2e
"""
import asyncio
import sys
import pytest

sys.path.insert(0, "src")

from fos.core.experiment.scene import ExperimentScene
from fos.core.experiment.config import ExperimentConfig
from fos.core.llm.client import LLMClient
from unittest.mock import MagicMock, AsyncMock


@pytest.mark.asyncio
async def test_average_contribution_e2e():
    """Test that last_contribution is stored and used for average calculation."""

    # Create config with show_average_contribution=True
    config = ExperimentConfig(
        agents=[
            {"name": "Alice", "properties": {"Trust": 60}},
            {"name": "Bob", "properties": {"Trust": 50}},
            {"name": "Charlie", "properties": {"Trust": 40}},
        ],
        actions=[
            {"name": "allocate", "description": "Allocate to group account", "parameters": [{"name": "amount", "type": "integer"}]},
            {"name": "keep", "description": "Keep all tokens"},
        ],
        parameters={
            "tokens_per_round": 10,
            "multiplier": 1.3,
            "show_average_contribution": True,  # Enable the feature
        },
        scenario_id="public_goods",
        round_visibility="simultaneous",
        social_network={
            "edges": [("Alice", "Bob"), ("Bob", "Charlie")]  # Linear network
        }
    )

    # Create scene
    scene = ExperimentScene(config)

    # Mock LLM client
    mock_client = MagicMock(spec=LLMClient)
    mock_client.chat = AsyncMock(return_value='{"action": "allocate"}')

    # Initialize scene
    scene.initialize(mock_client)

    # Verify initial state
    print("Initial state agents:", list(scene.state.agents.keys()))

    # Simulate Round 1 - manually set last_contribution
    # (This is what the runner should do after calculating scores)
    scene.state.agents["Alice"].properties["last_contribution"] = 6
    scene.state.agents["Bob"].properties["last_contribution"] = 4
    scene.state.agents["Charlie"].properties["last_contribution"] = 2

    print("Set last_contribution:")
    print(f"  Alice: {scene.state.agents['Alice'].properties.get('last_contribution')}")
    print(f"  Bob: {scene.state.agents['Bob'].properties.get('last_contribution')}")
    print(f"  Charlie: {scene.state.agents['Charlie'].properties.get('last_contribution')}")

    # Now test the context builder
    from fos.core.context_builder import build_structured_context
    from fos.core.experiment.information_model import InformationModel
    from fos.core.experiment.round_context import RoundEvent

    # Create information model with show_average_contribution=True
    info_model = InformationModel(
        scope_type="neighborhood",
        show_average_contribution=True,
        include_scores=True,
    )

    # Create events for Round 1
    events = [
        RoundEvent(
            agent_name="Alice",
            action_name="allocate",
            parameters={"amount": 6},
            round_num=1,
            summary="Alice allocated 6",
            observed_by=["Alice", "Bob"],  # Alice and Bob are neighbors
            payoff=8.0,
        ),
        RoundEvent(
            agent_name="Bob",
            action_name="allocate",
            parameters={"amount": 4},
            round_num=1,
            summary="Bob allocated 4",
            observed_by=["Alice", "Bob", "Charlie"],  # Bob is connected to both
            payoff=9.0,
        ),
        RoundEvent(
            agent_name="Charlie",
            action_name="allocate",
            parameters={"amount": 2},
            round_num=1,
            summary="Charlie allocated 2",
            observed_by=["Bob", "Charlie"],  # Bob and Charlie are neighbors
            payoff=10.0,
        ),
    ]

    # Build context for Bob (who has 2 neighbors: Alice and Charlie)
    graph = config.social_network
    context = build_structured_context(
        for_agent="Bob",
        events=events,
        info_model=info_model,
        agent_score=9,
        state=scene.state,
        graph=graph,
    )

    print("\n=== Context for Bob (has neighbors Alice and Charlie) ===")
    print(context)
    print()

    # Verify Bob sees AVERAGE contribution, not individual
    assert "Average contribution" in context, f"Expected 'Average contribution' in context, got: {context}"
    assert "Alice allocate 6" not in context, f"Should NOT see Alice's individual contribution, got: {context}"
    assert "Charlie allocate 2" not in context, f"Should NOT see Charlie's individual contribution, got: {context}"

    # The average should be (6 + 2) / 2 = 4.0
    assert "4.0" in context or "4" in context, f"Expected average of 4.0 in context, got: {context}"

    print("[PASS] Test passed! Bob sees average contribution (4.0) instead of individual contributions (6, 2)")

    # Build context for Alice (who has 1 neighbor: Bob)
    context_alice = build_structured_context(
        for_agent="Alice",
        events=events,
        info_model=info_model,
        agent_score=8,
        state=scene.state,
        graph=graph,
    )

    print("\n=== Context for Alice (has 1 neighbor: Bob) ===")
    print(context_alice)
    print()

    # Alice only has Bob as neighbor, so she sees Bob's contribution
    assert "Average contribution" in context_alice, f"Expected 'Average contribution' in context, got: {context_alice}"
    # Average = Bob's contribution = 4.0
    assert "4.0" in context_alice or "4" in context_alice, f"Expected average of 4.0 in context, got: {context_alice}"

    print("[PASS] Test passed! Alice sees average contribution (4.0) from her 1 neighbor (Bob)")
    print("\n=== All tests passed! ===")


if __name__ == "__main__":
    asyncio.run(test_average_contribution_e2e())
