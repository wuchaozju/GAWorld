"""
Smoke tests verifying ContagionScene is wired into the backend.

Confirms registry entries, construction from simtree_runtime parameters,
and correct class hierarchy.

Contains: test_contagion_scene_in_scene_map,
          test_scene_map_entry_is_contagion_class,
          test_contagion_in_scene_descriptions,
          test_contagion_scene_instantiation,
          test_contagion_scene_is_experiment_subclass
"""

from fos.core.registry import SCENE_MAP, SCENE_DESCRIPTIONS
from fos.core.contagion.scene import ContagionScene
from fos.core.contagion.states import ContagionState
from fos.core.contagion.rules import StateTransition
from fos.core.map.grid import GameMap
from fos.core.experiment.scene import ExperimentScene


def test_contagion_scene_in_scene_map():
    """ContagionScene key is present in SCENE_MAP."""
    assert "contagion_scene" in SCENE_MAP


def test_scene_map_entry_is_contagion_class():
    """SCENE_MAP['contagion_scene'] points to the ContagionScene class."""
    assert SCENE_MAP["contagion_scene"] is ContagionScene


def test_contagion_in_scene_descriptions():
    """contagion_scene has a non-empty description in SCENE_DESCRIPTIONS."""
    assert "contagion_scene" in SCENE_DESCRIPTIONS
    assert len(SCENE_DESCRIPTIONS["contagion_scene"]) > 0


def test_contagion_scene_instantiation():
    """ContagionScene can be built with parameters simtree_runtime would pass."""
    game_map = GameMap(width=10, height=10)
    rules = [
        StateTransition(
            from_state=ContagionState.SUSCEPTIBLE,
            to_state=ContagionState.INFECTED,
            trigger_type="proximity",
            probability=0.3,
        ),
        StateTransition(
            from_state=ContagionState.SUSCEPTIBLE,
            to_state=ContagionState.INFECTED,
            trigger_type="action",
            probability=0.5,
        ),
        StateTransition(
            from_state=ContagionState.INFECTED,
            to_state=ContagionState.RECOVERED,
            trigger_type="decay",
            probability=1.0,
            decay_turns=5,
        ),
    ]
    scene = ContagionScene(
        name="test",
        initial_event="outbreak begins",
        game_map=game_map,
        rules=rules,
        initial_infected_count=1,
    )
    assert scene.name == "test"
    assert scene.game_map.width == 10
    assert len(scene.rules) == 3


def test_contagion_scene_is_experiment_subclass():
    """ContagionScene is a subclass of ExperimentScene."""
    assert issubclass(ContagionScene, ExperimentScene)
