"""Finite organization counterparties and durable economic payment receipts.

The economy sector map owns live balances. Organization storage records their
projection and obligations; it must reconcile it with these receipts on resume.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

MAX_CENTS = 10**14


def cents(value):
    if type(value) is not int or not 0 <= value <= MAX_CENTS:
        raise ValueError("amount must be an integer number of cents between 0 and 10^14")
    return value


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _runtime(context):
    from gaworld.economy import finance

    runtime = finance._economy_state(context)
    if not runtime.get("enabled") or not isinstance(runtime.get("sectors"), dict):
        raise ValueError("organization payments require an initialized economy")
    return runtime


def _key(organization_id):
    value = str(organization_id)
    if not value or len(value) > 128 or any(c in value for c in "/\\\x00"):
        raise ValueError("invalid organization id")
    return "organization:" + value


def _lock(runtime):
    return runtime.setdefault("_organization_lock", threading.RLock())


def register_organization_account(context, organization_id, balance_cents=0):
    from gaworld.economy import finance

    balance = cents(balance_cents) / 100
    runtime = _runtime(context)
    key = _key(organization_id)
    with _lock(runtime):
        if key in runtime["sectors"]:
            if round(runtime["sectors"][key] * 100) != balance_cents:
                raise ValueError("recovery_required: organization account disagrees with persisted balance")
            return
        runtime["sectors"][key] = balance
        # Registering restored money establishes this run's baseline. Fresh
        # organizations register zero, then receive a conserving funding flow.
        runtime["initial_system_total"] = finance._system_total(context.get("agents", []), runtime["sectors"])


def organization_fund(context, organization_id, amount_cents, source, transaction_id):
    amount = cents(amount_cents)
    if source not in ("government", "firms"):
        raise ValueError("funding source must be government or firms")
    if not isinstance(transaction_id, str) or not transaction_id:
        raise ValueError("transaction id is required")
    runtime = _runtime(context)
    key = _key(organization_id)
    with _lock(runtime):
        if key not in runtime["sectors"]:
            raise ValueError("organization account is not registered")
        receipts = runtime.setdefault("organization_funding_receipts", {})
        prior = receipts.get(transaction_id)
        if prior:
            if (prior["organization_id"], prior["requested_cents"], prior["source"]) != (
                str(organization_id),
                amount,
                source,
            ):
                raise ValueError("funding receipt conflicts with transaction")
            return dict(prior)
        balance = round(runtime["sectors"][key] * 100)
        if balance + amount > MAX_CENTS:
            raise ValueError("organization balance exceeds supported amount")
        runtime["sectors"][source] = round(runtime["sectors"][source] - amount / 100, 2)
        runtime["sectors"][key] = (balance + amount) / 100
        receipt = {
            "transaction_id": transaction_id,
            "organization_id": str(organization_id),
            "requested_cents": amount,
            "paid_cents": amount,
            "unpaid_cents": 0,
            "source": source,
            "balance_after_cents": balance + amount,
            "purpose": "funding",
        }
        receipts[transaction_id] = receipt
        return dict(receipt)


def get_organization_receipt(context, agent, transaction_id):
    receipt = agent.get("economy", {}).get("_organization_receipts", {}).get(transaction_id)
    return dict(receipt) if isinstance(receipt, dict) else None


def organization_account_balance(context, organization_id):
    return round(_runtime(context)["sectors"][_key(organization_id)] * 100)


def get_organization_funding_receipt(context, transaction_id):
    receipt = _runtime(context).get("organization_funding_receipts", {}).get(transaction_id)
    return dict(receipt) if isinstance(receipt, dict) else None


def organization_transfer(
    context,
    organization_id,
    agent,
    amount_cents,
    transaction_id,
    purpose,
    *,
    max_paid_cents=None,
    is_arrears=False,
):
    """Transfer once, then save recipient accounts and receipt in one JSON file.

    wage includes its labor tax base; aid is a transfer; bonus carries its
    existing 15% withholding; housing_fund is an employer contribution.
    Arrears retain their period classification so coarse wages can still accrue.
    """
    from gaworld.economy import finance

    amount = cents(amount_cents)
    if type(is_arrears) is not bool:
        raise ValueError("is_arrears must be a boolean")
    limit = cents(max_paid_cents) if max_paid_cents is not None else amount
    if purpose not in ("aid", "wage", "bonus", "housing_fund"):
        raise ValueError("invalid organization payment purpose")
    if not isinstance(transaction_id, str) or not transaction_id:
        raise ValueError("transaction id is required")
    econ = agent.get("economy")
    if not isinstance(econ, dict) or not isinstance(econ.get("accounts"), dict):
        raise ValueError("recipient has no initialized economic account")
    runtime = _runtime(context)
    key = _key(organization_id)
    with _lock(runtime):
        prior = get_organization_receipt(context, agent, transaction_id)
        if prior:
            signature = (str(organization_id), agent["id"], amount, purpose)
            if (
                prior["organization_id"],
                prior["agent_id"],
                prior["requested_cents"],
                prior["purpose"],
            ) != signature:
                raise ValueError("payment receipt conflicts with transaction")
            if prior.get("is_arrears", False) != is_arrears:
                raise ValueError("payment receipt conflicts with obligation period")
            return prior
        if key not in runtime["sectors"]:
            raise ValueError("organization account is not registered")
        balance = round(runtime["sectors"][key] * 100)
        if balance < 0:
            raise ValueError("recovery_required: negative organization balance")
        paid = min(amount, balance, limit)
        tax = round(paid * 0.15) if purpose == "bonus" else 0
        credited = paid - tax
        target = "housing_fund" if purpose == "housing_fund" else "checking"
        econ["accounts"][target] = round(float(econ["accounts"].get(target, 0)) + credited / 100, 2)
        runtime["sectors"][key] = (balance - paid) / 100
        if tax:
            runtime["sectors"]["government"] = round(runtime["sectors"]["government"] + tax / 100, 2)
        if purpose in ("wage", "bonus"):
            econ["daily_income"] = round(float(econ.get("daily_income", 0)) + credited / 100, 2)
            econ["lifetime_income"] = round(float(econ.get("lifetime_income", 0)) + credited / 100, 2)
            day = int(context.get("day", 0))
            if is_arrears:
                earlier = econ.get("_organization_arrears_income", {})
                income = earlier.get("amount", 0) if earlier.get("day") == day else 0
                econ["_organization_arrears_income"] = {
                    "day": day,
                    "amount": round(income + credited / 100, 2),
                }
            elif amount > 0:
                # An unpaid current wage/leave is already an obligation; coarse
                # accrual must not create another one just because cash is zero.
                econ["_organization_current_wage_day"] = day
        if purpose == "wage":
            econ["month_gross_income"] = round(float(econ.get("month_gross_income", 0)) + paid / 100, 2)
        finance._sync_balance(econ)
        receipt = {
            "transaction_id": transaction_id,
            "organization_id": str(organization_id),
            "agent_id": agent["id"],
            "purpose": purpose,
            "is_arrears": is_arrears,
            "requested_cents": amount,
            "paid_cents": paid,
            "unpaid_cents": amount - paid,
            "credited_cents": credited,
            "tax_cents": tax,
            "balance_after_cents": balance - paid,
            "day": int(context.get("day", 0)),
            "time_str": str(context.get("time_str", "")),
        }
        econ.setdefault("_organization_receipts", {})[transaction_id] = receipt
        # The previous day checkpoint is invalid as soon as a live transfer
        # occurs. A crash cannot reuse it to silently roll back one side.
        econ["_organization_checkpoint_day"] = None
        finance._save_agent_economy(context, agent, finance._get_cfg(context))
        return dict(receipt)


def _checkpoint_path(context):
    return Path(context.get("config", {}).get("memory_dir", "output/memory")) / "organization_economy.json"


def checkpoint_organization_economy(context, day):
    from gaworld.economy import finance

    if not finance._is_stateful(context):
        return
    runtime = _runtime(context)
    accounts = dict(runtime.get("organization_checkpoint_accounts", {}))
    recipient_days = dict(runtime.get("organization_checkpoint_recipient_days", {}))
    for agent in context.get("agents", []):
        econ = agent.get("economy")
        if not isinstance(econ, dict):
            continue
        econ["_organization_checkpoint_day"] = int(day)
        finance._save_agent_economy(context, agent, finance._get_cfg(context))
        accounts[str(agent["id"])] = dict(econ["accounts"])
        recipient_days[str(agent["id"])] = int(day)
    runtime["organization_checkpoint_accounts"] = accounts
    runtime["organization_checkpoint_recipient_days"] = recipient_days
    atomic_json(
        _checkpoint_path(context),
        {
            "day": int(day),
            "sectors": runtime["sectors"],
            "accounts": accounts,
            "recipient_days": recipient_days,
            "funding_receipts": runtime.get("organization_funding_receipts", {}),
            "macro": runtime.get("macro", {}),
            "sim_day_counter": runtime.get("sim_day_counter", 0),
            "sim_month_counter": runtime.get("sim_month_counter", 0),
            "initial_system_total": runtime.get("initial_system_total"),
        },
    )


def restore_organization_economy(context, expected_day):
    from gaworld.economy import finance

    if not finance._is_stateful(context) or not expected_day:
        return False
    path = _checkpoint_path(context)
    try:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        if checkpoint["day"] != expected_day:
            raise ValueError("checkpoint day does not match organization day")
        sectors = checkpoint["sectors"]
        if not isinstance(sectors, dict) or not {"firms", "government", "bank"} <= sectors.keys():
            raise ValueError("missing sector balances")
        for key, balance in sectors.items():
            if not isinstance(balance, (int, float)) or not (-MAX_CENTS <= balance * 100 <= MAX_CENTS):
                raise ValueError("invalid sector balance")
            if key.startswith("organization:") and balance < 0:
                raise ValueError("negative organization balance")
        for agent in context.get("agents", []):
            econ = agent.get("economy")
            if not isinstance(econ, dict):
                continue
            agent_id = str(agent["id"])
            recorded = checkpoint["accounts"].get(agent_id)
            if recorded is None:
                if "_organization_checkpoint_day" in econ or econ.get("_organization_receipts"):
                    raise ValueError("untracked recipient has existing organization history")
                # A newly activated resident has no past organization flows;
                # its initial assets join this run's measured money stock.
                continue
            expected_recipient_day = checkpoint.get("recipient_days", {}).get(agent_id, expected_day)
            if econ.get("_organization_checkpoint_day") != expected_recipient_day:
                raise ValueError("recipient checkpoint day mismatch")
            if econ.get("accounts") != recorded:
                raise ValueError("recipient accounts do not match checkpoint")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"recovery_required: cannot reconcile organization economy: {exc}") from exc
    runtime = _runtime(context)
    runtime["sectors"] = sectors
    runtime["organization_funding_receipts"] = checkpoint.get("funding_receipts", {})
    runtime["organization_checkpoint_accounts"] = checkpoint["accounts"]
    runtime["organization_checkpoint_recipient_days"] = checkpoint.get("recipient_days", {})
    for name in ("macro", "sim_day_counter", "sim_month_counter"):
        runtime[name] = checkpoint[name]
    runtime["initial_system_total"] = finance._system_total(context.get("agents", []), sectors)
    return True
