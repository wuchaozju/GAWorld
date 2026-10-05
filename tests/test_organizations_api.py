"""Organization management queues commands; only the simulator applies them."""

from __future__ import annotations

import importlib
import json

import pytest

from gaworld.accounts import context, policy
from gaworld.apps import openapi, routes, world_paths

CREATE = {
    "type": "create",
    "organization_id": "mutual-aid",
    "name": "互助会",
    "kind": "community",
    "leader_id": 1,
    "initial_balance_cents": 10000,
}


def test_organization_management_module_exists():
    assert importlib.util.find_spec("gaworld.apps.organizations_api") is not None


@pytest.fixture
def api(tmp_path, monkeypatch):
    module = importlib.import_module("gaworld.apps.organizations_api")
    monkeypatch.setattr(world_paths, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(world_paths, "DASHBOARD_CONFIG_PATH", str(tmp_path / "dashboard_config.json"))
    (tmp_path / "dashboard_config.json").write_text("{}", encoding="utf-8")
    user_token = context.USER.set(None)
    world_token = context.WORLD.set(None)
    yield module
    context.WORLD.reset(world_token)
    context.USER.reset(user_token)


def test_routes_and_openapi_cover_all_management_operations():
    for path in (
        "/api/organizations",
        "/api/organizations/commands",
        "/api/organizations/commands/c1",
        "/api/organizations/mutual-aid",
        "/api/organizations/mutual-aid/history",
    ):
        assert routes.find(routes.GET_ROUTES, path).module == "organizations_api"
        assert openapi.allowed_methods(path) == ({"GET", "POST"} if path.endswith("/commands") else {"GET"})
    operation = openapi.spec()["paths"]["/api/organizations/commands"]["post"]
    assert "202" in operation["responses"]
    assert operation["x-gaworld-access"] == "world"
    schema = operation["requestBody"]["content"]["application/json"]["schema"]["oneOf"][0]
    assert "kind" in schema["required"]
    assert "kind" in schema["properties"]


def test_list_exposes_execution_boundary_and_real_empty_state(api):
    body, status = api.handle_get("/api/organizations", {})
    assert status == 200
    assert body["organizations"] == []
    assert body["enabled"] is False
    assert body["can_write"] is True
    assert body["execution"] == "next_day_boundary"
    assert body["governance_enabled"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "set_governance", "governance": {"mode": "leader"}},
        {"type": "propose_rule", "agent_id": 1, "rule": "need_first", "reason": "优先困难成员"},
        {"type": "cast_vote", "agent_id": 1, "proposal_id": "p1", "choice": "abstain"},
        {"type": "leader_decide", "agent_id": 1, "proposal_id": "p1", "choice": "yes"},
    ],
)
def test_governance_commands_are_queued_and_documented(api, payload):
    row, code = api.handle_post("/api/organizations/commands", {"organization_id": "care", **payload})
    assert code == 202 and row["status"] == "pending"
    variants = openapi.spec()["paths"]["/api/organizations/commands"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]["oneOf"]
    schema = next(v for v in variants if v["properties"]["type"]["const"] == payload["type"])
    assert set(payload) <= schema["properties"].keys()
    assert "target_generation_id" in row


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "set_governance", "governance": {"mode": []}},
        {"type": "set_governance", "governance": {"threshold": {}}},
        {"type": "cast_vote", "agent_id": 1, "proposal_id": "p1", "choice": []},
        {"type": "propose_rule", "agent_id": 1, "rule": []},
    ],
)
def test_malformed_governance_enums_return_400(api, payload):
    assert api.handle_post("/api/organizations/commands", {"organization_id": "care", **payload})[1] == 400


def test_reads_can_select_prior_generation_without_changing_current_state(api):
    store = api._store()
    store.set_meta("generation_id", "prior")
    store.set_meta("last_processed_day", 7)
    store.set_meta("recovery_required", False)
    store.add_history("care", "note", {"marker": "old"})
    store.put("organizations", "care", {"organization_id": "care", "name": "旧世代"})
    current = store.new_generation()
    store.set_meta("last_processed_day", 2)
    store.set_meta("recovery_required", True)
    store.add_history("care", "note", {"marker": "new"})
    store.put("organizations", "care", {"organization_id": "care", "name": "新世代"})
    store.close()
    body, status = api.handle_get("/api/organizations", {"generation_id": ["prior"]})
    assert status == 200
    assert body["organizations"][0]["name"] == "旧世代"
    assert body["meta"]["generation_id"] == "prior"
    assert body["meta"]["last_processed_day"] == 7
    assert body["meta"]["recovery_required"] is False
    assert body["can_write"] is False and body["execution"] == "historical_read_only"
    assert api.handle_get("/api/organizations/care", {"generation_id": ["prior"]})[0]["name"] == "旧世代"
    old_history = api.handle_get("/api/organizations/care/history", {"generation_id": ["prior"]})[0][
        "history"
    ]
    assert [row["marker"] for row in old_history] == ["old"]
    assert api.handle_get("/api/organizations", {})[0]["meta"]["generation_id"] == current
    assert api.handle_get("/api/organizations", {"generation_id": ["../other"]})[1] == 400


def test_post_returns_pending_command_without_creating_organization(api):
    queued, status = api.handle_post("/api/organizations/commands", CREATE)
    assert status == 202
    assert queued["status"] == "pending"
    assert queued["result"] is None
    assert api.handle_get("/api/organizations", {})[0]["organizations"] == []
    polled, status = api.handle_get(f"/api/organizations/commands/{queued['command_id']}", {})
    assert status == 200
    assert polled["status"] == "pending"


def test_profile_management_command_is_queued_and_documented(api):
    payload = {"type": "update_profile", "organization_id": "care", "goal": "照顾困难成员"}
    command, status = api.handle_post("/api/organizations/commands", payload)
    assert status == 202 and command["status"] == "pending"
    variants = openapi.spec()["paths"]["/api/organizations/commands"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]["oneOf"]
    variant = next((row for row in variants if row["properties"]["type"]["const"] == "update_profile"), None)
    assert variant is not None
    assert variant["anyOf"] == [{"required": ["name"]}, {"required": ["goal"]}]


def test_command_list_and_actor_are_persistent(api):
    context.USER.set({"id": 7, "nickname": "研究者", "role": "member"})
    context.WORLD.set({"id": "w0123abcd", "owner_id": 7})
    queued, status = api.handle_post("/api/organizations/commands", CREATE)
    assert status == 202
    body, _ = api.handle_get("/api/organizations/commands", {})
    assert body["commands"][0]["command_id"] == queued["command_id"]
    assert body["commands"][0]["actor"] == {"owner_id": 7, "owner": "研究者"}


def test_same_command_id_is_isolated_between_worlds(api):
    context.WORLD.set({"id": "w0123abcd", "owner_id": 7})
    payload = {**CREATE, "command_id": "request-a"}
    assert api.handle_post("/api/organizations/commands", payload)[1] == 202
    context.WORLD.set({"id": "w0123abce", "owner_id": 7})
    assert api.handle_get("/api/organizations/commands", {})[0]["commands"] == []
    assert api.handle_get("/api/organizations/commands/request-a", {})[1] == 404
    assert api.handle_post("/api/organizations/commands", payload)[1] == 202
    context.WORLD.set(None)
    assert api.handle_get("/api/organizations/commands", {})[0]["commands"] == []


@pytest.mark.parametrize("world", [None, {"id": "w0123abcd", "owner_id": 8}])
def test_other_member_and_shared_default_writes_are_denied(api, world):
    context.USER.set({"id": 7, "role": "member"})
    context.WORLD.set(world)
    assert policy.required("POST", "/api/organizations/commands") == "world"
    assert api.handle_post("/api/organizations/commands", CREATE)[1] == 403
    assert api.handle_get("/api/organizations", {})[0]["can_write"] is False


def test_admin_may_queue_in_shared_default(api):
    context.USER.set({"id": 1, "role": "admin"})
    assert api.handle_post("/api/organizations/commands", CREATE)[1] == 202


@pytest.mark.parametrize("extra", ["world", "world_id", "memory_dir", "path", "output_dir"])
def test_client_cannot_redirect_organization_storage(api, extra):
    assert api.handle_post("/api/organizations/commands", {**CREATE, extra: "other"})[1] == 400
    assert api.handle_get("/api/organizations", {extra: ["other"]})[1] == 400


@pytest.mark.parametrize(
    "patch",
    [
        {"initial_balance_cents": -1},
        {"initial_balance_cents": 1.5},
        {"kind": "government"},
        {"leader_id": True},
        {"type": "execute"},
    ],
)
def test_invalid_command_rejected_before_enqueue(api, patch):
    body, status = api.handle_post("/api/organizations/commands", {**CREATE, **patch})
    assert status == 400
    assert "error" in body
    assert api.handle_get("/api/organizations/commands", {})[0]["commands"] == []


def test_unknown_records_and_bad_history_limit_have_explicit_errors(api):
    assert api.handle_get("/api/organizations/missing", {})[1] == 404
    assert api.handle_get("/api/organizations/missing/history", {})[1] == 404
    assert api.handle_get("/api/organizations/commands/missing", {})[1] == 404
    for limit in ("no", "-1", "1001"):
        assert api.handle_get("/api/organizations/missing/history", {"limit": [limit]})[1] == 400


def test_cli_queues_json_file_and_reports_the_same_pending_command(api, tmp_path, capsys):
    cli = importlib.import_module("gaworld.organizations.__main__")
    payload_file = tmp_path / "command.json"
    payload_file.write_text(json.dumps(CREATE), encoding="utf-8")
    assert cli.main(["command", "--json-file", str(payload_file)]) == 0
    queued = json.loads(capsys.readouterr().out)
    assert queued["status"] == "pending"
    assert cli.main(["status", queued["command_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["command_id"] == queued["command_id"]
    assert cli.main(["list"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_cli_world_selects_existing_world_and_rejects_nonexistent_world(api, tmp_path, capsys):
    cli = importlib.import_module("gaworld.organizations.__main__")
    world_root = tmp_path / "output/worlds/w0123abcd"
    world_root.mkdir(parents=True)
    (world_root / "config.json").write_text("{}", encoding="utf-8")
    assert cli.main(["--world", "w0123abcd", "command", "--json", json.dumps(CREATE)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pending"
    assert api.handle_get("/api/organizations/commands", {})[0]["commands"] == []
    assert cli.main(["--world", "w0123abce", "list"]) == 2
    assert "error" in json.loads(capsys.readouterr().err)


def test_cli_invalid_json_never_queues_a_command(api, capsys):
    cli = importlib.import_module("gaworld.organizations.__main__")
    assert cli.main(["command", "--json", "[]"]) == 2
    assert "error" in json.loads(capsys.readouterr().err)
    assert api.handle_get("/api/organizations/commands", {})[0]["commands"] == []
