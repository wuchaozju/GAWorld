# Rumor and disaster implementation plan

**Goal:** Deliver the confirmed design in `../specs/2026-11-10-rumor-disaster-design.md`.

**Architecture:** Keep the existing API/job stores. Add narrowly scoped structured-reply and disaster-context helpers under `gaworld/apps/`; retain injectable model functions and in-memory game state. Add mechanism metadata to new results.

**Tech stack:** Python, pytest, browser JavaScript, Node assertions.

## 1. Reply parsing and measurement
- [x] Add regressions in `tests/test_game_mechanisms.py` for malformed JSON, false strings, absent actions, missing/nonfinite scores and empty denominators; run and observe failure.
- [x] Implement bounded literal parsing in `gaworld/apps/game_reactions.py`; integrate in `disaster_api.py` with independent field validity and diagnostic raw text.
- [x] Aggregate total attempts, valid action/panic/help counts and helper numerator; empty means null. Update obsolete tests that require fabricated values.

## 2. Disaster context
- [x] Add tests for mountain/coastal/water-town stages, explicit versus inferred edges, disconnected residents, simultaneous prior-stage messages, and blackout channels.
- [x] Implement `gaworld/apps/disaster_context.py`; load region and seed relationships with world-aware paths. Expand primary/secondary actions, attach observations and transmissions to results.

## 3. Rumor behavior
- [x] Add a multi-hop low-belief entertainment regression and checks for local prior-round social proof.
- [x] Extend `rumor_api.py` with motives and per-turn events; carry actual utterances along edges, distinguish belief-driven/entertainment forwarding; preserve existing four behavior verbs.

## 4. Display and exports
- [x] Extend `site/dashboard/game-export.test.js` for nulls, denominators, diagnostics, relation and motive records.
- [x] Update disaster/rumor pages, renderers and locale entries; preserve existing tokens and old-result fallbacks.

## 5. Verification
- [x] Run targeted Python and Node tests, core suite, OpenAPI tests, changed-file lint/format checks; resolve regressions caused by this work.
- [x] Review changes against the confirmed design; document validation and limitations in `docs/reports/2026-11-10-rumor-disaster.md`.

Execute inline in the current checkout, preserving pre-existing uncommitted work. No commit, deployment, population regeneration or live paid experiment is needed for delivery.

## Completion notes

- Added `gaworld/apps/game_measurements.py` and thin benchmark hooks after finding downstream archive pooling would otherwise mix legacy/new definitions. Independent field denominators and a mixed-mechanism abstention have regression coverage.
- Targeted tests: 169 passed plus 5 subtests; Node export: 13 passed. Core: 515 passed, 1 skipped; OpenAPI: 11 passed, 1 skipped.
- Independent review: no blocking findings after fixes; 28 mechanism regressions independently passed.
- Existing concurrent changes remain outside this task. Global lint findings are recorded separately in the delivery report.
