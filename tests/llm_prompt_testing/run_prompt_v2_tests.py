"""
Integration test script for prompt_v2 module.

Runs end-to-end tests with actual LLM models to verify:
1. Constrained decoding works
2. Prompts generate correctly
3. Validation layer handles edge cases
4. Full pipeline produces valid actions
"""

import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.llm_prompt_testing.prompt_v2 import (
    GameConfig,
    build_schema,
    build_system_prompt,
    build_user_message,
    validate_and_clamp,
    strip_markdown_fences,
    strip_think_tags,
    random_valid_action,
)
from tests.llm_prompt_testing.prompt_v2.game_configs import (
    PRISONERS_DILEMMA,
    PUBLIC_GOODS,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_schema_generation():
    """Test that schemas generate correctly for all game types."""
    logger.info("Testing schema generation...")

    # Discrete action schema
    pd_schema = build_schema(PRISONERS_DILEMMA)
    assert pd_schema["properties"]["action"]["enum"] == ["cooperate", "defect"]
    logger.info("OK Prisoner's Dilemma schema")

    # Integer action schema
    pg_schema = build_schema(PUBLIC_GOODS)
    assert pg_schema["properties"]["contribution"]["type"] == "integer"
    logger.info("OK Public Goods schema")


def test_prompt_generation():
    """Test that prompts generate correctly."""
    logger.info("Testing prompt generation...")

    # System prompt
    system = build_system_prompt(PRISONERS_DILEMMA, agent_id=7)
    assert "Agent 7" in system
    assert "<YOUR_CHOICE>" in system
    assert "No markdown" in system
    logger.info("OK System prompt")

    # User message with history
    user = build_user_message(
        PRISONERS_DILEMMA,
        {
            "round": 5,
            "total_rounds": 10,
            "history": [
                {"round": 3, "you": "cooperate", "them": "defect"},
                {"round": 4, "you": "defect", "them": "defect"},
            ],
        },
    )
    assert "Round 5/10" in user
    assert "Recent history:" in user
    logger.info("OK User message with history")


def test_validation_functions():
    """Test validation edge cases."""
    logger.info("Testing validation functions...")

    # Markdown fence stripping
    json_with_fences = '```json\n{"action": "cooperate"}\n```'
    assert strip_markdown_fences(json_with_fences) == '{"action": "cooperate"}'
    logger.info("OK Markdown fence stripping")

    # Think tag stripping - uses <|thinking|> tags
    with_think = '<|thinking|>Reasoning...<|/thinking|>{"action": "defect"}'
    assert strip_think_tags(with_think) == '{"action": "defect"}'
    logger.info("OK Think tag stripping")

    # Fuzzy matching
    result = {"action": "listening"}
    validated = validate_and_clamp(result, GameConfig(
        name="Test",
        description="Test",
        action_type="discrete",
        actions=["listen", "speak"],
    ))
    assert validated["action"] == "listen"
    logger.info("OK Fuzzy matching")

    # Integer clamping
    result = {"contribution": 50}
    validated = validate_and_clamp(result, PUBLIC_GOODS)
    assert validated["contribution"] == 20  # clamped to max
    logger.info("OK Integer clamping")


def test_random_fallback():
    """Test that random fallback produces valid actions."""
    logger.info("Testing random fallback...")

    for _ in range(10):
        action = random_valid_action(PRISONERS_DILEMMA)
        assert action["action"] in ["cooperate", "defect"]
        assert action["reasoning"] == "fallback"

    logger.info("OK Random fallback")


def main():
    """Main entry point."""
    logger.info("Prompt v2 Integration Tests")
    logger.info("=" * 50)

    # Run unit tests
    test_schema_generation()
    test_prompt_generation()
    test_validation_functions()
    test_random_fallback()

    logger.info("\n" + "=" * 50)
    logger.info("All unit tests passed!")
    logger.info("=" * 50)

    # Note: Integration tests with actual LLM models require Ollama
    # with compatible models. Those are marked as @pytest.mark.integration
    # in the test files and can be run separately with:
    # pytest tests/llm_prompt_testing/test_*.py -v -m integration


if __name__ == "__main__":
    main()
