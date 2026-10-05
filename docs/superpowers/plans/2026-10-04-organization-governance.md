# Organization Governance Implementation Plan

> **For agentic workers:** Execute task-by-task in this authorized session; use test-driven-development and requesting-code-review. Preserve the shared dirty checkout; no commit is requested.

**Goal:** Give persistent community and company organizations an auditable proposal, decision and delayed rule execution loop.

**Architecture:** A focused Governance component uses OrganizationStore's generation-scoped tables and existing command queue. OrganizationService calls it after pending commands and before resource decisions; approved changes reuse set_rule at the following boundary.

**Tech Stack:** Python 3.11, SQLite, pytest, existing dashboard JavaScript, Node tests.

---

### Task 1: Policy and ballot semantics

Files: create `gaworld/organizations/governance.py`, `tests/test_organization_governance.py`; modify `schemas.py`, `validation.py`, `gaworld/settings/organizations.py`.

- [x] Write tests for strict governance commands and three tally policies; run `python -m pytest -q tests/test_organization_governance.py` and observe the unsupported-command failure.
- [x] Implement `validate_policy(value)` returning `{mode, threshold, voting_days}` and `tally(policy, electorate, ballots)` returning `{yes,no,abstain,participation,eligible,quorum,status,reason}`. Reject unknown fields, booleans as days, invalid choices, and proposal parameters other than max_award_cents.
- [x] Run the same tests until green.

Protocol examples:
```python
{"type": "propose_rule", "organization_id": "care", "agent_id": 1,
 "proposal_id": "p1", "rule": "need_first", "reason": "优先帮助困难成员"}
{"type": "cast_vote", "organization_id": "care", "agent_id": 2,
 "proposal_id": "p1", "choice": "yes", "reason": "同意"}
{"type": "set_governance", "organization_id": "care",
 "governance": {"mode": "member_vote", "threshold": "quorum_majority", "voting_days": 1}}
```

### Task 2: Persistent loop and resident actions

Files: modify `store.py`, `service.py`, `narrative.py`; implement `Governance` in `governance.py`.

- [x] Add real-service failing tests: Day 1 proposal leaves rule v1; Day 2 votes produce approved with rule v1; Day 3 applies rule v2 and uses it for aid. Run `python -m pytest -q tests/test_organization_governance.py`.
- [x] Add proposals/ballots tables and generation-bound commands. Implement `Governance.apply(command, day)`, `resolve(day)`, `execute(command, day)`, `candidates(agent)`, `export(day)`. Extract `_set_rule(org, command, day)` so manual and governed changes share rule persistence.
- [x] Test and implement frozen eligibility, idempotent votes/execution, late ballots, handover/version conflicts, missing members, clean resume, old-generation command rejection and default-off behavior.
- [x] Test and implement action strings `org:propose_rule:<oid>:<rule>`, `org:cast_vote:<oid>:<pid>:<choice>`, `org:leader_decide:<oid>:<pid>:<choice>` and perception of deadlines/own vote/final tally. Governance candidates must remain available while aid is pending.
- [x] Export a separate governance.json alongside completed-day archives, retaining existing economic metrics.

### Task 3: API and dashboard

Files: modify `gaworld/apps/organizations_api.py`, `gaworld/apps/openapi.py`, `site/dashboard/organizations.js`; tests `tests/test_organizations_api.py`, `site/dashboard/organizations.test.js`.

- [x] Add failing API and Node tests for four governance commands, policy controls and proposal→execution presentation.
- [x] Document every command variant in existing OpenAPI oneOf; expose governance_enabled via current-world config. Add command forms with explicit proxy wording and display fixed electorate, tally, dates, old/new rules and execution links.
- [x] Run `python -m pytest -q tests/test_organizations_api.py tests/test_openapi.py` and `node --test site/dashboard/organizations.test.js` until green.

### Task 4: Review and delivery

Files: update `docs/ORGANIZATIONS_TUTORIAL.md`, this plan; preserve unrelated files.

- [x] Request a read-only review via requesting-code-review; reproduce and repair actionable findings with regression tests.
- [x] Run all organization Python tests, affected API/config tests, Node frontend tests, `python -m pytest --suite core`, and Ruff on changed Python files.
- [x] Document the default-off switch, command examples, timeline, modeling assumptions, outputs and recovery limitations. Report actual verification outcomes.

Self-review: all design requirements map to Tasks 1–4; governance changes only rule execution, uses no model call, and stays within the existing organization plugin.


## Completed verification (2026-10-05, Asia/Shanghai)

- `python -m pytest -q tests/test_organization*.py tests/test_organizations*.py`: **238 passed**. This includes 44 governance cases and four real simulator runs (ticks / daily fast-forward, governance off / on), all with mocked model responses.
- Affected OpenAPI, dashboard configuration, world-path and plugin checks: **92 passed, 1 skipped, 616 subtests passed**. The optional openapi-spec-validator dependency is unavailable; route/schema coverage checks passed.
- `python -m pytest --suite core -q`: **472 passed, 1 skipped, 671 subtests passed**. Existing plot font warnings remain.
- `node --test site/dashboard/organizations.test.js`: **16 passed**, including continuous proposal refresh and distinct leader/member instructions. Ruff check, focused format check and `git diff --check` passed.
- Read-only reviewer independently confirmed the backend, API and simulator tests; findings were reproduced with failing regressions and repaired: round-trip leadership handover, execution-ID collision, malformed enums, stale proposal dropdown.
- Browser exercised the real API and OrganizationService using a disposable four-member fixture: Day 2 opened, Day 3 yes + abstain reached participation 2/4 and approved while rule stayed v1, Day 4 executed need_first v2. It preserved reasons, decision and execution command links. Final screenshot and cumulative/archived governance.json are under the task artifact directory `organization-governance/`.
- The verification fixture did not use the active city/world or real model calls. Production configuration remains opt-in. Shared unrelated changes were preserved; no commit was created.
