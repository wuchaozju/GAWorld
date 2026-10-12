"""
Configuration management for LLM prompt testing framework.

Handles Ollama API connection settings, model configurations, and test parameters.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


@dataclass
class OllamaConfig:
    """Configuration for Ollama API connection."""

    base_url: str = "http://localhost:11434/v1"
    timeout: int = 120  # seconds
    max_retries: int = 3
    retry_delay: float = 1.0  # seconds


@dataclass
class ModelConfig:
    """Configuration for an LLM model."""

    name: str  # e.g., "qwen3:4b"
    display_name: str  # e.g., "Qwen3 4B"
    api_name: str  # Name to send to API
    max_tokens: int = 2048
    temperature: float = 0.7
    preferred_format: str = "json"  # "json", "xml", or "text"


# Available models for testing - Small 3-4B models for action format testing
AVAILABLE_MODELS: List[ModelConfig] = [
    ModelConfig(
        name="qwen3_4b",
        display_name="Qwen3 4B",
        api_name="qwen3:4b",
        preferred_format="json",  # Test with JSON first
    ),
    ModelConfig(
        name="smollm3",
        display_name="Smollm3",
        api_name="alibayram/smollm3:latest",
        preferred_format="json",  # Start with JSON
    ),
    ModelConfig(
        name="gemma3_4b_it_qat",
        display_name="Gemma3 4B IT QAT",
        api_name="gemma3:4b-it-qat",
        preferred_format="xml",  # Gemma often works well with XML
    ),
    ModelConfig(
        name="ministral_3b",
        display_name="Ministral 3B",
        api_name="ministral-3:3b",
        preferred_format="json",  # Ministral prefers JSON
    ),
    ModelConfig(
        name="phi4_mini",
        display_name="Phi4 Mini",
        api_name="phi4-mini:latest",
        preferred_format="json",  # Phi models prefer JSON
    ),
]

# Note: The goal of this framework is to find which format (JSON/XML/text) works
# best for each small model through systematic testing. Each model will be tested
# with all three formats to determine optimal configuration.


@dataclass
class TestConfig:
    """Configuration for test execution."""

    # Iteration settings
    runs_per_iteration: int = 5  # 5 runs per format for statistical significance
    max_iterations: int = 5
    stop_on_perfect: bool = True

    # Cross-LLM portability
    min_models_for_pass: int = 5  # All 5 target models must pass with at least one format

    # Format testing
    formats_to_test: List[str] = field(default_factory=lambda: ["json", "xml", "text"])
    target_success_rate: float = 0.85  # 85% success rate target per model/format

    # Output settings
    results_dir: Path = field(default_factory=lambda: Path("test_results"))
    detailed_csv: bool = True

    # Logging
    log_level: str = "INFO"
    log_file: Path = field(default_factory=lambda: Path("test_results/test.log"))


# Interaction patterns
INTERACTION_PATTERNS = [
    "Strategic Decisions",
    "Opinions & Influence",
    "Network & Spread",
    "Markets & Exchange",
    "Spatial & Movement",
    "Open Conversation",
]


# Scenarios per pattern
SCENARIOS_BY_PATTERN = {
    "Strategic Decisions": [
        "prisoners_dilemma",
        "stag_hunt",
        "minimum_effort",
    ],
    "Opinions & Influence": [
        "opinion_polarization",
        "consensus_game",
        "design_your_own",
    ],
    "Network & Spread": [
        "information_cascade",
        "opinion_spread",
        "design_your_own",
    ],
    "Markets & Exchange": [
        "basic_trading",
        "double_auction",
        "design_your_own",
    ],
    "Spatial & Movement": [
        "spatial_cooperation",
        "segregation_model",
        "design_your_own",
    ],
    "Open Conversation": [
        "focus_group",
        "deliberation",
        "design_your_own",
    ],
}


def get_model_by_name(name: str) -> ModelConfig | None:
    """Get model configuration by name."""
    for model in AVAILABLE_MODELS:
        if model.name == name or model.api_name == name:
            return model
    return None


def get_all_model_names() -> List[str]:
    """Get all available model names."""
    return [m.api_name for m in AVAILABLE_MODELS]


def get_scenarios_for_pattern(pattern: str) -> List[str]:
    """Get scenarios for a given pattern."""
    return SCENARIOS_BY_PATTERN.get(pattern, [])


# Global test configuration instance
test_config = TestConfig()


# ============================================================================
# Format Testing Helpers
# ============================================================================

# Store best format for each model (updated after testing)
MODEL_BEST_FORMATS: Dict[str, str] = {
    "qwen3_4b": "json",
    "smollm3": "json",
    "gemma3_4b_it_qat": "xml",
    "ministral_3b": "json",
    "phi4_mini": "json",
}


def get_models_by_format(format_type: str) -> List[ModelConfig]:
    """
    Get all models that prefer a specific format.

    Args:
        format_type: One of "json", "xml", "text"

    Returns:
        List of ModelConfig objects that prefer this format
    """
    return [m for m in AVAILABLE_MODELS if m.preferred_format == format_type]


def update_model_format(model_name: str, best_format: str) -> None:
    """
    Update the preferred format for a model based on test results.

    Args:
        model_name: Name or API name of the model
        best_format: The format that worked best ("json", "xml", "text")
    """
    for model in AVAILABLE_MODELS:
        if model.name == model_name or model.api_name == model_name:
            model.preferred_format = best_format
            MODEL_BEST_FORMATS[model.name] = best_format
            break


def get_model_format(model_name: str) -> str:
    """
    Get the preferred format for a model.

    Args:
        model_name: Name or API name of the model

    Returns:
        Preferred format ("json", "xml", or "text")
    """
    model = get_model_by_name(model_name)
    if model:
        return model.preferred_format
    return MODEL_BEST_FORMATS.get(model_name, "json")
