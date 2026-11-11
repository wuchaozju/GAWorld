const { test } = require('node:test');
const assert = require('node:assert/strict');
const checks = require('./result-checks.js');

test('old results explicitly show untested, never pass', () => {
  const html = checks.render(null);
  assert.match(html, /未检验/);
  assert.match(html, /历史/);
  assert.doesNotMatch(html, /检查通过/);
});
test('evidence is escaped and the result reference is visible', () => {
  const html = checks.render({ref:'Q1/C2-C1', scope:'scope', checks:[
    {id:'human',label:'真人参照',status:'insufficient',detail:'<img src=x onerror=alert(1)>',
     evidence:{difference:2,ci:[1,3],margin:.2}}
  ]});
  assert.match(html,/Q1\/C2-C1/);
  assert.match(html,/&lt;img/);
  assert.doesNotMatch(html,/<img/);
  assert.match(html,/证据不足/);
  assert.match(html,/容许误差/);
});

test('identity cues and contrast are readable before opening raw records', () => {
  const html = checks.render({ref:'Q1/C1',scope:'scope',checks:[
    {id:'identity',status:'detected',detail:'sensitivity',evidence:{contrast:'B - A',a:'<b>甲</b>',b:'乙',difference:1}}
  ]});
  const visible = html.split('<details><summary>查看记录')[0];
  assert.match(visible,/比较方向: &quot;B - A&quot;/);
  assert.match(visible,/A 线索: &quot;&lt;b&gt;甲&lt;\/b&gt;&quot;/);
  assert.doesNotMatch(visible,/<b>甲/);
});

test('group counts and three contrasts appear outside raw records', () => {
  const html = checks.render({checks:[{id:'interaction',status:'detected',evidence:{complete_groups:4,missing_groups:1,
    contrasts:{peer:{label:'同伴反馈<script>',status:'detected',evidence:{difference:1,ci:[.2,1.8],margin:.3}},
      memory:{label:'自己过往回答',status:'stable',evidence:{difference:0,ci:[-.1,.1]}},
      interaction:{label:'二者共同作用',status:'insufficient',evidence:{difference:0}}}}}]});
  const visible = html.split('<details><summary>查看记录')[0];
  assert.match(visible,/完整小组: 4/);
  assert.match(visible,/缺失小组: 1/);
  assert.match(visible,/同伴反馈&lt;script&gt;/);
  assert.match(visible,/自己过往回答/);
  assert.match(visible,/二者共同作用/);
  assert.doesNotMatch(visible,/<script>/);
});

test('repeated-draw noise and nominal contrasts remain visible and escaped', () => {
  const html = checks.render({checks:[{id:'sampling',status:'observed',evidence:{
    noise:{main:{complete_residents:4,missing:4,mean_within_resident_sd:.125}},
    contrasts:{order:{label:'order',status:'observed',evidence:{option_shifts:{'<label>':.2}}}}}}]});
  const visible = html.split('<details><summary>查看记录')[0];
  assert.match(visible,/居民内标准差均值/);
  assert.match(visible,/0.1250/);
  assert.match(visible,/&lt;label&gt;/);
});
