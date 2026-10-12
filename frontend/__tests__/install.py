#!/usr/bin/env python3
"""
install.py — drop the i18n tests into the Social-Sim repo.

Usage (from FOS root):
    python install.py [--dry-run]

What it does:
  1. Copies test_i18n_backend.py   → tests/test_i18n_backend.py
  2. Copies test_i18n_llm_prompts.py → tests/test_i18n_llm_prompts.py
  3. Copies i18n.comprehensive.test.ts → frontend/__tests__/i18n.comprehensive.test.ts
  4. Adds vitest script to package.json (if not present)
  5. Prints CI snippet to add to GitHub Actions
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).parent
REPO = Path(".")   # run from FOS root


def install(dry: bool = False):
    copies = [
        (HERE / "test_i18n_backend.py",        REPO / "tests" / "test_i18n_backend.py"),
        (HERE / "test_i18n_llm_prompts.py",    REPO / "tests" / "test_i18n_llm_prompts.py"),
        (HERE / "i18n.comprehensive.test.ts",  REPO / "frontend" / "__tests__" / "i18n.comprehensive.test.ts"),
    ]

    for src, dst in copies:
        if not src.exists():
            print(f"  SKIP (source missing): {src}")
            continue
        if dry:
            print(f"  DRY  {src.name} → {dst}")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            print(f"  OK   {src.name} → {dst}")

    # Patch package.json with test:i18n script
    pkg_path = REPO / "frontend" / "package.json"
    if pkg_path.exists() and not dry:
        with open(pkg_path) as f:
            pkg = json.load(f)
        scripts = pkg.setdefault("scripts", {})
        if "test:i18n" not in scripts:
            scripts["test:i18n"] = "vitest run __tests__/i18n.comprehensive.test.ts"
            with open(pkg_path, "w") as f:
                json.dump(pkg, f, indent=2, ensure_ascii=False)
                f.write("\n")
            print("  OK   Added 'test:i18n' script to frontend/package.json")
        else:
            print("  SKIP 'test:i18n' already in package.json")

    print()
    print("=" * 60)
    print("DONE. Run the tests:")
    print()
    print("  # Python backend tests")
    print("  pytest tests/test_i18n_backend.py tests/test_i18n_llm_prompts.py -v")
    print()
    print("  # Frontend tests")
    print("  cd frontend && npm run test:i18n")
    print()
    print("  # All i18n tests together")
    print("  pytest tests/test_i18n_backend.py tests/test_i18n_llm_prompts.py tests/test_i18n_parity.py -v")
    print()
    print("Add to .github/workflows/ (see CI snippet below):")
    print()
    print(CI_YAML)


CI_YAML = """
# Add to .github/workflows/ci.yml or create .github/workflows/i18n.yml

  i18n-check:
    name: i18n Hardcode Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install Python deps
        run: pip install pytest

      - name: Run Python i18n tests
        run: |
          pytest tests/test_i18n_backend.py \\
                 tests/test_i18n_llm_prompts.py \\
                 tests/test_i18n_parity.py \\
                 -v --tb=short

      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json

      - name: Install frontend deps
        run: cd frontend && npm ci

      - name: Run frontend i18n tests
        run: cd frontend && npm run test:i18n
"""

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Verify we're in the right directory
    if not (REPO / "src" / "fos").exists():
        print("ERROR: Run this script from the FOS root directory.")
        print(f"       (Could not find src/fos/ in {REPO.absolute()})")
        sys.exit(1)

    install(dry=args.dry_run)
