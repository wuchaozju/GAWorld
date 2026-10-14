# Durable day-boundary checkpoints (Phase 5)

SAVE / RESTORE / CONTINUE only — no auto-retry, no rollback, no branching.
Checkpoints are runtime truth; CSV/timeline/reports are outputs and are never
checkpoint state. No secrets (API keys / tokens) are ever serialized;
provider/model identifiers are.

## Storage layout

```
<run>/checkpoints/day_NNNN/
    manifest.json   # versioned metadata (see below)
    state.pkl       # or state.json — the serialized components
```

`<run>` is the directory holding the state output (e.g.
`output/cities/<city>/`). Writes are atomic: temp dir → validate → rename;
`list_checkpoints()` / `latest_checkpoint()` never return partial writes and a
valid checkpoint is never silently overwritten.

## Manifest fields

`checkpoint_version`, `run_id`, `completed_day`, `city`, `agent_ids`,
`created_at`, `state_files`, `state_format`, plus provenance:
`llm_routing` (identifiers only), `sim_config_snapshot` (sanitized runtime
config — distinct from simulation state so post-restore overrides are
possible), `memory_model_version` (compat gate).

## Python API

```python
from gaworld.checkpoints import CheckpointManager, simulation_state_hooks

mgr = CheckpointManager(run_dir, run_id, hooks=simulation_state_hooks())
ref = mgr.save_checkpoint(carrier, completed_day=3)      # → "run:day_0003"
mgr.list_checkpoints(); mgr.latest_checkpoint()
mgr.restore_checkpoint(carrier, ref="run:day_0003")      # or path / latest
mgr.resolve_ref("run:day_0003")
```

Errors: `CheckpointError` base; `CheckpointExists`,
`CheckpointNotFound`, `CheckpointVersionUnsupported`,
`CheckpointCorrupted` — all with human-readable messages; restore validates
fully before touching any runtime state (no partial continuation).

## Launcher interface

```bash
# record a checkpoint after every completed day (and a pre-day-1 one):
GAWORLD_CONFIG_OVERRIDES='{"checkpoint": {"enabled": true, "run_id": "my-run"}}' \
    python generative_city_sim.py run

# resume a finished run from a checkpoint (completed_day=N → next day is N+1):
GAWORLD_CONFIG_OVERRIDES='{"resume_from_checkpoint": "my-run:day_0003"}' \
    python generative_city_sim.py run
```

`resume_from_checkpoint` also accepts a checkpoint day-directory path. On
restore, simulation state (agents, memories, plugin state, clock, per-agent
day cursor, RNG: python `random` + legacy numpy surface) comes from the
checkpoint; runtime configuration is applied fresh from the current config,
so overrides after restore win without mutating state. Plugin namespaces
holding live runtime resources (worker threads, locks) are never serialized —
they carry an explicit rebuild marker and their plugins recreate them on
`on_simulation_start` (a loud decision, never a silent fallback).
