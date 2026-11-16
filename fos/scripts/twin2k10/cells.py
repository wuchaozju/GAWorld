# This file defines what one measurement IS and how runs resume: one
# record is one (model, persona, experiment, arm, blinding) cell — 3,800
# cells per model, 57,000 in the whole study (19 arms: nine 2-arm
# between-subjects experiments plus false_consensus's single
# within-subject arm; an anchoring arm's two questions share their one
# cell). enumerate_cells lists every cell in a fixed deterministic order;
# smoke_cells lists the small live pre-launch check's grid (one model,
# one persona, every arm, both blinding arms); record_key reads a cell's
# or a record's five-part identity; load_existing_keys reads finished
# cells back from a records.jsonl file; and run_cells scores only the
# missing cells, writing each finished record to disk (flushed,
# force-synced regularly) before the next call starts, so a crash never
# loses or duplicates finished work.

import json
import os
from pathlib import Path
from typing import Callable, Iterable

from twin2k10 import config, experiments

# The pinned totals the whole study is sized by: 100 personas x 19 arms
# x 2 blinding arms = 3,800 records per model; 15 models = 57,000 total.
EXPECTED_RECORDS_PER_MODEL = 3800
EXPECTED_RECORDS_TOTAL = 57000


def enumerate_cells(models: Iterable[str] | None = None,
                    personas: Iterable[int] | None = None,
                    experiments_map: dict | None = None) -> list[tuple]:
    """Every cell of the study as (model, persona_id, experiment, arm, blind).

    The full grid is 57,000 cells in a fixed deterministic order (model,
    then persona id 0-99, then experiment, then arm in registry order,
    then blinding). All three arguments default to the study's own
    settings, so a subset (e.g. one model) can be enumerated by passing
    just that piece. One cell per ARM — an anchoring arm's two questions
    are measured together inside their arm's single cell.
    """
    models = list(models) if models is not None else config.MODELS
    persona_ids = (list(personas) if personas is not None
                   else range(config.PERSONA_COUNT))
    specs = experiments_map if experiments_map is not None \
        else experiments.EXPERIMENTS
    grid: list[tuple] = []
    for model in models:
        for persona_id in persona_ids:
            for experiment_name, spec in specs.items():
                for arm_name, _qids in spec.arms:
                    for blinding in config.BLINDINGS:
                        grid.append(
                            (model, persona_id, experiment_name,
                             arm_name, blinding)
                        )
    return grid


def smoke_cells() -> list[tuple]:
    """The --smoke grid: 1 model x 1 persona x 19 arms x 2 blinding arms.

    The live pre-launch check's 38 cells: the smallest study model
    (config.SMOKE_MODEL) answers persona config.SMOKE_PERSONA_ID on
    every arm in both blinding arms, so every question kind (choice,
    numeric, multi-row) goes through the real execution path before a
    57,000-cell launch. A pure filter over enumerate_cells — it never
    mixes into the production grid, which keeps its own 100 personas.
    """
    return enumerate_cells(models=[config.SMOKE_MODEL],
                           personas=[config.SMOKE_PERSONA_ID])


def record_key(cell_or_record) -> tuple:
    """A cell's five-part identity, from a cell tuple or a record dict.

    A cell tuple is returned as-is (as a tuple); a record dict is read
    through its five identity fields (model, persona_id, experiment, arm,
    blind). Anything else raises TypeError.
    """
    if isinstance(cell_or_record, tuple):
        model, persona_id, experiment, arm, blind = cell_or_record
    elif isinstance(cell_or_record, dict):
        record = cell_or_record
        model = record["model"]
        persona_id = record["persona_id"]
        experiment = record["experiment"]
        arm = record["arm"]
        blind = record["blind"]
    else:
        raise TypeError(
            f"record_key needs a cell tuple or a record dict, "
            f"got {type(cell_or_record).__name__}"
        )
    return (model, persona_id, experiment, arm, blind)


def load_existing_keys(path: Path) -> set[tuple]:
    """The identity keys of every record already in a records.jsonl file.

    Reads each line as a record dict and extracts its five-part identity.
    A missing file means nothing is done yet (empty set); a malformed line
    raises json.JSONDecodeError rather than being silently skipped.
    """
    path = Path(path)
    if not path.is_file():
        return set()
    keys: set[tuple] = set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            keys.add(record_key(json.loads(line)))
    return keys


def _identity_fields(cell: tuple) -> dict:
    """The five identity fields of one cell as a record dict fragment."""
    model, persona_id, experiment, arm, blind = cell
    return {
        "model": model,
        "persona_id": persona_id,
        "experiment": experiment,
        "arm": arm,
        "blind": blind,
    }


def _write_record(handle, record: dict, records_since_fsync: int) -> int:
    """Append one record line and flush it; force-sync every FSYNC_EVERY.

    Returns the updated since-fsync counter. Flushing happens on every
    record so a process crash keeps everything already returned; the fsync
    bounds what a hard power loss can lose.
    """
    handle.write(json.dumps(record) + "\n")
    handle.flush()
    records_since_fsync += 1
    if records_since_fsync >= config.FSYNC_EVERY:
        os.fsync(handle.fileno())
        return 0
    return records_since_fsync


def run_cells(planned: list[tuple], transport: Callable, path: Path) -> None:
    """Score the planned cells that are not done yet, appending records.

    Reads the records file first; cells whose identity is already on disk
    are skipped, so a resumed run calls the transport only for missing
    cells. Each result is stamped with the cell's five identity fields and
    appended to the file before the next call is made. The transport's
    exceptions propagate untouched — a crashed run keeps every finished
    record and resumes cleanly.
    """
    path = Path(path)
    existing = load_existing_keys(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    records_since_fsync = 0
    with open(path, "a", encoding="utf-8") as handle:
        for cell in planned:
            if record_key(cell) in existing:
                continue
            result = transport(cell)
            record = {**result, **_identity_fields(cell)}
            records_since_fsync = _write_record(handle, record,
                                                records_since_fsync)
        if records_since_fsync:
            os.fsync(handle.fileno())
