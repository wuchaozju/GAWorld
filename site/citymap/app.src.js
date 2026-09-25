/* GAWorld CityMap viewer — Phaser 3 edition.
 *
 * Two scenes share a module-level `state`:
 *   MapScene    — outdoor city: baked terrain/overlay/road textures, river,
 *                 metro, styled node markers, smooth camera, agent replay.
 *   IndoorScene — Graphics-drawn pixel room entered by double-clicking a node;
 *                 furniture by category, agent sprites + NAME:emoji bubbles.
 *
 * Base map  ← citymap_visualization.json (build_visualization_payload).
 * Replay    ← simulation_trace.json (frames[] / agents[]).
 * DOM side-panel handles file loading, layer toggles, filters, transport.
 */
(function () {
  "use strict";

  const PX = 44;               // pixels per grid unit at zoom 1
  const $ = (id) => document.getElementById(id);

  // ---- palettes -----------------------------------------------------------
  const CATEGORY_STYLE = {
    residential: { color: 0x7bb37a }, commerce: { color: 0xe0a458 },
    education: { color: 0x5a9bd4 }, medical: { color: 0xd96c6c },
    industry: { color: 0x8a8f98 }, government: { color: 0xb08ad4 },
    leisure: { color: 0x5cc2a8 }, transit: { color: 0xd4b95a }, mixed: { color: 0xa8a8a8 },
  };
  const CAT_HEX = {
    residential: "#7bb37a", commerce: "#e0a458", education: "#5a9bd4",
    medical: "#d96c6c", industry: "#8a8f98", government: "#b08ad4",
    leisure: "#5cc2a8", transit: "#d4b95a", mixed: "#a8a8a8",
  };
  const ZONE_COLORS = { R: 0x3e5e3d, C: 0x7a5a2e, E: 0x2f5675, M: 0x75383a,
    I: 0x4a4d52, G: 0x5a4575, L: 0x2f6657, T: 0x74663a, X: 0x444444 };
  const TERRAIN_COLORS = { "#": 0x3a3f48, A: 0x4b515c, C: 0x42474f, L: 0x363a41,
    "=": 0x7a5a3a, "~": 0x1d3a5f, "*": 0x1f3a25, r: 0x22321f, c: 0x3a2e18,
    e: 0x1c2d3e, m: 0x3a1f20, i: 0x26282b, g: 0x2c2238, l: 0x173028,
    t: 0x332c16, "+": 0x5a3f86, d: 0x23272e };
  const ROAD_STYLE = { arterial: { w: 3.2, c: 0x69737f }, collector: { w: 2.2, c: 0x4a515c },
    local: { w: 1.4, c: 0x3a4049 }, road: { w: 1.8, c: 0x454b55 } };
  const AGENT_COLORS = [0xdc7d2d, 0x0d8a73, 0x9a4d38, 0x6ea8fe, 0xc84c61,
    0x7b8f27, 0x0083a8, 0xa35b9c, 0xb67d2a, 0x3f7ba6];
  const AGENT_HEX = AGENT_COLORS.map((c) => "#" + c.toString(16).padStart(6, "0"));

  // ---- shared state -------------------------------------------------------
  const state = {
    map: null, trace: null, frames: [], frameIdx: 0,
    playing: false, speedMs: 300,
    catFilter: new Set(),     // hidden categories
    selAgent: null, indoor: null,
    layers: { terrain: true, zone: false, density: false, roads: true,
      metro: true, river: true, nodes: true, labels: false },
    overlayAlpha: 0.55,
  };
  const App = { game: null, map: null, indoor: null };

  // ---- normalize map ------------------------------------------------------
  const num = (v) => (typeof v === "number" ? v : parseFloat(v) || 0);
  function normalizeMap(raw) {
    if (!raw) return null;
    if (raw.type === "FeatureCollection") return fromGeoJSON(raw);
    const src = raw.map && raw.nodes === undefined ? raw.map : raw;
    const nodesIn = src.nodes || {};
    const nodes = Array.isArray(nodesIn) ? nodesIn.slice() : Object.values(nodesIn);
    nodes.forEach((n) => { n.category = n.category || "mixed"; n.grid_x = num(n.grid_x); n.grid_y = num(n.grid_y); });
    const byId = {}; nodes.forEach((n) => { byId[n.id || n.name] = n; });
    return { nodes, byId, edges: src.edges || [], metro_lines: src.metro_lines || [],
      river: src.river || null, bridges: src.bridges || [], overlays: src.overlays || null,
      tile_map: src.tile_map || null, bounds: src.bounds || computeBounds(nodes), scale: src.scale || {} };
  }
  function fromGeoJSON(fc) {
    const nodes = [];
    (fc.features || []).forEach((f) => {
      if (f.geometry && f.geometry.type === "Point") {
        const p = f.properties || {};
        nodes.push({ id: p.id || p.name, name: p.name, category: p.category || "mixed",
          grid_x: f.geometry.coordinates[0], grid_y: f.geometry.coordinates[1] });
      }
    });
    return normalizeMap({ nodes });
  }
  function computeBounds(nodes) {
    if (!nodes.length) return { min_x: 0, min_y: 0, max_x: 10, max_y: 10 };
    let a = Infinity, b = Infinity, c = -Infinity, d = -Infinity;
    nodes.forEach((n) => { a = Math.min(a, n.grid_x); b = Math.min(b, n.grid_y); c = Math.max(c, n.grid_x); d = Math.max(d, n.grid_y); });
    return { min_x: a - 1.5, min_y: b - 1.5, max_x: c + 1.5, max_y: d + 1.5 };
  }
  function nodeVisible(n) { return !state.catFilter.has(n.category); }

  // =========================================================================
  // MAP SCENE
  // =========================================================================
  class MapScene extends Phaser.Scene {
    constructor() { super("map"); }

    create() {
      App.map = this;
      this.dragging = false;
      this.lastClick = 0; this.lastClickXY = null;
      this.layerImgs = {};
      this.nodeHit = [];          // {node, wx, wy}
      this.agentGfx = this.add.graphics().setDepth(50);
      this.agentLabels = [];
      this.gfxStatic = {};
      this.buildAll();
      this.bindCamera();
      this.scale.on("resize", () => { this.fitCamera(); });
    }

    worldX(gx) { return (gx - state.map.bounds.min_x) * PX; }
    worldY(gy) { return (gy - state.map.bounds.min_y) * PX; }

    buildAll() {
      // clear previous
      Object.values(this.layerImgs).forEach((im) => im && im.destroy());
      this.layerImgs = {};
      (this.riverGfx && this.riverGfx.destroy());
      (this.roadGfx && this.roadGfx.destroy());
      (this.metroGfx && this.metroGfx.destroy());
      (this.nodeGfx && this.nodeGfx.destroy());
      this.agentLabels.forEach((t) => t.destroy()); this.agentLabels = [];
      (this.nodeLabelGroup && this.nodeLabelGroup.clear(true, true));

      const m = state.map; if (!m) return;
      const span = m.bounds;
      const W = Math.max(1, Math.round((span.max_x - span.min_x) * PX));
      const H = Math.max(1, Math.round((span.max_y - span.min_y) * PX));
      this.worldW = W; this.worldH = H;

      this.buildTerrainTexture(W, H);
      this.buildOverlayTexture("zone", W, H);
      this.buildOverlayTexture("density", W, H);
      this.buildRiver();
      this.buildRoads();
      this.buildMetro();
      this.buildNodes();
      this.buildNodeLabels();

      this.cameras.main.setBounds(-80, -80, W + 160, H + 160);
      this.fitCamera();
      this.applyLayerVisibility();
      this.refreshHud();
    }

    bakeTexture(key, W, H, drawFn) {
      if (this.textures.exists(key)) this.textures.remove(key);
      const g = this.make.graphics({ x: 0, y: 0, add: false });
      drawFn(g);
      g.generateTexture(key, W, H);
      g.destroy();
      const img = this.add.image(0, 0, key).setOrigin(0, 0);
      return img;
    }

    buildTerrainTexture(W, H) {
      const m = state.map, tm = m.tile_map;
      this.layerImgs.terrain = this.bakeTexture("cm-terrain", W, H, (g) => {
        g.fillStyle(0x11161d, 1); g.fillRect(0, 0, W, H);
        if (!tm || !tm.terrain) return;
        const rows = tm.terrain, h = rows.length, w = rows[0].length;
        const cw = W / w, ch = H / h;
        for (let r = 0; r < h; r++) for (let c = 0; c < w; c++) {
          const col = TERRAIN_COLORS[rows[r][c]]; if (col == null) continue;
          g.fillStyle(col, 1); g.fillRect(c * cw, r * ch, cw + 1, ch + 1);
        }
      }).setDepth(1);
    }

    buildOverlayTexture(kind, W, H) {
      const m = state.map, ov = m.overlays; if (!ov || !ov[kind]) return;
      const rows = ov[kind], h = rows.length, w = rows[0].length, cw = W / w, ch = H / h;
      this.layerImgs[kind] = this.bakeTexture("cm-" + kind, W, H, (g) => {
        for (let r = 0; r < h; r++) for (let c = 0; c < w; c++) {
          const ch0 = rows[r][c]; let col;
          if (kind === "zone") col = ZONE_COLORS[ch0] || 0x333333;
          else { const v = parseInt(ch0, 10) || 0; if (v === 0) continue; col = densityColor(v); }
          g.fillStyle(col, 1); g.fillRect(c * cw, r * ch, cw + 1, ch + 1);
        }
      }).setDepth(kind === "zone" ? 2 : 3);
    }

    buildRiver() {
      const m = state.map, r = m.river; if (!r || !r.path) return;
      const b = m.bounds;
      const pts = r.path.map(([px, py]) => ({ x: this.worldX(b.min_x + px * (b.max_x - b.min_x)),
        y: this.worldY(b.min_y + py * (b.max_y - b.min_y)) }));
      this.riverGfx = this.add.graphics().setDepth(4);
      if (pts.length >= 2) {
        const wpx = Math.max(7, (r.width || 0.08) * (b.max_y - b.min_y) * PX);
        this.riverGfx.lineStyle(wpx, 0x1d3a5f, 1);
        this.riverGfx.beginPath(); this.riverGfx.moveTo(pts[0].x, pts[0].y);
        pts.slice(1).forEach((p) => this.riverGfx.lineTo(p.x, p.y)); this.riverGfx.strokePath();
        this.riverGfx.lineStyle(2, 0x78aadc, 0.3);
        this.riverGfx.beginPath(); this.riverGfx.moveTo(pts[0].x, pts[0].y);
        pts.slice(1).forEach((p) => this.riverGfx.lineTo(p.x, p.y)); this.riverGfx.strokePath();
      }
    }

    buildRoads() {
      const m = state.map;
      this.roadGfx = this.add.graphics().setDepth(6);
      m.edges.forEach((e) => {
        const a = m.byId[e.source], b = m.byId[e.target]; if (!a || !b) return;
        const st = ROAD_STYLE[e.road_type] || ROAD_STYLE.road;
        this.roadGfx.lineStyle(st.w, e.bridge ? 0x8a6a44 : st.c, 1);
        this.roadGfx.beginPath();
        this.roadGfx.moveTo(this.worldX(a.grid_x), this.worldY(a.grid_y));
        this.roadGfx.lineTo(this.worldX(b.grid_x), this.worldY(b.grid_y));
        this.roadGfx.strokePath();
      });
    }

    buildMetro() {
      const m = state.map;
      this.metroGfx = this.add.graphics().setDepth(7);
      (m.metro_lines || []).forEach((line) => {
        const stops = (line.stops || []).map((id) => m.byId[id]).filter(Boolean);
        if (stops.length < 2) return;
        const col = colorToInt(line.color, 0x8f5bd8);
        this.metroGfx.lineStyle(2.6, col, 1);
        this.metroGfx.beginPath();
        stops.forEach((n, i) => { const x = this.worldX(n.grid_x), y = this.worldY(n.grid_y);
          i ? this.metroGfx.lineTo(x, y) : this.metroGfx.moveTo(x, y); });
        this.metroGfx.strokePath();
        this.metroGfx.fillStyle(col, 1);
        stops.forEach((n) => this.metroGfx.fillCircle(this.worldX(n.grid_x), this.worldY(n.grid_y), 3));
      });
    }

    buildNodes() {
      const m = state.map;
      this.nodeGfx = this.add.graphics().setDepth(20);
      this.redrawNodes();
    }
    redrawNodes() {
      const m = state.map, g = this.nodeGfx; g.clear();
      this.nodeHit = [];
      m.nodes.forEach((n) => {
        if (!nodeVisible(n)) return;
        const x = this.worldX(n.grid_x), y = this.worldY(n.grid_y);
        const isHub = n.kind === "hub";
        const rad = isHub ? 6 : 3.6;
        const col = (CATEGORY_STYLE[n.category] || CATEGORY_STYLE.mixed).color;
        if (isHub && n.popularity) { g.fillStyle(col, 0.12); g.fillCircle(x, y, rad + 4 + n.popularity * 4); }
        g.fillStyle(col, 1); g.fillCircle(x, y, rad);
        g.lineStyle(1, 0x000000, 0.5); g.strokeCircle(x, y, rad);
        this.nodeHit.push({ node: n, wx: x, wy: y });
      });
    }

    buildNodeLabels() {
      if (this.nodeLabelGroup) this.nodeLabelGroup.clear(true, true);
      this.nodeLabelGroup = this.add.group();
      const m = state.map;
      m.nodes.forEach((n) => {
        if (n.kind !== "hub") return;
        const t = this.add.text(this.worldX(n.grid_x) + 8, this.worldY(n.grid_y) - 6,
          n.label || n.name || n.id, { fontFamily: "-apple-system, sans-serif", fontSize: "11px", color: "#e7ecf3" })
          .setDepth(21).setVisible(state.layers.labels);
        this.nodeLabelGroup.add(t);
      });
    }

    applyLayerVisibility() {
      const L = state.layers;
      if (this.layerImgs.terrain) this.layerImgs.terrain.setVisible(L.terrain);
      if (this.layerImgs.zone) this.layerImgs.zone.setVisible(L.zone).setAlpha(state.overlayAlpha);
      if (this.layerImgs.density) this.layerImgs.density.setVisible(L.density).setAlpha(state.overlayAlpha);
      if (this.riverGfx) this.riverGfx.setVisible(L.river);
      if (this.roadGfx) this.roadGfx.setVisible(L.roads);
      if (this.metroGfx) this.metroGfx.setVisible(L.metro);
      if (this.nodeGfx) this.nodeGfx.setVisible(L.nodes);
      if (this.nodeLabelGroup) this.nodeLabelGroup.getChildren().forEach((t) => t.setVisible(L.labels));
    }

    fitCamera() {
      const cam = this.cameras.main;
      const vw = this.scale.width, vh = this.scale.height;
      const z = Math.min(vw / (this.worldW + 120), vh / (this.worldH + 120));
      cam.setZoom(Phaser.Math.Clamp(z, 0.05, 4));
      cam.centerOn(this.worldW / 2, this.worldH / 2);
    }

    bindCamera() {
      const cam = this.cameras.main;
      this.input.on("wheel", (p, o, dx, dy) => {
        const f = dy < 0 ? 1.12 : 1 / 1.12;
        const before = cam.getWorldPoint(p.x, p.y);
        cam.setZoom(Phaser.Math.Clamp(cam.zoom * f, 0.05, 6));
        const after = cam.getWorldPoint(p.x, p.y);
        cam.scrollX += before.x - after.x; cam.scrollY += before.y - after.y;
      });
      this.input.on("pointerdown", (p) => { this.dragging = true; this.dragX = p.x; this.dragY = p.y;
        this.scrX = cam.scrollX; this.scrY = cam.scrollY; this.movedFar = false; });
      this.input.on("pointerup", (p) => {
        this.dragging = false;
        const now = performance.now();
        if (!this.movedFar && this.lastClick && now - this.lastClick < 350 &&
            this.lastClickXY && Phaser.Math.Distance.Between(p.x, p.y, this.lastClickXY.x, this.lastClickXY.y) < 12) {
          const wp = cam.getWorldPoint(p.x, p.y); const n = this.pickNode(wp.x, wp.y);
          if (n) enterIndoor(n.id);
          this.lastClick = 0;
        } else { this.lastClick = now; this.lastClickXY = { x: p.x, y: p.y }; }
      });
      this.input.on("pointermove", (p) => {
        const cam2 = this.cameras.main;
        if (this.dragging) {
          cam2.scrollX = this.scrX - (p.x - this.dragX) / cam2.zoom;
          cam2.scrollY = this.scrY - (p.y - this.dragY) / cam2.zoom;
          if (Phaser.Math.Distance.Between(p.x, p.y, this.dragX, this.dragY) > 6) this.movedFar = true;
          hideTooltip(); return;
        }
        const wp = cam2.getWorldPoint(p.x, p.y);
        const n = this.pickNode(wp.x, wp.y);
        if (n) showTooltip(n, p.x, p.y); else hideTooltip();
      });
    }

    pickNode(wx, wy) {
      let best = null, bestD = (16 / this.cameras.main.zoom) ** 2;
      for (const h of this.nodeHit) {
        const d = (h.wx - wx) ** 2 + (h.wy - wy) ** 2;
        if (d < bestD) { bestD = d; best = h.node; }
      }
      return best;
    }

    refreshHud() {
      const m = state.map; if (!m) return;
      let t = `${m.nodes.length} 节点 · ${m.edges.length} 道路`;
      if (state.frames.length) { t += ` · 第 ${state.frameIdx + 1}/${state.frames.length} 帧`; }
      $("hud").textContent = t;
    }

    // ---- agent replay ----
    update() {
      this.drawAgents();
    }
    agentWorldPos(a) {
      const m = state.map, tr = a.travel || {};
      const route = (tr.route || []).map((id) => m.byId[id]).filter(Boolean);
      if (route.length >= 2 && tr.status !== "stationary" && tr.status !== "arrived") {
        const p = Phaser.Math.Clamp(tr.progress != null ? tr.progress : 1, 0, 1);
        const seg = p * (route.length - 1), i = Math.min(route.length - 2, Math.floor(seg)), f = seg - i;
        const A = route[i], B = route[i + 1];
        return { x: this.worldX(A.grid_x + (B.grid_x - A.grid_x) * f), y: this.worldY(A.grid_y + (B.grid_y - A.grid_y) * f) };
      }
      const loc = m.byId[a.resolved_location] || m.byId[a.location] || (route.length ? route[route.length - 1] : null);
      return loc ? { x: this.worldX(loc.grid_x), y: this.worldY(loc.grid_y) } : null;
    }
    drawAgents() {
      const g = this.agentGfx; g.clear();
      this.agentLabels.forEach((t) => t.destroy()); this.agentLabels = [];
      if (!state.frames.length) return;
      const frame = state.frames[state.frameIdx]; if (!frame) return;
      const z = this.cameras.main.zoom;
      (frame.agents || []).forEach((a, i) => {
        const pos = this.agentWorldPos(a); if (!pos) return;
        const col = AGENT_COLORS[(a.agent_id ?? i) % AGENT_COLORS.length];
        const sel = state.selAgent != null && state.selAgent === a.agent_id;
        const inTransit = a.travel && /transit|departed|in_transit/.test(a.travel.status || "");
        if (inTransit && a.travel.route) {
          const route = a.travel.route.map((id) => state.map.byId[id]).filter(Boolean);
          if (route.length >= 2) {
            g.lineStyle(2 / z, col, 0.5); g.beginPath();
            route.forEach((n, k) => { const x = this.worldX(n.grid_x), y = this.worldY(n.grid_y); k ? g.lineTo(x, y) : g.moveTo(x, y); });
            g.strokePath();
          }
        }
        const rad = (sel ? 7 : 5) / z;
        g.fillStyle(col, 0.22); g.fillCircle(pos.x, pos.y, rad + 3 / z);
        g.fillStyle(col, 1); g.fillCircle(pos.x, pos.y, rad);
        g.lineStyle(2 / z, 0x0c0f14, 1); g.strokeCircle(pos.x, pos.y, rad);
        if (sel) { g.lineStyle(1.5 / z, 0xffffff, 1); g.strokeCircle(pos.x, pos.y, rad + 5 / z); }
        const label = this.add.text(pos.x + rad + 3 / z, pos.y, a.name || ("#" + a.agent_id),
          { fontFamily: "-apple-system, sans-serif", fontSize: (11 / z) + "px", color: "#e7ecf3" })
          .setDepth(51).setOrigin(0, 0.5);
        this.agentLabels.push(label);
      });
    }
  }

  // =========================================================================
  // INDOOR SCENE  (pixel room via Graphics)
  // =========================================================================
  const ROOM = roomTable();
  class IndoorScene extends Phaser.Scene {
    constructor() { super("indoor"); }
    init(data) { this.nodeId = data.nodeId; this.wander = {}; }
    create() {
      App.indoor = this;
      this.g = this.add.graphics();
      this.labels = [];
      this.cameras.main.setBackgroundColor("#7cc36a");
      this.scale.on("resize", () => this.draw());
      this.draw();
    }
    update(time) { if (!this._last || time - this._last > 70) { this._last = time; this.draw(); } }

    draw() {
      const g = this.g; g.clear();
      this.labels.forEach((t) => t.destroy()); this.labels = [];
      const m = state.map; if (!m) return;
      const node = m.byId[this.nodeId];
      const layout = roomLayout(node);
      const W = this.scale.width, H = this.scale.height;
      // surround
      g.fillStyle(0x7cc36a, 1); g.fillRect(0, 0, W, H);
      if (!layout.outdoor) grassTufts(g, 0, 0, W, H);
      const bannerH = 52, padX = Math.max(40, W * 0.07), padTop = bannerH + 26, padBot = 48;
      const rx = padX, ry = padTop, rw = W - padX * 2, rh = H - padTop - padBot;
      const wt = 14, doorW = 64, doorX = rx + rw / 2 - doorW / 2;
      drawRoomFloor(g, layout, rx, ry, rw, rh);
      if (!layout.outdoor) {
        wall(g, rx - wt, ry - wt, rw + wt * 2, wt); wall(g, rx - wt, ry, wt, rh); wall(g, rx + rw, ry, wt, rh);
        wall(g, rx - wt, ry + rh, doorX - rx + wt, wt); wall(g, doorX + doorW, ry + rh, rx + rw + wt - (doorX + doorW), wt);
        g.fillStyle(0x7a5a3a, 1); g.fillRect(doorX, ry + rh - 2, doorW, wt + 2);
        g.fillStyle(0x8b6a44, 1); g.fillRect(doorX + 4, ry + rh, doorW - 8, wt - 4);
        const winCount = Math.max(2, Math.floor(rw / 300)), winW = 78;
        for (let i = 0; i < winCount; i++) {
          const wx = rx + (rw / (winCount + 1)) * (i + 1) - winW / 2, wy = ry - wt;
          g.fillStyle(0xbfe1f2, 1); g.fillRect(wx, wy + 2, winW, wt - 4);
          g.fillStyle(0x8fc4e0, 1); g.fillRect(wx, wy + 2, winW, 2);
          g.lineStyle(1, 0x6f757d, 1); g.strokeRect(wx, wy + 2, winW, wt - 4);
        }
      }
      const fr = [];
      layout.furniture.forEach((f) => {
        const fx = rx + f.x * rw, fy = ry + f.y * rh, fw = f.w * rw, fh = f.h * rh;
        drawFurn(g, f.k, fx, fy, fw, fh);
        fr.push({ ...f, cx: fx + fw / 2, cy: fy + fh / 2 });
      });
      // agents present
      let here = [];
      if (state.frames.length) {
        const frame = state.frames[state.frameIdx];
        here = (frame.agents || []).filter((a) => {
          const loc = a.resolved_location || a.location || a.target_location;
          return loc === this.nodeId && (!a.travel || !/transit|departed/.test(a.travel.status || ""));
        });
      }
      const used = new Set();
      here.forEach((a, i) => {
        const slot = activitySlot(a.activity || a.scheduled_activity || a.action);
        let spot = fr.find((f) => f.slot === slot && !used.has(f)) || fr.find((f) => f.slot && !used.has(f));
        if (spot) used.add(spot);
        const tx = spot ? spot.cx : rx + rw * (0.3 + (i % 5) * 0.1);
        const ty = spot ? spot.cy : ry + rh * 0.8;
        const w = this.indoorWander(a, tx, ty, rx + 20, ry + 20, rx + rw - 20, ry + rh - 20);
        const col = AGENT_COLORS[(a.agent_id ?? i) % AGENT_COLORS.length];
        const lying = (slot === "sleep" || slot === "rest") && !w.walking;
        this.drawAgent(g, a, w.x, w.y, col, state.selAgent === a.agent_id, lying);
      });
      // banner
      g.fillStyle(0x1c2630, 0.92); roundRect(g, W / 2 - 300, 12, 600, bannerH, 10);
      const title = this.add.text(W / 2, 12 + bannerH / 2 - 7,
        `${layout.outdoor ? "🌳" : "🏠"}  ${(node && (node.label || node.name)) || this.nodeId}`,
        { fontFamily: "-apple-system, sans-serif", fontStyle: "bold", fontSize: "22px", color: "#f4ede0" }).setOrigin(0.5);
      const sub = this.add.text(W / 2, 12 + bannerH / 2 + 13,
        `${(node && node.category) || ""} · ${here.length} 人在场 · 双击空白或 Esc 返回地图`,
        { fontFamily: "-apple-system, sans-serif", fontSize: "12px", color: "rgba(244,237,224,0.72)" }).setOrigin(0.5);
      this.labels.push(title, sub);
    }

    drawAgent(g, a, x, y, col, sel, lying) {
      g.fillStyle(0x000000, 0.18); g.fillEllipse(x, y + 18, 24, 8);
      const w = 18, h = 26;
      if (lying) {
        g.fillStyle(col, 1); g.fillRect(x - h / 2, y - w / 2, h - 8, w);
        g.fillStyle(0xf0c79a, 1); g.fillCircle(x + h / 2 - 6, y, 7);
      } else {
        g.fillStyle(col, 1); g.fillRect(x - w / 2, y - h / 2 + 8, w, h - 8);
        g.fillStyle(0x000000, 0.18); g.fillRect(x - w / 2, y - h / 2 + 8, w, 4);
        g.fillStyle(0xf0c79a, 1); g.fillCircle(x, y - h / 2 + 4, 7);
        g.fillStyle(0x3a2a1a, 1); g.fillRect(x - 6, y - h / 2, 12, 4);
      }
      if (sel) { g.lineStyle(2, 0xffffff, 1); g.strokeEllipse(x, y + 18, 30, 12); }
      const text = `${initials(a.name, a.agent_id)}: ${actEmoji(a.activity || a.scheduled_activity || a.action)}`;
      const lbl = this.add.text(x, y - h / 2 - 20, text,
        { fontFamily: "-apple-system, sans-serif", fontSize: "13px", color: "#1e2c2c",
          backgroundColor: "#ffffff", padding: { x: 7, y: 4 } }).setOrigin(0.5).setDepth(5);
      this.labels.push(lbl);
    }

    indoorWander(a, tx, ty, minX, minY, maxX, maxY) {
      let s = this.wander[a.agent_id];
      const now = performance.now();
      if (!s) { s = { x: tx, y: ty, tx, ty, walking: false, hold: now + 2000 + Math.random() * 3000 }; this.wander[a.agent_id] = s; return s; }
      if (Math.abs(tx - s.tx) + Math.abs(ty - s.ty) > 6) { s.tx = tx; s.ty = ty; s.walking = true; }
      if (!s.walking && now > s.hold) {
        s.tx = Phaser.Math.Clamp(tx + (Math.random() - 0.5) * 90, minX, maxX);
        s.ty = Phaser.Math.Clamp(ty + (Math.random() - 0.5) * 50, minY, maxY); s.walking = true;
      }
      const dx = s.tx - s.x, dy = s.ty - s.y, d = Math.hypot(dx, dy);
      if (d < 2) { s.x = s.tx; s.y = s.ty; if (s.walking) { s.walking = false; s.hold = now + 2500 + Math.random() * 4000; } }
      else { const step = Math.min(d, 1.6); s.x += dx / d * step; s.y += dy / d * step; }
      return s;
    }
  }

  // ---- indoor pixel helpers (Graphics-based) ------------------------------
  function px(g, x, y, w, h, c, a) { g.fillStyle(c, a == null ? 1 : a); g.fillRect(x, y, w, h); }
  function roundRect(g, x, y, w, h, r) {
    g.fillRoundedRect(x, y, w, h, r);
  }
  function grassTufts(g, x, y, w, h) {
    let seed = 991;
    const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
    for (let i = 0; i < (w * h) / 5000; i++) {
      const gx = x + rnd() * w, gy = y + rnd() * h, r = rnd();
      if (r < 0.7) { px(g, gx, gy, 4, 2, 0x5a964b, 0.5); px(g, gx + 1, gy - 2, 2, 2, 0x5a964b, 0.5); }
      else if (r < 0.85) px(g, gx, gy, 3, 3, 0xe86b6b);
      else px(g, gx, gy, 3, 3, 0xe8c84e);
    }
  }
  function drawRoomFloor(g, layout, x, y, w, h) {
    px(g, x, y, w, h, layout.floor);
    if (layout.outdoor) { grassTufts(g, x, y, w, h); return; }
    if (layout.tiled) {
      const t = 26;
      for (let yy = y, ry = 0; yy < y + h; yy += t, ry++)
        for (let xx = x, rx = 0; xx < x + w; xx += t, rx++)
          if ((rx + ry) % 2 === 0) px(g, xx, yy, Math.min(t, x + w - xx), Math.min(t, y + h - yy), 0xffffff, 0.05);
      g.lineStyle(1, 0x28374633 & 0xffffff, 0.07);
      for (let xx = x; xx <= x + w; xx += t) { g.lineBetween(xx, y, xx, y + h); }
      for (let yy = y; yy <= y + h; yy += t) { g.lineBetween(x, yy, x + w, yy); }
    } else {
      const ph = 20;
      for (let yy = y, row = 0; yy < y + h; yy += ph, row++) {
        if (row % 2) px(g, x, yy, w, Math.min(ph, y + h - yy), 0x78502855 & 0xffffff, 0.06);
        g.lineStyle(1, 0x50321e, 0.18); g.lineBetween(x, yy, x + w, yy);
        const off = (row % 2) * 64; g.lineStyle(1, 0x50321e, 0.10);
        for (let xx = x + off; xx < x + w; xx += 128) g.lineBetween(xx, yy, xx, Math.min(yy + ph, y + h));
      }
    }
  }
  function wall(g, x, y, w, h) {
    px(g, x, y, w, h, 0x9aa0a8); px(g, x, y, w, Math.min(3, h), 0xc4c9cf);
    px(g, x, y + h - Math.min(3, h), w, Math.min(3, h), 0x6f757d);
  }
  function drawFurn(g, k, x, y, w, h) {
    switch (k) {
      case "bed":
        px(g, x, y, w, h, 0x8b5a2b); px(g, x + 4, y + 4, w - 8, h - 8, 0xfff5d6);
        px(g, x + 6, y + 6, w - 12, h * 0.3, 0xd96b4e); px(g, x + 8, y + h - Math.min(20, h * 0.3), w - 16, 12, 0xfff8e0); break;
      case "nightstand": px(g, x, y, w, h, 0xa87042); px(g, x + 2, y + 2, w - 4, h - 4, 0xc89060); break;
      case "kitchen": px(g, x, y, w, h, 0xcfc3a0); px(g, x, y, w, 4, 0xe8dcc0);
        for (let i = 0; i < 3; i++) px(g, x + 6 + i * (w / 3), y + h * 0.4, w / 6, h * 0.4, 0x9a8a64); break;
      case "fridge": px(g, x, y, w, h, 0xe8e8e0); px(g, x, y + h * 0.45, w, 2, 0xb8b8b0); px(g, x + w - 4, y + h * 0.2, 2, h * 0.18, 0x9a9a92); break;
      case "table": px(g, x, y, w, h, 0xb07a45); px(g, x + 3, y + 3, w - 6, h - 6, 0xc89058); break;
      case "coffee_table": px(g, x, y, w, h, 0x7a5331); px(g, x + 2, y + 2, w - 4, h - 4, 0x8b5a2b); px(g, x + w / 2 - 4, y + h / 2 - 3, 8, 6, 0xffffff); break;
      case "chair": px(g, x, y, w, h, 0xc84c4c); px(g, x + 2, y, w - 4, 3, 0xa83a3a); break;
      case "desk": px(g, x, y, w, h, 0xcaa06a); px(g, x + 3, y + 3, w - 6, h - 6, 0xd9b483); px(g, x + w * 0.6, y + h * 0.3, w * 0.28, h * 0.4, 0x3a4658); break;
      case "sofa": px(g, x, y, w, h, 0x5a67a8); px(g, x + 3, y + 3, w - 6, h - 6, 0x6e7cc0); px(g, x, y, 6, h, 0x4a5690); px(g, x + w - 6, y, 6, h, 0x4a5690); break;
      case "tv": px(g, x, y, w, h, 0x1c2630); px(g, x + 2, y + 2, w - 4, h - 4, 0x2e4a6a); break;
      case "bookshelf": case "shelf": {
        px(g, x, y, w, h, 0x8b5a2b);
        const cols = [0xc84c61, 0x5a9bd4, 0x7b8f27, 0xe0a458, 0x5cc2a8];
        for (let i = 0, bx = x + 2; bx < x + w - 3; i++, bx += 5) px(g, bx, y + 2, 4, h - 4, cols[i % cols.length]);
        break;
      }
      case "counter": px(g, x, y, w, h, 0x7d5331); px(g, x, y, w, 5, 0xa07853); break;
      case "coffee_machine": px(g, x, y, w, h, 0xbfb6a3); px(g, x + 2, y + 2, w - 4, h * 0.5, 0x7a7064); break;
      case "chalkboard": px(g, x, y, w, h, 0x3a4d3a); px(g, x + 3, y + 3, w - 6, h - 6, 0x2e3e2e); break;
      case "podium": px(g, x, y, w, h, 0x8b5a2b); px(g, x + 2, y + 2, w - 4, h * 0.6, 0xa87042); break;
      case "checkout": px(g, x, y, w, h, 0x7d5331); px(g, x, y, w, 6, 0xa07853); px(g, x + w * 0.1, y + 6, w * 0.3, h * 0.5, 0x3a3a3a); break;
      case "plant": px(g, x + w * 0.2, y + h * 0.5, w * 0.6, h * 0.5, 0x8b5a2b); g.fillStyle(0x5cc2a8, 1); g.fillCircle(x + w / 2, y + h * 0.4, w * 0.45); break;
      case "tree": px(g, x + w * 0.4, y + h * 0.6, w * 0.2, h * 0.4, 0x7a5331); g.fillStyle(0x4e8c3a, 1); g.fillCircle(x + w / 2, y + h * 0.4, w * 0.5); break;
      case "fountain": g.fillStyle(0x9aa0a8, 1); g.fillCircle(x + w / 2, y + h / 2, Math.min(w, h) / 2); g.fillStyle(0x5aa6d8, 1); g.fillCircle(x + w / 2, y + h / 2, Math.min(w, h) / 2 - 4); break;
      case "bench": px(g, x, y, w, h, 0xbfa074); px(g, x, y, w, 2, 0xa8895c); break;
      default: px(g, x, y, w, h, 0xbfb6a3);
    }
  }

  // ---- room layouts -------------------------------------------------------
  function gridDesks() {
    const out = [];
    for (let r = 0; r < 2; r++) for (let c = 0; c < 4; c++) {
      out.push({ k: "desk", x: 0.15 + c * 0.19, y: 0.38 + r * 0.20, w: 0.12, h: 0.10, slot: "study" });
      out.push({ k: "chair", x: 0.18 + c * 0.19, y: 0.50 + r * 0.20, w: 0.06, h: 0.07, slot: "sit" });
    }
    return out;
  }
  function shelfRow() { const out = []; for (let c = 0; c < 5; c++) out.push({ k: "shelf", x: 0.08 + c * 0.14, y: 0.20, w: 0.08, h: 0.50 }); return out; }
  function roomTable() {
    const R = {
      residential: { floor: 0xf0d9a8, tiled: false, furniture: [
        { k: "bed", x: 0.07, y: 0.30, w: 0.24, h: 0.30, slot: "sleep" },
        { k: "nightstand", x: 0.32, y: 0.36, w: 0.07, h: 0.12 },
        { k: "kitchen", x: 0.55, y: 0.16, w: 0.40, h: 0.14 },
        { k: "fridge", x: 0.90, y: 0.18, w: 0.07, h: 0.20 },
        { k: "table", x: 0.62, y: 0.42, w: 0.20, h: 0.18, slot: "eat" },
        { k: "chair", x: 0.58, y: 0.60, w: 0.07, h: 0.09, slot: "sit" },
        { k: "chair", x: 0.79, y: 0.60, w: 0.07, h: 0.09, slot: "sit" },
        { k: "sofa", x: 0.42, y: 0.74, w: 0.30, h: 0.13, slot: "watch" },
        { k: "coffee_table", x: 0.50, y: 0.88, w: 0.15, h: 0.07 },
        { k: "tv", x: 0.85, y: 0.74, w: 0.10, h: 0.09 },
        { k: "plant", x: 0.78, y: 0.87, w: 0.07, h: 0.11 },
        { k: "bookshelf", x: 0.05, y: 0.74, w: 0.24, h: 0.09, slot: "read" },
      ] },
      education: { floor: 0xd8c89a, tiled: false, furniture: [
        { k: "chalkboard", x: 0.20, y: 0.05, w: 0.60, h: 0.09 },
        { k: "podium", x: 0.46, y: 0.18, w: 0.09, h: 0.10 },
        ...gridDesks(),
        { k: "bookshelf", x: 0.05, y: 0.86, w: 0.42, h: 0.09, slot: "read" },
        { k: "plant", x: 0.88, y: 0.85, w: 0.08, h: 0.12 },
      ] },
      commerce: { floor: 0xe8d8b8, tiled: true, furniture: [
        ...shelfRow(),
        { k: "checkout", x: 0.78, y: 0.55, w: 0.18, h: 0.11, slot: "shop" },
        { k: "fridge", x: 0.86, y: 0.20, w: 0.10, h: 0.30 },
        { k: "plant", x: 0.78, y: 0.80, w: 0.08, h: 0.13 },
      ] },
      medical: { floor: 0xe8eef0, tiled: true, furniture: [
        { k: "bed", x: 0.07, y: 0.20, w: 0.24, h: 0.16, slot: "rest" },
        { k: "bed", x: 0.07, y: 0.44, w: 0.24, h: 0.16, slot: "rest" },
        { k: "bed", x: 0.07, y: 0.68, w: 0.24, h: 0.16, slot: "rest" },
        { k: "desk", x: 0.62, y: 0.34, w: 0.22, h: 0.13, slot: "consult" },
        { k: "chair", x: 0.60, y: 0.52, w: 0.08, h: 0.10, slot: "sit" },
        { k: "shelf", x: 0.88, y: 0.34, w: 0.09, h: 0.40 },
        { k: "plant", x: 0.66, y: 0.78, w: 0.08, h: 0.13 },
      ] },
      government: { floor: 0xdfd6c2, tiled: false, furniture: [
        { k: "desk", x: 0.16, y: 0.28, w: 0.20, h: 0.13, slot: "work" },
        { k: "desk", x: 0.42, y: 0.28, w: 0.20, h: 0.13, slot: "work" },
        { k: "desk", x: 0.68, y: 0.28, w: 0.20, h: 0.13, slot: "work" },
        { k: "chair", x: 0.20, y: 0.44, w: 0.08, h: 0.10, slot: "sit" },
        { k: "chair", x: 0.46, y: 0.44, w: 0.08, h: 0.10, slot: "sit" },
        { k: "chair", x: 0.72, y: 0.44, w: 0.08, h: 0.10, slot: "sit" },
        { k: "bookshelf", x: 0.05, y: 0.80, w: 0.24, h: 0.09, slot: "read" },
        { k: "plant", x: 0.86, y: 0.78, w: 0.08, h: 0.13 },
      ] },
      leisure: { floor: 0xe6d3a8, tiled: false, furniture: [
        { k: "counter", x: 0.06, y: 0.16, w: 0.55, h: 0.11, slot: "order" },
        { k: "coffee_machine", x: 0.10, y: 0.05, w: 0.10, h: 0.11 },
        { k: "table", x: 0.24, y: 0.48, w: 0.15, h: 0.13, slot: "eat" },
        { k: "chair", x: 0.21, y: 0.63, w: 0.07, h: 0.08, slot: "sit" },
        { k: "chair", x: 0.36, y: 0.63, w: 0.07, h: 0.08, slot: "sit" },
        { k: "table", x: 0.58, y: 0.48, w: 0.15, h: 0.13, slot: "eat" },
        { k: "chair", x: 0.55, y: 0.63, w: 0.07, h: 0.08, slot: "sit" },
        { k: "chair", x: 0.70, y: 0.63, w: 0.07, h: 0.08, slot: "sit" },
        { k: "plant", x: 0.86, y: 0.42, w: 0.08, h: 0.16 },
        { k: "plant", x: 0.86, y: 0.74, w: 0.08, h: 0.16 },
      ] },
      leisure_park: { floor: 0x7da35d, tiled: false, outdoor: true, furniture: [
        { k: "tree", x: 0.10, y: 0.28, w: 0.13, h: 0.22 },
        { k: "tree", x: 0.77, y: 0.28, w: 0.13, h: 0.22 },
        { k: "fountain", x: 0.42, y: 0.40, w: 0.16, h: 0.18, slot: "rest" },
        { k: "bench", x: 0.25, y: 0.66, w: 0.15, h: 0.06, slot: "rest" },
        { k: "bench", x: 0.60, y: 0.66, w: 0.15, h: 0.06, slot: "rest" },
      ] },
    };
    R.industry = R.commerce; R.transit = R.government; R.mixed = R.residential;
    return R;
  }
  function roomLayout(node) {
    const name = String((node && (node.label || node.name || node.id)) || "").toLowerCase();
    if (/park|公园|绿地|广场|botanical|garden|trail|greenbelt/.test(name) && ROOM.leisure_park) return ROOM.leisure_park;
    const cat = (node && node.category) || "residential";
    return ROOM[cat] || ROOM.residential;
  }
  function activitySlot(text) {
    const s = String(text || "");
    if (/睡|休息|床|sleep|rest/i.test(s)) return "sleep";
    if (/咖啡|coffee|order|点单/i.test(s)) return "order";
    if (/吃|饭|餐|eat|dining/i.test(s)) return "eat";
    if (/读|看书|book|read|阅读/i.test(s)) return "read";
    if (/看电视|tv|watch/i.test(s)) return "watch";
    if (/学|课|study/i.test(s)) return "study";
    if (/买|shop|购物/i.test(s)) return "shop";
    if (/工作|办公|work|consult|看病|诊/i.test(s)) return "work";
    return null;
  }
  const ACT_EMOJI = [
    [/睡|sleep|休息|rest/i, "💤"], [/吃|饭|餐|eat/i, "🍽️"], [/咖啡|coffee/i, "☕"],
    [/工作|办公|work/i, "💻"], [/学|课|study|read|看书|阅读/i, "📚"], [/买|购物|shop/i, "🛒"],
    [/锻炼|健身|run|gym|exercise/i, "💪"], [/看电视|tv|watch|娱乐/i, "📺"],
    [/医|诊|看病|consult/i, "🩺"], [/散步|walk|公园|park/i, "🌳"],
  ];
  function actEmoji(text) { const s = String(text || ""); for (const [re, e] of ACT_EMOJI) if (re.test(s)) return e; return "💬"; }
  function initials(name, id) {
    const n = String(name || "").trim(); if (!n) return "#" + (id ?? "?");
    const ascii = n.match(/[A-Za-z]+/g); if (ascii) return ascii.map((w) => w[0].toUpperCase()).join("").slice(0, 2);
    return n.slice(0, 2);
  }
  function densityColor(v) {
    const t = v / 9; const r = Math.round(40 + t * 200);
    const g = Math.round(60 + (1 - Math.abs(t - 0.5) * 2) * 120); const b = Math.round(150 - t * 120);
    return (r << 16) | (g << 8) | b;
  }
  function colorToInt(hex, def) {
    if (typeof hex === "number") return hex;
    if (typeof hex !== "string") return def;
    const h = hex.replace("#", ""); const n = parseInt(h, 16); return isNaN(n) ? def : n;
  }

  // ---- enter / exit indoor ------------------------------------------------
  function enterIndoor(nodeId) {
    if (!App.game) return;
    state.indoor = nodeId; hideTooltip();
    $("back-btn").classList.add("show");
    $("hud").textContent = "室内模式 · 双击空白或 Esc 返回";
    App.game.scene.sleep("map");
    App.game.scene.run("indoor", { nodeId });
  }
  function exitIndoor() {
    if (!App.game || !state.indoor) return;
    state.indoor = null;
    $("back-btn").classList.remove("show");
    App.game.scene.stop("indoor");
    App.game.scene.wake("map");
    if (App.map) App.map.refreshHud();
  }

  // ---- DOM: tooltip / legend / filters / agent list -----------------------
  function showTooltip(n, sx, sy) {
    const tt = $("tooltip"); const rows = [];
    const add = (k, v) => { if (v !== undefined && v !== null && v !== "") rows.push(`<div class="t-row"><span>${k}</span><span>${v}</span></div>`); };
    add("分类", n.category); add("类型", n.kind); add("片区", n.district);
    if (n.capacity != null) add("容量", n.capacity);
    if (n.popularity != null) add("热度", n.popularity);
    if (n.density != null) add("密度", n.density);
    if (n.lat != null && n.lng != null) add("坐标", `${(+n.lat).toFixed(4)}, ${(+n.lng).toFixed(4)}`);
    tt.innerHTML = `<div class="t-name">${n.label || n.name || n.id}</div>${rows.join("")}`;
    const r = $("stage").getBoundingClientRect();
    let x = sx + 14, y = sy + 14;
    if (x + 260 > r.width) x = sx - 260; if (y + 170 > r.height) y = sy - 170;
    tt.style.left = x + "px"; tt.style.top = y + "px"; tt.style.opacity = 1;
  }
  function hideTooltip() { $("tooltip").style.opacity = 0; }

  function buildLegend() {
    const el = $("legend-items"); el.innerHTML = "";
    Object.entries(CAT_HEX).forEach(([cat, color]) => {
      const li = document.createElement("div"); li.className = "li";
      li.innerHTML = `<span class="swatch" style="background:${color}"></span>${cat}`;
      el.appendChild(li);
    });
  }
  function buildCatFilter() {
    const el = $("cat-filter"); el.innerHTML = "";
    const cats = [...new Set(state.map.nodes.map((n) => n.category))].sort();
    cats.forEach((cat) => {
      const chip = document.createElement("label"); chip.className = "chip";
      chip.innerHTML = `<input type="checkbox" checked><span class="swatch" style="background:${CAT_HEX[cat] || "#a8a8a8"}"></span>${cat}`;
      chip.querySelector("input").addEventListener("change", (e) => {
        if (e.target.checked) state.catFilter.delete(cat); else state.catFilter.add(cat);
        if (App.map) App.map.redrawNodes();
      });
      el.appendChild(chip);
    });
  }
  function buildAgentList() {
    const el = $("agent-list");
    const agents = state.trace && state.trace.agents ? state.trace.agents : [];
    if (!agents.length) { el.className = "empty-hint small"; el.textContent = "该轨迹无 agent"; return; }
    el.className = ""; el.innerHTML = "";
    agents.forEach((a, i) => {
      const color = AGENT_HEX[(a.id ?? i) % AGENT_HEX.length];
      const pill = document.createElement("div"); pill.className = "agent-pill";
      pill.innerHTML = `<span class="dot" style="background:${color}"></span><div><div>${a.name || "#" + a.id}</div><div class="small">家 ${a.home || "?"} · 班 ${a.workplace || "?"}</div></div>`;
      pill.addEventListener("click", () => {
        state.selAgent = state.selAgent === a.id ? null : a.id;
        [...el.children].forEach((c) => c.classList.remove("sel"));
        if (state.selAgent != null) pill.classList.add("sel");
      });
      el.appendChild(pill);
    });
  }

  // ---- load map / trace ---------------------------------------------------
  function loadMap(raw, label) {
    state.map = normalizeMap(raw); if (!state.map) return;
    $("map-meta").textContent = label || `${state.map.nodes.length} 节点 · ${state.map.edges.length} 道路 · ${state.map.metro_lines.length} 地铁线`;
    buildCatFilter();
    if (App.map) App.map.buildAll();
    $("data-status").textContent = "地图已载入：" + (label || "");
  }
  function loadTrace(raw) {
    state.trace = raw; state.frames = raw.frames || [];
    if ((!state.map || !state.map.nodes.length) && raw.map) loadMap(raw, "来自轨迹的地图");
    buildAgentList();
    const tp = $("transport");
    if (state.frames.length) {
      tp.classList.remove("hidden");
      $("scrub").max = state.frames.length - 1; setFrame(0);
      $("data-status").textContent = `轨迹已载入：${state.frames.length} 帧 · ${(raw.agents || []).length} agent`;
    } else { tp.classList.add("hidden"); $("data-status").textContent = "该轨迹无帧数据"; }
  }
  function setFrame(i) {
    state.frameIdx = Math.max(0, Math.min(state.frames.length - 1, i));
    $("scrub").value = state.frameIdx;
    const f = state.frames[state.frameIdx];
    if (f) $("clock").innerHTML = `Day ${f.day ?? "—"} · <b>${f.time || "--:--"}</b> ${f.weekday || ""}`;
    if (App.map) App.map.refreshHud();
  }
  function togglePlay() {
    if (!state.frames.length) return;
    state.playing = !state.playing; $("btn-play").textContent = state.playing ? "❚❚" : "▶";
  }
  function readJSON(file, cb) {
    if (!file) return;
    const fr = new FileReader();
    fr.onload = () => { try { cb(JSON.parse(fr.result), file.name); } catch (e) { alert("解析失败: " + e.message); } };
    fr.readAsText(file);
  }

  // ---- wire DOM -----------------------------------------------------------
  function wire() {
    const map = { "l-terrain": "terrain", "l-zone": "zone", "l-density": "density",
      "l-roads": "roads", "l-metro": "metro", "l-river": "river", "l-nodes": "nodes", "l-labels": "labels" };
    Object.entries(map).forEach(([id, key]) => {
      $(id).addEventListener("change", (e) => { state.layers[key] = e.target.checked; if (App.map) App.map.applyLayerVisibility(); });
    });
    $("overlay-alpha").addEventListener("input", (e) => { state.overlayAlpha = e.target.value / 100; if (App.map) App.map.applyLayerVisibility(); });
    $("f-map").addEventListener("change", (e) => readJSON(e.target.files[0], (d, name) => loadMap(d, name)));
    $("f-trace").addEventListener("change", (e) => readJSON(e.target.files[0], (d) => loadTrace(d)));
    $("btn-play").addEventListener("click", togglePlay);
    $("scrub").addEventListener("input", (e) => { state.playing = false; $("btn-play").textContent = "▶"; setFrame(+e.target.value); });
    $("speed").addEventListener("change", (e) => { state.speedMs = +e.target.value; });
    $("btn-fit").addEventListener("click", () => { if (App.map) App.map.fitCamera(); });
    $("back-btn").addEventListener("click", exitIndoor);
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && state.indoor) { exitIndoor(); return; }
      if (e.code === "Space") { e.preventDefault(); togglePlay(); }
      else if (e.key === "r" || e.key === "R") { if (App.map) App.map.fitCamera(); }
      else if (e.key === "ArrowRight" && state.frames.length) { state.playing = false; setFrame(state.frameIdx + 1); }
      else if (e.key === "ArrowLeft" && state.frames.length) { state.playing = false; setFrame(state.frameIdx - 1); }
    });
    // double-click empty space inside indoor → exit
    $("game").addEventListener("dblclick", () => { if (state.indoor) exitIndoor(); });
    // playback clock driver
    let last = 0;
    function loop(ts) {
      if (state.playing && state.frames.length) {
        if (!last) last = ts;
        if (ts - last >= state.speedMs) { last = ts; let n = state.frameIdx + 1; if (n >= state.frames.length) n = 0; setFrame(n); }
      } else last = 0;
      requestAnimationFrame(loop);
    }
    requestAnimationFrame(loop);
  }

  // ---- boot ---------------------------------------------------------------
  function boot() {
    buildLegend(); wire();
    // embedded map
    let embedded = null;
    try {
      const raw = $("bootstrap-data").textContent.trim();
      if (raw && raw[0] === "{") embedded = JSON.parse(raw);
    } catch (e) { /* ignore */ }
    if (embedded) { state.map = normalizeMap(embedded);
      $("map-meta").textContent = `${state.map.nodes.length} 节点 · ${state.map.edges.length} 道路`;
      buildCatFilter();
    } else { $("map-meta").textContent = "请载入地图 JSON"; }

    App.game = new Phaser.Game({
      type: Phaser.AUTO, parent: "game", backgroundColor: "#0c0f14",
      scale: { mode: Phaser.Scale.RESIZE, width: "100%", height: "100%" },
      render: { pixelArt: false, antialias: true },
      scene: [MapScene, IndoorScene],
    });
    App.game.scene.start("map");
  }

  if (typeof Phaser === "undefined") {
    $("map-meta").textContent = "Phaser 未加载（缺 site/vendor/phaser.min.js）";
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else { boot(); }

  // expose for headless tests
  window.__CITYMAP__ = { state, App, normalizeMap, loadMap, loadTrace, enterIndoor, exitIndoor,
    roomLayout, activitySlot, MapScene, IndoorScene };
})();
