# Research flow implementation plan

**Goal:** Restore interrupted task tracking and make plans/results understandable at first glance.

**Architecture:** Reuse research APIs and scoped ownership. Extend research-runtime.js with bounded fetch and reusable job tracking; persist planning jobs through a focused Python store. Add deterministic reading summaries shared by API detail and Markdown export. Keep statistical evaluators unchanged.

**Tech Stack:** Python, pytest, vanilla JS, node:test, existing dashboard CSS tokens.

## Tasks (execute inline in this session)

- [x] Add failing frontend regressions for transient failure/recovery, terminal errors, stale responses, request timeout and scoped restore; implement the controller and wire analysis/digest/compile through it.
  Files: site/dashboard/research-runtime.js, research-runtime.test.js, research.js.
  Check: `node --test site/dashboard/research-runtime.test.js`.
- [x] Add failing backend regressions for persisted jobs, interrupted restart, scope isolation, available report while interpreting; implement focused store and research-only model waiting scope.
  Files: gaworld/research/jobs.py, gaworld/llm/call_scope.py, gaworld/apps/research_api.py, gaworld/llm/providers.py, tests/test_research_study.py, tests/test_research_jobs.py, tests/test_llm_call_scope.py.
  Check: `python -m pytest -q tests/test_research_jobs.py tests/test_llm_call_scope.py tests/test_research_study.py`.
- [x] Add reading-summary regressions (missing data, direction-only, incomplete execution, bilingual); implement summaries for API detail and Markdown, then render summary before technical details using existing tokens.
  Files: gaworld/research/reading.py, workbench.py, report.py, tests/test_research_reading.py, site/dashboard/research.js, research.css, locales/en.json, locales/zh-CN.json.
  Check: `python -m pytest -q tests/test_research_reading.py tests/test_research_workbench.py tests/test_research_study.py`.
- [x] Run targeted frontend/backend checks, core suite, changed-file lint and controlled browser acceptance; record exact outcomes and limitations in docs/reports/2026-11-08-research-flow-verification.md.

No real paid experiments or automatic restart of existing runs are needed. Keep unrelated worktree edits intact; do not commit the dirty workspace as a whole.

Completed on 2026-11-08. Independent review found and verified fixes for lost POST replies, wall waiting budgets, storage unavailability, and Dashboard query-list parsing. Browser acceptance is reproducible with `python tests/browser/research_flow_acceptance.py`.
