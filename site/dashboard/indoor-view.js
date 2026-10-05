/* Indoor activity view for GAWorld front-ends.
 *
 * Draws the floor plan of one building — rooms, furniture, the residents who
 * are inside it at the current frame — as a mode of the city map, in the live
 * dashboard and in the simulation replay. Each resident sits at the furniture
 * that fits what they are doing (bed for 睡觉, stove for 做饭, desk for 工作)
 * using the same detailed pixel renderer as the village view.
 *
 * Rooms and furniture come from the spatial tree (site/simviz/spatial-tree.js,
 * window.GAWorldSpatial): a preset selected by each place's use. Nothing here
 * changes the simulation; it only reads trace frames.
 *
 *   const view = new IndoorView(hostDiv, { getSelectedAgentId: () => id });
 *   view.setTrace(trace);
 *   view.render(frame);
 *
 * Exposes window.IndoorView; the pure helpers are require()-able under Node.
 */
(function (global) {
  "use strict";

  const t = (key, fallback) => {
    const v = typeof global.__ === "function" ? global.__(key) : key;
    return v && v !== key ? v : fallback;
  };

  const ROOM_ZH = {
    bedroom: "卧室", bathroom: "卫生间", study: "书房", kitchen: "厨房", living: "客厅", reception: "前台",
    ward: "病房", consult: "诊室", pharmacy: "药房", classroom: "教室", library: "图书室", office: "办公室",
    shop: "卖场", storeroom: "库房", checkout: "收银台", seating: "就餐区", counter: "吧台", meeting: "会议室",
    park: "公园",
  };
  // Where a room-less activity lands: the building's common room.
  const DEFAULT_ROOM_TYPES = ["living", "seating", "shop", "office", "reception", "classroom", "park"];

  /* ============================================================
   * Pure helpers (tested under Node)
   * ============================================================ */

  // Which furniture slot an activity uses. Mirrors the Phaser village's
  // activitySlot so both indoor renderers seat people the same way.
  function activitySlot(text) {
    const s = String(text || "");
    if (/刷牙|洗漱|洗手|洗澡|brush|wash|shower/i.test(s)) return "wash";
    if (/上厕所|厕所|卫生间|如厕|toilet/i.test(s)) return "toilet";
    if (/做饭|做菜|烹饪|cook/i.test(s)) return "cook";
    if (/健身|锻炼|运动|跑步|exercise|workout|treadmill|jog/i.test(s)) return "exercise";
    if (/钢琴|弹琴|piano|音乐|music/i.test(s)) return "music";
    if (/睡|休息|床|sleep|rest|nap/i.test(s)) return "sleep";
    if (/咖啡|coffee|order|点单|点餐/i.test(s)) return "order";
    if (/开会|会议|meeting/i.test(s)) return "meeting";
    if (/看病|问诊|consult|诊/i.test(s)) return "consult";
    if (/吃|饭|餐|eat|用餐/i.test(s)) return "eat";
    if (/读|看书|book|read|阅读/i.test(s)) return "read";
    if (/看电视|tv|watch/i.test(s)) return "watch";
    if (/学|课|study/i.test(s)) return "study";
    if (/买|shop|购物|超市/i.test(s)) return "shop";
    if (/工作|办公|上班|work/i.test(s)) return "work";
    return null;
  }
  const SLOT_ALIASES = { sleep: ["rest"], rest: ["sleep"], order: ["eat"], watch: ["sit"], study: ["work", "read"] };

  function agentLocation(agent) {
    return String((agent && (agent.resolved_location || agent.location || agent.target_location)) || "").trim();
  }
  function isTravelling(agent) {
    const status = agent && agent.travel && agent.travel.status;
    return /in_transit|departed/.test(String(status || ""));
  }
  // Residents physically inside `location` at this frame.
  function agentsAt(frame, location, node = null) {
    const agents = (frame && Array.isArray(frame.agents)) ? frame.agents : [];
    const names = [location, node && node.id, node && node.label].filter(Boolean);
    return agents.filter((a) => !isTravelling(a) && names.includes(agentLocation(a)));
  }
  // [{ name, count }] for every place someone is in, busiest first.
  function occupiedLocations(frame) {
    const counts = new Map();
    for (const a of (frame && Array.isArray(frame.agents)) ? frame.agents : []) {
      if (isTravelling(a)) continue;
      const loc = agentLocation(a);
      if (loc) counts.set(loc, (counts.get(loc) || 0) + 1);
    }
    return [...counts.entries()]
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  }
  // The building to show: the one the user pinned, else where the selected
  // resident is, else the busiest one. null when everyone is on the road.
  function pickLocation(frame, selectedId, pinned) {
    if (pinned) return pinned;
    const agents = (frame && Array.isArray(frame.agents)) ? frame.agents : [];
    const sel = agents.find((a) => Number(a.agent_id) === Number(selectedId));
    if (sel && !isTravelling(sel) && agentLocation(sel)) return agentLocation(sel);
    const busiest = occupiedLocations(frame)[0];
    return busiest ? busiest.name : null;
  }

  // Seat each resident in building space (0..1). Returns
  // [{ agent, x, y, room, slot }]. Two people never share one object; when
  // the slots run out they stand around the middle of the fitting room.
  function placeAgents(tree, agents) {
    const sector = tree.sector;
    const used = new Set();
    const crowd = new Map();
    const rooms = tree.arenaNames(sector);
    const defaultRoom = DEFAULT_ROOM_TYPES
      .map((type) => rooms.find((name) => (tree.arena(sector, name).meta || {}).type === type))
      .find(Boolean) || rooms[0];
    return agents.map((agent) => {
      const slot = activitySlot(agent.activity || agent.scheduled_activity || agent.action);
      const wanted = slot ? [slot, ...(SLOT_ALIASES[slot] || [])] : [];
      let rec = null;
      for (const s of wanted) {
        rec = tree.objects(sector).find((r) => r.slot === s && !used.has(r.address));
        if (rec) break;
      }
      if (rec) {
        used.add(rec.address);
        const box = tree.objectBuildingRect(rec);
        return { agent, x: box.x + box.w / 2, y: box.y + box.h / 2, room: rec.arena, slot };
      }
      let room = defaultRoom;
      for (const s of wanted) {
        const hit = tree.objects(sector).find((r) => r.slot === s);
        if (hit) { room = hit.arena; break; }
      }
      const meta = (tree.arena(sector, room) || {}).meta || { x: 0, y: 0, w: 1, h: 1 };
      const n = crowd.get(room) || 0;
      crowd.set(room, n + 1);
      // spiral out from the room centre so a crowd doesn't stack
      const ang = n * 2.4, rad = n ? 0.12 + 0.06 * Math.sqrt(n) : 0;
      return {
        agent,
        x: meta.x + meta.w * Math.min(0.9, Math.max(0.1, 0.5 + Math.cos(ang) * rad)),
        y: meta.y + meta.h * Math.min(0.9, Math.max(0.1, 0.5 + Math.sin(ang) * rad)),
        room, slot,
      };
    });
  }

  function roomLabel(meta, name) {
    const type = (meta && meta.type) || "";
    const num = (String(name).match(/\d+$/) || [""])[0];
    return t(`indoor.room.${type}`, ROOM_ZH[type] || name) + (num ? " " + num : "");
  }

  /* ============================================================
   * Shared pixel renderer adapter
   * ============================================================ */
  function injectStyle() {
    if (typeof document === "undefined" || document.getElementById("indoor-view-style")) return;
    const style = document.createElement("style");
    style.id = "indoor-view-style";
    style.textContent = `
      .iv-host { display:flex; flex-direction:column; gap:8px; min-width:0; }
      .iv-head { display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap; }
      .iv-title { display:flex; flex-direction:column; min-width:0; }
      .iv-title strong { font-size:15px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
      .iv-title span { font-size:12px; opacity:.7; }
      .iv-head select { max-width:220px; min-height:30px; font-size:12px; }
      .iv-viewport { width:100%; height:clamp(360px,62vh,640px); min-width:0; overflow:hidden;
        border-radius:10px; background:#30463d; touch-action:none; }
      .iv-viewport canvas { display:block; image-rendering:pixelated; }
      .iv-controls { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }
      .iv-controls button { min-width:36px; min-height:32px; padding:0 8px; }
      .iv-controls span { font-size:12px; opacity:.75; }
      .scene-modes { display:flex; flex-wrap:wrap; gap:6px; }
      [data-scene-workspace] .scene-modes button.is-active { background:#126a54; color:#fffef9; border-color:#126a54; }
      [data-scene-workspace] [hidden] { display:none !important; }
      @media(max-width:600px) { .iv-viewport { height:360px; } .iv-head select { max-width:100%; } }
    `;
    document.head.appendChild(style);
  }

  class IndoorView {
    constructor(host, opts = {}) {
      this.host = host;
      this.getSelectedAgentId = opts.getSelectedAgentId || (() => null);
      this.trace = null; this.frame = null; this.pinned = ""; this.zoom = 1;
      injectStyle();
      host.classList.add("iv-host"); host.innerHTML = "";
      const head = document.createElement("div"); head.className = "iv-head";
      const title = document.createElement("div"); title.className = "iv-title";
      this.titleEl = document.createElement("strong"); this.subEl = document.createElement("span");
      title.append(this.titleEl, this.subEl);
      this.select = document.createElement("select");
      this.select.setAttribute("aria-label", t("indoor.building", "查看建筑"));
      this.select.addEventListener("change", () => { this.pinned = this.select.value; this.render(this.frame); });
      head.append(title, this.select);
      this.viewport = document.createElement("div"); this.viewport.className = "iv-viewport";
      this.viewport.setAttribute("aria-label", t("indoor.mode", "室内模式"));
      const controls = document.createElement("div"); controls.className = "iv-controls";
      this.zoomEl = document.createElement("span"); this.zoomEl.textContent = "100%";
      for (const [label, key, fallback, factor] of [["＋", "indoor.zoom_in", "放大室内", 1.25],
        ["－", "indoor.zoom_out", "缩小室内", 0.8], ["⟲", "indoor.zoom_reset", "重置室内", 0]]) {
        const button = document.createElement("button"); button.type = "button"; button.textContent = label;
        button.setAttribute("aria-label", t(key, fallback));
        button.addEventListener("click", () => this.renderer && this.renderer.setZoom(factor ? this.zoom * factor : 1));
        controls.append(button);
      }
      controls.append(this.zoomEl);
      const hint = document.createElement("span"); hint.textContent = t("indoor.drag", "拖动查看细节"); controls.append(hint);
      host.append(head, this.viewport, controls);
      this.workspace = host.closest("[data-scene-workspace]");
      if (this.workspace) {
        this.modeButtons = [...this.workspace.querySelectorAll("[data-scene-mode]")];
        this.modeButtons.forEach(button => button.addEventListener("click", () => this.setMode(button.dataset.sceneMode)));
        this.setMode("city");
      }
      if (typeof ResizeObserver !== "undefined") {
        this.resizeObserver = new ResizeObserver(() => {
          if (!this.host.hidden && this.renderer) this.renderer.resize();
        });
        this.resizeObserver.observe(this.viewport);
      }
    }

    setMode(mode) {
      const indoor = mode === "indoor";
      this.host.hidden = !indoor;
      const city = this.workspace.querySelector("[data-city-view]");
      if (city) city.hidden = indoor;
      this.modeButtons.forEach(button => {
        const active = button.dataset.sceneMode === mode;
        button.setAttribute("aria-pressed", String(active)); button.classList.toggle("is-active", active);
      });
      if (indoor) { this.draw(); if (this.renderer) this.renderer.resize(); }
      // The city map may have been initialized in a hidden container.
      if (!indoor && global.dispatchEvent && global.Event) global.dispatchEvent(new global.Event("resize"));
    }

    setTrace(trace) {
      this.trace = trace;
      const nodes = (trace && trace.map && trace.map.nodes) || [];
      if (this.pinned && !nodes.some(node => node.id === this.pinned || node.label === this.pinned)) this.pinned = "";
    }

    render(frame) {
      this.frame = frame || null; this._syncSelect(); this.draw();
    }

    _syncSelect() {
      const places = occupiedLocations(this.frame);
      // Empty buildings remain selectable while scrubbing a replay.
      const nodes = (this.trace && this.trace.map && this.trace.map.nodes) || [];
      nodes.filter(node => !["road", "junction", "intersection"].includes(node.kind)).forEach(node => {
        const name = node.label || node.id;
        if (!places.some(p => p.name === name || p.name === node.id)) places.push({name, count: 0});
      });
      const html = [`<option value="">${escapeHtml(t("indoor.auto", "自动跟随"))}</option>`]
        .concat(places.map(p => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)} · ${p.count}</option>`)).join("");
      if (this._selectHtml !== html) { this.select.innerHTML = html; this._selectHtml = html; }
      this.select.value = this.pinned;
    }

    _node(location) {
      const nodes = (this.trace && this.trace.map && this.trace.map.nodes) || [];
      return nodes.find(node => node.label === location || node.id === location) || {id: location, label: location};
    }

    draw() {
      const selectedId = this.getSelectedAgentId();
      const location = pickLocation(this.frame, selectedId, this.frame ? this.pinned : "");
      const node = location ? this._node(location) : null;
      const layout = node && global.GAWorldSpatial && global.GAWorldSpatial.layoutFor(node);
      this.titleEl.textContent = location ? `${layout && layout.blueprint.outdoor ? "🌳" : "🏠"} ${node.label || location}` : t("indoor.title", "室内活动");
      const selected = this.frame && (this.frame.agents || []).find(a => Number(a.agent_id) === Number(selectedId));
      const flat = global.GAWorldSpatial && global.GAWorldSpatial.flatView
        ? global.GAWorldSpatial.flatView(location ? agentsAt(this.frame, location, node) : [], selectedId)
        : { unit: "", units: 0, agents: location ? agentsAt(this.frame, location, node) : [] };
      this.subEl.textContent = location ? `${layout ? layout.label + " · " : ""}`
        + `${flat.unit ? `${t("indoor.flat", "户")} ${flat.unit} · ` : ""}`
        + `${flat.agents.length} ${t("indoor.present", "人在场")}` :
        selected && isTravelling(selected) ? t("indoor.travelling", "选中的居民正在路上") : t("indoor.empty", "当前帧没有居民在室内");
      if (this.host.hidden) return;
      if (!this.renderer && global.createIndoorRenderer) {
        this.renderer = global.createIndoorRenderer(this.viewport, {onZoom: value => {
          this.zoom = value; this.zoomEl.textContent = Math.round(value * 100) + "%";
        }});
      }
      if (this.renderer) this.renderer.render(this.trace, this.frame, node, selectedId);
      else this.subEl.textContent = t("indoor.unavailable", "室内视图未加载，请刷新页面");
    }

    destroy() {
      if (this.resizeObserver) this.resizeObserver.disconnect();
      if (this.renderer) this.renderer.destroy();
    }
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  const api = { activitySlot, agentsAt, occupiedLocations, pickLocation, placeAgents, isTravelling, IndoorView };
  global.IndoorView = IndoorView;
  global.GAWorldIndoor = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
