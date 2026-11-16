import asyncio
from unittest.mock import Mock

from fos.core.experiment.action_handler import ActionHandler
from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.controller import ExperimentController
from fos.core.experiment.game_configs import GameConfig
from fos.core.experiment.information_model import InformationModel
from fos.core.experiment.kernel import ExperimentKernel
from fos.core.experiment.round_context import RoundContextManager
from fos.core.experiment.scene import ExperimentScene
from fos.core.experiment.state import ExperimentState
from fos.core.llm_config import LLMConfig


def test_unknown_action_failure_semantics_are_explicit():
    handler_result = ActionHandler().execute("unsupported_custom_action", "Alice", {}, ExperimentState())
    assert handler_result == {"success": False, "error": "Unknown action: unsupported_custom_action"}

    controller = ExperimentController(ExperimentKernel(), RoundContextManager())
    agent = ExperimentAgent(name="Alice", properties={}, llm_config=LLMConfig(dialect="mock"))
    custom_config = GameConfig(
        name="custom",
        description="Open custom discussion.",
        action_type="discrete",
        actions=["speak", "skip"],
        payoff_type="none",
        grouping_mode="individual",
    )

    result = asyncio.run(
        controller.process_response(
            '{"action": "invent_action", "message": "not allowed"}',
            agent,
            custom_config,
            None,
            round_num=1,
        )
    )

    assert result.success is False
    assert result.skipped is True
    assert result.action_name == "invent_action"
    assert result.error == "Action not in allowed set"


def test_undirected_chain_visibility_filtering_unit():
    model = InformationModel(scope_type="neighborhood", include_scores=False)
    graph = {"edges": [["Alice", "Bob"], ["Bob", "Charlie"]]}
    names = ["Alice", "Bob", "Charlie", "Diana"]

    assert set(model.get_observers("Alice", {"graph": graph}, names)) == {"Alice", "Bob"}
    assert set(model.get_observers("Bob", {"graph": graph}, names)) == {"Alice", "Bob", "Charlie"}
    assert set(model.get_observers("Charlie", {"graph": graph}, names)) == {"Bob", "Charlie"}
    assert set(model.get_observers("Diana", {"graph": graph}, names)) == {"Diana"}


def test_custom_scene_runtime_uses_network_visible_history_only():
    llm_client = Mock()
    llm_client.provider = Mock(dialect="mock", model="mock", base_url=None)
    llm_client.chat = Mock(return_value='{"action": "skip", "message": null}')

    scene = ExperimentScene(
        ExperimentConfig(
            agents=[
                {"name": "Alice", "properties": {}, "llm_config": {}},
                {"name": "Bob", "properties": {}, "llm_config": {}},
                {"name": "Charlie", "properties": {}, "llm_config": {}},
            ],
            actions=[],
            parameters={
                "custom_prompt": "Discuss only what your network neighbors have said.",
                "turn_ordering": "simultaneous",
            },
            description="fallback custom prompt",
            scenario_id="custom",
            round_visibility="simultaneous",
            social_network={"edges": [["Alice", "Bob"], ["Bob", "Charlie"]]},
            locale="en",
        )
    )
    scene.initialize(llm_client)

    assert scene.runner is not None
    assert scene.runner.information_model.scope_type == "neighborhood"

    scene.runner.context_manager.record_action_with_observers(
        agent_name="Bob",
        action_name="speak",
        parameters={"message": "VISIBLE_BRIDGE_MESSAGE"},
        round_num=1,
        summary="Bob spoke: VISIBLE_BRIDGE_MESSAGE",
    )
    scene.runner.context_manager.record_action_with_observers(
        agent_name="Charlie",
        action_name="speak",
        parameters={"message": "HIDDEN_CHAIN_TAIL_MESSAGE"},
        round_num=1,
        summary="Charlie spoke: HIDDEN_CHAIN_TAIL_MESSAGE",
    )

    result = asyncio.run(scene.runner._prompt_agent(scene.agents[0], round_num=2))

    sent_prompt = llm_client.chat.call_args.args[0][0]["content"]
    assert result.success is True
    assert result.action_name == "skip"
    assert "VISIBLE_BRIDGE_MESSAGE" in sent_prompt
    assert "HIDDEN_CHAIN_TAIL_MESSAGE" not in sent_prompt
    assert "Your social network neighbors: Bob." in sent_prompt
