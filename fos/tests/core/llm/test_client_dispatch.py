"""
Tests for provider dispatch in core/llm/client.py chat/completion/embedding methods.

Mocks _get_openai/_get_gemini/_get_ollama to verify correct provider function is
called with correct arguments for each dialect. Does not duplicate existing
test_llm.py integration tests.

Contains: TestChatDispatch, TestCompletionDispatch, TestEmbeddingDispatch,
TestDispatchErrorPropagation
"""

from unittest.mock import MagicMock, patch

import pytest

from fos.core.llm import LLMClient
from fos.core.llm_config import LLMConfig


def _openai_dict(**overrides):
    """Complete provider dict for OpenAI with sensible mock defaults."""
    d = {
        "create_openai_client": MagicMock(),
        "openai_chat": MagicMock(return_value="chat-resp"),
        "openai_completion": MagicMock(return_value="comp-resp"),
        "openai_embedding": MagicMock(return_value=[0.1]),
        "normalize_messages_for_openai": MagicMock(return_value=[]),
        "clone_openai_client": MagicMock(),
    }
    d.update(overrides)
    return d


def _gemini_dict(**overrides):
    d = {
        "create_gemini_client": MagicMock(),
        "gemini_chat": MagicMock(return_value="chat-resp"),
        "gemini_completion": MagicMock(return_value="comp-resp"),
        "gemini_embedding": MagicMock(return_value=[0.1]),
        "normalize_messages_for_gemini": MagicMock(return_value=[]),
        "clone_gemini_client": MagicMock(),
    }
    d.update(overrides)
    return d


def _ollama_dict(**overrides):
    d = {
        "create_ollama_client": MagicMock(),
        "ollama_chat": MagicMock(return_value="chat-resp"),
        "ollama_completion": MagicMock(return_value="comp-resp"),
        "ollama_embedding": MagicMock(return_value=[0.1]),
        "normalize_messages_for_ollama": MagicMock(return_value=[]),
        "clone_ollama_client": MagicMock(),
    }
    d.update(overrides)
    return d


class TestChatDispatch:
    """chat() routes to the correct provider function."""

    def test_openai_dispatch(self):
        chat_fn = MagicMock(return_value="openai-resp")
        with patch("fos.core.llm.client._get_openai", return_value=_openai_dict(openai_chat=chat_fn)):
            c = LLMClient(LLMConfig(dialect="openai", api_key="k", model="m"))
            c.max_retries = 0
            c.retry_backoff_s = 0.0
            result = c.chat([{"role": "user", "content": "hi"}])
        assert result == "openai-resp"
        assert chat_fn.call_args[1]["json_mode"] is False

    def test_openai_dispatch_json_mode(self):
        chat_fn = MagicMock(return_value="json-resp")
        with patch("fos.core.llm.client._get_openai", return_value=_openai_dict(openai_chat=chat_fn)):
            c = LLMClient(LLMConfig(dialect="openai", api_key="k", model="m"))
            c.max_retries = 0
            c.retry_backoff_s = 0.0
            c.chat([{"role": "user", "content": "go"}], json_mode=True)
        assert chat_fn.call_args[1]["json_mode"] is True

    def test_gemini_dispatch(self):
        chat_fn = MagicMock(return_value="gemini-resp")
        with patch("fos.core.llm.client._get_gemini", return_value=_gemini_dict(gemini_chat=chat_fn)):
            c = LLMClient(LLMConfig(dialect="gemini", api_key="k", model="m"))
            c.max_retries = 0
            c.retry_backoff_s = 0.0
            result = c.chat([{"role": "user", "content": "hi"}])
        assert result == "gemini-resp"
        assert chat_fn.call_args[1]["model"] == "m"

    def test_ollama_dispatch(self):
        chat_fn = MagicMock(return_value="ollama-resp")
        with patch("fos.core.llm.client._get_ollama", return_value=_ollama_dict(ollama_chat=chat_fn)):
            c = LLMClient(LLMConfig(dialect="ollama", api_key="k", model="m"))
            c.max_retries = 0
            c.retry_backoff_s = 0.0
            result = c.chat([{"role": "user", "content": "hi"}])
        assert result == "ollama-resp"

    def test_mock_dispatch(self):
        with patch("fos.core.llm.client._get_openai", return_value={
            "normalize_messages_for_openai": MagicMock(return_value=[{"role": "user", "content": "hi"}])
        }):
            c = LLMClient(LLMConfig(dialect="mock"))
            c.max_retries = 0
            c.retry_backoff_s = 0.0
            c.client.chat = MagicMock(return_value="mock-resp")
            result = c.chat([{"role": "user", "content": "hi"}])
        assert result == "mock-resp"


class TestCompletionDispatch:
    """completion() routes to the correct provider function."""

    def test_openai_completion(self):
        comp_fn = MagicMock(return_value="comp-resp")
        with patch("fos.core.llm.client._get_openai", return_value=_openai_dict(openai_completion=comp_fn)):
            c = LLMClient(LLMConfig(dialect="openai", api_key="k", model="m"))
            c.max_retries = 0
            c.retry_backoff_s = 0.0
            result = c.completion("prompt")
        assert result == "comp-resp"
        assert comp_fn.call_args[1]["prompt"] == "prompt"

    def test_gemini_completion(self):
        comp_fn = MagicMock(return_value="g-comp")
        with patch("fos.core.llm.client._get_gemini", return_value=_gemini_dict(gemini_completion=comp_fn)):
            c = LLMClient(LLMConfig(dialect="gemini", api_key="k", model="m"))
            c.max_retries = 0
            c.retry_backoff_s = 0.0
            result = c.completion("prompt")
        assert result == "g-comp"

    def test_ollama_completion(self):
        comp_fn = MagicMock(return_value="o-comp")
        with patch("fos.core.llm.client._get_ollama", return_value=_ollama_dict(ollama_completion=comp_fn)):
            c = LLMClient(LLMConfig(dialect="ollama", api_key="k", model="m"))
            c.max_retries = 0
            c.retry_backoff_s = 0.0
            result = c.completion("prompt")
        assert result == "o-comp"

    def test_mock_completion_returns_empty(self):
        c = LLMClient(LLMConfig(dialect="mock"))
        assert c.completion("prompt") == ""


class TestEmbeddingDispatch:
    """embedding() routes to the correct provider function."""

    def test_openai_embedding(self):
        emb_fn = MagicMock(return_value=[0.1, 0.2])
        with patch("fos.core.llm.client._get_openai", return_value=_openai_dict(openai_embedding=emb_fn)):
            c = LLMClient(LLMConfig(dialect="openai", api_key="k", model="m"))
            c.max_retries = 0
            c.retry_backoff_s = 0.0
            result = c.embedding("text")
        assert result == [0.1, 0.2]
        assert emb_fn.call_args[1]["text"] == "text"

    def test_gemini_embedding(self):
        emb_fn = MagicMock(return_value=[0.3])
        with patch("fos.core.llm.client._get_gemini", return_value=_gemini_dict(gemini_embedding=emb_fn)):
            c = LLMClient(LLMConfig(dialect="gemini", api_key="k", model="m"))
            c.max_retries = 0
            c.retry_backoff_s = 0.0
            result = c.embedding("text")
        assert result == [0.3]

    def test_ollama_embedding(self):
        emb_fn = MagicMock(return_value=[0.4])
        with patch("fos.core.llm.client._get_ollama", return_value=_ollama_dict(ollama_embedding=emb_fn)):
            c = LLMClient(LLMConfig(dialect="ollama", api_key="k", model="m"))
            c.max_retries = 0
            c.retry_backoff_s = 0.0
            result = c.embedding("text")
        assert result == [0.4]

    def test_mock_embedding_returns_empty(self):
        c = LLMClient(LLMConfig(dialect="mock"))
        assert c.embedding("text") == []


class TestDispatchErrorPropagation:
    """Provider errors are propagated, not swallowed."""

    def test_openai_chat_propagates_error(self):
        chat_fn = MagicMock(side_effect=RuntimeError("API down"))
        with patch("fos.core.llm.client._get_openai", return_value=_openai_dict(openai_chat=chat_fn)):
            c = LLMClient(LLMConfig(dialect="openai", api_key="k", model="m"))
            c.max_retries = 0
            c.retry_backoff_s = 0.0
            with pytest.raises(RuntimeError, match="API down"):
                c.chat([{"role": "user", "content": "hi"}])

    def test_gemini_completion_propagates_error(self):
        comp_fn = MagicMock(side_effect=ValueError("bad key"))
        with patch("fos.core.llm.client._get_gemini", return_value=_gemini_dict(gemini_completion=comp_fn)):
            c = LLMClient(LLMConfig(dialect="gemini", api_key="k", model="m"))
            c.max_retries = 0
            c.retry_backoff_s = 0.0
            with pytest.raises(ValueError, match="bad key"):
                c.completion("prompt")
