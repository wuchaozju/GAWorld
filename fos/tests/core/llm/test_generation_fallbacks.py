"""
Tests for LLM generation.py timeout and error fallback paths.

Covers lines 141-263: generate_archetype_template timeout via threading,
exception from LLM call, empty response, unparseable JSON, and
_validate_and_normalize_probabilities / _validate_trait_ranges.

Contains: TestGenerationTimeout, TestGenerationErrorFallbacks,
          TestProbabilityValidation, TestTraitValidation
"""

import pytest
import time
from unittest.mock import MagicMock

from fos.core.llm.generation import (
    generate_archetype_template,
    _validate_and_normalize_probabilities,
    _validate_trait_ranges,
    add_gaussian_noise,
)


def _archetype(**kw):
    """Create a minimal archetype dict."""
    defaults = dict(
        id="arch_0",
        attributes={"type": "A"},
        label="type: A",
        probability=1.0,
    )
    defaults.update(kw)
    return defaults


# ---------------------------------------------------------------------------
# Timeout Path
# ---------------------------------------------------------------------------


class TestGenerationTimeout:
    """LLM call exceeding timeout returns fallback values."""

    def test_timeout_returns_fallback(self):
        """When LLM thread exceeds timeout, fallback description/roles used."""
        slow_client = MagicMock()

        def slow_chat(messages):
            time.sleep(2)
            return '{"description": "x", "roles": ["a"]}'

        slow_client.chat.side_effect = slow_chat

        archetype = _archetype()
        with pytest.warns(UserWarning, match="LLM timeout"):
            result = generate_archetype_template(
                archetype, slow_client, timeout=0  # immediate timeout
            )

        assert "description" in result
        assert "roles" in result
        assert isinstance(result["roles"], list)

    def test_slow_but_within_timeout(self):
        """LLM call completing within timeout returns real response."""
        client = MagicMock()
        client.chat.return_value = '{"description": "Fast enough", "roles": ["R1"]}'

        archetype = _archetype()
        result = generate_archetype_template(archetype, client, timeout=30)

        assert result["description"] == "Fast enough"
        assert result["roles"] == ["R1"]


# ---------------------------------------------------------------------------
# Error Fallback Paths
# ---------------------------------------------------------------------------


class TestGenerationErrorFallbacks:
    """Various LLM error conditions return fallbacks instead of crashing."""

    def test_llm_exception_returns_fallback(self):
        """When LLM raises exception, fallback is used."""
        client = MagicMock()
        client.chat.side_effect = RuntimeError("API error")

        archetype = _archetype()
        with pytest.warns(UserWarning, match="LLM error"):
            result = generate_archetype_template(archetype, client)

        assert "description" in result
        assert isinstance(result["roles"], list)

    def test_empty_response_returns_fallback(self):
        """Empty LLM response triggers fallback."""
        client = MagicMock()
        client.chat.return_value = "   "

        archetype = _archetype()
        with pytest.warns(UserWarning, match="empty response"):
            result = generate_archetype_template(archetype, client)

        assert "description" in result

    def test_no_json_in_response_returns_fallback(self):
        """Response without JSON object triggers fallback."""
        client = MagicMock()
        client.chat.return_value = "No JSON here, just text."

        archetype = _archetype()
        with pytest.warns(UserWarning, match="No JSON found"):
            result = generate_archetype_template(archetype, client)

        assert "description" in result

    def test_invalid_json_returns_fallback(self):
        """Response with malformed JSON triggers fallback."""
        client = MagicMock()
        client.chat.return_value = '{description: "broken json", roles: []}'

        archetype = _archetype()
        with pytest.warns(UserWarning, match="Invalid JSON"):
            result = generate_archetype_template(archetype, client)

        assert "description" in result

    def test_missing_description_uses_fallback(self):
        """Valid JSON missing 'description' uses fallback description."""
        client = MagicMock()
        client.chat.return_value = '{"roles": ["A", "B"]}'

        archetype = _archetype()
        with pytest.warns(UserWarning, match="Missing .description"):
            result = generate_archetype_template(archetype, client)

        assert result["roles"] == ["A", "B"]

    def test_missing_roles_uses_fallback(self):
        """Valid JSON missing 'roles' uses fallback roles."""
        client = MagicMock()
        client.chat.return_value = '{"description": "Test desc"}'

        archetype = _archetype()
        with pytest.warns(UserWarning, match="Missing or invalid .roles"):
            result = generate_archetype_template(archetype, client)

        assert result["description"] == "Test desc"
        assert isinstance(result["roles"], list)

    def test_non_string_role_skipped(self):
        """Non-string roles are filtered out."""
        client = MagicMock()
        client.chat.return_value = '{"description": "D", "roles": ["Valid", 42, ""]}'

        archetype = _archetype()
        with pytest.warns(UserWarning, match="not a valid string"):
            result = generate_archetype_template(archetype, client)

        assert result["roles"] == ["Valid"]

    def test_markdown_wrapped_json_parsed(self):
        """JSON wrapped in markdown code blocks is correctly extracted."""
        client = MagicMock()
        client.chat.return_value = '```json\n{"description": "Markdown", "roles": ["A"]}\n```'

        archetype = _archetype()
        result = generate_archetype_template(archetype, client)

        assert result["description"] == "Markdown"
        assert result["roles"] == ["A"]


# ---------------------------------------------------------------------------
# Probability Validation
# ---------------------------------------------------------------------------


class TestProbabilityValidation:
    """_validate_and_normalize_probabilities checks and fixes probabilities."""

    def test_already_normalized_no_change(self):
        """Probabilities summing to 1.0 are left unchanged."""
        archetypes = [
            {"id": "a0", "probability": 0.5},
            {"id": "a1", "probability": 0.5},
        ]
        _validate_and_normalize_probabilities(archetypes)
        assert archetypes[0]["probability"] == 0.5

    def test_unnormalized_gets_fixed(self):
        """Probabilities not summing to 1.0 are normalized."""
        archetypes = [
            {"id": "a0", "probability": 0.6},
            {"id": "a1", "probability": 0.6},
        ]
        with pytest.warns(UserWarning, match="Normalizing"):
            _validate_and_normalize_probabilities(archetypes)
        assert abs(sum(a["probability"] for a in archetypes) - 1.0) < 0.01

    def test_zero_sum_raises(self):
        """All-zero probabilities raise ValueError."""
        archetypes = [
            {"id": "a0", "probability": 0},
            {"id": "a1", "probability": 0},
        ]
        with pytest.raises(ValueError, match="sum is 0"):
            _validate_and_normalize_probabilities(archetypes)


# ---------------------------------------------------------------------------
# Trait Validation
# ---------------------------------------------------------------------------


class TestTraitValidation:
    """_validate_trait_ranges checks mean and std bounds."""

    def test_valid_traits_pass(self):
        """Traits within bounds pass validation."""
        traits = [{"name": "trust", "mean": 50, "std": 10}]
        _validate_trait_ranges(traits)  # should not raise

    def test_mean_out_of_range_raises(self):
        """Mean outside 0-100 raises ValueError."""
        traits = [{"name": "bad", "mean": 150, "std": 10}]
        with pytest.raises(ValueError, match="outside valid range"):
            _validate_trait_ranges(traits)

    def test_std_out_of_range_raises(self):
        """Std outside 0-50 raises ValueError."""
        traits = [{"name": "bad", "mean": 50, "std": 60}]
        with pytest.raises(ValueError, match="outside valid range"):
            _validate_trait_ranges(traits)


# ---------------------------------------------------------------------------
# Gaussian Noise
# ---------------------------------------------------------------------------


class TestGaussianNoise:
    """add_gaussian_noise produces values within clamp range."""

    def test_output_within_range(self):
        """Output is clamped to [min_val, max_val]."""
        for _ in range(50):
            val = add_gaussian_noise(50, 20, 0, 100)
            assert 0 <= val <= 100

    def test_negative_std_clamps_to_min(self):
        """Very negative value with high std still clamps to min."""
        for _ in range(50):
            val = add_gaussian_noise(0, 200, 0, 100)
            assert val >= 0

    def test_high_value_clamps_to_max(self):
        """Very high value with high std still clamps to max."""
        for _ in range(50):
            val = add_gaussian_noise(100, 200, 0, 100)
            assert val <= 100
