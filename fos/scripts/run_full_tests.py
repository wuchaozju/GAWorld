"""This file runs every automated test suite and prints one final summary.

run_command executes one suite without stopping later suites.
main runs Python, frontend unit, Node helper, and complete Playwright tests.
"""

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys


@dataclass(frozen=True)
class Suite:
    """Describe one test suite command and its working directory."""

    name: str
    command: list[str]
    working_directory: Path


@dataclass(frozen=True)
class SuiteResult:
    """Store one suite name and its process exit code."""

    name: str
    exit_code: int


def run_command(suite: Suite) -> SuiteResult:
    """Run one suite and return its exit code without stopping the runner."""
    print(f"\n{'=' * 72}\nRunning {suite.name}\n{'=' * 72}", flush=True)
    completed = subprocess.run(
        suite.command,
        cwd=suite.working_directory,
        check=False,
    )
    return SuiteResult(suite.name, completed.returncode)


def build_suites(repo_root: Path) -> list[Suite]:
    """Build the ordered list of complete local test commands."""
    frontend = repo_root / "frontend"
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    node = "node.exe" if sys.platform == "win32" else "node"
    return [
        Suite("Python", [sys.executable, "-m", "pytest"], repo_root),
        Suite("Vitest", [npm, "run", "test:run"], frontend),
        Suite(
            "Node load helpers",
            [node, "--test", "tests/load/lib/loadUsers.test.mjs"],
            repo_root,
        ),
        Suite("Playwright", [npm, "run", "test:e2e"], frontend),
    ]


def print_summary(results: list[SuiteResult]) -> None:
    """Print a compact pass or fail line for every completed suite."""
    print(f"\n{'=' * 72}\nFull test summary\n{'=' * 72}")
    for result in results:
        status = "PASS" if result.exit_code == 0 else "FAIL"
        print(f"[{status}] {result.name} (exit {result.exit_code})")


def main() -> int:
    """Run every suite and fail when any suite has a nonzero exit code."""
    repo_root = Path(__file__).resolve().parents[1]
    results = [run_command(suite) for suite in build_suites(repo_root)]
    print_summary(results)
    return 1 if any(result.exit_code != 0 for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
