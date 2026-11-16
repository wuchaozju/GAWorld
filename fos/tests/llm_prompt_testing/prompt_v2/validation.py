"""
Validation layer for LLM outputs.

Handles fuzzy matching, clamping, and parsing edge cases identified
from empirical testing of 3-4B models.
"""

import re
from typing import Optional
from .game_configs import GameConfig


def strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` wrapping that 14% of outputs include.

    Models like Phi-4 Mini (10x) and Ministral (7x) frequently wrap
    valid JSON in markdown code fences.

    Args:
        text: Raw model output

    Returns:
        Text with markdown fences removed
    """
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (with optional language tag like ```json)
        text = re.sub(r'^```\w*\n?', '', text)
        # Remove closing fence
        text = re.sub(r'\n?```\s*$', '', text)
    return text.strip()


def strip_think_tags(text: str) -> str:
    """Remove <|thinking|><|/thinking|> blocks from model output.

    Models like Qwen3 and SmolLM3 emit empty or populated think tags
    before the actual JSON response.

    Args:
        text: Raw model output

    Returns:
        Text with think tags removed
    """
    # Handle <|thinking|>...</thinking|> tags - use re.DOTALL for multi-line blocks
    return re.sub(r'<\|thinking\|>.*?<\|/thinking\|>\s*', '', text, flags=re.DOTALL).strip()


def validate_and_clamp(result: dict, game_config: GameConfig) -> Optional[dict]:
    """Validate and fix the model's output. Returns None if unrecoverable.

    This implements the validation layer from the three-layer architecture:
    - Discrete actions: exact match, fuzzy match, or None
    - Integer values: clamp to valid range
    - String integers: extract and convert

    Args:
        result: Parsed JSON from model output
        game_config: The game configuration

    Returns:
        Validated result dict, or None if validation fails (triggers retry)
    """
    field = game_config.output_field

    if field not in result:
        return None

    if game_config.action_type == "discrete":
        valid_actions = game_config.actions
        raw_action = str(result[field]).strip().lower()

        # Exact match (case-insensitive)
        for valid in valid_actions:
            if raw_action == valid.lower():
                result[field] = valid
                return result

        # Fuzzy: check if a valid action is a substring
        # Handles "listening" -> "listen"
        for valid in valid_actions:
            if valid.lower() in raw_action or raw_action in valid.lower():
                result[field] = valid
                return result

        return None  # No valid action found - trigger retry

    elif game_config.action_type == "integer":
        val = result[field]

        # Handle strings like "15 tokens" or "fifteen" -> extract number
        if isinstance(val, str):
            nums = re.findall(r'-?\d+', val)
            val = int(nums[0]) if nums else 0

        val = int(val)
        # Clamp to valid range
        val = max(game_config.min, min(game_config.max, val))
        result[field] = val
        return result

    return result
