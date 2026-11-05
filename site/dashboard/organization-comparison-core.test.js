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
    factors:{roles:'same',topology:'candidate',rounds:'same',review:'same',decision:'same'},
    scope_factors:{candidate:['topology'],baseline:[]},scope:'topology',repeats:7,seed:11,delta:.2,limits:{calls:19},max_tokens:512};
  const fields=core().protocolFields(p);
  assert.equal(fields.provider,'pinned');
  assert.deepEqual(fields.ids,[9,8]);
  assert.equal(fields.baseline,'hierarchy');
  assert.equal(fields.repeats,7);
  assert.equal(fields.seed,11);
  assert.equal(fields.delta,.2);
  assert.equal(fields.calls,19);
  assert.equal(fields.tokens,512);
  assert.deepEqual(fields.scopeFactors,{candidate:['topology'],baseline:[]});
  assert.equal(fields.factors.topology,'candidate');
  // A protocol frozen before the arms existed still has two of them.
  assert.deepEqual(fields.arms.map(a=>a.id),['candidate','baseline']);
});

test('more than two organizations travel with the study settings', () => {
  const c=core();
  const state={method:{name:'a'},benchmark:null,ids:[1,2],provider:'p',baseline:'random',factors:{topology:'candidate'},
    candidates:[{label:'层级做法',method:{name:'h',roles:['甲','乙']}},{label:'随机做法',method:{name:'r',roles:['甲','乙']}}]};
  const payload=c.settings(state,{repeats:2});
  assert.equal(payload.candidates.length,2);
  assert.equal(payload.candidates[0].label,'层级做法');
  assert.deepEqual(payload.candidates[1].method.roles,['甲','乙']);
  // A study without extra candidates sends an empty list, not a missing key.
  assert.deepEqual(c.settings({...state,candidates:[]},{}).candidates,[]);
});

test('every arm is named and every arm has its own scope', () => {
  const c=core();
  const p={candidate:{name:'主'},baseline:{name:'对'},arms:[
    {id:'candidate',label:'主',is_control:false},{id:'candidate-2',label:'第二',is_control:false},{id:'baseline',label:'对',is_control:true}],
    scope_factors:{candidate:['topology'],'candidate-2':['roles'],baseline:[]}};
  assert.equal(c.armLabel(p,'candidate-2'),'第二');
  assert.deepEqual(c.scopeOf(p,'candidate-2'),['roles']);
  assert.deepEqual(c.scopeOf(p,'baseline'),[]);
  // A protocol without arms still answers with two.
  assert.deepEqual(c.armsOf({candidate:{name:'主'},baseline:{name:'对'}}).map(a=>a.id),['candidate','baseline']);
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

test('paused control flags do not disable stop and the preview matches the frozen mechanisms', () => {
  assert.equal(core().controls({status:'paused',control:'pause'}).stopDisabled,false);
  const candidate={roles:['a','b'],rounds:2,decision:'vote',review:false,revisions:0,topology:{kind:'full'}};
  const control={roles:['coordinator','worker'],rounds:1,decision:'synthesis',review:true,revisions:1,topology:{kind:'hierarchy'}};
  // Only the communication structure may differ: the rest is held equal.
  const factors={roles:'same',topology:'candidate',rounds:'same',review:'same',decision:'same'};
  const preview=core().applyFactors(candidate,control,factors);
  assert.equal(preview.rounds,2);
  assert.equal(preview.review,false);
  assert.deepEqual(preview.roles,candidate.roles);
  assert.equal(preview.topology.kind,'hierarchy');
  assert.equal(control.review,true);
  // A factor allowed to differ is left alone.
  const open=core().applyFactors(candidate,control,Object.assign({},factors,{review:'candidate'}));
  assert.equal(open.review,true);
  assert.equal(open.revisions,1);
  // A custom baseline keeps the roles its author wrote.
  const custom=core().applyFactors(candidate,control,factors,false);
  assert.deepEqual(custom.roles,['coordinator','worker']);
});

test('the factors that differ are named, and the default keeps only the structure different', () => {
  const c=core();
  assert.deepEqual(c.factorTable({}),c.DEFAULT_FACTORS);
  assert.equal(c.DEFAULT_FACTORS.topology,'candidate');
  assert.equal(c.DEFAULT_FACTORS.roles,'same');
  const candidate={roles:['a','b'],rounds:2,decision:'auto',review:false,revisions:0,topology:{kind:'full'}};
  const control={roles:['a','b'],rounds:2,decision:'auto',review:false,revisions:0,topology:{kind:'hierarchy'}};
  assert.deepEqual(c.differingFactors(candidate,control),['topology']);
  assert.deepEqual(c.differingFactors(candidate,Object.assign({},control,{roles:['x','y']})),['roles','topology']);
  assert.equal(c.factorLabel('topology',false),'通信结构');
  assert.equal(c.factorLabel('topology',true),'Communication structure');
});

test('the saved settings carry the factor table, and a duration reads in minutes and hours', () => {
  const c=core();
  const state={method:{name:'m'},benchmark:{tasks:[]},ids:[1,2],provider:'x',baseline:'random',
    factors:{roles:'same',topology:'candidate',rounds:'same',review:'same',decision:'same'}};
  const payload=c.settings(state,{});
  assert.equal(payload.factors.topology,'candidate');
  assert.equal(payload.factors.rounds,'same');
  assert.equal(c.duration(90,false),'2分钟');
  assert.equal(c.duration(7200,false),'2小时');
  assert.equal(c.duration(7200,true),'2 h');
});
