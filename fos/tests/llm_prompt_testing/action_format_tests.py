"""
Action format testing framework for 3-4B LLM models.

Provides comprehensive test suites for:
1. Format extraction tests - testing each parser in isolation
2. Model compatibility tests - testing each model with each format
3. Prompt length tests - testing prompts at different lengths

Run with:
    python -m tests.llm_prompt_testing.action_format_tests
    python -m tests.llm_prompt_testing.action_format_tests --model-compat
    python -m tests.llm_prompt_testing.action_format_tests --length-tests
"""

import argparse
import csv
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Setup path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from tests.llm_prompt_testing.action_parser import (
    parse_action,
    FORMAT_TEST_FIXTURES,
    ParseResult,
)
from tests.llm_prompt_testing.agents import ARCHETYPAL_AGENTS
from tests.llm_prompt_testing.config import (
    AVAILABLE_MODELS,
    get_model_by_name,
)
from tests.llm_prompt_testing.ollama_client import (
    OllamaClient,
    ChatMessage,
)
from tests.llm_prompt_testing.prompt_builder import (
    build_json_prompt,
    PROMPT_BUILDERS,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================================
# Test Scenarios and Agents
# ============================================================================

# Simple test scenario for format testing
@dataclass
class TestScenario:
    """Simple scenario for format testing."""
    id: str = "test_scenario"
    name: str = "Test Scenario"
    description: str = "Format testing scenario"
    pattern: str = "Strategic Decisions"
    system_instructions: str = ""
    actions: List[Any] = field(default_factory=list)

    def __post_init__(self):
        if not self.actions:
            from tests.llm_prompt_testing.scenarios import Action
            self.actions = [
                Action("cooperate", "Choose to cooperate"),
                Action("defect", "Choose to defect"),
            ]


# Test agent
TEST_AGENT = ARCHETYPAL_AGENTS.get("Analyst", ARCHETYPAL_AGENTS["Authority"])


# ============================================================================
# Format Extraction Tests
# ============================================================================

@dataclass
class FormatTestResult:
    """Result of testing a single format parse."""
    test_name: str
    input_output: str
    expected_action: Optional[str]
    actual_result: ParseResult
    passed: bool

    def to_dict(self) -> dict:
        return {
            "test_name": self.test_name,
            "input_output": self.input_output[:100],
            "expected_action": self.expected_action,
            "actual_action": self.actual_result.action,
            "parse_method": self.actual_result.parse_method,
            "format_score": self.actual_result.format_score,
            "passed": self.passed,
        }


def run_format_extraction_tests() -> List[FormatTestResult]:
    """
    Test each parser in isolation with valid and malformed inputs.

    Returns:
        List of FormatTestResult objects
    """
    valid_actions = ["cooperate", "defect"]
    results = []

    # Test JSON parsing
    logger.info("Testing JSON format extraction...")
    for fixture in FORMAT_TEST_FIXTURES.get("json_valid", []):
        result = parse_action(fixture, valid_actions)
        results.append(FormatTestResult(
            test_name="json_valid",
            input_output=fixture,
            expected_action="cooperate",
            actual_result=result,
            passed=result.success and result.parse_method == "json",
        ))

    # Test XML parsing
    logger.info("Testing XML format extraction...")
    for fixture in FORMAT_TEST_FIXTURES.get("xml_valid", []):
        result = parse_action(fixture, valid_actions)
        results.append(FormatTestResult(
            test_name="xml_valid",
            input_output=fixture,
            expected_action="cooperate",
            actual_result=result,
            passed=result.success and result.parse_method == "xml",
        ))

    # Test text parsing
    logger.info("Testing text format extraction...")
    for fixture in FORMAT_TEST_FIXTURES.get("text_valid", []):
        result = parse_action(fixture, valid_actions)
        results.append(FormatTestResult(
            test_name="text_valid",
            input_output=fixture,
            expected_action="cooperate",
            actual_result=result,
            passed=result.success and result.parse_method == "text",
        ))

    # Test conversational parsing
    logger.info("Testing conversational format extraction...")
    for fixture in FORMAT_TEST_FIXTURES.get("conversational", []):
        result = parse_action(fixture, valid_actions)
        results.append(FormatTestResult(
            test_name="conversational",
            input_output=fixture,
            expected_action="cooperate",
            actual_result=result,
            passed=result.success,  # Any parse method is okay for conversational
        ))

    # Test malformed handling
    logger.info("Testing malformed input handling...")
    for fixture in FORMAT_TEST_FIXTURES.get("malformed", []):
        result = parse_action(fixture, valid_actions)
        results.append(FormatTestResult(
            test_name="malformed",
            input_output=fixture,
            expected_action=None,
            actual_result=result,
            passed=not result.success,  # Should fail gracefully
        ))

    return results


def summarize_format_tests(results: List[FormatTestResult]) -> Dict[str, Any]:
    """Summarize format extraction test results."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)

    by_method = {}
    for r in results:
        method = r.actual_result.parse_method
        if method not in by_method:
            by_method[method] = {"total": 0, "passed": 0}
        by_method[method]["total"] += 1
        if r.passed:
            by_method[method]["passed"] += 1

    return {
        "total_tests": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": (passed / total * 100) if total > 0 else 0,
        "by_method": by_method,
    }


# ============================================================================
# Model Compatibility Tests
# ============================================================================

@dataclass
class ModelFormatTest:
    """Test result for a model-format combination."""
    model_name: str
    format_type: str
    run_number: int
    prompt: str
    output: str
    parse_result: ParseResult
    latency_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "model_name": self.model_name,
            "format_type": self.format_type,
            "run_number": self.run_number,
            "prompt_length": len(self.prompt.split()),
            "output_length": len(self.output),
            "parsed_action": self.parse_result.action,
            "parse_method": self.parse_result.parse_method,
            "format_score": self.parse_result.format_score,
            "success": self.parse_result.success,
            "latency_ms": self.latency_ms,
        }


async def run_model_format_test(
    model_name: str,
    format_type: str,
    scenario: TestScenario,
    agent,
    runs: int = 5,
    client: Optional[OllamaClient] = None,
) -> List[ModelFormatTest]:
    """
    Test a specific model with a specific format.

    Args:
        model_name: Name of the model to test
        format_type: Format type ("json", "xml", "text")
        scenario: Test scenario
        agent: Agent profile
        runs: Number of test runs
        client: Ollama client (creates new if None)

    Returns:
        List of ModelFormatTest results
    """
    if client is None:
        client = OllamaClient()

    model_config = get_model_by_name(model_name)
    if not model_config:
        logger.error(f"Model {model_name} not found in config")
        return []

    api_name = model_config.api_name
    results = []

    # Build prompt for this format
    prompt_builder = PROMPT_BUILDERS.get(format_type, build_json_prompt)
    prompt = prompt_builder(scenario, agent)

    logger.info(f"Testing {model_name} with {format_type} format ({runs} runs)...")

    for i in range(runs):
        try:
            start_time = time.time()

            response = client.chat_completion(
                messages=[
                    ChatMessage(role="system", content=prompt),
                    ChatMessage(role="user", content="What do you choose?"),
                ],
                model=api_name,
                temperature=0.7,
                max_tokens=200,
            )

            latency_ms = int((time.time() - start_time) * 1000)
            output = response.content

            # Parse the output
            valid_actions = [a.name for a in scenario.actions]
            parse_result = parse_action(output, valid_actions)

            results.append(ModelFormatTest(
                model_name=model_name,
                format_type=format_type,
                run_number=i + 1,
                prompt=prompt,
                output=output,
                parse_result=parse_result,
                latency_ms=latency_ms,
            ))

            logger.debug(
                f"  Run {i+1}/{runs}: "
                f"action={parse_result.action}, "
                f"method={parse_result.parse_method}, "
                f"success={parse_result.success}"
            )

        except Exception as e:
            logger.error(f"Error running test {i+1} for {model_name}: {e}")
            results.append(ModelFormatTest(
                model_name=model_name,
                format_type=format_type,
                run_number=i + 1,
                prompt=prompt,
                output="",
                parse_result=ParseResult(
                    success=False,
                    action=None,
                    parse_method="failed",
                    format_score=0,
                    raw_output="",
                    error_message=str(e),
                ),
            ))

    return results


async def run_all_model_compat_tests(
    models: Optional[List[str]] = None,
    formats: Optional[List[str]] = None,
    runs_per_format: int = 5,
) -> List[ModelFormatTest]:
    """
    Run model compatibility tests for all model-format combinations.

    Args:
        models: List of model names (tests all if None)
        formats: List of format types (tests all if None)
        runs_per_format: Number of runs per format

    Returns:
        List of all ModelFormatTest results
    """
    if models is None:
        models = [m.name for m in AVAILABLE_MODELS]
    if formats is None:
        formats = ["json", "xml", "text"]

    scenario = TestScenario()
    all_results = []
    client = OllamaClient()

    total_tests = len(models) * len(formats) * runs_per_format
    current_test = 0

    for model_name in models:
        for format_type in formats:
            current_test += 1
            logger.info(f"[{current_test}/{total_tests}] Testing {model_name} with {format_type}...")

            results = await run_model_format_test(
                model_name=model_name,
                format_type=format_type,
                scenario=scenario,
                agent=TEST_AGENT,
                runs=runs_per_format,
                client=client,
            )
            all_results.extend(results)

    return all_results


def summarize_model_compat_tests(results: List[ModelFormatTest]) -> Dict[str, Any]:
    """Summarize model compatibility test results."""
    summary = {}

    # Group by model and format
    for result in results:
        key = f"{result.model_name}_{result.format_type}"
        if key not in summary:
            summary[key] = {
                "model_name": result.model_name,
                "format_type": result.format_type,
                "total_runs": 0,
                "successful": 0,
                "failed": 0,
                "parse_methods": {},
                "total_latency_ms": 0,
                "actions": {},
            }

        s = summary[key]
        s["total_runs"] += 1
        s["total_latency_ms"] += result.latency_ms

        if result.parse_result.success:
            s["successful"] += 1
        else:
            s["failed"] += 1

        # Track parse methods
        method = result.parse_result.parse_method
        s["parse_methods"][method] = s["parse_methods"].get(method, 0) + 1

        # Track actions
        action = result.parse_result.action or "None"
        s["actions"][action] = s["actions"].get(action, 0) + 1

    # Calculate rates
    for key, s in summary.items():
        s["success_rate"] = (s["successful"] / s["total_runs"] * 100) if s["total_runs"] > 0 else 0
        s["avg_latency_ms"] = s["total_latency_ms"] / s["total_runs"] if s["total_runs"] > 0 else 0
        s["meets_target"] = s["success_rate"] >= 85.0

    return summary


# ============================================================================
# CSV Reporting
# ============================================================================

def save_format_tests_csv(results: List[FormatTestResult], output_path: Path) -> None:
    """Save format extraction test results to CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "test_name",
            "input_output",
            "expected_action",
            "actual_action",
            "parse_method",
            "format_score",
            "passed",
        ])

        for r in results:
            writer.writerow([
                r.test_name,
                r.input_output[:100],
                r.expected_action,
                r.actual_result.action,
                r.actual_result.parse_method,
                r.actual_result.format_score,
                r.passed,
            ])

    logger.info(f"Saved format test results to {output_path}")


def save_model_compat_csv(results: List[ModelFormatTest], output_path: Path) -> None:
    """Save model compatibility test results to CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "model_name",
            "format_type",
            "run_number",
            "prompt_length",
            "output_length",
            "parsed_action",
            "parse_method",
            "format_score",
            "success",
            "latency_ms",
        ])

        for r in results:
            writer.writerow([
                r.model_name,
                r.format_type,
                r.run_number,
                len(r.prompt.split()),
                len(r.output),
                r.parse_result.action,
                r.parse_result.parse_method,
                r.parse_result.format_score,
                r.parse_result.success,
                r.latency_ms,
            ])

    logger.info(f"Saved model compat results to {output_path}")


def save_summary_report(
    summary: Dict[str, Any],
    output_path: Path,
    report_type: str = "format",
) -> None:
    """Save summary report as JSON and text."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Save JSON
    json_path = output_path.with_suffix(".json")
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Save text report
    with open(output_path, "w") as f:
        f.write(f"# {report_type.capitalize()} Test Summary Report\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        if report_type == "format":
            f.write(f"Total Tests: {summary['total_tests']}\n")
            f.write(f"Passed: {summary['passed']}\n")
            f.write(f"Failed: {summary['failed']}\n")
            f.write(f"Pass Rate: {summary['pass_rate']:.1f}%\n\n")

            f.write("## Results by Parse Method\n\n")
            for method, stats in summary['by_method'].items():
                f.write(f"- {method}: {stats['passed']}/{stats['total']} passed\n")

        elif report_type == "model_compat":
            f.write("## Model-Format Results\n\n")

            # Create summary table
            f.write("| Model | Format | Success Rate | Meets Target |\n")
            f.write("|-------|--------|-------------|--------------|\n")
            for key, s in summary.items():
                target = "✓" if s['meets_target'] else "✗"
                f.write(f"| {s['model_name']} | {s['format_type']} | {s['success_rate']:.0f}% | {target} |\n")

            f.write("\n## Detailed Results\n\n")
            for key, s in summary.items():
                f.write(f"### {s['model_name']} - {s['format_type']}\n\n")
                f.write(f"- Success Rate: {s['success_rate']:.1f}%\n")
                f.write(f"- Runs: {s['successful']}/{s['total_runs']} successful\n")
                f.write(f"- Parse Methods: {s['parse_methods']}\n")
                f.write(f"- Actions: {s['actions']}\n")
                f.write(f"- Avg Latency: {s['avg_latency_ms']:.0f}ms\n\n")

    logger.info(f"Saved summary report to {output_path}")


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """Main entry point for action format tests."""
    parser = argparse.ArgumentParser(
        description="Test action format parsing and model compatibility"
    )
    parser.add_argument(
        "--format-tests",
        action="store_true",
        help="Run format extraction tests (no API calls)"
    )
    parser.add_argument(
        "--model-compat",
        action="store_true",
        help="Run model compatibility tests (requires Ollama)"
    )
    parser.add_argument(
        "--models",
        nargs="+",
        help="Specific models to test (default: all)"
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        choices=["json", "xml", "text"],
        help="Specific formats to test (default: all)"
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        help="Number of runs per format (default: 5)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="test_results/format_tests",
        help="Output directory for results"
    )

    args = parser.parse_args()

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Default: run format tests if nothing specified
    if not args.format_tests and not args.model_compat:
        args.format_tests = True

    # Run format extraction tests
    if args.format_tests:
        logger.info("Running format extraction tests...")
        results = run_format_extraction_tests()
        summary = summarize_format_tests(results)

        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_format_tests_csv(
            results,
            output_dir / f"format_tests_{timestamp}.csv"
        )
        save_summary_report(
            summary,
            output_dir / f"format_summary_{timestamp}.txt",
            "format"
        )

        # Print summary
        print("\n" + "="*50)
        print("FORMAT EXTRACTION TEST SUMMARY")
        print("="*50)
        print(f"Total Tests: {summary['total_tests']}")
        print(f"Passed: {summary['passed']}")
        print(f"Failed: {summary['failed']}")
        print(f"Pass Rate: {summary['pass_rate']:.1f}%")
        print("\nBy Parse Method:")
        for method, stats in summary['by_method'].items():
            print(f"  {method}: {stats['passed']}/{stats['total']} passed")

    # Run model compatibility tests
    if args.model_compat:
        logger.info("Running model compatibility tests...")
        logger.info("This requires Ollama to be running locally.")

        # Import asyncio for async
        import asyncio

        results = asyncio.run(run_all_model_compat_tests(
            models=args.models,
            formats=args.formats,
            runs_per_format=args.runs,
        ))

        summary = summarize_model_compat_tests(results)

        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_model_compat_csv(
            results,
            output_dir / f"model_compat_{timestamp}.csv"
        )
        save_summary_report(
            summary,
            output_dir / f"compat_summary_{timestamp}.txt",
            "model_compat"
        )

        # Print summary table
        print("\n" + "="*60)
        print("MODEL COMPATIBILITY TEST SUMMARY")
        print("="*60)
        print("\n| Model | Format | Success Rate | Meets 85% Target |")
        print("|--------|--------|-------------|-------------------|")

        # Group for display
        model_format_summary = {}
        for key, s in summary.items():
            model_format_summary[key] = s

        # Sort by model name
        for key in sorted(model_format_summary.keys()):
            s = model_format_summary[key]
            target = "✓" if s['meets_target'] else "✗"
            print(f"| {s['model_name']} | {s['format_type']} | {s['success_rate']:.0f}% | {target} |")

        # Find best format for each model
        print("\n## Recommended Format per Model")
        model_best = {}
        for key, s in summary.items():
            model = s['model_name']
            if model not in model_best:
                model_best[model] = {"format": None, "rate": 0}
            if s['success_rate'] > model_best[model]['rate']:
                model_best[model] = {"format": s['format_type'], "rate": s['success_rate']}

        for model, best in model_best.items():
            print(f"  {model}: {best['format']} ({best['rate']:.0f}%)")


if __name__ == "__main__":
    main()
