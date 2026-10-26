const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

function harness(links = []) {
  const elements = new Map();
  function element() {
    return {innerHTML:'',textContent:'',hidden:false,style:{},classList:{add(){},remove(){},toggle(){}},
      addEventListener(){},setAttribute(){},querySelector(){return element();},querySelectorAll(){return [];}};
  }
  const requests = [];
  const document = {body:{hasAttribute:()=>true},getElementById:id=>{
    if (!elements.has(id)) elements.set(id,element()); return elements.get(id);
  },querySelectorAll:selector=>selector === 'link[rel="stylesheet"]' ? links.map(href=>({getAttribute:()=>href})) : [],addEventListener(){}};
  const window = {addEventListener(){},GAWorldAnalyticsExport:{},GAWorldResultsCore:require('./results-core.js'),location:{href:'http://localhost/analytics.html'}};
  const context = {window,document,URL,URLSearchParams,MutationObserver:class {observe(){}},
    requestAnimationFrame(){},setTimeout(){},__:(key)=>key,__f:(key)=>key,
    fetch:url=>new Promise((resolve,reject)=>requests.push({url,resolve:data=>resolve({ok:true,json:async()=>data,text:async()=>data}),reject})),
  };
  vm.runInNewContext(fs.readFileSync(__dirname+'/analytics.js','utf8').replace('if (!managed) load();','window.testReport = {reportCss};'),context);
  return {api:window.GAWorldAnalytics,requests,elements,report:window.testReport};
}
const flush = async()=>{for(let i=0;i<8;i++) await Promise.resolve();};
const runList = {runs:[{id:'a',sections:{}},{id:'b',sections:{}}]};
function answerRun(h, id, count) {
  for (const request of h.requests.filter(r=>r.url.includes('run='+id))) {
    request.resolve(request.url.includes('/overview') ? {agent_count:count,top_movers:[],sim_meta:{}} : {available:false,agents:[],metrics:[]});
  }
}

test('switching runs invalidates delayed metadata before it can fetch sections', async()=>{
  const h = harness();
  const a = h.api.loadRun('a');
  const b = h.api.loadRun('b');
  h.requests[0].resolve(runList); h.requests[1].resolve(runList);
  await flush();
  assert.equal(await a,false);
  h.requests.find(r=>r.url === '/api/auth/me').resolve({mode:'accounts',user:{role:'member'}});
  await flush();
  assert.equal(h.requests.some(r=>r.url.includes('run=a')),false);
  assert.equal(h.requests.some(r=>r.url === '/api/analytics/system'),false);
  answerRun(h,'b',222); await flush();
  assert.equal(await b,true);
  assert.match(h.elements.get('anOverview').innerHTML,/222/);
});

test('late results cannot overwrite the new run or repopulate cleared charts', async()=>{
  const h = harness();
  const a = h.api.loadRun('a'); h.requests[0].resolve(runList); await flush();
  h.requests.find(r=>r.url === '/api/auth/me').resolve({mode:'accounts',user:{role:'member'}}); await flush();
  const b = h.api.loadRun('b');
  assert.equal(h.elements.get('anOverview').innerHTML,'');
  h.requests.filter(r=>r.url === '/api/analytics/runs').at(-1).resolve(runList); await flush();
  h.requests.filter(r=>r.url === '/api/auth/me').at(-1).resolve({mode:'accounts',user:{role:'member'}}); await flush();
  answerRun(h,'b',222); await flush();
  assert.equal(await b,true);
  answerRun(h,'a',111); await flush();
  assert.equal(await a,false);
  assert.match(h.elements.get('anOverview').innerHTML,/222/);
  assert.doesNotMatch(h.elements.get('anOverview').innerHTML,/111/);
});

test('offline HTML styles include the shared tokens and remove server-only imports', async()=>{
  const h = harness(['/site/dashboard/styles.css']);
  const result = h.report.reportCss();
  assert.equal(h.requests.some(request=>request.url === '/site/tokens.css'),true);
  h.requests.find(request=>request.url === '/site/tokens.css').resolve(':root{--paper:#fff}');
  h.requests.find(request=>request.url === '/site/dashboard/styles.css').resolve('@import url("/site/tokens.css"); body{color:var(--ink)}');
  const css = await result;
  assert.match(css,/--paper:#fff/);
  assert.doesNotMatch(css,/@import/);
});
