"""Unit tests for LM Studio model unload in ExperimentRunner._preload_model().

Verifies that after a successful model load + warmup, all other loaded models
are unloaded via POST /api/v1/models/unload, keeping only the current model in memory.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import GameConfig
from fos.core.experiment.runner import ExperimentRunner
from fos.core.llm_config import LLMConfig


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_runner(last_model: str | None = None) -> ExperimentRunner:
    """Build a minimal ExperimentRunner for testing _preload_model."""
    llm_client = MagicMock()
    llm_client.provider.base_url = "http://127.0.0.1:1234/v1"

    agent = ExperimentAgent(
        name="agent_0",
        role_prompt="Test agent",
        properties={"provider_id": "provider_0"},
        llm_config=LLMConfig(dialect="openai"),
    )

    runner = ExperimentRunner(
        agents=[agent],
        game_config=GameConfig(name="test", description="test game", actions=["vote"], action_type="discrete"),
        llm_client=llm_client,
    )
    runner._last_model = last_model
    runner._model_blocks = [(0, 0, "mock/model")]
    runner._preloaded_blocks: set[int] = set()

    runner._trigger_model_load = MagicMock(return_value=True)
    return runner


def _mock_models_response(loaded_models: list[dict]) -> MagicMock:
    """Build a mock GET /api/v1/models response."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"models": loaded_models}
    return resp


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestPreloadUnloadsStaleModels:
    """Verify unload cleans up ALL other loaded models after warmup."""

    @patch("requests.get")
    @patch("requests.post")
    def test_unloads_previous_model(self, mock_post, mock_get):
        """When warmup succeeds, unload the previous model found in model list."""
        runner = _make_runner(last_model="old/model")

        # Arrange: warmup succeeds, GET shows old/model loaded
        client = MagicMock()
        client.provider.base_url = "http://127.0.0.1:1234/v1"
        client.chat.return_value = '{"status": "ok"}'

        mock_get.return_value = _mock_models_response([
            {"key": "new/model", "loaded_instances": ["inst-new"]},
            {"key": "old/model", "loaded_instances": ["inst-old"]},
        ])

        result = runner._preload_model("new/model", client)

        assert result is True

        # Find unload calls
        unload_calls = [
            c for c in mock_post.call_args_list
            if "/api/v1/models/unload" in str(c.args[0] if c.args else "")
        ]
        assert len(unload_calls) > 0, "Expected at least one POST to /api/v1/models/unload"

        # Check instance_id targets the stale model
        unloaded_ids = [c.kwargs.get("json", {}).get("instance_id", "") for c in unload_calls]
        assert "inst-old" in unloaded_ids, f"Expected old model unload, got {unloaded_ids}"

    @patch("requests.get")
    @patch("requests.post")
    def test_unloads_multiple_stale_models(self, mock_post, mock_get):
        """When multiple stale models are loaded, unload all of them."""
        runner = _make_runner(last_model="old/model")

        client = MagicMock()
        client.provider.base_url = "http://127.0.0.1:1234/v1"
        client.chat.return_value = '{"status": "ok"}'

        # 3 models loaded: current + 2 stale
        mock_get.return_value = _mock_models_response([
            {"key": "new/model", "loaded_instances": ["inst-new"]},
            {"key": "old/model", "loaded_instances": ["inst-old"]},
            {"key": "extra/model", "loaded_instances": ["inst-extra"]},
        ])

        result = runner._preload_model("new/model", client)
        assert result is True

        unload_calls = [
            c for c in mock_post.call_args_list
            if "/api/v1/models/unload" in str(c.args[0] if c.args else "")
        ]
        unloaded_ids = [c.kwargs.get("json", {}).get("instance_id", "") for c in unload_calls]

        assert "inst-old" in unloaded_ids, f"Expected old model unload, got {unloaded_ids}"
        assert "inst-extra" in unloaded_ids, f"Expected extra model unload, got {unloaded_ids}"
        assert "inst-new" not in unloaded_ids, "Should NOT unload the current model"

    @patch("requests.get")
    @patch("requests.post")
    def test_no_unload_when_only_current_model_loaded(self, mock_post, mock_get):
        """When only the current model is loaded, no unloads are made."""
        runner = _make_runner(last_model="old/model")

        client = MagicMock()
        client.provider.base_url = "http://127.0.0.1:1234/v1"
        client.chat.return_value = '{"status": "ok"}'

        mock_get.return_value = _mock_models_response([
            {"key": "new/model", "loaded_instances": ["inst-new"]},
        ])

        result = runner._preload_model("new/model", client)
        assert result is True

        unload_calls = [
            c for c in mock_post.call_args_list
            if "/api/v1/models/unload" in str(c.args[0] if c.args else "")
        ]
        assert len(unload_calls) == 0, f"No unload expected, got {len(unload_calls)}"


class TestWarmupFailureSkipsUnload:
    """Verify unload is skipped when warmup fails."""

    @patch("requests.get")
    @patch("requests.post")
    def test_no_unload_when_warmup_fails(self, mock_post, mock_get):
        """When all 5 warmup attempts return empty, no unload should happen."""
        runner = _make_runner(last_model="old/model")

        client = MagicMock()
        client.provider.base_url = "http://127.0.0.1:1234/v1"
        client.chat.return_value = ""

        result = runner._preload_model("new/model", client)
        assert result is True

        unload_calls = [
            c for c in mock_post.call_args_list
            if "/api/v1/models/unload" in str(c.args[0] if c.args else "")
        ]
        assert len(unload_calls) == 0, "No unload expected when warmup fails"


class TestUnloadFailureIsNonfatal:
    """Verify _preload_model still returns True when unload fails."""

    @patch("requests.get")
    @patch("requests.post")
    def test_unload_failure_nonfatal(self, mock_post, mock_get):
        """When unload returns 500, _preload_model still returns True."""
        runner = _make_runner(last_model="old/model")

        client = MagicMock()
        client.provider.base_url = "http://127.0.0.1:1234/v1"
        client.chat.return_value = '{"status": "ok"}'

        mock_get.return_value = _mock_models_response([
            {"key": "new/model", "loaded_instances": ["inst-new"]},
            {"key": "old/model", "loaded_instances": ["inst-old"]},
        ])

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        result = runner._preload_model("new/model", client)
        assert result is True

        # Unload was attempted even though it failed
        unload_calls = [
            c for c in mock_post.call_args_list
            if "/api/v1/models/unload" in str(c.args[0] if c.args else "")
        ]
        assert len(unload_calls) > 0, "Unload should have been attempted"


class TestModelEnumerationFailure:
    """Verify _preload_model handles GET /models failure gracefully."""

    @patch("requests.get")
    @patch("requests.post")
    def test_enumeration_failure_nonfatal(self, mock_post, mock_get):
        """When the GET /models call fails, unload is skipped but returns True."""
        runner = _make_runner(last_model="old/model")

        client = MagicMock()
        client.provider.base_url = "http://127.0.0.1:1234/v1"
        client.chat.return_value = '{"status": "ok"}'

        mock_get.side_effect = Exception("Connection refused")

        result = runner._preload_model("new/model", client)
        assert result is True

        # No unload calls because enumeration failed
        unload_calls = [
            c for c in mock_post.call_args_list
            if "/api/v1/models/unload" in str(c.args[0] if c.args else "")
        ]
        assert len(unload_calls) == 0, "No unload expected when model enumeration fails"
