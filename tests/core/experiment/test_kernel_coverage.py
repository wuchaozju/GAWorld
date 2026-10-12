"""
Tests for ExperimentKernel — uncovered schema and parameter features.

Covers needs_parameters, get_action_schemas structure, action execution
variants, and schema_builder integration for JSON schema generation.

Contains: tests for ExperimentKernel, schema_builder.build_schema
"""

from fos.core.experiment.kernel import (
    ExperimentKernel,
    VoteAction,
    NumericalAction,
)
from fos.core.experiment.schema_builder import build_schema
from fos.core.experiment.game_configs import GameConfig


def test_needs_parameters_true_for_speak():
    """SpeakAction has a parameter schema, so needs_parameters returns True."""
    assert ExperimentKernel.needs_parameters("speak") is True


def test_needs_parameters_true_for_vote():
    """VoteAction has a parameter schema, so needs_parameters returns True."""
    assert ExperimentKernel.needs_parameters("vote") is True


def test_needs_parameters_false_for_choice():
    """ChoiceAction has no parameters, so needs_parameters returns False."""
    assert ExperimentKernel.needs_parameters("choice") is False


def test_needs_parameters_false_for_unknown_action():
    """Unknown action name returns False for needs_parameters."""
    assert ExperimentKernel.needs_parameters("nonexistent") is False


def test_get_action_schemas_includes_speak_with_plain_text_mode():
    """Speak action appears in schemas with plain_text mode."""
    schemas = ExperimentKernel.get_action_schemas()

    assert "speak" in schemas
    assert schemas["speak"]["mode"] == "plain_text"
    assert "message" in schemas["speak"]["schema"]


def test_get_action_schemas_includes_vote_with_json_mode():
    """Vote action appears in schemas with json mode."""
    schemas = ExperimentKernel.get_action_schemas()

    assert "vote" in schemas
    assert schemas["vote"]["mode"] == "json"
    assert "target" in schemas["vote"]["schema"]


def test_vote_action_execute_returns_correct_summary():
    """VoteAction.execute formats the target into the summary."""
    vote = VoteAction()
    summary = vote.execute("Alice", {"target": "Bob"}, {})
    assert summary == "Alice voted for Bob"


def test_numerical_action_execute_returns_correct_summary():
    """NumericalAction.execute formats the value into the summary."""
    num = NumericalAction()
    summary = num.execute("Charlie", {"value": 42}, {})
    assert summary == "Charlie chose 42"


def test_schema_builder_produces_valid_json_schema():
    """build_schema produces a valid JSON schema with required field."""
    config = GameConfig(
        name="test",
        description="test game",
        action_type="discrete",
        actions=["cooperate", "defect", "speak"],
    )
    schema = build_schema(config)

    assert schema["type"] == "object"
    assert schema["properties"]["action"]["type"] == "string"
    assert set(schema["properties"]["action"]["enum"]) == {"cooperate", "defect", "speak"}
    assert schema["required"] == ["action"]
