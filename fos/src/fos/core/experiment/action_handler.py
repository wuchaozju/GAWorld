"""
ActionHandler - dispatches actions and applies effects.

Receives action name, agent, parameters, and state. Looks up
the action definition, checks requirements, applies effects
or calls handler function.

Contains: ActionHandler
"""
from typing import Any
from fos.core.experiment.actions.registry import get_action
from fos.core.experiment.state import ExperimentState


class ActionHandler:
    """Dispatches actions and applies state effects."""

    def execute(
        self,
        action_name: str,
        agent_name: str,
        params: dict[str, Any],
        state: ExperimentState,
        scene: Any = None,
    ) -> dict[str, Any]:
        """Execute an action.

        Args:
            action_name: Name of action to execute
            agent_name: Agent performing action
            params: Action parameters
            state: Current experiment state (modified in place)
            scene: Optional scene instance for handlers that need scene context

        Returns:
            Result dict with success status and any error/details
        """
        action = get_action(action_name)
        if action is None:
            return {"success": False, "error": f"Unknown action: {action_name}"}

        # Record-only actions are logged but do not mutate state
        if action.record_only:
            return {"success": True, "effect_applied": False, "record_only": True}

        # Check requirements
        if action.requires:
            for req in action.requires:
                if not self._check_requirement(req, state, agent_name):
                    return {"success": False, "error": f"Missing requirement: {req}"}

        # Use handler if present, otherwise apply declarative effects
        if action.handler:
            # Try calling with scene parameter first (council handlers need scene)
            # Handler signatures: (action_data, agent_name, state, scene) or (agent_name, params, state)
            import inspect
            sig = inspect.signature(action.handler)
            param_count = len(sig.parameters)

            if param_count >= 4 and scene is not None:
                # Council-style handler: (action_data, agent_name, state, scene)
                handler_result = action.handler(params, agent_name, state, scene)
            else:
                # Standard handler: (agent_name, params, state)
                handler_result = action.handler(agent_name, params, state)
            # Ensure effect_applied is set for successful handler execution
            if handler_result.get("success", True):
                handler_result["effect_applied"] = True
            return handler_result
        else:
            return self._apply_effects(action.effects, agent_name, params, state)

    def _check_requirement(
        self, requirement: str, state: ExperimentState, agent_name: str
    ) -> bool:
        """Check if scenario meets action requirement.

        Args:
            requirement: Required feature name
            state: Current state
            agent_name: Agent name

        Returns:
            True if requirement is met
        """
        if requirement == "spatial":
            # Agent must have a position
            return state.get_agent_position(agent_name) is not None
        elif requirement == "resources":
            # Agent must have resources dict
            agent = state.agents.get(agent_name)
            return agent is not None and len(agent.resources) > 0
        elif requirement == "pools":
            # State must have pools extension
            return "pools" in state.extensions
        elif requirement == "voting":
            # State must have voting extension
            return "voting" in state.extensions or "proposals" in state.extensions
        else:
            # Unknown requirement - allow by default
            return True

    def _apply_effects(
        self,
        effects: list,
        agent_name: str,
        params: dict[str, Any],
        state: ExperimentState,
    ) -> dict[str, Any]:
        """Apply declarative effects to state.

        Args:
            effects: List of EffectSpec
            agent_name: Agent performing action
            params: Action parameters
            state: State to modify

        Returns:
            Success result
        """
        for effect in effects:
            self._apply_single_effect(effect, agent_name, params, state)

        return {"success": True, "effect_applied": True}

    def _apply_single_effect(
        self,
        effect,
        agent_name: str,
        params: dict[str, Any],
        state: ExperimentState,
    ) -> None:
        """Apply a single effect to state."""
        target = effect.target
        operation = effect.operation
        value_ref = effect.value

        # Resolve value (might be parameter reference or static)
        if value_ref in params:
            value = params[value_ref]
        else:
            value = value_ref

        # Parse target path
        if target.startswith("agent."):
            # Agent-scoped target
            parts = target.split(".")
            sub_field = parts[2] if len(parts) > 2 else None

            agent = state.agents.get(agent_name)
            if agent is None:
                return

            if sub_field:
                # e.g., agent.resources.tokens
                if operation == "subtract":
                    agent.resources[sub_field] = agent.resources.get(sub_field, 0) - value
                elif operation == "add":
                    agent.resources[sub_field] = agent.resources.get(sub_field, 0) + value
                elif operation == "set":
                    agent.resources[sub_field] = value

        elif target.startswith("extensions."):
            # Extension-scoped target
            parts = target.split(".")
            ext_name = parts[1]
            sub_field = parts[2] if len(parts) > 2 else None

            # Handle template variables like {pool}
            if sub_field and "{" in sub_field:
                for param_name, param_value in params.items():
                    sub_field = sub_field.replace(f"{{{param_name}}}", str(param_value))

            if operation == "add":
                if ext_name not in state.extensions:
                    state.extensions[ext_name] = {}
                if sub_field:
                    if sub_field not in state.extensions[ext_name]:
                        state.extensions[ext_name][sub_field] = 0
                    state.extensions[ext_name][sub_field] += value
            elif operation == "set":
                if ext_name not in state.extensions:
                    state.extensions[ext_name] = {}
                if sub_field:
                    state.extensions[ext_name][sub_field] = value
