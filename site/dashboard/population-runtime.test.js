"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const runtime = require("./population-runtime.js");

function response(payload, status) {
  return { ok: !status || status < 400, status: status || 200, json: async () => payload };
}
function fixture(fetch, extra) {
  const timers = [], progress = [], done = [], errors = [], disconnected = [];
  const tracker = runtime.create(Object.assign({
    fetch, timeoutMs: 1000,
    setTimer: (fn) => { timers.push(fn); return timers.length; }, clearTimer: () => {},
    onProgress: (...x) => progress.push(x), onDone: (...x) => done.push(x),
    onError: (...x) => errors.push(x), onDisconnected: (...x) => disconnected.push(x),
  }, extra));
  return { tracker, timers, progress, done, errors, disconnected };
}

test("lost POST response recovers the same request without resubmission or storage", async () => {
  const sent = [];
  const f = fixture(async (url, opts) => {
    sent.push([url, opts.method]);
    if (opts.method === "POST") throw new TypeError("Failed to fetch");
    return response({ id: "pop-12345678", kind: "pop", status: "done", result: { people: [1] } });
  }, { storage: { setItem() { throw Error("disabled"); }, getItem() { throw Error("disabled"); } } });
  await f.tracker.start("pop", "/api/population/generate", { spec: { size: 20 } });
  assert.equal(sent.filter(x => x[1] === "POST").length, 1);
  assert.match(sent[1][0], /recover\?request_id=/);
  assert.equal(f.done.length, 1);
  assert.equal(f.done[0][0].id, "pop-12345678");
});

test("transient GET failures reconnect and complete only once", async () => {
  let queries = 0;
  const f = fixture(async (url, opts) => {
    if (opts.method === "POST") return response({ job_id: "pop-12345678" });
    if (++queries === 1) throw Error("network");
    return response({ id: "pop-12345678", status: "done", kind: "pop", result: {} });
  });
  await f.tracker.start("pop", "/generate", {});
  assert.equal(f.errors.length, 0);
  await f.timers.shift()();
  assert.equal(f.done.length, 1);
  assert.equal(f.timers.length, 0);
});

test("retry exhaustion means disconnected, and manual reconnect tracks original job", async () => {
  let healthy = false, posts = 0;
  const f = fixture(async (_url, opts) => {
    if (opts.method === "POST") { posts++; return response({ job_id: "group-12345678" }); }
    if (!healthy) throw Error("network");
    return response({ id: "group-12345678", status: "done", kind: "group", result: {} });
  }, { maxFailures: 2 });
  await f.tracker.start("group", "/run", {});
  await f.timers.shift()();
  assert.equal(f.disconnected.length, 1);
  assert.equal(f.errors.length, 0);
  healthy = true;
  await f.tracker.reconnect();
  assert.equal(posts, 1);
  assert.equal(f.done.length, 1);
});

test("reload restores job without sending POST and forbidden access ends tracking", async () => {
  let saved;
  const storage = { setItem: (_k, v) => { saved = v; }, getItem: () => saved, removeItem: () => { saved = null; } };
  const a = fixture(async (_url, opts) => opts.method === "POST"
    ? response({ job_id: "pop-12345678" }) : response({ status: "running", progress: 0.2 }), { storage });
  await a.tracker.start("pop", "/generate", {});
  const calls = [];
  const b = fixture(async (url, opts) => { calls.push(opts.method); return response({ error: "Forbidden" }, 403); }, { storage });
  await b.tracker.restore();
  assert.deepEqual(calls, ["GET"]);
  assert.equal(b.errors.length, 1);
  assert.equal(b.timers.length, 0);
});

test("request deadline covers a stalled response body", async () => {
  const request = runtime.createRequest({ timeoutMs: 10, fetch: async () => ({
    ok: true, status: 200, json: () => new Promise(() => {}),
  }) });
  await assert.rejects(request("GET", "/status"), e => e.code === "timeout");
});

test("stale response cannot finish a newly selected submission", async () => {
  let release;
  const f = fixture(async (url, opts) => {
    if (opts.method === "POST") return response({ job_id: url === "/a" ? "pop-aaaaaaaa" : "pop-bbbbbbbb" });
    if (url.includes("aaaaaaaa")) return new Promise(resolve => { release = resolve; });
    return response({ id: "pop-bbbbbbbb", kind: "pop", status: "done", result: { value: "b" } });
  });
  const first = f.tracker.start("pop", "/a", {});
  await new Promise(resolve => setImmediate(resolve));
  await f.tracker.start("pop", "/b", {});
  release(response({ id: "pop-aaaaaaaa", kind: "pop", status: "done", result: { value: "a" } }));
  await first;
  assert.equal(f.done.length, 1);
  assert.equal(f.done[0][0].result.value, "b");
});
