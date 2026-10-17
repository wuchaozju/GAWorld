# Research batches implementation plan

> Execute inline in this session, task by task, with failing regression tests before implementation. User confirmed implementation; no further design approval is needed.

**Goal:** Model/city/repetition comparisons and portable Python experiments in the research workbench.

**Architecture:** Persist a private batch with immutable protocol, matrix and input snapshots. Each cell launches an ordinary study using an explicitly supplied isolated base config. A coordinator handles admission and lifecycle; deterministic comparison and portable import/export remain separate modules.

**Tech Stack:** Python stdlib, existing GAWorld research/parallel engines, NumPy statistics, vanilla JavaScript and pytest.

### 1. Batch matrix and persistence
- [x] Add `tests/test_research_batches.py`: expand 2 models × 2 cities × 3 repetitions; fixed/vary seed policy, invalid/oversized matrix, safe IDs and ownership.
- [x] Run `python -m pytest tests/test_research_batches.py -q` and observe missing batch functionality.
- [x] Create `gaworld/research/batches.py` for bounded matrix, atomic store, protocol fingerprint and task identities.

### 2. Comparison and reporting
- [x] Add regression examples for known effects, missing tasks, mixed code/model/mode/sample, selected subsets and non-independent fixed-seed repetitions.
- [x] Create `gaworld/research/batch_compare.py`, using run-level effects, sample SD and existing t interval; preserve exclusions and denominators.

### 3. Isolated API execution
- [x] Add API tests for city isolation, snapshot freezing, permissions, controls, admission queue and interrupted tasks.
- [x] Create `gaworld/apps/research_batches_api.py` and `gaworld/research/batch_execution.py`; extend `_preflight`/`_launch_run` with an internal optional config, retaining existing defaults.
- [x] Register route before research delegate; document routes in OpenAPI and member/quota policy.

### 4. Portable experiment export/import
- [x] Add ZIP inspection, tamper rejection, configuration validation and real loopback HTTP tests of generated Python (fake simulation/model backend).
- [x] Create `gaworld/research/batch_export.py` and packaged runner template: localhost API, environment credentials, optional world selection, dry check, progress, resume via batch ID, report/JSON download.

### 5. Workbench UI and documentation
- [x] Add `site/dashboard/research-batches.js` with tested pure rendering helpers and a panel using existing visual tokens. Expose source-study events from `research.js`; add batch history, controls, selected task comparison and downloads.
- [x] Update `docs/RESEARCH_WORKBENCH_TUTORIAL.md` with scope, statistics, execution and local setup.

### 6. Verification
- [x] Run targeted pytest, Node frontend tests, OpenAPI and core suite; format new Python, lint ratchet and diff checks.
- [x] Inspect live UI in desktop and narrow widths using mocked/read-only fixtures; do not launch paid models.
- [x] Self-review lifecycle, comparison boundaries, export secrets and persisted evidence; fix findings and record measured results.
