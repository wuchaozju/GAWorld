"""Tests that pin the repository .gitignore ignore policy.

These tests check which paths git would ignore if the path were created fresh
in the repository. They run `git check-ignore --no-index` from the repository
root. The --no-index flag is important: it evaluates the ignore rules alone,
without considering whether a path is already tracked, so the tests pin the
ignore policy rather than the current tracked state.

The test file has three kinds of tests:

- test_path_is_ignored: generated or derived files (run outputs, artifacts,
  caches, venvs, scratch files) must be excluded by the ignore rules.
- test_path_is_not_ignored: source, config and reference data files must never
  be excluded by accident, no matter how broad a rule looks.
- test_gitignore_has_no_duplicate_patterns: the .gitignore must not repeat the
  same ignore pattern more than once. Duplicate patterns are a symptom of
  accretion: they hide which rule actually matters and invite contradictions.

The _is_ignored helper runs git check-ignore for a single path and reports
whether the rules would exclude it. Every other function in this file is a
test case that uses that helper.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Paths that the ignore policy MUST ignore: generated, derived, cached or
# large regenerable files. Each entry is (path, human-readable reason).
IGNORED_CASES = [
    ("runs/anything/foo.json", "run outputs under runs/ must be ignored"),
    ("artifacts/x.csv", "artifacts/ must be ignored"),
    ("results/y.json", "results/ must be ignored"),
    ("extracted_users/u.csv", "extracted user data must be ignored"),
    ("personas/p.json", "persona data must be ignored"),
    ("venv/lib/x", "venv must be ignored"),
    (".venv/lib/x", "hidden venv must be ignored"),
    ("data/experiment_state.db", "experiment state database must be ignored"),
    ("data/experiment_state.db-wal", "experiment state WAL file must be ignored"),
    ("frontend/node_modules/x.js", "frontend node_modules must be ignored"),
    ("__pycache__/x.pyc", "python bytecode cache must be ignored"),
    (".pytest_cache/x", "pytest cache must be ignored"),
    ("scratch.csv", "scratch csv at repo root must be ignored"),
    ("downloads.tar.zst", "zstd archives must be ignored"),
]

# Paths that must stay tracked: source, config and reference data. Each entry
# is (path, human-readable reason).
TRACKED_CRITICAL_CASES = [
    ("data/configs/run_matrix.csv", "run matrix config must stay tracked"),
    ("data/populations/pop_a1.json", "population data must stay tracked"),
    ("data/configs/network_configs.json", "network configs must stay tracked"),
    ("data/proposals/proposals.json", "proposals must stay tracked"),
    ("src/fos/__init__.py", "source package must stay tracked"),
    ("tests/test_gitignore_policy.py", "test files must stay tracked"),
    ("README.md", "readme must stay tracked"),
    ("frontend/package.json", "frontend package.json must stay tracked"),
    (".gitignore", "the gitignore itself must stay tracked"),
]


def _is_ignored(relative_path: str) -> bool:
    """Return True when git's ignore rules would exclude relative_path."""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "check-ignore",
            "--no-index",
            "-q",
            "--",
            relative_path,
        ],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


@pytest.mark.parametrize("relative_path,reason", IGNORED_CASES)
def test_path_is_ignored(relative_path: str, reason: str) -> None:
    """Generated and derived paths must be excluded by the ignore policy."""
    assert _is_ignored(relative_path), (
        f"{relative_path} should be ignored ({reason}), but the current "
        ".gitignore does not exclude it"
    )


@pytest.mark.parametrize("relative_path,reason", TRACKED_CRITICAL_CASES)
def test_path_is_not_ignored(relative_path: str, reason: str) -> None:
    """Source, config and reference paths must never be excluded by accident."""
    assert not _is_ignored(relative_path), (
        f"{relative_path} must stay tracked ({reason}), but the current "
        ".gitignore excludes it"
    )


def test_gitignore_has_no_duplicate_patterns() -> None:
    """The .gitignore must not repeat the same ignore pattern twice."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    normalized: list[str] = []
    for raw_line in gitignore.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        normalized.append(stripped)
    duplicates = {pattern for pattern in normalized if normalized.count(pattern) > 1}
    assert not duplicates, (
        "duplicate ignore patterns found in .gitignore: "
        + ", ".join(sorted(duplicates))
    )
