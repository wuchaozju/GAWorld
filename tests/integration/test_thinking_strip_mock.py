"""Integration test: Mock provider returns <think>-wrapped JSON -> chat() returns clean JSON."""

import json

import pytest

from fos.core.agent.parsing import strip_thinking_tokens
from fos.core.llm_config import LLMConfig


class TestMockThinkingStripped:
    """Verify thinking tokens are stripped via the full LLMClient.chat() path."""

    @pytest.fixture
    def client_with_thinking_mock(self):
        """Create an LLMClient with a mock that returns <think>-wrapped content."""
        pytest.importorskip("openai")
        from fos.core.llm.client import LLMClient

        class ThinkingMock:
            """Mock that returns a response with <think> tags before the JSON."""

            def chat(self, messages, json_mode=False):
                return '<think>long chain of reasoning here</think>\n{"action": "cooperate", "amount": 5}'

        config = LLMConfig(dialect="mock", model="thinking-mock")
        client = LLMClient(config)
        client.client = ThinkingMock()
        return client

    def test_thinking_tags_stripped_from_mock_response(self, client_with_thinking_mock):
        """chat() with mock provider -> no <think> tags, valid JSON."""
        messages = [{"role": "user", "content": "What do you do?"}]
        result = client_with_thinking_mock.chat(messages, json_mode=True)

        assert "<think>" not in result, f"<think> tag leaked: {result!r}"
        assert "</think>" not in result, f"</think> tag leaked: {result!r}"

        parsed = json.loads(result)
        assert parsed == {"action": "cooperate", "amount": 5}

    def test_clean_mock_response_passes_through(self, client_with_thinking_mock):
        """chat() without thinking tags -> response unchanged."""
        # Override to return clean JSON
        client_with_thinking_mock.client.chat = (
            lambda msgs, json_mode=False: '{"action": "defect"}'
        )
        messages = [{"role": "user", "content": "What do you do?"}]
        result = client_with_thinking_mock.chat(messages, json_mode=True)

        assert result == '{"action": "defect"}'


class TestStripThinkingTokensIntegration:
    """Integration-level tests for strip_thinking_tokens with realistic payloads."""

    def test_realistic_qwen3_output(self):
        """Simulate Qwen3 output: <think> block then JSON response."""
        response = '<think>\nOkay, the user wants me to choose an action.\nI should cooperate because it benefits both.\n</think>\n\n{"action": "cooperate", "reasoning": "mutual benefit"}'

        cleaned = strip_thinking_tokens(response)
        assert "<think>" not in cleaned
        assert "</think>" not in cleaned
        parsed = json.loads(cleaned)
        assert parsed["action"] == "cooperate"

    def test_realistic_deepseek_r1_output(self):
        """Simulate DeepSeek-R1 output with thinking before JSON."""
        response = '<think>Let me analyze this step by step.\nThe scenario is a prisoner\'s dilemma with repeated interactions.\nGiven the history, the optimal move is to cooperate.\n</think>\n{"action": "cooperate"}'

        cleaned = strip_thinking_tokens(response)
        assert "<think>" not in cleaned
        parsed = json.loads(cleaned)
        assert parsed["action"] == "cooperate"

    def test_realistic_special_markers_output(self):
        """Simulate GGUF quant output with <|thinking|> markers."""
        response = '<|thinking|>\nUser asked for action. I\'ll choose cooperate.\n<|/thinking|>\n{"action": "cooperate"}'

        cleaned = strip_thinking_tokens(response)
        assert "<|thinking|>" not in cleaned
        assert "<|/thinking|>" not in cleaned
        parsed = json.loads(cleaned)
        assert parsed["action"] == "cooperate"

    def test_json_with_embedded_think_in_field_value(self):
        """Ensure literal 'think' in JSON values is not stripped."""
        response = '{"action": "think", "description": "I think this is best"}'
        cleaned = strip_thinking_tokens(response)
        assert cleaned == response
        parsed = json.loads(cleaned)
        assert parsed["action"] == "think"

    def test_markdown_code_block_with_json(self):
        """Verify markdown-wrapped JSON survives after thinking section is stripped."""
        # Realistic model output: thinking section, blank line, then code block
        response = '# Thinking\nI will output JSON.\n\n```json\n{"action": "cooperate"}\n```'

        cleaned = strip_thinking_tokens(response)
        # The thinking section should be gone
        assert "# Thinking" not in cleaned
        # The JSON should still be present
        assert '"action": "cooperate"' in cleaned
