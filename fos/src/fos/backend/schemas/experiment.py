"""
Pydantic schemas for experiment template API.

Provides structured schemas for creating experiment templates with
predefined action types and proper validation.
"""

from datetime import datetime
from typing import Any
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ActionType(str, Enum):
    """Predefined action types for common social science experiments.

    These are the most common actions used in experiments. The frontend
    can display these as selectable options with descriptions.
    """
    COOPERATE = "cooperate"
    DEFECT = "defect"
    CONFORM = "conform"
    VOTE_YES = "vote_yes"
    VOTE_NO = "vote_no"
    ABSTAIN = "abstain"
    INVEST = "invest"
    WITHDRAW = "withdraw"
    SHARE = "share"
    KEEP = "keep"
    MOVE_LEFT = "move_left"
    MOVE_RIGHT = "move_right"
    STAY = "stay"
    SPEAK = "speak"
    CUSTOM = "custom"


# Human-readable descriptions for each action type
ACTION_DESCRIPTIONS: dict[str, str] = {
    "cooperate": "Cooperate with the other player(s) for mutual benefit",
    "defect": "Act in self-interest, potentially harming others",
    "conform": "Follow the group's choice or opinion",
    "vote_yes": "Cast a yes vote in favor of a proposal",
    "vote_no": "Cast a no vote against a proposal",
    "abstain": "Choose not to participate in a vote",
    "invest": "Contribute resources to a public good",
    "withdraw": "Take resources out for personal use",
    "share": "Share resources or information with others",
    "keep": "Keep resources or information private",
    "move_left": "Move to the left in a spatial setting",
    "move_right": "Move to the right in a spatial setting",
    "stay": "Stay in the current location",
    "speak": "Send a message to other participants",
    "custom": "A custom action defined by the researcher",
}


class ActionParameter(BaseModel):
    """Schema for an action parameter."""
    name: str = Field(..., description="Parameter name (e.g., 'amount', 'target')")
    type: str = Field(..., description="Parameter type (string, integer, float, boolean)")
    description: str = Field(..., description="Human-readable description of what this parameter does")
    required: bool = Field(default=True, description="Whether this parameter is required")
    default: Any = Field(default=None, description="Default value if not provided")


class ExperimentAction(BaseModel):
    """Schema for a single experiment action.

    Frontend can display the predefined actions as a selectable list,
    or allow custom actions with full parameter specification.
    """
    action_type: ActionType = Field(
        ...,
        description="Type of action (select from predefined or use 'custom')"
    )
    name: str = Field(
        ...,
        description="Display name for this action (e.g., 'Cooperate', 'Invest 50%')"
    )
    description: str = Field(
        default="",
        description="Human-readable description of what this action does"
    )
    parameters: list[ActionParameter] = Field(
        default_factory=list,
        description="Parameters this action accepts (leave empty for simple actions)"
    )

    # For custom actions, allow overriding the enum-based action_type
    custom_action_name: str | None = Field(
        default=None,
        description="For custom actions, the actual action name to use"
    )


class ExperimentSettings(BaseModel):
    """Schema for experiment settings."""
    model_config = ConfigDict(extra="allow")

    scenario_id: str = Field(
        default="custom",
        description="Scenario type identifier (e.g., 'prisoners_dilemma', 'stag_hunt', 'public_goods')"
    )
    round_visibility: str = Field(
        default="simultaneous",
        description="How agents see each other's choices: 'simultaneous' or 'sequential'"
    )
    max_rounds: int = Field(
        default=10,
        description="Maximum number of rounds to run"
    )

    # Payoff parameters for Prisoner's Dilemma style games
    cooperate_reward: int | None = Field(
        default=None,
        description="Payoff when both cooperate (R)"
    )
    sucker_penalty: int | None = Field(
        default=None,
        description="Payoff when you cooperate, they defect (S)"
    )
    temptation_reward: int | None = Field(
        default=None,
        description="Payoff when you defect, they cooperate (T)"
    )
    defect_penalty: int | None = Field(
        default=None,
        description="Payoff when both defect (P)"
    )


class ExperimentTemplateCreate(BaseModel):
    """Schema for creating an experiment template."""
    name: str = Field(..., description="Name of the experiment template")
    description: str = Field(..., description="Scenario description shown to agents")
    actions: list[ExperimentAction] = Field(
        ...,
        description="Available actions in this experiment"
    )
    settings: ExperimentSettings = Field(
        default_factory=ExperimentSettings,
        description="Experiment execution settings"
    )


class ExperimentTemplateResponse(BaseModel):
    """Schema for experiment template response."""
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: int
    name: str
    description: str
    actions: list[dict[str, Any]]
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ExperimentTemplateUpdate(BaseModel):
    """Schema for updating an experiment template."""
    name: str | None = None
    description: str | None = None
    actions: list[ExperimentAction] | None = None
    settings: ExperimentSettings | None = None


class ExperimentRunRequest(BaseModel):
    """Schema for running an experiment from a template."""
    template_id: int
    agents: list[dict[str, Any]]
    # TODO: implement llm_config handling in experiment execution
    llm_config: dict[str, Any]


class ExperimentRunResponse(BaseModel):
    """Schema for experiment run response."""
    experiment_id: str
    status: str
    initial_state: dict[str, Any]


# Schema for listing available action types (frontend can use this for UI)
class AvailableActionTypes(BaseModel):
    """Response schema for listing available action types."""
    actions: list[dict[str, str]] = Field(
        default_factory=lambda: [
            {"value": action.value, "label": action.value.replace("_", " ").title(), "description": desc}
            for action, desc in ACTION_DESCRIPTIONS.items()
        ]
    )
