"""Batch-level reproducibility, isolation and comparison contracts."""

import copy

import pytest

from gaworld.research import batches


def protocol_data():
    return {
        "title": "Stress experiment",
        "kind": "parallel_worlds",
        "sim_days": 3,
        "execution_mode": "daily_brief",
        "purpose": "exploratory",
        "sample": {"agent_ids": [1]},
        "validity": {"seeds": [42]},
        "conditions": [
            {"id": "base", "label": "Base", "role": "baseline", "events": [], "config": {}},
            {"id": "treat", "label": "Treat", "role": "treatment", "events": [], "config": {}},
        ],
        "measures": [{"id": "stress"}],
        "hypotheses": [
            {
                "id": "H1",
                "statement": "Stress falls",
                "measure": "stress",
                "control": "base",
                "treatment": "treat",
                "direction": "decrease",
                "aggregation": "mean",
                "min_effect": 0.01,
            }
        ],
    }


def test_matrix_expands_unique_cells_without_mutating_protocol():
    protocol = protocol_data()
    before = copy.deepcopy(protocol)
    matrix = batches.matrix(
        {"providers": ["a", "b"], "cities": ["c1", "c2"], "repeats": 3, "seed": 42, "seed_strategy": "vary"}
    )
    cells = batches.cells(matrix)
    assert len(cells) == len({c["id"] for c in cells}) == 12
    assert [c["seed"] for c in cells[:3]] == [42, 43, 44]
    assert protocol == before
    assert {c["city"] for c in cells} == {"c1", "c2"}


def test_fixed_seed_repeats_still_have_distinct_ids():
    cells = batches.cells(
        batches.matrix(
            {"providers": ["a"], "cities": [""], "repeats": 3, "seed_strategy": "fixed", "seed": 7}
        )
    )
    assert [c["seed"] for c in cells] == [7, 7, 7]
    assert len({c["id"] for c in cells}) == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"repeats": 0},
        {"repeats": 101},
        {"providers": []},
        {"providers": ["a", "a"]},
        {"cities": ["c", "c"]},
        {"seed_strategy": "anything"},
        {"seed": True},
    ],
)
def test_matrix_rejects_ambiguous_or_unbounded_work(changes):
    with pytest.raises(ValueError):
        batches.matrix({"providers": ["a"], "cities": ["c"], "repeats": 3, **changes})


def test_store_rejects_traversal_and_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(batches, "root", lambda: tmp_path)
    record = batches.new(protocol_data(), {"providers": ["a"], "cities": ["c"], "repeats": 2})
    batches.save(record)
    assert batches.load(record["id"]) == record
    with pytest.raises(ValueError):
        batches.load("../secrets")


def test_protocol_fingerprint_ignores_only_execution_dimensions():
    a = protocol_data()
    b = copy.deepcopy(a)
    b.update(sim_provider="different", budget={"estimated_calls": 900})
    b["validity"]["seeds"] = [99]
    b["sample"].update(city="other", seed_identity={"sha256": "other"})
    assert batches.protocol_hash(a) == batches.protocol_hash(b)
    b["hypotheses"][0]["direction"] = "increase"
    assert batches.protocol_hash(a) != batches.protocol_hash(b)
