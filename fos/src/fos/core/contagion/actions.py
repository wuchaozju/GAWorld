"""
Contagion scene action definitions for Pipeline A.

Provides minimal action stubs for ContagionScene: MoveAdjacentAction lets
an agent move to an adjacent cell; SpeakToAction directs speech at a nearby
agent and triggers a transmission check via ContagionScene.check_action_transmission.

Contains: MoveAdjacentAction, SpeakToAction, DIRECTION_DELTAS
"""

DIRECTION_DELTAS: dict[str, tuple[int, int]] = {
    "N":  (0, -1),
    "NE": (1, -1),
    "E":  (1,  0),
    "SE": (1,  1),
    "S":  (0,  1),
    "SW": (-1, 1),
    "W":  (-1, 0),
    "NW": (-1,-1),
}


class MoveAdjacentAction:
    """Move to an adjacent cell on the grid."""

    name = "move"
    description = "Move to an adjacent position on the map."

    def get_description(self, agent=None) -> str:
        return self.description


class SpeakToAction:
    """Direct speech at a nearby agent, potentially triggering contagion transmission."""

    name = "speak"
    description = "Speak to a nearby agent."

    def get_description(self, agent=None) -> str:
        return self.description
