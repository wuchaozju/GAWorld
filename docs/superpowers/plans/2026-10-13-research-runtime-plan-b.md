# Research runtime Plan B implementation plan

**Goal:** Implement the approved diagnosis/design in `docs/reports/2026-10-13-research-runtime-diagnosis-and-design.md` without changing old protocol execution modes or starting paid studies.

**Architecture:** Extend protocol/spec mode mapping; isolate quick-version creation and log reading in research modules. Use an opt-in SQLite run ledger shared by world processes for provider cooldown, failures and telemetry. Integrate existing study API and polling UI, preserving unrelated dirty changes.

**Tech stack:** Python 3.11+, sqlite3, requests, pytest, plain browser JavaScript.

## 1. Modes, budget and quick study

Files: `gaworld/research/{protocol,study,quick,evaluate,report,backends}.py`, `gaworld/parallel/spec.py`, `tests/test_research_runtime.py`.

- [x] Add failing regression tests: old `fast` resolves to `lean_tick`; `daily_brief` enables day-step long_run; quick clone retains conditions/events/days and concrete sample while selecting first seed; placebo never promotes exploratory verdicts.
- [x] Run `pytest tests/test_research_runtime.py -q` and confirm missing behavior.
- [x] Implement `execution_mode`, explicit run purpose and parent/diff metadata; mode-aware budget breakdown including non-brief calls; block incompatible measures/configs.
- [x] Re-run tests and update the old assertion that incorrectly estimates lean tick as one daily call.

## 2. Provider reliability and telemetry

Files: `gaworld/llm/{run_state,providers}.py`, `gaworld/parallel/runner.py`, `gaworld/research/{backends,provider_check}.py`, `tests/test_llm_run_state.py`.

- [x] Add failing tests for Retry-After seconds/date, waiting budget, shared cooldown, plan-limit classification, consecutive terminal failures, pinned provider, and telemetry isolation.
- [x] Implement opt-in shared ledger via child-process environment; keep global/default simulation output unchanged. Respect server wait without shortening it; abort remaining worlds when research failure budget is exceeded.
- [x] Persist logical requests/provider attempts and phase/slot/cooldown waits. Use list-only Ollama inspection and explicit one-shot generation checks.
- [x] Reject deterministic placeholder briefs in daily-brief research; persist degraded/failed-world information.
- [x] Run `pytest tests/test_llm_run_state.py tests/test_gaworld_llm_fallback.py -q`.

## 3. Log API and study integration

Files: `gaworld/research/run_logs.py`, `gaworld/apps/{research_api,openapi}.py`, `gaworld/research/backends.py`, `tests/test_research_runtime.py`.

- [x] Add failing tests for active and completed manifests, attempt isolation, capped cursor reads, UTF-8 boundaries, rotations, redaction, path traversal/symlinks and unauthorized user/world.
- [x] Implement `GET .../logs`, `POST .../quick`, `POST .../check-provider`; expose ledger snapshots and persisted status. Stamp new studies and preserve admin-only study policy.
- [x] Persist seed references before execution; write survey output and study stage events to files. Keep pause/stop semantics and terminal ETA behavior.
- [x] Register new API schemas and verify `pytest tests/test_openapi.py tests/test_research_runtime.py -q`.

## 4. Browser interface

Files: `site/dashboard/research.{js,css,html}`, locale JSONs, browser-level regression test.

- [x] Add runtime mode selector, quick clone and provider-check controls; show actual population/provider and cost components.
- [x] Add independent log polling with selected seed/world/kind, cursor retention, textContent, 64 KiB response cap, bounded DOM, auto-scroll toggle and final drain.
- [x] Show measured requests/errors/fallbacks, active/wall/paused/queue/provider wait and quality flags; lower polling frequency while hidden.
- [x] Verify a mocked controlled browser session at desktop/mobile widths and the live read-only historical study.

## 5. Verification and review

- [x] Run research/provider/parallel/OpenAPI tests, frontend checks and `pytest --suite core`.
- [x] Run changed-file Ruff/lint ratchet; distinguish inherited backlog from new findings using `/tmp/gaworld-planb-20261013-baseline`.
- [x] Request an independent code reviewer for the Plan B diff, fix important issues, and update the tutorial and implementation evidence.
- [x] No paid research, account/package switch, commit, push or unrelated checkout changes are needed for delivery.

## Delivery evidence

- Focused research/provider/parallel/OpenAPI/fast-forward/manifests: 195 passed, 1 skipped at the broad verification checkpoint; final focused regressions: 171 passed, 1 skipped, 690 subtests, including input snapshots, explicit population changes and credential echo protection.
- Core suite: 485 passed, 1 skipped, 742 subtests. The skip is the absent optional OpenAPI validator; existing plot font warnings remain.
- JavaScript log polling: 4 tests pass, including reactivating logs when an already open protocol starts running.
- Controlled browser fixture proves incremental log display, final drain, redaction and runtime counters; 390px layout has no horizontal overflow. It does not establish scientific efficacy or a real-model speedup.
- Historical production study logs were read through the new endpoint. Existing output artifacts were not rewritten.
- Independent review identified and drove fixes for cooldown peers, sample/mode/provider identity, wire attempts and credential source coverage.
- Full-worktree lint ratchet remains blocked by unrelated existing changes in games/holiday modules; task delta is checked against the saved dirty baseline without expanding those changes.
