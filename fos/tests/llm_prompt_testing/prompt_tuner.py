"""
Automated prompt improvement for LLM prompt testing.

Analyzes test failures and generates improved prompts with better
instructions, examples, and formatting.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .agents import AgentProfile
from .evaluators import EvaluationResult
from .scenarios import ScenarioConfig

logger = logging.getLogger(__name__)


@dataclass
class PromptVersion:
    """A version of a prompt with metadata."""

    version_id: int
    prompt_text: str
    changes_from_previous: str = ""
    timestamp: str = ""


@dataclass
class PromptImprovement:
    """Suggested improvements to a prompt."""

    new_prompt: str
    changes_made: List[str] = field(default_factory=list)
    rationale: str = ""


# ============================================================================
# Failure Analysis
# ============================================================================

def analyze_failure_pattern(results: List[EvaluationResult]) -> Dict[str, int]:
    """
    Analyze patterns in evaluation failures.

    Args:
        results: List of evaluation results to analyze

    Returns:
        Dict mapping failure type to count
    """
    failures = {
        "xml_format": 0,
        "action": 0,
        "role": 0,
        "errors": 0,
    }

    for result in results:
        if not result.xml_valid:
            failures["xml_format"] += 1
        if not result.action_correct:
            failures["action"] += 1
        if not result.role_aligned:
            failures["role"] += 1
        if not result.no_errors:
            failures["errors"] += 1

    return failures


def identify_primary_failure(results: List[EvaluationResult]) -> Optional[str]:
    """Identify the most common failure type."""
    failures = analyze_failure_pattern(results)
    max_count = 0
    primary = None

    for failure_type, count in failures.items():
        if count > max_count:
            max_count = count
            primary = failure_type

    return primary


# ============================================================================
# Prompt Improvement Strategies
# ============================================================================

def improve_xml_format(
    prompt: str,
    results: List[EvaluationResult],
) -> PromptImprovement:
    """
    Improve prompt to fix XML format issues.

    Strategies:
    - Add clearer format instructions
    - Add XML examples
    - Emphasize exact format requirements
    """
    changes = []
    new_prompt = prompt

    # Check if examples already exist
    if "Example:" not in prompt and "example:" not in prompt:
        example = """

Example output format:
--- Thoughts ---
I am considering my options...

---- Plan ---
Goals: [your goals]
Milestones: [completed ✓, pending →]

---- Action ---
<Action name="action_name">
  parameter="value"
</Action>"""
        new_prompt += example
        changes.append("Added XML format example")

    # Emphasize format if failures persist
    if any("Missing" in r.error_message for r in results if r.error_message):
        emphasis = "\n\nIMPORTANT: You must use EXACTLY this format with these headers:"
        new_prompt = emphasis + "\n" + new_prompt
        changes.append("Added emphasis on exact format requirements")

    return PromptImprovement(
        new_prompt=new_prompt,
        changes_made=changes,
        rationale="XML format issues detected - added examples and emphasis",
    )


def improve_action_clarity(
    prompt: str,
    results: List[EvaluationResult],
    scenario: ScenarioConfig,
) -> PromptImprovement:
    """
    Improve prompt to fix action-related issues.

    Strategies:
    - Clarify available actions
    - Add action constraints
    - Emphasize valid action names
    """
    changes = []
    new_prompt = prompt

    # Add action list if not present
    if scenario.actions and "Available Actions:" not in new_prompt:
        actions_text = "\n\nAvailable Actions:\n"
        for action in scenario.actions:
            actions_text += f"  - {action.name}: {action.description}\n"

        # Insert before output format
        if "---- Action ---" in new_prompt or "output" in new_prompt.lower():
            # Find position to insert
            insert_pos = new_prompt.lower().find("output")
            if insert_pos == -1:
                insert_pos = len(new_prompt)
            new_prompt = new_prompt[:insert_pos] + actions_text + "\n" + new_prompt[insert_pos:]
            changes.append("Added list of available actions")

    # Emphasize exact action names
    if scenario.actions:
        action_names = ", ".join(f'"{a.name}"' for a in scenario.actions)
        emphasis = f"\n\nIMPORTANT: You must use EXACTLY these action names: {action_names}"
        new_prompt += emphasis
        changes.append("Emphasized exact action names")

    return PromptImprovement(
        new_prompt=new_prompt,
        changes_made=changes,
        rationale="Action issues detected - clarified available actions",
    )


def improve_role_instructions(
    prompt: str,
    results: List[EvaluationResult],
    agent: AgentProfile,
) -> PromptImprovement:
    """
    Improve prompt to fix role alignment issues.

    Strategies:
    - Strengthen role instructions
    - Add personality guidance
    - Emphasize staying in character
    """
    changes = []
    new_prompt = prompt

    # Check if role is well-defined
    role_section = f"\n\nYour Role: {agent.name}\n"
    role_section += f"Personality: {agent.personality}\n"
    role_section += f"Style: {agent.style}\n"

    if "Your Role:" not in new_prompt:
        # Add role section at the beginning
        new_prompt = role_section + new_prompt
        changes.append("Added explicit role section")
    else:
        # Strengthen existing role section
        emphasis = f"\nREMAIN IN CHARACTER as {agent.name}. Your responses should reflect your {agent.personality} personality."
        new_prompt += emphasis
        changes.append("Strengthened role instructions")

    return PromptImprovement(
        new_prompt=new_prompt,
        changes_made=changes,
        rationale="Role alignment issues detected - strengthened role instructions",
    )


def improve_error_prevention(
    prompt: str,
    results: List[EvaluationResult],
) -> PromptImprovement:
    """
    Improve prompt to prevent errors and hallucinations.

    Strategies:
    - Add negative constraints
    - Clarify what NOT to do
    - Remove AI self-reference triggers
    """
    changes = []
    new_prompt = prompt

    negative_instructions = """

Important constraints:
- Do NOT say "I cannot" or "I'm unable" - you must always take an action
- Do NOT mention being an AI, language model, or assistant
- Do NOT apologize for your responses
- Stay in character and respond as the agent you are playing
- Always provide a valid action from the available options
"""

    if "Do NOT say" not in new_prompt:
        new_prompt += negative_instructions
        changes.append("Added negative constraints to prevent errors")

    return PromptImprovement(
        new_prompt=new_prompt,
        changes_made=changes,
        rationale="Error/hallucination issues detected - added constraints",
    )


def improve_for_model(
    prompt: str,
    model: str,
) -> PromptImprovement:
    """
    Improve prompt for a specific model's characteristics.

    Different models may need different prompting styles.
    """
    changes = []
    new_prompt = prompt

    # Model-specific adjustments
    if "qwen" in model.lower():
        # Qwen may benefit from more explicit instructions
        if "Remember:" not in new_prompt:
            new_prompt += "\n\nRemember: Follow the format exactly."
            changes.append("Added explicit reminder for Qwen model")

    elif "gemma" in model.lower():
        # Gemma may benefit from examples
        if "For example:" not in new_prompt and "Example:" not in new_prompt:
            example = "\n\nFor example, if you choose to cooperate:\n---- Action ---\n<Action name=\"cooperate\" />"
            new_prompt += example
            changes.append("Added example for Gemma model")

    elif "ministral" in model.lower() or "mistral" in model.lower():
        # Mistral models generally follow instructions well
        # May benefit from concise prompts
        pass

    return PromptImprovement(
        new_prompt=new_prompt,
        changes_made=changes,
        rationale=f"Adjusted prompt for {model} model characteristics",
    )


# ============================================================================
# Main Prompt Tuner
# ============================================================================

class PromptTuner:
    """
    Automated prompt improvement system.

    Analyzes failures and applies targeted improvements.
    """

    def __init__(self):
        """Initialize the prompt tuner."""
        self.version_history: List[PromptVersion] = []
        self.current_version = 0

    def tune_prompt(
        self,
        current_prompt: str,
        results: List[EvaluationResult],
        scenario: ScenarioConfig,
        agent: AgentProfile,
        model: str,
    ) -> PromptImprovement:
        """
        Analyze results and generate an improved prompt.

        Args:
            current_prompt: The current prompt being used
            results: Evaluation results from the current iteration
            scenario: The scenario being tested
            agent: The agent profile being used
            model: The model being tested

        Returns:
            PromptImprovement with the new prompt and changes
        """
        primary_failure = identify_primary_failure(results)

        if not primary_failure:
            # No clear failure pattern, apply general improvements
            return self._general_improvement(current_prompt, model)

        # Apply targeted improvement based on failure type
        if primary_failure == "xml_format":
            improvement = improve_xml_format(current_prompt, results)
        elif primary_failure == "action":
            improvement = improve_action_clarity(current_prompt, results, scenario)
        elif primary_failure == "role":
            improvement = improve_role_instructions(current_prompt, results, agent)
        elif primary_failure == "errors":
            improvement = improve_error_prevention(current_prompt, results)
        else:
            improvement = self._general_improvement(current_prompt, model)

        # Apply model-specific adjustments
        model_improvement = improve_for_model(improvement.new_prompt, model)
        improvement.new_prompt = model_improvement.new_prompt
        improvement.changes_made.extend(model_improvement.changes_made)

        # Update version history
        self.current_version += 1
        self.version_history.append(
            PromptVersion(
                version_id=self.current_version,
                prompt_text=improvement.new_prompt,
                changes_from_previous="; ".join(improvement.changes_made),
            )
        )

        return improvement

    def _general_improvement(self, prompt: str, model: str) -> PromptImprovement:
        """Apply general improvements when no specific failure is identified."""
        new_prompt = prompt
        changes = []

        # Ensure format instructions are clear
        if "--- Thoughts ---" not in new_prompt:
            format_section = """

Output Format (follow exactly):
--- Thoughts ---
[your thinking]

---- Plan ---
Goals: [your goals]
Milestones: [what's completed, what's pending]

---- Action ---
<Action name="action_name">
  parameter="value"
</Action>"""
            new_prompt += format_section
            changes.append("Added output format instructions")

        # Apply model-specific adjustments
        model_improvement = improve_for_model(new_prompt, model)
        new_prompt = model_improvement.new_prompt
        changes.extend(model_improvement.changes_made)

        return PromptImprovement(
            new_prompt=new_prompt,
            changes_made=changes,
            rationale="General improvements applied",
        )

    def get_version(self, version_id: int) -> Optional[PromptVersion]:
        """Get a specific prompt version."""
        for v in self.version_history:
            if v.version_id == version_id:
                return v
        return None

    def rollback(self, to_version: int) -> Optional[str]:
        """Rollback to a previous prompt version."""
        version = self.get_version(to_version)
        if version:
            self.current_version = version.version_id
            return version.prompt_text
        return None


# Global tuner instance
default_tuner = PromptTuner()
