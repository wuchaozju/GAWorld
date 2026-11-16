"""Serialization helpers for ExperimentRunnerAdapter."""

from __future__ import annotations

from fos.core.experiment.scene import ExperimentScene


def serialize_experiment_adapter(scene: ExperimentScene) -> dict:
    """Serialize an experiment-scene adapter in the legacy SimTree shape."""
    return {
        "agents": {},
        "scene": {
            "type": "experiment_template",
            "config": scene.serialize_config(),
        },
        "max_steps_per_turn": 5,
        "ordering": "sequential",
        "ordering_state": {},
        "event_queue": [],
        "turns": scene.current_round,
        "environment_config": None,
        "_suggestions_viewed_turn": None,
    }


def deserialize_experiment_scene(data: dict) -> ExperimentScene:
    """Restore the concrete experiment scene stored in an adapter snapshot."""
    scene_data = data["scene"]["config"]
    scenario_id = scene_data.get("config", {}).get("scenario_id", "")
    scene_type = scene_data.get("type", "")

    if scenario_id in ("council", "council_chamber"):
        from fos.core.experiment.scenes.council_experiment import (
            CouncilExperimentScene,
        )

        return CouncilExperimentScene.deserialize_config(scene_data)
    if scene_type == "gaworld_scene" or scenario_id == "gaworld":
        from fos.core.experiment.scenes.gaworld import GAWorldScene

        return GAWorldScene.deserialize_config(scene_data)
    return ExperimentScene.deserialize_config(scene_data)
