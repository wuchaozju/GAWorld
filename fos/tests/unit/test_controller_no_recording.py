"""
Unit tests to verify controller does NOT record to context manager.
Runner is now the single recording source.
"""
import asyncio
from unittest.mock import Mock

from fos.core.experiment.controller import ExperimentController
from fos.core.experiment.round_context import RoundContextManager
from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import PRISONERS_DILEMMA, GameConfig
from fos.core.experiment.kernel import ExperimentKernel
from fos.core.llm_config import LLMConfig


def run(coro):
    return asyncio.run(coro)


def test_process_response_does_not_record_to_context_manager():
    cm = RoundContextManager()
    controller = ExperimentController(ExperimentKernel(), cm)
    llm_config = LLMConfig(dialect="openai", api_key="test")
    agent = ExperimentAgent(name="Alice", properties={}, llm_config=llm_config)
    mock_llm = Mock()
    mock_llm.chat.return_value = '{"action": "cooperate"}'

    result = run(controller.process_response(
        '{"action": "cooperate"}', agent, PRISONERS_DILEMMA, mock_llm, round_num=1
    ))

    assert result.success
    assert result.action_name == "cooperate"
    # Controller must NOT record — runner is now the single recording source
    assert len(cm._round_events) == 0


def test_process_response_with_followup_no_recording():
    cm = RoundContextManager()
    controller = ExperimentController(ExperimentKernel(), cm)
    llm_config = LLMConfig(dialect="openai", api_key="test")
    agent = ExperimentAgent(name="Alice", properties={}, llm_config=llm_config)
    mock_llm = Mock()
    mock_llm.chat.return_value = '{"action": "cooperate"}'

    result = run(controller.process_response_with_followup(
        '{"action": "cooperate"}', agent, PRISONERS_DILEMMA, mock_llm, round_num=1
    ))

    assert result.success
    assert len(cm._round_events) == 0


def test_process_response_with_followup_collects_contribute_amount():
    cm = RoundContextManager()
    controller = ExperimentController(ExperimentKernel(), cm)
    llm_config = LLMConfig(dialect="openai", api_key="test")
    agent = ExperimentAgent(name="Alice", properties={}, llm_config=llm_config)
    mock_llm = Mock()
    mock_llm.chat.return_value = '{"amount": 7, "pool": "main"}'
    public_goods = GameConfig(
        name="Public Goods",
        description="Contribute to the pool.",
        action_type="discrete",
        actions=["Contribute"],
        action_descriptions={"Contribute": "Contribute tokens to the shared pool"},
    )

    result = run(controller.process_response_with_followup(
        '{"action": "Contribute"}',
        agent,
        public_goods,
        mock_llm,
        round_num=1,
        action_schemas=ExperimentKernel.get_action_schemas(),
    ))

    assert result.success
    assert result.action_name == "contribute"
    assert result.parameters == {"amount": 7, "pool": "main"}
    assert len(cm._round_events) == 0


def test_followup_prompt_reuses_main_prompt_context():
    cm = RoundContextManager()
    controller = ExperimentController(ExperimentKernel(), cm)
    llm_config = LLMConfig(dialect="openai", api_key="test")
    agent = ExperimentAgent(name="Alice", properties={}, llm_config=llm_config)
    mock_llm = Mock()
    mock_llm.chat.return_value = "I still support the plan because costs are lower."
    discussion = GameConfig(
        name="Discussion",
        description="Discuss a proposal.",
        action_type="discrete",
        actions=["speak"],
        action_descriptions={"speak": "Say something"},
    )
    prior_context = "Round 1: I speak (message=I support the plan), Bob speak (message=I disagree with the plan)."

    result = run(controller.process_response_with_followup(
        '{"action": "speak"}',
        agent,
        discussion,
        mock_llm,
        round_num=2,
        action_schemas=ExperimentKernel.get_action_schemas(),
        context_summary=prior_context,
        neighbor_context="Your social network neighbors: Bob.",
        kb_context="Relevant knowledge: Budget pressure is rising.",
    ))

    followup_prompt = mock_llm.chat.call_args.args[0][0]["content"]

    assert result.success
    assert result.action_name == "speak"
    assert result.parameters == {"message": "I still support the plan because costs are lower."}
    assert prior_context in followup_prompt
