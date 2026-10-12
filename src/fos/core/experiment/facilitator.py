"""This file keeps simple council phase helpers in one place.

This file gives the council scene a small helper object for phase text and
backward-compatible phase checks.
CouncilPhase names the simple discussion, voting, and concluded states.
SystemFacilitator stores the scene, reports the current simple phase, saves the
deliberation round count, gives prompt text, records when voting starts, and
offers a no-op compatibility hook for older transition calls.
"""

from __future__ import annotations

from enum import Enum


class CouncilPhase(Enum):
    """Simple council phases used by older council code paths."""

    DISCUSSION = "discussion"
    VOTING = "voting"
    CONCLUDED = "concluded"


class SystemFacilitator:
    """Manages simple council phase state for the council experiment scene."""

    def __init__(self, scene) -> None:
        self.scene = scene
        self.current_round_num = 1
        self._deliberation_rounds = 3
        self._vote_title = ""

    @property
    def phase(self) -> CouncilPhase:
        """Report the current simple phase from the scene state."""
        if self.scene.state.extensions.get("concluded", False):
            return CouncilPhase.CONCLUDED
        if getattr(self.scene, "cycle_phase", None) is not None:
            if getattr(self.scene.cycle_phase, "value", "") == "voting":
                return CouncilPhase.VOTING
        if self.scene.state.extensions.get("voting_started", False):
            return CouncilPhase.VOTING
        return CouncilPhase.DISCUSSION

    def set_deliberation_rounds(self, n: int) -> None:
        """Store how many discussion rounds should happen before voting."""
        self._deliberation_rounds = n

    def get_status_prompt(self) -> str:
        """Build a short plain-language phase summary for agents."""
        phase_name = self.phase.value
        if self.phase == CouncilPhase.VOTING and self._vote_title:
            return f"Current Phase: {phase_name}\nVote Topic: {self._vote_title}"
        return f"Current Phase: {phase_name}"

    def transition_to_voting(self, title: str) -> None:
        """Remember the vote title and mark voting as started."""
        self._vote_title = title
        self.scene.state.extensions["voting_started"] = True

    def check_and_transition_phase(self, round_num: int) -> bool:
        """Keep older caller code working without taking over scene transitions."""
        _ = round_num
        return False
