"""Tests for action registry."""
from fos.core.experiment.actions.registry import (
    ACTION_REGISTRY,
    get_action,
    register_action,
)
from fos.core.experiment.actions.definitions import ActionDefinition


class TestActionRegistry:
    def test_registry_has_choose_action(self):
        """Registry includes choose action."""
        assert "choose" in ACTION_REGISTRY
        action = ACTION_REGISTRY["choose"]
        assert action.name == "choose"

    def test_registry_has_move_action(self):
        """Registry includes move action."""
        assert "move" in ACTION_REGISTRY
        action = ACTION_REGISTRY["move"]
        assert action.name == "move"
        assert action.requires == ["spatial"]

    def test_registry_has_contribute_action(self):
        """Registry includes contribute action."""
        assert "contribute" in ACTION_REGISTRY
        action = ACTION_REGISTRY["contribute"]
        assert action.name == "contribute"

    def test_get_action(self):
        """get_action returns action by name."""
        action = get_action("choose")
        assert action.name == "choose"

    def test_get_action_missing(self):
        """get_action returns None for unknown action."""
        action = get_action("unknown_action")
        assert action is None

    def test_register_action(self):
        """Can register custom action."""
        custom = ActionDefinition(
            name="custom_action",
            description="A custom action",
            parameters=[],
            effects=[],
            requires=None,
            handler=None,
        )
        register_action(custom)
        assert "custom_action" in ACTION_REGISTRY
        assert ACTION_REGISTRY["custom_action"].name == "custom_action"
