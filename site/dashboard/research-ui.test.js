const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

test('repeated polling releases the generation button exactly once on completion', () => {
  const source = fs.readFileSync(__dirname + '/research.js','utf8');
  const start = source.indexOf('  function setBusy(busy)');
  const end = source.indexOf('  /* ---------------------------------------------------------------- upload */',start);
  const elements = {rwRun:{disabled:false},rwSkipDigest:{disabled:false}};
  let opened = 0, released = 0;
  const ctx = {state:{busy:false},$:id=>elements[id],syncRunLabel(){},t:(_,f)=>f,
    setButtonBusy(button){opened++; const previous=button.disabled;button.disabled=true;return () => {released++;button.disabled=previous;};}};
  vm.createContext(ctx);
  vm.runInContext(source.slice(start,end),ctx);
  for (let n=0;n<5;n++) ctx.setBusy(true);
  ctx.setBusy(false);
  assert.equal(elements.rwRun.disabled,false);
  assert.equal(opened,1);
  assert.equal(released,1);
});
