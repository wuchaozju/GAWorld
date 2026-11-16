# This file repairs the damaged Gemma-4-31B answer file WITHOUT touching the
# frozen run: it merges the current (frozen, post-retry) answer file with the
# run's own pre-retry backup into a "sidecar" file stored next to the analysis
# outputs. The frozen file had 25 of its 440 product-price cells dropped and
# 1,198 persona slots written twice; the backup has every cell but 3,215 empty
# (null) readings. The sidecar keeps exactly one row per product-price-persona
# slot: where the frozen file has a reading it wins, otherwise the backup
# backfills (and backup nulls stay null — cell means just skip nulls).
# Functions:
#   read_latest_rows — read an answers file, keeping the last raw line seen
#     for each product-price-persona slot (so double-writes resolve to the
#     file's final word) plus the schema (key order) of the file;
#   build_sidecar_rows — merge frozen and backup rows into the canonical
#     440-cell x 20-persona grid, sorted, as raw JSON lines copied verbatim;
#   validate_sidecar — check the sidecar is complete (8,800 rows, 440 cells,
#     at least one row per cell, one schema) and report how many of the 20
#     personas per cell carry a real (non-null) reading;
#   write_sidecar — write the raw lines to the sidecar file on disk;
#   write_provenance — write the short .provenance.md note (sources, rule,
#     counts) next to the sidecar;
#   main — command-line entry point: build, validate, write, report.

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Slot key: one product at one price for one persona.
Slot = tuple[str, float, int]

EXPECTED_ROWS = 8_800        # 440 cells x 20 personas
EXPECTED_CELLS = 440         # 40 products x 11 price levels (0..200%)
EXPECTED_PERSONAS = 20       # personas per cell in the demographics design

RUN_DIR = Path.home() / (
    "Documents/ZJU work/fos/results/unblinding/R1-YESNO-GEMMA31B-20260917T120236"
    "/google_gemma-4-31b-it-qat/demographics_unblinded"
)
DEFAULT_FROZEN = RUN_DIR / "records.jsonl"
DEFAULT_BACKUP = RUN_DIR / "records.jsonl.bak-20260918-pre-retry"
DEFAULT_OUT = (
    Path.home() / "Documents/ZJU work/fos/results/unblinding/R1-YESNO-ANALYSIS-V2/derived"
    / "gemma31b_120236_demographics_unblinded_repaired.jsonl"
)


def _slot_of(record: dict) -> Slot:
    """Return the product-price-persona key of one answer row."""
    return (record["product"], float(record["treatment_value"]), int(record["persona_index"]))


def read_latest_rows(path: Path) -> tuple[dict[Slot, str], list[str]]:
    """Read an answers file; keep the LAST raw line per slot plus the schema.

    Returns (rows, schema) where rows maps each slot to its raw JSON line
    (whitespace-stripped, exactly as stored) and schema is the ordered list
    of field names every line must carry. Keeping raw lines means merged rows
    are copied bit-for-bit, never re-serialized.
    """
    rows: dict[Slot, str] = {}
    schema: list[str] | None = None
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            record = json.loads(stripped)
            if schema is None:
                schema = list(record.keys())
            elif list(record.keys()) != schema:
                raise ValueError(f"{path}: row schema changed mid-file at slot {_slot_of(record)}")
            rows[_slot_of(record)] = stripped
    if schema is None:
        raise ValueError(f"{path}: no answer rows found")
    return rows, schema


def build_sidecar_rows(frozen: Path, backup: Path) -> list[str]:
    """Merge frozen and pre-retry rows into one raw line per canonical slot.

    The backup defines the full 440-cell x 20-persona grid. A slot present in
    the frozen file uses the frozen line (the repaired reading wins); a slot
    only in the backup is backfilled from it. Output is sorted by slot for a
    deterministic file. Returns the raw JSON lines, in file order.
    """
    frozen_rows, schema = read_latest_rows(frozen)
    backup_rows, backup_schema = read_latest_rows(backup)
    if backup_schema != schema:
        raise ValueError("frozen and backup files do not share one row schema")
    merged: dict[Slot, str] = {}
    for slot in backup_rows:
        merged[slot] = frozen_rows.get(slot, backup_rows[slot])
    missing = set(frozen_rows) - set(backup_rows)
    if missing:
        raise ValueError(f"{len(missing)} frozen slots absent from the backup grid, e.g. {sorted(missing)[:3]}")
    return [merged[slot] for slot in sorted(merged)]


def validate_sidecar(path: Path, schema: list[str]) -> dict:
    """Assert the sidecar is complete and report its per-cell reading health.

    Hard checks (raise ValueError on failure): exactly 8,800 rows, exactly
    440 distinct cells, every cell at least one row, one row per slot, and
    every row carries the frozen file's schema. Soft report: how many of the
    20 personas per cell hold a real (non-null) yes/no reading — backfilled
    cells may carry fewer, which is expected and fine.
    """
    slots: set[Slot] = set()
    cells: dict[tuple[str, float], int] = {}
    valid_per_cell: Counter[tuple[str, float]] = Counter()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            record = json.loads(stripped)
            if list(record.keys()) != schema:
                raise ValueError(f"{path}: row schema differs from the frozen schema")
            slot = _slot_of(record)
            if slot in slots:
                raise ValueError(f"{path}: duplicate slot {slot}")
            slots.add(slot)
            cell = (slot[0], slot[1])
            cells[cell] = cells.get(cell, 0) + 1
            if record.get("p_yes_binary") is not None:
                valid_per_cell[cell] += 1
    if len(slots) != EXPECTED_ROWS:
        raise ValueError(f"{path}: expected {EXPECTED_ROWS} rows, found {len(slots)}")
    if len(cells) != EXPECTED_CELLS:
        raise ValueError(f"{path}: expected {EXPECTED_CELLS} cells, found {len(cells)}")
    thin = {cell: n for cell, n in cells.items() if n < 1}
    if thin:
        raise ValueError(f"{path}: cells without any row: {sorted(thin)[:5]}")
    distribution = Counter(valid_per_cell.get(cell, 0) for cell in cells)
    return {
        "rows": len(slots),
        "cells": len(cells),
        "valid_personas_per_cell_histogram": dict(sorted(distribution.items())),
        "cells_below_full": sum(n for level, n in distribution.items() if level < EXPECTED_PERSONAS),
    }


def write_sidecar(path: Path, lines: list[str]) -> None:
    """Write the merged raw JSON lines to the sidecar file (one per line)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")


def _file_stamp(path: Path) -> str:
    """Describe a source file: size, modification time and short sha256."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone()
    return f"`{path.name}` ({path.stat().st_size} bytes, mtime {mtime:%Y-%m-%d %H:%M}, sha256 {digest}…)"


def write_provenance(out_path: Path, frozen: Path, backup: Path, report: dict) -> None:
    """Write the <=10-line .provenance.md note (sources, rule, counts)."""
    text = (
        "# Provenance — repaired Gemma-4-31B unblinded leg (sidecar)\n"
        f"- Frozen source: {RUN_DIR}/records.jsonl — {_file_stamp(frozen)}\n"
        f"- Backfill source: {RUN_DIR}/records.jsonl.bak-20260918-pre-retry — {_file_stamp(backup)}\n"
        "- Conflict rule: one row per (product, price, persona_index); frozen-file row wins "
        "(last occurrence for double-writes); slots only in the pre-retry backup are backfilled; "
        "backup nulls stay null and are excluded from cell means.\n"
        f"- Counts: {report['rows']} rows, {report['cells']} cells x {EXPECTED_PERSONAS} personas; "
        f"{report['cells_below_full']} cells carry fewer than {EXPECTED_PERSONAS} valid readings "
        f"(valid-persona histogram: {report['valid_personas_per_cell_histogram']}).\n"
        f"- Built {datetime.now(tz=timezone.utc).astimezone():%Y-%m-%d %H:%M %Z} by "
        "`scripts/r1yesno_v2/sidecar_repair.py` (crew task 2035); the frozen run dir is untouched.\n"
    )
    stamp = out_path.with_name(out_path.stem + ".provenance.md")
    stamp.write_text(text, encoding="utf-8")
    print(f"  provenance: {stamp}")


def main() -> None:
    """Build, validate and write the sidecar; print the completeness report."""
    parser = argparse.ArgumentParser(description="Rebuild the Gemma-4-31B unblinded leg as a sidecar")
    parser.add_argument("--frozen", type=Path, default=DEFAULT_FROZEN)
    parser.add_argument("--backup", type=Path, default=DEFAULT_BACKUP)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    _, schema = read_latest_rows(args.frozen)
    lines = build_sidecar_rows(args.frozen, args.backup)
    write_sidecar(args.out, lines)
    report = validate_sidecar(args.out, schema)
    write_provenance(args.out, args.frozen, args.backup, report)
    print(f"  sidecar: {args.out}")
    print(f"  rows={report['rows']} cells={report['cells']}")
    print(f"  valid personas per cell (histogram): {report['valid_personas_per_cell_histogram']}")
    print(f"  cells below {EXPECTED_PERSONAS} valid personas: {report['cells_below_full']}")


if __name__ == "__main__":
    main()
