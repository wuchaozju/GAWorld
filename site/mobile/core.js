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

  function hasFiniteGrid(point) {
    return !!(point && point.grid
      && Number.isFinite(point.grid.x) && Number.isFinite(point.grid.y));
  }

  function drawableTrailPoints(points) {
    return (points || []).filter(function (point) {
      if (!hasFiniteGrid(point)) { return false; }
      // Older APIs lack has_location; keep their conservative map-only view.
      return typeof point.has_location === "boolean"
        ? point.has_location : !point.out_of_map;
    });
  }

  function trailBounds(points) {
    const list = (points || []).filter(function (p) {
      return hasFiniteGrid(p);
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

  /* The intro is a first-run explainer, not a gate. Anyone already holding a
   * token has used the app before, so it is skipped even if the "seen" flag
   * was lost (new device, cleared storage) — re-explaining the product to a
   * returning user is worse than never explaining it. */
  function shouldShowIntro(hasToken, hasSeenIntro) {
    if (hasToken) { return false; }
    return !hasSeenIntro;
  }

  /* The nine normalized state variables, with the direction that counts as
   * "good" so the bar can be coloured without the caller deciding. */
  const STATE_LABELS = {
    emotion: {label: "情绪", good: "high"},
    stress: {label: "压力", good: "low"},
    econ_security: {label: "经济安全感", good: "high"},
    city_identity: {label: "城市认同", good: "high"},
    policy_sensitivity: {label: "政策敏感度", good: "neutral"},
    platform_dependence: {label: "平台依赖", good: "neutral"},
    risk_preference: {label: "风险偏好", good: "neutral"},
    voice_propensity: {label: "表达意愿", good: "neutral"},
    mobility_intent: {label: "迁移意愿", good: "neutral"},
  };

  function stateBars(state) {
    const rows = [];
    Object.keys(STATE_LABELS).forEach(function (key) {
      const raw = (state || {})[key];
      if (typeof raw !== "number" || !isFinite(raw)) { return; }
      const value = Math.max(0, Math.min(1, raw));
      const meta = STATE_LABELS[key];
      let tone = "neutral";
      if (meta.good === "high") { tone = value >= 0.5 ? "good" : "warn"; }
      if (meta.good === "low") { tone = value <= 0.5 ? "good" : "warn"; }
      rows.push({
        key: key,
        label: meta.label,
        value: value,
        percent: Math.round(value * 100),
        tone: tone,
      });
    });
    return rows;
  }

  /* Local-day grouping, using each report's own tz_offset rather than the
   * reader's clock: a report made in Hangzhou belongs to the Hangzhou day it
   * was made on, whoever is looking at it later. */
  function localDayKey(report) {
    const ts = Number((report || {}).ts || 0);
    const offsetMinutes = Number((report || {}).tz_offset || 0);
    const shifted = new Date((ts + offsetMinutes * 60) * 1000);
    return shifted.toISOString().slice(0, 10);
  }

  function groupReportsByDay(reports) {
    const groups = [];
    const index = {};
    (reports || []).forEach(function (report) {
      const key = localDayKey(report);
      if (!index[key]) {
        index[key] = {day: key, reports: []};
        groups.push(index[key]);
      }
      index[key].reports.push(report);
    });
    return groups;
  }

  /* Auto-sampling only makes sense while the page is actually on screen; a
   * backgrounded tab would burn battery for data the browser may throttle
   * anyway. iOS additionally cannot sample at all once the app is closed. */
  function shouldAutoSample(lastSampleTs, nowTs, intervalMinutes, visible) {
    if (!visible) { return false; }
    if (!lastSampleTs) { return true; }
    return (Number(nowTs) - Number(lastSampleTs)) >= Number(intervalMinutes) * 60;
  }

  /* Wording matters here: the old copy said the position "would not sync",
   * which read as the location being thrown away. It never was — the
   * coordinate is recorded either way. What actually happens is that it
   * matches no map node, so the agent is marked as being away. */
  function outOfMapNotice(report) {
    if (report && report.out_of_map) {
      const place = String(report.place || "").trim();
      return place
        ? "已记录你在「" + place + "」的真实位置。这里不在仿真地图内，智能体会显示为异地。"
        : "已记录你的真实位置。这里不在仿真地图内，智能体会显示为异地。";
    }
    return "";
  }

  /* What to show as "where you are" — a map node when one matched, otherwise
   * the offline place name, otherwise the raw coordinate. Never blank, and
   * never the word "unknown": the position is known in every one of these
   * cases, only its match to the simulated city differs. */
  function locationLabel(report) {
    if (!report) { return ""; }
    if (!report.out_of_map && report.node_id) { return report.node_id; }
    const place = String(report.place || "").trim();
    if (place) { return "异地（" + place + "）"; }
    const loc = report.loc || {};
    if (typeof loc.lat === "number" && typeof loc.lng === "number") {
      return "异地（" + loc.lat.toFixed(2) + ", " + loc.lng.toFixed(2) + "）";
    }
    return "异地";
  }

  return {
    ACTION_TAGS: ACTION_TAGS,
    TAG_LABELS: TAG_LABELS,
    buildReport: buildReport,
    dropSynced: dropSynced,
    drawableTrailPoints: drawableTrailPoints,
    trailBounds: trailBounds,
    projectPoint: projectPoint,
    visiblePoints: visiblePoints,
    shouldShowIntro: shouldShowIntro,
    STATE_LABELS: STATE_LABELS,
    stateBars: stateBars,
    localDayKey: localDayKey,
    groupReportsByDay: groupReportsByDay,
    shouldAutoSample: shouldAutoSample,
    syncLabel: syncLabel,
    outOfMapNotice: outOfMapNotice,
    locationLabel: locationLabel,
  };
}));
