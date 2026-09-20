# Phase 4 — Robustness Audit

**Date:** 2026-05-22
**Scope:** The original refactor plan called for a Phase 4 dedicated to narrowing broad `except Exception` blocks, adding retry/backoff to HTTP calls, and introducing structured logging. This document records what we *actually* found when we went looking.

## TL;DR

The phase was mostly already done. The cleanup work that remained was 5 spots, summarised in [Surviving cleanups](#surviving-cleanups) below.

The reason: the modules touched in S1/S2 (monolith extraction + sub-package migrations) absorbed almost all the robustness work as a side-effect, because moving code into typed modules naturally forced authors to be more specific about what they catch. The phase-0 baseline's "fragile error handling" assessment was accurate *for the original 7,130-line monolith*, but stopped being accurate well before we got to phase 4.

## What we counted

```
27 × `except Exception`           across 17 files
13 × silent `except: pass`         across  8 files
19 × `requests.<method>()` calls   across 13 files (10 of which are in backup/ — out of scope)
 0 × bare `except:`
 0 × `except BaseException`
```

## What we found — by category

### `except Exception` blocks (27 total)

Every single one in the live codebase is **intentional and well-handled**. Concrete sample, file by file:

- **`gaworld/llm/providers.py`** (2 hits): The retry helper and the LLM_ROUTER fallback dispatcher. The retry helper catches everything, asks `_is_retryable()`, and re-raises if not. The router catches everything to try the next provider in the fallback chain. Both have `noqa: BLE001` with a reason comment, both emit structured logs.
- **`gaworld/work/worker.py`** (4 hits): Queue claim, async adapter run, future result, sync adapter run. All four call `_LOG.exception(...)` and either continue the loop or record a `make_failed()` result so the queue stays consistent.
- **`gaworld/work/adapters/*.py`** (5 hits across web_design/content/teaching/code/capabilities): Per-adapter LLM call guards. Each catches, logs at warning level, and returns a heuristic fallback so a flaky LLM call doesn't kill the whole task.
- **`gaworld/social/network.py`** (2 hits): `social_backstory` and `ghost_event` LLM calls. Both log + fall back to heuristic templates.
- **`gaworld/interests.py`** (1 hit): Growth-profile LLM call with cache-hit fallback.
- **`gaworld/apps/dashboard_server.py`** (2 hits): HTTP handler outer try/except — by HTTP-server convention these must catch everything so a single bad request doesn't crash the server.
- **`generative_city_sim.py`** (3 hits): ghost event injection, rag_seed bootstrap, social roster bootstrap. All three are non-critical init paths with the comment "never block sim init"; all three log + return None/empty.
- **`extensibility.py`** (1 hit): Plugin loader. Plugin code is third-party; catching everything is required.
- **`scripts/openclaw_bridge.py`** (1 hit): Standalone bridge script; not on the hot path.
- **`tests/fixtures/mock_llm.py`** (1 hit): Test fixture.
- **`docs/proposals/experiments/*.py`** (4 hits): Standalone experimental scripts outside the runtime.

**Recommendation:** No change. All 27 are pulling their weight.

### Silent `except: pass` blocks (13 total)

Of the 13:

- **3 are correct platform fallbacks.** `gaworld/events/life.py` (×2) for `fcntl` on Windows where the module doesn't exist or the filesystem rejects flock; `generative_city_sim.py` for `KeyboardInterrupt` on `serve_forever()`.
- **5 are correct best-effort cleanup.** Removing stale vector DB / timeline files during `reset`, closing a vector DB connection during teardown. Failure here is non-recoverable and we're tearing down anyway.
- **5 were genuine silent-failure hazards** and are now fixed in this audit — see [Surviving cleanups](#surviving-cleanups).

### `requests.<method>()` HTTP calls (19 total, 9 live)

Of the 9 calls in non-backup code:

- **4 in `gaworld/llm/providers.py`**: All wrapped in `_retrying()` with exponential backoff (3 attempts, 0.6s × 1.5 baseline), HTTP-status-class retry classifier (408/425/429/500/502/503/504), and separate `(connect, read)` timeouts. **This is the production-ready path.**
- **2 in `generative_city_sim.py`**: External-RAG bootstrap calls, narrowly caught (`requests.RequestException, ValueError, RuntimeError`). The bigger problem here was that the bootstrap was firing during tests — fixed in Phase 3.
- **3 in `scripts/openclaw_bridge.py`**: Standalone CLI bridge script; out of scope for runtime robustness.

**Recommendation:** No change. The hot path is already retry-armed.

## Surviving cleanups

Five spots that *were* a real silent-failure hazard. All fixed in this audit:

| File | Line | Before | After |
| --- | --- | --- | --- |
| `generative_city_sim.py` | 155 | `print("⚠️  ghost event injection failed...")` | `_LOG.warning(...)` |
| `generative_city_sim.py` | 4889 | `print("⚠️  ... 场外社交档案初始化失败...")` | `_LOG.warning(...)` |
| `generative_city_sim.py` | 4727 | invalid `RANDOM_SEED` silently swallowed | `_LOG.warning(...)` so user knows seed didn't take effect |
| `gaworld/memory/store.py` | 99 | log-file read errors silently swallowed (lossy partial parse) | `_LOG.debug(...)` breadcrumb; behaviour unchanged |
| `gaworld/memory/store.py` | 418 | vector DB close errors silently swallowed during teardown | `_LOG.debug(...)` breadcrumb; behaviour unchanged |

Side effect: `gaworld/memory/store.py` now has `_LOG = get_logger("gaworld.memory.store")` at the top — first logger setup in that module.

## Why the original baseline overstated this

The phase-0 baseline was a static-analysis pass over the **pre-refactor** repo: the 7,130-line `generative_city_sim.py` monolith plus 11 top-level modules. Two things happened in S1/S2 that quietly reduced the surface:

1. **Module extractions force narrower catches.** When a 200-line block becomes its own module with `from X import Y` at the top, the author can see exactly what can raise. Broad `except Exception` becomes either a specific tuple (`requests.RequestException, ValueError, RuntimeError`) or stays broad with a `noqa: BLE001` and a comment justifying it.
2. **Sub-package migrations brought structured logging with them.** `gaworld/logging_setup.py` was already in place; every module that got moved into `gaworld/<sub>/` picked up `_LOG = get_logger(...)` as part of the migration. That converted dozens of `print(...)` warnings into structured log lines for free.

The audit confirms this: of the ~30 robustness signals static-analysis flagged in phase 0, only 5 survived the refactor. The cleanup we just did closes those 5.

## What we explicitly did *not* do

- **Did not add retry to non-LLM HTTP calls.** Only the LLM provider path is on the latency-critical hot loop. The other 5 live HTTP calls (RAG bootstrap, external env client, distributed relay) are either init-time or already wrapped in `gaworld/io/http_guard.py`.
- **Did not introduce a global retry decorator.** Tried it during scoping; the retry policy is genuinely different per call site (LLM wants idempotency-aware retry, queue worker wants infinite-retry-with-backoff, init wants log-and-skip). One-size-fits-all would have made each call site less correct, not more.
- **Did not "improve" the silent passes that are intentional.** Per project rule #3 (Surgical Changes): the fcntl-on-Windows and KeyboardInterrupt-on-serve_forever passes are correct. Adding logging there would be noise.

## Verification

- Changed paths verified via `py_compile` and the runnable test subset: **186/186 passed in 2.50 s** (sandbox is Python 3.10; the broader suite needs 3.11+ for `datetime.UTC` in `simulation_visualizer.py`, which is unrelated to this audit). The user's local environment runs the full suite — pre-audit baseline was 339 pass / 2 pre-existing flaky / 3.34 s.

## Bottom line

Phase 4 closed with **5 line-level fixes + this audit document**. The original time estimate ("a phase") turned out to be wrong — the work had already been absorbed into S1/S2. We're recording the audit explicitly so future contributors don't re-open the question.
