"""Unit tests for thinking token disable + stripping."""

import pytest

from fos.core.agent.parsing import strip_thinking_tokens


# ---------------------------------------------------------------------------
# strip_thinking_tokens() unit tests
# ---------------------------------------------------------------------------


class TestStripThinkingTokens:
    """Verify all known thinking token formats are stripped."""

    def test_xml_think_tags(self):
        assert (
            strip_thinking_tokens('<think>some reasoning</think>{"a":1}') == '{"a":1}'
        )

    def test_xml_reasoning_tags(self):
        assert strip_thinking_tokens('<reasoning>why</reasoning>{"a":1}') == '{"a":1}'

    def test_xml_thought_tags(self):
        assert strip_thinking_tokens('<thought>hmm</thought>{"a":1}') == '{"a":1}'

    def test_xml_reflection_tags(self):
        assert strip_thinking_tokens('<reflection>hmm</reflection>{"a":1}') == '{"a":1}'

    def test_xml_analysis_tags(self):
        assert strip_thinking_tokens('<analysis>hmm</analysis>{"a":1}') == '{"a":1}'

    def test_self_closing_think_tag(self):
        assert strip_thinking_tokens('<think/>{"a":1}') == '{"a":1}'

    def test_pipe_style_tags(self):
        assert strip_thinking_tokens('|think>content|/think>{"a":1}') == '{"a":1}'

    def test_pipe_style_reasoning(self):
        assert strip_thinking_tokens('|reasoning>why|/reasoning>{"a":1}') == '{"a":1}'

    def test_special_thinking_markers(self):
        result = strip_thinking_tokens('<|thinking|>long chain<|/thinking|>{"a":1}')
        assert result == '{"a":1}'

    def test_kimi_markers(self):
        assert (
            strip_thinking_tokens('\u25c1think\u25b7stuff\u25c1/think\u25b7{"a":1}')
            == '{"a":1}'
        )

    def test_bracket_markup(self):
        assert strip_thinking_tokens('[THINK]thoughts[/THINK]{"a":1}') == '{"a":1}'

    def test_thought_for_prefix_seconds(self):
        assert strip_thinking_tokens('Thought for 2.3 seconds {"a":1}') == '{"a":1}'

    def test_thought_for_prefix_milliseconds(self):
        assert strip_thinking_tokens('Thought for 150ms {"a":1}') == '{"a":1}'

    def test_markdown_thinking_header(self):
        text = '# Thinking\nstuff\n\n{"a":1}'
        assert '{"a":1}' in strip_thinking_tokens(text)

    def test_markdown_reasoning_header(self):
        text = '## Reasoning\nsome thoughts\n\n{"a":1}'
        assert '{"a":1}' in strip_thinking_tokens(text)

    def test_bare_think_marker_at_line_start(self):
        result = strip_thinking_tokens('/think\nextra\n{"a":1}')
        assert '{"a":1}' in result

    def test_dangling_inline_marker(self):
        assert strip_thinking_tokens('content /think {"a":1}') == 'content {"a":1}'

    def test_json_prefix_before_think(self):
        assert strip_thinking_tokens('JSON<think>stuff</think>{"a":1}') == '{"a":1}'

    def test_valid_json_passes_through_unchanged(self):
        original = '{"action": "cooperate", "amount": 5}'
        assert strip_thinking_tokens(original) == original

    def test_empty_input(self):
        assert strip_thinking_tokens("") == ""

    def test_multiple_think_blocks(self):
        text = '<think>a</think>text<think>b</think>{"c":1}'
        assert strip_thinking_tokens(text) == 'text{"c":1}'

    def test_multiline_think_block(self):
        text = '<think>\nline1\nline2\n</think>\n{"a":1}'
        assert strip_thinking_tokens(text).strip() == '{"a":1}'

    def test_none_input_safe(self):
        # strip_thinking_tokens returns early on falsy input
        assert strip_thinking_tokens(None) is None


# ---------------------------------------------------------------------------
# Provider parameter tests (verify disable params are sent)
# ---------------------------------------------------------------------------


class TestOpenAIThinkingDisableParam:
    """Verify openai_chat passes thinking disable parameter."""

    def test_extra_body_contains_thinking_disabled(self, monkeypatch):
        pytest.importorskip("openai")
        from fos.core.llm.providers.openai import openai_chat

        captured_kwargs = {}

        class FakeChoice:
            message = type("msg", (), {"content": '{"ok": true}'})()

        class FakeResp:
            choices = [FakeChoice()]

        class FakeClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kwargs):
                        captured_kwargs.update(kwargs)
                        return FakeResp()

        def fake_normalize(msgs, vision, safe):
            return msgs

        monkeypatch.setattr(
            "fos.core.llm.providers.openai.normalize_messages_for_openai",
            fake_normalize,
        )

        openai_chat(
            client=FakeClient(),
            model="deepseek-reasoner",
            messages=[],
            temperature=0.0,
            max_tokens=100,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            timeout=30.0,
            allow_vision=False,
            safe_urls_func=lambda u: "valid",
            json_mode=False,
        )

        assert "extra_body" in captured_kwargs, (
            f"expected extra_body in kwargs, got keys: {list(captured_kwargs.keys())}"
        )
        assert captured_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


class TestOllamaThinkingDisableParam:
    """Verify ollama_chat passes think=false in payload."""

    def test_payload_contains_think_false(self, monkeypatch):
        pytest.importorskip("httpx")
        from fos.core.llm.providers.ollama import ollama_chat

        captured_payload = {}

        class FakeResp:
            @staticmethod
            def raise_for_status():
                pass

            @staticmethod
            def json():
                return {"message": {"content": '{"ok": true}'}}

        class FakeClient:
            @staticmethod
            def post(url, json=None, timeout=None):
                captured_payload.update(json or {})
                return FakeResp()

        def fake_normalize(msgs, vision, safe):
            return msgs

        monkeypatch.setattr(
            "fos.core.llm.providers.ollama.normalize_messages_for_ollama",
            fake_normalize,
        )

        ollama_chat(
            client=FakeClient(),
            model="qwen3",
            messages=[],
            temperature=0.0,
            top_p=1.0,
            max_tokens=100,
            timeout=30.0,
            allow_vision=False,
            safe_urls_func=lambda u: "valid",
            json_mode=False,
        )

        assert captured_payload.get("think") is False, (
            f"expected think=False in payload, got: {captured_payload}"
        )


class TestGeminiThinkingDisableParam:
    """Verify gemini_chat passes thinking_config with budget=0."""

    def test_config_contains_thinking_budget_zero(self, monkeypatch):
        pytest.importorskip("google.genai")
        from fos.core.llm.providers.gemini import gemini_chat

        captured_config = {}

        class FakeResp:
            text = '{"ok": true}'

        class FakeModel:
            @staticmethod
            def generate_content(contents, config):
                captured_config["config"] = config
                return FakeResp()

        def fake_normalize(msgs, vision, safe):
            return msgs

        monkeypatch.setattr(
            "fos.core.llm.providers.gemini.normalize_messages_for_gemini",
            fake_normalize,
        )

        gemini_chat(
            client=FakeModel(),
            model="gemini-2.0-flash",
            messages=[],
            temperature=0.0,
            max_tokens=100,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            safe_urls_func=lambda u: "valid",
            allow_vision=False,
            json_mode=False,
        )

        config = captured_config.get("config")
        assert config is not None, "expected GenerateContentConfig to be captured"
        tc = getattr(config, "thinking_config", None)
        assert tc is not None, (
            "expected thinking_config on GenerateContentConfig, got None"
        )
        assert tc.thinking_budget == 0, (
            f"expected thinking_budget=0, got {tc.thinking_budget}"
        )


class TestGeminiThinkingGracefulDegrade:
    """Verify gemini_chat gracefully handles thinking_budget=0 rejection."""

    def test_graceful_when_thinking_budget_rejected(self, monkeypatch):
        pytest.importorskip("google.genai")
        from fos.core.llm.providers.gemini import gemini_chat

        class FakeResp:
            text = '{"ok": true}'

        class FakeModel:
            @staticmethod
            def generate_content(contents, config):
                return FakeResp()

        def fake_normalize(msgs, vision, safe):
            return msgs

        monkeypatch.setattr(
            "fos.core.llm.providers.gemini.normalize_messages_for_gemini",
            fake_normalize,
        )

        # Patch ThinkingConfig to raise when budget=0 (simulating Gemini 2.5 Pro)
        class RaisingThinkingConfig:
            def __init__(self, thinking_budget=0):
                if thinking_budget == 0:
                    raise ValueError("thinking_budget=0 not supported")
                self.thinking_budget = thinking_budget

        import fos.core.llm.providers.gemini as gemini_mod

        monkeypatch.setattr(gemini_mod, "ThinkingConfig", RaisingThinkingConfig)

        # Should not raise — should catch the exception and proceed
        result = gemini_chat(
            client=FakeModel(),
            model="gemini-2.5-pro",
            messages=[],
            temperature=0.0,
            max_tokens=100,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            safe_urls_func=lambda u: "valid",
            allow_vision=False,
            json_mode=False,
        )

        assert result == '{"ok": true}'
