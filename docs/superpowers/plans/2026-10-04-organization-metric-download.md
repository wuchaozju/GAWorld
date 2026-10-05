# Organization Metric Download Implementation Plan

> **For agentic workers:** Execute in this session with test-first changes and read-only review. Preserve unrelated edits; leave changes uncommitted.

**Goal:** Complete the approved v1 design's world-scoped CSV/JSON output workflow by letting dashboard users retrieve completed organization metric JSON files for offline rule comparison.

**Architecture:** A focused reader under `gaworld/organizations/exports.py` reads existing generation/day archives and SQLite metadata in read-only mode. `organizations_api` exposes one JSON document envelope containing filename, original content, SHA-256, generation, day and scope. The existing organization page offers a download button pinned to the generation and completed day returned by its overview; it is available to read-only viewers too.

**Tech Stack:** Python standard library, existing world paths and route/OpenAPI patterns, pytest, Node VM tests, browser verification with synthetic data. No model calls or new simulation behavior.

## Design and existing authorization

This continues approved `docs/proposals/2026-10-03-persistent-organizations-v1-design.md` §§8.3/9: management entry points, actual records and JSON/CSV outputs supporting offline comparison. The raw files and comparison CLI already exist. Browser access closes the remote-user gap without adding new organization decisions, an automatic experiment runner or a comparison backend.

`GET /api/organizations/exports/metrics` accepts only `generation_id` and `day`. Omitted generation means current; omitted day means that generation's last completed day. Historical generations predating saved metadata require an explicit day and an existing archive. Always select `generations/<generation>/day-<day>/metrics.json`, never the potentially stale top-level `metrics.json`. Validate generation IDs and positive integer days before file resolution. Current or archived known metadata bounds the requested day. During a later open/incomplete day, the preceding completed archive remains readable. Missing data returns 404; corrupt metadata/JSON or mismatched generation/day/scope returns 409; invalid or duplicate queries return 400.

The reader opens SQLite with `mode=ro`, creates no database/directories, changes no metadata and performs no payment. It uses the active world's effective `organizations.output_dir` and `memory_dir`; client paths or world overrides are rejected. Directory traversal and symlinks escaping the configured export directory are rejected. Existing login/world read authorization applies. The new API is documented in OpenAPI; no dashboard handler branch is needed because `organizations_api` already owns the prefix.

Download the original UTF-8 file text, preserving all integer cents and allowing the saved bytes to match the server SHA-256. The API envelope is not itself the input to `compare`: the UI saves only its `content`. The filename contains generation and day. The UI disables the button before a known completed day and while exporting, pins both IDs at click time, displays failures, and releases its temporary Blob URL. Changes reuse the current page layout and styles.

## Task 1: Completed-export reader and API

Files: create `gaworld/organizations/exports.py`; modify `gaworld/apps/organizations_api.py` and `gaworld/apps/openapi.py`; create `tests/test_organization_exports.py`.

- [x] Add real-service export tests with isolated directories. Verify original bytes/hash and current/history selection. Write a test that calls the API and fails with its current 404.
- [x] Test no database/file creation before the first run, stale top-level exports after a new generation, missing archive, incomplete later day, malformed content and mismatched identity/scope. Test traversal, duplicate/unsupported queries, symlink escape and actual effective-world isolation.
- [x] Implement `read_metrics(output_dir, memory_dir, *, generation_id=None, day=None)` and typed unavailable/invalid export exceptions. Read metadata with SQLite `mode=ro`; preserve raw JSON text and hash.
- [x] Add the exact export branch before normal store opening; document its operation, arguments and error statuses in OpenAPI. Confirm preexisting organization IDs such as `exports` or `metrics` still resolve as details.
- [x] Run `python -m pytest tests/test_organization_exports.py tests/test_organizations_api.py tests/test_openapi.py -q` and Ruff on the new/changed focused files; fix only relevant failures.

## Task 2: Browser download

Files: modify `site/dashboard/organizations.html`, `organizations.js`, `organizations.test.js`.

- [x] Write failing Node VM tests for initially disabled download, read-only viewer access after a completed day, pinned generation/day, exact content saved through a Blob and filename, duplicate-click suppression, failed request and temporary URL cleanup.
- [x] Add `orgDownload` to existing top actions and wire its enabled state from overview metadata. Capture the completed generation/day on click and request the explicit endpoint; save the response `content` as `application/json` without parsing or rebuilding it.
- [x] Keep `exporting` state independent of management writes and refresh; preserve all existing selection-race tests.
- [x] Run `node --test site/dashboard/organizations.test.js` and the Python frontend wrapper. Verify an actual browser against a temporary localhost server using real synthetic organization records and the actual API/JS, then stop that server.

## Task 3: Documentation, review and verification

Files: update `docs/ORGANIZATIONS_TUTORIAL.md`, `docs/FEATURES.md` and this plan.

- [x] Document browser retrieval, the envelope versus saved file, archived queries, scope and original hash. Keep comparison interpretation and funding-history limits unchanged.
- [x] Use the requesting-code-review skill to dispatch a read-only reviewer for completion/identity, path/world isolation, unchanged state and frontend lifecycle. Reproduce and resolve important findings before completion.
- [x] Run all organization test modules, affected OpenAPI/world-path tests, Ruff and `git diff --check`, then `python -m pytest --suite core -q`. Record exact results and material limitations here.

## Self-review

All functionality consumes existing completed files. No schema, payment, default simulation output, rule behavior or model-call path changes. Current generation selection and immutable archives prevent a restarted world's old top-level file from appearing to be current. Browser output can be handed directly to the existing offline comparison command.

## Completion evidence

- Test-first API work: initial new route tests failed (15 failures, 9 passes for already-supported invalid queries) before the reader/route existed. The three new Node download tests also failed before UI implementation. No production simulation or model calls were made.
- Real-service download reader/API tests: **28 passed**. Downloads preserve original UTF-8 bytes/hash, use read-only SQLite and validate current/history/day identity. Tests include new-generation stale-latest exclusion, previous completed day during recovery, metadata-less legacy history with an explicit day, actual account-world path overrides, traversal/duplicate queries, malformed archives, symlinks and unchanged database bytes.
- Review identified a P2 unhandled path-resolution error for circular symlinks. File and directory loop regressions reproduced the exception, then passed after conversion to `ExportInvalid`. A 5000-digit JSON integer also reproduced an unhandled parser `ValueError`, now returned as 409. Independent final review closed the P2 and found no important remaining issue in the limited scope.
- All nine organization Python test modules: **184 passed** with 12 existing plot font warnings. Existing OpenAPI/account/world-path selection: **31 passed, 1 skipped, 616 subtests passed**. All **11 Node frontend tests passed**, including read-only access, exact integer preservation, pinned requests, in-flight duplicate suppression and cleanup.
- Core: **472 passed, 1 skipped, 671 subtests passed**, 3122 deselected, 96 existing plot warnings. The optional `openapi-spec-validator` remains absent. The shared worktree's core selection has increased since the prior 462-pass run; no unrelated changes were edited for this continuation.
- Ruff check passed for `exports.py`, organization API, new tests and the shared OpenAPI module. Ruff format check passed for the focused reader/API/tests; the shared OpenAPI module was kept in its existing layout. `git diff --check` passed.
- Actual browser verification used the current page and API against a temporary localhost server with existing synthetic organization records. Management controls were disabled for a simulated member viewer; the download button was enabled. The actual downloaded file in Downloads and its saved artifact copy matched the source byte for byte, SHA-256 `087d84fc27d281b5caca5272d3b6eaa3b54332cf31252bdceaabdff054fd576d`. IAB did not report its download event, so success was verified from the resulting file and page status instead of the event listener.
- Artifacts: `/Users/cw/.codex/visualizations/2026/10/03/01a100d1-3c40-7c91-bb3e-bdfb8d5a4618/organization-metric-download/`: downloaded JSON copy, `download-verification.json`, `download-preview.jpg` and README. Temporary tab and server have been closed. Documentation explains the raw file versus API envelope and how to hand browser downloads to the existing comparison CLI.
- Default simulation, rules, accounting and schemas were unchanged in this continuation. Work remains uncommitted; unrelated edits were preserved.
