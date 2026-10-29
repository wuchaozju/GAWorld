"""
Tests for comprehension module.
"""

from unittest.mock import Mock, patch
from tests.llm_prompt_testing.prompt_v2.game_configs import PRISONERS_DILEMMA, PUBLIC_GOODS
from tests.llm_prompt_testing.prompt_v2.comprehension import verify_comprehension


@patch('tests.llm_prompt_testing.prompt_v2.comprehension.OllamaClient')
def test_verify_comprehension_prisoners_dilemma_pass(mock_client_class):
    """Test comprehension check passes for PD with correct answers."""
    mock_client = Mock()
    mock_client_class.return_value = mock_client

    mock_response = Mock()
    mock_response.content = '{"payoff_cooperate_they_defect": 0, "payoff_both_defect": 1}'
    mock_client.chat_completion_with_schema.return_value = mock_response

    result = verify_comprehension(mock_client, "test-model", PRISONERS_DILEMMA)

    assert result is True


@patch('tests.llm_prompt_testing.prompt_v2.comprehension.OllamaClient')
def test_verify_comprehension_prisoners_dilemma_fail(mock_client_class):
    """Test comprehension check fails for PD with wrong answers."""
    mock_client = Mock()
    mock_client_class.return_value = mock_client

    mock_response = Mock()
    # Wrong answers
    mock_response.content = '{"payoff_cooperate_they_defect": 5, "payoff_both_defect": 3}'
    mock_client.chat_completion_with_schema.return_value = mock_response

    result = verify_comprehension(mock_client, "test-model", PRISONERS_DILEMMA)

    assert result is False


@patch('tests.llm_prompt_testing.prompt_v2.comprehension.OllamaClient')
def test_verify_comprehension_public_goods_pass(mock_client_class):
    """Test comprehension check passes for Public Goods with correct answer."""
    mock_client = Mock()
    mock_client_class.return_value = mock_client

    mock_response = Mock()
    # 10 kept + 16 share = 26
    mock_response.content = '{"total_payoff": 26}'
    mock_client.chat_completion_with_schema.return_value = mock_response

    result = verify_comprehension(mock_client, "test-model", PUBLIC_GOODS)

    assert result is True


@patch('tests.llm_prompt_testing.prompt_v2.comprehension.OllamaClient')
def test_verify_comprehension_api_error(mock_client_class):
    """Test comprehension check returns False on API error."""
    mock_client = Mock()
    mock_client_class.return_value = mock_client

    mock_client.chat_completion_with_schema.side_effect = Exception("API error")

    result = verify_comprehension(mock_client, "test-model", PRISONERS_DILEMMA)

    assert result is False


@patch('tests.llm_prompt_testing.prompt_v2.comprehension.OllamaClient')
def test_verify_comprehension_unknown_game(mock_client_class):
    """Test comprehension check returns True for unknown game types."""
    from tests.llm_prompt_testing.prompt_v2.game_configs import GameConfig

    unknown_config = GameConfig(
        name="Unknown Game",
        description="Some game",
        action_type="discrete",
        actions=["a", "b"],
    )

    mock_client = Mock()
    mock_client_class.return_value = mock_client

    result = verify_comprehension(mock_client, "test-model", unknown_config)

    # Should skip check and return True
    assert result is True
