# This file manually checks coordination fixes and lets pytest report them clearly.
# build_context_manager creates a small memory of agent actions for the checks.
# test_fix_1_visibility_filtering checks that agents only see neighbor actions.
# test_fix_2_no_score_display checks that hidden scores stay hidden.
# check_debug_log_format checks that debug logs use the expected readable layout.
# run_check runs one check and turns its result into a simple pass or fail value.
# main runs these checks from the command line and reports a simple summary.
from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, "src")

from fos.core.experiment.information_model import InformationModel
from fos.core.experiment.round_context import RoundContextManager


def build_context_manager(agent_names: list[str]) -> RoundContextManager:
    """Create a context manager that hides scores and only shows nearby actions."""
    info_model = InformationModel(
        scope_type="neighborhood",
        include_scores=False,
        recent_window=5,
    )

    return RoundContextManager(
        information_model=info_model,
        all_agent_names=agent_names,
    )


def test_fix_1_visibility_filtering() -> None:
    """Fix 1: Context shows only neighbors, not every agent."""
    print("\n=== Fix 1: Visibility Filtering ===")

    context_manager = build_context_manager(["NodeA", "NodeB", "NodeC"])

    context_manager.record_action(
        agent_name="NodeA",
        action_name="choose_color",
        parameters={"color": "red"},
        round_num=1,
        summary="NodeA chose red",
        observed_by=["NodeA", "NodeB"],
        payoff=0,
    )
    context_manager.record_action(
        agent_name="NodeB",
        action_name="choose_color",
        parameters={"color": "blue"},
        round_num=1,
        summary="NodeB chose blue",
        observed_by=["NodeA", "NodeB", "NodeC"],
        payoff=0,
    )
    context_manager.record_action(
        agent_name="NodeC",
        action_name="choose_color",
        parameters={"color": "green"},
        round_num=1,
        summary="NodeC chose green",
        observed_by=["NodeB", "NodeC"],
        payoff=0,
    )

    context_a = context_manager.get_context_for_agent("NodeA", agent_score=None)

    print(f"Context for NodeA:\n{context_a}\n")

    assert "NodeB" in context_a, "NodeA should see neighbor NodeB"
    assert "NodeC" not in context_a, "NodeA should not see non-neighbor NodeC"
    print("PASS: NodeA sees only neighbor NodeB, not NodeC")


def test_fix_2_no_score_display() -> None:
    """Fix 2: No 'My score' line appears when scores are hidden."""
    print("\n=== Fix 2: No Score Display ===")

    context_manager = build_context_manager(["Node1", "Node2"])

    context_manager.record_action(
        agent_name="Node1",
        action_name="coordinate",
        parameters={"color": "red"},
        round_num=1,
        summary="Node1 chose red",
        observed_by=["Node1", "Node2"],
        payoff=0,
    )
    context_manager.record_action(
        agent_name="Node2",
        action_name="coordinate",
        parameters={"color": "blue"},
        round_num=1,
        summary="Node2 chose blue",
        observed_by=["Node1", "Node2"],
        payoff=0,
    )

    context = context_manager.get_context_for_agent("Node1", agent_score=0)

    print(f"Context for Node1:\n{context}\n")

    assert "My score" not in context, "Score appears when include_scores=False"
    print("PASS: No score displayed when include_scores=False")


def check_debug_log_format() -> bool | None:
    """Fix 3: Debug log has a sequential format instead of a nested one."""
    print("\n=== Fix 3: Debug Log Format ===")

    log_files = sorted(Path("test_results").glob("experiment_debug_*.txt"))

    if not log_files:
        print("SKIP: No debug log files found")
        return None

    latest_log = log_files[-1]
    print(f"Checking latest log: {latest_log}")

    content = latest_log.read_text(encoding="utf-8")
    agent_count = sum(1 for line in content.splitlines() if line.startswith("## AGENT:"))

    assert "## AGENT:" in content, "Debug log should include agent headers"
    assert "## ROUND:" in content, "Debug log should include round headers"
    assert "---" in content and "===" in content, "Debug log should include section markers"
    assert agent_count > 0, "Debug log should include at least one agent entry"
    print("PASS: Debug log has sequential format")
    return True


def run_check(name: str, check: Callable[[], object]) -> tuple[str, bool]:
    """Run one manual check and record whether it passed."""
    try:
        check()
    except AssertionError as error:
        print(f"FAIL in {name}: {error}")
        return name, False
    return name, True


def main() -> int:
    """Run all manual verification checks."""
    print("=" * 60)
    print("MANUAL VERIFICATION OF COORDINATION GAME FIXES")
    print("=" * 60)

    results = [
        run_check("Fix 1: Visibility Filtering", test_fix_1_visibility_filtering),
        run_check("Fix 2: No Score Display", test_fix_2_no_score_display),
    ]

    debug_result = check_debug_log_format()
    if debug_result is not None:
        results.append(("Fix 3: Debug Log Format", debug_result))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\nALL FIXES VERIFIED!")
        return 0

    print("\nSOME FIXES FAILED!")
    return 1


if __name__ == "__main__":
    sys.exit(main())
