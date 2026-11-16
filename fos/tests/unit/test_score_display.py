"""
Tests for score display visibility based on InformationModel.include_scores.

Verifies that scores are hidden when include_scores=False in coordination games.
"""
from fos.core.experiment.round_context import RoundContextManager
from fos.core.experiment.information_model import InformationModel


def test_score_hidden_when_include_scores_false():
    """Test that 'My score: 0' does not appear when include_scores=False."""
    # Create an InformationModel with include_scores=False (coordination game)
    info_model = InformationModel(
        scope_type="all",
        include_scores=False,
        recent_window=3,
    )

    # Create context manager with this model
    context_manager = RoundContextManager(
        information_model=info_model,
        all_agent_names=["Alice", "Bob"],
    )

    # Record some events
    context_manager.record_action(
        agent_name="Alice",
        action_name="coordinate",
        parameters={},
        round_num=1,
        summary="Alice coordinated",
        observed_by=["Alice", "Bob"],
        payoff=0,  # Even with a score
    )

    context_manager.record_action(
        agent_name="Bob",
        action_name="coordinate",
        parameters={},
        round_num=1,
        summary="Bob coordinated",
        observed_by=["Alice", "Bob"],
        payoff=0,
    )

    # Get context for Alice with agent_score=0
    context = context_manager.get_context_for_agent("Alice", agent_score=0)

    # Verify "My score" does NOT appear
    assert "My score" not in context, f"Score should be hidden when include_scores=False, but got: {context}"


def test_score_shown_when_include_scores_true():
    """Test that 'My score' DOES appear when include_scores=True (default)."""
    # Create an InformationModel with include_scores=True (default)
    info_model = InformationModel(
        scope_type="all",
        include_scores=True,  # Explicitly True
        recent_window=3,
    )

    # Create context manager with this model
    context_manager = RoundContextManager(
        information_model=info_model,
        all_agent_names=["Alice", "Bob"],
    )

    # Record some events
    context_manager.record_action(
        agent_name="Alice",
        action_name="choose",
        parameters={},
        round_num=1,
        summary="Alice chose",
        observed_by=["Alice", "Bob"],
        payoff=5,
    )

    # Get context for Alice with agent_score=10
    context = context_manager.get_context_for_agent("Alice", agent_score=10)

    # Verify "My score: 10" DOES appear
    assert "My score: 10" in context, f"Score should be shown when include_scores=True, but got: {context}"


def test_score_hidden_when_agent_score_is_none():
    """Test that score is hidden when agent_score=None regardless of include_scores."""
    # Create an InformationModel with include_scores=True
    info_model = InformationModel(
        scope_type="all",
        include_scores=True,
        recent_window=3,
    )

    # Create context manager with this model
    context_manager = RoundContextManager(
        information_model=info_model,
        all_agent_names=["Alice"],
    )

    # Record an event
    context_manager.record_action(
        agent_name="Alice",
        action_name="act",
        parameters={},
        round_num=1,
        summary="Alice acted",
        observed_by=["Alice"],
        payoff=5,
    )

    # Get context for Alice with agent_score=None
    context = context_manager.get_context_for_agent("Alice", agent_score=None)

    # Verify "My score" does NOT appear
    assert "My score" not in context, f"Score should be hidden when agent_score=None, but got: {context}"
