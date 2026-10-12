"""Test that round_context passes state and graph in get_context_for_agent."""
from fos.core.experiment.round_context import RoundContextManager
from fos.core.experiment.information_model import InformationModel
from fos.core.experiment.state import ExperimentState, AgentState


def test_round_context_passes_state_and_graph():
    """Test that get_context_for_agent shows neighbor-averaged contributions via graph."""
    ctx = RoundContextManager(
        information_model=InformationModel(
            scope_type="neighborhood",
            show_average_contribution=True,
        )
    )
    state = ExperimentState(agents={
        "Alice": AgentState(resources={"tokens": 20}, properties={"last_contribution": 0}),
        "Bob": AgentState(resources={"tokens": 15}, properties={"last_contribution": 5}),
        "Charlie": AgentState(resources={"tokens": 10}, properties={"last_contribution": 10}),
    })
    graph = {"edges": [("Alice", "Bob"), ("Alice", "Charlie")]}

    # Set scene state with graph and configure agent names for observer resolution
    ctx.scene_state = {"graph": graph, "state": state}
    ctx.all_agent_names = ["Alice", "Bob", "Charlie"]

    # Record events via the proper API
    ctx.record_action_with_observers(
        agent_name="Alice", action_name="allocate",
        parameters={"amount": 0}, round_num=1, summary="Alice allocated 0",
    )
    ctx.record_action_with_observers(
        agent_name="Bob", action_name="allocate",
        parameters={"amount": 5}, round_num=1, summary="Bob allocated 5",
    )
    ctx.record_action_with_observers(
        agent_name="Charlie", action_name="allocate",
        parameters={"amount": 10}, round_num=1, summary="Charlie allocated 10",
    )

    # Get context for Alice
    context = ctx.get_context_for_agent("Alice", agent_score=None)

    # Verify that context contains average contribution from 2 neighbors
    assert "Average contribution from 2 neighbors" in context or "7.5" in context or "7.50" in context
    # Verify individual contributions are NOT shown (averaged instead)
    assert "Bob allocated 5" not in context
    assert "Charlie allocated 10" not in context
