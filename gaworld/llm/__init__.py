"""LLM provider router.

Hosts the migrated ``llm_providers`` module — provider wrappers
(Ollama, OpenAI-compatible, Anthropic-compatible) and the
``call_llm`` / ``LLMRouter`` dispatcher.

For backwards compatibility the legacy ``llm_providers`` import path is
preserved by a ``sys.modules`` alias shim at the project root, so both
``import llm_providers`` and ``from gaworld.llm.providers import ...``
return the same module object.

New code should import from ``gaworld.llm.providers`` directly.
"""

from __future__ import annotations

from gaworld.llm.providers import (  # noqa: F401 — re-export
    LLM_ROUTER,
    AnthropicProvider,
    LLMRouter,
    OllamaProvider,
    OpenAIProvider,
    call_llm,
)

__all__ = [
    "LLM_ROUTER",
    "AnthropicProvider",
    "LLMRouter",
    "OllamaProvider",
    "OpenAIProvider",
    "call_llm",
]
