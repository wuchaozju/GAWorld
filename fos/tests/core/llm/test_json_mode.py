"""
Tests for json_mode parameter in LLMClient.
"""

from fos.core.llm.client import LLMClient
from fos.core.llm.llm_config import LLMConfig


def test_json_mode_parameter():
    """Test that json_mode parameter is accepted by LLMClient.chat()."""
    config = LLMConfig(dialect="mock", api_key="test")
    client = LLMClient(config)

    # Mock client should accept json_mode without error
    result = client.chat(
        [{"role": "user", "content": "test"}],
        json_mode=True
    )

    # Mock returns a response string; we're just checking it doesn't crash
    assert isinstance(result, str)
    assert len(result) > 0  # Mock always returns some content


def test_json_mode_default_false():
    """Test that json_mode defaults to False."""
    config = LLMConfig(dialect="mock", api_key="test")
    client = LLMClient(config)

    # Call without json_mode parameter
    result = client.chat([{"role": "user", "content": "test"}])

    # Mock returns a response string
    assert isinstance(result, str)
    assert len(result) > 0


def test_json_mode_signature():
    """Test that chat method has json_mode parameter with correct default."""
    import inspect
    from fos.core.llm.client import LLMClient

    sig = inspect.signature(LLMClient.chat)
    json_mode_param = sig.parameters.get("json_mode")

    assert json_mode_param is not None, "json_mode parameter not found"
    assert json_mode_param.default is False, "json_mode should default to False"
