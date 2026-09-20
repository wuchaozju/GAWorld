/* Headless render smoke test for the External Systems panel.
 *
 *   node site/dashboard/external.test.js
 *
 * Same convention as population.test.js: plain node, no test framework, no
 * browser. It stubs just enough DOM and fetch to boot the panel and asserts
 * the first render produced real content.
 *
 * Worth having because the Python tests cover the endpoints but cannot see the
 * panel: a typo'd element id, a crash in a renderer, or a config tree that
 * emits no inputs would leave every backend test green and the page blank.
 */
"use strict";

var path = require("path");

var HERE = __dirname;

/* Trimmed copy of the real `/api/external-systems/overview` shape. Regenerate
 * the full thing with:
 *   python -c "import json; from gaworld.apps import external_systems_api as a; \
 *     print(json.dumps(a.overview(), ensure_ascii=False))"
 * Note `"Infinity"` in the tax brackets — the wire form the backend sends so
 * the response survives JSON.parse. */
var OVERVIEW = {
  generated_at: "2026-08-01 08:00:00",
  /* Field labels arrive from the server now (overview().labels), resolved
     through gaworld.settings.config_docs and carrying both languages — this
     file used to keep its own 195-entry copy. The fixture mirrors that
     contract, so the assertion below still tests a real rendered label. */
  labels: {
    economy: { zh: "经济 / 货币系统", en: "Economy / money system" },
    monthly_exemption: { zh: "月起征点", en: "Monthly exemption" },
    tax: { zh: "个人所得税", en: "Income tax" },
    macro: { zh: "宏观周期", en: "Macro cycle" },
    initial_inflation_rate: { zh: "初始通胀率", en: "Initial inflation rate" },
    brackets: { zh: "税率表 [上限, 税率, 速算扣除]", en: "Bracket table [cap, rate, quick deduction]" },
  },
  currency: {
    config: {
      economy: {
        enabled: true,
        currency: "CNY",
        work_days_per_month: 22,
        tax: { monthly_exemption: 5000.0, brackets: [[3000, 0.03, 0], ["Infinity", 0.45, 15160]] },
        // `unemployment_rate` here is a contribution rate; the macro subtree's
        // similarly-named field is a business-cycle indicator. The help lookup
        // must key off the full path or it describes one as the other.
        social_insurance: { pension_rate: 0.08, unemployment_rate: 0.005 },
        macro: { initial_inflation_rate: 0.025, initial_unemployment_rate: 0.052 },
        sectors: { initial_firms_balance: 0.0 },
      },
    },
    runtime: {
      macro: { phase: "expansion", inflation_rate: 0.025, unemployment_rate: 0.052, cumulative_inflation: 1.002 },
      sectors: { firms: 1342.24, government: 468.51, bank: 234.95 },
      money_stock: { initial_system_total: 181229.05, final_system_total: 181229.05, intervention_injected_total: 0.0 },
      conservation: {
        rows: [
          { day: 1, system_total: 181229.05, drift: 0.0 },
          { day: 2, system_total: 181229.05, drift: 0.0 },
          { day: 3, system_total: 181229.05, drift: 0.0 },
        ],
        latest: { day: 3, system_total: 181229.05, drift: 0.0 },
        max_abs_drift: 0.0,
        ok: true,
      },
      wealth: {
        agents: 3, currency: "CNY", total_balance: 96879.2, total_debt: 0.0,
        total_housing_fund: 146890.28, mean_balance: 32293.07, median_balance: 32293.07,
        min_balance: 100.0, max_balance: 60000.0, gini: 0.3142, indebted_agents: 0,
      },
      ledger: [
        { day: 1, income: 100, expense: 56, balance: 1000, net: 44 },
        { day: 2, income: 120, expense: 60, balance: 1060, net: 60 },
        { day: 3, income: 90, expense: 70, balance: 1080, net: 20 },
      ],
      output_dir: "output/economy",
      interventions: {
        pending: [{ id: "iv-abc123", day: null, note: "财政刺激", macro: { phase: "contraction" }, sector_delta: { government: 50000 } }],
        applied: [{ id: "iv-old999", applied_day: 2, note: "", applied_macro: { inflation_rate: 0.09 }, applied_sector_delta: {} }],
        path: "output/economy/interventions.json",
      },
    },
  },
  environment: {
    config: {
      external_environment: {
        enabled: true, seed: 42, max_events_per_tick: 3,
        natural: { daily_weather_chance: 0.95, extreme_events: ["短时强降雨预警"] },
      },
      policy_events: [{ day: 2, time: "10:00", name: "平台用工保护", description: "提高社保覆盖" }],
    },
    runtime: {
      available: true,
      latest_day: 49,
      day_count: 9,
      tick_records: 0,
      mean_severity: 0.524,
      event_type_counts: { natural: 9, economic: 9 },
      timeline_path: "output/environment/timeline.jsonl",
      days: [
        {
          day: 49, date: "2026-09-15", summary: "阴雨减弱但仍多云。",
          events: [
            { type: "natural", name: "雨势减弱", description: "<img src=x onerror=alert(1)>", severity: 0.3, impact_tags: ["mobility"] },
            { type: "political", name: "新型零工监管细则发布", description: "监管细则落地。", severity: 0.7, impact_tags: ["employment"] },
          ],
        },
      ],
    },
  },
  services: {
    config: {
      external_environment_service: { enabled: false, base_url: "http://127.0.0.1:8765", timeout: 6 },
      news: { enabled: true, daily_chance: 0.9 },
      llm: { routing: { "default": "minimax", tasks: { schedule: "minimax" } } },
    },
    runtime: {
      llm_providers: ["minimax", "openai_gpt"],
      llm_routing: { "default": "minimax", tasks: { schedule: "minimax" } },
      news_cache: { path: "data/news_cache.json", entries: 2, exists: true },
      targets: [
        { id: "external_environment_service", label: "外部环境服务", url: "http://127.0.0.1:8765/health", enabled: false },
        { id: "distributed_relay", label: "分布式中继", url: "http://127.0.0.1:8877/health", enabled: true },
      ],
    },
  },
};

/* ------------------------------------------------------------------ stubs */

var els = {};
var listeners = {};

function makeEl(id) {
  return {
    id: id,
    innerHTML: "",
    textContent: "",
    className: "",
    disabled: false,
    value: "",
    dataset: {},
    classList: { toggle: function () {}, add: function () {}, remove: function () {} },
    addEventListener: function (type, fn) {
      listeners[id] = listeners[id] || {};
      listeners[id][type] = fn;
    },
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; },
    parentNode: { classList: { add: function () {}, toggle: function () {} } },
  };
}

global.document = {
  readyState: "complete",
  getElementById: function (id) {
    els[id] = els[id] || makeEl(id);
    return els[id];
  },
  querySelectorAll: function () { return []; },
  addEventListener: function () {},
};

global.window = { confirm: function () { return true; } };

global.fetch = function () {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: function () { return Promise.resolve(JSON.parse(JSON.stringify(OVERVIEW))); },
  });
};

/* The panel draws every string through __()/__f() now, so supply the real
   zh-CN locale rather than a stub that echoes keys: the Chinese assertions
   below keep their meaning, and a typo'd key lands in missingKeys. */
var LOCALE = require(path.join(HERE, "locales", "zh-CN.json"));
var missingKeys = [];
global.__ = function (key) {
  if (!Object.prototype.hasOwnProperty.call(LOCALE, key)) {
    missingKeys.push(key);
    return key;
  }
  return LOCALE[key];
};
global.__f = function (key, params) {
  var text = global.__(key);
  Object.keys(params || {}).forEach(function (name) {
    text = text.split("{" + name + "}").join(String(params[name]));
  });
  return text;
};

require(path.join(HERE, "external.js"));

/* ----------------------------------------------------------------- checks */

function switchTo(tab) {
  // The panel binds one delegated click handler on the rail.
  listeners.extTabs.click({ target: { closest: function () { return { dataset: { tab: tab } }; } } });
}

setTimeout(function () {
  var observe = els.extObserve.innerHTML;
  var edit = els.extEdit.innerHTML;
  var meta = els.extTopMeta.innerHTML;

  var checks = [
    // --- currency tab (default) ---
    ["currency observation renders", observe.indexOf("货币系统现状") >= 0],
    ["macro phase is shown", observe.indexOf("扩张") >= 0],
    ["sector pools are listed", observe.indexOf("企业池") >= 0 && observe.indexOf("1,342") >= 0],
    ["conservation verdict is stated plainly", observe.indexOf("守恒审计通过") >= 0],
    ["gini is reported", observe.indexOf("0.3142") >= 0],
    ["charts render as inline svg", observe.indexOf("<svg") >= 0],
    ["pending interventions are visible", observe.indexOf("iv-abc123") >= 0],
    ["applied interventions are visible", observe.indexOf("iv-old999") >= 0],

    // The point of the runtime form: it must say the money is really injected.
    ["intervention form is present", edit.indexOf('id="ivSubmit"') >= 0],
    ["intervention form explains sector deltas", edit.indexOf("增减量") >= 0],
    ["config editor emits real inputs", edit.indexOf('data-path="economy.macro.initial_inflation_rate"') >= 0],
    ["booleans render as checkboxes", edit.indexOf('data-kind="bool"') >= 0],
    ["lists fall back to a JSON textarea", edit.indexOf('data-kind="json"') >= 0],
    ["known keys carry Chinese labels", edit.indexOf("月起征点") >= 0],
    ["unbounded tax bracket is preserved for editing", edit.indexOf("Infinity") >= 0],
    ["every locale key the panel asks for exists",
      missingKeys.length === 0 || !process.stdout.write(
        "    missing: " + missingKeys.join(", ") + "\n")],
    ["save starts disabled with nothing dirty", edit.indexOf("disabled") >= 0],
    ["header states the observation time", meta.indexOf("2026-08-01 08:00:00") >= 0],

    // --- hover help ---
    // Every metric on this panel is jargon to someone. The explanations must
    // say what the number *means*, not restate its label.
    ["metrics carry hover help", observe.indexOf('class="help-tip" data-help=') >= 0],
    ["drift help says a non-zero value is a bug", observe.indexOf("程序出问题") >= 0],
    ["gini help gives a real-world anchor", observe.indexOf("贫富差距") >= 0],
    ["unemployment help corrects the obvious misreading", observe.indexOf("并不会真的让谁丢工作") >= 0],
    ["sector pools are explained in plain language", observe.indexOf("企业池发工资") >= 0],
    ["intervention deltas are explained", edit.indexOf("加减多少钱") >= 0],
    ["config card says when edits take effect", edit.indexOf("下一次运行的规则") >= 0],
    ["config knobs carry hover help", edit.indexOf("月收入低于这个数不交税") >= 0],
    ["ambiguous keys resolve by full path", edit.indexOf("失业保险的个人缴费比例") >= 0],
    // Tooltips render via textContent, so markdown emphasis would show as
    // literal asterisks.
    ["no markdown leaks into tooltips", (observe + edit).indexOf("**") < 0],
  ];

  switchTo("environment");
  var envObserve = els.extObserve.innerHTML;
  var envEdit = els.extEdit.innerHTML;
  checks = checks.concat([
    ["environment timeline renders", envObserve.indexOf("第 49 天") >= 0],
    ["events carry type badges", envObserve.indexOf("ext-badge t-natural") >= 0],
    ["event severity is drawn", envObserve.indexOf("ext-sev") >= 0],
    // LLM-authored text lands in innerHTML; it must arrive escaped.
    ["llm event text is escaped", envObserve.indexOf("<img src=x") < 0 && envObserve.indexOf("&lt;img") >= 0],
    ["policy event schedule is editable", envEdit.indexOf('data-path="policy_events"') >= 0],
    ["severity bars explain themselves on hover", envObserve.indexOf("严重度 0.3") >= 0],
    ["impact tags explain themselves on hover", envObserve.indexOf("影响居民的哪些方面") >= 0],
    ["policy_events explains why to prefer it", envEdit.indexOf("比调概率靠谱") >= 0],
  ]);

  switchTo("services");
  var svcObserve = els.extObserve.innerHTML;
  var svcEdit = els.extEdit.innerHTML;
  checks = checks.concat([
    ["service targets are listed", svcObserve.indexOf("分布式中继") >= 0],
    ["unprobed targets say so", svcObserve.indexOf("未探测") >= 0],
    ["probe button exists", svcObserve.indexOf('id="svcProbe"') >= 0],
    ["llm routing is shown", svcObserve.indexOf("minimax") >= 0],
    ["llm routing is editable", svcEdit.indexOf('data-path="llm.routing.default"') >= 0],
    ["provider credentials are not rendered", svcEdit.indexOf("providers") < 0],
    ["health statuses are decoded on hover", svcObserve.indexOf("连不上") >= 0],
    ["llm routing help suggests a real use", svcObserve.indexOf("便宜的本地模型") >= 0],
  ]);

  var failed = 0;
  checks.forEach(function (pair) {
    if (!pair[1]) failed++;
    process.stdout.write((pair[1] ? "  ok   " : "  FAIL ") + pair[0] + "\n");
  });

  if (failed) {
    process.stdout.write("external.test.js: " + failed + " check(s) failed\n");
    process.exit(1);
  }
  process.stdout.write("external.test.js: all " + checks.length + " checks passed\n");
}, 30);
