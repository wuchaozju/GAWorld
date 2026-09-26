/* Shared terrain-map renderer for GAWorld front-ends.
 *
 * One renderer, used by both the Dashboard (控制台) map panel and the
 * Simulation replay (仿真回放) tab, so they stay identical. Renders the
 * simulation trace's embedded city map (real or virtual): baked terrain tiles,
 * place markers, level-of-detail landmark labels, agent movement trails, and
 * large agent avatars — with shared zoom (wheel / buttons) and pan (drag).
 *
 *   const view = new CityMapView(canvas, { getSelectedAgentId: () => id });
 *   view.setTrace(trace);
 *   view.render(framesUpTo);   // framesUpTo = frames[0..current]; [] = base only
 *
 * Exposes window.CityMapView (no build step / modules).
 */
(function (global) {
  "use strict";

  /* i18n.js is loaded before this file on every page that uses it, but the
     locale JSON arrives asynchronously — so these resolve at call time, never
     at load time, and fall back to the key if the globals are absent. */
  const t = (key) => (typeof global.__ === "function" ? global.__(key) : key);
  const tf = (key, params) =>
    (typeof global.__f === "function" ? global.__f(key, params) : key);

  const tileColors = {
    ".": "#e5ece4", "#": "#7d8c82", "=": "#f3cf63", "~": "#7fb3be",
    "*": "#82a661", "r": "#d8d7c3", "c": "#d6a81e", "e": "#8db0c2",
    "m": "#d98b8b", "i": "#a3aaa1", "g": "#bcc87c", "l": "#72a773",
    "t": "#9b8fc0", "+": "#b28bd6", "d": "#cfc9a6",
    // real-map road classes share the collector/arterial palette
    "A": "#6f7c86", "C": "#8492a0", "L": "#9aa39a",
  };
  const agentColors = ["#13795b", "#b73e3e", "#385866", "#d6a81e", "#6e5f97", "#1f8a9b", "#8a5b30"];

  // Famous Hangzhou landmarks are labelled first; others fill in as you zoom.
  /* i18n-exempt-start: matches place names in the map data, not interface text */
  const FAMOUS_LANDMARKS = /西湖|武林|龙翔桥|城站|火车东站|杭州东|钱江|市民中心|灵隐|西溪|浙江大学|浙大|黄龙|湘湖|奥体|良渚|之江|萧山国际机场|机场/;
  /* i18n-exempt-end */

  function roundRect(c, x, y, w, h, r) {
    c.beginPath();
    c.moveTo(x + r, y);
    c.arcTo(x + w, y, x + w, y + h, r);
    c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r);
    c.arcTo(x, y, x + w, y, r);
    c.closePath();
  }

  function landmarkScore(node) {
    let s = Number(node.popularity || 0) * 0.5;
    if (node.kind === "hub") s += 0.45;
    const cat = node.category;
    if (cat === "transit") s += 0.4;
    else if (cat === "leisure") s += 0.28;
    else if (cat === "commerce") s += 0.22;
    else if (cat === "education" || cat === "medical" || cat === "government") s += 0.16;
    if (FAMOUS_LANDMARKS.test(node.label || node.id || "")) s += 1.0;
    return s;
  }

  class CityMapView {
    constructor(canvas, opts) {
      opts = opts || {};
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.avatarBase = opts.avatarBase || "/output/visualization/";
      this.getSelectedAgentId = opts.getSelectedAgentId || (() => null);
      // Home-mode hook: returns the home-node id for the selected agent (or
      // null). The renderer draws a soft orange ring around that node so a
      // viewer can find "where does this person live?" without opening any
      // panel. Optional — callers that don't wire it just lose the ring.
      this.getSelectedAgentHome = opts.getSelectedAgentHome || (() => null);
      // May be a function: the locale file loads after this constructor runs,
      // so a caller translating the string has to defer it to render time or
      // it paints the untranslated key. The default defers for the same reason.
      this.emptyText = opts.emptyText || (() => t("map.waiting_data"));
      this.trailFrames = opts.trailFrames || 96;
      this.trace = null;
      this.framesUpTo = [];
      this.view = { zoom: 1, panX: 0, panY: 0 };
      this.lastLayout = null;
      this.terrainCache = null;   // { key, canvas }
      this.avatarCache = new Map();
      this._setupInteractions();
    }

    // ---- public API -------------------------------------------------------
    setTrace(trace) {
      if (trace !== this.trace) this.terrainCache = null;
      this.trace = trace;
    }
    get selectedAgentId() { return this.getSelectedAgentId(); }
    render(framesUpTo) { this.framesUpTo = framesUpTo || []; this._draw(); }
    rerender() { this._draw(); }

    hasMap() {
      const m = this.trace && this.trace.map;
      return !!(m && Array.isArray(m.nodes) && m.nodes.length);
    }

    renderEmpty(text) {
      const c = this.ctx, w = this.canvas.width, h = this.canvas.height;
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.clearRect(0, 0, w, h);
      c.fillStyle = "#e5ece4";
      c.fillRect(0, 0, w, h);
      c.fillStyle = "#385866";
      c.font = '22px "Noto Sans SC", "Microsoft YaHei", Georgia, sans-serif';
      c.textBaseline = "alphabetic";
      const fallback = typeof this.emptyText === "function" ? this.emptyText() : this.emptyText;
      c.fillText(text || fallback, 40, 56);
    }

    // ---- coordinate model -------------------------------------------------
    _layout(map) {
      const cw = this.canvas.width, ch = this.canvas.height;
      const tileMap = map.tile_map || {};
      const width = Number(tileMap.width || 160);
      const height = Number(tileMap.height || 112);
      const baseScale = Math.max(4, Math.floor(Math.min(cw / width, ch / height)));
      const worldW = width * baseScale, worldH = height * baseScale;
      return {
        width, height, baseScale, worldW, worldH,
        baseOffsetX: Math.floor((cw - worldW) / 2),
        baseOffsetY: Math.floor((ch - worldH) / 2),
      };
    }

    _bakedTerrain(map, layout) {
      const gen = (this.trace && this.trace.meta && this.trace.meta.generated_at) || "";
      const key = gen + ":" + layout.baseScale + ":" + layout.width + "x" + layout.height;
      if (this.terrainCache && this.terrainCache.key === key) return this.terrainCache.canvas;
      const off = document.createElement("canvas");
      off.width = layout.worldW;
      off.height = layout.worldH;
      const octx = off.getContext("2d");
      octx.fillStyle = tileColors["."];
      octx.fillRect(0, 0, off.width, off.height);
      const terrain = Array.isArray(map.tile_map && map.tile_map.terrain) ? map.tile_map.terrain : [];
      const s = layout.baseScale;
      terrain.forEach((line, row) => {
        String(line).split("").forEach((cell, col) => {
          const color = tileColors[cell];
          if (!color || cell === ".") return;
          octx.fillStyle = color;
          octx.fillRect(col * s, row * s, s, s);
        });
      });
      this.terrainCache = { key, canvas: off };
      return off;
    }

    _nodeWorld(node, layout) {
      return [node.tile_x * layout.baseScale + layout.baseScale / 2,
              node.tile_y * layout.baseScale + layout.baseScale / 2];
    }
    _toScreen(wx, wy) {
      const L = this.lastLayout, v = this.view;
      return [L.baseOffsetX + v.panX + wx * v.zoom, L.baseOffsetY + v.panY + wy * v.zoom];
    }
    _agentWorld(agent, nodes, layout) {
      const tgt = nodes.get(agent.target_location);
      const cur = nodes.get(agent.resolved_location);
      const p = Number(agent.travel_progress);
      if (cur && tgt && cur !== tgt && p >= 0 && p <= 1) {
        const a = this._nodeWorld(cur, layout), b = this._nodeWorld(tgt, layout);
        return [a[0] + (b[0] - a[0]) * p, a[1] + (b[1] - a[1]) * p];
      }
      const node = tgt || cur;
      return node ? this._nodeWorld(node, layout) : null;
    }

    // ---- avatars ----------------------------------------------------------
    _avatarPath(agentId) {
      const agents = (this.trace && Array.isArray(this.trace.agents)) ? this.trace.agents : [];
      const meta = agents.find((a) => Number(a.id) === Number(agentId));
      const raw = (meta && meta.avatar_path) || `avatars/agent_${Number(agentId || 0)}.svg`;
      if (/^(https?:)?\/\//.test(raw) || raw.startsWith("data:")) return raw;
      if (!raw.startsWith("/")) return this.avatarBase + raw;
      return raw;
    }
    _loadAvatar(agentId) {
      const path = this._avatarPath(agentId);
      if (this.avatarCache.has(path)) {
        const cached = this.avatarCache.get(path);
        return cached.loaded ? cached.img : null;
      }
      const img = new Image();
      const rec = { img, loaded: false };
      this.avatarCache.set(path, rec);
      img.onload = () => { rec.loaded = true; this.rerender(); };
      img.onerror = () => this.avatarCache.delete(path);
      img.src = path;
      return null;
    }

    // ---- drawing ----------------------------------------------------------
    _draw() {
      const map = (this.trace || {}).map || {};
      if (!map.tile_map || !Array.isArray(map.nodes)) { this.renderEmpty(); return; }
      const layout = this._layout(map);
      this.lastLayout = layout;
      const c = this.ctx, cw = this.canvas.width, ch = this.canvas.height;
      const frame = this.framesUpTo[this.framesUpTo.length - 1];

      c.setTransform(1, 0, 0, 1, 0, 0);
      c.clearRect(0, 0, cw, ch);
      c.fillStyle = "#cfd8cf";   // letterbox around the map when zoomed/panned
      c.fillRect(0, 0, cw, ch);

      const terrainImg = this._bakedTerrain(map, layout);
      const originX = layout.baseOffsetX + this.view.panX;
      const originY = layout.baseOffsetY + this.view.panY;
      c.imageSmoothingEnabled = false;
      c.drawImage(terrainImg, originX, originY, layout.worldW * this.view.zoom, layout.worldH * this.view.zoom);

      const nodes = new Map(map.nodes.map((n) => [n.id, n]));

      map.nodes.forEach((node) => {
        const w = this._nodeWorld(node, layout);
        const [x, y] = this._toScreen(w[0], w[1]);
        if (x < -8 || x > cw + 8 || y < -8 || y > ch + 8) return;
        const hub = node.kind === "hub";
        c.fillStyle = hub ? "#17211d" : "rgba(56,88,102,0.7)";
        const r = hub ? 3 : 2;
        c.fillRect(x - r, y - r, r * 2, r * 2);
      });

      // Home-mode highlight: a soft orange ring around the selected agent's
      // home node. Drawn after the dots so it sits on top, before the
      // landmark labels so the existing label-priority logic still wins
      // when the home node is also a famous landmark.
      this._drawHomeHighlight(map.nodes, layout);

      this._drawLandmarks(map.nodes, layout);

      if (frame) {
        this._drawTrails(this.framesUpTo, nodes, layout);
        (frame.agents || []).forEach((agent) => this._drawAgent(agent, nodes, layout));
      }
      this._drawHint();
    }

    _drawLandmarks(nodesArr, layout) {
      const c = this.ctx, cw = this.canvas.width, ch = this.canvas.height;
      const scored = nodesArr.map((n) => ({ n, s: landmarkScore(n) })).filter((o) => o.s > 0.15);
      scored.sort((a, b) => b.s - a.s);
      const maxLabels = Math.max(6, Math.min(80, Math.round(6 + (this.view.zoom - 1) * 22)));
      const placed = [];
      c.font = '600 12px "Noto Sans SC", "Microsoft YaHei", sans-serif';
      c.textBaseline = "middle";
      let shown = 0;
      for (const { n, s } of scored) {
        if (shown >= maxLabels) break;
        const w = this._nodeWorld(n, layout);
        const [x, y] = this._toScreen(w[0], w[1]);
        if (x < 24 || x > cw - 24 || y < 14 || y > ch - 14) continue;
        const text = n.label || n.id || "";
        if (!text) continue;
        const famous = s >= 1.0;
        const tw = c.measureText(text).width;
        const bx = x + 7, by = y - 8, bw = tw + 8, bh = 16;
        if (placed.some((p) => bx < p.x + p.w + 3 && bx + bw + 3 > p.x && by < p.y + p.h + 3 && by + bh + 3 > p.y)) continue;
        placed.push({ x: bx, y: by, w: bw, h: bh });
        c.fillStyle = famous ? "#b5451f" : "#31543f";
        c.beginPath(); c.arc(x, y, famous ? 4 : 3, 0, Math.PI * 2); c.fill();
        c.fillStyle = "rgba(255,255,255,0.85)";
        roundRect(c, bx, by, bw, bh, 4); c.fill();
        c.fillStyle = famous ? "#7a2d12" : "#20321f";
        c.fillText(text, bx + 4, by + bh / 2);
        shown += 1;
      }
    }

    _drawHomeHighlight(nodesArr, layout) {
      // Soft orange halo around the selected agent's home node. Off when no
      // selection, no home, or the home node isn't in the current map.
      const homeId = typeof this.getSelectedAgentHome === "function"
        ? this.getSelectedAgentHome()
        : null;
      if (!homeId) return;
      const node = nodesArr.find((n) => (n.id === homeId || n.label === homeId));
      if (!node) return;
      const c = this.ctx;
      const w = this._nodeWorld(node, layout);
      const [x, y] = this._toScreen(w[0], w[1]);
      c.save();
      c.strokeStyle = "rgba(214, 124, 56, 0.85)";
      c.lineWidth = 2;
      c.setLineDash([4, 3]);
      c.beginPath(); c.arc(x, y, 11, 0, Math.PI * 2); c.stroke();
      c.strokeStyle = "rgba(214, 124, 56, 0.35)";
      c.lineWidth = 1;
      c.beginPath(); c.arc(x, y, 16, 0, Math.PI * 2); c.stroke();
      c.setLineDash([]);
      c.restore();
    }

    _isAgentAtHome(agent) {
      // An agent is "at home" when their current location equals their home
      // node — same definition the HomeEnvironmentPlugin uses internally.
      const home = String(agent.home || "").trim();
      const current = String(agent.resolved_location || agent.location || "").trim();
      if (!home || !current) return false;
      return home === current;
    }

    _drawHomeBadge(c, x, y, radius) {
      // A small "🏠" badge anchored bottom-right of the avatar. We use the
      // emoji glyph directly so it follows the system font stack instead of
      // shipping a custom icon.
      const bx = x + radius * 0.78;
      const by = y + radius * 0.78;
      c.save();
      c.fillStyle = "rgba(255, 254, 249, 0.96)";
      c.beginPath(); c.arc(bx, by, 9, 0, Math.PI * 2); c.fill();
      c.strokeStyle = "rgba(20, 121, 91, 0.85)";
      c.lineWidth = 1.4;
      c.beginPath(); c.arc(bx, by, 9, 0, Math.PI * 2); c.stroke();
      c.font = '11px "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif';
      c.textAlign = "center";
      c.textBaseline = "middle";
      c.fillText("🏠", bx, by + 1);
      c.restore();
    }

    _drawTrails(framesUpTo, nodes, layout) {
      const c = this.ctx;
      const trail = framesUpTo.slice(-this.trailFrames);
      const byAgent = new Map();
      trail.forEach((frame) => {
        (frame.agents || []).forEach((agent) => {
          const w = this._agentWorld(agent, nodes, layout);
          if (!w) return;
          const key = Number(agent.agent_id);
          if (!byAgent.has(key)) byAgent.set(key, []);
          const pts = byAgent.get(key);
          const last = pts[pts.length - 1];
          if (!last || last[0] !== w[0] || last[1] !== w[1]) pts.push(w);
        });
      });
      byAgent.forEach((pts, agentId) => {
        if (pts.length < 2) return;
        const selected = agentId === Number(this.selectedAgentId);
        const color = agentColors[Math.abs(agentId) % agentColors.length];
        c.save();
        c.strokeStyle = color;
        c.globalAlpha = selected ? 0.9 : 0.5;
        c.lineWidth = selected ? 4 : 2.5;
        c.lineJoin = "round";
        c.lineCap = "round";
        c.setLineDash(selected ? [] : [7, 6]);
        c.beginPath();
        const p0 = this._toScreen(pts[0][0], pts[0][1]);
        c.moveTo(p0[0], p0[1]);
        for (let i = 1; i < pts.length; i += 1) {
          const p = this._toScreen(pts[i][0], pts[i][1]);
          c.lineTo(p[0], p[1]);
        }
        c.stroke();
        c.setLineDash([]);
        pts.forEach((pt) => {
          const p = this._toScreen(pt[0], pt[1]);
          c.beginPath(); c.arc(p[0], p[1], selected ? 3 : 2, 0, Math.PI * 2); c.fill();
        });
        c.restore();
      });
    }

    _drawAgent(agent, nodes, layout) {
      const c = this.ctx;
      const w = this._agentWorld(agent, nodes, layout);
      if (!w) return;
      const [x, y] = this._toScreen(w[0], w[1]);
      const selected = Number(agent.agent_id) === Number(this.selectedAgentId);
      const radius = selected ? 26 : 18;
      const color = agentColors[Math.abs(Number(agent.agent_id || 0)) % agentColors.length];
      // soft halo
      c.save();
      c.shadowColor = "rgba(0,0,0,0.35)";
      c.shadowBlur = 8;
      c.shadowOffsetY = 2;
      c.fillStyle = "#fffef9";
      c.beginPath(); c.arc(x, y, radius + 3, 0, Math.PI * 2); c.fill();
      c.restore();
      // avatar image clipped to circle
      const avatarImage = this._loadAvatar(agent.agent_id);
      c.save();
      c.beginPath(); c.arc(x, y, radius, 0, Math.PI * 2); c.closePath(); c.clip();
      if (avatarImage) {
        c.drawImage(avatarImage, x - radius, y - radius, radius * 2, radius * 2);
      } else {
        c.fillStyle = color;
        c.fillRect(x - radius, y - radius, radius * 2, radius * 2);
      }
      c.restore();
      // ring
      c.strokeStyle = selected ? color : "#fffef9";
      c.lineWidth = selected ? 4 : 3;
      c.beginPath(); c.arc(x, y, radius, 0, Math.PI * 2); c.stroke();
      // home-mode badge: small 🏠 on agents who are actually at their home node
      if (this._isAgentAtHome(agent)) this._drawHomeBadge(c, x, y, radius);
      // name pill
      const name = agent.name || String(agent.agent_id);
      c.font = '600 13px "Noto Sans SC", "Microsoft YaHei", sans-serif';
      c.textBaseline = "middle";
      const tw = c.measureText(name).width;
      const lx = x - tw / 2 - 5, ly = y + radius + 6, lw = tw + 10, lh = 18;
      c.fillStyle = "rgba(23,33,29,0.82)";
      roundRect(c, lx, ly, lw, lh, 5); c.fill();
      c.fillStyle = "#fffef9";
      c.fillText(name, lx + 5, ly + lh / 2);
    }

    _drawHint() {
      const c = this.ctx;
      c.font = '11px "Noto Sans SC", "Microsoft YaHei", sans-serif';
      c.textBaseline = "bottom";
      c.fillStyle = "rgba(23,33,29,0.55)";
      c.fillText(tf("map.hint", { zoom: Math.round(this.view.zoom * 100) }), 12, this.canvas.height - 10);
    }

    // ---- interactions (zoom / pan) ---------------------------------------
    _clampPan() {
      if (!this.lastLayout) return;
      const L = this.lastLayout, v = this.view;
      const cw = this.canvas.width, ch = this.canvas.height;
      const w = L.worldW * v.zoom, h = L.worldH * v.zoom;
      const minX = 0.75 * cw - L.baseOffsetX - w, maxX = 0.25 * cw - L.baseOffsetX;
      const minY = 0.75 * ch - L.baseOffsetY - h, maxY = 0.25 * ch - L.baseOffsetY;
      v.panX = minX > maxX ? (minX + maxX) / 2 : Math.min(maxX, Math.max(minX, v.panX));
      v.panY = minY > maxY ? (minY + maxY) / 2 : Math.min(maxY, Math.max(minY, v.panY));
    }
    zoomAt(cx, cy, factor) {
      if (!this.lastLayout) return;
      const L = this.lastLayout, v = this.view;
      const nz = Math.min(8, Math.max(1, v.zoom * factor));
      const originX = L.baseOffsetX + v.panX, originY = L.baseOffsetY + v.panY;
      const wx = (cx - originX) / v.zoom, wy = (cy - originY) / v.zoom;
      v.panX = cx - L.baseOffsetX - wx * nz;
      v.panY = cy - L.baseOffsetY - wy * nz;
      v.zoom = nz;
      this._clampPan();
      this.rerender();
    }
    resetView() { this.view.zoom = 1; this.view.panX = 0; this.view.panY = 0; this.rerender(); }

    _setupInteractions() {
      const cv = this.canvas;
      const toCanvas = (e) => {
        const rect = cv.getBoundingClientRect();
        return [(e.clientX - rect.left) * (cv.width / rect.width),
                (e.clientY - rect.top) * (cv.height / rect.height)];
      };
      cv.addEventListener("wheel", (e) => {
        e.preventDefault();
        const [mx, my] = toCanvas(e);
        this.zoomAt(mx, my, e.deltaY < 0 ? 1.12 : 1 / 1.12);
      }, { passive: false });
      let dragging = false, lastX = 0, lastY = 0;
      cv.addEventListener("mousedown", (e) => {
        dragging = true;
        const [x, y] = toCanvas(e); lastX = x; lastY = y;
        cv.style.cursor = "grabbing";
      });
      window.addEventListener("mousemove", (e) => {
        if (!dragging) return;
        const [x, y] = toCanvas(e);
        this.view.panX += x - lastX; this.view.panY += y - lastY;
        lastX = x; lastY = y;
        this._clampPan();
        this.rerender();
      });
      window.addEventListener("mouseup", () => { dragging = false; cv.style.cursor = "grab"; });
      cv.addEventListener("dblclick", (e) => { e.preventDefault(); this.resetView(); });
      cv.style.cursor = "grab";
      this._buildControls();
    }

    _buildControls() {
      const cv = this.canvas;
      const parent = cv.parentElement;
      if (!parent || parent.querySelector(".cmv-zoom")) return;
      if (getComputedStyle(parent).position === "static") parent.style.position = "relative";
      const wrap = document.createElement("div");
      wrap.className = "cmv-zoom";
      wrap.style.cssText = "position:absolute;right:16px;bottom:18px;display:flex;flex-direction:column;gap:6px;z-index:6;";
      const mk = (label, title, fn) => {
        const b = document.createElement("button");
        b.type = "button"; b.textContent = label; b.title = title;
        b.style.cssText = "width:36px;height:36px;border-radius:9px;border:1px solid rgba(0,0,0,0.14);" +
          "background:rgba(255,255,255,0.94);color:#20321f;font-size:19px;line-height:1;cursor:pointer;" +
          "box-shadow:0 1px 5px rgba(0,0,0,0.18);";
        b.addEventListener("click", (e) => { e.preventDefault(); fn(); });
        return b;
      };
      const cx = () => this.canvas.width / 2, cy = () => this.canvas.height / 2;
      wrap.appendChild(mk("+", t("map.zoom_in"), () => this.zoomAt(cx(), cy(), 1.25)));
      wrap.appendChild(mk("−", t("map.zoom_out"), () => this.zoomAt(cx(), cy(), 1 / 1.25)));
      wrap.appendChild(mk("↻", t("map.reset_view"), () => this.resetView()));
      parent.appendChild(wrap);
    }
  }

  global.CityMapView = CityMapView;
})(window);
