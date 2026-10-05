"""Persistent, finite organization state transitions (no model/network calls)."""

import copy
import json
import math
from pathlib import Path

import pytest

from gaworld.economy import finance


def agent(number, cash=20, skill=0.5):
    return {
        "id": number,
        "name": f"Resident {number}",
        "age": 30,
        "job": "待业",
        "employment": "unemployed",
        "economy": {
            "accounts": {"checking": cash, "savings": 0},
            "income_skill": skill,
            "base_hourly_income": 10,
        },
    }


@pytest.fixture
def adapters(monkeypatch):
    """Isolate state machine from the independently tested finance adapter."""

    def register(ctx, oid, balance):
        ctx.setdefault("sectors", {}).setdefault(f"organization:{oid}", balance)

    def fund(ctx, oid, amount, source, transaction_id):
        receipts = ctx.setdefault("fund_receipts", {})
        if transaction_id not in receipts:
            sectors = ctx.setdefault("sectors", {})
            sectors[source] = sectors.get(source, 0) - amount
            sectors[f"organization:{oid}"] += amount
            receipts[transaction_id] = {
                "transaction_id": transaction_id,
                "paid_cents": amount,
                "unpaid_cents": 0,
            }
        return receipts[transaction_id]

    def transfer(ctx, oid, person, amount, transaction_id, purpose, *, max_paid_cents=None, is_arrears=False):
        receipts = person["economy"].setdefault("organization_receipts", {})
        if transaction_id not in receipts:
            sectors = ctx["sectors"]
            paid = min(
                amount,
                sectors[f"organization:{oid}"],
                max_paid_cents if max_paid_cents is not None else amount,
            )
            sectors[f"organization:{oid}"] -= paid
            person["economy"]["accounts"]["checking"] += paid / 100
            receipts[transaction_id] = {
                "transaction_id": transaction_id,
                "organization_id": oid,
                "agent_id": person["id"],
                "purpose": purpose,
                "requested_cents": amount,
                "paid_cents": paid,
                "unpaid_cents": amount - paid,
            }
        return receipts[transaction_id]

    def checkpoint(ctx, day):
        for person in ctx["agents"]:
            person["economy"]["_organization_checkpoint_day"] = day
        Path(ctx["config"]["memory_dir"], "fake-checkpoint.json").write_text(
            json.dumps({"day": day, "sectors": ctx.get("sectors", {})})
        )

    def restore(ctx, expected_day):
        path = Path(ctx["config"]["memory_dir"], "fake-checkpoint.json")
        if not path.exists():
            return False
        row = json.loads(path.read_text())
        if row["day"] != expected_day:
            return False
        ctx["sectors"] = row["sectors"]
        return all(p["economy"].get("_organization_checkpoint_day") == expected_day for p in ctx["agents"])

    monkeypatch.setattr(finance, "register_organization_account", register, raising=False)
    monkeypatch.setattr(finance, "organization_fund", fund, raising=False)
    monkeypatch.setattr(finance, "organization_transfer", transfer, raising=False)
    monkeypatch.setattr(
        finance,
        "get_organization_receipt",
        lambda ctx, p, tx: p["economy"].get("organization_receipts", {}).get(tx),
        raising=False,
    )
    monkeypatch.setattr(finance, "checkpoint_organization_economy", checkpoint, raising=False)
    monkeypatch.setattr(finance, "restore_organization_economy", restore, raising=False)

    def salary(person, cents, config):
        person["economy"]["gross_monthly_salary"] = cents / 100
        person["economy"]["base_hourly_income"] = cents / 100 / 176

    monkeypatch.setattr(finance, "set_contract_salary", salary, raising=False)


def service(tmp_path, people, adapters, stateful=True):
    from gaworld.organizations.service import OrganizationService

    cfg = {
        "memory_dir": str(tmp_path / "memory"),
        "stateful": stateful,
        "csv_path": "same-population.csv",
        "organizations": {"enabled": True, "output_dir": str(tmp_path / "organizations"), "seed": 71},
    }
    ctx = {"config": cfg, "agents": people, "day": 1}
    return OrganizationService(cfg, people, ctx)


def create(svc, oid="aid", kind="community", budget=1001, rule=None, members=None):
    return svc.store.enqueue(
        {
            "type": "create",
            "organization_id": oid,
            "name": oid,
            "kind": kind,
            "leader_id": 1,
            "member_ids": members or [1, 2, 3],
            "initial_balance_cents": budget,
            "funding_source": "government",
            "rule": rule or ("equal_split" if kind == "community" else "skill_first"),
            "rule_params": {"max_award_cents": 1000} if kind == "community" else {},
        }
    )


def queue_aid(svc, ids=(1, 2, 3), amount=1000):
    for number in ids:
        svc.store.enqueue(
            {
                "type": "apply_aid",
                "organization_id": "aid",
                "agent_id": number,
                "amount_cents": amount,
                "request_id": f"ask-{number}",
            }
        )


def test_profile_update_keeps_identity_accounts_and_prior_decisions(tmp_path, adapters):
    svc = service(tmp_path, [agent(i) for i in (1, 2, 3)], adapters)
    create(svc)
    queue_aid(svc, ids=(2,))
    svc.start(1)
    svc.process_day(1)
    before = svc.store.detail("aid")
    command = svc.store.enqueue(
        {
            "type": "update_profile",
            "organization_id": "aid",
            "name": "河畔互助会",
            "goal": "优先保障基本生活",
        },
        actor={"owner_id": 7},
    )
    svc.process_day(2)
    after = svc.store.detail("aid")
    assert after["name"] == "河畔互助会" and after["goal"] == "优先保障基本生活"
    for key in (
        "organization_id",
        "generation_id",
        "balance_cents",
        "income_cents",
        "expense_cents",
        "members",
        "decisions",
        "rule_version",
    ):
        assert after[key] == before[key]
    assert after["state_version"] == before["state_version"] + 1
    applied = svc.store.command(command["command_id"])
    assert applied["status"] == "applied"
    assert applied["result"]["before"]["name"] == "aid"
    assert applied["result"]["after"]["name"] == "河畔互助会"
    assert "河畔互助会" in svc.perception(svc.agents[2])
    svc.close()


@pytest.mark.parametrize(
    "fields",
    [{}, {"name": " "}, {"name": 3}, {"goal": None}, {"kind": "company"}, {"initial_balance_cents": 100}],
)
def test_profile_update_rejects_empty_or_structural_changes(fields):
    from gaworld.organizations.schemas import validate_command

    with pytest.raises(ValueError):
        validate_command({"type": "update_profile", "organization_id": "aid", **fields})


def test_amounts_reject_nonfinite_negative_and_noninteger():
    from gaworld.organizations.schemas import OrganizationValidationError, cents

    for value in [-1, True, 1.5, math.inf, math.nan, "100", 10**18]:
        with pytest.raises(OrganizationValidationError):
            cents(value)
    assert cents(101) == 101


def test_queue_idempotent_and_rejects_unknown_fields(tmp_path):
    from gaworld.organizations.schemas import OrganizationValidationError
    from gaworld.organizations.store import OrganizationStore

    store = OrganizationStore(tmp_path / "org.sqlite")
    payload = {"type": "fund", "organization_id": "a", "amount_cents": 100, "command_id": "same"}
    first = store.enqueue(payload, actor={"user_id": "teacher"})
    assert first == store.enqueue(payload, actor={"user_id": "teacher"})
    assert len(store.commands()) == 1
    with pytest.raises(OrganizationValidationError):
        store.enqueue(dict(payload, amount_cents=101))
    with pytest.raises(OrganizationValidationError):
        store.enqueue(dict(payload, memory_dir="/elsewhere"))


def test_handover_preserves_identity_budget_and_history(tmp_path, adapters):
    svc = service(tmp_path, [agent(i) for i in (1, 2, 3)], adapters)
    create(svc)
    svc.start(1)
    svc.process_day(1)
    svc.store.enqueue({"type": "handover", "organization_id": "aid", "leader_id": 2})
    svc.store.enqueue({"type": "remove_member", "organization_id": "aid", "agent_id": 2})
    svc.process_day(2)
    row = svc.store.detail("aid")
    assert row["leader_id"] == 2 and row["balance_cents"] == 1001
    assert len(svc.store.history("aid")) >= 2
    assert svc.store.commands()[-1]["status"] == "rejected"
    svc.close()


def test_equal_split_conserves_cents_and_repeated_boundary_is_idempotent(tmp_path, adapters):
    people = [agent(i) for i in (1, 2, 3)]
    svc = service(tmp_path, people, adapters)
    create(svc)
    queue_aid(svc)
    svc.start(1)
    svc.process_day(1)
    balances = [p["economy"]["accounts"]["checking"] for p in people]
    assert sum(round((b - 20) * 100) for b in balances) == 1001
    awards = sorted(round((b - 20) * 100) for b in balances)
    assert awards == [333, 334, 334]
    svc.process_day(1)
    assert balances == [p["economy"]["accounts"]["checking"] for p in people]
    row = svc.store.detail("aid")
    assert row["balance_cents"] == 0 and len(row["applications"]) == 3
    svc.close()


def test_need_first_uses_frozen_cash_and_records_missing_qualifications(tmp_path, adapters):
    people = [agent(1, 1), agent(2, 2), agent(3, 0)]
    people[2]["economy"].pop("accounts")
    svc = service(tmp_path, people, adapters)
    create(svc, budget=1000, rule="need_first")
    queue_aid(svc)
    svc.start(1)
    svc.process_day(1)
    apps = {a["agent_id"]: a for a in svc.store.detail("aid")["applications"]}
    assert apps[1]["paid_cents"] == 1000
    assert apps[2]["reason"] == "budget_exhausted"
    assert apps[3]["reason"] == "economic_account_missing"
    assert apps[1]["frozen"]["cash_cents"] == 100
    assert apps[1]["frozen"]["dependants_missing"] is True
    svc.close()


def test_company_finite_hiring_salary_and_single_employer(tmp_path, adapters):
    people = [agent(1, skill=0.3), agent(2, skill=0.9), agent(3, skill=0.7)]
    svc = service(tmp_path, people, adapters)
    for oid in ("firm", "other"):
        create(svc, oid=oid, kind="company", budget=100000)
        svc.store.enqueue(
            {
                "type": "publish_job",
                "organization_id": oid,
                "job_id": "engineer",
                "occupation": "工程师",
                "vacancies": 1,
                "monthly_salary_cents": 880000,
                "min_income_skill": 0.5,
            }
        )
        for number in (1, 2, 3):
            svc.store.enqueue(
                {"type": "apply_job", "organization_id": oid, "job_id": "engineer", "agent_id": number}
            )
    svc.start(1)
    svc.process_day(1)
    first, second = svc.store.detail("firm"), svc.store.detail("other")
    assert first["jobs"][0]["occupied"] == 1
    assert second["jobs"][0]["occupied"] == 1
    assert people[1]["ext"]["organizations"]["employer_id"] == "firm"
    assert people[2]["ext"]["organizations"]["employer_id"] == "other"
    assert people[1]["job"] == "工程师"
    assert people[1]["economy"]["gross_monthly_salary"] == 8800
    svc.close()


def test_missing_skill_is_rejected_even_for_lottery(tmp_path, adapters):
    people = [agent(1), agent(2), agent(3)]
    people[1]["economy"].pop("income_skill")
    svc = service(tmp_path, people, adapters)
    create(svc, oid="firm", kind="company", rule="lottery")
    svc.store.enqueue(
        {
            "type": "publish_job",
            "organization_id": "firm",
            "job_id": "job",
            "occupation": "工人",
            "vacancies": 1,
            "monthly_salary_cents": 10000,
        }
    )
    svc.store.enqueue({"type": "apply_job", "organization_id": "firm", "job_id": "job", "agent_id": 2})
    svc.start(1)
    svc.process_day(1)
    assert svc.store.detail("firm")["applications"][0]["reason"] == "income_skill_missing"
    svc.close()


def test_partial_wage_idempotency_and_funding_pays_arrears_first(tmp_path, adapters):
    people = [agent(1)]
    svc = service(tmp_path, people, adapters)
    create(svc, oid="firm", kind="company", budget=500, members=[1])
    svc.store.enqueue(
        {
            "type": "publish_job",
            "organization_id": "firm",
            "job_id": "job",
            "occupation": "工人",
            "vacancies": 1,
            "monthly_salary_cents": 10000,
        }
    )
    svc.store.enqueue({"type": "apply_job", "organization_id": "firm", "job_id": "job", "agent_id": 1})
    svc.start(1)
    svc.process_day(1)
    ctx = dict(svc.context, day=1, time="09:00")
    assert svc.pay_wage(people[0], 8, ctx, "work") == 5
    assert svc.pay_wage(people[0], 8, ctx, "work") == 5
    assert people[0]["economy"]["accounts"]["checking"] == 25
    assert svc.store.detail("firm")["arrears_cents"] == 300
    svc.store.enqueue({"type": "fund", "organization_id": "firm", "amount_cents": 600})
    svc.process_day(2)
    assert svc.store.detail("firm")["balance_cents"] == 300
    assert svc.store.detail("firm")["arrears_cents"] == 0
    assert people[0]["economy"]["accounts"]["checking"] == 28
    svc.close()


def test_clean_resume_retains_inactive_members_and_rejects_identity_reuse(tmp_path, adapters):
    people = [agent(i) for i in (1, 2, 3)]
    svc = service(tmp_path, people, adapters)
    create(svc)
    svc.start(1)
    svc.process_day(1)
    svc.finish_day(1)
    generation = svc.snapshot()["generation_id"]
    svc.close()
    resumed = service(tmp_path, people[:2], adapters)
    resumed.start(2)
    row = resumed.store.detail("aid")
    assert len(row["members"]) == 3
    assert row["members"][2]["active"] is False
    assert resumed.snapshot()["generation_id"] == generation
    resumed.close()
    changed = copy.deepcopy(people[:2])
    changed[0]["name"] = "Different person"
    broken = service(tmp_path, changed, adapters)
    with pytest.raises(RuntimeError, match="identity"):
        broken.start(2)
    broken.close()


def test_preparation_requires_completed_checkpoint_before_resume(tmp_path, adapters):
    people = [agent(i) for i in (1, 2, 3)]
    svc = service(tmp_path, people, adapters)
    svc.start(1)
    svc.prepare_day(1)
    assert svc.store.get_meta("open_day") == 1
    svc.close()
    resumed = service(tmp_path, people, adapters)
    try:
        with pytest.raises(RuntimeError, match="previous day did not reach"):
            resumed.start(1)
    finally:
        resumed.close()


def test_repeated_preparation_does_not_reopen_completed_day(tmp_path, adapters):
    svc = service(tmp_path, [agent(i) for i in (1, 2, 3)], adapters)
    svc.start(1)
    svc.prepare_day(1)
    svc.process_day(1)
    svc.finish_day(1)
    svc.prepare_day(1)
    assert svc.store.get_meta("open_day") is None
    assert svc.store.get_meta("last_processed_day") == 1
    svc.close()


def test_resume_requires_matching_economy_checkpoint(tmp_path, adapters):
    people = [agent(i) for i in (1, 2, 3)]
    svc = service(tmp_path, people, adapters)
    create(svc)
    svc.start(1)
    svc.process_day(1)
    svc.finish_day(1)
    svc.close()
    Path(tmp_path / "memory" / "fake-checkpoint.json").unlink()
    broken = service(tmp_path, people, adapters)
    with pytest.raises(RuntimeError, match="recovery_required"):
        broken.start(2)
    broken.close()


def test_missing_payment_receipt_fails_closed(tmp_path, adapters, monkeypatch):
    people = [agent(i) for i in (1, 2, 3)]
    svc = service(tmp_path, people, adapters)
    create(svc)
    queue_aid(svc, ids=(1,))
    svc.start(1)

    def broken_transfer(*args, **kwargs):
        raise OSError("interrupted payment")

    monkeypatch.setattr(finance, "organization_transfer", broken_transfer)
    with pytest.raises(RuntimeError, match="recovery_required"):
        svc.process_day(1)
    assert svc.snapshot()["recovery_required"] is True
    svc.close()
    resumed = service(tmp_path, people, adapters)
    with pytest.raises(RuntimeError, match="recovery_required"):
        resumed.start(1)
    resumed.close()


def test_single_writer_lease(tmp_path, adapters):
    people = [agent(i) for i in (1, 2, 3)]
    first = service(tmp_path, people, adapters)
    first.start(1)
    second = service(tmp_path, people, adapters)
    with pytest.raises(RuntimeError, match="writer"):
        second.start(1)
    second.close()
    first.close()


def test_stateless_restart_has_new_generation_without_repeat_old_initial_funding(tmp_path, adapters):
    people = [agent(i) for i in (1, 2, 3)]
    svc = service(tmp_path, people, adapters, stateful=False)
    create(svc)
    svc.start(1)
    svc.process_day(1)
    old = svc.snapshot()["generation_id"]
    svc.close()
    restarted = service(tmp_path, people, adapters, stateful=False)
    restarted.start(1)
    assert restarted.snapshot()["generation_id"] != old
    assert restarted.store.list_organizations() == []
    restarted.close()


def test_metrics_and_controlled_actions_are_real_records(tmp_path, adapters):
    people = [agent(i) for i in (1, 2, 3)]
    svc = service(tmp_path, people, adapters)
    create(svc)
    svc.start(1)
    svc.process_day(1)
    choices = svc.candidates(people[0], "申请资助")
    assert choices and choices[0].startswith("org:apply_aid:aid:")
    assert svc.handle_action(people[0], choices[0], 1, "10:00")
    assert not svc.handle_action(people[0], "我已收到组织资助", 1, "10:01")
    svc.process_day(2)
    svc.finish_day(2)
    payload = json.loads((tmp_path / "organizations" / "metrics.json").read_text())
    assert payload["generation_id"] == svc.snapshot()["generation_id"]
    row = payload["organizations"][0]
    assert row["applications"] == 1 and row["eligible_applications"] == 1
    assert row["coverage_denominator"] == 1
    assert row["aid_paid_cents"] == 1000
    svc.close()


def test_metrics_keep_frozen_group_denominators_and_rejection_reasons(tmp_path, adapters):
    people = [agent(i) for i in (1, 2, 3)]
    for person, age, gender in zip(people, (16, 40, 70), ("男", "女", "女"), strict=True):
        person.update(age=age, gender=gender)
    svc = service(tmp_path, people, adapters)
    create(svc, budget=1000)
    svc.start(1)
    for person in people:
        svc.store.enqueue(
            {"type": "apply_aid", "organization_id": "aid", "agent_id": person["id"], "amount_cents": 1000}
        )
    svc.process_day(1)
    # Changing the resident later must not alter the decision's subgroup.
    people[1]["age"] = 80
    svc.finish_day(1)
    row = json.loads((tmp_path / "organizations" / "metrics.json").read_text())["organizations"][0]
    assert row["rejection_reasons"] == {"under_age": 1}
    groups = row["groups"]
    assert groups["age_band"]["35_to_64"]["aid_paid_cents"] == 500
    assert groups["age_band"]["65_plus"]["eligible_applications"] == 1
    assert groups["gender"]["female"]["eligible_applications"] == 2
    assert groups["gender"]["male"]["rejections"] == 1
    assert groups["employment"]["unemployed"]["applications"] == 3
    assert (
        tmp_path / "organizations" / "generations" / svc.generation_id / "day-1" / "metrics.json"
    ).exists()
    svc.close()


def test_company_metrics_use_eligible_job_applications_as_hiring_denominator(tmp_path, adapters):
    people = [agent(1), agent(2), agent(3, skill=0.1)]
    svc = service(tmp_path, people, adapters)
    create(svc, kind="company")
    svc.start(1)
    svc.store.enqueue(
        {
            "type": "publish_job",
            "organization_id": "aid",
            "job_id": "work",
            "occupation": "设计师",
            "vacancies": 1,
            "monthly_salary_cents": 300000,
            "min_income_skill": 0.5,
        }
    )
    for person in people:
        svc.store.enqueue(
            {"type": "apply_job", "organization_id": "aid", "job_id": "work", "agent_id": person["id"]}
        )
    svc.process_day(1)
    svc.finish_day(1)
    row = json.loads((tmp_path / "organizations" / "metrics.json").read_text())["organizations"][0]
    assert row["eligible_applications"] == 2
    assert row["coverage_numerator"] == 1 and row["coverage_denominator"] == 2
    assert row["coverage"] == 0.5
    assert row["rejection_reasons"] == {"qualification_not_met": 1, "vacancy_filled": 1}
    svc.close()
