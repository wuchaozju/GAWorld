"""Tests for the playground game archive (gaworld.apps.game_archive).

What we defend:

* a store opened with ``archive=True`` writes each finished result — with
  its kind, job id and routed provider — before the job reads as done;
* stores without the flag, and empty results, write nothing;
* a failing write costs the archive, never the player's result;
* on a shared server the file says who played;
* the three games GAWorld-Bench Track B reads are the ones archived;
* a rumor resident's belief history is kept turn by turn.

``tests/conftest.py`` points ``ARCHIVE_DIR`` at a per-test directory.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from gaworld.accounts.context import USER
from gaworld.apps import disaster_api, game_archive, referendum_api, rumor_api
from gaworld.apps.game_jobs import JobStore


def _settle(store: JobStore, job_id: str, timeout: float = 2.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = store.status(job_id)
        if record and record["status"] != "running":
            return record
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never finished")


def _files(kind: str) -> list[Path]:
    return sorted((Path(game_archive.ARCHIVE_DIR) / kind).glob("*.json"))


def test_a_finished_game_is_on_disk_when_the_job_reads_done(monkeypatch) -> None:
    monkeypatch.setattr("gaworld.llm.providers.resolve_provider", lambda task=None, **_: f"stub:{task}")
    store = JobStore("demo", archive=True)
    job_id = store.run(lambda progress: {"run_id": "r1", "created_at": 1.0})
    record = _settle(store, job_id)
    assert record["status"] == "done"
    files = _files("demo")
    assert len(files) == 1 and files[0].name.endswith(f"-{job_id}.json")
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert saved["kind"] == "demo" and saved["job_id"] == job_id
    assert saved["provider"] == "stub:games.demo"
    assert saved["result"] == {"run_id": "r1", "created_at": 1.0}
    assert "owner_id" not in saved  # single-user mode: nobody to name


def test_unflagged_stores_and_empty_results_write_nothing() -> None:
    plain = JobStore("plain")
    _settle(plain, plain.run(lambda progress: {"run_id": "x"}))
    flagged = JobStore("empty", archive=True)
    _settle(flagged, flagged.run(lambda progress: {}))
    assert _files("plain") == [] and _files("empty") == []


def test_a_failed_write_keeps_the_players_result(monkeypatch, tmp_path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(game_archive, "ARCHIVE_DIR", str(blocker))
    assert game_archive.save("demo", "demo-1", {"run_id": "r"}) is None
    store = JobStore("demo", archive=True)
    record = _settle(store, store.run(lambda progress: {"run_id": "r2"}))
    assert record["status"] == "done" and record["result"] == {"run_id": "r2"}


def test_a_shared_server_records_who_played() -> None:
    token = USER.set({"id": 7, "nickname": "阿青", "role": "member"})
    try:
        path = game_archive.save("demo", "demo-2", {"run_id": "r"})
    finally:
        USER.reset(token)
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    assert (saved["owner_id"], saved["owner"]) == (7, "阿青")


def test_the_three_track_b_games_are_archived() -> None:
    for module in (rumor_api, referendum_api, disaster_api):
        assert module._JOBS.archive, module.__name__


def test_a_corrected_believer_keeps_both_beliefs() -> None:
    nodes = {
        1: rumor_api.Node(agent_id=1, name="甲1", persona_text="你是甲1"),
        2: rumor_api.Node(agent_id=2, name="乙2", persona_text="你是乙2"),
    }
    edges = [{"a": 1, "b": 2, "label": "邻居", "closeness": 0.6}]

    def answer(prompt: str) -> str:
        if "你是甲1" in prompt:
            belief, action = (20, "不管") if "你之前听到这条" in prompt else (90, "转发")
        else:
            belief, action = 5, "辟谣"
        return json.dumps({"belief": belief, "action": action, "say": "…"}, ensure_ascii=False)

    run = rumor_api.run_rumor(
        city="",
        agent_ids=[],
        rumor_id="water",
        nodes=nodes,
        edges=edges,
        seeds=[1],
        rounds=3,
        answer_fn=answer,
        summary_fn=lambda p: "",
    )
    by_id = {n["agent_id"]: n for n in run["nodes"]}
    assert by_id[1]["beliefs"] == [90, 20]
    assert by_id[2]["beliefs"] == [5]
