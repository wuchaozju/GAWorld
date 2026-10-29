"""
Tests for game_configs module.
"""

from tests.llm_prompt_testing.prompt_v2.game_configs import (
    GameConfig,
    PRISONERS_DILEMMA,
    PUBLIC_GOODS,
)


def test_game_config_discrete():
    """Test discrete action game config."""
    config = GameConfig(
        name="Test Game",
        description="Test description",
        action_type="discrete",
        actions=["action_a", "action_b"],
    )

    assert config.name == "Test Game"
    assert config.action_type == "discrete"
    assert config.actions == ["action_a", "action_b"]
    assert config.output_field == "action"  # default


def test_game_config_integer():
    """Test integer action game config."""
    config = GameConfig(
        name="Test Integer Game",
        description="Test integer description",
        action_type="integer",
        output_field="offer",
        min=0,
        max=100,
    )

    assert config.action_type == "integer"
    assert config.output_field == "offer"
    assert config.min == 0
    assert config.max == 100


def test_prisoners_dilemma_config():
    """Test Prisoner's Dilemma config is properly defined."""
    assert PRISONERS_DILEMMA.name == "Prisoner's Dilemma"
    assert PRISONERS_DILEMMA.action_type == "discrete"
    assert PRISONERS_DILEMMA.actions == ["cooperate", "defect"]
    assert "CC=3" in PRISONERS_DILEMMA.payoff_summary


def test_public_goods_config():
    """Test Public Goods config is properly defined."""
    assert PUBLIC_GOODS.name == "Public Goods Game"
    assert PUBLIC_GOODS.action_type == "integer"
    assert PUBLIC_GOODS.output_field == "contribution"
    assert PUBLIC_GOODS.min == 0
    assert PUBLIC_GOODS.max == 20
