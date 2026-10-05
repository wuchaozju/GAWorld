"""Organization state and real economic persistence share the same world."""

import pytest

from gaworld.economy import finance
from gaworld.organizations.service import OrganizationService
from tests.test_economy_conservation import _build_agent, _build_config


def boot(tmp_path, people, day=1):
    cfg = _build_config(str(tmp_path))
    cfg["stateful"] = True
    cfg["csv_path"] = str(tmp_path / "population.csv")
    cfg["organizations"] = {"enabled": True, "output_dir": str(tmp_path / "organizations")}
    ctx = {"config": cfg, "agents": people, "extension_state": {}, "day": day}
    finance.on_simulation_start(ctx)
    svc = OrganizationService(cfg, people, ctx)
    svc.start(day)
    return svc, ctx


def company(svc, oid, leader=1):
    svc.store.enqueue(
        {
            "type": "create",
            "organization_id": oid,
            "name": oid,
            "kind": "company",
            "leader_id": leader,
            "initial_balance_cents": 100000,
            "rule": "skill_first",
        }
    )
    svc.store.enqueue(
        {
            "type": "publish_job",
            "organization_id": oid,
            "job_id": "job",
            "occupation": "工程师",
            "vacancies": 1,
            "monthly_salary_cents": 400000,
        }
    )


def apply(svc, oid, number=1):
    svc.store.enqueue({"type": "apply_job", "organization_id": oid, "job_id": "job", "agent_id": number})


def test_accountless_family_dependant_is_rejected_before_payment(tmp_path):
    people = [_build_agent(1), dict(_build_agent(2, age=75), family_dependant=True)]
    svc, _ = boot(tmp_path, people)
    svc.store.enqueue(
        {
            "type": "create",
            "organization_id": "care",
            "name": "互助会",
            "kind": "community",
            "leader_id": 1,
            "member_ids": [2],
            "initial_balance_cents": 1000,
        }
    )
    svc.store.enqueue({"type": "apply_aid", "organization_id": "care", "agent_id": 2, "amount_cents": 100})
    svc.process_day(1)
    app = svc.store.rows("applications", "care")[0]
    assert app["status"] == "rejected" and app["reason"] == "economic_account_missing"
    assert not svc.store.get_meta("recovery_required")
    assert svc.store.detail("care")["balance_cents"] == 1000
    svc.finish_day(1)
    svc.close()


def test_real_clean_resume_preserves_employment_budget_and_history(tmp_path):
    people = [_build_agent(1, job="待业")]
    svc, ctx = boot(tmp_path, people)
    company(svc, "firm")
    apply(svc, "firm")
    svc.process_day(1)
    assert svc.pay_wage(people[0], 15, dict(ctx, time_str="09:00"), "wage") == 15
    svc.finish_day(1)
    balance = svc.store.detail("firm")["balance_cents"]
    svc.close()
    seeded = [_build_agent(1, job="待业")]
    second, _ = boot(tmp_path, seeded, 2)
    assert second.store.detail("firm")["balance_cents"] == balance
    assert seeded[0]["employment"] == "employed"
    assert seeded[0]["job"] == "工程师"
    assert seeded[0]["economy"]["gross_monthly_salary"] == 4000
    second.close()


@pytest.mark.parametrize("category", ["wage", "year_bonus"])
@pytest.mark.parametrize("funding", [10000, 50000])
def test_old_wage_arrears_do_not_replace_todays_fast_forward_income(tmp_path, category, funding):
    people = [_build_agent(1)]
    svc, ctx = boot(tmp_path, people)
    company(svc, "firm")
    apply(svc, "firm")
    svc.process_day(1)
    svc.pay_wage(people[0], 1100, ctx, category)
    assert svc.store.detail("firm")["arrears_cents"] == 10000
    svc.finish_day(1)
    svc.prepare_day(2)
    finance.on_day_start(ctx)
    svc.store.enqueue({"type": "fund", "organization_id": "firm", "amount_cents": funding})
    svc.process_day(2)
    arrears_income = people[0]["economy"]["daily_income"]
    assert arrears_income > 0
    balance = funding - 10000
    assert svc.store.detail("firm")["balance_cents"] == balance
    finance.on_day_end({**ctx, "coarse": True, "period_days": 1})
    if balance:
        assert people[0]["economy"]["daily_income"] > arrears_income
        assert svc.store.detail("firm")["balance_cents"] < balance
    else:
        assert people[0]["economy"]["daily_income"] == arrears_income
        assert svc.store.detail("firm")["arrears_cents"] > 0
    wages = [
        row
        for row in svc.store.rows("transactions", "firm")
        if row["day"] == 2 and row["purpose"] == "wage" and row["new_obligation"]
    ]
    assert len(wages) == 1 and wages[0]["requested_cents"] > 0
    svc.finish_day(2)
    svc.close()


@pytest.mark.parametrize("funding", [0, 500])
def test_unfunded_or_partial_paid_leave_does_not_add_another_fast_forward_wage(tmp_path, funding):
    people = [_build_agent(1)]
    svc, ctx = boot(tmp_path, people)
    company(svc, "firm")
    apply(svc, "firm")
    svc.process_day(1)
    svc.pay_wage(people[0], 1000, ctx, "wage")
    svc.finish_day(1)
    svc.prepare_day(2)
    finance.on_day_start(ctx)
    if funding:
        svc.store.enqueue({"type": "fund", "organization_id": "firm", "amount_cents": funding})
    svc.process_day(2)
    record = finance.credit_paid_leave(people[0], ctx, day=2)
    assert record["pay"] == funding / 100
    wages = [row for row in svc.store.rows("transactions", "firm") if row["day"] == 2]
    assert len(wages) == (2 if funding else 1)
    finance.on_day_end({**ctx, "coarse": True, "period_days": 1})
    assert [row for row in svc.store.rows("transactions", "firm") if row["day"] == 2] == wages
    svc.finish_day(2)
    svc.close()


@pytest.mark.parametrize("absent", [False, True])
def test_departure_is_restored_before_returning_resident_can_receive_old_contract_pay(tmp_path, absent):
    people = [_build_agent(1), _build_agent(2)]
    svc, _ = boot(tmp_path, people)
    company(svc, "firm", leader=2)
    apply(svc, "firm")
    svc.process_day(1)
    svc.finish_day(1)
    svc.close()
    current = [_build_agent(2)] if absent else [_build_agent(1), _build_agent(2)]
    second, _ = boot(tmp_path, current, 2)
    second.store.enqueue({"type": "remove_member", "organization_id": "firm", "agent_id": 1})
    second.process_day(2)
    second.finish_day(2)
    second.close()
    returned, ctx = boot(tmp_path, [_build_agent(1), _build_agent(2)], 3)
    returned.process_day(3)
    person = ctx["agents"][0]
    assert person["employment"] == "unemployed"
    assert person["job"] == person["economy"]["job"] == "待业中"
    assert finance.labour_force_snapshot(ctx["agents"])["unemployment_rate"] == 0.5
    cash = person["economy"]["accounts"]["checking"]
    firms = finance._economy_state(ctx)["sectors"]["firms"]
    finance.credit_paid_leave(person, ctx, day=3)
    assert person["economy"]["accounts"]["checking"] == cash
    assert finance._economy_state(ctx)["sectors"]["firms"] == firms
    assert returned.store.detail("firm")["jobs"][0]["occupied"] == 0
    shock_count = len(person["economy"]["shock_log"])
    returned.finish_day(3)
    returned.close()
    fourth, fourth_ctx = boot(tmp_path, [_build_agent(1), _build_agent(2)], 4)
    fourth.process_day(4)
    assert fourth_ctx["agents"][0]["employment"] == "unemployed"
    assert len(fourth_ctx["agents"][0]["economy"]["shock_log"]) == shock_count
    fourth.close()


@pytest.mark.parametrize("new_job", ["教师", "工程师"])
def test_pending_departure_does_not_override_later_external_employment(tmp_path, new_job):
    svc, _ = boot(tmp_path, [_build_agent(1), _build_agent(2)])
    company(svc, "firm", leader=2)
    apply(svc, "firm")
    svc.process_day(1)
    svc.finish_day(1)
    svc.close()
    absent, _ = boot(tmp_path, [_build_agent(2)], 2)
    absent.store.enqueue({"type": "remove_member", "organization_id": "firm", "agent_id": 1})
    absent.process_day(2)
    absent.finish_day(2)
    absent.close()
    returned, ctx = boot(tmp_path, [_build_agent(1), _build_agent(2)], 3)
    person = ctx["agents"][0]
    finance.apply_employment_event(
        person,
        {"template_key": "job_change", "new_job": new_job, "new_monthly_salary_cents": 450000},
        returned.config,
        3,
    )
    shocks = len(person["economy"]["shock_log"])
    returned.process_day(3)
    assert person["employment"] == "employed" and person["job"] == new_job
    assert person["economy"]["gross_monthly_salary"] == 4500
    assert len(person["economy"]["shock_log"]) == shocks
    assert returned.store.get("members", "firm:1")["pending_employment_exit"] is None
    assert returned.store.history("firm")[0]["result"] == "superseded_by_new_employment"
    returned.close()


@pytest.mark.parametrize("absent", [False, True])
def test_employee_exit_precedes_real_travel_pay_and_refreshes_employment_statistics(tmp_path, absent):
    from gaworld.economy.plugin import EconomyPlugin
    from gaworld.kernel import build_kernel
    from gaworld.organizations.plugin import OrganizationsPlugin
    from gaworld.travel.plugin import TravelPlugin

    svc, _ = boot(tmp_path, [_build_agent(1), _build_agent(2)])
    company(svc, "firm", leader=2)
    apply(svc, "firm")
    svc.process_day(1)
    svc.finish_day(1)
    cfg = svc.config
    if not absent:
        svc.store.enqueue({"type": "remove_member", "organization_id": "firm", "agent_id": 1})
    svc.close()
    if absent:
        subset, _ = boot(tmp_path, [_build_agent(2)], 2)
        subset.store.enqueue({"type": "remove_member", "organization_id": "firm", "agent_id": 1})
        subset.process_day(2)
        subset.finish_day(2)
        cfg = subset.config
        subset.close()
    day = 3 if absent else 2
    cfg["economy"]["shocks"] = {"enabled": False}
    cfg["travel"] = {"enabled": True, "max_away_share": 0, "daily_surcharge": 0}
    cfg["records"] = {"output_dir": str(tmp_path / "records")}
    people = [_build_agent(1), _build_agent(2)]
    people[0]["ext"] = {
        "travel": {
            "status": "away",
            "purpose": "leisure",
            "place": "成都",
            "depart_day": day,
            "return_day": day + 1,
        }
    }
    kernel = build_kernel(cfg, load_entry_points=False)
    kernel.set_agents(people)
    for plugin in [EconomyPlugin(), TravelPlugin(), OrganizationsPlugin()]:
        plugin.setup(kernel)
    context = {"config": cfg, "agents": people, "extension_state": {}, "day": day, "schedule_map": {}}
    assert kernel.bus.emit("on_simulation_start", **context) == []
    returned = kernel.plugin_state("organizations")["service"]
    try:
        balance = returned.store.detail("firm")["balance_cents"]
        used = people[0]["economy"].get("_paid_leave", {}).get("days", 0)
        assert kernel.bus.emit("on_day_start", **context) == []
        assert people[0]["employment"] == "unemployed"
        assert people[0]["economy"]["daily_income"] == 0
        assert people[0]["economy"].get("_paid_leave", {}).get("days", 0) == used
        assert finance._economy_state(context)["macro"]["unemployment_rate"] == 0.5
        assert returned.store.detail("firm")["balance_cents"] == balance
        assert returned.store.get("members", "firm:1")["pending_employment_exit"] is None
        assert returned.store.get_meta("open_day") == day
        returned.finish_day(day)
    finally:
        returned.close()


def test_employee_can_switch_and_release_previous_vacancy(tmp_path):
    people = [_build_agent(1), _build_agent(2)]
    svc, _ = boot(tmp_path, people)
    company(svc, "first", leader=2)
    company(svc, "second", leader=2)
    apply(svc, "first")
    svc.process_day(1)
    apply(svc, "second")
    svc.process_day(2)
    assert svc.store.detail("first")["jobs"][0]["occupied"] == 0
    assert svc.store.detail("second")["jobs"][0]["occupied"] == 1
    assert people[0]["ext"]["organizations"]["employer_id"] == "second"
    svc.close()


def test_real_family_snapshot_counts_only_registered_co_resident_dependants(tmp_path):
    person = _build_agent(1)
    person["ext"] = {
        "family": {
            "members": [
                {"kind": "ghost", "role": "child", "age": 8, "coresident": True},
                {"kind": "ghost", "role": "child", "age": 26, "coresident": True},
                {"kind": "agent", "role": "mother", "age": 74, "coresident": True},
                {"kind": "ghost", "role": "father", "age": 76, "coresident": False},
                {"kind": "agent", "role": "partner", "age": 32, "coresident": True},
            ]
        }
    }
    svc, _ = boot(tmp_path, [person])
    frozen = svc._freeze(person)
    assert frozen["dependants"] == 2
    assert not frozen["dependants_missing"]
    assert frozen["age"] == person["age"]
    person["ext"]["family"]["members"] = [{"kind": "ghost", "role": "child", "age": 8, "coresident": True}]
    assert svc._freeze(person)["age"] == person["age"]
    svc.close()


def test_controlled_action_waits_once_in_queue(tmp_path):
    people = [_build_agent(1)]
    svc, _ = boot(tmp_path, people)
    svc.store.enqueue(
        {"type": "create", "organization_id": "aid", "name": "Aid", "kind": "community", "leader_id": 1}
    )
    svc.process_day(1)
    action = svc.candidates(people[0], "自由活动")[0]
    assert svc.handle_action(people[0], action, 1, "09:00")
    assert not svc.handle_action(people[0], action, 1, "09:30")
    assert len([c for c in svc.store.commands() if c["status"] == "pending"]) == 1
    svc.close()


def test_employment_life_event_releases_slot_and_prior_payer(tmp_path):
    from gaworld.kernel import build_kernel
    from gaworld.organizations.plugin import OrganizationsPlugin

    people = [_build_agent(1)]
    svc, ctx = boot(tmp_path, people)
    company(svc, "firm")
    apply(svc, "firm")
    svc.process_day(1)
    kernel = build_kernel(ctx["config"], load_entry_points=False)
    plugin = OrganizationsPlugin()
    plugin.setup(kernel)
    kernel.plugin_state("organizations")["service"] = svc
    event = {"template_key": "retirement"}
    finance.apply_employment_event(people[0], event, ctx["config"], day=1)
    kernel.bus.emit("life.event.applied", agent=people[0], life_event=event, day=1)
    assert svc.store.detail("firm")["jobs"][0]["occupied"] == 0
    assert svc.pay_wage(people[0], 3, ctx, "wage") is None
    assert people[0]["ext"]["organizations"]["employer_id"] is None
    # A leader can stop working while retaining organizational leadership.
    assert svc.store.detail("firm")["leader_id"] == 1
    svc.close()


def test_payment_receipt_uses_current_day_and_time(tmp_path):
    people = [_build_agent(1)]
    svc, ctx = boot(tmp_path, people)
    company(svc, "firm")
    apply(svc, "firm")
    svc.process_day(1)
    svc.finish_day(1)
    svc.process_day(2)
    svc.pay_wage(people[0], 3, dict(ctx, day=2, time_str="14:00"), "wage")
    receipts = list(people[0]["economy"]["_organization_receipts"].values())
    assert receipts[-1]["day"] == 2
    assert receipts[-1]["time_str"] == "14:00"
    svc.close()


def test_inactive_arrears_are_reserved_then_paid_on_return(tmp_path):
    people = [_build_agent(1), _build_agent(2)]
    svc, ctx = boot(tmp_path, people)
    company(svc, "firm")
    # Two positions let us observe a continuing active employee separately.
    job = {
        "type": "publish_job",
        "organization_id": "firm",
        "job_id": "second",
        "occupation": "工程师",
        "vacancies": 1,
        "monthly_salary_cents": 400000,
    }
    svc.store.enqueue(job)
    apply(svc, "firm", 1)
    svc.store.enqueue({"type": "apply_job", "organization_id": "firm", "job_id": "second", "agent_id": 2})
    svc.process_day(1)
    svc.pay_wage(people[0], 1100, dict(ctx, day=1, time_str="09:00"), "wage")
    svc.finish_day(1)
    svc.close()
    only_two, ctx2 = boot(tmp_path, [_build_agent(2)], 2)
    only_two.store.enqueue({"type": "fund", "organization_id": "firm", "amount_cents": 10000})
    only_two.process_day(2)
    assert only_two.pay_wage(ctx2["agents"][0], 5, dict(ctx2, time_str="09:00"), "wage") == 0
    only_two.finish_day(2)
    only_two.close()
    returned, ctx3 = boot(tmp_path, [_build_agent(1), _build_agent(2)], 3)
    cash = ctx3["agents"][0]["economy"]["accounts"]["checking"]
    returned.process_day(3)
    assert ctx3["agents"][0]["economy"]["accounts"]["checking"] == round(cash + 100, 2)
    assert returned.store.detail("firm")["balance_cents"] == 0
    assert returned.store.detail("firm")["arrears_cents"] == 500
    returned.close()


def test_proven_receipt_completes_pending_index_without_double_credit(tmp_path):
    people = [_build_agent(1)]
    svc, ctx = boot(tmp_path, people)
    company(svc, "firm")
    apply(svc, "firm")
    svc.process_day(1)
    svc.pay_wage(people[0], 7, dict(ctx, time_str="09:00"), "wage")
    svc.finish_day(1)
    tx = next(t for t in svc.store.rows("transactions") if t["purpose"] == "wage")
    org = svc.store.get("organizations", "firm")
    # A valid completed economic checkpoint proves the transfer. Only the
    # organization's pending ledger projection still needs committing.
    org["balance_cents"] += tx["paid_cents"]
    org["expense_cents"] -= tx["paid_cents"]
    tx["stage"] = "prepared"
    svc.store.put("organizations", "firm", org)
    svc.store.put("transactions", tx["transaction_id"], tx)
    cash = people[0]["economy"]["accounts"]["checking"]
    svc.close()
    resumed, new_ctx = boot(tmp_path, [_build_agent(1)], 2)
    assert new_ctx["agents"][0]["economy"]["accounts"]["checking"] == cash
    assert resumed.store.get("transactions", tx["transaction_id"])["stage"] == "committed"
    assert resumed.store.detail("firm")["balance_cents"] == 100000 - 700
    resumed.close()
