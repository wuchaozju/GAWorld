const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness(settings = {}) {
  const nodes = new Map();
  const requests = [];
  const record = {id:'OI2fixture', status:'draft', committed:0, total:2000, build_id:'frozen', counts:{pending:2000}, protocol:{seeds:[1,2],version:'OI-2.0'}, ...settings.record};
  const document = {
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, {hidden:false, disabled:false, value:id==='oi2Seeds'?'10':'20261024', textContent:'', innerHTML:'', children:[], handlers:{}, addEventListener(event, fn){this.handlers[event]=fn;}, appendChild(child){this.children.push(child);}, replaceChildren(){this.children=[];}, setAttribute(){}});
      return nodes.get(id);
    },
    createElement(){return {textContent:'', className:'', children:[], appendChild(child){this.children.push(child);}, setAttribute(){}, addEventListener(){}, click(){}, remove(){}};},
    body:{appendChild(){}}
  };
  const context = {document, location:{search:'', origin:'http://localhost:8767'}, history:{replaceState(){}}, URLSearchParams, URL, Blob, setTimeout(){}, clearTimeout(){}, console,
    fetch:async (url, options={}) => {
      requests.push({url,options});
      let data = url.endsWith('/results') ? {analysis: settings.analysis || {complete:false,cells:[],contrasts:[]}} : options.method==='POST' ? record : url.endsWith('v2') ? {engine:{version:'OI-2.0',build_id:'server',workspace_matches:true,pid:1,...settings.engine},studies:[]} : record;
      return {ok:true, json:async()=>data};
    }};
  vm.runInNewContext(fs.readFileSync(__dirname+'/organization-intelligence-v2.js','utf8'),context);
  return {nodes,requests,context,record};
}
const settle = () => new Promise(resolve => setImmediate(resolve));
const textOf = node => node.textContent + (node.children || []).map(textOf).join(' ');

test('initialization is read-only and identifies zero-call runtime',async()=>{
  const h=harness(); await settle();
  assert.equal(h.requests.length,1);
  assert.equal(h.requests[0].options.method,undefined);
  assert.match(h.nodes.get('oi2Runtime').textContent,/OI-2.0/);
  assert.equal(h.nodes.get('oi2Create').disabled,false);
});
test('freeze sends handshake and never auto starts',async()=>{
  const h=harness(); await settle();
  await h.nodes.get('oi2Form').handlers.submit({preventDefault(){}}); await settle();
  const posts=h.requests.filter(r=>r.options.method==='POST');
  assert.equal(posts.length,1);
  assert.equal(JSON.parse(posts[0].options.body).expected_build,'server');
  assert.ok(!posts[0].url.endsWith('/run'));
  assert.equal(h.nodes.get('oi2Run').hidden,false);
  assert.equal(h.nodes.get('oi2Run').textContent,'开始实验');
  assert.equal(h.nodes.get('oi2Status').textContent,'设置已保存，尚未开始');
  assert.doesNotMatch(h.nodes.get('oi2Metrics').textContent,/PID|构建|提交/);
  await h.nodes.get('oi2Run').handlers.click();
  assert.equal(JSON.parse(h.requests.find(r=>r.url.endsWith('/run')).options.body).expected_build,'frozen');
});

test('budget explains practice and comparison tasks in ordinary language',async()=>{
  const h=harness(); await settle();
  h.nodes.get('oi2Seeds').value='2';
  h.nodes.get('oi2Seeds').handlers.input();
  assert.match(h.nodes.get('oi2Budget').textContent,/2 组/);
  assert.match(h.nodes.get('oi2Budget').textContent,/400 题/);
  assert.match(h.nodes.get('oi2Budget').textContent,/80 题练习/);
  assert.match(h.nodes.get('oi2Budget').textContent,/320 题正式比较/);
  assert.doesNotMatch(h.nodes.get('oi2Budget').textContent,/种子|单元|留出/);
});

test('partial and paused studies describe continuation without giving results',async()=>{
  const h=harness({record:{status:'paused',committed:7,counts:{pending:1993}}}); await settle();
  await h.nodes.get('oi2Form').handlers.submit({preventDefault(){}}); await settle();
  assert.equal(h.nodes.get('oi2Run').textContent,'继续实验');
  assert.match(h.nodes.get('oi2Metrics').textContent,/已完成 7/);
  assert.match(h.nodes.get('oi2Notice').textContent,/已完成的题不会重做/);
  assert.equal(textOf(h.nodes.get('oi2Results')),'');
});

test('results explain a negative difference and uncertainty without reversing its meaning',async()=>{
  const h=harness({record:{status:'completed',committed:2000},analysis:{complete:true,cells:[{procedure:1,memory:1,turnover:1,net_reward:20}],contrasts:[{id:'primary_memory_after_turnover',mean:-0.25,ci95:[-1,0.5],n_seeds:2}]}}); await settle();
  await h.nodes.get('oi2Form').handlers.submit({preventDefault(){}}); await settle();
  const text=textOf(h.nodes.get('oi2Results'));
  assert.match(text,/低 0.250 分/);
  assert.match(text,/跨过 0/);
  assert.match(text,/暂时不能确定/);
  assert.doesNotMatch(text,/种子配对|主比较|机制结果/);
});

test('incompatible runtime gives a plain explanation and cannot save settings',async()=>{
  const h=harness({engine:{workspace_matches:false}}); await settle();
  assert.equal(h.nodes.get('oi2Create').disabled,true);
  assert.match(h.nodes.get('oi2Ready').textContent,/重启服务/);
  assert.match(h.nodes.get('oi2Runtime').textContent,/server/);
  assert.equal(h.requests.filter(r=>r.options.method==='POST').length,0);
});

test('positive difference stays conditional on this simulation and explains uncertainty',async()=>{
  const h=harness({record:{status:'completed'},analysis:{complete:true,cells:[],contrasts:[{id:'primary_memory_after_turnover',mean:0.77,ci95:[0.28,1.345],n_seeds:10}]}}); await settle();
  await h.nodes.get('oi2Form').handlers.submit({preventDefault(){}}); await settle();
  const text=textOf(h.nodes.get('oi2Results'));
  assert.match(text,/高 0.770 分/);
  assert.match(text,/不能直接代表现实团队/);
  assert.match(text,/10 组重复实验/);
  assert.match(text,/0.280, 1.345/);
});

test('zero difference with one repeat does not imply an improvement',async()=>{
  const h=harness({record:{status:'completed'},analysis:{complete:true,cells:[],contrasts:[{id:'primary_memory_after_turnover',mean:0,ci95:null,n_seeds:1}]}}); await settle();
  await h.nodes.get('oi2Form').handlers.submit({preventDefault(){}}); await settle();
  const text=textOf(h.nodes.get('oi2Results'));
  assert.match(text,/平均成绩没有差别/);
  assert.match(text,/只做了一组/);
  assert.doesNotMatch(text,/高 0|低 0|支持保留记录有帮助/);
});
