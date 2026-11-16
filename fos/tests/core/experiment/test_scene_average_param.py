"""Test that scene passes show_average_contribution to InformationModel."""

from fos.core.experiment.scene import ExperimentScene
from fos.core.experiment.config import ExperimentConfig
from unittest.mock import MagicMock


def test_scene_creates_information_model_with_average_param():
    """Scene should pass show_average_contribution to InformationModel."""
    config = ExperimentConfig(
        scenario_id="public_goods",
        description="PGG with average contribution",
        agents=[
            {"name": "Alice", "role_prompt": "You are Alice."},
            {"name": "Bob", "role_prompt": "You are Bob."},
        ],
        actions=[{"name": "allocate"}, {"name": "keep"}],
        parameters={
            "tokens_per_round": 20,
            "multiplier": 1.5,
            "show_average_contribution": True,
            "deduction_budget_per_phase": 0,
        },
        state_schema={},
    )

    scene = ExperimentScene(config)
    mock_client = MagicMock()
    mock_client.chat = MagicMock(return_value='{"action": "allocate"}')
    scene.initialize(mock_client)

    # Verify InformationModel has the parameter
    assert scene.runner.information_model.show_average_contribution is True


def test_scene_defaults_show_average_to_false():
    """Scene should default show_average_contribution to False if not specified."""
    config = ExperimentConfig(
        scenario_id="public_goods",
        description="PGG without average contribution",
        agents=[
            {"name": "Alice", "role_prompt": "You are Alice."},
        ],
        actions=[{"name": "allocate"}],
        parameters={
            "tokens_per_round": 20,
            "multiplier": 1.5,
            # NO show_average_contribution parameter!
            "deduction_budget_per_phase": 0,
        },
        state_schema={},
    )

    scene = ExperimentScene(config)
    mock_client = MagicMock()
    mock_client.chat = MagicMock(return_value='{"action": "allocate"}')
    scene.initialize(mock_client)

    # Verify InformationModel defaults to False
    assert scene.runner.information_model.show_average_contribution is False


def test_custom_scene_uses_custom_prompt_and_actions_without_followup():
    config = ExperimentConfig(
        scenario_id="custom",
        description="fallback prompt",
        agents=[
            {"name": "Alice", "role_prompt": "You are Alice."},
        ],
        actions=[{"name": "Speak"}, {"name": "Skip"}],
        parameters={
            "custom_prompt": "Discuss a neighborhood tool library.",
            "turn_ordering": "sequential",
        },
        round_visibility="sequential",
    )

    scene = ExperimentScene(config)
    mock_client = MagicMock()
    mock_client.chat = MagicMock(return_value='{"action": "skip", "message": null}')
    scene.initialize(mock_client)

    assert scene.runner.game_config.description == "Discuss a neighborhood tool library."
    assert scene.runner.game_config.actions == ["speak", "skip"]
    assert scene.runner.game_config.action_followup_modes == {}
