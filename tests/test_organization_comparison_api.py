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
