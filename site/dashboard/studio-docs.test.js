/* The two long-form documents in the Studio's step 1 (身份): 生成自传 and
 * 人生预测, rendered headlessly.
 *
 *   node site/dashboard/studio-docs.test.js
 *
 * Same slicing technique as studio-big5.test.js: studio.js touches too much
 * DOM at load to boot, so each card's own block is evaluated against stubs.
 *
 * Three things are worth a test here:
 *
 * 1. **Where the cards live.** The autobiography moved out of step 7
 *    (复核·部署) into step 1, next to the prediction. A card that drifts
 *    back is invisible in a browser check — the user just finds it in the
 *    wrong tab.
 * 2. **The three operator inputs.** 人生大致走向 is a text box, 人生随机性
 *    and 时代动荡性 are 0–100 sliders; a re-render must not eat a half-typed
 *    direction or reset the knobs.
 * 3. **The bilingual keys.** A key that exists in one locale only shows the
 *    raw key to half the users, and a key that carries a placeholder must
 *    never be rendered through __() — the placeholder would stay in the
 *    text.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const STUDIO = fs.readFileSync(path.join(__dirname, "studio.js"), "utf8");
const ZH = require(path.join(__dirname, "locales", "zh-CN.json"));
const EN = require(path.join(__dirname, "locales", "en.json"));

const DOCS_START = "/* ---------- long-form documents";
const DOCS_END = "function profileCard() {";
const REVIEW_START = "function stepReview() {";
const REVIEW_END = "function agentCardBlock(";

function slice(start, end) {
  const from = STUDIO.indexOf(start);
  assert.notEqual(from, -1, `${start} not found in studio.js`);
  const to = STUDIO.indexOf(end);
  assert.notEqual(to, -1, `${end} not found in studio.js`);
  assert.ok(to > from, `unexpected ordering in studio.js: ${start}`);
  return STUDIO.slice(from, to);
}

const missingKeys = new Set();

function makeLookup(table, locale) {
  return (key) => {
    if (!(key in table)) { missingKeys.add(locale + " " + key); return key; }
    return table[key];
  };
}

function makeFormat(table, locale) {
  const lookup = makeLookup(table, locale);
  return (key, params) =>
    String(lookup(key)).replace(/\{(\w+)\}/g, (whole, name) =>
      (params && name in params ? String(params[name]) : whole));
}

const esc = (text) =>
  String(text == null ? "" : text).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/** Boot the two cards plus step 1 against stubs. */
function bootDocs(locale, extraStore) {
  const table = locale === "en" ? EN : ZH;
  const store = Object.assign(
    {
      creating: false,
      currentId: 7,
      autobioCache: null,
      predictCache: null,
      predictDraft: { direction: "", randomness: 50, turbulence: 50 },
      draft: {
        identity: { id: 7, name: "测试居民", gender: "女", age: 32, hukou: "杭州", residence: "杭州" },
        state: { emotion: 0.5, stress: 0.5 },
        narrative: { personality: "", job: "" },
        profile_text: "",
      },
      detail: null,
      educationSchema: {education_levels:["高中/中专", "本科"], student_statuses:["未知", "非在读", "本科", "硕士"]},
      studentSample: {count:30, seed:42, student_status:"本科"},
    },
    extraStore || {}
  );
  const factory = new Function(
    "store", "esc", "__", "__f", "renderMarkdown", "field", "radarSVG", "profileCard", "GAWorldResidentFilters",
    `${slice("function educationSelect", "function bindStudentSamples")}
     ${slice(DOCS_START, DOCS_END)}
     return { stepIdentity, autobiographyCard, lifePredictionCard, predictSlider };`
  );
  return factory(
    store, esc, makeLookup(table, locale), makeFormat(table, locale),
    (md) => "<md>" + String(md || "") + "</md>",
    (label, html) => `<label>${label}${html}</label>`,
    () => "<svg/>",
    () => "<profile/>",
    require("./resident-filters.js")
  );
}

/** Boot step 7 (复核·部署) on its own, to prove the documents left it. */
function bootReview(locale) {
  const table = locale === "en" ? EN : ZH;
  const store = {
    creating: false,
    currentId: 7,
    detail: null,
    draft: {
      identity: { id: 7, name: "测试居民", gender: "女", age: 32, hukou: "杭州", residence: "杭州" },
      state: { emotion: 0.5, stress: 0.5 },
    },
  };
  const factory = new Function(
    "store", "esc", "__", "STATE_VARS", "varLabel", "financeCard", "agentCardBlock", "moltbookCard",
    `${slice(REVIEW_START, REVIEW_END)}
     return { stepReview };`
  );
  return factory(
    store, esc, makeLookup(table, locale),
    [{ key: "emotion" }],
    (v) => v.key,
    () => "<finance/>",
    () => "",
    () => ""
  );
}

test("both documents are rendered in step 1 (身份)", () => {
  for (const locale of ["zh-CN", "en"]) {
    const mod = bootDocs(locale);
    const html = mod.stepIdentity();
    assert.match(html, /id="autobioBtn"/, `${locale}: no autobiography button in step 1`);
    assert.match(html, /id="predictBtn"/, `${locale}: no prediction button in step 1`);
  }
});

test("step 7 (复核·部署) no longer carries the autobiography", () => {
  for (const locale of ["zh-CN", "en"]) {
    const html = bootReview(locale).stepReview();
    assert.ok(!html.includes("autobioBtn"), `${locale}: the autobiography is still in step 7`);
    assert.ok(!html.includes("autobioOut"), `${locale}: the autobiography output is still in step 7`);
  }
});

test("the prediction card offers the three operator inputs", () => {
  const html = bootDocs("zh-CN").lifePredictionCard();
  assert.match(html, /id="predictDirection"/, "no 人生大致走向 text box");
  assert.match(html, /data-predict-scale="randomness"/, "no 人生随机性 slider");
  assert.match(html, /data-predict-scale="turbulence"/, "no 时代动荡性 slider");
  // Both knobs are 0–100, and both say what their ends mean.
  const sliders = html.match(/type="range"[^>]*>/g) || [];
  assert.equal(sliders.length, 2);
  for (const slider of sliders) {
    assert.match(slider, /min="0"/);
    assert.match(slider, /max="100"/);
  }
  assert.match(html, /class="poles"/, "the knobs have no pole description");
});

test("the draft survives a re-render", () => {
  /* The panel re-renders on every keystroke elsewhere (the sliders, the
   * arriving document), so a half-typed direction that only lives in the
   * DOM would be lost. */
  const mod = bootDocs("zh-CN", {
    predictDraft: { direction: "去南方做制造业管理", randomness: 85, turbulence: 20 },
  });
  const html = mod.lifePredictionCard();
  assert.match(html, /去南方做制造业管理/, "the typed direction was dropped");
  assert.match(html, /value="85"[^>]*data-predict-scale="randomness"/);
  assert.match(html, /value="20"[^>]*data-predict-scale="turbulence"/);
});

test("a saved document flips the button to Regenerate", () => {
  const mod = bootDocs("zh-CN", {
    autobioCache: { markdown: "# 自传\n\n正文", length_cjk: 1200 },
    predictCache: { markdown: "# 人生预测\n\n正文", length_cjk: 1800 },
  });
  assert.match(mod.autobiographyCard(), /重新生成/);
  assert.match(mod.lifePredictionCard(), /重新生成/);
  // The saved body is rendered, not just a link to it.
  assert.match(mod.lifePredictionCard(), /人生预测/);
});

test("both locales carry every key the two cards use", () => {
  bootDocs("zh-CN");
  bootDocs("en");
  assert.deepEqual([...missingKeys], [], "the cards ask for keys a locale does not have");
});

test("a key with a placeholder is never rendered through __()", () => {
  /* __() returns the raw string, so a {length} in the text would reach the
   * screen. Such keys have to go through __f() with the parameter. */
  const used = new Set();
  for (const match of STUDIO.matchAll(/__f?\(\s*"(sd\.(?:autobio|predict)_[a-z_]+)"/g)) {
    used.add(match[1]);
  }
  assert.ok(used.size > 0, "the cards use no locale keys at all?");

  for (const key of used) {
    for (const [locale, table] of [["zh-CN", ZH], ["en", EN]]) {
      assert.ok(key in table, `${locale} has no ${key}`);
      const value = String(table[key]);
      const placeholders = [...value.matchAll(/\{(\w+)\}/g)].map((m) => m[1]);
      if (!placeholders.length) continue;
      const plain = new RegExp(`__\\(\\s*"${key}"`);
      assert.ok(!plain.test(STUDIO), `${key} carries ${placeholders.join(", ")} but is rendered through __()`);
    }
  }
});
