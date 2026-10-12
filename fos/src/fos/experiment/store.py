"""
SQLite state store for the checkpointed experiment runner.

Stores one row per run (including empty-response statistics), the progress
stages reached, and every agent LLM call. All writes are committed
immediately. The runs directory can be redirected with the
FOS_EXPERIMENT_RUNS_DIR environment variable so tests and deployments never
touch the repository's own runs/ directory.

Functions: get_db, init_db, seed_from_csv, get_run, list_runs, get_progress,
mark_running, mark_complete, mark_failed, record_progress, record_agent_call,
get_agent_calls, reset_stale_runs, reset_failed_runs, record_empty_stats,
get_checkpoint_path, get_status_summary, matrix_run_ids
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from fos.experiment.schema import TABLES, migrate_runs_table

# ── Paths, resolved relative to the repository root ─────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNS_DIR = Path(
    os.environ.get("FOS_EXPERIMENT_RUNS_DIR", str(REPO_ROOT / "runs"))
)
STATE_DB_PATH = RUNS_DIR / "state.db"
RUN_MATRIX_PATH = REPO_ROOT / "data" / "configs" / "run_matrix.csv"
NETWORK_CONFIGS_PATH = REPO_ROOT / "data" / "configs" / "network_configs.json"
RESULTS_DIR = RUNS_DIR / "results"

# ── Schema (defined in schema.py) ─────────────────────────────────────────────

# Generator names (network_configs.json) shortened for the status output.
GENERATOR_ABBREVS = {"watts_strogatz": "ws", "holme_kim": "hk", "sbm": "sbm"}
GENERATOR_ORDER = ("ws", "hk", "sbm")


def get_db() -> sqlite3.Connection:
    """Open a fresh connection to runs/state.db, creating the directory first.

    Every call returns a brand-new connection owned by the caller; WAL mode
    keeps readers and writers from blocking each other.
    """
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(STATE_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _resolve(conn: sqlite3.Connection | None) -> tuple[sqlite3.Connection, bool]:
    """Return the caller's connection, or open our own, plus whether we opened it."""
    if conn is not None:
        return conn, False
    return get_db(), True


def init_db(conn: sqlite3.Connection | None = None) -> None:
    """Create the tables if they do not already exist; migrate old schemas."""
    c, opened = _resolve(conn)
    try:
        for statement in TABLES:
            c.execute(statement)
        migrate_runs_table(c)
        c.commit()
    finally:
        if opened:
            c.close()


def seed_from_csv(conn: sqlite3.Connection | None = None) -> int:
    """Insert the run matrix rows into runs; returns how many rows were inserted.

    Uses INSERT OR IGNORE so re-running never duplicates rows.
    """
    rows = _read_run_matrix()
    c, opened = _resolve(conn)
    try:
        inserted = 0
        for row in rows:
            cursor = c.execute(
                """
                INSERT OR IGNORE INTO runs
                    (run_id, config_id, proposal_id, population_id, execution_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["run_id"],
                    int(row["config_id"]),
                    row["proposal_id"],
                    row["population_id"],
                    int(row["execution_order"]),
                ),
            )
            inserted += cursor.rowcount
        c.commit()
        return inserted
    finally:
        if opened:
            c.close()


def get_run(
    run_id: str, conn: sqlite3.Connection | None = None
) -> dict[str, Any] | None:
    """Fetch a single run as a dict, or None when it does not exist."""
    c, opened = _resolve(conn)
    try:
        row = c.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row is not None else None
    finally:
        if opened:
            c.close()


def list_runs(
    status: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Fetch runs, optionally filtered by status, ordered by execution_order."""
    c, opened = _resolve(conn)
    try:
        if status is None:
            rows = c.execute("SELECT * FROM runs ORDER BY execution_order").fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM runs WHERE status = ? ORDER BY execution_order",
                (status,),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        if opened:
            c.close()


def get_progress(
    run_id: str, conn: sqlite3.Connection | None = None
) -> list[dict[str, Any]]:
    """Fetch the completed stages of a run, oldest first."""
    c, opened = _resolve(conn)
    try:
        rows = c.execute(
            "SELECT * FROM run_progress WHERE run_id = ? ORDER BY completed_at",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        if opened:
            c.close()


def mark_running(run_id: str, conn: sqlite3.Connection | None = None) -> None:
    """Mark a run as in progress, record its start time, count an attempt."""
    c, opened = _resolve(conn)
    try:
        c.execute(
            "UPDATE runs SET status = 'running', started_at = ?, "
            "attempts = attempts + 1 WHERE run_id = ?",
            (_now(), run_id),
        )
        c.commit()
    finally:
        if opened:
            c.close()


def mark_complete(
    run_id: str,
    output_path: str,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Mark a run as finished successfully and record where its result lives."""
    c, opened = _resolve(conn)
    try:
        c.execute(
            "UPDATE runs SET status = 'complete', finished_at = ?, output_path = ? "
            "WHERE run_id = ?",
            (_now(), output_path, run_id),
        )
        c.commit()
    finally:
        if opened:
            c.close()


def mark_failed(
    run_id: str, error_msg: str, conn: sqlite3.Connection | None = None
) -> None:
    """Mark a run as failed and store the error message."""
    c, opened = _resolve(conn)
    try:
        c.execute(
            "UPDATE runs SET status = 'failed', finished_at = ?, last_error = ? "
            "WHERE run_id = ?",
            (_now(), error_msg, run_id),
        )
        c.commit()
    finally:
        if opened:
            c.close()


def record_empty_stats(
    run_id: str,
    empty_count: int,
    total_calls: int,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Store the empty-response count and total LLM calls for a run."""
    c, opened = _resolve(conn)
    try:
        c.execute(
            "UPDATE runs SET empty_response_count = ?, total_llm_calls = ? "
            "WHERE run_id = ?",
            (empty_count, total_calls, run_id),
        )
        c.commit()
    finally:
        if opened:
            c.close()


def get_checkpoint_path(run_id: str) -> Path:
    """Return the checkpoint file path for a run: runs/checkpoints/{run_id}.json."""
    return RUNS_DIR / "checkpoints" / f"{run_id}.json"


def record_progress(
    run_id: str, stage: str, conn: sqlite3.Connection | None = None
) -> None:
    """Record that a run finished a stage; re-recording a stage refreshes its time."""
    c, opened = _resolve(conn)
    try:
        c.execute(
            """
            INSERT OR REPLACE INTO run_progress (run_id, stage, completed_at)
            VALUES (?, ?, ?)
            """,
            (run_id, stage, _now()),
        )
        c.commit()
    finally:
        if opened:
            c.close()


def record_agent_call(
    run_id: str,
    round_index: int,
    agent_uid: str,
    response_json: str,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Record one agent LLM call; re-recording the same call refreshes it."""
    c, opened = _resolve(conn)
    try:
        c.execute(
            """
            INSERT OR REPLACE INTO agent_calls
                (run_id, round_index, agent_uid, response_json, completed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, round_index, agent_uid, response_json, _now()),
        )
        c.commit()
    finally:
        if opened:
            c.close()


def get_agent_calls(
    run_id: str,
    round_index: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Fetch recorded agent calls for a run, optionally for one round only."""
    c, opened = _resolve(conn)
    try:
        if round_index is None:
            rows = c.execute(
                "SELECT * FROM agent_calls WHERE run_id = ? ORDER BY round_index, agent_uid",
                (run_id,),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM agent_calls WHERE run_id = ? AND round_index = ? "
                "ORDER BY agent_uid",
                (run_id, round_index),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        if opened:
            c.close()


def reset_stale_runs(conn: sqlite3.Connection | None = None) -> int:
    """Return crashed 'running' runs to 'pending' and count them as another attempt."""
    c, opened = _resolve(conn)
    try:
        cursor = c.execute(
            "UPDATE runs SET status = 'pending', attempts = attempts + 1 "
            "WHERE status = 'running'"
        )
        c.commit()
        return cursor.rowcount
    finally:
        if opened:
            c.close()


def reset_failed_runs(conn: sqlite3.Connection | None = None) -> int:
    """Reset failed runs back to pending; returns how many were reset."""
    c, opened = _resolve(conn)
    try:
        cursor = c.execute("UPDATE runs SET status = 'pending' WHERE status = 'failed'")
        c.commit()
        return cursor.rowcount
    finally:
        if opened:
            c.close()


def get_status_summary(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Aggregate everything the status command needs into one dict.

    Works even before the database is initialised: missing tables simply
    count as zero runs. Totals per generator and per population always come
    from the run matrix so they stay correct even when the DB is empty.
    Empty-response statistics are summed across all runs.
    """
    c, opened = _resolve(conn)
    try:
        try:
            runs = [
                dict(row)
                for row in c.execute("SELECT * FROM runs ORDER BY execution_order")
            ]
        except sqlite3.OperationalError:
            runs = []
    finally:
        if opened:
            c.close()

    matrix = _read_run_matrix()
    n_proposals = len({row["proposal_id"] for row in matrix})
    n_configs = len({row["config_id"] for row in matrix})
    generators = _config_generators()

    gen_totals: Counter[str] = Counter()
    for row in matrix:
        gen_totals[_generator_abbr(generators.get(int(row["config_id"])))] += 1
    pop_totals: Counter[str] = Counter(
        row["population_id"].removeprefix("pop_") for row in matrix
    )

    complete = running = pending = failed = 0
    failed_run_ids: list[str] = []
    gen_complete: Counter[str] = Counter()
    pop_complete: Counter[str] = Counter()
    in_progress: list[str] = []
    next_up: list[str] = []
    last_completed: dict[str, str] | None = None
    elapsed = 0.0
    empty_total = 0
    call_total = 0
    max_empty_run: tuple[str, float] | None = None

    for run in runs:
        status = run["status"]
        complete += status == "complete"
        running += status == "running"
        pending += status == "pending"
        failed += status == "failed"
        abbr = _generator_abbr(generators.get(run["config_id"]))
        empty_calls = int(run.get("empty_response_count") or 0)
        total_calls = int(run.get("total_llm_calls") or 0)
        empty_total += empty_calls
        call_total += total_calls
        if total_calls > 0:
            pct = 100.0 * empty_calls / total_calls
            if max_empty_run is None or pct > max_empty_run[1]:
                max_empty_run = (run["run_id"], pct)
        label = run["population_id"].removeprefix("pop_")
        if status == "complete":
            gen_complete[abbr] += 1
            pop_complete[label] += 1
            start = _parse_timestamp(run["started_at"])
            end = _parse_timestamp(run["finished_at"])
            if start is not None and end is not None:
                delta = (end - start).total_seconds()
                if delta > 0:
                    elapsed += delta
            if run["finished_at"] and (
                last_completed is None
                or run["finished_at"] > last_completed["finished_at"]
            ):
                last_completed = {
                    "run_id": run["run_id"],
                    "finished_at": run["finished_at"],
                }
        elif status == "failed":
            failed_run_ids.append(run["run_id"])
        elif status == "running":
            in_progress.append(run["run_id"])
        elif status == "pending" and len(next_up) < 3:
            next_up.append(run["run_id"])

    by_generator = {
        abbr: (gen_complete[abbr], gen_totals[abbr])
        for abbr in sorted(set(gen_totals) | set(gen_complete), key=_generator_sort_key)
    }
    by_population = {
        label: (pop_complete[label], pop_totals[label])
        for label in sorted(set(pop_totals) | set(pop_complete))
    }

    mean_per_run = elapsed / complete if complete else 0.0
    remaining_count = pending + failed

    return {
        "empty_pct": (100.0 * empty_total / call_total) if call_total else 0.0,
        "max_empty_run": max_empty_run,
        "n_proposals": n_proposals,
        "n_configs": n_configs,
        "total": len(matrix),
        "complete": complete,
        "running": running,
        "pending": pending,
        "failed": failed,
        "failed_run_ids": failed_run_ids,
        "by_generator": by_generator,
        "by_population": by_population,
        "last_completed": last_completed,
        "in_progress": in_progress,
        "next_up": next_up,
        "elapsed_seconds": elapsed,
        "mean_per_run_seconds": mean_per_run,
        "est_remaining_seconds": mean_per_run * remaining_count,
        "remaining_count": remaining_count,
    }


def matrix_run_ids() -> list[str]:
    """Return the run ids from the run matrix, in execution order."""
    rows = sorted(_read_run_matrix(), key=lambda row: int(row["execution_order"]))
    return [row["run_id"] for row in rows]


def _read_run_matrix() -> list[dict[str, str]]:
    """Read the run matrix CSV into a list of row dicts."""
    with RUN_MATRIX_PATH.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _config_generators() -> dict[int, str]:
    """Map each config_id to its network generator name from network_configs.json."""
    payload = json.loads(NETWORK_CONFIGS_PATH.read_text(encoding="utf-8"))
    return {
        int(config["config_id"]): config["generator"] for config in payload["configs"]
    }


def _generator_abbr(generator: str | None) -> str:
    """Shorten a generator name (watts_strogatz -> ws) for display."""
    return GENERATOR_ABBREVS.get(generator or "", generator or "unknown")


def _generator_sort_key(abbr: str) -> tuple[int, int | str]:
    """Sort key that puts ws, hk, sbm first, then any other generator alphabetically."""
    if abbr in GENERATOR_ORDER:
        return (0, GENERATOR_ORDER.index(abbr))
    return (1, abbr)


def _now() -> str:
    """Current local time in the format used for started_at / finished_at."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse a stored timestamp, tolerating a few common formats."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
