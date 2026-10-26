const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

test('map residents offer keyboard and pointer selection without changing other map consumers', () => {
  const window = {};
  vm.runInNewContext(fs.readFileSync(__dirname+'/citymap-view.js','utf8'),{window,Map,Number,Array});
  const View = window.CityMapView;
  const handlers = {};
  let selected = null;
  const host = {addEventListener:(event,fn)=>{ handlers[event]=fn; }};
  const view = Object.create(View.prototype);
  Object.assign(view,{host,onSelectAgent:id=>{selected=id;},_buildControls:()=>{}});
  view._setupInteractions();
  const target = {closest:()=>({dataset:{mapAgent:'12'}})};
  assert.equal(typeof handlers.click,'function');
  handlers.click({target,preventDefault(){},stopPropagation(){}});
  assert.equal(selected,12);
  selected=null;
  handlers.keydown({target,key:'Enter',preventDefault(){},stopPropagation(){}});
  assert.equal(selected,12);
});
