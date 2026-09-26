/* Unit tests for the home-mode panel renderer (home.js).
 *
 *   node site/dashboard/home.test.js
 *
 * Plain node, no framework, no browser — exercises the pure DOM helpers
 * (el, renderHomePanel) the way the survey-charts.test.js convention does.
 * The DOM is mocked just enough to satisfy the renderer; we don't need a
 * full document, just createElement + a fake root.
 */
"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

// Minimal DOM mock. Just enough surface for the renderer to build a tree and
// walk it; the assertions don't care about pixel layout, only structure.
class FakeClassList {
  constructor() { this.set = new Set(); }
  add(c) { this.set.add(c); }
  remove(c) { this.set.delete(c); }
  contains(c) { return this.set.has(c); }
}

let lastAttrs = null;

function makeNode(tag) {
  const node = {
    tag,
    children: [],
    attrs: {},
    textContent: "",
    classList: new FakeClassList(),
    className: "",
    setAttribute(k, v) { this.attrs[k] = v; },
    appendChild(child) {
      if (child == null) return child;
      if (typeof child === "string") {
        const wrapper = { text, children: [], classList: new FakeClassList() };
        this.children.push(wrapper);
        return wrapper;
      }
      this.children.push(child);
      return child;
    },
    querySelector(sel) {
      const m = sel.match(/\.home-room\[data-room="([^"]+)"\]/);
      if (!m) return null;
      const target = m[1];
      const stack = [...this.children];
      while (stack.length) {
        const n = stack.shift();
        if (n.attrs && n.attrs["data-room"] === target) return n;
        if (n.children) stack.push(...n.children);
      }
      return null;
    },
    get innerHTML() { return ""; },
    set innerHTML(_v) {
      this.children = [];
    },
  };
  // Mirror className writes into the classList so assertions can use either.
  Object.defineProperty(node, "className", {
    get() { return Array.from(node.classList.set).join(" "); },
    set(v) {
      node.classList.set.clear();
      String(v || "").split(/\s+/).filter(Boolean).forEach((c) => node.classList.set.add(c));
    },
  });
  return node;
}

const fakeDoc = {
  createElement(tag) { return makeNode(tag); },
  createTextNode(text) { return { text, children: [], classList: new FakeClassList() }; },
};

// Load the source as a script — it writes `window.HomePanel` on execution.
const code = fs.readFileSync(__dirname + "/home.js", "utf8");
const sandbox = { window: {}, document: fakeDoc, console };
sandbox.globalThis = sandbox.window;
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const HomePanel = sandbox.window.HomePanel;
assert.ok(HomePanel, "HomePanel not exported");
assert.strictEqual(typeof HomePanel.render, "function");
assert.strictEqual(typeof HomePanel.highlightCurrentRoom, "function");

let passed = 0;

function test(name, fn) {
  try {
    fn();
    passed += 1;
  } catch (err) {
    console.error("FAIL: " + name);
    console.error(err && err.message ? err.message : err);
    process.exit(1);
  }
}

const PAYLOAD = {
  has_home: true,
  summary: { home_id: "agent_1", home_node: "Lakeview Tower", rooms: ["living_room", "kitchen"], room_count: 2, ambiance_quality: "comfortable", vibe: "warm" },
  design: {
    home_id: "agent_1",
    home_node: "Lakeview Tower",
    rooms: {
      living_room: { name: "客厅", size_sqm: 16, furniture: ["沙发", "茶几", "电视"] },
      kitchen: { name: "厨房", size_sqm: 8, furniture: ["灶台", "抽油烟机"] },
      bedroom: { name: "卧室", size_sqm: 12, furniture: ["床"] },
    },
    ambiance_quality: "comfortable",
    vibe: "采光不错，养了几盆绿植",
    at_home_activities: {
      living_room: ["看电视", "刷手机"],
      kitchen: ["做饭", "泡茶"],
      bedroom: ["睡觉", "敷面膜"],
    },
  },
  recent_observations: [
    { day: 1, time: "07:30", current_room: { key: "kitchen", name: "厨房" }, ambiance: { lighting: "晨光初起", sound: "厨房传来锅碗声" } },
    { day: 1, time: "12:00", current_room: { key: "living_room", name: "客厅" }, ambiance: { lighting: "自然光", sound: "电视/手机的低语" } },
    { day: 1, time: "18:30", current_room: { key: null }, ambiance: {} },  // out
  ],
};

function collect(root) {
  const out = [];
  const stack = [...root.children];
  while (stack.length) {
    const n = stack.shift();
    if (n.classList) out.push(n);
    if (n.children) stack.push(...n.children);
  }
  return out;
}

function render(payload) {
  const root = makeNode("div");
  HomePanel.render(payload, { root, t: (k) => k });
  return root;
}

test("renders empty state when payload is missing", () => {
  const root = render(null);
  assert.strictEqual(root.children.length, 1);
  const node = root.children[0];
  assert.ok(node.classList.contains("home-empty"));
});

test("renders empty state when has_home is false", () => {
  const root = render({ has_home: false });
  assert.ok(root.children[0].classList.contains("home-empty"));
});

test("renders four-cell summary, vibe, rooms, ambiance, observations", () => {
  const root = render(PAYLOAD);
  const nodes = collect(root);
  // Each section contributes one or more rows; just sanity-check the structure.
  const has = (cls) => nodes.some((n) => n.classList.contains(cls));
  assert.ok(has("home-summary-grid"), "summary grid missing");
  assert.ok(has("home-vibe"), "vibe missing");
  assert.ok(has("home-rooms"), "rooms container missing");
  assert.ok(has("home-ambiance"), "ambiance grid missing");
  assert.ok(has("home-observations"), "observations block missing");
});

test("summary cells carry the expected labels", () => {
  const root = render(PAYLOAD);
  const grid = collect(root).find((n) => n.classList.contains("home-summary-grid"));
  assert.strictEqual(grid.children.length, 4);
  const values = grid.children.map((c) => {
    const val = c.children.find((k) => k.classList && k.classList.contains("home-summary-value"));
    return val ? val.textContent : null;
  });
  assert.deepStrictEqual(values, ["3", "36 平米", "舒适", "3"]);
});

test("room cards carry the furniture string", () => {
  const root = render(PAYLOAD);
  const wrap = collect(root).find((n) => n.classList.contains("home-rooms"));
  const living = wrap.children.find((c) => c.attrs["data-room"] === "living_room");
  assert.ok(living, "living_room card missing");
  const furnitureLine = living.children.find((c) => c.classList && c.classList.contains("home-room-furniture"));
  assert.ok(furnitureLine.textContent.includes("沙发"));
  assert.ok(furnitureLine.textContent.includes("茶几"));
});

test("ambiance grid picks the latest at-home observation", () => {
  const root = render(PAYLOAD);
  const grid = collect(root).find((n) => n.classList.contains("home-ambiance"));
  // Latest at-home is the second row (living_room at 12:00, lighting=自然光).
  const labels = grid.children.map((c) => {
    const label = c.children.find((k) => k.classList && k.classList.contains("home-ambiance-label"));
    const value = c.children.find((k) => k.classList && k.classList.contains("home-ambiance-value"));
    return [label && label.textContent, value && value.textContent];
  });
  // The renderer's built-in FALLBACKS resolves the keys without a host t().
  assert.deepStrictEqual(labels[0], ["光线", "自然光"]);
  assert.deepStrictEqual(labels[1], ["声音", "电视/手机的低语"]);
});

test("observations list is rendered newest-first with out flag on the right row", () => {
  const root = render(PAYLOAD);
  const list = collect(root).find((n) => n.classList.contains("home-observations-list"));
  assert.strictEqual(list.children.length, 3);
  // PAYLOAD ends with the "out" observation. The renderer reverses the array,
  // so the "out" row becomes children[0] of the rendered list (the newest).
  const outRow = list.children[0];
  assert.ok(outRow.classList.contains("is-out"));
  // The first at-home observation (07:30, kitchen) ends up at the tail.
  const lastRow = list.children[2];
  assert.ok(!lastRow.classList.contains("is-out"));
});

test("highlightCurrentRoom flips the matching card's class", () => {
  const root = render(PAYLOAD);
  HomePanel.highlightCurrentRoom(root, "kitchen");
  const kitchen = root.querySelector('.home-room[data-room="kitchen"]');
  assert.ok(kitchen.classList.contains("is-current"));
  const living = root.querySelector('.home-room[data-room="living_room"]');
  assert.ok(!living.classList.contains("is-current"));
});

test("escapes the vibe text against HTML injection", () => {
  const malicious = {
    ...PAYLOAD,
    design: { ...PAYLOAD.design, vibe: '<script>alert(1)</script>' },
  };
  const root = render(malicious);
  // Renderer's textContent path neutralises the tag — the DOM node only
  // stores the literal string. Confirm the renderer did not expose a node
  // whose tag name is 'script'.
  const stack = [...root.children];
  while (stack.length) {
    const n = stack.shift();
    if (n.tag === "script") {
      throw new Error("vibe string was injected as a script node");
    }
    if (n.children) stack.push(...n.children);
  }
});

console.log("home.test.js: " + passed + " passed");