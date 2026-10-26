# Organization intelligence redesign implementation plan

> For agentic workers: execute the approved design task by task, using test-first changes and code review at integration checkpoints. Implementation stays in the current checkout to preserve the existing work.

**Goal:** Complete the six-step organization comparison workflow and reuse the exact tested rules in cooperation sessions.

**Architecture:** Pure organization schemas and a shared bounded message-passing executor live in `gaworld/collaboration/`. A comparison package owns benchmarks, immutable protocols, paired execution and statistics. Delegate APIs apply user/world isolation; the existing research and collaboration pages consume them.

**Tech Stack:** Python 3.11+, pytest, standard-library JSON/CSV/statistics, existing LLM router, vanilla JavaScript and Node tests.

## Task 1 — Shared rules and execution

Files: create `gaworld/collaboration/organization_methods.py`, `organization_engine.py`; tests `tests/test_organization_methods.py`.

- [x] Write and run failing tests for deterministic random edges, invalid/custom rules, previous-round recipient filtering, hidden-information exclusion, bounded calls, voting ties, and checkpoint replay.
- [x] Implement `normalize_method(payload)`, `baseline(kind, slots)`, `method_hash(method)` and `run_method(method, members, task, llm, seed, limits, state, checkpoint, before_call)`.
- [x] A caller returns JSON answers; only supplied public task/observations enter prompts. Store every completed call before advancing. Resume replays matching calls without network activity.
- [x] Run `python -m pytest -q tests/test_organization_methods.py`.

```python
def test_independent_members_do_not_receive_other_messages():
    prompts = []
    def call(prompt, **kwargs):
        prompts.append(prompt)
        return '{"answer":"A","message":"PRIVATE-SENTINEL"}'
    result = run_method(baseline('independent', 2), members, public_task, call)
    assert result['answer']['answer'] == 'A'
    assert all('PRIVATE-SENTINEL' not in p for p in prompts)
```

## Task 2 — Benchmarks and deterministic analysis

Files: new `gaworld/research/organization_intelligence/comparison/{__init__,benchmarks,analysis}.py`; tests `tests/test_organization_comparison_workbench.py`.

- [x] Write failing tests for JSONL/CSV field mapping, duplicate IDs, objective/constraint scoring, local observations and hidden answer stripping.
- [x] Add two seeded built-in task families, registered scoring modes, strict imported data validation and public-input projection.
- [x] Write failing tests for paired differences clustered by question, missing/duplicate cells, exploratory sample sizes and negative results.
- [x] Implement seeded bootstrap and fixed decision thresholds; export per-question rows and a deterministic Markdown report.
- [x] Run `python -m pytest -q tests/test_organization_comparison_workbench.py`.

```python
def test_missing_arm_never_produces_advantage():
    result = analyze([{'task_id':'q1','repeat':0,'arm':'candidate','score':1}], expected=2)
    assert result['verdict'] == 'incomplete'
```

## Task 3 — Durable comparison service

Files: new comparison `store.py`, `protocol.py`, `runner.py`, `material.py`; extend the workbench tests.

- [x] Write failing tests proving save does not call a model, immutable hashes detect tampering, pause/restart reuses completed calls, and failed attempts remain auditable.
- [x] Implement atomic scoped storage and immutable experiment snapshots, model fingerprint, execution version and task/member hashes.
- [x] Implement balanced paired order, isolated per-cell state, pause/resume/stop, ordinary invalid-answer scores and infrastructure-interrupted state.
- [x] Implement material extraction with source quotes, explicit inferred rules and unsupported mechanism errors.
- [x] Run service tests using deterministic fake LLMs; no external model calls are needed for these checks.

## Task 4 — APIs and ownership

Files: new `gaworld/apps/organization_comparison_api.py`, `organization_methods_api.py`; modify `routes.py`, `openapi.py`, `accounts/policy.py`; tests `tests/test_organization_comparison_api.py`.

- [x] Add failing tests for create/run/pause/resume/results/export/save-method, provider drift, quota gating, and cross-user/world rejection.
- [x] Register comparison routes before the existing OI prefix. Add OpenAPI entries for every route and structured query parameters.
- [x] Use request-scoped paths, ownership-stamped records and `ownership.spawn()`; recheck visibility on every mutation/export.
- [x] Expose model options, built-ins, import preview and material analysis. Keep old OI interfaces reachable.
- [x] Run API and OpenAPI tests.

## Task 5 — Cooperation integration

Files: modify `collaboration/models.py`, `service.py`; new `organization_runner.py`; adjust collaboration creation/lookup in `dashboard_server.py`; extend collaboration service/API tests.

- [x] Write failing tests for selected method version, immutable snapshot, missing/incompatible slots and default-path compatibility.
- [x] Resolve method references server-side, map role slots to selected residents, dispatch the same executor and write normal session events/artifacts.
- [x] Isolate cached dashboard cooperation services by user/world/configuration; preserve existing default cooperation behavior.
- [x] Extend existing session OpenAPI fields and run collaboration regression tests.

## Task 6 — Six-step research interface

Files: new `site/dashboard/organization-comparison{,-core}.js`, `organization-comparison.css`, associated Node tests; modify `research.html`.

- [x] Add failing pure-core tests for progression, material/benchmark payloads, settings invalidation, safe rendering and status/result presentation.
- [x] Add six-step navigation, editable sourced rules, baseline cards/communication graph, built-in/imported benchmark preview, matched setup, explicit save/start, progress and report/library actions.
- [x] Keep old OI panes as historical/topic experiments. Use existing theme tokens and English/Chinese dictionary, responsive layout and keyboard controls.
- [x] Run Node tests and syntax checks.

## Task 7 — Cooperation picker and acceptance

Files: modify `site/dashboard/collaboration{.html,.js,-core.js}`, locales as needed; add picker tests; add verification report under `docs/reports/`.

- [x] Add an organization picker showing provenance, evidence range, slots and version; include only an ID/version in create requests.
- [x] Run focused Python/Node regressions, OpenAPI tests, `pytest --suite core`, lint ratchet and whitespace checks; preserve pre-existing failures with evidence.
- [x] Inspect real served research/cooperation pages in light/dark/mobile, run the workflow with controlled fixture calls, and record which checks use real external model calls.
- [x] Request independent code review, fix actionable findings, and report remaining material limits candidly.

## Scope self-review

Tasks 1/5/7 cover reuse; 3/4/6 cover material and six-step workflow; 2/3 cover benchmark support, fairness, inference and reports; 4/5 cover permissions and legacy compatibility. No change to the simulation entry point or unrelated working-tree files is required.

## Completion evidence

Implemented and reviewed on 2026-10-26. See `docs/reports/2026-10-26-organization-intelligence-redesign-verification.md` for exact test results and controlled browser evidence. No external model study was launched.
