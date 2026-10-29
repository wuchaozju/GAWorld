"""
Game-agnostic prompt builder for LLM agents.

Implements the improved prompt design from empirical testing:
- Payoff information included
- Round state with history (last 3 rounds)
- <YOUR_CHOICE> placeholder instead of ambiguous "name"
- "reasoning" field for think-then-constrain pattern
- Explicit markdown prohibition
"""

import json
from .game_configs import GameConfig


# System prompt template
SYSTEM_TEMPLATE = """You are Agent {agent_id} playing {game_name}.

RULES: {description}

{action_block}

OUTPUT FORMAT — respond with ONLY this JSON, nothing else:
{format_example}

{constraint_reminder}
No markdown. No explanation outside the JSON. No code fences."""


def build_system_prompt(game_config: GameConfig, agent_id: int = 0) -> str:
    """Build game-agnostic system prompt from config.

    The prompt includes:
    - Agent role and game name
    - Full rules/payoffs from description
    - Action list with clear instructions
    - JSON output format with <YOUR_CHOICE> placeholder
    - Explicit prohibition of markdown code fences

    Args:
        game_config: The game configuration
        agent_id: ID for multi-agent scenarios

    Returns:
        System prompt string
    """
    field = game_config.output_field

    if game_config.action_type == "discrete":
        actions_str = ", ".join(f'"{a}"' for a in game_config.actions)
        action_block = (
            f"YOUR ACTIONS: {actions_str}\n"
            f"You must choose exactly ONE action per round."
        )
        format_example = '{' + f'"reasoning": "one sentence about your choice", "{field}": "<YOUR_CHOICE>"' + '}'
        constraint_reminder = f'<YOUR_CHOICE> must be one of: {actions_str}'

    elif game_config.action_type == "integer":
        lo, hi = game_config.min, game_config.max
        action_block = f"Choose a value from {lo} to {hi}."
        format_example = '{' + f'"reasoning": "one sentence about your choice", "{field}": <INTEGER>' + '}'
        constraint_reminder = f"<INTEGER> must be a whole number from {lo} to {hi}."

    else:
        raise ValueError(f"Unknown action_type: {game_config.action_type}")

    return SYSTEM_TEMPLATE.format(
        agent_id=agent_id,
        game_name=game_config.name,
        description=game_config.description,
        action_block=action_block,
        format_example=format_example,
        constraint_reminder=constraint_reminder,
    )


def build_user_message(game_config: GameConfig, round_info: dict) -> str:
    """Build game-agnostic user message from config and round state.

    The user message is minimal — only dynamic game state:
    - Round number
    - Payoff summary (if available)
    - Recent history (last 3 rounds, capped for small models)
    - Additional context (if provided)
    - Imperative closing (not a question)

    Args:
        game_config: The game configuration
        round_info: Dict with round state:
            - round: Current round number
            - total_rounds: Total rounds
            - history: List of past round data (optional)
            - context: Additional context string (optional)

    Returns:
        User message string
    """
    parts = []

    rnd = round_info.get("round", 1)
    total = round_info.get("total_rounds", 10)
    parts.append(f"Round {rnd}/{total}.")

    if game_config.payoff_summary:
        parts.append(f"Payoffs: {game_config.payoff_summary}.")

    if round_info.get("history"):
        # Cap at last 3 rounds — critical for small models
        recent = round_info["history"][-3:]
        parts.append(f"Recent history: {json.dumps(recent)}.")
    else:
        parts.append("No history yet — this is the first round.")

    if round_info.get("context"):
        parts.append(round_info["context"])

    # Closing imperative (not a question — avoids inviting rambling)
    if game_config.action_type == "discrete":
        parts.append("Choose your action now.")
    else:
        parts.append(f"Choose your {game_config.output_field} now.")

    return " ".join(parts)
