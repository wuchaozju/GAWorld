"""Household money: dependants cost, and a couple's balance sheets are joint.

The existing economy models one agent as one balance sheet. That is exactly
wrong for a family: a parent's disposable income is not their salary minus
their own consumption, it is what is left after the children, and a
married couple does not go into hardship one at a time.

Two mechanisms, both **conserving** — this repo's currency system tracks
every yuan, so nothing here creates or destroys money:

* :func:`charge_dependants` bills the household's earners for children and
  elders through the economy's own expense path, so the money lands in the
  firms pool like any other consumption.
* :func:`settle_couple` moves cash *between two in-sim agents' accounts*
  when one is short and the other is liquid. Pure transfer, sum unchanged.
"""

from __future__ import annotations

from typing import Any

from gaworld.family.duties import care_load
from gaworld.family.schema import family_config

DAYS_PER_MONTH = 30.0


def _econ(agent: dict[str, Any]) -> dict[str, Any] | None:
    econ = agent.get("economy") if isinstance(agent, dict) else None
    return econ if isinstance(econ, dict) else None


def _checking(econ: dict[str, Any]) -> float:
    accounts = econ.get("accounts")
    if not isinstance(accounts, dict):
        return 0.0
    try:
        return float(accounts.get("checking", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def dependant_cost_monthly(
    records: dict[str, Any] | list[dict[str, Any]] | None,
    config: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Monthly household cost of dependants, broken out by kind.

    Accepts one record or all the records of a household's in-sim agents.
    The split matters: a married couple *shares* children and a co-resident
    grandparent (both records list the same ghosts, so counting them twice
    would double the school fees), but each partner supports **their own**
    parents elsewhere, so those are summed across records.
    """
    if not records:
        return {}
    if isinstance(records, dict):
        records = [records]
    records = [r for r in records if r]
    if not records:
        return {}
    cfg = family_config(config)
    fin = cfg.get("finance", {})
    duties = cfg.get("duties", {})
    preschool_max = int(duties.get("preschool_age_max", 6))
    coresident_child_max = int(cfg.get("fertility", {}).get("coresident_child_max_age", 22))
    support_age = int(fin.get("elder_support_min_age", 65))

    children = 0
    preschool = 0
    coresident_elders = 0
    for member in records[0].get("members", []) or []:
        role = member.get("role")
        age = int(member.get("age", 0) or 0)
        if role == "child" and member.get("coresident") and age <= coresident_child_max:
            children += 1
            if age <= preschool_max:
                preschool += 1
        elif role in ("father", "mother", "parent") and member.get("coresident"):
            coresident_elders += 1

    remote_parents = 0
    for record in records:
        for member in record.get("members", []) or []:
            if (
                member.get("role") in ("father", "mother", "parent")
                and not member.get("coresident")
                and int(member.get("age", 0) or 0) >= support_age
            ):
                remote_parents += 1

    costs = {
        "children": children * float(fin.get("child_cost_monthly", 2200.0)),
        "preschool": preschool * float(fin.get("preschool_extra_monthly", 1500.0)),
        "coresident_elders": coresident_elders * float(fin.get("coresident_elder_monthly", 600.0)),
        "elder_support": remote_parents * float(fin.get("elder_support_monthly", 900.0)),
    }
    return {k: round(v, 2) for k, v in costs.items() if v > 0}


def charge_dependants(
    members_of_household: list[dict[str, Any]],
    record: dict[str, Any] | list[dict[str, Any]] | None,
    *,
    charge_fn,
    config: dict[str, Any] | None = None,
) -> float:
    """Bill one day of dependant cost, split across the household's earners.

    ``charge_fn(agent, category, amount)`` performs the actual (conserving)
    debit — injected so this module never imports the economy internals.
    Splitting is proportional to each earner's *income*, not their balance:
    a household where one partner earns twice as much carries the cost that
    way, and a non-earning partner is not billed at all.
    """
    if not record or not members_of_household:
        return 0.0
    monthly = dependant_cost_monthly(record, config)
    total_daily = sum(monthly.values()) / DAYS_PER_MONTH
    if total_daily <= 0:
        return 0.0

    earners = []
    for agent in members_of_household:
        econ = _econ(agent)
        if econ is None:
            continue
        try:
            income = float(econ.get("net_monthly_salary", 0) or 0)
        except (TypeError, ValueError):
            income = 0.0
        earners.append((agent, max(0.0, income)))
    if not earners:
        return 0.0
    total_income = sum(income for _, income in earners)
    if total_income <= 0:
        # Nobody earns: split evenly so the cost still bites (savings drain).
        weights = [(agent, 1.0 / len(earners)) for agent, _ in earners]
    else:
        weights = [(agent, income / total_income) for agent, income in earners]

    # Childcare/schooling is education; elder care is healthcare. Using the
    # economy's own categories keeps the family bill visible in the existing
    # expense breakdown instead of hiding in `misc`.
    education_daily = (monthly.get("children", 0.0) + monthly.get("preschool", 0.0)) / DAYS_PER_MONTH
    care_daily = (
        monthly.get("coresident_elders", 0.0) + monthly.get("elder_support", 0.0)
    ) / DAYS_PER_MONTH

    charged = 0.0
    for agent, weight in weights:
        for category, amount in (("education", education_daily), ("healthcare", care_daily)):
            value = round(amount * weight, 2)
            if value <= 0:
                continue
            charge_fn(agent, category, value)
            charged += value
    return round(charged, 2)


def settle_couple(
    left: dict[str, Any],
    right: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> float:
    """Move cash from the liquid partner to the short one. Returns the amount.

    Pooling is not "merge both accounts": partners in this model keep
    separate balances and top each other up, which is both closer to how
    Chinese urban couples actually run their money and far less disruptive
    to the rest of the economy module.
    """
    cfg = family_config(config).get("finance", {})
    if not cfg.get("spouse_bailout_enabled", True):
        return 0.0
    left_econ, right_econ = _econ(left), _econ(right)
    if left_econ is None or right_econ is None:
        return 0.0

    pooling = max(0.0, min(1.0, float(cfg.get("pooling_rate", 0.65))))
    for short_econ, rich_econ in ((left_econ, right_econ), (right_econ, left_econ)):
        try:
            buffer = float(short_econ.get("monthly_expense_estimate", 0) or 0) * 0.5
        except (TypeError, ValueError):
            buffer = 0.0
        deficit = buffer - _checking(short_econ)
        if deficit <= 0:
            continue
        rich_buffer = 0.0
        try:
            rich_buffer = float(rich_econ.get("monthly_expense_estimate", 0) or 0) * 0.5
        except (TypeError, ValueError):
            pass
        spare = max(0.0, _checking(rich_econ) - rich_buffer) * pooling
        transfer = round(min(deficit, spare), 2)
        if transfer <= 0:
            continue
        rich_econ["accounts"]["checking"] = round(_checking(rich_econ) - transfer, 2)
        short_econ["accounts"]["checking"] = round(_checking(short_econ) + transfer, 2)
        short_econ["family_received"] = round(
            float(short_econ.get("family_received", 0) or 0) + transfer, 2
        )
        rich_econ["family_given"] = round(
            float(rich_econ.get("family_given", 0) or 0) + transfer, 2
        )
        return transfer
    return 0.0


def household_state_effects(
    record: dict[str, Any] | None,
    *,
    partner_earns: bool,
    config: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Daily state deltas from the household's economics.

    A second earner buys security; carrying dependants alone costs calm.
    Both are small per-day nudges — the point is a persistent tilt over
    hundreds of days, not a shock.
    """
    if not record:
        return {}
    cfg = family_config(config).get("finance", {})
    load = care_load(record, config)
    effects: dict[str, float] = {}
    if partner_earns:
        effects["econ_security"] = float(cfg.get("dual_income_security_bonus", 0.004))
    if load > 0 and not partner_earns:
        effects["stress"] = float(cfg.get("sole_earner_stress", 0.003)) * (0.5 + load)
    return effects
