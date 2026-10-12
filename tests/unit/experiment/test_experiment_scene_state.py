"""Tests for ExperimentScene state integration."""
import asyncio
from fos.core.experiment.scene import ExperimentScene
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.controller import ActionResult
from fos.core.experiment.runner import RoundResult


class TestExperimentSceneState:
    def test_scene_has_state(self):
        """ExperimentScene has ExperimentState."""
        config = ExperimentConfig(
            scenario_id="test",
            agents=[{"name": "Alice"}],
            actions=[],
        )
        scene = ExperimentScene(config)
        assert scene.state is not None
        assert scene.state.round == 0

    def test_scene_initializes_agent_states(self):
        """Scene creates AgentState for each agent."""
        config = ExperimentConfig(
            scenario_id="test",
            agents=[
                {"name": "Alice"},
                {"name": "Bob"},
            ],
            actions=[],
        )
        scene = ExperimentScene(config)
        scene._initialize_state()

        assert "Alice" in scene.state.agents
        assert "Bob" in scene.state.agents

    def test_scene_applies_state_schema(self):
        """Scene applies state_schema from config."""
        config = ExperimentConfig(
            scenario_id="public_goods",
            agents=[{"name": "Alice"}],
            actions=[],
        )
        # Set state_schema directly (normally comes from scenario)
        config.state_schema = {
            "extensions": {"pools": {"main": 0}},
        }
        scene = ExperimentScene(config)
        scene._initialize_state()

        assert scene.state.extensions["pools"]["main"] == 0

    def test_scene_initializes_resources(self):
        """Scene initializes agent resources from config."""
        config = ExperimentConfig(
            scenario_id="test",
            agents=[{"name": "Alice", "resources": {"tokens": 20}}],
            actions=[],
        )
        scene = ExperimentScene(config)
        scene._initialize_state()

        assert scene.state.agents["Alice"].resources["tokens"] == 20

    def test_run_round_emits_parameters_summary_and_payoff(self):
        config = ExperimentConfig(
            scenario_id="public_goods",
            agents=[{"name": "Alice"}],
            actions=[{"name": "Contribute", "description": "Contribute some tokens to the pool"}],
        )
        scene = ExperimentScene(config)

        class DummyRunner:
            def __init__(self):
                self.pending_host_messages = []
                self.context_manager = type(
                    "ContextManagerStub",
                    (),
                    {"get_round_events": lambda self, round_num: []},
                )()
                self.execute_action = lambda action_name, agent_name, parameters, state, scene: {"success": True}

            async def _run_single_round(self, round_num, context_summary, round_history):
                return RoundResult(
                    round_num=round_num,
                    actions=[
                        ActionResult(
                            success=True,
                            action_name="contribute",
                            parameters={"amount": 7, "pool": "main"},
                            summary="Alice chose contribute (amount=7, pool=main)",
                            agent_name="Alice",
                            round_num=round_num,
                        )
                    ],
                    completed=True,
                    payoffs={"Alice": 18.25},
                )

        scene.runner = DummyRunner()

        emitted = []
        asyncio.run(scene.run_round(lambda event_type, data: emitted.append((event_type, data))))

        assert emitted == [
            (
                "experiment_action",
                {
                    "agent": "Alice",
                    "action": "contribute",
                    "parameters": {"amount": 7, "pool": "main"},
                    "summary": "Alice chose contribute (amount=7, pool=main)",
                    "payoff": 18.25,
                    "round": 1,
                    "success": True,
                    "skipped": False,
                },
            )
        ]

    def test_coordination_game_runs_with_neighbor_visibility(self):
        config = ExperimentConfig(
            scenario_id="coordination_game",
            round_visibility="sequential",
            description="Choose a color different from your neighbors.",
            parameters={"choices": "red, blue", "goal": "differ"},
            agents=[
                {"name": "Node1", "llmConfig": {"dialect": "mock"}},
                {"name": "Node2", "llmConfig": {"dialect": "mock"}},
            ],
            actions=[],
            social_network={"edges": [("Node1", "Node2")]},
        )
        scene = ExperimentScene(config)

        class StubLLM:
            def __init__(self):
                self.responses = ['{"action": "red"}', '{"action": "blue"}']
                self.index = 0

            def chat(self, messages, json_mode=False):
                response = self.responses[self.index]
                self.index += 1
                return response

        scene.initialize(StubLLM())

        emitted = []
        result = asyncio.run(scene.run_round(lambda event_type, data: emitted.append((event_type, data))))

        assert result.completed is True
        assert len(result.actions) == 2
        assert [action.action_name for action in result.actions] == ["red", "blue"]
        assert len(emitted) == 2

    def test_coordination_game_replays_feedback_into_next_round_prompt(self):
        config = ExperimentConfig(
            scenario_id="coordination_game",
            round_visibility="sequential",
            description="Choose a color different from your neighbors.",
            parameters={"choices": "red, blue", "goal": "differ"},
            agents=[
                {"name": "Node1", "llmConfig": {"dialect": "mock"}},
                {"name": "Node2", "llmConfig": {"dialect": "mock"}},
            ],
            actions=[],
            social_network={"edges": [("Node1", "Node2")]},
        )
        scene = ExperimentScene(config)

        class StubLLM:
            def __init__(self):
                self.prompts = []
                self.responses = [
                    '{"action": "red"}',
                    '{"action": "blue"}',
                    '{"action": "red"}',
                    '{"action": "blue"}',
                ]
                self.index = 0

            def chat(self, messages, json_mode=False):
                self.prompts.append(messages[-1]["content"])
                response = self.responses[self.index]
                self.index += 1
                return response

        llm = StubLLM()
        scene.initialize(llm)

        asyncio.run(scene.run_round(lambda event_type, data: None))
        asyncio.run(scene.run_round(lambda event_type, data: None))

        round_2_prompt = llm.prompts[2]
        assert "Round 1: I chose red." in round_2_prompt
        assert "Node2 chose blue" in round_2_prompt
        assert "→ Coordinated with: Node2 (you red, they blue)" in round_2_prompt

    def test_custom_action_parameters_trigger_followup(self):
        config = ExperimentConfig(
            scenario_id="custom",
            round_visibility="simultaneous",
            description="Choose an investment amount.",
            agents=[
                {"name": "Alice", "llmConfig": {"dialect": "mock"}},
            ],
            actions=[
                {
                    "name": "invest",
                    "description": "Invest some amount",
                    "parameters": [
                        {
                            "name": "amount",
                            "type": "integer",
                            "description": "How much to invest",
                            "required": True,
                            "default": None,
                        }
                    ],
                }
            ],
        )
        scene = ExperimentScene(config)

        class StubLLM:
            def __init__(self):
                self.responses = [
                    '{"action": "invest"}',
                    '{"amount": 5}',
                ]
                self.index = 0

            def chat(self, messages, json_mode=False):
                response = self.responses[self.index]
                self.index += 1
                return response

        scene.initialize(StubLLM())

        emitted = []
        result = asyncio.run(scene.run_round(lambda event_type, data: emitted.append((event_type, data))))

        assert result.completed is True
        assert result.actions[0].action_name == "invest"
        assert result.actions[0].parameters == {"amount": 5}
        assert emitted == [
            (
                "experiment_action",
                {
                    "agent": "Alice",
                    "action": "invest",
                    "parameters": {"amount": 5},
                    "summary": "Alice chose invest (amount=5)",
                    "payoff": None,
                    "round": 1,
                    "success": True,
                    "skipped": False,
                },
            )
        ]

    def test_policy_erosion_round_uses_two_step_message_followup(self):
        config = ExperimentConfig(
            scenario_id="policy_erosion",
            round_visibility="sequential",
            description="Policy cascade follow-up.",
            parameters={"policy_text": "Keep the office open late this week."},
            agents=[
                {"name": "Alice", "llmConfig": {"dialect": "mock"}},
            ],
            actions=[],
        )
        scene = ExperimentScene(config)

        class StubLLM:
            def __init__(self) -> None:
                self.responses = [
                    '{"action": "send_message", "message": "debug only"}',
                    "We need a clearer explanation before frontline rollout.",
                ]
                self.prompts: list[str] = []
                self.json_modes: list[bool] = []
                self.index = 0

            def chat(self, messages, json_mode=False):
                self.prompts.append(messages[-1]["content"])
                self.json_modes.append(json_mode)
                response = self.responses[self.index]
                self.index += 1
                return response

        llm = StubLLM()
        scene.initialize(llm)

        emitted = []
        result = asyncio.run(scene.run_round(lambda event_type, data: emitted.append((event_type, data))))

        assert result.completed is True
        assert len(llm.prompts) == 2
        assert llm.json_modes == [True, False]
        assert '"send_message"' in llm.prompts[0]
        assert '"yield"' in llm.prompts[0]
        assert '"report_upward"' in llm.prompts[0]
        assert "You chose to send_message. Please provide your response." in llm.prompts[1]
        assert result.actions[0].action_name == "send_message"
        assert result.actions[0].parameters == {
            "message": "We need a clearer explanation before frontline rollout."
        }
        assert emitted == [
            (
                "experiment_action",
                {
                    "agent": "Alice",
                    "action": "send_message",
                    "parameters": {
                        "message": "We need a clearer explanation before frontline rollout."
                    },
                    "summary": (
                        "Alice chose send_message "
                        "(message=We need a clearer explanation before frontline rollout.)"
                    ),
                    "payoff": None,
                    "round": 1,
                    "success": True,
                    "skipped": False,
                    "record_only": True,
                    "effect_applied": False,
                },
            )
        ]

    def test_custom_contribute_action_writes_state_and_survives_serialize(self):
        config = ExperimentConfig(
            scenario_id="custom",
            round_visibility="simultaneous",
            description="Contribute some tokens to the pool.",
            state_schema={"extensions": {"pools": {"main": 0}}},
            agents=[
                {
                    "name": "Alice",
                    "llmConfig": {"dialect": "mock"},
                    "resources": {"tokens": 20},
                },
            ],
            actions=[
                {
                    "name": "contribute",
                    "description": "Contribute to the shared pool",
                }
            ],
            social_network={"edges": []},
        )
        scene = ExperimentScene(config)

        class StubLLM:
            def __init__(self):
                self.responses = [
                    '{"action": "contribute"}',
                    '{"amount": 7, "pool": "main"}',
                ]
                self.index = 0

            def chat(self, messages, json_mode=False):
                response = self.responses[self.index]
                self.index += 1
                return response

        scene.initialize(StubLLM())
        asyncio.run(scene.run_round(lambda event_type, data: None))

        assert scene.state.round == 1
        assert scene.state.agents["Alice"].resources["tokens"] == 13
        assert scene.state.extensions["pools"]["main"] == 7
        assert scene.state.history[0]["actions"][0]["parameters"] == {"amount": 7, "pool": "main"}

        serialized = scene.serialize_config()
        restored = ExperimentScene.deserialize_config(serialized)

        assert restored.config.state_schema == {"extensions": {"pools": {"main": 0}}}
        assert restored.config.social_network == {"edges": []}
        assert restored.state.agents["Alice"].resources["tokens"] == 13
        assert restored.state.extensions["pools"]["main"] == 7

        restored.initialize(StubLLM())
        assert restored.state.agents["Alice"].resources["tokens"] == 13
        assert restored.state.extensions["pools"]["main"] == 7

    def test_pgg_phase_persists_across_serialization(self):
        """PGG phase should persist through serialize/deserialize cycle."""
        config = ExperimentConfig(
            scenario_id="public_goods",
            agents=[{"name": "Alice"}],
            actions=[],
            parameters={"deduction_budget_per_phase": 3},
        )
        scene = ExperimentScene(config)

        # Initial phase should be "allocate"
        assert scene.get_pgg_phase() == "allocate"

        # Advance to "deduct" phase
        scene.advance_pgg_phase()
        assert scene.get_pgg_phase() == "deduct"

        # Serialize and deserialize
        serialized = scene.serialize_config()
        restored = ExperimentScene.deserialize_config(serialized)

        # Phase should still be "deduct" after restoration
        assert restored.get_pgg_phase() == "deduct"

    def test_pgg_phase_defaults_to_allocate_for_backwards_compatibility(self):
        """PGG phase should default to 'allocate' when not in serialized data."""
        config = ExperimentConfig(
            scenario_id="public_goods",
            agents=[{"name": "Alice"}],
            actions=[],
        )
        # Manually serialize without pgg_phase (simulating old serialized data)
        scene = ExperimentScene(config)
        serialized = scene.serialize_config()
        # Remove pgg_phase to simulate old data
        serialized.pop("pgg_phase", None)

        # Deserialize - should default to "allocate"
        restored = ExperimentScene.deserialize_config(serialized)
        assert restored.get_pgg_phase() == "allocate"

    def test_advance_pgg_phase_skips_deduct_when_budget_is_zero(self):
        """When deduction_budget_per_phase is 0, phase should stay in allocate."""
        config = ExperimentConfig(
            scenario_id="public_goods",
            agents=[{"name": "Alice"}],
            actions=[],
            parameters={"deduction_budget_per_phase": 0},
        )
        scene = ExperimentScene(config)

        # Initial phase should be "allocate"
        assert scene.get_pgg_phase() == "allocate"

        # Advance phase - should STAY in allocate since deduction is disabled
        scene.advance_pgg_phase()
        assert scene.get_pgg_phase() == "allocate"

        # Multiple advances should still stay in allocate
        scene.advance_pgg_phase()
        assert scene.get_pgg_phase() == "allocate"

    def test_advance_pgg_phase_advances_when_deduction_enabled(self):
        """When deduction_budget_per_phase > 0, phase should cycle normally."""
        config = ExperimentConfig(
            scenario_id="public_goods",
            agents=[{"name": "Alice"}],
            actions=[],
            parameters={"deduction_budget_per_phase": 5},
        )
        scene = ExperimentScene(config)

        # Initial phase should be "allocate"
        assert scene.get_pgg_phase() == "allocate"

        # Advance phase - should go to deduct
        scene.advance_pgg_phase()
        assert scene.get_pgg_phase() == "deduct"

        # Advance again - should return to allocate
        scene.advance_pgg_phase()
        assert scene.get_pgg_phase() == "allocate"

    def test_skipped_actions_are_not_written_into_round_history(self):
        config = ExperimentConfig(
            scenario_id="council_chamber",
            agents=[{"name": "Alice"}, {"name": "Bob"}],
            actions=[],
        )
        scene = ExperimentScene(config)

        class DummyRunner:
            def __init__(self):
                self.pending_host_messages = []
                self.context_manager = type(
                    "ContextManagerStub",
                    (),
                    {"get_round_events": lambda self, round_num: []},
                )()
                self.execute_action = lambda action_name, agent_name, parameters, state, scene: {"success": True}

            async def _run_single_round(self, round_num, context_summary, round_history):
                return RoundResult(
                    round_num=round_num,
                    actions=[
                        ActionResult(
                            success=True,
                            action_name="speak",
                            parameters={"message": "Fund the project"},
                            summary="Alice chose speak (message=Fund the project)",
                            agent_name="Alice",
                            round_num=round_num,
                        ),
                        ActionResult(
                            success=False,
                            action_name="",
                            parameters={},
                            summary="",
                            agent_name="Bob",
                            round_num=round_num,
                            skipped=True,
                            error="Invalid JSON",
                        ),
                    ],
                    completed=False,
                    payoffs=None,
                )

        scene.runner = DummyRunner()

        asyncio.run(scene.run_round(lambda event_type, data: None))

        assert scene._history == [
            {
                "round": 1,
                "actions": [
                    {
                        "agent": "Alice",
                        "action": "speak",
                        "parameters": {"message": "Fund the project"},
                        "summary": "Alice chose speak (message=Fund the project)",
                        "feedback": None,
                    }
                ],
            }
        ]
        assert scene.state.history == scene._history
