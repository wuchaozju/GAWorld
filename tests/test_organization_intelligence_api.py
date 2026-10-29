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
    monkeypatch.setattr(api, "pace", lambda *a: None)
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


def test_429_pauses_once_and_records_actionable_reason(env, monkeypatch):
    from tests.test_organization_intelligence import fake
    from tests.test_organization_intelligence_recovery import http_error

    api, store, _ = env
    record = create(api)
    submitted = []

    def limited(prompt):
        submitted.append(prompt)
        if len(submitted) == 7:
            raise http_error()
        return fake(prompt)

    monkeypatch.setattr(api, "make_caller", lambda spec: limited)
    monkeypatch.setattr(api.ownership, "spawn", lambda fn, *a, **kw: fn(*a))
    api.handle_post(api.PREFIX + "/" + record["id"] + "/run", {})
    paused = store.load(record["id"])
    assert paused["status"] == "rate_limited"
    assert paused["rate_limit"]["kind"] == "token_plan_2062"
    assert len(submitted) == 7 and paused["valid_responses"] == 6
    assert paused["rate_limit"]["retry_at"] > paused["finished_at"]


def test_recovery_draft_preserves_original_and_reuses_only_verified_prefix(env, monkeypatch):
    import json

    from tests.test_organization_intelligence import fake
    from tests.test_organization_intelligence_recovery import http_error

    api, store, _ = env
    record = create(api)
    submitted = []

    def limited(prompt):
        submitted.append(prompt)
        if len(submitted) == 7:
            raise http_error(retry_after=0)
        return fake(prompt)

    monkeypatch.setattr(api, "make_caller", lambda spec: limited)
    monkeypatch.setattr(api.ownership, "spawn", lambda fn, *a, **kw: fn(*a))
    api.handle_post(api.PREFIX + "/" + record["id"] + "/run", {})
    original = (store.directory(record["id"]) / "study.json").read_bytes()
    recovered, status = api.handle_post(api.PREFIX + "/" + record["id"] + "/recover", {})
    assert status == 201, recovered
    assert recovered["status"] == "draft" and len(submitted) == 7
    assert recovered["id"] != record["id"]
    assert recovered["protocol"]["blocks"] == record["protocol"]["blocks"]
    assert recovered["protocol"]["recovery"]["responses"] == 6
    path = api.PREFIX + "/" + recovered["id"] + "/run"
    assert api.handle_post(path, {})[1] == 400  # Retry-After floor is enforced at launch too.
    monkeypatch.setattr(api.time, "time", lambda: json.loads(original)["finished_at"] + 1000)
    calls = []
    monkeypatch.setattr(api, "make_caller", lambda spec: lambda prompt: calls.append(prompt) or fake(prompt))
    assert api.handle_post(path, {})[1] == 202
    result = store.load(recovered["id"])
    assert result["status"] == "completed" and result["replayed_responses"] == 6
    assert result["valid_responses"] == 109 and len(calls) == 103
    assert result["analysis"]["complete"]
    assert (store.directory(record["id"]) / "study.json").read_bytes() == original
    report = api.handle_get(api.PREFIX + "/" + recovered["id"] + "/export")[0]["markdown"]
    assert "6" in report and record["id"] in report


def test_recovery_rejects_model_drift_and_other_owner(env):
    api, store, config = env
    record = create(api)
    record["status"] = "failed"
    store.save(record)
    config["llm"]["providers"]["test"]["model"] = "changed"
    body, status = api.handle_post(api.PREFIX + "/" + record["id"] + "/recover", {})
    assert status == 400 and "模型" in body["error"]
    token = USER.set({"id": "bob", "role": "member"})
    try:
        assert api.handle_post(api.PREFIX + "/" + record["id"] + "/recover", {})[1] == 404
    finally:
        USER.reset(token)


def test_fresh_study_cannot_bypass_provider_cooldown(env, monkeypatch):
    from tests.test_organization_intelligence_recovery import http_error

    api, store, _ = env
    original = create(api)
    monkeypatch.setattr(api, "make_caller", lambda spec: lambda p: (_ for _ in ()).throw(http_error()))
    monkeypatch.setattr(api.ownership, "spawn", lambda fn, *a, **kw: fn(*a))
    api.handle_post(api.PREFIX + "/" + original["id"] + "/run", {})
    another = create(api)
    body, status = api.handle_post(api.PREFIX + "/" + another["id"] + "/run", {})
    assert status == 400 and "限流" in body["error"]
    assert store.load(another["id"])["calls_started"] == 0


def test_chained_recovery_retains_full_prefix_when_stopped_during_replay(env, monkeypatch):
    from tests.test_organization_intelligence import fake

    api, store, _ = env
    parent = create(api)
    calls = []

    def stop_at_six(prompt):
        calls.append(prompt)
        if len(calls) == 6:
            store.atomic(store.directory(parent["id"]) / "stop.request", "stop")
        return fake(prompt)

    monkeypatch.setattr(api, "make_caller", lambda spec: stop_at_six)
    monkeypatch.setattr(api.ownership, "spawn", lambda fn, *a, **kw: fn(*a))
    api.handle_post(api.PREFIX + "/" + parent["id"] + "/run", {})
    child, status = api.handle_post(api.PREFIX + "/" + parent["id"] + "/recover", {})
    assert status == 201
    write = store.event

    def stop_replaying(identifier, event):
        write(identifier, event)
        if event.get("replayed") and event["number"] == 2:
            store.atomic(store.directory(identifier) / "stop.request", "stop")

    monkeypatch.setattr(store, "event", stop_replaying)
    api.handle_post(api.PREFIX + "/" + child["id"] + "/run", {})
    assert store.load(child["id"])["status"] == "stopped"
    grandchild, status = api.handle_post(api.PREFIX + "/" + child["id"] + "/recover", {})
    assert status == 201
    assert grandchild["protocol"]["recovery"]["responses"] == 6
    assert len(calls) == 6  # Replay never reached any provider call.


def test_eta_excludes_replayed_work_and_includes_future_spacing(env):
    api, _, _ = env
    record = create(api)
    record.update(status="running", valid_responses=50, replayed_responses=49)

    class Timing:
        def snapshot(self, fraction):
            return {
                "elapsed_seconds": 1,
                "wall_seconds": 500,
                "paused_seconds": 499,
                "remaining_seconds": None,
            }

    estimate = api.timing_snapshot(record, {"timing": Timing()})
    assert estimate["remaining_seconds"] >= (109 - 50) * 10


def test_real_router_and_http_ledger_pause_on_mocked_minimax_2062(env, monkeypatch):
    import json

    import requests

    from gaworld.llm import providers
    from tests.test_organization_intelligence import fake

    api, store, config = env
    config["llm"]["providers"]["test"]["type"] = "anthropic"
    config["llm"]["providers"]["test"]["base_url"] = "https://example.invalid/anthropic"
    record = create(api)
    submissions, charged = [], []

    def post(url, **kwargs):
        submissions.append(kwargs["json"]["messages"][0]["content"])
        response = requests.Response()
        response.status_code = 429 if len(submissions) == 7 else 200
        body = (
            {"error": {"type": "rate_limit_error", "message": "Token Plan (2062)"}}
            if response.status_code == 429
            else {"content": [{"type": "text", "text": fake("")}], "stop_reason": "end_turn"}
        )
        response._content = json.dumps(body).encode()
        return response

    monkeypatch.setattr(providers.requests, "post", post)
    monkeypatch.setattr(api.usage, "record", lambda task: charged.append(task))
    monkeypatch.setattr(api.ownership, "spawn", lambda fn, *a, **kw: fn(*a))
    api.handle_post(api.PREFIX + "/" + record["id"] + "/run", {})
    result = store.load(record["id"])
    assert result["status"] == "rate_limited"
    assert len(submissions) == len(charged) == 7
    assert result["telemetry"]["http_attempts"] == 7
    assert result["telemetry"]["http_failures"] == 1
    assert result["telemetry"]["requests_fell_back"] == 0
    assert result["valid_responses"] == 6
    assert not result["analysis"]["complete"]


@pytest.mark.parametrize("tail", [b"", b'{"kind":"response","message":"\xe4\xb8'])
def test_recovery_preserves_unicode_separators_and_ignores_partial_utf8_tail(env, monkeypatch, tail):
    import json

    api, store, _ = env
    record = create(api)

    def stop_then_answer(prompt):
        store.atomic(store.directory(record["id"]) / "stop.request", "stop")
        return json.dumps({"choice": 1, "message": "证据\u2028第二段\u2029第三段"}, ensure_ascii=False)

    monkeypatch.setattr(api, "make_caller", lambda spec: stop_then_answer)
    monkeypatch.setattr(api.ownership, "spawn", lambda fn, *a, **kw: fn(*a))
    api.handle_post(api.PREFIX + "/" + record["id"] + "/run", {})
    with (store.directory(record["id"]) / "events.jsonl").open("ab") as handle:
        handle.write(tail)
    recovered, status = api.handle_post(api.PREFIX + "/" + record["id"] + "/recover", {})
    assert status == 201, recovered
    assert recovered["protocol"]["recovery"]["responses"] == 1
