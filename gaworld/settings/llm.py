"""LLM provider and routing defaults."""

from __future__ import annotations

import os
from typing import Any


def llm_settings() -> dict[str, Any]:
    """Return legacy top-level LLM defaults plus the multi-provider block."""
    return {
        # LLM (legacy defaults for compatibility)
        "ollama_url": "http://localhost:11434/api/generate",
        # "model_name": "gemma3n:e4b",
        "model_name": "qwen3.5:9b",
        "llm_timeout": 600,
        # LLM routing (multi-backend)
        "llm": {
            "providers": {
                "ollama_local": {
                    "type": "ollama",
                    "url": "http://localhost:11434/api/generate",
                    "model": "gemma3n:e4b",
                    "timeout": 120,
                },
                "ollama_gemma4": {
                    "type": "ollama",
                    "url": "http://localhost:11434/api/generate",
                    "model": "gemma4:e4b",
                    # Local generation is slow; 120s often times out on long agent
                    # prompts and would trip the multi-seed checkpoint-stop.
                    "timeout": 600,
                },
                "ollama_qwen": {
                    "type": "ollama",
                    "url": "http://localhost:11434/api/generate",
                    "model": "qwen3.5:9b",
                    "timeout": 600,
                },
                "omlx_qwen": {
                    "type": "openai",
                    "base_url": "http://127.0.0.1:8000/v1",
                    "model": "Qwen3.5-9B-MLX-4bit",
                    # omlx exposes an OpenAI-compatible API locally.
                    # If your local server does not require auth, this placeholder is sufficient.
                    "api_key": os.environ.get("OMLX_API_KEY", "omlx-local"),
                    # Stream responses so the client receives incremental chunks
                    # during long local prefill/generation phases.
                    "stream": True,
                    # Keep local generations bounded; the simulator makes many calls.
                    "max_tokens": 256,
                    "temperature": 0.2,
                    "timeout": 600,
                },
                "openai_gpt": {
                    "type": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-5.4",
                    "api_key_env": "OPENAI_API_KEY",
                    "timeout": 120,
                },
                "minimax": {
                    "type": "anthropic",
                    # Use a Minimax-specific base URL so the generic ANTHROPIC_BASE_URL
                    # (set by Claude Code / other Anthropic tooling) cannot misroute this
                    # provider to api.anthropic.com.
                    "base_url": os.environ.get("MINIMAX_BASE_URL", "https://api.minimaxi.com/anthropic"),
                    "model": os.environ.get("MINIMAX_MODEL", "MiniMax-M2.7"),
                    "api_key_env": "MINIMAX_API_KEY",
                    # Only trust the Minimax key here; falling back to ANTHROPIC_AUTH_TOKEN /
                    # ANTHROPIC_API_KEY would send an Anthropic token to Minimax and 401.
                    "api_key_envs": ["MINIMAX_API_KEY"],
                    # China-region Minimax expects the raw secret key in Authorization.
                    # Set MINIMAX_AUTHORIZATION_SCHEME=bearer for endpoints that require Bearer tokens.
                    "authorization_scheme": os.environ.get("MINIMAX_AUTHORIZATION_SCHEME", "raw"),
                    "authorization_retry_schemes": ["bearer"],
                    "include_x_api_key": False,
                    "timeout": 120,
                    # MiniMax-M2 is a reasoning model and its `thinking` block counts
                    # against max_tokens. A 512 budget is spent entirely on reasoning,
                    # so the response carries no text block at all and every caller
                    # receives an empty completion. Leave enough room for reasoning
                    # plus a full document-length answer.
                    "max_tokens": int(os.environ.get("MINIMAX_MAX_TOKENS", "16384")),
                },
                "local_qwen4b": {
                    "type": "openai",
                    "base_url": "http://127.0.0.1:8080/v1",
                    "model": "qwen3-4b",
                    "api_key": "not-needed",
                    "stream": False,
                    "max_tokens": 512,
                    "temperature": 0.2,
                    "timeout": 600,
                },
            },
            "routing": {
                "default": "ollama_gemma4",
                "tasks": {
                    "schedule": "ollama_gemma4",
                },
                # Tried in order after the primary fails. gemma4:e4b is small
                # enough to answer inside its timeout when a bigger local model
                # stalls, so one slow call no longer aborts a whole run.
                "fallback": ["ollama_gemma4"],
            },
        },
    }
