"""This file manages scene phases, actions, host messages, and saved scene data."""

from __future__ import annotations

import logging
from typing import Self
from copy import deepcopy

from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.state import ExperimentState

logger = logging.getLogger(__name__)


class SceneRuntimeMixin:
    def post_turn(self, agent, simulator) -> None:
        """No-op base case for mixin super() chains.

        Pipeline A scenes don't use post_turn for orchestration,
        but policy cascade mixins call super().post_turn() through
        the MRO chain. This provides the terminal method so the
        chain resolves without AttributeError.
        """

    def is_complete(self) -> bool:
        """Check if experiment has natural end (most don't)."""
        return False  # Run forever via SimTree control

    def get_pgg_phase(self) -> str:
        """Get current PGG phase.

        Returns:
            "allocate" or "deduct"
        """
        return self._pgg_phase

    def advance_pgg_phase(self) -> None:
        """Advance to next PGG phase.

        Cycles: allocate -> deduct -> allocate (next round) -> ...
        BUT: Skip deduct phase entirely if deduction_budget_per_phase is 0.

        This ensures every "advance" click runs a valid allocation round
        with proper actions, never an empty/null round.

        Note: Does NOT reset deduction budget here. Budget reset happens
        via _reset_deduction_budgets() when entering deduct phase to avoid
        spurious resets from initialization or state replay.
        """
        params = self.config.parameters or {}
        deduction_budget = params.get("deduction_budget_per_phase", 0)

        if self._pgg_phase == "allocate":
            # Only go to deduct phase if deduction is enabled
            if deduction_budget and deduction_budget > 0:
                self._pgg_phase = "deduct"
            else:
                # Skip deduct phase entirely - stay in allocate for next round
                pass  # Phase stays "allocate", round advances in run_round()
        else:
            self._pgg_phase = "allocate"

    def _reset_deduction_budgets(self) -> None:
        """Reset deduction budgets at start of deduct phase.

        Reads deduction_budget_per_phase from current config, so mid-run
        config changes will affect subsequent phases. Setting budget to 0
        clears any leftover budget from when it was enabled.

        Called by runner when entering deduct phase, NOT in advance_pgg_phase
        to avoid spurious resets during initialization or state replay.
        """
        params = self.config.parameters or {}
        budget = int(params.get("deduction_budget_per_phase", 0) or 0)

        for agent_state in self.state.agents.values():
            agent_state.resources["deduction_budget"] = budget

        logger.debug(
            f"Reset deduction budgets to {budget} for {len(self.state.agents)} agents"
        )

    def get_scene_actions(self, agent_name: str) -> list[str] | None:
        """Filter available actions by current PGG phase.

        For PUBLIC_GOODS scenario, returns phase-appropriate actions.
        For other scenarios, returns None (caller should use all configured actions).

        Args:
            agent_name: Name of agent (for future per-agent filtering)

        Returns:
            List of action names available in current phase, or None if
            no filtering should be applied (use all configured actions).
        """
        if self.config.scenario_id != "public_goods":
            return None  # None = no filtering, use all configured actions

        current_phase = self._pgg_phase
        params = self.config.parameters or {}
        deduction_budget = params.get("deduction_budget_per_phase", 0)

        logger.info(
            f"[PGG] get_scene_actions called: phase={current_phase}, deduction_budget={deduction_budget}"
        )

        if current_phase == "allocate":
            return ["allocate", "keep"]
        else:  # deduct phase
            # Only show reduce/skip if deduction is enabled
            if deduction_budget and deduction_budget > 0:
                return ["reduce", "skip"]
            # Deductions disabled: no actions available in deduct phase
            return []

    def inject_host_message(self, message: str) -> None:
        """Queue a host message to be injected into all agents' context on the next round."""
        self._pending_host_messages.append(message)

    def serialize_config(self) -> dict:
        """Serialize for SimTree persistence."""
        agents = self.config.agents
        if self.agents:
            agents = []
            for agent in self.agents:
                llm = agent.llm_config
                llm_config = (
                    llm
                    if type(llm) is dict
                    else {
                        "dialect": llm.dialect,
                        "api_key": llm.api_key,
                        "model": llm.model,
                        "base_url": llm.base_url,
                        "temperature": llm.temperature,
                        "top_p": llm.top_p,
                        "frequency_penalty": llm.frequency_penalty,
                        "presence_penalty": llm.presence_penalty,
                        "max_tokens": llm.max_tokens,
                        "supports_vision": llm.supports_vision,
                    }
                )
                agents.append(
                    {
                        "name": agent.name,
                        "properties": dict(agent.properties),
                        "llm_config": llm_config,
                        "role_prompt": agent.role_prompt,
                        "provider_id": agent.provider_id,
                        "action_history": list(agent.action_history),
                        "score": agent.score,
                        "knowledge_base": list(agent.knowledge_base),
                        "documents": dict(agent.documents),
                    }
                )
        return {
            "config": {
                "agents": agents,
                "actions": self.config.actions,
                "parameters": self.config.parameters,
                "state_schema": self.config.state_schema,
                "description": self.config.description,
                "scenario_id": self.config.scenario_id,
                "round_visibility": self.config.round_visibility,
                "social_network": self.config.social_network,
                "locale": self.config.locale,
                "global_knowledge": self.global_knowledge,
            },
            "current_round": self.current_round,
            "history": self._history,
            "state": self.state.to_dict(),
            "pending_host_messages": self._pending_host_messages,
            "pgg_phase": self._pgg_phase,
        }

    @classmethod
    def deserialize_config(cls, data: dict) -> Self:
        """Restore from serialized state."""

        config = ExperimentConfig(**data["config"])
        scene = cls(config)
        scene.current_round = data.get("current_round", 0)
        # CRITICAL FIX: Deep copy history to prevent sharing across cloned scenes
        # Without this, all scenes share the same history list object, causing
        # rounds from later nodes to appear in earlier nodes' histories
        scene._history = deepcopy(data.get("history", []))
        if data.get("state") is not None:
            scene.state = ExperimentState.from_dict(data["state"])
        scene._pending_host_messages = deepcopy(data.get("pending_host_messages", []))
        # Restore PGG phase state (defaults to "allocate" for backwards compatibility)
        scene._pgg_phase = data.get("pgg_phase", "allocate")
        return scene
