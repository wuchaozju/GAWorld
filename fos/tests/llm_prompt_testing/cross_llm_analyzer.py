"""
Cross-LLM analysis for prompt testing.

Analyzes results across multiple models to determine prompt portability
and identify model-specific capabilities and limitations.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List

from .csv_reporter import TestResult

logger = logging.getLogger(__name__)


# ============================================================================
# Cross-LLM Analysis Data Structures
# ============================================================================

@dataclass
class ModelPerformance:
    """Performance metrics for a single model."""

    model_name: str
    total_runs: int = 0
    perfect_runs: int = 0
    xml_valid_count: int = 0
    action_correct_count: int = 0
    role_aligned_count: int = 0
    no_errors_count: int = 0
    _avg_score: float = field(default=0.0, init=False, repr=False)

    @property
    def pass_rate(self) -> float:
        """Percentage of perfect runs."""
        if self.total_runs == 0:
            return 0.0
        return (self.perfect_runs / self.total_runs) * 100

    @property
    def average_score(self) -> float:
        """Average score (0-4)."""
        if self.total_runs == 0:
            return 0.0
        return self._avg_score


@dataclass
class CrossLLMAnalysis:
    """Analysis of results across multiple models."""

    scenario: str
    pattern: str
    model_performances: Dict[str, ModelPerformance] = field(default_factory=dict)
    pass_count: int = 0  # Number of models passing
    total_models: int = 0
    overall_status: str = "UNKNOWN"  # "PASS", "FAIL"
    failure_analysis: Dict[str, List[str]] = field(default_factory=dict)
    recommendation: str = ""


@dataclass
class ModelCapabilityProfile:
    """Capability profile for a model across all patterns."""

    model_name: str
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    overall_pass_rate: float = 0.0
    pattern_performance: Dict[str, float] = field(default_factory=dict)


# ============================================================================
# Cross-LLM Analysis Functions
# ============================================================================

def analyze_model_results(results: List[TestResult]) -> ModelPerformance:
    """
    Analyze results for a single model.

    Args:
        results: List of test results for a single model

    Returns:
        ModelPerformance with metrics
    """
    if not results:
        return ModelPerformance(model_name="unknown")

    model_name = results[0].model
    avg_score = sum(r.overall_score for r in results) / len(results)
    performance = ModelPerformance(model_name=model_name)
    performance.total_runs = len(results)
    performance._avg_score = avg_score

    for result in results:
        if result.overall_score == 4:
            performance.perfect_runs += 1
        if result.xml_valid:
            performance.xml_valid_count += 1
        if result.action_correct:
            performance.action_correct_count += 1
        if result.role_aligned:
            performance.role_aligned_count += 1
        if result.no_errors:
            performance.no_errors_count += 1

    return performance


def analyze_cross_llm(
    results_by_model: Dict[str, List[TestResult]],
    min_pass_count: int = 2,
) -> CrossLLMAnalysis:
    """
    Analyze results across multiple models for a scenario.

    Args:
        results_by_model: Dict mapping model name to list of results
        min_pass_count: Minimum number of models that must pass (default: 2)

    Returns:
        CrossLLMAnalysis with cross-model evaluation
    """
    if not results_by_model:
        return CrossLLMAnalysis(scenario="", pattern="")

    # Get scenario/pattern from first result
    first_result = next(iter(results_by_model.values()))[0]
    scenario = first_result.scenario
    pattern = first_result.pattern

    analysis = CrossLLMAnalysis(
        scenario=scenario,
        pattern=pattern,
        total_models=len(results_by_model),
    )

    # Analyze each model
    perfect_count = 0
    for model_name, results in results_by_model.items():
        if not results:
            continue

        performance = analyze_model_results(results)
        analysis.model_performances[model_name] = performance

        # A model "passes" if more than 50% of its runs are perfect
        if performance.pass_rate >= 50:
            perfect_count += 1
        else:
            # Analyze why this model failed
            failures = []
            for result in results:
                if result.overall_score < 4:
                    failures.extend(result.failure_reasons)
            analysis.failure_analysis[model_name] = list(set(failures))

    analysis.pass_count = perfect_count
    analysis.overall_status = "PASS" if perfect_count >= min_pass_count else "FAIL"

    # Generate recommendation
    if analysis.overall_status == "PASS":
        if perfect_count == analysis.total_models:
            analysis.recommendation = "Excellent! All models perform well with this prompt."
        else:
            failing_models = [m for m, p in analysis.model_performances.items() if p.pass_rate < 50]
            analysis.recommendation = (
                f"Prompt is portable (2/3+ models pass). "
                f"Failing model(s): {', '.join(failing_models)}. "
                f"This may indicate model capability limitations rather than prompt issues."
            )
    else:
        analysis.recommendation = (
            f"Prompt needs improvement - only {perfect_count}/{analysis.total_models} models pass. "
            "Focus on portability across models."
        )

    return analysis


def apply_cross_llm_status(
    results: List[TestResult],
    min_pass_count: int = 2,
) -> None:
    """
    Apply cross-LLM status to test results in-place.

    Organizes results by model, analyzes cross-LLM performance,
    and updates each result's cross_llm_status field.

    Args:
        results: List of all test results for a scenario
        min_pass_count: Minimum number of models that must pass
    """
    # Group results by model
    results_by_model: Dict[str, List[TestResult]] = {}
    for result in results:
        if result.model not in results_by_model:
            results_by_model[result.model] = []
        results_by_model[result.model].append(result)

    # Analyze cross-LLM
    analysis = analyze_cross_llm(results_by_model, min_pass_count)

    # Update each result
    for model_name, model_results in results_by_model.items():
        performance = analysis.model_performances.get(model_name)
        if not performance:
            continue

        # Determine if this specific model instance passes
        model_passes = performance.pass_rate >= 50

        for result in model_results:
            result.cross_llm_status = "PASS" if analysis.overall_status == "PASS" else "FAIL"

            if not model_passes and analysis.failure_analysis.get(model_name):
                result.model_failure_reason = "; ".join(analysis.failure_analysis[model_name][:3])


# ============================================================================
# Model Capability Profiling
# ============================================================================

def build_model_capability_profiles(
    all_results: List[TestResult],
) -> Dict[str, ModelCapabilityProfile]:
    """
    Build capability profiles for each model across all tested patterns.

    Args:
        all_results: All test results across all scenarios

    Returns:
        Dict mapping model name to ModelCapabilityProfile
    """
    profiles: Dict[str, ModelCapabilityProfile] = {}

    # Group by model
    results_by_model: Dict[str, List[TestResult]] = {}
    for result in all_results:
        if result.model not in results_by_model:
            results_by_model[result.model] = []
        results_by_model[result.model].append(result)

    # Analyze each model
    for model_name, model_results in results_by_model.items():
        profile = ModelCapabilityProfile(model_name=model_name)

        # Overall pass rate
        perfect = sum(1 for r in model_results if r.overall_score == 4)
        profile.overall_pass_rate = (perfect / len(model_results) * 100) if model_results else 0

        # Performance by pattern
        results_by_pattern: Dict[str, List[TestResult]] = {}
        for result in model_results:
            if result.pattern not in results_by_pattern:
                results_by_pattern[result.pattern] = []
            results_by_pattern[result.pattern].append(result)

        for pattern, pattern_results in results_by_pattern.items():
            pattern_perfect = sum(1 for r in pattern_results if r.overall_score == 4)
            pattern_rate = (pattern_perfect / len(pattern_results) * 100) if pattern_results else 0
            profile.pattern_performance[pattern] = pattern_rate

            # Identify strengths (80%+ pass rate) and weaknesses (<50% pass rate)
            if pattern_rate >= 80:
                profile.strengths.append(pattern)
            elif pattern_rate < 50:
                profile.weaknesses.append(pattern)

        profiles[model_name] = profile

    return profiles


# ============================================================================
# Summary Reporting
# ============================================================================

def generate_capability_matrix(
    profiles: Dict[str, ModelCapabilityProfile],
    patterns: List[str],
) -> str:
    """
    Generate a markdown table showing model capabilities by pattern.

    Args:
        profiles: Model capability profiles
        patterns: List of all patterns

    Returns:
        Markdown table string
    """
    lines = [
        "\n## Model Capability Matrix\n",
        "| Pattern | " + " | ".join(p.model_name for p in profiles.values()) + " |",
        "|" * (100),  # Separator line
    ]

    for pattern in patterns:
        row = f"| {pattern} |"
        for profile in profiles.values():
            rate = profile.pattern_performance.get(pattern, 0)
            status = "✓" if rate >= 80 else "~" if rate >= 50 else "✗"
            row += f" {rate:.0f}% {status} |"
        lines.append(row)

    return "\n".join(lines)


def generate_model_recommendations(
    profiles: Dict[str, ModelCapabilityProfile],
) -> str:
    """Generate recommendations for each model."""
    lines = ["\n## Model-Specific Recommendations\n"]

    for profile in profiles.values():
        lines.append(f"### {profile.model_name}")
        lines.append(f"**Overall Pass Rate**: {profile.overall_pass_rate:.1f}%\n")

        if profile.strengths:
            lines.append("**Strengths**:")
            for strength in profile.strengths:
                rate = profile.pattern_performance.get(strength, 0)
                lines.append(f"  - {strength}: {rate:.0f}%")
            lines.append("")

        if profile.weaknesses:
            lines.append("**Weaknesses**:")
            for weakness in profile.weaknesses:
                rate = profile.pattern_performance.get(weakness, 0)
                lines.append(f"  - {weakness}: {rate:.0f}%")
            lines.append("")

        # Generate recommendation
        if profile.overall_pass_rate >= 80:
            rec = "This model performs well overall and is recommended for all scenarios."
        elif profile.overall_pass_rate >= 50:
            rec = "This model performs adequately but may struggle with some scenarios."
        else:
            rec = "This model has significant limitations. Consider using alternative models."

        lines.append(f"**Recommendation**: {rec}\n")

    return "\n".join(lines)
