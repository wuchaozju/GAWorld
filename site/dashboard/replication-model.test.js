const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

const source = fs.readFileSync(__dirname + '/replication.js', 'utf8');

/* The parameter fields and the model block are read off the page, so the
   tests drive the real source with a stub DOM rather than a copy of it. */
function loadScope() {
  const start = source.indexOf('  var GEN_FIELDS');
  const end = source.indexOf('  function fillCities(', start);
  assert.ok(start > 0 && end > start, 'the parameter helpers must be extractable from replication.js');
  const fields = {
    rpGenExtractTemp: { value: '0.1' },
    rpGenExtractMax: { value: '6000' },
    rpGenAnswerTemp: { value: '0.9' },
    rpGenAnswerMax: { value: '2000' },
    rpGenInterpretTemp: { value: '0.3' },
    rpGenInterpretMax: { value: '4000' },
    rpGenError: { textContent: '', classList: { toggle() {} } },
    rpProvider: { value: '' },
    rpModelInfo: { textContent: '' },
  };
  const ctx = {
    state: { providers: [], generation: null },
    t: (key, fallback) => fallback,
    tf: (key, fallback, params) => {
      let text = fallback;
      Object.keys(params || {}).forEach((name) => {
        text = text.split('{' + name + '}').join(String(params[name]));
      });
      return text;
    },
    esc: (text) => String(text == null ? '' : text),
    $: (id) => fields[id] || null,
  };
  vm.createContext(ctx);
  vm.runInContext(source.slice(start, end), ctx);
  ctx.fields = fields;
  return ctx;
}

test('the defaults the server sends fill the fields', () => {
  const ctx = loadScope();
  ctx.fillGeneration({
    extract: { temperature: 0.15, max_tokens: 5000 },
    answer: { temperature: 0.8, max_tokens: 1500 },
    interpret: { temperature: 0.2, max_tokens: 3000 },
  });
  assert.equal(ctx.fields.rpGenAnswerTemp.value, 0.8);
  assert.equal(ctx.fields.rpGenAnswerMax.value, 1500);
  assert.equal(ctx.fields.rpGenInterpretMax.value, 3000);
});

test('the parameters the researcher typed are what is sent', () => {
  const ctx = loadScope();
  ctx.fields.rpGenAnswerTemp.value = '0.42';
  ctx.fields.rpGenAnswerMax.value = '900';
  const payload = ctx.generationPayload();
  assert.equal(payload.answer.temperature, 0.42);
  assert.equal(payload.answer.max_tokens, 900);
  assert.equal(ctx.fields.rpGenError.textContent, '');
});

test('an impossible temperature is refused and said out loud', () => {
  const ctx = loadScope();
  ctx.fields.rpGenAnswerTemp.value = '9';
  assert.equal(ctx.generationPayload(), null);
  assert.ok(ctx.fields.rpGenError.textContent.includes('0–2'), ctx.fields.rpGenError.textContent);
});

test('an impossible token budget is refused too', () => {
  const ctx = loadScope();
  ctx.fields.rpGenExtractMax.value = '5';
  assert.equal(ctx.generationPayload(), null);
  assert.ok(ctx.fields.rpGenError.textContent.includes('32–32000'), ctx.fields.rpGenError.textContent);
});

test('the model the configuration names is shown next to the picker', () => {
  const ctx = loadScope();
  ctx.state.providers = [{ name: 'gpt', model: 'gpt-4o-2024-08-06', type: 'openai' }];
  ctx.fields.rpProvider.value = 'gpt';
  ctx.renderModelInfo();
  assert.ok(ctx.fields.rpModelInfo.textContent.includes('gpt-4o-2024-08-06'), ctx.fields.rpModelInfo.textContent);
});

test('a model the configuration does not version says so', () => {
  const ctx = loadScope();
  ctx.state.providers = [{ name: 'local', model: '', type: 'ollama' }];
  ctx.fields.rpProvider.value = 'local';
  ctx.renderModelInfo();
  assert.ok(ctx.fields.rpModelInfo.textContent.includes('没有写明版本'), ctx.fields.rpModelInfo.textContent);
});

/* The block that tells a reader which model answered and with which
   parameters. It is the answer to "can I trust this number?". */
function loadModelBlock() {
  const start = source.indexOf('  function modelBlock(run)');
  const end = source.indexOf('  function render()', start);
  assert.ok(start > 0 && end > start, 'modelBlock must be extractable from replication.js');
  const ctx = {
    t: (key, fallback) => fallback,
    tf: (key, fallback, params) => {
      let text = fallback;
      Object.keys(params || {}).forEach((name) => {
        text = text.split('{' + name + '}').join(String(params[name]));
      });
      return text;
    },
    esc: (text) => String(text == null ? '' : text),
  };
  vm.createContext(ctx);
  vm.runInContext(source.slice(start, end), ctx);
  return ctx;
}

test('the run says which model answered, with its fingerprints and parameters', () => {
  const ctx = loadModelBlock();
  const html = ctx.modelBlock({
    model: {
      provider: 'gpt',
      model: 'gpt-4o-2024-08-06',
      backend_type: 'OpenAIProvider',
      endpoint_hash: 'abc123',
      config_hash: 'def456',
    },
    generation: {
      extract: { temperature: 0.1, max_tokens: 6000 },
      answer: { temperature: 0.9, max_tokens: 2000 },
    },
  });
  assert.ok(html.includes('gpt-4o-2024-08-06'), html);
  assert.ok(html.includes('abc123'), html);
  assert.ok(html.includes('def456'), html);
  assert.ok(html.includes('温度 0.9'), html);
  assert.ok(html.includes('max tokens 2000'), html);
});

test('a run with no model recorded does not invent one', () => {
  const ctx = loadModelBlock();
  const html = ctx.modelBlock({});
  assert.ok(html.includes('未记录模型名'), html);
  assert.ok(!html.includes('undefined'), html);
});

test('the block also names the model that read the paper', () => {
  const ctx = loadModelBlock();
  const html = ctx.modelBlock({
    model: { provider: 'gpt', model: 'gpt-4o' },
    extraction_model: { provider: 'mini', model: 'gpt-4o-mini' },
  });
  assert.ok(html.includes('gpt-4o-mini'), html);
  assert.ok(html.includes('读文献的模型'), html);
});

test('a run with no extraction model does not invent one', () => {
  const ctx = loadModelBlock();
  const html = ctx.modelBlock({ model: { provider: 'gpt', model: 'gpt-4o' } });
  assert.ok(!html.includes('读文献的模型'), html);
});
