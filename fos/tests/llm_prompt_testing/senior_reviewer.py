"""
Senior reviewer agent for LLM prompt testing.

Reviews all test results from all patterns, synthesizes findings,
identifies issues, and generates actionable recommendations.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .config import INTERACTION_PATTERNS
from .csv_reporter import CSVReporter, TestResult
from .cross_llm_analyzer import (
    build_model_capability_profiles,
    ModelCapabilityProfile,
)


logger = logging.getLogger(__name__)


# ============================================================================
# Review Data Structures
# ============================================================================

@dataclass
class PatternReview:
    """Review summary for a single pattern."""

    pattern: str
    total_runs: int = 0
    perfect_runs: int = 0
    pass_rate: float = 0.0
    avg_score: float = 0.0
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    needs_attention: bool = False


@dataclass
class FinalReview:
    """Complete review of all test results."""

    pattern_reviews: Dict[str, PatternReview] = field(default_factory=dict)
    model_profiles: Dict[str, ModelCapabilityProfile] = field(default_factory=dict)
    overall_summary: str = ""
    critical_issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


# ============================================================================
# Pattern Review
# ============================================================================

def review_pattern(
    pattern: str,
    results: List[TestResult],
) -> PatternReview:
    """
    Review test results for a single pattern.

    Args:
        pattern: The interaction pattern name
        results: All test results for this pattern

    Returns:
        PatternReview with analysis and recommendations
    """
    review = PatternReview(pattern=pattern)
    review.total_runs = len(results)

    if not results:
        review.issues.append("No test results found")
        return review

    # Calculate metrics
    perfect = sum(1 for r in results if r.overall_score == 4)
    review.perfect_runs = perfect
    review.pass_rate = (perfect / len(results) * 100) if results else 0
    review.avg_score = sum(r.overall_score for r in results) / len(results)

    # Analyze failures
    failures = [r for r in results if r.overall_score < 4]
    if failures:
        # Count failure types
        xml_failures = sum(1 for r in failures if not r.xml_valid)
        action_failures = sum(1 for r in failures if not r.action_correct)
        role_failures = sum(1 for r in failures if not r.role_aligned)
        error_failures = sum(1 for r in failures if not r.no_errors)

        # Identify primary issues
        if xml_failures > len(failures) * 0.3:
            review.issues.append(
                f"XML format issues in {xml_failures}/{len(failures)} failures"
            )
            review.recommendations.append(
                "Improve XML format instructions with clearer examples"
            )

        if action_failures > len(failures) * 0.3:
            review.issues.append(
                f"Action issues in {action_failures}/{len(failures)} failures"
            )
            review.recommendations.append(
                "Clarify available actions and add usage examples"
            )

        if role_failures > len(failures) * 0.3:
            review.issues.append(
                f"Role alignment issues in {role_failures}/{len(failures)} failures"
            )
            review.recommendations.append(
                "Strengthen role instructions and personality guidance"
            )

        if error_failures > len(failures) * 0.3:
            review.issues.append(
                f"Error/hallucination issues in {error_failures}/{len(failures)} failures"
            )
            review.recommendations.append(
                "Add negative constraints to prevent AI self-reference"
            )

    # Check if pattern needs attention
    review.needs_attention = review.pass_rate < 80

    if review.needs_attention:
        review.recommendations.insert(
            0, f"PRIORITY: Review and improve prompts for {pattern} pattern"
        )

    return review


# ============================================================================
# Senior Reviewer
# ============================================================================

class SeniorReviewer:
    """
    Senior reviewer agent for comprehensive test result analysis.

    Reviews all CSV outputs, synthesizes findings, identifies issues,
    and generates actionable recommendations.
    """

    def __init__(self, results_dir: Optional[Path] = None):
        """
        Initialize the senior reviewer.

        Args:
            results_dir: Directory containing test results
        """
        self.results_dir = results_dir or Path("test_results")
        self.csv_reporter = CSVReporter(results_dir)
        self.review: Optional[FinalReview] = None

    def load_all_results(self) -> Dict[str, List[TestResult]]:
        """Load all test results from CSV files."""
        all_results: Dict[str, List[TestResult]] = {}

        for pattern in INTERACTION_PATTERNS:
            pattern_dir = (
                self.results_dir / pattern.replace(" & ", "_").replace(" ", "_").lower()
            )
            if not pattern_dir.exists():
                logger.warning(f"Pattern directory not found: {pattern_dir}")
                continue

            pattern_results: List[TestResult] = []
            for csv_file in pattern_dir.glob("*.csv"):
                scenario_results = self.csv_reporter.read_scenario_results(
                    pattern, csv_file.stem
                )
                pattern_results.extend(scenario_results)

            all_results[pattern] = pattern_results
            logger.info(f"Loaded {len(pattern_results)} results for {pattern}")

        return all_results

    def review_all(self) -> FinalReview:
        """
        Perform a comprehensive review of all test results.

        Returns:
            FinalReview with complete analysis
        """
        self.review = FinalReview()

        # Load all results
        all_results = self.load_all_results()

        if not all_results:
            self.review.overall_summary = "No test results found to review."
            return self.review

        # Review each pattern
        for pattern, results in all_results.items():
            pattern_review = review_pattern(pattern, results)
            self.review.pattern_reviews[pattern] = pattern_review

        # Build model capability profiles
        all_results_flat = []
        for results in all_results.values():
            all_results_flat.extend(results)

        self.review.model_profiles = build_model_capability_profiles(
            all_results_flat
        )

        # Generate overall summary
        self._generate_summary(all_results)

        # Identify critical issues
        self._identify_critical_issues()

        # Generate recommendations
        self._generate_recommendations()

        return self.review

    def _generate_summary(self, all_results: Dict[str, List[TestResult]]) -> None:
        """Generate overall summary statistics."""
        total_runs = sum(len(r) for r in all_results.values())
        total_perfect = sum(
            sum(1 for r in results if r.overall_score == 4)
            for results in all_results.values()
        )
        overall_pass_rate = (total_perfect / total_runs * 100) if total_runs else 0

        patterns_with_issues = sum(
            1 for pr in self.review.pattern_reviews.values() if pr.needs_attention
        )

        self.review.overall_summary = f"""
## Overall Summary

- **Total Test Runs**: {total_runs}
- **Perfect Runs**: {total_perfect} ({overall_pass_rate:.1f}%)
- **Patterns Tested**: {len(all_results)}
- **Patterns Needing Attention**: {patterns_with_issues}

### Status
"""

        if overall_pass_rate >= 90:
            self.review.overall_summary += "✅ Excellent - Most prompts are working well"
        elif overall_pass_rate >= 70:
            self.review.overall_summary += "⚠️ Good - Some improvements needed"
        else:
            self.review.overall_summary += "❌ Poor - Significant prompt improvements needed"

    def _identify_critical_issues(self) -> None:
        """Identify critical issues across all patterns."""
        self.review.critical_issues = []

        for pattern, review in self.review.pattern_reviews.items():
            if review.needs_attention:
                self.review.critical_issues.append(
                    f"{pattern}: Only {review.pass_rate:.0f}% pass rate"
                )
                self.review.critical_issues.extend(review.issues)

        # Check for model-specific issues
        for model, profile in self.review.model_profiles.items():
            if profile.overall_pass_rate < 50:
                self.review.critical_issues.append(
                    f"{model}: Very low pass rate ({profile.overall_pass_rate:.0f}%)"
                )
            elif profile.overall_pass_rate < 70:
                self.review.critical_issues.append(
                    f"{model}: Low pass rate ({profile.overall_pass_rate:.0f}%)"
                )

    def _generate_recommendations(self) -> None:
        """Generate actionable recommendations."""
        self.review.recommendations = []

        # Pattern-specific recommendations
        for pattern, review in self.review.pattern_reviews.items():
            if review.recommendations:
                self.review.recommendations.extend(review.recommendations)

        # Model-specific recommendations
        for model, profile in self.review.model_profiles.items():
            if profile.weaknesses:
                self.review.recommendations.append(
                    f"{model}: Consider limitations in {', '.join(profile.weaknesses)}"
                )

        # Remove duplicates
        self.review.recommendations = list(dict.fromkeys(self.review.recommendations))

    def generate_markdown_report(self) -> str:
        """Generate a markdown report of the review."""
        if not self.review:
            self.review_all()

        lines = [
            "# LLM Prompt Testing - Senior Review Report",
            "\n---\n",
            self.review.overall_summary,
            "\n---\n",
        ]

        # Pattern reviews
        lines.append("## Pattern-by-Pattern Review\n")
        for pattern, review in self.review.pattern_reviews.items():
            status = "✅" if not review.needs_attention else "⚠️"
            lines.append(f"### {status} {pattern}")
            lines.append(f"- **Pass Rate**: {review.pass_rate:.1f}%")
            lines.append(f"- **Average Score**: {review.avg_score:.2f}/4")
            lines.append(f"- **Total Runs**: {review.total_runs}")

            if review.issues:
                lines.append("\n**Issues:**")
                for issue in review.issues:
                    lines.append(f"  - {issue}")

            if review.recommendations:
                lines.append("\n**Recommendations:**")
                for rec in review.recommendations:
                    lines.append(f"  - {rec}")

            lines.append("")

        # Critical issues
        if self.review.critical_issues:
            lines.append("## Critical Issues\n")
            for issue in self.review.critical_issues:
                lines.append(f"  - ❌ {issue}")
            lines.append("")

        # All recommendations
        lines.append("## All Recommendations\n")
        for i, rec in enumerate(self.review.recommendations, 1):
            lines.append(f"{i}. {rec}")
        lines.append("")

        # Model capability matrix
        lines.append("## Model Capability Summary\n")
        for model, profile in self.review.model_profiles.items():
            lines.append(f"### {model}")
            lines.append(f"- **Overall Pass Rate**: {profile.overall_pass_rate:.0f}%")
            if profile.strengths:
                lines.append(f"- **Strengths**: {', '.join(profile.strengths)}")
            if profile.weaknesses:
                lines.append(f"- **Weaknesses**: {', '.join(profile.weaknesses)}")
            lines.append("")

        return "\n".join(lines)

    def write_report(self, path: Optional[Path] = None) -> Path:
        """Write the review report to a file."""
        report_path = path or self.results_dir / "senior_review_report.md"

        if not self.review:
            self.review_all()

        content = self.generate_markdown_report()

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Senior review report written to {report_path}")
        return report_path


# ============================================================================
# Standalone Functions
# ============================================================================

def review_results(results_dir: Optional[Path] = None) -> FinalReview:
    """
    Review all test results and return the review.

    Args:
        results_dir: Directory containing test results

    Returns:
        FinalReview with complete analysis
    """
    reviewer = SeniorReviewer(results_dir)
    return reviewer.review_all()


def generate_review_report(results_dir: Optional[Path] = None) -> Path:
    """
    Review all test results and generate a report file.

    Args:
        results_dir: Directory containing test results

    Returns:
        Path to the generated report
    """
    reviewer = SeniorReviewer(results_dir)
    reviewer.review_all()
    return reviewer.write_report()
