"""
This file checks the Phase-3 persona population files and the quota generator.

The data-level tests read the six data/populations/pop_*.json files and
verify the shared blueprint invariants: identical archetype composition and
model assignment across populations, an identical frozen-spec hash, at least
3 agents in every one of the 27 cells, the exact canonical archetype labels,
and sane Big Five statistics. The generator-level tests exercise the pure
functions in scripts/persona_blueprint.py directly.

The data-level tests will fail until the six populations are regenerated with
the new quota-based generator — the current files were produced by the old
uniform-draw generator and use the old archetype labels. The generator-level
tests pass immediately because they only exercise the new code.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from persona_blueprint import (  # noqa: E402
    AGE_KEYS,
    AGENTS_PER_POPULATION,
    POLITICAL_KEYS,
    SECTOR_KEYS,
    VOTING_MODELS,
    assign_voting_models,
    build_frozen_spec,
    compute_quota,
    frozen_spec_sha256,
)

DATA_DIR = _REPO_ROOT / "data" / "populations"
POPULATION_IDS = ("pop_a1", "pop_a2", "pop_b1", "pop_b2", "pop_c1", "pop_c2")

CANONICAL_AGE = frozenset(AGE_KEYS)
CANONICAL_POLITICAL = frozenset(POLITICAL_KEYS)
CANONICAL_SECTOR = frozenset(SECTOR_KEYS)


def _load_populations() -> dict[str, dict]:
    """Load the six population JSON files, keyed by population id."""
    populations: dict[str, dict] = {}
    for pop_id in POPULATION_IDS:
        with open(DATA_DIR / f"{pop_id}.json", encoding="utf-8") as f:
            populations[pop_id] = json.load(f)
    return populations


def _cell_key(cell: dict[str, str]) -> tuple[str, str, str]:
    """Tuple form of one archetype cell dict."""
    return (cell["age"], cell["political"], cell["sector"])


@pytest.fixture(scope="module")
def populations() -> dict[str, dict]:
    """The six population files from data/populations/."""
    return _load_populations()


# ── Generator-level tests (exercise the new code directly) ──────────────────


def test_compute_quota_returns_100_cells_with_balanced_marginals() -> None:
    """compute_quota() must give 100 cells, every cell >= 3, marginals 33-34."""
    quota = compute_quota()
    assert len(quota) == AGENTS_PER_POPULATION
    counts = Counter(_cell_key(c) for c in quota)
    assert len(counts) == 27
    assert all(count >= 3 for count in counts.values())
    for label, keys in (
        ("age", AGE_KEYS),
        ("political", POLITICAL_KEYS),
        ("sector", SECTOR_KEYS),
    ):
        marginals = [sum(1 for c in quota if c[label] == key) for key in keys]
        assert all(33 <= m <= 34 for m in marginals), f"{label} marginals {marginals}"


def test_compute_quota_is_deterministic() -> None:
    """Two calls to compute_quota() must return the exact same 100 cells."""
    assert compute_quota() == compute_quota()


def test_quota_cells_use_canonical_labels() -> None:
    """Every quota cell must use the exact canonical archetype labels."""
    for cell in compute_quota():
        assert cell["age"] in CANONICAL_AGE
        assert cell["political"] in CANONICAL_POLITICAL
        assert cell["sector"] in CANONICAL_SECTOR


def test_voting_models_are_canonical_blocks_of_twenty() -> None:
    """The five voting models must be the canonical ones, 20 slots each."""
    models = assign_voting_models()
    assert len(models) == AGENTS_PER_POPULATION
    assert models == [model for model in VOTING_MODELS for _ in range(20)]
    assert Counter(models) == {model: 20 for model in VOTING_MODELS}


def test_frozen_spec_sha256_is_stable_and_covers_spec() -> None:
    """The frozen-spec hash must be deterministic and derived from the blueprint."""
    spec = build_frozen_spec()
    expected = hashlib.sha256(
        json.dumps(spec, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert frozen_spec_sha256(spec) == expected
    assert len(spec) == AGENTS_PER_POPULATION
    assert all(slot["voting_model"] in VOTING_MODELS for slot in spec)


# ── Data-level tests (need regenerated population files to pass) ─────────────


def test_all_populations_have_identical_archetype_composition(populations: dict[str, dict]) -> None:
    """Every population must assign the same 27-cell archetype to each slot."""
    compositions = {
        pop_id: [_cell_key(a["archetype_cell"]) for a in pop["agents"]]
        for pop_id, pop in populations.items()
    }
    first = next(iter(compositions.values()))
    for pop_id, composition in compositions.items():
        assert composition == first, f"{pop_id} archetype composition differs"


def test_all_populations_have_identical_model_assignment(populations: dict[str, dict]) -> None:
    """Agent slot i must use the same voting model in every population."""
    assignments = {
        pop_id: [a["voting_model"] for a in pop["agents"]]
        for pop_id, pop in populations.items()
    }
    first = next(iter(assignments.values()))
    for pop_id, models in assignments.items():
        assert models == first, f"{pop_id} model assignment differs"
    assert Counter(first) == {model: 20 for model in VOTING_MODELS}


def test_all_populations_share_frozen_spec_sha256(populations: dict[str, dict]) -> None:
    """The frozen blueprint hash must be identical across all six populations."""
    hashes = {
        pop_id: pop["generation_meta"]["frozen_spec_sha256"]
        for pop_id, pop in populations.items()
    }
    assert len(set(hashes.values())) == 1


def test_every_cell_has_at_least_three_agents(populations: dict[str, dict]) -> None:
    """Each of the 27 archetype cells must hold >= 3 agents in every population."""
    for pop_id, pop in populations.items():
        counts = Counter(_cell_key(a["archetype_cell"]) for a in pop["agents"])
        assert len(counts) == 27, f"{pop_id} does not use all 27 cells"
        for cell, count in counts.items():
            assert count >= 3, f"{pop_id}: cell {cell} has only {count} agents"


def test_archetype_labels_are_canonical(populations: dict[str, dict]) -> None:
    """Age, political, and sector labels must use the exact canonical strings."""
    for pop_id, pop in populations.items():
        for agent in pop["agents"]:
            cell = agent["archetype_cell"]
            assert cell["age"] in CANONICAL_AGE, f"{pop_id} {agent['agent_id']}: bad age {cell['age']}"
            assert cell["political"] in CANONICAL_POLITICAL, f"{pop_id} {agent['agent_id']}: bad political {cell['political']}"
            assert cell["sector"] in CANONICAL_SECTOR, f"{pop_id} {agent['agent_id']}: bad sector {cell['sector']}"


def test_big_five_means_and_sds_within_bounds(populations: dict[str, dict]) -> None:
    """Big Five means stay within 7 of 50 and sds within 5 of 20."""
    for pop_id, pop in populations.items():
        for trait in ("o", "c", "e", "a", "n"):
            values = [a["big_five"][trait] for a in pop["agents"]]
            mean = statistics.mean(values)
            sd = statistics.pstdev(values)
            assert abs(mean - 50) <= 7, f"{pop_id} trait {trait} mean {mean:.2f}"
            assert abs(sd - 20) <= 5, f"{pop_id} trait {trait} sd {sd:.2f}"
