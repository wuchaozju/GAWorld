"""
Comprehensive Action Testing for Social-Sim Platform

Tests ALL platform actions against small 3-4B models using JSON/XML/text formats.

Usage:
    python -m tests.llm_prompt_testing.test_all_platform_actions --runs 1
"""

import asyncio
import csv
import json
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
from tests.llm_prompt_testing.ollama_client import OllamaClient, ChatMessage


def get_test_agent():
    """Get a test agent profile."""
    return ARCHETYPAL_AGENTS.get("Analyst", ARCHETYPAL_AGENTS["Authority"])


# ============================================================================
# All Platform Actions (samples for testing)
# ============================================================================

PLATFORM_ACTIONS = {
    "start_voting": {
        "name": "start_voting",
        "description": "Initiate a voting round",
        "valid_params": ["title"],
        "example_input": {"title": "Budget Approval"},
        "example_output": '<Action name="start_voting"><title>Budget Approval</title></Action>',
    },
    "vote": {
        "name": "vote",
        "description": "Cast a vote (yes/no/abstain)",
        "valid_params": ["vote", "comment"],
        "example_input": {"vote": "yes", "comment": "I agree"},
        "example_output": '<Action name="vote"><vote>yes</vote><comment>I agree</comment></Action>',
    },
    "finish_meeting": {
        "name": "finish_meeting",
        "description": "Conclude the meeting",
        "valid_params": [],
        "example_input": {},
        "example_output": '<Action name="finish_meeting"/>',
    },
    "move_to_location": {
        "name": "move_to_location",
        "description": "Move to a location",
        "valid_params": ["location"],
        "example_input": {"location": "market"},
        "example_output": '<Action name="move_to_location"><location>market</location></Action>',
    },
    "speak": {
        "name": "speak",
        "description": "Speak a message",
        "valid_params": ["message"],
        "example_input": {"message": "Hello"},
        "example_output": '<Action name="speak"/>',
    },
    "play_cards": {
        "name": "play_cards",
        "description": "Play cards in a game",
        "valid_params": ["cards"],
        "example_input": {"cards": "A,K,2,3"},
        "example_output": '<Action name="play_cards"><cards>A,K,2,3</cards></Action>',
    },
    "pass": {
        "name": "pass",
        "description": "Pass your turn in a game",
        "valid_params": [],
        "example_input": {},
        "example_output": '<Action name="pass"/>',
    },
}


@dataclass
class ActionTestResult:
    """Result of testing a single action with detailed tracking."""
    action_name: str
    model_name: str
    format_type: str
    run_index: int
    success: bool
    extracted_action: Optional[str]
    parse_method: str
    format_score: int
    latency_ms: int

    # Detailed tracking fields
    prompt_sent: str = ""
    model_output: str = ""
    error_message: str = ""


def build_test_prompt(action_name: str, action_data: dict, format_type: str, agent) -> str:
    """Build a test prompt for a specific action."""
    desc = action_data.get("description", action_name)
    params_desc = ""
    if action_data.get("valid_params"):
        params_desc = "\nValid parameters: " + ", ".join(action_data["valid_params"])

    prompt = f"""You are {agent.name}.

Action: {action_name}
Description: {desc}{params_desc}

Respond with ONLY: {{"action": "action_name", "parameters": {"param": "value" for param in action_data.get("valid_params", [])}}}"""

    return prompt


async def test_action(
    client: OllamaClient,
    model_config,
    action_name: str,
    action_data: dict,
    format_type: str,
    run_index: int,
    agent,
) -> Optional[ActionTestResult]:
    """Test a single action on a single model."""
    api_name = model_config.api_name
    model_name = model_config.name

    # Build prompt
    prompt = build_test_prompt(action_name, action_data, format_type, agent)

    # Prepare user message
    if action_data.get("example_input"):
        user_content = f"Execute this action: {action_data['example_input']}"
    else:
        user_content = f"Execute the {action_name} action"

    try:
        start_time = time.time()

        response = client.chat_completion(
            messages=[
                ChatMessage(role="system", content=prompt),
                ChatMessage(role="user", content=user_content),
            ],
            model=api_name,
            temperature=0.7,
            max_tokens=150,
        )

        latency_ms = int((time.time() - start_time) * 1000)
        output = response.content

        # Parse output
        parse_result = parse_action(output, [action_name])

        result = ActionTestResult(
            action_name=action_name,
            model_name=model_name,
            format_type=format_type,
            run_index=run_index,
            success=parse_result.success and parse_result.action == action_name,
            extracted_action=parse_result.action,
            parse_method=parse_result.parse_method,
            format_score=parse_result.format_score,
            latency_ms=latency_ms,
            prompt_sent=prompt,
            model_output=output,
            error_message="",
        )

        return result

    except Exception as e:
        return ActionTestResult(
            action_name=action_name,
            model_name=model_name,
            format_type=format_type,
            run_index=run_index,
            success=False,
            extracted_action=None,
            parse_method="failed",
            format_score=0,
            latency_ms=0,
            prompt_sent="",
            model_output="",
            error_message=str(e)[:100],
        )


async def run_action_tests(
    actions_to_test: List[str],
    models: List[str],
    formats: List[str],
    runs_per_action: int = 1,
    verbose: bool = True,
) -> tuple[List[ActionTestResult], dict]:
    """Run comprehensive tests on all specified actions."""
    client = OllamaClient()
    agent = get_test_agent()

    # Check connection
    print("Checking Ollama connection...")
    try:
        available_models = client.list_models()
        print(f"[OK] Ollama running. Found {len(available_models)} models.")
    except Exception as e:
        print(f"[ERROR] Could not connect to Ollama: {e}")
        return [], {}

    # Filter available models
    missing_models = []

    for model_config in AVAILABLE_MODELS:
        if model_config.name in models:
            if model_config.api_name not in available_models:
                missing_models.append(model_config.name)

    if missing_models:
        print(f"\n[WARNING] Models not available: {', '.join(missing_models)}")
        print("Continuing with available models...\n")
        models = [m for m in models if m not in missing_models]

    if not models:
        print("\n[ERROR] No models available for testing.")
        return [], {}

    # Calculate total tests
    total_tests = len(models) * len(formats) * len(actions_to_test) * runs_per_action

    print(f"\n{'='*70}")
    print(f"Testing {len(models)} models x {len(formats)} formats x {len(actions_to_test)} actions")
    print(f"Total tests: {total_tests}")
    print(f"{'='*70}\n")

    all_results = []
    summary = {}

    completed = 0
    total_to_complete = total_tests

    # Test each model-format-action combination
    for model_name in models:
        model_config = None
        for m in AVAILABLE_MODELS:
            if m.name == model_name:
                model_config = m
                break

        if not model_config:
            continue

        for format_type in formats:
            for action_name in actions_to_test:
                if action_name not in PLATFORM_ACTIONS:
                    if verbose:
                        print(f"[SKIP] Unknown action: {action_name}")
                    continue

                action_data = PLATFORM_ACTIONS[action_name]

                for run in range(runs_per_action):
                    completed += 1
                    progress = f"[{completed}/{total_to_complete}]"

                    if verbose:
                        print(f"{progress} {model_name:15} | {format_type:4} | {action_name:20} | Run {run+1}/{runs_per_action}")

                    result = await test_action(
                        client=client,
                        model_config=model_config,
                        action_name=action_name,
                        action_data=action_data,
                        format_type=format_type,
                        run_index=run + 1,
                        agent=agent,
                    )

                    if result:
                        all_results.append(result)

                        key = f"{model_config.name}_{format_type}_{action_name}"
                        if key not in summary:
                            summary[key] = {
                                "model": model_config.name,
                                "format": format_type,
                                "action": action_name,
                                "total": 0,
                                "success": 0,
                            }

                        summary[key]["total"] += 1
                        if result.success:
                            summary[key]["success"] += 1

    print(f"\nCompleted {completed} tests")
    return all_results, summary


def print_final_summary(summary: dict, models: List[str], formats: List[str], actions: List[str]) -> None:
    """Print formatted final summary."""
    print(f"\n{'='*70}")
    print("FINAL SUMMARY")
    print(f"{'='*70}\n")

    # Group by action
    by_action = {}
    for key, stats in summary.items():
        action = key.split("_")[-1]
        if action not in by_action:
            by_action[action] = {}
        by_action[action][key] = stats

    # Count passing actions
    passing_actions = []
    total_tested = 0

    for action, formats_data in by_action.items():
        for key, stats in formats_data.items():
            if stats["success"] > 0:
                passing_actions.append(action)
                break
        total_tested += 1

    pass_rate = (len(passing_actions) / total_tested * 100) if total_tested > 0 else 0

    print(f"Actions Tested: {len(by_action)}")
    print(f"Actions Passing (>0%): {len(passing_actions)} ({pass_rate:.0f}%)")
    print(f"Actions Failing (0%): {len(by_action) - len(passing_actions)}")

    if passing_actions:
        print("\nPassing Actions:")
        for action in sorted(passing_actions):
            print(f"  [OK] {action}")

    failing_actions = set(by_action.keys()) - set(passing_actions)
    if failing_actions:
        print("\nFailing Actions:")
        for action in sorted(failing_actions):
            print(f"  [--] {action}")

    print(f"\n{'='*70}")
    print(f"OVERALL: {pass_rate:.0f}% of actions work")
    print("TARGET: 85%")

    if pass_rate >= 85:
        print("[SUCCESS] Target met!")
    else:
        print("[PARTIAL] Below target.")


def save_results(results: List[ActionTestResult], summary: dict, output_dir: str) -> None:
    """Save results to CSV with detailed tracking."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Save detailed CSV
    csv_path = output_path / f"action_tests_{timestamp}.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "action_name",
            "model_name",
            "format_type",
            "run_index",
            "success",
            "extracted_action",
            "parse_method",
            "format_score",
            "latency_ms",
            "prompt_sent",
            "model_output",
            "error_message",
            "output_preview",
        ])

        for r in results:
            # Truncate long fields for CSV
            output_truncated = r.model_output[:200] if len(r.model_output) > 200 else r.model_output
            error_truncated = r.error_message[:200] if len(r.error_message) > 200 else r.error_message
            prompt_truncated = r.prompt_sent[:200] if len(r.prompt_sent) > 200 else r.prompt_sent

            writer.writerow([
                r.action_name,
                r.model_name,
                r.format_type,
                r.run_index,
                r.success,
                r.extracted_action,
                r.parse_method,
                r.format_score,
                r.latency_ms,
                prompt_truncated,
                output_truncated,
                error_truncated,
            ])

    print(f"\n[OK] Results saved to: {csv_path}")

    # Also save summary JSON
    summary_path = output_path / f"summary_{timestamp}.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"[OK] Summary saved to: {summary_path}")


def main():
    """Main entry point."""
    import argparse

    # Default actions to test (sample from each category)
    default_actions = [
        "start_voting",
        "vote",
        "finish_meeting",
        "move_to_location",
        "speak",
        "play_cards",
        "pass",
    ]

    parser = argparse.ArgumentParser(
        description="Test ALL Social-Sim platform actions against 3-4B models"
    )
    parser.add_argument(
        "--actions",
        nargs="+",
        help=f"Specific actions to test (default: {len(default_actions)} sample actions)",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        help="Specific models to test (default: all available)",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        choices=["json", "xml", "text"],
        help="Formats to test (default: JSON only)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Runs per action-format combination (default: 1)",
    )
    parser.add_argument(
        "--all-actions",
        action="store_true",
        help="Test ALL platform actions (not just samples)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="test_results/all_action_tests",
        help="Output directory for results",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Less verbose output",
    )

    args = parser.parse_args()

    # Determine what to test
    if args.all_actions:
        actions_to_test = list(PLATFORM_ACTIONS.keys())
        print(f"[INFO] Testing ALL {len(actions_to_test)} platform actions")
    elif args.actions:
        actions_to_test = args.actions
        print(f"[INFO] Testing {len(actions_to_test)} specified actions")
    else:
        actions_to_test = default_actions
        print(f"[INFO] Testing sample of {len(actions_to_test)} actions")

    # Determine models
    models = args.models if args.models else [m.name for m in AVAILABLE_MODELS]

    # Determine formats - default to JSON only
    formats = args.formats if args.formats else ["json"]

    print("=" * 70)
    print("Social-Sim Platform Action Testing")
    print("=" * 70)
    print("\nConfiguration:")
    print(f"  Models: {', '.join(models)}")
    print(f"  Formats: {', '.join(formats)}")
    print(f"  Actions: {len(actions_to_test)}")
    print(f"  Runs per combo: {args.runs}")

    # Import asyncio

    # Run tests
    results, summary = asyncio.run(run_action_tests(
        actions_to_test=actions_to_test,
        models=models,
        formats=formats,
        runs_per_action=args.runs,
        verbose=not args.quiet,
    ))

    # Print summary
    print_final_summary(summary, models, formats, actions_to_test)

    # Save results
    save_results(results, summary, args.output_dir)


if __name__ == "__main__":
    main()
