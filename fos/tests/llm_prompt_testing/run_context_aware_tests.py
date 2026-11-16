"""
Context-Aware Action Testing for Social-Sim Platform

Tests real platform actions with context-aware prompts that match
actual use cases. Uses the real XML action format from semantic_actions.py.

Key features:
- Short prompts for 3-4B models
- Context-aware scenarios (not generic "give back this action")
- Real XML format: <Action name="action"><param>value</param></Action>
- Tests all parameter handling scenarios

Usage:
    python -m tests.llm_prompt_testing.run_context_aware_tests
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

sys.path.insert(0, "tests/llm_prompt_testing")

from tests.llm_prompt_testing.action_parser import parse_action
from tests.llm_prompt_testing.agents import ARCHETYPAL_AGENTS
from tests.llm_prompt_testing.config import AVAILABLE_MODELS
from tests.llm_prompt_testing.ollama_client import OllamaClient, ChatMessage


# ============================================================================
# Context-Aware Action Definitions
# ============================================================================

CONTEXT_AWARE_ACTIONS = {
    # Council actions with context
    "start_voting": {
        "name": "start_voting",
        "description": "Initiate a voting round on a proposal",
        "instruction": "Use when you want the council to vote on something",
        "parameters": {"title": "The proposal title"},
        "xml_example": '<Action name="start_voting"><title>Budget Approval</title></Action>',
        "scenarios": [
            ("You are in a council meeting. You want to vote on the budget.",
             "start_voting", {"title": "Budget Approval"}),
            ("The council needs to decide on the new policy.",
             "start_voting", {"title": "New Policy"}),
        ],
    },

    "vote": {
        "name": "vote",
        "description": "Cast your vote (yes/no/abstain)",
        "instruction": "Use when a vote is in progress",
        "parameters": {"vote": "Your vote: yes/no/abstain"},
        "xml_example": '<Action name="vote"><vote>yes</vote></Action>',
        "scenarios": [
            ("A vote is happening on the budget. You support it.",
             "vote", {"vote": "yes"}),
            ("The council is voting. You disagree with the proposal.",
             "vote", {"vote": "no"}),
        ],
    },

    "finish_meeting": {
        "name": "finish_meeting",
        "description": "Conclude the council meeting",
        "instruction": "Use when the meeting is complete",
        "parameters": {},
        "xml_example": '<Action name="finish_meeting"/>',
        "scenarios": [
            ("The meeting agenda is complete. Everyone has voted.",
             "finish_meeting", {}),
        ],
    },

    # Village/location actions
    "move_to_location": {
        "name": "move_to_location",
        "description": "Move to a different location",
        "instruction": "Use when you want to go somewhere",
        "parameters": {"location": "Where you want to go"},
        "xml_example": '<Action name="move_to_location"><location>market</location></Action>',
        "scenarios": [
            ("You are at home. You want to buy supplies.",
             "move_to_location", {"location": "market"}),
            ("You need to rest at your house.",
             "move_to_location", {"location": "home"}),
            ("You want to visit the shrine.",
             "move_to_location", {"location": "shrine"}),
        ],
    },

    "look_around": {
        "name": "look_around",
        "description": "Observe your surroundings",
        "instruction": "Use when you want to see what's around you",
        "parameters": {},
        "xml_example": '<Action name="look_around"/>',
        "scenarios": [
            ("You just arrived at a new place. You want to see what's here.",
             "look_around", {}),
        ],
    },

    # Communication actions
    "speak": {
        "name": "speak",
        "description": "Say something to everyone nearby",
        "instruction": "Use when you want to communicate with others",
        "parameters": {"message": "What you want to say"},
        "xml_example": '<Action name="speak"><message>Hello everyone</message></Action>',
        "scenarios": [
            ("You arrive at the market. You want to greet others.",
             "speak", {"message": "Hello everyone!"}),
            ("You agree with what was said.",
             "speak", {"message": "I agree with that."}),
        ],
    },

    "talk_to": {
        "name": "talk_to",
        "description": "Speak directly to a specific person",
        "instruction": "Use when you want to have a private conversation",
        "parameters": {"target": "Who you want to talk to"},
        "xml_example": '<Action name="talk_to"><target>John</target></Action>',
        "scenarios": [
            ("You see John nearby. You want to ask him something.",
             "talk_to", {"target": "John"}),
            ("You need to speak with the merchant.",
             "talk_to", {"target": "merchant"}),
        ],
    },

    # Game actions
    "play_cards": {
        "name": "play_cards",
        "description": "Play cards in a card game",
        "instruction": "Use when it's your turn in a card game",
        "parameters": {"cards": "The cards you want to play"},
        "xml_example": '<Action name="play_cards"><cards>A,K,2,3</cards></Action>',
        "scenarios": [
            ("It's your turn. You have good cards.",
             "play_cards", {"cards": "A,K,2,3"}),
            ("You want to play these cards.",
             "play_cards", {"cards": "Q,J,10"}),
        ],
    },

    "pass": {
        "name": "pass",
        "description": "Pass your turn in a game",
        "instruction": "Use when you don't want to play this round",
        "parameters": {},
        "xml_example": '<Action name="pass"/>',
        "scenarios": [
            ("It's your turn but your cards are bad.",
             "pass", {}),
        ],
    },

    # Werewolf game actions
    "vote_lynch": {
        "name": "vote_lynch",
        "description": "Vote to eliminate a suspected werewolf",
        "instruction": "Use during day voting in werewolf game",
        "parameters": {"target": "Who you want to vote against"},
        "xml_example": '<Action name="vote_lynch"><target>John</target></Action>',
        "scenarios": [
            ("You suspect John is a werewolf. Day voting has started.",
             "vote_lynch", {"target": "John"}),
            ("You think Sarah is acting suspicious.",
             "vote_lynch", {"target": "Sarah"}),
        ],
    },

    # RAG/Knowledge actions
    "query_knowledge": {
        "name": "query_knowledge",
        "description": "Ask about something you want to know",
        "instruction": "Use when you need information",
        "parameters": {"query": "What you want to know"},
        "xml_example": '<Action name="query_knowledge"><query>How do I play?</query></Action>',
        "scenarios": [
            ("You don't know how to play this game.",
             "query_knowledge", {"query": "How do I play this game?"}),
            ("You want to know about the village rules.",
             "query_knowledge", {"query": "What are the village rules?"}),
        ],
    },
}


@dataclass
class ContextTestResult:
    """Result of testing an action with context."""
    action_name: str
    model_name: str
    format_type: str
    scenario_index: int
    success: bool
    extracted_action: Optional[str]
    expected_action: str
    parse_method: str
    format_score: int
    latency_ms: int
    scenario_text: str = ""
    model_output: str = ""
    error_message: str = ""


# ============================================================================
# Prompt Builders with Real XML Format
# ============================================================================

def build_context_prompt(
    action_name: str,
    action_data: dict,
    agent,
    format_type: str,
) -> tuple[str, str]:
    """
    Build a context-aware prompt with real XML format.

    Returns:
        (system_prompt, user_message)
    """
    description = action_data.get("description", "")
    instruction = action_data.get("instruction", "")
    xml_example = action_data.get("xml_example", "")

    # Available actions list (just this one for focused testing)
    actions_list = f'"{action_name}"'

    if format_type == "xml":
        # Real platform XML format
        system_prompt = f"""You are {agent.name}.

{description}
Use when: {instruction}

Available: {actions_list}
Respond with XML: {xml_example}"""
        system_prompt = system_prompt.strip()

    elif format_type == "json":
        # JSON format (alternative)
        param_info = ""
        if action_data.get("parameters"):
            params = action_data["parameters"]
            param_info = "\\nParameters: " + json.dumps(params)

        system_prompt = f"""You are {agent.name}.

{description}{param_info}
Available: {actions_list}
Respond with JSON: {{"action": "{action_name}", "parameters": {{...}}}}"""
        system_prompt = system_prompt.strip()

    else:  # text
        system_prompt = f"""You are {agent.name}.

{description}
Available: {actions_list}
Respond with action name only."""
        system_prompt = system_prompt.strip()

    return system_prompt, ""


def build_scenario_prompt(
    scenario: str,
    action_name: str,
    action_data: dict,
    format_type: str,
) -> str:
    """Build user message with scenario context."""
    return scenario


# ============================================================================
# Test Execution
# ============================================================================

async def test_context_action(
    client: OllamaClient,
    model_config,
    action_name: str,
    action_data: dict,
    scenario_index: int,
    format_type: str,
    agent,
) -> ContextTestResult:
    """Test a single action with context."""
    api_name = model_config.api_name
    model_name = model_config.name

    scenario, expected_action, expected_params = action_data["scenarios"][scenario_index]

    system_prompt, _ = build_context_prompt(action_name, action_data, agent, format_type)
    user_message = scenario

    try:
        start_time = time.time()

        response = client.chat_completion(
            messages=[
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_message),
            ],
            model=api_name,
            temperature=0.7,
            max_tokens=100,
        )

        latency_ms = int((time.time() - start_time) * 1000)
        output = response.content

        # Parse output
        parse_result = parse_action(output, [action_name])

        return ContextTestResult(
            action_name=action_name,
            model_name=model_name,
            format_type=format_type,
            scenario_index=scenario_index,
            success=parse_result.success and parse_result.action == action_name,
            extracted_action=parse_result.action,
            expected_action=expected_action,
            parse_method=parse_result.parse_method,
            format_score=parse_result.format_score,
            latency_ms=latency_ms,
            scenario_text=scenario,
            model_output=output,
            error_message="",
        )

    except Exception as e:
        return ContextTestResult(
            action_name=action_name,
            model_name=model_name,
            format_type=format_type,
            scenario_index=scenario_index,
            success=False,
            extracted_action=None,
            expected_action=action_name,
            parse_method="failed",
            format_score=0,
            latency_ms=0,
            scenario_text=scenario,
            model_output="",
            error_message=str(e)[:100],
        )


async def run_context_tests(
    actions_to_test: List[str],
    models: List[str],
    formats: List[str],
    verbose: bool = True,
) -> tuple[List[ContextTestResult], dict]:
    """Run context-aware tests."""
    client = OllamaClient()
    agent = ARCHETYPAL_AGENTS.get("Analyst", ARCHETYPAL_AGENTS["Authority"])

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

    # Count total scenarios
    total_scenarios = sum(
        len(CONTEXT_AWARE_ACTIONS[a]["scenarios"])
        for a in actions_to_test
        if a in CONTEXT_AWARE_ACTIONS
    )
    total_tests = len(models) * len(formats) * total_scenarios

    print(f"\n{'='*70}")
    print("Context-Aware Action Testing")
    print(f"Models: {len(models)} | Formats: {len(formats)} | Actions: {len(actions_to_test)}")
    print(f"Total scenarios: {total_scenarios} | Total tests: {total_tests}\n")

    all_results = []
    summary = {}
    completed = 0

    for model_name in models:
        model_config = next((m for m in AVAILABLE_MODELS if m.name == model_name), None)
        if not model_config:
            continue

        for format_type in formats:
            for action_name in actions_to_test:
                if action_name not in CONTEXT_AWARE_ACTIONS:
                    if verbose:
                        print(f"[SKIP] Unknown action: {action_name}")
                    continue

                action_data = CONTEXT_AWARE_ACTIONS[action_name]
                scenarios = action_data["scenarios"]

                for scenario_idx, scenario in enumerate(scenarios):
                    completed += 1
                    if verbose:
                        print(f"[{completed}/{total_tests}] {model_name:15} | {format_type:4} | {action_name:20} | Scenario {scenario_idx+1}")

                    result = await test_context_action(
                        client, model_config, action_name, action_data,
                        scenario_idx, format_type, agent,
                    )
                    all_results.append(result)

                    # Update summary
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


# ============================================================================
# Reporting
# ============================================================================

def print_context_summary(summary: dict, models: List[str], formats: List[str]) -> None:
    """Print formatted summary of context-aware tests."""
    print(f"\n{'='*70}")
    print("CONTEXT-AWARE TEST SUMMARY")
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

    # By format
    print(f"\n{'='*70}")
    print("Success by Format:")
    by_format = {"json": {"total": 0, "success": 0}, "xml": {"total": 0, "success": 0}, "text": {"total": 0, "success": 0}}
    for stats in summary.values():
        fmt = stats["format"]
        by_format[fmt]["total"] += stats["total"]
        by_format[fmt]["success"] += stats["success"]

    for fmt, data in by_format.items():
        if data["total"] > 0:
            rate = data["success"] / data["total"] * 100
            print(f"  {fmt:4}: {data['success']}/{data['total']} ({rate:.0f}%)")

    print(f"\n{'='*70}")
    print(f"OVERALL: {pass_rate:.0f}% of actions work")
    print("TARGET: 85%")

    if pass_rate >= 85:
        print("[SUCCESS] Target met!")
    else:
        print("[PARTIAL] Below target.")


def save_context_results(results: List[ContextTestResult], summary: dict, output_dir: str) -> None:
    """Save context-aware test results."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    csv_path = output_path / f"context_tests_{timestamp}.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "action_name", "model_name", "format_type", "scenario_index",
            "success", "extracted_action", "expected_action", "parse_method",
            "format_score", "latency_ms", "scenario_text",
            "model_output", "error_message",
        ])

        for r in results:
            output_trunc = r.model_output[:200] if len(r.model_output) > 200 else r.model_output
            scenario_trunc = r.scenario_text[:100] if len(r.scenario_text) > 100 else r.scenario_text

            writer.writerow([
                r.action_name,
                r.model_name,
                r.format_type,
                r.scenario_index,
                r.success,
                r.extracted_action or "",
                r.expected_action,
                r.parse_method,
                r.format_score,
                r.latency_ms,
                scenario_trunc,
                output_trunc,
                r.error_message[:100] if r.error_message else "",
            ])

    print(f"\n[OK] Results saved to: {csv_path}")

    summary_path = output_path / f"context_summary_{timestamp}.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"[OK] Summary saved to: {summary_path}")


# ============================================================================
# Main
# ============================================================================

def main():
    import argparse

    default_actions = list(CONTEXT_AWARE_ACTIONS.keys())

    parser = argparse.ArgumentParser(description="Context-aware action testing")
    parser.add_argument("--actions", nargs="+", help="Specific actions to test")
    parser.add_argument("--models", nargs="+", help="Models to test (default: all)")
    parser.add_argument("--formats", nargs="+", choices=["json", "xml", "text"], help="Formats (default: xml)")
    parser.add_argument("--output-dir", type=str, default="test_results/context_tests", help="Output dir")
    parser.add_argument("--quiet", action="store_true", help="Less verbose")

    args = parser.parse_args()

    actions_to_test = args.actions if args.actions else default_actions
    models = args.models if args.models else [m.name for m in AVAILABLE_MODELS]
    formats = args.formats if args.formats else ["xml"]  # Default to XML (real platform format)

    print("=" * 70)
    print("Social-Sim Context-Aware Action Testing")
    print("=" * 70)
    print("\nConfiguration:")
    print(f"  Models: {', '.join(models)}")
    print(f"  Formats: {', '.join(formats)}")
    print(f"  Actions: {len(actions_to_test)}")

    results, summary = asyncio.run(run_context_tests(
        actions_to_test=actions_to_test,
        models=models,
        formats=formats,
        verbose=not args.quiet,
    ))

    if results:
        print_context_summary(summary, models, formats)
        save_context_results(results, summary, args.output_dir)


if __name__ == "__main__":
    main()
