"""
JSON schema builder for constrained decoding.

Generates JSON schemas from GameConfig that can be passed to Ollama's
format parameter for constrained decoding.
"""

from .game_configs import GameConfig


def build_schema(game_config: GameConfig) -> dict:
    """Build JSON schema from game config for constrained decoding.

    The schema includes:
    - A "reasoning" field for the model's thinking (decoupled from output)
    - The action field with enum constraints for discrete actions
    - The action field as integer for numeric actions

    Args:
        game_config: The game configuration

    Returns:
        JSON schema dict compatible with Ollama's format parameter

    Example output for Prisoner's Dilemma:
        {
            "type": "object",
            "properties": {
                "reasoning": {"type": "string"},
                "action": {"type": "string", "enum": ["cooperate", "defect"]}
            },
            "required": ["action"]
        }
    """
    properties = {
        "reasoning": {"type": "string"}  # Always include reasoning field
    }
    required = []

    field = game_config.output_field

    if game_config.action_type == "discrete":
        properties[field] = {
            "type": "string",
            "enum": game_config.actions
        }
    elif game_config.action_type == "integer":
        properties[field] = {"type": "integer"}

    required.append(field)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
