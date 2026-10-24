const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname,'url.js'),'utf8');
function boot(prefix='/GAWorld') {
  const calls=[];
  const original = async (input, init) => {calls.push({input,init}); return {ok:true};};
  const ctx = {document:{currentScript:{src:`https://mo.test${prefix}/site/url.js`}}, location:new URL(`https://mo.test${prefix}/site/dashboard/research.html`),URL,Request,fetch:original};
  vm.runInNewContext(source,ctx);
  return {ctx,calls,original,U:ctx.GAWorldURL};
}
test('mount URLs stay local, normalized and idempotent without changing external links',()=>{
  const {U}=boot();
  assert.equal(U.url('/api/config?x=1#result'),'/GAWorld/api/config?x=1#result');
  assert.equal(U.url('/GAWorld/api/config'),'/GAWorld/api/config');
  assert.equal(U.url('/GAWorld/../api/config'),'/GAWorld/api/config');
  assert.equal(U.url('/GAWorld/%2e%2e/api/config'),'/GAWorld/api/config');
  assert.equal(U.url('../../../api/config'),'/GAWorld/api/config');
  assert.equal(U.url('https://mo.test/api/config'),'https://mo.test/GAWorld/api/config');
  for(const value of ['https://elsewhere.test/api/config','//elsewhere.test/image.png','blob:https://mo.test/a','data:text/plain,a','#pane','?tab=worlds']) assert.equal(U.url(value),value);
  const config={api_key:'not-a-url'}; assert.equal(U.url(config),config);
  assert.equal(U.path('/GAWorld/workspace?view=worlds'),'/workspace?view=worlds');
  assert.equal(U.path('/GAWorld?x=1'),'/?x=1');
  assert.equal(U.path('/GAWorld-other/workspace'),'/GAWorld-other/workspace');
});
test('root deployment leaves fetch and values unchanged',async()=>{
  const {ctx,U,original}=boot('');
  assert.equal(ctx.fetch,original);
  assert.equal(U.url('/api/config'),'/api/config');
  assert.equal(U.html('<a href="/console">Open</a>'),'<a href="/console">Open</a>');
  const url=new URL('https://mo.test/api/config'); assert.equal(U.url(url),url);
});
test('fetch accepts Request bodies, headers and init overrides',async()=>{
  const {ctx,calls}=boot();
  const controller=new AbortController();
  const req=new Request('https://mo.test/api/research/analyze',{method:'POST',body:'{"title":"x"}',headers:{'Content-Type':'application/json','X-GAWorld-World':'w12345678'},credentials:'same-origin',signal:controller.signal});
  await ctx.fetch(req,{cache:'no-store'});
  const forwarded=calls[0].input;
  assert.equal(forwarded.url,'https://mo.test/GAWorld/api/research/analyze');
  assert.equal(forwarded.method,'POST');
  assert.equal(await forwarded.clone().text(),'{"title":"x"}');
  assert.equal(forwarded.headers.get('X-GAWorld-World'),'w12345678');
  assert.equal(forwarded.credentials,'same-origin');
  assert.equal(calls[0].init.cache,'no-store');
  controller.abort(); assert(forwarded.signal.aborted);
  await ctx.fetch(new URL('https://mo.test/api/worlds'));
  assert.equal(calls[1].input,'https://mo.test/GAWorld/api/worlds');
});
