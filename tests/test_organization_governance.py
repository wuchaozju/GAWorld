"""Auditable organizational rule changes with real daily execution boundaries."""

import pytest

from gaworld.economy import finance
from gaworld.organizations.schemas import OrganizationValidationError, validate_command
from gaworld.organizations.service import OrganizationService
from tests.test_economy_conservation import _build_agent, _build_config


def boot(tmp_path, day=1, ids=(1, 2, 3, 4), enabled=True, stateful=True):
    cfg = _build_config(str(tmp_path))
    cfg.update(stateful=stateful, csv_path=str(tmp_path / "population.csv"))
    cfg["organizations"] = {
        "enabled": True,
        "output_dir": str(tmp_path / "organizations"),
        "governance": {"enabled": enabled},
    }
    people = [_build_agent(i) for i in ids]
    ctx = {"config": cfg, "agents": people, "extension_state": {}, "day": day}
    finance.on_simulation_start(ctx)
    svc = OrganizationService(cfg, people, ctx)
    svc.start(day)
    return svc


def queue(svc, command_type, oid="care", **fields):
    return svc.store.enqueue({"type": command_type, "organization_id": oid, **fields})


def seed(svc, mode="member_vote", kind="community", **policy):
    queue(
        svc,
        "create",
        name="互助会",
        kind=kind,
        leader_id=1,
        member_ids=[2, 3, 4],
        initial_balance_cents=1000,
        governance={"mode": mode, **policy},
    )


def propose(svc, kind="community", **fields):
    return queue(
        svc,
        "propose_rule",
        agent_id=1,
        proposal_id="p1",
        rule="need_first" if kind == "community" else "skill_first",
        **fields,
    )


def vote(svc, number, choice="yes", kind="cast_vote", **fields):
    return queue(svc, kind, agent_id=number, proposal_id="p1", choice=choice, **fields)


def proposal(svc):
    return svc.store.get("proposals", "care:p1")


def test_member_vote_executes_only_at_next_boundary_and_uses_existing_aid(tmp_path):
    svc = boot(tmp_path)
    seed(svc)
    propose(svc, rule_params={"max_award_cents": 200}, reason="优先困难成员")
    svc.process_day(1)
    assert proposal(svc)["status"] == "open"
    assert svc.store.detail("care")["rule_version"] == 1
    vote(svc, 1)
    vote(svc, 2, "abstain")
    svc.finish_day(1)
    svc.process_day(2)
    assert proposal(svc)["status"] == "approved"
    assert proposal(svc)["tally"]["participation"] == 2
    assert svc.store.detail("care")["rule_version"] == 1
    vote_late = vote(svc, 3)
    queue(svc, "apply_aid", agent_id=1, amount_cents=300)
    svc.finish_day(2)
    svc.process_day(3)
    org = svc.store.detail("care")
    assert org["rule"] == "need_first" and org["rule_version"] == 2
    assert proposal(svc)["status"] == "executed"
    assert proposal(svc)["decision_outcome"] == "approved"
    assert proposal(svc)["execution_rule_version"] == 2
    assert org["applications"][0]["paid_cents"] == 200
    assert svc.store.command(vote_late["command_id"])["status"] == "rejected"
    execution = svc.store.command(proposal(svc)["execution_command_id"])
    assert svc._apply_command(execution, 3)["rule_version"] == 2
    assert svc.store.detail("care")["rule_version"] == 2
    svc.finish_day(3)
    import json

    data = json.loads((svc.output_dir / "governance.json").read_text())
    assert data["day"] == 3 and data["organizations"][0]["executed"] == 1
    svc.close()


@pytest.mark.parametrize("choice,status", [("yes", "executed"), ("no", "rejected"), (None, "expired")])
def test_company_leader_decision(tmp_path, choice, status):
    svc = boot(tmp_path)
    seed(svc, mode="leader", kind="company")
    propose(svc, kind="company")
    svc.process_day(1)
    unauthorized = vote(svc, 2, kind="leader_decide")
    if choice:
        vote(svc, 1, choice, kind="leader_decide")
    svc.finish_day(1)
    svc.process_day(2)
    assert svc.store.command(unauthorized["command_id"])["status"] == "rejected"
    svc.finish_day(2)
    svc.process_day(3)
    assert proposal(svc)["status"] == status
    assert svc.store.detail("care")["rule"] == ("skill_first" if choice == "yes" else "lottery")
    svc.close()


def test_electorate_frozen_and_ballots_immutable(tmp_path):
    svc = boot(tmp_path, ids=(1, 2, 3, 4, 5))
    seed(svc)
    propose(svc)
    svc.process_day(1)
    queue(svc, "remove_member", agent_id=2)
    queue(svc, "add_member", agent_id=5)
    first = vote(svc, 2)
    same = vote(svc, 2)
    different = vote(svc, 2, "no")
    newcomer = vote(svc, 5)
    vote(svc, 1, "abstain")
    svc.finish_day(1)
    svc.process_day(2)
    assert proposal(svc)["electorate"] == [1, 2, 3, 4]
    assert (
        svc.store.command(same["command_id"])["result"]["ballot_id"]
        == svc.store.command(first["command_id"])["result"]["ballot_id"]
    )
    for cmd in (different, newcomer):
        assert svc.store.command(cmd["command_id"])["status"] == "rejected"
    assert len(svc.store.rows("ballots")) == 2
    assert proposal(svc)["status"] == "approved"
    svc.close()


@pytest.mark.parametrize("change", ["set_rule", "set_governance", "close", "handover"])
@pytest.mark.parametrize("after_approval", [False, True])
def test_conflicts_never_overwrite_newer_state(tmp_path, change, after_approval):
    svc = boot(tmp_path)
    seed(svc, mode="leader")
    propose(svc)
    svc.process_day(1)
    vote(svc, 1, kind="leader_decide")
    svc.finish_day(1)
    if after_approval:
        svc.process_day(2)
        svc.finish_day(2)
    fields = {
        "set_rule": {"rule": "equal_split"},
        "set_governance": {"governance": {"mode": "off"}},
        "close": {},
        "handover": {"leader_id": 2},
    }[change]
    queue(svc, change, **fields)
    svc.process_day(3 if after_approval else 2)
    # Existing queue order executes an already-approved change before a later manual command.
    # A conflict inserted earlier in the queue must also be rejected (tested separately).
    if not after_approval:
        assert proposal(svc)["status"] == "invalidated"
        assert svc.store.detail("care")["rule"] == "equal_split"
    else:
        assert proposal(svc)["status"] == "executed"
    svc.close()


def test_resume_keeps_absent_members_in_denominator(tmp_path):
    svc = boot(tmp_path)
    seed(svc)
    propose(svc)
    svc.process_day(1)
    vote(svc, 1)
    svc.finish_day(1)
    generation = svc.generation_id
    svc.close()
    resumed = boot(tmp_path, day=2, ids=(1,))
    resumed.process_day(2)
    assert resumed.generation_id == generation
    assert proposal(resumed)["status"] == "expired"
    assert proposal(resumed)["tally"]["eligible"] == 4
    resumed.close()


def test_resident_governance_actions_survive_pending_aid_and_hide_open_tally(tmp_path):
    svc = boot(tmp_path)
    seed(svc)
    svc.process_day(1)
    assert "org:propose_rule:care:need_first" in svc.candidates(svc.agents[1], "")
    assert svc.handle_action(svc.agents[1], "org:propose_rule:care:need_first", 1, "12:00")
    svc.finish_day(1)
    svc.process_day(2)
    p = svc.store.rows("proposals")[0]
    action = f"org:cast_vote:care:{p['proposal_id']}:yes"
    queue(svc, "apply_aid", agent_id=1, amount_cents=10)
    assert action in svc.candidates(svc.agents[1], "")
    assert svc.handle_action(svc.agents[1], action, 2, "12:00")
    assert action not in svc.candidates(svc.agents[1], "")
    assert "截止" in svc.perception(svc.agents[1])
    assert "总票数" not in svc.perception(svc.agents[2])
    assert not svc.handle_action(svc.agents[2], "org:cast_vote:care:forged:yes", 2, "12:00")
    svc.close()


def test_disabled_governance_is_inert(tmp_path):
    svc = boot(tmp_path, enabled=False)
    queue(svc, "create", name="互助会", kind="community", leader_id=1)
    cmd = propose(svc)
    svc.process_day(1)
    assert svc.store.command(cmd["command_id"])["status"] == "rejected"
    assert not svc.store.rows("proposals")
    assert not any("propose" in a for a in svc.candidates(svc.agents[1], ""))
    svc.finish_day(1)
    assert not (svc.output_dir / "governance.json").exists()
    svc.close()


def test_pending_governance_cannot_cross_generation(tmp_path):
    svc = boot(tmp_path)
    seed(svc)
    svc.process_day(1)
    cmd = propose(svc)
    svc.finish_day(1)
    svc.close()
    fresh = boot(tmp_path, stateful=False)
    seed(fresh)
    fresh.process_day(1)
    assert fresh.store.command(cmd["command_id"])["status"] == "rejected"
    assert not fresh.store.rows("proposals")
    fresh.close()


@pytest.mark.parametrize(
    "policy",
    [
        {"voting_days": True},
        {"voting_days": 0},
        {"mode": "autocrat"},
        {"threshold": "majority"},
        {"alien": 1},
    ],
)
def test_invalid_governance_configuration_rejected_before_start(policy):
    from gaworld.organizations.validation import validate_config

    with pytest.raises(ValueError):
        validate_config({"organizations": {"enabled": True, "governance": {"enabled": True, **policy}}})


def test_governance_is_default_off():
    from gaworld.settings.organizations import organizations_settings

    assert organizations_settings()["organizations"]["governance"]["enabled"] is False


def test_round_trip_handover_invalidates_leader_authority(tmp_path):
    svc = boot(tmp_path)
    seed(svc, mode="leader")
    propose(svc)
    svc.process_day(1)
    vote(svc, 1, kind="leader_decide")
    queue(svc, "handover", leader_id=2)
    queue(svc, "handover", leader_id=1)
    svc.finish_day(1)
    svc.process_day(2)
    assert proposal(svc)["status"] == "invalidated"
    svc.close()


def test_execution_id_collision_preserves_approved_decision_without_applying(tmp_path):
    import hashlib

    svc = boot(tmp_path)
    seed(svc)
    propose(svc)
    svc.process_day(1)
    vote(svc, 1)
    vote(svc, 2)
    token = hashlib.sha256(f"{svc.generation_id}:care:p1:execute".encode()).hexdigest()
    queue(svc, "fund", amount_cents=0, command_id=token)
    svc.finish_day(1)
    svc.process_day(2)
    assert proposal(svc)["decision_outcome"] == "approved"
    assert proposal(svc)["status"] == "execution_failed"
    assert svc.store.detail("care")["rule_version"] == 1
    svc.close()


@pytest.mark.parametrize("change", ["set_rule", "set_governance", "handover", "close"])
def test_conflict_queued_before_resolution_blocks_governed_execution(tmp_path, change):
    svc = boot(tmp_path)
    seed(svc, mode="leader")
    propose(svc)
    svc.process_day(1)
    vote(svc, 1, kind="leader_decide")
    svc.finish_day(1)
    fields = {
        "set_rule": {"rule": "equal_split"},
        "set_governance": {"governance": {"mode": "off"}},
        "handover": {"leader_id": 2},
        "close": {},
    }[change]

    class ConcurrentSubmission:
        def record(self, event, _row):
            if event == "organizations.governance.ballot":
                # A dashboard request arrives after the day's command snapshot,
                # but before resolution enqueues the governed execution.
                queue(svc, change, **fields)

    svc.recorder = ConcurrentSubmission()
    svc.process_day(2)
    assert proposal(svc)["status"] == "approved"
    svc.finish_day(2)
    svc.process_day(3)
    assert proposal(svc)["decision_outcome"] == "approved"
    assert proposal(svc)["status"] == "execution_failed"
    assert svc.store.detail("care")["rule"] == "equal_split"
    svc.close()


def test_resume_preserves_approved_execution_queue_and_historical_ballots(tmp_path):
    svc = boot(tmp_path)
    seed(svc)
    propose(svc)
    svc.process_day(1)
    vote(svc, 1)
    vote(svc, 2)
    svc.finish_day(1)
    svc.process_day(2)
    assert proposal(svc)["status"] == "approved"
    svc.finish_day(2)
    generation = svc.generation_id
    svc.close()
    resumed = boot(tmp_path, day=3)
    resumed.process_day(3)
    assert proposal(resumed)["status"] == "executed"
    resumed.finish_day(3)
    resumed.close()
    fresh = boot(tmp_path, stateful=False)
    assert not fresh.store.rows("proposals")
    fresh.close()
    from gaworld.organizations.store import OrganizationStore

    history = OrganizationStore(tmp_path / "memory" / "organizations.sqlite", generation_id=generation)
    assert history.detail("care")["proposals"][0]["status"] == "executed"
    assert len(history.detail("care")["ballots"]) == 2
    with pytest.raises(OrganizationValidationError):
        history.enqueue(
            {
                "type": "cast_vote",
                "organization_id": "care",
                "proposal_id": "p1",
                "agent_id": 3,
                "choice": "yes",
            }
        )
    history.close()


def test_switching_off_governance_does_not_execute_pending_approval(tmp_path):
    svc = boot(tmp_path)
    seed(svc)
    propose(svc)
    svc.process_day(1)
    vote(svc, 1)
    vote(svc, 2)
    svc.finish_day(1)
    svc.process_day(2)
    svc.finish_day(2)
    svc.close()
    resumed = boot(tmp_path, day=3, enabled=False)
    resumed.process_day(3)
    assert proposal(resumed)["status"] == "execution_failed"
    assert proposal(resumed)["decision_outcome"] == "approved"
    assert resumed.store.detail("care")["rule_version"] == 1
    resumed.close()


def test_proposal_cannot_claim_changed_eligibility_or_inactive_actor(tmp_path):
    svc = boot(tmp_path)
    seed(svc)
    same = queue(svc, "propose_rule", agent_id=1, rule="equal_split")
    outsider = queue(svc, "propose_rule", agent_id=99, rule="need_first")
    good = propose(svc)
    another = queue(svc, "propose_rule", agent_id=2, rule="need_first")
    svc.process_day(1)
    for command in (same, outsider, another):
        assert svc.store.command(command["command_id"])["status"] == "rejected"
    assert svc.store.command(good["command_id"])["status"] == "applied"
    svc.close()


def test_execution_tampering_and_premature_execution_do_not_change_rule(tmp_path):
    import copy

    svc = boot(tmp_path)
    seed(svc)
    propose(svc)
    svc.process_day(1)
    vote(svc, 1)
    vote(svc, 2)
    svc.finish_day(1)
    svc.process_day(2)
    command = svc.store.command(proposal(svc)["execution_command_id"])
    with pytest.raises(OrganizationValidationError):
        svc._apply_command(command, 2)
    tampered = copy.deepcopy(command)
    tampered["payload"]["rule_params"] = {"max_award_cents": 99999}
    with pytest.raises(OrganizationValidationError):
        svc._apply_command(tampered, 3)
    assert svc.store.detail("care")["rule_version"] == 1
    svc.close()


def test_governance_command_protocol():
    row = validate_command(
        {
            "type": "propose_rule",
            "organization_id": "care",
            "agent_id": 1,
            "rule": "need_first",
            "reason": "优先困难成员",
        }
    )
    assert row["reason"] == "优先困难成员"


@pytest.mark.parametrize(
    "threshold,choices,expected",
    [
        ("quorum_majority", ["yes", "abstain"], "approved"),
        ("quorum_majority", ["yes"], "expired"),
        ("quorum_majority", ["yes", "no"], "rejected"),
        ("electorate_majority", ["yes", "yes"], "rejected"),
        ("electorate_majority", ["yes", "yes", "yes"], "approved"),
        ("simple_majority", ["yes"], "approved"),
        ("simple_majority", [], "expired"),
    ],
)
def test_tally_thresholds(threshold, choices, expected):
    from gaworld.organizations.governance import tally

    result = tally(
        {"mode": "member_vote", "threshold": threshold},
        [1, 2, 3, 4],
        [{"agent_id": i + 1, "choice": c} for i, c in enumerate(choices)],
    )
    assert result["status"] == expected
    assert result["eligible"] == 4
    assert result["participation"] == len(choices)


@pytest.mark.parametrize(
    "extra",
    [
        {"rule_params": {"min_age": 18}},
        {"choice": "yes"},
        {"rule": "skill_first", "rule_params": {"max_award_cents": 1}},
    ],
)
def test_proposal_scope_is_strict(extra):
    with pytest.raises(OrganizationValidationError):
        validate_command(
            {"type": "propose_rule", "organization_id": "care", "agent_id": 1, "rule": "need_first", **extra}
        )
