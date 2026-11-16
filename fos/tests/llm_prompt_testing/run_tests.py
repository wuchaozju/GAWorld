"""
Small Model Action Testing Runner - Windows Compatible

Runs comprehensive tests on 3-4B models to determine which
format (JSON/XML/text) works best for each.

Usage:
    python -m tests.llm_prompt_testing.run_tests
    python -m tests.llm_prompt_testing.run_tests --models qwen3_4b --runs 3
"""

import sys
import time
from pathlib import Path
from typing import List

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
    system_instructions="Choose your action carefully.",
)


def test_model_format(
    client: OllamaClient,
    model_config,
    format_type: str,
    runs: int,
    scenario,
    agent,
    verbose: bool = True,
) -> List[dict]:
    """Test a single model with a single format."""
    api_name = model_config.api_name
    model_name = model_config.name
    results = []

    # Build prompt
    builder = PROMPT_BUILDERS.get(format_type, build_json_prompt)
    prompt = builder(scenario, agent)

    if verbose:
        print(f"  Testing {model_name} with {format_type} format...")

    valid_actions = [a.name for a in scenario.actions]

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
            parse_result = parse_action(output, valid_actions)

            result = {
                "model": model_name,
                "format": format_type,
                "run": i + 1,
                "success": parse_result.success and parse_result.action in valid_actions,
                "action": parse_result.action,
                "parse_method": parse_result.parse_method,
                "format_score": parse_result.format_score,
                "output_length": len(output),
                "latency_ms": latency_ms,
                "output_preview": output[:100],
            }
            results.append(result)

            # Show run result
            if verbose:
                icon = "+" if result["success"] else "-"
                print(f"    Run {i+1}/{runs}: {icon} action={result['action']}, method={result['parse_method']}, latency={latency_ms}ms")

        except Exception as e:
            if verbose:
                print(f"    Run {i+1}/{runs}: ERROR - {e}")

            result = {
                "model": model_name,
                "format": format_type,
                "run": i + 1,
                "success": False,
                "action": None,
                "parse_method": "failed",
                "format_score": 0,
                "output_length": 0,
                "latency_ms": 0,
                "output_preview": str(e),
            }
            results.append(result)

    return results


def run_all_tests(
    models: List[str],
    formats: List[str],
    runs_per_format: int,
    scenario,
    agent,
    verbose: bool = True,
) -> tuple[List[dict], dict]:
    """Run all model-format combination tests."""
    client = OllamaClient()

    # Check connection
    print("Checking Ollama connection...")
    try:
        available_models = client.list_models()
        print(f"[OK] Ollama running. Found {len(available_models)} models.")
    except Exception as e:
        print(f"[ERROR] Could not connect to Ollama: {e}")
        print("  Make sure Ollama is running: ollama serve")
        return [], {}

    # Check which test models are available
    missing_models = []

    for model_config in AVAILABLE_MODELS:
        if model_config.name in models:
            if model_config.api_name not in available_models:
                missing_models.append(model_config.name)

    if missing_models:
        print(f"\n[WARNING] These models are not available: {', '.join(missing_models)}")
        print("  Install with: ollama pull <model_name>")
        print("  Continuing with available models...\n")
        models = [m for m in models if m not in missing_models]

    if not models:
        print("\n[ERROR] No models available for testing.")
        return [], {}

    # Calculate total tests
    total_tests = len(models) * len(formats) * runs_per_format

    print(f"\n{'='*65}")
    print(f"Testing {len(models)} models x {len(formats)} formats x {runs_per_format} runs = {total_tests} total")
    print(f"Target success rate: {TARGET_SUCCESS_RATE}%")
    print(f"{'='*65}\n")

    all_results = []
    summary = {}

    for model_name in models:
        model_config = None
        for m in AVAILABLE_MODELS:
            if m.name == model_name:
                model_config = m
                break

        if not model_config:
            continue

        model_results = {}

        for format_type in formats:
            results = test_model_format(
                client=client,
                model_config=model_config,
                format_type=format_type,
                runs=runs_per_format,
                scenario=scenario,
                agent=agent,
                verbose=verbose,
            )
            all_results.extend(results)

            # Calculate stats for this model-format combo
            successful = sum(1 for r in results if r["success"])
            rate = (successful / len(results) * 100) if results else 0

            summary[f"{model_name}_{format_type}"] = {
                "model": model_name,
                "format": format_type,
                "total": len(results),
                "successful": successful,
                "success_rate": rate,
                "avg_latency_ms": sum(r["latency_ms"] for r in results) / len(results) if results else 0,
            }

            model_results[format_type] = f"{rate:.0f}%"

        # Show model summary
        print(f"\n{model_name} Results:")
        for fmt in formats:
            rate_str = model_results.get(fmt, "N/A")
            icon = "[OK]" if summary[f"{model_name}_{fmt}"]["success_rate"] >= TARGET_SUCCESS_RATE else "[--]"
            print(f"  {fmt.upper():6} : {rate_str:>6} {icon}")

    return all_results, summary


def print_final_summary(summary: dict, models: List[str], formats: List[str]):
    """Print formatted summary of results."""
    print(f"\n{'='*65}")
    print("FINAL SUMMARY")
    print(f"{'='*65}\n")

    # Table header
    print(f"{'Model':<15} | {'JSON':<7} | {'XML':<7} | {'TEXT':<7} | BEST")
    print("-" * 65)

    for model in models:
        row_data = {}
        for fmt in formats:
            key = f"{model}_{fmt}"
            if key in summary:
                rate = summary[key]["success_rate"]
                icon = "Y" if rate >= TARGET_SUCCESS_RATE else "N"
                row_data[fmt] = f"{rate:.0f}%{icon}"
            else:
                row_data[fmt] = "---"

        # Find best format
        valid_rates = [(fmt, summary[f"{model}_{fmt}"]["success_rate"])
                      for fmt in formats if f"{model}_{fmt}" in summary]
        if valid_rates:
            best_fmt, best_rate = max(valid_rates, key=lambda x: x[1])
            best_str = f"{best_fmt.upper()}({best_rate:.0f}%)"
        else:
            best_str = "NONE"

        print(f"{model:<15} | {row_data.get('json','---'):<7} | {row_data.get('xml','---'):<7} | {row_data.get('text','---'):<7} | {best_str}")

    # Overall recommendations
    print(f"\n{'='*65}")
    print("RECOMMENDATIONS")
    print(f"{'='*65}\n")

    models_meeting_target = []

    for model in models:
        best_format = None
        best_rate = 0

        for fmt in formats:
            key = f"{model}_{fmt}"
            if key in summary:
                rate = summary[key]["success_rate"]
                if rate > best_rate:
                    best_rate = rate
                    best_format = fmt

        if best_format:
            icon = "[OK]" if best_rate >= TARGET_SUCCESS_RATE else "[--]"
            status = "PASSES" if best_rate >= TARGET_SUCCESS_RATE else "NEEDS WORK"
            print(f"  {model}: {best_format.upper()} format ({best_rate:.0f}%) {icon} {status}")

            if best_rate >= TARGET_SUCCESS_RATE:
                models_meeting_target.append(model)

    # Overall status
    print(f"\n{'='*65}")
    passing = len(models_meeting_target)
    total = len(models)
    print(f"OVERALL: {passing}/{total} models meet {TARGET_SUCCESS_RATE}% target")

    if passing == total:
        print("[SUCCESS] All models have at least one working format!")
    elif passing >= total * 0.6:
        print(f"[PARTIAL] {passing} of {total} models pass. Consider prompt tuning.")
    else:
        print(f"[FAIL] Only {passing} of {total} models pass. Significant rework needed.")


def save_results(results: List[dict], summary: dict, output_dir: str):
    """Save results to files."""
    from datetime import datetime
    import csv
    import json

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Save detailed CSV
    csv_path = output_path / f"test_results_{timestamp}.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "model", "format", "run", "success", "action",
            "parse_method", "format_score", "output_length", "latency_ms", "output_preview"
        ])
        writer.writeheader()
        for r in results:
            writer.writerow(r)

    print(f"\n[OK] Results saved to: {csv_path}")

    # Save summary JSON
    summary_path = output_path / f"summary_{timestamp}.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"[OK] Summary saved to: {summary_path}")


def main():
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
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Less verbose output"
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
    results, summary = run_all_tests(
        models=models,
        formats=formats,
        runs_per_format=args.runs,
        scenario=TEST_SCENARIO,
        agent=TEST_AGENT,
        verbose=not args.quiet,
    )

    # Print summary
    print_final_summary(summary, models, formats)

    # Save results
    save_results(results, summary, args.output_dir)


if __name__ == "__main__":
    main()
