"""
Tests for context builder visibility filtering.

Verifies that agents only see events they can observe based on observed_by field.

Contains: test_visibility_filtering
"""

from fos.core.context_builder import build_structured_context
from fos.core.experiment.information_model import InformationModel
from fos.core.experiment.round_context import RoundEvent


def test_visibility_filtering():
    """Events should be filtered by observed_by, not just excluded by agent name.

    Agent 1 sees only Agent 2 (not Agent 3).
    Agent 2 sees only Agent 1 (not Agent 3).
    Agent 3 sees only Agent 1 (not Agent 2).
    """
    # Agent 1 sees only Agent 2 (not Agent 3)
    event1 = RoundEvent(
        agent_name="Agent 1",
        action_name="red",
        parameters={},
        round_num=1,
        summary="Agent 1 chose red",
        observed_by=["Agent 1", "Agent 2", "Agent 3"],
    )
    # Agent 2 sees only Agent 1 (not Agent 3)
    event2 = RoundEvent(
        agent_name="Agent 2",
        action_name="blue",
        parameters={},
        round_num=1,
        summary="Agent 2 chose blue",
        observed_by=["Agent 1", "Agent 2"],
    )
    # Agent 3 sees only Agent 1 (not Agent 2)
    event3 = RoundEvent(
        agent_name="Agent 3",
        action_name="green",
        parameters={},
        round_num=1,
        summary="Agent 3 chose green",
        observed_by=["Agent 3"],
    )

    info_model = InformationModel(scope_type="neighborhood", include_scores=False)

    # Agent 1 should see Agent 1 and Agent 2, but NOT Agent 3
    context = build_structured_context(
        for_agent="Agent 1",
        events=[event1, event2, event3],
        info_model=info_model,
        agent_score=0,
    )

    # Debug: print the context
    print(f"\nContext for Agent 1: {context}")

    # Should contain "I" (Agent 1) and Agent 2, but NOT Agent 3
    assert "I red" in context  # Agent 1's own action
    assert "Agent 2" in context
    assert "Agent 3" not in context  # This should FAIL initially (bug exists)

    # Agent 2 should see Agent 1 and Agent 2, but NOT Agent 3
    context2 = build_structured_context(
        for_agent="Agent 2",
        events=[event1, event2, event3],
        info_model=info_model,
        agent_score=0,
    )

    assert "Agent 1" in context2
    assert "I blue" in context2  # Agent 2's own action
    assert "Agent 3" not in context2

    # Agent 3 should see Agent 1 and Agent 3, but NOT Agent 2
    context3 = build_structured_context(
        for_agent="Agent 3",
        events=[event1, event2, event3],
        info_model=info_model,
        agent_score=0,
    )

    assert "Agent 1" in context3
    assert "I green" in context3  # Agent 3's own action
    assert "Agent 2" not in context3
