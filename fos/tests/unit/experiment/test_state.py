"""Tests for ExperimentState classes."""
from fos.core.experiment.state import ExperimentState, AgentState


class TestAgentState:
    def test_default_values(self):
        """AgentState initializes with correct defaults."""
        agent = AgentState()
        assert agent.score == 0
        assert agent.position is None
        assert agent.resources == {}
        assert agent.properties == {}

    def test_custom_values(self):
        """AgentState accepts custom values."""
        agent = AgentState(
            score=10,
            position=(3, 4),
            resources={"tokens": 20},
            properties={"role": "leader"}
        )
        assert agent.score == 10
        assert agent.position == (3, 4)
        assert agent.resources["tokens"] == 20

    def test_position_tuple(self):
        """Position is stored as tuple."""
        agent = AgentState(position=[1, 2])
        assert agent.position == (1, 2)


class TestExperimentState:
    def test_default_values(self):
        """ExperimentState initializes with correct defaults."""
        state = ExperimentState()
        assert state.round == 0
        assert state.agents == {}
        assert state.history == []
        assert state.extensions == {}

    def test_add_agent(self):
        """Can add agents to state."""
        state = ExperimentState()
        state.agents["Alice"] = AgentState(score=5)
        assert "Alice" in state.agents
        assert state.agents["Alice"].score == 5

    def test_extensions_storage(self):
        """Extensions store scenario-specific data."""
        state = ExperimentState(extensions={"pools": {"main": 0}})
        assert state.extensions["pools"]["main"] == 0

    def test_get_agent_position(self):
        """Can query agent position."""
        state = ExperimentState()
        state.agents["Bob"] = AgentState(position=(5, 5))
        assert state.get_agent_position("Bob") == (5, 5)

    def test_get_agent_position_missing_agent(self):
        """Missing agent returns None."""
        state = ExperimentState()
        assert state.get_agent_position("Unknown") is None

    def test_update_agent_resource(self):
        """Can update agent resources."""
        state = ExperimentState()
        state.agents["Alice"] = AgentState(resources={"tokens": 10})
        state.update_agent_resource("Alice", "tokens", 15)
        assert state.agents["Alice"].resources["tokens"] == 15

    def test_serialize_deserialize(self):
        """State can be serialized and restored."""
        state = ExperimentState(round=3)
        state.agents["Alice"] = AgentState(score=10, position=(1, 2))
        state.extensions["pools"] = {"main": 50}

        data = state.to_dict()
        restored = ExperimentState.from_dict(data)

        assert restored.round == 3
        assert restored.agents["Alice"].score == 10
        assert restored.agents["Alice"].position == (1, 2)
        assert restored.extensions["pools"]["main"] == 50
