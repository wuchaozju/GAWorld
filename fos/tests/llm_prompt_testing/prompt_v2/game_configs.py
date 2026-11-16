"""
Game configuration objects for prompt v2 module.

Flexible configuration that works with any social science scenario.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class GameConfig:
    """Flexible game configuration for any social science scenario.

    This is game-agnostic - the prompt builder works with any GameConfig
    to generate appropriate prompts dynamically.

    Attributes:
        name: Display name of the game/scenario
        description: Full rules and payoff information
        action_type: "discrete" for enum actions, "integer" for numeric ranges
        actions: List of valid action names (for discrete type)
        output_field: JSON field name for the action (default "action")
        min: Minimum value for integer type
        max: Maximum value for integer type
        payoff_summary: Optional concise payoff string
    """
    name: str
    description: str
    action_type: str  # "discrete" or "integer"
    actions: List[str] = field(default_factory=list)
    output_field: str = "action"
    min: int = 0
    max: int = 100
    payoff_summary: str = ""


# ============================================================================
# Example Game Configurations
# ============================================================================

PRISONERS_DILEMMA = GameConfig(
    name="Prisoner's Dilemma",
    description=(
        "Each round, you and your partner independently choose to cooperate or defect. "
        "Both cooperate = 3 points each. Both defect = 1 point each. "
        "You defect, they cooperate = 5 for you, 0 for them. "
        "You cooperate, they defect = 0 for you, 5 for them."
    ),
    action_type="discrete",
    actions=["cooperate", "defect"],
    output_field="action",
    payoff_summary="CC=3, DD=1, DC=5, CD=0",
)

STAG_HUNT = GameConfig(
    name="Stag Hunt",
    description=(
        "You and other hunters choose prey. Stag requires everyone to cooperate — "
        "high reward if all choose stag, nothing if anyone defects. "
        "Hare is a safe but small reward regardless of others. "
        "All choose stag = 4 points each. You choose hare = 2 points (guaranteed). "
        "You choose stag, anyone chooses hare = 0 points for you."
    ),
    action_type="discrete",
    actions=["stag", "hare"],
    output_field="action",
    payoff_summary="all_stag=4, any_hare_you_stag=0, you_hare=2",
)

MINIMUM_EFFORT = GameConfig(
    name="Minimum Effort Game",
    description=(
        "All players simultaneously choose an effort level. "
        "Your payoff depends on your effort and the MINIMUM effort chosen by anyone in the group. "
        "Payoff = 2 × min(all efforts) − your effort. "
        "Higher group minimum = higher payoff, but your own high effort is costly if others choose low."
    ),
    action_type="discrete",
    actions=["effort_1", "effort_2", "effort_3", "effort_4", "effort_5", "effort_6", "effort_7"],
    output_field="action",
    payoff_summary="2 × min(all) − yours",
)

CONSENSUS_GAME = GameConfig(
    name="Consensus Game",
    description=(
        "A group is discussing a topic. Each round you either share your perspective "
        "to build consensus, or listen to absorb others' views. "
        "The group benefits when members balance speaking and listening."
    ),
    action_type="discrete",
    actions=["consensus", "listen"],
    output_field="action",
)

SPATIAL_COOPERATION = GameConfig(
    name="Spatial Cooperation",
    description=(
        "You occupy a cell on a grid with neighbors. Each round you choose to "
        "cooperate with your neighbors, move to a new cell, or imitate the strategy "
        "of your most successful neighbor."
    ),
    action_type="discrete",
    actions=["cooperate", "move", "imitate"],
    output_field="action",
)

ULTIMATUM_PROPOSER = GameConfig(
    name="Ultimatum Game (Proposer)",
    description=(
        "You have 100 points. Propose how many points to offer the Responder (0-100). "
        "If they accept, you keep the remainder. If they reject, both get 0."
    ),
    action_type="integer",
    output_field="offer",
    min=0,
    max=100,
)

ULTIMATUM_RESPONDER = GameConfig(
    name="Ultimatum Game (Responder)",
    description=(
        "The Proposer has offered you a share of 100 points. "
        "If you accept, you get the offered amount and they keep the rest. "
        "If you reject, both get 0."
    ),
    action_type="discrete",
    actions=["accept", "reject"],
    output_field="action",
)

PUBLIC_GOODS = GameConfig(
    name="Public Goods Game",
    description=(
        "You have 20 tokens each round. Contribute any amount (0-20) to the public pool. "
        "The pool is multiplied by 1.6 then split equally among all 4 players. "
        "Tokens you keep are yours. Your total = kept tokens + your share of the pool."
    ),
    action_type="integer",
    output_field="contribution",
    min=0,
    max=20,
)
