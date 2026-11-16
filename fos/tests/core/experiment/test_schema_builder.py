"""
Tests for schema builder module.

Tests the JSON schema generation for constrained decoding.
"""


from fos.core.experiment.game_configs import PRISONERS_DILEMMA, MINIMUM_EFFORT
from fos.core.experiment.schema_builder import build_schema


def test_build_schema_discrete():
    """Schema for discrete actions includes enum constraint."""
    schema = build_schema(PRISONERS_DILEMMA)

    assert schema["type"] == "object"
    assert "action" in schema["properties"]
    assert schema["properties"]["action"]["type"] == "string"
    assert schema["properties"]["action"]["enum"] == ["cooperate", "defect"]
    assert schema["required"] == ["action"]
    # No reasoning field - prompts explicitly say "No reasoning"
    assert "reasoning" not in schema["properties"]


def test_build_schema_integer():
    """Schema for integer actions includes type constraint."""
    schema = build_schema(MINIMUM_EFFORT)

    assert schema["type"] == "object"
    assert "effort" in schema["properties"]
    assert schema["properties"]["effort"]["type"] == "integer"
    assert schema["required"] == ["effort"]
    # No reasoning field - prompts explicitly say "No reasoning"
    assert "reasoning" not in schema["properties"]
