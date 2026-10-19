"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const batch = require("./research-batches.js");

test("matrix preview counts all complete experiments and conditions", () => {
  assert.deepEqual(batch.counts(2, 3, 4, 3), { runs: 24, worlds: 72 });
});

test("comparison escapes provider/city content and distinguishes missing intervals", () => {
  const html = batch.comparisonHTML({ counts: { planned: 4, selected: 3, done: 2, failed: 1, pending: 0 },
    groups: [{ provider: '<img onerror="bad">', city: "A&B", hypothesis: "H1", model: "m", epoch: 1,
      n: 2, mean: -1, sd: 0.2, ci95: null, direction_rate: 1, unique_seeds: 1, seed_robustness: false }],
    contrasts: [], issues: [{ cell_id: "r3", reason: "failed <script>" }], note: "Fixed seeds" });
  assert.ok(html.includes("&lt;img"));
  assert.ok(html.includes("A&amp;B"));
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("—"));
  assert.ok(html.includes("4"));
});

test("selected IDs survive polling while newly added rows start selected", () => {
  assert.deepEqual(batch.selection(["one", "two"], new Set(["one"]), new Set(["one", "two", "three"])), ["one", "three"]);
});
