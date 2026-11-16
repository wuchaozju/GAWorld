"""
Tests for ExperimentController (Layer 3 validation and execution).
"""

import pytest
from fos.core.experiment.controller import ExperimentController
from fos.core.experiment.game_configs import GameConfig, PRISONERS_DILEMMA
from fos.core.experiment.kernel import ExperimentKernel
from fos.core.experiment.round_context import RoundContextManager
from fos.core.experiment.agent import ExperimentAgent
from fos.core.llm_config import LLMConfig


class StubFollowupLLMClient:
    """Small fake LLM client that returns one canned follow-up reply."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def chat(self, messages: list[dict[str, str]], json_mode: bool = True) -> str:
        self.calls.append({"messages": messages, "json_mode": json_mode})
        return self.response


@pytest.mark.asyncio
async def test_process_valid_response():
    """Process a valid LLM response."""
    kernel = ExperimentKernel()
    context_manager = RoundContextManager()
    controller = ExperimentController(kernel, context_manager)

    agent = ExperimentAgent(
        name="Alice",
        properties={},
        llm_config=LLMConfig(dialect="mock")
    )

    raw_json = '{"reasoning": "I want to cooperate", "action": "cooperate"}'
    result = await controller.process_response(
        raw_json, agent, PRISONERS_DILEMMA, None, round_num=1
    )

    assert result.success is True
    assert result.action_name == "cooperate"
    assert result.skipped is False
    assert "Alice chose cooperate" in result.summary


@pytest.mark.asyncio
async def test_process_invalid_action():
    """Invalid action results in skipped turn."""
    kernel = ExperimentKernel()
    context_manager = RoundContextManager()
    controller = ExperimentController(kernel, context_manager)

    agent = ExperimentAgent(
        name="Bob",
        properties={},
        llm_config=LLMConfig(dialect="mock")
    )

    raw_json = '{"reasoning": "...", "action": "invalid_action"}'
    result = await controller.process_response(
        raw_json, agent, PRISONERS_DILEMMA, None, round_num=1
    )

    assert result.success is False
    assert result.skipped is True
    assert "not in allowed set" in result.error


@pytest.mark.asyncio
async def test_invalid_action_preserves_original_controller_diagnostic():
    """Invalid model action names should stay visible at the controller boundary."""
    kernel = ExperimentKernel()
    context_manager = RoundContextManager()
    controller = ExperimentController(kernel, context_manager)

    agent = ExperimentAgent(
        name="Bob",
        properties={},
        llm_config=LLMConfig(dialect="mock")
    )

    result = await controller.process_response(
        '{"reasoning": "...", "action": "teleport_away"}',
        agent,
        PRISONERS_DILEMMA,
        None,
        round_num=1,
    )

    assert result.success is False
    assert result.action_name == "teleport_away"
    assert result.skipped is True


@pytest.mark.asyncio
async def test_color_choice_in_action_field_is_repaired():
    """A color placed in the action field should become a choose_color parameter."""
    kernel = ExperimentKernel()
    context_manager = RoundContextManager()
    controller = ExperimentController(kernel, context_manager)

    agent = ExperimentAgent(
        name="NodeC",
        properties={},
        llm_config=LLMConfig(dialect="mock")
    )
    color_config = GameConfig(
        name="coordination_game",
        description="Choose a color different from your neighbors.",
        action_type="discrete",
        actions=["choose_color"],
        action_descriptions={"choose_color": "Select a color for your node"},
    )

    result = await controller.process_response(
        '{"action": "green"}',
        agent,
        color_config,
        None,
        round_num=2,
    )

    assert result.success is True
    assert result.action_name == "choose_color"
    assert result.parameters == {"color": "green"}


@pytest.mark.asyncio
async def test_process_json_with_markdown():
    """Handle JSON wrapped in markdown fences."""
    kernel = ExperimentKernel()
    context_manager = RoundContextManager()
    controller = ExperimentController(kernel, context_manager)

    agent = ExperimentAgent(
        name="Charlie",
        properties={},
        llm_config=LLMConfig(dialect="mock")
    )

    raw_json = '```json\n{"action": "defect"}\n```'
    result = await controller.process_response(
        raw_json, agent, PRISONERS_DILEMMA, None, round_num=1
    )

    assert result.success is True
    assert result.action_name == "defect"


@pytest.mark.asyncio
async def test_malformed_json_skipped_with_raw_text_in_error():
    """Malformed JSON results in skipped turn with raw text in error."""
    kernel = ExperimentKernel()
    context_manager = RoundContextManager()
    controller = ExperimentController(kernel, context_manager)

    agent = ExperimentAgent(
        name="Diana",
        properties={},
        llm_config=LLMConfig(dialect="mock")
    )

    malformed_json = '{"reasoning": "I think", "action": "cooperate"'  # Missing closing brace
    result = await controller.process_response(
        malformed_json, agent, PRISONERS_DILEMMA, None, round_num=1
    )

    assert result.success is False
    assert result.skipped is True
    # Error should contain the raw text for debugging
    assert result.error is not None


@pytest.mark.asyncio
async def test_think_tags_stripped_before_parse():
    """Think tags should be stripped before parsing JSON."""
    kernel = ExperimentKernel()
    context_manager = RoundContextManager()
    controller = ExperimentController(kernel, context_manager)

    agent = ExperimentAgent(
        name="Eve",
        properties={},
        llm_config=LLMConfig(dialect="mock")
    )

    response_with_think = '<|thinking|>I should cooperate<|/thinking|>\n{"reasoning": "cooperate", "action": "cooperate"}'
    result = await controller.process_response(
        response_with_think, agent, PRISONERS_DILEMMA, None, round_num=1
    )

    assert result.success is True
    assert result.action_name == "cooperate"


@pytest.mark.asyncio
async def test_action_result_contains_required_fields():
    """Controller should return ActionResult with all required fields for recording.

    Note: Recording to context_manager happens in the runner, not the controller.
    The controller's job is to validate and return an ActionResult.
    """
    kernel = ExperimentKernel()
    context_manager = RoundContextManager()
    controller = ExperimentController(kernel, context_manager)

    agent = ExperimentAgent(
        name="Frank",
        properties={},
        llm_config=LLMConfig(dialect="mock")
    )

    raw_json = '{"reasoning": "I choose to defect", "action": "defect"}'
    result = await controller.process_response(
        raw_json, agent, PRISONERS_DILEMMA, None, round_num=2
    )

    # Verify the ActionResult has all fields needed for recording
    assert result.success is True
    assert result.agent_name == "Frank"
    assert result.action_name == "defect"
    assert result.round_num == 2
    assert result.summary == "Frank chose defect"
    assert result.skipped is False


@pytest.mark.asyncio
async def test_communication_action_triggers_plain_text_followup_and_logs_it():
    kernel = ExperimentKernel()
    context_manager = RoundContextManager()
    controller = ExperimentController(kernel, context_manager)

    agent = ExperimentAgent(
        name="Manager",
        properties={},
        llm_config=LLMConfig(dialect="mock"),
    )
    game_config = GameConfig(
        name="policy_erosion",
        description="Policy cascade follow-up.",
        action_type="discrete",
        actions=["notify_subordinate", "yield"],
        payoff_type="none",
        grouping_mode="individual",
    )
    llm_client = StubFollowupLLMClient("Please tell the district offices to delay enforcement by one day.")

    result = await controller.process_response_with_followup(
        raw_json='{"action": "notify_subordinate", "message": "debug only"}',
        agent=agent,
        game_config=game_config,
        llm_client=llm_client,
        round_num=3,
        action_schemas={
            "notify_subordinate": {
                "schema": {
                    "target": {
                        "type": "string",
                        "description": "Name of the subordinate",
                    },
                    "message": {
                        "type": "string",
                        "description": "Private notification content",
                    },
                },
                "mode": "plain_text",
            }
        },
    )

    assert result.success is True
    assert result.action_name == "notify_subordinate"
    assert result.parameters == {
        "message": "Please tell the district offices to delay enforcement by one day."
    }
    assert result.summary == (
        "Manager chose notify_subordinate "
        "(message=Please tell the district offices to delay enforcement by one day.)"
    )
    assert llm_client.calls == [
        {
            "messages": llm_client.calls[0]["messages"],
            "json_mode": False,
        }
    ]
    debug_text = "".join(result.debug_log)
    assert "FOLLOW-UP PROMPT REQUIRED" in debug_text
    assert "--- FOLLOW-UP PROMPT ---" in debug_text
    assert "--- FOLLOW-UP RESPONSE ---" in debug_text
    assert "should_follow_up: True" in debug_text


@pytest.mark.asyncio
async def test_custom_speak_accepts_message_in_initial_json():
    kernel = ExperimentKernel()
    context_manager = RoundContextManager()
    controller = ExperimentController(kernel, context_manager)
    agent = ExperimentAgent(name="Alice", properties={}, llm_config=LLMConfig(dialect="mock"))
    custom_config = GameConfig(
        name="custom",
        description="Open discussion",
        action_type="discrete",
        actions=["speak", "skip"],
        payoff_type="none",
        grouping_mode="individual",
    )

    result = await controller.process_response(
        '{"action": "speak", "message": "I support starting with a pilot."}',
        agent,
        custom_config,
        None,
        round_num=1,
    )

    assert result.success is True
    assert result.action_name == "speak"
    assert result.parameters == {"message": "I support starting with a pilot."}
    assert result.skipped is False


@pytest.mark.asyncio
async def test_custom_skip_is_successful_recordable_skip():
    kernel = ExperimentKernel()
    context_manager = RoundContextManager()
    controller = ExperimentController(kernel, context_manager)
    agent = ExperimentAgent(name="Bob", properties={}, llm_config=LLMConfig(dialect="mock"))
    custom_config = GameConfig(
        name="custom",
        description="Open discussion",
        action_type="discrete",
        actions=["speak", "skip"],
        payoff_type="none",
        grouping_mode="individual",
    )

    result = await controller.process_response(
        '{"action": "skip", "message": null}',
        agent,
        custom_config,
        None,
        round_num=1,
    )

    assert result.success is True
    assert result.action_name == "skip"
    assert result.parameters == {"message": None}
    assert result.skipped is True
