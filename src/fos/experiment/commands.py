"""
Implementations of the runner commands: init, status, verify, run, retry.

init seeds the state store from the run matrix (idempotent), status prints
a progress summary (read-only), and verify checks that every result file
exists and contains the required keys (read-only). run and retry delegate
to the runner module, which owns the execution loop.

Functions:
    init()             — initialise the state store from the run matrix
    status()           — print the progress summary and return it
    verify()           — check every result file and print the outcome
    verify_runs()      — core verify logic, also usable from tests
    run()              — execute pending runs (delegates to runner.run)
    retry()            — reset failed runs to pending (delegates to runner.retry)
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fos.experiment import runner, store

REQUIRED_RESULT_KEYS = (
    "run_id",
    "schema_version",
    "config_id",
    "proposal_id",
    "population_id",
    "agents",
    "deliberation",
)


def init() -> None:
    """Create the tables, load the run matrix, and print what happened."""
    store.init_db()
    before = len(store.list_runs())
    store.seed_from_csv()
    total = len(store.list_runs())
    if before > 0:
        print(f"Already initialised — {total} runs present")
    else:
        print(f"Initialised {total} runs from run_matrix.csv")


def status(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Print the progress summary in the specified format and return it."""
    summary = store.get_status_summary(conn)
    print(_format_status(summary))
    return summary


def verify() -> None:
    """Check every expected result file and print the outcome."""
    report = verify_runs()
    if report["verified"] == report["total"]:
        print(f"{report['total']}/{report['total']} verified")
    else:
        print(f"Verified {report['verified']}/{report['total']}")
        if report["missing"]:
            print(f"Missing: {', '.join(report['missing'])}")
        for run_id, reason in report["invalid"]:
            print(f"Invalid: {run_id} ({reason})")


def run(
    limit: int | None = None,
    run_id: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Execute pending runs, or one specific run; returns how many completed."""
    return runner.run(limit=limit, run_id=run_id, conn=conn)


def retry(conn: sqlite3.Connection | None = None) -> int:
    """Reset every failed run back to pending; prints and returns the count."""
    return runner.retry(conn=conn)


def verify_runs(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Check every expected result file exists, parses, and has the required keys.

    Returns a report dict with total, verified, missing (run ids), and
    invalid (run id, reason) pairs.
    """
    run_ids = _all_run_ids(conn)
    missing: list[str] = []
    invalid: list[tuple[str, str]] = []
    verified = 0
    for run_id in run_ids:
        path = store.RESULTS_DIR / f"{run_id}.json"
        if not path.exists():
            missing.append(run_id)
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            invalid.append((run_id, f"not valid JSON ({type(exc).__name__})"))
            continue
        if not isinstance(payload, dict):
            invalid.append((run_id, "JSON is not an object"))
            continue
        absent = [key for key in REQUIRED_RESULT_KEYS if key not in payload]
        if absent:
            invalid.append((run_id, f"missing keys: {', '.join(absent)}"))
            continue
        verified += 1
    return {
        "total": len(run_ids),
        "verified": verified,
        "missing": missing,
        "invalid": invalid,
    }


def _all_run_ids(conn: sqlite3.Connection | None) -> list[str]:
    """Run ids from the state store, falling back to the matrix when the DB is empty."""
    try:
        runs = store.list_runs(conn=conn)
    except sqlite3.OperationalError:
        runs = []
    if runs:
        return [run["run_id"] for run in runs]
    return store.matrix_run_ids()


def _format_status(summary: dict[str, Any]) -> str:
    """Turn a status summary into the exact display text."""
    total = summary["total"]
    percent = (100.0 * summary["complete"] / total) if total else 0.0
    lines = [
        f"Experiment: {summary['n_proposals']} proposals x {summary['n_configs']} configs = {total} runs",
        f"Complete:  {summary['complete']} / {total}  ({percent:.1f}%)",
        f"Running:    {summary['running']}",
        f"Pending:   {summary['pending']}",
    ]
    if summary["failed"]:
        lines.append(
            f"Failed:     {summary['failed']}   ({', '.join(summary['failed_run_ids'])})"
        )
    else:
        lines.append(f"Failed:     {summary['failed']}")
    lines.append("")

    empty_line = f"Empty responses:   {summary['empty_pct']:.1f}% of calls"
    if summary["max_empty_run"]:
        run_id, pct = summary["max_empty_run"]
        empty_line += f" (max {pct:.1f}% in {run_id})"
    lines.append(empty_line)
    lines.append("")

    generator_parts = "   ".join(
        f"{abbr}  {f'{complete}/{total}':>5}"
        for abbr, (complete, total) in summary["by_generator"].items()
    )
    lines.append(f"By generator:      {generator_parts}")
    population_parts = "  ".join(
        f"{label} {complete}/{total}"
        for label, (complete, total) in summary["by_population"].items()
    )
    lines.append(f"By population:     {population_parts}")
    lines.append("")

    if summary["last_completed"]:
        last = summary["last_completed"]
        lines.append(f"Last completed: {last['run_id']}  ({last['finished_at']})")
    else:
        lines.append("Last completed: none")
    if summary["in_progress"]:
        lines.append(f"In progress:    {', '.join(summary['in_progress'])}")
    else:
        lines.append("In progress:    none")
    next_up = ", ".join(summary["next_up"]) if summary["next_up"] else "none"
    lines.append(f"Next up:        {next_up}")
    lines.append(
        f"Elapsed:        {_format_hours_minutes(summary['elapsed_seconds'])}"
        f"    Mean per run: {_format_minutes_seconds(summary['mean_per_run_seconds'])}"
    )
    lines.append(
        f"Est. remaining: {_format_hours_minutes(summary['est_remaining_seconds'])}"
        f"   ({summary['remaining_count']} runs pending/failed)"
    )
    return "\n".join(lines)


def _format_hours_minutes(total_seconds: float) -> str:
    """Format a duration as e.g. 6h 12m (minutes zero-padded)."""
    total = int(total_seconds)
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def _format_minutes_seconds(total_seconds: float) -> str:
    """Format a duration as e.g. 7m 55s (seconds zero-padded)."""
    total = int(total_seconds)
    minutes, seconds = divmod(total, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {seconds:02d}s"
