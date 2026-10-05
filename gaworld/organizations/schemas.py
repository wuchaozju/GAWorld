"""Strict command and money validation shared by simulation, API and CLI."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from typing import Any

from gaworld.economy.organization_accounts import MAX_CENTS

RULES = {"community": {"equal_split", "need_first"}, "company": {"lottery", "skill_first"}}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
COMMAND_FIELDS = {
    "create": {
        "name",
        "kind",
        "goal",
        "leader_id",
        "member_ids",
        "initial_balance_cents",
        "funding_source",
        "rule",
        "rule_params",
        "decision_interval",
        "seed",
        "governance",
    },
    "add_member": {"agent_id", "role", "reason"},
    "remove_member": {"agent_id", "reason"},
    "handover": {"leader_id"},
    "fund": {"amount_cents", "source"},
    "apply_aid": {"agent_id", "amount_cents", "reason", "request_id"},
    "publish_job": {
        "job_id",
        "occupation",
        "vacancies",
        "monthly_salary_cents",
        "min_income_skill",
        "location",
    },
    "apply_job": {"agent_id", "job_id", "reason", "request_id"},
    "set_rule": {"rule", "rule_params"},
    "set_governance": {"governance"},
    "propose_rule": {"agent_id", "proposal_id", "rule", "rule_params", "title", "reason"},
    "cast_vote": {"agent_id", "proposal_id", "choice", "reason"},
    "leader_decide": {"agent_id", "proposal_id", "choice", "reason"},
    "update_profile": {"name", "goal"},
    "close": {"reason"},
}
REQUIRED_FIELDS = {
    "create": {"name", "kind", "leader_id"},
    "add_member": {"agent_id"},
    "remove_member": {"agent_id"},
    "handover": {"leader_id"},
    "fund": {"amount_cents"},
    "apply_aid": {"agent_id", "amount_cents"},
    "publish_job": {"occupation", "vacancies", "monthly_salary_cents"},
    "apply_job": {"agent_id", "job_id"},
    "set_rule": {"rule"},
    "set_governance": {"governance"},
    "propose_rule": {"agent_id", "rule"},
    "cast_vote": {"agent_id", "proposal_id", "choice"},
    "leader_decide": {"agent_id", "proposal_id", "choice"},
    "update_profile": set(),
    "close": set(),
}


class OrganizationValidationError(ValueError):
    """A command or persisted organization cannot be interpreted safely."""


def now() -> str:
    return datetime.now(UTC).isoformat()


def cents(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_CENTS:
        raise OrganizationValidationError("amount must be nonnegative integer cents within bounds")
    return value


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise OrganizationValidationError("invalid organization, job, request or command identifier")
    return value


def positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10**9:
        raise OrganizationValidationError(f"{name} must be a positive integer")
    return value


def validate_rule(kind: str, rule: str, params: Any) -> dict:
    if rule not in RULES.get(kind, set()):
        raise OrganizationValidationError(f"rule {rule!r} is invalid for {kind}")
    if not isinstance(params, dict):
        raise OrganizationValidationError("rule_params must be an object")
    allowed = {"max_award_cents", "min_age", "members_only"} if kind == "community" else set()
    if set(params) - allowed:
        raise OrganizationValidationError("unknown rule parameter")
    if "max_award_cents" in params:
        cents(params["max_award_cents"])
    if "min_age" in params and (type(params["min_age"]) is not int or not 0 <= params["min_age"] <= 150):
        raise OrganizationValidationError("min_age must be an integer between 0 and 150")
    if "members_only" in params and not isinstance(params["members_only"], bool):
        raise OrganizationValidationError("members_only must be boolean")
    return dict(params)


def validate_command(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise OrganizationValidationError("command must be an object")
    row = dict(payload)
    kind = row.get("type")
    if kind not in COMMAND_FIELDS:
        raise OrganizationValidationError("unknown command type")
    common = {"type", "organization_id", "command_id"}
    if set(row) - common - COMMAND_FIELDS[kind]:
        raise OrganizationValidationError("unknown command fields")
    missing = REQUIRED_FIELDS[kind] - row.keys()
    if missing:
        raise OrganizationValidationError(f"missing fields: {', '.join(sorted(missing))}")
    identifier(row.get("organization_id"))
    for field in ("command_id", "job_id", "request_id", "proposal_id"):
        if field in row:
            identifier(row[field])
    for field in ("amount_cents", "initial_balance_cents", "monthly_salary_cents"):
        if field in row:
            cents(row[field])
    for field in ("agent_id", "leader_id", "vacancies", "decision_interval"):
        if field in row:
            positive_int(row[field], field)
    for field in ("reason", "name", "goal", "occupation", "location", "role", "title"):
        if field in row and (not isinstance(row[field], str) or len(row[field]) > 2000):
            raise OrganizationValidationError(f"{field} must be a bounded string")
    for field in ("source", "funding_source"):
        if field in row and row[field] not in {"government", "firms"}:
            raise OrganizationValidationError("funding source must be government or firms")
    if "min_income_skill" in row:
        value = row["min_income_skill"]
        if (
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise OrganizationValidationError("min_income_skill must be finite between 0 and 1")
    if kind == "create":
        if row["kind"] not in RULES:
            raise OrganizationValidationError("kind must be community or company")
        if not row["name"].strip():
            raise OrganizationValidationError("name cannot be empty")
        members = row.get("member_ids", [])
        if not isinstance(members, list) or len(members) > 100000:
            raise OrganizationValidationError("member_ids must be a bounded list")
        for number in members:
            positive_int(number, "member_id")
        rule = row.get("rule", "equal_split" if row["kind"] == "community" else "lottery")
        validate_rule(row["kind"], rule, row.get("rule_params", {}))
        if "seed" in row and (type(row["seed"]) is not int or abs(row["seed"]) > 2**63 - 1):
            raise OrganizationValidationError("seed must be a bounded integer")
    if kind in {"set_rule", "propose_rule"}:
        if not isinstance(row["rule"], str):
            raise OrganizationValidationError("rule must be a registered string")
        rule_kind = next((k for k, values in RULES.items() if row["rule"] in values), "")
        validate_rule(rule_kind, row["rule"], row.get("rule_params", {}))
        if kind == "propose_rule" and set(row.get("rule_params", {})) - {"max_award_cents"}:
            raise OrganizationValidationError("proposals may change only the rule and aid cap")
    if "governance" in row:
        from gaworld.organizations.governance import validate_policy

        row["governance"] = validate_policy(row["governance"])
    if kind in {"cast_vote", "leader_decide"}:
        choices = {"yes", "no", "abstain"} if kind == "cast_vote" else {"yes", "no"}
        if not isinstance(row["choice"], str) or row["choice"] not in choices:
            raise OrganizationValidationError("invalid ballot choice")
    if kind == "update_profile":
        if not {"name", "goal"} & row.keys():
            raise OrganizationValidationError("update_profile requires name and/or goal")
        if "name" in row:
            row["name"] = row["name"].strip()
            if not row["name"]:
                raise OrganizationValidationError("name cannot be empty")
    return row


def identity_fingerprint(agent: dict) -> str:
    """Use immutable identity columns; job, balances and age evolve during a run."""
    identity = {key: str(agent.get(key, "")) for key in ("id", "name", "gender", "birth_date")}
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
