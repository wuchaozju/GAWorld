const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(__dirname + "/theme.js", "utf8");

function page(saved, dark = false, blocked = false) {
  const listeners = {};
  const media = { matches: dark, addEventListener: (name, fn) => { listeners.media = fn; } };
  const storage = new Map(saved ? [["gaworld.theme", saved]] : []);
  const localStorage = {
    getItem: key => { if (blocked) throw Error("disabled"); return storage.get(key); },
    setItem: (key, value) => { if (blocked) throw Error("disabled"); storage.set(key, value); },
  };
  const document = {
    documentElement: { dataset: {}, style: {} },
    getElementById: () => null,
    addEventListener: () => {},
  };
  const window = {
    matchMedia: () => media,
    addEventListener: (name, fn) => { listeners[name] = fn; },
  };
  vm.runInNewContext(source, { window, document, localStorage });
  return { window, document, media, listeners, storage };
}

test("applies the system theme before page rendering", () => {
  const p = page(null, true);
  assert.equal(p.document.documentElement.dataset.theme, "dark");
  p.media.matches = false;
  p.listeners.media();
  assert.equal(p.document.documentElement.dataset.theme, "light");
});

test("explicit choice is persistent and overrides the system", () => {
  const p = page("light", true);
  assert.equal(p.document.documentElement.dataset.theme, "light");
  p.window.GAWorldTheme.set("dark");
  assert.equal(p.storage.get("gaworld.theme"), "dark");
  assert.equal(p.document.documentElement.style.colorScheme, "dark");
});

test("storage events synchronize independent pages and console frames", () => {
  const p = page("light");
  p.storage.set("gaworld.theme", "dark");
  p.listeners.storage({ key: "gaworld.theme" });
  assert.equal(p.document.documentElement.dataset.theme, "dark");
  p.storage.clear();
  p.listeners.storage({ key: null });
  assert.equal(p.window.GAWorldTheme.get(), "system");
});

test("blocked storage and invalid settings do not break startup", () => {
  const p = page("invalid", false, true);
  p.window.GAWorldTheme.set("dark");
  assert.equal(p.document.documentElement.dataset.theme, "dark");
  p.window.GAWorldTheme.set("invalid");
  assert.equal(p.window.GAWorldTheme.get(), "system");
});
