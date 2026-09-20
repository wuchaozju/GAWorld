# Twin Mobile Round Two Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the "write-only" gap in the phone client — let it show what the agent is living, let the user correct and delete what they reported, cut the cost of reporting, and keep working when GPS is unavailable.

**Architecture:** One new data-model concept (amendment records folded at read time), four new read/write endpoints on the existing `TwinBackend`, and four frontend additions. `dashboard_server.py`, the kernel, and `generative_city_sim.py` remain untouched.

**Depends on:** the three prior twin plans (`c656451`…`0a2510d`).

---

## The one irreversible decision: amendments, not mutations

`reports.jsonl` is append-only and `report_id` is the idempotency key. Editing or deleting in place would break both. So corrections are **new records that reference an earlier one**:

```json
{"report_id": "<new uuid>", "kind": "amend", "target": "<original report_id>",
 "op": "delete", "ts": 1754640000}

{"report_id": "<new uuid>", "kind": "amend", "target": "<original report_id>",
 "op": "update", "patch": {"action_tag": "meal", "note": "改成吃饭"}, "ts": 1754640000}
```

`load_reports()` folds these at read time. Every consumer — the mirror stage, perception injection, the trail, calibration — therefore sees corrected data for free, with no consumer changes.

### Only `action_tag` and `note` are patchable

**Location is deliberately not editable.** It came off the device sensor at a specific moment. Letting a user rewrite it turns measured data into asserted data, and the calibration corpus silently stops being a record of where anyone actually was. If a fix was wrong, the honest operation is `delete`, not `update`.

The backend enforces this by whitelisting patch keys rather than merging whatever arrives.

### Consequences to handle

- **Snapshot must be recomputed after an amendment.** Deleting the newest report has to promote the previous one. Deleting everything must clear the snapshot file — the current `_refresh_snapshot` returns early when there are no reports, which would leave a stale snapshot claiming a position the user just erased. That is a real bug this plan must fix.
- **Already-consumed reports are not re-injected.** `twin_perceive` tracks a timestamp offset; amending a report the agent already remembered will not rewrite that memory. Accepted and documented — retroactively editing an agent's memory is a bigger idea than a typo fix.

---

## Task 1: Amendment support in the store

**Files:** Modify `gaworld/twin/store.py` · Test `tests/test_twin_store.py`

- [ ] **Step 1: Add these tests to `tests/test_twin_store.py`**

```python
    def test_delete_amendment_hides_the_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            store.append_amendment(7, "amend-1", "a", "delete", root=tmpdir)
            self.assertEqual(store.load_reports(7, root=tmpdir), [])

    def test_update_amendment_patches_whitelisted_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000, "work")], root=tmpdir)
            store.append_amendment(
                7, "amend-1", "a", "update",
                patch={"action_tag": "meal", "note": "改了"}, root=tmpdir,
            )
            loaded = store.load_reports(7, root=tmpdir)
            self.assertEqual(loaded[0]["action_tag"], "meal")
            self.assertEqual(loaded[0]["note"], "改了")

    def test_update_amendment_cannot_rewrite_location(self):
        # Location is measured, not asserted. A wrong fix must be deleted,
        # not edited, or the calibration corpus stops being a record of where
        # anyone actually was.
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            store.append_amendment(
                7, "amend-1", "a", "update",
                patch={"node_id": "somewhere-else", "loc": {"lat": 1, "lng": 2}},
                root=tmpdir,
            )
            loaded = store.load_reports(7, root=tmpdir)
            self.assertEqual(loaded[0]["node_id"], "home")
            self.assertEqual(loaded[0]["loc"]["lat"], 30.27)

    def test_amendments_are_not_returned_as_reports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            store.append_amendment(7, "amend-1", "a", "update",
                                   patch={"note": "x"}, root=tmpdir)
            loaded = store.load_reports(7, root=tmpdir)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["report_id"], "a")

    def test_deleting_the_newest_report_promotes_the_previous_one(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(
                7, [_report("a", 1000, "sleep"), _report("b", 2000, "work")],
                root=tmpdir,
            )
            store.append_amendment(7, "amend-1", "b", "delete", root=tmpdir)
            snapshot = store.read_snapshot(7, root=tmpdir)
            self.assertEqual(snapshot["report_id"], "a")

    def test_deleting_every_report_clears_the_snapshot(self):
        # Otherwise the phone keeps showing a position the user just erased.
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            store.append_amendment(7, "amend-1", "a", "delete", root=tmpdir)
            self.assertIsNone(store.read_snapshot(7, root=tmpdir))

    def test_amendment_is_idempotent_on_its_own_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            store.append_amendment(7, "amend-1", "a", "delete", root=tmpdir)
            store.append_amendment(7, "amend-1", "a", "delete", root=tmpdir)
            raw = store.load_raw(7, root=tmpdir)
            self.assertEqual(len([r for r in raw if r.get("kind") == "amend"]), 1)

    def test_last_amendment_wins(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            store.append_amendment(7, "m1", "a", "update",
                                   patch={"note": "first"}, root=tmpdir)
            store.append_amendment(7, "m2", "a", "update",
                                   patch={"note": "second"}, root=tmpdir)
            self.assertEqual(store.load_reports(7, root=tmpdir)[0]["note"], "second")
```

- [ ] **Step 2:** Run `python3 -m pytest tests/test_twin_store.py -q` — expect failures on `append_amendment` / `load_raw`.

- [ ] **Step 3:** Implement in `store.py`: `PATCHABLE_FIELDS`, `load_raw()`, `append_amendment()`, fold logic in `load_reports()`, and fix `_refresh_snapshot()` to clear the snapshot when nothing remains.

- [ ] **Step 4:** Run the tests — expect 16 passed.

- [ ] **Step 5:** Commit `feat(twin): amendment records for correcting and deleting reports`.

---

## Task 2: Life, history, amend, and places endpoints

**Files:** Modify `gaworld/twin/backend.py` · Create `gaworld/twin/life.py` · Test `tests/test_twin_life.py`, `tests/test_twin_backend.py`

`life.py` reads the four artifacts confirmed to exist:

| Field | Source |
|---|---|
| `diary` | latest `output/diaries/agent_<id>/day_NNN.md` |
| `state` | last row per metric in `output/state/agent_state_history.csv` |
| `goals` | `output/memory/agent_<id>_goals.json` |
| `episodes` | `load_agent_episodes()`, most recent few |

All read-only and scoped to the token's agent. Every artifact is optional — a fresh install has none of them, and the endpoint must return empty structures rather than erroring.

- [ ] **Step 1:** Write `tests/test_twin_life.py` covering: latest diary chosen by day number; missing diary returns `""`; state folds to the last value per metric; missing state file returns `{}`; goals load; missing goals return empty tiers; a corrupt CSV row is skipped rather than fatal.

- [ ] **Step 2:** Run — expect `ModuleNotFoundError`.

- [ ] **Step 3:** Implement `gaworld/twin/life.py` and add `TwinBackend.life()`, `.reports()`, `.amend()`, `.places()`.

`.amend()` must reject a target the caller does not own — the same class of bug as writing another agent's reports.

- [ ] **Step 4:** Add to `tests/test_twin_backend.py`: amend rejects an unknown target; amend rejects another agent's report; `places()` returns nodes sorted by distance and supports a name query.

- [ ] **Step 5:** Run both files, then commit.

---

## Task 3: Routes

**Files:** Modify `gaworld/apps/twin_server.py` · Test `tests/test_twin_server.py`

| Route | Method | Notes |
|---|---|---|
| `/api/twin/life` | GET | diary + state + goals + recent episodes |
| `/api/twin/reports` | GET | effective (folded) reports, newest first |
| `/api/twin/amend` | POST | `{target, op, patch}` |
| `/api/twin/places` | GET | `?q=` name search, `?limit=` |

- [ ] **Step 1:** Add tests — each new route 401s without a token; amend round-trips; the dashboard-surface 404 test still passes.
- [ ] **Step 2–4:** Implement, run, commit.

---

## Task 4: Frontend

**Files:** Modify `site/mobile/{core.js,core.test.js,index.html,styles.css,app.js,sw.js}`

Four additions:

1. **今日卡片** — diary text, state bars for the nine variables, active goals.
2. **上报历史** — today's reports, each with a tag-change control and a delete control. Deleting asks for confirmation; it is not undoable from the phone.
3. **省力上报** — a 「和刚才一样」 button that repeats the last tag, plus optional auto-sampling every N minutes **while the page is visible**. Uses `document.visibilityState` so a backgrounded tab does not silently burn battery.
4. **手动选点** — when geolocation is denied or unavailable, show a searchable node list instead of sending `0,0`.

Testable logic goes in `core.js`: `stateBars()`, `groupReportsByDay()`, `nextAutoSampleDue()`, `formatGoals()`. DOM wiring stays in `app.js`.

- [ ] **Step 1:** core.js logic + tests, run `node site/mobile/core.test.js`.
- [ ] **Step 2:** HTML/CSS/app.js wiring; `node --check`; id cross-reference script.
- [ ] **Step 3:** Bump `CACHE_NAME` to `v3`.
- [ ] **Step 4:** Browser verification: life card renders, a report can be retagged and deleted, manual picker appears without GPS.
- [ ] **Step 5:** Commit.

---

## Honest Scope Limits

- **No true background collection.** iOS PWAs cannot sample location with the page closed. Auto-sampling only runs while the page is visible, and the UI must not imply otherwise.
- **Amendments do not rewrite agent memory.** Already-injected episodes stay as they were.
- **Deletion is a tombstone, not an erasure.** The original line remains in `reports.jsonl`. For a research tool this is correct — the audit trail survives — but it is *not* GDPR/PIPL-grade deletion, and must not be described as such if this ever faces real users.

## Done When

- `python3 -m pytest tests/test_twin_*.py -q` passes.
- `node site/mobile/core.test.js` passes.
- Browser: life card renders, retag and delete work, manual picker appears with geolocation denied.
- `/api/config` on the twin server still returns 404.
