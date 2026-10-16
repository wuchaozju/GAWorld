"""Private editable research workspaces and independent controlled runs."""

import copy
import threading

import pytest

from gaworld.accounts.context import USER, WORLD
from gaworld.apps import research_api as api
from gaworld.research import protocol, study, workbench


def protocol_data():
    return protocol.Protocol(
        title="Workspace study",
        sim_days=3,
        execution_mode="daily_brief",
        purpose="exploratory",
        sample={"agent_ids": [1]},
        validity={"seeds": [42]},
        conditions=[
            {"id": "base", "label": "Base", "role": "baseline", "events": [], "config": {}},
            {"id": "treat", "label": "Treatment", "role": "treatment", "events": [], "config": {}},
        ],
        measures=[{"id": "stress"}],
        hypotheses=[
            {
                "id": "H1",
                "statement": "lower stress",
                "measure": "stress",
                "control": "base",
                "treatment": "treat",
                "direction": "decrease",
                "aggregation": "mean",
                "min_effect": 0.01,
            }
        ],
    ).to_dict()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(api, "_repo_root", lambda: str(tmp_path))
    monkeypatch.setattr(api, "_ACTIVE_STUDIES", {}, raising=False)
    monkeypatch.setattr(api, "_JOBS", {})
    monkeypatch.setattr(
        api,
        "_base_config",
        lambda: {
            "agent_ids": [1],
            "llm": {"providers": {"fixed": {"type": "openai", "model": "fixture", "api_key": "fake"}}},
        },
    )
    user = USER.set({"id": "alice", "nickname": "Alice", "role": "member"})
    world = WORLD.set({"id": "world-alice"})
    yield tmp_path
    WORLD.reset(world)
    USER.reset(user)


def save_plan():
    plan = workbench.ResearchPlan(
        id="plan-alice",
        kind="idea",
        title="Original plan",
        language="zh-CN",
        provider="fixed",
        created_at="2026-10-13T00:00:00+00:00",
        summary="Original summary",
        research_questions=["What happens?"],
        hypotheses=["stress falls"],
        design={"name": "Original design"},
    )
    workbench.save_plan(plan, {"owner_id": "alice", "world_id": "world-alice"})
    return plan


def save_study(**fields):
    p = protocol_data()
    record = study.new_study({"id": "plan-alice"}, p, protocol.preflight(protocol.Protocol.from_dict(p)))
    record.owner_id = "alice"
    record.world_id = "world-alice"
    for key, value in fields.items():
        setattr(record, key, value)
    study.save_study(record)
    return record


def test_member_sees_only_own_world_studies(workspace):
    mine = save_study()
    save_study(owner_id="bob")
    save_study(world_id="world-other")
    body, status = api.handle_get("/api/research/studies")
    assert status == 200
    assert [item["id"] for item in body["studies"]] == [mine.id]
    assert [item["id"] for item in api.context()["studies"]] == [mine.id]
    assert api.handle_get(f"/api/research/studies/{mine.id}")[1] == 200


def test_plan_world_filter_and_compile_reject_other_owner(workspace):
    save_plan()
    world = WORLD.set({"id": "world-other"})
    try:
        assert api.plans()["plans"] == []
        assert api.handle_post("/api/research/studies", {"plan_id": "plan-alice"})[1] == 400
    finally:
        WORLD.reset(world)
    user = USER.set({"id": "bob", "role": "member"})
    try:
        assert api.handle_post("/api/research/studies", {"plan_id": "plan-alice"})[1] == 400
    finally:
        USER.reset(user)


def test_delete_checks_owner_before_removing_artifact(workspace):
    theirs = save_study(owner_id="bob")
    assert api.handle_post(f"/api/research/studies/{theirs.id}/delete", {})[1] == 404
    assert study.load_study(theirs.id) is not None


def test_plan_edit_preserves_identity_and_revision(workspace):
    save_plan()
    body, status = api.handle_post(
        "/api/research/plans/plan-alice/update",
        {"plan": {"title": "Revised plan", "summary": "New summary", "research_questions": ["New question"]}},
    )
    assert status == 200, body
    saved = api.plan_detail("plan-alice")
    assert saved["title"] == "Revised plan"
    assert "New summary" in saved["markdown"]
    assert saved["owner_id"] == "alice"
    assert saved["revisions"][-1]["title"] == "Original plan"
    assert api.handle_post("/api/research/plans/plan-alice/update", {"plan": {"owner_id": "bob"}})[1] == 400


def test_protocol_edit_requires_reapproval_and_valid_references(workspace):
    record = save_study(stage="approved")
    data = copy.deepcopy(record.protocol)
    data["title"] = "Edited protocol"
    data["hypotheses"][0]["min_effect"] = 0.03
    body, status = api.handle_post(f"/api/research/studies/{record.id}/update", {"protocol": data})
    assert status == 200, body
    saved = study.load_study(record.id)
    assert saved.stage == "protocol"
    assert saved.title == "Edited protocol"
    data["hypotheses"][0]["treatment"] = "missing-world"
    assert api.handle_post(f"/api/research/studies/{record.id}/update", {"protocol": data})[1] == 400
    assert study.load_study(record.id).protocol["hypotheses"][0]["treatment"] == "treat"


def test_revision_of_reported_study_preserves_parent_and_source(workspace):
    original = save_study(
        stage="reported", evaluation={"summary": {"inconclusive": 1}}, report_markdown="old report"
    )
    before = study.load_study(original.id).to_dict()
    body, status = api.handle_post(f"/api/research/studies/{original.id}/revise", {})
    assert status == 200, body
    child = study.load_study(body["study_id"])
    assert child.parent_study_id == original.id
    assert child.stage == "protocol"
    assert child.runs == [] and child.evaluation == {}
    assert study.load_study(original.id).to_dict() == before


def test_quick_discards_only_unused_unsupported_measure(workspace):
    record = save_study()
    record.protocol["execution_mode"] = "lean_tick"
    record.protocol["measures"].append({"id": "risk_preference"})
    study.save_study(record)
    body = api.quick_study(record.id)
    child = study.load_study(body["study_id"])
    assert child.preflight["ok"]
    assert child.protocol_changes["excluded_unused_measures"] == ["risk_preference"]
    assert record.protocol["measures"][-1]["id"] == "risk_preference"


def test_two_runs_have_independent_controls_and_limits(workspace, monkeypatch):
    records = [save_study(stage="approved") for _ in range(3)]
    launched = []
    monkeypatch.setattr(api, "_run_in_background", lambda jid, work: launched.append(jid))
    jobs = [api._launch_run(record.id) for record in records[:2]]
    assert len(set(jobs)) == 2
    assert all(api._is_live(record.id) for record in records[:2])
    api.pause_study(records[0].id)
    assert api.study_detail(records[0].id)["paused"]
    assert not api.study_detail(records[1].id)["paused"]
    api.stop_study(records[0].id)
    assert not api.study_detail(records[1].id)["stopping"]
    assert api.handle_post(f"/api/research/studies/{records[2].id}/run", {})[1] == 409
    assert api.handle_post(f"/api/research/studies/{records[1].id}/run", {})[1] == 400


def test_job_status_denies_other_world(workspace):
    job_id = api._new_job("test")
    world = WORLD.set({"id": "world-other"})
    try:
        assert api.job_status(job_id) is None
    finally:
        WORLD.reset(world)


def test_parallel_completion_does_not_release_other_run(workspace, monkeypatch):
    first, second = save_study(stage="approved"), save_study(stage="approved")
    monkeypatch.setattr(api, "_run_in_background", lambda jid, work: None)
    api._launch_run(first.id)
    api._launch_run(second.id)
    api.stop_study(first.id)
    api._run_study(first.id, lambda p, m: None)
    assert not api._is_live(first.id)
    assert api._is_live(second.id)


def test_edit_cannot_accept_aggregation_that_evaluator_does_not_implement(workspace):
    record = save_study()
    data = copy.deepcopy(record.protocol)
    data["hypotheses"][0]["aggregation"] = "change"
    assert api.handle_post(f"/api/research/studies/{record.id}/update", {"protocol": data})[1] == 400


def test_edit_rejects_condition_id_that_engine_would_rename(workspace):
    record = save_study()
    data = copy.deepcopy(record.protocol)
    data["conditions"][1]["id"] = "Treatment / custom"
    data["hypotheses"][0]["treatment"] = "Treatment / custom"
    assert api.handle_post(f"/api/research/studies/{record.id}/update", {"protocol": data})[1] == 400


def test_edit_cannot_upgrade_measure_evidence_grade(workspace):
    record = save_study()
    data = copy.deepcopy(record.protocol)
    data["measures"][0].update(grade="a", basis="fabricated calibration", source="invented")
    body, status = api.handle_post(f"/api/research/studies/{record.id}/update", {"protocol": data})
    assert status == 200, body
    metric = study.load_study(record.id).protocol["measures"][0]
    assert metric["grade"] == "c"
    assert metric["basis"] != "fabricated calibration"


def test_world_subprocess_usage_is_attributed_to_member(workspace):
    from gaworld.accounts import usage
    from gaworld.parallel.runner import ExperimentRunner

    runner = ExperimentRunner(
        {"worlds": {"base": {"dir": "world", "overrides": {}}}, "spec": {}}, str(workspace)
    )
    env = runner._env("base")
    assert env[usage.ENV_USER] == "alice"
    assert env[usage.ENV_WORLD] == "world-alice"


def test_parallel_routes_cannot_bypass_study_privacy(workspace, monkeypatch):
    from gaworld.apps import parallel_worlds_api
    from gaworld.parallel import runner, spec

    monkeypatch.setattr(parallel_worlds_api, "_repo_root", lambda: str(workspace))
    manifest = runner.prepare_experiment(
        spec.normalize_experiment(
            {"worlds": [{"id": "base", "label": "Base"}, {"id": "treat", "label": "Treatment"}]}
        ),
        str(workspace),
        experiment_id="private-experiment",
    )
    assert parallel_worlds_api._load_any_manifest(manifest["root"]) is not None
    token = USER.set({"id": "bob", "role": "member"})
    try:
        assert parallel_worlds_api.list_experiments() == []
        assert parallel_worlds_api._load_any_manifest(manifest["root"]) is None
        assert (
            parallel_worlds_api.handle_get("/api/parallel-worlds/experiment", {"root": [manifest["root"]]})[1]
            == 404
        )
    finally:
        USER.reset(token)


def test_member_can_delete_and_run_owned_studies_at_policy_boundary(workspace):
    from gaworld.accounts import policy

    assert policy.required("POST", "/api/research/studies/owned/delete") == "member"
    assert policy.required("POST", "/api/research/studies/owned/run") == "member"


@pytest.mark.parametrize("action", ["update", "approve", "reset", "delete"])
def test_launch_is_atomic_with_protocol_mutations(workspace, monkeypatch, action):
    from gaworld.accounts import ownership

    record = save_study(stage="approved")
    entered, release, attempting = threading.Event(), threading.Event(), threading.Event()
    original_check = api._check_runtime_compatibility
    monkeypatch.setattr(api, "_run_in_background", lambda jid, work: None)

    def blocked_check(*args):
        entered.set()
        assert release.wait(2)
        return original_check(*args)

    monkeypatch.setattr(api, "_check_runtime_compatibility", blocked_check)
    results = []
    first = ownership.spawn(lambda: results.append(api._launch_run(record.id)), name="test-launch")
    assert entered.wait(2)

    def mutate():
        attempting.set()
        payload = {"protocol": record.protocol} if action == "update" else {}
        results.append(api.handle_post(f"/api/research/studies/{record.id}/{action}", payload)[1])

    second = ownership.spawn(mutate, name="test-mutate")
    assert attempting.wait(2)
    release.set()
    first.join(2)
    second.join(2)
    assert not first.is_alive() and not second.is_alive()
    assert 400 in results
    assert study.load_study(record.id).stage == "running"


def test_provider_probe_counted_but_config_inspection_is_free(workspace, monkeypatch):
    from gaworld.accounts import usage
    from gaworld.llm import providers

    calls = []
    monkeypatch.setattr(usage, "record", lambda task=None: calls.append(task))
    monkeypatch.setattr(providers, "probe_provider", lambda cfg: {"ok": True})
    record = save_study()
    api.check_study_provider(record.id, {})
    assert calls == []
    api.check_study_provider(record.id, {"probe": True})
    assert calls == ["research_provider_probe"]


def test_source_snapshot_survives_later_plan_edits_and_deletion(workspace, monkeypatch):
    import json
    import time

    save_plan()
    monkeypatch.setattr(api, "_llm", lambda *args: lambda prompt: json.dumps(protocol_data()))
    result = api.start_study({"plan_id": "plan-alice"})
    deadline = time.monotonic() + 2
    while api.job_status(result["job_id"])["status"] == "running" and time.monotonic() < deadline:
        threading.Event().wait(0.01)
    job = api.job_status(result["job_id"])
    assert job["status"] == "done", job
    sid = job["result"]["study_id"]
    api.update_plan("plan-alice", {"plan": {"title": "Changed later"}})
    api.delete({"plan_id": "plan-alice"})
    assert api.study_detail(sid)["source_plan"]["title"] == "Original plan"


def test_world_usage_identity_survives_worker_thread(workspace):
    from gaworld.accounts import usage
    from gaworld.parallel.runner import ExperimentRunner

    runner = ExperimentRunner(
        {"worlds": {"base": {"dir": "world", "overrides": {}}}, "spec": {}}, str(workspace)
    )
    results = []
    thread = threading.Thread(target=lambda: results.append(runner._env("base")))
    thread.start()
    thread.join(2)
    assert results[0][usage.ENV_USER] == "alice"


def test_adding_measured_survey_selects_composite_engine(workspace):
    record = save_study()
    data = copy.deepcopy(record.protocol)
    data["survey"] = {"questions": [{"id": "Q1", "text": "Stress?", "kind": "scale", "min": 0, "max": 10}]}
    body, status = api.handle_post(f"/api/research/studies/{record.id}/update", {"protocol": data})
    assert status == 200, body
    assert study.load_study(record.id).protocol["kind"] == "composite"


@pytest.mark.parametrize(
    "prefix", ["/output/parallel_worlds/", "/output//parallel_worlds/", "/output%2fparallel_worlds/"]
)
def test_static_research_traces_are_private_including_archives(workspace, monkeypatch, prefix):
    from gaworld.apps import dashboard_server, world_paths
    from gaworld.parallel import runner, spec

    monkeypatch.setattr(world_paths, "REPO_ROOT", str(workspace))
    manifest = runner.prepare_experiment(
        spec.normalize_experiment(
            {"worlds": [{"id": "base", "label": "Base"}, {"id": "treat", "label": "Treatment"}]}
        ),
        str(workspace),
        experiment_id="private-experiment",
    )
    handler = object.__new__(dashboard_server.DashboardHandler)
    handler.accounts = object()
    handler.user = {"id": "bob", "role": "member"}
    handler.headers = {}
    denied = []
    monkeypatch.setattr(handler, "_deny", lambda code, msg: denied.append(code))
    route = prefix + manifest["id"] + "/worlds/base/visualization/runs/archived/simulation_trace.json"
    user_token, world_token = USER.set(USER.get()), WORLD.set(WORLD.get())
    try:
        assert handler._enter_world(route)
        assert denied == [404]
    finally:
        USER.reset(user_token)
        WORLD.reset(world_token)


def test_replay_list_hides_another_users_research(workspace, monkeypatch):
    from gaworld.apps import dashboard_server, world_paths
    from gaworld.parallel import runner, spec

    monkeypatch.setattr(world_paths, "REPO_ROOT", str(workspace))
    monkeypatch.setattr(world_paths, "effective_config", dict)
    manifest = runner.prepare_experiment(
        spec.normalize_experiment(
            {"worlds": [{"id": "base", "label": "Base"}, {"id": "treat", "label": "Treatment"}]}
        ),
        str(workspace),
        experiment_id="private-experiment",
    )
    row = {"id": manifest["root"] + "/worlds/base/visualization/simulation_trace.json"}
    monkeypatch.setattr(dashboard_server.replay_runs, "list_runs", lambda *args: [row])
    monkeypatch.setattr(dashboard_server.accounts, "enabled_store", lambda *args: object())
    assert dashboard_server._replay_runs() == [row]
    user = USER.set({"id": "bob", "role": "member"})
    try:
        assert dashboard_server._replay_runs() == []
    finally:
        USER.reset(user)


@pytest.mark.parametrize("field", ["id", "statement"])
def test_hypothesis_required_fields_rejected_before_execution(workspace, field):
    record = save_study()
    data = copy.deepcopy(record.protocol)
    data["hypotheses"][0].pop(field)
    assert api.handle_post(f"/api/research/studies/{record.id}/update", {"protocol": data})[1] == 400


@pytest.mark.parametrize("key", ["plugins", "pipeline"])
def test_member_study_cannot_override_server_code_loading(workspace, key):
    record = save_study()
    record.protocol["conditions"][1]["config"] = {key: {"class": "custom.code:Class"}}
    study.save_study(record)
    assert api.handle_post(f"/api/research/studies/{record.id}/approve", {})[1] == 400


def test_unhashable_metric_input_returns_validation_error(workspace):
    record = save_study()
    data = copy.deepcopy(record.protocol)
    data["measures"] = [{"id": ["stress"]}]
    assert api.handle_post(f"/api/research/studies/{record.id}/update", {"protocol": data})[1] == 400


def test_runtime_knob_revision_preserves_previous_seed_list(workspace):
    record = save_study()
    api.update_study(record.id, {"seeds": [99]})
    saved = study.load_study(record.id)
    assert saved.protocol["validity"]["seeds"] == [99]
    assert saved.protocol_revisions[-1]["validity"]["seeds"] == [42]


def test_current_sample_change_records_original_population(workspace):
    record = save_study()
    record.protocol["sample"]["agent_ids"] = [8]
    study.save_study(record)
    result = api.quick_study(record.id, {"use_current_sample": True})
    child = study.load_study(result["study_id"])
    assert child.protocol_changes["sample"]["before"]["agent_ids"] == [8]
    assert child.protocol_changes["sample"]["after"]["agent_ids"] == [1]
