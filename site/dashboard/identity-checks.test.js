const {test} = require('node:test');
const assert = require('node:assert/strict');
const identity = require('./identity-checks.js');
const settings = {enabled:true,template:'共同材料 {{identity}}。',a:'甲',b:'乙'};

test('opt-out adds no calls and permits an unfinished draft', () => {
  assert.deepEqual(identity.inspect(), {enabled:false,extraCalls:0,error:'',a:'',b:''});
  assert.equal(identity.inspect({enabled:false,template:'draft'}).error,'');
});
test('enabled pair adds exactly two calls and substitutes only the shared token', () => {
  const view=identity.inspect(settings);
  assert.equal(view.extraCalls,2);
  assert.equal(view.error,'');
  assert.equal(view.a,'共同材料 甲。');
  assert.equal(view.b,'共同材料 乙。');
});
test('invalid or duplicated cues and malformed templates block execution', () => {
  for (const patch of [{a:''},{b:'甲'},{a:[]},{template:'x'},{template:'{{identity}}{{identity}}'},{b:'{{identity}}'}]) {
    assert.ok(identity.inspect({...settings,...patch}).error);
  }
});
test('text is not interpreted as HTML or JavaScript by the preview helper', () => {
  const view=identity.inspect({...settings,a:'<img src=x onerror=alert(1)>'});
  assert.equal(view.a,'共同材料 <img src=x onerror=alert(1)>。');
});
test('length bounds count Unicode characters consistently with Python', () => {
  assert.equal(identity.inspect({...settings,a:'😀'.repeat(100)}).error,'');
  assert.ok(identity.inspect({...settings,a:'😀'.repeat(101)}).error);
});
