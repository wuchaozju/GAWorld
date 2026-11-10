"""Durable, scoped population jobs; no network or real model calls."""

import concurrent.futures
import json

import pytest

from gaworld.accounts.context import USER, WORLD
from gaworld.apps import population_api as api


@pytest.fixture(autouse=True)
def isolated_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(api.world_paths, "run_root", lambda: str(tmp_path))
    monkeypatch.setattr(api, "_JOBS", {})
    monkeypatch.setattr(api, "_LAST_POPULATION", {})
    monkeypatch.setattr(api, "_SCOPED_POPULATIONS", {}, raising=False)
    tokens = (USER.set(None), WORLD.set(None))
    yield tmp_path
    USER.reset(tokens[0])
    WORLD.reset(tokens[1])


def complete_inline(monkeypatch):
    monkeypatch.setattr(api.ownership, "spawn", lambda work, **kwargs: work())


def test_terminal_job_survives_memory_eviction(monkeypatch, isolated_jobs):
    complete_inline(monkeypatch)
    started = api.start_population_job({"spec": {"size": 20}, "request_id": "generation-123456"})
    before = api.job_status(started["job_id"])
    assert before["status"] == "done"
    api._JOBS.clear()
    api._LAST_POPULATION.clear()
    after = api.job_status(started["job_id"])
    assert after["result"]["people"] == before["result"]["people"]
    assert len(api.export_population("csv")["content"].splitlines()) == 21
    metadata = json.loads((isolated_jobs / "population" / "jobs" / (started["job_id"] + ".json")).read_text())
    assert "people" not in json.dumps(metadata)
    assert metadata.get("result") is None


def test_same_request_is_idempotent_after_restart(monkeypatch):
    complete_inline(monkeypatch)
    payload = {"spec": {"size": 20}, "request_id": "same-request-123"}
    first = api.start_population_job(payload)
    api._JOBS.clear()
    second = api.start_population_job(payload)
    assert second["job_id"] == first["job_id"]
    with pytest.raises(ValueError, match="提交标识"):
        api.start_population_job({**payload, "spec": {"size": 21}})


def test_concurrent_duplicate_posts_start_one_worker(monkeypatch):
    started = []
    monkeypatch.setattr(api, "_run_in_background", lambda job_id, work: started.append(job_id))
    payload = {"spec": {"size": 20}, "request_id": "concurrent-request-123"}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: api.start_population_job(payload), range(12)))
    assert len({r["job_id"] for r in results}) == 1
    assert len(started) == 1


def test_reads_check_owner_and_world_in_memory_and_on_disk(monkeypatch):
    complete_inline(monkeypatch)
    USER.set({"id": "alice", "role": "member"})
    WORLD.set({"id": "world-a"})
    started = api.start_population_job({"spec": {"size": 20}, "request_id": "owner-request-123"})
    assert api.job_status(started["job_id"])["status"] == "done"
    USER.set({"id": "bob", "role": "member"})
    assert api.job_status(started["job_id"]) is None
    api._JOBS.clear()
    assert api.job_status(started["job_id"]) is None
    USER.set({"id": "alice", "role": "member"})
    WORLD.set({"id": "world-b"})
    assert api.job_status(started["job_id"]) is None
    assert api.handle_get("/api/population/last")[0]["count"] == 0
    with pytest.raises(ValueError):
        api.export_population("csv")


def test_orphaned_running_job_is_interrupted_not_running(monkeypatch):
    monkeypatch.setattr(api, "_run_in_background", lambda *args: None)
    started = api.start_population_job({"spec": {"size": 20}, "request_id": "interrupted-request-123"})
    api._JOBS.clear()
    record = api.job_status(started["job_id"])
    assert record["status"] == "error"
    assert record["error"]["code"] == "service_restarted"


def test_recover_by_request_handles_list_query_values(monkeypatch):
    complete_inline(monkeypatch)
    started = api.start_population_job({"spec": {"size": 20}, "request_id": "reply-lost-request-123"})
    api._JOBS.clear()
    record, status = api.handle_get("/api/population/recover", {"request_id": ["reply-lost-request-123"]})
    assert status == 200
    assert record["id"] == started["job_id"]


def test_payload_and_bad_request_ids_are_not_recoverable(monkeypatch):
    complete_inline(monkeypatch)
    with pytest.raises(ValueError, match="提交标识"):
        api.start_population_job({"spec": {"size": 20}, "request_id": "../evil"})
    assert api.job_status("../../outside") is None
    assert api.handle_get("/api/population/recover", {"request_id": ["missing-request-123"]})[1] == 404


def test_same_request_in_other_scope_does_not_reuse_a_job(monkeypatch):
    complete_inline(monkeypatch)
    payload = {"spec": {"size": 20}, "request_id": "separate-scope-123"}
    USER.set({"id": "alice", "role": "member"})
    a = api.start_population_job(payload)
    USER.set({"id": "bob", "role": "member"})
    b = api.start_population_job(payload)
    assert a["job_id"] != b["job_id"]
    assert api.recover_job(payload["request_id"])["id"] == b["job_id"]


def test_restored_population_supports_group_run_without_regenerating(monkeypatch):
    complete_inline(monkeypatch)
    generated = api.start_population_job({"spec": {"size": 20}, "request_id": "restore-source-123"})
    api._JOBS.clear()
    api._LAST_POPULATION.clear()
    started = api.start_group_job(
        {
            "population_job_id": generated["job_id"],
            "source": "last",
            "days": 1,
            "materialization_budget": 0,
            "request_id": "restore-group-123",
        }
    )
    record = api.job_status(started["job_id"])
    assert record["status"] == "done"
    assert record["result"]["cost"]["population"] == 20
    assert record["population_job_id"] == generated["job_id"]


def test_queued_group_captures_source_before_other_population_replaces_it(monkeypatch):
    complete_inline(monkeypatch)
    api.start_population_job({"spec": {"size": 20}})
    pending = []
    monkeypatch.setattr(api, "_run_in_background", lambda job_id, work: pending.append(work))
    api.start_group_job({"source": "last", "days": 1, "materialization_budget": 0})
    original = api._last_population()["job_id"]
    api._LAST_POPULATION.clear()
    result = pending[0](lambda *_: None)
    assert result["cost"]["population"] == 20
    assert original


@pytest.mark.parametrize("kind", ["group", "validate"])
@pytest.mark.parametrize("explicit", [True, False])
def test_follow_on_submission_and_work_use_same_population_during_replacement(monkeypatch, kind, explicit):
    """A second tab replacing the shared cache during admission cannot change the sample."""
    import inspect

    complete_inline(monkeypatch)
    generated = api.start_population_job({"spec": {"size": 20}})
    selected_id = generated["job_id"]
    pending = []
    monkeypatch.setattr(api, "_run_in_background", lambda jid, work: pending.append(work))
    original_claim = api._claim_job

    def replace_during_claim(job_kind, payload):
        result = original_claim(job_kind, payload)
        population = api._last_population()
        population.clear()
        population.update(job_id="pop-other", agents=[{"id": 999}], neighbours={})
        return result

    monkeypatch.setattr(api, "_claim_job", replace_during_claim)
    payload = {"source": "last", "days": 1, "materialization_budget": 0}
    if explicit:
        payload["population_job_id"] = selected_id
    started = (api.start_group_job if kind == "group" else api.start_validation_job)(payload)
    frozen = inspect.getclosurevars(pending[0]).nonlocals["frozen_population"]
    assert api._JOBS[started["job_id"]]["population_job_id"] == selected_id
    assert frozen["job_id"] == selected_id
    assert len(frozen["agents"]) == 20
