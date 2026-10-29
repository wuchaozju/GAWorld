# Organization intelligence implementation plan

**Goal:** Add an executable, preregistered organization-intelligence template to the research workbench and start the authorized first exploratory study.

**Architecture:** A standalone research experiment package under `gaworld/research/organization_intelligence/`, following the existing policy/replication workbench delegates. It does not change the city simulation loop or default run comparability. An API delegate provides frozen creation, explicit launch, progress, stop and export. Artifacts are user/world scoped. Existing city seeds and live organization accounts are read-only.

**Tech stack:** Python, pytest, existing LLMRouter/RunLedger and ownership context, plain dashboard JavaScript.

## Frozen first-study design

Title: 人换了，组织还会吗？ Version OI-1.1. Exploratory, 3 independent seeded blocks; each block samples 3 incumbent and 3 replacement adults without replacement. Same roster and novel tasks across matched conditions. Different blocks may share residents; independent model sessions and task seeds, not a claim of independent human samples.

Task: choose one of four rescue plans. Each has three integer attributes observed by separate roles. Utility is a weighted sum with a per-block hidden permutation of weights 1, 3, 7. During three training tasks public feedback reveals all plan utilities, never hidden weights. Three held-out tasks provide no outcome feedback. Training and test instances differ. The scorer alone receives the hidden weights.

Training modes: organized communication, independent aggregation, pooled single resident. Each task uses exactly four capped model requests: three role reports then coordinator; independent mode's fourth call refines role 0 privately before deterministic plurality; pooled mode uses four successive passes by the same persona with all observations. Per-role personal history stores only observations/messages received and public training feedback. A single additional organized archive call after training synthesizes shared experience; this one-call archive cost is reported separately.

Test arms: organized incumbent/archive, incumbent/no archive, 100% replacement/archive, replacement/no archive; independent aggregation with incumbent private histories; pooled agent with its training history. Test branches clone training state and never learn from test results. Removal means withholding only the explicit shared archive; incumbent memories remain intact. Replacement receives no incumbent private memory. This tests transfer and retention, not spontaneous formation, environment adaptation or general intelligence.

Budget: 3 × (3 training modes × 3 tasks × 4 requests + 1 archive + 6 test arms × 3 tasks × 4 requests) = 327 planned requests, within the user-approved approximate 333. Per-call output ceiling 2048 tokens, same temperature .3, bounded input characters. No model fallback or application repair calls. Abort on first provider/parse error; preserve partial artifacts without comparative inference. First scientific request also tests live connectivity. Pin MiniMax-M3 and freeze model fingerprint, roster, tasks, protocol and code fingerprints before launch.

Primary outcomes: held-out normalized utility (chosen / optimum) and optimum-choice accuracy. Secondary: communication/input/output characters and actual HTTP attempts. Paired block contrasts: organized versus independent; organized versus pooled; archive effect after replacement; turnover effect with archive; turnover-by-archive difference. Report block estimates and means descriptively, no significance claims with n=3. Reject incomplete cells from comparisons. Invalid output is missing data, never zero performance. Output tokens/monetary cost unavailable unless returned by transport; do not substitute character counts.

## Tasks

- [x] Protocol/task tests first: deterministic tasks, exact budgets, strict validation, information separation, turnover memory boundaries, objective scoring, incomplete-data gate.
- [x] Implement `protocol.py`, `experiment.py`, `analysis.py`, `store.py`: frozen artifacts, audit JSONL, SHA-256, report generation.
- [x] Implement `gaworld/apps/organization_intelligence_api.py`; register explicit routes and OpenAPI; member quota gate, owner/world checks, pinned provider and atomic start/stop admission. Persist each request and terminal failures. No automatic restart/retry.
- [x] Add workbench tab/template with model selection, repeats, draft protocol preview, explicit start, live progress/telemetry/logs and export, existing tab controller and styles.
- [x] Run focused pytest including API ownership, routes/OpenAPI and frontend behavior; lint ratchet/diff checks and core suite. Inspect real API and browser layout.
- [x] Save first study with approved MiniMax-M3 / current Wuzhen city / seed 20261020 / repeats 3. Start once through API after validation; verify nonzero live telemetry and artifact persistence. Follow to completion if feasible, otherwise preserve observable job and state exact status.

## Acceptance and execution boundaries

No unrelated dirty changes staged or committed. Fixture success is implementation evidence only. The live study is separately labelled exploratory; partial completion cannot establish an organizational benefit. Model call authorization was explicitly confirmed by the user on 2026-10-20. Stop is cooperative at request boundaries, no unsafe thread termination. Process restart marks an orphaned running job interrupted; another launch creates a new immutable study rather than silently resuming or changing its protocol.

## Execution record

- OI483361061c3f4348b4f228c7 (OI-1): stopped at 12 responses after identifying ambiguous array/plan indexing in the task interface. Excluded from comparisons; diagnostic.md explains the correction.
- OIa6c87ad6c429489f832ce013 (OI-1.1): task interface corrected with named attributes, explicit plan IDs, message provenance and role instructions. Verified population, model, task bank, utilities, randomized order and request budget identical to OI-1. Started through the actual workbench UI.
- OI-1.1 failed at response 11 because the model inserted unescaped double quotes inside its JSON message. All 11 HTTP requests succeeded. The preregistered stop-on-format-error rule applied; no repair, retry, model fallback or silent continuation. No held-out comparison is available. Total actual calls across both records: 23.
- Template, API, persisted artifacts and real UI verified. Execution-start scope completed; scientific study remains incomplete and requires a separately versioned recovery protocol before another run.
