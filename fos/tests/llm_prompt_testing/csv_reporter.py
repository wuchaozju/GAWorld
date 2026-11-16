"""
CSV reporting for LLM prompt testing.

Generates detailed CSV files for each scenario and pattern, with all
testing results, metrics, and analysis.
"""

import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import INTERACTION_PATTERNS, SCENARIOS_BY_PATTERN, test_config
from .evaluators import EvaluationResult

logger = logging.getLogger(__name__)


# ============================================================================
# Test Result Data Structure
# ============================================================================

@dataclass
class TestResult:
    """A single test result."""

    pattern: str
    scenario: str
    model: str
    iteration: int
    run_number: int
    agent_type: str  # "archetypal" or "domain-specific"
    agent_role: str

    # Input
    input_prompt: str
    prompt_version: int = 1

    # Output
    output_raw: str = ""

    # Evaluation
    xml_valid: bool = False
    action_correct: bool = False
    role_aligned: bool = False
    no_errors: bool = False
    overall_score: int = 0

    # Parsed data
    parsed_action: Optional[str] = None
    parsed_thoughts: Optional[str] = None
    parsed_plan: Optional[str] = None

    # Metrics
    token_count: int = 0
    time_ms: int = 0

    # Errors
    error_message: str = ""
    failure_reasons: List[str] = field(default_factory=list)

    # Cross-LLM status (filled later)
    cross_llm_status: str = "NA"  # "PASS", "FAIL", or "NA"
    model_failure_reason: str = ""

    # Timestamp
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def from_evaluation(
        cls,
        pattern: str,
        scenario: str,
        model: str,
        iteration: int,
        run_number: int,
        agent_type: str,
        agent_role: str,
        input_prompt: str,
        evaluation: EvaluationResult,
        response_content: str = "",  # Add parameter for actual response
        token_count: int = 0,
        time_ms: int = 0,
        prompt_version: int = 1,
    ) -> "TestResult":
        """Create TestResult from EvaluationResult."""
        return cls(
            pattern=pattern,
            scenario=scenario,
            model=model,
            iteration=iteration,
            run_number=run_number,
            agent_type=agent_type,
            agent_role=agent_role,
            input_prompt=input_prompt,
            output_raw=response_content or evaluation.error_message or "No output",
            xml_valid=evaluation.xml_valid,
            action_correct=evaluation.action_correct,
            role_aligned=evaluation.role_aligned,
            no_errors=evaluation.no_errors,
            overall_score=evaluation.overall_score,
            parsed_action=evaluation.parsed_action,
            parsed_thoughts=evaluation.parsed_thoughts,
            parsed_plan=evaluation.parsed_plan,
            token_count=token_count,
            time_ms=time_ms,
            error_message=evaluation.error_message,
            failure_reasons=evaluation.failure_reasons,
            prompt_version=prompt_version,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for CSV writing."""
        return {
            "pattern": self.pattern,
            "scenario": self.scenario,
            "model": self.model,
            "iteration": self.iteration,
            "run_number": self.run_number,
            "agent_type": self.agent_type,
            "agent_role": self.agent_role,
            "input_prompt": self.input_prompt,
            "output_raw": self.output_raw,
            "xml_valid": self.xml_valid,
            "action_correct": self.action_correct,
            "role_aligned": self.role_aligned,
            "no_errors": self.no_errors,
            "overall_score": self.overall_score,
            "parsed_action": self.parsed_action or "",
            "parsed_thoughts": self.parsed_thoughts or "",
            "parsed_plan": self.parsed_plan or "",
            "token_count": self.token_count,
            "time_ms": self.time_ms,
            "error_message": self.error_message,
            "failure_reasons": "; ".join(self.failure_reasons),
            "prompt_version": self.prompt_version,
            "cross_llm_status": self.cross_llm_status,
            "model_failure_reason": self.model_failure_reason,
            "timestamp": self.timestamp,
        }


# ============================================================================
# CSV Reporter
# ============================================================================

class CSVReporter:
    """Generates CSV reports for test results."""

    CSV_COLUMNS = [
        "pattern",
        "scenario",
        "model",
        "iteration",
        "run_number",
        "agent_type",
        "agent_role",
        "input_prompt",
        "output_raw",
        "xml_valid",
        "action_correct",
        "role_aligned",
        "no_errors",
        "overall_score",
        "parsed_action",
        "parsed_thoughts",
        "parsed_plan",
        "token_count",
        "time_ms",
        "error_message",
        "failure_reasons",
        "prompt_version",
        "cross_llm_status",
        "model_failure_reason",
        "timestamp",
    ]

    def __init__(self, results_dir: Optional[Path] = None):
        """
        Initialize the CSV reporter.

        Args:
            results_dir: Directory to write CSV files (defaults to config)
        """
        self.results_dir = results_dir or test_config.results_dir
        self.results_dir.mkdir(parents=True, exist_ok=True)

        # Create pattern subdirectories
        for pattern in INTERACTION_PATTERNS:
            pattern_dir = self.results_dir / pattern.replace(" & ", "_").replace(" ", "_").lower()
            pattern_dir.mkdir(parents=True, exist_ok=True)

    def get_scenario_csv_path(self, pattern: str, scenario: str) -> Path:
        """Get the CSV file path for a specific scenario."""
        pattern_dir = self.results_dir / pattern.replace(" & ", "_").replace(" ", "_").lower()
        filename = f"{scenario}.csv"
        return pattern_dir / filename

    def write_scenario_results(
        self,
        results: List[TestResult],
        pattern: str,
        scenario: str,
        mode: str = "w",
    ) -> Path:
        """
        Write results for a single scenario to CSV.

        Args:
            results: List of test results
            pattern: Interaction pattern name
            scenario: Scenario ID
            mode: File write mode ('w' for overwrite, 'a' for append)

        Returns:
            Path to the written CSV file
        """
        csv_path = self.get_scenario_csv_path(pattern, scenario)

        # Write header if new file or overwrite mode
        write_header = mode == "w" or not csv_path.exists()

        with open(csv_path, mode, newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_COLUMNS)
            if write_header:
                writer.writeheader()

            for result in results:
                writer.writerow(result.to_dict())

        logger.info(f"Wrote {len(results)} results to {csv_path}")
        return csv_path

    def append_result(self, result: TestResult, pattern: str, scenario: str) -> Path:
        """Append a single result to the scenario CSV."""
        return self.write_scenario_results([result], pattern, scenario, mode="a")

    def read_scenario_results(
        self,
        pattern: str,
        scenario: str,
    ) -> List[TestResult]:
        """Read existing results from a scenario CSV."""
        csv_path = self.get_scenario_csv_path(pattern, scenario)

        if not csv_path.exists():
            return []

        results = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Reconstruct TestResult from dict
                result = TestResult(
                    pattern=row["pattern"],
                    scenario=row["scenario"],
                    model=row["model"],
                    iteration=int(row["iteration"]),
                    run_number=int(row["run_number"]),
                    agent_type=row["agent_type"],
                    agent_role=row["agent_role"],
                    input_prompt=row["input_prompt"],
                    output_raw=row["output_raw"],
                    xml_valid=row["xml_valid"].lower() == "true",
                    action_correct=row["action_correct"].lower() == "true",
                    role_aligned=row["role_aligned"].lower() == "true",
                    no_errors=row["no_errors"].lower() == "true",
                    overall_score=int(row["overall_score"]),
                    parsed_action=row["parsed_action"] or None,
                    parsed_thoughts=row["parsed_thoughts"] or None,
                    parsed_plan=row["parsed_plan"] or None,
                    token_count=int(row["token_count"]),
                    time_ms=int(row["time_ms"]),
                    error_message=row["error_message"],
                    failure_reasons=row["failure_reasons"].split(";") if row["failure_reasons"] else [],
                    prompt_version=int(row["prompt_version"]),
                    cross_llm_status=row["cross_llm_status"],
                    model_failure_reason=row["model_failure_reason"],
                    timestamp=row["timestamp"],
                )
                results.append(result)

        return results

    def generate_summary_report(self) -> str:
        """Generate a markdown summary report of all test results."""
        lines = [
            "# LLM Prompt Testing Summary Report",
            f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            "## Test Matrix Overview\n",
            "| Pattern | Scenarios | Models Tested | Total Runs |",
            "|---------|-----------|---------------|------------|",
        ]

        total_runs = 0
        total_perfect = 0

        for pattern in INTERACTION_PATTERNS:
            scenarios = SCENARIOS_BY_PATTERN.get(pattern, [])
            pattern_dir = self.results_dir / pattern.replace(" & ", "_").replace(" ", "_").lower()

            scenario_count = len(scenarios)
            runs = 0
            perfect = 0

            for scenario in scenarios:
                csv_path = pattern_dir / f"{scenario}.csv"
                if csv_path.exists():
                    results = self.read_scenario_results(pattern, scenario)
                    runs += len(results)
                    perfect += sum(1 for r in results if r.overall_score == 4)

            total_runs += runs
            total_perfect += perfect

            lines.append(f"| {pattern} | {scenario_count} | 3 | {runs} |")

        lines.append("\n## Overall Results\n")
        pass_rate = (total_perfect / total_runs * 100) if total_runs > 0 else 0
        lines.append(f"- **Total Runs**: {total_runs}")
        lines.append(f"- **Perfect Runs**: {total_perfect}")
        lines.append(f"- **Pass Rate**: {pass_rate:.1f}%\n")

        return "\n".join(lines)

    def write_summary_report(self, path: Optional[Path] = None) -> Path:
        """Write the summary report to a file."""
        report_path = path or self.results_dir / "summary_report.md"
        content = self.generate_summary_report()

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Summary report written to {report_path}")
        return report_path


# Global reporter instance
default_reporter = CSVReporter()
