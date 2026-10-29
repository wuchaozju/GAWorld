"""
Tests for schema_builder module.
"""

from tests.llm_prompt_testing.prompt_v2.game_configs import (
    GameConfig,
    PRISONERS_DILEMMA,
    PUBLIC_GOODS,
)
from tests.llm_prompt_testing.prompt_v2.schema_builder import build_schema


def test_build_schema_discrete():
    """Test schema builder for discrete actions."""
    config = GameConfig(
        name="Test",
        description="Test",
        action_type="discrete",
        actions=["cooperate", "defect"],
    )

    schema = build_schema(config)

    assert schema["type"] == "object"
    assert "reasoning" in schema["properties"]
    assert schema["properties"]["reasoning"]["type"] == "string"
    assert "action" in schema["properties"]
    assert schema["properties"]["action"]["type"] == "string"
    assert schema["properties"]["action"]["enum"] == ["cooperate", "defect"]
    assert "action" in schema["required"]


def test_build_schema_integer():
    """Test schema builder for integer actions."""
    config = GameConfig(
        name="Test",
        description="Test",
        action_type="integer",
        output_field="offer",
    )

    schema = build_schema(config)

    assert schema["type"] == "object"
    assert "reasoning" in schema["properties"]
    assert schema["properties"]["offer"]["type"] == "integer"
    assert "offer" in schema["required"]


def test_build_schema_prisoners_dilemma():
    """Test schema for actual Prisoner's Dilemma config."""
    schema = build_schema(PRISONERS_DILEMMA)

    assert schema["properties"]["action"]["enum"] == ["cooperate", "defect"]


def test_build_schema_public_goods():
    """Test schema for actual Public Goods config."""
    schema = build_schema(PUBLIC_GOODS)

    assert schema["properties"]["contribution"]["type"] == "integer"


def test_schema_reasoning_always_included():
    """Test that reasoning field is always included in schema."""
    config = GameConfig(
        name="Test",
        description="Test",
        action_type="discrete",
        actions=["a"],
    )

    schema = build_schema(config)

    assert "reasoning" in schema["properties"]
    # Reasoning should not be required (it's optional)
    assert "reasoning" not in schema.get("required", [])
