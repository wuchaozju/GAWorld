"""Minimal LLM client factory for CLI and demo scripts.

Provides make_clients_from_env which reads LLM config from environment
variables and returns a client dict.

Contains: make_clients_from_env
"""

import os
from typing import Dict

from fos.i18n import T
from fos.core.llm.client import create_llm_client
from fos.core.llm_config import LLMConfig, guess_supports_vision
from fos.backend.services.provider_dialect import normalize_provider_dialect


def make_clients_from_env() -> Dict[str, object]:
    """Create LLM clients from environment variables."""
    dialect = normalize_provider_dialect(os.getenv("LLM_DIALECT", "mock"))
    if dialect not in {"openai", "gemini", "mock", "ollama"}:
        raise ValueError(T("Unsupported LLM dialect: {dialect}", dialect=dialect))

    default_models = {
        "openai": "gpt-4o-mini",
        "gemini": "gemini-2.0-flash-exp",
        "mock": "mock",
        "ollama": "qwen3:4b-instruct-2507-q4_K_M",
    }
    model = os.getenv("LLM_MODEL") or default_models[dialect]

    config = LLMConfig(
        dialect=dialect,
        api_key=os.getenv("LLM_API_KEY", ""),
        model=model,
        base_url=os.getenv("LLM_BASE_URL")
        or ("http://127.0.0.1:11434" if dialect == "ollama" else None),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
        top_p=float(os.getenv("LLM_TOP_P", "1.0")),
        frequency_penalty=float(os.getenv("LLM_FREQUENCY_PENALTY", "0.0")),
        presence_penalty=float(os.getenv("LLM_PRESENCE_PENALTY", "0.0")),
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1024")),
        supports_vision=guess_supports_vision(model),
    )

    client = create_llm_client(config)
    return {"chat": client, "default": client}
