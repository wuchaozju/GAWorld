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
