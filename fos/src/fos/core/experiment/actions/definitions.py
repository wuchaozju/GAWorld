"""
Action definitions for the experiment system.

Provides schemas for defining actions: what parameters they need,
what effects they have, and what scenario features they require.

Contains: ActionDefinition, ParameterSpec, EffectSpec
"""
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class ParameterSpec:
    """Specification for an action parameter.

    Attributes:
        name: Parameter name (used in JSON response)
        type: One of "enum", "number", "text", "agent"
        options: For enum type, list of valid options
        required: Whether this parameter is required
    """
    name: str
    type: str  # "enum", "number", "text", "agent"
    options: list[str]
    required: bool = True


@dataclass
class EffectSpec:
    """Specification for an action's effect on state.

    Attributes:
        target: Path to state field (e.g., "agent.resources.tokens")
        operation: One of "set", "add", "subtract", "update_spatial"
        value: Static value or reference to parameter
    """
    target: str
    operation: str  # "set", "add", "subtract", "update_spatial"
    value: Any  # Static value or parameter reference


@dataclass
class ActionDefinition:
    """Definition of an action type.

    Attributes:
        name: Action name (used in JSON response)
        description: Human-readable description for prompts
        parameters: Parameters needed after action selection
        effects: State changes to apply
        requires: Scenario features required (e.g., ["spatial"])
        handler: Optional Python function for complex logic
        record_only: If True, action is logged but does not mutate state
    """
    name: str
    description: str
    parameters: list[ParameterSpec]
    effects: list[EffectSpec]
    requires: Optional[list[str]]
    handler: Optional[Callable] = None
    record_only: bool = False

    def needs_followup(self) -> bool:
        """Returns True if action needs parameter follow-up prompt."""
        return len(self.parameters) > 0
