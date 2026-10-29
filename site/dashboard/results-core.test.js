const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('./results-core.js');

test('joins capabilities and collapses identical storage copies, retaining deep-link aliases', () => {
  const base = {generated_at:'2026-10-01', frame_count:3, finished:true};
  const runs = C.mergeRuns([
    {...base,id:'output/cities/a/visualization/runs/r1',kind:'archive',trace_url:'/archive'},
    {...base,id:'output/cities/a/visualization',kind:'scenario',trace_url:'/scenario'},
    {...base,id:'output/worlds/b/visualization',kind:'scenario',trace_url:'/other'},
  ], [{id:'output/cities/a/visualization',sections:{economy:true}}]);
  assert.equal(runs.length, 2);
  assert.equal(runs[0].id, 'output/cities/a/visualization');
  assert.equal(runs[0].sections.economy, true);
  assert.equal(C.findRun(runs, 'output/cities/a/visualization/runs/r1').trace_url, '/scenario');
  assert.equal(C.findRun(runs, 'missing'), null);
});

test('partial archives and runs without provenance are never deduplicated', () => {
  const runs = C.mergeRuns([
    {id:'output/visualization',trace_url:'/a',generated_at:'same',frame_count:8},
    {id:'output/visualization/runs/1',trace_url:'/b',generated_at:'same',frame_count:7},
    {id:'output/visualization/runs/2',trace_url:'/c'},
    {id:'output/visualization/runs/3',trace_url:'/d'},
  ], []);
  assert.equal(runs.length, 4);
});

const trace = {agents:[{id:1,name:'A'},{id:2,name:'B'}], frames:[
  {day:9,time:'06:00',agents:[{agent_id:1,state:{stress:0.2}},{agent_id:2,state:{stress:0.8}}]},
  {day:9,time:'07:00',agents:[{agent_id:1,state:{stress:null}}]},
  {day:10,time:'06:00',agents:[{agent_id:1,state:{stress:0.6}},{agent_id:2,state:{stress:0.4}}]},
]};

test('curve x positions use simulation time rather than proportional frame indexes', () => {
  assert.deepEqual(C.frameTimes(trace), [0,60,1440]);
  assert.equal(C.nearestFrame(trace, 0.05), 1);
  assert.equal(C.nearestFrame(trace, 1), 2);
});

test('state curves keep missing samples null and population means use observed residents', () => {
  assert.deepEqual(C.series(trace,'stress',1), [0.2,null,0.6]);
  assert.deepEqual(C.series(trace,'stress',null), [0.5,null,0.5]);
  assert.deepEqual(C.series(trace,'absent',1), [null,null,null]);
  assert.deepEqual(C.metrics(trace), ['stress']);
  assert.equal(C.resident(trace,1,2), null);
  assert.equal(C.roster(trace).length, 2);
});

test('zero is a real observation, while non-numeric state values are missing', () => {
  const data = {frames:[{agents:[{agent_id:1,state:{a:0,b:'0.9',c:false}}]}]};
  assert.deepEqual(C.metrics(data), ['a']);
  assert.deepEqual(C.series(data,'a',1), [0]);
  assert.deepEqual(C.series(data,'b',1), [null]);
});

test('indexes event onset once, even when the event persists across frames', () => {
  const data = {frames:[
    {day:1,time:'08:00',env_events:[{id:'rain',name:'Rain',severity:0}]},
    {day:1,time:'09:00',env_events:[{id:'rain',name:'Rain',severity:0}]},
    {day:2,time:'08:00',env_events:[{id:'heat',name:'Heat'}]},
  ]};
  assert.deepEqual(C.events(data).map(e=>[e.index,e.name]), [[0,'Rain'],[2,'Heat']]);
});

test('empty traces and missing clocks remain navigable without invented values', () => {
  assert.deepEqual(C.frameTimes({frames:[{},{}]}), [0,1]);
  assert.deepEqual(C.frameTimes(null), []);
  assert.equal(C.nearestFrame(null,0.5), 0);
  assert.deepEqual(C.roster(null), []);
  assert.deepEqual(C.events(null), []);
  assert.equal(C.resident(null,0,1), null);
});

test('identical timestamps remain separate samples instead of collapsing curves', () => {
  assert.deepEqual(C.frameTimes({frames:[{day:1,time:'08:00'},{day:1,time:'08:00'}]}),[0,1]);
});

test('playback stops at the last frame and a fresh play at the end restarts', () => {
  assert.deepEqual(C.advance(1,3), {index:2,done:true});
  assert.deepEqual(C.advance(0,3), {index:1,done:false});
  assert.deepEqual(C.advance(0,0), {index:0,done:true});
});

test('historical analysis uses the selected trace names rather than active-city identities', () => {
  const names = [{id:'1',name:'乌镇居民'}];
  assert.equal(C.labelAnalytics('history',{agents:[{id:1,name:'London resident'}]},names).agents[0].name,'乌镇居民');
  assert.equal(C.labelAnalytics('economy',{ledger:[{id:1,name:'London resident'}],wealth:[]},names).ledger[0].name,'乌镇居民');
  const social = C.labelAnalytics('social',{nodes:[{id:'1',agent_id:1,kind:'agent',label:'London resident'},{id:'1:mother',kind:'ghost',label:'母亲'}]},names);
  assert.deepEqual(social.nodes.map(node=>node.label),['乌镇居民','母亲']);
  assert.equal(C.labelAnalytics('behavior',{habits:[{agent_id:1,name:'London resident'}]},names).habits[0].name,'乌镇居民');
});
