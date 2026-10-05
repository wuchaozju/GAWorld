"""Deterministic governance policy and the persisted proposal lifecycle."""

from __future__ import annotations

import hashlib

from gaworld.organizations.schemas import RULES, OrganizationValidationError, now, validate_rule

GOVERNANCE_COMMANDS = {"set_governance", "propose_rule", "cast_vote", "leader_decide"}
DEFAULT_POLICY = {"mode": "member_vote", "threshold": "quorum_majority", "voting_days": 1}


def validate_policy(value):
    if not isinstance(value, dict) or set(value) - DEFAULT_POLICY.keys():
        raise OrganizationValidationError("invalid governance policy fields")
    policy = {**DEFAULT_POLICY, **value}
    if not isinstance(policy["mode"], str) or policy["mode"] not in {"off", "leader", "member_vote"}:
        raise OrganizationValidationError("invalid governance mode")
    if not isinstance(policy["threshold"], str) or policy["threshold"] not in {
        "quorum_majority",
        "electorate_majority",
        "simple_majority",
    }:
        raise OrganizationValidationError("invalid voting threshold")
    if type(policy["voting_days"]) is not int or not 1 <= policy["voting_days"] <= 365:
        raise OrganizationValidationError("voting_days must be an integer from 1 to 365")
    return policy


def tally(policy, electorate, ballots):
    counts = {choice: sum(b["choice"] == choice for b in ballots) for choice in ("yes", "no", "abstain")}
    eligible, participation = len(electorate), len(ballots)
    quorum = (eligible + 1) // 2
    threshold = policy["threshold"]
    if not participation or (threshold == "quorum_majority" and participation < quorum):
        status, reason = "expired", "participation_insufficient"
    else:
        passed = (
            counts["yes"] > eligible / 2
            if threshold == "electorate_majority"
            else counts["yes"] > counts["no"]
        )
        status, reason = ("approved", "threshold_met") if passed else ("rejected", "threshold_not_met")
    return {
        **counts,
        "participation": participation,
        "eligible": eligible,
        "quorum": quorum,
        "status": status,
        "reason": reason,
    }


class Governance:
    """All governance writes belong to the simulator's existing single writer."""

    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.options = service.options.get("governance", {})
        self.enabled = bool(self.options.get("enabled", False))
        self.default = (
            validate_policy({k: v for k, v in self.options.items() if k != "enabled"})
            if self.enabled
            else dict(DEFAULT_POLICY)
        )

    def initialize(self, org, policy=None):
        if not self.enabled:
            if policy is not None:
                raise OrganizationValidationError("organization governance is disabled")
            return org
        if "governance" not in org:
            org.update(
                governance=validate_policy(policy or self.default),
                governance_version=1,
                leader_version=org.get("leader_version", 1),
            )
            self.store.put("organizations", org["organization_id"], org)
        return org

    def _record(self, proposal, event, day):
        self.store.put("proposals", f"{proposal['organization_id']}:{proposal['proposal_id']}", proposal)
        self.store.add_history(proposal["organization_id"], f"governance_{event}", dict(proposal, day=day))
        self.service._event(f"governance.{event}", dict(proposal, day=day))

    def _conflict(self, proposal):
        org = self.store.get("organizations", proposal["organization_id"])
        if not self.enabled:
            return "governance_disabled"
        if not org or org["status"] != "open":
            return "organization_closed"
        if org["rule_version"] != proposal["base_rule_version"]:
            return "rule_version_changed"
        if org.get("governance_version") != proposal["governance_version"]:
            return "governance_version_changed"
        if proposal["policy"]["mode"] == "leader" and (
            org["leader_id"] != proposal["leader_id"]
            or org.get("leader_version", 1) != proposal["leader_version"]
        ):
            return "leader_changed"
        return None

    def apply(self, command, day):
        if not self.enabled:
            raise OrganizationValidationError("organization governance is disabled")
        if command.get("target_generation_id") not in (None, self.service.generation_id):
            raise OrganizationValidationError("governance command belongs to another generation")
        p = command["payload"]
        org = self.service._organization(p["organization_id"], open_only=True)
        policy = org.get("governance", self.default)
        if p["type"] == "set_governance":
            org.update(
                governance=validate_policy(p["governance"]),
                governance_version=org.get("governance_version", 0) + 1,
                state_version=org["state_version"] + 1,
            )
            self.store.put("organizations", org["organization_id"], org)
            self.service._event("governance.policy", dict(org, day=day))
            return {"governance": org["governance"], "governance_version": org["governance_version"]}
        self.service._person(p["agent_id"])
        if p["type"] == "propose_rule":
            if policy["mode"] == "off":
                raise OrganizationValidationError("organization governance mode is off")
            members = sorted(
                m["agent_id"]
                for m in self.store.rows("members", org["organization_id"])
                if m["left_day"] is None
            )
            if p["agent_id"] not in members:
                raise OrganizationValidationError("proposer must be a current member")
            if any(
                r["status"] in {"open", "approved"}
                for r in self.store.rows("proposals", org["organization_id"])
            ):
                raise OrganizationValidationError("organization already has an unfinished proposal")
            pid = p.get("proposal_id", command["command_id"])
            if self.store.get("proposals", f"{org['organization_id']}:{pid}"):
                raise OrganizationValidationError("proposal_id already exists")
            params = {**org["rule_params"], **p.get("rule_params", {})}
            validate_rule(org["kind"], p["rule"], params)
            if org["rule"] == p["rule"] and org["rule_params"] == params:
                raise OrganizationValidationError("proposal does not change the rule")
            proposal = {
                "organization_id": org["organization_id"],
                "proposal_id": pid,
                "proposer_id": p["agent_id"],
                "title": p.get("title", ""),
                "reason": p.get("reason", ""),
                "actor": command["actor"],
                "created_at": now(),
                "opened_day": day,
                "closing_day": day + policy["voting_days"],
                "status": "open",
                "policy": dict(policy),
                "electorate": members,
                "leader_id": org["leader_id"],
                "leader_version": org.get("leader_version", 1),
                "base_rule_version": org["rule_version"],
                "governance_version": org["governance_version"],
                "before": {"rule": org["rule"], "rule_params": dict(org["rule_params"])},
                "after": {"rule": p["rule"], "rule_params": params},
                "decision_outcome": None,
                "tally": None,
            }
            self._record(proposal, "proposal", day)
            return {"proposal_id": pid, "status": "open", "closing_day": proposal["closing_day"]}
        proposal = self.store.get("proposals", f"{org['organization_id']}:{p['proposal_id']}")
        if not proposal:
            raise OrganizationValidationError("proposal does not exist")
        if proposal["status"] != "open" or day > proposal["closing_day"]:
            raise OrganizationValidationError("proposal voting is closed")
        if self._conflict(proposal):
            raise OrganizationValidationError("proposal authority or rule has changed")
        mode = proposal["policy"]["mode"]
        if (p["type"] == "cast_vote") != (mode == "member_vote"):
            raise OrganizationValidationError("ballot type does not match governance mode")
        voters = proposal["electorate"] if mode == "member_vote" else [proposal["leader_id"]]
        if p["agent_id"] not in voters:
            raise OrganizationValidationError("resident is not eligible for this proposal")
        key = f"{org['organization_id']}:{p['proposal_id']}:{p['agent_id']}"
        old = self.store.get("ballots", key)
        if old:
            if old["choice"] != p["choice"]:
                raise OrganizationValidationError("first ballot is immutable")
            return old
        ballot = {
            "ballot_id": key,
            "organization_id": org["organization_id"],
            "proposal_id": proposal["proposal_id"],
            "agent_id": p["agent_id"],
            "choice": p["choice"],
            "reason": p.get("reason", ""),
            "day": day,
            "actor": command["actor"],
            "command_id": command["command_id"],
            "created_at": now(),
        }
        self.store.put("ballots", key, ballot)
        self.store.add_history(org["organization_id"], "governance_ballot", ballot)
        self.service._event("governance.ballot", ballot)
        return ballot

    def resolve(self, day):
        for proposal in self.store.rows("proposals"):
            if proposal["status"] != "open":
                continue
            conflict = self._conflict(proposal)
            if not conflict and day < proposal["closing_day"]:
                continue
            ballots = [
                b
                for b in self.store.rows("ballots", proposal["organization_id"])
                if b["proposal_id"] == proposal["proposal_id"]
            ]
            if proposal["policy"]["mode"] == "leader":
                choice = ballots[0]["choice"] if ballots else None
                outcome = "approved" if choice == "yes" else ("rejected" if choice else "expired")
                result = {
                    "yes": int(choice == "yes"),
                    "no": int(choice == "no"),
                    "abstain": 0,
                    "eligible": 1,
                    "participation": len(ballots),
                    "quorum": 1,
                    "status": outcome,
                    "reason": "leader_decision" if choice else "leader_did_not_decide",
                }
            else:
                result = tally(proposal["policy"], proposal["electorate"], ballots)
            if conflict:
                result.update(status="invalidated", reason=conflict)
            proposal.update(
                status=result["status"],
                decision_outcome=result["status"],
                resolution_reason=result["reason"],
                tally=result,
                resolved_day=day,
            )
            with self.store.atomic():
                if proposal["status"] == "approved":
                    token = hashlib.sha256(
                        f"{self.service.generation_id}:{proposal['organization_id']}:{proposal['proposal_id']}:execute".encode()
                    ).hexdigest()
                    actor = {
                        "source": "organization_governance",
                        "proposal_id": proposal["proposal_id"],
                        "generation_id": self.service.generation_id,
                    }
                    try:
                        command = self.store.enqueue(
                            {
                                "type": "set_rule",
                                "organization_id": proposal["organization_id"],
                                "command_id": token,
                                **proposal["after"],
                            },
                            actor=actor,
                        )
                    except OrganizationValidationError:
                        command = None
                    if command is None or command["actor"] != actor or command["status"] != "pending":
                        proposal.update(
                            status="execution_failed", execution_reason="execution_command_collision"
                        )
                    else:
                        proposal.update(execution_command_id=token, execute_not_before_day=day + 1)
                self._record(proposal, "resolution", day)

    def execute(self, command, day):
        actor = command["actor"]
        p = command["payload"]
        proposal = self.store.get("proposals", f"{p['organization_id']}:{actor.get('proposal_id')}")
        if not proposal or actor.get("generation_id") != self.service.generation_id:
            raise OrganizationValidationError("governed execution belongs to another generation or proposal")
        if (
            command["command_id"] != proposal.get("execution_command_id")
            or p["rule"] != proposal["after"]["rule"]
            or p.get("rule_params", {}) != proposal["after"]["rule_params"]
        ):
            raise OrganizationValidationError("governed execution does not match the approved proposal")
        if proposal["status"] == "executed":
            return proposal["execution_result"]
        conflict = self._conflict(proposal)
        if proposal["status"] != "approved" or day < proposal["execute_not_before_day"]:
            raise OrganizationValidationError("proposal has no executable resolution for this day")
        if conflict:
            proposal.update(status="execution_failed", execution_reason=conflict, execution_day=day)
            self._record(proposal, "execution", day)
            raise OrganizationValidationError(conflict)
        with self.store.atomic():
            org = self.service._organization(p["organization_id"], open_only=True)
            result = self.service._set_rule(org, command, day)
            proposal.update(
                status="executed",
                execution_day=day,
                execution_rule_version=result["rule_version"],
                execution_result=result,
            )
            self._record(proposal, "execution", day)
        return result

    def candidates(self, agent):
        if not self.enabled or agent["id"] not in self.service.agents:
            return []
        result = []
        pending = [
            c
            for c in self.store.commands()
            if c["status"] == "pending"
            and c.get("target_generation_id") in (None, self.service.generation_id)
        ]
        for org in self.store.list_organizations():
            oid, number = org["organization_id"], agent["id"]
            if org["status"] != "open" or org.get("governance", self.default)["mode"] == "off":
                continue
            unfinished = [p for p in self.store.rows("proposals", oid) if p["status"] in {"open", "approved"}]
            if not unfinished:
                member = self.store.get("members", f"{oid}:{number}")
                if (
                    member
                    and member["left_day"] is None
                    and not any(c["organization_id"] == oid and c["type"] == "propose_rule" for c in pending)
                ):
                    result.extend(
                        f"org:propose_rule:{oid}:{r}" for r in sorted(RULES[org["kind"]]) if r != org["rule"]
                    )
                continue
            proposal = unfinished[0]
            pid = proposal["proposal_id"]
            if (
                proposal["status"] != "open"
                or self.service.day >= proposal["closing_day"]
                or self._conflict(proposal)
            ):
                continue
            leader = proposal["policy"]["mode"] == "leader"
            if number not in ([proposal["leader_id"]] if leader else proposal["electorate"]):
                continue
            if self.store.get("ballots", f"{oid}:{pid}:{number}") or any(
                c["organization_id"] == oid
                and c["type"] in {"cast_vote", "leader_decide"}
                and c["payload"].get("proposal_id") == pid
                and c["payload"].get("agent_id") == number
                for c in pending
            ):
                continue
            verb = "leader_decide" if leader else "cast_vote"
            result.extend(
                f"org:{verb}:{oid}:{pid}:{c}" for c in (["yes", "no"] if leader else ["yes", "no", "abstain"])
            )
        return result

    def export(self, day):
        organizations = []
        for org in self.store.list_organizations():
            proposals = self.store.rows("proposals", org["organization_id"])
            resolved = [p for p in proposals if p["decision_outcome"] is not None]
            member_votes = [p for p in resolved if p["policy"]["mode"] == "member_vote"]
            organizations.append(
                {
                    "organization_id": org["organization_id"],
                    "policy": org.get("governance"),
                    "proposed": len(proposals),
                    "resolved": len(resolved),
                    "approved": sum(p["decision_outcome"] == "approved" for p in resolved),
                    "executed": sum(p["status"] == "executed" for p in proposals),
                    "execution_failed": sum(p["status"] == "execution_failed" for p in proposals),
                    "participation_numerator": sum(p["tally"]["participation"] for p in member_votes),
                    "participation_denominator": sum(p["tally"]["eligible"] for p in member_votes),
                    "proposals": proposals,
                    "ballots": self.store.rows("ballots", org["organization_id"]),
                }
            )
        return {
            "generation_id": self.service.generation_id,
            "day": day,
            "scope": "cumulative_current_generation",
            "definitions": {
                "participation": "resolved member-vote proposals weighted by eligible seats, not unique residents"
            },
            "organizations": organizations,
        }
