const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

test('comparison core exists', () => {
  assert.ok(fs.existsSync(path.join(__dirname, 'organization-comparison-core.js')));
});

function core() { return require('./organization-comparison-core.js'); }

test('stage prerequisites require reviewed rules and a saved study', () => {
  assert.equal(core().canVisit(1, {}), false);
  assert.equal(core().canVisit(1, {method:{}, reviewed:false}), false);
  assert.equal(core().canVisit(3, { method: {}, benchmark: {} }), true);
  assert.equal(core().canVisit(5, { method: {}, benchmark: {} }), false);
});

test('untrusted names are escaped and graph has no executable markup', () => {
  assert.equal(core().escape('<img onerror="x">'), '&lt;img onerror=&quot;x&quot;&gt;');
  const svg = core().graph({roles: ['<script>', 'B'], topology: {kind: 'full'}});
  assert.ok(!svg.includes('<script>'));
  assert.ok(svg.includes('&lt;script&gt;'));
});

test('payload uses selected resident ids and benchmark, never launches implicitly', () => {
  const s = {method: {name:'test'}, benchmark: {tasks:[]}, ids:[2,4,6], provider:'x'};
  const p = core().settings(s, {repeats:3, seed:10, delta:0});
  assert.deepEqual(p.agent_ids, [2,4,6]);
  assert.equal(p.candidate.name, 'test');
  assert.equal(p.run, undefined);
});

test('only running studies poll; uncertain never means equal', () => {
  assert.equal(core().shouldPoll({status:'paused'}), false);
  assert.equal(core().shouldPoll({status:'running'}), true);
  assert.ok(!core().verdict('uncertain', false).includes('相同'));
});

test('cooperation selection sends only owned method identity and clears conflicting overrides', () => {
  const c = require('./collaboration-core.js');
  const payload = c.cooperationPayload([1,2], 'write', 1, {'1':'custom'}, {id:'Mabc',version:2,method:{private:'hidden'}});
  assert.equal(payload.organization_method_id, 'Mabc');
  assert.equal(payload.organization_method_version, 2);
  assert.equal(payload.leader_id, undefined);
  assert.deepEqual(payload.role_overrides, {});
  assert.equal(payload.method, undefined);
});

test('review without revision round-trips and history settings are restored', () => {
  assert.deepEqual(core().reviewFields({review:true,revisions:0}),{review:true,revisions:0});
  const p={model:{name:'pinned'},members:[{id:9},{id:8}],baseline:{topology:{kind:'hierarchy'}},
    scope:'whole_method',repeats:7,seed:11,delta:.2,limits:{calls:19},max_tokens:512};
  assert.deepEqual(core().protocolFields(p),{provider:'pinned',ids:[9,8],baseline:'hierarchy',mode:'whole_method',repeats:7,seed:11,delta:.2,calls:19,tokens:512});
});

test('rate limits have a readable reason, cooldown and read-only polling', () => {
  const r={status:'rate_limited',error:'HTTPError',error_info:{kind:'token_plan_rate_limit',retry_at:1000}};
  assert.match(core().failureMessage(r,false), /速率限制/);
  assert.equal(core().coolingDown(r,900),true);
  assert.equal(core().coolingDown(r,1001),false);
  assert.equal(core().shouldPoll(r),true);
  assert.ok(!core().failureMessage({error:'HTTPError'},false).includes('HTTPError'));
});

test('study links open only a validated local comparison identifier', () => {
  const id='C'+'a'.repeat(24);
  assert.equal(core().studyFromSearch('?tab=organization-intelligence&comparison='+id),id);
  assert.equal(core().studyFromSearch('?comparison=../../elsewhere'),null);
});

test('successful history response can contain the saved experiment error', async () => {
  const record={id:'saved',status:'interrupted',error:'HTTPError'};
  assert.equal(await core().responseValue({ok:true,json:async()=>record}),record);
  await assert.rejects(()=>core().responseValue({ok:false,status:429,json:async()=>({error:'等待配额'})}),/等待配额/);
});

test('controls distinguish pause pending, resumable error, cooldown and completion', () => {
  const controls=core().controls;
  assert.equal(controls({status:'running',control:'pause'}).pauseLabel,'pausing');
  assert.equal(controls({status:'running',control:'pause'}).pauseDisabled,true);
  assert.equal(controls({status:'paused'}).resume,true);
  assert.equal(controls({status:'interrupted',resume_requires_recovery:true}).retry,true);
  assert.equal(controls({status:'rate_limited',error_info:{retry_at:Date.now()/1000+60}}).retryDisabled,true);
  assert.equal(controls({status:'completed'}).retry,false);
  assert.equal(controls({status:'completed'}).pause,false);
  assert.equal(controls({status:'paused'},true).resumeDisabled,true);
});

test('custom baseline must be reviewed before proceeding and round-trips as frozen rules', () => {
  const method={roles:['a','b'],topology:{kind:'custom',edges:[[0,1]]}};
  const state={method:{},reviewed:true,baseline:'custom',baselineMethod:null,ids:[1,2]};
  assert.equal(core().canVisit(2,state),false);
  state.baselineMethod=method;
  assert.equal(core().canVisit(2,state),true);
  assert.deepEqual(core().settings(state,{}).baseline_method,method);
  const p={model:{name:'test'},members:[{id:1},{id:2}],baseline:method,baseline_kind:'custom',limits:{}};
  assert.equal(core().protocolFields(p).baseline,'custom');
});

test('paused control flags do not disable stop and topology preview matches frozen mechanisms', () => {
  assert.equal(core().controls({status:'paused',control:'pause'}).stopDisabled,false);
  const candidate={roles:['a','b'],rounds:2,decision:'vote',review:false,revisions:0};
  const control={roles:['coordinator','worker'],rounds:1,decision:'synthesis',review:true,revisions:1,topology:{kind:'hierarchy'}};
  const preview=core().effectiveBaseline(candidate,control,'topology');
  assert.equal(preview.rounds,2);
  assert.equal(preview.review,false);
  assert.deepEqual(preview.roles,candidate.roles);
  assert.equal(preview.topology.kind,'hierarchy');
  assert.equal(control.review,true);
  assert.deepEqual(core().effectiveBaseline(candidate,control,'whole_method'),control);
});
