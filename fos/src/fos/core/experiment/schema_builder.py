"""
JSON schema builder for constrained decoding.

Generates JSON schemas from GameConfig that can be passed to LLM providers
for structured output (Layer 1 of Three-Layer Architecture).
"""

from fos.core.experiment.game_configs import GameConfig


def build_schema(game_config: GameConfig) -> dict:
    """Build JSON schema from game config for constrained decoding.

    The schema enforces output structure at the API level:
    - The action field with enum constraints for discrete actions
    - The action field as integer for numeric actions

    Args:
        game_config: The game configuration

    Returns:
        JSON schema dict compatible with OpenAI/Ollama response_format

    Example output for Prisoner's Dilemma:
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["cooperate", "defect"]}
            },
            "required": ["action"]
        }
    """
    properties = {}
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
