"""
Tests for core/llm/providers/gemini.py — direct unit tests for all public functions.

Mocks google.genai so tests run without the SDK installed.
Covers: create_gemini_client, clone_gemini_client, normalize_messages_for_gemini,
gemini_chat, gemini_completion, gemini_embedding.

Contains: TestCreateClient, TestCloneClient, TestNormalizeMessages,
TestGeminiChat, TestGeminiCompletion, TestGeminiEmbedding
"""

import sys
from unittest.mock import MagicMock, patch


# Ensure google.genai is importable (mock it if not installed)
if "google.genai" not in sys.modules:
    mock_genai = MagicMock()
    mock_genai_types = MagicMock()
    sys.modules["google"] = MagicMock()
    sys.modules["google.genai"] = mock_genai
    sys.modules["google.genai.types"] = mock_genai_types

from fos.core.llm.providers.gemini import (
    create_gemini_client,
    clone_gemini_client,
    normalize_messages_for_gemini,
    gemini_chat,
    gemini_completion,
    gemini_embedding,
)


class TestCreateClient:
    """create_gemini_client configures and returns a GenerativeModel."""

    @patch("fos.core.llm.providers.gemini.genai")
    def test_configures_api_key(self, mock_genai):
        create_gemini_client("gemini-pro", "my-key")
        mock_genai.configure.assert_called_once_with(api_key="my-key")
        mock_genai.GenerativeModel.assert_called_once_with(model_name="gemini-pro")

    @patch("fos.core.llm.providers.gemini.genai")
    def test_returns_model_instance(self, mock_genai):
        mock_genai.GenerativeModel.return_value = "model-obj"
        assert create_gemini_client("m", "k") == "model-obj"


class TestCloneClient:
    """clone_gemini_client creates an independent instance from an LLMConfig."""

    @patch("fos.core.llm.providers.gemini.genai")
    def test_clone_reconfigures(self, mock_genai):
        provider = MagicMock(api_key="orig-key", model="orig-model")
        clone_gemini_client(provider)
        mock_genai.configure.assert_called_once_with(api_key="orig-key")
        mock_genai.GenerativeModel.assert_called_once_with(model_name="orig-model")


class TestNormalizeMessages:
    """normalize_messages_for_gemini: role mapping, vision, unsafe URL filtering."""

    @staticmethod
    def _safe_urls(url):
        """Always-valid URL validator for tests."""
        return "valid"

    def test_user_role_stays_user(self):
        out = normalize_messages_for_gemini(
            [{"role": "user", "content": "hi"}], False, self._safe_urls
        )
        assert out[0]["role"] == "user"

    def test_assistant_role_becomes_model(self):
        out = normalize_messages_for_gemini(
            [{"role": "assistant", "content": "hi"}], False, self._safe_urls
        )
        assert out[0]["role"] == "model"

    def test_system_role_preserved(self):
        """system messages are kept (role mapped to user for Gemini)."""
        out = normalize_messages_for_gemini(
            [{"role": "system", "content": "sys"}], False, self._safe_urls
        )
        assert out[0]["role"] == "user"

    def test_unknown_role_skipped(self):
        out = normalize_messages_for_gemini(
            [{"role": "tool", "content": "data"}], False, self._safe_urls
        )
        assert out == []

    def test_vision_mode_includes_image_url_parts(self):
        out = normalize_messages_for_gemini(
            [{"role": "user", "content": "look", "images": ["https://x.com/i.png"]}],
            True,
            self._safe_urls,
        )
        assert any("image_url" in p for p in out[0]["parts"])

    def test_no_vision_uses_placeholder(self):
        out = normalize_messages_for_gemini(
            [{"role": "user", "content": "look", "images": ["https://x.com/i.png"]}],
            False,
            self._safe_urls,
        )
        assert "[image:" in out[0]["parts"][0]["text"]

    def test_unsafe_url_filtered(self):
        def reject(url):
            return "private_network"

        out = normalize_messages_for_gemini(
            [{"role": "user", "content": "hi", "images": ["http://evil/img"]}],
            True,
            reject,
        )
        # No image_url parts since URL was rejected
        assert all("image_url" not in p for p in out[0]["parts"])

    def test_audio_and_video_placeholders(self):
        out = normalize_messages_for_gemini(
            [{"role": "user", "content": "media", "audio": ["https://a/u.mp3"],
              "video": ["https://v/clip.mp4"]}],
            False,
            self._safe_urls,
        )
        text = out[0]["parts"][0]["text"]
        assert "[audio:" in text
        assert "[video:" in text


class TestGeminiChat:
    """gemini_chat: response extraction, JSON mode, empty fallback."""

    def _make_client(self, text_val=None, candidates=None):
        client = MagicMock()
        resp = MagicMock()
        if text_val:
            resp.text = text_val
        else:
            del resp.text
        resp.candidates = candidates
        client.generate_content.return_value = resp
        return client

    def test_basic_response(self):
        client = self._make_client(text_val="  hello  ")
        result = gemini_chat(
            client, "m", [{"role": "user", "content": "hi"}],
            0.5, 100, 0.9, 0.0, 0.0, lambda u: "valid", False,
        )
        assert result == "hello"

    def test_json_mode_sets_mime_type(self):
        mock_types = sys.modules["google.genai.types"]
        mock_types.GenerateContentConfig = MagicMock()
        client = self._make_client(text_val='{"k":1}')
        gemini_chat(
            client, "m", [{"role": "user", "content": "go"}],
            0.5, 100, 0.9, 0.0, 0.0, lambda u: "valid", False, json_mode=True,
        )
        call_kwargs = mock_types.GenerateContentConfig.call_args[1]
        assert call_kwargs["response_mime_type"] == "application/json"

    def test_empty_response_returns_empty_string(self):
        client = self._make_client(text_val=None, candidates=None)
        result = gemini_chat(
            client, "m", [{"role": "user", "content": "hi"}],
            0.5, 100, 0.9, 0.0, 0.0, lambda u: "valid", False,
        )
        assert result == ""

    def test_fallback_to_candidates(self):
        part = MagicMock()
        part.text = "from-parts"
        content = MagicMock()
        content.parts = [part]
        cand = MagicMock()
        cand.content = content
        client = self._make_client(text_val=None, candidates=[cand])
        result = gemini_chat(
            client, "m", [{"role": "user", "content": "hi"}],
            0.5, 100, 0.9, 0.0, 0.0, lambda u: "valid", False,
        )
        assert result == "from-parts"


class TestGeminiCompletion:
    """gemini_completion: basic and empty response."""

    def test_returns_text(self):
        client = MagicMock()
        client.generate_content.return_value = MagicMock(text="done  ")
        assert gemini_completion(client, "prompt") == "done"

    def test_empty_response(self):
        client = MagicMock()
        resp = MagicMock()
        resp.text = None
        client.generate_content.return_value = resp
        assert gemini_completion(client, "prompt") == ""


class TestGeminiEmbedding:
    """gemini_embedding returns the embedding list from genai."""

    @patch("fos.core.llm.providers.gemini.genai")
    def test_returns_embedding(self, mock_genai):
        mock_genai.embed_content.return_value = {"embedding": [0.1, 0.2]}
        result = gemini_embedding("model-x", "text")
        mock_genai.embed_content.assert_called_once_with(model="model-x", content="text")
        assert result == [0.1, 0.2]
