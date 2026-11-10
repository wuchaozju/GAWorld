const {test} = require('node:test');
const assert = require('node:assert/strict');

test('mode checks show unsupported measurements and reviewed budget candidates', () => {
  const view = require('./research-admission.js');
  const html = view.renderChecks({budget:{http_budget:60000, maximum:100000}, modes:{
    tick:{compatible:true,estimated_calls:80000},
    daily_brief:{compatible:false,estimated_calls:250,errors:['social_need <missing>']}
  },candidates:[{estimated_calls:45000,note:'fewer seeds'}]}, {language:'en',editable:true});
  assert.match(html, /social_need &lt;missing&gt;/);
  assert.match(html, /HTTP/);
  assert.match(html, /data-budget-candidate="0"/);
  assert.match(html, /review/i);
});

test('fault cards escape context and provide a recovery action', () => {
  const view = require('./research-admission.js');
  const html = view.renderDiagnostic({code:'budget_exhausted',stage:'simulation',
    message:'<unsafe>', next_action:'review budget',provider:'<img onerror=x>',attempts:2}, {language:'en'});
  assert.doesNotMatch(html, /<unsafe>|<img/);
  assert.match(html, /&lt;img onerror=x&gt;/);
  assert.match(html, /budget_exhausted/);
  assert.match(html, /review/i);
});
