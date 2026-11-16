"""Tests for action definitions."""
from fos.core.experiment.actions.definitions import (
    ActionDefinition,
    ParameterSpec,
    EffectSpec,
)


class TestParameterSpec:
    def test_enum_parameter(self):
        """Enum parameter with options."""
        param = ParameterSpec(
            name="direction",
            type="enum",
            options=["north", "south", "east", "west"],
            required=True,
        )
        assert param.name == "direction"
        assert param.type == "enum"
        assert len(param.options) == 4

    def test_number_parameter(self):
        """Number parameter without options."""
        param = ParameterSpec(
            name="amount",
            type="number",
            options=[],
            required=True,
        )
        assert param.type == "number"
        assert param.options == []

    def test_text_parameter(self):
        """Text parameter for free-form input."""
        param = ParameterSpec(
            name="message",
            type="text",
            options=[],
            required=True,
        )
        assert param.type == "text"


class TestEffectSpec:
    def test_add_effect(self):
        """Add to a value."""
        effect = EffectSpec(
            target="extensions.pools.main",
            operation="add",
            value="amount",
        )
        assert effect.operation == "add"
        assert effect.target == "extensions.pools.main"

    def test_subtract_effect(self):
        """Subtract from a value."""
        effect = EffectSpec(
            target="agent.resources.tokens",
            operation="subtract",
            value="amount",
        )
        assert effect.operation == "subtract"


class TestActionDefinition:
    def test_simple_action(self):
        """Action with no parameters or effects."""
        action = ActionDefinition(
            name="cooperate",
            description="Choose to cooperate",
            parameters=[],
            effects=[],
            requires=None,
            handler=None,
        )
        assert action.name == "cooperate"
        assert len(action.parameters) == 0

    def test_action_with_parameters(self):
        """Action with parameters requires follow-up."""
        action = ActionDefinition(
            name="move",
            description="Move to adjacent tile",
            parameters=[
                ParameterSpec("direction", "enum", ["north", "south"], True),
            ],
            effects=[],
            requires=["spatial"],
            handler=None,
        )
        assert len(action.parameters) == 1
        assert action.requires == ["spatial"]

    def test_action_with_effects(self):
        """Action with declarative effects."""
        action = ActionDefinition(
            name="contribute",
            description="Contribute to pool",
            parameters=[
                ParameterSpec("amount", "number", [], True),
            ],
            effects=[
                EffectSpec("agent.resources.tokens", "subtract", "amount"),
                EffectSpec("extensions.pools.main", "add", "amount"),
            ],
            requires=None,
            handler=None,
        )
        assert len(action.effects) == 2

    def test_needs_followup(self):
        """Action with parameters needs follow-up prompt."""
        action_with_params = ActionDefinition(
            name="move",
            description="Move",
            parameters=[ParameterSpec("direction", "enum", ["north"], True)],
            effects=[],
            requires=None,
            handler=None,
        )
        action_without_params = ActionDefinition(
            name="cooperate",
            description="Cooperate",
            parameters=[],
            effects=[],
            requires=None,
            handler=None,
        )
        assert action_with_params.needs_followup() is True
        assert action_without_params.needs_followup() is False
