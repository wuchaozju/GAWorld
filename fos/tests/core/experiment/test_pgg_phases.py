"""
Unit tests for PGG phase management.

Tests phase alternation, budget reset timing, and action filtering.
"""

import pytest

from fos.core.experiment.scene import ExperimentScene
from fos.core.experiment.config import ExperimentConfig


class TestPGGPhaseManagement:
    """Tests for PGG phase management in ExperimentScene."""

    @pytest.fixture
    def scene(self):
        """Create ExperimentScene with PGG config."""
        config = ExperimentConfig(
            scenario_id="public_goods",
            agents=[
                {"name": "Alice", "properties": {}},
                {"name": "Bob", "properties": {}},
            ],
            actions=[{"name": "allocate"}, {"name": "keep"}],
            parameters={
                "resource_name": "tokens",
                "tokens_per_round": 20,
                "deduction_budget_per_phase": 10,
                "deduction_cost_ratio": 3.0,
            },
        )
        scene = ExperimentScene(config)
        # Initialize state manually for tests (normally done in initialize())
        scene._initialize_state()
        return scene

    def test_initial_phase_is_allocate(self, scene):
        """Scene starts in allocate phase."""
        assert scene.get_pgg_phase() == "allocate"

    def test_advance_to_deduct(self, scene):
        """Advancing from allocate goes to deduct."""
        scene.advance_pgg_phase()
        assert scene.get_pgg_phase() == "deduct"

    def test_advance_back_to_allocate(self, scene):
        """Advancing from deduct goes back to allocate."""
        scene.advance_pgg_phase()  # allocate -> deduct
        scene.advance_pgg_phase()  # deduct -> allocate
        assert scene.get_pgg_phase() == "allocate"

    def test_get_scene_actions_allocate_phase(self, scene):
        """Allocate phase shows allocate and keep actions."""
        actions = scene.get_scene_actions("Alice")
        assert "allocate" in actions
        assert "keep" in actions
        assert "reduce" not in actions

    def test_get_scene_actions_deduct_phase(self, scene):
        """Deduct phase shows reduce and skip actions."""
        scene.advance_pgg_phase()
        actions = scene.get_scene_actions("Alice")
        assert "reduce" in actions
        assert "skip" in actions
        assert "allocate" not in actions

    def test_get_scene_actions_deductions_disabled(self, scene):
        """Deduct phase is skipped when deduction_budget is 0 — stays in allocate."""
        scene.config.parameters["deduction_budget_per_phase"] = 0
        scene.advance_pgg_phase()
        # Phase stays "allocate" because deduct phase is skipped
        assert scene.get_pgg_phase() == "allocate"
        actions = scene.get_scene_actions("Alice")
        assert "reduce" not in actions
        assert "skip" not in actions
        assert "allocate" in actions
        assert "keep" in actions

    def test_get_scene_actions_non_pgg(self):
        """Non-PGG scenarios return None (no filtering)."""
        config = ExperimentConfig(
            scenario_id="prisoners_dilemma",
            agents=[{"name": "Alice", "properties": {}}],
            actions=[{"name": "cooperate"}, {"name": "defect"}],
        )
        scene = ExperimentScene(config)
        actions = scene.get_scene_actions("Alice")
        assert actions is None

    def test_reset_deduction_budgets(self, scene):
        """Budget reset sets all agents to config value."""
        # Manually modify budgets
        scene.state.agents["Alice"].resources["deduction_budget"] = 3
        scene.state.agents["Bob"].resources["deduction_budget"] = 7

        # Reset
        scene._reset_deduction_budgets()

        # All agents should have fresh budget
        assert scene.state.agents["Alice"].resources["deduction_budget"] == 10
        assert scene.state.agents["Bob"].resources["deduction_budget"] == 10

    def test_reset_deduction_budgets_to_zero(self, scene):
        """Reset with budget=0 clears all budgets."""
        scene.config.parameters["deduction_budget_per_phase"] = 0
        scene._reset_deduction_budgets()
        assert scene.state.agents["Alice"].resources["deduction_budget"] == 0
        assert scene.state.agents["Bob"].resources["deduction_budget"] == 0

    def test_phase_cycles_multiple_times(self, scene):
        """Phase correctly cycles through multiple rounds."""
        # Round 1: allocate -> deduct
        assert scene.get_pgg_phase() == "allocate"
        scene.advance_pgg_phase()
        assert scene.get_pgg_phase() == "deduct"

        # Round 2: allocate -> deduct
        scene.advance_pgg_phase()
        assert scene.get_pgg_phase() == "allocate"
        scene.advance_pgg_phase()
        assert scene.get_pgg_phase() == "deduct"

        # Round 3: allocate
        scene.advance_pgg_phase()
        assert scene.get_pgg_phase() == "allocate"
