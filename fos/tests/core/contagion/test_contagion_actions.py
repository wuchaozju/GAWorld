"""
Tests for contagion action definitions and direction deltas.

Verifies action name attributes and that DIRECTION_DELTAS contains
all eight compass directions with correct (dx, dy) tuples.

Contains: test_move_adjacent_action_has_correct_name,
          test_speak_to_action_has_correct_name,
          test_direction_deltas_contain_all_eight_directions
"""
from fos.core.contagion.actions import DIRECTION_DELTAS, MoveAdjacentAction, SpeakToAction


def test_move_adjacent_action_has_correct_name():
    """MoveAdjacentAction.name should be 'move'."""
    assert MoveAdjacentAction.name == "move"


def test_speak_to_action_has_correct_name():
    """SpeakToAction.name should be 'speak'."""
    assert SpeakToAction.name == "speak"


def test_direction_deltas_contain_all_eight_directions():
    """DIRECTION_DELTAS must have N, NE, E, SE, S, SW, W, NW."""
    expected = {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}
    assert set(DIRECTION_DELTAS.keys()) == expected
    # Sanity-check a couple of values
    assert DIRECTION_DELTAS["N"] == (0, -1)
    assert DIRECTION_DELTAS["SE"] == (1, 1)
