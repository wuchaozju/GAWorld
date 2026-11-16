"""
Tests for ExperimentState and AgentState — state tracking coverage.

Ensures agents are registered correctly, scores/positions/resources update,
pools accumulate, and serialization round-trips preserve all data.

Contains: tests for ExperimentState, AgentState
"""

from fos.core.experiment.state import AgentState, ExperimentState


def test_agent_auto_created_on_score_update():
    """Updating score for unknown agent creates the agent automatically."""
    state = ExperimentState()
    state.update_agent_score("Alice", 10)

    assert "Alice" in state.agents
    assert state.agents["Alice"].score == 10


def test_agent_auto_created_on_position_update():
    """Updating position for unknown agent creates the agent automatically."""
    state = ExperimentState()
    state.update_agent_position("Bob", (3, 4))

    assert "Bob" in state.agents
    assert state.agents["Bob"].position == (3, 4)


def test_agent_score_is_cumulative():
    """Score accumulates across multiple updates."""
    state = ExperimentState()
    state.update_agent_score("Alice", 5)
    state.update_agent_score("Alice", 3)
    state.update_agent_score("Alice", -2)

    assert state.agents["Alice"].score == 6


def test_agent_position_update_overwrites():
    """Position update replaces the previous position."""
    state = ExperimentState()
    state.update_agent_position("Alice", (1, 1))
    state.update_agent_position("Alice", (2, 3))

    assert state.agents["Alice"].position == (2, 3)


def test_agent_resource_update():
    """Resource amounts are set per resource type."""
    state = ExperimentState()
    state.update_agent_resource("Alice", "tokens", 10)
    state.update_agent_resource("Alice", "tokens", 5)  # overwrite
    state.update_agent_resource("Alice", "mana", 100)

    assert state.agents["Alice"].resources["tokens"] == 5
    assert state.agents["Alice"].resources["mana"] == 100


def test_get_agent_position_returns_none_for_unknown():
    """Getting position of unregistered agent returns None."""
    state = ExperimentState()
    assert state.get_agent_position("Nobody") is None


def test_pool_add_and_retrieve():
    """Contribution pools accumulate amounts correctly."""
    state = ExperimentState()
    state.add_to_pool("main", 10)
    state.add_to_pool("main", 5)
    state.add_to_pool("bonus", 20)

    assert state.get_pool("main") == 15
    assert state.get_pool("bonus") == 20
    assert state.get_pool("nonexistent") == 0


def test_to_dict_from_dict_round_trip():
    """Serialization round-trip preserves all fields."""
    state = ExperimentState(
        round=3,
        agents={
            "Alice": AgentState(score=10, position=(1, 2), resources={"tokens": 5}),
            "Bob": AgentState(score=20, resources={"tokens": 8}),
        },
        history=[{"round": 1, "actions": []}],
        extensions={"pools": {"main": 15}, "custom": "data"},
    )

    data = state.to_dict()
    restored = ExperimentState.from_dict(data)

    assert restored.round == 3
    assert "Alice" in restored.agents
    assert restored.agents["Alice"].score == 10
    assert restored.agents["Alice"].position == (1, 2)
    assert restored.agents["Alice"].resources == {"tokens": 5}
    assert "Bob" in restored.agents
    assert restored.agents["Bob"].score == 20
    assert restored.history == [{"round": 1, "actions": []}]
    assert restored.extensions["custom"] == "data"


def test_empty_state_serializes_cleanly():
    """Empty state serializes and deserializes without error."""
    state = ExperimentState()
    data = state.to_dict()
    restored = ExperimentState.from_dict(data)

    assert restored.round == 0
    assert restored.agents == {}
    assert restored.history == []
    assert restored.extensions == {}


def test_agent_state_to_dict_from_dict_round_trip():
    """AgentState serialization preserves all fields including None position."""
    agent = AgentState(score=15, position=(5, 6), resources={"gold": 3}, properties={"role": "leader"})

    data = agent.to_dict()
    restored = AgentState.from_dict(data)

    assert restored.score == 15
    assert restored.position == (5, 6)
    assert restored.resources == {"gold": 3}
    assert restored.properties == {"role": "leader"}


def test_agent_state_from_dict_uses_defaults():
    """AgentState.from_dict fills in defaults for missing fields."""
    data = {"score": 5}
    agent = AgentState.from_dict(data)

    assert agent.score == 5
    assert agent.position is None
    assert agent.resources == {}
    assert agent.properties == {}
