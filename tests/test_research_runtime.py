"""Research runtime regression tests; no network or real model execution."""

import copy

import pytest

from gaworld.parallel import spec as parallel_spec
from gaworld.research import protocol as protocol_mod
from gaworld.research.evaluate import evaluate


def protocol():
    return protocol_mod.Protocol(
        title="test",
        sim_days=4,
        fast=True,
        sample={"agent_ids": [], "city": "requested-city"},
        conditions=[
            {"id": "baseline", "label": "base", "role": "baseline", "events": []},
            {
                "id": "treatment",
                "label": "t",
                "role": "treatment",
                "events": [{"day": 2, "time": "09:00", "name": "event", "description": "event"}],
            },
            {"id": "placebo", "label": "p", "role": "placebo", "events": []},
        ],
        measures=[{"id": "stress", "label": "stress"}],
        hypotheses=[
            {
                "id": "H1",
                "statement": "lower stress",
                "measure": "stress",
                "treatment": "treatment",
                "control": "baseline",
                "direction": "decrease",
                "min_effect": 0.01,
                "aggregation": "final",
            }
        ],
        validity={"seeds": [42, 123], "placebo": True},
    )


def test_legacy_fast_cost_no_longer_claims_one_call_per_day():
    p = protocol()
    check = protocol_mod.preflight(p, default_agents=2)
    assert check["budget"]["calls_per_agent_day"] > 1
    assert check["budget"]["execution_mode"] == "lean_tick"


def test_daily_brief_enables_actual_fast_forward_without_changing_legacy():
    payload = {
        "name": "test",
        "sim_days": 4,
        "fast": True,
        "worlds": [{"id": "baseline", "label": "base"}, {"id": "t", "label": "t"}],
    }
    old = parallel_spec.normalize_experiment(payload)
    old_overrides = parallel_spec.world_overrides(old, old.worlds[0], "world")
    assert not (old_overrides.get("long_run") or {}).get("enabled")
    daily = parallel_spec.normalize_experiment({**payload, "execution_mode": "daily_brief"})
    overrides = parallel_spec.world_overrides(daily, daily.worlds[0], "world")
    assert overrides["long_run"]["enabled"] is True
    assert overrides["long_run"]["unit"] == "day"
    assert overrides["simulate_realtime"] is False


def test_quick_protocol_freezes_sample_and_preserves_events():
    from gaworld.research.quick import quick_protocol

    parent = protocol()
    before = copy.deepcopy(parent.to_dict())
    quick, changes = quick_protocol(parent, {"agent_ids": [3, 8], "city": "actual-city"})
    assert parent.to_dict() == before
    assert quick.mode == "daily_brief"
    assert quick.purpose == "exploratory"
    assert quick.sample["agent_ids"] == [3, 8]
    assert quick.sample["city"] == "actual-city"
    assert quick.conditions == parent.conditions
    assert quick.sim_days == parent.sim_days
    assert quick.seeds == [42]
    assert changes["seeds"]["before"] == [42, 123]
    assert protocol_mod.preflight(quick)["ok"]


def test_quick_preflight_blocks_metrics_not_updated_by_daily_brief():
    from gaworld.research.quick import quick_protocol

    parent = protocol()
    parent.measures = [{"id": "cross_viewpoint_exposure"}]
    parent.hypotheses[0]["measure"] = "cross_viewpoint_exposure"
    quick, _ = quick_protocol(parent, {"agent_ids": [1]})
    check = protocol_mod.preflight(quick)
    assert not check["ok"]
    assert any("cross_viewpoint_exposure" in message for message in check["errors"])


def test_exploratory_placebo_never_produces_confirmatory_verdict():
    p = protocol()
    p.purpose = "exploratory"
    run = {
        "seed": 42,
        "report": {
            "baseline_id": "baseline",
            "trajectories": {
                "stress": {"baseline": [0.5, 0.5], "treatment": [0.5, 0.2], "placebo": [0.5, 0.5]}
            },
            "worlds": [
                {"id": wid, "has_data": True, "status": "done"}
                for wid in ("baseline", "treatment", "placebo")
            ],
        },
    }
    result = evaluate(p, [run])
    assert result["summary"]["supported"] == 0
    assert result["hypotheses"][0]["verdict"] == "inconclusive"
    assert result["purpose"] == "exploratory"


@pytest.fixture
def runtime_root(tmp_path, monkeypatch):
    from gaworld.apps import research_api
    from gaworld.research import workbench

    monkeypatch.setattr(workbench, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(research_api, "_repo_root", lambda: str(tmp_path))
    monkeypatch.setattr(research_api, "_base_config", lambda: {"agent_ids": [1, 3], "city": "actual"})
    monkeypatch.setattr(research_api, "_ACTIVE_STUDIES", {})
    monkeypatch.setattr(research_api, "_ATTEMPT_LOG_SECRETS", {})
    return tmp_path


def test_quick_api_creates_reviewable_child_and_leaves_parent_intact(runtime_root):
    from gaworld.apps import research_api
    from gaworld.research import study as store

    parent = store.new_study({"id": "plan-id"}, protocol().to_dict(), {"ok": True})
    store.save_study(parent)
    before = store.load_study(parent.id).to_dict()
    body, status = research_api.handle_post(f"/api/research/studies/{parent.id}/quick", {})
    assert status == 200
    child = store.load_study(body["study_id"])
    assert child.stage == "protocol"
    assert child.parent_study_id == parent.id
    assert child.protocol["execution_mode"] == "daily_brief"
    assert store.load_study(parent.id).to_dict() == before


@pytest.mark.parametrize(
    "patch", [{"csv_path": "different.csv"}, {"llm": {"providers": {"fixture": {"model": "changed"}}}}]
)
def test_research_condition_cannot_change_population_or_provider_identity(runtime_root, patch):
    from gaworld.apps import research_api
    from gaworld.research import study as store

    p = protocol()
    p.conditions[1]["config"] = patch
    study = store.new_study({"id": "plan-id"}, p.to_dict(), {"ok": True})
    store.save_study(study)
    assert research_api.handle_post(f"/api/research/studies/{study.id}/approve", {})[1] == 400


def test_log_api_reads_saved_world_and_denies_unowned_member(runtime_root):
    from gaworld.accounts.context import USER
    from gaworld.apps import research_api
    from gaworld.parallel.runner import prepare_experiment
    from gaworld.research import backends
    from gaworld.research import study as store

    parent = store.new_study({"id": "plan-id"}, protocol().to_dict(), {"ok": True})
    manifest = prepare_experiment(
        backends.experiment_spec(protocol(), 42), str(runtime_root), experiment_id=f"study_{parent.id}_s42"
    )
    Path = __import__("pathlib").Path
    Path(runtime_root / manifest["worlds"]["baseline"]["run_log"]).write_text("visible log\n")
    parent.runs = [{"seed": 42, "root": manifest["root"], "status": "done"}]
    store.save_study(parent)
    route = f"/api/research/studies/{parent.id}/logs"
    body, status = research_api.handle_get(route, {"seed": ["42"], "world": ["baseline"], "kind": ["run"]})
    assert status == 200
    assert "visible log" in body["text"]
    token = USER.set({"id": "member", "role": "member"})
    try:
        assert research_api.handle_get(route, {})[1] == 404
    finally:
        USER.reset(token)


@pytest.mark.parametrize("active", [True, False])
def test_logs_redact_frozen_credentials_after_config_rotation(runtime_root, monkeypatch, active):
    from gaworld.apps import research_api
    from gaworld.research import study as store

    study = store.new_study({"id": "plan-id"}, protocol().to_dict(), {"ok": True})
    store.save_study(study)
    directory = research_api._attempt_dir(study)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "events.log").write_text("server echoed old-private-key and new-private-key\n")
    monkeypatch.setattr(
        research_api,
        "_base_config",
        lambda: {"llm": {"providers": {"fixed": {"api_key": "new-private-key"}}}},
    )
    if active:
        research_api._ACTIVE_STUDIES[study.id] = {
            "study_id": study.id,
            "base_config": {"llm": {"providers": {"fixed": {"api_key": "old-private-key"}}}},
        }
    else:
        research_api._ATTEMPT_LOG_SECRETS[(study.id, study.attempt)] = ["old-private-key"]
    body = research_api.study_logs(study.id, {})
    assert "private-key" not in body["text"]
    assert body["text"].count("[REDACTED]") == 2


def test_provider_preview_does_not_make_generation_request(monkeypatch):
    from gaworld.research.provider_check import inspect_provider

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: pytest.fail("unexpected inference"))
    result = inspect_provider(
        {
            "llm": {
                "routing": {"default": "cloud"},
                "providers": {
                    "cloud": {"type": "anthropic", "model": "test", "api_key_env": "MISSING_TEST_KEY"}
                },
            }
        }
    )
    assert result["primary"] == "cloud"
    assert result["status"] == "missing_key"


def test_failed_world_with_partial_data_cannot_contribute_to_effect():
    p = protocol()
    run = {
        "seed": 42,
        "report": {
            "baseline_id": "baseline",
            "trajectories": {"stress": {"baseline": [0.5], "treatment": [0.1]}},
            "worlds": [
                {"id": "baseline", "status": "done", "has_data": True},
                {"id": "treatment", "status": "error", "has_data": True},
            ],
        },
    }
    assert evaluate(p, [run])["hypotheses"][0]["verdict"] == "unmeasured"


def test_mixed_execution_modes_cannot_be_pooled():
    p = protocol()
    report = {
        "baseline_id": "baseline",
        "trajectories": {"stress": {"baseline": [0.5], "treatment": [0.1], "placebo": [0.5]}},
        "worlds": [],
    }
    runs = [
        {"seed": 42, "execution_mode": "tick", "actual_provider": "a", "report": report},
        {"seed": 123, "execution_mode": "daily_brief", "actual_provider": "a", "report": report},
    ]
    result = evaluate(p, runs)
    assert result["summary"]["supported"] == 0
    assert result["comparability"]["mixed_runtime"]


def test_provider_abort_does_not_spawn_worlds_or_later_seeds(runtime_root, monkeypatch):
    from gaworld.llm.run_state import RunLedger
    from gaworld.parallel import runner as runner_mod
    from gaworld.research import backends

    ledger_path = str(runtime_root / "providers.sqlite")
    RunLedger(ledger_path).abort("provider failure budget")
    manifest = runner_mod.prepare_experiment(backends.experiment_spec(protocol(), 42), str(runtime_root))
    manifest["research"] = {"ledger": ledger_path}
    monkeypatch.setattr(runner_mod.subprocess, "run", lambda *a, **kw: pytest.fail("spawned after abort"))
    runner = runner_mod.ExperimentRunner(manifest, str(runtime_root))
    runner.run()
    assert runner.provider_blocked
    assert runner.manifest["status"] == "error"
    seeds = []

    def seed(spec, number, report):
        seeds.append(number)
        return {"provider_blocked": True, "status": "error"}

    backends.run_protocol(protocol(), run_seed=seed)
    assert seeds == [42]


def test_logs_cannot_be_read_from_another_active_world(runtime_root, monkeypatch):
    from gaworld.apps import research_api
    from gaworld.research import study as store

    parent = store.new_study({"id": "plan-id"}, protocol().to_dict(), {"ok": True})
    parent.world_id = "world-a"
    store.save_study(parent)
    monkeypatch.setattr(research_api.world_paths, "current_world", lambda: {"id": "world-b"})
    assert research_api.handle_get(f"/api/research/studies/{parent.id}/logs", {})[1] == 404


def test_explicit_tick_cannot_inherit_or_patch_long_run():
    payload = {
        "name": "test",
        "sim_days": 4,
        "execution_mode": "tick",
        "worlds": [
            {"id": "baseline", "label": "base", "config": {"long_run": {"enabled": True, "unit": "year"}}},
            {"id": "t", "label": "t"},
        ],
    }
    spec = parallel_spec.normalize_experiment(payload)
    overrides = parallel_spec.world_overrides(
        spec, spec.worlds[0], "world", base_config={"long_run": {"enabled": True}}
    )
    assert overrides["long_run"]["enabled"] is False
    assert overrides["long_run"]["unit"] == "day"


def test_provider_preview_resolves_first_provider_when_default_missing():
    from gaworld.research.provider_check import inspect_provider

    config = {"llm": {"providers": {"local": {"type": "ollama", "model": "model"}}}}
    assert inspect_provider(config)["primary"] == "local"


def test_quick_sample_rejects_switched_city_and_missing_ids(tmp_path):
    from gaworld.research.quick import quick_protocol, sample_identity

    original = tmp_path / "original.csv"
    current = tmp_path / "current.csv"
    original.write_text("agent_id,name\n1,A\n")
    current.write_text("agent_id,name\n1,B\n")
    p = protocol()
    p.sample["seed_identity"] = sample_identity({"csv_path": str(original)}, str(tmp_path))
    with pytest.raises(ValueError, match="样本"):
        quick_protocol(p, {"csv_path": str(current), "agent_ids": [1]}, repo_root=str(tmp_path))
    p.sample.pop("seed_identity")
    p.sample["agent_ids"] = [8]
    with pytest.raises(ValueError, match="8"):
        quick_protocol(p, {"csv_path": str(current)}, repo_root=str(tmp_path))


def test_daily_incompatibility_cannot_be_forced(runtime_root):
    from gaworld.apps import research_api
    from gaworld.research import study as store

    p = protocol()
    p.execution_mode = "daily_brief"
    p.measures.append({"id": "cross_viewpoint_exposure"})
    study = store.new_study({"id": "plan-id"}, p.to_dict(), {"ok": False})
    store.save_study(study)
    assert research_api.handle_post(f"/api/research/studies/{study.id}/approve", {"force": True})[1] == 400


def test_quick_approval_accepts_defaults_disabled_by_parallel_worlds(runtime_root, monkeypatch):
    from gaworld.apps import research_api
    from gaworld.research import backends
    from gaworld.research import study as store

    config = {
        "agent_ids": [1],
        "distributed": {"enabled": True},
        "moltbook": {"enabled": True},
    }
    monkeypatch.setattr(research_api, "_base_config", lambda: config)
    parent = store.new_study({"id": "plan-id"}, protocol().to_dict(), {"ok": True})
    store.save_study(parent)
    before = parent.to_dict()
    child_id = research_api.quick_study(parent.id)["study_id"]
    body, status = research_api.handle_post(f"/api/research/studies/{child_id}/approve", {})
    assert status == 200, body
    child = store.load_study(child_id)
    spec = backends.experiment_spec(protocol_mod.Protocol.from_dict(child.protocol), 42)
    for world in spec.worlds:
        overrides = parallel_spec.world_overrides(spec, world, "isolated", base_config=config)
        assert overrides["distributed"]["enabled"] is False
        assert overrides["moltbook"]["enabled"] is False
    assert store.load_study(parent.id).to_dict() == before
    assert config["distributed"]["enabled"] is True
    assert config["moltbook"]["enabled"] is True


@pytest.mark.parametrize("mechanism", ["distributed", "moltbook", "multiplayer"])
def test_daily_brief_still_blocks_explicit_tick_mechanisms(mechanism):
    from gaworld.research.quick import compatibility_errors

    p = protocol()
    p.execution_mode = "daily_brief"
    p.conditions[1]["config"] = {mechanism: {"enabled": True}}
    assert any(mechanism in message for message in compatibility_errors(p))


def test_daily_brief_still_blocks_inherited_multiplayer():
    from gaworld.research.quick import compatibility_errors

    assert any(
        "multiplayer" in message
        for message in compatibility_errors(protocol(), {"multiplayer": {"enabled": True}})
    )


def test_current_sample_pilot_requires_explicit_choice_and_records_difference(runtime_root, monkeypatch):
    from gaworld.apps import research_api
    from gaworld.research import quick
    from gaworld.research import study as store

    parent = store.new_study({"id": "plan-id"}, protocol().to_dict(), {"ok": True})
    store.save_study(parent)

    def inconsistent(*args):
        raise ValueError("原研究各世界的实际居民样本不一致")

    monkeypatch.setattr(quick, "original_sample", inconsistent)
    path = f"/api/research/studies/{parent.id}/quick"
    assert research_api.handle_post(path, {})[1] == 400
    data, status = research_api.handle_post(path, {"use_current_sample": True})
    assert status == 200
    child = store.load_study(data["study_id"])
    assert child.protocol["sample"]["agent_ids"] == [1, 3]
    assert child.protocol_changes["sample_origin"]["after"] == "current_city_independent_pilot"
    assert child.stage == "protocol"


def test_only_exploratory_child_can_explicitly_exclude_incompatible_measures(runtime_root):
    from gaworld.apps import research_api
    from gaworld.research import study as store

    p = protocol()
    p.execution_mode = "daily_brief"
    p.purpose = "exploratory"
    p.measures.append({"id": "cross_viewpoint_exposure"})
    child = store.new_study({"id": "plan-id"}, p.to_dict(), {"ok": False})
    child.parent_study_id = "parent-study"
    store.save_study(child)
    body, status = research_api.handle_post(
        f"/api/research/studies/{child.id}/update", {"exclude_incompatible": True}
    )
    assert status == 200 and body["preflight"]["ok"]
    saved = store.load_study(child.id)
    assert saved.protocol_changes["excluded_measures"] == ["cross_viewpoint_exposure"]
    assert len(saved.protocol["hypotheses"]) == 1
    ordinary = store.new_study({"id": "plan-id"}, p.to_dict(), {"ok": False})
    store.save_study(ordinary)
    assert (
        research_api.handle_post(
            f"/api/research/studies/{ordinary.id}/update", {"exclude_incompatible": True}
        )[1]
        == 400
    )
