"""Small contiguous memory groups commit once, with real SQLite behavior."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from gaworld.core.performance import ACTIVE_TIMINGS, TimingCollector
from gaworld.core.runner import parallel_map
from gaworld.memory import store as ms
from gaworld.sim import _stages

ENTRIES = [
    ("log", "log text"),
    ("plan", "plan text"),
    ("reflection", "reflection text"),
    ("action", "action text"),
]


@pytest.fixture
def store(tmp_path, monkeypatch):
    ms._close_vector_db()
    ms._LOG_CACHE.clear()
    monkeypatch.setattr(ms, "VECTOR_DB_PATH", str(tmp_path / "memory.sqlite"))
    monkeypatch.setattr(ms, "LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(ms, "_embed_text", lambda text: [1.0, 0.0, 0.0])
    monkeypatch.setattr(ms.time, "time", lambda: 2_000_000_000)
    yield
    ms._close_vector_db()
    ms._LOG_CACHE.clear()


def rows():
    return (
        ms._vector_db_connect()
        .execute(
            "SELECT agent_id, entry_type, text, sim_day, sim_time, created_at, embedding, salience, emotion "
            "FROM memory_entries ORDER BY id"
        )
        .fetchall()
    )


def test_record_stage_commits_four_memories_once(store):
    ms._init_vector_db()
    statements = []
    ms._vector_db_connect().set_trace_callback(statements.append)
    scope = _stages.StepScope(day=1, time_str="08:00", daily_logs={1: ""}, log_simple=False)
    step = {
        "_plan_text": "plan text",
        "_refl_text": "reflection text",
        "_outcome": "action text",
        "_act": "work",
    }
    _stages._stage_record(
        {"id": 1, "name": "fixture", "state": {}}, step, SimpleNamespace(recorder=None), scope=scope
    )
    assert [row[1] for row in rows()] == ["log", "plan", "reflection", "action"]
    assert sum(sql == "COMMIT" for sql in statements) == 1
    assert sum(sql == "BEGIN " for sql in statements) == 1
    assert "plan text" in step["log"]


def test_batch_has_exactly_the_same_rows_as_single_inserts(store):
    entries = [("log", " first\n text "), ("plan", "   "), ("reflection", "other text")]
    for kind, text in entries:
        ms.vector_db_add_entry(1, kind, text, 2, "09:00", salience=1.5, emotion=-1.5)
    expected = rows()
    # Independent fixed field expectations, not just two paths sharing the
    # same implementation (the pre-batch single-row contract).
    assert expected == [
        (1, kind, text, 2, "09:00", 2_000_000_000, "[1.0, 0.0, 0.0]", 1.0, -1.0)
        for kind, text in [("log", "first text"), ("reflection", "other text")]
    ]
    ms.vector_db_delete_agent(1)
    ms.vector_db_add_entries(1, entries, 2, "09:00", salience=1.5, emotion=-1.5)
    assert rows() == expected


@pytest.mark.parametrize("entries", [[], [("log", ""), ("plan", "  \n ")]])
def test_empty_batch_does_not_create_database_or_embeddings(store, entries, monkeypatch):
    def forbidden(text):
        raise AssertionError("empty text was embedded")

    monkeypatch.setattr(ms, "_embed_text", forbidden)
    ms.vector_db_add_entries(1, entries)
    assert not Path(ms.VECTOR_DB_PATH).exists()


def test_embedding_preparation_is_in_order_and_outside_write_transaction(store, monkeypatch):
    ms._init_vector_db()
    seen = []
    with sqlite3.connect(ms.VECTOR_DB_PATH) as observer:

        def embed(text):
            assert not ms._vector_db_connect().in_transaction
            assert observer.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0] == 0
            seen.append(text)
            return [1.0, 0.0, 0.0]

        monkeypatch.setattr(ms, "_embed_text", embed)
        ms.vector_db_add_entries(1, ENTRIES, 1, "08:00")
        assert observer.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0] == 4
    assert seen == [text for _, text in ENTRIES]
    assert [row[1] for row in rows()] == [kind for kind, _ in ENTRIES]


def test_sql_error_rolls_back_the_whole_batch(store):
    ms._init_vector_db()
    conn = ms._vector_db_connect()
    conn.execute(
        "CREATE TRIGGER reject_reflection BEFORE INSERT ON memory_entries "
        "WHEN NEW.entry_type = 'reflection' BEGIN SELECT RAISE(ABORT, 'fixture rejection'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="fixture rejection"):
        ms.vector_db_add_entries(1, ENTRIES)
    assert rows() == []
    assert not conn.in_transaction


def test_embedding_failure_does_not_write_a_partial_batch(store, monkeypatch):
    def embed(text):
        if text == "reflection text":
            raise ValueError("fixture embedding failure")
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(ms, "_embed_text", embed)
    with pytest.raises(ValueError, match="fixture embedding failure"):
        ms.vector_db_add_entries(1, ENTRIES)
    assert rows() == []


def test_worker_batches_keep_all_rows_and_per_agent_order(store):
    ms._init_vector_db()
    parallel_map(lambda agent: ms.vector_db_add_entries(agent, ENTRIES), range(1, 17), max_workers=4)
    actual = rows()
    assert len(actual) == 64
    for agent in range(1, 17):
        assert [row[1] for row in actual if row[0] == agent] == [kind for kind, _ in ENTRIES]
    assert all(json.loads(row[6]) == [1.0, 0.0, 0.0] for row in actual)


def test_write_timing_counts_one_operation_for_one_group(store):
    stats = TimingCollector()
    token = ACTIVE_TIMINGS.set(stats)
    try:
        ms.vector_db_add_entries(1, ENTRIES)
        assert stats.snapshot()["operations"]["memory.write"]["calls"] == 1
    finally:
        ACTIVE_TIMINGS.reset(token)


def test_generator_batch_and_single_entry_keep_default_fields(store):
    ms.vector_db_add_entries(1, (entry for entry in ENTRIES), 1, "08:00")
    ms.vector_db_add_entry(2, "episode", "same-day episode", 1, "08:00")
    actual = rows()
    assert [row[1] for row in actual] == [kind for kind, _ in ENTRIES] + ["episode"]
    assert all(row[-2:] == (0.5, 0.0) for row in actual)
