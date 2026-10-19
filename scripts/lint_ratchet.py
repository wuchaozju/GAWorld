"""Lint ratchet: changed files may not get worse; the repo total may only go down.

The repository carries a backlog of ruff findings and unformatted files that
predates CI enforcement, so ``ruff check .`` / ``ruff format --check .`` fail
on every run and say nothing about the change in hand. This script checks
only what a change touches, against the same file on the base branch:

* a changed Python file may not have more ruff findings than it had on the
  base (a new file must have none);
* a changed file that was formatted on the base must still be formatted, and
  a new file must be formatted (old unformatted files are not forced through
  ``ruff format`` just because one line changed);
* the whole-repo totals may not rise above ``scripts/lint_baseline.json``
  (checked only under the ruff version the baseline was recorded with, since
  a new ruff can add rules); when they fall, ``--update-baseline`` records it.

Usage::

    python scripts/lint_ratchet.py --base origin/main      # CI: compare with the target branch
    python scripts/lint_ratchet.py                         # locally: against HEAD (uncommitted work)
    python scripts/lint_ratchet.py --update-baseline       # after cleaning up, lower the totals
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

#: The repository checked (``--root`` points elsewhere, for tests).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUFF = [sys.executable, "-m", "ruff"]


def _baseline_path() -> str:
    return os.path.join(ROOT, "scripts", "lint_baseline.json")


def _run(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, input=stdin, capture_output=True, text=True, check=False)


def _git(*args: str) -> str:
    out = _run(["git", "--no-optional-locks", *args])
    if out.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def _ruff_version() -> str:
    return _run([*RUFF, "--version"]).stdout.strip()


def _findings(path: str, source: str | None = None) -> int:
    """ruff findings for *path* (its working-tree file, or *source* as that path)."""
    args = [*RUFF, "check", "--force-exclude", "--output-format", "json"]
    out = (
        _run([*args, path]) if source is None else _run([*args, "--stdin-filename", path, "-"], stdin=source)
    )
    try:
        return len(json.loads(out.stdout or "[]"))
    except ValueError as exc:
        raise SystemExit(f"ruff check {path}: {out.stderr.strip() or exc}") from exc


def _formatted(path: str, source: str | None = None) -> bool:
    args = [*RUFF, "format", "--check", "--force-exclude"]
    out = (
        _run([*args, path]) if source is None else _run([*args, "--stdin-filename", path, "-"], stdin=source)
    )
    return out.returncode == 0


def changed_files(base: str) -> tuple[list[str], str]:
    """Python files added or modified since *base* (committed or not), plus untracked ones."""
    merge_base = _git("merge-base", base, "HEAD").strip()
    names = _git("diff", "--name-only", "--diff-filter=AMR", merge_base, "--", "*.py").split()
    names += _git("ls-files", "--others", "--exclude-standard", "--", "*.py").split()
    return sorted({n for n in names if os.path.isfile(os.path.join(ROOT, n))}), merge_base


def base_source(merge_base: str, path: str) -> str | None:
    out = _run(["git", "--no-optional-locks", "show", f"{merge_base}:{path}"])
    return out.stdout if out.returncode == 0 else None


def totals() -> dict[str, int]:
    check = _run([*RUFF, "check", ".", "--output-format", "json"])
    fmt = _run([*RUFF, "format", "--check", "."])
    found = re.search(r"(\d+) files? would be reformatted", fmt.stdout + fmt.stderr)
    unformatted = int(found.group(1)) if found else 0
    return {"ruff_findings": len(json.loads(check.stdout or "[]")), "unformatted_files": unformatted}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="HEAD", help="ref to compare with (CI: the target branch)")
    parser.add_argument("--update-baseline", action="store_true", help="record the current totals")
    parser.add_argument("--root", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.root:
        global ROOT
        ROOT = os.path.abspath(args.root)

    version = _ruff_version()
    now = totals()
    if args.update_baseline:
        with open(_baseline_path(), "w", encoding="utf-8") as fh:
            json.dump({"ruff": version, **now}, fh, indent=2)
            fh.write("\n")
        print(f"baseline: {now} ({version})")
        return 0

    problems: list[str] = []
    files, merge_base = changed_files(args.base)
    for path in files:
        before = base_source(merge_base, path)
        after_n = _findings(path)
        before_n = _findings(path, before) if before is not None else 0
        if after_n > before_n:
            problems.append(
                f"{path}: {after_n} ruff findings, was {before_n} — fix the new ones (ruff check {path})"
            )
        if (before is None or _formatted(path, before)) and not _formatted(path):
            problems.append(f"{path}: not formatted — ruff format {path}")
    print(f"lint ratchet: {len(files)} changed Python file(s) checked against {args.base} ({merge_base[:8]})")

    try:
        with open(_baseline_path(), encoding="utf-8") as fh:
            baseline = json.load(fh)
    except (OSError, ValueError):
        baseline = {}
    for key, value in now.items():
        recorded = baseline.get(key)
        if recorded is None:
            continue
        print(f"  {key}: {value} (baseline {recorded})")
        if value > recorded and baseline.get("ruff") == version:
            problems.append(f"repo {key} rose from {recorded} to {value}")
        elif value < recorded:
            print("  ↳ down — lower the baseline: python scripts/lint_ratchet.py --update-baseline")
    if baseline.get("ruff") and baseline.get("ruff") != version:
        print(f"  (baseline recorded with {baseline['ruff']}, running {version}: totals not enforced)")

    for line in problems:
        print(f"✗ {line}")
    print("✓ nothing got worse" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
