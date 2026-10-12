"""This file translates GAWorld output into FOS event and state data.
Each function does one simple job:
- GAWorldOutputTranslator stores ID-to-name mapping and unknown action warnings.
- translate_day turns GAWorld day actions into FOS event dictionaries.
- _translate_action maps one GAWorld action into one FOS action and parameters.
- translate_state_updates pulls state values for each agent.
- translate_intervention_metrics wraps metrics for FOS use.

This module is the boundary between GAWorld output and FOS events.
The reverse direction (translate_to_gaworld_experiment) will be added here in v2.
"""

from __future__ import annotations

import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


class GAWorldOutputTranslator:
    """Converts GAWorld structures to FOS-friendly structures."""

    def __init__(self, agent_name_map: dict[int, str]) -> None:
        self.agent_name_map = agent_name_map
        self.warnings: list[str] = []

    def translate_day(self, day_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Converts all actions in a day payload into FOS event dictionaries."""

        events: list[dict[str, Any]] = []
        unknown_in_call: list[str] = []
        round_index = int(day_data.get("round", 0))

        for agent_data in day_data.get("agents", []):
            agent_id = int(agent_data.get("id", -1))
            agent_name = self.agent_name_map.get(agent_id, str(agent_id))
            actions = agent_data.get("actions", [])
            for action in self._normalized_actions(actions):
                action_type = str(action.get("type", ""))
                mapped_action, parameters, summary, is_unknown = self._translate_action(action_type, action)
                if is_unknown:
                    self.warnings.append(action_type)
                    unknown_in_call.append(action_type)
                events.append(
                    {
                        "agent": agent_name,
                        "action": mapped_action,
                        "parameters": parameters,
                        "summary": summary,
                        "round": round_index,
                        "success": True,
                    }
                )

        if unknown_in_call:
            LOGGER.warning(
                "gaworld.translator.unknown_action_types",
                extra={"action_types": unknown_in_call},
            )

        return events

    def _normalized_actions(self, actions: Any) -> list[dict[str, Any]]:
        """Turns different GAWorld action payload shapes into one list of action dicts."""
        if isinstance(actions, list):
            return [action for action in actions if isinstance(action, dict)]

        if isinstance(actions, dict):
            normalized: list[dict[str, Any]] = []
            for activity_name, options in actions.items():
                normalized.append(
                    {
                        "type": str(activity_name),
                        "description": str(activity_name),
                        "options": list(options) if isinstance(options, list) else [options],
                    }
                )
            return normalized

        return []

    def _translate_action(
        self,
        action_type: str,
        action_dict: dict[str, Any],
    ) -> tuple[str, dict[str, Any], str, bool]:
        """Maps one GAWorld action payload into FOS action values."""

        summary = str(action_dict.get("description", ""))
        if action_type == "work":
            return "work", {"hours": float(action_dict.get("hours", 0))}, summary, False
        if action_type == "social_interact":
            return "social_interact", {"target": action_dict.get("target")}, summary, False
        if action_type == "consume_media":
            return "consume_media", {"platform": action_dict.get("platform")}, summary, False
        if action_type == "move":
            return "move", {"destination": action_dict.get("destination")}, summary, False
        if action_type == "rest":
            return "rest", {"hours": float(action_dict.get("hours", 0))}, summary, False
        return "custom", {"raw_action": action_type}, summary, True

    def translate_state_updates(self, day_data: dict[str, Any]) -> dict[str, dict[str, float]]:
        """Extracts tracked state values by mapped agent name."""

        state_updates: dict[str, dict[str, float]] = {}
        for agent_data in day_data.get("agents", []):
            agent_id = int(agent_data.get("id", -1))
            agent_name = self.agent_name_map.get(agent_id, str(agent_id))
            state_updates[agent_name] = {
                "emotion": float(agent_data.get("emotion", 0.0)),
                "stress": float(agent_data.get("stress", 0.0)),
                "econ_security": float(agent_data.get("econ_security", 0.0)),
                "city_identity": float(agent_data.get("city_identity", 0.0)),
            }
        return state_updates

    def translate_intervention_metrics(self, metrics_data: dict[str, Any]) -> dict[str, Any]:
        """Wraps metrics in the expected FOS envelope key."""

        return {"intervention_metrics": metrics_data}
