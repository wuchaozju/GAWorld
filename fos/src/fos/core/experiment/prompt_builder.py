"""
Experiment Prompt Builder - builds 5-section prompts (Layer 2).

The prompt builder constructs structured prompts from:
1. Agent Description (demographics)
2. Scenario (researcher-defined)
3. Available Actions (from kernel)
4. Context (cumulative per-agent summary)
5. JSON format instruction
"""

import json
import logging
import os
import re
from typing import Dict, Any, Literal

from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import GameConfig
from fos.i18n import T
from fos.core.experiment.prompt_audit import audit_prompt

logger = logging.getLogger(__name__)

def _interpret_score(value: int, locale: str = "en") -> str:
    """Convert numeric score to interpretation bracket.

    Args:
        value: Numeric score from 0-100
        locale: Language code for i18n (default "en")

    Returns:
        "low", "moderate", or "high" (translated)
    """
    if value <= 33:
        level = "low"
    elif value <= 66:
        level = "moderate"
    else:
        level = "high"
    return T(f"experiment.interpretation.{level}", locale=locale)

def _get_article(word: str) -> str:
    """Get the appropriate article (a/an) for a word.

    Args:
        word: The word to get an article for

    Returns:
        "an" if word starts with a vowel sound, "a" otherwise
    """
    vowels = ("a", "e", "i", "o", "u")
    return "an" if word.lower().startswith(vowels) else "a"

def truncate_context_to_budget(context: str, budget_chars: int, locale: str = "en") -> str:
    """Truncate context to fit within a character budget.

    Preserves whole lines, dropping from the middle to keep first and last content.
    Returns context unchanged if budget_chars is 0 (no limit).

    Args:
        context: Context string to truncate
        budget_chars: Maximum number of characters (0 = no limit)
        locale: Language code for i18n (default "en")

    Returns:
        Truncated context string, or original if within budget
    """
    if budget_chars <= 0 or len(context) <= budget_chars:
        return context
    lines = context.split("\n")
    result = []
    chars = 0
    for line in lines:
        needed = len(line) + (1 if result else 0)
        if chars + needed > budget_chars:
            result.append(T("experiment.rounds_omitted", locale=locale))
            break
        result.append(line)
        chars += needed
    return "\n".join(result)

def build_agent_description(
    agent_properties: Dict[str, Any],
    role_prompt: str = None,
    agent_name: str = "",
    locale: str = "en",
) -> str:
    """Build agent description section from demographic properties.

    If role_prompt is provided, it takes precedence and is used as the entire description.
    If properties are empty (manual agent), uses agent_name as identity.
    Otherwise, formats numeric traits with interpretation brackets:
    - 0-33 -> (low)
    - 34-66 -> (moderate)
    - 67-100 -> (high)

    Args:
        agent_properties: Dict of demographic properties
        role_prompt: Optional role prompt to use instead of demographic description
        agent_name: Agent name used as identity fallback for manual agents
        locale: Language code for i18n (default "en")

    Returns:
        Formatted agent description string with "=== EMBODY THIS PERSON ===" header

    Example:
        >>> build_agent_description({}, agent_name="Psychology Student")
        "=== EMBODY THIS PERSON ===\\nYou are Psychology Student."
        >>> build_agent_description({"age_group": "young adult", "social_capital": 82})
        "=== EMBODY THIS PERSON ===\\nYou are a young adult person. Your social_capital score is 82/100 (high)."
    """
    # If role_prompt exists, use it as the entire description
    if role_prompt:
        return role_prompt

    # Skip internal bookkeeping keys that don't describe the agent
    _skip_keys = {"avatarUrl", "archetype_id", "demographic_attributes"}
    # Also filter out empty string values - they don't provide meaningful information
    meaningful_props = {
        k: v for k, v in agent_properties.items()
        if k not in _skip_keys and v is not None and v != ""
    }

    # Manual agent: no meaningful properties → use name directly
    if not meaningful_props:
        return T("experiment.agent_identity", locale=locale, name=agent_name) if agent_name else T("experiment.participant_fallback", locale=locale)

    parts = []

    # Identity-related properties that define who the agent is
    _identity_keys = {"age_group", "profession", "role", "occupation"}
    # Only consider identity as present if the value is non-empty
    has_identity = any(
        k in meaningful_props and meaningful_props.get(k)
        for k in _identity_keys
    )

    if has_identity:
        # Build identity from available fields
        age_group = meaningful_props.get("age_group")
        profession = meaningful_props.get("profession") or meaningful_props.get("role") or meaningful_props.get("occupation")

        if age_group and profession:
            parts.append(T("experiment.agent_identity_with_adj", locale=locale, article=_get_article(age_group), adj=age_group, noun=profession))
        elif age_group:
            parts.append(T("experiment.agent_identity_adj_only", locale=locale, article=_get_article(age_group), adj=age_group))
        elif profession:
            parts.append(T("experiment.agent_identity_noun_only", locale=locale, article=_get_article(profession), noun=profession))
    else:
        # No identity properties - use agent name as identity
        if agent_name:
            parts.append(T("experiment.agent_identity", locale=locale, name=agent_name))

    # Add numeric traits with interpretation
    for key, value in meaningful_props.items():
        if key in _identity_keys:
            continue  # Already handled
        if isinstance(value, (int, float)):
            interpretation = _interpret_score(int(value), locale=locale)
            parts.append(T("experiment.trait_numeric", locale=locale, trait=key, value=value, interpretation=interpretation))
        elif isinstance(value, str) and value:
            parts.append(T("experiment.trait_string", locale=locale, trait=key, value=value))

    return " ".join(parts)

# -- Prompt audit (env-gated, FOS_PROMPT_AUDIT=<dir>) --
    return prompt

def build_prompt(
    agent: ExperimentAgent,
    game_config: GameConfig,
    context_summary: str,
    include_section_markers: bool = False,
    *,
    information_model=None,
    kb_context: str = "",
    neighbor_context: str = "",
    allowed_actions: list[str] | None = None,
    speak_instruction: str | None = None,
    locale: str = "en",
) -> str:
    """Build the 5-section structured prompt.

    Args:
        agent: The agent acting
        game_config: Game/scenario configuration
        context_summary: Cumulative context summary for this agent
        include_section_markers: If True, add explicit section markers for debugging
        allowed_actions: Optional filtered list of actions (GAP-CLOSURE-01).
                        If provided, overrides game_config.actions for phase-based filtering.
        speak_instruction: Optional instruction for speak action (e.g., brevity constraint).
        locale: Language code for i18n (default "en").

    Returns:
        Complete prompt string
    """
    sections = []

    # Section 1: Agent Description (role_prompt takes precedence if present;
    # manual agents with no properties fall back to their name)
    agent_desc = build_agent_description(
        agent.get_properties_dict(),
        role_prompt=getattr(agent, 'role_prompt', None),
        agent_name=agent.name,
        locale=locale,
    )
    # Add header for Section 1 - "EMBODY THIS PERSON"
    sections.append(T("experiment.section_embodiment", locale=locale))
    sections.append(agent_desc)

    # Section 2: Scenario (including payoff_summary if present - Bug B)
    scenario_text = game_config.description
    if game_config.payoff_summary:
        scenario_text += f"\n\n{game_config.payoff_summary}"
    if include_section_markers:
        sections.append("\n=== SECTION 2: SCENARIO ===")
    sections.append(f"\n{T('experiment.section_scenario', locale=locale)}\n{scenario_text}")

    # Section 3: Available Actions (using descriptions - Bug A)
    # GAP-CLOSURE-01: Use allowed_actions if provided for phase-based filtering
    actions_to_show = allowed_actions if allowed_actions is not None else game_config.actions

    if include_section_markers:
        sections.append("\n=== SECTION 3: AVAILABLE ACTIONS ===")
    if game_config.action_type == "discrete":
        if game_config.action_descriptions:
            # Bug A: Use action descriptions instead of "cooperate: cooperate"
            actions_list = "\n".join(
                f"- {a}: {game_config.action_descriptions.get(a, a)}"
                for a in actions_to_show
            )
        else:
            # Fallback to action name only if no descriptions available
            actions_list = "\n".join(f"- {a}" for a in actions_to_show)

        # Add speak instruction if provided (for brevity constraint)
        if speak_instruction and "speak" in actions_to_show:
            actions_list += f"\n\n{speak_instruction}"

        sections.append(f"\n{T('experiment.section_actions', locale=locale)}\n{actions_list}")
    else:  # integer
        sections.append(f"\n{T('experiment.section_action_integer', locale=locale)}\n{T('experiment.choose_range', locale=locale, min=game_config.min, max=game_config.max)}")

    # Section 3.5: Social Network Neighbors (if provided)
    if neighbor_context:
        if include_section_markers:
            sections.append("\n=== SECTION 3.5: SOCIAL NETWORK ===")
        sections.append(f"\n{T('experiment.section_social_network', locale=locale)}\n{neighbor_context}")

    # Section 3.6: Knowledge Base (if agent has relevant knowledge)
    if kb_context:
        if include_section_markers:
            sections.append("\n=== SECTION 3.6: KNOWLEDGE BASE ===")
        sections.append(f"\n{kb_context}")

    # Section 4: Context
    if include_section_markers:
        sections.append("\n=== SECTION 4: CONTEXT ===")
    budget = getattr(information_model, 'context_budget_chars', 0)
    display_context = (
        truncate_context_to_budget(context_summary, budget, locale=locale)
        if context_summary else ""
    )
    if display_context:
        sections.append(f"\n{T('experiment.section_context', locale=locale)}\n{display_context}")
    else:
        sections.append(f"\n{T('experiment.section_context', locale=locale)}\n{T('experiment.first_round', locale=locale)}")

    # Section 5: Output Format
    if include_section_markers:
        sections.append("\n=== SECTION 5: JSON OUTPUT REQUIREMENT ===")
    field = game_config.output_field
    if game_config.action_type == "discrete":
        # GAP-CLOSURE-01: Use filtered actions in output format
        actions_formatted = ", ".join(f'"{a}"' for a in actions_to_show)
        normalized_actions = {str(a).strip().lower() for a in actions_to_show}
        custom_speak_skip_only = (
            game_config.name == "custom"
            and normalized_actions == {"speak", "skip"}
        )
        if custom_speak_skip_only:
            sections.append(
                'Respond with exactly one JSON object in one of these forms:\n'
                '{"action": "speak", "message": "..."}\n'
                '{"action": "skip", "message": null}'
            )
        else:
            sections.append(T("experiment.response_actions", locale=locale, actions=actions_formatted, field=field, example=actions_to_show[0] if actions_to_show else "speak"))
    else:  # integer
        sections.append(T("experiment.response_integer", locale=locale, min=game_config.min, max=game_config.max, field=field))

    sections.append(f"\n{T('experiment.json_only', locale=locale)}")

    prompt = "\n".join(sections)

    # Log the full prompt for debugging
    logger.debug(f"\n{'='*60}")
    logger.debug(f"PROMPT FOR AGENT: {agent.name}")
    logger.debug(f"{'='*60}")
    logger.debug(prompt)
    logger.debug(f"{'='*60}\n")

    audit_prompt("build_prompt", prompt, agent_name=agent.name)
    return prompt



def build_reprompt(
    agent: ExperimentAgent,
    game_config: GameConfig,
    context_summary: str,
    chosen_action: str,
    parameter_schema: Dict[str, Any],
    mode: Literal["json", "plain_text"] = "json",
    include_section_markers: bool = False,
    *,
    information_model=None,
    kb_context: str = "",
    neighbor_context: str = "",
    allowed_actions: list[str] | None = None,
    speak_instruction: str | None = None,
    locale: str = "en",
) -> str:
    """Build a re-prompt for collecting missing parameters.

    Args:
        agent: The agent acting
        game_config: Game/scenario configuration
        context_summary: Cumulative context (same as original prompt)
        chosen_action: The action the agent chose
        parameter_schema: JSON schema of required parameters
        mode: json or plain_text
        include_section_markers: If True, add explicit section markers for debugging
        allowed_actions: Optional filtered list of actions (GAP-CLOSURE-01)
        speak_instruction: Optional instruction for speak action (e.g., brevity constraint)
        locale: Language code for i18n (default "en").

    Returns:
        Re-prompt string
    """
    # For plain_text mode, build a simplified prompt without JSON format instructions
    # The agent should respond with natural language, not JSON
    if mode == "plain_text":
        sections = []

        # Section 1: Agent Description
        agent_desc = build_agent_description(
            agent.get_properties_dict(),
            role_prompt=getattr(agent, 'role_prompt', None),
            agent_name=agent.name,
            locale=locale,
        )
        if include_section_markers:
            sections.append("=== SECTION 1: AGENT DESCRIPTION ===")
        sections.append(agent_desc)

        # Section 2: Scenario
        scenario_text = game_config.description
        if game_config.payoff_summary:
            scenario_text += f"\n\n{game_config.payoff_summary}"
        if include_section_markers:
            sections.append("\n=== SECTION 2: SCENARIO ===")
        sections.append(f"\n{T('experiment.section_scenario', locale=locale)}\n{scenario_text}")

        if neighbor_context:
            if include_section_markers:
                sections.append("\n=== SECTION 3.5: SOCIAL NETWORK ===")
            sections.append(f"\n{T('experiment.section_social_network', locale=locale)}\n{neighbor_context}")

        # Section 4: Context (truncated if needed)
        if include_section_markers:
            sections.append("\n=== SECTION 4: CONTEXT ===")
        budget = getattr(information_model, 'context_budget_chars', 0) if information_model else 0
        display_context = (
            truncate_context_to_budget(context_summary, budget, locale=locale)
            if context_summary else ""
        )
        if display_context:
            sections.append(f"\n{T('experiment.section_context', locale=locale)}\n{display_context}")
        else:
            sections.append(f"\n{T('experiment.section_context', locale=locale)}\n{T('experiment.first_round', locale=locale)}")

        # Follow-up instruction - NO JSON format for plain_text mode
        if include_section_markers:
            sections.append("\n=== FOLLOW-UP PROMPT (Action Requires Parameters) ===")

        sections.append(f"\n{T('experiment.followup_plain', locale=locale, action=chosen_action)}")

        # Add brevity instruction for speak action if provided
        if speak_instruction and chosen_action == "speak":
            sections.append(f"\n{speak_instruction}")

        sections.append(T("experiment.your_response", locale=locale))

        full_prompt = "\n".join(sections)

        if include_section_markers:
            logger.debug(f"\n{'='*60}")
            logger.debug(f"FOLLOW-UP PROMPT (plain_text) FOR AGENT: {agent.name}")
            logger.debug(f"CHOSEN ACTION: {chosen_action}")
            logger.debug(f"REQUIRED PARAMS: {list(parameter_schema.keys())}")
            logger.debug(f"{'='*60}")
            logger.debug(full_prompt)
            logger.debug(f"{'='*60}\n")

        audit_prompt("build_reprompt", full_prompt, agent_name=agent.name, mode=mode)
        return full_prompt

    # For JSON mode, build a simpler follow-up prompt WITHOUT full action list
    # This prevents confusion where the model re-selects from all actions instead of providing parameters
    sections = []

    # Section 1: Agent Description (keep identity context)
    agent_desc = build_agent_description(
        agent.get_properties_dict(),
        role_prompt=getattr(agent, 'role_prompt', None),
        agent_name=agent.name,
        locale=locale,
    )
    if include_section_markers:
        sections.append("=== SECTION 1: AGENT DESCRIPTION ===")
    sections.append(agent_desc)

    # Section 2: Scenario (keep game context)
    scenario_text = game_config.description
    if game_config.payoff_summary:
        scenario_text += f"\n\n{game_config.payoff_summary}"
    if include_section_markers:
        sections.append("\n=== SECTION 2: SCENARIO ===")
    sections.append(f"\n{T('experiment.section_scenario', locale=locale)}\n{scenario_text}")

    if neighbor_context:
        if include_section_markers:
            sections.append("\n=== SECTION 3.5: SOCIAL NETWORK ===")
        sections.append(f"\n{T('experiment.section_social_network', locale=locale)}\n{neighbor_context}")

    # Section 4: Context (truncated if needed)
    if include_section_markers:
        sections.append("\n=== SECTION 4: CONTEXT ===")
    budget = getattr(information_model, 'context_budget_chars', 0) if information_model else 0
    display_context = (
        truncate_context_to_budget(context_summary, budget, locale=locale)
        if context_summary else ""
    )
    if display_context:
        sections.append(f"\n{T('experiment.section_context', locale=locale)}\n{display_context}")
    else:
        sections.append(f"\n{T('experiment.section_context', locale=locale)}\n{T('experiment.first_round', locale=locale)}")

    # Follow-up instruction with JSON format
    if include_section_markers:
        sections.append("\n=== FOLLOW-UP PROMPT (Action Requires Parameters) ===")

    sections.append(f"\n{T('experiment.followup_params', locale=locale, action=chosen_action)}")

    # Detect numeric range constraints in parameter descriptions and highlight them.
    # Pattern matches descriptions like "(integer, 0 to 10)" or "(0 to 20)".
    _range_pattern = re.compile(
        r'\(\s*(?:(?:integer|number|float)\s*,?\s*)?(\d+)\s+to\s+(\d+)\s*\)',
        re.IGNORECASE,
    )
    for param_name, param_spec in parameter_schema.items():
        desc = param_spec.get("description", param_name)
        param_type = param_spec.get("type", "string")
        match = _range_pattern.search(desc)
        if match:
            min_val, max_val = match.group(1), match.group(2)
            sections.append(
                T("experiment.range_constraint", locale=locale, param=param_name, type=param_type, min=min_val, max=max_val)
            )

    # Build JSON template with concise range-aware placeholders
    params_parts: list[str] = []
    for k, v in parameter_schema.items():
        desc = v.get("description", k)
        match = _range_pattern.search(desc)
        if match:
            params_parts.append(f'"{k}": <{match.group(1)}-{match.group(2)}>')
        else:
            params_parts.append(f'"{k}": <{desc}>')
    params_desc = ", ".join(params_parts)

    sections.append(f"\n{T('experiment.followup_json', locale=locale, action=chosen_action, params=params_desc)}")
    sections.append(f"\n{T('experiment.json_only', locale=locale)}")

    full_prompt = "\n".join(sections)

    # Log the follow-up prompt
    if include_section_markers:
        logger.debug(f"\n{'='*60}")
        logger.debug(f"FOLLOW-UP PROMPT (json) FOR AGENT: {agent.name}")
        logger.debug(f"CHOSEN ACTION: {chosen_action}")
        logger.debug(f"REQUIRED PARAMS: {list(parameter_schema.keys())}")
        logger.debug(f"{'='*60}")
        logger.debug(full_prompt)
        logger.debug(f"{'='*60}\n")

    return full_prompt
