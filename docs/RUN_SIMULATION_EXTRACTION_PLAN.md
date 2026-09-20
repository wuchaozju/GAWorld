# `run_simulation` Extraction Plan

**Date:** 2026-05-22
**Status:** Deferred. Recorded as the next big step.

## Why this isn't done yet

`run_simulation` is the 1,380-line orchestrator at the heart of
`generative_city_sim.py` (currently L3439–L4830). The cuts in S3
rounds 1–3 took the file from 7,032 → 5,753 lines by extracting
*helpers and side modules*. `run_simulation` itself was deliberately
left alone because of three compounding factors:

1. **Dense module-level dependency.** Just the first 80 lines reference
   ~20 module-level constants (`CSV_PATH`, `MAP_PATH`, `AGENT_IDS`,
   `STATEFUL`, `HUMAN_REALISM_ENABLED`, `INTERESTS_ENABLED`,
   `PRINT_AGENT_PROFILE`, `RANDOM_SEED`, `INTERVENTION_CONFIG`,
   `INTERESTS_CACHE_PATH`, `INTERESTS_MAX_ITEMS`, etc.) and ~10
   in-file helpers (`build_agent`, `print_agent_profiles`,
   `_enforce_memory_model_compat`, `evoke_memory`,
   `_social_relationship_snapshot`, `_activity_matches_keywords`,
   `_build_recall_context_labels`, plus several still-unmigrated
   per-step routines). Estimated full dependency set: **30–50
   distinct symbols** — every one of which has to either move with
   `run_simulation`, become a runtime CONFIG lookup, get re-exported
   via the established pattern, or get passed in.

2. **Not enough helpers have been migrated yet.** `choose_action`'s
   support helpers (`evoke_memory` and friends) still live in
   gen_city_sim. Lifting `run_simulation` before those are moved
   means re-exports get *very* noisy, and bare-name lookups inside
   the lifted `run_simulation` would resolve in the wrong namespace.
   The right order is: move the helpers first, then lift the
   orchestrator.

3. **Test-rig constraint.** `tests/test_cli_run_sim_days.py` does
   `patch.object(sim, "run_simulation")` — so the name must stay an
   attribute on the legacy `sim` module. Re-export handles that, but
   only if the lifted function's internal bare-name calls resolve
   correctly. Hard to verify without the full e2e suite, which the
   sandbox can't run (Python 3.10 vs `datetime.UTC` 3.11+).

The honest summary: doing it right is more work than this round can
absorb; doing it wrong invites a hard-to-debug semantic regression in
the test rig's mock-LLM mode. So we stop short, leave a map, and
record the prerequisites.

## What we did instead (zero-risk navigation aids)

Added phase-section banners *inside* `run_simulation`'s body so future
extractors don't have to re-discover the boundaries:

```
PHASE 1   L3447  Initialise (seed, load data, build agents, restore state, growth bootstrap)
PHASE 2   L3586  Build social network + initialise per-agent edges and weights
PHASE 3   L3717  DAY LOOP
  PHASE 3a L3718  Per-day setup (real-work tick, day context, schedule/routine generation, action space)
  PHASE 3b L3894  STEP LOOP — the megaloop
  PHASE 3c L4721  Day-end consolidation (memory review, daily summary, diary, episode persist)
```

These are comment-only changes — verified by 288 passing tests, zero
behaviour delta.

## What needs to happen before lifting `run_simulation` (in dependency order)

1. **Move `evoke_memory` and friends to `gaworld/sim/_memory_recall.py`.**
   `evoke_memory`, `_social_relationship_snapshot`,
   `_activity_matches_keywords`, `_build_recall_context_labels`,
   `_memory_recall_top_k`, `_infer_recall_valence`,
   `_apply_recall_effect`, `_format_recollection`. These are the
   single largest blocker — `choose_action` and the per-step loop
   both depend on them.

2. **Lift `choose_action` to `gaworld/sim/_action.py`.** With its
   helpers gone, the dependency surface shrinks to ~10 symbols, most
   of which are already in migrated modules. Re-export at the
   original location to preserve `sim.choose_action(...)` test calls.

3. **Move per-step routines to a `_step.py` sub-module.** Functions
   like `_routine_change_probability`, `_routine_change_trigger_strength`,
   `_spontaneity_probability`, `maybe_generate_transient_thought`,
   `format_transient_thought`, `maybe_adjust_activity`, all of which
   live in the L2167–L2541 zone today.

4. **Convert remaining module-level constant snapshots to runtime
   `CONFIG.get(...)` lookups** — particularly the
   `HUMAN_REALISM_*`, `INTERVENTION_*`, `DYNAMIC_BEHAVIOR_*`,
   `INTERESTS_*` knobs. This is the same pattern as the S3 Phase 3
   `_bootstrap_agent_external_rag` fix.

5. **Lift `run_simulation` to `gaworld/sim/runner.py`.** With the
   above done, the function shrinks to its actual orchestration
   role (~600 lines instead of 1,380), and the lift becomes
   mechanical: a single re-export at the gen_city_sim level to keep
   `sim.run_simulation` and the `patch.object` rig intact.

## Why this is worth doing eventually

`run_simulation` is where every cross-cutting concern (config gating,
state persistence, day/step looping, finalisation) lives. Until it's
in its own module, the file remains "the simulator + the orchestrator",
and people working on the simulator can't avoid the orchestrator.
After the lift, `generative_city_sim.py` becomes a thin CLI + glue
shim of well under 1,500 lines.

## Round-4 outcome

- ✅ Audit finished, plan written, phase banners inserted.
- 📅 Actual lift scheduled for a future round, with the 5 prerequisite
  cuts above in order.
- 🧪 288 passing tests, zero regression from the banner insertion.
