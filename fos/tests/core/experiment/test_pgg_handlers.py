"""
Unit tests for PGG reduction handler.

Tests budget clamping, self-reduction prevention, and cost ratio calculation.
"""

import pytest
from unittest.mock import MagicMock

from fos.core.experiment.state import ExperimentState, AgentState
from fos.core.experiment.actions.handlers import handle_reduce


class TestHandleReduce:
    """Tests for handle_reduce action handler."""

    @pytest.fixture
    def mock_state(self):
        """Create mock state with two agents."""
        state = ExperimentState()
        state.agents["Alice"] = AgentState(
            score=0,
            resources={"tokens": 20, "deduction_budget": 10}
        )
        state.agents["Bob"] = AgentState(
            score=0,
            resources={"tokens": 20, "deduction_budget": 10}
        )
        state.extensions["reductions"] = {}
        return state

    @pytest.fixture
    def mock_scene(self):
        """Create mock scene with config."""
        scene = MagicMock()
        scene.config.parameters = {"deduction_budget_per_phase": 10, "deduction_cost_ratio": 3.0}
        return scene

    def test_no_self_reduction(self, mock_state, mock_scene):
        """Agents cannot reduce themselves."""
        result = handle_reduce(
            {"target": "Alice", "amount": 5},
            "Alice",
            mock_state,
            mock_scene
        )
        assert result["success"] is False
        assert "Cannot reduce your own" in result["error"]

    def test_unknown_target(self, mock_state, mock_scene):
        """Reduction fails for unknown target."""
        result = handle_reduce(
            {"target": "Charlie", "amount": 5},
            "Alice",
            mock_state,
            mock_scene
        )
        assert result["success"] is False
        assert "Unknown target" in result["error"]

    def test_clamp_to_budget(self, mock_state, mock_scene):
        """Amount is clamped to available budget."""
        # Alice only has 10 budget, tries to spend 15
        result = handle_reduce(
            {"target": "Bob", "amount": 15},
            "Alice",
            mock_state,
            mock_scene
        )
        assert result["success"] is True
        assert result["amount"] == 10  # Clamped to budget

    def test_cost_ratio_calculation(self, mock_state, mock_scene):
        """Deduction = amount * cost_ratio."""
        result = handle_reduce(
            {"target": "Bob", "amount": 3},
            "Alice",
            mock_state,
            mock_scene
        )
        assert result["success"] is True
        assert result["amount"] == 3
        assert result["deduction"] == 9.0  # 3 * 3.0

    def test_budget_deducted(self, mock_state, mock_scene):
        """Budget is deducted after reduction."""
        handle_reduce(
            {"target": "Bob", "amount": 4},
            "Alice",
            mock_state,
            mock_scene
        )
        assert mock_state.agents["Alice"].resources["deduction_budget"] == 6

    def test_disabled_when_budget_zero(self, mock_state):
        """Reduction fails when deduction_budget_per_phase is 0."""
        mock_scene = MagicMock()
        mock_scene.config.parameters = {"deduction_budget_per_phase": 0}
        result = handle_reduce(
            {"target": "Bob", "amount": 1},
            "Alice",
            mock_state,
            mock_scene
        )
        assert result["success"] is False
        assert "disabled" in result["error"].lower()

    def test_stores_in_extensions(self, mock_state, mock_scene):
        """Reduction is stored in state.extensions["reductions"]."""
        handle_reduce(
            {"target": "Bob", "amount": 5},
            "Alice",
            mock_state,
            mock_scene
        )
        assert "Alice" in mock_state.extensions["reductions"]
        assert len(mock_state.extensions["reductions"]["Alice"]) == 1
        assert mock_state.extensions["reductions"]["Alice"][0]["target"] == "Bob"
        assert mock_state.extensions["reductions"]["Alice"][0]["amount"] == 5

    def test_no_budget_remaining(self, mock_state, mock_scene):
        """Reduction fails when agent has no budget remaining."""
        # Exhaust Alice's budget
        mock_state.agents["Alice"].resources["deduction_budget"] = 0
        result = handle_reduce(
            {"target": "Bob", "amount": 1},
            "Alice",
            mock_state,
            mock_scene
        )
        assert result["success"] is False
        assert "No deduction budget remaining" in result["error"]
