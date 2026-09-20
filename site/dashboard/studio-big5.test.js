/* The Studio's Big Five card, rendered headlessly.
 *
 *   node site/dashboard/studio-big5.test.js
 *
 * Same slicing technique as studio-family.test.js: studio.js touches too much
 * DOM at load to boot, so the card's own block is evaluated against stubs.
 *
 * Two things are worth a test here:
 *
 * 1. **The consistency flags.** They only appear once an operator has dragged
 *    a score away from the one the paragraph was written from, so a seeded
 *    roster shows none of them and a browser check cannot reach the branch at
 *    all. Every flag shape the server can emit is exercised here instead.
 * 2. **The bilingual payload.** The trait names and pole descriptions come
 *    from the server in both languages (BIG5_POLES_EN in dashboard_server.py)
 *    rather than from the locale, because the wording is shared with
 *    scripts/calibrate_big5.py. A client that reads the wrong field shows a
 *    Chinese slider in English mode and nothing else fails.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const STUDIO = fs.readFileSync(path.join(__dirname, "studio.js"), "utf8");
const ZH = require(path.join(__dirname, "locales", "zh-CN.json"));
const EN = require(path.join(__dirname, "locales", "en.json"));

const START = "const BIG5_DIMS = ";
const END = "function markBig5Dirty()";

const missingKeys = new Set();

function block() {
  const start = STUDIO.indexOf(START);
  assert.notEqual(start, -1, "Big Five block not found in studio.js");
  const end = STUDIO.indexOf(END);
  assert.notEqual(end, -1, "markBig5Dirty not found in studio.js");
  assert.ok(end > start, "unexpected ordering in studio.js");
  return STUDIO.slice(start, end);
}

function boot(locale, data, extra) {
  const table = locale === "en" ? EN : ZH;
  const lookup = (key) => {
    if (!(key in table)) { missingKeys.add(locale + " " + key); return key; }
    return table[key];
  };
  const format = (key, params) =>
    String(lookup(key)).replace(/\{(\w+)\}/g, (whole, name) =>
      (params && name in params ? String(params[name]) : whole));
  const esc = (text) =>
    String(text == null ? "" : text).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const store = Object.assign(
    { creating: false, currentId: 7, big5: data, big5Draft: null, big5Dirty: false },
    extra || {}
  );
  const factory = new Function(
    "store", "esc", "__", "__f", "getLocale", "$", "api", "renderStep", "foot",
    `${block()}\n return { big5Card, big5FlagInfo };`
  );
  return factory(
    store, esc, lookup, format, () => locale,
    () => null, async () => ({}), () => {}, () => {}
  );
}

const PAYLOAD = {
  id: 7,
  values: { o: 0.4, c: -0.8, e: 0.1, a: 0.0, n: 1.2 },
  authored: { o: 0.4, c: 0.9, e: 0.1, a: 0.0, n: 1.2 },
  source: "sampled_authored",
  paragraph: "她做事有条理，计划排得细。",
  consistency: {},
  poles: {
    o: ["只走熟悉的路线", "主动找新鲜事物"],
    c: ["计划容易落空", "提前排好顺序"],
    e: ["回避热闹场合", "主动搭话"],
    a: ["说话直接", "先替别人考虑"],
    n: ["情绪很稳", "容易往坏处想"],
  },
  poles_en: {
    o: ["sticks to familiar routes", "seeks out what is new"],
    c: ["plans slip", "orders things in advance"],
    e: ["avoids crowded occasions", "starts conversations"],
    a: ["speaks directly", "thinks of others first"],
    n: ["steady", "assumes the worst"],
  },
  names: { o: "开放性", c: "尽责性", e: "外向性", a: "宜人性", n: "神经质" },
  names_en: { o: "Openness", c: "Conscientiousness", e: "Extraversion", a: "Agreeableness", n: "Neuroticism" },
  floor: 0.5,
  clip: 2.5,
};

function withFlag(state, severity) {
  const data = JSON.parse(JSON.stringify(PAYLOAD));
  data.consistency = { c: severity ? { state, severity } : { state } };
  return data;
}

test("the bilingual tables are picked by locale, not merged", () => {
  const zh = boot("zh-CN", PAYLOAD).big5Card();
  assert.match(zh, /开放性/);
  assert.match(zh, /只走熟悉的路线/);
  assert.ok(!zh.includes("Openness</span>"), "Chinese mode showed the English name");

  const en = boot("en", PAYLOAD).big5Card();
  assert.match(en, /Openness/);
  assert.match(en, /sticks to familiar routes/);
  assert.ok(!en.includes("开放性"), "English mode showed the Chinese name");
});

test("a payload without the English twin falls back rather than blanking", () => {
  const trimmed = JSON.parse(JSON.stringify(PAYLOAD));
  delete trimmed.names_en;
  delete trimmed.poles_en;
  // An older server is still readable: better the Chinese label than an empty
  // slider with no idea which trait it is.
  const en = boot("en", trimmed).big5Card();
  assert.match(en, /开放性/);
  assert.match(en, /只走熟悉的路线/);
});

test("every flag the server can emit renders a label and a hint", () => {
  const cases = [
    ["rewrite", "flip", "bad"],
    ["rewrite", "drift", "warn"],
    ["now_missing", null, "warn"],
    ["now_moot", null, "warn"],
    ["unknown", null, ""],
  ];
  for (const [state, severity, cls] of cases) {
    for (const locale of ["zh-CN", "en"]) {
      const mod = boot(locale, withFlag(state, severity));
      const info = mod.big5FlagInfo(severity ? { state, severity } : { state });
      assert.ok(info, `${state}/${severity} produced no flag info`);
      assert.equal(info.cls, cls, `${state}/${severity} wrong class`);
      assert.ok(info.label && !info.label.startsWith("sd."), `${state} label is a bare key`);
      assert.ok(info.hint && !info.hint.startsWith("sd."), `${state} hint is a bare key`);
      const html = mod.big5Card();
      assert.ok(html.includes(info.label), `${state} label missing from the card`);
      assert.match(html, /b5-banner/, `${state} did not raise the banner`);
    }
  }
});

test("an ok or unrecognised flag stays silent", () => {
  const mod = boot("zh-CN", PAYLOAD);
  assert.equal(mod.big5FlagInfo(null), null);
  assert.equal(mod.big5FlagInfo({ state: "ok" }), null);
  // A state this build has never met must not render a missing-key name.
  assert.equal(mod.big5FlagInfo({ state: "invented_later" }), null);
  assert.ok(!mod.big5Card().includes("b5-banner"), "a clean agent raised a banner");
});

test("an unknown severity degrades to drift instead of throwing", () => {
  const mod = boot("zh-CN", withFlag("rewrite", "sideways"));
  const info = mod.big5FlagInfo({ state: "rewrite", severity: "sideways" });
  assert.ok(info, "an unrecognised severity produced nothing");
  assert.equal(info.cls, "warn");
});

test("the card degrades instead of throwing", () => {
  for (const locale of ["zh-CN", "en"]) {
    assert.match(boot(locale, null).big5Card(), /section-note/);
    assert.match(boot(locale, { error: "boom" }).big5Card(), /boom/);
    // A brand-new resident has no score row yet, so the card must say so
    // rather than render five sliders over nothing.
    const creating = boot(locale, PAYLOAD, { creating: true });
    const html = creating.big5Card();
    assert.match(html, /section-note/);
    assert.ok(!html.includes("b5-row"), "an unsaved resident got sliders");
  }
});

test("server text is escaped on its way to innerHTML", () => {
  const hostile = JSON.parse(JSON.stringify(PAYLOAD));
  hostile.paragraph = "<img src=x onerror=alert(1)>";
  hostile.names.o = "<script>bad()</script>";
  hostile.source = '"><b>x';
  const html = boot("zh-CN", hostile).big5Card();
  assert.ok(!html.includes("<img src=x"), "paragraph was not escaped");
  assert.ok(!html.includes("<script>bad()"), "trait name was not escaped");
  assert.match(html, /&lt;img src=x/);
});

test("every locale key the card asks for exists in both languages", () => {
  assert.deepEqual([...missingKeys].sort(), [], "missing locale keys");
});
