"""
Comprehensive Action Testing for Social-Sim Platform

Tests ALL platform actions against small 3-4B models.

Usage:
    python -m tests.llm_prompt_testing.run_all_actions
"""

import asyncio
import csv
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "tests/llm_prompt_testing")

from tests.llm_prompt_testing.action_parser import parse_action
from tests.llm_prompt_testing.agents import ARCHETYPAL_AGENTS
from tests.llm_prompt_testing.config import AVAILABLE_MODELS
from tests.llm_prompt_testing.ollama_client import OllamaClient, ChatMessage

# Platform actions to test
PLATFORM_ACTIONS = {
    "start_voting": {
        "name": "start_voting",
        "description": "Initiate a voting round",
        "valid_params": ["title"],
        "example_input": {"title": "Test"},
    },
    "vote": {
        "name": "vote",
        "description": "Cast a vote (yes/no)",
        "valid_params": ["vote"],
        "example_input": {"vote": "yes"},
    },
    "finish_meeting": {
        "name": "finish_meeting",
        "description": "Conclude the meeting",
        "valid_params": [],
    },
    "move_to_location": {
        "name": "move_to_location",
        "description": "Move to a location",
        "valid_params": ["location"],
        "example_input": {"location": "market"},
    },
    "speak": {
        "name": "speak",
        "description": "Speak a message",
        "valid_params": ["message"],
        "example_input": {"message": "Hello"},
    },
    "play_cards": {
        "name": "play_cards",
        "description": "Play cards in a game",
        "valid_params": ["cards"],
        "example_input": {"cards": "A,K,2,3"},
    },
    "pass": {
        "name": "pass",
        "description": "Pass your turn in a game",
        "valid_params": [],
        "example_input": {},
    },
}


@dataclass
class ActionTestResult:
    action_name: str
    model_name: str
    format_type: str
    run_index: int
    success: bool
    extracted_action: str
    parse_method: str
    format_score: int
    latency_ms: int
    prompt_sent: str = ""
    model_output: str = ""
    error_message: str = ""


def get_test_agent():
    return ARCHETYPAL_AGENTS.get("Analyst", ARCHETYPAL_AGENTS["Authority"])


def build_test_prompt(action_name: str, action_data: dict, agent) -> str:
    desc = action_data.get("description", action_name)
    params_desc = ""
    if action_data.get("valid_params"):
        params_desc = "\nValid: " + ", ".join(action_data["valid_params"])

    prompt = f'''You are {agent.name}.

Action: {action_name}
Description: {desc}{params_desc}

Respond with ONLY: {{"action": "action_name"}}, "parameters": {"param": "value" for param in action_data.get("valid_params", [])}}}'''

    return prompt


async def test_action(client, model_config, action_name, action_data, format_type, run_index, agent):
    api_name = model_config.api_name
    model_name = model_config.name

    prompt = build_test_prompt(action_name, action_data, format_type, agent)

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

        parse_result = parse_action(output, [action_name])

        return ActionTestResult(
            action_name=action_name,
            model_name=model_name,
            format_type=format_type,
            run_index=run_index,
            success=parse_result.success and parse_result.action == action_name,
            extracted_action=parse_result.action or "",
            parse_method=parse_result.parse_method,
            format_score=parse_result.format_score,
            latency_ms=latency_ms,
            prompt_sent=prompt,
            model_output=output,
            error_message="",
        )

    except Exception as e:
        return ActionTestResult(
            action_name=action_name,
            model_name=model_name,
            format_type=format_type,
            run_index=run_index,
            success=False,
            extracted_action="",
            parse_method="failed",
            format_score=0,
            latency_ms=0,
            prompt_sent="",
            model_output="",
            error_message=str(e)[:100],
        )


async def run_action_tests(actions_to_test, models, formats, runs_per_action, verbose):
    client = OllamaClient()
    agent = get_test_agent()

    print("Checking Ollama connection...")
    try:
        available_models = client.list_models()
        print(f"[OK] Ollama running. Found {len(available_models)} models.")
    except Exception as e:
        print(f"[ERROR] Could not connect to Ollama: {e}")
        return [], {}

    missing = []
    for m in AVAILABLE_MODELS:
        if m.name in models and m.api_name not in available_models:
            missing.append(m.name)

    if missing:
        print(f"\n[WARNING] Models not available: {', '.join(missing)}")
        models = [m for m in models if m not in missing]

    if not models:
        print("\n[ERROR] No models available.")
        return [], {}

    total_tests = len(models) * len(formats) * len(actions_to_test) * runs_per_action

    print(f"\n{'='*70}")
    print(f"Testing {len(models)} models x {len(formats)} formats x {len(actions_to_test)} actions")
    print(f"Total tests: {total_tests}\n")

    all_results = []
    summary = {}
    completed = 0

    for model_name in models:
        model_config = next(m for m in AVAILABLE_MODELS if m.name == model_name)

        for format_type in formats:
            for action_name in actions_to_test:
                if action_name not in PLATFORM_ACTIONS:
                    if verbose:
                        print(f"[SKIP] Unknown action: {action_name}")
                    continue

                action_data = PLATFORM_ACTIONS[action_name]

                for run in range(runs_per_action):
                    completed += 1
                    if verbose:
                        print(f"[{completed}/{total_tests}] {model_name:15} | {format_type:4} | {action_name:20} | Run {run+1}")

                    result = await test_action(
                        client, model_config, action_name, action_data, format_type, run+1, agent,
                    )

                    if result:
                        all_results.append(result)

                    key = f"{model_config.name}_{format_type}_{action_name}"
                    if key not in summary:
                        summary[key] = {"model": model_config.name, "format": format_type, "action": action_name, "total": 0, "success": 0}

                    summary[key]["total"] += 1
                    if result.success:
                        summary[key]["success"] += 1

    print(f"\nCompleted {completed} tests")


def print_final_summary(summary, models, formats, actions_to_test):
    print(f"\n{'='*70}")
    print("FINAL SUMMARY")
    print(f"{'='*70}\n")

    by_action = {}
    for key, stats in summary.items():
        action = key.split("_")[-1]
        if action not in by_action:
            by_action[action] = {}
        by_action[action][key] = stats

    passing = []
    total_tested = 0
    for action, formats_data in by_action.items():
        if any(s["success"] > 0 for s in formats_data.values()):
            passing.append(action)
            break
        total_tested += 1

    pass_rate = len(passing) / total_tested * 100 if total_tested > 0 else 0

    print(f"Actions Tested: {len(by_action)}")
    print(f"Actions Passing: {len(passing)} ({pass_rate:.0f}%)")

    if passing:
        print("\nPassing Actions:")
        for action in sorted(passing):
            print(f"  [OK] {action}")

    failing = set(by_action.keys()) - set(passing)
    if failing:
        print("\nFailing Actions:")
        for action in sorted(failing):
            print(f"  [--] {action}")

    print(f"\n{'='*70}")
    print(f"OVERALL: {pass_rate:.0f}% of actions work")
    print("TARGET: 85%")

    if pass_rate >= 85:
        print("[SUCCESS] Target met!")
    else:
        print("[PARTIAL] Below target.")


def save_results(results, summary, output_dir):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    csv_path = output_path / f"action_tests_{timestamp}.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "action_name", "model_name", "format_type", "run_index",
            "success", "extracted_action", "parse_method",
            "format_score", "latency_ms",
            "prompt_sent", "model_output", "error_message",
        ])

        for r in results:
            output_trunc = r.model_output[:200] if len(r.model_output) > 200 else r.model_output
            error_trunc = r.error_message[:200] if len(r.error_message) > 200 else r.error_message
            prompt_trunc = r.prompt_sent[:200] if len(r.prompt_sent) > 200 else r.prompt_sent

            writer.writerow([
                r.action_name, r.model_name, r.format_type, r.run_index,
                r.success, r.extracted_action, r.parse_method,
                r.format_score, r.latency_ms,
                prompt_trunc, output_trunc, error_trunc,
            ])

    print(f"\n[OK] Results saved to: {csv_path}")

    summary_path = output_path / f"summary_{timestamp}.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"[OK] Summary saved to: {summary_path}")


def main():
    import argparse

    default_actions = ["start_voting", "vote", "finish_meeting", "move_to_location", "speak", "play_cards", "pass"]

    parser = argparse.ArgumentParser(description="Test Social-Sim platform actions")
    parser.add_argument("--actions", nargs="+", help="Specific actions")
    parser.add_argument("--models", nargs="+", help="Models to test (default: all)")
    parser.add_argument("--formats", nargs="+", choices=["json", "xml", "text"], help="Formats (default: json)")
    parser.add_argument("--runs", type=int, default=1, help="Runs per action (default: 1)")
    parser.add_argument("--all-actions", action="store_true", help="Test ALL actions")
    parser.add_argument("--output-dir", type=str, default="test_results/action_tests", help="Output dir")
    parser.add_argument("--quiet", action="store_true", help="Less verbose")

    args = parser.parse_args()

    if args.all_actions:
        actions_to_test = list(PLATFORM_ACTIONS.keys())
    elif args.actions:
        actions_to_test = args.actions
    else:
        actions_to_test = default_actions

    models = args.models if args.models else [m.name for m in AVAILABLE_MODELS]
    formats = args.formats if args.formats else ["json"]

    print("=" * 70)
    print("Social-Sim Platform Action Testing")
    print("=" * 70)
    print("\nConfiguration:")
    print(f"  Models: {', '.join(models)}")
    print(f"  Formats: {', '.join(formats)}")
    print(f"  Actions: {len(actions_to_test)}")
    print(f"  Runs per combo: {args.runs}")

    results, summary = asyncio.run(run_action_tests(
        actions_to_test=actions_to_test,
        models=models,
        formats=formats,
        runs_per_action=args.runs,
        verbose=not args.quiet,
    ))

    print_final_summary(summary, models, formats, actions_to_test)
    save_results(results, summary, args.output_dir)


if __name__ == "__main__":
    main()
