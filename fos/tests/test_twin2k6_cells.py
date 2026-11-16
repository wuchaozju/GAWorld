# Locked tests for the twin2k6 study's cell enumeration, record identity,
# and resume/durability contract (TASK-2060 RED phase; tests ONLY — no
# implementation lives here yet).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - One record is one (model, persona, experiment, arm, blinding) cell.
#     The full study enumerates 48,000 cells: 15 models x 100 personas
#     (ids 0-99) x 16 arms x 2 blinding arms — exactly 3,200 per model.
#   - record_key is that 5-part identity, and all 48,000 keys are unique.
#   - Resume: cells already present in records.jsonl (matched by key) are
#     skipped — proven here with a counting fake transport. Records are
#     appended one by one, so a mid-run crash keeps every finished cell.
#
# All offline: pure enumeration plus a temp file; no network, no models.
import json
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k6 import cells, config, experiments  # noqa: E402

EXPECTED_ARMS_PER_EXPERIMENT = {
    "disease": ["gain", "loss"],
    "less_is_more": ["A", "B", "C"],
    "fire_extinguisher": ["all", "98pct", "95pct"],
    "seatbelt": ["all", "98pct", "95pct"],
    "sunk_cost": ["no_card", "card"],
    "wta_wtp": ["wtp_certainty", "wta_certainty", "wtp_noncertainty"],
}


def _record_from(cell):
    """Build a minimal record dict carrying one cell's identity (helper)."""
    model, persona_id, experiment, arm, blind = cell
    return {
        "model": model, "persona_id": persona_id, "experiment": experiment,
        "arm": arm, "blind": blind,
    }


def test_expected_totals_are_pinned():
    """3,200 records per model, 48,000 in the whole study — the pinned math."""
    assert cells.EXPECTED_RECORDS_PER_MODEL == 3200
    assert cells.EXPECTED_RECORDS_TOTAL == 48000
    assert cells.EXPECTED_RECORDS_TOTAL == len(config.MODELS) * cells.EXPECTED_RECORDS_PER_MODEL
    assert cells.EXPECTED_RECORDS_PER_MODEL == 100 * 16 * 2


def test_enumeration_is_exactly_48000_cells_deterministically():
    """enumerate_cells lists 48,000 cells and is stable across calls."""
    first = cells.enumerate_cells()
    assert len(first) == 48000
    assert first == cells.enumerate_cells()


def test_every_cell_is_a_model_persona_experiment_arm_blind_tuple():
    """Cell shape: (model, persona_id, experiment, arm, blind)."""
    cell = cells.enumerate_cells()[0]
    assert isinstance(cell, tuple) and len(cell) == 5
    model, persona_id, experiment, arm, blind = cell
    assert model in config.MODELS
    assert experiment in experiments.EXPERIMENTS
    assert blind in ("blinded", "unblinded")


def test_persona_ids_cover_exactly_0_to_99():
    """One shared pool: every persona id 0-99 appears, none else."""
    persona_ids = {cell[1] for cell in cells.enumerate_cells()}
    assert persona_ids == set(range(100))


def test_each_experiment_contributes_its_arms_for_every_persona_and_blind():
    """Per experiment: models x 100 personas x its arms x 2 blinds."""
    all_cells = cells.enumerate_cells()
    for exp_name, arm_names in EXPECTED_ARMS_PER_EXPERIMENT.items():
        subset = [c for c in all_cells if c[2] == exp_name]
        assert len(subset) == 15 * 100 * len(arm_names) * 2, exp_name
        assert {c[3] for c in subset} == set(arm_names), exp_name


def test_per_model_total_is_3200():
    """Each of the 15 models runs 100 x [2+3+3+3+2+3] x 2 = 3,200 records."""
    counts = {}
    for cell in cells.enumerate_cells():
        counts[cell[0]] = counts.get(cell[0], 0) + 1
    assert counts == {model: 3200 for model in config.MODELS}


def test_record_key_of_a_cell_is_the_five_part_identity():
    """record_key returns the (model, persona, experiment, arm, blind) tuple."""
    cell = ("granite-4.1-8b", 7, "disease", "gain", "blinded")
    assert cells.record_key(cell) == cell


def test_record_key_of_a_record_reads_its_identity_fields():
    """The same key comes out of a written record dict."""
    record = {
        "model": "granite-4.1-8b", "persona_id": 7, "experiment": "disease",
        "arm": "gain", "blind": "blinded", "branch_mass": 0.9,
    }
    assert cells.record_key(record) == ("granite-4.1-8b", 7, "disease", "gain", "blinded")


def test_all_48000_record_keys_are_unique():
    """No cell may ever collide with another — checked over the full grid."""
    keys = [cells.record_key(cell) for cell in cells.enumerate_cells()]
    assert len(keys) == len(set(keys)) == 48000


def test_load_existing_keys_reads_record_identity_from_jsonl(tmp_path):
    """load_existing_keys turns records.jsonl lines back into key tuples."""
    path = tmp_path / "records.jsonl"
    keys = {
        ("granite-4.1-8b", 0, "disease", "gain", "blinded"),
        ("qwen3-4b", 99, "wta_wtp", "wta_certainty", "unblinded"),
    }
    with open(path, "w") as f:
        for key in keys:
            f.write(json.dumps(_record_from(key)) + "\n")
    assert cells.load_existing_keys(path) == keys


def test_resume_skips_cells_already_in_the_records_file(tmp_path):
    """A resumed run calls the transport only for missing cells (fake counts)."""
    path = tmp_path / "records.jsonl"
    planned = cells.enumerate_cells()[:5]
    with open(path, "w") as f:
        for cell in planned[:3]:
            f.write(json.dumps(_record_from(cell)) + "\n")
    calls = []

    def fake_transport(cell):
        calls.append(cell)
        return {"branch_mass": 1.0}

    cells.run_cells(planned, fake_transport, path)
    assert calls == planned[3:], "only the 3 missing cells may be scored"
    lines = path.read_text().splitlines()
    assert len(lines) == 5
    assert [cells.record_key(json.loads(line)) for line in lines] == [
        cells.record_key(cell) for cell in planned
    ]


def test_run_cells_stamps_identity_fields_onto_each_record(tmp_path):
    """Every written record carries the 5 identity fields of its cell."""
    path = tmp_path / "records.jsonl"
    planned = cells.enumerate_cells()[:2]

    cells.run_cells(planned, lambda cell: {"branch_mass": 1.0}, path)

    for line, cell in zip(path.read_text().splitlines(), planned):
        record = json.loads(line)
        assert cells.record_key(record) == cells.record_key(cell)


def test_records_are_appended_one_by_one_so_a_crash_keeps_finished_cells(tmp_path):
    """Each finished record is on disk before the next call is made."""
    path = tmp_path / "records.jsonl"
    planned = cells.enumerate_cells()[:3]

    def crashing_transport(cell):
        if cells.record_key(cell) == cells.record_key(planned[2]):
            raise RuntimeError("simulated crash mid-run")
        return {"branch_mass": 1.0}

    with pytest.raises(RuntimeError, match="simulated crash"):
        cells.run_cells(planned, crashing_transport, path)
    survived = path.read_text().splitlines()
    assert len(survived) == 2, "the two finished records must survive the crash"
