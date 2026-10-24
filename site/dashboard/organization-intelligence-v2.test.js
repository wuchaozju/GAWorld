const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness() {
  const nodes = new Map();
  const requests = [];
  const record = {id:'OI2fixture', status:'draft', committed:0, total:2000, build_id:'frozen', counts:{pending:2000}, protocol:{seeds:[1,2],version:'OI-2.0'}};
  const document = {
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, {hidden:false, disabled:false, value:id==='oi2Seeds'?'10':'20261024', textContent:'', innerHTML:'', handlers:{}, addEventListener(event, fn){this.handlers[event]=fn;}, appendChild(){}, replaceChildren(){}, setAttribute(){}});
      return nodes.get(id);
    },
    createElement(){return {textContent:'', className:'', setAttribute(){}, addEventListener(){}, click(){}, remove(){}};},
    body:{appendChild(){}}
  };
  const context = {document, location:{search:'', origin:'http://localhost:8767'}, history:{replaceState(){}}, URLSearchParams, URL, Blob, setTimeout(){}, clearTimeout(){}, console,
    fetch:async (url, options={}) => {
      requests.push({url,options});
      let data = url.endsWith('/results') ? {analysis:{complete:false,cells:[],contrasts:[]}} : options.method==='POST' ? record : url.endsWith('v2') ? {engine:{version:'OI-2.0',build_id:'server',workspace_matches:true,pid:1},studies:[]} : record;
      return {ok:true, json:async()=>data};
    }};
  vm.runInNewContext(fs.readFileSync(__dirname+'/organization-intelligence-v2.js','utf8'),context);
  return {nodes,requests,context};
}
const settle = () => new Promise(resolve => setImmediate(resolve));

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
  await h.nodes.get('oi2Run').handlers.click();
  assert.equal(JSON.parse(h.requests.find(r=>r.url.endsWith('/run')).options.body).expected_build,'frozen');
});
