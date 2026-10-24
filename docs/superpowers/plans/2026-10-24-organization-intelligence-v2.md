# Organization Intelligence OI-2 Implementation Plan

**Goal:** Deliver and run the approved zero-model-call, paired organization-mechanism pilot in the research workbench.

**Architecture:** A standard-library-only frozen engine generates role-limited evidence and executes bounded actions. SQLite commits an episode's validated action log, score and next organization state in one transaction. A process lock and reclaimable leases allow the same study to resume without applying an episode twice. A separate subprocess imports the study's verified source bundle, independent of later workspace edits.

**Tech Stack:** Python 3.11+, SQLite, existing Dashboard routing/ownership, vanilla JavaScript, pytest and Node tests.

Implementation executes inline under the user's “继续” authorization; preserve the dirty checkout and historical OI-1 artifacts. No paid requests or commits.

## Files and boundaries

- `gaworld/research/organization_intelligence/v2/protocol.py`: immutable factorial design and validated parameters.
- `environment.py`: hidden task truth, permitted role observations and paid verification.
- `engine.py`: personal versus organizational memory, finite action policy and objective costs.
- `queue.py`: transactionally persisted task graph, leases, idempotent commits and pause/resume.
- `report.py`: completeness gates, paired seed contrasts and honest Markdown report.
- `build.py`, `worker.py`: source snapshot, build verification and isolated worker CLI.
- `gaworld/apps/organization_intelligence_v2_api.py`: world-scoped ownership, version handshake, freeze/run/pause/export.
- `routes.py`, `openapi.py`, `accounts/policy.py`: documented delegate and zero-call quota handling.
- `site/dashboard/organization-intelligence-v2.js`, existing research HTML/CSS: primary OI-2 workflow with historical OI-1 accessible.
- `tests/test_organization_intelligence_v2*.py`, frontend Node tests: mechanism, fault recovery, bundles and API access boundaries.

## Checkpoints

- [x] Write and run failing tests for the 8-cell/seed protocol, reproducibility, private-view isolation, turnover and budgets.
- [x] Implement finite rules, deduplicated evidence, paid checks, training-only feedback and frozen test memory. Test reliable/unreliable information and costly verification without assuming positive effects.
- [x] Write and run failing durable-queue tests, then implement dependency-linked episodes and atomic action/state commits. Inject interruptions after 7/65/107 commits and before commit; restart same ID; reject duplicate/different commits.
- [x] Freeze the actual executable source into a build bundle; verify every hash before worker import. Test workspace mutation versus frozen execution and corrupt bundle rejection.
- [x] Write and run API tests before wiring documented routes, owner/world isolation, explicit version handshake and zero-provider quota handling.
- [x] Add workbench controls for freeze, start/resume, pause, progress, seed/cell results, runtime identity, protocol and report download; retain OI-1 historical links.
- [x] Review with the code-review skill, fix findings, run focused tests, core suite, lint ratchet and browser flow.
- [x] Run the approved 10-seed pilot: 400 training + 1,600 held-out episodes, 80 test cells, 0 external requests. Verify persisted completion and publish the report and limitations.

Completed study: `OI26bd726172dbe4c6faeaa6696`. Frozen worker build: `e23eea16caa24908c2e7d959b53f36fb4c95b2baa6ac6a89c973fdf3f4575309`. Browser, HTTP exports and SQLite agree on 2,000 episodes and 11,196 action records. Actual version loading uses a verified source-bytes loader, including a regression against injected unchecked `.pyc` files. Review additionally hardened pause/resume transactions, exclusive report publication and recovery after the last episode but before export.

## Acceptance commands and invariants

`/opt/homebrew/Caskroom/miniconda/base/bin/python -m pytest tests/test_organization_intelligence_v2.py tests/test_organization_intelligence_v2_api.py -q`

`node --test site/dashboard/organization-intelligence-v2.test.js`

`/opt/homebrew/Caskroom/miniconda/base/bin/python -m pytest --suite core -q`

`/opt/homebrew/Caskroom/miniconda/base/bin/python scripts/lint_ratchet.py`

Expected: complete 8-cell pairing per seed, deterministic replay, no provider imports/calls in the engine, no test feedback, valid action budgets, unchanged old records, immutable source manifest and executable build identity. Incomplete studies report progress only; no treatment contrasts. Mechanism simulations are not human evidence, and no LLM deliberation is claimed.
