import pytest

from gaworld.accounts.context import USER, WORLD
from gaworld.research.organization_intelligence.v2 import build, queue


@pytest.fixture
def env(tmp_path, monkeypatch):
    from gaworld.apps import organization_intelligence_v2_api as api

    monkeypatch.setattr(api, "root", lambda: tmp_path)
    user = USER.set({"id": "alice", "role": "member"})
    world = WORLD.set({"id": "world-a"})
    yield api
    USER.reset(user)
    WORLD.reset(world)


def create(api):
    data, status = api.handle_post(api.PREFIX, {"seeds": 1, "expected_build": build.identity()["build_id"]})
    assert status == 201, data
    return data


def test_freeze_is_zero_call_draft_and_version_handshake_required(env):
    api = env
    assert api.handle_post(api.PREFIX, {"seeds": 1})[1] == 409
    record = create(api)
    assert record["status"] == "draft" and record["committed"] == 0
    assert record["external_calls"] == 0 and record["total"] == 200
    assert (api.directory(record["id"]) / "bundle" / "manifest.json").exists()
    context, status = api.handle_get(api.PREFIX)
    assert status == 200 and context["engine"]["pid"] > 0
    assert context["engine"]["version"] == "OI-2.0"


def test_owner_world_controls_all_artifacts_and_actions(env):
    record = create(env)
    path = env.PREFIX + "/" + record["id"]
    for variable, value in ((USER, {"id": "bob", "role": "member"}), (WORLD, {"id": "other"})):
        token = variable.set(value)
        try:
            assert env.handle_get(env.PREFIX)[0]["studies"] == []
            for suffix in ("", "/export", "/protocol", "/results"):
                assert env.handle_get(path + suffix)[1] == 404
            for suffix in ("/run", "/pause"):
                assert env.handle_post(path + suffix, {})[1] == 404
        finally:
            variable.reset(token)


def test_run_completes_frozen_worker_and_report(env, monkeypatch):
    record = create(env)
    path = env.PREFIX + "/" + record["id"]
    # Exercise production worker synchronously, no network or model mocks needed.
    monkeypatch.setattr(env, "spawn", lambda target, *args, **kwargs: target(*args))
    assert env.handle_post(path + "/run", {"expected_build": "old"})[1] == 409
    assert env.handle_post(path + "/run", {"expected_build": record["build_id"]})[1] == 202
    result, _ = env.handle_get(path)
    assert result["status"] == "completed" and result["committed"] == 200
    assert result["worker_build"] == record["build_id"]
    results, _ = env.handle_get(path + "/results")
    assert results["analysis"]["complete"] and len(results["rows"]) == 200
    exported, _ = env.handle_get(path + "/export")
    assert "外部模型请求 0" in exported["markdown"]


def test_protocol_corruption_blocks_worker_without_advancing(env, monkeypatch):
    record = create(env)
    directory = env.directory(record["id"])
    (directory / "protocol.json").write_text("{}")
    monkeypatch.setattr(env, "spawn", lambda target, *args, **kwargs: target(*args))
    env.handle_post(env.PREFIX + "/" + record["id"] + "/run", {"expected_build": record["build_id"]})
    result, _ = env.handle_get(env.PREFIX + "/" + record["id"])
    assert result["status"] == "blocked" and result["committed"] == 0


def test_v2_routes_documented_and_not_provider_quota_gated():
    from gaworld.accounts import policy
    from gaworld.apps import openapi, routes

    prefix = "/api/research/organization-intelligence/v2"
    path = prefix + "/OI2" + "a" * 24 + "/run"
    assert routes.find(routes.POST_ROUTES, path).module == "organization_intelligence_v2_api"
    assert policy.required("POST", path) == "member"
    assert not policy.quota_gated(path)
    assert openapi.allowed_methods(path) == {"POST"}
    assert openapi.allowed_methods(prefix) == {"GET", "POST"}


def test_startup_pause_and_immediate_resume_intent_persist(env, monkeypatch):
    record = create(env)
    path = env.PREFIX + "/" + record["id"]
    pending = []
    monkeypatch.setattr(env, "spawn", lambda target, *args, **kwargs: pending.append((target, args)))
    env.handle_post(path + "/run", {"expected_build": record["build_id"]})
    env.handle_post(path + "/pause", {})
    target, args = pending.pop()
    target(*args)
    snap = env.load(record["id"])
    assert snap["status"] == "paused" and snap["committed"] == 0
    env.handle_post(path + "/run", {"expected_build": record["build_id"]})
    env.handle_post(path + "/pause", {})
    env.handle_post(path + "/run", {"expected_build": record["build_id"]})
    assert env.load(record["id"])["status"] == "running"
    target, args = pending.pop()
    target(*args)
    assert env.load(record["id"])["committed"] == 200


def test_completed_missing_exports_are_automatically_finalized(env, monkeypatch):
    record = create(env)
    folder = env.directory(record["id"])
    queue.run(folder / "tasks.sqlite")
    monkeypatch.setattr(env, "spawn", lambda target, *args, **kwargs: target(*args))
    env.handle_get(env.PREFIX + "/" + record["id"])
    result, _ = env.handle_get(env.PREFIX + "/" + record["id"] + "/results")
    assert result["analysis"]["complete"]
