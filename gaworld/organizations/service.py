"""The simulation's single organization writer and finite execution engine.

SQLite and resident economy files are separate durability domains. A completed
day checkpoint is required for resume; an interrupted day fails closed rather
than guessing whether a transfer reached its recipient.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import threading
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from gaworld.economy import finance
from gaworld.organizations.governance import GOVERNANCE_COMMANDS, Governance
from gaworld.organizations.metrics import application_groups
from gaworld.organizations.rules import community_plan, hiring_plan
from gaworld.organizations.schemas import (
    MAX_CENTS,
    OrganizationValidationError,
    cents,
    identity_fingerprint,
    now,
    validate_rule,
)
from gaworld.organizations.store import OrganizationStore


class OrganizationService:
    def __init__(self, config, agents, context, recorder=None):
        self.config = config
        self.options = config.get("organizations", {})
        self.agents = {int(a["id"]): a for a in agents}
        self.context = context
        self.context["organization_service"] = self
        self.recorder = recorder
        self.store = OrganizationStore(
            Path(config.get("memory_dir", "output/memory")) / "organizations.sqlite"
        )
        self.output_dir = Path(self.options.get("output_dir", "output/organizations"))
        self._lock = threading.RLock()
        self._started = False
        self._closed = False
        self.day = 0
        self.governance = Governance(self)

    def _event(self, kind, row):
        if self.recorder is not None:
            self.recorder.record(f"organizations.{kind}", dict(row, generation_id=self.generation_id))

    @property
    def generation_id(self):
        return self.store.get_meta("generation_id")

    def _fail_recovery(self, message, cause=None):
        self.store.set_meta("recovery_required", True)
        self.store.set_meta("recovery_reason", message)
        raise RuntimeError(f"organizations recovery_required: {message}") from cause

    def start(self, day):
        with self._lock:
            self.store.acquire_writer()
            if self._started:
                return
            prior_generation = self.generation_id
            if not prior_generation or not self.config.get("stateful", False):
                self.store.new_generation()
            else:
                self.store.validate_population(self.agents.values(), self.config.get("csv_path"))
                if self.store.get_meta("recovery_required", False):
                    self._fail_recovery(
                        self.store.get_meta("recovery_reason", "unresolved previous execution")
                    )
                if self.store.get_meta("open_day") is not None:
                    self._fail_recovery("previous day did not reach the economic checkpoint")
                completed = self.store.get_meta("last_processed_day", 0)
                if int(day) < completed:
                    self._fail_recovery("resident clock precedes completed organization day")
                if completed and not finance.restore_organization_economy(self.context, completed):
                    self._fail_recovery("missing or incompatible economic checkpoint")
                self._reconcile_transactions()
            identities = self.store.get_meta("identities", {})
            identities.update({str(a["id"]): identity_fingerprint(a) for a in self.agents.values()})
            self.store.set_meta("identities", identities)
            if self.config.get("csv_path"):
                self.store.set_meta("population_source", str(Path(self.config["csv_path"]).resolve()))
            for org in self.store.list_organizations():
                self.governance.initialize(org)
                finance.register_organization_account(
                    self.context, org["organization_id"], org["balance_cents"]
                )
            for member in self.store.rows("members"):
                member["active"] = member["agent_id"] in self.agents and member["left_day"] is None
                self.store.put("members", member["membership_id"], member)
                if member["agent_id"] in self.agents and (
                    member.get("ever_employed")
                    or member.get("job_id")
                    or member.get("pending_employment_exit")
                ):
                    finance.restore_employment_state(self.agents[member["agent_id"]])
            self.day = int(day)
            self._started = True
            self._refresh_agents()
            # Seed job text is reconstructed on each process launch. Restore
            # the persisted contract without a new employment event/RNG draw.
            for number, oid in self._employers().items():
                if number not in self.agents:
                    continue
                person = self.agents[number]
                member = self.store.get("members", f"{oid}:{number}")
                job = self.store.get("jobs", f"{oid}:{member['job_id']}")
                person["job"] = person.get("economy", {}).get("job") or job["occupation"]
                person["employment"] = "employed"
            seeds = self.options.get("seeds", [])
            for seed in seeds:
                payload = dict(seed, type="create")
                oid = payload.get("organization_id")
                if self.store.detail(oid) is not None:
                    continue
                token = hashlib.sha256(f"{self.generation_id}:{oid}:seed".encode()).hexdigest()
                payload["command_id"] = token
                self.store.enqueue(payload, actor={"source": "organization_seed"})

    def _mark_open(self, day):
        self._check_ready()
        self.store.set_meta("open_day", int(day))
        self.store.set_meta("last_started_day", int(day))

    def _reconcile_transactions(self):
        """Complete only ledger projections proven by the restored checkpoint."""
        pending = [t for t in self.store.rows("transactions") if t["stage"] != "committed"]
        if not pending:
            return
        projections = {}
        try:
            for transaction in pending:
                oid = transaction["organization_id"]
                org = projections.setdefault(oid, self.store.get("organizations", oid))
                if transaction["purpose"] == "funding":
                    receipt = finance.get_organization_funding_receipt(
                        self.context, transaction["transaction_id"]
                    )
                else:
                    person = self.agents.get(transaction["agent_id"])
                    if person is None:
                        raise ValueError("pending receipt recipient is inactive")
                    receipt = finance.get_organization_receipt(
                        self.context, person, transaction["transaction_id"]
                    )
                if (
                    not receipt
                    or receipt["organization_id"] != oid
                    or receipt["purpose"] != transaction["purpose"]
                ):
                    raise ValueError("missing or incompatible payment receipt")
                if (
                    receipt["transaction_id"] != transaction["transaction_id"]
                    or receipt["requested_cents"] != transaction["requested_cents"]
                ):
                    raise ValueError("receipt identifies a different obligation")
                paid, unpaid = cents(receipt["paid_cents"]), cents(receipt["unpaid_cents"])
                if paid + unpaid != transaction["requested_cents"]:
                    raise ValueError("receipt amount mismatch")
                if transaction["purpose"] == "funding":
                    org["balance_cents"] += paid
                    org["income_cents"] += paid
                    debt = 0
                else:
                    if receipt["agent_id"] != transaction["agent_id"]:
                        raise ValueError("receipt recipient mismatch")
                    if not transaction.get("new_obligation", True):
                        raise ValueError("pending arrears projection requires manual reconciliation")
                    org["balance_cents"] -= paid
                    org["expense_cents"] += paid
                    debt = unpaid if transaction["purpose"] != "aid" else 0
                    org["arrears_cents"] += debt
                    org["committed_cents"] += debt
                if org["balance_cents"] != receipt["balance_after_cents"]:
                    raise ValueError("receipt sender balance mismatch")
                transaction.update(
                    stage="committed",
                    receipt=receipt,
                    paid_cents=paid,
                    unpaid_cents=unpaid,
                    arrears_remaining_cents=debt,
                )
            for oid, org in projections.items():
                if org["balance_cents"] != finance.organization_account_balance(self.context, oid):
                    raise ValueError("checkpoint does not prove sender balance")
        except (KeyError, TypeError, ValueError) as exc:
            self._fail_recovery("unresolved transaction cannot be proven: " + str(exc), exc)
        with self.store.atomic():
            for oid, org in projections.items():
                self.store.put("organizations", oid, org)
            for transaction in pending:
                self.store.put("transactions", transaction["transaction_id"], transaction)
                self.store.add_history(transaction["organization_id"], "receipt_reconciled", transaction)

    def _check_ready(self):
        if not self._started:
            raise RuntimeError("organization service has not started")
        if self.store.get_meta("recovery_required", False):
            self._fail_recovery(self.store.get_meta("recovery_reason", "unresolved transaction"))

    def prepare_day(self, day):
        """Synchronize employment before daily observers, without making payments."""
        with self._lock:
            self._check_ready()
            day = int(day)
            if day < self.store.get_meta("last_processed_day", 0):
                self._fail_recovery("cannot process before completed organization day")
            if day <= self.store.get_meta("last_command_day", 0):
                return
            self.day = day
            self.context["day"] = day
            self._mark_open(day)
            self._sync_pending_employment_exits(day)

    def process_day(self, day):
        with self._lock:
            self.prepare_day(day)
            day = int(day)
            if day <= self.store.get_meta("last_command_day", 0):
                return
            for command in self.store.commands():
                if command["status"] != "pending":
                    continue
                actor = command.get("actor") or {}
                if actor.get("source") == "organization_governance":
                    proposal = self.store.get(
                        "proposals", f"{command['organization_id']}:{actor.get('proposal_id')}"
                    )
                    if proposal and day < proposal.get("execute_not_before_day", 0):
                        continue
                try:
                    result = self._apply_command(command, day)
                except OrganizationValidationError as exc:
                    result, status = {"reason": str(exc)}, "rejected"
                else:
                    status = "applied"
                self.store.update_command(command, status, result, day)
                self.store.add_history(
                    command["organization_id"],
                    "command",
                    {
                        "command_id": command["command_id"],
                        "command_type": command["type"],
                        "actor": command["actor"],
                        "status": status,
                        "result": result,
                        "day": day,
                    },
                )
            self.governance.resolve(day)
            # All decisions observe the same cash/skill snapshot before any aid.
            for org in self.store.list_organizations():
                self._settle_arrears(org["organization_id"], f"day-{day}", day)
            frozen = {number: self._freeze(person) for number, person in self.agents.items()}
            for org in self.store.list_organizations():
                if org["status"] != "open" or (day - org["created_day"]) % org["decision_interval"]:
                    continue
                self._decide(org, frozen, day)
            self.store.set_meta("last_command_day", day)
            self._refresh_agents()
            finance.refresh_organization_employment_statistics(self.context)

    def _organization(self, oid, *, open_only=False, kind=None):
        org = self.store.get("organizations", oid)
        if org is None:
            raise OrganizationValidationError("organization does not exist")
        if open_only and org["status"] != "open":
            raise OrganizationValidationError("organization is closed")
        if kind is not None and org["kind"] != kind:
            raise OrganizationValidationError(f"command requires a {kind} organization")
        return org

    def _person(self, number):
        person = self.agents.get(number)
        if person is None:
            raise OrganizationValidationError("resident is inactive in this run")
        return person

    def _apply_command(self, command, day):
        p = command["payload"]
        oid, kind = p["organization_id"], p["type"]
        if kind in GOVERNANCE_COMMANDS:
            return self.governance.apply(command, day)
        if kind == "set_rule" and (command.get("actor") or {}).get("source") == "organization_governance":
            return self.governance.execute(command, day)
        if kind == "create":
            return self._create(command, day)
        org = self._organization(oid, open_only=kind not in {"fund", "handover", "remove_member", "close"})
        if kind == "fund":
            receipt = self._fund(
                org,
                p["amount_cents"],
                p.get("source", org["funding_source"]),
                f"fund-{command['command_id']}",
                day,
            )
            self._settle_arrears(oid, command["command_id"], day)
            return receipt
        if kind == "add_member":
            if p.get("role", "member") not in {"member", "employee"}:
                raise OrganizationValidationError(
                    "leader role requires a handover; employee role requires hiring"
                )
            if p.get("role") == "employee":
                raise OrganizationValidationError("employee role requires hiring")
            self._person(p["agent_id"])
            return self._join(oid, p["agent_id"], "member", day, p.get("reason", "command"))
        if kind == "remove_member":
            if org["leader_id"] == p["agent_id"]:
                raise OrganizationValidationError("leader must hand over before leaving")
            member = self.store.get("members", f"{oid}:{p['agent_id']}")
            if member is None or member["left_day"] is not None:
                raise OrganizationValidationError("resident is not a current member")
            member.update(left_day=day, active=False, left_reason=p.get("reason", "command"))
            if member.get("job_id"):
                job = self.store.get("jobs", f"{oid}:{member['job_id']}")
                job["occupied"] -= 1
                self.store.put("jobs", f"{oid}:{job['job_id']}", job)
                person = self.agents.get(p["agent_id"])
                if person is not None:
                    finance.apply_employment_event(person, {"template_key": "unemployment"}, self.config, day)
                member.update(
                    job_id=None,
                    ever_employed=True,
                    employment_ended_day=day,
                    pending_employment_exit={"day": day, "job": job["occupation"]}
                    if person is None
                    else None,
                )
            self.store.put("members", member["membership_id"], member)
            self._event("membership", member)
            return member
        if kind == "handover":
            member = self.store.get("members", f"{oid}:{p['leader_id']}")
            if member is None or member["left_day"] is not None:
                raise OrganizationValidationError("new leader must be a current member")
            old = self.store.get("members", f"{oid}:{org['leader_id']}")
            if old:
                old["role"] = "employee" if old.get("job_id") else "member"
                self.store.put("members", old["membership_id"], old)
            member["role"] = "leader"
            self.store.put("members", member["membership_id"], member)
            org["leader_id"] = p["leader_id"]
            if "governance" in org:
                org["leader_version"] = org.get("leader_version", 1) + 1
            org["state_version"] += 1
            self.store.put("organizations", oid, org)
            self._event("membership", member)
            return {"leader_id": p["leader_id"]}
        if kind == "set_rule":
            return self._set_rule(org, command, day)
        if kind == "update_profile":
            before = {key: org[key] for key in ("name", "goal")}
            after = {key: p.get(key, value) for key, value in before.items()}
            if before != after:
                org.update(after, state_version=org["state_version"] + 1)
                self.store.put("organizations", oid, org)
                self._event("organization", org)
            return {"before": before, "after": after, "state_version": org["state_version"]}
        if kind == "close":
            org.update(
                status="closed",
                closed_day=day,
                close_reason=p.get("reason", ""),
                state_version=org["state_version"] + 1,
            )
            self.store.put("organizations", oid, org)
            for app in self.store.rows("applications", oid):
                if app["status"] == "pending":
                    app.update(status="rejected", reason="organization_closed", decided_day=day)
                    self.store.put("applications", app["application_id"], app)
            return {"status": "closed"}
        if kind == "publish_job":
            self._organization(oid, kind="company")
            job_id = p.get("job_id", command["command_id"])
            if self.store.get("jobs", f"{oid}:{job_id}"):
                raise OrganizationValidationError("job_id already exists")
            job = {
                "organization_id": oid,
                "job_id": job_id,
                "occupation": p["occupation"],
                "vacancies": p["vacancies"],
                "occupied": 0,
                "monthly_salary_cents": p["monthly_salary_cents"],
                "min_income_skill": p.get("min_income_skill", 0),
                "location": p.get("location", ""),
                "created_day": day,
                "status": "open",
            }
            self.store.put("jobs", f"{oid}:{job_id}", job)
            return job
        if kind in {"apply_aid", "apply_job"}:
            return self._application(org, command, day)
        raise OrganizationValidationError("unknown command type")

    def _create(self, command, day):
        p = command["payload"]
        oid = p["organization_id"]
        existing = self.store.get("organizations", oid)
        if existing:
            raise OrganizationValidationError("organization_id already exists")
        members = sorted({*p.get("member_ids", []), p["leader_id"]})
        for number in members:
            self._person(number)
        kind = p["kind"]
        rule = p.get("rule", "equal_split" if kind == "community" else "lottery")
        org = {
            "organization_id": oid,
            "name": p["name"],
            "kind": kind,
            "goal": p.get("goal", ""),
            "leader_id": p["leader_id"],
            "status": "open",
            "created_at": now(),
            "created_day": day,
            "rule": rule,
            "rule_params": p.get("rule_params", {}),
            "rule_version": 1,
            "seed": p.get("seed", self.options.get("seed", 0)),
            "decision_interval": p.get("decision_interval", 1),
            "state_version": 1,
            "balance_cents": 0,
            "committed_cents": 0,
            "arrears_cents": 0,
            "income_cents": 0,
            "expense_cents": 0,
            "funding_source": p.get("funding_source", "government" if kind == "community" else "firms"),
            "created_by": command["actor"],
        }
        self.governance.initialize(org, p.get("governance"))
        self.store.put("organizations", oid, org)
        for number in members:
            self._join(oid, number, "leader" if number == p["leader_id"] else "member", day, "creation")
        self._save_rule(org, day, command["actor"])
        finance.register_organization_account(self.context, oid, 0)
        amount = p.get("initial_balance_cents", 0)
        if amount:
            self._fund(org, amount, org["funding_source"], f"initial-{command['command_id']}", day)
        self._event("organization", self.store.get("organizations", oid))
        return {"organization_id": oid}

    def _join(self, oid, number, role, day, reason, job_id=None):
        key = f"{oid}:{number}"
        old = self.store.get("members", key)
        if old and old["left_day"] is None and job_id is None:
            return old
        member = {
            "membership_id": key,
            "organization_id": oid,
            "agent_id": number,
            "role": role,
            "joined_day": day,
            "left_day": None,
            "reason": reason,
            "active": number in self.agents,
            "job_id": job_id,
            "ever_employed": bool(job_id) or bool(old and (old.get("ever_employed") or old.get("job_id"))),
        }
        if old and old["left_day"] is None:
            member["joined_day"] = old["joined_day"]
            if old["role"] == "leader":
                member["role"] = "leader"
        self.store.put("members", key, member)
        self.store.add_history(oid, "membership", dict(member, day=day))
        self._event("membership", member)
        return member

    def _sync_pending_employment_exits(self, day):
        """Apply an absent worker's termination once when they next participate."""
        employers = self._employers()
        for member in self.store.rows("members"):
            pending = member.get("pending_employment_exit")
            person = self.agents.get(member["agent_id"])
            if not pending or person is None:
                continue
            saved_job = person.get("economy", {}).get("job")
            newer_event = any(
                event.get("type") in {"job_change", "unemployment", "retirement"}
                and isinstance(event.get("day"), int)
                and event["day"] >= pending["day"]
                for event in person.get("economy", {}).get("shock_log", [])
                if isinstance(event, dict)
            )
            superseded = member["agent_id"] in employers or saved_job != pending["job"] or newer_event
            if not superseded:
                finance.apply_employment_event(person, {"template_key": "unemployment"}, self.config, day)
            member["pending_employment_exit"] = None
            self.store.put("members", member["membership_id"], member)
            self.store.add_history(
                member["organization_id"],
                "employment_exit_synced",
                {
                    "agent_id": member["agent_id"],
                    "day": day,
                    "exit_day": pending["day"],
                    "result": "superseded_by_new_employment" if superseded else "unemployed",
                },
            )
            self._event("membership", member)

    def _set_rule(self, org, command, day):
        p = command["payload"]
        params = validate_rule(org["kind"], p["rule"], p.get("rule_params", {}))
        with self.store.atomic():
            org.update(
                rule=p["rule"],
                rule_params=params,
                rule_version=org["rule_version"] + 1,
                state_version=org["state_version"] + 1,
            )
            self.store.put("organizations", org["organization_id"], org)
            self._save_rule(org, day, command["actor"])
        return {"rule_version": org["rule_version"]}

    def _save_rule(self, org, day, actor):
        row = {
            "organization_id": org["organization_id"],
            "version": org["rule_version"],
            "name": org["rule"],
            "params": org["rule_params"],
            "effective_day": day,
            "modified_by": actor,
        }
        self.store.put("rules", f"{org['organization_id']}:{org['rule_version']}", row)

    def _application(self, org, command, day):
        p = command["payload"]
        oid, number = org["organization_id"], p["agent_id"]
        self._person(number)
        aid = p["type"] == "apply_aid"
        self._organization(oid, kind="community" if aid else "company")
        if not aid:
            job = self.store.get("jobs", f"{oid}:{p['job_id']}")
            if job is None or job["status"] != "open":
                raise OrganizationValidationError("job does not exist or is closed")
        request_id = p.get("request_id", command["command_id"])
        key = f"{oid}:{request_id}"
        old = self.store.get("applications", key)
        row = {
            "application_id": key,
            "request_id": request_id,
            "organization_id": oid,
            "agent_id": number,
            "kind": "aid" if aid else "job",
            "status": "pending",
            "amount_cents": p.get("amount_cents", 0),
            "job_id": p.get("job_id"),
            "reason": p.get("reason", ""),
            "submitted_day": day,
            "created_at": now(),
            "source": command["actor"],
            "paid_cents": 0,
        }
        if old:
            fields = ("agent_id", "kind", "amount_cents", "job_id")
            if any(old[k] != row[k] for k in fields):
                raise OrganizationValidationError("request_id reused with different application")
            return old
        self.store.put("applications", key, row)
        self._event("application", row)
        return row

    def _freeze(self, person):
        econ = person.get("economy", {})
        econ = econ if isinstance(econ, dict) else {}
        accounts = econ.get("accounts", {})
        accounts = accounts if isinstance(accounts, dict) else {}
        checking = accounts.get("checking")
        has_account = (
            isinstance(checking, (int, float)) and not isinstance(checking, bool) and math.isfinite(checking)
        )
        cash = None
        if all(k in accounts for k in ("checking", "savings")):
            values = [accounts["checking"], accounts["savings"]]
            if all(
                isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values
            ):
                cash = self._money(sum(values), allow_negative=True)
        skill = econ.get("income_skill")
        if (
            isinstance(skill, bool)
            or not isinstance(skill, (int, float))
            or not math.isfinite(skill)
            or not 0 <= skill <= 1
        ):
            skill = None
        age = person.get("age")
        try:
            age = float(age)
            if not math.isfinite(age):
                age = None
        except (ValueError, TypeError):
            age = None
        record = person.get("ext", {}).get("family")
        if not isinstance(record, dict):
            record = person.get("family")
        dependants = None
        if isinstance(record, dict) and isinstance(record.get("members"), list):
            dependants = 0
            for member in record["members"]:
                if not isinstance(member, dict) or not member.get("coresident"):
                    continue
                member_age = member.get("age")
                if isinstance(member_age, (int, float)) and not isinstance(member_age, bool):
                    if (member.get("role") == "child" and member_age < 18) or (
                        member.get("role") in {"father", "mother", "parent"} and member_age >= 65
                    ):
                        dependants += 1
                elif member.get("dependant"):
                    dependants += 1
        return {
            "active": True,
            "age": age,
            "has_economic_account": has_account,
            "gender": person.get("gender"),
            "employment": person.get("employment"),
            "cash_cents": cash,
            "income_skill": skill,
            "dependants": dependants or 0,
            "dependants_missing": dependants is None,
            "employer_id": self._employers().get(person["id"]),
        }

    def _employers(self):
        return {
            m["agent_id"]: m["organization_id"]
            for m in self.store.rows("members")
            if m["left_day"] is None and m.get("job_id") is not None
        }

    def _decide(self, org, frozen, day):
        oid = org["organization_id"]
        batch_id = f"{oid}:day:{day}"
        if self.store.get("batches", batch_id):
            return
        applications = [a for a in self.store.rows("applications", oid) if a["status"] == "pending"]
        batch = {
            "organization_id": oid,
            "batch_id": batch_id,
            "day": day,
            "rule": org["rule"],
            "rule_version": org["rule_version"],
            "rule_params": org["rule_params"],
            "balance_before_cents": org["balance_cents"],
            "stage": "prepared",
            "application_ids": [a["application_id"] for a in applications],
            "snapshots": {
                str(a["agent_id"]): frozen.get(a["agent_id"], {"active": False}) for a in applications
            },
        }
        if org["kind"] == "community":
            members = {m["agent_id"] for m in self.store.rows("members", oid) if m["left_day"] is None}
            plan = community_plan(
                org,
                applications,
                frozen,
                members,
                max(0, org["balance_cents"] - org["arrears_cents"]),
                batch_id,
            )
        else:
            plan, employers = [], self._employers()
            for job in self.store.rows("jobs", oid):
                candidates = [a for a in applications if a["job_id"] == job["job_id"]]
                part = hiring_plan(org, job, candidates, frozen, employers, batch_id)
                for row in part:
                    row["job_id"] = job["job_id"]
                    if row["hired"]:
                        employers[row["agent_id"]] = oid
                plan.extend(part)
        batch["plan"] = plan
        self.store.put("batches", batch_id, batch)
        for decision in plan:
            app = self.store.get("applications", decision["application_id"])
            app.update(
                frozen=decision["frozen"],
                eligible=decision["eligible"],
                reason=decision["reason"],
                rule=decision["rule"],
                rule_version=decision["rule_version"],
                decided_day=day,
                batch_id=batch_id,
                waiting_days=day - app["submitted_day"],
            )
            if org["kind"] == "community" and decision["amount_cents"]:
                transaction_id = hashlib.sha256(
                    f"{self.generation_id}:{batch_id}:{app['application_id']}:aid".encode()
                ).hexdigest()
                receipt = self._transfer(
                    oid, self.agents[app["agent_id"]], decision["amount_cents"], transaction_id, "aid", day
                )
                app["paid_cents"] = receipt["paid_cents"]
                app["status"] = "paid" if receipt["paid_cents"] else "rejected"
            elif org["kind"] == "company" and decision["hired"]:
                job = self.store.get("jobs", f"{oid}:{decision['job_id']}")
                if job["occupied"] >= job["vacancies"]:
                    self._fail_recovery("hiring plan no longer matches vacancy or employment state")
                person = self.agents[app["agent_id"]]
                previous = self._employers().get(person["id"])
                if previous is not None:
                    if decision["frozen"].get("employer_id") != previous or previous == oid:
                        self._fail_recovery("hiring plan no longer matches previous employer")
                    old_member = self.store.get("members", f"{previous}:{person['id']}")
                    old_job = self.store.get("jobs", f"{previous}:{old_member['job_id']}")
                    old_job["occupied"] -= 1
                    old_member["job_id"] = None
                    if old_member["role"] != "leader":
                        old_member.update(left_day=day, active=False, left_reason="employer_switch")
                    with self.store.atomic():
                        self.store.put("jobs", f"{previous}:{old_job['job_id']}", old_job)
                        self.store.put("members", old_member["membership_id"], old_member)
                        self.store.add_history(previous, "membership", dict(old_member, day=day))
                    self._event("membership", old_member)
                finance.apply_employment_event(
                    person,
                    {
                        "template_key": "job_change",
                        "new_job": job["occupation"],
                        "new_monthly_salary_cents": job["monthly_salary_cents"],
                    },
                    self.config,
                    day,
                )
                finance.set_contract_salary(person, job["monthly_salary_cents"], self.config)
                self._join(oid, person["id"], "employee", day, "hired", job["job_id"])
                job["occupied"] += 1
                self.store.put("jobs", f"{oid}:{job['job_id']}", job)
                app["status"] = "hired"
            else:
                app["status"] = "rejected"
            self.store.put("applications", app["application_id"], app)
            row = dict(
                decision,
                organization_id=oid,
                batch_id=batch_id,
                day=day,
                application_status=app["status"],
                paid_cents=app["paid_cents"],
            )
            self.store.put("decisions", f"{batch_id}:{app['application_id']}", row)
            self.store.add_history(oid, "decision", row)
            self._event("decision", row)
        batch["stage"] = "committed"
        self.store.put("batches", batch_id, batch)

    @staticmethod
    def _money(amount, allow_negative=False):
        try:
            value = Decimal(str(amount))
            if not value.is_finite() or (not allow_negative and value < 0):
                raise OrganizationValidationError("invalid finite money amount")
            integer = int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except (InvalidOperation, TypeError, ValueError, OverflowError) as exc:
            raise OrganizationValidationError("invalid finite money amount") from exc
        if abs(integer) > MAX_CENTS:
            raise OrganizationValidationError("money amount exceeds bounds")
        return integer

    def _fund(self, org, amount, source, transaction_id, day):
        cents(amount)
        existing = self.store.get("transactions", transaction_id)
        if existing:
            if existing["stage"] != "committed":
                self._fail_recovery("funding transaction is unresolved")
            return existing["receipt"]
        if org["balance_cents"] + amount > MAX_CENTS:
            raise OrganizationValidationError("funding would exceed organization balance bounds")
        row = {
            "organization_id": org["organization_id"],
            "transaction_id": transaction_id,
            "purpose": "funding",
            "source": source,
            "requested_cents": amount,
            "day": day,
            "stage": "prepared",
            "balance_before_cents": org["balance_cents"],
        }
        self.store.put("transactions", transaction_id, row)
        try:
            receipt = finance.organization_fund(
                self.context, org["organization_id"], amount, source, transaction_id
            )
            paid = cents(receipt["paid_cents"])
            if paid != amount:
                raise ValueError("funding receipt does not match requested cents")
        except Exception as exc:
            self._fail_recovery("funding lacks a verified receipt", exc)
        org = self.store.get("organizations", org["organization_id"])
        org.update(
            balance_cents=org["balance_cents"] + paid,
            income_cents=org["income_cents"] + paid,
            state_version=org["state_version"] + 1,
        )
        row.update(stage="committed", receipt=receipt, paid_cents=paid, unpaid_cents=0)
        with self.store.atomic():
            self.store.put("organizations", org["organization_id"], org)
            self.store.put("transactions", transaction_id, row)
            self.store.add_history(org["organization_id"], "transaction", row)
        self._event("transaction", row)
        return receipt

    def _transfer(
        self, oid, person, amount, transaction_id, purpose, day, *, new_obligation=True, payment_context=None
    ):
        cents(amount)
        existing = self.store.get("transactions", transaction_id)
        if existing:
            if existing["stage"] != "committed":
                self._fail_recovery("payment transaction is unresolved")
            if (
                existing["requested_cents"] != amount
                or existing["agent_id"] != person["id"]
                or existing["purpose"] != purpose
                or existing.get("new_obligation", True) != new_obligation
            ):
                self._fail_recovery("payment ID reused for an incompatible obligation")
            return existing["receipt"]
        org = self._organization(oid)
        row = {
            "organization_id": oid,
            "agent_id": person["id"],
            "transaction_id": transaction_id,
            "purpose": purpose,
            "requested_cents": amount,
            "day": day,
            "stage": "prepared",
            "balance_before_cents": org["balance_cents"],
            "new_obligation": new_obligation,
        }
        self.store.put("transactions", transaction_id, row)
        try:
            receipt = finance.organization_transfer(
                {**self.context, **(payment_context or {}), "day": day},
                oid,
                person,
                amount,
                transaction_id,
                purpose,
                max_paid_cents=max(0, org["balance_cents"] - org["committed_cents"])
                if new_obligation
                else org["balance_cents"],
                is_arrears=not new_obligation,
            )
            paid, unpaid = cents(receipt["paid_cents"]), cents(receipt["unpaid_cents"])
            if paid + unpaid != amount or paid > org["balance_cents"]:
                raise ValueError("receipt violates payment or balance bounds")
        except Exception as exc:
            self._fail_recovery("payment lacks a verified recipient receipt", exc)
        debt = unpaid if new_obligation and purpose != "aid" else 0
        org.update(
            balance_cents=org["balance_cents"] - paid,
            expense_cents=org["expense_cents"] + paid,
            arrears_cents=org["arrears_cents"] + debt,
            committed_cents=org["committed_cents"] + debt,
            state_version=org["state_version"] + 1,
        )
        row.update(
            stage="committed",
            receipt=receipt,
            paid_cents=paid,
            unpaid_cents=unpaid,
            arrears_remaining_cents=debt,
        )
        with self.store.atomic():
            self.store.put("organizations", oid, org)
            self.store.put("transactions", transaction_id, row)
            self.store.add_history(oid, "transaction", row)
        self._event("transaction", row)
        return receipt

    def _settle_arrears(self, oid, funding_id, day):
        for debt in self.store.rows("transactions", oid):
            outstanding = debt.get("arrears_remaining_cents", 0)
            org = self._organization(oid)
            if not outstanding or not org["balance_cents"]:
                continue
            person = self.agents.get(debt["agent_id"])
            if person is None:
                continue  # Preserve inactive employees' obligations without inventing accounts.
            transaction_id = hashlib.sha256(
                f"{debt['transaction_id']}:arrears:{funding_id}".encode()
            ).hexdigest()
            receipt = self._transfer(
                oid, person, outstanding, transaction_id, debt["purpose"], day, new_obligation=False
            )
            paid = receipt["paid_cents"]
            debt["arrears_remaining_cents"] -= paid
            org = self._organization(oid)
            org["arrears_cents"] -= paid
            org["committed_cents"] -= paid
            with self.store.atomic():
                self.store.put("transactions", debt["transaction_id"], debt)
                self.store.put("organizations", oid, org)

    def pay_wage(self, agent, amount, context, category):
        with self._lock:
            employer = self._employers().get(int(agent["id"]))
            if employer is None:
                return None
            self._check_ready()
            day = int(context.get("day", self.day))
            time_str = str(context.get("time_str", context.get("time", "daily")))
            if day < self.store.get_meta("last_processed_day", 0):
                self._fail_recovery("wage clock precedes organization checkpoint")
            self._mark_open(day)
            purpose = {"housing_fund": "housing_fund", "year_bonus": "bonus"}.get(category, "wage")
            requested = self._money(amount)
            transaction_id = hashlib.sha256(
                f"{self.generation_id}:{employer}:{agent['id']}:{day}:{time_str}:{category}".encode()
            ).hexdigest()
            receipt = self._transfer(
                employer,
                agent,
                requested,
                transaction_id,
                purpose,
                day,
                payment_context={"time_str": time_str},
            )
            self._refresh_agents()
            return receipt["paid_cents"] / 100

    def release_employment(self, agent, day, reason):
        """An external employment event ends payroll while retaining obligations."""
        with self._lock:
            oid = self._employers().get(int(agent["id"]))
            if oid is None:
                return
            self._mark_open(day)
            member = self.store.get("members", f"{oid}:{agent['id']}")
            job = self.store.get("jobs", f"{oid}:{member['job_id']}")
            job["occupied"] -= 1
            member["job_id"] = None
            member["ever_employed"] = True
            member["employment_ended_day"] = day
            if member["role"] != "leader":
                member.update(left_day=day, active=False, left_reason=reason)
            with self.store.atomic():
                self.store.put("jobs", f"{oid}:{job['job_id']}", job)
                self.store.put("members", member["membership_id"], member)
                self.store.add_history(oid, "employment_ended", dict(member, day=day, reason=reason))
            self._event("membership", member)
            self._refresh_agents()

    def _refresh_agents(self):
        members = self.store.rows("members")
        for number, person in self.agents.items():
            own = [m for m in members if m["agent_id"] == number and m["left_day"] is None]
            ext = person.setdefault("ext", {}).setdefault("organizations", {})
            ext["memberships"] = [m["organization_id"] for m in own]
            employed = next((m for m in own if m.get("job_id")), None)
            ext["employer_id"] = employed["organization_id"] if employed else None
            ext["job_id"] = employed["job_id"] if employed else None
            if employed:
                org = self._organization(employed["organization_id"])
                ext["arrears_cents"] = sum(
                    t.get("arrears_remaining_cents", 0)
                    for t in self.store.rows("transactions", org["organization_id"])
                    if t.get("agent_id") == number
                )
            else:
                ext["arrears_cents"] = 0

    def candidates(self, agent, activity):
        if not self._started or self.store.get_meta("recovery_required", False):
            return []
        result = self.governance.candidates(agent)
        for org in self.store.list_organizations():
            if org["status"] != "open":
                continue
            if any(
                c["status"] == "pending"
                and c["organization_id"] == org["organization_id"]
                and c["payload"].get("agent_id") == agent["id"]
                and c["type"] in {"apply_aid", "apply_job"}
                for c in self.store.commands()
            ):
                continue
            if org["kind"] == "community":
                member = self.store.get("members", f"{org['organization_id']}:{agent['id']}")
                if not member or member["left_day"] is not None:
                    continue
                pending = any(
                    a["agent_id"] == agent["id"] and a["status"] == "pending"
                    for a in self.store.rows("applications", org["organization_id"])
                )
                if not pending:
                    cap = org["rule_params"].get(
                        "max_award_cents", self.options.get("default_aid_cents", 10000)
                    )
                    result.append(f"org:apply_aid:{org['organization_id']}:{cap}")
            elif self._employers().get(agent["id"]) != org["organization_id"]:
                for job in self.store.rows("jobs", org["organization_id"]):
                    if job["occupied"] < job["vacancies"] and job["status"] == "open":
                        result.append(f"org:apply_job:{org['organization_id']}:{job['job_id']}")
        return result

    def handle_action(self, agent, action, day, time_str):
        if not isinstance(action, str) or action not in self.candidates(agent, ""):
            return False
        _, command_type, oid, value = action.split(":", 3)
        token = hashlib.sha256(
            f"{self.generation_id}:{agent['id']}:{day}:{time_str}:{action}".encode()
        ).hexdigest()
        payload = {
            "type": command_type,
            "organization_id": oid,
            "agent_id": int(agent["id"]),
            "command_id": token,
            "request_id": token,
            "reason": "resident_action",
        }
        if command_type in GOVERNANCE_COMMANDS:
            payload.pop("request_id")
            payload["reason"] = ""
            if command_type == "propose_rule":
                payload["rule"] = value
            else:
                payload["proposal_id"], payload["choice"] = value.split(":", 1)
            self.store.enqueue(
                payload, actor={"source": "resident", "agent_id": agent["id"], "day": day, "time": time_str}
            )
            return True
        payload["amount_cents" if command_type == "apply_aid" else "job_id"] = (
            int(value) if command_type == "apply_aid" else value
        )
        self.store.enqueue(
            payload, actor={"source": "resident", "agent_id": agent["id"], "day": day, "time": time_str}
        )
        return True

    def perception(self, agent):
        from gaworld.organizations.narrative import perception

        return perception(self.store, agent)

    def snapshot(self):
        return {
            "generation_id": self.generation_id,
            "last_processed_day": self.store.get_meta("last_processed_day", 0),
            "recovery_required": self.store.get_meta("recovery_required", False),
            "organizations": [
                self.store.detail(o["organization_id"]) for o in self.store.list_organizations()
            ],
        }

    def finish_day(self, day):
        with self._lock:
            self._check_ready()
            day = int(day)
            if day < self.store.get_meta("last_processed_day", 0):
                self._fail_recovery("cannot checkpoint a past organization day")
            if any(t["stage"] != "committed" for t in self.store.rows("transactions")):
                self._fail_recovery("pending transactions prevent checkpoint")
            try:
                finance.checkpoint_organization_economy(self.context, day)
            except Exception as exc:
                self._fail_recovery("economic checkpoint failed", exc)
            self.store.set_meta("last_processed_day", day)
            self.store.set_meta("open_day", None)
            self._export(day)

    def _export(self, day):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        snapshot = self.snapshot()
        snapshot["day"] = day
        metrics = []
        for org in snapshot["organizations"]:
            applications = org["applications"]
            aid = [a for a in applications if a["kind"] == "aid" and a["status"] != "pending"]
            paid = [a for a in aid if a.get("paid_cents", 0)]
            jobs = [a for a in applications if a["kind"] == "job" and a["status"] != "pending"]
            hires = [a for a in jobs if a["status"] == "hired"]
            decided = aid if org["kind"] == "community" else jobs
            eligible_decided = [a for a in decided if a.get("eligible")]
            covered = paid if org["kind"] == "community" else hires
            wage = [
                t
                for t in org["transactions"]
                if t["purpose"] in {"wage", "bonus", "housing_fund"} and t["stage"] == "committed"
            ]
            row = {
                "organization_id": org["organization_id"],
                "kind": org["kind"],
                "generation_id": self.generation_id,
                "day": day,
                "rule": org["rule"],
                "rule_version": org["rule_version"],
                "applications": len(aid) if org["kind"] == "community" else len(jobs),
                "eligible_applications": len(eligible_decided),
                "coverage_numerator": len(covered),
                "coverage_denominator": len(eligible_decided),
                "coverage": len(covered) / len(eligible_decided) if eligible_decided else None,
                "aid_paid_cents": sum(a["paid_cents"] for a in paid),
                "balance_cents": org["balance_cents"],
                "arrears_cents": org["arrears_cents"],
                "budget_utilization_denominator_cents": org["income_cents"],
                "budget_utilization": org["expense_cents"] / org["income_cents"]
                if org["income_cents"]
                else None,
                "vacancies": sum(j["vacancies"] for j in org["jobs"]),
                "occupied": sum(j["occupied"] for j in org["jobs"]),
                "hires": len(hires),
                "rejections": sum(a["status"] == "rejected" for a in applications),
                "wage_owed_cents": sum(t["requested_cents"] for t in wage if t.get("new_obligation")),
                "wage_paid_cents": sum(t["paid_cents"] for t in wage),
                "waiting_days_sum": sum(a.get("waiting_days", 0) for a in applications),
                "waiting_days_denominator": sum(a["status"] != "pending" for a in applications),
                "rejection_reasons": dict(
                    sorted(
                        Counter(
                            a.get("reason") or "unknown" for a in decided if a["status"] == "rejected"
                        ).items()
                    )
                ),
                "groups": application_groups(decided),
            }
            metrics.append(row)
            self._event("summary", row)
        payload = {
            "generation_id": self.generation_id,
            "day": day,
            "scope": "cumulative_current_generation",
            "definitions": {
                "coverage": "community: paid aid / eligible decided aid; company: hires / eligible decided job applications",
                "budget_utilization": "all actual outflows / explicit funding received",
                "vacancies": "total published positions; occupied counts retained employment relations",
                "income_skill": "model work-capability proxy; not a validated real-world ability score",
                "groups": "application-weighted; frozen pre-decision age (<35, 35-64, 65+), gender, employment; missing values kept as unknown; counts are not unique residents",
            },
            "organizations": metrics,
        }
        exports = [("snapshot.json", snapshot), ("metrics.json", payload)]
        if self.governance.enabled or self.store.rows("proposals"):
            exports.append(("governance.json", self.governance.export(day)))
        for name, data in exports:
            history_dir = self.output_dir / "generations" / self.generation_id / f"day-{day}"
            history_dir.mkdir(parents=True, exist_ok=True)
            for path in (self.output_dir / name, history_dir / name):
                temporary = path.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
                )
                temporary.replace(path)
        if metrics:
            with (self.output_dir / "metrics.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(metrics[0]))
                writer.writeheader()
                writer.writerows(
                    {
                        key: json.dumps(value, ensure_ascii=False, allow_nan=False)
                        if isinstance(value, dict)
                        else value
                        for key, value in row.items()
                    }
                    for row in metrics
                )

    def close(self):
        if not self._closed:
            self.store.close()
            self._closed = True
