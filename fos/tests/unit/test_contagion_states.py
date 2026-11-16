"""
Unit tests for ContagionState enum.

Verifies the SEIR state values and string serialization behavior.

Contains: TestContagionState
"""
from fos.core.contagion.states import ContagionState


class TestContagionState:

    def test_four_states_defined(self):
        states = list(ContagionState)
        assert len(states) == 4

    def test_state_values_are_strings(self):
        for state in ContagionState:
            assert isinstance(state.value, str)

    def test_susceptible_value(self):
        assert ContagionState.SUSCEPTIBLE.value == "susceptible"

    def test_exposed_value(self):
        assert ContagionState.EXPOSED.value == "exposed"

    def test_infected_value(self):
        assert ContagionState.INFECTED.value == "infected"

    def test_recovered_value(self):
        assert ContagionState.RECOVERED.value == "recovered"

    def test_state_is_string_subclass(self):
        assert isinstance(ContagionState.SUSCEPTIBLE, str)

    def test_construct_from_string(self):
        assert ContagionState("infected") == ContagionState.INFECTED

    def test_json_serializable_as_string(self):
        import json
        result = json.dumps(ContagionState.INFECTED.value)
        assert result == '"infected"'
