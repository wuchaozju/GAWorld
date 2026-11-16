"""
Prompt builder for LLM prompt testing.

Provides simplified prompts for small 3B-4B models that struggle
with long, complex prompts. Includes minimal JSON, XML, and text variants.
"""


from .agents import AgentProfile
from .scenarios import ScenarioConfig


# ============================================================================
# Minimal Prompts for 3-4B Models
# ============================================================================

def build_json_prompt(
    scenario: ScenarioConfig,
    agent: AgentProfile,
) -> str:
    """
    Build a minimal JSON-only prompt for small 3B-4B models.

    Key principles:
    - Under 40 words total
    - Single clear instruction
    - No examples (saves tokens)
    - JSON-only output format

    Args:
        scenario: The scenario configuration
        agent: The agent profile

    Returns:
        Minimal JSON-only prompt
    """
    # Build action list string
    action_list = ", ".join(f'"{a.name}"' for a in scenario.actions)

    # Minimal JSON prompt (under 40 words)
    prompt = f"""You are {agent.name}. {agent.role_prompt}

Available actions: {action_list}

Respond with ONLY JSON: {{"action": "action_name"}}"""

    return prompt


def build_xml_prompt(
    scenario: ScenarioConfig,
    agent: AgentProfile,
) -> str:
    """
    Build a minimal XML-only prompt for small 3B-4B models.

    Key principles:
    - Under 40 words total
    - Single clear instruction
    - XML tag output format
    - No multi-section requirements

    Args:
        scenario: The scenario configuration
        agent: The agent profile

    Returns:
        Minimal XML-only prompt
    """
    # Build action list string
    action_list = ", ".join(f'"{a.name}"' for a in scenario.actions)
    first_action = scenario.actions[0].name if scenario.actions else "action_name"

    # Minimal XML prompt
    prompt = f"""You are {agent.name}. {agent.role_prompt}

Available actions: {action_list}

Respond with ONLY: <Action name="{first_action}" />"""

    return prompt


def build_text_prompt(
    scenario: ScenarioConfig,
    agent: AgentProfile,
) -> str:
    """
    Build a minimal plain text prompt for small 3B-4B models.

    Key principles:
    - Under 40 words total
    - Single clear instruction
    - Plain text action name only
    - No structured format requirements

    Args:
        scenario: The scenario configuration
        agent: The agent profile

    Returns:
        Minimal plain text prompt
    """
    # Build action list string
    action_list = ", ".join(f'"{a.name}"' for a in scenario.actions)

    # Minimal text prompt
    prompt = f"""You are {agent.name}. {agent.role_prompt}

Available actions: {action_list}

Respond with action name only."""

    return prompt


# ============================================================================
# Prompts by Format Type
# ============================================================================

PROMPT_BUILDERS = {
    "json": build_json_prompt,
    "xml": build_xml_prompt,
    "text": build_text_prompt,
}


def build_prompt_by_format(
    scenario: ScenarioConfig,
    agent: AgentProfile,
    format_type: str = "json",
) -> str:
    """
    Build a prompt for the specified format type.

    Args:
        scenario: The scenario configuration
        agent: The agent profile
        format_type: One of "json", "xml", "text"

    Returns:
        Prompt string for the specified format
    """
    builder = PROMPT_BUILDERS.get(format_type, build_json_prompt)
    return builder(scenario, agent)


# ============================================================================
# Original Simple Prompt (Multi-Section)
# ============================================================================

def build_simple_prompt(
    scenario: ScenarioConfig,
    agent: AgentProfile,
) -> str:
    """
    Build a simplified system prompt for small 3B-4B models.

    The key insight is that small models (3B-4B parameters) struggle with:
    - Long prompts (> 100 words)
    - Complex multi-part instructions
    - Multiple examples and warnings
    - Nested formatting requirements

    This function creates a minimal prompt that gets straight to the point.

    Args:
        scenario: The scenario configuration
        agent: The agent profile

    Returns:
        Simplified system prompt string with required sections for evaluator
    """
    # Build action list string
    action_list = ", ".join(f'"{a.name}"' for a in scenario.actions)
    first_action = scenario.actions[0].name if scenario.actions else "action_name"

    # Minimal prompt with required sections (satisfies evaluator, keeps short)
    prompt = f"""You are {agent.name}. {agent.role_prompt}

{scenario.system_instructions}

Available actions: {action_list}

--- Thoughts ---
Decision.

---- Plan ---
Action.

---- Action ---
<Action name="{first_action}" />"""

    return prompt


# ============================================================================
# Full Prompt for Larger Models
# ============================================================================

def build_full_prompt(
    scenario: ScenarioConfig,
    agent: AgentProfile,
) -> str:
    """
    Build the full system prompt with all details.

    Use this only for larger models (7B+) that can handle
    complex instructions.

    Args:
        scenario: The scenario configuration
        agent: The agent profile

    Returns:
        Complete system prompt string with all details
    """
    prompt = f"""You are {agent.name} - {agent.role_prompt}

Personality: {agent.personality}
Style: {agent.style}

Goals:
{chr(10).join(f"- {g}" for g in agent.goals)}

"""

    # Add scenario-specific instructions
    if scenario.system_instructions:
        prompt += scenario.system_instructions + "\n"

    # Add available actions
    if scenario.actions:
        action_names = ", ".join(f'"{a.name}"' for a in scenario.actions)
        prompt += f"""

IMPORTANT: You MUST use EXACTLY one of these action names: {action_names}
Do NOT invent your own actions. Do NOT use generic phrases like "I choose" or "I decide".
"""

    # Add output format instructions with explicit examples
    first_action = f'"{scenario.actions[0].name}"' if scenario.actions else "action_name"
    prompt += f"""
Output Format (follow exactly - NO OTHER TEXT):
--- Thoughts ---
[Brief thought]

---- Plan ---
Goals: [your goals]
Milestones: [completed ✓, pending →]

---- Action ---
<Action name="{first_action}">
  parameter="value"
</Action>

CRITICAL: Your output must end with Action tag. Do NOT add explanations, notes, or extra text after Action tag.
Keep thoughts and plan brief.

EXAMPLE: If choosing to cooperate, output EXACTLY:
--- Thoughts ---
I will cooperate to maximize mutual benefit.

---- Plan ---
Goals: Achieve best outcome
Milestones: → decision made

---- Action ---
<Action name="cooperate" />

That is ALL. No other text after Action tag.
"""

    return prompt


# ============================================================================
# Generic Prompt Builder
# ============================================================================

def build_prompt(
    scenario: ScenarioConfig,
    agent: AgentProfile,
    use_simple: bool = True,
    format_type: str = "json",
) -> str:
    """
    Build system prompt with automatic selection based on model size and format.

    For small models (3B-4B), use simplified prompts.
    For larger models (7B+), use full prompts.

    Args:
        scenario: The scenario configuration
        agent: The agent profile
        use_simple: Whether to use simplified prompt (default: True)
        format_type: Format type ("json", "xml", "text")

    Returns:
        System prompt string
    """
    # If using format-specific prompts, use those
    if format_type in PROMPT_BUILDERS:
        return build_prompt_by_format(scenario, agent, format_type)

    # Otherwise, fall back to simple/full prompts
    if use_simple:
        return build_simple_prompt(scenario, agent)
    return build_full_prompt(scenario, agent)


# ============================================================================
# Prompt Length Analysis
# ============================================================================

def count_words(prompt: str) -> int:
    """Count the number of words in a prompt."""
    return len(prompt.split())


def analyze_prompt_length(prompt: str) -> dict:
    """
    Analyze prompt length and provide recommendations.

    Returns:
        Dict with word count, token estimate, and recommendation
    """
    words = count_words(prompt)

    # Rough token estimate (1 token ≈ 0.75 words for English)
    tokens = int(words / 0.75)

    recommendation = "good"
    if words > 100:
        recommendation = "too_long"
    elif words > 60:
        recommendation = "acceptable"
    elif words < 20:
        recommendation = "too_short"

    return {
        "word_count": words,
        "estimated_tokens": tokens,
        "recommendation": recommendation,
    }


# ============================================================================
# Pre-Built Prompts for Quick Testing
# ============================================================================

# Test prompts for prompt length experiments
PROMPT_LENGTH_TESTS = {
    "minimal_20": (
        "You are Agent. Choose action: "
        '"cooperate" or "defect". '
        'Respond with {"action": "name"}'
    ),  # ~17 words
    "standard_40": (
        "You are Agent. Your role is to make strategic decisions. "
        'Available actions: "cooperate", "defect". '
        'Respond with JSON: {"action": "action_name"}'
    ),  # ~23 words
    "detailed_60": (
        "You are Agent. Consider the options carefully. "
        'Available actions: "cooperate", "defect". '
        'Think about your choice. '
        'Respond with JSON: {"action": "action_name"}'
    ),  # ~28 words
}


def get_prompt_by_length(
    scenario: ScenarioConfig,
    agent: AgentProfile,
    length: str = "standard_40",
    format_type: str = "json",
) -> str:
    """
    Get a prompt of specified length category.

    Args:
        scenario: The scenario configuration
        agent: The agent profile
        length: One of "minimal_20", "standard_40", "detailed_60"
        format_type: Format type ("json", "xml", "text")

    Returns:
        Prompt string of specified length
    """
    # Build action list string
    action_list = ", ".join(f'"{a.name}"' for a in scenario.actions)

    if length == "minimal_20":
        if format_type == "json":
            return f'You are {agent.name}. Choose: {action_list}. Respond with {{"action": "name"}}'
        elif format_type == "xml":
            first = scenario.actions[0].name if scenario.actions else "action"
            return f'You are {agent.name}. Choose: {action_list}. Respond with <Action name="{first}" />'
        else:  # text
            return f'You are {agent.name}. Choose: {action_list}. Respond with action name.'

    elif length == "detailed_60":
        if format_type == "json":
            return f"""You are {agent.name}. {agent.role_prompt}

Consider your options carefully.
Available actions: {action_list}

Think about your choice.
Respond with JSON: {{"action": "action_name"}}"""
        elif format_type == "xml":
            first = scenario.actions[0].name if scenario.actions else "action"
            return f"""You are {agent.name}. {agent.role_prompt}

Consider your options carefully.
Available actions: {action_list}

Think about your choice.
Respond with: <Action name="{first}" />"""
        else:  # text
            return f"""You are {agent.name}. {agent.role_prompt}

Consider your options carefully.
Available actions: {action_list}

Think about your choice.
Respond with action name only."""

    else:  # standard_40 (default)
        if format_type == "json":
            return f"""You are {agent.name}. {agent.role_prompt}

Available actions: {action_list}

Respond with JSON: {{"action": "action_name"}}"""
        elif format_type == "xml":
            first = scenario.actions[0].name if scenario.actions else "action"
            return f"""You are {agent.name}. {agent.role_prompt}

Available actions: {action_list}

Respond with: <Action name="{first}" />"""
        else:  # text
            return f"""You are {agent.name}. {agent.role_prompt}

Available actions: {action_list}

Respond with action name only."""
