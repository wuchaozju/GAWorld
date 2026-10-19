import copy
import csv

import pytest

from gaworld.accounts.context import USER, WORLD
from gaworld.apps import research_api
from gaworld.apps import research_batches_api as api
from gaworld.research import batches, study, workbench
from tests.test_research_batches import protocol_data


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(research_api, "_repo_root", lambda: str(tmp_path))
    monkeypatch.setattr(api, "_ACTIVE", {})
    (tmp_path / "agents.csv").write_text("agent_id,name\n1,A\n2,B\n3,C\n", encoding="utf-8")
    config = {
        "csv_path": str(tmp_path / "agents.csv"),
        "agent_ids": [1],
        "background": "First city",
        "llm": {
            "providers": {
                "a": {"type": "openai", "model": "test-a", "api_key": "SECRET_A"},
                "b": {"type": "openai", "model": "test-b", "api_key": "SECRET_B"},
            }
        },
    }
    monkeypatch.setattr(research_api, "_base_config", lambda: copy.deepcopy(config))
    monkeypatch.setattr(
        research_api,
        "_preflight",
        lambda p, **kw: {"ok": True, "errors": [], "warnings": [], "budget": {"estimated_calls": 10}},
    )
    who = USER.set({"id": "alice", "role": "member"})
    where = WORLD.set({"id": "alice-world"})
    source = study.new_study({"id": "source-plan"}, protocol_data(), {})
    source.owner_id, source.world_id = "alice", "alice-world"
    study.save_study(source)
    yield tmp_path, source, config
    WORLD.reset(where)
    USER.reset(who)


def create(source, **extra):
    body, status = api.handle_post(
        "/api/research/batches",
        {"study_id": source.id, "providers": ["a", "b"], "cities": [""], "repeats": 2, **extra},
    )
    assert status == 201, body
    return body


def test_create_freezes_city_sample_and_models_without_launch(env, monkeypatch):
    root, source, config = env
    monkeypatch.setattr(research_api, "_launch_run", lambda *a, **k: pytest.fail("create must not launch"))
    batch = create(source)
    assert len(batch["cells"]) == 4
    assert batch["preflight"]["estimated_calls"] == 40
    frozen = batch["inputs"][""]
    assert frozen["agent_ids"] == [1]
    assert frozen["assets"]["csv_path"]["path"].endswith(".csv")
    (root / "agents.csv").write_text("changed", encoding="utf-8")
    cfg = api.cell_config(batch, batch["cells"][0])
    with open(cfg["csv_path"], encoding="utf-8-sig") as handle:
        assert len(list(csv.DictReader(handle))) == 3
    assert "SECRET_A" not in str(batch)
    assert config["agent_ids"] == [1]
    assert batches.load(batch["id"])["protocol_hash"] == batch["protocol_hash"]


def test_other_user_or_world_cannot_read_control_or_export(env):
    _, source, _ = env
    batch = create(source)
    for field, value in ((USER, {"id": "bob", "role": "member"}), (WORLD, {"id": "other"})):
        token = field.set(value)
        try:
            assert api.handle_get(f"/api/research/batches/{batch['id']}")[1] == 404
            assert api.handle_get(f"/api/research/batches/{batch['id']}/export")[1] == 404
            assert api.handle_post(f"/api/research/batches/{batch['id']}/run", {})[1] == 404
            assert api.handle_get("/api/research/batches")[0]["batches"] == []
        finally:
            field.reset(token)


def test_unknown_city_or_model_is_rejected_without_fallback(env):
    _, source, _ = env
    for change in ({"cities": ["not-a-city"]}, {"providers": ["unconfigured"]}):
        body, status = api.handle_post(
            "/api/research/batches",
            {"study_id": source.id, "providers": ["a"], "cities": [""], "repeats": 2, **change},
        )
        assert status == 400, body


def test_new_routes_are_documented_and_member_quota_applies():
    from gaworld.accounts import policy
    from gaworld.apps import openapi, routes

    assert routes.find(routes.POST_ROUTES, "/api/research/batches").module == "research_batches_api"
    for suffix in ("run", "resume"):
        path = "/api/research/batches/B" + "a" * 24 + "/" + suffix
        assert policy.required("POST", path) == "member"
        assert policy.quota_gated(path)
        assert openapi.allowed_methods(path) == {"POST"}


def test_multiple_cities_freeze_different_populations_without_switching_world(env):
    root, source, config = env
    for name, label in (("north", "North"), ("south", "South")):
        city = root / "data" / "cities" / name
        city.mkdir(parents=True)
        (city / "city.json").write_text('{"slug":"' + name + '","name":"' + label + '"}')
        (city / "agents.csv").write_text("agent_id,name\n1," + label + "\n")
        (city / "profiles.md").write_text(label + " resident")
        (city / "citymap.md").write_text(label + " map")
    batch = create(source, cities=["north", "south"], sample_size=1)
    assert len(batch["cells"]) == 8
    assert batch["inputs"]["north"]["sample_hash"] != batch["inputs"]["south"]["sample_hash"]
    from pathlib import Path

    for cell in batch["cells"]:
        frozen = api.cell_config(batch, cell)
        assert cell["city"].title() in Path(frozen["csv_path"]).read_text()
        assert frozen["agent_ids"] == [1]
    assert config["background"] == "First city"
    assert WORLD.get()["id"] == "alice-world"


def test_city_environment_events_are_frozen_and_credentials_are_removed(env):
    _, source, config = env
    config["environment"] = {"events": [{"day": 2, "description": "Rain"}], "api_key": "ENV_SECRET"}
    config["personality"] = {"enabled": True, "profile_path": "/absent"}
    batch = create(source)
    params = batch["inputs"][""]["parameters"]
    assert params["environment"]["events"][0]["description"] == "Rain"
    assert "ENV_SECRET" not in str(batch)


def test_frozen_modeling_sections_replace_later_live_settings(env):
    _, source, config = env
    config.update(
        public_sector={"enabled": True, "tax": 0.1},
        calendar={"start": "2026-01-01"},
        long_run={"randomness": 0.2},
        time_step_minutes=60,
    )
    config["economy"] = {"enabled": True}
    batch = create(source)
    config["public_sector"]["tax"] = 0.9
    config["economy"]["new_runtime_option"] = True
    restored = api.cell_config(batch, batch["cells"][0])
    assert restored["public_sector"]["tax"] == 0.1
    assert "new_runtime_option" not in restored["economy"]
    assert restored["long_run"]["randomness"] == 0.2


def test_changed_nonportable_settings_are_blocked_not_silently_inherited(env):
    _, source, config = env
    config["plugins"] = ["gaworld.plugins.One"]
    batch = create(source)
    config["plugins"] = ["gaworld.plugins.Two"]
    with pytest.raises(ValueError):
        api.cell_config(batch, batch["cells"][0])


def test_portable_batch_rejects_credential_bearing_condition_even_for_admin(env):
    _, source, _ = env
    source.protocol["conditions"][1]["config"] = {"news": {"api_key": "PRIVATE_CREDENTIAL"}}
    study.save_study(source)
    token = USER.set({"id": "alice", "role": "admin"})
    try:
        body, status = api.handle_post(
            "/api/research/batches", {"study_id": source.id, "providers": ["a"], "cities": [""], "repeats": 2}
        )
        assert status == 400
        assert "PRIVATE_CREDENTIAL" not in str(body)
    finally:
        USER.reset(token)


def test_batch_checks_all_local_providers_before_launch(env, monkeypatch):
    _, source, _ = env
    from gaworld.research import provider_check

    seen = []

    def inspect(config, selected, **kwargs):
        seen.append(selected)
        return {"primary": selected, "status": "model_missing" if selected == "b" else "ready"}

    monkeypatch.setattr(provider_check, "inspect_provider", inspect)
    batch = create(source)
    assert not batch["preflight"]["ok"]
    assert seen == ["a", "b"]
    monkeypatch.setattr(research_api, "_launch_run", lambda *a, **kw: pytest.fail("preflight must block"))
    assert api.handle_post(f"/api/research/batches/{batch['id']}/run", {})[1] == 400


def test_local_only_input_paths_are_preserved_and_bound(env):
    _, source, config = env
    config["skills"] = {"global_dir": "/custom/library", "search_dirs": ["/custom/other"]}
    config["external_environment_service"] = {"url": "http://local-first"}
    batch = create(source)
    frozen = api.cell_config(batch, batch["cells"][0])
    assert frozen["skills"]["global_dir"] == "/custom/library"
    config["external_environment_service"]["url"] = "http://local-second"
    with pytest.raises(ValueError):
        api.cell_config(batch, batch["cells"][0])


def test_admin_can_batch_safe_public_sector_interventions(env):
    _, source, _ = env
    source.protocol["conditions"][1]["config"] = {"public_sector": {"enabled": True}}
    study.save_study(source)
    token = USER.set({"id": "alice", "role": "admin"})
    try:
        assert create(source)["protocol"]["conditions"][1]["config"]["public_sector"]["enabled"]
    finally:
        USER.reset(token)


def test_generation_options_outside_public_excerpt_cannot_drift(env):
    _, source, config = env
    config["llm"]["providers"]["a"]["extra_body"] = {"reasoning_effort": "low"}
    batch = create(source)
    config["llm"]["providers"]["a"]["extra_body"]["reasoning_effort"] = "high"
    with pytest.raises(ValueError):
        api.cell_config(batch, batch["cells"][0])
