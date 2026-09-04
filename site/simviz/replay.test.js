const test = require("node:test");
const assert = require("node:assert/strict");

const replay = require("./replay.js");

test("normalizes run payloads", () => {
  const runs = replay.normalizeRuns({
    runs: [
      { id: "live", trace_url: "/output/visualization/simulation_trace.json" },
      { id: "broken" },
      null,
    ],
  });
  assert.equal(runs.length, 1);
  assert.equal(runs[0].id, "live");
});

test("selects requested replay run or falls back to the newest run", () => {
  const runs = [
    { id: "live", trace_url: "/live.json" },
    { id: "archive-1", trace_url: "/archive.json" },
  ];
  assert.equal(replay.selectRun(runs, "archive-1").trace_url, "/archive.json");
  assert.equal(replay.selectRun(runs, "missing").id, "live");
});

test("slices frames through the selected timeline index", () => {
  const trace = { frames: [{ index: 0 }, { index: 1 }, { index: 2 }] };
  assert.deepEqual(replay.framesUntil(trace, 1), [{ index: 0 }, { index: 1 }]);
  assert.deepEqual(replay.framesUntil(trace, 99), trace.frames);
});

test("labels frames with day and time when available", () => {
  assert.equal(replay.frameLabel({ day: 2, time: "09:30" }, 1), "Day 2 09:30");
  assert.equal(replay.frameLabel({}, 3), "Frame 4");
});
