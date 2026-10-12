"""
Tests for CoordinationFeedbackBuilder - generates coordination feedback for neighbor-based games.

Tests the feedback generation for graph coloring and other coordination games.
"""

import pytest
from fos.core.experiment.feedback.builder import CoordinationFeedbackBuilder


class TestCoordinationFeedbackBuilder:
    """Test CoordinationFeedbackBuilder class."""

    @pytest.fixture
    def builder(self):
        return CoordinationFeedbackBuilder()

    def test_builder_exists(self, builder):
        """CoordinationFeedbackBuilder can be instantiated."""
        assert builder is not None

    def test_all_coordinated_same_choice(self, builder):
        """All neighbors chose the same -> all coordinated."""
        feedback = builder.build_feedback(
            agent_name="Alice",
            agent_choice="red",
            neighbors=["Bob", "Charlie"],
            all_choices={"Alice": "red", "Bob": "red", "Charlie": "red"},
        )

        assert "Coordinated with: Bob (both red), Charlie (both red)" in feedback
        assert "Conflicted" not in feedback

    def test_all_conflicted_different_choices(self, builder):
        """All neighbors chose different -> all conflicted."""
        feedback = builder.build_feedback(
            agent_name="Alice",
            agent_choice="red",
            neighbors=["Bob", "Charlie"],
            all_choices={"Alice": "red", "Bob": "blue", "Charlie": "green"},
        )

        assert "Conflicted with: Bob (you red, they blue), Charlie (you red, they green)" in feedback
        assert "Coordinated" not in feedback

    def test_mixed_coordination_and_conflict(self, builder):
        """Some neighbors coordinated, some conflicted."""
        feedback = builder.build_feedback(
            agent_name="Alice",
            agent_choice="red",
            neighbors=["Bob", "Charlie", "Diana"],
            all_choices={"Alice": "red", "Bob": "red", "Charlie": "blue", "Diana": "red"},
        )

        assert "Coordinated with: Bob (both red), Diana (both red)" in feedback
        assert "Conflicted with: Charlie (you red, they blue)" in feedback

    def test_no_neighbors(self, builder):
        """No neighbors -> appropriate message."""
        feedback = builder.build_feedback(
            agent_name="Alice",
            agent_choice="red",
            neighbors=[],
            all_choices={"Alice": "red"},
        )

        assert "no neighbors" in feedback.lower()

    def test_case_insensitive_comparison(self, builder):
        """Choices should be compared case-insensitively."""
        feedback = builder.build_feedback(
            agent_name="Alice",
            agent_choice="Red",
            neighbors=["Bob"],
            all_choices={"Alice": "Red", "Bob": "red"},
        )

        assert "Coordinated with: Bob" in feedback
        assert "Conflicted" not in feedback

    def test_neighbor_not_in_choices_skipped(self, builder):
        """Neighbors without choices are skipped gracefully."""
        feedback = builder.build_feedback(
            agent_name="Alice",
            agent_choice="red",
            neighbors=["Bob", "Charlie"],
            all_choices={"Alice": "red", "Bob": "blue"},  # Charlie missing
        )

        # Should only mention Bob, not error on Charlie
        assert "Conflicted with: Bob (you red, they blue)" in feedback
        assert "Charlie" not in feedback

    def test_differ_goal_treats_different_choices_as_coordinated(self, builder):
        """When goal=differ, different choices should count as coordination."""
        feedback = builder.build_feedback(
            agent_name="Alice",
            agent_choice="red",
            neighbors=["Bob", "Charlie"],
            all_choices={"Alice": "red", "Bob": "blue", "Charlie": "red"},
            goal="differ",
        )

        assert "Coordinated with: Bob (you red, they blue)" in feedback
        assert "Conflicted with: Charlie (you red, they red)" in feedback
