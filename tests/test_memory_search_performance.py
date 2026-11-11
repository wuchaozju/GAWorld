"""Exact retrieval and bounded work, using real temporary SQLite stores."""

from __future__ import annotations

import json
import math
import sqlite3
from unittest.mock import patch

import numpy as np
import pytest

from gaworld.memory import store as ms
from gaworld.settings import CONFIG


@pytest.fixture
def store(tmp_path, monkeypatch):
    ms._close_vector_db()
    monkeypatch.setattr(ms, "VECTOR_DB_PATH", str(tmp_path / "memory.sqlite"))
    monkeypatch.setitem(CONFIG, "memory", {"salience_weight": False})
    vectors = {"query": [1.0, 0.0, 0.0]}
    monkeypatch.setattr(ms, "_embed_text", lambda text: vectors[text])
    yield vectors
    ms._close_vector_db()


def add(vectors, text, vector, *, agent=1, kind="memory", salience=0.5):
    vectors[text] = vector
    ms.vector_db_add_entry(agent, kind, text, sim_day=1, sim_time="08:00", salience=salience)


def reference_search(*, agent=1, top_k=3, entry_types=None, weighted=False):
    """Original scalar-dot/full-sort ranking, before recall bookkeeping."""
    sql = "SELECT entry_type, text, sim_day, sim_time, embedding, created_at, salience, recall_count FROM memory_entries WHERE agent_id = ?"
    params = [agent]
    if entry_types:
        sql += f" AND entry_type IN ({','.join('?' for _ in entry_types)})"
        params.extend(entry_types)
    hits = []
    query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    for kind, text, day, clock, blob, created, salience, recalls in ms._vector_db_connect().execute(
        sql, params
    ):
        try:
            vector = np.array(json.loads(blob), dtype=np.float32)
        except (TypeError, json.JSONDecodeError):
            continue
        if vector.shape != query.shape:
            continue
        score = float(np.dot(query, vector))
        if score <= 0:
            continue
        if weighted:
            decay = math.exp(-max(0.0, (2_000_000_000 - created) / 86400) / 14)
            score *= 0.5 + 0.5 * max(0.0, min(1.0, float(salience or 0.5)))
            score *= decay
            score *= 1.0 + 0.1 * math.log1p(max(0, int(recalls or 0)))
        hits.append({"score": score, "type": kind, "text": text, "sim_day": day, "sim_time": clock})
    return sorted(hits, key=lambda hit: hit["score"], reverse=True)[: max(1, int(top_k))]


def test_repeated_search_does_not_decode_unchanged_vectors(store):
    for i in range(12):
        add(store, f"memory-{i}", [1.0, i / 20, 0.0])
    with patch.object(ms.json, "loads", wraps=json.loads) as decode:
        first = ms.vector_db_search(1, "query")
        assert decode.call_count == 12
    with patch.object(ms.json, "loads", wraps=json.loads) as decode:
        assert ms.vector_db_search(1, "query") == first
        assert decode.call_count == 0


@pytest.mark.parametrize("weighted", [False, True])
@pytest.mark.parametrize("top_k", [0, 1, 4, 100])
def test_exact_results_and_stable_ties_match_original(store, weighted, top_k, monkeypatch):
    monkeypatch.setitem(CONFIG, "memory", {"salience_weight": weighted})
    monkeypatch.setattr(ms.time, "time", lambda: 2_000_000_000)
    for i, score in enumerate([0.7, 0.9, 0.9, -0.2, 0.0, 0.4, 0.9]):
        add(store, f"memory-{i}", [score, 0.1, 0.0], salience=0.7)
    add(store, "other-type", [1.0, 0.0, 0.0], kind="external_info")
    add(store, "other-agent", [1.0, 0.0, 0.0], agent=2)
    expected = reference_search(top_k=top_k, entry_types=["memory"], weighted=weighted)
    assert ms.vector_db_search(1, "query", top_k=top_k, entry_types=["memory"]) == expected
    if weighted:
        rows = ms._vector_db_connect().execute("SELECT text, recall_count FROM memory_entries").fetchall()
        assert {text for text, count in rows if count} == {hit["text"] for hit in expected}
        expected = reference_search(top_k=top_k, entry_types=["memory"], weighted=True)
        assert ms.vector_db_search(1, "query", top_k=top_k, entry_types=["memory"]) == expected


def test_insert_update_and_delete_are_visible_after_warm_search(store):
    add(store, "first", [0.2, 0.0, 0.0])
    assert ms.vector_db_search(1, "query", top_k=1)[0]["text"] == "first"
    add(store, "second", [0.8, 0.0, 0.0])
    assert ms.vector_db_search(1, "query", top_k=1)[0]["text"] == "second"
    # A different connection models a writer outside the current process.
    with sqlite3.connect(ms.VECTOR_DB_PATH) as conn:
        conn.execute("UPDATE memory_entries SET embedding = ? WHERE text = 'first'", ("[1, 0, 0]",))
    assert ms.vector_db_search(1, "query", top_k=1)[0]["text"] == "first"
    ms.vector_db_delete_agent(1)
    assert ms.vector_db_search(1, "query") == []


def test_nonfinite_scores_keep_the_original_full_sort_order(store):
    for i, score in enumerate([0.6, float("nan"), 0.9, float("inf"), 0.7]):
        add(store, f"memory-{i}", [score, 0.0, 0.0])
    # JSON comparison also checks NaN positions, where float equality cannot.
    expected = json.dumps(reference_search(), sort_keys=True)
    assert json.dumps(ms.vector_db_search(1, "query"), sort_keys=True) == expected


def test_cache_is_bounded_and_vectors_are_immutable(store):
    from gaworld.memory.vector_cache import decode_vector

    decode_vector.cache_clear()
    vector = decode_vector(ms.VECTOR_DB_PATH, "[1, 0, 0]")
    with pytest.raises(ValueError):
        vector[0] = 9
    for i in range(decode_vector.cache_info().maxsize + 1):
        decode_vector(ms.VECTOR_DB_PATH, f"[{i}, 0, 0]")
    assert decode_vector.cache_info().currsize == decode_vector.cache_info().maxsize


def test_new_database_does_not_reuse_another_worlds_cache(store, tmp_path, monkeypatch):
    add(store, "private-first", [0.2, 0.0, 0.0])
    ms.vector_db_search(1, "query")
    ms._close_vector_db()
    monkeypatch.setattr(ms, "VECTOR_DB_PATH", str(tmp_path / "other.sqlite"))
    add(store, "private-second", [0.2, 0.0, 0.0])
    with patch.object(ms.json, "loads", wraps=json.loads) as decode:
        hits = ms.vector_db_search(1, "query")
        assert [hit["text"] for hit in hits] == ["private-second"]
        assert decode.call_count == 1


def test_malformed_and_wrong_dimension_vectors_keep_existing_skip_behavior(store):
    add(store, "good", [0.5, 0.0, 0.0])
    add(store, "wrong-dimension", [1.0, 0.0])
    add(store, "broken", [0.8, 0.0, 0.0])
    conn = ms._vector_db_connect()
    with conn:
        conn.execute("UPDATE memory_entries SET embedding = 'not json' WHERE text = 'broken'")
    assert ms.vector_db_search(1, "query") == reference_search()


def test_memory_search_reports_its_own_timing_without_changing_hits(store):
    from gaworld.core.performance import ACTIVE_TIMINGS, TimingCollector

    add(store, "one", [1.0, 0.0, 0.0])
    expected = reference_search()
    stats = TimingCollector()
    token = ACTIVE_TIMINGS.set(stats)
    try:
        assert ms.vector_db_search(1, "query") == expected
        assert stats.snapshot()["operations"]["memory.search"]["calls"] == 1
    finally:
        ACTIVE_TIMINGS.reset(token)


def test_oversized_scan_keeps_cached_prefix_instead_of_evicting_every_vector(store):
    from gaworld.memory.vector_cache import VECTOR_CACHE_SIZE

    ms._init_vector_db()
    conn = ms._vector_db_connect()
    with conn:
        conn.executemany(
            "INSERT INTO memory_entries(agent_id, entry_type, text, created_at, embedding) VALUES (?, ?, ?, ?, ?)",
            [
                (1, "memory", f"m{i}", 2e9, json.dumps([1.0, i / 10000, 0.0]))
                for i in range(VECTOR_CACHE_SIZE + 1)
            ],
        )
    first = ms.vector_db_search(1, "query", top_k=1)
    with patch.object(ms.json, "loads", wraps=json.loads) as decode:
        assert ms.vector_db_search(1, "query", top_k=1) == first
        # The uncached tail may decode, but it must not evict the whole prefix.
        assert decode.call_count == 1


def test_alternating_residents_preserve_vectors_needed_later_in_the_same_scan(store):
    from gaworld.memory.vector_cache import VECTOR_CACHE_SIZE

    ms._init_vector_db()
    size = 2500
    conn = ms._vector_db_connect()
    with conn:
        conn.executemany(
            "INSERT INTO memory_entries(agent_id, entry_type, text, created_at, embedding) VALUES (?, ?, ?, ?, ?)",
            [
                (agent, "memory", f"a{agent}-m{i}", 2e9, json.dumps([1.0, (agent * size + i) / 10000, 0.0]))
                for agent in (1, 2)
                for i in range(size)
            ],
        )
    ms.vector_db_search(1, "query")
    ms.vector_db_search(2, "query")
    for agent in (1, 2, 1, 2):
        expected = reference_search(agent=agent)
        with patch.object(ms.json, "loads", wraps=json.loads) as decode:
            assert ms.vector_db_search(agent, "query") == expected
            # Existing resident vectors must not be evicted before we reach
            # them later in the row scan. Only the other resident's excess
            # over global capacity needs decoding again.
            assert decode.call_count == size * 2 - VECTOR_CACHE_SIZE
