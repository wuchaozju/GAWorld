"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const controllerPath = path.join(__dirname, "theme.js");

test("the website provides a shared appearance controller", () => {
  assert.ok(fs.existsSync(controllerPath), "site/theme.js is required for light/dark switching");
});

function load({ saved = null, blocked = false, embedded = false, controls = false } = {}) {
  const windowEvents = {};
  const documentEvents = {};
  const attributes = {};
  const sent = [];
  const frameMessages = [];
  const writes = [];
  const groups = [];
  const header = { appendChild(group) { groups.push(group); } };
  const outerHeader = { appendChild() { throw new Error("the control must be inside the aligned header row"); } };
  const root = {
    dataset: {}, style: {},
    setAttribute(key, value) { attributes[key] = value; },
    getAttribute(key) { return attributes[key] || null; },
  };
  const document = {
    documentElement: root, readyState: "loading",
    addEventListener(type, listener) { documentEvents[type] = listener; },
    querySelectorAll(selector) {
      if (selector === "iframe") return [{ contentWindow: { postMessage: (...args) => frameMessages.push(args) } }];
      return selector === ".theme-switch" ? groups : [];
    },
    querySelector(selector) {
      if (!controls) return null;
      if (selector.includes(",") || selector === ".topbar") return outerHeader;
      return selector === ".topbar-inner" ? header : null;
    },
    createElement() {
      const attrs = {}, children = [], events = {}, span = {};
      return {
        dataset: {}, attrs, children, events, span,
        setAttribute(k, v) { attrs[k] = v; },
        addEventListener(k, v) { events[k] = v; },
        appendChild(child) { children.push(child); },
        querySelectorAll() { return children; },
        querySelector() { return span; },
      };
    },
    dispatchEvent() {},
  };
  const window = {
    addEventListener(type, listener) { windowEvents[type] = listener; },
    location: { origin: "http://localhost:8766" },
  };
  window.top = embedded ? {} : window;
  window.parent = embedded ? { postMessage: (...args) => sent.push(args) } : window;
  const localStorage = {
    getItem() { if (blocked) throw new Error("unavailable"); return saved; },
    setItem(key, value) { if (blocked) throw new Error("unavailable"); saved = value; writes.push([key, value]); },
  };
  const context = { window, document, localStorage, location: window.location, CustomEvent: class {} };
  vm.runInNewContext(fs.readFileSync(controllerPath, "utf8"), context);
  return { window, root, windowEvents, documentEvents, writes, sent, frameMessages, groups };
}

if (fs.existsSync(controllerPath)) {
  test("saved dark mode is applied before DOM readiness", () => {
    const app = load({ saved: "dark" });
    assert.equal(app.root.dataset.theme, "dark");
    assert.equal(app.root.style.colorScheme, "dark");
    assert.deepEqual(app.writes, []);
  });
  test("new visitors and invalid saved values start in light mode", () => {
    for (const saved of [null, "", "system", "constructor"]) {
      assert.equal(load({ saved }).root.dataset.theme, "light");
    }
  });
  test("manual changes persist and broadcast to hosted pages", () => {
    const app = load();
    app.window.GAWorldTheme.set("dark");
    assert.equal(app.root.dataset.theme, "dark");
    assert.deepEqual(app.writes, [["gaworld-theme", "dark"]]);
    assert.equal(app.frameMessages[0][0].theme, "dark");
    assert.equal(app.frameMessages[0][1], "http://localhost:8766");
    app.window.GAWorldTheme.set("light");
    assert.equal(app.root.dataset.theme, "light");
  });
  test("blocked storage leaves switching and parent synchronization usable", () => {
    const app = load({ blocked: true, embedded: true });
    assert.doesNotThrow(() => app.window.GAWorldTheme.set("dark"));
    assert.equal(app.window.GAWorldTheme.get(), "dark");
    assert.equal(app.sent[0][0].theme, "dark");
  });
  test("storage changes synchronize another page without rewriting storage", () => {
    const app = load();
    app.windowEvents.storage({ key: "gaworld-theme", newValue: "dark" });
    assert.equal(app.root.dataset.theme, "dark");
    assert.deepEqual(app.writes, []);
    app.windowEvents.storage({ key: "gaworld-theme", newValue: null });
    assert.equal(app.root.dataset.theme, "light");
  });
  test("only valid same-origin appearance messages are accepted", () => {
    const app = load();
    app.windowEvents.message({ origin: "https://other.example", data: { type: "gaworld-theme", theme: "dark" } });
    assert.equal(app.root.dataset.theme, "light");
    app.windowEvents.message({ origin: "http://localhost:8766", data: { type: "gaworld-theme", theme: "system" } });
    assert.equal(app.root.dataset.theme, "light");
    app.windowEvents.message({ origin: "http://localhost:8766", data: { type: "gaworld-theme", theme: "dark" } });
    assert.equal(app.root.dataset.theme, "dark");
    const count = app.frameMessages.length;
    app.windowEvents.message({ origin: "http://localhost:8766", data: { type: "gaworld-theme", theme: "dark" } });
    assert.equal(app.frameMessages.length, count, "repeated messages must not form an echo loop");
  });
  test("invalid manual modes are ignored", () => {
    const app = load();
    app.window.GAWorldTheme.set("system");
    assert.equal(app.root.dataset.theme, "light");
    assert.deepEqual(app.writes, []);
  });
  test("a late embedded page can obtain its parent's mode without storage", () => {
    const child = load({ blocked: true, embedded: true });
    child.documentEvents.DOMContentLoaded();
    assert.equal(child.sent[0][0].type, "gaworld-theme-request");
    const parent = load({ saved: "dark" });
    parent.windowEvents.message({
      origin: "http://localhost:8766", data: child.sent[0][0],
      source: { postMessage(message, origin) { child.windowEvents.message({ origin, data: message }); } },
    });
    assert.equal(child.root.dataset.theme, "dark");
    assert.deepEqual(child.writes, []);
  });
  test("clearing browser preferences returns open pages to light mode", () => {
    const app = load({ saved: "dark" });
    app.windowEvents.storage({ key: null, newValue: null });
    assert.equal(app.root.dataset.theme, "light");
    assert.deepEqual(app.writes, []);
  });
  test("standalone controls align with the header row and reflect clicks and locale", () => {
    const app = load({ controls: true });
    app.documentEvents.DOMContentLoaded();
    const [group] = app.groups;
    assert.equal(group.attrs["aria-label"], "外观模式");
    const [light, dark] = group.children;
    assert.equal(light.attrs["aria-pressed"], "true");
    dark.events.click();
    assert.equal(light.attrs["aria-pressed"], "false");
    assert.equal(dark.attrs["aria-pressed"], "true");
    app.root.lang = "en";
    app.documentEvents["locale-changed"]();
    assert.equal(group.attrs["aria-label"], "Appearance");
    assert.equal(light.span.textContent, "Light");
    assert.equal(dark.span.textContent, "Dark");
  });
}
