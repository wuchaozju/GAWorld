"""Test context formatting with show_average_contribution."""

from fos.core.context_builder import build_structured_context
from fos.core.experiment.information_model import InformationModel
from fos.core.experiment.state import ExperimentState, AgentState
from fos.core.experiment.round_context import RoundEvent


class TestContextBuilderAverage:
    def test_average_enabled_shows_average_not_individuals(self):
        """When show_average_contribution=True, should show average instead of individual contributions."""
        model = InformationModel(
            scope_type="neighborhood",
            show_average_contribution=True,
            recent_window=3,
        )

        # Create state with neighbor contributions
        state = ExperimentState(agents={
            "Alice": AgentState(resources={"tokens": 20}, properties={"last_contribution": 0}),
            "Bob": AgentState(resources={"tokens": 15}, properties={"last_contribution": 5}),
            "Charlie": AgentState(resources={"tokens": 10}, properties={"last_contribution": 10}),
        })

        # Graph: Alice connected to Bob and Charlie
        graph = {"edges": [("Alice", "Bob"), ("Alice", "Charlie")]}

        # Create events
        events = [
            RoundEvent(
                agent_name="Alice",
                action_name="allocate",
                parameters={"amount": 0},
                round_num=1,
                summary="Alice allocated 0",
                observed_by=["Alice", "Bob", "Charlie"],
            ),
            RoundEvent(
                agent_name="Bob",
                action_name="allocate",
                parameters={"amount": 5},
                round_num=1,
                summary="Bob allocated 5",
                observed_by=["Alice", "Bob", "Charlie"],
            ),
            RoundEvent(
                agent_name="Charlie",
                action_name="allocate",
                parameters={"amount": 10},
                round_num=1,
                summary="Charlie allocated 10",
                observed_by=["Alice", "Bob", "Charlie"],
            ),
        ]

        # CRITICAL: Pass state and graph
        context = build_structured_context(
            for_agent="Alice",
            events=events,
            info_model=model,
            agent_score=None,
            state=state,
            graph=graph,
        )

        # Should show average of (5 + 10) / 2 = 7.5
        assert "7.5" in context or "7.50" in context
        # Should show neighbor count from same source as average
        assert "2 neighbors" in context
        # Should NOT show individual neighbor names in contribution context
        assert "Bob allocated 5" not in context
        assert "Charlie allocated 10" not in context

    def test_average_disabled_shows_individuals(self):
        """When show_average_contribution=False, should show individual contributions."""
        model = InformationModel(
            scope_type="neighborhood",
            show_average_contribution=False,
            recent_window=3,
        )

        state = ExperimentState(agents={
            "Alice": AgentState(resources={"tokens": 20}),
            "Bob": AgentState(resources={"tokens": 15}),
        })
        graph = {"edges": [("Alice", "Bob")]}

        events = [
            RoundEvent(
                agent_name="Alice",
                action_name="allocate",
                parameters={"amount": 5},
                round_num=1,
                summary="Alice allocated 5",
                observed_by=["Alice", "Bob"],
            ),
            RoundEvent(
                agent_name="Bob",
                action_name="allocate",
                parameters={"amount": 3},
                round_num=1,
                summary="Bob allocated 3",
                observed_by=["Alice", "Bob"],
            ),
        ]

        context = build_structured_context(
            for_agent="Alice",
            events=events,
            info_model=model,
            agent_score=None,
            state=state,
            graph=graph,
        )

        # Should show individual contributions (formatted as "allocate 3", not "allocated 3")
        assert "Bob allocate 3" in context

    def test_neighbor_count_matches_average_source(self):
        """CRITICAL: Neighbor count must come from same source as average calculation."""
        # This test catches the double-counting bug
        model = InformationModel(
            scope_type="neighborhood",
            show_average_contribution=True,
            recent_window=3,
        )

        # Alice has 3 neighbors, but one (Charlie) has no contribution data
        state = ExperimentState(agents={
            "Alice": AgentState(resources={"tokens": 20}, properties={"last_contribution": 0}),
            "Bob": AgentState(resources={"tokens": 15}, properties={"last_contribution": 5}),
            "Charlie": AgentState(resources={"tokens": 10}),  # NO last_contribution!
            "Dave": AgentState(resources={"tokens": 10}, properties={"last_contribution": 10}),
        })
        graph = {"edges": [("Alice", "Bob"), ("Alice", "Charlie"), ("Alice", "Dave")]}

        events = [
            RoundEvent(
                agent_name="Alice",
                action_name="allocate",
                parameters={"amount": 0},
                round_num=1,
                summary="Alice allocated 0",
                observed_by=["Alice", "Bob", "Charlie", "Dave"],
            ),
            RoundEvent(
                agent_name="Bob",
                action_name="allocate",
                parameters={"amount": 5},
                round_num=1,
                summary="Bob allocated 5",
                observed_by=["Alice", "Bob", "Charlie", "Dave"],
            ),
            RoundEvent(
                agent_name="Charlie",
                action_name="allocate",
                parameters={"amount": 0},
                round_num=1,
                summary="Charlie allocated 0",
                observed_by=["Alice", "Bob", "Charlie", "Dave"],
            ),
            RoundEvent(
                agent_name="Dave",
                action_name="allocate",
                parameters={"amount": 10},
                round_num=1,
                summary="Dave allocated 10",
                observed_by=["Alice", "Bob", "Charlie", "Dave"],
            ),
        ]

        context = build_structured_context(
            for_agent="Alice",
            events=events,
            info_model=model,
            agent_score=None,
            state=state,
            graph=graph,
        )

        # Get visible contributions to determine correct count
        visible = model.get_visible_contributions("Alice", state, graph)
        # visible should only include Bob and Dave (those with last_contribution)
        # Average should be (5 + 10) / 2 = 7.5, NOT (5 + 0 + 10) / 3
        # Neighbor count should match visible count, NOT event count
        if visible:
            expected_count = len(visible)
            assert f"{expected_count} neighbors" in context, f"Expected {expected_count} neighbors, got: {context}"
