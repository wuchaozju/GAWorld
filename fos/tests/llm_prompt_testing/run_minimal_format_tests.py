"""
Minimal Format Tests for 3-4B Models

Tests extremely short prompts to see what formats small models
can actually follow reliably.

Usage:
    python -m tests.llm_prompt_testing.run_minimal_format_tests
"""

import asyncio
import csv
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

sys.path.insert(0, "tests/llm_prompt_testing")

from tests.llm_prompt_testing.action_parser import parse_action
from tests.llm_prompt_testing.config import AVAILABLE_MODELS
from tests.llm_prompt_testing.ollama_client import OllamaClient, ChatMessage


# ============================================================================
# Ultra-Minimal Prompt Tests
# ============================================================================

MINIMAL_TEST_CASES = {
    "council_vote": {
        "action": "vote",
        "description": "Cast a vote (yes/no)",
        "scenarios": [
            "A vote is happening. You support it. Respond with XML only.",
            "A vote is happening. You oppose it. Respond with XML only.",
        ],
        "expected_params": {"vote": "yes or no"},
    },

    "move": {
        "action": "move_to_location",
        "description": "Move to a location",
        "scenarios": [
            "You want to go to the market. Respond with XML only.",
            "You want to go home. Respond with XML only.",
        ],
        "expected_params": {"location": "destination"},
    },

    "speak": {
        "action": "speak",
        "description": "Say something",
        "scenarios": [
            "You want to say hello. Respond with XML only.",
            "You agree with what was said. Respond with XML only.",
        ],
        "expected_params": {"message": "what to say"},
    },
}


PROMPT_VARIANTS = {
    "ultra_short": {
        "xml": 'Respond with XML: <Action name="{action}" />',
        "json": 'Respond with JSON: {{"action": "{action}"}}',
        "text": 'Respond with action name only.',
    },

    "with_params": {
        "xml": 'Respond with XML: <Action name="{action}"><param>value</param></Action>',
        "json": 'Respond with JSON: {{"action": "{action}", "parameters": {{"param": "value"}}}',
        "text": 'Respond with action name and parameter.',
    },

    "example_first": {
        "xml": 'Example: <Action name="{action}" />\nYour task:',
        "json": 'Example: {{"action": "{action}"}}\nYour task:',
        "text": 'Example: {action}\nYour task:',
    },
}


@dataclass
class MinimalTestResult:
    """Result of minimal format test."""
    model_name: str
    action_name: str
    prompt_variant: str
    format_type: str
    scenario_index: int
    success: bool
    extracted_action: str
    parse_method: str
    format_score: int
    latency_ms: int
    prompt_length: int
    output_length: int
    model_output: str = ""
    prompt_sent: str = ""


async def test_minimal_prompt(
    client: OllamaClient,
    model_config,
    test_case: dict,
    variant_name: str,
    format_type: str,
    scenario_index: int,
) -> MinimalTestResult:
    """Test a minimal prompt variant."""
    action = test_case["action"]
    scenario = test_case["scenarios"][scenario_index]

    # Build ultra-minimal prompt
    prompt_templates = PROMPT_VARIANTS[variant_name]
    prompt_template = prompt_templates[format_type]
    prompt = prompt_template.replace("{action}", action)

    # Add scenario context
    full_prompt = f"{prompt}\n\n{scenario}"

    try:
        start_time = time.time()

        response = client.chat_completion(
            messages=[
                ChatMessage(role="user", content=full_prompt),
            ],
            model=model_config.api_name,
            temperature=0.1,  # Lower temp for more consistent output
            max_tokens=50,  # Short output for quick testing
        )

        latency_ms = int((time.time() - start_time) * 1000)
        output = response.content

        # Parse action from output
        parse_result = parse_action(output, [action])

        return MinimalTestResult(
            model_name=model_config.name,
            action_name=action,
            prompt_variant=variant_name,
            format_type=format_type,
            scenario_index=scenario_index,
            success=parse_result.success and parse_result.action == action,
            extracted_action=parse_result.action or "",
            parse_method=parse_result.parse_method,
            format_score=parse_result.format_score,
            latency_ms=latency_ms,
            prompt_length=len(full_prompt),
            output_length=len(output),
            model_output=output,
            prompt_sent=full_prompt,
        )

    except Exception:
        return MinimalTestResult(
            model_name=model_config.name,
            action_name=action,
            prompt_variant=variant_name,
            format_type=format_type,
            scenario_index=scenario_index,
            success=False,
            extracted_action="",
            parse_method="failed",
            format_score=0,
            latency_ms=0,
            prompt_length=len(full_prompt),
            output_length=0,
            model_output="",
            prompt_sent=full_prompt,
        )


async def run_minimal_tests(
    models: List[str],
    formats: List[str],
    variants: List[str],
    verbose: bool = True,
) -> tuple[List[MinimalTestResult], dict]:
    """Run minimal format tests."""
    client = OllamaClient()

    # Check connection
    print("Checking Ollama connection...")
    try:
        available_models = client.list_models()
        print(f"[OK] Ollama running. Found {len(available_models)} models.")
    except Exception as e:
        print(f"[ERROR] Could not connect to Ollama: {e}")
        return [], {}

    # Filter models
    available_api_names = [m.api_name for m in AVAILABLE_MODELS if m.name in models]
    missing = [m.name for m in AVAILABLE_MODELS if m.name in models and m.api_name not in available_api_names]

    if missing:
        print(f"\n[WARNING] Models not available: {', '.join(missing)}")
        models = [m for m in models if m not in missing]

    if not models:
        print("\n[ERROR] No models available.")
        return [], {}

    # Count tests
    total_tests = (
        len(models) *
        len(formats) *
        len(variants) *
        sum(len(tc["scenarios"]) for tc in MINIMAL_TEST_CASES.values())
    )

    print(f"\n{'='*70}")
    print("Minimal Format Testing")
    print(f"Models: {len(models)} | Formats: {len(formats)} | Variants: {len(variants)}")
    print(f"Total tests: {total_tests}\n")

    all_results = []
    summary = {}
    completed = 0

    for model_name in models:
        model_config = next((m for m in AVAILABLE_MODELS if m.name == model_name), None)
        if not model_config:
            continue

        for test_case_name, test_case in MINIMAL_TEST_CASES.items():
            for format_type in formats:
                for variant_name in variants:
                    for scenario_idx in range(len(test_case["scenarios"])):
                        completed += 1
                        if verbose:
                            print(f"[{completed}/{total_tests}] {model_name:15} | {variant_name:12} | {format_type:4} | {test_case_name}")

                        result = await test_minimal_prompt(
                            client, model_config, test_case,
                            variant_name, format_type, scenario_idx,
                        )
                        all_results.append(result)

                        # Update summary
                        key = f"{model_config.name}_{variant_name}_{format_type}_{test_case_name}"
                        if key not in summary:
                            summary[key] = {
                                "model": model_config.name,
                                "variant": variant_name,
                                "format": format_type,
                                "action": test_case_name,
                                "total": 0,
                                "success": 0,
                                "avg_format_score": 0,
                            }

                        summary[key]["total"] += 1
                        if result.success:
                            summary[key]["success"] += 1
                        summary[key]["avg_format_score"] += result.format_score

    # Calculate averages
    for key in summary:
        if summary[key]["total"] > 0:
            summary[key]["avg_format_score"] = (
                summary[key]["avg_format_score"] / summary[key]["total"]
            )

    print(f"\nCompleted {completed} tests")
    return all_results, summary


def print_minimal_summary(summary: dict, models: List[str]) -> None:
    """Print minimal test summary."""
    print(f"\n{'='*70}")
    print("MINIMAL FORMAT TEST SUMMARY")
    print(f"{'='*70}\n")

    # By model and format
    by_model_format = {}
    for key, stats in summary.items():
        model = stats["model"]
        fmt = stats["format"]
        variant = stats["variant"]
        mf_key = f"{model}_{fmt}_{variant}"
        if mf_key not in by_model_format:
            by_model_format[mf_key] = {"total": 0, "success": 0, "avg_score": 0}

        by_model_format[mf_key]["total"] += stats["total"]
        by_model_format[mf_key]["success"] += stats["success"]
        by_model_format[mf_key]["avg_score"] += stats["avg_format_score"]

    # Calculate averages and print
    print("Results by Model-Variant-Format:")
    print(f"{'Model':<15} {'Variant':<12} {'Format':<6} {'Success':<8} {'AvgScore':<8}")
    print("-" * 55)

    for mf_key in sorted(by_model_format.keys()):
        data = by_model_format[mf_key]
        rate = data["success"] / data["total"] * 100 if data["total"] > 0 else 0
        avg_score = data["avg_score"] / data["total"] if data["total"] > 0 else 0

        # Parse key
        parts = mf_key.split("_")
        model = parts[0]
        variant = "_".join(parts[1:-1])
        fmt = parts[-1]

        print(f"{model:<15} {variant:<12} {fmt:<6} {data['success']}/{data['total']:<4} ({rate:.0f}%) {avg_score:.1f}")

    # Best format per model
    print(f"\n{'='*70}")
    print("Best Format per Model:")
    for model in models:
        best_key = None
        best_score = -1
        for key, stats in summary.items():
            if stats["model"] == model:
                if stats["avg_format_score"] > best_score:
                    best_score = stats["avg_format_score"]
                    best_key = key

        if best_key:
            stats = summary[best_key]
            print(f"  {model}: {stats['format'].upper()} (avg score: {best_score:.2f})")


def save_minimal_results(results: List[MinimalTestResult], summary: dict, output_dir: str) -> None:
    """Save minimal test results."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    csv_path = output_path / f"minimal_tests_{timestamp}.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "model_name", "action_name", "prompt_variant", "format_type",
            "scenario_index", "success", "extracted_action",
            "parse_method", "format_score", "latency_ms",
            "prompt_length", "output_length", "prompt_sent", "model_output",
        ])

        for r in results:
            output_trunc = r.model_output[:150] if len(r.model_output) > 150 else r.model_output
            prompt_trunc = r.prompt_sent[:100] if len(r.prompt_sent) > 100 else r.prompt_sent

            writer.writerow([
                r.model_name,
                r.action_name,
                r.prompt_variant,
                r.format_type,
                r.scenario_index,
                r.success,
                r.extracted_action,
                r.parse_method,
                r.format_score,
                r.latency_ms,
                r.prompt_length,
                r.output_length,
                prompt_trunc,
                output_trunc,
            ])

    print(f"\n[OK] Results saved to: {csv_path}")

    summary_path = output_path / f"minimal_summary_{timestamp}.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"[OK] Summary saved to: {summary_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Minimal format testing")
    parser.add_argument("--models", nargs="+", help="Models to test (default: all)")
    parser.add_argument("--formats", nargs="+", choices=["json", "xml", "text"], help="Formats (default: all)")
    parser.add_argument("--variants", nargs="+",
                      choices=list(PROMPT_VARIANTS.keys()),
                      help="Prompt variants (default: ultra_short)")
    parser.add_argument("--output-dir", type=str, default="test_results/minimal_tests", help="Output dir")
    parser.add_argument("--quiet", action="store_true", help="Less verbose")

    args = parser.parse_args()

    models = args.models if args.models else [m.name for m in AVAILABLE_MODELS]
    formats = args.formats if args.formats else ["json", "xml", "text"]
    variants = args.variants if args.variants else ["ultra_short"]

    print("=" * 70)
    print("Minimal Format Testing for 3-4B Models")
    print("=" * 70)
    print("\nConfiguration:")
    print(f"  Models: {', '.join(models)}")
    print(f"  Formats: {', '.join(formats)}")
    print(f"  Variants: {', '.join(variants)}")

    results, summary = asyncio.run(run_minimal_tests(
        models=models,
        formats=formats,
        variants=variants,
        verbose=not args.quiet,
    ))

    if results:
        print_minimal_summary(summary, models)
        save_minimal_results(results, summary, args.output_dir)


if __name__ == "__main__":
    main()
