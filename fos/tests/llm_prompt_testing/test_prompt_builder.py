"""
Tests for prompt_builder module.
"""

from tests.llm_prompt_testing.prompt_v2.game_configs import (
    GameConfig,
    PRISONERS_DILEMMA,
    PUBLIC_GOODS,
)
from tests.llm_prompt_testing.prompt_v2.prompt_builder import (
    build_system_prompt,
    build_user_message,
)


def test_build_system_prompt_discrete():
    """Test system prompt for discrete actions."""
    config = GameConfig(
        name="Test Game",
        description="Cooperate = 5 points, Defect = 1 point",
        action_type="discrete",
        actions=["cooperate", "defect"],
    )

    prompt = build_system_prompt(config, agent_id=7)

    assert "Agent 7" in prompt
    assert "Test Game" in prompt
    assert "Cooperate = 5 points" in prompt
    assert '"cooperate"' in prompt
    assert '"defect"' in prompt
    assert "<YOUR_CHOICE>" in prompt
    assert "No markdown" in prompt
    assert "No code fences" in prompt


def test_build_system_prompt_integer():
    """Test system prompt for integer actions."""
    config = GameConfig(
        name="Test Integer Game",
        description="Choose an amount to offer",
        action_type="integer",
        output_field="offer",
        min=0,
        max=100,
    )

    prompt = build_system_prompt(config)

    assert "<INTEGER>" in prompt
    assert "0 to 100" in prompt
    assert '"offer"' in prompt
    assert "No markdown" in prompt


def test_build_user_message_first_round():
    """Test user message for first round (no history)."""
    config = GameConfig(
        name="Test",
        description="Test",
        action_type="discrete",
        actions=["a", "b"],
        payoff_summary="A=5, B=1",
    )

    message = build_user_message(config, {"round": 1, "total_rounds": 10})

    assert "Round 1/10" in message
    assert "Payoffs: A=5, B=1" in message
    assert "No history yet" in message
    assert "Choose your action now" in message


def test_build_user_message_with_history():
    """Test user message with history (capped at 3 rounds)."""
    config = GameConfig(
        name="Test",
        description="Test",
        action_type="discrete",
        actions=["a", "b"],
    )

    # Create 5 rounds of history
    history = [{"round": i, "action": "cooperate"} for i in range(1, 6)]

    message = build_user_message(config, {"round": 6, "total_rounds": 10, "history": history})

    # Should only include last 3 rounds
    assert "Recent history:" in message
    # History should be JSON with only last 3 entries
    history_start = message.index("Recent history:")
    history_str = message[history_start:]
    # Round 3 should appear, round 1 should not
    assert '"round": 3' in history_str
    assert '"round": 4' in history_str
    assert '"round": 5' in history_str
    assert '"round": 1' not in history_str
    assert '"round": 2' not in history_str


def test_build_user_message_with_context():
    """Test user message with additional context."""
    config = GameConfig(
        name="Test",
        description="Test",
        action_type="discrete",
        actions=["a", "b"],
    )

    message = build_user_message(
        config,
        {
            "round": 1,
            "total_rounds": 10,
            "context": "Your opponent chose defect last round."
        }
    )

    assert "Your opponent chose defect" in message


def test_prisoners_dilemma_prompt():
    """Test actual Prisoner's Dilemma prompt."""
    system = build_system_prompt(PRISONERS_DILEMMA, agent_id=7)

    assert "Agent 7" in system
    assert "Prisoner's Dilemma" in system
    assert '"cooperate", "defect"' in system
    assert "<YOUR_CHOICE>" in system

    user = build_user_message(
        PRISONERS_DILEMMA,
        {"round": 5, "total_rounds": 10, "history": [{"round": 4, "you": "cooperate", "them": "defect"}]}
    )

    assert "Round 5/10" in user
    assert "CC=3, DD=1" in user


def test_public_goods_prompt():
    """Test actual Public Goods prompt."""
    system = build_system_prompt(PUBLIC_GOODS)

    assert "Public Goods Game" in system
    assert "<INTEGER>" in system
    assert "0 to 20" in system

    user = build_user_message(
        PUBLIC_GOODS,
        {"round": 3, "total_rounds": 10}
    )

    assert "Choose your contribution now" in user
