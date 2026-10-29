"""This file builds experiment actions and extracts custom replies.

build_policy_cascade_action_definitions creates the translated communication
actions used by policy erosion experiments.
extract_custom_response_payload returns the visible reply fields from one
custom action.
"""

from typing import Any

from fos.i18n import T


def build_policy_cascade_action_definitions(locale: str) -> list[dict[str, Any]]:
    """Build the shared translated action list for policy communication."""
    action_specs = [
        (
            "send_message",
            [("message", "string", "message_content")],
        ),
        ("yield", []),
        (
            "report_upward",
            [
                ("target", "string", "direct_superior"),
                ("message", "string", "execution_difficulty"),
            ],
        ),
        (
            "escalate_complaint",
            [
                ("target", "string", "higher_superior"),
                ("message", "string", "escalation_report"),
            ],
        ),
        (
            "consult_peer",
            [
                ("target", "string", "peer_name"),
                ("message", "string", "consultation_message"),
            ],
        ),
        (
            "notify_subordinate",
            [
                ("target", "string", "subordinate_name"),
                ("message", "string", "private_notification"),
            ],
        ),
        (
            "announce_policy_adjustment",
            [("message", "string", "policy_adjustment")],
        ),
    ]
    return [
        {
            "id": action_name,
            "name": action_name,
            "description": T(
                f"experiment.action.{action_name}",
                locale=locale,
            ),
            "parameters": [
                {
                    "name": name,
                    "type": value_type,
                    "description": T(
                        f"experiment.action_parameter.{description_key}",
                        locale=locale,
                    ),
                }
                for name, value_type, description_key in parameters
            ],
        }
        for action_name, parameters in action_specs
    ]


def extract_custom_response_payload(
    parameters: dict[str, Any],
) -> dict[str, str]:
    """Pull the custom-visible reply fields out of action parameters."""
    response = str(
        parameters.get("response") or parameters.get("message") or ""
    ).strip()
    reason = str(
        parameters.get("reason")
        or parameters.get("reasoning")
        or parameters.get("rationale")
        or ""
    ).strip()
    message = str(parameters.get("message") or "").strip()
    return {
        "response": response,
        "reason": reason,
        "message": message,
    }
