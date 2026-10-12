"""This file turns experiment settings and history into clear prompts for agents."""

from __future__ import annotations

import logging

from fos.i18n import T

logger = logging.getLogger(__name__)


class ScenePromptMixin:
    def _uses_policy_cascade_actions(self) -> bool:
        """Tell whether this scenario should use the cascade communication action set."""
        return self.config.scenario_id == "policy_erosion"

    def _get_action_followup_modes(self, action_names: list[str]) -> dict[str, str]:
        """Determine which actions require follow-up prompts.

        Discussion scenarios (council_chamber, open_discussion, werewolf, contagion)
        need plain_text follow-up for Speak actions.

        Communication actions (notify, announce, report, etc.) detected by keyword
        also get plain_text follow-up so agents only need to pick an action first,
        then provide message content on a second prompt.

        Fallback: Auto-detect speak-like actions for any scenario, including "custom".

        Args:
            action_names: List of action names in this scenario

        Returns:
            Dict mapping action names to follow-up modes ("plain_text" or "json")
        """
        followup_modes = {}

        # Scenarios where "Speak" action needs free-text message input
        discussion_scenarios = {
            "council_chamber",
            "open_discussion",
            "werewolf",
            "contagion",
        }

        logger.debug(
            f"[FOLLOWUP] scenario_id={self.config.scenario_id}, action_names={action_names}"
        )
        logger.debug(
            f"[FOLLOWUP] is_discussion={self.config.scenario_id in discussion_scenarios}"
        )

        if self.config.scenario_id in discussion_scenarios:
            # Map any speak-like action to plain_text mode
            for action_name in action_names:
                if action_name.lower() in ("speak", "say", "talk"):
                    followup_modes[action_name] = "plain_text"
                    logger.debug(
                        f"[FOLLOWUP] Added followup mode for '{action_name}': plain_text"
                    )

        if self.config.scenario_id == "custom":
            return followup_modes

        # Fallback: Auto-detect speak-like actions for non-custom scenarios
        for action_name in action_names:
            if (
                action_name.lower() in ("speak", "say", "talk")
                and action_name not in followup_modes
            ):
                followup_modes[action_name] = "plain_text"
                logger.info(
                    f"[FOLLOWUP] Auto-detected speak action '{action_name}' (scenario_id={self.config.scenario_id})"
                )

        # Detect communication actions that need message content
        # Agents first pick just the action name (simple), then get reprompted
        # for their message content (follow-up prompt).
        communication_prefixes = (
            "notify",
            "announce",
            "report",
            "escalate",
            "consult",
            "send_",
            "tell",
            "reply",
            "message",
            "propose",
            "respond",
            "forward",
            "relay",
            "transmit",
        )
        for action_name in action_names:
            if action_name in followup_modes:
                continue
            lower_name = action_name.lower()
            if any(lower_name.startswith(p) for p in communication_prefixes):
                followup_modes[action_name] = "plain_text"
                logger.info(
                    f"[FOLLOWUP] Detected communication action '{action_name}' (scenario_id={self.config.scenario_id})"
                )

        logger.debug(f"[FOLLOWUP] Final followup_modes={followup_modes}")
        return followup_modes

    def _build_payoff_summary(self) -> str:
        """Build payoff_summary from scenario parameters - GENERIC version.

        Handles all game types:
        - PUBLIC_GOODS: Intertwined format with "person" language
        - Prisoner's Dilemma: Uses formatted payoff table
        - Other games: Generic parameter display
        """
        params = self.config.parameters
        locale = self.config.locale
        logger.debug(f"[PAYOFF] parameters: {params}")

        if not params:
            logger.debug("[PAYOFF] No parameters, returning empty")
            return ""
        if self.config.scenario_id == "custom":
            return ""

        # PUBLIC_GOODS: Use intertwined format with "person" language
        if self.config.scenario_id == "public_goods":
            tokens_per_round = params.get("tokens_per_round", 10)
            resource_name = params.get("resource_name", "tokens")
            multiplier = params.get("multiplier", 1.3)
            num_members = len(self.agents) if self.agents else 4
            deduction_budget = params.get("deduction_budget_per_phase", 0)
            deduction_cost_ratio = params.get("deduction_cost_ratio", 3)
            deduction_anonymous = params.get("deduction_anonymous", False)

            # Build intertwined scenario description
            lines = [
                T(
                    "experiment.payoff.pgg.intro",
                    locale=locale,
                    tokens=tokens_per_round,
                    resource=resource_name,
                ),
                T("experiment.payoff.pgg.pool_concept", locale=locale),
                T("experiment.payoff.pgg.distribution", locale=locale),
                "",
                T(
                    "experiment.payoff.pgg.multiplier",
                    locale=locale,
                    multiplier=multiplier,
                    members=num_members,
                ),
                T("experiment.payoff.pgg.keep", locale=locale, resource=resource_name),
            ]

            # Add deduction mechanics if enabled
            if deduction_budget and deduction_budget > 0:
                lines.append("")
                anonymity_key = (
                    "experiment.payoff.pgg.anonymous"
                    if deduction_anonymous
                    else "experiment.payoff.pgg.visible"
                )
                lines.append(
                    T(
                        "experiment.payoff.pgg.deduction_intro",
                        locale=locale,
                        resource=resource_name,
                    )
                    + " "
                    + T(
                        "experiment.payoff.pgg.deduction_budget",
                        locale=locale,
                        budget=deduction_budget,
                    )
                    + " "
                    + T(
                        "experiment.payoff.pgg.deduction_cost",
                        locale=locale,
                        ratio=deduction_cost_ratio,
                    )
                    + " "
                    + T(anonymity_key, locale=locale)
                )

            return "\n".join(lines)

        # Check if this is a Prisoner's Dilemma style game (has all 4 PD params)
        pd_params = [
            "cooperate_reward",
            "sucker_penalty",
            "temptation_reward",
            "defect_penalty",
        ]
        has_all_pd = all(params.get(p) is not None for p in pd_params)

        if has_all_pd:
            # Use the PD-specific format with generic "points" terminology
            # No meta-commentary - just the raw payoffs
            lines = [
                T("experiment.payoff.pd.header", locale=locale),
                T(
                    "experiment.payoff.pd.coop_coop",
                    locale=locale,
                    reward=params["cooperate_reward"],
                ),
                T(
                    "experiment.payoff.pd.coop_defect",
                    locale=locale,
                    penalty=params["sucker_penalty"],
                ),
                T(
                    "experiment.payoff.pd.defect_coop",
                    locale=locale,
                    reward=params["temptation_reward"],
                ),
                T(
                    "experiment.payoff.pd.defect_defect",
                    locale=locale,
                    penalty=params["defect_penalty"],
                ),
            ]
            return "\n".join(lines)

        # Generic parameter display for other game types
        lines = [T("experiment.payoff.generic_header", locale=locale)]
        for key, value in params.items():
            if value is not None:
                # Format key nicely (snake_case to Title Case)
                label = key.replace("_", " ").title()
                lines.append(
                    T(
                        "experiment.payoff.param_format",
                        locale=locale,
                        label=label,
                        value=value,
                    )
                )

        return "\n".join(lines)

    def _build_params_section(self) -> str:
        """Translate non-payoff scenario parameters into natural language for the prompt.

        Provides curated, human-readable descriptions for sociology scenario
        parameters so agents understand their environment without needing to
        interpret raw parameter values.
        """
        params = self.config.parameters
        scenario_id = self.config.scenario_id
        locale = self.config.locale
        if not params:
            return ""

        lines = []

        research_question = str(params.get("research_question", "") or "").strip()
        if research_question:
            lines.append(f"Research question: {research_question}")

        key_variables = params.get("ai_scientist_key_variables") or []
        if isinstance(key_variables, list) and key_variables:
            lines.append(
                "Key variables: "
                + ", ".join(str(item) for item in key_variables if str(item).strip())
            )

        assumptions = params.get("ai_scientist_assumptions") or []
        if isinstance(assumptions, list) and assumptions:
            lines.append(
                "Researcher review notes: "
                + " ".join(str(item) for item in assumptions if str(item).strip())
            )

        missing_information = params.get("ai_scientist_missing_information") or []
        if isinstance(missing_information, list) and missing_information:
            lines.append(
                "Open questions to keep in mind: "
                + " ".join(
                    str(item) for item in missing_information if str(item).strip()
                )
            )

        if scenario_id == "social_norm_disruption":
            norm_description = params.get("norm_description", "")
            norm_strength = params.get("norm_strength")
            if norm_description:
                lines.append(
                    T(
                        "experiment.scenario.social_norm.description",
                        locale=locale,
                        norm=norm_description,
                    )
                )
            if norm_strength is not None:
                strength_val = float(norm_strength)
                if strength_val <= 0.33:
                    label = T(
                        "experiment.scenario.social_norm.strength_weak", locale=locale
                    )
                elif strength_val <= 0.66:
                    label = T(
                        "experiment.scenario.social_norm.strength_moderate",
                        locale=locale,
                    )
                else:
                    label = T(
                        "experiment.scenario.social_norm.strength_strong", locale=locale
                    )
                lines.append(
                    T(
                        "experiment.scenario.social_norm.enforcement",
                        locale=locale,
                        label=label,
                    )
                )

        elif scenario_id == "policy_erosion":
            policy_text = params.get("policy_text", "")
            tier_labels = params.get("tier_labels", "")
            if policy_text:
                lines.append(
                    T(
                        "experiment.scenario.policy_erosion.policy_text",
                        locale=locale,
                        policy=policy_text,
                    )
                )
            if tier_labels:
                lines.append(
                    T(
                        "experiment.scenario.policy_erosion.tier_labels",
                        locale=locale,
                        tiers=tier_labels,
                    )
                )

        elif scenario_id == "echo_chamber":
            topic = params.get("topic", "")
            opinion_distribution = params.get("opinion_distribution", "")
            if topic:
                lines.append(
                    T(
                        "experiment.scenario.echo_chamber.topic",
                        locale=locale,
                        topic=topic,
                    )
                )
            if opinion_distribution:
                dist_key = (
                    f"experiment.scenario.echo_chamber.dist_{opinion_distribution}"
                )
                lines.append(T(dist_key, locale=locale))

        elif scenario_id == "resource_scarcity":
            resource_amount = params.get("resource_amount")
            initial_distribution = params.get("initial_distribution", "")
            if resource_amount is not None:
                lines.append(
                    T(
                        "experiment.scenario.resource_scarcity.amount",
                        locale=locale,
                        amount=resource_amount,
                    )
                )
            if initial_distribution:
                dist_key = (
                    f"experiment.scenario.resource_scarcity.dist_{initial_distribution}"
                )
                lines.append(T(dist_key, locale=locale))

        elif scenario_id == "open_discussion":
            topic = params.get("topic", "")
            if topic:
                lines.append(
                    T(
                        "experiment.scenario.open_discussion.topic",
                        locale=locale,
                        topic=topic,
                    )
                )

        elif scenario_id in ("council", "council_chamber"):
            # GAP-CLOSURE-01: Include deliberation rounds info for council scenarios
            deliberation_rounds = params.get("deliberation_rounds")
            proposal_text = params.get("proposal_text", "")
            if proposal_text:
                lines.append(
                    T(
                        "experiment.scenario.council.proposal",
                        locale=locale,
                        proposal=proposal_text,
                    )
                )
            if deliberation_rounds is not None and deliberation_rounds > 0:
                lines.append(
                    T(
                        "experiment.scenario.council.deliberation_rounds",
                        locale=locale,
                        rounds=deliberation_rounds,
                    )
                )
                lines.append(
                    T("experiment.scenario.council.no_vote_yet", locale=locale)
                )

        return "\n".join(lines)

    def _build_context_summary(self) -> str:
        """Build context summary from round history."""
        locale = self.config.locale
        if not self._history:
            return T("experiment.first_round", locale=locale)

        lines = []
        for entry in self._history[-5:]:  # Last 5 rounds max
            round_num = entry["round"]
            actions = entry["actions"]
            action_strs = [f"{a['agent']}: {a['action']}" for a in actions]
            actions_str = ", ".join(action_strs)
            line = T(
                "experiment.round_format",
                locale=locale,
                round_num=round_num,
                actions=actions_str,
            )
            # Include per-round payoffs if present (game theory scenarios)
            if entry.get("payoffs"):
                payoff_strs = [
                    f"{name} +{pts}" for name, pts in entry["payoffs"].items()
                ]
                line += T(
                    "experiment.payoffs_suffix",
                    locale=locale,
                    payoffs=", ".join(payoff_strs),
                )
                # Show cumulative scores for this agent
                agent_scores = {a.name: a.score for a in self.agents}
                score_strs = [f"{name}: {pts}" for name, pts in agent_scores.items()]
                line += T(
                    "experiment.scores_suffix",
                    locale=locale,
                    scores=", ".join(score_strs),
                )
            lines.append(line)

        return T("experiment.previous_rounds", locale=locale, rounds="\n".join(lines))
