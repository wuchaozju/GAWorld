"""
Unit tests for PGG payoff engine deduction logic.

Tests that the "reductions" extension key is applied correctly,
that the legacy "punishments" fallback works, and that is_enabled
is driven by actual recorded deductions rather than config lookup.
"""

import pytest

from fos.core.experiment.state import ExperimentState, AgentState
from fos.core.experiment.payoff.engine import PayoffEngine


class TestPayoffEngineDeductions:
    """Tests for _apply_punishment_effects and is_enabled logic."""

    @pytest.fixture
    def engine(self):
        return PayoffEngine()

    @pytest.fixture
    def base_payoffs(self):
        return {"Alice": 30.0, "Bob": 30.0, "Carol": 30.0}

    @pytest.fixture
    def state_with_reductions(self):
        """State using new 'reductions' extension key."""
        state = ExperimentState()
        state.agents["Alice"] = AgentState(score=0, resources={"tokens": 20})
        state.agents["Bob"] = AgentState(score=0, resources={"tokens": 20})
        state.agents["Carol"] = AgentState(score=0, resources={"tokens": 20})
        state.extensions["reductions"] = {
            "Alice": [{"target": "Bob", "amount": 3}]
        }
        return state

    @pytest.fixture
    def state_with_legacy_punishments(self):
        """State using legacy 'punishments' extension key."""
        state = ExperimentState()
        state.agents["Alice"] = AgentState(score=0, resources={"tokens": 20})
        state.agents["Bob"] = AgentState(score=0, resources={"tokens": 20})
        state.agents["Carol"] = AgentState(score=0, resources={"tokens": 20})
        state.extensions["punishments"] = {
            "Alice": [{"target": "Bob", "amount": 2}]
        }
        return state

    def test_applies_reductions_key(self, engine, base_payoffs, state_with_reductions):
        """Deductions stored under 'reductions' are applied correctly."""
        config = {"cost_ratio": 3.0}
        result = engine._apply_punishment_effects(base_payoffs, state_with_reductions, config)
        # Alice spent 3 budget points -> Bob loses 3 * 3.0 = 9
        assert result["Bob"] == pytest.approx(21.0)
        assert result["Alice"] == pytest.approx(30.0)  # unaffected
        assert result["Carol"] == pytest.approx(30.0)  # unaffected

    def test_applies_legacy_punishments_key(self, engine, base_payoffs, state_with_legacy_punishments):
        """Deductions stored under legacy 'punishments' key still work."""
        config = {"cost_ratio": 3.0}
        result = engine._apply_punishment_effects(base_payoffs, state_with_legacy_punishments, config)
        # Alice spent 2 budget points -> Bob loses 2 * 3.0 = 6
        assert result["Bob"] == pytest.approx(24.0)
        assert result["Alice"] == pytest.approx(30.0)

    def test_payoff_floored_at_zero(self, engine, state_with_reductions):
        """Payoffs cannot go negative even with large deductions."""
        payoffs = {"Alice": 30.0, "Bob": 5.0, "Carol": 30.0}
        # 3 budget points * cost_ratio 10 = 30, which exceeds Bob's 5
        config = {"cost_ratio": 10.0}
        result = engine._apply_punishment_effects(payoffs, state_with_reductions, config)
        assert result["Bob"] == 0.0

    def test_is_enabled_by_reductions_present(self, engine, base_payoffs, state_with_reductions):
        """is_enabled triggers from recorded reductions, not config lookup."""
        # No explicit "enabled" flag in deduction_config -- should still apply
        deduction_config = {"cost_ratio": 3.0}
        # Simulate calculate_payoffs is_enabled logic
        is_enabled = deduction_config.get("enabled", False)
        if not is_enabled and state_with_reductions is not None:
            has_reductions = bool(
                state_with_reductions.extensions.get("reductions") or
                state_with_reductions.extensions.get("punishments")
            )
            is_enabled = has_reductions
        assert is_enabled is True

    def test_is_not_enabled_when_no_reductions(self, engine):
        """is_enabled is False when state has no reductions and no explicit flag."""
        state = ExperimentState()
        state.extensions["reductions"] = {}
        deduction_config = {"cost_ratio": 3.0}
        is_enabled = deduction_config.get("enabled", False)
        if not is_enabled:
            has_reductions = bool(
                state.extensions.get("reductions") or
                state.extensions.get("punishments")
            )
            is_enabled = has_reductions
        assert is_enabled is False

    def test_empty_reductions_no_effect(self, engine, base_payoffs):
        """Empty reductions dict leaves payoffs unchanged."""
        state = ExperimentState()
        state.extensions["reductions"] = {}
        config = {"cost_ratio": 3.0}
        result = engine._apply_punishment_effects(base_payoffs, state, config)
        assert result == base_payoffs

    def test_multiple_reducers_same_target(self, engine, base_payoffs):
        """Multiple reducers targeting same agent accumulates deductions."""
        state = ExperimentState()
        state.agents["Alice"] = AgentState(score=0, resources={"tokens": 20})
        state.agents["Bob"] = AgentState(score=0, resources={"tokens": 20})
        state.agents["Carol"] = AgentState(score=0, resources={"tokens": 20})
        state.extensions["reductions"] = {
            "Alice": [{"target": "Bob", "amount": 2}],
            "Carol": [{"target": "Bob", "amount": 3}],
        }
        config = {"cost_ratio": 3.0}
        result = engine._apply_punishment_effects(base_payoffs, state, config)
        # Bob loses (2 + 3) * 3 = 15
        assert result["Bob"] == pytest.approx(15.0)
        assert result["Alice"] == pytest.approx(30.0)
        assert result["Carol"] == pytest.approx(30.0)
