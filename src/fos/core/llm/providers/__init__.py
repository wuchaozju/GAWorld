"""
LLM provider implementations.

This package contains provider-specific implementations for various LLM backends:

- openai: OpenAI API provider (GPT models, vision support)
- gemini: Google Gemini API provider (Gemini Pro, vision support)
- ollama: Local Ollama provider (llama, mistral, etc.)
- mock: Mock provider for offline testing

Each provider exports:
- Client creation functions
- Message normalization functions
- Chat, completion, and embedding functions

Note: Provider modules use lazy imports to avoid requiring all dependencies
to be installed. Only import providers you actually use.
"""

# Mock provider has no external dependencies
from .mock import _MockModel, action_to_xml

# Lazy imports for providers with external dependencies
# These are only imported when actually used to avoid import errors
# when optional dependencies are not installed

def _import_openai():
    """Lazy import OpenAI provider."""
    from .openai import (
        create_openai_client,
        normalize_messages_for_openai,
        openai_chat,
        openai_completion,
        openai_embedding,
        clone_openai_client,
    )
    return {
        "create_openai_client": create_openai_client,
        "normalize_messages_for_openai": normalize_messages_for_openai,
        "openai_chat": openai_chat,
        "openai_completion": openai_completion,
        "openai_embedding": openai_embedding,
        "clone_openai_client": clone_openai_client,
    }


def _import_gemini():
    """Lazy import Gemini provider."""
    from .gemini import (
        create_gemini_client,
        normalize_messages_for_gemini,
        gemini_chat,
        gemini_completion,
        gemini_embedding,
        clone_gemini_client,
    )
    return {
        "create_gemini_client": create_gemini_client,
        "normalize_messages_for_gemini": normalize_messages_for_gemini,
        "gemini_chat": gemini_chat,
        "gemini_completion": gemini_completion,
        "gemini_embedding": gemini_embedding,
        "clone_gemini_client": clone_gemini_client,
    }


def _import_ollama():
    """Lazy import Ollama provider."""
    from .ollama import (
        create_ollama_client,
        normalize_messages_for_ollama,
        ollama_chat,
        ollama_completion,
        ollama_embedding,
        clone_ollama_client,
    )
    return {
        "create_ollama_client": create_ollama_client,
        "normalize_messages_for_ollama": normalize_messages_for_ollama,
        "ollama_chat": ollama_chat,
        "ollama_completion": ollama_completion,
        "ollama_embedding": ollama_embedding,
        "clone_ollama_client": clone_ollama_client,
    }


__all__ = [
    # Mock
    "_MockModel",
    "action_to_xml",
    # Lazy import functions
    "_import_openai",
    "_import_gemini",
    "_import_ollama",
]
