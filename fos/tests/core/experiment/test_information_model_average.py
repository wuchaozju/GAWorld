"""Test get_neighbor_average calculation."""

from fos.core.experiment.information_model import InformationModel
from fos.core.experiment.state import ExperimentState, AgentState


class TestGetNeighborAverage:
    def test_empty_neighbors_returns_none(self):
        """Empty neighbors should return None."""
        model = InformationModel(
            scope_type="neighborhood",
            show_average_contribution=True,
        )

        state = ExperimentState(agents={"Alice": AgentState(resources={"tokens": 20})})
        graph = {"edges": []}  # No edges = no neighbors

        result = model.get_neighbor_average("Alice", state, graph)
        assert result is None

    def test_single_neighbor(self):
        """Single neighbor should return their contribution."""
        model = InformationModel(
            scope_type="neighborhood",
            show_average_contribution=True,
        )

        state = ExperimentState(agents={
            "Alice": AgentState(resources={"tokens": 20}, properties={"last_contribution": 0}),
            "Bob": AgentState(resources={"tokens": 15}, properties={"last_contribution": 5}),
        })
        graph = {"edges": [("Alice", "Bob")]}

        result = model.get_neighbor_average("Alice", state, graph)
        assert result == 5.0

    def test_multiple_neighbors(self):
        """Multiple neighbors should return correct average."""
        model = InformationModel(
            scope_type="neighborhood",
            show_average_contribution=True,
        )

        # Alice connected to Bob (contributed 5) and Charlie (contributed 10)
        state = ExperimentState(agents={
            "Alice": AgentState(resources={"tokens": 20}, properties={"last_contribution": 0}),
            "Bob": AgentState(resources={"tokens": 15}, properties={"last_contribution": 5}),
            "Charlie": AgentState(resources={"tokens": 10}, properties={"last_contribution": 10}),
        })
        graph = {"edges": [("Alice", "Bob"), ("Alice", "Charlie")]}

        result = model.get_neighbor_average("Alice", state, graph)
        # Average of 5 and 10 = 7.5
        assert result == 7.5

    def test_excludes_own_contribution(self):
        """CRITICAL: Agent's own contribution should NOT be included in average."""
        model = InformationModel(
            scope_type="neighborhood",
            show_average_contribution=True,
        )

        # Alice contributed 100, Bob contributed 5
        # Average should be 5 (Bob only), NOT (100+5)/2 = 52.5
        state = ExperimentState(agents={
            "Alice": AgentState(resources={"tokens": 20}, properties={"last_contribution": 100}),
            "Bob": AgentState(resources={"tokens": 15}, properties={"last_contribution": 5}),
        })
        graph = {"edges": [("Alice", "Bob")]}

        result = model.get_neighbor_average("Alice", state, graph)
        # Alice's own contribution (100) should NOT be in the average
        assert result == 5.0, f"Expected 5.0, got {result} - own contribution was incorrectly included!"
