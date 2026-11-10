"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const charts = require("./survey-charts.js");

function boot() {
  let query;
  let panelHTML = "";
  const document = {
    readyState: "loading",
    addEventListener() {},
    querySelectorAll() { return []; },
    getElementById(id) { return id === "svPanel" ? panel : id === "svQuery" ? query : null; },
  };
  const panel = {
    get innerHTML() { return panelHTML; },
    set innerHTML(html) {
      panelHTML = html;
      query = new EventTarget();
      query.value = /id="svQuery"[^>]*value="([^"]*)"/.exec(html)?.[1] || "";
      query.focus = () => { document.activeElement = query; };
      query.setSelectionRange = (start, end, direction) => {
        query.selectionStart = start;
        query.selectionEnd = end;
        query.selectionDirection = direction;
      };
    },
  };
  const window = { GAWorldSurveyCharts: charts };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "survey.js"), "utf8"), {window, document});
  const survey = window.__gaworldSurvey;
  survey.state.roster = { cities: [], axes: [], groups: [] };
  survey.render();
  return {survey, document, get query() { return query; }};
}

test("Chinese composition keeps the search input alive until the text is committed", () => {
  const app = boot();
  const input = app.query;
  input.focus();
  input.dispatchEvent(new Event("compositionstart"));
  input.value = "zhong";
  input.dispatchEvent(new Event("input"));
  assert.equal(app.query, input, "rerender interrupted the IME candidate session");
  input.value = "中文";
  input.setSelectionRange(2, 2, "none");
  input.dispatchEvent(new Event("compositionend"));
  assert.equal(app.survey.state.query, "中文");
  assert.equal(app.query.value, "中文");
  assert.equal(app.document.activeElement, app.query);
});

test("ordinary search preserves the caret and a backwards selection", () => {
  const app = boot();
  app.query.value = "李老师";
  app.query.setSelectionRange(1, 2, "backward");
  app.query.dispatchEvent(new Event("input"));
  assert.equal(app.survey.state.query, "李老师");
  assert.deepEqual([app.query.selectionStart, app.query.selectionEnd, app.query.selectionDirection], [1, 2, "backward"]);
});

test("an input event marked as composing does not rebuild the search box", () => {
  const app = boot();
  const input = app.query;
  input.value = "zhong";
  const event = new Event("input");
  Object.defineProperty(event, "isComposing", {value: true});
  input.dispatchEvent(event);
  assert.equal(app.query, input);
});
