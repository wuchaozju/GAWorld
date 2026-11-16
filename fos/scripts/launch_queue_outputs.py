"""The R1-5MODEL queue's live state files: progress.json + results.csv.

The 5-model queue keeps ONE run directory for the whole queue. While legs
run, two run-wide files are written continuously: progress.json (cells
done/total per leg, per model and over the whole queue, with the measured
rate, ETA and parse rate) and the normalized results.csv (one row per
executed cell, appended the moment the cell completes, so the operator can
tail it live). The results.csv row columns are fixed: model, product,
price (the shown dollar price), condition_depth, condition_blinding,
draw_id, parsed and purchase.

Both files stay coherent across a kill/restart: progress.json is seeded
from the leg records files that are already durable when an invocation
starts (a resume), so its counts are monotonic; results.csv is REBUILT
from the authoritative leg records files at each invocation start (a fresh
run gets just the header) and then appended per executed cell, so it
always holds exactly one row per durable cell - a cell whose record was
never durable has no row, and a durable cell is never duplicated.

What each function/class does (plain language):
    rebuild_results_csv(...)  - Rewrite results.csv from the leg records
                                files; return per-group draw counters.
    QueueResultsCsv           - The continuous per-cell csv appender
                                (thread safe, one row per executed cell).
    QueueProgress             - The per-model progress.json tracker.
Importing this module never opens a socket.
"""

from __future__ import annotations

import csv
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
for _dir in (_SCRIPT_DIR, _REPO_ROOT / "src"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from launch_cells import (  # noqa: E402
    RESULT_CSV_COLUMNS,
    plain_draw_ids_for_records,
    result_row,
    results_csv_path,
    scan_leg_jsonl,
    write_atomic_json,
)
from launch_queue import (  # noqa: E402
    MODEL_QUEUE,
    persona_slice,
    queue_leg_dir,
    queue_leg_jsonl,
)
from launch_support import _safe_model_name  # noqa: E402

PROGRESS_WRITE_SECONDS = 5.0  # progress.json rewrite cadence (at most)


def rebuild_results_csv(
    run_dir: Path,
    targets: list[dict[str, Any]],
    regular_prices: dict[str, float | None],
    log: Callable[[str], None],
) -> dict[tuple[Any, ...], int]:
    """Rewrite results.csv from the authoritative leg records files.

    The leg records files are the source of truth for every executed cell,
    so on each invocation start the run's results.csv is rebuilt from them
    (a fresh run gets just the header) and new cells are appended after it.
    A resume therefore always holds exactly one row per durable cell - a
    cell whose record was never durable has no row, and a durable cell is
    never duplicated. Returns the final per-group plain draw counters so
    the live appender continues numbering a resumed leg's missing draws
    where its durable prefix stopped.
    """
    plain_counts: dict[tuple[Any, ...], int] = {}
    rows: list[dict[str, Any]] = []
    rebuilt = 0
    for target in targets:
        jsonl = queue_leg_jsonl(queue_leg_dir(run_dir, target))
        if not jsonl.exists():
            continue
        records, torn = scan_leg_jsonl(jsonl)
        if torn:
            raise ValueError(
                f"{jsonl} has an interior torn record - refusing to rebuild "
                "results.csv from it"
            )
        if not records:
            continue
        if target["depth"] == "none":
            ids, counts = plain_draw_ids_for_records(records)
            for key, count in counts.items():
                plain_counts[key] = plain_counts.get(key, 0) + count
            for record, draw_id in zip(records, ids):
                rows.append(
                    result_row(record, regular_prices=regular_prices, draw_id=draw_id)
                )
        else:
            base = persona_slice(target["model_index"])[0]
            for record in records:
                draw_id = base + int(record.get("persona_index") or 0)
                rows.append(
                    result_row(record, regular_prices=regular_prices, draw_id=draw_id)
                )
        rebuilt += len(records)
    path = results_csv_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=RESULT_CSV_COLUMNS, extrasaction="ignore"
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
    log(
        f"results.csv: rebuilt {rebuilt:,} durable cell row(s) "
        f"(records files are the source of truth)"
    )
    return plain_counts


class QueueResultsCsv:
    """The run's continuous normalized results.csv appender (thread safe).

    One instance is shared by every concurrent leg of the whole queue. Each
    completed cell's row is written the moment the cell's record is built
    (one row per {model, product, price, condition_depth, condition_
    blinding, draw_id}), so the operator can tail the file while the run is
    live. draw_id for a plain cell is the draw's ordinal inside its
    (model, product, price level, blinding) group, seeded from the durable
    prefix a resumed invocation found; for a persona cell it is the
    persona's index in the shared pool (the model's slice start plus the
    record's slice-local persona_index).
    """

    def __init__(
        self,
        run_dir: Path,
        regular_prices: dict[str, float | None],
        plain_seed: dict[tuple[Any, ...], int],
    ) -> None:
        self._path = results_csv_path(run_dir)
        self._regular = regular_prices
        self._plain_counts = dict(plain_seed)
        self._lock = threading.Lock()
        self._handle = self._path.open("a", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(
            self._handle, fieldnames=RESULT_CSV_COLUMNS, extrasaction="ignore"
        )

    def append(self, record: dict[str, Any], *, target: dict[str, Any]) -> None:
        """Append one cell's normalized row and flush it to the OS."""
        if target["depth"] == "none":
            key = (
                record.get("model"),
                record.get("product"),
                record.get("treatment_value"),
                record.get("blinding"),
            )
            with self._lock:
                draw_id = self._plain_counts.get(key, 0)
                self._plain_counts[key] = draw_id + 1
                row = result_row(record, regular_prices=self._regular, draw_id=draw_id)
                self._writer.writerow(row)
                self._handle.flush()
        else:
            base = persona_slice(target["model_index"])[0]
            draw_id = base + int(record.get("persona_index") or 0)
            row = result_row(record, regular_prices=self._regular, draw_id=draw_id)
            with self._lock:
                self._writer.writerow(row)
                self._handle.flush()

    def close(self) -> None:
        """Close the append handle (run end or stop)."""
        with self._lock:
            if not self._handle.closed:
                self._handle.close()


class QueueProgress:
    """The run-wide progress.json tracker of the whole 5-model queue.

    One instance lives for the whole queue. Each leg thread reports its
    completed cells through note(); a lock makes the counters safe and the
    file is rewritten atomically at most every PROGRESS_WRITE_SECONDS while
    cells complete, with finish() forcing the final snapshot. Cells already
    durable when the invocation started (a resume) are seeded by set_leg,
    so progress across a restarted run is monotonic. The snapshot reports
    cells done/total per leg, per model and over the whole queue, plus the
    measured rate, ETA and parse rate over THIS invocation's executed cells.
    """

    def __init__(
        self,
        run_dir: Path,
        targets: list[dict[str, Any]],
        log: Callable[[str], None],
        started_wall: float | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.log = log
        self._lock = threading.Lock()
        self._started_wall = (
            started_wall if started_wall is not None else time.monotonic()
        )
        self._entries: dict[tuple[str, str, str], dict[str, int]] = {}
        for target in targets:
            key = (target["safe_model"], target["depth"], target["blinding"])
            self._entries[key] = {"done": 0, "total": int(target.get("calls") or 0)}
        self._executed = 0
        self._parsed_executed = 0
        self._last_write = 0.0
        self._closed = False

    def set_leg(
        self,
        target: dict[str, Any],
        *,
        done_at_start: int,
    ) -> None:
        """Seed one leg's durable done count (its records file at start)."""
        key = (target["safe_model"], target["depth"], target["blinding"])
        with self._lock:
            entry = self._entries.setdefault(
                key, {"done": 0, "total": int(target.get("calls") or 0)}
            )
            entry["done"] = max(entry["done"], done_at_start)

    def note(
        self,
        target: dict[str, Any],
        *,
        succeeded: bool,
        force: bool = False,
    ) -> None:
        """One cell completed for this leg; maybe rewrite progress.json."""
        key = (target["safe_model"], target["depth"], target["blinding"])
        due = False
        payload: dict[str, Any] = {}
        with self._lock:
            if self._closed:
                return
            entry = self._entries.setdefault(
                key, {"done": 0, "total": int(target.get("calls") or 0)}
            )
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
        """Force the final progress.json write (queue ended or stopped)."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            payload = self._snapshot_locked()
        try:
            write_atomic_json(self.run_dir / "progress.json", payload)
        except OSError as exc:
            self.log(f"warning: could not write final progress.json: {exc}")

    def snapshot(self) -> dict[str, Any]:
        """The current progress payload (thread safe)."""
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> dict[str, Any]:
        """Assemble the progress.json payload (caller holds the lock)."""
        cells_done = 0
        cells_total = 0
        per_model: dict[str, dict[str, Any]] = {}
        for safe in (_safe_model_name(model) for model in MODEL_QUEUE):
            per_model[safe] = {
                "done": 0,
                "total": 0,
                "per_leg": {},
            }
        for (safe, depth, blinding), entry in self._entries.items():
            done = entry["done"]
            total = entry["total"]
            cells_done += done
            cells_total += total
            per_model.setdefault(safe, {"done": 0, "total": 0, "per_leg": {}})
            per_model[safe]["done"] += done
            per_model[safe]["total"] += total
            per_model[safe]["per_leg"][f"{depth}_{blinding}"] = {
                "done": done,
                "total": total,
            }
        elapsed = max(1e-9, time.monotonic() - self._started_wall)
        rate = self._executed / elapsed
        remaining = max(0, cells_total - cells_done)
        return {
            "cells_done": cells_done,
            "cells_total": cells_total,
            "per_model": per_model,
            "calls_per_sec_measured": round(rate, 3),
            "eta_seconds": round(remaining / rate, 1) if rate > 0 else None,
            "parse_rate_so_far": round(self._parsed_executed / self._executed, 4)
            if self._executed
            else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
