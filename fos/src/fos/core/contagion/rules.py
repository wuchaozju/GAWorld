"""
State transition rules for contagion dynamics.

This module provides the rule evaluation engine for contagion state transitions.
Rules are defined declaratively and evaluated by the scene, not agents,
maintaining agent isolation.

Contains: StateTransition, check_probability
"""
from dataclasses import dataclass
from typing import Optional
import random
from .states import ContagionState
from fos.i18n import T


@dataclass
class StateTransition:
    """
    Declarative rule for contagion state transitions.

    Defines when and how agents transition between infection states.
    Rules are evaluated by the scene controller, not by agents themselves.

    Attributes:
        from_state: The state an agent must be in to trigger this transition
        to_state: The state the agent will transition to
        trigger_type: How the transition is triggered ("proximity", "action", "decay")
        probability: Probability of transition (0.0 to 1.0)
        decay_turns: Number of turns before decay transition (required if trigger_type is "decay")

    Raises:
        ValueError: If probability is outside [0.0, 1.0]
        ValueError: If trigger_type is not valid
        ValueError: If trigger_type is "decay" and decay_turns is None
    """

    from_state: ContagionState
    to_state: ContagionState
    trigger_type: str
    probability: float
    decay_turns: Optional[int] = None

    def __post_init__(self):
        """Validate transition parameters after initialization."""
        # Validate probability range
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(
                T("probability must be between 0.0 and 1.0, got {probability}", probability=self.probability)
            )

        # Validate trigger_type
        valid_triggers = ("proximity", "action", "decay")
        if self.trigger_type not in valid_triggers:
            raise ValueError(
                T("trigger_type must be one of {valid_triggers}, got '{trigger_type}'", valid_triggers=valid_triggers, trigger_type=self.trigger_type)
            )

        # Validate decay_turns requirement
        if self.trigger_type == "decay" and self.decay_turns is None:
            raise ValueError(
                T("decay_turns is required when trigger_type is 'decay'")
            )


def check_probability(probability: float) -> bool:
    """
    Check if a probabilistic event occurs.

    Args:
        probability: Probability threshold (0.0 to 1.0)

    Returns:
        True if random.random() < probability, False otherwise

    Example:
        >>> if check_probability(0.3):
        ...     # 30% chance this executes
        ...     transition_state()
    """
    return random.random() < probability
