"""Tests for ActionHandler integration in ExperimentRunner."""
from unittest.mock import MagicMock
from fos.core.experiment.runner import ExperimentRunner
from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import GameConfig
from fos.core.experiment.state import ExperimentState, AgentState


class TestRunnerActionIntegration:
    def setup_method(self):
        self.agents = [
            ExperimentAgent(
                name="Alice",
                properties={},
                llm_config={},
            ),
            ExperimentAgent(
                name="Bob",
                properties={},
                llm_config={},
            ),
        ]
        self.game_config = GameConfig(
            name="test",
            description="Test game",
            action_type="discrete",
            actions=["cooperate", "defect"],
        )
        self.mock_llm_client = MagicMock()
        self.state = ExperimentState()
        self.state.agents["Alice"] = AgentState(
            resources={"tokens": 20},
            position=(5, 5),
        )
        self.state.extensions["pools"] = {"main": 0}

    def test_runner_has_action_handler(self):
        """ExperimentRunner has ActionHandler."""
        runner = ExperimentRunner(
            agents=self.agents,
            game_config=self.game_config,
            llm_client=self.mock_llm_client,
        )
        assert runner.action_handler is not None

    def test_runner_execute_action(self):
        """Runner can execute actions via handler."""
        runner = ExperimentRunner(
            agents=self.agents,
            game_config=self.game_config,
            llm_client=self.mock_llm_client,
        )
        result = runner.execute_action("choose", "Alice", {"choice": "cooperate"}, self.state)
        assert result["success"] is True

    def test_runner_state_shared_with_scene(self):
        """Runner state is same object as scene state."""
        runner = ExperimentRunner(
            agents=self.agents,
            game_config=self.game_config,
            llm_client=self.mock_llm_client,
        )
        # Runner should have state reference (via set_scene_state)
        runner.set_scene_state({"test": "value"})
        assert runner.scene_state is not None
        assert runner.scene_state["test"] == "value"
