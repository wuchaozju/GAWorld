import copy
import importlib.util

import pytest

from gaworld.accounts.context import USER, WORLD
from gaworld.collaboration.organization_methods import baseline


@pytest.fixture
def env(tmp_path, monkeypatch):
    assert importlib.util.find_spec("gaworld.apps.organization_comparison_api"), "comparison API missing"
    from gaworld.apps import organization_comparison_api as api
    from gaworld.apps import organization_methods_api as methods
    from gaworld.research.organization_intelligence.comparison.store import Store

    monkeypatch.setattr(api, "database", lambda: Store(tmp_path / "studies"))
    monkeypatch.setattr(methods, "database", lambda: Store(tmp_path / "methods"))
    monkeypatch.setattr(api.legacy, "population", lambda: [{"id": i, "name": f"m{i}"} for i in range(1, 5)])
    model = {"name": "test", "model": "fixture", "fingerprint": "frozen"}
    monkeypatch.setattr(api.legacy, "model_info", lambda name="": copy.deepcopy(model))
    monkeypatch.setattr(api.legacy, "make_caller", lambda spec: lambda prompt: '{"answer":"A"}')
    monkeypatch.setattr(api.ownership, "spawn", lambda fn, *a, **kw: fn(*a))
    monkeypatch.setattr(api.runner.execution, "wait_for_request", lambda *a, **kw: None)
    u, w = USER.set({"id": "alice", "role": "member"}), WORLD.set({"id": "a"})
    yield api, methods, model
    WORLD.reset(w)
    USER.reset(u)


def create(api):
    value, status = api.handle_post(
        api.PREFIX,
        {
            "candidate": baseline("full", 3),
            "agent_ids": [1, 2, 3],
            "provider": "test",
            "count": 2,
            "repeats": 1,
        },
    )
    assert status == 201, value
    return value


def test_create_then_run_export_and_save_to_library(env):
    api, methods, _ = env
    draft = create(api)
    assert draft["status"] == "draft" and draft["rows"] == []
    url = api.PREFIX + "/" + draft["id"]
    assert api.handle_post(url + "/run", {})[1] == 202
    completed = api.handle_get(url)[0]
    assert completed["status"] == "completed"
    assert len(completed["rows"]) == 4
    assert api.handle_get(url + "/export")[0]["markdown"].startswith("# ")
    saved, status = api.handle_post(url + "/save-method", {"name": "tested"})
    assert status == 201, saved
    assert methods.resolve(saved["id"], 1)["method"] == saved["method"]
    assert methods.handle_get(methods.PREFIX)[0]["methods"][0]["name"] == "tested"


def test_cross_user_world_cannot_read_run_export_or_reuse(env):
    api, methods, _ = env
    draft = create(api)
    url = api.PREFIX + "/" + draft["id"]
    saved = api.handle_post(url + "/save-method", {})[0]
    for variable, value in ((USER, {"id": "bob", "role": "member"}), (WORLD, {"id": "b"})):
        token = variable.set(value)
        try:
            assert api.handle_get(api.PREFIX)[0]["studies"] == []
            for suffix in ("", "/export", "/results"):
                assert api.handle_get(url + suffix)[1] == 404
            assert api.handle_post(url + "/run", {})[1] == 404
            assert api.handle_post(url + "/recover", {})[1] == 404
            with pytest.raises(LookupError):
                methods.resolve(saved["id"], 1)
        finally:
            variable.reset(token)


def test_model_and_protocol_drift_blocks_start(env):
    api, _, model = env
    draft = create(api)
    url = api.PREFIX + "/" + draft["id"] + "/run"
    model["fingerprint"] = "changed"
    assert api.handle_post(url, {})[1] == 400
    model["fingerprint"] = "frozen"
    api.database().update(draft["id"], lambda r: r["protocol"].update(seed=0))
    assert api.handle_post(url, {})[1] == 400


def test_routes_openapi_and_quota():
    from gaworld.accounts import policy
    from gaworld.apps import openapi, routes

    path = "/api/research/organization-intelligence/comparisons/C" + "a" * 24 + "/run"
    assert routes.find(routes.POST_ROUTES, path).module == "organization_comparison_api"
    assert openapi.allowed_methods(path) == {"POST"}
    assert policy.quota_gated(path)
    assert policy.quota_gated("/api/research/organization-intelligence/comparisons/analyze")
    assert policy.required("POST", "/api/collaboration/organization-methods") == "member"
    recovery_path = path.rsplit("/", 1)[0] + "/recover"
    assert openapi.allowed_methods(recovery_path) == {"POST"}
    assert not policy.quota_gated(recovery_path)


def test_runtime_drift_and_method_version_edits_are_explicit(env, monkeypatch):
    api, methods, _ = env
    record = create(api)
    first = api.handle_post(api.PREFIX + "/" + record["id"] + "/save-method", {})[0]
    edited = copy.deepcopy(first["method"])
    edited["name"] = "new version"
    newer, status = methods.handle_post(methods.PREFIX + "/" + first["id"], {"method": edited})
    assert status == 201 and newer["version"] == 2
    assert methods.resolve(first["id"], 1)["method"]["name"] != "new version"
    monkeypatch.setattr(api.protocol, "runtime_fingerprint", lambda: "different-code")
    assert api.handle_post(api.PREFIX + "/" + record["id"] + "/run", {})[1] == 400


def test_context_selects_configured_default_model(env, monkeypatch):
    api, _, _ = env
    monkeypatch.setattr(api.research_api, "_base_config", lambda: {"llm": {"routing": {"default": "test"}}})
    monkeypatch.setattr(api.research_api, "_providers", lambda: [{"name": "test", "model": "fixture"}])
    value, status = api.handle_get(api.PREFIX + "/context")
    assert status == 200 and value["default_provider"] == "test"


def test_cooldown_blocks_model_calls_and_recovery_only_saves_settings(env, monkeypatch):
    from tests.test_organization_comparison_transport import http_error

    api, _, _ = env
    draft = create(api)
    url = api.PREFIX + "/" + draft["id"]
    calls = []

    def failed(prompt):
        calls.append(prompt)
        raise http_error()

    monkeypatch.setattr(api.legacy, "make_caller", lambda spec: failed)
    assert api.handle_post(url + "/run", {})[1] == 202
    record = api.handle_get(url)[0]
    assert record["status"] == "rate_limited"
    assert record["error_info"]["http_status"] == 429
    assert api.handle_post(url + "/resume", {})[1] == 429
    assert len(calls) == 1
    recovered, status = api.handle_post(url + "/recover", {})
    assert status == 201 and recovered["status"] == "draft"
    assert recovered["recovery"]["source_id"] == draft["id"]
    assert len(calls) == 1
    count = len(api.database().list("C"))
    assert api.handle_get(url + "/recover")[1] == 404
    assert len(api.database().list("C")) == count


def test_custom_baseline_is_frozen_validated_and_restored(env):
    api, _, _ = env
    control = baseline("hierarchy", 3)
    control.update(name="自定义对照", rounds=1, review=True, revisions=0)
    control["source"] = {"text": "一位协调人汇总，其他成员互不通信。", "title": "自定义"}
    payload = {
        "candidate": baseline("full", 3),
        "agent_ids": [1, 2, 3],
        "provider": "test",
        "baseline": "custom",
        "baseline_method": control,
        "count": 1,
        "repeats": 1,
    }
    record, code = api.handle_post(api.PREFIX, payload)
    assert code == 201, record
    assert record["protocol"]["baseline_kind"] == "custom"
    assert record["protocol"]["baseline"] == control
    control["roles"].pop()
    assert api.handle_post(api.PREFIX, payload)[1] == 400
    payload.pop("baseline_method")
    assert api.handle_post(api.PREFIX, payload)[1] == 400


def test_baseline_description_requests_exact_matched_role_count(env, monkeypatch):
    import json

    api, _, _ = env
    prompts = []

    def call(prompt):
        prompts.append(json.loads(prompt))
        value = baseline("full", 2)
        value["rules"] = [{"text": "交换信息", "quote": "", "origin": "inferred"}]
        return json.dumps(value)

    monkeypatch.setattr(api.legacy, "make_caller", lambda spec: call)
    value, code = api.handle_post(api.PREFIX + "/analyze", {"text": "两个人独立分析之后交换信息", "slots": 2})
    assert code == 200, value
    assert len(prompts[0]["example"]["roles"]) == 2
    assert len(value["roles"]) == 2


def test_pause_after_inflight_answer_then_resume_reuses_answer(env, monkeypatch):
    api, _, _ = env
    draft = create(api)
    url = api.PREFIX + "/" + draft["id"]
    submitted = []

    def call(prompt):
        submitted.append(prompt)
        if len(submitted) == 1:
            paused, code = api.handle_post(url + "/pause", {})
            assert code == 200 and paused["control"] == "pause"
        return '{"answer":"A"}'

    monkeypatch.setattr(api.legacy, "make_caller", lambda spec: call)
    assert api.handle_post(url + "/run", {})[1] == 202
    paused = api.database().get(draft["id"])
    assert paused["status"] == "paused"
    assert len(submitted) == 1
    cell = next(iter(paused["states"]))
    assert len(api.database().load_state(draft["id"], cell)["calls"]) == 1
    assert api.handle_post(url + "/resume", {})[1] == 202
    complete = api.database().get(draft["id"])
    assert complete["status"] == "completed"
    evidence = api.database().load_state(draft["id"], cell)
    assert evidence["calls"][0]["prompt"] == submitted[0]
    assert sum(a["prompt"] == submitted[0] for a in evidence["attempts"]) == 1


def test_recovery_draft_after_further_code_update_rechecks_original(env, monkeypatch):
    api, _, _ = env
    draft = create(api)
    api.database().update(draft["id"], lambda r: r.update(status="interrupted"))
    url = api.PREFIX + "/" + draft["id"]
    first, code = api.handle_post(url + "/recover", {})
    assert code == 201
    old_hash = api.protocol.runtime_fingerprint()
    monkeypatch.setattr(api.protocol, "runtime_fingerprint", lambda: "updated-transport-code")
    # The original is a known verified source; the unused recovery is only a copy.
    monkeypatch.setattr(api.recovery, "COMPATIBLE_SOURCE", old_hash)
    first_url = api.PREFIX + "/" + first["id"]
    assert api.handle_get(first_url)[0]["resume_requires_recovery"]
    next_copy, code = api.handle_post(first_url + "/recover", {})
    assert code == 201, next_copy
    assert next_copy["recovery"]["source_id"] == draft["id"]
    assert api.database().get(first["id"])["protocol_hash"] == first["protocol_hash"]


@pytest.mark.parametrize("legacy_completed", [False, True])
def test_invalid_judge_response_can_be_retried_within_frozen_limit(env, monkeypatch, legacy_completed):
    import json

    api, _, _ = env
    bank = {
        "name": "open",
        "scorer": "rubric",
        "tasks": [
            {"id": "open", "category": "reasoning", "prompt": "Explain", "rubric": "Score accuracy 0-1"}
        ],
    }
    record, code = api.handle_post(
        api.PREFIX,
        {
            "candidate": baseline("independent", 2),
            "agent_ids": [1, 2],
            "provider": "test",
            "baseline": "independent",
            "benchmark": bank,
            "repeats": 1,
        },
    )
    assert code == 201, record
    judges = []

    def call(prompt):
        if "rubric" in json.loads(prompt):
            judges.append(prompt)
            return "no json" if len(judges) == 1 else '{"score":0.5}'
        return '{"answer":"A"}'

    monkeypatch.setattr(api.legacy, "make_caller", lambda spec: call)
    url = api.PREFIX + "/" + record["id"]
    assert api.handle_post(url + "/run", {})[1] == 202
    assert api.database().get(record["id"])["status"] == "interrupted"
    if legacy_completed:
        interrupted = api.database().get(record["id"])
        cell = next(iter(interrupted["states"]))
        saved = api.database().load_state(record["id"], cell)
        saved["scoring_attempts"][0]["status"] = "completed"
        api.database().save_state(record["id"], cell, saved)
    assert api.handle_post(url + "/resume", {})[1] == 202
    result = api.database().get(record["id"])
    assert result["status"] == "completed"
    assert len(judges) == 3  # First invalid + replacement + other arm.
    assert len(result["rows"]) == 2


def test_invalid_judge_does_not_exceed_frozen_scoring_requests(env, monkeypatch):
    import json

    api, _, _ = env
    bank = {
        "name": "open",
        "scorer": "rubric",
        "tasks": [{"id": "open", "category": "reasoning", "prompt": "Explain", "rubric": "0-1"}],
    }
    record, _ = api.handle_post(
        api.PREFIX,
        {
            "candidate": baseline("independent", 2),
            "agent_ids": [1, 2],
            "provider": "test",
            "baseline": "independent",
            "benchmark": bank,
            "repeats": 1,
        },
    )
    judges = []

    def call(prompt):
        if "rubric" in json.loads(prompt):
            judges.append(prompt)
            return "invalid score"
        return '{"answer":"A"}'

    monkeypatch.setattr(api.legacy, "make_caller", lambda spec: call)
    url = api.PREFIX + "/" + record["id"]
    api.handle_post(url + "/run", {})
    api.handle_post(url + "/resume", {})
    assert len(judges) == 2
    assert api.handle_get(url)[0]["retry_blocked_reason"]
    assert api.handle_post(url + "/resume", {})[1] == 400
    assert len(judges) == 2
