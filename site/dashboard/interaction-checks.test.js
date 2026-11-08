const test = require('node:test');
const assert = require('node:assert/strict');
const {inspect} = require('./interaction-checks.js');
test('default off adds no calls', () => assert.equal(inspect().extraCalls, 0));
test('four arms each round', () => {
  const v = inspect({enabled:true,rounds:3,group_size:4});
  assert.equal(v.extraCalls,12); assert.equal(v.error,'');
});
test('invalid enabled settings block execution', () => {
  for (const rounds of [0,4,true,1.5,null,'2']) assert.ok(inspect({enabled:true,rounds,group_size:4}).error);
  for (const group_size of [1,9,2.5]) assert.ok(inspect({enabled:true,rounds:1,group_size}).error);
  assert.equal(inspect({enabled:false,rounds:0}).error,'');
});
