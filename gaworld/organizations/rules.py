"""Pure frozen-batch decisions; tie breaks never consume the simulation RNG."""

from __future__ import annotations

import hashlib


def tie_key(organization, batch_id, application):
    token = f"{organization['seed']}:{organization['organization_id']}:{batch_id}:{application['agent_id']}:{application['application_id']}"
    return hashlib.sha256(token.encode()).hexdigest()


def community_plan(organization, applications, snapshots, members, budget, batch_id):
    params = organization["rule_params"]
    plan, eligible, seen = [], [], set()
    for app in applications:
        snap = snapshots.get(app["agent_id"], {})
        reason = ""
        if not snap.get("active"):
            reason = "inactive_resident"
        elif params.get("members_only", True) and app["agent_id"] not in members:
            reason = "not_member"
        elif snap.get("age") is None:
            reason = "age_missing"
        elif snap["age"] < params.get("min_age", 18):
            reason = "under_age"
        elif not snap.get("has_economic_account"):
            reason = "economic_account_missing"
        elif app["agent_id"] in seen:
            reason = "duplicate_batch_application"
        elif organization["rule"] == "need_first" and snap.get("cash_cents") is None:
            reason = "cash_missing"
        seen.add(app["agent_id"])
        row = {
            "application_id": app["application_id"],
            "agent_id": app["agent_id"],
            "amount_cents": 0,
            "eligible": not reason,
            "reason": reason,
            "frozen": snap,
            "rule": organization["rule"],
            "rule_version": organization["rule_version"],
        }
        plan.append(row)
        if not reason:
            row["cap"] = min(app["amount_cents"], params.get("max_award_cents", app["amount_cents"]))
            eligible.append(row)
    ordered = sorted(eligible, key=lambda r: tie_key(organization, batch_id, r))
    if organization["rule"] == "need_first":
        ordered.sort(key=lambda r: (r["frozen"]["cash_cents"], -r["frozen"].get("dependants", 0)))
        for row in ordered:
            row["amount_cents"] = min(budget, row["cap"])
            budget -= row["amount_cents"]
    else:
        remaining = list(ordered)
        while remaining and budget:
            share, extra = divmod(budget, len(remaining))
            used = 0
            for index, row in enumerate(remaining):
                addition = min(row["cap"] - row["amount_cents"], share + (index < extra))
                row["amount_cents"] += addition
                used += addition
            budget -= used
            remaining = [r for r in remaining if r["amount_cents"] < r["cap"]]
            if not used:
                break
    for row in eligible:
        row.pop("cap")
        row["reason"] = "approved" if row["amount_cents"] else "budget_exhausted"
    return plan


def hiring_plan(organization, job, applications, snapshots, employers, batch_id):
    plan, eligible, seen = [], [], set()
    vacancies = job["vacancies"] - job["occupied"]
    for app in applications:
        snap = snapshots.get(app["agent_id"], {})
        reason = ""
        if not snap.get("active"):
            reason = "inactive_resident"
        elif not snap.get("has_economic_account"):
            reason = "economic_account_missing"
        elif snap.get("income_skill") is None:
            reason = "income_skill_missing"
        elif snap["income_skill"] < job["min_income_skill"]:
            reason = "qualification_not_met"
        elif snap.get("age") is None or snap["age"] < 18:
            reason = "under_age_or_age_missing"
        elif employers.get(app["agent_id"]) == organization["organization_id"]:
            reason = "already_employed_by_organization"
        elif app["agent_id"] in employers and snap.get("employer_id") != employers[app["agent_id"]]:
            reason = "already_hired_this_batch"
        elif app["agent_id"] in seen:
            reason = "duplicate_batch_application"
        elif organization["balance_cents"] <= organization["arrears_cents"]:
            reason = "employer_budget_exhausted"
        seen.add(app["agent_id"])
        row = {
            "application_id": app["application_id"],
            "agent_id": app["agent_id"],
            "eligible": not reason,
            "hired": False,
            "reason": reason,
            "frozen": snap,
            "rule": organization["rule"],
            "rule_version": organization["rule_version"],
        }
        plan.append(row)
        if not reason:
            eligible.append(row)
    ordered = sorted(eligible, key=lambda r: tie_key(organization, batch_id, r))
    if organization["rule"] == "skill_first":
        ordered.sort(key=lambda r: -r["frozen"]["income_skill"])
    for index, row in enumerate(ordered):
        row["hired"] = index < vacancies
        row["reason"] = "hired" if row["hired"] else "vacancy_filled"
    return plan
