# Simulation performance implementation plan

**Goal:** Reduce repeated memory vector decoding and identify expensive simulation work without changing decisions.

**Architecture:** Bounded immutable vector cache and stable partial selection in the existing memory store; context-scoped timing collector assembled by a kernel plugin. The existing simulator entry only wires a package-owned exception-safe scope decorator; no inline subsystem logic or user configuration changes.

**Tech Stack:** Python, NumPy, SQLite, pytest, existing kernel bus/recorder.

## Tasks

- [x] Add failing real-SQLite tests for repeated decode avoidance, exact legacy/weighted results, stable ties, insert/delete/update visibility and world isolation. Run `python -m pytest tests/test_memory_search_performance.py -q`.
- [x] Implement `gaworld/memory/vector_cache.py`, integrate into `gaworld/memory/store.py`, and re-run new and existing memory/thread tests. Keep float32 dot products and weighted update semantics intact.
- [x] Add failing tests for stage/model/search timing, failure propagation, plugin lifetime, disabled mode, bounded percentiles and worker context propagation. Run `python -m pytest tests/test_sim_performance.py -q`.
- [x] Implement `gaworld/core/performance.py` and `gaworld/plugins/performance.py`; instrument package-level pipeline/search/stats; assemble through builtin_plugins and add documented runtime defaults.
- [x] Run targeted tests and `python -m pytest --suite core -q`, line-budget and plugin-order regression tests; inspect `python scripts/lint_ratchet.py` results without changing unrelated work.
- [x] Benchmark isolated old/new retrieval with deterministic vectors and assert identical hit dictionaries. Save measured results and limits in `docs/reports/2026-10-29-simulation-performance.md`.
- [x] Review diff, resolve findings, document what is accelerated and what still waits on model responses. Leave changes uncommitted for review.
