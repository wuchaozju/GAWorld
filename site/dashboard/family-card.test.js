/* Headless render check for the 家庭结构 card.
 *
 *   node --test site/dashboard/family-card.test.js
 *
 * Same convention as collaboration-core.test.js / population.test.js: plain
 * node, no framework, no browser.
 *
 * The card lives inside app.js rather than on its own page, and app.js touches
 * a hundred DOM ids at load time, so booting the whole module headlessly is not
 * worth it. Instead this slices out the card's own block and evaluates it
 * against stubbed `els` / `state` / helpers. That is enough to catch the class
 * of bug the Python tests structurally cannot see: a crash inside a renderer,
 * or a name reaching innerHTML unescaped. If the slice markers ever move, this
 * fails loudly, which is the correct outcome.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const APP = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
const LOCALE = require("./locales/zh-CN.json");
const missingKeys = [];

const START = "const HOUSEHOLD_TYPES = [";
const END_FN = "function renderFamilyDetail()";

function familyBlock() {
  const start = APP.indexOf(START);
  assert.notEqual(start, -1, "family card block not found in app.js");
  const endStart = APP.indexOf(END_FN);
  assert.notEqual(endStart, -1, "renderFamilyDetail not found in app.js");
  const end = APP.indexOf("\n}", endStart);
  assert.notEqual(end, -1);
  return APP.slice(start, end + 2);
}

function makeEl() {
  return { innerHTML: "" };
}

/* Evaluate the card block with the handful of app.js helpers it leans on. */
function boot(family, selectedAgentId) {
  const els = { familyOverview: makeEl(), familyDetail: makeEl() };
  const state = { family, selectedAgentId };
  const escapeHtml = (value) =>
    String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  /* The card draws every string through __()/__f() now, so supply the real
     zh-CN locale rather than a stub that echoes keys. The Chinese assertions
     below keep their meaning, and a typo'd key shows up in missingKeys. */
  const __ = (key) => {
    if (!Object.prototype.hasOwnProperty.call(LOCALE, key)) {
      missingKeys.push(key);
      return key;
    }
    return LOCALE[key];
  };
  const __f = (key, params) => {
    let text = __(key);
    for (const [name, value] of Object.entries(params || {})) {
      text = text.split(`{${name}}`).join(String(value));
    }
    return text;
  };
  const api = async () => ({});
  const factory = new Function(
    "els",
    "state",
    "escapeHtml",
    "__",
    "__f",
    "api",
    `${familyBlock()}\n return { renderFamilyCard, renderFamilyOverview, renderFamilyDetail };`
  );
  return { els, api: factory(els, state, escapeHtml, __, __f, api) };
}

const PAYLOAD = {
  available: true,
  summary: {
    agents: 3,
    households: 2,
    in_sim_couples: 1,
    with_children: 2,
    household_types: { nuclear: 1, single: 1 },
    marital_statuses: { married: 2, never: 1 },
  },
  households: [{ id: "hh_001", type: "nuclear", agent_ids: [1, 2] }],
  agents: [
    {
      agent_id: 1,
      name: "蒋昊",
      household_id: "hh_001",
      household_type: "nuclear",
      marital_status: "married",
      brief: "已婚；核心家庭。配偶叶嘉宁（34岁，同住）",
      care_load: 0.21,
      members: [
        { key: "2", name: "叶嘉宁", role: "spouse", kind: "agent", age: 34, coresident: true },
        { key: "g_child_1", name: "蒋荷", role: "child", kind: "ghost", age: 2, coresident: true },
        { key: "g_father", name: "蒋晨轩", role: "father", kind: "ghost", age: 63, coresident: false },
      ],
    },
  ],
  finance: { hh_001: { dependant_cost: 123.45, partner_transfer: 10, days: 7 } },
};

test("an empty payload renders an empty card rather than throwing", () => {
  const { els, api } = boot({ available: false }, 1);
  api.renderFamilyCard();
  assert.equal(els.familyOverview.innerHTML, "");
  assert.equal(els.familyDetail.innerHTML, "");
});

test("a null payload is survivable (first paint, before the fetch lands)", () => {
  const { els, api } = boot(null, null);
  api.renderFamilyCard();
  assert.equal(els.familyDetail.innerHTML, "");
});

test("the overview renders stats, a mix bar and a legend", () => {
  const { els, api } = boot(PAYLOAD, 1);
  api.renderFamilyCard();
  const html = els.familyOverview.innerHTML;
  assert.match(html, /family-stat-value/);
  assert.match(html, /family-bar-seg/);
  assert.match(html, /核心家庭/);
  // Single count is shown against the population, not as a bare number:
  // "1" alone reads as "one household" rather than "one of three people".
  assert.match(html, /1\/3/);
});

test("the detail renders the selected resident's household", () => {
  const { els, api } = boot(PAYLOAD, 1);
  api.renderFamilyCard();
  const html = els.familyDetail.innerHTML;
  assert.match(html, /蒋昊/);
  assert.match(html, /叶嘉宁/);
  assert.match(html, /配偶/);
  assert.match(html, /也在本次仿真中/);
  assert.match(html, /住在一起/);
  assert.match(html, /不同住的家人/);
  assert.match(html, /¥123\.45/);
});

test("a resident with no record gets a note, not a blank card", () => {
  const { els, api } = boot(PAYLOAD, 99);
  api.renderFamilyCard();
  assert.match(els.familyDetail.innerHTML, /没有参与上一轮运行/);
});

test("names are escaped — profiles are operator-editable text", () => {
  const hostile = JSON.parse(JSON.stringify(PAYLOAD));
  hostile.agents[0].name = '<img src=x onerror="alert(1)">';
  hostile.agents[0].members[0].name = "<script>bad()</script>";
  hostile.agents[0].brief = "<b>不该加粗</b>";
  const { els, api } = boot(hostile, 1);
  api.renderFamilyCard();
  const html = els.familyDetail.innerHTML;
  assert.ok(!html.includes("<img src=x"), "resident name was not escaped");
  assert.ok(!html.includes("<script>"), "member name was not escaped");
  assert.ok(!html.includes("<b>不该加粗"), "brief was not escaped");
  assert.match(html, /&lt;script&gt;/);
});

test("every locale key the family card asks for exists", () => {
  // Collected by the __ stub as the tests above render every branch of the card.
  assert.deepEqual(missingKeys, []);
});
