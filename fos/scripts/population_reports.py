#!/usr/bin/env python3
"""
Write the population balance table and topic-leakage screen for Phase 3.

This script reads the six population files in data/populations/ and the
proposal registry, then writes two markdown reports:

- balance_table.md: per-population archetype-cell counts (27 cells), Big Five
  trait means/sds, voting-model counts, and a flag for any cell whose count
  differs by more than 2 agents across populations.
- leakage_screen.md: keyword flags (personas sharing >= 2 distinctive content
  words with a proposal statement), an optional LLM-based stance screen
  (--stance-check), and an optional in-place regeneration of stance-flagged
  bios (--regenerate-stance-flagged).

The leakage screen itself lives in leakage_screen.py; this module builds the
balance table, loads the populations, and orchestrates both reports.

Functions:
- load_populations: read the six population JSON files
- build_balance_table: produce the balance_table.md text
- main: write both reports

By default no LLM calls are made: stance-check and regeneration only run
when the corresponding command-line flag is passed.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

# Ensure the fos package is importable without pip install.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from leakage_screen import write_leakage_screen  # noqa: E402

from persona_blueprint import (  # noqa: E402
    AGE_KEYS,
    POLITICAL_KEYS,
    SECTOR_KEYS,
    VOTING_MODELS,
    cell_key,
)

OUT_DIR = _REPO_ROOT / "data" / "populations"


def load_populations() -> dict[str, dict]:
    """Read the six population JSON files from data/populations."""
    populations: dict[str, dict] = {}
    for path in sorted(OUT_DIR.glob("pop_*.json")):
        with open(path, encoding="utf-8") as f:
            populations[path.stem] = json.load(f)
    return populations


def _cell_counts(populations: dict[str, dict]) -> dict[str, dict[str, int]]:
    """Per-population counts of each of the 27 archetype cells."""
    counts: dict[str, dict[str, int]] = {}
    for pop_id, pop in populations.items():
        counter: Counter[tuple[str, str, str]] = Counter(
            cell_key(agent["archetype_cell"]) for agent in pop["agents"]
        )
        counts[pop_id] = {
            f"{age} | {pol} | {sec}": counter[(age, pol, sec)]
            for age in AGE_KEYS
            for pol in POLITICAL_KEYS
            for sec in SECTOR_KEYS
        }
    return counts


def _big_five_stats(populations: dict[str, dict]) -> dict[str, dict[str, dict[str, float]]]:
    """Per-population mean and sd of each Big Five trait."""
    stats: dict[str, dict[str, dict[str, float]]] = {}
    for pop_id, pop in populations.items():
        stats[pop_id] = {}
        for trait in ("o", "c", "e", "a", "n"):
            values = [agent["big_five"][trait] for agent in pop["agents"]]
            stats[pop_id][trait] = {
                "mean": statistics.mean(values),
                "sd": statistics.pstdev(values),
            }
    return stats


def _voting_model_counts(populations: dict[str, dict]) -> dict[str, Counter[str]]:
    """Per-population count of agents per voting model."""
    counts: dict[str, Counter[str]] = {}
    for pop_id, pop in populations.items():
        counts[pop_id] = Counter(agent["voting_model"] for agent in pop["agents"])
    return counts


def build_balance_table(populations: dict[str, dict]) -> str:
    """Produce the balance_table.md markdown text."""
    cell_counts = _cell_counts(populations)
    trait_stats = _big_five_stats(populations)
    model_counts = _voting_model_counts(populations)
    pop_ids = list(populations.keys())
    trait_names = {"o": "Openness", "c": "Conscientiousness",
                   "e": "Extraversion", "a": "Agreeableness", "n": "Neuroticism"}

    lines: list[str] = []
    lines.append("# Population Balance Table (Phase 3, Step 2)")
    lines.append("")
    lines.append(f"Generated from {len(populations)} populations of "
                 f"{len(next(iter(populations.values()))['agents'])} agents each "
                 f"(27-cell grid: age x political view x work sector).")
    lines.append("")

    # 1. Archetype cell counts
    lines.append("## 1. Archetype cell counts (agents per cell, per population)")
    lines.append("")
    header = ["Cell (age | political | sector)"] + pop_ids + ["max-min", "flag"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    for cell in cell_counts[pop_ids[0]]:
        row = [cell]
        values = [cell_counts[pop_id][cell] for pop_id in pop_ids]
        row.extend(str(v) for v in values)
        spread = max(values) - min(values)
        row.append(str(spread))
        row.append("⚠ FLAG" if spread > 2 else "")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("Cells whose count differs by more than 2 agents across "
                 "populations are flagged with ⚠ FLAG.")
    lines.append("")

    # 2. Big Five trait means and sds
    lines.append("## 2. Big Five trait means and standard deviations (per population)")
    lines.append("")
    for trait, label in trait_names.items():
        lines.append(f"### {label} (trait `{trait}`)")
        lines.append("")
        header = ["Population", "mean", "sd"]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "---|" * len(header))
        for pop_id in pop_ids:
            lines.append(f"| {pop_id} | {trait_stats[pop_id][trait]['mean']:.2f} "
                         f"| {trait_stats[pop_id][trait]['sd']:.2f} |")
        lines.append("")

    # 3. Voting model counts
    lines.append("## 3. Voting model counts (per population)")
    lines.append("")
    model_names = [m for m in VOTING_MODELS if m in model_counts[pop_ids[0]]]
    header = ["Population"] + model_names + ["total"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    for pop_id in pop_ids:
        counts = model_counts[pop_id]
        row = [pop_id] + [str(counts[m]) for m in model_names] + [str(sum(counts.values()))]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    """Write balance_table.md and leakage_screen.md."""
    parser = argparse.ArgumentParser(description="Write Phase-3 population reports.")
    parser.add_argument(
        "--stance-check",
        action="store_true",
        help="Run the LLM-based stance screen (makes LLM calls).",
    )
    parser.add_argument(
        "--regenerate-stance-flagged",
        action="store_true",
        help="Regenerate stance-flagged bios in place (makes LLM calls).",
    )
    args = parser.parse_args()

    populations = load_populations()
    balance = build_balance_table(populations)
    (OUT_DIR / "balance_table.md").write_text(balance, encoding="utf-8")

    stats = write_leakage_screen(
        populations,
        OUT_DIR,
        stance_check=args.stance_check,
        regenerate=args.regenerate_stance_flagged,
    )

    print(f"[reports] wrote {OUT_DIR / 'balance_table.md'}")
    print(f"[reports] wrote {OUT_DIR / 'leakage_screen.md'}")
    print(f"[reports] keyword-flagged personas: {stats['keyword_flags']}")
    if stats["stance_flags"] is not None:
        print(f"[reports] stance-flagged personas: {stats['stance_flags']}")
    if stats["regenerations"]:
        print(f"[reports] regenerated personas: {stats['regenerations']}")


if __name__ == "__main__":
    main()
