"""Organization payments conserve money and persist provable receipts."""

import csv
import json
from pathlib import Path

import pytest

from gaworld.economy import finance as eco
from tests.test_economy_conservation import _build_agent, _build_config


def economy(tmp_path):
    config = _build_config(str(tmp_path))
    config["stateful"] = True
    config["organizations"] = {"enabled": True}
    agent = _build_agent(1)
    context = {"config": config, "agents": [agent], "extension_state": {}, "day": 1}
    eco.on_simulation_start(context)
    return agent, context


def total(context):
    return eco._system_total(context["agents"], eco._economy_state(context)["sectors"])


@pytest.mark.parametrize("override", [False, True])
def test_post_organization_employment_snapshot_respects_today_macro_override(tmp_path, override):
    agent, context = economy(tmp_path)
    context["config"]["economy"]["shocks"] = {"enabled": False}
    if override:
        path = eco.intervention_path(eco._get_cfg(context))
        eco.write_interventions(path, {"pending": [{"macro": {"unemployment_rate": 0.12}}]})
    eco.on_day_start(context)
    eco.apply_employment_event(agent, {"template_key": "unemployment"}, context["config"], 1)
    eco.refresh_organization_employment_statistics(context)
    macro = eco._economy_state(context)["macro"]
    assert macro["labour_force"]["unemployment_rate"] == 1
    assert macro["unemployment_rate"] == (0.12 if override else 1)
    context["day"] = 2
    eco.on_day_start(context)
    eco.refresh_organization_employment_statistics(context)
    assert macro["unemployment_rate"] == 1


def test_funding_and_aid_are_conservative_and_not_taxable(tmp_path):
    agent, context = economy(tmp_path)
    before = total(context)
    cash = agent["economy"]["accounts"]["checking"]
    eco.register_organization_account(context, "care", 0)
    eco.organization_fund(context, "care", 10001, "government", "fund-1")
    receipt = eco.organization_transfer(context, "care", agent, 1234, "aid-1", "aid")
    assert receipt["paid_cents"] == 1234
    assert total(context) == before
    assert agent["economy"]["accounts"]["checking"] == round(cash + 12.34, 2)
    assert agent["economy"]["month_gross_income"] == 0
    assert agent["economy"]["daily_income"] == 0


def test_partial_wage_has_one_source_and_receipt_replay_is_noop(tmp_path):
    agent, context = economy(tmp_path)
    eco.register_organization_account(context, "firm", 0)
    eco.organization_fund(context, "firm", 500, "firms", "fund-1")
    sectors = eco._economy_state(context)["sectors"]
    firms = sectors["firms"]
    before = total(context)
    receipt = eco.organization_transfer(context, "firm", agent, 1000, "wage-1", "wage")
    assert receipt["paid_cents"] == receipt["unpaid_cents"] == 500
    assert agent["economy"]["daily_income"] == agent["economy"]["month_gross_income"] == 5
    cash = agent["economy"]["accounts"]["checking"]
    assert eco.organization_transfer(context, "firm", agent, 1000, "wage-1", "wage") == receipt
    assert agent["economy"]["accounts"]["checking"] == cash
    assert sectors["firms"] == firms
    assert sectors["organization:firm"] == 0
    assert total(context) == before
    with pytest.raises(ValueError, match="receipt"):
        eco.organization_transfer(context, "firm", agent, 999, "wage-1", "wage")
    path = eco._state_path(context, 1, eco._get_cfg(context))
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    assert saved["_organization_receipts"]["wage-1"] == receipt
    assert saved["accounts"]["checking"] == cash


@pytest.mark.parametrize("purpose, income", [("wage", 10), ("bonus", 8.5)])
def test_arrears_receipt_preserves_period_and_never_recounts_income_on_replay(tmp_path, purpose, income):
    agent, context = economy(tmp_path)
    eco.register_organization_account(context, "firm", 0)
    eco.organization_fund(context, "firm", 5000, "firms", "fund")
    receipt = eco.organization_transfer(context, "firm", agent, 1000, "old-pay", purpose, is_arrears=True)
    assert receipt["is_arrears"] is True
    assert agent["economy"]["_organization_arrears_income"] == {"day": 1, "amount": income}
    assert "_organization_current_wage_day" not in agent["economy"]
    cash = agent["economy"]["accounts"]["checking"]
    assert (
        eco.organization_transfer(context, "firm", agent, 1000, "old-pay", purpose, is_arrears=True)
        == receipt
    )
    assert agent["economy"]["_organization_arrears_income"]["amount"] == income
    assert agent["economy"]["accounts"]["checking"] == cash
    path = eco._state_path(context, 1, eco._get_cfg(context))
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    assert saved["_organization_arrears_income"] == {"day": 1, "amount": income}
    with pytest.raises(ValueError, match="obligation period"):
        eco.organization_transfer(context, "firm", agent, 1000, "old-pay", purpose)


def test_bonus_tax_and_housing_fund_debit_finite_employer(tmp_path):
    agent, context = economy(tmp_path)
    eco.register_organization_account(context, "firm", 0)
    eco.organization_fund(context, "firm", 10000, "firms", "fund")
    sectors = eco._economy_state(context)["sectors"]
    before = total(context)
    government = sectors["government"]
    hf = agent["economy"]["accounts"]["housing_fund"]
    bonus = eco.organization_transfer(context, "firm", agent, 1000, "bonus", "bonus")
    assert bonus["credited_cents"] == 850
    assert sectors["government"] == round(government + 1.5, 2)
    eco.organization_transfer(context, "firm", agent, 500, "hf", "housing_fund")
    assert agent["economy"]["accounts"]["housing_fund"] == round(hf + 5, 2)
    assert agent["economy"]["month_gross_income"] == 0
    assert total(context) == before


@pytest.mark.parametrize("amount", [-1, True, 1.2, float("nan"), float("inf"), 10**16])
def test_reject_invalid_money_before_mutation(tmp_path, amount):
    _agent, context = economy(tmp_path)
    eco.register_organization_account(context, "firm", 0)
    before = total(context)
    with pytest.raises(ValueError):
        eco.organization_fund(context, "firm", amount, "firms", "bad")
    assert total(context) == before


def test_checkpoint_resume_and_corrupt_receipt_fail_closed(tmp_path):
    agent, context = economy(tmp_path)
    eco.register_organization_account(context, "firm", 0)
    eco.organization_fund(context, "firm", 1000, "government", "fund")
    eco.organization_transfer(context, "firm", agent, 300, "wage", "wage")
    before = total(context)
    eco.checkpoint_organization_economy(context, 1)
    second = {"config": context["config"], "agents": [_build_agent(1)], "extension_state": {}, "day": 2}
    eco.on_simulation_start(second)
    assert eco.restore_organization_economy(second, 1)
    assert total(second) == before
    assert eco.get_organization_receipt(second, second["agents"][0], "wage")["paid_cents"] == 300
    second["agents"][0]["economy"]["_organization_checkpoint_day"] = 0
    with pytest.raises(ValueError, match="recovery_required"):
        eco.restore_organization_economy(second, 1)


def test_posted_salary_is_exact_and_does_not_draw_global_rng(tmp_path):
    agent, context = economy(tmp_path)
    state = eco._rng.getstate()
    eco.apply_employment_event(
        agent,
        {"template_key": "job_change", "new_job": "设计师", "new_monthly_salary_cents": 123456},
        config=context["config"],
        day=1,
    )
    assert agent["economy"]["gross_monthly_salary"] == 1234.56
    assert agent["economy"]["shock_log"][-1]["to_hourly"] == agent["economy"]["base_hourly_income"]
    assert agent["employment"] == "employed"
    assert eco._rng.getstate() == state


def test_checkpoint_preserves_inactive_recipients_across_subset_runs(tmp_path):
    agent, context = economy(tmp_path)
    eco.register_organization_account(context, "firm", 0)
    eco.organization_fund(context, "firm", 1000, "firms", "fund")
    eco.organization_transfer(context, "firm", agent, 200, "wage", "wage")
    eco.checkpoint_organization_economy(context, 1)
    subset = {"config": context["config"], "agents": [_build_agent(2)], "extension_state": {}, "day": 2}
    eco.on_simulation_start(subset)
    assert eco.restore_organization_economy(subset, 1)
    eco.checkpoint_organization_economy(subset, 2)
    restored = {"config": context["config"], "agents": [_build_agent(1)], "extension_state": {}, "day": 3}
    eco.on_simulation_start(restored)
    assert eco.restore_organization_economy(restored, 2)
    assert eco.get_organization_receipt(restored, restored["agents"][0], "wage")["paid_cents"] == 200


def test_enabled_audit_has_organization_subtotal_off_audit_unchanged(tmp_path):
    _agent, context = economy(tmp_path)
    eco.register_organization_account(context, "firm", 0)
    eco.organization_fund(context, "firm", 1000, "government", "fund")
    eco.on_day_end(context)
    eco.on_simulation_end(context)
    path = tmp_path / "economy" / "conservation_audit.csv"
    with path.open(encoding="utf-8") as handle:
        assert float(next(csv.DictReader(handle))["organizations_total"]) == 10
    context["config"]["organizations"]["enabled"] = False
    context["extension_state"] = {}
    eco.on_simulation_start(context)
    eco.on_day_end(context)
    eco.on_simulation_end(context)
    with path.open(encoding="utf-8") as handle:
        assert "organizations_total" not in next(csv.DictReader(handle))


class FinitePayroll:
    """Test collaborator using the real public transfer and finite account."""

    def __init__(self):
        self.categories = []

    def pay_wage(self, agent, amount, context, category):
        self.categories.append(category)
        purpose = {"housing_fund": "housing_fund", "year_bonus": "bonus"}.get(category, "wage")
        receipt = eco.organization_transfer(
            context, "firm", agent, round(amount * 100), f"{category}-{len(self.categories)}", purpose
        )
        return receipt["paid_cents"] / 100


def test_existing_leave_and_coarse_wages_use_finite_payroll(tmp_path):
    agent, context = economy(tmp_path)
    eco.register_organization_account(context, "firm", 0)
    eco.organization_fund(context, "firm", 100, "firms", "fund")
    service = FinitePayroll()
    context["organization_service"] = service
    firms = eco._economy_state(context)["sectors"]["firms"]
    leave = eco.credit_paid_leave(agent, context, day=1)
    assert leave["pay"] == 1
    assert leave["unpaid"] > 0
    assert agent["economy"]["month_gross_income"] == 1
    context["day"] = 2
    agent["economy"]["daily_income"] = 0
    cfg = eco._get_cfg(context)
    paid = eco._accrue_coarse_income(
        agent["economy"], cfg, 1, eco._economy_state(context)["sectors"], agent=agent, context=context
    )
    assert paid == 0
    assert service.categories == ["paid_leave", "coarse_wage"]
    assert eco._economy_state(context)["sectors"]["firms"] == firms


def test_native_tick_monthly_match_and_bonus_are_routed(tmp_path):
    agent, context = economy(tmp_path)
    eco.register_organization_account(context, "firm", 0)
    eco.organization_fund(context, "firm", 10000000, "firms", "fund")
    service = FinitePayroll()
    context["organization_service"] = service
    context.update(agent=agent, step={"activity": "工作", "action": "工作", "location": ""}, time_str="09:00")
    before = total(context)
    eco.on_agent_post_step(context)
    assert service.categories == ["wage"]
    assert total(context) == before
    runtime = eco._economy_state(context)
    runtime["sim_day_counter"] = 360
    runtime["sim_month_counter"] = 11
    eco.on_day_end(context)
    assert "housing_fund" in service.categories
    assert "year_bonus" in service.categories
    assert total(context) == before
