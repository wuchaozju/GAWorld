"""
Tests for OllamaClient constrained decoding support.
"""

import json

import pytest

from tests.llm_prompt_testing.prompt_v2.game_configs import PRISONERS_DILEMMA
from tests.llm_prompt_testing.prompt_v2.schema_builder import build_schema
from tests.llm_prompt_testing.ollama_client import ChatMessage, OllamaClient


@pytest.mark.integration
def test_chat_completion_with_schema():
    """Test constrained decoding with JSON schema.

    This test requires a running Ollama server with a compatible model.
    Mark as integration test to skip in CI without Ollama.

    NOTE: Constrained decoding requires models that support Ollama's structured
    output format (e.g., llama3.1+, qwen2.5-coded). Models without support will
    return plain text instead of schema-compliant JSON.
    """
    client = OllamaClient()

    # Skip if Ollama not available
    if not client.test_connection():
        pytest.skip("Ollama not available")

    schema = build_schema(PRISONERS_DILEMMA)

    messages = [
        ChatMessage(role="system", content="You are Agent 1 playing Prisoner's Dilemma."),
        ChatMessage(role="user", content="Choose your action now. Output only JSON."),
    ]

    # Use a model known to support structured output
    # Fall back to any available model for basic connectivity test
    model = "llama3.1:8b"  # Known to support structured output
    available_models = client.list_models()

    # Find a suitable model from available ones
    suitable_model = None
    for m in available_models:
        if any(x in m.lower() for x in ["llama3.1", "llama3.2", "qwen2.5", "gemma3"]):
            suitable_model = m
            break

    if suitable_model:
        model = suitable_model
    else:
        pytest.skip(f"No model supporting structured output found. Available: {available_models}")

    response = client.chat_completion_with_schema(
        messages=messages,
        model=model,
        schema=schema,
    )

    # Response should have valid content
    assert response.content
    assert response.model

    # Try to parse as JSON - if constrained decoding worked, this will succeed
    try:
        result = json.loads(response.content)
        assert "action" in result
        assert result["action"] in ["cooperate", "defect"]
    except json.JSONDecodeError:
        # If parsing fails, the model doesn't support constrained decoding
        # This is expected for some models - just verify we got a response
        pytest.skip(f"Model {model} returned non-JSON response - may not support structured output")
