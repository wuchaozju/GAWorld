"""Integration test: DeepSeek-R1 via OpenAI-compatible API.

Verifies thinking tokens are not returned when the disable parameter is set.
Requires DEEPSEEK_API_KEY env var. Skipped if not set.
"""

import json
import os

import pytest

from fos.core.llm_config import LLMConfig


pytestmark = pytest.mark.skipif(
    not os.getenv("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set",
)


def test_deepseek_r1_thinking_disabled():
    """DeepSeek-R1 with json_mode -> response is clean parseable JSON, no <think> tags."""
    pytest.importorskip("openai")
    from fos.core.llm.client import LLMClient

    config = LLMConfig(
        dialect="openai",
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        model="deepseek-reasoner",
        base_url="https://api.deepseek.com/v1",
        max_tokens=512,
        temperature=0.0,
    )

    client = LLMClient(config)

    messages = [
        {
            "role": "user",
            "content": 'Reply with ONLY valid JSON: {"color": "<your favorite color>", "number": <1-10>}',
        }
    ]

    response = client.chat(messages, json_mode=True)

    assert response, "got empty response"
    assert "<think>" not in response.lower(), f"<think> tag leaked: {response[:200]}"
    assert "</think>" not in response.lower(), f"</think> tag leaked: {response[:200]}"

    parsed = json.loads(response)
    assert "color" in parsed, f"missing 'color' in {parsed}"
    assert "number" in parsed, f"missing 'number' in {parsed}"
    assert isinstance(parsed["number"], int | float), f"number not numeric: {parsed['number']}"
