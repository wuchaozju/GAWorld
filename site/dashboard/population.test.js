/* Headless render smoke test for Population Studio.
 *
 *   node site/dashboard/population.test.js
 *
 * Mirrors the existing collaboration-core.test.js convention: plain node, no
 * test framework, no browser. It stubs just enough DOM and fetch to boot the
 * panel and asserts the first render actually produced content.
 *
 * Worth having because the Python tests cover the endpoints but cannot see the
 * panel at all — a typo'd element id or a crash inside a renderer would leave
 * every backend test green and the UI blank. This catches that class of bug in
 * about 50ms.
 */
"use strict";

var path = require("path");

var HERE = __dirname;

/* Fixtures are generated from the real backend so the shapes cannot drift:
 *   python -c "import json; from gaworld.apps import population_api as a; \
 *     print(json.dumps(a.population_schema(), ensure_ascii=False))"
 * A trimmed inline copy keeps the test runnable with no Python present. */
var SCHEMA = {
  version: "1.0",
  presets: ["aging_community", "cn_county_town", "custom"],
  state_var_keys: [
    "emotion", "stress", "econ_security", "city_identity", "policy_sensitivity",
    "platform_dependence", "risk_preference", "voice_propensity", "mobility_intent",
  ],
  industries: ["tech", "finance", "medical", "education", "service", "trade"],
  education_levels: ["小学及以下", "初中", "高中/中专", "大专", "本科", "硕士及以上"],
  hukou_labels: ["本地", "省内", "外省", "外国"],
  cohort_axes: ["age_band", "district", "employment", "gender", "hukou", "industry"],
  cohort_axis_labels: { age_band: "年龄段", industry: "行业", hukou: "户籍" },
  household_type_labels: {
    single: "独居", couple: "夫妻二人", nuclear: "核心家庭",
    single_parent: "单亲家庭", multigen: "三代同堂", shared_rental: "合租",
  },
  preset_descriptions: {
    cn_county_town: { title: "中国县城 / 普通城区", summary: "最接近平均的一座小城。", use_when: "不确定时就用它。" },
    aging_community: { title: "老龄化社区", summary: "65 岁以上占 34%。", use_when: "研究养老。" },
    custom: { title: "自定义", summary: "改过参数后自动切到这里。", use_when: "你已经知道要什么。" },
  },
  providers: [
    { name: "ollama_gemma4", type: "ollama", model: "gemma4:e4b", base_url: "", is_default: false },
    { name: "minimax", type: "anthropic", model: "MiniMax-M2.7", base_url: "", is_default: true },
  ],
  ranges: { size: { min: 20, max: 5000 } },
  notes: { network_coupling: "…需重新标定", materialization_budget: "…" },
  defaults: {
    size: 500, seed: 42, preset: "cn_county_town", name: "generated_town",
    demography: {
      median_age: 36, share_under_18: 0.16, share_over_65: 0.14,
      sex_ratio_m_per_100f: 104, migrant_share: 0.38, min_agent_age: 6,
    },
    household: {
      mean_size: 2.6, share_single_person: 0.25, share_multigen: 0.18,
      share_shared_rental: 0.12, max_size: 6, spouse_age_gap_mean: 2,
      fertility_children_mean: 1.1,
    },
    education_work: {
      tertiary_rate: 0.35, employment_rate: 0.68, unemployment_rate: 0.05,
      gig_platform_share: 0.1, industry_mix: {},
    },
    income: { median_monthly: 6500, gini: 0.42, pareto_tail_alpha: 2.2, tail_threshold_pct: 0.95 },
    geography: { district_weights: {} },
    psychology: {
      state_means: {
        emotion: 0.58, stress: 0.55, econ_security: 0.52, city_identity: 0.55,
        policy_sensitivity: 0.5, platform_dependence: 0.5, risk_preference: 0.45,
        voice_propensity: 0.45, mobility_intent: 0.45,
      },
      state_sd: 0.12, couple_states_to_attributes: true,
    },
    social_network: {
      mean_degree: 12, homophily_strength: 0.55, geo_decay: 0.35, rewire_p: 0.1,
      workplace_size_alpha: 2, dunbar_weak_cap: 150,
    },
  },
};

var PREVIEW = {
  spec: SCHEMA.defaults,
  issues: [],
  has_errors: false,
  bounds: {
    household_mean_size: { min: 1.75, max: 4.75 },
    median_age: { min: 26.26, max: 59.86 },
  },
};

/* A generated population, trimmed from a real
 * ``/api/population/generate`` result (size 24, seed 7). Step 2 renders the
 * roster straight off these fields, so a renamed field in the Python payload
 * has to show up here as a failing check rather than as an empty table. */
var POPULATION = {
  report: {
    size: 24,
    achieved: {
      median_age: { target: 36.0, achieved: 29.5, delta: -6.5 },
      share_over_65: { target: 0.14, achieved: 0.25, delta: 0.11 },
      employment_rate: { target: 0.68, achieved: 0.6875, delta: 0.0075 },
      income_median: { target: 6500, achieved: 6500, delta: 0 },
      income_gini: { target: 0.42, achieved: 0.4074, delta: -0.0126 },
      household_mean_size: { target: 2.6, achieved: 2.6667, delta: 0.0667 },
      mean_degree: { target: 12, achieved: 11.5, delta: -0.5 },
    },
    charts: {
      age_pyramid: [{ age_from: 5, age_to: 9, male: 1, female: 1 }],
      lorenz: [{ population_share: 0.0, income_share: 0.0 }, { population_share: 0.1, income_share: 0.0497 }],
      household_sizes: [{ size: 1, count: 2 }, { size: 2, count: 2 }],
      state_distribution: {},
    },
    network: {
      degree_histogram: [{ degree: 5, count: 1 }],
      clustering: 0.6568, random_clustering: 0.5, mean_path_length: 1.4818,
    },
  },
  worst_gaps: [{ knob: "share_over_65", target: 0.14, achieved: 0.25, relative_error: 0.7857 }],
  people: [
    {
      id: 1, name: "黄萱", gender: "女", age: 50, hukou: "本地", residence: "滨江·老小区",
      job: "无业，家庭照料为主", industry: "none", employment: "not_in_labor_force",
      income_monthly: 0.0, household_type: "multigen",
      state: {
        emotion: 0.6295, stress: 0.5319, econ_security: 0.382, city_identity: 0.5393,
        policy_sensitivity: 0.6197, platform_dependence: 0.5616, risk_preference: 0.4211,
        voice_propensity: 0.466, mobility_intent: 0.4867,
      },
    },
    {
      id: 3, name: "谭颖露", gender: "女", age: 28, hukou: "外省", residence: "西湖·青年公寓",
      job: "网约车司机", industry: "service", employment: "employed",
      income_monthly: 3981.83, household_type: "shared_rental",
      state: {
        emotion: 0.6788, stress: 0.6419, econ_security: 0.4765, city_identity: 0.2699,
        policy_sensitivity: 0.5119, platform_dependence: 0.538, risk_preference: 0.5103,
        voice_propensity: 0.3757, mobility_intent: 0.5633,
      },
    },
  ],
};

/* ------------------------------------------------------------------ stubs */

var els = {};

function makeEl(id) {
  return {
    id: id,
    innerHTML: "",
    textContent: "",
    disabled: false,
    value: "",
    type: "",
    dataset: {},
    classList: { toggle: function () {}, add: function () {}, remove: function () {} },
    addEventListener: function () {},
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; },
    parentNode: { querySelector: function () { return null; } },
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

// Run the panel's own scheduled work immediately (its preview call is
// debounced by 180ms) while keeping a real timer for the assertions, so they
// observe the state *after* the debounced render rather than before it.
var realSetTimeout = global.setTimeout;
global.setTimeout = function (fn) { fn(); return 0; };
global.clearTimeout = function () {};

global.fetch = function (url) {
  var body = String(url).indexOf("/schema") >= 0 ? SCHEMA : PREVIEW;
  return Promise.resolve({
    ok: true,
    status: 200,
    json: function () { return Promise.resolve(JSON.parse(JSON.stringify(body))); },
  });
};

/* The wizard draws its text through __()/__f() now, so supply the real zh-CN
   locale rather than a stub that echoes keys: the Chinese assertions below keep
   their meaning, and a typo'd key lands in missingKeys. */
var LOCALE = require(require("path").join(__dirname, "locales", "zh-CN.json"));
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

require(path.join(HERE, "population.js"));

/* ----------------------------------------------------------------- checks */

realSetTimeout(function () {
  var panel = els.popPanel ? els.popPanel.innerHTML : "";
  var issues = els.popIssues ? els.popIssues.innerHTML : "";
  var meta = els.popTopMeta ? els.popTopMeta.innerHTML : "";
  var summary = els.popSummary ? els.popSummary.textContent : "";

  var checks = [
    ["step 1 renders", panel.indexOf("第 1 步") >= 0],
    ["preset options come from the schema", panel.indexOf("cn_county_town") >= 0],
    ["size field bound to spec path", panel.indexOf('data-path="size"') >= 0],
    ["seed field present", panel.indexOf('data-path="seed"') >= 0],
    ["feasibility panel populated", issues.length > 0],
    ["no HTML injected unescaped", panel.indexOf("<script") < 0],

    // --- the things the user asked for ---
    // A bare identifier like "college_town" tells a user nothing; the panel
    // must say what the preset actually is.
    ["selected preset is described in plain language", panel.indexOf("中国县城") >= 0],
    ["preset says when to use it", panel.indexOf("什么时候用它") >= 0],
    // "same seed = byte-identical population" is jargon; explain the point.
    ["random seed explained without jargon", panel.indexOf("随机种子是什么") >= 0 && panel.indexOf("可复现") >= 0],
    // Hover help on the knobs.
    ["knobs carry hover help", panel.indexOf('class="pop-q"') >= 0 && panel.indexOf("title=") >= 0],
    // The primary action must live in the panel. Relying on a footer button
    // whose label changes is why "生成人口" looked like it did nothing.
    ["panel carries its own next-step button", panel.indexOf('data-go="2"') >= 0],
    // The feasibility panel must speak plainly too.
    ["feasibility panel speaks plainly", issues.indexOf("参数没有冲突") >= 0 || issues.indexOf("做不出来") >= 0],
    ["reachable range is explained", issues.indexOf("可行范围") >= 0],
    ["header lists localized cohort axes", meta.indexOf("年龄段") >= 0],
    ["summary tells the user where to generate", summary.indexOf("第 2 步") >= 0 || els.popSummary.innerHTML.indexOf("第 2 步") >= 0],
    ["every locale key the wizard asks for exists",
      missingKeys.length === 0 || !process.stdout.write(
        "    missing: " + missingKeys.join(", ") + "\n")],
  ];

  /* Step 2 with a population in hand: the generated agents must be
     previewable and downloadable without running a simulation first. */
  var hook = global.__POP_TEST__;
  hook.setPopulation(POPULATION);
  hook.setStep(2);
  hook.render();
  var step2 = els.popPanel.innerHTML;
  var roster = els.popRosterBody.innerHTML;
  hook.state.roster.open = 1;
  hook.render();
  var expanded = els.popRosterBody.innerHTML;

  checks = checks.concat([
    ["roster card renders after generation", step2.indexOf("居民名册") >= 0],
    ["roster lists the generated residents", roster.indexOf("黄萱") >= 0 && roster.indexOf("网约车司机") >= 0],
    ["household type is localized, not an identifier",
      roster.indexOf("三代同堂") >= 0 && roster.indexOf("multigen") < 0],
    ["people with no wage income are not shown as 0", roster.indexOf("—") >= 0],
    ["roster says how many of how many are shown", els.popRosterCount.textContent.indexOf("共 2 人") >= 0],
    ["a row expands into the nine state variables",
      (expanded.match(/pop-statebar"/g) || []).length === 9],
    ["all three downloads are offered",
      step2.indexOf('data-export="csv"') >= 0 && step2.indexOf('data-export="md"') >= 0 &&
      step2.indexOf('data-export="json"') >= 0],
    ["step 2 leaks no undefined", step2.indexOf("undefined") < 0 && expanded.indexOf("undefined") < 0],
  ]);

  var failed = 0;
  checks.forEach(function (pair) {
    var ok = pair[1];
    if (!ok) failed++;
    process.stdout.write((ok ? "  ok   " : "  FAIL ") + pair[0] + "\n");
  });

  if (failed) {
    process.stdout.write("population.test.js: " + failed + " check(s) failed\n");
    process.exit(1);
  }
  process.stdout.write("population.test.js: all " + checks.length + " checks passed\n");
}, 0);
