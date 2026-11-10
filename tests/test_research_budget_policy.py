"""Budget admission must agree at planning, approval and network dispatch."""

import copy
import json

import pytest

from gaworld.apps import research_api
from gaworld.research import study as studies
from gaworld.research.protocol import Protocol, preflight
from tests import test_research_study as support

isolated_root = support.isolated_root
stubbed_api = support.stubbed_api


@pytest.fixture(autouse=True)
def no_workers(monkeypatch):
    """Admission tests never start a worker, even before the guard exists."""
    monkeypatch.setattr(research_api, "_run_in_background", lambda *_: None)


def test_requested_budget_uses_deployment_cap():
    from gaworld.research.budget import resolve_budget

    policy = resolve_budget(
        {"research_workbench": {"max_call_budget": 200_000}},
        {"call_budget": 150_000},
        member=False,
    )
    assert policy["call_budget"] == policy["http_budget"] == 150_000
    assert policy["maximum"] == 200_000


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "NaN", float("inf")])
def test_invalid_budget_cannot_be_coerced(value):
    from gaworld.research.budget import resolve_budget

    with pytest.raises(ValueError):
        resolve_budget({}, {"call_budget": value}, member=False)


def test_member_cannot_bypass_account_limit_or_lower_http_separately():
    from gaworld.research.budget import resolve_budget

    config = {"research_workbench": {"max_call_budget": 200_000}}
    with pytest.raises(ValueError, match="上限"):
        resolve_budget(config, {"call_budget": 150_000}, member=True, member_limit=60_000)
    result = resolve_budget(
        config, {"call_budget": 60_000, "http_budget": 12}, member=True, member_limit=60_000
    )
    assert result["http_budget"] == 12
    with pytest.raises(ValueError):
        resolve_budget(config, {"call_budget": 60_000, "http_budget": 70_000}, member=False)


def test_mode_checks_do_not_remove_unsupported_hypotheses():
    from gaworld.research.budget import mode_checks

    protocol = support.make_protocol()
    protocol.measures.append({"id": "social_need"})
    protocol.hypotheses[0]["measure"] = "social_need"
    before = copy.deepcopy(protocol.to_dict())
    checks = mode_checks(protocol, {}, agents=3, call_budget=50_000)
    assert checks["tick"]["compatible"]
    assert not checks["daily_brief"]["compatible"]
    assert "social_need" in " ".join(checks["daily_brief"]["errors"])
    assert protocol.to_dict() == before


def test_approval_fingerprint_binds_material_and_model_but_not_secrets(tmp_path):
    from gaworld.research.budget import approval_fingerprint, resolve_budget

    source = tmp_path / "seed.csv"
    source.write_text("id\n1\n")
    config = {
        "csv_path": str(source),
        "llm": {"routing": {"default": "test"}, "providers": {"test": {"model": "one", "api_key": "secret"}}},
    }
    protocol = support.make_protocol().to_dict()
    policy = resolve_budget(config, protocol, member=False)
    first = approval_fingerprint(protocol, config, policy, str(tmp_path))
    config["llm"]["providers"]["test"]["api_key"] = "rotated"
    assert approval_fingerprint(protocol, config, policy, str(tmp_path)) == first
    config["llm"]["providers"]["test"]["model"] = "two"
    assert approval_fingerprint(protocol, config, policy, str(tmp_path)) != first
    config["llm"]["providers"]["test"]["model"] = "one"
    source.write_text("id\n2\n")
    assert approval_fingerprint(protocol, config, policy, str(tmp_path)) != first


def make_study():
    protocol = support.make_protocol()
    protocol.sim_days = 40
    protocol.call_budget = 200_000
    protocol.http_budget = 150_000
    study = studies.new_study(support.PLAN, protocol.to_dict(), {})
    studies.save_study(study)
    return study


def test_approved_large_budget_launches_with_same_limit(stubbed_api, monkeypatch):
    config = research_api._base_config()
    config["research_workbench"] = {"max_call_budget": 250_000}
    monkeypatch.setattr(research_api, "_base_config", lambda: config)
    study = make_study()
    approved = research_api.approve_study(study.id, {})
    assert approved["stage"] == "approved"
    saved = studies.load_study(study.id)
    assert saved.preflight["budget"]["limit"] == 200_000
    assert saved.approval["policy"]["http_budget"] == 150_000
    monkeypatch.setattr(research_api, "_run_in_background", lambda *_: None)
    research_api._launch_run(study.id)
    from gaworld.llm.run_state import RunLedger

    ledger = RunLedger(str(research_api._attempt_dir(saved) / "providers.sqlite"))
    assert ledger.snapshot()["http_budget"] == 150_000


def test_old_approval_and_changed_policy_require_review(stubbed_api, monkeypatch):
    study = studies.new_study(support.PLAN, support.make_protocol().to_dict(), {"ok": True})
    study.set_stage("approved")
    studies.save_study(study)
    with pytest.raises(ValueError, match="重新批准"):
        research_api._launch_run(study.id)
    assert studies.load_study(study.id).stage == "protocol"
    research_api.approve_study(study.id, {})
    config = research_api._base_config()
    config["llm"]["providers"]["m1"]["model"] = "changed-model"
    monkeypatch.setattr(research_api, "_base_config", lambda: config)
    with pytest.raises(ValueError, match="重新批准"):
        research_api._launch_run(study.id)
    assert studies.load_study(study.id).stage == "protocol"


def test_preflight_budget_message_names_compatible_modes():
    protocol = support.make_protocol()
    result = preflight(protocol, call_budget=1)
    assert not result["ok"]
    assert "打开快速模式" not in " ".join(result["errors"])


def test_overrides_accept_explicit_budgets_without_model_recompile():
    from gaworld.research.protocol import apply_overrides

    protocol = apply_overrides(Protocol("test"), {"call_budget": "80000", "http_budget": "70000"})
    assert protocol.call_budget == 80_000
    assert protocol.http_budget == 70_000
    assert json.loads(json.dumps(protocol.to_dict()))["http_budget"] == 70_000


def test_all_residents_budget_counts_actual_csv_instead_of_five(tmp_path, monkeypatch):
    path = tmp_path / "seed.csv"
    path.write_text("agent_id,name\n" + "".join(f"{i},Resident\n" for i in range(1, 21)))
    monkeypatch.setattr(research_api, "_repo_root", lambda: str(tmp_path))
    assert research_api._default_agents({"csv_path": "seed.csv"}) == 20


def test_candidates_do_not_budget_all_csv_residents_as_one(tmp_path):
    from gaworld.research.budget import budget_candidates

    path = tmp_path / "seed.csv"
    path.write_text("agent_id,name\n" + "".join(f"{i},Resident\n" for i in range(1, 21)))
    protocol = support.make_protocol()
    protocol.sample["agent_ids"] = []
    protocol.sim_days = 40
    for candidate in budget_candidates(protocol, {"csv_path": str(path)}, call_budget=50_000):
        revised = copy.deepcopy(protocol)
        from gaworld.research.protocol import apply_overrides

        apply_overrides(revised, candidate["overrides"])
        check = preflight(revised, default_agents=20, call_budget=50_000)
        assert check["ok"]
        assert candidate["estimated_calls"] == check["budget"]["estimated_calls"]


def test_approval_binds_fallback_models_and_personality_assets(tmp_path):
    from gaworld.research.budget import approval_fingerprint, resolve_budget

    traits = tmp_path / "traits.csv"
    traits.write_text("id,openness\n1,0.3")
    config = {
        "personality": {"profile_path": str(traits)},
        "llm": {
            "routing": {"default": "a", "fallback": ["b"]},
            "providers": {"a": {"model": "primary"}, "b": {"model": "fallback"}},
        },
    }
    protocol = support.make_protocol().to_dict()
    policy = resolve_budget(config, protocol, member=False)
    first = approval_fingerprint(protocol, config, policy, str(tmp_path))
    config["llm"]["providers"]["b"]["model"] = "different"
    assert approval_fingerprint(protocol, config, policy, str(tmp_path)) != first
    second = approval_fingerprint(protocol, config, policy, str(tmp_path))
    traits.write_text("id,openness\n1,0.9")
    assert approval_fingerprint(protocol, config, policy, str(tmp_path)) != second
