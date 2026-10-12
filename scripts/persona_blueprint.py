#!/usr/bin/env python3
"""
Shared archetype blueprint for the six Phase-3 persona populations.

This module holds everything about the 100-slot blueprint that is identical
across the six populations: the 27-cell archetype grid with its canonical
labels, the deterministic cell quota, the voting-model assignment, and the
hash of the frozen blueprint. It is imported by generate_persona_populations.py,
population_reports.py, and the tests so the canonical labels live in exactly
one place.

Functions:
- build_grid: the 27-cell archetype grid with the canonical labels
- cell_key: tuple form of a cell dict, used for counting
- compute_quota: deterministic 100-slot quota (every cell >= 3, marginals 33-34)
- print_quota: print the quota table and marginals to stderr
- cell_attrs: format one cell into the attribute string used in the prompt
- assign_voting_models: split 100 slots into five blocks of 20 voting models
- build_frozen_spec: the shared 100-slot blueprint (agent id, cell, model)
- frozen_spec_sha256: sha256 of the deterministic blueprint JSON
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from typing import Any

# ── Grid specification (identical for all six populations) ──────────────────
# The canonical labels below are used verbatim in the population JSON files
# and in the persona prompts.

AGE_CELLS = ("18-29", "30-49", "50+")
POLITICAL_CELLS = ("progressive", "moderate", "conservative")
SECTOR_CELLS = ("public service", "private sector", "not in paid work")

AGE_KEYS = AGE_CELLS
POLITICAL_KEYS = POLITICAL_CELLS
SECTOR_KEYS = SECTOR_CELLS

# Extra wording for the prompt so the model understands each sector value.
SECTOR_PROMPT_HINTS = {
    "public service": "public service (e.g., government, education, healthcare)",
    "private sector": "private sector (e.g., business, commerce, industry)",
    "not in paid work": "not in paid work (e.g., retired, student, carer, or unemployed)",
}

# The five voting models used in the council experiments, in block order.
VOTING_MODELS = (
    "gpt-oss-20b",
    "qwen3.6-35b-a3b",
    "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive",
    "gemma-4-26b-a4b",
    "gemma4-26b-a4b-uncensored-hauhaucs-balanced",
)
AGENTS_PER_MODEL = 20
AGENTS_PER_POPULATION = 100


def build_grid() -> list[dict[str, str]]:
    """Build the 27 archetype cells as canonical label dicts."""
    return [
        {"age": age, "political": pol, "sector": sec}
        for age in AGE_KEYS
        for pol in POLITICAL_KEYS
        for sec in SECTOR_KEYS
    ]


def cell_key(cell: dict[str, str]) -> tuple[str, str, str]:
    """Tuple form of a cell dict, used for counting cells."""
    return (cell["age"], cell["political"], cell["sector"])


def compute_quota() -> list[dict[str, str]]:
    """Return the fixed 100-cell archetype quota in deterministic order.

    Every one of the 27 cells starts with 3 agents (81 total). The remaining
    19 agents are added one at a time to the cell with the fewest agents so
    far, tie-broken by the lowest age, political, and sector marginals in
    that order. The result has every cell at 3-4 agents and every marginal
    (age / political / sector) at 33-34 agents.
    """
    grid = build_grid()
    cell_counts: Counter[tuple[str, str, str]] = Counter(
        {cell_key(cell): 3 for cell in grid}
    )
    age_total = {age: 3 * len(POLITICAL_KEYS) * len(SECTOR_KEYS) for age in AGE_KEYS}
    pol_total = {pol: 3 * len(AGE_KEYS) * len(SECTOR_KEYS) for pol in POLITICAL_KEYS}
    sec_total = {sec: 3 * len(AGE_KEYS) * len(POLITICAL_KEYS) for sec in SECTOR_KEYS}
    for _ in range(AGENTS_PER_POPULATION - 3 * len(grid)):
        cell = min(
            grid,
            key=lambda c: (
                cell_counts[cell_key(c)],
                age_total[c["age"]],
                pol_total[c["political"]],
                sec_total[c["sector"]],
            ),
        )
        cell_counts[cell_key(cell)] += 1
        age_total[cell["age"]] += 1
        pol_total[cell["political"]] += 1
        sec_total[cell["sector"]] += 1
    quota: list[dict[str, str]] = []
    for cell in grid:
        quota.extend([dict(cell)] * cell_counts[cell_key(cell)])
    return quota


def print_quota(quota: list[dict[str, str]]) -> None:
    """Print the 27-cell quota table and the three marginals to stderr."""
    counts: Counter[tuple[str, str, str]] = Counter(cell_key(c) for c in quota)
    print("Archetype quota (100 agents over 27 cells):", file=sys.stderr)
    for age in AGE_KEYS:
        for pol in POLITICAL_KEYS:
            for sec in SECTOR_KEYS:
                print(f"  {age} | {pol} | {sec}: {counts[(age, pol, sec)]}",
                      file=sys.stderr)
    for label, keys in (
        ("age", AGE_KEYS),
        ("political", POLITICAL_KEYS),
        ("sector", SECTOR_KEYS),
    ):
        marginals = {k: sum(1 for c in quota if c[label] == k) for k in keys}
        print(f"  marginal ({label}): {marginals}", file=sys.stderr)


def cell_attrs(cell: dict[str, str]) -> str:
    """Format one archetype cell into the attribute string used in the prompt."""
    return (
        f"Age: {cell['age']}, Political View: {cell['political']}, "
        f"Work Sector: {SECTOR_PROMPT_HINTS[cell['sector']]}"
    )


def assign_voting_models() -> list[str]:
    """Return 100 voting-model labels: five blocks of 20, in fixed order."""
    result: list[str] = []
    for model in VOTING_MODELS:
        result.extend([model] * AGENTS_PER_MODEL)
    return result


def build_frozen_spec(
    quota: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Return the shared 100-slot blueprint (agent id, archetype cell, model).

    The blueprint is identical for every population, so its sha256 is the
    same in all six population files.
    """
    cells = quota if quota is not None else compute_quota()
    models = assign_voting_models()
    return [
        {
            "agent_id": f"agent_{idx + 1:03d}",
            "archetype_cell": cells[idx],
            "voting_model": models[idx],
        }
        for idx in range(AGENTS_PER_POPULATION)
    ]


def frozen_spec_sha256(frozen_spec: list[dict[str, Any]]) -> str:
    """Hex digest of the deterministic blueprint JSON (sorted keys)."""
    payload = json.dumps(frozen_spec, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
