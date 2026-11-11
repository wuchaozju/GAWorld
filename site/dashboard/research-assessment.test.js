const test = require('node:test');
const assert = require('node:assert/strict');
const renderer = require('./research-assessment.js');

test('pending rubric is explicit and model evidence is escaped', () => {
  const html = renderer.render({status:'pending', score:null, dimensions:[{label:'机制', label_en:'Mechanism', weight:25, band:null, evidence:'<script>x</script>', gap:'missing'}]});
  assert.match(html, /待确认/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.doesNotMatch(html, /null\/100/);
});

test('legacy rating says no shared rubric in English', () => {
  const html = renderer.render({status:'legacy',score:62}, {language:'en'});
  assert.match(html, /Legacy model rating/);
  assert.match(html, /no shared rubric/);
  assert.match(html, /62\/100/);
  assert.doesNotMatch(html, /机制/);
});

test('source coverage shows partial text and source hash without claiming full paper', () => {
  const html = renderer.renderSource({input_chars:90000,used_chars:80000,truncated:true,sha256:'<hash>'}, {language:'en'});
  assert.match(html, /Partial material/);
  assert.match(html, /80000 \/ 90000/);
  assert.match(html, /&lt;hash&gt;/);
});

test('original design displays unknowns and quote checking limits', () => {
  const html = renderer.renderOriginalDesign({sample:{value:'20',status:'reported',manual_edited:true,source:{locator:'page:1',quote:'twenty',verified:true}}, measures:{value:'未说明',status:'unknown',source:{}}});
  assert.match(html, /研究者已修订/);
  assert.match(html, /片段已定位/);
  assert.match(html, /不能证明提炼结论正确/);
  assert.match(html, /未说明/);
});

test('preservation renders status and consequences as text', () => {
  const html = renderer.renderPreservation([{field:'measures',status:'approximated',original:'survey',proposed:'<img>',consequence:'scale differs'}], {language:'en'});
  assert.match(html, /Approximation/);
  assert.match(html, /scale differs/);
  assert.match(html, /&lt;img&gt;/);
});

test('English original design localizes unreported fields', () => {
  const html = renderer.renderOriginalDesign({measures:{value:'未说明',status:'unknown',source:{}}}, {language:'en'});
  assert.match(html, /Not reported/);
  assert.doesNotMatch(html, /未说明/);
});
