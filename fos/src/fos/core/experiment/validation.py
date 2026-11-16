"""
Validation layer for LLM outputs (Layer 3 of Three-Layer Architecture).

Handles fuzzy matching, clamping, and parsing edge cases for small models.
"""

import json
import re
from typing import Optional

from fos.core.experiment.game_configs import GameConfig


def strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` wrapping that some models output.

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

    Some models emit thinking tags before the actual JSON response.

    Args:
        text: Raw model output

    Returns:
        Text with think tags removed
    """
    cleaned = re.sub(r'<\|thinking\|>.*?<\|/thinking\|>\s*', '', text, flags=re.DOTALL)
    cleaned = re.sub(r'JSON<think>.*?</think>\s*', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'<think>.*?</think>\s*', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'^[A-Za-z]+<think>.*?</think>\s*', '', cleaned, flags=re.DOTALL)
    return cleaned.strip()


def extract_json(text: str) -> str:
    """Extract the first valid JSON object from text, ignoring trailing content.

    Handles cases where LLMs output:
    - {"action": "cooperate"}</im_end|></answer>
    - ```json\n{"action": "cooperate"}\n```\n</answer>
    - {"action": "cooperate"}\nSome explanation text

    Args:
        text: Raw model output

    Returns:
        Extracted JSON string, or original text if no valid JSON found
    """
    text = text.strip()

    # First strip markdown fences and think tags
    text = strip_markdown_fences(text)
    text = strip_think_tags(text)
    text = text.strip()

    # Try to find JSON object boundaries by tracking braces
    brace_depth = 0
    start_idx = None

    for i in range(len(text)):
        if text[i] == '{':
            if start_idx is None:
                start_idx = i
            brace_depth += 1
        elif text[i] == '}':
            brace_depth -= 1
            if brace_depth == 0 and start_idx is not None:
                # Found complete JSON object
                json_str = text[start_idx:i+1]
                # Validate it's parseable
                try:
                    json.loads(json_str)
                    return json_str
                except json.JSONDecodeError:
                    # Not valid JSON, keep looking
                    start_idx = None
                    continue

    # Fallback: return original text (will fail in controller with clear error)
    return text


def validate_and_clamp(result: dict, game_config: GameConfig) -> Optional[dict]:
    """Validate and fix the model's output. Returns None if unrecoverable.

    This implements Layer 3 of the Three-Layer Architecture:
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

        # Handle nested action format: {"action": {"name": "speak"}}
        # Some LLMs return actions as dicts instead of strings
        action_value = result[field]
        if isinstance(action_value, dict):
            action_value = action_value.get("name") or action_value.get("action") or ""

        raw_action = str(action_value).strip().lower()

        # Normalize both sides: strip underscores, spaces, hyphens
        # so "vote_no" matches "Vote No" after lowercasing
        def _norm(s: str) -> str:
            return re.sub(r'[_\-\s]', '', s)
        raw_norm = _norm(raw_action)

        # Exact match (case-insensitive, normalized)
        for valid in valid_actions:
            if raw_norm == _norm(valid.lower()):
                result[field] = valid
                return result

        # Fuzzy: check if a valid action is a substring (normalized)
        # Handles "listening" -> "listen"
        for valid in valid_actions:
            vn = _norm(valid.lower())
            if vn in raw_norm or raw_norm in vn:
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
