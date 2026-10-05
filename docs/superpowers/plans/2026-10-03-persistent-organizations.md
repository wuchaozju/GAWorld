# Persistent Organizations Implementation Plan

> **For agentic workers:** Execute the approved design task by task with tests first and independent code review. The referenced subagent-driven-development/executing-plans skills are unavailable in this installation; use the available writing-plans, test-driven-development and requesting-code-review workflows.

**Goal:** Deliver persistent community aid and company hiring with finite accounts and auditable outcomes.

**Architecture:** World-scoped SQLite stores organization identities, rules, queued commands, frozen decisions and transfer receipts. A default-off plugin drives daily execution and resident actions; public economy payment functions route wages and preserve conservation. Dashboard and CLI enqueue commands rather than modifying simulation state.

**Tech Stack:** Python 3.11, stdlib SQLite, pytest, existing kernel bus/recorder and vanilla dashboard JavaScript.

Approved specification: `docs/proposals/2026-10-03-persistent-organizations-v1-design.md`. Preserve all unrelated uncommitted edits. Work in this checkout because current dependencies are uncommitted. Do not stage or commit unrelated work.

## 1. Durable organization service
Files: `gaworld/organizations/{__init__,schemas,store,rules,service,narrative}.py`, `tests/test_organizations.py`.
- [x] Write and run failing tests for command idempotency, valid leader handover, frozen equal/need aid decisions, finite vacancies, single employer, clean resume, identity mismatch and missing/damaged payment receipt.
- [x] Implement validated cent amounts, versioned SQLite state, command queue, execution lease, transactions and batches; deterministic seeded ranking independent of kernel RNG.
- [x] Verify conservation through the public economy transfer adapter, arrears-first funding, and export metric denominators with generation/day labels.
Run: `python -m pytest tests/test_organizations.py -q`. Expected: passing real state-transition assertions.

## 2. Conservative finance interface
Files: `gaworld/economy/finance.py`, `tests/test_organization_finance.py`.
- [x] Write and run failing tests that aid preserves labor tax base, wages debit the employer exactly once, partial wages create arrears, receipt replay never double credits, daily coarse/paid leave/bonus use the same payer, and disabled behavior retains audit columns.
- [x] Add public account registration/funding/transfer functions and a wage routing helper. Persist receipt with recipient economy JSON atomically; reject incompatible receipts. Keep investment and merchant transfers on their existing sources.
- [x] Include organization balances in conservation audit only when enabled; save economic account checkpoint for clean resume.
Run: `python -m pytest tests/test_organization_finance.py tests/test_economy_module.py tests/test_employment_events.py tests/test_travel_leave_and_compression.py -q`.

## 3. Plugin and resident participation
Files: `gaworld/organizations/{plugin,validation}.py`, `gaworld/settings/organizations.py`, `gaworld/settings/defaults.py`, `gaworld/plugins/__init__.py`, `gaworld/sim/_action.py`, generic startup/action hooks, `gaworld/city/config.py`, `gaworld/core/run_manifest.py`, `tests/test_organization_plugin.py`.
- [x] Write and run failing tests for default-off no output/RNG change, actual controlled application actions, member perception, daily fast-forward and preflight rejection of month/year/cluster/economy-off combinations.
- [x] Add default-off configuration and isolated output paths. Initialize organization service after economic initialization, handle daily commands before agent actions, export after economic settlement, and fail closed on unresolved transactions.
- [x] Ensure startup failures propagate outside warning-only plugin callbacks and preserve inactive members.
Run: `python -m pytest tests/test_organization_plugin.py tests/test_kernel_plugin_e2e.py tests/test_world_paths_run_root.py -q`.

## 4. Management API, CLI and interface
Files: `gaworld/apps/organizations_api.py`, route/OpenAPI/account policy registration, `gaworld/organizations/__main__.py`, `site/dashboard/organizations.{html,css,js}`, console navigation, `tests/test_organizations_api.py` and frontend tests.
- [x] Write and run failing tests for current-world isolation, forbidden paths/unknown command fields, owner/admin authorization and pending 202 status.
- [x] Add organization list/detail/history/command status plus durable command submission; CLI lists/queues the same commands. Build community/company forms and actual balance/arrears/history views with explicit pending labels and funding source.
Run: `python -m pytest tests/test_organizations_api.py tests/test_openapi.py tests/test_accounts.py -q`; `node --check site/dashboard/organizations.js`.

## 5. Documentation and final verification
Files: `docs/ORGANIZATIONS_TUTORIAL.md`, `docs/FEATURES.md`, `docs/FEATURE_MAP.html`, example configs under `gaworld/organizations/`.
- [x] Document activation, normal resume/reset, seed isolation, both pilot rules, explicit funding, unsupported modes, raw metric exports and recovery limitations.
- [x] Run targeted suites, `python -m pytest --suite core -q`, changed-file lint, frontend verification and independent code review. Fix important findings and rerun affected tests.
- [x] Record completed checks and any preexisting failures here; final response reports actual implementation and verification, without claiming live scientific validity.


## Completed verification

- Organization modules, real finance adapters, API/CLI and both full simulator paths: 95 passed (12 existing CJK font warnings). Models were mocked; no real network or paid inference.
- Finance/employment regressions plus plugin preflight: 101 passed. Posted contract salary and its shock audit now agree without drawing the global economy RNG.
- Final core suite: 462 passed, 1 skipped, 2939 deselected, 651 subtests passed. The skip requires the optional openapi-spec-validator dependency; 96 existing font warnings.
- New Python files pass Ruff check and format check. Shared preexisting files still have lint findings; finance's five existing non-import findings were verified against its saved pre-change baseline. No broad unrelated formatting was applied.
- JavaScript syntax check and all 6 Node tests pass. Both example configurations validate.
- Independent review findings fixed: actual family shape and resident age, employer switching, inactive wage reserves, known-receipt reconciliation, historical generation audit isolation, Reset+Run preflight, accountless family dependants, and polling preserving management form inputs.
- Browser verification used a temporary localhost mock API and synthetic residents, never the live population/economy. Company creation and job publication show pending commands; salary 4200.50 submits as 420050 cents. Form data survives multiple five-second polling cycles. A synthetic-data screenshot is saved as a task artifact.
- Metrics retain frozen age/gender/employment group counts and refusal reasons. Per-day generation snapshots preserve cumulative series; exports are raw data, not research-workbench pre-registered verdicts.
- Scope remains single-machine tick/daily fast-forward, clean day-boundary resume, explicit funding, default disabled. Month/year, distributed worlds and arbitrary tick-crash automatic recovery are excluded.

All changes remain uncommitted; unrelated existing edits were preserved.

## Continuation: persistent identity and management boundaries

User requested continuation after the initial delivery. Complete the approved stable-identity design and fix management defects; keep the existing default-off and day-only scope.

- [x] Add `update_profile` (`name` and/or `goal`) through the same queue. Reject empty names and unknown identity/funding fields. Preserve ID, generation, members, rules, balance and prior decisions; store before/after in command audit. Files: schemas/service, API OpenAPI, JS forms, existing organization tests.
- [x] Archive generation runtime metadata when starting a new generation. Historical list reads return that generation's completed day/recovery flag (unknown for older untracked generations), and identify the view as read-only. Files: store, organizations_api, API tests.
- [x] Reproduce delayed detail responses and rapid selection using a Node VM test of the actual dashboard script. Ignore obsolete responses, request a fresh load after selection changes during loading, and disable management submission until detail and selection agree. Preserve form inputs during polling.
- [x] Review close/member lifecycle with independent reviewer; write a failing regression before fixing verified defects. Run targeted organization tests, affected existing tests, core suite, lint and mocked browser workflow. Update tutorial with concrete commands and final results.

## Continuation verification (2026-10-04)

- Organization suites: 121 passed, including real economic persistence and mocked root tick/daily fast-forward runs; 12 existing CJK font warnings. Existing finance/employment/travel/OpenAPI regression selection: 130 passed, 1 skipped, 596 subtests passed. The skip still requires optional `openapi-spec-validator`.
- All 8 Node frontend tests pass, including profile command validation and a delayed-response selection race in the actual dashboard script. New Python files pass Ruff check and format check (20 files). Both example configurations validate.
- The changed finance file has exactly the same five preexisting Ruff findings as the saved pre-organization baseline; travel has one preexisting unused `noqa`. No unrelated formatting or fixes were applied.
- Independent review closed the verified defects: restored departed employment, pending absent-worker exits before all day-start payers, current-day queued termination before travel pay, employment statistics after hiring/removal while preserving today's macro override, arrears not replacing current daily fast-forward wages, and zero/partial paid leave not creating duplicate wage obligations. Real failing regressions were observed before these fixes. The final read-only review found no important unresolved organization issue.
- Returning workers with later external employment (including the same occupation) keep their new job. Early preparation marks the day open before changing employment; an interrupted preparation fails closed, and repeating preparation cannot reopen a completed day.
- Browser verification submitted a profile-update command to a temporary localhost mock with synthetic residents. The queue visibly shows pending status; the screenshot is saved at `/Users/cw/.codex/visualizations/2026/10/03/01a100d1-3c40-7c91-bb3e-bdfb8d5a4618/organization-profile-preview.png`. The temporary preview tab/server are no longer running. No live residents, network models, or production payments were used.
- Final complete core run: 462 passed, 1 skipped, 3014 deselected, 667 subtests passed; 96 existing font warnings. Shared OpenAPI/plugin guards separately passed 14 tests and 612 subtests, with the same optional dependency skip. Concurrent game-route documentation was completed in the shared worktree before this final rerun; its earlier temporary failure is resolved. No unrelated game implementation was edited for this task.

Implementation and tutorial are complete within the existing default-off, single-machine, daily scope. Changes remain uncommitted.
