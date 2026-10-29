"""
Tests for validation layer (Layer 3 of Three-Layer Architecture).
"""


from fos.core.experiment.game_configs import PRISONERS_DILEMMA, MINIMUM_EFFORT
from fos.core.experiment.validation import (
    extract_json,
    strip_markdown_fences,
    strip_think_tags,
    validate_and_clamp,
)


def test_strip_markdown_fences():
    """Remove markdown code fences from JSON output."""
    result = strip_markdown_fences('```json\n{"action": "cooperate"}\n```')
    assert result == '{"action": "cooperate"}'


def test_strip_markdown_fences_no_language():
    """Remove markdown code fences without language specifier."""
    result = strip_markdown_fences('```\n{"action": "cooperate"}\n```')
    assert result == '{"action": "cooperate"}'


def test_strip_markdown_fences_plain_json():
    """Return plain JSON unchanged."""
    result = strip_markdown_fences('{"action": "cooperate"}')
    assert result == '{"action": "cooperate"}'


def test_strip_think_tags():
    """Remove thinking tags from model output."""
    result = strip_think_tags('<|thinking|>Let me think...<|/thinking|>\n{"action": "cooperate"}')
    assert result == '{"action": "cooperate"}'


def test_strip_think_tags_empty():
    """Remove empty thinking tags."""
    result = strip_think_tags('<|thinking|><|/thinking|>\n{"action": "cooperate"}')
    assert result == '{"action": "cooperate"}'


def test_strip_think_tags_multiline():
    """Remove multiline thinking tags."""
    result = strip_think_tags(
        '<|thinking|>\nLine 1\nLine 2\n<|/thinking|>\n{"action": "cooperate"}'
    )
    assert result == '{"action": "cooperate"}'


def test_validate_exact_match():
    """Accept exact action match (case-insensitive)."""
    result = {"action": "COOPERATE"}
    validated = validate_and_clamp(result, PRISONERS_DILEMMA)
    assert validated["action"] == "cooperate"


def test_validate_exact_match_lowercase():
    """Accept exact lowercase action match."""
    result = {"action": "cooperate"}
    validated = validate_and_clamp(result, PRISONERS_DILEMMA)
    assert validated["action"] == "cooperate"


def test_validate_exact_match_defect():
    """Accept exact defect action match (case-insensitive)."""
    result = {"action": "DEFECT"}
    validated = validate_and_clamp(result, PRISONERS_DILEMMA)
    assert validated["action"] == "defect"


def test_validate_fuzzy_match():
    """Accept fuzzy substring match - valid action contained in output."""
    # "cooperate" is contained in "I will cooperate"
    result = {"action": "I will cooperate"}
    validated = validate_and_clamp(result, PRISONERS_DILEMMA)
    assert validated["action"] == "cooperate"


def test_validate_fuzzy_match_reverse():
    """Accept fuzzy substring match - output contained in valid action."""
    # This tests the reverse: output substring is contained in valid action
    result = {"action": "coop"}
    validated = validate_and_clamp(result, PRISONERS_DILEMMA)
    assert validated["action"] == "cooperate"


def test_validate_fuzzy_match_fail():
    """Return None when no valid action matches."""
    result = {"action": "listening"}  # Not in actions
    validated = validate_and_clamp(result, PRISONERS_DILEMMA)
    assert validated is None


def test_validate_integer_clamp_above_max():
    """Clamp integer to max when above valid range."""
    result = {"effort": 15}  # Above max of 7
    validated = validate_and_clamp(result, MINIMUM_EFFORT)
    assert validated["effort"] == 7


def test_validate_integer_clamp_below_min():
    """Clamp integer to min when below valid range."""
    result = {"effort": -1}  # Below min of 1
    validated = validate_and_clamp(result, MINIMUM_EFFORT)
    assert validated["effort"] == 1


def test_validate_integer_in_range():
    """Accept integer within valid range."""
    result = {"effort": 5}
    validated = validate_and_clamp(result, MINIMUM_EFFORT)
    assert validated["effort"] == 5


def test_validate_integer_at_boundaries():
    """Accept integers at range boundaries."""
    result = {"effort": 1}
    validated = validate_and_clamp(result, MINIMUM_EFFORT)
    assert validated["effort"] == 1

    result = {"effort": 7}
    validated = validate_and_clamp(result, MINIMUM_EFFORT)
    assert validated["effort"] == 7


def test_validate_string_to_int():
    """Convert string numbers to integers."""
    result = {"effort": "5"}
    validated = validate_and_clamp(result, MINIMUM_EFFORT)
    assert validated["effort"] == 5


def test_validate_string_with_text_to_int():
    """Extract number from string containing text."""
    result = {"effort": "5 tokens"}
    validated = validate_and_clamp(result, MINIMUM_EFFORT)
    assert validated["effort"] == 5


def test_validate_negative_string_to_int():
    """Extract negative number from string."""
    result = {"effort": "-3"}
    validated = validate_and_clamp(result, MINIMUM_EFFORT)
    # Clamped to min of 1
    assert validated["effort"] == 1


def test_validate_missing_field():
    """Return None when output field is missing."""
    result = {"other_field": "cooperate"}
    validated = validate_and_clamp(result, PRISONERS_DILEMMA)
    assert validated is None


def test_validate_stag_hunt_actions():
    """Test validation with Stag Hunt actions."""
    from fos.core.experiment.game_configs import STAG_HUNT

    result = {"action": "stag"}
    validated = validate_and_clamp(result, STAG_HUNT)
    assert validated["action"] == "stag"

    result = {"action": "hare"}
    validated = validate_and_clamp(result, STAG_HUNT)
    assert validated["action"] == "hare"


def test_validate_information_cascade_actions():
    """Test validation with Information Cascade actions."""
    from fos.core.experiment.game_configs import INFORMATION_CASCADE

    result = {"action": "majority_red"}
    validated = validate_and_clamp(result, INFORMATION_CASCADE)
    assert validated["action"] == "majority_red"

    result = {"action": "majority_blue"}
    validated = validate_and_clamp(result, INFORMATION_CASCADE)
    assert validated["action"] == "majority_blue"


def test_validate_consensus_game_range():
    """Test validation with Consensus Game (0-100 range)."""
    from fos.core.experiment.game_configs import CONSENSUS_GAME

    result = {"value": 150}  # Above max of 100
    validated = validate_and_clamp(result, CONSENSUS_GAME)
    assert validated["value"] == 100

    result = {"value": -10}  # Below min of 0
    validated = validate_and_clamp(result, CONSENSUS_GAME)
    assert validated["value"] == 0

    result = {"value": 50}  # In range
    validated = validate_and_clamp(result, CONSENSUS_GAME)
    assert validated["value"] == 50


# Tests for extract_json function
def test_extract_json_plain():
    """Extract plain JSON object."""
    result = extract_json('{"action": "cooperate"}')
    assert result == '{"action": "cooperate"}'


def test_extract_json_with_trailing_tokens():
    """Extract JSON with trailing model-specific tokens."""
    result = extract_json('{"action": "cooperate"}</im_end|></answer>')
    assert result == '{"action": "cooperate"}'


def test_extract_json_with_trailing_text():
    """Extract JSON with trailing explanation text."""
    result = extract_json('{"action": "cooperate"}\nSome explanation text')
    assert result == '{"action": "cooperate"}'


def test_extract_json_with_markdown_fences():
    """Extract JSON from markdown fence with trailing tokens."""
    result = extract_json('```json\n{"action": "cooperate"}\n```\n</answer>')
    assert result == '{"action": "cooperate"}'


def test_extract_json_with_think_tags():
    """Extract JSON after stripping think tags."""
    result = extract_json('<|thinking|>Let me think...<|/thinking|>\n{"action": "cooperate"}')
    assert result == '{"action": "cooperate"}'


def test_extract_json_nested():
    """Extract nested JSON object."""
    result = extract_json('{"action": "cooperate", "metadata": {"reason": "trust"}}')
    assert result == '{"action": "cooperate", "metadata": {"reason": "trust"}}'


def test_extract_json_nested_with_trailing():
    """Extract nested JSON with trailing content."""
    result = extract_json('{"outer": {"inner": "value"}}\n</answer>')
    assert result == '{"outer": {"inner": "value"}}'


def test_extract_json_invalid_returns_original():
    """Return original text when no valid JSON found."""
    result = extract_json('not json at all')
    assert result == 'not json at all'


def test_extract_json_empty_object():
    """Extract empty JSON object."""
    result = extract_json('{}')
    assert result == '{}'


def test_extract_json_with_whitespace():
    """Extract JSON with surrounding whitespace."""
    result = extract_json('  \n  {"action": "cooperate"}  \n  ')
    assert result == '{"action": "cooperate"}'


def test_extract_json_multiple_objects():
    """Extract first valid JSON when multiple objects present."""
    result = extract_json('{"first": 1}{"second": 2}')
    assert result == '{"first": 1}'
