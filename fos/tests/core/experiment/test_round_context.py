"""
Tests for RoundContextManager.

Tests the context manager's ability to:
- Record and retrieve round events
- Manage per-agent context summaries
- Handle multiple rounds correctly
"""


from fos.core.experiment.round_context import (
    RoundContextManager,
    RoundEvent,
)


def test_record_action():
    """Record an action and retrieve it."""
    manager = RoundContextManager()

    manager.record_action(
        agent_name="Alice",
        action_name="cooperate",
        parameters={},
        round_num=1,
        summary="Alice cooperated"
    )

    events = manager.get_round_events(1)
    assert len(events) == 1
    assert events[0].agent_name == "Alice"
    assert events[0].action_name == "cooperate"


def test_get_context_empty():
    """Empty context returns empty string."""
    manager = RoundContextManager()
    assert manager.get_context("Alice") == ""


def test_get_context_with_initial():
    """Get initial context if provided."""
    manager = RoundContextManager(initial_contexts={"Alice": "Initial context"})
    assert manager.get_context("Alice") == "Initial context"


def test_multiple_rounds():
    """Events are tracked per round."""
    manager = RoundContextManager()

    manager.record_action("Alice", "cooperate", {}, 1, "Alice cooperated in round 1")
    manager.record_action("Bob", "defect", {}, 1, "Bob defected in round 1")
    manager.record_action("Alice", "defect", {}, 2, "Alice defected in round 2")

    assert len(manager.get_round_events(1)) == 2
    assert len(manager.get_round_events(2)) == 1
    assert manager.get_round_events(2)[0].agent_name == "Alice"


def test_round_event_dataclass():
    """RoundEvent stores all attributes correctly."""
    event = RoundEvent(
        agent_name="Bob",
        action_name="defect",
        parameters={"target": "Alice"},
        round_num=3,
        summary="Bob defected against Alice"
    )

    assert event.agent_name == "Bob"
    assert event.action_name == "defect"
    assert event.parameters == {"target": "Alice"}
    assert event.round_num == 3
    assert event.summary == "Bob defected against Alice"


def test_get_round_events_empty_round():
    """Getting events for non-existent round returns empty list."""
    manager = RoundContextManager()
    assert manager.get_round_events(1) == []


def test_record_action_with_parameters():
    """Record action with various parameter types."""
    manager = RoundContextManager()

    params = {
        "target": "Bob",
        "amount": 100,
        "willingness": 0.5
    }

    manager.record_action(
        agent_name="Alice",
        action_name="share",
        parameters=params,
        round_num=1,
        summary="Alice shared resources with Bob"
    )

    events = manager.get_round_events(1)
    assert events[0].parameters == params


def test_multiple_agents_contexts():
    """Each agent maintains separate context."""
    manager = RoundContextManager(initial_contexts={
        "Alice": "Alice's initial context",
        "Bob": "Bob's initial context"
    })

    assert manager.get_context("Alice") == "Alice's initial context"
    assert manager.get_context("Bob") == "Bob's initial context"
    assert manager.get_context("Charlie") == ""


def test_empty_round_list():
    """No events recorded returns empty list."""
    manager = RoundContextManager()
    manager.record_action("Alice", "cooperate", {}, 1, "Alice cooperated")

    assert manager.get_round_events(2) == []


def test_round_event_has_feedback_field():
    """RoundEvent should have a feedback field for coordination games."""
    event = RoundEvent(
        round_num=1,
        agent_name="Alice",
        action_name="red",
        parameters={},
        summary="Alice chose red",
        observed_by=["Alice", "Bob"],
        payoff=0,
        feedback="Coordinated with Bob (both chose red)",
    )

    assert event.feedback == "Coordinated with Bob (both chose red)"


def test_round_event_feedback_defaults_to_none():
    """RoundEvent feedback should default to None."""
    event = RoundEvent(
        round_num=1,
        agent_name="Alice",
        action_name="cooperate",
        parameters={},
        summary="Alice cooperated",
        observed_by=["Alice"],
    )

    assert event.feedback is None
