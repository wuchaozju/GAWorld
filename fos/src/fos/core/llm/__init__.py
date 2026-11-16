"""
LLM module - Multi-provider LLM client with retry, timeout, and vision support.

This module provides a unified interface for interacting with various LLM providers:
- OpenAI (GPT models with vision support)
- Google Gemini (Gemini Pro with vision support)
- Ollama (local models like Llama, Mistral)
- Mock (offline testing stub)

The module is organized into focused submodules:
- client: LLMClient class with timeout/retry/concurrency control
- validation: URL validation and SSRF prevention
- generation: Archetype-based agent generation utilities
- providers: Provider-specific implementations (openai, gemini, ollama, mock)

This is a refactored version that delegates specialized functionality
to focused submodules while maintaining backwards compatibility.

Example usage:
    from fos.core.llm import LLMClient, LLMConfig

    config = LLMConfig(
        dialect="openai",
        api_key="sk-...",
        model="gpt-4",
        supports_vision=True
    )
    client = LLMClient(config)
    response = client.chat([{"role": "user", "content": "Hello"}])
"""

# Main client class
from .client import LLMClient, create_llm_client

# Re-export validation functions for backwards compatibility
from .validation import validate_media_url, _is_private_network_url

# Re-export generation functions for backwards compatibility
from .generation import (
    generate_archetypes_from_demographics,
    add_gaussian_noise,
    generate_archetype_template,
    generate_agents_with_archetypes,
)

# Re-export mock provider utilities
from .providers.mock import _MockModel, action_to_xml

# Re-export config
from .llm_config import LLMConfig, guess_supports_vision

__all__ = [
    # Main client
    "LLMClient",
    "create_llm_client",
    # Validation
    "validate_media_url",
    "_is_private_network_url",
    # Generation
    "generate_archetypes_from_demographics",
    "add_gaussian_noise",
    "generate_archetype_template",
    "generate_agents_with_archetypes",
    # Mock
    "_MockModel",
    "action_to_xml",
    # Config
    "LLMConfig",
    "guess_supports_vision",
]
