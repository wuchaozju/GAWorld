"""This file builds initial experiment state and converts scene settings into game rules."""

from __future__ import annotations

import logging
from copy import deepcopy

from fos.core.experiment.game_configs import GameConfig
from fos.core.experiment.scene_actions import build_policy_cascade_action_definitions
from fos.core.experiment.state import AgentState
from fos.i18n import T

logger = logging.getLogger(__name__)


class SceneConfigurationMixin:
    def _initialize_state(self) -> None:
        """Initialize ExperimentState from config.

        Creates AgentState for each agent and applies state_schema extensions.
        Also initializes deduction budget if configured.

        Called during initialize() after agents are created.
        """
        params = self.config.parameters or {}

        # Get configurable resource name (default "tokens")
        resource_name = params.get("resource_name", "tokens")
        tokens_per_round = int(params.get("tokens_per_round", 20) or 20)
        deduction_budget = int(params.get("deduction_budget_per_phase", 0) or 0)

        # Create AgentState for each agent
        for agent_config in self.config.agents:
            name = agent_config.get("name", "")
            if not name:
                continue

            resources = deepcopy(agent_config.get("resources", {}))

            # Set initial resources using dynamic resource_name key
            if resource_name not in resources:
                resources[resource_name] = tokens_per_round

            # Add deduction budget if configured
            if deduction_budget > 0:
                resources["deduction_budget"] = deduction_budget

            agent_state = AgentState(
                score=0,
                position=agent_config.get("position"),
                resources=resources,
                properties=deepcopy(agent_config.get("properties", {})),
            )
            self.state.agents[name] = agent_state

        # Apply state_schema extensions
        if self.config.state_schema:
            if "extensions" in self.config.state_schema:
                self.state.extensions.update(
                    deepcopy(self.config.state_schema["extensions"])
                )

        # Initialize reductions tracking in extensions (renamed from punishments)
        if "reductions" not in self.state.extensions:
            self.state.extensions["reductions"] = {}

        logger.debug(
            f"Initialized state for {len(self.state.agents)} agents "
            f"(resource_name={resource_name}, deduction_budget={deduction_budget})"
        )

    def _create_game_config(self) -> GameConfig:
        """Create GameConfig from config data."""
        params = self.config.parameters or {}
        scenario = None
        try:
            from fos.core.scenarios.registry import get_scenario as _get_scenario

            scenario = _get_scenario(self.config.scenario_id, locale=self.config.locale)
        except Exception:
            scenario = None

        scenario_actions = scenario.get("actions", []) if scenario else []
        if self._uses_policy_cascade_actions():
            scenario_actions = build_policy_cascade_action_definitions(
                self.config.locale
            )
        if not scenario_actions and scenario and scenario.get("category_actions"):
            category_actions = scenario.get("category_actions", [])
            default_action_ids = scenario.get("default_action_ids", [])
            if default_action_ids:
                scenario_actions = [
                    action
                    for action in category_actions
                    if action.get("id") in default_action_ids
                ]
            else:
                scenario_actions = category_actions
        action_lookup = {}
        for action in scenario_actions:
            action_id = action.get("id")
            action_name = action.get("name")
            if action_id:
                action_lookup[str(action_id).lower()] = action
            if action_name:
                action_lookup[str(action_name).lower()] = action

        # Normalize selected actions back to canonical scenario action ids so runtime
        # semantics use stable machine names instead of frontend display labels.
        normalized_actions = []
        for action in self.config.actions:
            raw_name = str(action.get("name") or "").strip()
            if not raw_name:
                continue
            matched = action_lookup.get(raw_name.lower())
            if matched:
                normalized_actions.append(
                    {
                        "name": matched.get("id") or matched.get("name", raw_name),
                        "description": action.get("description")
                        or matched.get("description")
                        or raw_name,
                        # Use registry parameters if frontend doesn't provide them
                        "parameters": action.get("parameters")
                        or matched.get("parameters", []),
                    }
                )
            else:
                normalized_actions.append(
                    {
                        "name": raw_name,
                        "description": action.get("description") or raw_name,
                        "parameters": action.get("parameters", []),
                    }
                )

        if not normalized_actions and scenario_actions:
            normalized_actions = [
                {
                    "name": action.get("id") or action.get("name"),
                    "description": action.get("description")
                    or action.get("id")
                    or action.get("name"),
                    "parameters": action.get("parameters", []),
                }
                for action in scenario_actions
                if action.get("id")
            ]

        action_descriptions = {
            action["name"]: action["description"]
            for action in normalized_actions
            if action.get("name") and action.get("description")
        }
        action_names = [
            action["name"] for action in normalized_actions if action.get("name")
        ]
        action_schemas = {}
        type_map = {
            "string": "string",
            "text": "string",
            "integer": "integer",
            "float": "number",
            "number": "number",
            "boolean": "boolean",
        }
        for action in normalized_actions:
            parameter_specs = action.get("parameters", [])
            if not parameter_specs:
                continue
            schema_params = {}
            for param in parameter_specs:
                desc = param.get("description", param["name"])
                # Interpolate scenario params into description (e.g. "0 to {tokens_per_round}")
                try:
                    desc = desc.format(**params)
                except (KeyError, ValueError, IndexError):
                    pass
                schema_params[param["name"]] = {
                    "type": type_map.get(param.get("type", "string"), "string"),
                    "description": desc,
                }
            action_schemas[action["name"]] = {
                "schema": schema_params,
                "mode": "json",
            }

        # Handle configurable choices for coordination games (e.g., coordination_game)
        if self.config.scenario_id in ("coordination_game", "graph_coloring"):
            choices_str = (
                params.get("choices") or params.get("Choices") or "red, blue, green"
            )
            action_names = [c.strip() for c in choices_str.split(",")]
            action_descriptions = {
                c: T("experiment.choose_action", locale=self.config.locale, choice=c)
                for c in action_names
            }

        # Override action names/descriptions from parameterized action_1/action_2 if provided
        # Use translated descriptions from scenario registry when available
        if params.get("action_1") and params.get("action_2"):
            a1 = params["action_1"]
            a2 = params["action_2"]
            action_names = [a1.lower(), a2.lower()]
            # Prefer translated descriptions from scenario registry
            _reg_descs = {
                a.get("id", "").lower(): a.get("description", a.get("name", ""))
                for a in (scenario.get("actions", []) if scenario else [])
            }
            action_descriptions = {
                a1.lower(): _reg_descs.get(a1.lower(), a1),
                a2.lower(): _reg_descs.get(a2.lower(), a2),
            }

        # Build description: use description_template if present on the scenario
        # For PUBLIC_GOODS, we handle description in _build_payoff_summary instead
        description = self.config.description
        if self.config.scenario_id == "custom":
            description = str(params.get("custom_prompt") or self.config.description)
        if self.config.scenario_id == "public_goods":
            # For PUBLIC_GOODS, description is handled entirely by _build_payoff_summary
            description = ""
        try:
            _scenario = scenario
            if (
                _scenario
                and "description_template" in _scenario
                and params.get("action_1")
                and params.get("action_2")
            ):
                description = _scenario["description_template"].format(
                    action_1=params["action_1"],
                    action_2=params["action_2"],
                )
        except Exception:
            pass

        # Build supplementary prompt text: payoff table + sociology params
        supplementary_parts = []
        payoff_text = self._build_payoff_summary()
        if payoff_text:
            supplementary_parts.append(payoff_text)
        params_text = self._build_params_section()
        if params_text:
            supplementary_parts.append(params_text)

        # Build payoff_config from scenario registry metadata
        payoff_config = {}
        try:
            _scenario_for_payoff = scenario
            if _scenario_for_payoff and "matrix_meta" in _scenario_for_payoff:
                cells = _scenario_for_payoff["matrix_meta"].get("cells", {})
                # Remap matrix keys if action names were customized
                if params.get("action_1") and params.get("action_2"):
                    a1_key = params["action_1"].lower()
                    a2_key = params["action_2"].lower()
                    # Get the original action ids from registry actions
                    orig_actions = [
                        a["id"] for a in _scenario_for_payoff.get("actions", [])
                    ]
                    if len(orig_actions) >= 2:
                        orig_a1, orig_a2 = orig_actions[0], orig_actions[1]
                        remapped = {}
                        for cell_key, cell_val in cells.items():
                            new_key = cell_key.replace(orig_a1, a1_key).replace(
                                orig_a2, a2_key
                            )
                            remapped[new_key] = cell_val
                        cells = remapped
                payoff_config = {"matrix": cells}
            if (
                _scenario_for_payoff
                and _scenario_for_payoff.get("grouping_mode") == "group"
                and _scenario_for_payoff.get("payoff_type") == "matrix"
            ):
                _defaults = {
                    p["id"]: p["default"]
                    for p in _scenario_for_payoff.get("parameters", [])
                }
                if "stag_reward" in _defaults:
                    a1_key = params.get("action_1", "stag").lower()
                    payoff_config = {
                        "group_payoff_mode": "threshold",
                        "threshold_action": a1_key,
                        "threshold_reward": params.get(
                            "stag_reward", _defaults["stag_reward"]
                        ),
                        "threshold_failure": 0,
                        "safe_reward": params.get(
                            "hare_reward", _defaults["hare_reward"]
                        ),
                    }
            if (
                _scenario_for_payoff
                and _scenario_for_payoff.get("payoff_type") == "pool"
            ):
                defaults = {
                    p["id"]: p.get("default")
                    for p in _scenario_for_payoff.get("parameters", [])
                }
                payoff_config = {
                    "multiplier": params.get(
                        "multiplier", defaults.get("multiplier", 1.6)
                    ),
                    "initial_tokens": params.get(
                        "tokens_per_round", defaults.get("tokens_per_round", 20)
                    ),
                }
            if (
                _scenario_for_payoff
                and _scenario_for_payoff.get("payoff_type") == "feedback"
            ):
                defaults = {
                    p["id"]: p.get("default")
                    for p in _scenario_for_payoff.get("parameters", [])
                }
                payoff_config = {
                    "goal": params.get("goal", defaults.get("goal", "match")),
                }
        except Exception:
            pass

        followup_modes = self._get_action_followup_modes(action_names)
        for action_name, mode in followup_modes.items():
            if action_name in action_schemas:
                action_schemas[action_name]["mode"] = mode

        # FEAT-PGG: Handle reduce action based on deduction_budget_per_phase
        # When budget > 0: ensure reduce action is available
        # When budget <= 0: remove reduce action
        deduction_budget = int(params.get("deduction_budget_per_phase", 0) or 0)
        if deduction_budget > 0:
            # Add reduce action when deduction is enabled
            if "reduce" not in action_names:
                action_names = action_names + ["reduce"]
                action_descriptions["reduce"] = T(
                    "experiment.reduce_description", locale=self.config.locale
                )
                if "reduce" not in followup_modes:
                    followup_modes["reduce"] = "json"
            logger.debug(
                f"[GAME_CONFIG] Added 'reduce' action (deduction_budget={deduction_budget})"
            )
        else:
            # Remove reduce action when deduction is disabled
            if "reduce" in action_names:
                action_names = [a for a in action_names if a != "reduce"]
                action_descriptions.pop("reduce", None)
                action_schemas.pop("reduce", None)
                followup_modes.pop("reduce", None)
                logger.debug(
                    f"[GAME_CONFIG] Filtered 'reduce' action (deduction_budget={deduction_budget})"
                )

        logger.info(
            f"[GAME_CONFIG] scenario_id='{self.config.scenario_id}', action_names={action_names}, followup_modes={followup_modes}"
        )

        return GameConfig(
            name=self.config.scenario_id,
            description=description,
            action_type="discrete",
            actions=action_names if action_names else ["cooperate", "defect"],
            action_descriptions=action_descriptions or None,
            payoff_summary="\n\n".join(supplementary_parts),
            output_field="action",
            payoff_type=params.get(
                "payoff_type", (scenario or {}).get("payoff_type", "matrix")
            ),
            grouping_mode=params.get(
                "grouping_mode", (scenario or {}).get("grouping_mode", "pairwise")
            ),
            cooperate_reward=params.get("cooperate_reward"),
            sucker_penalty=params.get("sucker_penalty"),
            temptation_reward=params.get("temptation_reward"),
            defect_penalty=params.get("defect_penalty"),
            payoff_config=payoff_config,
            action_schemas=action_schemas,
            # Actions that require follow-up reprompt for free-text input
            action_followup_modes=followup_modes,
        )
