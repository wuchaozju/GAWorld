# Population education implementation plan

**Goal:** Supply adult student samples and consistent education editing/filtering across generation, Studio, games and replication.

**Architecture:** Central education vocabulary and legacy reader in `gaworld/population/education.py`. CSV is the structured source, explicit legacy prose is a fallback. Generation uses a separate RNG and reports unavailable capacity. Existing active-world write paths own additions.

**Tech stack:** Python dataclasses/pytest, existing HTTP routes/OpenAPI, vanilla JavaScript/Node tests.

- [x] Add regression tests in `tests/test_population_education.py`: generate 500 college-town residents with seed 42, require adult students, verify completed qualification and enrollment differ; round-trip CSV and explicit legacy profiles; apply intersected replication filters.
- [x] Run `python -m pytest tests/test_population_education.py -q` and observe missing behavior before implementation.
- [x] Extend `schema.py`, `synth.py`, `writer.py`, `report.py`: `education`, `student_status`, adult student target, feasible assignment and target/actual report. Centralize vocabularies and reading/filter validation in `education.py`.
- [x] Update `interview/roster.py`, `apps/residents.py`, `apps/games_api.py`, city additions and imports so structured fields survive reads, new residents and Studio edits. Test temporary-world files only.
- [x] Extend `research/replication.py` and `apps/replication_api.py`: retain education/student/occupation constraints in normalized specs and groups, extract reported eligibility, filter before seeded sampling, expose eligible counts via check, stamp sampled demographics.
- [x] Add preview/append student samples in `apps/student_samples_api.py`, with active-world paths, stale-preview rejection and policy/OpenAPI entries; exercise preview without writes and duplicate submission failure.
- [x] Add Studio identity controls, filters, append preview; roommate intersected filters and filtered random selection; replication editable filters/count; generation student ratio control. Reuse existing theme tokens and add both locales.
- [x] Run targeted Python and Node tests, OpenAPI/accounts tests, core suite, changed-file lint/format, and inspect final diff without overwriting concurrent changes. Document operation and actual limits.

Validation and concurrent scoring-test failures are recorded in `docs/reports/2026-11-09-population-education.md`. Existing city data was not regenerated; browser additions used temporary QA seeds only.
