# Memory record batching implementation plan

**Goal:** Commit the four contiguous record-stage memories once without delaying cognition-visible episode writes.

**Architecture:** Add a small-batch memory store API, retain the single-row wrapper, and use the batch only in `_stage_record`. Build embedding payloads outside the transaction; preserve successful row contents and order; roll back a failed group atomically.

**Tech Stack:** Python, SQLite WAL/NORMAL, existing timing collector, pytest.

- [x] Add failing real-SQLite tests for record-stage commit count and the new batch API in tests/test_memory_write_batching.py.
- [x] Implement shared single/batch insertion and instrument memory.write; integrate only the four record-stage rows.
- [x] Verify equivalence, immediate post-return visibility, rollback, empty batches, no embedding inside write transactions, and thread behavior; run related memory/recall/pipeline tests.
- [x] Run core suite, lint ratchet and independent review, preserving unrelated and prior changes.
- [x] Benchmark exact row/query equivalence and commit counts on temporary databases; write docs/reports/2026-10-30-memory-write-performance.md and leave code uncommitted.
