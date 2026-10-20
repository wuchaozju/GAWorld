import copy
import importlib.util

import pytest

from gaworld.accounts.context import USER, WORLD
from gaworld.apps import research_api
from gaworld.research import workbench
from tests.test_organization_intelligence import residents


@pytest.fixture
def env(tmp_path, monkeypatch):
    name = "gaworld.apps.organization_intelligence_api"
    assert importlib.util.find_spec(name) is not None, "organization intelligence API is missing"
    from gaworld.apps import organization_intelligence_api as api
    from gaworld.research.organization_intelligence import store

    monkeypatch.setattr(workbench, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(store, "root", lambda: tmp_path / "studies")
    config = {
        "llm": {
            "providers": {"test": {"type": "openai", "model": "fixture", "api_key": "SECRET"}},
            "routing": {"default": "test"},
        }
    }
    monkeypatch.setattr(research_api, "_base_config", lambda: copy.deepcopy(config))
    monkeypatch.setattr(api, "population", residents)
    monkeypatch.setattr(api, "_ACTIVE", {})
    user = USER.set({"id": "alice", "role": "member"})
    world = WORLD.set({"id": "world-a"})
    yield api, store, config
    WORLD.reset(world)
    USER.reset(user)


def create(api):
    body, status = api.handle_post(api.PREFIX, {"repeats": 1, "provider": "test"})
    assert status == 201, body
    return body


def test_create_freezes_protocol_without_model_call(env):
    api, store, _ = env
    record = create(api)
    assert record["status"] == "draft"
    assert record["protocol"]["budget"]["requests"] == 109
    assert "SECRET" not in str(record)
    assert (store.directory(record["id"]) / "protocol.json").exists()
    assert record["protocol_hash"] == store.load(record["id"])["protocol_hash"]


def test_other_user_or_world_cannot_read_start_stop_or_export(env):
    api, _, _ = env
    record = create(api)
    for variable, value in ((USER, {"id": "bob", "role": "member"}), (WORLD, {"id": "world-b"})):
        token = variable.set(value)
        try:
            assert api.handle_get(api.PREFIX)[0]["studies"] == []
            for suffix in ("", "/export", "/logs"):
                assert api.handle_get(api.PREFIX + "/" + record["id"] + suffix)[1] == 404
            for suffix in ("run", "stop"):
                assert api.handle_post(api.PREFIX + "/" + record["id"] + "/" + suffix, {})[1] == 404
        finally:
            variable.reset(token)


def test_model_drift_blocks_launch(env):
    api, _, config = env
    record = create(api)
    config["llm"]["providers"]["test"]["model"] = "changed"
    body, status = api.handle_post(api.PREFIX + "/" + record["id"] + "/run", {})
    assert status == 400 and "模型" in body["error"]


def test_protocol_tampering_blocks_launch(env):
    api, store, _ = env
    record = create(api)
    record["protocol"]["seed"] = 1
    store.save(record)
    body, status = api.handle_post(api.PREFIX + "/" + record["id"] + "/run", {})
    assert status == 400 and "协议" in body["error"]


def test_routes_documented_and_member_launch_quota_gated():
    from gaworld.accounts import policy
    from gaworld.apps import openapi, routes

    path = "/api/research/organization-intelligence/OI" + "a" * 24 + "/run"
    route = routes.find(routes.POST_ROUTES, path)
    assert route.module == "organization_intelligence_api"
    assert policy.required("POST", path) == "member"
    assert policy.quota_gated(path)
    assert openapi.allowed_methods(path) == {"POST"}


def test_run_completion_persists_auditable_rows_and_no_second_launch(env, monkeypatch):
    from tests.test_organization_intelligence import fake

    api, store, _ = env
    record = create(api)
    monkeypatch.setattr(api, "make_caller", lambda spec: fake)
    monkeypatch.setattr(api.ownership, "spawn", lambda fn, *a, **kw: fn(*a))
    body, status = api.handle_post(api.PREFIX + "/" + record["id"] + "/run", {})
    assert status == 202, body
    completed = store.load(record["id"])
    assert completed["status"] == "completed"
    assert completed["calls_completed"] == 109
    assert len(completed["rows"]) == 27
    assert (store.directory(record["id"]) / "report.md").exists()
    assert api.handle_post(api.PREFIX + "/" + record["id"] + "/run", {})[1] == 400


def test_failure_persists_partial_evidence(env, monkeypatch):
    api, store, _ = env
    record = create(api)
    monkeypatch.setattr(api, "make_caller", lambda spec: lambda prompt: "bad json")
    monkeypatch.setattr(api.ownership, "spawn", lambda fn, *a, **kw: fn(*a))
    api.handle_post(api.PREFIX + "/" + record["id"] + "/run", {})
    failed = store.load(record["id"])
    assert failed["status"] == "failed"
    assert failed["rows"] == []
    assert "bad json" in (store.directory(record["id"]) / "events.jsonl").read_text()


def test_orphaned_run_becomes_interrupted(env):
    api, store, _ = env
    record = create(api)
    record["status"] = "running"
    record["runner_pid"] = 99999999
    store.save(record)
    result, status = api.handle_get(api.PREFIX + "/" + record["id"])
    assert status == 200 and result["status"] == "interrupted"


def test_worker_initialization_failure_releases_admission_and_records_failure(env, monkeypatch):
    from tests.test_organization_intelligence import fake

    api, store, _ = env
    record = create(api)
    monkeypatch.setattr(api, "make_caller", lambda spec: fake)
    queued = []
    monkeypatch.setattr(api.ownership, "spawn", lambda fn, *a, **kw: queued.append((fn, a)))

    def unavailable(*args, **kwargs):
        raise OSError("ledger unavailable")

    monkeypatch.setattr(api, "RunLedger", unavailable)
    api.handle_post(api.PREFIX + "/" + record["id"] + "/run", {})
    fn, args = queued[0]
    fn(*args)
    assert record["id"] not in api._ACTIVE
    assert store.load(record["id"])["status"] == "failed"


def test_stop_is_observed_after_first_response_before_any_next_request(env, monkeypatch):
    from tests.test_organization_intelligence import fake

    api, store, _ = env
    record = create(api)

    def stop_then_answer(prompt):
        store.atomic(store.directory(record["id"]) / "stop.request", "stop")
        return fake(prompt)

    monkeypatch.setattr(api, "make_caller", lambda spec: stop_then_answer)
    monkeypatch.setattr(api.ownership, "spawn", lambda fn, *a, **kw: fn(*a))
    api.handle_post(api.PREFIX + "/" + record["id"] + "/run", {})
    stopped = store.load(record["id"])
    assert stopped["status"] == "stopped" and stopped["calls_completed"] == 1
    assert not stopped["analysis"]["complete"]


def test_audit_reader_keeps_oversized_utf8_records_in_full(env):
    api, store, _ = env
    record = create(api)
    content = '{"message":"' + "原始记录" * 70000 + '"}\n'
    (store.directory(record["id"]) / "events.jsonl").write_text(content, encoding="utf-8")
    received, offset = "", 0
    while len(received) < len(content):
        chunk, status = api.handle_get(api.PREFIX + "/" + record["id"] + "/logs", {"offset": [offset]})
        assert status == 200 and chunk["next_offset"] > offset
        received += chunk["text"]
        offset = chunk["next_offset"]
    assert received == content
