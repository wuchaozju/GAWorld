/* Transient gateway errors must never submit another paid interview. */
const test = require('node:test');
const assert = require('node:assert/strict');
const {createClient, followJob} = require('./survey-jobs.js');

test('safe reads retry HTML 502 and network failures, then return JSON', async () => {
  let calls = 0;
  const waits = [];
  const request = createClient({fetch: async () => {
    calls++;
    if (calls === 1) return {ok:false,status:502,json:async () => {throw new SyntaxError('HTML');}};
    if (calls === 2) throw new TypeError('Failed to fetch');
    return {ok:true,status:200,json:async () => ({status:'running'})};
  }, delay:async ms => waits.push(ms)});
  assert.deepEqual(await request('GET','/job'),{status:'running'});
  assert.equal(calls,3);
  assert.deepEqual(waits,[1000,2000]);
});

test('writes are never replayed after an ambiguous network failure', async () => {
  let calls = 0;
  const request = createClient({fetch:async () => {calls++; throw new TypeError('offline');}});
  const result = await request('POST','/run',{questions:[]});
  assert.equal(calls,1);
  assert.equal(result.retryable,true);
});

test('authorization errors do not retry', async () => {
  for (const status of [401,403,404]) {
    let calls = 0;
    const request = createClient({fetch:async () => {
      calls++; return {ok:false,status,json:async () => ({error:'denied'})};
    }});
    assert.equal((await request('GET','/job')).retryable,false);
    assert.equal(calls,1);
  }
});

test('an unresponsive request times out and does not hold the page forever', async () => {
  const request = createClient({timeoutMs:10,fetch:async (_,options) => new Promise((_,reject) => {
    options.signal.addEventListener('abort',() => reject(new Error('Request timed out')));
  })});
  const result = await request('POST','/run',{});
  assert.equal(result.error,'Request timed out');
  assert.equal(result.retryable,true);
});

test('polling reconnects with bounded backoff and finishes the original job', async () => {
  const queue = [], waits = [], progress = [], retries = [], finished = [], paths = [];
  const responses = [{status:'running',progress:0.6,message:'answering'},
    ...Array(8).fill({error:'HTTP 502',retryable:true}),
    {status:'done',result:{session_id:'saved-session'}}];
  const watcher = followJob({jobId:'round-12345678', request:async (method,path) => {
    assert.equal(method,'GET'); paths.push(path); return responses.shift();
  }, setTimer:(fn,ms) => {queue.push(fn); waits.push(ms); return queue.length;}, clearTimer:() => {},
  onProgress:job => progress.push(job.progress), onRetry:p => retries.push(p),
  onDone:result => finished.push(result), onFail:error => assert.fail(error)});
  await watcher.ready;
  while (queue.length) await queue.shift()();
  assert.deepEqual(progress,[0.6]);
  assert.deepEqual(retries,Array(8).fill(0.6));
  assert(Math.max(...waits)<=30000);
  assert.deepEqual(finished,[{session_id:'saved-session'}]);
  assert(paths.every(path => path==='/api/interview/jobs/round-12345678'));
});

test('failed jobs show their message and polling stops', async () => {
  const errors = [];
  const watcher = followJob({jobId:'round-12345678',
    request:async () => ({status:'error',message:'Already running',error:{detail:'trace'}}),
    onProgress:() => {}, onRetry:() => assert.fail('no retry'), onDone:() => assert.fail('no result'),
    onFail:error => errors.push(error), setTimer:() => assert.fail('no timer'), clearTimer:() => {}});
  await watcher.ready;
  assert.deepEqual(errors,['Already running']);
});
