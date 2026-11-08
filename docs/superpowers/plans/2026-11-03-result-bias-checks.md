# Result bias checks implementation plan

**Goal:** Attach inspectable, result-specific checks to research results; measure optional presentation/wording sensitivity and human-effect discrepancies without calling an LLM judge.

**Architecture:** Pure functions in `gaworld/research/result_checks.py` own versioned cards and conservative interval decisions. `replication_checks.py` owns replication adapters and opt-in paired probes. Existing evaluators, reports and dashboard render the same evidence. Existing ownership and world-scoped stores remain the persistence boundary.

**Tech stack:** Python standard library, NumPy and SciPy Student-t quantiles, pytest, browser JavaScript and node:test.

## Accepted scope and rules

- Research hypotheses, replication result rows and batch model comparisons receive check cards. Historical records with no evidence show untested; no automatic extra calls.
- Replication can opt into reversed choice order and researcher-written alternative questions. Frozen settings show extra calls before running. Canonical answers are restored before comparison. Probe calls never enter the main outcome sample.
- Each numeric item may have a positive, pre-run equivalence margin in original units. Human comparison requires reported sampling uncertainty and design. Paired human contrasts without covariance remain insufficient.
- Use conservative 95% t intervals; equivalence requires the entire interval strictly inside the margin. Missing uncertainty, duplicate respondents, selective missingness and nominal post-selection cannot establish equivalence. Multiplicity is handled within each check family.
- Count failures and missing answers by item/condition/group, including partial answers; do not infer refusal from sentiment or guess missing data.
- Existing score identifiers remain compatible, but labels and interpretation distinguish direction agreement from equivalence.

## Tasks

- [x] Add regression tests for missing evidence, wide intervals, effect disagreement, duplicates, paired missing covariance, canonical remapping and opt-in call counts. Run `python -m pytest tests/test_result_checks.py -q` and verify failures before implementation.
- [x] Implement pure check modules and integrate replication normalization, frozen probe configuration, execution, comparison and exports. Run new tests plus `tests/test_replication.py`.
- [x] Attach cards to hypothesis evaluation and batch comparison. Include cards in Markdown and interpretation inputs. Verify existing research/batch tests.
- [x] Add shared escaped dashboard renderer using existing theme tokens, per-row cards, editable margins and opt-in checks with call estimates. Verify Node rendering/XSS tests and browser light/dark/mobile views.
- [x] Run core suite and lint ratchet, obtain independent code review, fix findings, and document actual coverage and deferred interaction/identity experiments.

## Validation boundary

All development validation uses deterministic fixtures/mocked model calls. No live research experiment is authorized by this implementation task. Group dynamics, factorial identity studies and human-equivalence claims beyond the supplied evidence remain untested.


## Completed validation (2026-11-03)

- Core suite: 515 passed, 1 skipped, 944 subtests passed. The skip is the optional OpenAPI schema validator, which is not installed; existing plotting font warnings remain.
- Final focused suite (result checks, replication, research studies/batches, OpenAPI, ownership and locales): 172 passed, 2 skipped, 966 subtests passed. Skips are the same optional validator and an existing cosmetic locale-order check.
- Browser JavaScript: 5 Node tests passed (escaping, historical untested state and batch rendering); syntax and `git diff --check` passed.
- Lint ratchet: no regressions in 11 changed Python files. Repository totals 1027 findings / 441 unformatted files versus baseline 1040 / 443; installed Ruff differs from baseline, so the tool did not enforce global totals.
- Independent review identified duplicate-probe inference, malformed optional settings, failure-record preservation, model fallback/provenance, and worker context issues. Added regressions and fixed these; the reviewer ended at its usage limit, so there is no separate final clean-review claim.
- Browser used a local fixture HTTP server (no real model calls or account changes): checked per-result evidence expansion, 151-to-51 call estimate change for 50 requested residents, submitted opt-ins plus edited 0.75 tolerance, and downloaded JSON containing prompts hashes, raw probes and planned budget.
- Inspected desktop light and 390px mobile dark screenshots. Fixed compressed mobile table columns with stacked rows; document width remains 390px. Browser console has no errors/warnings in this fixture flow. Screenshots and downloaded fixture evidence are in ignored `output/playwright/`.
- No end-to-end live model, live-account browser, or real-world validity claim. Identity, interaction/memory, mechanism intervention and full-platform adapters remain future work and display untested.
