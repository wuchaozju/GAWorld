# Twin Mobile PWA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The phone client — redeem an invite code, report location and activity with one tap, see the bound agent's avatar and state, and watch the day's trail animate. Works offline by queueing reports until signal returns.

**Architecture:** Pure logic lives in a UMD-wrapped `core.js` testable under `node:test` with no DOM; `app.js` does DOM wiring, Geolocation, and IndexedDB. Matches the existing `collaboration-core.js` / `collaboration-core.test.js` split. Served by `twin_server.py`, which already routes `/`, `/m`, and `/m/` to `site/mobile/index.html`.

**Tech Stack:** Vanilla JS (no framework, no build step), SVG avatar from the API, one `<canvas>` for the trail, IndexedDB for the offline queue, `node:test` for tests. No new dependencies. Deliberately no Phaser — see below.

**Source spec:** `docs/superpowers/specs/2026-08-08-mobile-digital-twin-design.md` §6, §7

**Depends on:** Plan 1 (server endpoints). Plan 2 is not required — the PWA talks only to the HTTP API.

---

## Why No Phaser

`site/simviz/` has a Phaser 3 replay viewer, and reusing it would look like the DRY choice. It is not: that viewer is built for desktop pointer interaction, and its vendored engine is poor value over mobile data and battery for what is a polyline and a moving dot. Spec §6 records this decision. One `<canvas>` and ~40 lines of drawing code cover it.

"Animation" here is two separate things, and conflating them is the main design risk:

- **State animation** — the avatar's CSS posture, switching with `action_tag`.
- **Temporal animation** — the trail replaying along the day's timeline on the canvas.

---

## File Structure

| File | Responsibility |
|---|---|
| `site/mobile/core.js` | Pure logic: report construction, offline queue, trail projection, sync labels. No DOM, no fetch. |
| `site/mobile/core.test.js` | `node:test` coverage of the above |
| `site/mobile/index.html` | Shell: avatar card, tag grid, trail canvas |
| `site/mobile/styles.css` | Mobile-first layout and the avatar state keyframes |
| `site/mobile/app.js` | DOM wiring, Geolocation, IndexedDB, fetch, polling |
| `site/mobile/manifest.webmanifest` | Installability |
| `site/mobile/sw.js` | App-shell cache so the page opens without signal |

Everything testable is in `core.js`. `app.js` is deliberately thin glue — browser APIs that a headless test cannot meaningfully exercise.

---

## Task 1: Core logic

**Files:**
- Create: `site/mobile/core.js`
- Test: `site/mobile/core.test.js`

- [ ] **Step 1: Write the failing test**

Create `site/mobile/core.test.js`:

```javascript
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("./core.js");


test("buildReport assembles the server's expected shape", () => {
  const report = core.buildReport({
    reportId: "abc",
    ts: 1000,
    tzOffset: 480,
    coords: {latitude: 30.27, longitude: 120.15, accuracy: 12},
    tag: "work",
    note: "  加班  ",
  });
  assert.equal(report.report_id, "abc");
  assert.equal(report.ts, 1000);
  assert.equal(report.tz_offset, 480);
  assert.equal(report.loc.lat, 30.27);
  assert.equal(report.loc.lng, 120.15);
  assert.equal(report.loc.acc_m, 12);
  assert.equal(report.loc.source, "gps");
  assert.equal(report.action_tag, "work");
  assert.equal(report.note, "加班");
});


test("buildReport marks manual fixes so the server can tell them apart", () => {
  const report = core.buildReport({
    reportId: "abc", ts: 1000, tzOffset: 0,
    coords: {latitude: 1, longitude: 2, accuracy: null},
    tag: "rest", note: "", manual: true,
  });
  assert.equal(report.loc.source, "manual");
  assert.equal(report.loc.acc_m, 0);
});


test("buildReport falls back to the other tag for an unknown one", () => {
  const report = core.buildReport({
    reportId: "a", ts: 1, tzOffset: 0,
    coords: {latitude: 1, longitude: 2, accuracy: 1},
    tag: "nonsense", note: "",
  });
  assert.equal(report.action_tag, "other");
});


test("queue drops reports the server has accepted, keeping the rest", () => {
  const queue = [{report_id: "a"}, {report_id: "b"}, {report_id: "c"}];
  assert.deepEqual(core.dropSynced(queue, ["a", "c"]), [{report_id: "b"}]);
});


test("queue is unchanged when nothing synced", () => {
  const queue = [{report_id: "a"}];
  assert.deepEqual(core.dropSynced(queue, []), [{report_id: "a"}]);
});


test("trailBounds covers every point with a non-zero span", () => {
  const bounds = core.trailBounds([
    {grid: {x: 0, y: 0}},
    {grid: {x: 4, y: 2}},
  ]);
  assert.equal(bounds.minX, 0);
  assert.equal(bounds.maxX, 4);
  assert.equal(bounds.minY, 0);
  assert.equal(bounds.maxY, 2);
});


test("trailBounds pads a single point so projection cannot divide by zero", () => {
  const bounds = core.trailBounds([{grid: {x: 3, y: 3}}]);
  assert.ok(bounds.maxX > bounds.minX);
  assert.ok(bounds.maxY > bounds.minY);
});


test("trailBounds on no points returns a usable unit box", () => {
  const bounds = core.trailBounds([]);
  assert.ok(bounds.maxX > bounds.minX);
  assert.ok(bounds.maxY > bounds.minY);
});


test("projectPoint maps grid coordinates into canvas pixels", () => {
  const bounds = {minX: 0, maxX: 10, minY: 0, maxY: 10};
  const mid = core.projectPoint({grid: {x: 5, y: 5}}, bounds, 100, 100, 0);
  assert.equal(mid.x, 50);
  assert.equal(mid.y, 50);
});


test("projectPoint flips the y axis so north is up", () => {
  const bounds = {minX: 0, maxX: 10, minY: 0, maxY: 10};
  const low = core.projectPoint({grid: {x: 0, y: 0}}, bounds, 100, 100, 0);
  const high = core.projectPoint({grid: {x: 0, y: 10}}, bounds, 100, 100, 0);
  assert.ok(high.y < low.y);
});


test("projectPoint honours padding", () => {
  const bounds = {minX: 0, maxX: 10, minY: 0, maxY: 10};
  const corner = core.projectPoint({grid: {x: 0, y: 0}}, bounds, 100, 100, 10);
  assert.equal(corner.x, 10);
});


test("visiblePoints returns the prefix up to a timestamp", () => {
  const points = [{ts: 1}, {ts: 2}, {ts: 3}];
  assert.deepEqual(core.visiblePoints(points, 2), [{ts: 1}, {ts: 2}]);
});


test("visiblePoints on an empty trail is empty", () => {
  assert.deepEqual(core.visiblePoints([], 5), []);
});


test("syncLabel reports synced state when the server says fresh", () => {
  assert.equal(core.syncLabel({fresh: true, report: {ts: 100}}, 160), "已同步");
});


test("syncLabel reports not-synced rather than showing a stale position", () => {
  assert.equal(core.syncLabel({fresh: false, report: {ts: 100}}, 99999), "未同步");
});


test("syncLabel handles an agent that has never reported", () => {
  assert.equal(core.syncLabel({fresh: false, report: null}, 100), "尚无上报");
});


test("outOfMapNotice appears only for an out-of-map report", () => {
  assert.ok(core.outOfMapNotice({out_of_map: true}));
  assert.equal(core.outOfMapNotice({out_of_map: false}), "");
  assert.equal(core.outOfMapNotice(null), "");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node site/mobile/core.test.js`

Expected: FAIL — `Cannot find module './core.js'`

- [ ] **Step 3: Write the implementation**

Create `site/mobile/core.js`:

```javascript
/* Pure logic for the twin mobile client.
 *
 * No DOM, no fetch, no browser APIs — everything here is testable under
 * `node site/mobile/core.test.js`. Browser-only concerns (Geolocation,
 * IndexedDB, rendering) live in app.js, which is deliberately thin.
 *
 * Mirrors the collaboration-core.js convention: UMD wrapper exporting to both
 * CommonJS and the window global.
 */
(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.GAWorldTwinCore = api;
  }
}(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  /* Must stay in step with ACTION_TAGS in gaworld/twin/backend.py. The server
   * re-validates, so a drift here degrades to "other" rather than corrupting
   * data. */
  const ACTION_TAGS = [
    "commute", "work", "study", "meal", "shopping",
    "rest", "social", "exercise", "errand", "other",
  ];

  const TAG_LABELS = {
    commute: "通勤",
    work: "工作",
    study: "学习",
    meal: "吃饭",
    shopping: "购物",
    rest: "休息",
    social: "社交",
    exercise: "运动",
    errand: "办事",
    other: "其他",
  };

  function buildReport(options) {
    const opts = options || {};
    const coords = opts.coords || {};
    const tag = ACTION_TAGS.includes(opts.tag) ? opts.tag : "other";
    return {
      report_id: String(opts.reportId || ""),
      ts: Number(opts.ts || 0),
      tz_offset: Number(opts.tzOffset || 0),
      loc: {
        lat: Number(coords.latitude || 0),
        lng: Number(coords.longitude || 0),
        acc_m: Number(coords.accuracy || 0),
        source: opts.manual ? "manual" : "gps",
      },
      action_tag: tag,
      note: String(opts.note || "").trim(),
    };
  }

  /* Remove reports the server confirmed, keeping anything still unsent.
   * Called after a queue flush; the server is idempotent on report_id, so a
   * report that syncs twice is harmless — one that is dropped early is not. */
  function dropSynced(queue, syncedIds) {
    const synced = new Set(syncedIds || []);
    return (queue || []).filter(function (item) {
      return !synced.has(item.report_id);
    });
  }

  function trailBounds(points) {
    const list = (points || []).filter(function (p) {
      return p && p.grid && typeof p.grid.x === "number";
    });
    if (!list.length) {
      return {minX: 0, maxX: 1, minY: 0, maxY: 1};
    }
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    list.forEach(function (p) {
      minX = Math.min(minX, p.grid.x);
      maxX = Math.max(maxX, p.grid.x);
      minY = Math.min(minY, p.grid.y);
      maxY = Math.max(maxY, p.grid.y);
    });
    /* A single point (or a perfectly straight line) would give a zero span and
     * make projectPoint divide by zero. Pad it into a real box. */
    if (maxX - minX < 1e-6) { minX -= 0.5; maxX += 0.5; }
    if (maxY - minY < 1e-6) { minY -= 0.5; maxY += 0.5; }
    return {minX: minX, maxX: maxX, minY: minY, maxY: maxY};
  }

  function projectPoint(point, bounds, width, height, padding) {
    const pad = Number(padding || 0);
    const innerW = Math.max(1, width - pad * 2);
    const innerH = Math.max(1, height - pad * 2);
    const spanX = bounds.maxX - bounds.minX;
    const spanY = bounds.maxY - bounds.minY;
    const fx = (point.grid.x - bounds.minX) / spanX;
    const fy = (point.grid.y - bounds.minY) / spanY;
    return {
      x: pad + fx * innerW,
      /* Canvas y grows downward; map grid y grows north. Flip so the drawing
       * matches the world. */
      y: pad + (1 - fy) * innerH,
    };
  }

  function visiblePoints(points, uptoTs) {
    return (points || []).filter(function (p) {
      return Number(p.ts) <= Number(uptoTs);
    });
  }

  function syncLabel(snapshot, nowTs) {
    const snap = snapshot || {};
    if (!snap.report) {
      return "尚无上报";
    }
    return snap.fresh ? "已同步" : "未同步";
  }

  function outOfMapNotice(report) {
    if (report && report.out_of_map) {
      return "当前位置在地图覆盖范围之外，位置不会同步到智能体";
    }
    return "";
  }

  return {
    ACTION_TAGS: ACTION_TAGS,
    TAG_LABELS: TAG_LABELS,
    buildReport: buildReport,
    dropSynced: dropSynced,
    trailBounds: trailBounds,
    projectPoint: projectPoint,
    visiblePoints: visiblePoints,
    syncLabel: syncLabel,
    outOfMapNotice: outOfMapNotice,
  };
}));
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node site/mobile/core.test.js`

Expected: `# pass 17`, `# fail 0`

- [ ] **Step 5: Commit**

```bash
git add site/mobile/core.js site/mobile/core.test.js
git commit -m "feat(twin): mobile client core logic with offline queue and trail projection"
```

---

## Task 2: Shell and styles

**Files:**
- Create: `site/mobile/index.html`
- Create: `site/mobile/styles.css`

- [ ] **Step 1: Create the HTML shell**

Create `site/mobile/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <meta name="theme-color" content="#11151c" />
  <title>GAWorld · 我的孪生</title>
  <link rel="manifest" href="manifest.webmanifest" />
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <main id="app">
    <!-- Gate: shown until a token exists in localStorage. -->
    <section id="authGate" class="card" hidden>
      <h1>连接到 GAWorld</h1>
      <p class="muted">输入邀请码，把这台手机绑定到你的智能体。</p>
      <input id="codeInput" type="text" inputmode="text" autocomplete="off"
             placeholder="邀请码" aria-label="邀请码" />
      <button id="codeSubmit" type="button">连接</button>
      <p id="authError" class="error" role="alert"></p>
    </section>

    <section id="main" hidden>
      <header class="card avatar-card">
        <div id="avatar" class="avatar" aria-label="智能体形象"></div>
        <div class="avatar-meta">
          <h1 id="agentLabel">—</h1>
          <p><span id="syncState" class="badge">—</span></p>
          <p id="currentState" class="muted">—</p>
        </div>
      </header>

      <p id="notice" class="notice" role="status" hidden></p>

      <section class="card">
        <h2>你在做什么？</h2>
        <div id="tagGrid" class="tag-grid"></div>
        <input id="noteInput" type="text" placeholder="备注（可选）" aria-label="备注" />
        <button id="reportButton" type="button" class="primary">上报</button>
        <p id="queueState" class="muted"></p>
      </section>

      <section class="card">
        <h2>今日轨迹</h2>
        <canvas id="trail" width="600" height="400" aria-label="今日轨迹"></canvas>
        <button id="replayButton" type="button">回放</button>
      </section>
    </section>
  </main>

  <script src="core.js"></script>
  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create the styles**

Create `site/mobile/styles.css`:

```css
/* Mobile-first. Colour variables mirror site/simviz/index.html so the twin
   client reads as part of the same product. */
:root {
  --bg: #11151c;
  --panel: #1a2029;
  --panel2: #222a35;
  --ink: #e7ecf3;
  --muted: #97a3b4;
  --line: #2c3644;
  --accent: #6ea8fe;
  --accent2: #5cc2a8;
  --warn: #e0a458;
  --err: #e06c75;
}

* { box-sizing: border-box; }

html, body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 15px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI",
        "PingFang SC", "Microsoft YaHei", sans-serif;
}

#app {
  max-width: 560px;
  margin: 0 auto;
  padding: max(12px, env(safe-area-inset-top)) 12px
           max(12px, env(safe-area-inset-bottom));
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 14px;
}

h1 { font-size: 18px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 0 0 10px; color: var(--muted); font-weight: 600; }
.muted { color: var(--muted); font-size: 13px; margin: 4px 0 0; }
.error { color: var(--err); font-size: 13px; min-height: 18px; margin: 8px 0 0; }

.notice {
  background: rgba(224, 164, 88, 0.12);
  border: 1px solid var(--warn);
  color: var(--warn);
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 13px;
  margin: 0;
}

.avatar-card { display: flex; gap: 14px; align-items: center; }
.avatar { width: 84px; height: 84px; flex: none; }
.avatar svg { width: 100%; height: 100%; display: block; }
.avatar-meta { min-width: 0; }

/* State animation: the avatar's posture tracks the reported activity.
   Distinct from the trail's temporal animation on the canvas. */
.avatar[data-state="commute"] svg,
.avatar[data-state="exercise"] svg { animation: bob 0.9s ease-in-out infinite; }
.avatar[data-state="work"] svg,
.avatar[data-state="study"] svg { animation: lean 3.4s ease-in-out infinite; }
.avatar[data-state="rest"] svg { animation: breathe 4.2s ease-in-out infinite; }

@keyframes bob {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-4px); }
}
@keyframes lean {
  0%, 100% { transform: rotate(0deg); }
  50% { transform: rotate(-2deg); }
}
@keyframes breathe {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.03); }
}

/* Respect users who ask the OS to reduce motion. */
@media (prefers-reduced-motion: reduce) {
  .avatar svg { animation: none !important; }
}

.badge {
  display: inline-block;
  background: var(--panel2);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
  color: var(--muted);
}
.badge[data-sync="已同步"] { color: var(--accent2); border-color: var(--accent2); }
.badge[data-sync="未同步"] { color: var(--warn); border-color: var(--warn); }

.tag-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(88px, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}

.tag-grid button {
  background: var(--panel2);
  border: 1px solid var(--line);
  color: var(--ink);
  border-radius: 10px;
  /* Comfortably above the 44px touch-target minimum. */
  padding: 14px 6px;
  font: inherit;
  font-size: 14px;
  cursor: pointer;
}
.tag-grid button[aria-pressed="true"] {
  background: var(--accent);
  border-color: var(--accent);
  color: #0b1018;
  font-weight: 600;
}

input[type="text"] {
  width: 100%;
  background: var(--panel2);
  border: 1px solid var(--line);
  color: var(--ink);
  border-radius: 10px;
  padding: 12px;
  font: inherit;
  margin-bottom: 10px;
}

button {
  background: var(--panel2);
  border: 1px solid var(--line);
  color: var(--ink);
  border-radius: 10px;
  padding: 12px 16px;
  font: inherit;
  cursor: pointer;
}
button.primary {
  width: 100%;
  background: var(--accent);
  border-color: var(--accent);
  color: #0b1018;
  font-weight: 600;
}
button:disabled { opacity: 0.55; }

canvas {
  width: 100%;
  height: auto;
  background: #0c0f14;
  border: 1px solid var(--line);
  border-radius: 10px;
  display: block;
  margin-bottom: 10px;
}
```

- [ ] **Step 3: Verify the HTML parses and references only files that will exist**

```bash
python3 - <<'PY'
import re, pathlib
html = pathlib.Path("site/mobile/index.html").read_text(encoding="utf-8")
refs = re.findall(r'(?:src|href)="([^"]+)"', html)
print("referenced:", refs)
ids = re.findall(r'id="([^"]+)"', html)
for required in ["authGate", "codeInput", "codeSubmit", "authError", "main",
                 "avatar", "agentLabel", "syncState", "currentState", "notice",
                 "tagGrid", "noteInput", "reportButton", "queueState",
                 "trail", "replayButton"]:
    assert required in ids, f"missing id: {required}"
print("all required ids present")
PY
```

Expected: the referenced list, then `all required ids present`.

- [ ] **Step 4: Commit**

```bash
git add site/mobile/index.html site/mobile/styles.css
git commit -m "feat(twin): mobile client shell and avatar state animations"
```

---

## Task 3: App wiring

**Files:**
- Create: `site/mobile/app.js`

- [ ] **Step 1: Write the implementation**

Create `site/mobile/app.js`:

```javascript
/* DOM wiring for the twin mobile client.
 *
 * Deliberately thin: everything worth testing lives in core.js. This file
 * holds only the browser-API glue a headless test cannot meaningfully drive —
 * Geolocation, IndexedDB, fetch, canvas, and event listeners.
 */
(function () {
  "use strict";

  const core = window.GAWorldTwinCore;
  const TOKEN_KEY = "gaworld.twin.token";
  const DB_NAME = "gaworld-twin";
  const STORE = "queue";
  const POLL_MS = 30000;

  let token = localStorage.getItem(TOKEN_KEY) || "";
  let selectedTag = "work";
  let trailPoints = [];

  const el = function (id) { return document.getElementById(id); };

  /* -- offline queue (IndexedDB) ------------------------------------- */

  function openDb() {
    return new Promise(function (resolve, reject) {
      const request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = function () {
        request.result.createObjectStore(STORE, {keyPath: "report_id"});
      };
      request.onsuccess = function () { resolve(request.result); };
      request.onerror = function () { reject(request.error); };
    });
  }

  function queueTx(mode, fn) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        const tx = db.transaction(STORE, mode);
        const result = fn(tx.objectStore(STORE));
        tx.oncomplete = function () { resolve(result && result.result); };
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }

  function enqueue(report) {
    return queueTx("readwrite", function (store) { return store.put(report); });
  }

  function readQueue() {
    return queueTx("readonly", function (store) { return store.getAll(); })
      .then(function (rows) { return rows || []; });
  }

  function removeSynced(ids) {
    return queueTx("readwrite", function (store) {
      ids.forEach(function (id) { store.delete(id); });
      return null;
    });
  }

  /* -- API ----------------------------------------------------------- */

  function api(path, options) {
    const opts = options || {};
    const headers = {"Content-Type": "application/json"};
    if (token) { headers.Authorization = "Bearer " + token; }
    return fetch(path, {
      method: opts.method || "GET",
      headers: headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    }).then(function (response) {
      return response.json().then(function (data) {
        return {status: response.status, data: data};
      });
    });
  }

  /* -- rendering ------------------------------------------------------ */

  function renderTagGrid() {
    const grid = el("tagGrid");
    grid.innerHTML = "";
    core.ACTION_TAGS.forEach(function (tag) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = core.TAG_LABELS[tag] || tag;
      button.setAttribute("aria-pressed", String(tag === selectedTag));
      button.addEventListener("click", function () {
        selectedTag = tag;
        renderTagGrid();
      });
      grid.appendChild(button);
    });
  }

  function renderSnapshot(snapshot) {
    const nowTs = Date.now() / 1000;
    const label = core.syncLabel(snapshot, nowTs);
    const badge = el("syncState");
    badge.textContent = label;
    badge.setAttribute("data-sync", label);

    const report = snapshot.report;
    el("avatar").setAttribute("data-state", report ? report.action_tag : "rest");
    el("currentState").textContent = report
      ? (core.TAG_LABELS[report.action_tag] || report.action_tag)
        + " · " + (report.node_id || "地图之外")
      : "还没有上报过";

    const notice = core.outOfMapNotice(report);
    el("notice").textContent = notice;
    el("notice").hidden = !notice;
  }

  function drawTrail(points) {
    const canvas = el("trail");
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    if (!points.length) {
      ctx.fillStyle = "#97a3b4";
      ctx.font = "16px sans-serif";
      ctx.fillText("今日还没有轨迹", 20, 30);
      return;
    }
    const bounds = core.trailBounds(trailPoints.length ? trailPoints : points);
    const projected = points.map(function (p) {
      return core.projectPoint(p, bounds, w, h, 24);
    });

    ctx.strokeStyle = "#6ea8fe";
    ctx.lineWidth = 2;
    ctx.beginPath();
    projected.forEach(function (pt, i) {
      if (i === 0) { ctx.moveTo(pt.x, pt.y); } else { ctx.lineTo(pt.x, pt.y); }
    });
    ctx.stroke();

    projected.forEach(function (pt, i) {
      const last = i === projected.length - 1;
      ctx.beginPath();
      ctx.fillStyle = last ? "#5cc2a8" : "#2c3644";
      ctx.arc(pt.x, pt.y, last ? 7 : 4, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  /* Temporal animation: replay the day's points along their own timeline. */
  function replayTrail() {
    if (trailPoints.length < 2) { drawTrail(trailPoints); return; }
    let index = 1;
    const timer = setInterval(function () {
      drawTrail(trailPoints.slice(0, index));
      index += 1;
      if (index > trailPoints.length) { clearInterval(timer); }
    }, 240);
  }

  /* -- flows ---------------------------------------------------------- */

  function refresh() {
    if (!token) { return Promise.resolve(); }
    return Promise.all([api("/api/twin/snapshot"), api("/api/twin/trail")])
      .then(function (results) {
        const snapshot = results[0];
        const trail = results[1];
        if (snapshot.status === 401 || trail.status === 401) {
          return signOut();
        }
        renderSnapshot(snapshot.data);
        trailPoints = (trail.data.points || []).filter(function (p) {
          return p.grid && !p.out_of_map;
        });
        drawTrail(trailPoints);
      })
      .catch(function () {
        /* Offline: keep the last render rather than blanking the screen. */
        el("syncState").textContent = "离线";
      });
  }

  function flushQueue() {
    return readQueue().then(function (queue) {
      if (!queue.length) {
        el("queueState").textContent = "";
        return null;
      }
      el("queueState").textContent = "待上传 " + queue.length + " 条";
      return api("/api/twin/report", {method: "POST", body: queue})
        .then(function (result) {
          if (result.status !== 200) { return null; }
          /* The server is idempotent on report_id, so everything we just sent
           * is now durable regardless of accepted-vs-duplicate. */
          const ids = queue.map(function (r) { return r.report_id; });
          return removeSynced(ids).then(function () {
            el("queueState").textContent = "";
            return refresh();
          });
        })
        .catch(function () {
          el("queueState").textContent = "待上传 " + queue.length + " 条（离线）";
        });
    });
  }

  function currentPosition() {
    return new Promise(function (resolve) {
      if (!navigator.geolocation) { return resolve(null); }
      navigator.geolocation.getCurrentPosition(
        function (position) { resolve(position.coords); },
        function () { resolve(null); },
        {enableHighAccuracy: true, timeout: 10000, maximumAge: 60000}
      );
    });
  }

  function submitReport() {
    const button = el("reportButton");
    button.disabled = true;
    return currentPosition().then(function (coords) {
      if (!coords) {
        /* Permission denied or unavailable: the spec requires the feature to
         * keep working, so fall back to a manual fix at the last known node
         * rather than dropping the activity report. */
        el("notice").textContent = "无法获取定位，本次仅上报行为";
        el("notice").hidden = false;
        coords = {latitude: 0, longitude: 0, accuracy: 0};
      }
      const report = core.buildReport({
        reportId: (crypto.randomUUID && crypto.randomUUID())
          || String(Date.now()) + Math.random().toString(16).slice(2),
        ts: Math.floor(Date.now() / 1000),
        tzOffset: -new Date().getTimezoneOffset(),
        coords: coords,
        tag: selectedTag,
        note: el("noteInput").value,
        manual: !coords.accuracy,
      });
      return enqueue(report)
        .then(flushQueue)
        .then(function () { el("noteInput").value = ""; });
    }).finally(function () {
      button.disabled = false;
    });
  }

  function signOut() {
    token = "";
    localStorage.removeItem(TOKEN_KEY);
    el("main").hidden = true;
    el("authGate").hidden = false;
  }

  function signIn() {
    const code = el("codeInput").value.trim();
    if (!code) { return; }
    el("authError").textContent = "";
    api("/api/twin/auth", {method: "POST", body: {code: code}})
      .then(function (result) {
        if (result.status !== 200 || !result.data.token) {
          el("authError").textContent = "邀请码无效或已撤销";
          return;
        }
        token = result.data.token;
        localStorage.setItem(TOKEN_KEY, token);
        start();
      })
      .catch(function () {
        el("authError").textContent = "无法连接服务器";
      });
  }

  function start() {
    el("authGate").hidden = true;
    el("main").hidden = false;
    renderTagGrid();
    api("/api/twin/profile").then(function (result) {
      if (result.status === 401) { return signOut(); }
      el("avatar").innerHTML = result.data.avatar_svg || "";
      el("agentLabel").textContent = result.data.label
        || ("Agent " + result.data.agent_id);
    });
    refresh();
    flushQueue();
    setInterval(function () { refresh(); flushQueue(); }, POLL_MS);
  }

  function init() {
    el("codeSubmit").addEventListener("click", signIn);
    el("reportButton").addEventListener("click", submitReport);
    el("replayButton").addEventListener("click", replayTrail);
    window.addEventListener("online", flushQueue);

    if (token) { start(); } else { el("authGate").hidden = false; }

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("sw.js").catch(function () {});
    }
  }

  document.addEventListener("DOMContentLoaded", init);
}());
```

- [ ] **Step 2: Syntax-check the file**

```bash
node --check site/mobile/app.js && echo "app.js parses"
```

Expected: `app.js parses`

- [ ] **Step 3: Confirm every id app.js touches exists in the HTML**

```bash
python3 - <<'PY'
import re, pathlib
app = pathlib.Path("site/mobile/app.js").read_text(encoding="utf-8")
html = pathlib.Path("site/mobile/index.html").read_text(encoding="utf-8")
used = set(re.findall(r'el\("([^"]+)"\)', app))
present = set(re.findall(r'id="([^"]+)"', html))
missing = sorted(used - present)
assert not missing, f"app.js references ids not in the HTML: {missing}"
print(f"all {len(used)} referenced ids exist")
PY
```

Expected: `all 13 referenced ids exist`

This check matters because a typo'd id fails silently at runtime — `getElementById` returns null and the listener never binds.

- [ ] **Step 4: Commit**

```bash
git add site/mobile/app.js
git commit -m "feat(twin): mobile client wiring for reporting, sync, and trail replay"
```

---

## Task 4: Manifest, service worker, and end-to-end verification

**Files:**
- Create: `site/mobile/manifest.webmanifest`
- Create: `site/mobile/sw.js`

- [ ] **Step 1: Create the manifest**

Create `site/mobile/manifest.webmanifest`:

```json
{
  "name": "GAWorld 数字孪生",
  "short_name": "GAWorld",
  "start_url": ".",
  "scope": ".",
  "display": "standalone",
  "background_color": "#11151c",
  "theme_color": "#11151c",
  "lang": "zh-CN",
  "icons": []
}
```

`icons` is intentionally empty: an installable icon is a design asset this plan does not have, and shipping a placeholder would be worse than shipping none. Browsers fall back to a screenshot of the page.

- [ ] **Step 2: Create the service worker**

Create `site/mobile/sw.js`:

```javascript
/* App-shell cache so the client opens without signal.
 *
 * Without this, losing signal means the page will not load at all and the
 * IndexedDB offline queue never gets a chance to work — the queue only helps
 * if the app can start.
 *
 * Bump CACHE_NAME on every shell change. A stale cached bundle is the classic
 * service-worker failure, so the shell list is kept short and explicit rather
 * than pattern-matched.
 */
const CACHE_NAME = "gaworld-twin-v1";
const SHELL = [
  "./",
  "./index.html",
  "./styles.css",
  "./core.js",
  "./app.js",
  "./manifest.webmanifest",
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) { return cache.addAll(SHELL); })
  );
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(names.map(function (name) {
        return name === CACHE_NAME ? null : caches.delete(name);
      }));
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", function (event) {
  const url = new URL(event.request.url);
  /* API calls must never be served from cache: a cached snapshot would show a
   * stale position as if it were current, which is exactly what the spec's
   * "not synced" state exists to prevent. */
  if (url.pathname.startsWith("/api/")) {
    return;
  }
  event.respondWith(
    caches.match(event.request).then(function (hit) {
      return hit || fetch(event.request);
    })
  );
});
```

- [ ] **Step 3: Syntax-check both**

```bash
node --check site/mobile/sw.js && python3 -c "import json; json.load(open('site/mobile/manifest.webmanifest')); print('manifest is valid JSON')"
```

Expected: `manifest is valid JSON`

- [ ] **Step 4: Verify the server actually serves the client**

Start the server:

```bash
python3 -m gaworld.apps.twin_server --port 8767
```

In another terminal, confirm every shell file is reachable and that the root route resolves to the client:

```bash
for path in / /m /index.html /core.js /app.js /styles.css /manifest.webmanifest /sw.js; do
  printf '%s -> ' "$path"
  curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:8767/site/mobile${path#/}" 2>/dev/null || true
done
curl -s -o /dev/null -w 'root / -> %{http_code}\n' http://127.0.0.1:8767/
curl -s http://127.0.0.1:8767/ | grep -q 'GAWorld · 我的孪生' && echo "root serves the mobile client"
```

Expected: `root / -> 200` and `root serves the mobile client`.

- [ ] **Step 5: Confirm the API is still protected**

```bash
curl -s -o /dev/null -w 'unauth snapshot -> %{http_code}\n' http://127.0.0.1:8767/api/twin/snapshot
curl -s -o /dev/null -w 'POST /api/config -> %{http_code}\n' -X POST http://127.0.0.1:8767/api/config -d '{}'
```

Expected: `401` and `404`. Serving static files must not have opened any API surface.

- [ ] **Step 6: Stop the server**

Press Ctrl+C in the server terminal.

- [ ] **Step 7: Run every test**

```bash
node site/mobile/core.test.js && python3 -m pytest tests/test_twin_*.py -q
```

Expected: `# pass 17` from node, then `62 passed` from pytest.

- [ ] **Step 8: Commit**

```bash
git add site/mobile/manifest.webmanifest site/mobile/sw.js
git commit -m "feat(twin): mobile client manifest and app-shell service worker"
```

---

## Done When

- `node site/mobile/core.test.js` passes 17 tests.
- `python3 -m pytest tests/test_twin_*.py -q` still passes 62.
- `curl http://127.0.0.1:8767/` returns the mobile client.
- Unauthenticated `/api/twin/snapshot` still returns 401 and `/api/config` still returns 404.
- `node --check` passes on `app.js` and `sw.js`.

## Known Limitations

Stated rather than hidden, because each is a real gap someone will otherwise discover the hard way:

1. **Untested on a real phone.** Everything here is verified headlessly. Geolocation permission prompts, iOS Safari's IndexedDB behaviour in standalone mode, and the install flow need a physical device over HTTPS. Do that before relying on it for data collection.
2. **No HTTPS in the local verification.** Geolocation will not run on `http://` from a phone. The Cloudflare Tunnel from spec §4.1 is required for any real use; `curl` over localhost cannot exercise that path.
3. **The "no GPS" fallback sends zero coordinates.** These land far outside Hangzhou, so the server flags them `out_of_map` and the mirror channel skips the position — the activity still records. This is the honest behaviour, but the spec's richer "manual point selection" is not built.
4. **`icons` in the manifest is empty**, so the installed app has no custom icon.
5. **Service-worker cache invalidation is manual.** Editing any shell file requires bumping `CACHE_NAME`, or returning users keep the old bundle.
