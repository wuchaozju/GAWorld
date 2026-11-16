"""
Game configuration for experiment prompts.

Adapted from tests/llm_prompt_testing/prompt_v2/game_configs.py
Provides translated game configs for social science experiment patterns.

Contains: GameConfig, CouncilConfig, GAME_CONFIGS, get_game_config
"""

from dataclasses import dataclass, field
from typing import Literal, Any

from ...i18n import T, get_request_locale


@dataclass
class GameConfig:
    """Configuration for a game/experiment.

    Attributes:
        name: Game name
        description: Full rules/payoffs description
        action_type: Type of action - "discrete" (enum) or "integer" (range)
        actions: List of valid action names (for discrete type)
        action_descriptions: Dict mapping action names to descriptions (Bug A fix)
        output_field: JSON field name for the action
        min: Minimum value (for integer type)
        max: Maximum value (for integer type)
        payoff_summary: Optional payoff description (Bug B fix)
        cooperate_reward: Payoff when both cooperate (R)
        sucker_penalty: Payoff when you cooperate, they defect (S)
        temptation_reward: Payoff when you defect, they cooperate (T)
        defect_penalty: Payoff when both defect (P)
        grouping_mode: How agents are grouped - "pairwise", "group", "neighbor", "individual"
        payoff_type: Type of payoff - "matrix", "pool", "feedback", "none"
        payoff_config: Configuration for payoff calculation
        action_schemas: Optional follow-up parameter schemas for per-action prompts
    """
    name: str
    description: str
    action_type: Literal["discrete", "integer"]
    actions: list[str]
    action_descriptions: dict[str, str] | None = None  # Bug A: Action descriptions
    output_field: str = "action"
    min: int = 0
    max: int = 10
    payoff_summary: str = ""
    # Payoff parameters for Prisoner's Dilemma style games
    cooperate_reward: int | None = None
    sucker_penalty: int | None = None
    temptation_reward: int | None = None
    defect_penalty: int | None = None
    # New fields for generic payoff system
    grouping_mode: str = "pairwise"
    payoff_type: str = "matrix"
    payoff_config: dict[str, Any] = field(default_factory=dict)
    # Schema definitions for actions requiring follow-up prompts
    # Format: {action_name: {"schema": {param: spec}, "mode": "json"|"plain_text"}}
    action_schemas: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Mapping of action names to follow-up modes for reprompting
    # e.g., {"Speak": "plain_text", "Vote": "json"}
    # Actions not in this dict are treated as simple discrete choices (no reprompt)
    action_followup_modes: dict[str, str] = field(default_factory=dict)


# Predefined game configs for the 6 social science patterns

PRISONERS_DILEMMA = GameConfig(
    name="Prisoner's Dilemma",
    description=(
        "Two suspects are arrested and held separately. Each must decide "
        "whether to betray the other or remain silent.\n"
        "Payoffs: If both cooperate (remain silent), both get 1 year. "
        "If one defects (betrays) and other cooperates, defector goes free, "
        "cooperator gets 5 years. If both defect, both get 3 years."
    ),
    action_type="discrete",
    actions=["cooperate", "defect"],
    action_descriptions={
        "cooperate": "Remain silent and cooperate with your partner",
        "defect": "Betray your partner and testify against them"
    },
    payoff_summary="Your payoff depends on both your choice and your partner's choice.",
)

STAG_HUNT = GameConfig(
    name="Stag Hunt",
    description=(
        "Hunters must all choose stag (high reward) or hare (safe but low reward). "
        "Stag requires everyone to cooperate. If even one person chooses hare, "
        "the stag escapes and stag hunters get nothing."
    ),
    action_type="discrete",
    actions=["stag", "hare"],
    payoff_summary="Stag pays 5 if ALL choose it, else 0. Hare always pays 1.",
)

MINIMUM_EFFORT = GameConfig(
    name="Minimum Effort Game",
    description=(
        "Team members choose effort levels from 1-7. Your payoff depends on "
        "the MINIMUM effort chosen by anyone in the group, minus your effort cost. "
        "Higher effort = higher potential reward but requires everyone to coordinate."
    ),
    action_type="integer",
    actions=[],
    output_field="effort",
    min=1,
    max=7,
    payoff_summary="Payoff = (minimum group effort * 2) - (your effort * 0.1)",
)

INFORMATION_CASCADE = GameConfig(
    name="Information Cascade (Urn Experiment)",
    description=(
        "An urn contains either 70% red balls (majority-red) or 70% blue balls "
        "(majority-blue). You will privately draw a ball, see its color, replace it. "
        "Then you must guess the urn type. You also see all previous participants' "
        "public guesses (but not their private draws)."
    ),
    action_type="discrete",
    actions=["majority_red", "majority_blue"],
    payoff_summary="You earn $1 if correct, $0 if wrong.",
)

CONSENSUS_GAME = GameConfig(
    name="Consensus Game",
    description=(
        "Participants coordinate to select the same number from 0-100 through "
        "local negotiation. You can see your neighbors' current values. "
        "Success when all agents converge on the same value (within +/-2)."
    ),
    action_type="integer",
    actions=[],
    output_field="value",
    min=0,
    max=100,
    payoff_summary="All agents earn $10 if consensus achieved, else $0.",
)

SPATIAL_COOPERATION = GameConfig(
    name="Spatial Cooperation Game",
    description=(
        "Agents arranged on a grid play Prisoner's Dilemma with immediate neighbors. "
        "You can see your neighbors' last choices (cooperate/defect). "
        "Cooperate: both get 1. Defect vs cooperate: defector gets 2, cooperator gets 0. "
        "Both defect: both get 0."
    ),
    action_type="discrete",
    actions=["cooperate", "defect"],
    payoff_summary="Your payoff is the sum of outcomes with all neighbors.",
)


# Sentinel value for required fields
_MISSING = object()


@dataclass
class CouncilConfig(GameConfig):
    """Configuration for Council experiment scene.

    Extends GameConfig with council-specific parameters for
    multi-round deliberation and voting.

    Attributes:
        deliberation_rounds: Number of rounds for discussion before voting
        voting_threshold: Fraction of yes votes needed to pass (0.0-1.0)
        proposal_text: Text of the proposal being voted on
    """
    # Override parent fields with defaults
    name: str = "Council Meeting"
    description: str = "Multi-round deliberation with voting"
    action_type: Literal["discrete", "integer"] = "discrete"
    # Minimal action set for controlled experiments - system controls phase transitions
    actions: list[str] = field(default_factory=lambda: ["speak", "skip", "vote_yes", "vote_no", "abstain"])
    # Council-specific fields - use sentinel to enforce required validation
    deliberation_rounds: int = field(default=_MISSING)  # type: ignore
    voting_threshold: float = field(default=_MISSING)  # type: ignore
    proposal_text: str = field(default=_MISSING)  # type: ignore

    def __post_init__(self):
        """Validate that required fields were provided."""
        if self.deliberation_rounds is _MISSING:
            raise ValueError(T("deliberation_rounds is required for CouncilConfig"))
        if self.voting_threshold is _MISSING:
            raise ValueError(T("voting_threshold is required for CouncilConfig"))
        if self.proposal_text is _MISSING:
            raise ValueError(T("proposal_text is required for CouncilConfig"))


def create_council_config(
    proposal_text: str,
    deliberation_rounds: int,  # NO DEFAULT
    voting_threshold: float  # NO DEFAULT
) -> CouncilConfig:
    """Create a CouncilConfig with specified parameters.

    Factory function for creating council experiment configurations
    with proper action definitions.

    Args:
        proposal_text: The text of the proposal to vote on
        deliberation_rounds: Number of discussion rounds before voting
        voting_threshold: Fraction of yes votes needed to pass

    Returns:
        CouncilConfig instance with all actions configured
    """
    return CouncilConfig(
        name="Council Meeting",
        description=f"Deliberation on: {proposal_text[:50]}...",
        actions=["speak", "skip", "vote_yes", "vote_no", "abstain"],
        deliberation_rounds=deliberation_rounds,
        voting_threshold=voting_threshold,
        proposal_text=proposal_text,
    )


# Map of game type keys to base GameConfig instances
GAME_CONFIGS: dict[str, GameConfig] = {
    "prisoners_dilemma": PRISONERS_DILEMMA,
    "stag_hunt": STAG_HUNT,
    "minimum_effort": MINIMUM_EFFORT,
    "information_cascade": INFORMATION_CASCADE,
    "consensus_game": CONSENSUS_GAME,
    "spatial_cooperation": SPATIAL_COOPERATION,
}


def get_game_config(game_type: str, locale: str | None = None) -> GameConfig:
    """Return a translated GameConfig for the given game type and locale.

    Args:
        game_type: Key from GAME_CONFIGS (e.g., 'prisoners_dilemma')
        locale: Language code. Falls back to request context or default.

    Returns:
        A new GameConfig with translated text fields.
    """
    effective_locale = locale or get_request_locale()
    base = GAME_CONFIGS[game_type]
    prefix = f"game_configs.{game_type}"

    action_descriptions = base.action_descriptions or {}
    translated_descriptions = {
        action_key: T(f"{prefix}.actions.{action_key}", locale=effective_locale)
        for action_key in action_descriptions
    }
    # Keep original for keys where no translation exists
    for k, v in translated_descriptions.items():
        if v == f"{prefix}.actions.{k}":
            translated_descriptions[k] = action_descriptions[k]

    return GameConfig(
        name=T(f"{prefix}.name", locale=effective_locale),
        description=T(f"{prefix}.description", locale=effective_locale),
        action_type=base.action_type,
        actions=base.actions,
        action_descriptions=translated_descriptions or None,
        output_field=base.output_field,
        min=base.min,
        max=base.max,
        payoff_summary=T(f"{prefix}.payoff_summary", locale=effective_locale),
        cooperate_reward=base.cooperate_reward,
        sucker_penalty=base.sucker_penalty,
        temptation_reward=base.temptation_reward,
        defect_penalty=base.defect_penalty,
        grouping_mode=base.grouping_mode,
        payoff_type=base.payoff_type,
        payoff_config=base.payoff_config,
        action_schemas=base.action_schemas,
        action_followup_modes=base.action_followup_modes,
    )
