# Research workspaces implementation plan

**Goal:** Deliver the six approved workbench improvements while preserving existing protocols, reports and unrelated checkout changes.

**Architecture:** Keep stores backwards compatible; enforce user/world visibility at every API boundary. Use per-study active handles and bounded admission. Put structured editing and revision rules in a dedicated research module. Extend the existing frontend with persistent source access, editors and actionable checks.

**Tech Stack:** Python, pytest, vanilla JavaScript, existing ownership ContextVars and parallel runner.

## Runtime and workspace isolation

- [x] Write failing user/world list/detail/delete/compile tests and simultaneous-study control tests in tests/test_research_workspaces.py.
- [x] Add workspace predicates and ownership fields to summaries; open owned study routes to members, apply quota gates.
- [x] Replace the single active handle with a per-study map, isolate controls/telemetry/logs and enforce configurable study limits.
- [x] Run research, account, parallel and OpenAPI regressions.

## Editable drafts and preserved versions

- [x] Write failing tests for plan edits/source snapshots, protocol edits/reapproval, post-run revision and unused incompatible quick metrics.
- [x] Add gaworld/research/editing.py for bounded schema validation and safe edits; add plan update and study revise routes, registered in OpenAPI.
- [x] Snapshot source plans at compile time, preserve plan revision history, and normalize only unused incompatible quick metrics with recorded differences.
- [x] Verify saved artifacts and error cases without model calls.

## Frontend and delivery

- [x] Add plan/protocol editors, copy-and-revise, source plan/snapshot access and visible history deletion controls.
- [x] Show blocked reasons beside actions; retain selected implementation plan when opening its study and refresh parallel history independently.
- [x] Verify backend workflows, browser desktop/mobile workflows and owner isolation in a controlled fixture.
- [x] Run core, focused regressions, JavaScript and changed-file lint; request independent review and fix findings.
- [x] Update tutorial/evidence and restart the local service only after checking that no user research is running.

User approved the complete design through the in-chat question. No real-model studies or deletion of existing user records are needed to deliver this implementation.

Validation: core 485 passed/1 skipped; final focused regressions 273 passed/1 skipped (700 subtests); JavaScript 8 tests pass. Read-only current-instance inspection confirms accounts database absent (single-user mode). Full workspace lint retains unrelated inherited failures; task paths are checked separately.
