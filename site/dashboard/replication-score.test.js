const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

const source = fs.readFileSync(__dirname + '/replication.js', 'utf8');

function loadScope() {
  const start = source.indexOf('  function scoreNote(s)');
  const end = source.indexOf('  function dist(distribution)', start);
  assert.ok(start > 0 && end > start, 'scoreNote must be extractable from replication.js');
  const ctx = { t: (key, fallback) => fallback, tf: (key, fallback, params) => {
    let text = fallback;
    Object.keys(params || {}).forEach((name) => {
      text = text.split('{' + name + '}').join(String(params[name]));
    });
    return text;
  }, esc: (text) => String(text == null ? '' : text) };
  vm.createContext(ctx);
  vm.runInContext(source.slice(start, end), ctx);
  return ctx;
}

function weightsOf(note) {
  const parts = note.split('本次权重：');
  return parts.length > 1 ? parts[1] : '';
}

test('the note lists the weights the run was actually scored with', () => {
  const ctx = loadScope();
  const note = ctx.scoreNote({
    score_version: 2,
    score_weights: { level: 0.35, spread: 0.3, direction: 0.35 },
  });
  const weights = weightsOf(note);
  assert.ok(weights.includes('35% 水平准确度'), note);
  assert.ok(weights.includes('30% 离散度准确度'), note);
  assert.ok(weights.includes('35% 效应方向一致率'), note);
});

test('a run whose dispersion could not be judged says so instead of inventing a weight', () => {
  const ctx = loadScope();
  const note = ctx.scoreNote({ score_version: 2, score_weights: { level: 0.5, direction: 0.5 } });
  const weights = weightsOf(note);
  assert.ok(!weights.includes('离散度'), note);
  assert.ok(weights.includes('50% 水平准确度'), note);
  assert.ok(weights.includes('50% 效应方向一致率'), note);
});

test('a record scored under the old formula is flagged, not silently mixed in', () => {
  const ctx = loadScope();
  const note = ctx.scoreNote({ score_version: 1, score_weights: { level: 0.5, direction: 0.5 } });
  assert.ok(note.includes('旧公式'), note);
  assert.ok(note.includes('没有计入离散度'), note);
  assert.ok(!note.includes('本次权重'), note);
});

test('a collapsed interval charged to the score is said out loud', () => {
  const ctx = loadScope();
  const note = ctx.scoreNote({
    score_version: 3,
    score_weights: { level: 1 },
    degenerate_ci_cells: 2,
  });
  assert.ok(note.includes('退化'), note);
  assert.ok(note.includes('2'), note);
});

test('a run without a collapsed interval does not mention one', () => {
  const ctx = loadScope();
  const note = ctx.scoreNote({ score_version: 3, score_weights: { level: 1 } });
  assert.ok(!note.includes('退化'), note);
});

test('a record scored before the collapse was charged keeps its own note', () => {
  const ctx = loadScope();
  const note = ctx.scoreNote({
    score_version: 2,
    score_weights: { level: 1 },
    degenerate_ci_cells: 2,
  });
  assert.ok(!note.includes('退化'), note);
});

test('a 0% hit rate caused by collapsed intervals is explained', () => {
  const ctx = loadScope();
  const note = ctx.withinNote({ collapsed_ci_cells: 4, degenerate_ci_cells: 4 });
  assert.ok(note.includes('4'), note);
  assert.ok(note.includes('退化'), note);
});

test('a healthy run carries no note about collapsed intervals', () => {
  const ctx = loadScope();
  assert.equal(ctx.withinNote({ collapsed_ci_cells: 0 }), '');
  assert.equal(ctx.withinNote({}), '');
});

test('a run whose provider takes no seed says the answers cannot be reproduced', () => {
  const ctx = loadScope();
  const note = ctx.seedScopeNote({ seed_scope: { provider_supports_seed: false } });
  assert.ok(note.includes('不接受 seed'), note);
  assert.ok(note.includes('无法复现'), note);
});

test('a run whose provider takes a seed says what was asked for', () => {
  const ctx = loadScope();
  const note = ctx.seedScopeNote({ seed_scope: { provider_supports_seed: true } });
  assert.ok(note.includes('接受 seed'), note);
  assert.ok(note.includes('不承诺逐字复现'), note);
});

test('a run with no recorded scope says so rather than staying silent', () => {
  const ctx = loadScope();
  assert.equal(ctx.seedScopeNote({}), '');
});
