/* Headless render smoke test for the Parallel Worlds panel.
 *
 *   node site/dashboard/worlds.test.js
 *
 * Mirrors the population.test.js convention: plain node, no test framework,
 * no browser. It stubs just enough DOM and fetch to boot the panel and asserts
 * that the first render produced real content.
 *
 * Worth having because the Python tests cover the endpoints and the analysis
 * but cannot see the panel at all — a typo'd element id, a crash inside an SVG
 * builder, or an unescaped label would leave every backend test green and the
 * page blank. This catches that class of bug in about 50ms.
 */
"use strict";

var path = require("path");

var HERE = __dirname;

/* Shapes are the real ones. Regenerate with:
 *   python -c "import json; from gaworld.apps import parallel_worlds_api as a; \
 *     print(json.dumps(a.overview(), ensure_ascii=False))"
 * A trimmed inline copy keeps the test runnable with no Python present. */
var OVERVIEW = {
  defaults: { sim_days: 3, agent_ids: [1, 2], seed: 42, max_parallel: 2, llm_provider: "minimax" },
  providers: ["minimax", "ollama_local"],
  agents: [{ id: 1, name: "徐桂兰", configured: true }, { id: 2, name: "李伟", configured: true }],
  tunables: [
    { path: "economy.shocks.layoff_base_prob", value: 0.02, label: "裁员基础概率" },
    { path: "traffic.agents_represent", value: 25, label: "每人代表车辆数" },
  ],
  presets: [{
    id: "layoff",
    name: "裁员冲击",
    note: "同一批居民，一个世界里工厂裁员。",
    worlds: [
      { label: "基准世界", events: [] },
      { label: "裁员世界", events: [{ day: 2, time: "09:00", name: "大规模裁员", description: "d" }] },
    ],
  }],
  experiments: [
    { id: "e1", root: "output/parallel_worlds/e1", name: "限行实验", created_at: "2026-08-08 03:00:00",
      status: "done", worlds: 3, sim_days: 3, seed: 42, has_data: true, legacy: false },
    { id: "e0", root: "output/comparisons/e0", name: "旧实验", created_at: "2026-07-01 00:00:00",
      status: "done", worlds: 2, sim_days: 30, seed: 42, has_data: false, legacy: true },
  ],
  job: null,
  metric_labels: { emotion: "情绪", stress: "压力" },
};

/* A three-world report: baseline, a mild branch and a severe one. The severe
 * world's label carries a script tag on purpose — the panel builds SVG and
 * tables by string concatenation, so escaping is a real risk, not a ritual. */
var REPORT = {
  experiment_id: "e1",
  root: "output/parallel_worlds/e1",
  name: "限行实验",
  created_at: "2026-08-08 03:00:00",
  baseline_id: "base",
  metrics: ["emotion", "stress"],
  metric_labels: { emotion: "情绪", stress: "压力" },
  steps: 6,
  steps_per_day: 2,
  sim_days: 3,
  split_threshold: 0.02,
  status: "done",
  legacy: false,
  worlds: [
    { id: "base", label: "基准世界", events: [], config: {}, is_baseline: true, has_data: true,
      steps: 6, agents: 2, divergence_final: 0, divergence_peak: 0, split_step: null,
      top_metric: null, top_label: null, top_delta: 0, status: "done",
      trace: "output/parallel_worlds/e1/worlds/base/visualization/simulation_trace.json",
      dir: "output/parallel_worlds/e1/worlds/base" },
    { id: "mild", label: "轻度限行", is_baseline: false, has_data: true, steps: 6, agents: 2,
      config: {}, events: [{ day: 2, time: "07:00", name: "限行", description: "单双号" }],
      divergence_final: 0.05, divergence_peak: 0.06, split_step: 2,
      top_metric: "emotion", top_label: "情绪", top_delta: -0.08, status: "done",
      trace: "output/parallel_worlds/e1/worlds/mild/visualization/simulation_trace.json",
      dir: "output/parallel_worlds/e1/worlds/mild" },
    { id: "harsh", label: "<script>alert(1)</script>重度管制", is_baseline: false, has_data: true,
      steps: 6, agents: 2, config: {},
      events: [{ day: 2, time: "07:00", name: "全面管制", description: "主干道封闭" }],
      divergence_final: 0.12, divergence_peak: 0.14, split_step: 2,
      top_metric: "stress", top_label: "压力", top_delta: 0.19, status: "done",
      trace: "output/parallel_worlds/e1/worlds/harsh/visualization/simulation_trace.json",
      dir: "output/parallel_worlds/e1/worlds/harsh" },
  ],
  trajectories: {
    emotion: {
      base: [0.60, 0.61, 0.62, 0.63, 0.64, 0.65],
      mild: [0.60, 0.61, 0.57, 0.56, 0.57, 0.57],
      harsh: [0.60, 0.61, 0.50, 0.48, null, 0.47],
    },
    stress: {
      base: [0.40, 0.41, 0.42, 0.43, 0.44, 0.45],
      mild: [0.40, 0.41, 0.47, 0.48, 0.49, 0.50],
      harsh: [0.40, 0.41, 0.60, 0.62, 0.63, 0.64],
    },
  },
  divergence: {
    base: [0, 0, 0, 0, 0, 0],
    mild: [0, 0, 0.05, 0.055, 0.06, 0.05],
    harsh: [0, 0, 0.11, 0.13, 0.14, 0.12],
  },
  deltas: [
    { world_id: "harsh", metric: "stress", label: "压力", baseline_final: 0.45, final: 0.64,
      delta_final: 0.19, baseline_mean: 0.425, mean: 0.55, delta_mean: 0.125 },
    { world_id: "mild", metric: "emotion", label: "情绪", baseline_final: 0.65, final: 0.57,
      delta_final: -0.08, baseline_mean: 0.625, mean: 0.58, delta_mean: -0.045 },
  ],
  movers: {
    mild: [{ agent_id: "1", distance: 0.06, top_metric: "emotion", top_label: "情绪",
      top_delta: -0.08, deltas: { emotion: -0.08 } }],
    harsh: [{ agent_id: "2", distance: 0.15, top_metric: "stress", top_label: "压力",
      top_delta: 0.19, deltas: { stress: 0.19 } }],
  },
  summary: ["基准世界：基准世界", "轻度限行：第 2 步开始分叉，终局距离基准 0.0500"],
  causal: {
    baseline_id: "base",
    alpha: 0.05,
    method: { bootstrap: 2000, permutations: 5000 },
    placebo_ids: [],
    noise: {},
    warnings: [],
    summary: { robust: 1, null: 1 },
    estimates: [
      { world_id: "harsh", metric: "stress", label: "压力", n: 2, event_step: 2, ate: 0.19, ci_low: 0.15,
        ci_high: 0.22, p_value: 0.0002, q_value: 0.0004, d_z: 3.1, ate_final: 0.19, relative: 0.42,
        pre_gap: 0.0, did: 0.19, balanced: true, noise: null, role: "treatment", verdict: "robust" },
      { world_id: "mild", metric: "emotion", label: "情绪", n: 2, event_step: 2, ate: -0.01, ci_low: -0.04,
        ci_high: 0.02, p_value: 0.5, q_value: 0.5, d_z: null, ate_final: -0.02, relative: null,
        pre_gap: null, did: null, balanced: null, noise: null, role: "", verdict: "null" },
    ],
    dynamics: {
      harsh: { order: ["stress"], metrics: {
        stress: { onset_step: 2, peak_step: 3, peak: 0.2, final: 0.19, persistence: 0.95, half_life: null },
        emotion: { onset_step: null, peak_step: 1, peak: -0.01, final: 0, persistence: 0, half_life: 1 },
      } },
    },
    effect_curves: {
      harsh: { stress: { mean: [0, 0, 0.18, 0.2, 0.19, 0.19], lo: [0, 0, 0.15, 0.17, null, 0.16],
                         hi: [0, 0, 0.21, 0.23, null, 0.22] } },
    },
    dose_response: [
      { metric: "stress", label: "压力", slope: 0.09, intercept: 0, r2: 0.98, monotonic: true,
        points: [{ world_id: "base", dose: 0, ate: 0 }, { world_id: "mild", dose: 1, ate: 0.08 },
                 { world_id: "harsh", dose: 2, ate: 0.19 }] },
    ],
  },
  replication: {
    group: "g", seeds: [42, 43, 44],
    summary: { replicated: 1 },
    rows: [{ world_id: "harsh", metric: "stress", label: "压力", seeds: 3, mean: 0.18, sd: 0.01,
             ci_low: 0.155, ci_high: 0.205, agree: 3, verdict: "replicated",
             per_seed: [{ seed: 42, ate: 0.19 }, { seed: 43, ate: 0.17 }, { seed: 44, ate: 0.18 }] }],
    excluded: [{ seed: 45, root: "output/parallel_worlds/g_s45", comparability_epoch: 4 }],
  },
};

var INTERPRETATION = { interpretation: {
  summary: "重度管制显著推高了压力。", baseline_id: "base", provider: "minimax", created_at: "2026-10-03 01:00:00",
  findings: [
    { world: "harsh", metric: "stress", metric_label: "压力", claim: "压力上升", evidence: "ATE +0.19",
      grounded: true, verdict: "robust" },
    { world: "mild", metric: "emotion", metric_label: "情绪", claim: "情绪下降", evidence: "",
      grounded: true, verdict: "null" },
    { world: "nope", metric: "emotion", claim: "凭空", evidence: "", grounded: false, verdict: "" },
  ],
  limitations: ["没有安慰剂世界"],
  next_experiments: [{ title: "加安慰剂", rationale: "量噪声", design: "加一个市政通告世界" }],
} };

var HTE = {
  metric: "stress", label: "压力", n: 2, ate: 0.19, world_id: "harsh", baseline_id: "base", event_step: 2,
  attributes: [
    { id: "gender", p_value: 0.01, spread: 0.1, groups: [
      { group: "女", n: 1, cate: 0.24, ci_low: 0.24, ci_high: 0.24 },
      { group: "男", n: 1, cate: 0.14, ci_low: 0.14, ci_high: 0.14 } ] },
    { id: "initial", p_value: 0.4, spread: null, groups: [
      { group: "low", n: 1, cate: 0.2, ci_low: 0.2, ci_high: 0.2 },
      { group: "high", n: 1, cate: 0.18, ci_low: 0.18, ci_high: 0.18 } ] },
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
    hidden: false,
    value: "",
    type: "",
    checked: false,
    dataset: {},
    classList: { toggle: function () {}, add: function () {}, remove: function () {} },
    addEventListener: function () {},
    getAttribute: function () { return null; },
    setAttribute: function () {},
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; },
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

// The panel only sets timers while a run is in flight; neutralise them so the
// test process does not stay alive waiting for a poll that never resolves.
global.setInterval = function () { return 0; };
global.clearInterval = function () {};

/* The panel draws every string through __() now, so the test supplies the real
   zh-CN locale rather than a stub that echoes keys. That makes the assertions
   below keep their meaning, and it turns this into a check that every key the
   panel asks for actually exists — a typo'd key would surface as a raw
   "pw.something" in the rendered HTML and trip the checks. */
var LOCALE = require(path.join(HERE, "locales", "zh-CN.json"));
var missingKeys = [];
global.__ = function (key) {
  if (Object.prototype.hasOwnProperty.call(LOCALE, key)) return LOCALE[key];
  missingKeys.push(key);
  return key;
};
global.__f = function (key, params) {
  var text = global.__(key);
  Object.keys(params || {}).forEach(function (name) {
    text = text.split("{" + name + "}").join(String(params[name]));
  });
  return text;
};

var requested = [];
global.fetch = function (url) {
  requested.push(String(url));
  var body = String(url).indexOf("/interpretation") >= 0 ? INTERPRETATION
    : String(url).indexOf("/heterogeneity") >= 0 ? HTE
    : String(url).indexOf("/experiment") >= 0 ? REPORT : OVERVIEW;
  return Promise.resolve({
    ok: true,
    status: 200,
    json: function () { return Promise.resolve(JSON.parse(JSON.stringify(body))); },
  });
};

/* What POST /api/parallel-worlds/sweep returns (gaworld/parallel/sweep.py). */
var SWEEP = {
  path: "economy.shocks.layoff_base_prob", label: "裁员基础概率", current: 0.02, values: [0.04, 0.08],
  baseline_id: "baseline",
  dropped: [{ value: "0.02", reason: "与当前值相同，就是基准世界" }],
  worlds: [
    { id: "baseline", label: "基准：裁员基础概率 = 0.02", role: "baseline", dose: 0.02, config: {}, events: [] },
    { id: "v1", label: "裁员基础概率 = 0.04", role: "treatment", dose: 0.04,
      config: { economy: { shocks: { layoff_base_prob: 0.04 } } }, events: [] },
    { id: "v2", label: "裁员基础概率 = 0.08", role: "treatment", dose: 0.08,
      config: { economy: { shocks: { layoff_base_prob: 0.08 } } }, events: [] },
    { id: "placebo", label: "安慰剂：裁员基础概率 = 0.02", role: "placebo", dose: 0.02, config: {}, events: [] },
  ],
};

var panel = require(path.join(HERE, "worlds.js"));

/* ----------------------------------------------------------------- checks */

setTimeout(function () {
  var shared = els.pwShared.innerHTML;
  var worlds = els.pwWorldList.innerHTML;
  var presets = els.pwPresets.innerHTML;
  var branch = els.pwBranch.innerHTML;
  var trajectory = els.pwTrajectory.innerHTML;
  var divergence = els.pwDivergence.innerHTML;
  var deltas = els.pwDeltas.innerHTML;
  var movers = els.pwMovers.innerHTML;
  var legend = els.pwLegend.innerHTML;
  var history = els.pwHistory.innerHTML;
  var meta = els.pwTopMeta.innerHTML;
  var metrics = els.pwMetricSelect.innerHTML;
  var verdicts = els.pwVerdicts.innerHTML;
  var forest = els.pwForest.innerHTML;
  var estimates = els.pwEstimates.innerHTML;
  var dynamics = els.pwDynamics.innerHTML;
  var hte = els.pwHte.innerHTML;
  var replication = els.pwReplication.innerHTML;
  var dose = els.pwDose.innerHTML;
  var compare = els.pwCompare.innerHTML;
  var interpretation = els.pwInterpret.innerHTML;
  var all = [branch, trajectory, divergence, deltas, movers, legend, meta, verdicts, forest, estimates,
    dynamics, hte, replication, dose, compare, interpretation].join("");

  var sweepForm = els.pwSweep.innerHTML;
  panel.applySweep(SWEEP);
  var swept = els.pwWorldList.innerHTML;
  var sweepMsg = els.pwSweep.innerHTML;
  var payload = panel.specPayload();

  var checks = [
    // --- design column: the thing the user actually edits ---
    ["shared settings render", shared.indexOf('data-spec="sim_days"') >= 0],
    ["defaults come from the backend", shared.indexOf('value="3"') >= 0],
    ["providers come from the backend", shared.indexOf("minimax") >= 0],
    ["two worlds are offered to start with",
      (worlds.match(/class="pw-world[ "]/g) || []).length === 2],
    ["a world exposes an editable event", worlds.indexOf('data-field="name"') >= 0],
    ["a world can be marked as the baseline", worlds.indexOf('data-baseline=') >= 0],
    ["events can be added and removed",
      worlds.indexOf("data-addevent=") >= 0 && worlds.indexOf("data-delevent=") >= 0],
    ["a world can be copied or deleted",
      worlds.indexOf("data-copy=") >= 0 && worlds.indexOf("data-remove=") >= 0],
    ["presets come from the backend", presets.indexOf("裁员冲击") >= 0],

    // --- observation column ---
    ["it auto-loads the newest experiment that has data",
      requested.join(" ").indexOf("parallel_worlds%2Fe1") >= 0],
    ["it does not open the empty legacy run",
      requested.join(" ").indexOf("comparisons%2Fe0") < 0],
    ["branch diagram draws one line per world",
      (branch.match(/class="pw-series/g) || []).length === 3],
    ["branch diagram marks where each history split",
      (branch.match(/class="pw-node"/g) || []).length === 2],
    ["branch diagram labels the events", branch.indexOf("全面管制") >= 0],
    ["each world links to its own replay",
      (branch.match(/class="pw-replay"/g) || []).length === 3 &&
      branch.indexOf("simviz") >= 0],
    ["trajectory chart draws the selected metric",
      trajectory.indexOf("<svg") >= 0 && (trajectory.match(/class="pw-series/g) || []).length === 3],
    ["a null in a series breaks the path instead of drawing through it",
      (trajectory.match(/M\d/g) || []).length > 3],
    ["trajectory marks the event days", trajectory.indexOf("pw-eventline") >= 0],
    ["metric selector is populated and localized",
      metrics.indexOf("情绪") >= 0 && metrics.indexOf("压力") >= 0],
    ["divergence chart draws the split threshold", divergence.indexOf("分叉阈值") >= 0],
    ["divergence chart skips the baseline (it is zero by definition)",
      (divergence.match(/class="pw-series/g) || []).length === 2],
    ["delta table names worlds and metrics in words",
      deltas.indexOf("轻度限行") >= 0 && deltas.indexOf("压力") >= 0],
    ["delta table signs the change", deltas.indexOf("+0.190") >= 0 && deltas.indexOf("-0.080") >= 0],
    ["movers table resolves agent ids to names", movers.indexOf("徐桂兰") >= 0],
    ["legend offers a per-world toggle",
      (legend.match(/data-toggle=/g) || []).length === 3],
    ["header carries the experiment summary", meta.indexOf("限行实验") >= 0],
    ["history lists past experiments and flags the empty ones",
      history.indexOf("旧实验") >= 0 && history.indexOf("无数据") >= 0],

    // --- counterfactual inference ---
    ["a world can be given a role and a dose",
      worlds.indexOf('data-field="role"') >= 0 && worlds.indexOf('data-field="dose"') >= 0],
    ["seed replicates are part of the shared setup", shared.indexOf('data-spec="replicates"') >= 0],
    ["the comparison world can be switched", (compare.match(/<option/g) || []).length === 3 &&
      compare.indexOf('value="base" selected') >= 0],
    ["verdict counts are summarized", verdicts.indexOf("稳健") >= 0 && verdicts.indexOf("无效应") >= 0],
    ["a missing placebo is called out", verdicts.indexOf("安慰剂") >= 0],
    ["forest plot draws one interval per estimate", (forest.match(/<circle/g) || []).length === 2],
    ["estimates table shows CI, p and q",
      estimates.indexOf("[+0.150, +0.220]") >= 0 && estimates.indexOf("&lt;0.001") >= 0],
    ["dynamics order the metrics by onset", dynamics.indexOf("压力") >= 0 && dynamics.indexOf("未起效") >= 0],
    ["heterogeneity is fetched and drawn by attribute",
      requested.join(" ").indexOf("/heterogeneity") >= 0 && hte.indexOf("性别") >= 0 &&
      hte.indexOf("低于中位") >= 0],
    ["replication pools the seeds", replication.indexOf("跨种子复现") >= 0 && replication.indexOf("3/3") >= 0],
    ["a seed from another code epoch is named, not silently dropped",
      replication.indexOf("种子 45") >= 0 && replication.indexOf("代码版本") >= 0],
    ["dose-response renders its slope", dose.indexOf("+0.0900") >= 0],

    ["the cached interpretation is loaded and drawn",
      requested.join(" ").indexOf("/interpretation") >= 0 && interpretation.indexOf("显著推高了压力") >= 0],
    ["each finding carries its row's verdict", interpretation.indexOf("稳健") >= 0],
    ["a finding on a non-robust row is cautioned", interpretation.indexOf("没有被判为「稳健」") >= 0],
    ["a finding that points at no row does not count", interpretation.indexOf("不作数") >= 0],
    ["limitations and next experiments are listed",
      interpretation.indexOf("没有安慰剂世界") >= 0 && interpretation.indexOf("加安慰剂") >= 0],
    ["the interpretation can be re-run", els.pwInterpretRun.textContent === "重新解读"],

    // --- safety / correctness ---
    ["labels are escaped everywhere they are drawn", all.indexOf("<script>alert") < 0],
    ["the escaped label still reads correctly", all.indexOf("重度管制") >= 0],
    ["nothing leaks undefined or NaN",
      all.indexOf("undefined") < 0 && all.indexOf("NaN") < 0],

    // --- parameter sweep ---
    ["the sweep form offers the numeric settings",
      sweepForm.indexOf('data-sweep="path"') >= 0 && sweepForm.indexOf("traffic.agents_represent") >= 0],
    ["a sweep fills the form with one world per value",
      (swept.match(/class="pw-world[ "]/g) || []).length === 4],
    ["a swept world shows its config patch", swept.indexOf("economy.shocks.layoff_base_prob = 0.04") >= 0],
    ["the config patch and the dose reach the run payload",
      payload.worlds[1].config.economy.shocks.layoff_base_prob === 0.04 && payload.worlds[1].dose === 0.04],
    ["the sweep baseline keeps the current value as its dose",
      payload.worlds[0].role === "baseline" && payload.worlds[0].dose === 0.02 &&
      JSON.stringify(payload.worlds[0].config) === "{}"],
    ["the placebo copy is marked as a placebo", payload.worlds[3].role === "placebo"],
    ["a skipped value is reported", sweepMsg.indexOf("跳过 0.02") >= 0],
    ["the experiment is named after the setting", payload.name.indexOf("裁员基础概率") >= 0],

    // --- i18n ---
    ["every locale key the panel asks for exists",
      missingKeys.length === 0 || !process.stdout.write("    missing: " + missingKeys.join(", ") + "\n")],
    ["no untranslated key leaked into the markup", !/\bpw\.[a-z_]+\b/.test(all)],
  ];

  var failed = 0;
  checks.forEach(function (pair) {
    if (!pair[1]) failed++;
    process.stdout.write((pair[1] ? "  ok   " : "  FAIL ") + pair[0] + "\n");
  });

  if (failed) {
    process.stdout.write("worlds.test.js: " + failed + " check(s) failed\n");
    process.exit(1);
  }
  process.stdout.write("worlds.test.js: all " + checks.length + " checks passed\n");
}, 0);
