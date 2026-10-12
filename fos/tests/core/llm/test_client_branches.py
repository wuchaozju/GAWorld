"""
Tests for uncovered branches in core/llm/client.py.

Targets: clone() unknown dialect, chat/completion/embedding unknown dialect,
mock completion/embedding returns, max_concurrent clamp, empty response,
create_llm_client factory, semaphore inheritance on clone.

Contains: TestCloneBranches, TestUnknownDialectBranches, TestMockShortCircuits,
TestMaxConcurrentClamp, TestEmptyResponse, TestCreateFactory
"""

import os
from threading import BoundedSemaphore
from unittest.mock import MagicMock, patch

import pytest

from fos.core.llm import LLMClient
from fos.core.llm_config import LLMConfig


def _mock_cfg() -> LLMConfig:
    """Return a mock-dialect LLMConfig."""
    return LLMConfig(
        dialect="mock", api_key="", model="mock",
        base_url=None, temperature=0.1, top_p=1.0,
        frequency_penalty=0.0, presence_penalty=0.0, max_tokens=256,
    )


class TestCloneBranches:
    """clone() ValueError on unknown dialect and semaphore independence."""

    def test_clone_unknown_dialect_raises(self):
        cfg = _mock_cfg()
        client = LLMClient(cfg)
        # Tamper with dialect after init
        client.provider.dialect = "bogus"
        with pytest.raises(ValueError, match="Unknown LLM provider dialect"):
            client.clone()

    def test_clone_has_independent_semaphore(self):
        cfg = _mock_cfg()
        client = LLMClient(cfg)
        clone = client.clone()
        assert clone._sem is not client._sem
        assert isinstance(clone._sem, BoundedSemaphore)


class TestUnknownDialectBranches:
    """chat/completion/embedding raise ValueError on unknown dialect."""

    def _client_with_bad_dialect(self):
        cfg = _mock_cfg()
        client = LLMClient(cfg)
        client.provider.dialect = "bogus"
        # Bypass _with_timeout_and_retry by setting retries to 0
        client.max_retries = 0
        client.retry_backoff_s = 0.0
        return client

    def test_chat_unknown_dialect(self):
        c = self._client_with_bad_dialect()
        with pytest.raises(ValueError, match="Unknown LLM dialect"):
            c.chat([{"role": "user", "content": "hi"}])

    def test_completion_unknown_dialect(self):
        c = self._client_with_bad_dialect()
        with pytest.raises(ValueError, match="Unknown LLM dialect"):
            c.completion("hello")

    def test_embedding_unknown_dialect(self):
        c = self._client_with_bad_dialect()
        with pytest.raises(ValueError, match="Unknown LLM dialect"):
            c.embedding("hello")


class TestMockShortCircuits:
    """Mock dialect returns '' for completion, [] for embedding."""

    def test_mock_completion_returns_empty(self):
        c = LLMClient(_mock_cfg())
        assert c.completion("hello") == ""

    def test_mock_embedding_returns_empty_list(self):
        c = LLMClient(_mock_cfg())
        assert c.embedding("hello") == []


class TestMaxConcurrentClamp:
    """max_concurrent < 1 is clamped to 1."""

    def test_zero_clamped_to_one(self):
        with patch.dict(os.environ, {"LLM_MAX_CONCURRENT_PER_CLIENT": "0"}):
            c = LLMClient(_mock_cfg())
            # BoundedSemaphore(1) — we verify by checking the _sem._value
            assert c._sem._value == 1

    def test_negative_clamped_to_one(self):
        with patch.dict(os.environ, {"LLM_MAX_CONCURRENT_PER_CLIENT": "-5"}):
            c = LLMClient(_mock_cfg())
            assert c._sem._value == 1


class TestEmptyResponse:
    """Provider returning empty string is propagated, not crashed."""

    def test_mock_chat_empty_response(self):
        c = LLMClient(_mock_cfg())
        # Replace internal mock with one that returns ""
        c.client = MagicMock()
        c.client.chat.return_value = ""
        with patch("fos.core.llm.client._get_openai") as mock_oai:
            mock_oai.return_value = {
                "normalize_messages_for_openai": lambda msgs, v, s: msgs
            }
            result = c.chat([{"role": "user", "content": "hi"}])
        assert result == ""


class TestCreateFactory:
    """create_llm_client factory returns a working LLMClient."""

    def test_factory_returns_client(self):
        from fos.core.llm.client import create_llm_client
        c = create_llm_client(_mock_cfg())
        assert isinstance(c, LLMClient)
        assert c.provider.dialect == "mock"
