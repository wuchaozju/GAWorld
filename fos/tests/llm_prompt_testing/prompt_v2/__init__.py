"""
Prompt Engineering v2 - Three-layer architecture for LLM agent prompts.

This module provides:
- Game-agnostic prompt building
- JSON schema generation for constrained decoding
- Validation with fuzzy matching and fallback
- Comprehension checking

The design preserves flexibility - works with any game scenario configuration.
"""

from .game_configs import (
    GameConfig,
    PRISONERS_DILEMMA,
    STAG_HUNT,
    MINIMUM_EFFORT,
    CONSENSUS_GAME,
    SPATIAL_COOPERATION,
    ULTIMATUM_PROPOSER,
    ULTIMATUM_RESPONDER,
    PUBLIC_GOODS,
)

__all__ = [
    "GameConfig",
    "PRISONERS_DILEMMA",
    "STAG_HUNT",
    "MINIMUM_EFFORT",
    "CONSENSUS_GAME",
    "SPATIAL_COOPERATION",
    "ULTIMATUM_PROPOSER",
    "ULTIMATUM_RESPONDER",
    "PUBLIC_GOODS",
]
