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
  const INTRO_KEY = "gaworld.twin.introSeen";
  const DB_NAME = "gaworld-twin";
  const STORE = "queue";
  const POLL_MS = 30000;

  const LAST_TAG_KEY = "gaworld.twin.lastTag";
  const AUTO_KEY = "gaworld.twin.autoSample";
  const AUTO_INTERVAL_MIN = 10;

  let token = localStorage.getItem(TOKEN_KEY) || "";
  let selectedTag = "work";
  let trailPoints = [];
  let lastAutoSampleTs = null;
  let pendingManualReport = null;

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
    const outside = points.filter(function (p) { return p.out_of_map; }).length;
    el("trailSummary").textContent = points.length
      ? points.length + " 个位置点" + (points.length === 1 ? "，尚未形成路线" : "")
        + (outside ? " · " + outside + " 个在仿真地图外" : "")
      : "尚无有效位置记录";
    el("replayButton").disabled = trailPoints.length < 2;
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

  function renderLife(data) {
    const diary = (data.diary || {}).text || "";
    el("lifeDiary").textContent = diary
      ? (data.diary.day ? "第 " + data.diary.day + " 天\n\n" : "") + diary
      : "还没有日记。跑一次仿真后这里会出现它写的东西。";

    const bars = core.stateBars(data.state);
    const stateEl = el("lifeState");
    stateEl.innerHTML = "";
    bars.forEach(function (bar) {
      const row = document.createElement("div");
      row.className = "bar-row";

      const name = document.createElement("span");
      name.className = "name";
      name.textContent = bar.label;

      const track = document.createElement("span");
      track.className = "bar-track";
      const fill = document.createElement("span");
      fill.className = "bar-fill";
      fill.setAttribute("data-tone", bar.tone);
      fill.style.width = bar.percent + "%";
      track.appendChild(fill);

      const pct = document.createElement("span");
      pct.className = "pct";
      pct.textContent = bar.percent;

      row.appendChild(name);
      row.appendChild(track);
      row.appendChild(pct);
      stateEl.appendChild(row);
    });

    const TIERS = {life_goals: "人生", long_term_goals: "长期", short_term_goals: "近期"};
    const goalsEl = el("lifeGoals");
    goalsEl.innerHTML = "";
    Object.keys(TIERS).forEach(function (tier) {
      ((data.goals || {})[tier] || []).forEach(function (goal) {
        const li = document.createElement("li");
        const badge = document.createElement("span");
        badge.className = "tier";
        badge.textContent = TIERS[tier];
        const text = document.createElement("span");
        text.textContent = goal.title || "";
        li.appendChild(badge);
        li.appendChild(text);
        goalsEl.appendChild(li);
      });
    });
  }

  function renderHistory(reports) {
    const listEl = el("historyList");
    listEl.innerHTML = "";
    const groups = core.groupReportsByDay(reports);
    const today = groups.length ? groups[0].reports : [];

    if (!today.length) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "今天还没有上报。";
      listEl.appendChild(empty);
      return;
    }

    today.forEach(function (report) {
      const row = document.createElement("div");
      row.className = "history-row";

      const time = document.createElement("span");
      time.className = "time";
      const when = new Date((Number(report.ts) + Number(report.tz_offset || 0) * 60) * 1000);
      time.textContent = when.toISOString().slice(11, 16);

      const what = document.createElement("span");
      what.className = "what";
      const select = document.createElement("select");
      select.setAttribute("aria-label", "更正行为");
      core.ACTION_TAGS.forEach(function (tag) {
        const option = document.createElement("option");
        option.value = tag;
        option.textContent = core.TAG_LABELS[tag] || tag;
        option.selected = tag === report.action_tag;
        select.appendChild(option);
      });
      select.addEventListener("change", function () {
        amend(report.report_id, "update", {action_tag: select.value});
      });
      const where = document.createElement("div");
      where.className = "where";
      where.textContent = (report.node_id || "地图之外")
        + (report.note ? " · " + report.note : "");
      what.appendChild(select);
      what.appendChild(where);

      const del = document.createElement("button");
      del.type = "button";
      del.className = "del";
      del.setAttribute("aria-label", "删除这条上报");
      del.textContent = "✕";
      del.addEventListener("click", function () {
        /* Deletion cannot be undone from the phone, so it asks first. */
        if (window.confirm("删除这条上报？无法撤销。")) {
          amend(report.report_id, "delete");
        }
      });

      row.appendChild(time);
      row.appendChild(what);
      row.appendChild(del);
      listEl.appendChild(row);
    });
  }

  function amend(target, op, patch) {
    return api("/api/twin/amend", {
      method: "POST",
      body: {
        target: target,
        op: op,
        patch: patch || {},
        amend_id: (crypto.randomUUID && crypto.randomUUID())
          || String(Date.now()) + Math.random().toString(16).slice(2),
      },
    }).then(function () { return refresh(); });
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
    return Promise.all([
      api("/api/twin/snapshot"),
      api("/api/twin/trail"),
      api("/api/twin/life"),
      api("/api/twin/reports"),
    ])
      .then(function (results) {
        const snapshot = results[0];
        const trail = results[1];
        if (snapshot.status === 401 || trail.status === 401) {
          return signOut();
        }
        renderSnapshot(snapshot.data);
        trailPoints = core.drawableTrailPoints(trail.data.points);
        drawTrail(trailPoints);
        renderLife(results[2].data || {});
        renderHistory((results[3].data || {}).reports || []);
        renderRepeat(snapshot.data.report);
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

  function renderRepeat(report) {
    const button = el("repeatButton");
    if (!report || !report.action_tag) {
      button.hidden = true;
      return;
    }
    button.hidden = false;
    button.textContent = "和刚才一样 · "
      + (core.TAG_LABELS[report.action_tag] || report.action_tag);
    button.onclick = function () {
      selectedTag = report.action_tag;
      renderTagGrid();
      submitReport();
    };
  }

  function newReportId() {
    return (crypto.randomUUID && crypto.randomUUID())
      || String(Date.now()) + Math.random().toString(16).slice(2);
  }

  function sendReport(coords, options) {
    const opts = options || {};
    const report = core.buildReport({
      reportId: newReportId(),
      ts: Math.floor(Date.now() / 1000),
      tzOffset: -new Date().getTimezoneOffset(),
      coords: coords,
      tag: opts.tag || selectedTag,
      note: opts.note === undefined ? el("noteInput").value : opts.note,
      manual: !!opts.manual,
    });
    return enqueue(report).then(flushQueue).then(function () {
      if (opts.note === undefined) { el("noteInput").value = ""; }
    });
  }

  /* -- manual place picking ------------------------------------------- */

  function renderPlaces(places) {
    const listEl = el("placeList");
    listEl.innerHTML = "";
    (places || []).forEach(function (place) {
      const button = document.createElement("button");
      button.type = "button";
      const name = document.createElement("span");
      name.textContent = place.name;
      const dist = document.createElement("span");
      dist.className = "dist";
      dist.textContent = place.distance_km + " km";
      button.appendChild(name);
      button.appendChild(dist);
      button.addEventListener("click", function () {
        closePicker();
        /* A manually chosen node still travels as a coordinate, so the server
         * runs the same snapping and out-of-map logic as a real GPS fix — the
         * client never gets to assert a node id directly. */
        sendReport(
          {latitude: place.lat, longitude: place.lng, accuracy: 0},
          {manual: true, tag: pendingManualReport && pendingManualReport.tag}
        );
      });
      listEl.appendChild(button);
    });
  }

  function openPicker() {
    pendingManualReport = {tag: selectedTag};
    el("placePicker").hidden = false;
    el("placeSearch").value = "";
    api("/api/twin/places").then(function (result) {
      renderPlaces((result.data || {}).places);
    });
  }

  function closePicker() {
    el("placePicker").hidden = true;
    pendingManualReport = null;
  }

  function searchPlaces() {
    const q = encodeURIComponent(el("placeSearch").value.trim());
    api("/api/twin/places?q=" + q).then(function (result) {
      renderPlaces((result.data || {}).places);
    });
  }

  function submitReport() {
    const button = el("reportButton");
    button.disabled = true;
    return currentPosition().then(function (coords) {
      if (!coords) {
        /* Permission denied or unavailable. Offer a manual pick rather than
         * silently sending 0,0 — those coordinates land ~12000 km from the
         * map and get flagged out-of-map, losing the location entirely. */
        openPicker();
        return null;
      }
      return sendReport(coords);
    }).finally(function () {
      button.disabled = false;
    });
  }

  /* -- auto-sampling --------------------------------------------------- */

  function maybeAutoSample() {
    if (!el("autoSample").checked) { return; }
    const visible = document.visibilityState === "visible";
    const now = Date.now() / 1000;
    if (!core.shouldAutoSample(lastAutoSampleTs, now, AUTO_INTERVAL_MIN, visible)) {
      return;
    }
    currentPosition().then(function (coords) {
      if (!coords) { return; }
      lastAutoSampleTs = now;
      /* Auto samples carry the last chosen tag and no note: they record where
       * you were, not a fresh claim about what you were doing. */
      sendReport(coords, {note: ""});
    });
  }

  function showAuthGate() {
    el("intro").hidden = true;
    el("authGate").hidden = false;
  }

  function dismissIntro() {
    localStorage.setItem(INTRO_KEY, "1");
    showAuthGate();
  }

  function signOut() {
    token = "";
    localStorage.removeItem(TOKEN_KEY);
    el("main").hidden = true;
    /* Signing out returns to the gate, not the intro: the user has already
     * seen the explainer and just needs to re-enter a code. */
    showAuthGate();
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
    el("intro").hidden = true;
    el("authGate").hidden = true;
    el("main").hidden = false;
    renderTagGrid();
    api("/api/twin/profile").then(function (result) {
      if (result.status === 401) { return signOut(); }
      el("avatar").innerHTML = result.data.avatar_svg || "";
      el("agentLabel").textContent = result.data.label
        || ("Agent " + result.data.agent_id);
    });
    el("autoSample").checked = localStorage.getItem(AUTO_KEY) === "1";
    refresh();
    flushQueue();
    setInterval(function () {
      refresh();
      flushQueue();
      maybeAutoSample();
    }, POLL_MS);
  }

  function init() {
    el("codeSubmit").addEventListener("click", signIn);
    el("introStart").addEventListener("click", dismissIntro);
    el("reportButton").addEventListener("click", submitReport);
    el("replayButton").addEventListener("click", replayTrail);
    el("placeCancel").addEventListener("click", function () {
      closePicker();
      /* "Activity only": send with no usable fix. The server flags it
       * out-of-map and the mirror channel skips the position, but the
       * behaviour is still recorded. */
      sendReport({latitude: 0, longitude: 0, accuracy: 0}, {manual: true});
    });
    el("placeSearch").addEventListener("input", searchPlaces);
    el("autoSample").addEventListener("change", function () {
      localStorage.setItem(AUTO_KEY, el("autoSample").checked ? "1" : "0");
    });
    window.addEventListener("online", flushQueue);

    if (token) {
      start();
    } else if (core.shouldShowIntro(!!token, !!localStorage.getItem(INTRO_KEY))) {
      el("intro").hidden = false;
    } else {
      showAuthGate();
    }

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("sw.js").catch(function () {});
    }
  }

  document.addEventListener("DOMContentLoaded", init);
}());
