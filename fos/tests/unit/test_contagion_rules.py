"""
Unit tests for contagion state transition rules.

Tests StateTransition validation and check_probability behavior.

Contains: TestStateTransition, TestCheckProbability
"""
import pytest
from fos.core.contagion.states import ContagionState
from fos.core.contagion.rules import StateTransition, check_probability


def _susceptible_to_exposed_decay():
    return StateTransition(
        from_state=ContagionState.SUSCEPTIBLE,
        to_state=ContagionState.EXPOSED,
        trigger_type="proximity",
        probability=1.0,
    )


class TestStateTransition:

    def test_valid_proximity_rule_creates_ok(self):
        rule = StateTransition(
            from_state=ContagionState.SUSCEPTIBLE,
            to_state=ContagionState.EXPOSED,
            trigger_type="proximity",
            probability=0.5,
        )
        assert rule.trigger_type == "proximity"
        assert rule.probability == 0.5

    def test_valid_decay_rule_requires_decay_turns(self):
        rule = StateTransition(
            from_state=ContagionState.INFECTED,
            to_state=ContagionState.RECOVERED,
            trigger_type="decay",
            probability=1.0,
            decay_turns=5,
        )
        assert rule.decay_turns == 5

    def test_valid_action_rule_creates_ok(self):
        rule = StateTransition(
            from_state=ContagionState.INFECTED,
            to_state=ContagionState.EXPOSED,
            trigger_type="action",
            probability=0.3,
        )
        assert rule.trigger_type == "action"

    def test_invalid_probability_below_zero_raises(self):
        with pytest.raises(ValueError):
            StateTransition(
                from_state=ContagionState.SUSCEPTIBLE,
                to_state=ContagionState.EXPOSED,
                trigger_type="proximity",
                probability=-0.1,
            )

    def test_invalid_probability_above_one_raises(self):
        with pytest.raises(ValueError):
            StateTransition(
                from_state=ContagionState.SUSCEPTIBLE,
                to_state=ContagionState.EXPOSED,
                trigger_type="proximity",
                probability=1.1,
            )

    def test_invalid_trigger_type_raises(self):
        with pytest.raises(ValueError):
            StateTransition(
                from_state=ContagionState.SUSCEPTIBLE,
                to_state=ContagionState.EXPOSED,
                trigger_type="telekinesis",
                probability=0.5,
            )

    def test_decay_without_decay_turns_raises(self):
        with pytest.raises(ValueError):
            StateTransition(
                from_state=ContagionState.INFECTED,
                to_state=ContagionState.RECOVERED,
                trigger_type="decay",
                probability=1.0,
                decay_turns=None,
            )

    def test_boundary_probability_zero_ok(self):
        rule = StateTransition(
            from_state=ContagionState.SUSCEPTIBLE,
            to_state=ContagionState.EXPOSED,
            trigger_type="proximity",
            probability=0.0,
        )
        assert rule.probability == 0.0

    def test_boundary_probability_one_ok(self):
        rule = StateTransition(
            from_state=ContagionState.INFECTED,
            to_state=ContagionState.RECOVERED,
            trigger_type="proximity",
            probability=1.0,
        )
        assert rule.probability == 1.0


class TestCheckProbability:

    def test_probability_one_always_true(self):
        assert all(check_probability(1.0) for _ in range(20))

    def test_probability_zero_always_false(self):
        assert not any(check_probability(0.0) for _ in range(20))

    def test_returns_bool(self):
        result = check_probability(0.5)
        assert isinstance(result, bool)
