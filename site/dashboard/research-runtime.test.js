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

function trackerHarness(api, storage = new Map()) {
  let timer;
  const updates = [], done = [], errors = [];
  const tracker = require('./research-runtime.js').createJobTracker({api,
    storage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)},
    storageKey: 'user-7/world-1/plan', setTimer: fn => { timer = fn; return 1; }, clearTimer: () => { timer = null; },
    onUpdate: job => updates.push(job), onDone: (job, kind) => done.push([job, kind]), onError: error => errors.push(error.message)});
  return {tracker, updates, done, errors, next: () => timer(), storage};
}

test('job tracking reconnects to the same job after transient failure', async () => {
  let n = 0;
  const h = trackerHarness(async () => { if (++n === 1) throw new TypeError('offline'); return {status:'done', result:{plan_id:'p'}}; });
  await h.tracker.watch('plan-1', 'plan');
  assert.equal(h.errors.length, 0);
  assert.equal(h.updates[0].reconnecting, true);
  await h.next();
  assert.equal(h.done[0][0].result.plan_id, 'p');
  assert.equal(h.storage.size, 0);
});

test('refresh restores tracking without restarting the model job', async () => {
  const storage = new Map();
  const first = trackerHarness(async () => ({status:'running'}), storage);
  await first.tracker.watch('plan-1', 'digest');
  first.tracker.stop();
  const second = trackerHarness(async (method, path) => { assert.equal(method, 'GET'); assert(path.endsWith('/plan-1')); return {status:'done', result:{title:'paper'}}; }, storage);
  assert.equal(await second.tracker.restore(), true);
  assert.equal(second.done[0][1], 'digest');
});

test('missing or forbidden jobs terminate rather than retry forever', async () => {
  for (const status of [401,403,404]) {
    const h = trackerHarness(async () => { throw Object.assign(new Error('unavailable'), {status}); });
    await h.tracker.watch('old', 'plan');
    assert.deepEqual(h.errors, ['unavailable']);
    assert.equal(h.storage.size, 0);
  }
});

test('a stale job response cannot finish a newly selected job', async () => {
  let resolveOld;
  const h = trackerHarness(async (_, path) => path.endsWith('/old') ? new Promise(resolve => {resolveOld = resolve;}) : {status:'running'});
  const pending = h.tracker.watch('old', 'plan');
  await h.tracker.watch('new', 'plan');
  resolveOld({status:'done',result:{plan_id:'old'}});
  await pending;
  assert.equal(h.done.length, 0);
  assert.equal(JSON.parse([...h.storage.values()][0]).id, 'new');
  h.tracker.stop();
});

test('bounded requests time out even if a response body never finishes', async () => {
  const request = require('./research-runtime.js').createRequest({timeoutMs:10, fetch:async () => ({ok:true, json:() => new Promise(() => {})})});
  await assert.rejects(request('GET','/status'), error => error.code === 'timeout');
});

test('bounded requests preserve HTTP status for job recovery decisions', async () => {
  const request = require('./research-runtime.js').createRequest({fetch:async () => ({ok:false,status:403,json:async () => ({error:'Forbidden'})})});
  await assert.rejects(request('GET','/status'), error => error.status === 403 && error.message === 'Forbidden');
});

test('a lost POST reply restores the correlated completed task, including a digest', async () => {
  const storage = new Map();
  let posts = 0;
  const first = trackerHarness(async () => { posts++; }, storage);
  const requestId = first.tracker.begin('digest');
  assert(requestId);
  const pending = JSON.parse([...storage.values()][0]);
  assert.equal(pending.request_id, requestId);
  // Page reloads before the POST response supplies a job id.
  const second = trackerHarness(async (method, path) => {
    assert.equal(method, 'GET');
    if (path.startsWith('/api/research/context')) return {jobs:[{id:'digest-1',kind:'digest',request_id:requestId,status:'done'}]};
    return {status:'done',result:{title:'Recovered paper'}};
  }, storage);
  await second.tracker.restore();
  assert.equal(second.done[0][0].result.title, 'Recovered paper');
  assert.equal(second.done[0][1], 'digest');
  assert.equal(posts, 0);
});

test('lost POST recovery works when browser storage is blocked', async () => {
  let done;
  let requestId;
  const tracker = require('./research-runtime.js').createJobTracker({
    storage:{getItem(){throw new Error('blocked');},setItem(){throw new Error('blocked');},removeItem(){}}, storageKey:'blocked',
    api:async (_, path) => path.startsWith('/api/research/context') ? {jobs:[{id:'plan-1',kind:'plan',request_id:requestId,status:'done'}]} : {status:'done',result:{plan_id:'recovered'}},
    onUpdate(){},onError: error => {throw error;},onDone: job => {done=job;}
  });
  requestId=tracker.begin('plan');
  assert.equal(await tracker.restore(), true);
  assert.equal(done.result.plan_id,'recovered');
});

test('a completed paper reading remains recoverable until the next submission', async () => {
  const storage = new Map();
  const first=trackerHarness(async () => ({status:'done',result:{title:'Paper'}}),storage);
  await first.tracker.watch('digest-1','digest');
  const second=trackerHarness(async () => ({status:'done',result:{title:'Paper'}}),storage);
  assert.equal(await second.tracker.restore(),true);
  assert.equal(second.done[0][1],'digest');
});
