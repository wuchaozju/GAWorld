"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

test("Studio header buttons invoke their actions on click", async () => {
  const source = fs.readFileSync(path.join(__dirname, "studio.js"), "utf8");
  const elements = new Map();
  const calls = [];
  const $ = selector => {
    if (!elements.has(selector)) elements.set(selector, Object.assign(new EventTarget(), {disabled: false}));
    return elements.get(selector);
  };
  const context = {
    $, document: {querySelectorAll: () => [], addEventListener() {}},
    window: {location: {search: ""}}, URLSearchParams,
    startCreate: () => calls.push("new"), save: () => calls.push("save"), runSim: () => calls.push("run"),
    applyPersona() {}, loadCities: () => new Promise(() => {}), api: () => new Promise(() => {}),
  };
  vm.runInNewContext(
    source.slice(source.indexOf("function withBusy("), source.indexOf("async function browseAgent("))
    + source.slice(source.indexOf("function init() {"), source.indexOf('document.addEventListener("DOMContentLoaded", init);'))
    + "\ninit();", context
  );
  for (const id of ["newAgentBtn", "saveBtn", "runBtn"]) {
    $("#" + id).dispatchEvent(new Event("click"));
    await new Promise(resolve => setImmediate(resolve));
    assert.equal($("#" + id).disabled, false);
  }
  assert.deepEqual(calls, ["new", "save", "run"]);
});
