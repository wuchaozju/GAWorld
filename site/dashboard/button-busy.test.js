/**
 * The shared button busy-state helper (`_button-busy.js`).
 *
 * Every "运行仿真 / 重置并运行 / 保存配置 …" button in the dashboard is wrapped
 * in this helper, so a defect here shows up all over the console: a button that
 * keeps its busy copy ("启动中…") after the work is long finished.
 *
 * The regression this file pins: a busy cycle *deletes* the snapshot of the
 * resting label when it releases. If the next busy cycle does not take a fresh
 * snapshot, the second use of a button can never restore its label and the
 * button stays stuck on the busy copy for good.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const SOURCE = fs.readFileSync(path.join(__dirname, '_button-busy.js'), 'utf8');

const ZH = {
  'btn.run_simulation': '运行仿真',
  'btn.starting': '启动中…',
  'btn.stop': '停止',
};

function makeButton(label, i18nKey) {
  const btn = {
    dataset: {},
    textContent: label,
    disabled: false,
    attributes: {},
    classes: new Set(),
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
    },
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
    classList: {
      add(name) { btn.classes.add(name); },
      remove(name) { btn.classes.delete(name); },
    },
  };
  if (i18nKey) btn.setAttribute('data-i18n', i18nKey);
  return btn;
}

function loadHelper(translations) {
  const sandbox = {
    window: {
      __(key, fallback) {
        if (Object.prototype.hasOwnProperty.call(translations, key)) return translations[key];
        if (fallback !== undefined) return fallback;
        return key;
      },
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(SOURCE, sandbox);
  return sandbox.window;
}

test('a busy cycle shows the busy copy and restores the resting label', () => {
  const { setButtonBusy } = loadHelper(ZH);
  const btn = makeButton('运行仿真', 'btn.run_simulation');
  const release = setButtonBusy(btn, 'btn.starting', '启动中…');
  assert.equal(btn.textContent, '启动中…');
  assert.equal(btn.disabled, true);
  release();
  assert.equal(btn.textContent, '运行仿真');
  assert.equal(btn.disabled, false);
});

test('a second busy cycle restores the label too (regression)', () => {
  const { setButtonBusy } = loadHelper(ZH);
  const btn = makeButton('运行仿真', 'btn.run_simulation');

  setButtonBusy(btn, 'btn.starting', '启动中…')();
  assert.equal(btn.textContent, '运行仿真', 'first cycle restores the label');

  const release = setButtonBusy(btn, 'btn.starting', '启动中…');
  assert.equal(btn.textContent, '启动中…');
  release();
  assert.equal(btn.textContent, '运行仿真', 'the second cycle must restore the label as well');
  assert.equal(btn.disabled, false);
});

test('a button without an i18n key restores its plain text', () => {
  const { setButtonBusy } = loadHelper(ZH);
  const btn = makeButton('保存配置', null);
  setButtonBusy(btn, 'btn.starting', '启动中…')();
  assert.equal(btn.textContent, '保存配置');
  setButtonBusy(btn, 'btn.starting', '启动中…')();
  assert.equal(btn.textContent, '保存配置');
});

test('nested busy calls restore the label exactly once', () => {
  const { setButtonBusy } = loadHelper(ZH);
  const btn = makeButton('运行仿真', 'btn.run_simulation');
  const outer = setButtonBusy(btn, 'btn.starting', '启动中…');
  const inner = setButtonBusy(btn, 'btn.starting', '启动中…');
  inner();
  assert.equal(btn.textContent, '启动中…', 'the outer caller is still busy');
  outer();
  assert.equal(btn.textContent, '运行仿真');
});

test('the resting disabled state survives a busy cycle', () => {
  const { setButtonBusy } = loadHelper(ZH);
  const btn = makeButton('运行仿真', 'btn.run_simulation');
  btn.disabled = true;
  setButtonBusy(btn, 'btn.starting', '启动中…')();
  assert.equal(btn.disabled, true, 'a button that started disabled stays disabled');
  assert.equal(btn.textContent, '运行仿真');
});
