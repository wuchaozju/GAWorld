"""
SQLite schema for the checkpointed experiment runner's state store.

Defines the tables (runs, run_progress, agent_calls) and the migration that
adds columns introduced after the first release to pre-existing databases.
The store module imports TABLES and runs them in init_db.

Functions:
    migrate_runs_table(conn) — add the empty-response columns if missing
"""

from __future__ import annotations

import sqlite3

TABLES = (
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'pending',
        config_id INTEGER NOT NULL,
        proposal_id TEXT NOT NULL,
        population_id TEXT NOT NULL,
        execution_order INTEGER NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        attempts INTEGER DEFAULT 0,
        last_error TEXT,
        output_path TEXT,
        empty_response_count INTEGER DEFAULT 0,
        total_llm_calls INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS run_progress (
        run_id TEXT NOT NULL,
        stage TEXT NOT NULL,
        completed_at TEXT NOT NULL,
        PRIMARY KEY (run_id, stage),
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_calls (
        run_id TEXT NOT NULL,
        round_index INTEGER NOT NULL,
        agent_uid TEXT NOT NULL,
        response_json TEXT NOT NULL,
        completed_at TEXT NOT NULL,
        PRIMARY KEY (run_id, round_index, agent_uid),
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    )
    """,
)


def migrate_runs_table(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the first release to an existing runs table."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    additions = {"empty_response_count": "INTEGER DEFAULT 0", "total_llm_calls": "INTEGER DEFAULT 0"}
    for column, definition in additions.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {column} {definition}")
