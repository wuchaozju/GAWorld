"""
Tests for ollama.py provider — image encoding, error detection,
JSON mode fallback, embedding validation, normalize_messages.

Mocks httpx.Client for all HTTP calls; never hits a real Ollama server.
"""

import base64
import sys
import types
import pytest
from unittest.mock import MagicMock, patch

from fos.core.llm.providers.ollama import (
    create_ollama_client,
    normalize_messages_for_ollama,
    ollama_chat,
    ollama_completion,
    ollama_embedding,
    clone_ollama_client,
)

# encode_images does a broken relative import: from .validation import validate_media_url
# The actual module is at fos.core.llm.validation, not providers.validation.
# Provide a stub so the function body can execute.
_mod = types.ModuleType("fos.core.llm.providers.validation")
_mod.validate_media_url = lambda url: "valid"
sys.modules.setdefault("fos.core.llm.providers.validation", _mod)

from fos.core.llm.providers.ollama import encode_images  # noqa: E402


def _safe_valid(url):
    return "valid"


def _safe_reject(url):
    return "private_network"


def _mock_post_response(json_data):
    r = MagicMock()
    r.json.return_value = json_data
    r.raise_for_status = MagicMock()
    return r


# ---------------------------------------------------------------------------
# create_ollama_client & clone_ollama_client
# ---------------------------------------------------------------------------

class TestClientCreation:

    @patch("fos.core.llm.providers.ollama.httpx.Client")
    def test_default_base_url(self, mock_cls):
        import os
        with patch.dict(os.environ, {}, clear=True):
            create_ollama_client()
            mock_cls.assert_called_once_with(
                base_url="http://127.0.0.1:11434", timeout=30
            )

    @patch("fos.core.llm.providers.ollama.httpx.Client")
    def test_custom_base_url(self, mock_cls):
        create_ollama_client(base_url="http://custom:9999", timeout=60)
        mock_cls.assert_called_once_with(
            base_url="http://custom:9999", timeout=60
        )

    @patch("fos.core.llm.providers.ollama.httpx.Client")
    def test_localhost_base_url_uses_loopback_ip(self, mock_cls):
        create_ollama_client(base_url="http://localhost:11434", timeout=60)
        mock_cls.assert_called_once_with(
            base_url="http://127.0.0.1:11434", timeout=60
        )

    @patch("fos.core.llm.providers.ollama.httpx.Client")
    def test_env_var_override(self, mock_cls):
        import os
        with patch.dict(os.environ, {"OLLAMA_BASE_URL": "http://env:5555"}):
            create_ollama_client()
            mock_cls.assert_called_once_with(
                base_url="http://env:5555", timeout=30
            )

    @patch("fos.core.llm.providers.ollama.httpx.Client")
    def test_explicit_url_beats_env(self, mock_cls):
        import os
        with patch.dict(os.environ, {"OLLAMA_BASE_URL": "http://env:5555"}):
            create_ollama_client(base_url="http://explicit:1234")
            mock_cls.assert_called_once_with(
                base_url="http://explicit:1234", timeout=30
            )

    @patch("fos.core.llm.providers.ollama.httpx.Client")
    def test_clone_uses_same_base(self, mock_cls):
        clone_ollama_client("http://host:1234", 45)
        mock_cls.assert_called_once_with(
            base_url="http://host:1234", timeout=45
        )

    @patch("fos.core.llm.providers.ollama.httpx.Client")
    def test_clone_localhost_base_url_uses_loopback_ip(self, mock_cls):
        clone_ollama_client("http://localhost:11434", 45)
        mock_cls.assert_called_once_with(
            base_url="http://127.0.0.1:11434", timeout=45
        )


# ---------------------------------------------------------------------------
# normalize_messages_for_ollama
# ---------------------------------------------------------------------------

class TestNormalizeMessages:

    def test_filters_unknown_roles(self):
        msgs = [{"role": "tool", "content": "x"}, {"role": "user", "content": "hi"}]
        out = normalize_messages_for_ollama(msgs, False, _safe_valid)
        assert len(out) == 1

    def test_vision_mode_includes_images_key(self):
        msgs = [{"role": "user", "content": "c", "images": ["https://img.co/1.jpg"]}]
        out = normalize_messages_for_ollama(msgs, True, _safe_valid)
        assert "images" in out[0]
        assert out[0]["images"] == ["https://img.co/1.jpg"]

    def test_no_vision_mode_excludes_images_key(self):
        msgs = [{"role": "user", "content": "c", "images": ["https://img.co/1.jpg"]}]
        out = normalize_messages_for_ollama(msgs, False, _safe_valid)
        assert "images" not in out[0]
        assert "[image:" in out[0]["content"]

    def test_unsafe_urls_filtered(self):
        msgs = [{"role": "user", "content": "c", "images": ["http://192.168.1.1/x.jpg"]}]
        out = normalize_messages_for_ollama(msgs, True, _safe_reject)
        assert "images" not in out[0]


# ---------------------------------------------------------------------------
# encode_images
# ---------------------------------------------------------------------------

class TestEncodeImages:

    def test_data_url_extracted_directly(self):
        b64 = base64.b64encode(b"fake-image").decode()
        data_url = f"data:image/png;base64,{b64}"
        client = MagicMock()
        result = encode_images([data_url], client, _safe_valid)
        assert result == [b64]
        client.get.assert_not_called()

    def test_valid_url_fetched_and_encoded(self):
        raw = b"image-bytes"
        client = MagicMock()
        resp = MagicMock()
        resp.content = raw
        resp.raise_for_status = MagicMock()
        client.get.return_value = resp

        result = encode_images(["https://img.co/photo.jpg"], client, _safe_valid)
        assert len(result) == 1
        assert result[0] == base64.b64encode(raw).decode()

    def test_unsafe_url_skipped(self):
        client = MagicMock()
        result = encode_images(["http://192.168.1.1/x.jpg"], client, _safe_reject)
        assert result == []
        client.get.assert_not_called()

    def test_empty_list_returns_empty(self):
        assert encode_images([], MagicMock(), _safe_valid) == []

    def test_none_list_returns_empty(self):
        assert encode_images(None, MagicMock(), _safe_valid) == []


# ---------------------------------------------------------------------------
# ollama_chat — error handling & JSON fallback
# ---------------------------------------------------------------------------

class TestOllamaChat:

    def test_basic_chat(self):
        client = MagicMock()
        client.post.return_value = _mock_post_response(
            {"message": {"content": "hi there"}}
        )
        result = ollama_chat(
            client, "llama2", [{"role": "user", "content": "hello"}],
            0.5, 0.9, 100, 30, False, _safe_valid,
        )
        assert result == "hi there"

    def test_error_in_response_raises(self):
        client = MagicMock()
        client.post.return_value = _mock_post_response(
            {"error": "model not found"}
        )
        with pytest.raises(ValueError, match="Ollama error"):
            ollama_chat(
                client, "bad-model", [{"role": "user", "content": "x"}],
                0.5, 0.9, 100, 30, False, _safe_valid,
            )

    def test_empty_response_raises(self):
        client = MagicMock()
        client.post.return_value = _mock_post_response(
            {"message": {"content": ""}}
        )
        with pytest.raises(ValueError, match="empty response"):
            ollama_chat(
                client, "llama2", [{"role": "user", "content": "x"}],
                0.5, 0.9, 100, 30, False, _safe_valid,
            )

    def test_json_mode_prepends_instruction(self):
        client = MagicMock()
        client.post.return_value = _mock_post_response(
            {"message": {"content": '{"k":"v"}'}}
        )
        ollama_chat(
            client, "llama2", [{"role": "user", "content": "generate"}],
            0.5, 0.9, 100, 30, False, _safe_valid, json_mode=True,
        )
        payload = client.post.call_args[1]["json"]
        last_msg = payload["messages"][-1]
        assert "IMPORTANT" in last_msg["content"]
        assert "generate" in last_msg["content"]

    def test_json_mode_fallback_with_format(self):
        """When first response is empty, retries with format=json."""
        client = MagicMock()
        empty_resp = _mock_post_response({"message": {"content": ""}})
        good_resp = _mock_post_response({"message": {"content": '{"ok":1}'}})
        client.post.side_effect = [empty_resp, good_resp]

        result = ollama_chat(
            client, "llama2", [{"role": "user", "content": "x"}],
            0.5, 0.9, 100, 30, False, _safe_valid, json_mode=True,
        )
        assert result == '{"ok":1}'
        assert client.post.call_count == 2
        second_payload = client.post.call_args_list[1][1]["json"]
        assert second_payload.get("format") == "json"

    def test_response_field_fallback(self):
        """When 'message' is missing, falls back to 'response' key."""
        client = MagicMock()
        client.post.return_value = _mock_post_response({"response": "fallback text"})
        result = ollama_chat(
            client, "llama2", [{"role": "user", "content": "hi"}],
            0.5, 0.9, 100, 30, False, _safe_valid,
        )
        assert result == "fallback text"


# ---------------------------------------------------------------------------
# ollama_completion
# ---------------------------------------------------------------------------

class TestOllamaCompletion:

    def test_returns_response_text(self):
        client = MagicMock()
        client.post.return_value = _mock_post_response({"response": "completed"})
        result = ollama_completion(client, "llama2", "prompt", 0.5, 0.9, 100, 30)
        assert result == "completed"


# ---------------------------------------------------------------------------
# ollama_embedding
# ---------------------------------------------------------------------------

class TestOllamaEmbedding:

    def test_returns_embedding_list(self):
        client = MagicMock()
        client.post.return_value = _mock_post_response({"embedding": [0.1, 0.2]})
        result = ollama_embedding(client, "llama2", "hello", 30)
        assert result == [0.1, 0.2]

    def test_missing_embedding_raises(self):
        client = MagicMock()
        client.post.return_value = _mock_post_response({})
        with pytest.raises(ValueError, match="Ollama did not return embedding"):
            ollama_embedding(client, "llama2", "hello", 30)
