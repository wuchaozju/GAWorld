# Research Reliability Implementation Plan

> **For agentic workers:** Execute the approved design task by task, using isolated module ownership and independent code review. Preserve unrelated working changes; do not commit them.

**Goal:** Make research assessment auditable, budget admission consistent, mode changes explicit, and research/population failures recoverable and diagnosable.

**Architecture:** Add bounded assessment/source normalization, one budget policy resolver and approval fingerprint, and atomic HTTP reservations in the shared research ledger. Reuse job tracking patterns for population; render backend contracts through small frontend modules and the existing pages.

**Tech Stack:** Python 3.11+, pytest, SQLite, vanilla JavaScript/Node tests, existing dashboard API, agent-browser fixtures.

**Approved spec:** `docs/superpowers/specs/2026-11-10-research-reliability-design.md` (user confirmed 2026-11-10).

---

## Ownership and sequence

The assessment worker owns `gaworld/research/assessment.py`, `workbench.py`, assessment tests and a standalone frontend renderer. The population worker owns durable population jobs, `population_api.py`, `population.js`, and its recovery tests. The runtime worker owns `gaworld/llm/run_state.py`, `providers.py`, a diagnostic classifier, and related tests. The coordinator owns budget policy, protocol/API admission, frontend integration, OpenAPI/account additions, docs and end-to-end validation. Workers must not overwrite existing unrelated changes.

### Task 1: Explainable assessment and paper evidence

Files: create `gaworld/research/assessment.py`, `tests/test_research_assessment.py`, `site/dashboard/research-assessment.js`; modify `gaworld/research/workbench.py`; integrate via existing `research.js`/HTML by coordinator.

- [x] Write tests that fail for missing assessment functions and new plan/digest fields. Exercise complete/unknown rubric, adversarial model total, old score, confirmed digest, source references, per-design preservation and truncation.

```python
def test_incomplete_rubric_cannot_score():
    from gaworld.research.assessment import normalize_assessment
    result = normalize_assessment({"dimensions": []})
    assert result["score"] is None
    assert result["status"] == "pending"
```

- [x] Run `python -m pytest tests/test_research_assessment.py -q` and verify failure, then implement rubric v1 with weights 25/25/20/20/10 and 0–4 evidence-backed bands. Preserve legacy scores as legacy; never invent missing evidence.
- [x] Normalize original design fields with bounded strings and checked source locators. Preserve source hash, input length and used range; expose PDF page/text-page counts and paragraph locators. Retain manual confirmation and provide per-design mappings.
- [x] Extend prompt/schema and Markdown renderer; add pure JS renderer with English/Chinese labels, safe text escaping, and a Node test showing pending/legacy scores.
- [x] Run new tests plus `tests/test_research_workbench.py tests/test_research_reading.py tests/test_research_inputs.py` and assessment Node tests.

### Task 2: Runtime HTTP budget and fault classification

Files: modify `gaworld/llm/run_state.py`, `gaworld/llm/providers.py`; create `gaworld/llm/diagnostics.py`, `tests/test_research_request_budget.py`, `tests/test_llm_diagnostics.py`.

- [x] Write concurrent reservation tests first, proving a cap of 3 permits exactly 3 sends across workers and rejects further attempts before network dispatch.

```python
def test_http_reservations_stop_before_send(tmp_path):
    from gaworld.llm.run_state import RunLedger
    ledger = RunLedger(str(tmp_path / "run.sqlite"))
    ledger.configure_http_budget(1)
    ledger.reserve_http_attempt()
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        ledger.reserve_http_attempt()
```

- [x] Add persistent optional hard limit and atomic pre-send reservation. Keep actual completed attempts/failures separate; unconfigured ordinary simulations retain behavior. Router fallback and provider retries must not bypass exhaustion.
- [x] Classify configuration/auth/model/connection/DNS/429/quota/timeout/format/exit/restart/user-stop/budget failures into code, stage, safe message, retryable and next_action, without returning raw exceptions or secrets. Keep bounded existing retries, but stop known deterministic quota failures.
- [x] Run ledger, provider, transport and diagnostics tests. Return exact integration contract for coordinator; do not edit research API.

### Task 3: Durable population tasks and reconnect

Files: create `gaworld/population/jobs.py`, recovery tests and optional standalone JS helper; modify existing `gaworld/apps/population_api.py`, `site/dashboard/population.js`, `site/dashboard/population.html` only where needed. New route registration belongs to coordinator.

- [x] Write tests for restart-readable terminal jobs, interrupted running jobs, owner/world isolation, POST idempotence (including concurrent duplicate submission), and bounded GET reconnection after lost responses.

```python
def test_population_outcome_survives_memory_eviction(monkeypatch):
    job = start_population_job({"spec": {"size": 20}, "request_id": "same-request-123"})
    wait_for_terminal(job["job_id"])
    population_api._JOBS.clear()
    assert population_api.job_status(job["job_id"])["status"] == "done"
```

- [x] Persist metadata separately from large results with atomic writes. Validate IDs and access at every read; stamp records with user/world and retain ownership.spawn. New or retried work never overwrites old artifacts.
- [x] Use a stable request ID for submission, request deadlines, finite GET backoff, refresh restoration and manual reconnect. Lost POST must recover the same submission; network loss must not label backend work failed. Avoid duplicate callbacks and stale responses; support disabled localStorage.
- [x] Return explicit route and response changes to coordinator; run population and frontend tests without actual model calls.

### Task 4: Unified planning budget and approval binding

Files: create `gaworld/research/budget.py`, `tests/test_research_budget_policy.py`; modify `protocol.py`, `editing.py`, `apps/research_api.py`, `apps/research_batches_api.py`, `study.py` as required, and account limits integration.

- [x] Write tests for one policy across compile/approve/launch, allowed >50k research, forbidden member increases, old approvals requiring review, changes in sample/provider/policy invalidating approval, and hard budget initialization.

```python
def test_requested_budget_uses_deployment_cap():
    from gaworld.research.budget import resolve_budget
    policy = resolve_budget({"research_workbench": {"max_call_budget": 200000}},
                            {"call_budget": 150000}, member=False)
    assert policy["call_budget"] == 150000
```

- [x] Add validated protocol `call_budget`/`http_budget` fields; resolve defaults, deployment caps and member limits through one module. Produce explicit per-mode compatibility, scale estimates and viable revision candidates without mutating the protocol.
- [x] Bind approval to protocol hash, effective policy, actual sample identity and provider/model fingerprint; store server-owned approval separately from editable protocol. Use it again at launch, initialize the ledger hard limit before spawning work, and recheck all permissions. Batch child studies use the same contract.
- [x] Update editable budget UI and display code-derived mode checks, estimates, approved limits and missing metrics. Selecting a candidate yields a reviewed revision; no automatic hypothesis removal.
- [x] Run budget/runtime/study/member/batch tests; keep legacy report reading intact.

### Task 5: Integration, review and verification

Files: existing research HTML/JS/editors/locales, OpenAPI and account policy, tutorial; `docs/reports/2026-11-10-research-reliability-verification.md`.

- [x] Integrate assessment renderer and evidence edits, PDF extraction metadata, safe fault cards and provider probe timestamps. Add route documentation and member allowlists only for needed endpoints.
- [x] Add controlled browser acceptance using local fixtures for assessment, budget incompatibility, lost response/reload and population recovery; exercise desktop/mobile and dark mode. Never generate paid traffic.
- [x] Run targeted new and existing tests, then `python -m pytest --suite core -q --disable-warnings`, Node tests, `python scripts/lint_ratchet.py`, and `git diff --check`. Diagnose failures against pre-existing changes; do not hide introduced regressions.
- [x] Request independent review per requesting-code-review skill; fix critical/important findings and rerun affected tests. Record exact test results and limitations in verification doc. Do not restart an active user server or run a paid experiment automatically.

Implementation work is already authorized by the user's confirmation. No second design approval or execution-choice prompt is required.

## Execution notes

Implemented in the existing checkout with independent review. Review findings about fallback/input binding and concurrent population selection were reproduced and fixed. Browser acceptance used local fixtures. No commits, server restart or paid research. Final evidence is in `docs/reports/2026-11-10-research-reliability-verification.md`.
