#!/usr/bin/env python3
"""GAWorld → FOS AI Scientist Prompt Generator (CLI entry point).

Reads GAWorld simulation output and generates a structured research observation
prompt that can be pasted into FOS' AI Scientist to design a follow-up experiment.

All core logic lives in ``gaworld.integrations.fos_prompt``; this script is
a thin CLI wrapper.

Usage:
    python scripts/gaworld-to-fos-prompt.py --help
    python scripts/gaworld-to-fos-prompt.py --manual "Agent X did Y"
    python scripts/gaworld-to-fos-prompt.py --manual-file observations.txt
    python scripts/gaworld-to-fos-prompt.py --output-dir output/
    python scripts/gaworld-to-fos-prompt.py --output-dir output/ --hint "Look for social withdrawal"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# Add repo root to sys.path so gaworld is importable from scripts/
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gaworld.integrations.fos_prompt import (
    generate_fos_prompt,
    generate_manual_fos_prompt,
    generate_english_summary,
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a structured research observation prompt for FOS AI Scientist "
            "from GAWorld simulation output or manual observation text."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --manual \"Agent X showed reduced social interaction after policy Y\"\n"
            "  %(prog)s --manual-file observations.txt\n"
            "  %(prog)s --output-dir /path/to/gaworld/output\n"
            "  %(prog)s --output-dir output/ --hint \"Look for economic anxiety patterns\"\n"
        ),
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--manual",
        type=str,
        default=None,
        help="Manual observation text to wrap for FOS AI Scientist.",
    )
    mode.add_argument(
        "--manual-file",
        type=str,
        default=None,
        help="Path to a text file containing the observation.",
    )
    mode.add_argument(
        "--output-dir",
        "--output",
        type=str,
        default=None,
        dest="output_dir",
        help=(
            "Path to a GAWorld simulation output directory. The script reads "
            "profiles.csv, actions, diaries, and state data from this directory."
        ),
    )

    parser.add_argument(
        "--hint",
        type=str,
        default=None,
        help=(
            "Optional focus hint for the LLM analysis (auto mode only). "
            "E.g. --hint 'Look for social withdrawal patterns'"
        ),
    )

    parser.add_argument(
        "--max-profiles",
        type=int,
        default=10,
        help="Maximum number of agent profiles to include in auto mode (default: 10).",
    )

    parser.add_argument(
        "--english",
        action="store_true",
        help=("Print an English summary of the simulation output (translates Chinese "
               "data) before the FOS prompt."),
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.english and not args.output_dir:
        print("Error: --english requires --output-dir.", file=sys.stderr)
        sys.exit(1)

    # ---- Manual mode ----
    if args.manual is not None:
        prompt = generate_manual_fos_prompt(args.manual, hint=args.hint)
        print(prompt)
        return

    if args.manual_file is not None:
        path = Path(args.manual_file)
        if not path.is_file():
            print(f"Error: manual file not found: {path}", file=sys.stderr)
            sys.exit(1)
        observation = path.read_text(encoding="utf-8").strip()
        prompt = generate_manual_fos_prompt(observation, hint=args.hint)
        print(prompt)
        return

    # ---- Auto mode ----
    output_dir = Path(args.output_dir)
    if not output_dir.is_dir():
        print(f"Error: output directory not found: {output_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"[gaworld-to-fos] Auto mode: reading GAWorld output from {output_dir.resolve()}", file=sys.stderr)
    print(f"[gaworld-to-fos] Hint: {args.hint or '(none)'}", file=sys.stderr)

    result = generate_fos_prompt(
        output_dir=output_dir,
        hint=args.hint,
        english=args.english,
        max_profiles=args.max_profiles,
    )

    if result["error"]:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    # ---- English summary (optional) ----
    if args.english and result.get("summary"):
        print("\n" + "=" * 60)
        print("  ENGLISH SUMMARY OF SIMULATION OUTPUT")
        print("=" * 60 + "\n")
        print(result["summary"])
        print("\n" + "=" * 60 + "\n")

    # Final prompt goes to stdout
    print(result["prompt"])


if __name__ == "__main__":
    main()
