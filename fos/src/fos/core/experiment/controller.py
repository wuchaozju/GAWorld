"""
Experiment Controller - validates LLM responses and executes actions (Layer 3).

The controller implements the validation layer:
1. Parse JSON (Layer 1 guarantees valid JSON)
2. Check action is in allowed set
3. Re-prompt for missing parameters if needed
4. Validate parameters
5. Execute action via Kernel
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import GameConfig
from fos.core.experiment.kernel import ExperimentKernel
from fos.core.experiment.round_context import RoundContextManager
from fos.core.experiment.prompt_builder import build_reprompt
from fos.core.agent.parsing import strip_thinking_tokens, strip_reasoning_prose, detect_reasoning_leak
from fos.core.experiment.validation import (
    validate_and_clamp,
    extract_json,
)
from fos.core.llm.client import LLMClient


logger = logging.getLogger(__name__)


def _summary_parameters(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only user-facing execution parameters for action summaries."""
    ignored_keys = {"reasoning", "reason", "rationale"}
    return {
        key: value
        for key, value in parameters.items()
        if key not in ignored_keys
    }


def _coerce_param(value: Any) -> Any:
    if isinstance(value, (int, float, bool, str)):
        return value
    if isinstance(value, dict):
        for key in ("value", "amount", "number", "num"):
            if key in value:
                inner = value[key]
                if isinstance(inner, (int, float)):
                    return inner
        if len(value) == 1:
            inner = next(iter(value.values()))
            if isinstance(inner, (int, float, bool, str)):
                return inner
        return str(value)
    if isinstance(value, list) and len(value) == 1:
        return _coerce_param(value[0])
    return value


def _repair_single_choose_action(
    result: dict[str, Any],
    game_config: GameConfig,
) -> dict[str, Any]:
    """Move a mistaken choice value into the parameter for a single choose action."""
    if game_config.action_type != "discrete":
        return result
    if len(game_config.actions) != 1:
        return result

    action_name = game_config.actions[0]
    if not action_name.startswith("choose_"):
        return result

    field = game_config.output_field
    raw_value = result.get(field)
    if not isinstance(raw_value, str) or raw_value.strip() == "":
        return result

    if raw_value.strip().lower() == action_name.lower():
        return result

    parameter_name = action_name.removeprefix("choose_")
    if parameter_name in result:
        return result

    repaired = dict(result)
    repaired[field] = action_name
    repaired[parameter_name] = raw_value.strip()
    return repaired


@dataclass
class ActionResult:
    """Result of processing an LLM action response.

    Attributes:
        success: Whether the action executed successfully
        action_name: Name of the action taken
        parameters: Action parameters (if any)
        summary: One-line human-readable summary
        agent_name: Agent who performed the action
        round_num: Round number
        skipped: True if validation failed and turn was skipped
        error: Error message if skipped
        debug_log: List of debug log lines (for atomic writing by runner)
    """
    success: bool
    action_name: str
    parameters: Dict[str, Any]
    summary: str
    agent_name: str
    round_num: int
    skipped: bool = False
    error: str = ""
    debug_log: List[str] = field(default_factory=list)
    prompt_tokens: int = 0
    degraded: bool = False
    degrade_reason: str = ""
    rounds_dropped: int = 0
    tokens_before: int = 0
    tokens_after: int = 0


class ExperimentController:
    """Controller for processing LLM responses with validation.

    Implements Layer 3 of the Three-Layer Architecture:
    - Validates action is in allowed set
    - Re-prompts for missing parameters (max 1)
    - Validates parameter types and values
    - Executes actions via Kernel
    """

    def __init__(
        self,
        kernel: ExperimentKernel,
        context_manager: RoundContextManager
    ):
        """Initialize controller.

        Args:
            kernel: Action registry
            context_manager: Context tracking manager
        """
        self.kernel = kernel
        self.context_manager = context_manager

    async def process_response(
        self,
        raw_json: str,
        agent: ExperimentAgent,
        game_config: GameConfig,
        llm_client: LLMClient,
        round_num: int
    ) -> ActionResult:
        """Process an LLM response through validation and execution.

        Args:
            raw_json: Raw JSON string from LLM
            agent: Agent who generated the response
            game_config: Game configuration
            llm_client: LLM client (for re-prompting)
            round_num: Current round number

        Returns:
            ActionResult with outcome and debug_log
        """
        debug_log = []

        debug_log.append("\n--- CONTROLLER: Processing Response ---\n")
        debug_log.append(f"  agent: {agent.name}\n")
        debug_log.append(f"  output_field: {game_config.output_field}\n")
        debug_log.append(f"  allowed actions: {game_config.actions}\n")

        # Step 1: Extract and parse JSON (handles trailing content from some models)
        cleaned = extract_json(raw_json)

        # If the model prepends junk before the first JSON object, trim to the
        # outermost braces to keep parsing strict while tolerating prefixes.
        if "{" in cleaned and "}" in cleaned:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start:end + 1]

        debug_log.append(f"  cleaned JSON: {cleaned[:200]}...\n" if len(cleaned) > 200 else f"  cleaned JSON: {cleaned}\n")

        try:
            parsed = json.loads(cleaned)

            debug_log.append(f"  parsed OK: {parsed}\n")

        except json.JSONDecodeError as e:
            # Try to salvage the first JSON-looking object in the text.
            import re
            match = re.search(r'\{[^{}]*\}', cleaned, re.DOTALL)
            if match:
                candidate = match.group(0)
                try:
                    parsed = json.loads(candidate)
                    debug_log.append(f"  parsed via salvage: {parsed}\n")
                except json.JSONDecodeError as e2:
                    debug_log.append(f"  ERROR: Failed to parse JSON after salvage: {e2}\n")
                    logger.error(f"Failed to parse JSON from {agent.name}: {e2}")
                    return ActionResult(
                        success=False,
                        action_name="",
                        parameters={},
                        summary="",
                        agent_name=agent.name,
                        round_num=round_num,
                        skipped=True,
                        error=f"Invalid JSON: {e2}",
                        debug_log=debug_log
                    )
            else:
                debug_log.append(f"  ERROR: Failed to parse JSON: {e}\n")
                logger.error(f"Failed to parse JSON from {agent.name}: {e}")
                return ActionResult(
                    success=False,
                    action_name="",
                    parameters={},
                    summary="",
                    agent_name=agent.name,
                    round_num=round_num,
                    skipped=True,
                    error=f"Invalid JSON: {e}",
                    debug_log=debug_log
                )

        repaired = _repair_single_choose_action(parsed, game_config)
        if repaired != parsed:
            debug_log.append(f"  repaired single choose action: {repaired}\n")
            parsed = repaired

        # Step 2: Validate against game config
        validated = validate_and_clamp(parsed, game_config)
        if validated is None:
            invalid_action = parsed.get(game_config.output_field, "")
            debug_log.append("  ERROR: Validation failed - action not in allowed set\n")
            debug_log.append(f"  parsed action field: {invalid_action}\n")
            logger.error(f"Validation failed for {agent.name}: {parsed}")
            return ActionResult(
                success=False,
                action_name=invalid_action,
                parameters={},
                summary="",
                agent_name=agent.name,
                round_num=round_num,
                skipped=True,
                error="Action not in allowed set",
                debug_log=debug_log
            )

        # Step 3: Extract action
        action_value = validated.get(game_config.output_field)

        debug_log.append(f"  extracted action: {action_value}\n")

        parameters = {
            key: value
            for key, value in validated.items()
            if key != game_config.output_field
        }

        # Belt-and-suspenders: strip thinking tokens from message field
        # that survived the initial chat-level stripping in LLMClient.chat()
        if "message" in parameters and isinstance(parameters["message"], str):
            raw_message = parameters["message"]
            # Strip both tag-style and prose-style reasoning
            cleaned = strip_thinking_tokens(raw_message)
            cleaned = strip_reasoning_prose(cleaned)
            parameters["message"] = cleaned
            # Detect residual leaks
            leak_detected = detect_reasoning_leak(cleaned)
            debug_log.append(f"  raw_message_length: {len(raw_message)}\n")
            debug_log.append(f"  clean_message_length: {len(cleaned)}\n")
            debug_log.append(f"  leak_detected: {leak_detected}\n")

        visible_parameters = _summary_parameters(parameters)
        summary = f"{agent.name} chose {action_value}"
        if visible_parameters:
            param_str = ", ".join(f"{k}={v}" for k, v in visible_parameters.items())
            summary = f"{agent.name} chose {action_value} ({param_str})"
        skipped = str(action_value).lower() == "skip"
        if game_config.name == "custom" and str(action_value).lower() == "speak":
            message = parameters.get("message")
            if message is None or str(message).strip() == "":
                return ActionResult(
                    success=False,
                    action_name=action_value,
                    parameters={},
                    summary="",
                    agent_name=agent.name,
                    round_num=round_num,
                    skipped=True,
                    error="Speak requires message",
                    debug_log=debug_log,
                )
        if skipped:
            summary = f"{agent.name} skipped"

        return ActionResult(
            success=True,
            action_name=action_value,
            parameters=parameters,
            summary=summary,
            agent_name=agent.name,
            round_num=round_num,
            skipped=skipped,
            debug_log=debug_log
        )

    async def process_response_with_followup(
        self,
        raw_json: str,
        agent: ExperimentAgent,
        game_config: GameConfig,
        llm_client: LLMClient,
        round_num: int,
        action_schemas: Optional[Dict[str, Dict[str, Any]]] = None,
        context_summary: str = "",
        information_model=None,
        kb_context: str = "",
        neighbor_context: str = "",
        speak_instruction: str | None = None,
        allowed_actions: Optional[List[str]] = None,
        locale: str = "en",
    ) -> ActionResult:
        """Process an LLM response with potential follow-up prompt for parameters.

        This method extends process_response to handle actions that require
        additional parameters (like 'talk' which needs a message).

        Args:
            raw_json: Raw JSON string from LLM
            agent: Agent who generated the response
            game_config: Game configuration
            llm_client: LLM client (for re-prompting)
            round_num: Current round number
            action_schemas: Dict mapping action names to their parameter schemas
            context_summary: The exact context used in the main prompt
            information_model: Information model used when building the prompt
            kb_context: Knowledge-base context used in the main prompt
            neighbor_context: Social-network context used in the main prompt
            allowed_actions: Optional filtered list of actions for phase-based filtering
            speak_instruction: Optional instruction for speak action (e.g., brevity constraint)

        Returns:
            ActionResult with outcome and debug_log
        """
        # First, process normally
        initial_result = await self.process_response(
            raw_json, agent, game_config, llm_client, round_num
        )

        # If initial processing failed, return the error
        if not initial_result.success:
            return initial_result

        action_name = initial_result.action_name
        debug_log = initial_result.debug_log.copy()
        schema_keys = list(action_schemas.keys()) if action_schemas else []
        canonical_action_name = action_name
        if action_schemas:
            for schema_key in action_schemas.keys():
                # Convert to strings for comparison (action_name may be int for integer-type games)
                if str(schema_key).lower() == str(action_name).lower():
                    canonical_action_name = schema_key
                    break
        should_follow_up = bool(action_schemas and canonical_action_name in action_schemas)

        debug_log.append("\n--- FOLLOW-UP GATING ---\n")
        debug_log.append(f"  action_name: {action_name}\n")
        debug_log.append(f"  canonical_action_name: {canonical_action_name}\n")
        debug_log.append(f"  schema_keys: {schema_keys}\n")
        debug_log.append(f"  should_follow_up: {should_follow_up}\n")

        # Check if this action requires a follow-up prompt.
        # action_schemas format: {action_name: {"schema": param_schema, "mode": "json"|"plain_text"}}
        if should_follow_up:
            schema_info = action_schemas[canonical_action_name]
            # Support both flat {param: schema} and wrapped {"schema": ..., "mode": ...} formats
            if "schema" in schema_info:
                param_schema = schema_info["schema"]
                followup_mode = schema_info.get("mode", "json")
            else:
                param_schema = schema_info
                followup_mode = "json"

            debug_log.append(f"\n{'='*80}\n")
            debug_log.append("FOLLOW-UP PROMPT REQUIRED\n")
            debug_log.append(f"{'='*80}\n")
            debug_log.append(f"  action: {action_name}\n")
            debug_log.append(f"  mode: {followup_mode}\n")
            debug_log.append(f"  required params: {list(param_schema.keys())}\n")


            followup_context = context_summary or self.context_manager.get_context_for_agent(
                agent.name,
                agent_score=agent.score,
            )

            # Build follow-up prompt using the action's parameter mode
            followup_prompt = build_reprompt(
                agent=agent,
                game_config=game_config,
                context_summary=followup_context,
                chosen_action=action_name,
                parameter_schema=param_schema,
                mode=followup_mode,
                include_section_markers=True,
                information_model=information_model,
                kb_context=kb_context,
                neighbor_context=neighbor_context,
                allowed_actions=allowed_actions,
                speak_instruction=speak_instruction,
                locale=locale,
            )

            # Log the follow-up prompt
            debug_log.append("\n--- FOLLOW-UP PROMPT ---\n")
            debug_log.append(followup_prompt)
            debug_log.append("\n--- END FOLLOW-UP PROMPT ---\n\n")


            try:
                # Send follow-up prompt; use json_mode only for json-type follow-ups
                messages = [{"role": "user", "content": followup_prompt}]
                followup_response = await asyncio.to_thread(
                    llm_client.chat, messages, json_mode=(followup_mode == "json")
                )

                # Log the follow-up response IMMEDIATELY after the prompt
                debug_log.append("\n--- FOLLOW-UP RESPONSE ---\n")
                debug_log.append(followup_response)
                debug_log.append("\n--- END FOLLOW-UP RESPONSE ---\n\n")


                # Parse the follow-up response based on mode
                if followup_mode == "plain_text":
                    # Plain text response (e.g., Speak action): store the whole string as "message"
                    parameters = {"message": followup_response.strip()}
                    parameter_source = "followup_plain_text"
                else:
                    # JSON response: parse and extract expected parameters
                    cleaned = extract_json(followup_response)
                    parsed_followup = json.loads(cleaned)
                    parameters = {k: _coerce_param(parsed_followup.get(k)) for k in param_schema.keys() if k in parsed_followup}
                    parameter_source = "followup_json"

                # Belt-and-suspenders: strip thinking tokens from message
                # field that survived the initial chat-level stripping
                if "message" in parameters and isinstance(parameters["message"], str):
                    raw_message = parameters["message"]
                    # Strip both tag-style and prose-style reasoning
                    cleaned = strip_thinking_tokens(raw_message)
                    cleaned = strip_reasoning_prose(cleaned)
                    parameters["message"] = cleaned
                    # Detect residual leaks
                    leak_detected = detect_reasoning_leak(cleaned)
                    debug_log.append(f"  raw_message_length: {len(raw_message)}\n")
                    debug_log.append(f"  clean_message_length: {len(cleaned)}\n")
                    debug_log.append(f"  leak_detected: {leak_detected}\n")

                debug_log.append(f"  final_parameter_source: {parameter_source}\n")
                debug_log.append(f"  final_parameters: {parameters}\n")

                # Update summary with parameters
                param_str = ", ".join(f"{k}={v}" for k, v in parameters.items())
                summary = f"{agent.name} chose {action_name} ({param_str})"

                # Add final result to debug log
                debug_log.append("\n--- PROCESSED RESULT ---\n")
                debug_log.append(f"  action: {action_name}\n")
                debug_log.append("  success: True\n")
                debug_log.append("  skipped: False\n")
                debug_log.append(f"  summary: {summary}\n")
                debug_log.append("\n" + "-"*80 + "\n\n")

                return ActionResult(
                    success=True,
                    action_name=canonical_action_name,
                    parameters=parameters,
                    summary=f"{agent.name} chose {canonical_action_name} ({param_str})",
                    agent_name=agent.name,
                    round_num=round_num,
                    skipped=False,
                    debug_log=debug_log
                )

            except Exception as e:
                debug_log.append(f"\n  ERROR in follow-up: {e}\n")
                logger.error(f"Follow-up prompt failed for {agent.name}: {e}")
                # Return the initial result without parameters but with updated debug log
                initial_result.debug_log = debug_log
                return initial_result

        # No follow-up needed - add final result to debug log
        debug_log.append("\n--- PROCESSED RESULT ---\n")
        debug_log.append(f"  action: {action_name}\n")
        debug_log.append("  success: True\n")
        debug_log.append("  skipped: False\n")
        debug_log.append(f"  summary: {initial_result.summary}\n")
        debug_log.append("\n" + "-"*80 + "\n\n")

        initial_result.debug_log = debug_log
        return initial_result
