const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
test('a stale workbench keeps its expected world when another tab changes the cookie', async () => {
  const calls = [];
  const window = { fetch: async (input, options) => {
    calls.push({ input, options });
    return { ok: true, json: async () => ({ current: { id: 'w12345678' }, mode: 'accounts' }) };
  }};
  vm.runInNewContext(fs.readFileSync('site/community/context.js', 'utf8'), { window, location: { href:'http://localhost/console', origin:'http://localhost' }, URL, Headers });
  await window.fetch('/api/research/analyze', { method:'POST', body:'{}' });
  assert.equal(calls[1].options.headers.get('X-GAWorld-World'), 'w12345678');
  await window.fetch('/api/run/start', { method:'POST' });
  assert.equal(calls[2].options.headers.get('X-GAWorld-World'), 'w12345678');
});
test('failed world initialization refuses a mutation instead of dropping its world guard', async () => {
  const calls = [];
  const window = { fetch: async (input) => { calls.push(input); throw new Error('world endpoint unavailable'); } };
  vm.runInNewContext(fs.readFileSync('site/community/context.js','utf8'), { window, location:{href:'http://localhost/console',origin:'http://localhost'}, URL, Headers });
  await assert.rejects(window.fetch('/api/run/start',{method:'POST'}), /world|世界/);
  assert.deepEqual(calls, ['/api/worlds']);
});
