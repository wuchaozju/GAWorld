/* Format tests for the analytics export builders.
 *
 *   node --test site/dashboard/analytics-export.test.js
 *
 * Follows the collaboration-core.test.js convention: plain node, no framework,
 * no browser. The builders are pure, so the fixtures below stand in for the
 * /api/analytics/* payloads and the assertions pin down the exact shape of
 * every exported file — the thing a user actually ends up with on disk.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const exporter = require("./analytics-export.js");

/* The exporter takes its translator through `labels` (it reaches for no
   globals), so hand it the real zh-CN locale. That keeps the Chinese
   assertions below meaningful and turns this into a check that every key the
   report asks for actually exists — a typo'd key would surface as a raw
   "ax.something" in the output. */
const LOCALE = require("./locales/zh-CN.json");
const missingKeys = [];

const LABELS = {
  metric: { emotion: "情绪", stress: "压力" },
  econ: { balance: "总资产", income: "收入" },
  period: { morning: "上午" },
  lang: "zh-CN",
  t: (key) => {
    if (!Object.prototype.hasOwnProperty.call(LOCALE, key)) {
      missingKeys.push(key);
      return key;
    }
    return LOCALE[key];
  },
};

const STAMP = "2026-07-31 09:30:00";

function fixture() {
  return {
    metrics: ["emotion", "stress"],
    agents: ["40"],
    econSeries: ["balance"],
    runInfo: { id: "output/comparisons/限行/with_event/visualization", kind: "scenario",
               label: "comparisons/限行/with_event" },
    overview: {
      agent_count: 2, metric_count: 2, step_count: 3, frame_count: 4,
      day_span: { first: 1, last: 2 }, event_total: 1, diary_count: 5,
      relationship_total: 7, finished: true, generated_at: "", last_updated: "2026-07-30",
      sim_meta: { sim_days: 2, seconds_per_day: 60, map_path: "maps/hz.json" },
      top_movers: [{ metric: "emotion", mean_delta: -0.12 }],
    },
    history: {
      available: true, steps: 3, sampled: false,
      metrics: ["emotion", "stress"],
      agents: [{ id: 40, name: "邓思琦" }, { id: 33, name: "钱福生" }],
      series: {
        emotion: { 40: [0.5, 0.4, 0.38], 33: [0.7, 0.7, 0.7] },
        stress: { 40: [0.2, 0.5, 0.6], 33: [0.1, 0.1, 0.1] },
      },
      deltas: {
        emotion: {
          40: { first: 0.5, last: 0.38, delta: -0.12, min: 0.38, max: 0.5, mean: 0.426667 },
          33: { first: 0.7, last: 0.7, delta: 0, min: 0.7, max: 0.7, mean: 0.7 },
        },
        stress: {
          40: { first: 0.2, last: 0.6, delta: 0.4, min: 0.2, max: 0.6, mean: 0.433333 },
          33: { first: 0.1, last: 0.1, delta: 0, min: 0.1, max: 0.1, mean: 0.1 },
        },
      },
    },
    economy: {
      available: true,
      series_keys: ["balance", "income"],
      ledger: [
        { id: 40, name: "邓思琦", days: [1, 2], balance: [100, 120], income: [10, 20] },
        { id: 33, name: "钱福生", days: [1, 2], balance: [90, 80], income: [5, 5] },
      ],
      wealth: [
        { id: 40, name: "邓思琦", portfolio_type: "稳健", balance: 120, savings: 60 },
        { id: 33, name: "钱福生", portfolio_type: "保守", balance: 80, savings: 40 },
      ],
      conservation: { day: 2, drift: 0.0001, system_total: 1000 },
      macro: { phase: "expansion", inflation_rate: 0.021, unemployment_rate: 0.05, cumulative_inflation: 1.02 },
      macro_timeline: [{ day: 1, phase: "expansion" }],
      sectors: {},
    },
    social: {
      available: true,
      nodes: [{ id: "a40", label: "邓思琦", kind: "agent" }, { id: "g1", label: "母亲", kind: "ghost" }],
      links: [{ source: "a40", target: "g1", role: "母亲", closeness: 0.9, trust: 0.8, obligation: 0.7, last_contact_day: 2 }],
      tier_counts: { inner: 1 },
      role_counts: { 母亲: 1 },
    },
    behavior: {
      available: true,
      places: [{ name: "西湖, 杭州", visits: 3 }],
      modes: [{ mode: "walk", trips: 2 }],
      heatmap: { periods: ["morning"], contexts: ["work"], cells: [{ period: "morning", context: "work", value: 0.5 }] },
      habits: [{ agent_id: 40, name: "邓思琦", period: "morning", context: "work", activity: "通勤", strength: 0.8, action: "walk", last_updated_day: 2 }],
      schedule_hours: [{ hour: 8, count: 2 }],
      agents: [],
    },
    events: {
      available: true,
      timeline: [{
        index: 0, day: 1, date: "2026-01-01", weekday: "周四", day_type: "holiday",
        events: [{ type: "policy", topic: "housing", name: "限购放松", description: "说明", severity: 0.6, scope: "city", impact_tags: ["econ", "policy"] }],
        policy: {},
      }],
      type_counts: { policy: 1 },
      impact_counts: { econ: 1 },
    },
  };
}

function fileNamed(files, name) {
  const found = files.find((file) => file.name === name);
  assert.ok(found, "missing " + name);
  return found.text;
}

/* Minimal reader for the store-only archives zipStore() writes: walk the
   central directory, then pull each entry's bytes back out of its local
   header. Proves the offsets and sizes are self-consistent. */
function unzip(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let eocd = bytes.length - 22;
  while (eocd >= 0 && view.getUint32(eocd, true) !== 0x06054b50) eocd--;
  assert.ok(eocd >= 0, "no end-of-central-directory record");

  const count = view.getUint16(eocd + 10, true);
  let cursor = view.getUint32(eocd + 16, true);
  // ignoreBOM so the assertions can see the BOM the writer prepends; the
  // default decoder would silently eat it.
  const decoder = new TextDecoder("utf-8", { ignoreBOM: true });
  const out = {};
  for (let i = 0; i < count; i++) {
    assert.equal(view.getUint32(cursor, true), 0x02014b50);
    const size = view.getUint32(cursor + 24, true);
    const nameLen = view.getUint16(cursor + 28, true);
    const offset = view.getUint32(cursor + 42, true);
    const name = decoder.decode(bytes.subarray(cursor + 46, cursor + 46 + nameLen));

    assert.equal(view.getUint32(offset, true), 0x04034b50);
    assert.equal(view.getUint16(offset + 8, true), 0, "entries must be stored, not deflated");
    const localNameLen = view.getUint16(offset + 26, true);
    const start = offset + 30 + localNameLen + view.getUint16(offset + 28, true);
    out[name] = decoder.decode(bytes.subarray(start, start + size));
    cursor += 46 + nameLen + view.getUint16(cursor + 30, true) + view.getUint16(cursor + 32, true);
  }
  assert.equal(Object.keys(out).length, count);
  return out;
}

test("selection resolves the pickers against the payloads", () => {
  const state = fixture();
  const pick = exporter.selection(state);
  assert.deepEqual(pick.metrics, ["emotion", "stress"]);
  assert.deepEqual(pick.agents.map((a) => a.name), ["邓思琦"]);
  assert.deepEqual(pick.econSeries, ["balance"]);
  assert.deepEqual(pick.ledgers.map((l) => l.id), [40]);
});

test("selection drops picks that no longer exist and keeps unknown metrics out", () => {
  const state = fixture();
  state.metrics = ["emotion", "ghost_metric"];
  state.agents = ["999"];
  state.econSeries = ["balance", "nope"];
  const pick = exporter.selection(state);
  assert.deepEqual(pick.metrics, ["emotion"]);
  assert.deepEqual(pick.agents, []);
  assert.deepEqual(pick.econSeries, ["balance"]);
  // No selected agent has a ledger, so the economy section falls back to all
  // of them — same rule renderEconomy() uses on screen.
  assert.deepEqual(pick.ledgers.map((l) => l.id), [40, 33]);
});

test("json export carries only the selected metrics and agents", () => {
  const payload = exporter.buildJson(fixture(), LABELS, STAMP);
  assert.equal(payload.exported_at, STAMP);
  assert.deepEqual(payload.scope.metrics, ["情绪", "压力"]);
  assert.deepEqual(payload.scope.agents, ["邓思琦"]);
  assert.deepEqual(Object.keys(payload.state_history.series), ["emotion", "stress"]);
  assert.deepEqual(Object.keys(payload.state_history.series.emotion), ["40"]);
  assert.deepEqual(payload.state_history.series.emotion["40"], [0.5, 0.4, 0.38]);
  assert.deepEqual(payload.economy.series_keys, ["balance"]);
  assert.equal(payload.economy.ledger.length, 1);
  assert.equal(payload.economy.ledger[0].income, undefined);
  // Sections with no picker stay whole.
  assert.equal(payload.social.links.length, 1);
  assert.equal(payload.events.timeline.length, 1);
  // Round-trips as JSON, which is the only contract the file has.
  assert.deepEqual(JSON.parse(JSON.stringify(payload)).scope, payload.scope);
});

test("exports name the run they came from", () => {
  const state = fixture();
  const json = exporter.buildJson(state, LABELS, STAMP);
  assert.equal(json.run.id, state.runInfo.id);
  assert.equal(json.scope.run, "comparisons/限行/with_event");
  assert.match(exporter.buildMarkdown(state, LABELS, STAMP), /运行：comparisons\/限行\/with_event/);
  // The picker lives in the chrome the report strips, so the banner carries it.
  assert.match(exporter.buildHtmlReport(state, LABELS, STAMP, "", ""), /运行<\/b>comparisons/);
  // Without a picked run the export is of the current one.
  assert.equal(exporter.buildJson({ ...state, runInfo: null }, LABELS, STAMP).scope.run, "当前运行");
});

test("json export survives an empty run", () => {
  const empty = {
    metrics: [], agents: [], econSeries: [],
    overview: null, history: { available: false }, economy: { available: false },
    social: { available: false }, behavior: { available: false }, events: { available: false },
  };
  const payload = exporter.buildJson(empty, LABELS, STAMP);
  assert.equal(payload.state_history, null);
  assert.equal(payload.economy, null);
  assert.deepEqual(exporter.buildCsvFiles(empty, LABELS), []);
  assert.match(exporter.buildMarkdown(empty, LABELS, STAMP), /导出范围/);
});

test("csv bundle emits one long-format file per figure", () => {
  const files = exporter.buildCsvFiles(fixture(), LABELS);
  assert.deepEqual(files.map((f) => f.name).sort(), [
    "behavior_habits.csv", "behavior_heatmap.csv", "behavior_modes.csv",
    "behavior_places.csv", "economy_ledger.csv", "economy_wealth.csv",
    "events.csv", "overview.csv", "schedule_hours.csv", "social_links.csv",
    "state_deltas.csv", "state_history.csv",
  ]);

  const history = fileNamed(files, "state_history.csv").trim().split("\r\n");
  assert.equal(history[0], "metric,metric_label,agent_id,agent_name,step_index,value");
  assert.equal(history[1], "emotion,情绪,40,邓思琦,0,0.500000");
  // Two metrics × one agent × three steps.
  assert.equal(history.length, 1 + 6);

  const deltas = fileNamed(files, "state_deltas.csv").trim().split("\r\n");
  assert.equal(deltas[1], "emotion,情绪,40,邓思琦,0.500000,0.380000,-0.120000,0.380000,0.500000,0.426667");

  const ledger = fileNamed(files, "economy_ledger.csv").trim().split("\r\n");
  assert.equal(ledger[0], "agent_id,agent_name,day,balance");
  assert.equal(ledger[1], "40,邓思琦,1,100.0000");
  assert.equal(ledger.length, 3);

  assert.equal(fileNamed(files, "events.csv").trim().split("\r\n")[1],
    "1,2026-01-01,周四,holiday,policy,housing,限购放松,city,0.600,econ|policy,说明");
});

test("csv quoting protects commas and quotes in model-authored names", () => {
  const state = fixture();
  state.behavior.places = [{ name: '西湖, "杭州"', visits: 3 }];
  const places = fileNamed(exporter.buildCsvFiles(state, LABELS), "behavior_places.csv");
  assert.equal(places.trim().split("\r\n")[1], '"西湖, ""杭州""",3');
});

test("markdown summary reports scope and the headline tables", () => {
  const md = exporter.buildMarkdown(fixture(), LABELS, STAMP);
  assert.match(md, /^# GAWorld 仿真结果分析/);
  assert.match(md, /导出时间：2026-07-31 09:30:00/);
  assert.match(md, /指标 情绪、压力；居民 邓思琦；经济序列 总资产/);
  assert.match(md, /\| 情绪 \| 邓思琦 \| 0\.500 \| 0\.380 \| -0\.120 \| 0\.427 \|/);
  assert.match(md, /\| 邓思琦 \| 120\.00 \|/);
  assert.match(md, /通胀率 \| 2\.10%/);
  assert.match(md, /\| Day 1 \| policy \| 限购放松 \| city \| 0\.60 \|/);
  // A pipe inside a place name would otherwise split the row.
  const piped = exporter.buildMarkdown(
    Object.assign(fixture(), { behavior: Object.assign(fixture().behavior, { places: [{ name: "a|b", visits: 1 }] }) }),
    LABELS, STAMP);
  assert.match(piped, /\| a\\\|b \| 1 \|/);
});

test("html report inlines the css and the rendered body", () => {
  const html = exporter.buildHtmlReport(
    fixture(), LABELS, STAMP, "<section><svg><title>x</title></svg></section>", ".an-card{color:red}");
  assert.match(html, /^<!doctype html>/);
  assert.match(html, /<style>[\s\S]*\.an-card\{color:red\}/);
  assert.match(html, /<svg><title>x<\/title><\/svg>/);
  assert.match(html, /<b>居民<\/b>邓思琦/);
  assert.match(html, /@media print/);
  // No <script> and no network references — the file has to open offline.
  assert.ok(!/<script/i.test(html));
  assert.ok(!/<link\b/i.test(html));
  assert.match(html, /\.hero::before\{display:none\}/);
});

test("html report escapes the scope banner", () => {
  const state = fixture();
  state.history.agents[0].name = '<img src=x onerror="alert(1)">';
  const html = exporter.buildHtmlReport(state, LABELS, STAMP, "", "");
  assert.ok(!html.includes("<img src=x"));
  assert.match(html, /&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;/);
});

test("zip archive is readable and preserves utf-8 content", () => {
  const files = exporter.buildCsvFiles(fixture(), LABELS);
  const entries = unzip(exporter.zipStore(files, new Date(2026, 6, 31, 9, 30, 0)));
  assert.deepEqual(Object.keys(entries).sort(), files.map((f) => f.name).sort());
  // Excel needs the BOM to read the Chinese columns as UTF-8.
  assert.equal(entries["state_history.csv"][0], "﻿");
  assert.equal(entries["state_history.csv"].slice(1), fileNamed(files, "state_history.csv"));
  assert.match(entries["behavior_places.csv"], /西湖, 杭州/);
});

test("stamps are filename-safe and human-readable", () => {
  const when = new Date(2026, 6, 3, 9, 5, 7);
  assert.equal(exporter.timestamp(when), "2026-07-03 09:05:07");
  assert.equal(exporter.fileStamp(when), "20260703-0905");
});

test("every locale key the report asks for exists", () => {
  // Populated by the LABELS.t stub above as the builders run. The tests before
  // this one exercise all four formats, so by now the tally is complete.
  assert.deepEqual(missingKeys, []);
});
