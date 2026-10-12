"""
Pre-game comprehension checking for LLM agents.

Verifies that the model understands the game mechanics before
running simulations. Can be used as a gate to exclude models
that don't understand the game.
"""

import json
from ..ollama_client import OllamaClient, ChatMessage
from .game_configs import GameConfig


def verify_comprehension(
    client: OllamaClient,
    model: str,
    game_config: GameConfig,
) -> bool:
    """Verify model understands game mechanics before simulation.

    This is an optional pre-game check. For each game type, we ask
    specific comprehension questions that verify the model understands
    the payoffs and rules.

    Args:
        client: OllamaClient instance
        model: Model name to test
        game_config: The game configuration

    Returns:
        True if comprehension check passes, False otherwise

    Note:
        Currently implements checks for Prisoner's Dilemma.
        Other game types return True (skip check) by default.
        Add more game-specific checks over time.
    """
    # Prisoner's Dilemma specific check
    if game_config.action_type == "discrete" and "cooperate" in game_config.actions:
        if "Dilemma" in game_config.name or "dilemma" in game_config.name:
            return _check_prisoners_dilemma_comprehension(client, model, game_config)

    # Public Goods check
    if "Public Goods" in game_config.name:
        return _check_public_goods_comprehension(client, model, game_config)

    # For other game types, implement specific checks or return True to skip
    return True


def _check_prisoners_dilemma_comprehension(
    client: OllamaClient,
    model: str,
    game_config: GameConfig,
) -> bool:
    """Check comprehension of Prisoner's Dilemma payoffs.

    Asks: "If you cooperate and your partner defects, what is your payoff?"
    Expected: 0 (from payoff_summary CD=0)
    """
    check_prompt = f"""In {game_config.name} with payoffs: {game_config.payoff_summary}

If you cooperate and your partner defects, what is your payoff?
If both defect, what is your payoff?

Respond with JSON: {{"payoff_cooperate_they_defect": <number>, "payoff_both_defect": <number>}}"""

    check_schema = {
        "type": "object",
        "properties": {
            "payoff_cooperate_they_defect": {"type": "integer"},
            "payoff_both_defect": {"type": "integer"},
        },
        "required": ["payoff_cooperate_they_defect", "payoff_both_defect"],
    }

    try:
        messages = [ChatMessage(role="user", content=check_prompt)]
        response = client.chat_completion_with_schema(
            messages=messages, model=model, schema=check_schema
        )
        result = json.loads(response.content)

        # Expected: CD=0, DD=1
        return (
            result.get("payoff_cooperate_they_defect") == 0
            and result.get("payoff_both_defect") == 1
        )
    except Exception:
        return False


def _check_public_goods_comprehension(
    client: OllamaClient,
    model: str,
    game_config: GameConfig,
) -> bool:
    """Check comprehension of Public Goods Game mechanics.

    Asks: "If all 4 players contribute 10 tokens, what is your total payoff?"
    Expected: pool = 10*4*1.6 = 64, share = 64/4 = 16, kept = 10, total = 26
    """
    check_prompt = f"""In {game_config.name}, you have 20 tokens each round.
The pool is multiplied by 1.6 then split equally among all 4 players.

If all 4 players contribute 10 tokens each, what is your total payoff?
(Tokens kept + your share of the pool)

Respond with JSON: {{"total_payoff": <number>}}"""

    check_schema = {
        "type": "object",
        "properties": {
            "total_payoff": {"type": "integer"},
        },
        "required": ["total_payoff"],
    }

    try:
        messages = [ChatMessage(role="user", content=check_prompt)]
        response = client.chat_completion_with_schema(
            messages=messages, model=model, schema=check_schema
        )
        result = json.loads(response.content)

        # Expected: 10 (kept) + (10*4*1.6)/4 = 10 + 16 = 26
        return result.get("total_payoff") == 26
    except Exception:
        return False
