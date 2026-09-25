"""Read-only ``/api/economy/*``: the money system after (or during) a run.

Macro state, sector pools, conservation audit and the city ledger were already
computed for the External Systems panel; ``overview`` re-serves that payload
under the economy namespace rather than duplicating it. What was missing is the
agent-to-agent layer: friend loans (``friend_debts`` / ``friend_credits`` in
each agent's snapshot) and each agent's own ledger series.

Changes to the economy go through the existing day-scheduled queue
(``POST /api/external-systems/interventions``).
"""

from __future__ import annotations

import csv
import glob
import json
import os
from typing import Any

#: Borrower-side and lender-side records of one loan may differ by rounding.
_LEDGER_TOL = 0.05


def _agents_dir() -> str:
    from gaworld.apps import external_systems_api

    return os.path.join(external_systems_api._economy_dir(), "agents")


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _first(query: dict, key: str) -> str:
    return str((query.get(key) or [""])[0]).strip()


def _snapshots() -> dict[str, dict[str, Any]]:
    out = {}
    for path in glob.glob(os.path.join(_agents_dir(), "agent_*_snapshot.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("economy"), dict):
            out[str(data.get("agent_id"))] = data
    return out


def loans_payload() -> dict[str, Any]:
    """Friend-loan graph plus bank debt, with a two-sided consistency check.

    Every loan is booked twice (borrower's ``friend_debts`` and lender's
    ``friend_credits``). A pair that does not match means money was created or
    lost in the plumbing, so mismatches are reported, not smoothed over.
    """
    snaps = _snapshots()
    names = {aid: s.get("name", "") for aid, s in snaps.items()}
    debts: dict[tuple[str, str], float] = {}
    credits: dict[tuple[str, str], float] = {}
    bank = []
    for aid, snap in snaps.items():
        econ = snap["economy"]
        for lender, amount in (econ.get("friend_debts") or {}).items():
            debts[(aid, str(lender))] = _num(amount)
        for borrower, amount in (econ.get("friend_credits") or {}).items():
            credits[(str(borrower), aid)] = _num(amount)
        if _num(econ.get("debt")) > 0:
            bank.append({"agent_id": aid, "name": names.get(aid, ""), "debt": round(_num(econ.get("debt")), 2)})
    edges, mismatches = [], []
    for key in sorted(set(debts) | set(credits)):
        borrower, lender = key
        owed, held = debts.get(key, 0.0), credits.get(key, 0.0)
        if abs(owed - held) > _LEDGER_TOL:
            mismatches.append({"borrower": borrower, "lender": lender,
                               "borrower_records": round(owed, 2), "lender_records": round(held, 2)})
        amount = round(max(owed, held), 2)
        if amount > 0:
            edges.append({"borrower": borrower, "borrower_name": names.get(borrower, ""),
                          "lender": lender, "lender_name": names.get(lender, ""), "amount": amount})
    bank.sort(key=lambda r: -r["debt"])
    return {
        "agents": len(snaps),
        "friend_loans": edges,
        "friend_loans_total": round(sum(e["amount"] for e in edges), 2),
        "bank_debt": bank,
        "bank_debt_total": round(sum(r["debt"] for r in bank), 2),
        "consistent": not mismatches,
        "mismatches": mismatches,
    }


def ledger_payload(query: dict) -> tuple[dict[str, Any], int]:
    agent_id = _first(query, "agent_id")
    if not agent_id.isdigit():
        return {"error": "agent_id (integer) is required"}, 400
    path = os.path.join(_agents_dir(), f"agent_{agent_id}_ledger.csv")
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return {"error": f"no ledger for agent {agent_id} (has a run with the economy enabled finished?)"}, 404
    raw_limit = _first(query, "limit")
    if raw_limit:
        if not raw_limit.isdigit() or int(raw_limit) < 1:
            return {"error": "limit must be a positive integer"}, 400
        rows = rows[-int(raw_limit):]
    parsed = [{k: (v if k == "macro_phase" else _num(v)) for k, v in row.items()} for row in rows]
    snap = _snapshots().get(agent_id, {}).get("economy", {})
    return {
        "agent_id": int(agent_id),
        "rows": parsed,
        "friend_debts": snap.get("friend_debts") or {},
        "friend_credits": snap.get("friend_credits") or {},
    }, 200


def handle_get(path: str, query: dict) -> tuple[dict[str, Any], int]:
    route = path.rstrip("/")
    if route == "/api/economy/overview":
        from gaworld.apps import external_systems_api

        return external_systems_api._wire_safe(external_systems_api.currency_runtime()), 200
    if route == "/api/economy/loans":
        return loans_payload(), 200
    if route == "/api/economy/ledger":
        return ledger_payload(query)
    return {"error": "Unknown endpoint"}, 404
