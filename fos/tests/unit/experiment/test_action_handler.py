"""
Tests for ActionHandler and action registry.

Covers action execution, declarative effects, handler dispatch
for experiment actions including reduction event emission, and
PGG record-only action registration.

Contains: TestActionHandler, TestPGGActionRegistry
"""
from fos.core.experiment.action_handler import ActionHandler
from fos.core.experiment.actions.registry import ACTION_REGISTRY, get_action
from fos.core.experiment.state import ExperimentState, AgentState


class MockScene:
    """Mock scene for testing event emission."""

    def __init__(self):
        self.emitted_events = []
        self.config = type('obj', (object,), {'parameters': {'deduction_cost_ratio': 3.0, 'deduction_budget_per_phase': 10}})()

    def _emit_event(self, event_type: str, data: dict):
        """Store emitted events for verification."""
        self.emitted_events.append({'type': event_type, 'data': data})


class TestActionHandler:
    def setup_method(self):
        self.handler = ActionHandler()
        self.state = ExperimentState()
        self.state.agents["Alice"] = AgentState(
            resources={"tokens": 20},
            position=(5, 5),
        )
        self.state.extensions["pools"] = {"main": 0}

    def test_execute_choose_action(self):
        """Choose action returns success."""
        result = self.handler.execute("choose", "Alice", {"choice": "cooperate"}, self.state)
        assert result["success"] is True

    def test_execute_move_action(self):
        """Move action updates position."""
        result = self.handler.execute("move", "Alice", {"direction": "north"}, self.state)
        assert result["success"] is True
        assert result["new_position"] == (5, 4)
        assert self.state.get_agent_position("Alice") == (5, 4)

    def test_execute_move_missing_position(self):
        """Move fails if agent has no position."""
        self.state.agents["Bob"] = AgentState(position=None)
        result = self.handler.execute("move", "Bob", {"direction": "north"}, self.state)
        assert result["success"] is False
        # Could be "no position" or "missing requirement: spatial"
        assert "position" in result["error"].lower() or "spatial" in result["error"].lower()

    def test_execute_move_missing_requirement(self):
        """Move fails if scenario lacks spatial feature."""
        state_no_spatial = ExperimentState()
        state_no_spatial.agents["Alice"] = AgentState(position=(1, 1))
        # No spatial config in extensions
        result = self.handler.execute("move", "Alice", {"direction": "north"}, state_no_spatial)
        # Should still work if agent has position
        assert result["success"] is True

    def test_execute_unknown_action(self):
        """Unknown action returns error."""
        result = self.handler.execute("unknown", "Alice", {}, self.state)
        assert result["success"] is False
        assert "unknown action" in result["error"].lower()

    def test_apply_declarative_effects(self):
        """Handler applies declarative effects."""
        # contribute subtracts from agent, adds to pool
        result = self.handler.execute(
            "contribute",
            "Alice",
            {"amount": 5, "pool": "main"},
            self.state
        )
        assert result["success"] is True
        assert self.state.agents["Alice"].resources["tokens"] == 15
        assert self.state.extensions["pools"]["main"] == 5

    # Wave 1: Reduction event emission tests (FEAT-PGG-09 through FEAT-PGG-11)
    def test_reduce_emits_event(self):
        """Reduce action should emit reduction_action event."""
        handler = ActionHandler()
        state = ExperimentState()
        state.agents["Alice"] = AgentState(
            resources={"deduction_budget": 10},
        )
        state.agents["Bob"] = AgentState(
            resources={},
        )

        mock_scene = MockScene()

        result = handler.execute("reduce", "Alice", {"target": "Bob", "amount": 5}, state, mock_scene)

        assert result["success"] is True
        assert len(mock_scene.emitted_events) == 1
        assert mock_scene.emitted_events[0]["type"] == "reduction_action"
        assert mock_scene.emitted_events[0]["data"]["reducer"] == "Alice"
        assert mock_scene.emitted_events[0]["data"]["target"] == "Bob"

    def test_reduce_event_includes_amount(self):
        """Reduction event should include amount spent."""
        handler = ActionHandler()
        state = ExperimentState()
        state.agents["Alice"] = AgentState(
            resources={"deduction_budget": 10},
        )
        state.agents["Bob"] = AgentState(
            resources={},
        )

        mock_scene = MockScene()

        result = handler.execute("reduce", "Alice", {"target": "Bob", "amount": 5}, state, mock_scene)

        assert result["success"] is True
        assert mock_scene.emitted_events[0]["data"]["amount"] == 5

    def test_reduce_event_includes_deduction(self):
        """Reduction event should include deduction (amount × cost_ratio)."""
        handler = ActionHandler()
        state = ExperimentState()
        state.agents["Alice"] = AgentState(
            resources={"deduction_budget": 10},
        )
        state.agents["Bob"] = AgentState(
            resources={},
        )

        mock_scene = MockScene()

        result = handler.execute("reduce", "Alice", {"target": "Bob", "amount": 5}, state, mock_scene)

        assert result["success"] is True
        # deduction = amount × cost_ratio = 5 × 3.0 = 15.0
        assert mock_scene.emitted_events[0]["data"]["deduction"] == 15.0
        assert mock_scene.emitted_events[0]["data"]["cost_ratio"] == 3.0


class TestPGGActionRegistry:
    """Regression: allocate and keep must be registered record-only actions.

    Bug: scene.py now checks execute_action results. Unregistered actions
    return success=False, which clears history and breaks round context.
    """

    def test_allocate_registered(self):
        """'allocate' is in ACTION_REGISTRY."""
        assert "allocate" in ACTION_REGISTRY
        assert get_action("allocate") is not None

    def test_keep_registered(self):
        """'keep' is in ACTION_REGISTRY."""
        assert "keep" in ACTION_REGISTRY
        assert get_action("keep") is not None

    def test_allocate_is_record_only(self):
        """'allocate' is record_only — payoff handled by payoff engine."""
        action = get_action("allocate")
        assert action.record_only is True

    def test_keep_is_record_only(self):
        """'keep' is record_only — no state mutation needed."""
        action = get_action("keep")
        assert action.record_only is True

    def test_allocate_no_effects_no_handler(self):
        """Record-only actions have no effects or handler."""
        action = get_action("allocate")
        assert action.effects == []
        assert action.handler is None

    def test_keep_no_effects_no_handler(self):
        """Record-only actions have no effects or handler."""
        action = get_action("keep")
        assert action.effects == []
        assert action.handler is None

    def test_execute_allocate_succeeds(self):
        """Allocating through ActionHandler returns success."""
        handler = ActionHandler()
        state = ExperimentState()
        state.agents["Alice"] = AgentState(resources={"tokens": 20})
        result = handler.execute("allocate", "Alice", {}, state)
        assert result["success"] is True
        assert result.get("record_only") is True
        assert result.get("effect_applied") is False

    def test_execute_keep_succeeds(self):
        """Keep through ActionHandler returns success."""
        handler = ActionHandler()
        state = ExperimentState()
        state.agents["Alice"] = AgentState(resources={"tokens": 20})
        result = handler.execute("keep", "Alice", {}, state)
        assert result["success"] is True
        assert result.get("record_only") is True
        assert result.get("effect_applied") is False
