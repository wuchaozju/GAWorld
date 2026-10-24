const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const navigation = require('./navigation');
function page({user=null, embedded=false}={}) {
  const location = {pathname:'/explore',search:'',hash:'',href:'',replace(target) { this.href=target; },reload() { this.reloaded=true; }};
  const nodes = {accountNav:{},notice:{}};
  const document = {documentElement:{classList:{add(){}}},createElement(){return {};},head:{appendChild(){}},getElementById(id){return nodes[id];},addEventListener(){}};
  const window = {location,GAWorldNavigation:navigation};
  window.parent = embedded ? {location:{},history:{replaceState(a,b,target){ this.target=target; }},GAWorldConsole:true} : window;
  const context={window,document,location,URL,URLSearchParams,setTimeout,clearTimeout,fetch:async()=>({ok:true,json:async()=>({mode:'accounts',user})})};
  vm.runInNewContext(fs.readFileSync(require.resolve('./common'),'utf8'),context);
  return window;
}
test('anonymous public search and version switching keep their public URLs',async()=>{
  const w=page(); await w.Community.ready;
  w.Community.navigate('/explore?q=community');
  assert.equal(w.location.href,'/explore?q=community');
  w.Community.navigate('/publications/p1?version=1');
  assert.equal(w.location.href,'/publications/p1?version=1');
});
test('signed-in old links redirect into the existing console',async()=>{
  const w=page({user:{id:1,nickname:'alice'}}); await w.Community.ready;
  assert.equal(w.location.href,'/console#explore');
});
test('embedded detail navigation updates the parent without nesting shells',async()=>{
  const w=page({user:{id:1,nickname:'alice'},embedded:true}); await w.Community.ready;
  w.Community.navigate('/publications/p1?version=2');
  assert.equal(w.parent.location.href,'/console#explore/publications/p1?version=2');
  assert.equal(w.location.href,'');
});
test('world changes reload the entire console at the target workbench',async()=>{
  const w=page({user:{id:1,nickname:'alice'},embedded:true}); await w.Community.ready;
  w.parent.location.reload=function(){this.reloaded=true;};
  w.Community.navigate('/site/dashboard/research.html?plan_id=p1',true);
  assert.equal(w.parent.history.target,'/console#research?plan_id=p1');
  assert.equal(w.parent.location.reloaded,true);
});
test('a lazy personal view rejects a different world from another browser tab',async()=>{
  const w=page({user:{id:1,nickname:'alice'},embedded:true});
  w.parent.GAWorldConsole={worldReady:Promise.resolve('world-a')};
  await w.Community.ready;
  await assert.rejects(w.Community.bindWorld('world-b'),/世界.*刷新/);
  assert.equal(w.Community.world,null);
  await w.Community.bindWorld('world-a');
  assert.equal(w.Community.world,'world-a');
});
