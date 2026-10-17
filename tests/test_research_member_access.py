"""A member's complete study workflow and its cross-account boundaries."""

import copy
import json
import time
from pathlib import Path
from unittest import mock

import pytest

from gaworld.accounts import policy
from gaworld.accounts.context import USER, WORLD
from gaworld.apps import research_api, world_paths
from gaworld.parallel import runner
from gaworld.parallel.spec import normalize_experiment
from gaworld.research import study, workbench
from tests import test_accounts as account_support
from tests import test_research_study as support


@pytest.fixture
def classroom(monkeypatch, request):
    host = account_support.HttpTest()
    host.setUp()
    request.addfinalizer(host.tearDown)
    root = Path(host.tmp.name)
    monkeypatch.setattr(workbench, "PROJECT_ROOT", root)
    monkeypatch.setattr(world_paths, "REPO_ROOT", str(root))
    monkeypatch.setattr(research_api, "_base_config", lambda: {
        "agent_ids": [1, 2, 3],
        "llm": {"providers": {"test": {"type": "openai", "model": "fixture", "api_key": "fixture-key"}},
                "routing": {"default": "test"}},
    })
    monkeypatch.setattr(research_api, "_JOBS", {})
    monkeypatch.setattr(research_api, "_ACTIVE_STUDIES", {})
    store = account_support._store(host.tmp.name)
    users = {name: store.create_user(name, account_support.PASSWORD, role=role)
             for name, role in [("owner", "member"), ("other", "member"), ("teacher", "admin")]}
    cookies = {name: host._login(name) for name in users}
    plan = workbench.ResearchPlan.from_dict(dict(support.PLAN, provider="test", created_at="2026-10-15"))
    workbench.save_plan(plan, {"owner_id": users["owner"]["id"], "owner": "owner"})
    seen = []

    def llm(provider, max_tokens):
        from gaworld.research.protocol import PROTOCOL_MAX_TOKENS

        def call(prompt):
            seen.append(("model", USER.get()["id"]))
            return json.dumps(support.ANSWER if max_tokens == PROTOCOL_MAX_TOKENS else support.INTERPRETATION)
        return call

    def seed_runner(current):
        def run(spec, seed, report):
            seen.append(("run", USER.get()["id"]))
            manifest = runner.prepare_experiment(spec, str(root), experiment_id=f"study_{current.id}_s{seed}")
            return {"root": manifest["root"], "id": manifest["id"], "status": "done",
                    "report": support.fake_report(support.series(0.5, 0.3, 0.5))}
        return run

    monkeypatch.setattr(research_api, "_llm", llm)
    monkeypatch.setattr(research_api, "_seed_runner", seed_runner)
    host.store, host.users, host.cookies, host.seen = store, users, cookies, seen
    yield host


def req(host, who, method, path, data=None):
    response, payload = host._req(method, path, data, cookie=host.cookies[who])
    return response.status, payload


def job(host, job_id):
    for _ in range(100):
        status, result = req(host, "owner", "GET", "/api/research/jobs/" + job_id)
        assert status == 200
        if result["status"] != "running":
            assert result["status"] == "done", result
            return result["result"]
        time.sleep(0.02)
    pytest.fail("Study worker did not finish")


def create(host, autopilot=False):
    status, result = req(host, "owner", "POST", "/api/research/studies", {
        "plan_id": support.PLAN["id"], "autopilot": autopilot,
        "owner_id": host.users["other"]["id"],  # client cannot choose the owner
    })
    assert status == 202, result
    return job(host, result["job_id"])


@pytest.mark.parametrize("autopilot", [False, True])
def test_member_compiles_runs_and_exports_own_study(classroom, autopilot):
    result = create(classroom, autopilot)
    sid = result["study_id"]
    path = "/api/research/studies/" + sid
    if not autopilot:
        status, result = req(classroom, "owner", "POST", path + "/approve", {"run": True})
        assert status == 202, result
    completed = job(classroom, result["run_job_id"])
    assert completed["stage"] == "reported"
    status, detail = req(classroom, "owner", "GET", path)
    assert status == 200
    assert detail["owner_id"] == classroom.users["owner"]["id"]
    assert detail["runs"]
    assert req(classroom, "owner", "GET", path + "/report")[1]["markdown"]
    assert req(classroom, "teacher", "GET", path)[0] == 200
    assert all(uid == classroom.users["owner"]["id"] for _, uid in classroom.seen)
    assert {kind for kind, _ in classroom.seen} == {"run", "model"}
    assert req(classroom, "owner", "POST", path + "/reset", {})[0] == 200
    assert req(classroom, "owner", "POST", path + "/delete", {})[1]["deleted"] is True


def test_another_account_cannot_read_modify_or_compile(classroom):
    result = create(classroom)
    path = "/api/research/studies/" + result["study_id"]
    before = study.load_study(result["study_id"]).to_dict()
    assert req(classroom, "other", "GET", "/api/research/studies")[1] == {"studies": []}
    assert req(classroom, "other", "GET", "/api/research/context")[1]["studies"] == []
    for suffix in ("", "/report"):
        assert req(classroom, "other", "GET", path + suffix)[0] == 404
    for action in policy.STUDY_ACTIONS:
        assert req(classroom, "other", "POST", path + "/" + action, {"force": True, "run": True})[0] == 404
    assert study.load_study(result["study_id"]).to_dict() == before
    calls = len(classroom.seen)
    assert req(classroom, "other", "POST", "/api/research/studies", {"plan_id": support.PLAN["id"]})[0] == 400
    assert len(classroom.seen) == calls


def test_unowned_legacy_studies_stay_admin_only(classroom):
    protocol = support.make_protocol()
    old = study.new_study(support.PLAN, protocol.to_dict(), {"ok": True})
    study.save_study(old)
    path = "/api/research/studies/" + old.id
    assert req(classroom, "owner", "GET", path)[0] == 404
    assert req(classroom, "owner", "POST", path + "/delete", {})[0] == 404
    assert req(classroom, "teacher", "GET", path)[0] == 200


def test_force_cannot_bypass_member_preflight(classroom):
    sid = create(classroom)["study_id"]
    path = "/api/research/studies/" + sid
    assert req(classroom, "owner", "POST", path + "/approve", {"force": True})[0] == 403
    record = study.load_study(sid)
    record.protocol["conditions"][1]["config"] = {"llm": {"providers": {"bad": {"base_url": "http://invalid"}}}}
    record.stage = "approved"
    study.save_study(record)
    assert req(classroom, "owner", "POST", path + "/run", {})[0] == 400
    assert not any(kind == "run" for kind, _ in classroom.seen)


@pytest.mark.parametrize("patch", [
    {"real_work": {"enabled": True}}, {"economy": {"output_dir": "/tmp/escape"}},
    {"llm": {"providers": {"bad": {"base_url": "https://invalid"}}}},
    {"plugins": ["arbitrary"]}, {"memory": {"file": "../other"}},
])
def test_generated_infrastructure_changes_fail_preflight(classroom, patch):
    token = USER.set(classroom.users["owner"])
    try:
        protocol = support.make_protocol()
        protocol.conditions[1]["config"] = copy.deepcopy(patch)
        check = research_api._preflight(protocol)
        assert not check["ok"]
    finally:
        USER.reset(token)


def test_allowed_parameters_and_world_binding(classroom):
    token = USER.set(classroom.users["owner"])
    world_token = WORLD.set(None)
    try:
        protocol = support.make_protocol()
        protocol.conditions[1]["config"] = {"economy": {"tax_rate": 0.1}}
        assert research_api._preflight(protocol)["ok"]
        current = study.new_study(support.PLAN, protocol.to_dict(), {"ok": True})
        current.owner_id = classroom.users["owner"]["id"]
        current.world_id = "waaaaaaaa"
        with pytest.raises(ValueError, match="世界"):
            research_api._check_scope(current)
        WORLD.set({"id": "waaaaaaaa"})
        research_api._check_scope(current)
    finally:
        WORLD.reset(world_token)
        USER.reset(token)


def test_quota_gates_new_work_but_not_stop_or_delete(classroom):
    sid = create(classroom)["study_id"]
    classroom.store.set_setting("daily_llm_calls_per_user", 1)
    with mock.patch("gaworld.accounts.usage.TALLY.today", return_value=1):
        for suffix in ("/approve", "/run", "/resume", "/reset"):
            assert req(classroom, "owner", "POST", "/api/research/studies/" + sid + suffix, {})[0] == 429
        assert req(classroom, "owner", "POST", "/api/research/studies", {"plan_id": support.PLAN["id"]})[0] == 429
        assert req(classroom, "owner", "POST", "/api/research/studies/" + sid + "/stop", {})[0] == 200
        assert req(classroom, "owner", "POST", "/api/research/studies/" + sid + "/delete", {})[0] == 200


def test_parallel_outputs_and_static_traces_are_private(classroom):
    token = USER.set(classroom.users["owner"])
    try:
        spec = normalize_experiment({"worlds": [{"id": "base"}, {"id": "policy"}]})
        manifest = runner.prepare_experiment(spec, classroom.tmp.name, experiment_id="private-study")
        assert manifest["owner_id"] == classroom.users["owner"]["id"]
    finally:
        USER.reset(token)
    trace = Path(classroom.tmp.name) / manifest["worlds"]["base"]["trace"]
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text("{}", encoding="utf-8")
    root = manifest["root"]
    for who in ("owner", "teacher"):
        assert req(classroom, who, "GET", "/" + manifest["worlds"]["base"]["trace"])[0] == 200
        assert req(classroom, who, "GET", "/api/parallel-worlds/experiments")[1]["experiments"]
    assert req(classroom, "other", "GET", "/api/parallel-worlds/experiments")[1]["experiments"] == []
    for api in ("experiment", "interpretation", "heterogeneity"):
        assert req(classroom, "other", "GET", f"/api/parallel-worlds/{api}?root={root}&world=base&metric=stress")[0] == 404
    for prefix in ("/", "/site/../", "/site/%2e%2e/", "//", "/site/auth/../../"):
        assert req(classroom, "other", "GET", prefix + manifest["worlds"]["base"]["trace"])[0] == 404
        assert classroom._req("GET", prefix + manifest["worlds"]["base"]["trace"])[0].status in (303, 404)
    alias = Path(classroom.tmp.name) / "site" / "auth" / "alias"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(trace.parent)
    assert req(classroom, "other", "GET", "/site/auth/alias/simulation_trace.json")[0] == 404
    assert classroom._req("GET", "/site/auth/alias/simulation_trace.json")[0].status in (303, 404)


def test_unknown_study_mutations_are_not_allowed():
    assert policy.required("POST", "/api/research/studies/future/dangerous") == "admin"
    assert policy.required("POST", "/api/research/studies/id/run/extra") == "admin"


def test_teacher_run_preserves_study_output_ownership(classroom):
    from gaworld.research.backends import default_seed_runner

    token = USER.set(classroom.users["teacher"])
    try:
        spec = normalize_experiment({"worlds": [{"id": "base"}, {"id": "policy"}]})
        run = default_seed_runner(
            repo_root=classroom.tmp.name, base_config={}, experiment_prefix="teacher-check", active={},
            owner={"owner_id": classroom.users["owner"]["id"], "owner": "owner"},
        )
        with mock.patch("gaworld.research.backends.prunner.ExperimentRunner") as fake:
            fake.return_value.run.return_value = {}
            fake.return_value.manifest = {"status": "done"}
            result = run(spec, 42, lambda *args: None)
        assert runner.load_manifest(classroom.tmp.name, result["root"])["owner_id"] == classroom.users["owner"]["id"]
    finally:
        USER.reset(token)


def test_finished_study_cannot_stop_another_active_study(classroom, monkeypatch):
    sid = create(classroom)["study_id"]
    other_stop = mock.Mock()
    monkeypatch.setattr(research_api, "_ACTIVE_STUDIES", {"another-study": {"study_id": "another-study", "stop": other_stop}})
    status, result = req(classroom, "owner", "POST", "/api/research/studies/" + sid + "/stop", {})
    assert status == 200 and result["stopping"] is False
    other_stop.set.assert_not_called()
