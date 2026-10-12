"""
Output evaluation logic for LLM prompt testing.

Provides flexible evaluation with multi-format support:
- JSON/XML/Plain text format parsing
- Action correctness checking
- Role alignment evaluation
- Error/hallucination detection
- Scoring system instead of strict pass/fail
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .action_parser import parse_action, ParseResult
from .agents import AgentProfile
from .scenarios import ScenarioConfig

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    """Result of evaluating an LLM output with flexible scoring."""

    # Core metrics
    action_extracted: bool  # Successfully extracted an action
    action_valid: bool  # Action matches valid list
    format_score: int  # 0-2 (JSON=2, XML=1, text=0)

    # Additional quality metrics
    role_aligned: bool
    no_errors: bool

    # Tracking
    parsed_action: Optional[str] = None
    parse_method: str = "failed"  # "json", "xml", "text", "keyword", "failed"
    raw_output: str = ""
    raw_output_preview: str = ""  # First 200 chars

    # Computed
    overall_success: bool = False  # Met minimum criteria (action extracted + valid)
    failure_reasons: List[str] = field(default_factory=list)

    @property
    def is_perfect(self) -> bool:
        """Check if all criteria passed with good format."""
        return (
            self.action_extracted
            and self.action_valid
            and self.role_aligned
            and self.no_errors
            and self.format_score >= 1
        )

    @property
    def quality_score(self) -> float:
        """Calculate quality score (0-100)."""
        score = 0.0

        # Action extraction is most important (40 points)
        if self.action_extracted:
            score += 40

        # Action validity (30 points)
        if self.action_valid:
            score += 30

        # Format quality (15 points)
        score += (self.format_score / 2) * 15

        # Role alignment (10 points)
        if self.role_aligned:
            score += 10

        # No errors (5 points)
        if self.no_errors:
            score += 5

        return score

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "action_extracted": self.action_extracted,
            "action_valid": self.action_valid,
            "format_score": self.format_score,
            "role_aligned": self.role_aligned,
            "no_errors": self.no_errors,
            "parsed_action": self.parsed_action,
            "parse_method": self.parse_method,
            "overall_success": self.overall_success,
            "quality_score": self.quality_score,
            "is_perfect": self.is_perfect,
            "raw_output_preview": self.raw_output_preview,
            "failure_reasons": self.failure_reasons,
        }


# ============================================================================
# Action Extraction with Multi-Format Parser
# ============================================================================

def extract_action_from_output(
    output: str,
    valid_actions: List[str],
) -> ParseResult:
    """
    Extract action from output using the multi-format parser.

    Args:
        output: The LLM output
        valid_actions: List of valid action names

    Returns:
        ParseResult with action details
    """
    if not valid_actions:
        return ParseResult(
            success=False,
            action=None,
            parse_method="failed",
            format_score=0,
            raw_output=output,
            error_message="No valid actions provided",
        )

    return parse_action(output, valid_actions)


# ============================================================================
# Role Alignment Evaluation
# ============================================================================

def check_role_alignment(
    output: str,
    agent: AgentProfile,
    scenario: ScenarioConfig,
) -> Tuple[bool, List[str]]:
    """
    Check if the output aligns with the agent's role and personality.

    This is a heuristic check - we look for keywords and tone consistency.

    Args:
        output: The LLM output
        agent: The agent profile
        scenario: The scenario configuration

    Returns:
        Tuple of (is_aligned, failure_reasons)
    """
    failures = []
    output_lower = output.lower()

    # Check for personality traits in output
    personality_keywords = {
        "decisive": ["decide", "choose", "will", "must"],
        "critical": ["question", "why", "however", "but", "concern"],
        "cooperative": ["agree", "support", "together", "we", "us"],
        "logical": ["because", "therefore", "analyze", "data", "evidence"],
        "diplomatic": ["understand", "respect", "compromise", "middle"],
        "practical": ["do", "work", "need", "real", "actual"],
        "vigilant": ["watch", "check", "ensure", "protect", "careful"],
    }

    # Get personality keywords
    agent_personality = agent.personality.lower()
    found_personality_keywords = 0

    for trait, keywords in personality_keywords.items():
        if trait in agent_personality:
            if any(kw in output_lower for kw in keywords):
                found_personality_keywords += 1

    # Basic check: if the output is empty or too short, fail
    if len(output.strip()) < 10:
        failures.append("Output too short to assess role alignment")

    # If the output mentions contradictory stances, note it
    if "i don't know" in output_lower and "decisive" in agent_personality:
        failures.append("Agent claims indecision despite being decisive")

    # Check for AI self-reference (breaks character)
    ai_phrases = ["as an ai", "as a language model", "i am an ai"]
    if any(phrase in output_lower for phrase in ai_phrases):
        failures.append("AI self-reference detected (breaks character)")

    is_aligned = len(failures) == 0
    return is_aligned, failures


# ============================================================================
# Error and Hallucination Detection
# ============================================================================

def check_errors_and_hallucinations(
    output: str,
    scenario: ScenarioConfig,
    agent: AgentProfile,
) -> Tuple[bool, str]:
    """
    Check for errors and hallucinations in the output.

    Args:
        output: The LLM output
        scenario: The scenario configuration
        agent: The agent profile

    Returns:
        Tuple of (no_errors, error_message)
    """
    output_lower = output.lower()

    # Check for common error indicators
    error_patterns = [
        ("i cannot", "Agent refuses to act"),
        ("i'm unable", "Agent indicates inability"),
        ("i apologize but", "Agent apologizes for inability"),
        ("<error>", "Error tag in output"),
    ]

    for pattern, description in error_patterns:
        if pattern in output_lower:
            return False, f"Potential issue: {description}"

    return True, ""


# ============================================================================
# Main Evaluation Function
# ============================================================================

def evaluate_output(
    output: str,
    scenario: ScenarioConfig,
    agent: AgentProfile,
    valid_actions: Optional[List[str]] = None,
) -> EvaluationResult:
    """
    Evaluate an LLM output with flexible multi-format parsing.

    Args:
        output: The LLM output to evaluate
        scenario: The scenario that was tested
        agent: The agent profile that was used
        valid_actions: List of valid action names (defaults to scenario.actions)

    Returns:
        EvaluationResult with all evaluation details
    """
    # Get valid actions
    if valid_actions is None:
        valid_actions = [a.name for a in scenario.actions]

    # Initialize result
    result = EvaluationResult(
        action_extracted=False,
        action_valid=False,
        format_score=0,
        role_aligned=False,
        no_errors=False,
        raw_output=output,
        raw_output_preview=output[:200] if len(output) > 200 else output,
    )

    # 1. Extract action using multi-format parser
    parse_result = extract_action_from_output(output, valid_actions)

    result.action_extracted = parse_result.success
    result.parsed_action = parse_result.action
    result.parse_method = parse_result.parse_method
    result.format_score = parse_result.format_score

    if not parse_result.success:
        result.failure_reasons.append(f"Action extraction: {parse_result.error_message}")
        # Return early since action extraction failed
        result.overall_success = False
        return result

    # 2. Validate action against allowed actions
    # The parser already validates, but let's double-check
    is_valid_action = parse_result.action in valid_actions
    result.action_valid = is_valid_action

    if not is_valid_action:
        result.failure_reasons.append(
            f"Invalid action '{parse_result.action}'. Valid: {valid_actions}"
        )
    else:
        result.failure_reasons.append(f"Action '{parse_result.action}' extracted via {parse_result.parse_method}")

    # 3. Check role alignment
    role_aligned, role_failures = check_role_alignment(output, agent, scenario)
    result.role_aligned = role_aligned
    if not role_aligned:
        result.failure_reasons.extend([f"Role: {f}" for f in role_failures])

    # 4. Check for errors/hallucinations
    no_errors, error_msg = check_errors_and_hallucinations(output, scenario, agent)
    result.no_errors = no_errors
    if not no_errors:
        result.failure_reasons.append(f"Errors: {error_msg}")

    # 5. Determine overall success
    # Minimum criteria: action extracted AND valid
    result.overall_success = result.action_extracted and result.action_valid

    return result


# ============================================================================
# Batch Evaluation
# ============================================================================

@dataclass
class BatchEvaluationSummary:
    """Summary of evaluating multiple outputs."""

    total_evaluations: int = 0
    successful_parses: int = 0  # Extracted any action
    valid_actions: int = 0  # Extracted valid action
    perfect_count: int = 0  # All criteria passed with good format
    role_aligned_count: int = 0
    no_errors_count: int = 0
    average_quality_score: float = 0.0
    average_format_score: float = 0.0

    # Parse method distribution
    json_count: int = 0
    xml_count: int = 0
    text_count: int = 0
    keyword_count: int = 0
    failed_count: int = 0

    # Action distribution
    action_distribution: Dict[str, int] = field(default_factory=dict)

    @property
    def extraction_rate(self) -> float:
        """Percentage of outputs where action was extracted."""
        if self.total_evaluations == 0:
            return 0.0
        return (self.successful_parses / self.total_evaluations) * 100

    @property
    def validity_rate(self) -> float:
        """Percentage of outputs with valid actions."""
        if self.total_evaluations == 0:
            return 0.0
        return (self.valid_actions / self.total_evaluations) * 100

    @property
    def pass_rate(self) -> float:
        """Percentage of perfect outputs."""
        if self.total_evaluations == 0:
            return 0.0
        return (self.perfect_count / self.total_evaluations) * 100


def evaluate_batch(
    outputs: List[str],
    scenario: ScenarioConfig,
    agent: AgentProfile,
    valid_actions: Optional[List[str]] = None,
) -> Tuple[List[EvaluationResult], BatchEvaluationSummary]:
    """
    Evaluate multiple outputs.

    Args:
        outputs: List of LLM outputs
        scenario: The scenario that was tested
        agent: The agent profile that was used
        valid_actions: List of valid action names

    Returns:
        Tuple of (list of EvaluationResult, BatchEvaluationSummary)
    """
    if valid_actions is None:
        valid_actions = [a.name for a in scenario.actions]

    results = []
    summary = BatchEvaluationSummary(total_evaluations=len(outputs))

    for output in outputs:
        result = evaluate_output(output, scenario, agent, valid_actions)
        results.append(result)

        # Update summary stats
        if result.action_extracted:
            summary.successful_parses += 1

        if result.action_valid:
            summary.valid_actions += 1

        if result.is_perfect:
            summary.perfect_count += 1

        if result.role_aligned:
            summary.role_aligned_count += 1

        if result.no_errors:
            summary.no_errors_count += 1

        # Count parse methods
        if result.parse_method == "json":
            summary.json_count += 1
        elif result.parse_method == "xml":
            summary.xml_count += 1
        elif result.parse_method == "text":
            summary.text_count += 1
        elif result.parse_method == "keyword":
            summary.keyword_count += 1
        else:
            summary.failed_count += 1

        # Accumulate scores
        summary.average_quality_score += result.quality_score
        summary.average_format_score += result.format_score

        # Track action distribution
        if result.parsed_action:
            summary.action_distribution[result.parsed_action] = (
                summary.action_distribution.get(result.parsed_action, 0) + 1
            )

    # Calculate averages
    if summary.total_evaluations > 0:
        summary.average_quality_score /= summary.total_evaluations
        summary.average_format_score /= summary.total_evaluations

    return results, summary


# ============================================================================
# Format-Specific Evaluation
# ============================================================================

@dataclass
class FormatTestResult:
    """Result of testing a specific format with a specific model."""

    model_name: str
    format_type: str  # "json", "xml", "text"
    total_runs: int = 0
    successful_extractions: int = 0
    valid_actions: int = 0
    average_quality_score: float = 0.0
    average_format_score: float = 0.0
    success_rate: float = 0.0  # Percentage of valid action extractions
    meets_target: bool = False  # Meets 85% target

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "model_name": self.model_name,
            "format_type": self.format_type,
            "total_runs": self.total_runs,
            "successful_extractions": self.successful_extractions,
            "valid_actions": self.valid_actions,
            "average_quality_score": self.average_quality_score,
            "average_format_score": self.average_format_score,
            "success_rate": self.success_rate,
            "meets_target": self.meets_target,
        }


def evaluate_format_test(
    model_name: str,
    format_type: str,
    outputs: List[str],
    scenario: ScenarioConfig,
    agent: AgentProfile,
    target_rate: float = 0.85,
) -> FormatTestResult:
    """
    Evaluate the results of testing a specific format.

    Args:
        model_name: Name of the model tested
        format_type: Format type ("json", "xml", "text")
        outputs: List of LLM outputs
        scenario: The scenario tested
        agent: The agent profile used
        target_rate: Target success rate (default 0.85 = 85%)

    Returns:
        FormatTestResult with summary statistics
    """
    results, summary = evaluate_batch(outputs, scenario, agent)

    result = FormatTestResult(
        model_name=model_name,
        format_type=format_type,
        total_runs=len(outputs),
        successful_extractions=summary.successful_parses,
        valid_actions=summary.valid_actions,
        average_quality_score=summary.average_quality_score,
        average_format_score=summary.average_format_score,
    )

    # Calculate success rate (valid action extractions / total runs)
    if result.total_runs > 0:
        result.success_rate = (result.valid_actions / result.total_runs) * 100

    # Check if meets target
    result.meets_target = result.success_rate >= (target_rate * 100)

    return result
