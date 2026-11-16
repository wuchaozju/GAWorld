"""
Tests for openai.py provider — JSON fallback, role filtering,
vision formatting, media URL handling, error paths.

Mocks the OpenAI SDK client; never makes real API calls.
"""

import pytest
from unittest.mock import MagicMock, patch

from fos.core.llm.providers.openai import (
    create_openai_client,
    normalize_messages_for_openai,
    openai_chat,
    openai_completion,
    openai_embedding,
    clone_openai_client,
)


def _mock_response(text="Hello"):
    r = MagicMock()
    r.choices = [MagicMock()]
    r.choices[0].message.content = text
    return r


def _safe_valid(url):
    return "valid"


def _safe_reject(url):
    return "private_network"


# ---------------------------------------------------------------------------
# create_openai_client
# ---------------------------------------------------------------------------

class TestCreateClient:

    @patch("fos.core.llm.providers.openai.OpenAI")
    def test_creates_client_with_key(self, mock_cls):
        create_openai_client("sk-test")
        mock_cls.assert_called_once_with(api_key="sk-test", base_url=None)

    @patch("fos.core.llm.providers.openai.OpenAI")
    def test_creates_client_with_base_url(self, mock_cls):
        create_openai_client("sk-test", base_url="http://localhost:1234")
        mock_cls.assert_called_once_with(
            api_key="sk-test", base_url="http://localhost:1234"
        )


# ---------------------------------------------------------------------------
# clone_openai_client
# ---------------------------------------------------------------------------

class TestCloneClient:

    @patch("fos.core.llm.providers.openai.OpenAI")
    def test_clones_from_provider(self, mock_cls):
        provider = MagicMock()
        provider.api_key = "sk-x"
        provider.base_url = "http://custom"
        clone_openai_client(provider, 10.0)
        mock_cls.assert_called_once_with(
            api_key="sk-x", base_url="http://custom"
        )


# ---------------------------------------------------------------------------
# normalize_messages_for_openai
# ---------------------------------------------------------------------------

class TestNormalizeMessages:

    def test_filters_unknown_roles(self):
        msgs = [
            {"role": "tool", "content": "data"},
            {"role": "user", "content": "hi"},
        ]
        out = normalize_messages_for_openai(msgs, False, _safe_valid)
        assert len(out) == 1
        assert out[0]["role"] == "user"

    def test_all_valid_roles_pass(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "usr"},
            {"role": "assistant", "content": "ast"},
        ]
        out = normalize_messages_for_openai(msgs, False, _safe_valid)
        assert [m["role"] for m in out] == ["system", "user", "assistant"]

    def test_vision_mode_formats_image_parts(self):
        msgs = [{"role": "user", "content": "look", "images": ["https://img.co/1.jpg"]}]
        out = normalize_messages_for_openai(msgs, True, _safe_valid)
        content = out[0]["content"]
        assert isinstance(content, list)
        types = [p["type"] for p in content]
        assert "text" in types
        assert "image_url" in types

    def test_no_vision_mode_uses_text_placeholder(self):
        msgs = [{"role": "user", "content": "look", "images": ["https://img.co/1.jpg"]}]
        out = normalize_messages_for_openai(msgs, False, _safe_valid)
        assert isinstance(out[0]["content"], str)
        assert "[image:" in out[0]["content"]

    def test_unsafe_urls_stripped(self):
        msgs = [{"role": "user", "content": "c", "images": ["http://192.168.1.1/img.jpg"]}]
        out = normalize_messages_for_openai(msgs, True, _safe_reject)
        content = out[0]["content"]
        assert isinstance(content, str)  # no image parts — all filtered
        assert "image_url" not in str(content)

    def test_non_string_media_skipped(self):
        msgs = [{"role": "user", "content": "c", "images": [123, None]}]
        out = normalize_messages_for_openai(msgs, False, _safe_valid)
        assert "[image:" not in out[0]["content"]

    def test_audio_and_video_placeholders(self):
        msgs = [{"role": "user", "content": "c", "audio": ["https://a.co/s.mp3"], "video": ["https://v.co/m.mp4"]}]
        out = normalize_messages_for_openai(msgs, False, _safe_valid)
        text = out[0]["content"]
        assert "[audio:" in text
        assert "[video:" in text

    def test_empty_content_defaults_to_empty_string(self):
        msgs = [{"role": "user"}]
        out = normalize_messages_for_openai(msgs, False, _safe_valid)
        assert out[0]["content"] == ""


# ---------------------------------------------------------------------------
# openai_chat — JSON mode fallback
# ---------------------------------------------------------------------------

class TestOpenAIChatJsonFallback:

    @patch("fos.core.llm.providers.openai.OpenAI")
    def test_json_mode_empty_triggers_retry(self, mock_cls):
        client = mock_cls.return_value
        # First call returns empty, second returns content
        empty_resp = _mock_response("")
        good_resp = _mock_response('{"k": "v"}')
        client.chat.completions.create.side_effect = [empty_resp, good_resp]

        result = openai_chat(
            client, "gpt-4", [{"role": "user", "content": "do it"}],
            0.5, 100, 0, 0, 30, False, _safe_valid, json_mode=True,
        )
        assert result == '{"k": "v"}'
        assert client.chat.completions.create.call_count == 2
        # Second call should NOT have response_format
        second_call = client.chat.completions.create.call_args_list[1]
        assert "response_format" not in second_call[1]

    @patch("fos.core.llm.providers.openai.OpenAI")
    def test_json_mode_retry_prepends_instruction(self, mock_cls):
        client = mock_cls.return_value
        empty_resp = _mock_response("")
        good_resp = _mock_response('{"a": 1}')
        client.chat.completions.create.side_effect = [empty_resp, good_resp]

        openai_chat(
            client, "gpt-4",
            [{"role": "user", "content": "give me json"}],
            0.5, 100, 0, 0, 30, False, _safe_valid, json_mode=True,
        )
        second_msgs = client.chat.completions.create.call_args_list[1][1]["messages"]
        user_msg = second_msgs[-1]["content"]
        assert "IMPORTANT" in user_msg
        assert "give me json" in user_msg

    @patch("fos.core.llm.providers.openai.OpenAI")
    def test_json_mode_both_empty_raises(self, mock_cls):
        client = mock_cls.return_value
        client.chat.completions.create.side_effect = [
            _mock_response(""), _mock_response("")
        ]
        with pytest.raises(ValueError, match="empty response"):
            openai_chat(
                client, "gpt-4", [{"role": "user", "content": "x"}],
                0.5, 100, 0, 0, 30, False, _safe_valid, json_mode=True,
            )

    @patch("fos.core.llm.providers.openai.OpenAI")
    def test_non_json_empty_still_raises(self, mock_cls):
        client = mock_cls.return_value
        client.chat.completions.create.return_value = _mock_response("")
        with pytest.raises(ValueError, match="empty response"):
            openai_chat(
                client, "gpt-4", [{"role": "user", "content": "x"}],
                0.5, 100, 0, 0, 30, False, _safe_valid, json_mode=False,
            )

    @patch("fos.core.llm.providers.openai.OpenAI")
    def test_json_mode_with_vision_list_content(self, mock_cls):
        """Fallback handles list-type content in the last user message."""
        client = mock_cls.return_value
        empty_resp = _mock_response("")
        good_resp = _mock_response('{"ok": true}')
        client.chat.completions.create.side_effect = [empty_resp, good_resp]

        result = openai_chat(
            client, "gpt-4o",
            [{"role": "user", "content": "describe", "images": ["https://img.co/x.jpg"]}],
            0.5, 100, 0, 0, 30, True, _safe_valid, json_mode=True,
        )
        assert result == '{"ok": true}'
        assert client.chat.completions.create.call_count == 2


# ---------------------------------------------------------------------------
# openai_completion & openai_embedding
# ---------------------------------------------------------------------------

class TestCompletionAndEmbedding:

    @patch("fos.core.llm.providers.openai.OpenAI")
    def test_completion_returns_text(self, mock_cls):
        client = mock_cls.return_value
        client.completions.create.return_value = _mock_response("done")
        # completion uses .text not .content
        client.completions.create.return_value.choices[0].text = "done"
        assert openai_completion(client, "gpt-4", "hello", 0.5, 50, 30) == "done"

    @patch("fos.core.llm.providers.openai.OpenAI")
    def test_embedding_returns_list(self, mock_cls):
        client = mock_cls.return_value
        client.embeddings.create.return_value.data[0].embedding = [0.1, 0.2]
        assert openai_embedding(client, "text-emb", "hi", 10) == [0.1, 0.2]
