const test = require("node:test");
const assert = require("node:assert/strict");
const { merge } = require("./research-editors.js");
const { hasResults } = require("./research-editors.js");

test("read-only telemetry on a fresh draft does not disable approval or editing", () => {
  assert.equal(hasResults({ stage: "protocol", runtime: { telemetry: { available: false } }, runs: [] }), false);
  assert.equal(hasResults({ runtime: { started_at_epoch: 123 }, runs: [] }), true);
});

test("plan editor preserves source data while changing scientific content", () => {
  const original = { title: "old", material: "source paper", owner_id: 1, recommended_design: 0 };
  const edited = merge("plan", original, { title: "new", summary: "summary", questions: "Q1\nQ2", hypotheses: "H1", design: '[{"name":"revised"}]', steps: '[]' });
  assert.equal(original.title, "old");
  assert.equal(edited.material, "source paper");
  assert.deepEqual(edited.research_questions, ["Q1", "Q2"]);
  assert.equal(edited.design.name, "revised");
});

test("protocol editing preserves sample and event timing", () => {
  const original = { title: "old", sample: { agent_ids: [1] }, sim_days: 90 };
  const edited = merge("protocol", original, { title: "new", notes: "note", conditions: '[{"events":[{"day":8,"description":"new event"}]}]', hypotheses: '[]', measures: '[]', survey: '{}' });
  assert.equal(edited.sim_days, 90);
  assert.equal(edited.conditions[0].events[0].day, 8);
  assert.deepEqual(edited.sample, original.sample);
  assert.equal(original.title, "old");
});

test("malformed edits fail before sending a request", () => {
  assert.throws(() => merge("plan", {}, { design: "not JSON", steps: "[]" }), SyntaxError);
});
