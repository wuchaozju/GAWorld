"""
Pytest fixtures for Ollama-based smoke tests.

Provides fixtures for creating LLM clients, output directories, and
scenario configurations.
"""

import pytest
from pathlib import Path
from fos.core.llm_config import LLMConfig
from fos.core.llm import create_llm_client

# Ollama configuration
OLLAMA_BASE_URL = "http://localhost:11434"

# User's installed models (all 4B parameter models)
OLLAMA_MODELS = [
    "alibayram/hunyuan:4b",
    "qwen3:4b-instruct-2507-q4_K_M",
    "phi4-mini:latest",
    "gemma3:4b-it-qat",
]

# Default model for quick tests (picks first available)
DEFAULT_MODEL = "phi4-mini:latest"


@pytest.fixture(scope="session")
def ollama_models():
    """Return list of Ollama models to test with."""
    return OLLAMA_MODELS


@pytest.fixture
def ollama_client_factory():
    """Factory fixture to create Ollama LLM clients.

    Usage:
        client = ollama_client_factory("phi4-mini:latest")
    """
    def _create(model: str, temperature: float = 0.7, max_tokens: int = 512):
        config = LLMConfig(
            dialect="ollama",
            model=model,
            base_url=OLLAMA_BASE_URL,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return create_llm_client(config)
    return _create


@pytest.fixture
def output_dir():
    """Return output directory for test results."""
    output_path = Path("test_results/scenario_smoke_tests")
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path


@pytest.fixture
def default_llm_client(ollama_client_factory):
    """Create default LLM client for single-model tests."""
    return ollama_client_factory(DEFAULT_MODEL)
