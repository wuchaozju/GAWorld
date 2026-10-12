"""
Tests for validation module.
"""

from tests.llm_prompt_testing.prompt_v2.game_configs import GameConfig, PRISONERS_DILEMMA, PUBLIC_GOODS
from tests.llm_prompt_testing.prompt_v2.validation import (
    strip_markdown_fences,
    strip_think_tags,
    validate_and_clamp,
)


class TestStripMarkdownFences:
    """Tests for strip_markdown_fences function."""

    def test_plain_json(self):
        """Test plain JSON without fences."""
        result = strip_markdown_fences('{"action": "cooperate"}')
        assert result == '{"action": "cooperate"}'

    def test_json_with_markdown_fences(self):
        """Test JSON wrapped in ```json```."""
        result = strip_markdown_fences('```json\n{"action": "cooperate"}\n```')
        assert result == '{"action": "cooperate"}'

    def test_json_with_code_fences_no_lang(self):
        """Test JSON wrapped in ``` ``` without language tag."""
        result = strip_markdown_fences('```\n{"action": "cooperate"}\n```')
        assert result == '{"action": "cooperate"}'

    def test_json_with_leading_trailing_whitespace(self):
        """Test JSON with whitespace and fences."""
        result = strip_markdown_fences('  \n```json\n{"action": "cooperate"}\n```\n  ')
        assert result == '{"action": "cooperate"}'


class TestStripThinkTags:
    """Tests for strip_think_tags function."""

    def test_no_think_tags(self):
        """Test output without think tags."""
        result = strip_think_tags('{"action": "cooperate"}')
        assert result == '{"action": "cooperate"}'

    def test_empty_think_tags(self):
        """Test output with empty think tags (SmolLM3)."""
        # Note: Use raw string with actual
        test_str = '<|thinking|><|/thinking|>{"action": "cooperate"}'
        result = strip_think_tags(test_str)
        assert result == '{"action": "cooperate"}'

    def test_populated_think_tags(self):
        """Test output with populated think tags (Qwen3)."""
        test_str = '<|thinking|>I should cooperate...<|/thinking|>{"action": "cooperate"}'
        result = strip_think_tags(test_str)
        assert result == '{"action": "cooperate"}'

    def test_multiline_think_tags(self):
        """Test output with multiline think tags."""
        test_str = '<|thinking|>\nLet me think about this...\nI will cooperate.\n<|/thinking|>\n{"action": "cooperate"}'
        result = strip_think_tags(test_str)
        assert result == '{"action": "cooperate"}'


class TestValidateAndClamp:
    """Tests for validate_and_clamp function."""

    def test_discrete_exact_match(self):
        """Test exact action match (case-insensitive)."""
        config = GameConfig(
            name="Test",
            description="Test",
            action_type="discrete",
            actions=["cooperate", "defect"],
        )

        result = {"action": "cooperate"}
        validated = validate_and_clamp(result, config)

        assert validated == {"action": "cooperate"}

    def test_discrete_case_insensitive(self):
        """Test case-insensitive matching."""
        config = GameConfig(
            name="Test",
            description="Test",
            action_type="discrete",
            actions=["Cooperate", "Defect"],
        )

        result = {"action": "cooperate"}  # lowercase
        validated = validate_and_clamp(result, config)

        assert validated == {"action": "Cooperate"}  # normalized to config case

    def test_discrete_fuzzy_match(self):
        """Test fuzzy substring matching."""
        config = GameConfig(
            name="Test",
            description="Test",
            action_type="discrete",
            actions=["listen", "speak"],
        )

        result = {"action": "listening"}  # morphed form
        validated = validate_and_clamp(result, config)

        assert validated == {"action": "listen"}  # matched via substring

    def test_discrete_invalid_action(self):
        """Test invalid action returns None."""
        config = GameConfig(
            name="Test",
            description="Test",
            action_type="discrete",
            actions=["cooperate", "defect"],
        )

        result = {"action": "choose"}  # invented action
        validated = validate_and_clamp(result, config)

        assert validated is None

    def test_discrete_missing_field(self):
        """Test missing action field returns None."""
        config = GameConfig(
            name="Test",
            description="Test",
            action_type="discrete",
            actions=["cooperate", "defect"],
        )

        result = {"reasoning": "I choose cooperate"}  # no action field
        validated = validate_and_clamp(result, config)

        assert validated is None

    def test_integer_valid_value(self):
        """Test valid integer value."""
        config = GameConfig(
            name="Test",
            description="Test",
            action_type="integer",
            output_field="offer",
            min=0,
            max=100,
        )

        result = {"offer": 50}
        validated = validate_and_clamp(result, config)

        assert validated == {"offer": 50}

    def test_integer_clamp_above_max(self):
        """Test clamping value above max."""
        config = GameConfig(
            name="Test",
            description="Test",
            action_type="integer",
            output_field="offer",
            min=0,
            max=100,
        )

        result = {"offer": 150}
        validated = validate_and_clamp(result, config)

        assert validated == {"offer": 100}  # clamped to max

    def test_integer_clamp_below_min(self):
        """Test clamping value below min."""
        config = GameConfig(
            name="Test",
            description="Test",
            action_type="integer",
            output_field="offer",
            min=0,
            max=100,
        )

        result = {"offer": -10}
        validated = validate_and_clamp(result, config)

        assert validated == {"offer": 0}  # clamped to min

    def test_integer_extract_from_string(self):
        """Test extracting integer from string."""
        config = GameConfig(
            name="Test",
            description="Test",
            action_type="integer",
            output_field="contribution",
            min=0,
            max=20,
        )

        result = {"contribution": "15 tokens"}
        validated = validate_and_clamp(result, config)

        assert validated == {"contribution": 15}

    def test_prisoners_dilemma_validation(self):
        """Test validation with actual Prisoner's Dilemma config."""
        result = {"action": "cooperate", "reasoning": "Best choice"}
        validated = validate_and_clamp(result, PRISONERS_DILEMMA)

        assert validated["action"] == "cooperate"

    def test_public_goods_validation(self):
        """Test validation with actual Public Goods config."""
        result = {"contribution": 25, "reasoning": "Generous"}
        validated = validate_and_clamp(result, PUBLIC_GOODS)

        assert validated["contribution"] == 20  # clamped to max

