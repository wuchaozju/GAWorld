"""
Small Model Action Testing Runner

Runs comprehensive tests on 3-4B models to determine which
format (JSON/XML/text) works best for each.

Progress Tracking:
- Real-time console output with progress bar
- CSV results with format tracking
- Summary report with recommendations
"""

import asyncio
import csv
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Setup path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from tests.llm_prompt_testing.action_parser import parse_action
from tests.llm_prompt_testing.agents import ARCHETYPAL_AGENTS
from tests.llm_prompt_testing.config import AVAILABLE_MODELS
from tests.llm_prompt_testing.ollama_client import (
    OllamaClient,
    ChatMessage,
)
from tests.llm_prompt_testing.prompt_builder import (
    build_json_prompt,
    PROMPT_BUILDERS,
)
from tests.llm_prompt_testing.scenarios import Action, ScenarioConfig

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Test configuration
MODELS_TO_TEST = [m.name for m in AVAILABLE_MODELS]
FORMATS_TO_TEST = ["json", "xml", "text"]
RUNS_PER_FORMAT = 5
TARGET_SUCCESS_RATE = 85.0

# Test agent
TEST_AGENT = ARCHETYPAL_AGENTS.get("Analyst")

# Simple test scenario
TEST_SCENARIO = ScenarioConfig(
    id="test_pd",
    name="Prisoner's Dilemma Test",
    description="Simple cooperate/defect scenario",
    pattern="Strategic Decisions",
    actions=[
        Action("cooperate", "Cooperate with partner"),
        Action("defect", "Betray partner"),
    ],
    system_instructions="Choose your action carefully based on what you think your partner will do.",
)


@dataclass
class TestRun:
    """A single test run result."""
    model_name: str
    format_type: str
    run_index: int
    success: bool
    action: Optional[str]
    parse_method: str
    format_score: int
    output_length: int
    latency_ms: int


class ProgressTracker:
    """Track and display test progress."""

    def __init__(self, total_tests: int):
        self.total_tests = total_tests
        self.completed_tests = 0
        self.start_time = time.time()
        self.last_update = time.time()

    def update(self, model: str, format_type: str, run: int, total_runs: int, success: bool):
        """Update progress and display if enough time passed."""
        self.completed_tests += 1
        current_time = time.time()

        # Only update display every 0.5 seconds
        if current_time - self.last_update < 0.5:
            return

        self.last_update = current_time
        elapsed = current_time - self.start_time
        percent = (self.completed_tests / self.total_tests) * 100

        # Calculate ETA
        if self.completed_tests > 0:
            avg_time = elapsed / self.completed_tests
            remaining = (self.total_tests - self.completed_tests) * avg_time
            eta = int(remaining)
        else:
            eta = 0

        # Status icon
        icon = "✓" if success else "✗"

        # Clear line and show progress
        sys.stdout.write(f"\r[{percent:5.1f}%] {model:15} | {format_type:4} | Run {run}/{total_runs} {icon}  ETA: {eta}s  ")
        sys.stdout.flush()

    def complete(self):
        """Display completion message."""
        elapsed = time.time() - self.start_time
        print(f"\n✓ Completed {self.completed_tests} tests in {elapsed:.1f}s")


def build_prompt(format_type: str, scenario, agent) -> str:
    """Build prompt for given format type."""
    builder = PROMPT_BUILDERS.get(format_type, build_json_prompt)
    return builder(scenario, agent)


async def test_model_format(
    client: OllamaClient,
    model_config,
    format_type: str,
    runs: int,
    scenario,
    agent,
    progress: Optional[ProgressTracker] = None,
) -> List[TestRun]:
    """Test a single model with a single format."""
    api_name = model_config.api_name
    model_name = model_config.name
    results = []

    # Build prompt
    prompt = build_prompt(format_type, scenario, agent)

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
                max_tokens=100,
            )

            latency_ms = int((time.time() - start_time) * 1000)
            output = response.content

            # Parse output
            valid_actions = [a.name for a in scenario.actions]
            parse_result = parse_action(output, valid_actions)

            run = TestRun(
                model_name=model_name,
                format_type=format_type,
                run_index=i + 1,
                success=parse_result.success and parse_result.action in valid_actions,
                action=parse_result.action,
                parse_method=parse_result.parse_method,
                format_score=parse_result.format_score,
                output_length=len(output),
                latency_ms=latency_ms,
            )
            results.append(run)

            # Update progress
            if progress:
                progress.update(model_name, format_type, i + 1, runs, run.success)

        except Exception as e:
            logger.error(f"Error: {e}")
            run = TestRun(
                model_name=model_name,
                format_type=format_type,
                run_index=i + 1,
                success=False,
                action=None,
                parse_method="failed",
                format_score=0,
                output_length=0,
                latency_ms=0,
            )
            results.append(run)

            if progress:
                progress.update(model_name, format_type, i + 1, runs, False)

    return results


async def run_all_tests(
    models: List[str],
    formats: List[str],
    runs_per_format: int,
    scenario,
    agent,
) -> tuple[List[TestRun], dict]:
    """Run all model-format combination tests."""
    client = OllamaClient()

    # Check connection
    print("Checking Ollama connection...")
    available_models = client.list_models()
    print(f"✓ Ollama running. Found {len(available_models)} models.")

    # Check which test models are available
    missing_models = []

    for model_config in AVAILABLE_MODELS:
        if model_config.name in models:
            if model_config.api_name not in available_models:
                missing_models.append(model_config.name)

    if missing_models:
        print(f"\n⚠ Warning: These models are not available in Ollama: {', '.join(missing_models)}")
        print("  Run: ollama pull <model_name> to install missing models")
        print("  Continuing with available models...\n")
        models = [m for m in models if m not in missing_models]

    if not models:
        print("\n✗ No models available for testing. Please install at least one model.")
        return [], {}

    # Calculate total tests
    total_tests = len(models) * len(formats) * runs_per_format
    progress = ProgressTracker(total_tests)

    all_results = []
    summary = {}  # {model_format: [success, total, avg_score]}

    print(f"\n{'='*65}")
    print(f"Testing {len(models)} models × {len(formats)} formats × {runs_per_format} runs = {total_tests} total tests")
    print(f"Target success rate: {TARGET_SUCCESS_RATE}%")
    print(f"{'='*65}\n")

    for model_name in models:
        model_config = get_model_by_name(model_name)
        if not model_config:
            continue

        for format_type in formats:
            results = await test_model_format(
                client=client,
                model_config=model_config,
                format_type=format_type,
                runs=runs_per_format,
                scenario=scenario,
                agent=agent,
                progress=progress,
            )
            all_results.extend(results)

            # Calculate stats for this model-format combo
            key = f"{model_name}_{format_type}"
            successful = sum(1 for r in results if r.success)
            summary[key] = {
                "model": model_name,
                "format": format_type,
                "total": len(results),
                "successful": successful,
                "success_rate": (successful / len(results) * 100) if results else 0,
                "avg_latency_ms": sum(r.latency_ms for r in results) / len(results) if results else 0,
                "parse_methods": {},
                "format_scores": {},
                "actions": {},
            }

            for r in results:
                summary[key]["parse_methods"][r.parse_method] = summary[key]["parse_methods"].get(r.parse_method, 0) + 1
                summary[key]["format_scores"][r.format_score] = summary[key]["format_scores"].get(r.format_score, 0) + 1
                if r.action:
                    summary[key]["actions"][r.action] = summary[key]["actions"].get(r.action, 0) + 1

    progress.complete()
    return all_results, summary


def get_model_by_name(name: str):
    """Get model config by name."""
    for m in AVAILABLE_MODELS:
        if m.name == name:
            return m
    return None


def print_results_summary(summary: dict, models: List[str], formats: List[str]):
    """Print formatted summary of results."""
    print(f"\n{'='*65}")
    print("RESULTS SUMMARY")
    print(f"{'='*65}\n")

    # Group by model for easier reading
    model_results = {}
    for key, stats in summary.items():
        model = stats["model"]
        if model not in model_results:
            model_results[model] = {}
        model_results[model][stats["format"]] = stats

    # Table header
    print(f"{'Model':<15} | {'JSON':<6} | {'XML':<6} | {'Text':<6} | Best")
    print("-" * 60)

    for model in models:
        if model not in model_results:
            print(f"{model:<15} | -       | -      | -     | (no data)")
            continue

        formats_data = model_results[model]

        # Get rates
        json_rate = formats_data.get("json", {}).get("success_rate", 0)
        xml_rate = formats_data.get("xml", {}).get("success_rate", 0)
        text_rate = formats_data.get("text", {}).get("success_rate", 0)

        # Find best
        rates = [("json", json_rate), ("xml", xml_rate), ("text", text_rate)]
        best_format, best_rate = max(rates, key=lambda x: x[1])
        best_mark = "✓" if best_rate >= TARGET_SUCCESS_RATE else "?"

        # Format display
        def fmt(rate: float) -> str:
            if rate == 0:
                return "-"
            mark = "✓" if rate >= TARGET_SUCCESS_RATE else "✗"
            return f"{rate:.0f}%{mark}"

        print(f"{model:<15} | {fmt(json_rate):<6} | {fmt(xml_rate):<6} | {fmt(text_rate):<6} | {best_format.upper()}:{best_mark}")

    # Overall recommendations
    print(f"\n{'='*65}")
    print("RECOMMENDATIONS")
    print(f"{'='*65}\n")

    models_meeting_target = []

    for model in models:
        if model not in model_results:
            continue

        formats_data = model_results[model]
        best_format = None
        best_rate = 0

        for fmt_name in formats:
            stats = formats_data.get(fmt_name)
            if stats:
                rate = stats["success_rate"]
                if rate > best_rate:
                    best_rate = rate
                    best_format = fmt_name

        icon = "✓" if best_rate >= TARGET_SUCCESS_RATE else "⚠"
        status = "PASSES" if best_rate >= TARGET_SUCCESS_RATE else "NEEDS WORK"
        print(f"  {model}: {best_format.upper()} format ({best_rate:.0f}% success) {icon} {status}")

        if best_rate >= TARGET_SUCCESS_RATE:
            models_meeting_target.append(model)

    # Overall status
    print(f"\n{'='*65}")
    print(f"OVERALL: {len(models_meeting_target)}/{len(models)} models meet {TARGET_SUCCESS_RATE}% target")

    if len(models_meeting_target) == len(models):
        print("✓ All models have at least one working format!")
    elif len(models_meeting_target) >= len(models) * 0.6:
        print(f"⚠ {len(models_meeting_target)} of {len(models)} models pass. Consider prompt tuning.")
    else:
        print(f"✗ Only {len(models_meeting_target)} of {len(models)} models pass. Significant rework needed.")


def save_results(results: List[TestRun], summary: dict, output_dir: Path):
    """Save results to CSV and JSON files."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Save detailed CSV
    csv_path = output_dir / f"test_results_{timestamp}.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "model_name",
            "format_type",
            "run_index",
            "success",
            "action",
            "parse_method",
            "format_score",
            "output_length",
            "latency_ms",
        ])

        for r in results:
            writer.writerow([
                r.model_name,
                r.format_type,
                r.run_index,
                r.success,
                r.action,
                r.parse_method,
                r.format_score,
                r.output_length,
                r.latency_ms,
            ])

    print(f"\n✓ Detailed results saved to: {csv_path}")

    # Save summary JSON
    summary_path = output_dir / f"summary_{timestamp}.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"✓ Summary saved to: {summary_path}")

    # Save text report
    report_path = output_dir / f"report_{timestamp}.txt"
    with open(report_path, "w") as f:
        f.write("Small Model Action Testing Report\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"Target Success Rate: {TARGET_SUCCESS_RATE}%\n\n")

        f.write("## Model-Format Results\n\n")
        for key, stats in summary.items():
            f.write(f"### {stats['model']} - {stats['format'].upper()}\n")
            f.write(f"  Success Rate: {stats['success_rate']:.1f}%\n")
            f.write(f"  Successful Runs: {stats['successful']}/{stats['total']}\n")
            f.write(f"  Avg Latency: {stats['avg_latency_ms']:.0f}ms\n")
            f.write(f"  Parse Methods: {stats['parse_methods']}\n")
            f.write(f"  Actions: {stats['actions']}\n\n")

    print(f"✓ Report saved to: {report_path}")


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Test 3-4B LLM models with different action formats"
    )
    parser.add_argument(
        "--models",
        nargs="+",
        help="Specific models to test (default: all available)"
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        choices=["json", "xml", "text"],
        help="Formats to test (default: all)"
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=RUNS_PER_FORMAT,
        help=f"Runs per format (default: {RUNS_PER_FORMAT})"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="test_results/small_model_tests",
        help="Output directory for results"
    )

    args = parser.parse_args()

    # Determine what to test
    models = args.models if args.models else MODELS_TO_TEST
    formats = args.formats if args.formats else FORMATS_TO_TEST

    print("="*65)
    print("Small Model Action Testing Framework")
    print("="*65)
    print("\nConfiguration:")
    print(f"  Models: {', '.join(models)}")
    print(f"  Formats: {', '.join(formats)}")
    print(f"  Runs per format: {args.runs}")
    print(f"  Target success rate: {TARGET_SUCCESS_RATE}%")

    # Run tests
    results, summary = await run_all_tests(
        models=models,
        formats=formats,
        runs_per_format=args.runs,
        scenario=TEST_SCENARIO,
        agent=TEST_AGENT,
    )

    # Print summary
    print_results_summary(summary, models, formats)

    # Save results
    save_results(results, summary, Path(args.output_dir))


if __name__ == "__main__":
    asyncio.run(main())
