#!/usr/bin/env python3
"""Cell-level durability for the launch wrapper's sweep legs.

The launch wrapper's sweep legs used to buffer every record in memory and
write the leg's files only when the whole leg finished (1522/1525), so a
kill mid-leg lost that leg's completed calls. This module is the
cell-granular core: one chat call is one "cell", and each completed cell's
record is appended to the leg's jsonl and flushed (fsync every
FSYNC_EVERY records and always at leg end / stop) the moment it is
produced. The records file is therefore the resume state: a resumed leg
counts its own jsonl, skips the cells already durably present
(skip_first), and executes only the missing cells.

Durability contract (documented choice): the record line is flushed to the
OS after every cell and fsync'ed every FSYNC_EVERY records, so a process
kill (SIGKILL/SIGINT) or an orderly machine restart loses at most the one
in-flight call whose record was not yet written; a hard power loss can
lose at most the FSYNC_EVERY un-fsynced trailing records, which the resume
planner simply re-runs (no duplicates can appear, because a record that
was never durable is treated as not-done). The torn-tail repair below
keeps the file valid jsonl across such losses.

Function map (plain language):
    leg_jsonl(leg_dir, safe_model, blinding) - The leg's records file path.
    scan_leg_jsonl(path)        - Records + torn-line count (materialized).
    durable_cells(path)         - Cells durably on disk after repairing a
                                  torn tail: the resume planner.
    cell_group_counts(records, persona) - Records per cell group (the
                                  exact-once unit check).
    duplicate_cells(records, persona, ...) - Cell groups above the planned
                                  count (zero duplicates check).
    write_leg_csv(base, records) - A leg's derived csv (jsonl never rewritten).
    write_atomic_json(path, payload) - tmp+rename file write.
    RunProgress                 - shared per-run progress.json tracker
                                  (thread safe).
    results_csv_path(run_dir)   - The run's normalized results.csv path.
    shown_price(regular, level) - The dollar price a level showed.
    result_row(record, ...)     - One normalized row for one cell's record.
    plain_draw_ids_for_records(...) - Per-group draw ordinals for plain-leg
                                  records (stable across a resume).
Every function is pure file/counter logic: importing this module never
opens a socket or touches the GPU.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

FSYNC_EVERY = 64  # fsync cadence for the per-cell writer
PROGRESS_WRITE_SECONDS = 5.0  # progress.json rewrite cadence (at most)


def leg_jsonl(leg_dir: Path, safe_model: str, blinding: str) -> Path:
    """The leg's jsonl path (the cell log and resume state)."""
    return leg_dir / f"{safe_model}_{blinding}.jsonl"


def _line_record(text: str) -> dict[str, Any] | None:
    """One line parsed as a record dict, or None when torn/garbage."""
    if not text.strip():
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def scan_leg_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Read a leg jsonl into records plus the number of torn lines.

    A torn trailing line (the tail of a kill mid-write, or a record that a
    power loss stripped below the fsync point) is counted, never silently
    dropped or mis-parsed. Returns (records, torn) with the records in file
    order.
    """
    records: list[dict[str, Any]] = []
    torn = 0
    if not path.exists():
        return records, 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            record = _line_record(line)
            if record is None:
                torn += 1
            else:
                records.append(record)
    return records, torn


def durable_cells(path: Path) -> tuple[int, int]:
    """The resume planner: (records, parsed) durably on disk.

    Reads the leg jsonl streaming (never materializes the records), counts
    the complete JSON lines and how many of them succeeded. A torn tail (an
    unterminated partial final line from a kill mid-write) is truncated so
    the file stays valid jsonl for the appends that follow; the cell behind
    that torn line was never durable and will be re-run. An unparseable line
    followed by more content is interior corruption and raises - the file
    can no longer be trusted, so we never guess.
    """
    if not path.exists() or path.stat().st_size == 0:
        return 0, 0
    records = 0
    parsed = 0
    good_end = 0
    with path.open("rb") as handle:
        while True:
            raw = handle.readline()
            if not raw:
                break
            end = handle.tell()
            record = _line_record(raw.decode("utf-8", errors="replace"))
            if record is not None:
                records += 1
                if record.get("succeeded"):
                    parsed += 1
                good_end = end
                continue
            rest = handle.read()
            if rest.strip():
                raise ValueError(
                    f"{path} has an unparseable line before the end - "
                    "refusing to resume"
                )
            # A single unterminated partial final line: torn tail.
            break
    if good_end == 0 and path.stat().st_size > 0:
        # The whole file is one torn line (kill before the first record
        # finished). Clear it so the resume can start the leg cleanly.
        with path.open("w", encoding="utf-8"):
            pass
        return 0, 0
    if good_end < path.stat().st_size:
        with path.open("r+b") as handle:
            handle.truncate(good_end)
    return records, parsed


def cell_group_counts(
    records: list[dict[str, Any]], persona: bool
) -> dict[tuple[Any, ...], int]:
    """Count records per cell group.

    Plain sweeps iterate product -> level -> draw, so records share
    (product, treatment_value) across the draws of one level: the count of a
    (product, level) group is how many draws of that level are recorded
    (must equal the planned draws, never more). Persona sweeps iterate
    product -> persona -> level and store persona_index on every record, so
    a group is (product, persona_index, treatment_value) and the count must
    be exactly one. A group count above the planned number means the same
    cell was executed twice (a duplicate).
    """
    counts: dict[tuple[Any, ...], int] = {}
    for record in records:
        product = record.get("product")
        level = record.get("treatment_value")
        if persona:
            key: tuple[Any, ...] = (product, record.get("persona_index"), level)
        else:
            key = (product, level)
        counts[key] = counts.get(key, 0) + 1
    return counts


def duplicate_cells(
    records: list[dict[str, Any]],
    persona: bool,
    expected_per_group: int = 1,
) -> list[tuple[Any, ...]]:
    """Cell groups whose record count exceeds the planned per-group count.

    expected_per_group is the number of draws per (product, level) for a
    plain sweep (persona groups hold exactly one record, so the default of 1
    applies). A group with more records than expected means that cell ran
    twice - the duplicate groups are returned (empty means no duplicates).
    """
    counts = cell_group_counts(records, persona)
    return [key for key, count in counts.items() if count > expected_per_group]


def write_atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON payload so no reader ever sees a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


class RunProgress:
    """The shared per-run progress.json tracker.

    One instance lives for the whole sweep phase of a launch run. Each leg
    thread reports completed cells through note(); a lock makes the shared
    counters safe. The file is rewritten atomically at most every
    PROGRESS_WRITE_SECONDS while cells complete (the operator can tail it),
    and finish() forces a final write so the last snapshot is always on
    disk. Cells that were already durable when the run started (a resume)
    are seeded by set_leg and counted in cells_done, so progress across a
    restarted run is monotonic. calls_per_sec_measured, eta_seconds and
    parse_rate_so_far are measured over THIS invocation's executed cells
    (the same semantics as the launcher's live progress lines), while
    cells_done/cells_total/per_leg count durable cells.
    """

    def __init__(
        self,
        run_dir: Path,
        legs: list[dict[str, Any]],
        log: Callable[[str], None],
        started_wall: float | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.log = log
        self._lock = threading.Lock()
        self._started_wall = (
            started_wall if started_wall is not None else time.monotonic()
        )
        self._legs: dict[str, dict[str, int]] = {}
        for leg in legs:
            key = f"{leg['depth']}_{leg['blinding']}"
            self._legs[key] = {"done": 0, "total": int(leg.get("calls") or 0)}
        self._executed = 0
        self._parsed_executed = 0
        self._last_write = 0.0
        self._closed = False

    # -- updates from the legs ---------------------------------------------

    def set_leg(
        self,
        leg_key: str,
        *,
        done_at_start: int,
    ) -> None:
        """Seed one leg's durable done count (its records file at leg start)."""
        with self._lock:
            entry = self._legs.setdefault(leg_key, {"done": 0, "total": 0})
            entry["done"] = max(entry["done"], done_at_start)

    def note(self, leg_key: str, *, succeeded: bool, force: bool = False) -> None:
        """One cell completed for this leg; maybe rewrite progress.json."""
        due = False
        payload: dict[str, Any] = {}
        with self._lock:
            if self._closed:
                return
            entry = self._legs.setdefault(leg_key, {"done": 0, "total": 0})
            entry["done"] += 1
            self._executed += 1
            if succeeded:
                self._parsed_executed += 1
            now = time.monotonic()
            due = force or now - self._last_write >= PROGRESS_WRITE_SECONDS
            if due:
                self._last_write = now
                payload = self._snapshot_locked()
        if due:
            try:
                write_atomic_json(self.run_dir / "progress.json", payload)
            except OSError as exc:
                self.log(f"warning: could not write progress.json: {exc}")

    def finish(self) -> None:
        """Force the final progress.json write (run ended or stopped)."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            payload = self._snapshot_locked()
        try:
            write_atomic_json(self.run_dir / "progress.json", payload)
        except OSError as exc:
            self.log(f"warning: could not write final progress.json: {exc}")

    # -- payload -----------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """The current progress payload (thread safe)."""
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> dict[str, Any]:
        """Assemble the progress.json payload (caller holds the lock)."""
        cells_done = 0
        cells_total = 0
        per_leg: dict[str, dict[str, int]] = {}
        for key, entry in self._legs.items():
            done = entry["done"]
            cells_done += done
            cells_total += entry["total"]
            per_leg[key] = {"done": done, "total": entry["total"]}
        elapsed = max(1e-9, time.monotonic() - self._started_wall)
        rate = self._executed / elapsed
        remaining = max(0, cells_total - cells_done)
        return {
            "cells_done": cells_done,
            "cells_total": cells_total,
            "per_leg": per_leg,
            "calls_per_sec_measured": round(rate, 3),
            "eta_seconds": round(remaining / rate, 1) if rate > 0 else None,
            "parse_rate_so_far": round(self._parsed_executed / self._executed, 4)
            if self._executed
            else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


def write_leg_csv(base: Path, records: list[dict[str, Any]]) -> None:
    """Write a leg's derived csv only (the jsonl is never rewritten here).

    CSV columns mirror scripts/unblinding_sweep.py's _write_records: the
    first record's keys that are not None in at least one record.
    """
    if not records:
        Path(f"{base}.csv").write_text("", encoding="utf-8")
        return
    columns = [
        key
        for key in records[0]
        if any(record.get(key) is not None for record in records)
    ]
    with Path(f"{base}.csv").open("w", newline="", encoding="utf-8") as csv_handle:
        writer = csv.DictWriter(csv_handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            writer.writerow({key: _csv_cell(record.get(key)) for key in columns})


def _csv_cell(value: Any) -> Any:
    """One record value as a CSV-safe cell; nested values become JSON."""
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value)


# -------------------------------------------------------------------------
# The run-wide normalized results.csv (R1-5MODEL queue)
# -------------------------------------------------------------------------
# The 5-model queue keeps ONE run directory for the whole queue and appends
# one normalized row per executed cell to <run>/results.csv continuously
# while legs run, so the operator can tail it live. The row columns are
# fixed: model, product, price (the shown dollar price), condition_depth,
# condition_blinding, draw_id, parsed and purchase. Rows are rebuilt from
# the authoritative leg records files whenever an invocation starts, then
# appended per executed cell, so the file always holds exactly one row per
# durable cell (no duplicate or lost rows across a kill/restart).
RESULT_CSV_COLUMNS = [
    "model",
    "product",
    "price",
    "condition_depth",
    "condition_blinding",
    "draw_id",
    "parsed",
    "purchase",
]


def results_csv_path(run_dir: Path) -> Path:
    """The run directory's normalized results.csv path."""
    return run_dir / "results.csv"


def shown_price(regular_price: float | None, level: float) -> float:
    """The dollar price a level showed, with the sweep kit's own rounding.

    A level is a percent of the product's regular price (100 = the regular
    price itself); the prompt that ran the cell showed round(regular *
    level / 100, 2), so the row's price reproduces exactly that number.
    A product with no regular price (legacy persona pools) was prompted
    with the raw level instead (sweep_kit's fallback).
    """
    if regular_price is None:
        return level
    return round(regular_price * level / 100.0, 2)


def result_row(
    record: dict[str, Any],
    *,
    regular_prices: dict[str, float | None],
    draw_id: int,
) -> dict[str, Any]:
    """One normalized results.csv row for one cell's record.

    price is the shown dollar price for the record's (product, level),
    parsed is whether the answer parsed, and purchase is the parsed True/
    False decision (empty when the answer did not parse). draw_id comes
    from the caller: the draw's ordinal for a plain cell, or the persona's
    index in the shared pool for a persona cell.
    """
    product = record.get("product")
    level = float(record.get("treatment_value") or 0.0)
    purchase = record.get("parsed_purchase")
    return {
        "model": record.get("model"),
        "product": product,
        "price": shown_price(
            regular_prices.get(product) if product is not None else None, level
        ),
        "condition_depth": record.get("persona_depth"),
        "condition_blinding": record.get("blinding"),
        "draw_id": draw_id,
        "parsed": bool(record.get("succeeded")),
        "purchase": "" if purchase is None else bool(purchase),
    }


def plain_draw_ids_for_records(
    records: list[dict[str, Any]],
) -> tuple[list[int], dict[tuple[Any, ...], int]]:
    """Assign each plain-leg record its draw ordinal inside its cell group.

    A plain (none) leg runs draws per (product x level x blinding) in
    enumeration order, so the draw ordinal of a record is the count of the
    records already seen for the same group. Returns the per-record draw
    ids in file order plus the final per-group counts (so a caller that
    keeps appending rows after a durable prefix can continue numbering the
    missing draws where the durable ones stopped).
    """
    counts: dict[tuple[Any, ...], int] = {}
    ids: list[int] = []
    for record in records:
        key = (
            record.get("model"),
            record.get("product"),
            record.get("treatment_value"),
            record.get("blinding"),
        )
        draw_id = counts.get(key, 0)
        counts[key] = draw_id + 1
        ids.append(draw_id)
    return ids, counts
