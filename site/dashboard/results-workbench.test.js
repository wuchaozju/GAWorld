const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const C = require('./results-core.js');

function harness() {
  const elements = new Map(), pending = [], focuses = [];
  const element = id => ({hidden:id === 'systemTab', value:'',innerHTML:'',textContent:'',
    setAttribute(){},addEventListener(){},querySelectorAll(){return [];}});
  const document = {body:{hasAttribute:()=>true},getElementById:id=>{
    if (!elements.has(id)) elements.set(id,element(id)); return elements.get(id);
  },querySelectorAll:()=>[],querySelector:()=>({addEventListener(){}}),addEventListener(){}};
  class MapView {setTrace(){} renderEmpty(){} render(){}}
  const window = {GAWorldResultsCore:C,CityMapView:MapView,__:key=>key,__f:key=>key,
    addEventListener(){},dispatchEvent(){},GAWorldAnalytics:{clear(){},
      loadRun:()=>new Promise(resolve=>pending.push(resolve)),focus:id=>focuses.push(id)}};
  window.parent = window;
  // Expose lexical state only inside this isolated VM; run the production lifecycle unchanged.
  const source = fs.readFileSync(__dirname+'/results-workbench.js','utf8')
    .replace('setView(state.view); refresh(false);','window.test = {state,loadAnalytics,loadRun};');
  vm.runInNewContext(source,{window,document,location:{href:'http://localhost/analytics.html',search:''},
    history:{replaceState(){}},URL,URLSearchParams,AbortController,Event,clearInterval(){},
    fetch:url=>url === '/trace' ? Promise.resolve({ok:true,json:async()=>({frames:[]})}) : new Promise(()=>{})});
  return {api:window.test,pending,focuses};
}

test('same-run refresh invalidates old analytics work and retains the new pending request', async()=>{
  const {api,pending} = harness();
  const run = {id:'a',trace_url:'/trace',aliases:['a']};
  Object.assign(api.state,{run,runs:[run],view:'analysis'});
  const obsolete = api.loadAnalytics(false);
  await api.loadRun(run,true);
  assert.equal(pending.length,2);
  pending[0](false); await obsolete;
  const current = api.loadAnalytics(false);
  assert.equal(pending.length,2);
  pending[1](true); await current;
  assert.equal(api.state.analyticsRun,'a');
});

test('failed export loading can retry and uses the resident selected while it was pending', async()=>{
  const {api,pending,focuses} = harness();
  Object.assign(api.state,{run:{id:'a'},view:'replay'});
  const first = api.loadAnalytics(true);
  pending[0](false); await first;
  assert.equal(api.state.analyticsRun,null);
  const retry = api.loadAnalytics(true);
  api.state.resident = '3'; pending[1](true); await retry;
  assert.equal(api.state.analyticsRun,'a');
  assert.deepEqual(focuses,['3']);
});

test('workbench controls and bilingual messages have complete bindings',()=>{
  const script = fs.readFileSync(__dirname+'/results-workbench.js','utf8');
  const html = fs.readFileSync(__dirname+'/analytics.html','utf8');
  for (const [,id] of script.matchAll(/\$\('([^']+)'\)/g)) assert.ok(html.includes(`id="${id}"`),id);
  const zh = JSON.parse(fs.readFileSync(__dirname+'/locales/zh-CN.json','utf8'));
  const en = JSON.parse(fs.readFileSync(__dirname+'/locales/en.json','utf8'));
  const keys = new Set([...script.matchAll(/\bt\('([a-z_]+)'/g)].map(match=>'results.'+match[1]));
  for (const [,key] of html.matchAll(/data-i18n[^=]*="(results\.[^"]+)"/g)) keys.add(key);
  for (const key of keys) {
    assert.equal(typeof zh[key],'string',key+' Chinese');
    assert.equal(typeof en[key],'string',key+' English');
    assert.deepEqual(zh[key].match(/\{[^}]+\}/g),en[key].match(/\{[^}]+\}/g),key+' placeholders');
  }
  assert.equal(zh['nav.analytics'],'回放与分析');
  assert.equal(en['nav.analytics'],'Replay & Analysis');
});
