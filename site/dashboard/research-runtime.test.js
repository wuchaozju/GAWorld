const test = require("node:test");
const assert = require("node:assert/strict");

test("incremental logs drain terminal chunks and stop polling", async () => {
  const { createLogStream } = require("./research-runtime.js");
  let timer;
  const calls = [];
  const chunks = [
    { text: "one\n", next_offset: 4, file_id: "a", sources: [], live: true },
    { text: "two\n", next_offset: 8, file_id: "a", sources: [], live: false, has_more: true },
    { text: "last\n", next_offset: 13, file_id: "a", sources: [], live: false },
  ];
  const stream = createLogStream({ api: async (_, path) => { calls.push(path); return chunks.shift(); },
    setTimer: fn => { timer = fn; return 1; }, clearTimer: () => { timer = null; }, onUpdate: () => {} });
  await stream.activate("study", 1);
  await timer();
  await timer();
  assert.equal(stream.snapshot().text, "one\ntwo\nlast\n");
  assert(calls[1].includes("offset=4"));
  assert.equal(timer, null);
});

test("changing studies discards stale responses and uses text only", async () => {
  const { createLogStream } = require("./research-runtime.js");
  let complete;
  const stream = createLogStream({ api: async (_, path) => {
    if (path.includes("old")) return new Promise(resolve => { complete = resolve; });
    return { text: "<script>untrusted</script>\n", next_offset: 30, sources: [], live: false };
  }, setTimer: () => 1, clearTimer: () => {}, onUpdate: () => {} });
  const pending = stream.activate("old", 1);
  await stream.activate("new", 1);
  complete({ text: "old logs", next_offset: 8, live: false });
  await pending;
  assert.equal(stream.snapshot().text, "<script>untrusted</script>\n");
});

test("hidden pages lower polling and buffers remain bounded", async () => {
  const { createLogStream } = require("./research-runtime.js");
  let hidden = false;
  let timer;
  let delay;
  let count = 0;
  const stream = createLogStream({ api: async () => { count++; return {
    text: "x".repeat(200000), next_offset: 200000, sources: [], live: true }; },
    setTimer: (fn, ms) => { timer = fn; delay = ms; return 1; }, clearTimer: () => { timer = null; },
    isHidden: () => hidden, onUpdate: () => {} });
  await stream.activate("study", 1);
  assert(stream.snapshot().text.length <= 160000);
  hidden = true;
  await timer();
  assert.equal(count, 1);
  assert.equal(delay, 15000);
  stream.stop();
});

test("starting an already open study restarts stopped log polling", async () => {
  const { createLogStream } = require("./research-runtime.js");
  let calls = 0;
  const stream = createLogStream({ api: async () => { calls++; return {
    text: calls === 1 ? "" : "started\n", next_offset: calls === 1 ? 0 : 8,
    sources: [], live: calls > 1 }; }, setTimer: () => 1, clearTimer: () => {}, onUpdate: () => {} });
  await stream.activate("study", 1, false);
  await stream.activate("study", 1, true);
  assert.equal(calls, 2);
  assert.equal(stream.snapshot().text, "started\n");
  stream.stop();
});
