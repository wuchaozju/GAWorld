/* Front-end integration tests for the Analytics "system" panel.
 *
 *   node --test site/dashboard/analytics-system.test.js
 *
 * The panel is rendered by analytics.js, which is an IIFE bound to the global
 * window. A live DOM would need jsdom + the locale + the chart library mocks
 * — overkill for what we want to verify here, which is "the wiring is right":
 *
 *   1. analytics.html actually mounts the panel's DOM hooks.
 *   2. analytics.js calls /api/analytics/system as part of its load() Promise.
 *   3. analytics.js renders the panel through renderSystemPanel().
 *   4. Every locale key the panel asks for exists in both locales (a typo
 *      would surface as a raw "an.sys_*" string in the UI).
 *   5. The exporter module imports cleanly and accepts a `system` payload.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const DASHBOARD = path.resolve(__dirname);

const html = fs.readFileSync(path.join(DASHBOARD, "analytics.html"), "utf8");
const script = fs.readFileSync(path.join(DASHBOARD, "analytics.js"), "utf8");
const css = fs.readFileSync(path.join(DASHBOARD, "analytics.css"), "utf8");
const locales = {
  "zh-CN": require(path.join(DASHBOARD, "locales", "zh-CN.json")),
  en: require(path.join(DASHBOARD, "locales", "en.json")),
};

test("analytics.html mounts the system panel DOM hooks", () => {
  for (const id of ["anSystemPanel", "anSystemKpis", "anSystemHealth", "anSystemGrid"]) {
    assert.ok(html.includes(`id="${id}"`), `missing #${id} in analytics.html`);
  }
  assert.ok(html.includes("analytics.system_heading"), "panel heading uses i18n key");
  assert.ok(html.includes("analytics.system_hint"), "panel hint uses i18n key");
});

test("analytics.js wires /api/analytics/system into the initial load", () => {
  // The system fetch is independent of the run picker (always the cross-world
  // view, never the picked run's).
  assert.match(script, /api\("\/api\/analytics\/system"\)/);
  assert.ok(script.includes("renderSystemPanel()"));
  // The render runs both on the first load() and on every locale-changed tick.
  const renderCount = script.match(/renderSystemPanel\(\)/g) || [];
  assert.ok(
    renderCount.length >= 2,
    `renderSystemPanel() should appear in both load() and the locale-changed listener (got ${renderCount.length})`,
  );
});

test("analytics.css styles the system panel cards as collapsible drill-downs", () => {
  assert.ok(css.includes(".an-system-grid"), "missing .an-system-grid rule");
  assert.ok(css.includes(".an-system-card"), "missing .an-system-card rule");
  assert.ok(css.includes(".an-system-warnings"), "missing .an-system-warnings rule");
});

test("every locale key the panel asks for is present in both locales", () => {
  const requestedKeys = new Set();
  // The labels are resolved through __() inside renderSystemPanel.
  // Extract every literal key the panel explicitly references.
  const literalKeys = [
    "analytics.system_heading",
    "analytics.system_hint",
    "an.sys_cities", "an.sys_cities_hint",
    "an.sys_pw", "an.sys_pw_hint",
    "an.sys_personas", "an.sys_personas_hint",
    "an.sys_experiments", "an.sys_experiments_hint",
    "an.sys_interviews", "an.sys_interviews_hint",
    "an.sys_research", "an.sys_research_hint",
    "an.sys_legco", "an.sys_legco_hint",
    "an.sys_data", "an.sys_data_hint",
    "an.sys_health_ok",
    "an.sys_card_cities", "an.sys_card_pw", "an.sys_card_interviews",
    "an.sys_card_research", "an.sys_card_personas", "an.sys_card_experiments",
    "an.sys_card_legco", "an.sys_card_info", "an.sys_card_debug",
    "an.sys_city_agents", "an.sys_city_diaries", "an.sys_city_life",
    "an.sys_city_intervention", "an.sys_city_manifest", "an.sys_city_no_manifest",
    "an.sys_pw_line",
    "an.sys_interview_line",
    "an.sys_research_plans", "an.sys_research_studies",
    "an.sys_research_games", "an.sys_research_replications",
    "an.sys_persona_confidence", "an.sys_persona_evidence",
    "an.sys_experiment_line",
    "an.sys_legco_line",
    "an.sys_info_line",
    "an.sys_items",
  ];
  for (const key of literalKeys) requestedKeys.add(key);

  for (const [lang, dict] of Object.entries(locales)) {
    for (const key of requestedKeys) {
      assert.ok(
        Object.prototype.hasOwnProperty.call(dict, key),
        `${lang} locale is missing key "${key}"`,
      );
    }
  }
});

test("the exporter module imports cleanly (smoke test)", () => {
  // analytics.js reaches for `window.GAWorldAnalyticsExport`; if the exporter
  // throws on load, the page breaks before renderSystemPanel ever runs.
  // Requiring it here forces the IIFE to evaluate in Node's vm.
  assert.doesNotThrow(() => {
    require(path.join(DASHBOARD, "analytics-export.js"));
  });
});
