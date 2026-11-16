"""This file initializes experiment agents and runs one experiment round at a time."""

from __future__ import annotations

import logging
from typing import Callable

from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.runner import ExperimentRunner, RoundResult
from fos.core.experiment.scene_actions import extract_custom_response_payload
from fos.core.experiment.state import AgentState
from fos.core.llm.client import LLMClient
from fos.i18n import T

logger = logging.getLogger(__name__)


class SceneLifecycleMixin:
    def initialize(
        self, llm_client: LLMClient, provider_clients: dict | None = None
    ) -> None:
        """Create ExperimentAgents directly from config.

        Args:
            llm_client: LLM client for prompting agents (default for agents without llm_config)
            provider_clients: Optional mapping of provider_id -> LLMClient for per-agent distribution
        """
        if self.runner is not None:
            return  # Already initialized

        self.llm_client = llm_client

        # Create ExperimentAgents directly from config
        self.agents = [
            ExperimentAgent(
                name=a["name"],
                properties=a.get("properties", {}),
                # Accept camelCase llmConfig from frontend as well as snake_case llm_config
                llm_config=a.get("llm_config") or a.get("llmConfig") or {},
                # Accept multiple field names for compatibility (camelCase from frontend, snake_case from backend)
                role_prompt=a.get("role_prompt")
                or a.get("rolePrompt")
                or a.get("profile"),
                action_history=list(a.get("action_history") or []),
                score=int(a.get("score", 0) or 0),
                knowledge_base=list(
                    a.get("knowledgeBase") or a.get("knowledge_base") or []
                ),
                documents=dict(a.get("documents") or {}),
                provider_id=a.get("provider_id") or a.get("providerId"),
            )
            for a in self.config.agents
        ]

        # Create per-agent LLM clients based on provider_id or llm_config.dialect
        # This enables LLM distribution - different agents can use different providers
        #
        # Resolution order (defense-in-depth):
        #   1. provider_clients[provider_id] â€” authoritative source from DB ProviderConfig
        #   2. llm_config dict/object        â€” fallback from agent config
        #   3. default llm_client             â€” final fallback
        self._agent_llm_clients = {}
        _is_stub = not isinstance(llm_client, LLMClient)
        for agent in self.agents:
            if _is_stub:
                self._agent_llm_clients[agent.name] = llm_client
                continue
            # PRIORITY: Use provider_clients[provider_id] when available.
            # This is the authoritative source â€” the DB ProviderConfig has the correct
            # model for each provider, whereas llm_config may have the default provider's
            # model due to a frontend bug where all agents get the same llmConfig.
            if (
                agent.provider_id
                and provider_clients
                and agent.provider_id in provider_clients
            ):
                self._agent_llm_clients[agent.name] = provider_clients[
                    agent.provider_id
                ]
                logger.debug(
                    f"Using provider_clients[{agent.provider_id}] for {agent.name}"
                )
                continue

            # Fallback: Create client from llm_config when provider_id lookup fails
            if agent.llm_config:
                _known_dialects = {"openai", "gemini", "mock", "ollama"}
                if isinstance(agent.llm_config, dict):
                    dialect = agent.llm_config.get("dialect") or agent.llm_config.get(
                        "provider"
                    )
                    if not dialect or dialect not in _known_dialects:
                        self._agent_llm_clients[agent.name] = llm_client
                        continue
                    model = agent.llm_config.get("model", "")
                    api_key = agent.llm_config.get("api_key", "")
                    base_url = agent.llm_config.get("base_url")
                    temperature = agent.llm_config.get("temperature", 0.7)
                    # Resolve credentials from default client if missing
                    if not api_key and hasattr(llm_client, "provider"):
                        api_key = llm_client.provider.api_key
                        base_url = base_url or llm_client.provider.base_url
                else:
                    # It's an LLMConfig object
                    dialect = getattr(agent.llm_config, "dialect", None)
                    if not dialect:
                        self._agent_llm_clients[agent.name] = llm_client
                        continue
                    model = getattr(agent.llm_config, "model", "")
                    api_key = getattr(agent.llm_config, "api_key", "")
                    base_url = getattr(agent.llm_config, "base_url", None)
                    temperature = getattr(agent.llm_config, "temperature", 0.7)

                from fos.core.llm_config import LLMConfig
                from fos.core.llm.client import LLMClient as AgentLLMClient

                config = LLMConfig(
                    dialect=dialect,
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                    temperature=temperature,
                )
                self._agent_llm_clients[agent.name] = AgentLLMClient(config)
                logger.debug(
                    f"Created LLM client for {agent.name}: dialect={config.dialect}, model={config.model}"
                )
            else:
                # Use default client for agents without explicit llm_config
                self._agent_llm_clients[agent.name] = llm_client

        logger.debug(
            f"Created {len(self.agents)} ExperimentAgents with LLM distribution"
        )

        # Write scenario start marker to shared debug log
        from fos.core.experiment.debug_log import write_scenario_header

        write_scenario_header(
            scenario_id=self.config.scenario_id,
            agent_names=[a.name for a in self.agents],
            params=dict(self.config.parameters or {}),
        )

        logger.debug(f"Created {len(self.agents)} ExperimentAgents")

        # Initialize experiment state only for fresh scenes.
        if (
            not self.state.agents
            and not self.state.extensions
            and not self.state.history
            and self.state.round == 0
        ):
            self._initialize_state()

        # Get InformationModel from registry (deferred import to avoid circular dependency)
        from fos.core.registry import get_information_model, pair_agents_randomly
        from fos.core.experiment.information_model import InformationModel

        information_model = get_information_model(self.config.scenario_id)

        # If the registry returned a generic "all" scope but this is a pairwise game
        # (more than 2 agents with PD-style payoffs), upgrade to pair scope so each
        # agent only sees their own game's results, not other pairs' actions.
        params = self.config.parameters or {}
        pd_keys = [
            "cooperate_reward",
            "sucker_penalty",
            "temptation_reward",
            "defect_penalty",
        ]
        has_pd_payoffs = all(params.get(k) is not None for k in pd_keys)

        if (
            information_model.scope_type == "all"
            and len(self.agents) > 2
            and has_pd_payoffs
        ):
            # Get show_average_contribution from parameters
            show_average = bool(params.get("show_average_contribution", False))
            information_model = InformationModel(
                scope_type="pair",
                pairing_fn=pair_agents_randomly,
                recent_window=information_model.recent_window,
                payoff_template="Round {N}: I {my_action}, partner {partner_action} â†’ {payoff} pts",
                show_average_contribution=show_average,
            )

        # For games without score-based payoffs, ensure include_scores=False
        # This handles cases where scenario_id doesn't match registry exactly
        payoff_type = params.get("payoff_type", "matrix")
        show_average = bool(params.get("show_average_contribution", False))

        # CRITICAL: Always apply show_average_contribution if parameter is True
        if payoff_type in ("feedback", "none", "") and information_model.include_scores:
            information_model = InformationModel(
                scope_type=information_model.scope_type,
                scope_fn=information_model.scope_fn,
                pairing_fn=information_model.pairing_fn,
                recent_window=information_model.recent_window,
                primacy_keep=information_model.primacy_keep,
                context_budget_chars=information_model.context_budget_chars,
                payoff_template=information_model.payoff_template,
                include_scores=False,
                show_average_contribution=show_average,
            )
        elif show_average:
            # CRITICAL: Apply show_average_contribution even for normal payoff types
            # Recreate information_model with the parameter
            information_model = InformationModel(
                scope_type=information_model.scope_type,
                scope_fn=information_model.scope_fn,
                pairing_fn=information_model.pairing_fn,
                recent_window=information_model.recent_window,
                primacy_keep=information_model.primacy_keep,
                context_budget_chars=information_model.context_budget_chars,
                payoff_template=information_model.payoff_template,
                include_scores=information_model.include_scores,
                show_average_contribution=show_average,
            )

        # Create the runner
        self.runner = ExperimentRunner(
            agents=self.agents,
            game_config=self._create_game_config(),
            llm_client=llm_client,
            round_visibility=self.config.round_visibility,
            information_model=information_model,
            scene=self,  # GAP-CLOSURE-01: pass scene for action filtering
            agent_llm_clients=self._agent_llm_clients,  # Pass per-agent LLM clients
        )

        # Wire social network graph AND state to runner's scene_state
        # CRITICAL: Both graph and state are needed for show_average_contribution feature
        # - graph: defines network neighbors for visibility calculation
        # - state: contains agent properties including last_contribution
        scene_state_dict = {"state": self.state}
        if self.config.social_network:
            scene_state_dict["graph"] = self.config.social_network
            logger.debug(
                f"Social network set: {len(self.config.social_network.get('edges', []))} edges"
            )
        else:
            logger.warning("No social network configured for this experiment")
        self.runner.set_scene_state(scene_state_dict)

        logger.debug("ExperimentRunner initialized:")
        logger.debug(f"  scenario_id={self.config.scenario_id}")
        logger.debug(f"  scope_type={information_model.scope_type}")
        logger.debug(f"  include_scores={information_model.include_scores}")
        logger.debug(f"  round_visibility={self.config.round_visibility}")
        logger.debug(f"  agents={len(self.agents)}")

    async def run_round(
        self, event_emitter: Callable[[str, dict], None]
    ) -> RoundResult:
        """Run exactly ONE round of the experiment.

        Args:
            event_emitter: Callback to emit events (type, data)

        Returns:
            RoundResult with all agent actions

        Raises:
            ValueError: If scene not initialized
        """
        if self.runner is None:
            raise ValueError(
                T("ExperimentScene not initialized - call initialize() first")
            )

        self.current_round += 1
        round_num = self.current_round

        # Flush pending host messages into runner for this round
        if self._pending_host_messages:
            self.runner.pending_host_messages = list(self._pending_host_messages)
            self._pending_host_messages.clear()

        logger.info(f"Running round {round_num}")

        # Build context from history
        context_summary = self._build_context_summary()

        # Run the round
        result = await self.runner._run_single_round(
            round_num=round_num,
            context_summary=context_summary,
            round_history=self._history,
        )

        round_events = {
            event.agent_name: event
            for event in self.runner.context_manager.get_round_events(round_num)
        }

        # Apply action effects to durable experiment state.
        # Capture execution results so failures are surfaced.
        exec_results: dict[str, dict] = {}
        for action in result.actions:
            if action.skipped and not action.success:
                continue
            exec_result = self.runner.execute_action(
                action.action_name,
                action.agent_name,
                action.parameters,
                self.state,
                self,  # Pass scene for council action handlers
            )
            exec_results[action.agent_name] = exec_result
            # If execution failed, mark the action as unsuccessful
            if not exec_result.get("success", False):
                action.success = False
                action.error = exec_result.get("error", "")

        # Update history for next round's context
        completed_actions = [action for action in result.actions if action.success]

        history_entry: dict = {
            "round": round_num,
            "actions": [
                {
                    "agent": a.agent_name,
                    "action": a.action_name,
                    "parameters": a.parameters,
                    "summary": a.summary,
                    "feedback": round_events.get(a.agent_name).feedback
                    if round_events.get(a.agent_name)
                    else None,
                }
                for a in completed_actions
            ],
        }
        if result.payoffs:
            history_entry["payoffs"] = result.payoffs
        self._history.append(history_entry)
        self.state.round = round_num
        self.state.history.append(history_entry)
        for agent in self.agents:
            if agent.name not in self.state.agents:
                self.state.agents[agent.name] = AgentState()
            self.state.agents[agent.name].score = agent.score

        # Emit events for frontend
        for action in result.actions:
            payoff = result.payoffs.get(action.agent_name) if result.payoffs else None
            exec_result = exec_results.get(action.agent_name, {})
            event_data = {
                "agent": action.agent_name,
                "action": action.action_name,
                "parameters": action.parameters,
                "summary": action.summary,
                "payoff": payoff,
                "round": round_num,
                "success": action.success,
                "skipped": action.skipped,
            }
            # Include execution-level metadata
            if exec_result.get("record_only"):
                event_data["record_only"] = True
                event_data["effect_applied"] = False
            elif action.success and exec_result.get("effect_applied", False):
                event_data["effect_applied"] = True
            # Always include error when present (regardless of success flag)
            if action.error:
                event_data["error"] = action.error
            event_emitter("experiment_action", event_data)
            if self.config.scenario_id == "custom" and action.success:
                reply_payload = extract_custom_response_payload(action.parameters)
                if reply_payload["response"] or reply_payload["reason"]:
                    event_emitter(
                        "experiment_response",
                        {
                            "agent": action.agent_name,
                            "action": action.action_name,
                            "round": round_num,
                            **reply_payload,
                        },
                    )

        logger.info(f"Round {round_num} complete: {len(result.actions)} actions")

        # Phase transition hook for council scenes (FEAT-COUNCIL-02)
        # Check if scene has facilitator with check_and_transition_phase method
        if hasattr(self, "facilitator") and hasattr(
            self.facilitator, "check_and_transition_phase"
        ):
            transitioned = self.facilitator.check_and_transition_phase(round_num)
            if transitioned:
                logger.info(f"Phase transitioned to VOTING after round {round_num}")

        return result
