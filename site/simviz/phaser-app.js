/* GAWorld simviz — Phaser 3 edition.
 *
 * Village replay + pixel indoor rooms rendered with Phaser. Outdoor uses the
 * tuxmon tileset (grass/water/trees/buildings) + misa character atlas; indoor
 * uses Graphics-drawn pixel furniture. Reuses simviz's trace JSON shape:
 *   trace.map {nodes[],edges[],metro_lines[],river,bridges,tile_map,bounds},
 *   trace.agents[], trace.frames[] (frame.agents[].{location,travel,activity…}).
 *
 * DOM controls from index.html drive it: play/pause, timeline, speed,
 * village/indoor toggle, data path + reload.
 */
(function () {
  "use strict";
  if (typeof Phaser === "undefined") return;
  const indoorOnly = !!(document.currentScript && document.currentScript.hasAttribute("data-indoor-only"));
  const $ = (id) => document.getElementById(id);
  const DEFAULT_DATA_PATH = "../../output/visualization/simulation_trace.json";

  // tuxmon source rects (px) — 768x960 sheet, 32px tiles.
  const TILE = {
    grass: [32, 32, 32, 32], sand: [288, 32, 32, 32], water: [352, 256, 32, 32],
    flower_red: [192, 0, 32, 32], flower_yellow: [192, 128, 32, 32],
    tree: [32, 192, 32, 64], bush: [288, 288, 32, 32], fountain: [256, 320, 96, 64],
    b_school: [0, 416, 192, 128], b_cafe: [448, 416, 128, 96], b_medical: [576, 448, 96, 96],
    b_house_wood: [288, 544, 96, 96], b_shop: [288, 416, 128, 96],
    b_house_red: [384, 736, 96, 96], b_house_tan: [0, 736, 96, 96],
  };
  const CAT_BUILDING = { residential: "b_house_wood", commerce: "b_shop", education: "b_school",
    medical: "b_medical", leisure: "b_cafe", government: "b_house_tan", mixed: "b_house_red",
    industry: "b_shop", transit: "b_house_tan" };
  const AGENT_COLORS = [0xdc7d2d, 0x0d8a73, 0x9a4d38, 0x6ea8fe, 0xc84c61,
    0x7b8f27, 0x0083a8, 0xa35b9c, 0xb67d2a, 0x3f7ba6];

  const TILE_PX = 32;          // world tile size
  const state = {
    trace: null, frames: [], frameIdx: 0, agents: [],
    playing: false, speed: 1, view: "village", indoorLoc: null,
    selectedId: null, dataPath: DEFAULT_DATA_PATH, live: true, pollTimer: null,
  };
  const App = { game: null, village: null, indoor: null };

  // ---- activity → emoji / slot (shared) ----
  const ACT_EMOJI = [
    [/刷牙|洗漱|brush/i, "🪥"], [/上厕所|厕所|卫生间|如厕|toilet/i, "🚽"], [/做饭|做菜|烹饪|cook/i, "🍳"],
    [/钢琴|弹琴|piano/i, "🎹"], [/洗手|wash/i, "🧼"],
    [/睡|sleep|休息/i, "💤"], [/早饭|早餐|breakfast/i, "🍳"], [/午饭|lunch/i, "🍱"],
    [/晚饭|dinner/i, "🍲"], [/吃|饭|餐|eat/i, "🍽️"], [/咖啡|coffee/i, "☕"], [/茶|tea/i, "🍵"],
    [/上班|工作|办公|work/i, "💻"], [/学|课|school|study/i, "📚"], [/读|书|read/i, "📖"],
    [/会议|meeting/i, "📋"], [/买|购物|shop/i, "🛒"], [/银行|bank/i, "💰"], [/聊|社交|chat/i, "💬"],
    [/跑步|run/i, "🏃"], [/散步|walk/i, "🚶"], [/健身|gym|exercise/i, "💪"], [/瑜伽|yoga/i, "🧘"],
    [/玩|游戏|game/i, "🎮"], [/音乐|music/i, "🎵"], [/电视|tv/i, "📺"], [/电影|movie/i, "🎬"],
    [/洗澡|shower/i, "🚿"], [/医|诊|看病/i, "🩺"], [/公园|park/i, "🌳"],
  ];
  function actEmoji(t) { const s = String(t || ""); for (const [re, e] of ACT_EMOJI) if (re.test(s)) return e; return "💬"; }
  function activitySlot(text) {
    const s = String(text || "");
    if (/刷牙|洗漱|洗手|brush|wash/i.test(s)) return "wash";
    if (/上厕所|厕所|卫生间|如厕|toilet/i.test(s)) return "toilet";
    if (/做饭|做菜|烹饪|cook/i.test(s)) return "cook";
    if (/健身|锻炼|运动|跑步|exercise|workout|treadmill|jog/i.test(s)) return "exercise";
    if (/钢琴|弹琴|piano|音乐|music/i.test(s)) return "music";
    if (/睡|休息|床|sleep|rest/i.test(s)) return "sleep";
    if (/咖啡|coffee|order|点单|点餐/i.test(s)) return "order";
    if (/开会|会议|meeting/i.test(s)) return "meeting";
    if (/看病|问诊|consult|诊/i.test(s)) return "consult";
    if (/吃|饭|餐|eat|用餐/i.test(s)) return "eat";
    if (/读|看书|book|read|阅读/i.test(s)) return "read";
    if (/看电视|tv|watch/i.test(s)) return "watch";
    if (/学|课|study/i.test(s)) return "study";
    if (/买|shop|购物/i.test(s)) return "shop";
    if (/工作|办公|work/i.test(s)) return "work";
    return null;
  }
  function initials(name, id) {
    const n = String(name || "").trim(); if (!n) return "#" + (id ?? "?");
    const a = n.match(/[A-Za-z]+/g); if (a) return a.map((w) => w[0].toUpperCase()).join("").slice(0, 2);
    return n.slice(0, 2);
  }
  function agentColor(id) { return AGENT_COLORS[Math.abs(Number(id || 0)) % AGENT_COLORS.length]; }

  // Indoor furniture + room geometry now live in the spatial tree
  // (spatial-tree.js → window.GAWorldSpatial). The IndoorScene below walks
  // that tree per building to draw a full multi-room floor plan.

  // ===== VILLAGE SCENE =====
  class VillageScene extends Phaser.Scene {
    constructor() { super("village"); }
    preload() {
      this.load.spritesheet("tux", "./assets/tuxmon.png", { frameWidth: 32, frameHeight: 32 });
      this.load.atlas("misa", "./assets/misa.png", "./assets/misa.json");
    }
    create() {
      App.village = this;
      this.tux = this.textures.get("tux") ? null : null;
      this.layout = null;
      this.agentSprites = {};
      this.agentLabels = {};
      this.makeMisaAnims();
      this.gGround = this.add.graphics().setDepth(0);
      this.gRoads = this.add.graphics().setDepth(2);
      this.bldgLayer = this.add.container(0, 0).setDepth(3);
      this.agentLayer = this.add.container(0, 0).setDepth(10);
      this.bindCamera();
      if (state.trace) this.buildVillage();
      this.scale.on("resize", () => this.fit());
    }
    makeMisaAnims() {
      const dirs = ["front", "back", "left", "right"];
      dirs.forEach((d) => {
        const key = "walk-" + d;
        if (this.anims.exists(key)) return;
        const frames = [0, 1, 2, 3].map((i) => ({ key: "misa", frame: `misa-${d}-walk.00${i}` }));
        this.anims.create({ key, frames, frameRate: 8, repeat: -1 });
      });
    }
    bindCamera() {
      const cam = this.cameras.main;
      this.input.on("wheel", (p, o, dx, dy) => {
        const f = dy < 0 ? 1.12 : 1 / 1.12;
        const b = cam.getWorldPoint(p.x, p.y);
        cam.setZoom(Phaser.Math.Clamp(cam.zoom * f, 0.1, 4));
        const a = cam.getWorldPoint(p.x, p.y); cam.scrollX += b.x - a.x; cam.scrollY += b.y - a.y;
      });
      this.input.on("pointerdown", (p) => { this.drag = true; this.dx = p.x; this.dy = p.y; this.sx = cam.scrollX; this.sy = cam.scrollY; this.moved = false; });
      this.input.on("pointerup", (p) => {
        this.drag = false;
        if (!this.moved) { const wp = cam.getWorldPoint(p.x, p.y); const n = this.pickBuilding(wp.x, wp.y); if (n) enterIndoor(n.id); }
      });
      this.input.on("pointermove", (p) => {
        if (!this.drag) return;
        cam.scrollX = this.sx - (p.x - this.dx) / cam.zoom; cam.scrollY = this.sy - (p.y - this.dy) / cam.zoom;
        if (Phaser.Math.Distance.Between(p.x, p.y, this.dx, this.dy) > 6) this.moved = true;
      });
    }
    mapNodes() { const m = new Map(); const md = state.trace && state.trace.map; if (md) (md.nodes || []).forEach((n) => m.set(n.id, n)); return m; }
    buildVillage() {
      const md = state.trace.map; if (!md) return;
      const tm = md.tile_map, b = md.bounds || { min_x: 0, min_y: 0, max_x: 20, max_y: 14 };
      // world size from tile_map if present else node bounds
      const cols = (tm && tm.width) || 80, rows = (tm && tm.height) || 56;
      this.worldW = cols * TILE_PX; this.worldH = rows * TILE_PX;
      this.bounds = b; this.gridCols = cols; this.gridRows = rows;
      this.drawGround(tm, cols, rows);
      this.drawRoads(md);
      this.buildBuildings(md);
      this.cameras.main.setBounds(-100, -100, this.worldW + 200, this.worldH + 200);
      this.fit();
    }
    nodeToWorld(n) {
      const b = this.bounds;
      const fx = (n.grid_x - b.min_x) / Math.max(0.001, b.max_x - b.min_x);
      const fy = (n.grid_y - b.min_y) / Math.max(0.001, b.max_y - b.min_y);
      return { x: fx * this.worldW, y: fy * this.worldH };
    }
    drawGround(tm, cols, rows) {
      const g = this.gGround; g.clear();
      // base grass
      g.fillStyle(0x6fb84e, 1); g.fillRect(0, 0, this.worldW, this.worldH);
      // tile-image grass for texture (sparse, cheap): use tux frames as images on a grid
      if (!tm || !tm.terrain) return;
      const terr = tm.terrain, th = terr.length, tw = terr[0].length;
      const cw = this.worldW / tw, ch = this.worldH / th;
      for (let r = 0; r < th; r++) for (let c = 0; c < tw; c++) {
        const ch0 = terr[r][c];
        let col = null;
        if (ch0 === "~") col = 0x4a90c2;          // water
        else if (ch0 === "*") col = 0x2f6b32;     // forest
        else if (ch0 === "=") col = 0xb08850;     // bridge
        if (col != null) { g.fillStyle(col, 1); g.fillRect(c * cw, r * ch, cw + 1, ch + 1); }
      }
    }
    drawRoads(md) {
      const g = this.gRoads; g.clear();
      const nodes = this.mapNodes();
      (md.edges || []).forEach((e) => {
        const a = nodes.get(e.source), b = nodes.get(e.target); if (!a || !b) return;
        const pa = this.nodeToWorld(a), pb = this.nodeToWorld(b);
        const w = e.road_type === "arterial" ? 9 : e.road_type === "collector" ? 6 : 4;
        g.lineStyle(w + 3, 0x9a8d6a, 1); g.beginPath(); g.moveTo(pa.x, pa.y); g.lineTo(pb.x, pb.y); g.strokePath();
        g.lineStyle(w, 0xc9bd97, 1); g.beginPath(); g.moveTo(pa.x, pa.y); g.lineTo(pb.x, pb.y); g.strokePath();
      });
    }
    buildBuildings(md) {
      this.bldgLayer.removeAll(true);
      this.bldgHit = [];
      (md.nodes || []).forEach((n) => {
        if (n.kind !== "hub") return;
        const p = this.nodeToWorld(n);
        const key = CAT_BUILDING[n.category] || "b_house_wood";
        const rect = TILE[key];
        const img = this.makeTileImage(key, rect, p.x, p.y);
        if (img) this.bldgLayer.add(img);
        // label
        const t = this.add.text(p.x, p.y - (rect[3] * 0.5) - 8, n.label || n.id,
          { fontFamily: "VT323, monospace", fontSize: "16px", color: "#22303a", backgroundColor: "#ffffffcc", padding: { x: 3, y: 1 } }).setOrigin(0.5);
        this.bldgLayer.add(t);
        this.bldgHit.push({ node: n, x: p.x, y: p.y, w: rect[2], h: rect[3] });
      });
    }
    makeTileImage(key, rect, x, y) {
      // crop a sub-rect of the tux sheet into its own texture once, reuse as image
      const tkey = "crop-" + key;
      if (!this.textures.exists(tkey)) {
        const src = this.textures.get("tux").getSourceImage();
        const cnv = this.textures.createCanvas(tkey, rect[2], rect[3]);
        if (cnv) { cnv.context.drawImage(src, rect[0], rect[1], rect[2], rect[3], 0, 0, rect[2], rect[3]); cnv.refresh(); }
      }
      if (!this.textures.exists(tkey)) return null;
      return this.add.image(x, y, tkey).setOrigin(0.5, 0.7);
    }
    pickBuilding(wx, wy) {
      let best = null, bd = 1e9;
      for (const h of this.bldgHit || []) { const d = (h.x - wx) ** 2 + (h.y - wy) ** 2; if (d < bd && d < (Math.max(h.w, h.h)) ** 2) { bd = d; best = h.node; } }
      return best;
    }
    fit() {
      if (!this.worldW) return;
      const cam = this.cameras.main, vw = this.scale.width, vh = this.scale.height;
      cam.setZoom(Phaser.Math.Clamp(Math.min(vw / (this.worldW + 80), vh / (this.worldH + 80)), 0.1, 3));
      cam.centerOn(this.worldW / 2, this.worldH / 2);
    }
    update() { this.drawAgents(); }
    agentPos(a, nodes) {
      const tr = a.travel || {};
      const route = (tr.route || []).map((id) => nodes.get(id)).filter(Boolean);
      if (route.length >= 2 && /transit|departed|in_transit/.test(tr.status || "")) {
        const p = Phaser.Math.Clamp(tr.progress != null ? tr.progress : 1, 0, 1);
        const seg = p * (route.length - 1), i = Math.min(route.length - 2, Math.floor(seg)), f = seg - i;
        const A = this.nodeToWorld(route[i]), B = this.nodeToWorld(route[i + 1]);
        return { x: A.x + (B.x - A.x) * f, y: A.y + (B.y - A.y) * f, moving: true };
      }
      const loc = nodes.get(a.resolved_location) || nodes.get(a.location) || (route.length ? route[route.length - 1] : null);
      const p2 = loc ? this.nodeToWorld(loc) : null; return p2 ? { x: p2.x, y: p2.y, moving: false } : null;
    }
    drawAgents() {
      if (!state.frames.length) return;
      const frame = state.frames[state.frameIdx]; if (!frame) return;
      const nodes = this.mapNodes();
      const seen = new Set();
      (frame.agents || []).forEach((a) => {
        const pos = this.agentPos(a, nodes); if (!pos) return;
        seen.add(a.agent_id);
        let spr = this.agentSprites[a.agent_id];
        if (!spr) {
          spr = this.add.sprite(pos.x, pos.y, "misa", "misa-front").setDepth(11);
          spr.setTint(agentColor(a.agent_id));
          this.agentLayer.add(spr); this.agentSprites[a.agent_id] = spr;
          const lbl = this.add.text(pos.x, pos.y - 26, "", { fontFamily: "VT323, monospace", fontSize: "15px", color: "#1e2c2c", backgroundColor: "#ffffffe6", padding: { x: 4, y: 1 } }).setOrigin(0.5).setDepth(12);
          this.agentLayer.add(lbl); this.agentLabels[a.agent_id] = lbl;
        }
        // smooth move
        spr.x += (pos.x - spr.x) * 0.25; spr.y += (pos.y - spr.y) * 0.25;
        const dir = this.dirOf(a, nodes);
        if (pos.moving) { if (spr.anims.currentAnim?.key !== "walk-" + dir) spr.play("walk-" + dir); }
        else { spr.anims.stop(); spr.setFrame("misa-" + dir); }
        const lbl = this.agentLabels[a.agent_id];
        lbl.setText(`${initials(a.name, a.agent_id)}: ${actEmoji(a.activity || a.scheduled_activity || a.action)}`);
        lbl.x = spr.x; lbl.y = spr.y - 26;
        spr.setScale(state.selectedId === a.agent_id ? 1.25 : 1);
      });
      // hide absent
      Object.keys(this.agentSprites).forEach((id) => {
        const present = seen.has(Number(id)) || seen.has(id);
        this.agentSprites[id].setVisible(present); this.agentLabels[id].setVisible(present);
      });
    }
    dirOf(a, nodes) {
      const tr = a.travel || {}; if (!/transit|departed/.test(tr.status || "")) return "front";
      const s = nodes.get(a.resolved_location), e = nodes.get(a.target_location);
      if (!s || !e) return "front";
      const dx = e.grid_x - s.grid_x, dy = e.grid_y - s.grid_y;
      if (Math.abs(dx) > Math.abs(dy)) return dx > 0 ? "right" : "left";
      return dy > 0 ? "front" : "back";
    }
    rebuild() { this.agentSprites = {}; this.agentLabels = {}; this.agentLayer.removeAll(true); this.buildVillage(); }
  }

  // ===== INDOOR SCENE — isometric 2.5D (sloped 45°) =====
  //
  // World units stay rectangular (the spatial tree is built in 0..1 normalized
  // arena geometry). We translate every (ux, uy) world coordinate to screen
  // coordinates on draw using:
  //
  //     sx = ux - uy              // screen x grows when world x grows AND
  //                                // when world y shrinks (back of room)
  //     sy = (ux + uy) * 0.5      // screen y grows when both grow
  //
  // That is the standard isometric "dimetric" projection — y axis is half-
  // compressed to keep the floor a clean 2:1 lozenge while keeping axes
  // perpendicular in world space. Walls are drawn at constant height h (in
  // world-y units) which translates to the same h in screen y (no half on
  // the vertical). Sorting uses world `uy + ux` (depth) so a person standing
  // behind a chair is correctly occluded by it.

  const ISO = {
    // vertical lift for walls, agents, furniture tops — in screen px
    wallH: 96,
  };

  function iso(ux, uy) {
    return { sx: ux - uy, sy: (ux + uy) * 0.5 };
  }
  function isoDepth(x, y, w = 0, h = 0) { return x + y + w + h; } // for Y-sort

  // Room floor + ceiling tints.
  const ROOM_FLOOR = {
    bedroom: { floor: 0xf0d9a8, plank: true }, living: { floor: 0xf0d9a8, plank: true },
    bathroom: { floor: 0xdfeaee, tiled: true }, kitchen: { floor: 0xe8dcc0, tiled: true },
    study: { floor: 0xdfd6c2, plank: true }, office: { floor: 0xdfd6c2, plank: true },
    reception: { floor: 0xe4ddcb, tiled: true }, meeting: { floor: 0xdfd6c2, plank: true },
    ward: { floor: 0xe8eef0, tiled: true }, consult: { floor: 0xe8eef0, tiled: true },
    pharmacy: { floor: 0xe8eef0, tiled: true },
    classroom: { floor: 0xd8c89a, plank: true }, library: { floor: 0xe6dcb4, plank: true },
    shop: { floor: 0xe8d8b8, tiled: true }, storeroom: { floor: 0xded0b0, plank: true },
    checkout: { floor: 0xe8d8b8, tiled: true }, seating: { floor: 0xe6d3a8, plank: true },
    counter: { floor: 0xe6d3a8, plank: true }, park: { floor: 0x7da35d, outdoor: true },
    guestroom: { floor: 0xdcc6a6, plank: true }, lounge: { floor: 0xdfd7bd, plank: true },
    waiting: { floor: 0xd9e5e4, tiled: true }, treatment: { floor: 0xe8eef0, tiled: true },
    reading: { floor: 0xe6dcb4, plank: true }, workshop: { floor: 0xb5bcb7, tiled: true },
    warehouse: { floor: 0xc5b799, tiled: true }, ticket: { floor: 0xd6dedb, tiled: true },
    concourse: { floor: 0xd7d8c9, tiled: true }, fitness: { floor: 0xaaa99c, tiled: true },
    studio: { floor: 0xdcc79c, plank: true }, locker: { floor: 0xd5e0d8, tiled: true },
  };

  class IndoorScene extends Phaser.Scene {
    constructor(opts = {}) {
      super("indoor"); this.viewState = opts.state || state; this.embedded = !!opts.embedded; this.onZoom = opts.onZoom;
    }
    init(d = {}) { this.nodeId = d.nodeId ?? this.nodeId; this.wander = {}; this.tree = null; this.node = null; this.zoom = 1; this.pan = { x: 0, y: 0 }; }
    create() {
      if (!this.embedded) App.indoor = this;
      this.g = this.add.graphics();
      this.gWalls = this.add.graphics();
      // One painter-ordered layer: walls, furniture and residents occlude correctly.
      this.gObjs = this.gWalls;
      this.gAgents = this.gWalls;
      this.gUI = this.add.graphics();
      this.labels = [];
      this.cameras.main.setBackgroundColor("#30463d");
      this._onResize = () => this.draw();
      this.scale.on("resize", this._onResize);
      this.events.once("shutdown", () => this.scale.off("resize", this._onResize));
      const onDown = p => { this._dragPoint = { x: p.x, y: p.y }; };
      const onMove = p => {
        if (!this._dragPoint || !p.isDown) return;
        this.pan.x += p.x - this._dragPoint.x; this.pan.y += p.y - this._dragPoint.y;
        this._dragPoint = { x: p.x, y: p.y }; this.draw();
      };
      const onUp = () => { this._dragPoint = null; };
      this.input.on("pointerdown", onDown); this.input.on("pointermove", onMove); this.input.on("pointerup", onUp);
      this.events.once("shutdown", () => {
        this.input.off("pointerdown", onDown); this.input.off("pointermove", onMove); this.input.off("pointerup", onUp);
      });
      this.draw();
    }
    update() {
      const state = this.viewState;
      if (this._renderedFrame !== state.frames[state.frameIdx] || this._renderedSelected !== state.selectedId) this.draw();
    }
    setZoom(value) {
      this.zoom = Phaser.Math.Clamp(value, 0.75, 3);
      if (this.zoom === 1) this.pan = { x: 0, y: 0 };
      if (this.onZoom) this.onZoom(this.zoom);
      else if (!this.embedded && $("zoomLevel")) $("zoomLevel").textContent = Math.round(this.zoom * 100) + "%";
      this.draw();
    }
    mapNodes() { const m = new Map(); const md = this.viewState.trace && this.viewState.trace.map; if (md) (md.nodes || []).forEach((n) => m.set(n.id, n)); return m; }
    ensureTree() {
      if (this.tree) return this.tree;
      const GS = (typeof window !== "undefined" && window.GAWorldSpatial) || null;
      const node = this.mapNodes().get(this.nodeId); if (!node || !GS) return null;
      this.node = node; this.tree = GS.buildBuildingTree(node);
      if (!this.embedded && window.__SIMVIZ__) window.__SIMVIZ__.indoorTree = this.tree;
      return this.tree;
    }
    draw() {
      const state = this.viewState;
      this._renderedFrame = state.frames[state.frameIdx]; this._renderedSelected = state.selectedId;
      const W = this.scale.width, H = this.scale.height;
      const gBg = this.g, gW = this.gWalls, gO = this.gObjs, gA = this.gAgents, gU = this.gUI;
      [...new Set([gBg, gW, gO, gA, gU])].forEach((gg) => gg.clear());
      this.labels.forEach((t) => t.destroy()); this.labels = [];
      // backdrop
      gBg.fillStyle(0x30463d, 1); gBg.fillRect(0, 0, W, H);
      const bannerH = 52, padTop = bannerH + 20, padBot = 40;
      const fit = Math.max(0.01, Math.min((W - 32) / 1860, (H - padTop - padBot) / 1050));
      const scale = fit * this.zoom;
      const rw = 1100 * scale, rh = 760 * scale;
      const tree = this.ensureTree();
      if (!tree) {
        this.labels.push(this.add.text(W / 2, H / 2, this.embedded ? "当前帧没有居民在室内" : "加载中…", { fontFamily: "PingFang SC, monospace", fontSize: "16px", color: "#e7edda" }).setOrigin(0.5));
        return;
      }
      const node = this.node, sector = tree.sector, outdoor = !!tree.outdoor;
      if (outdoor) grass(gBg, 0, 0, W, H);

      // ---- collect world-space rooms ----
      const arenas = tree.arenaNames(sector);
      const arenaMeta = arenas.map((name) => {
        const m = tree.arena(sector, name).meta;
        return { name, x: m.x * rw, y: m.y * rh, w: m.w * rw, h: m.h * rh, meta: m };
      });
      const arenaByName = Object.fromEntries(arenaMeta.map((a) => [a.name, a]));

      // isometric origin so the whole building is centered
      const aabb = arenaMeta.reduce((b, a) => ({
        x0: Math.min(b.x0, a.x), y0: Math.min(b.y0, a.y),
        x1: Math.max(b.x1, a.x + a.w), y1: Math.max(b.y1, a.y + a.h),
      }), { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity });
      if (!isFinite(aabb.x0)) return;
      const wCx = (aabb.x0 + aabb.x1) / 2, wCy = (aabb.y0 + aabb.y1) / 2;
      const floorTop = padTop + (H - padTop - padBot - 1038 * scale) / 2 + ISO.wallH * scale + this.pan.y;
      const offset = { sx: W / 2 - iso(wCx, wCy).sx + this.pan.x, sy: floorTop, scale };
      this.viewBounds = { left: W / 2 - (rw + rh) / 2 + this.pan.x, right: W / 2 + (rw + rh) / 2 + this.pan.x,
        top: floorTop - ISO.wallH * scale, bottom: floorTop + (rw + rh) / 2 + 12 * scale };

      // ---- 1) floor tiles (under walls, behind everything else) ----
      arenaMeta.forEach((a) => {
        const style = ROOM_FLOOR[a.meta.type] || { floor: 0xe6dcc4, plank: true };
        const c = { sx: offset.sx + iso(a.x, a.y).sx, sy: offset.sy + iso(a.x, a.y).sy };
        // floor diamond (ramp shade)
        gBg.fillStyle(style.floor, 1);
        gBg.beginPath();
        gBg.moveTo(c.sx + iso(0, 0).sx, c.sy + iso(0, 0).sy);
        gBg.lineTo(c.sx + iso(a.w, 0).sx, c.sy + iso(a.w, 0).sy);
        gBg.lineTo(c.sx + iso(a.w, a.h).sx, c.sy + iso(a.w, a.h).sy);
        gBg.lineTo(c.sx + iso(0, a.h).sx, c.sy + iso(0, a.h).sy);
        gBg.closePath(); gBg.fillPath();
        // subtle inner pattern
        if (style.tiled) isoTile(gBg, a.x, a.y, a.w, a.h, offset);
        else isoPlank(gBg, a.x, a.y, a.w, a.h, offset);
        if (["living", "bedroom", "study", "seating"].includes(a.meta.type)) {
          const rx = a.x + a.w * 0.06, ry = a.y + a.h * 0.56, ww = a.w * 0.38, hh = a.h * 0.38;
          isoRug(gBg, rx, ry, ww, hh, offset, a.meta.type === "living" ? 0xb39d73 : 0x9ba079);
        }
      });

      // ---- 2) collect drawables for Y-sort ----
      const drawables = [];
      // floor outlines — depth = front of room
      arenaMeta.forEach((a) => {
        drawables.push({ kind: "floorEdge", a, depth: isoDepth(a.x, a.y, a.w, a.h) });
      });
      // exterior shell walls (4 sides of the building)
      if (!outdoor) {
        const shellEdges = this.shellEdgesOf(arenaMeta);
        shellEdges.forEach((e) => {
          const rear = e.side === "N" || e.side === "W";
          drawables.push({ kind: "wall", e, height: rear ? ISO.wallH : 12,
            depth: rear ? -1 : e.x + e.y + e.w + e.h });
        });
        // interior partitions
        arenaMeta.forEach((a) => {
          this.partitionEdgesOf(a, arenaMeta).forEach((e) => {
            drawables.push({ kind: "wall", e, height: 42, depth: e.x + e.y + e.w + e.h, doorSide: e.door ? e.side : null });
          });
        });
      }
      // furniture
      const objSpots = [];
      tree.objects(sector).forEach((rec) => {
        const a = arenaByName[rec.arena]; if (!a) return;
        const fx = a.x + rec.geom.x * a.w, fy = a.y + rec.geom.y * a.h, fw = rec.geom.w * a.w, fh = rec.geom.h * a.h;
        const depth = isoDepth(fx, fy, fw, fh);
        drawables.push({ kind: "furn", rec, fx, fy, fw, fh, depth });
        if (rec.slot) objSpots.push({ rec, fx, fy, fw, fh, cx: fx + fw / 2, cy: fy + fh / 2, depth });
      });

      // ---- 3) agents ----
      let here = [];
      if (state.frames.length) {
        const frame = state.frames[state.frameIdx];
        here = (frame.agents || []).filter((a) => {
          const loc = a.resolved_location || a.location || a.target_location;
          return (loc === this.nodeId || loc === node.label) && (!a.travel || !/transit|departed/.test(a.travel.status || ""));
        });
      }
      // A block of flats shows one flat (the simulation's rooms, local_physical.rooms).
      const GS = window.GAWorldSpatial;
      const flat = GS && GS.flatView ? GS.flatView(here, state.selectedId) : { unit: "", units: 0, agents: here };
      here = flat.agents;
      const usedObj = new Set(), usedChairs = new Set(), crowds = new Map();
      this.residentPlacements = [];
      here.sort((a, b) => Number(a.agent_id) - Number(b.agent_id)).forEach((a) => {
        const slot = activitySlot(a.activity || a.scheduled_activity || a.action);
        const aliases = { sleep: ["rest"], watch: ["sit"], order: ["eat"], study: ["work", "read"] };
        const wanted = slot ? [slot, ...(aliases[slot] || [])] : [];
        // the room (and object) the simulation put them in, when the trace has it
        const given = a.room && a.room.arena && arenaByName[a.room.arena] ? a.room : null;
        const spot = given
          ? objSpots.find(o => o.rec.arena === given.arena && o.rec.object === given.object
            && !usedObj.has(o.rec.address) && !usedChairs.has(o.rec.address))
          : wanted.map(s => objSpots.find(o => o.rec.slot === s && !usedObj.has(o.rec.address)
            && !usedChairs.has(o.rec.address))).find(Boolean);
        if (spot) usedObj.add(spot.rec.address);
        const roomName = spot ? spot.rec.arena : given ? given.arena : slot ? tree.arenaForActivity(sector, slot) :
          (arenas.find(name => ["living", "seating", "reception", "shop", "park", "lounge", "waiting"].includes(arenaByName[name].meta.type)) || arenas[0]);
        const room = arenaByName[roomName] || arenaMeta[0];
        const n = crowds.get(room.name) || 0; crowds.set(room.name, n + 1);
        let tx = room.x + room.w * (0.45 + 0.10 * Math.cos(n * 2.4)),
          ty = room.y + room.h * (0.65 + 0.10 * Math.sin(n * 2.4)), pose = "stand", seat = null, supportDepth = -Infinity;
        const lying = !!spot && spot.rec.kind === "bed" && (slot === "sleep" || slot === "rest");
        if (spot) {
          tx = spot.cx; ty = spot.fy + spot.fh + 9 * scale;
          supportDepth = spot.depth;
          if (slot === "cook") {
            const counter = tree.objects(sector, room.name).find(rec => rec.kind === "counter");
            if (counter) {
              const box = tree.objectBuildingRect(counter);
              ty = Math.max(ty, (box.y + box.h) * rh + 14 * scale);
              supportDepth = Math.max(supportDepth, (box.x + box.w) * rw + (box.y + box.h) * rh);
            }
          }
          if (lying) { ty = spot.cy; }
          else if (["work", "study", "eat", "watch", "meeting", "music", "order", "consult"].includes(slot)
            || ["sleep", "rest"].includes(slot) && ["chair", "sofa", "bench"].includes(spot.rec.kind)) {
            const chairs = tree.objects(sector, room.name).filter(r => ["chair", "sofa", "bench"].includes(r.kind) && !usedChairs.has(r.address));
            const positions = chairs.map(rec => ({ rec, box: tree.objectBuildingRect(rec) }));
            positions.sort((a, b) => Math.hypot((a.box.x + a.box.w / 2) * rw - spot.cx, (a.box.y + a.box.h / 2) * rh - spot.cy) -
              Math.hypot((b.box.x + b.box.w / 2) * rw - spot.cx, (b.box.y + b.box.h / 2) * rh - spot.cy));
            const chair = positions[0];
            if (chair) {
              usedChairs.add(chair.rec.address); tx = (chair.box.x + chair.box.w / 2) * rw;
              ty = (chair.box.y + chair.box.h) * rh + 4 * scale; pose = "sit";
              seat = { x: tx, y: (chair.box.y + chair.box.h / 2) * rh,
                height: chair.rec.kind === "sofa" ? 28 : 27 };
              supportDepth = (chair.box.x + chair.box.w) * rw + (chair.box.y + chair.box.h) * rh;
            }
          }
        }
        const position = this.wanderStep(a, tx, ty, room.x + 6 * scale, room.y + 6 * scale,
          room.x + room.w - 6 * scale, room.y + room.h - 6 * scale);
        const depth = Math.max(supportDepth + 0.1, position.x + position.y + 2 * scale);
        const resident = { kind: "agent", agent: a, ux: position.x, uy: position.y, col: agentColor(a.agent_id),
          sel: state.selectedId === a.agent_id, lying, pose, seat, depth,
          objectDepth: spot ? spot.depth : null, objectFront: spot ? spot.fy + spot.fh : null };
        this.residentPlacements.push(resident); drawables.push(resident);
      });

      // ---- 4) paint sorted ----
      drawables.sort((a, b) => a.depth - b.depth);
      drawables.forEach((d) => {
        if (d.kind === "floorEdge") this.drawFloorEdge(d.a, offset);
        else if (d.kind === "wall") this.drawIsoWall(d.e, d.height, offset, d.doorSide);
        else if (d.kind === "furn") this.drawIsoFurn(d.rec, d.fx, d.fy, d.fw, d.fh, offset);
        else if (d.kind === "agent") this.drawIsoAgent(d.agent, d.ux, d.uy, d.col, d.sel, d.lying, offset, d.pose, d.seat);
      });

      // ---- 5) UI / banner ----
      const bannerW = Math.min(W - 16, 520);
      gU.fillStyle(0x1c2630, 0.92);
      gU.fillRoundedRect(W / 2 - bannerW / 2, 12, bannerW, bannerH, 10);
      this.labels.push(this.add.text(W / 2, 12 + bannerH / 2 - 7, `${outdoor ? "🌳" : "🏠"}  ${(node && (node.label || node.id)) || this.nodeId}`, { fontFamily: "VT323, monospace", fontSize: W < 500 ? "18px" : "22px", color: "#f4ede0" }).setOrigin(0.5).setDepth(20));
      this.labels.push(this.add.text(W / 2, 12 + bannerH / 2 + 13, `${tree.layoutLabel}${flat.unit ? ` · ${flat.unit} 户（本楼 ${flat.units} 户有人）` : ""} · ${arenas.length} ${outdoor ? "区域" : "房间"} · ${here.length} 人在场 · ＋放大 · 拖动查看`, { fontFamily: "VT323, monospace", fontSize: W < 500 ? "10px" : "13px", color: "#b9c8b3" }).setOrigin(0.5).setDepth(20));
      // small room tags
      arenaMeta.forEach((a) => {
        if (scale < 0.18) return;
        const p = offset.sx + iso(a.x, a.y).sx;
        const py = offset.sy + iso(a.x, a.y).sy;
        this.labels.push(this.add.text(p + 4, py - 6, ({ bedroom: "卧室", bathroom: "卫生间", kitchen: "厨房", living: "客厅", study: "书房",
          seating: "就餐区", counter: "吧台", ward: "病房", reception: "前台", office: "办公室", meeting: "会议室",
          consult: "诊室", pharmacy: "药房", classroom: "教室", library: "图书室", shop: "卖场", storeroom: "库房",
          checkout: "收银台", park: "公园", guestroom: "客房", lounge: "休息区", waiting: "等候区", treatment: "治疗室",
          reading: "阅览室", workshop: "生产车间", warehouse: "仓储区", ticket: "售票厅", concourse: "进站通道",
          fitness: "器械区", studio: "训练室", locker: "更衣室" }[a.meta.type] || a.name) + ((a.name.match(/\d+$/) || [""])[0]),
          { fontFamily: "VT323, PingFang SC, monospace", fontSize: "10px", color: outdoor ? "#2c4a2c" : "#706a4d" }).setOrigin(0, 1).setDepth(3));
      });
    }

    // ----- Y-sort helpers: world-space geometry -----
    // Returns the rectangle of an arena. Used for the floor outline.
    drawFloorEdge(a, off) {
      const g = this.gObjs;
      const tl = { sx: off.sx + iso(a.x, a.y).sx, sy: off.sy + iso(a.x, a.y).sy };
      const tr = { sx: off.sx + iso(a.x + a.w, a.y).sx, sy: off.sy + iso(a.x + a.w, a.y).sy };
      const br = { sx: off.sx + iso(a.x + a.w, a.y + a.h).sx, sy: off.sy + iso(a.x + a.w, a.y + a.h).sy };
      const bl = { sx: off.sx + iso(a.x, a.y + a.h).sx, sy: off.sy + iso(a.x, a.y + a.h).sy };
      g.lineStyle(1, 0x6f5a3a, 0.35);
      g.beginPath(); g.moveTo(tl.sx, tl.sy); g.lineTo(tr.sx, tr.sy); g.lineTo(br.sx, br.sy); g.lineTo(bl.sx, bl.sy); g.closePath(); g.strokePath();
    }
    shellEdgesOf(arenaMeta) {
      // 4 world-space edges that bound the union of rooms
      const aabb = arenaMeta.reduce((b, a) => ({
        x0: Math.min(b.x0, a.x), y0: Math.min(b.y0, a.y),
        x1: Math.max(b.x1, a.x + a.w), y1: Math.max(b.y1, a.y + a.h),
      }), { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity });
      return [
        { x: aabb.x0, y: aabb.y0, w: aabb.x1 - aabb.x0, h: 0, side: "N" }, // top
        { x: aabb.x0, y: aabb.y1, w: aabb.x1 - aabb.x0, h: 0, side: "S" }, // bottom
        { x: aabb.x0, y: aabb.y0, w: 0, h: aabb.y1 - aabb.y0, side: "W" }, // left
        { x: aabb.x1, y: aabb.y0, w: 0, h: aabb.y1 - aabb.y0, side: "E" }, // right
      ];
    }
    partitionEdgesOf(a, all) {
      // Visit only the south/east neighbours so shared edges appear once.
      const edges = [], eps = 0.01;
      for (const b of all) {
        if (a === b) continue;
        const left = Math.max(a.x, b.x), right = Math.min(a.x + a.w, b.x + b.w);
        if (Math.abs(a.y + a.h - b.y) < eps && right > left + eps) {
          edges.push({ x: left, y: b.y, w: right - left, h: 0, side: "N",
            door: a.meta.door === "S" || b.meta.door === "N" });
        }
        const top = Math.max(a.y, b.y), bottom = Math.min(a.y + a.h, b.y + b.h);
        if (Math.abs(a.x + a.w - b.x) < eps && bottom > top + eps) {
          edges.push({ x: b.x, y: top, w: 0, h: bottom - top, side: "W", door: true });
        }
      }
      return edges;
    }
    drawIsoWall(e, height, off, doorSide) {
      const g = this.gWalls, scale = off.scale, lift = height * scale;
      const horiz = e.h === 0, length = horiz ? e.w : e.h;
      const door = doorSide === e.side;
      const gap = Math.min(56 * scale, length * 0.32) / length;
      const segments = door ? [[0, (1 - gap) / 2], [(1 + gap) / 2, 1]] : [[0, 1]];
      const point = (t, z, inset = 0) => {
        const p = iso(e.x + (horiz ? length * t : inset), e.y + (horiz ? inset : length * t));
        return { sx: off.sx + p.sx, sy: off.sy + p.sy - z };
      };
      const quad = (points, color) => {
        g.fillStyle(color, 1); g.beginPath(); g.moveTo(points[0].sx, points[0].sy);
        points.slice(1).forEach(p => g.lineTo(p.sx, p.sy)); g.closePath(); g.fillPath();
      };
      for (const [a, b] of segments) {
        quad([point(a, 0), point(b, 0), point(b, lift), point(a, lift)], horiz ? 0xe4d8bc : 0xc7c6a8);
        const edge = 6 * scale;
        quad([point(a, lift), point(b, lift), point(b, lift, edge), point(a, lift, edge)], 0xf7ebd1);
        quad([point(a, 0), point(b, 0), point(b, 5 * scale), point(a, 5 * scale)], 0x74765a);
        // Rear windows have a sill, mullions and stepped curtains.
        if (height > 60 && length * (b - a) > 100 * scale) {
          const mid = (a + b) / 2, half = Math.min((b - a) * 0.24, 60 * scale / length);
          const lo = mid - half, hi = mid + half, z0 = lift * 0.30, z1 = lift * 0.78;
          quad([point(lo, z0), point(hi, z0), point(hi, z1), point(lo, z1)], 0x68583f);
          const inset = 3 * scale / length;
          quad([point(lo + inset, z0 + 3 * scale), point(hi - inset, z0 + 3 * scale),
            point(hi - inset, z1 - 3 * scale), point(lo + inset, z1 - 3 * scale)], 0xa8d4d2);
          const div = 2 * scale / length;
          quad([point(mid - div, z0), point(mid + div, z0), point(mid + div, z1), point(mid - div, z1)], 0xf7edda);
          quad([point(lo, z0 - 4 * scale), point(hi, z0 - 4 * scale), point(hi, z0), point(lo, z0)], 0xb29a6f);
          for (const t of [lo, hi - 0.025]) {
            quad([point(t, z0 + 7 * scale), point(t + 0.025, z0 + 7 * scale),
              point(t + 0.025, z1 + 4 * scale), point(t, z1 + 4 * scale)], 0x879267);
          }
        }
      }
      if (door) {
        const a = (1 - gap) / 2, b = (1 + gap) / 2;
        quad([point(a, 0), point(b, 0), point(b, 0, 9 * scale), point(a, 0, 9 * scale)], 0xc8a578);
      }
    }

    drawIsoFurn(rec, x, y, w, h, off) {
      const g = this.gObjs, s = off.scale, kind = rec.kind;
      const wood = 0xab7e4f, cream = 0xf1e8d0, green = 0x778b5b, metal = 0xc9d5ce;
      const point = (xx, yy, z) => { const p = iso(xx, yy); return { sx: off.sx + p.sx, sy: off.sy + p.sy - z }; };
      const polygon = (pts, color, alpha = 1) => {
        g.fillStyle(color, alpha); g.beginPath(); g.moveTo(pts[0].sx, pts[0].sy);
        pts.slice(1).forEach(p => g.lineTo(p.sx, p.sy)); g.closePath(); g.fillPath();
      };
      // All dimensions are world units; the common projection keeps scale consistent.
      const plane = (xx, yy, ww, hh, z, color, alpha = 1) => polygon([
        point(xx, yy, z), point(xx + ww, yy, z), point(xx + ww, yy + hh, z), point(xx, yy + hh, z)], color, alpha);
      const box = (xx, yy, ww, hh, z, height, color) => {
        polygon([point(xx, yy + hh, z), point(xx + ww, yy + hh, z), point(xx + ww, yy + hh, z + height), point(xx, yy + hh, z + height)], this.darken(color, 0.78));
        polygon([point(xx + ww, yy, z), point(xx + ww, yy + hh, z), point(xx + ww, yy + hh, z + height), point(xx + ww, yy, z + height)], this.darken(color, 0.60));
        plane(xx, yy, ww, hh, z + height, this.lighten(color, 1.12));
      };
      const part = (fx, fy, fw, fh, z, height, color) => box(x + fx * w, y + fy * h, fw * w, fh * h, z * s, height * s, color);
      const top = (fx, fy, fw, fh, z, color) => plane(x + fx * w, y + fy * h, fw * w, fh * h, z * s, color);
      const legs = (height, color = wood) => {
        for (const fx of [0.06, 0.84]) for (const fy of [0.06, 0.80]) part(fx, fy, 0.09, 0.13, 0, height, color);
      };
      const mug = (fx, fy, z) => {
        part(fx, fy, 0.09, 0.12, z, 5, cream); top(fx + 0.015, fy + 0.015, 0.06, 0.08, z + 5.2, 0x74543e);
      };
      plane(x + 4 * s, y + 5 * s, w, h, 0, 0x574934, 0.14);
      switch (kind) {
        case "bed":
          part(0, 0, 1, 1, 0, 9, wood); part(0, 0, 1, 0.075, 0, 52, wood);
          part(0.03, 0.08, 0.94, 0.88, 9, 12, cream);
          top(0.04, 0.33, 0.92, 0.60, 22, rec.arena.endsWith("2") ? green : 0xbb735c);
          for (const fx of [0.10, 0.55]) part(fx, 0.12, 0.34, 0.17, 22, 3, 0xfff5df);
          for (let i = 0; i < 5; i++) top(0.06, 0.36 + i * 0.11, 0.88, 0.012, 22.4, 0xdfb99b);
          top(0.07, 0.86, 0.86, 0.045, 22.5, cream);
          break;
        case "sofa":
          legs(7, 0x65513c); part(0, 0, 1, 1, 7, 16, green);
          part(0, 0, 1, 0.18, 16, 30, green); part(0, 0.1, 0.12, 0.9, 16, 19, green); part(0.88, 0.1, 0.12, 0.9, 16, 19, green);
          for (let i = 0; i < 3; i++) part(0.14 + i * 0.245, 0.24, 0.22, 0.65, 23, 5, 0x98a677);
          part(0.18, 0.20, 0.18, 0.25, 28, 9, 0xd4b587); part(0.64, 0.20, 0.16, 0.22, 28, 9, 0xe3d7b6);
          break;
        case "chair": case "bench":
          legs(22); part(0, 0, 1, 1, 22, 5, wood); part(0, 0, 1, 0.18, 22, 25, wood);
          top(0.08, 0.24, 0.84, 0.64, 27.2, green);
          break;
        case "desk": case "table": case "coffee_table": case "workbench":
          { const height = kind === "coffee_table" ? 22 : 42;
            legs(height - 4); part(0, 0, 1, 1, height - 4, 5, wood);
            for (let i = 1; i < 4; i++) top(i * 0.22, 0.03, 0.009, 0.94, height + 1.2, 0x967047);
            if (kind === "desk") {
              part(0.13, 0.10, 0.50, 0.10, height + 1, 22, 0x3b4d47);
              const a = point(x + w * 0.17, y + h * 0.21, (height + 20) * s);
              const b = point(x + w * 0.59, y + h * 0.21, (height + 20) * s);
              polygon([a, b, { sx: b.sx, sy: b.sy + 13 * s }, { sx: a.sx, sy: a.sy + 13 * s }], 0x98bab1);
              top(0.17, 0.38, 0.42, 0.22, height + 1.4, 0xd5d8c7);
              for (let row = 0; row < 3; row++) top(0.20, 0.40 + row * 0.06, 0.35, 0.012, height + 1.6, 0x808c81);
              part(0.69, 0.26, 0.20, 0.34, height + 1, 3, 0xbc7658);
              top(0.70, 0.26, 0.02, 0.34, height + 4.3, cream);
            } else if (kind === "workbench") {
              part(0.1, 0.2, 0.16, 0.25, height + 1, 8, metal);
              top(0.4, 0.35, 0.3, 0.05, height + 1.5, 0x425a56);
              top(0.65, 0.28, 0.05, 0.35, height + 1.5, 0xb87f4d);
            } else {
              for (const fx of (kind === "table" ? [0.18, 0.66] : [0.18])) {
                top(fx, 0.26, 0.18, 0.26, height + 1.5, cream); top(fx + 0.03, 0.30, 0.12, 0.17, height + 1.8, 0xd6ad70);
              }
            }
            mug(0.74, 0.69, height + 1);
          } break;
        case "bookshelf": case "shelf": case "wardrobe":
          part(0, 0, 1, 1, 0, 90, wood);
          { const zMax = 90 * s, levels = kind === "wardrobe" ? 2 : 4;
            for (let row = 0; row < levels; row++) {
              const z = (8 + row * 19) * s;
              const aa = point(x + w * 0.08, y + h, z), bb = point(x + w * 0.92, y + h, z);
              polygon([aa, bb, { sx: bb.sx, sy: bb.sy - 16 * s }, { sx: aa.sx, sy: aa.sy - 16 * s }], 0x665039);
              if (kind !== "wardrobe") for (let i = 0; i < 8; i++) {
                const p = point(x + w * (0.10 + i * 0.10), y + h + s, z);
                const bw = w * 0.075;
                const colors = [0x8b9e69, 0xc88961, 0x659491, 0xe5d0a0, 0xb86658];
                polygon([p, { sx: p.sx + bw, sy: p.sy + bw * 0.5 },
                  { sx: p.sx + bw, sy: p.sy + bw * 0.5 - (12 + i % 3) * s }, { sx: p.sx, sy: p.sy - (12 + i % 3) * s }], colors[(i + row) % colors.length]);
              }
            }
            if (kind === "wardrobe") {
              const a = point(x + w * 0.5, y + h, 8 * s), b = point(x + w * 0.5, y + h, zMax - 5 * s);
              g.lineStyle(Math.max(1, s), 0x705739); g.beginPath(); g.moveTo(a.sx, a.sy); g.lineTo(b.sx, b.sy); g.strokePath();
              const p = point(x + w * 0.5, y + h, 40 * s);
              px(g, p.sx - 4 * s, p.sy, 2 * s, 6 * s, 0xdac28e); px(g, p.sx + 2 * s, p.sy + 3 * s, 2 * s, 6 * s, 0xdac28e);
            }
          } break;
        case "plant": case "tree":
          part(0.28, 0.30, 0.44, 0.44, 0, 16, 0xb57852);
          part(0.25, 0.27, 0.50, 0.50, 14, 3, 0xd99a6b);
          { const p = point(x + w / 2, y + h / 2, 22 * s), u = s * (kind === "tree" ? 2 : 1);
            px(g, p.sx - 2 * u, p.sy - 20 * u, 4 * u, 25 * u, 0x677345);
            for (const [dx, dy, ww, hh, color] of [[-14,-14,13,8,0x718c4a], [2,-20,12,9,0x4e7148],[-9,-28,12,11,0x8ea15e],[-17,-6,16,8,0x5d8050],[2,-9,15,9,0x839952],[-4,-17,11,10,0x9ba966]]) {
              px(g, p.sx + dx * u, p.sy + dy * u, ww * u, hh * u, color);
            }
          } break;
        case "counter": case "checkout": case "nightstand":
          { const z = kind === "nightstand" ? 27 : 45;
            part(0, 0, 1, 1, 0, z - 4, kind === "counter" ? green : wood); part(0, 0, 1, 1, z - 4, 4, cream);
            for (let i = 1; i < 3; i++) part(i / 3, 0.94, 0.014, 0.04, 8, z - 16, 0x6c714d);
            mug(0.15, 0.23, z);
            if (kind === "nightstand") {
              part(0.45, 0.45, 0.08, 0.08, z, 15, 0x715f42);
              part(0.23, 0.22, 0.54, 0.54, z + 12, 10, 0xe2bd79);
            }
          } break;
        case "fridge":
          part(0, 0, 1, 1, 0, 90, metal);
          { const p = point(x + w * 0.1, y + h, 58 * s), q = point(x + w * 0.9, y + h, 58 * s);
            g.lineStyle(Math.max(1, s), 0x788b80); g.beginPath(); g.moveTo(p.sx, p.sy); g.lineTo(q.sx, q.sy); g.strokePath();
            px(g, p.sx + 3 * s, p.sy + 8 * s, 3 * s, 14 * s, 0x62766d);
          } break;
        case "stove": case "sink":
          part(0, 0, 1, 1, 0, 41, green); part(0, 0, 1, 1, 41, 4, cream);
          if (kind === "stove") {
            top(0.06, 0.06, 0.88, 0.88, 45.3, 0x4f5952);
            for (const fx of [0.17, 0.60]) for (const fy of [0.15, 0.59]) {
              top(fx, fy, 0.24, 0.24, 45.6, 0x242f2a); top(fx + 0.04, fy + 0.04, 0.15, 0.15, 45.8, 0x7e8976);
            }
            part(0.16, 0.14, 0.26, 0.26, 46, 4, 0x303d32); top(0.20, 0.18, 0.18, 0.18, 50.2, 0xa6b567);
          } else {
            top(0.16, 0.22, 0.66, 0.60, 45.3, 0x829a94); top(0.25, 0.29, 0.48, 0.45, 45.5, 0xabc9c4);
            part(0.43, 0.09, 0.05, 0.07, 45, 11, metal); part(0.43, 0.09, 0.05, 0.26, 54, 2, metal);
          } break;
        case "toilet":
          part(0.1, 0.03, 0.80, 0.24, 0, 34, cream); part(0.15, 0.20, 0.70, 0.70, 0, 18, cream);
          top(0.26, 0.37, 0.47, 0.36, 18.4, 0x90aaa3); top(0.33, 0.43, 0.33, 0.22, 18.6, 0xbdd7cf);
          break;
        case "bathtub":
          part(0, 0, 1, 1, 0, 27, cream); top(0.08, 0.09, 0.84, 0.83, 27.2, 0x869f98);
          top(0.14, 0.16, 0.72, 0.69, 27.4, 0xaacec7); top(0.20, 0.25, 0.56, 0.018, 27.6, 0xdaf0db);
          break;
        case "tv": case "chalkboard":
          legs(16, 0x4b5144); part(0, 0, 1, 0.30, 16, 40, 0x4b5144);
          { const a = point(x + w * 0.07, y + h * 0.30, 52 * s), b = point(x + w * 0.93, y + h * 0.30, 52 * s);
            polygon([a, b, { sx: b.sx, sy: b.sy + 30 * s }, { sx: a.sx, sy: a.sy + 30 * s }], kind === "tv" ? 0x729b91 : 0x547461);
            const q = point(x + w * 0.14, y + h * 0.30, 47 * s);
            px(g, q.sx, q.sy, 13 * s, 2 * s, 0xb3cfb9);
          } break;
        case "piano":
          legs(30, 0x42463d); part(0, 0, 1, 0.7, 28, 44, 0x42463d); top(0.05, 0.67, 0.90, 0.25, 46, cream);
          for (let i = 0; i < 12; i++) top(0.08 + i * 0.07, 0.68, 0.028, 0.16, 46.3, 0x30352c);
          break;
        case "coffee_machine":
          part(0, 0, 1, 1, 0, 26, 0x727c6a); part(0.05, 0.10, 0.90, 0.55, 26, 16, metal); mug(0.35, 0.67, 10);
          break;
        case "machine":
          part(0, 0, 1, 1, 0, 12, 0x52655e); part(0.05, 0.05, 0.9, 0.65, 12, 48, 0x899c92);
          part(0.12, 0.18, 0.34, 0.35, 60, 20, metal); top(0.18, 0.22, 0.21, 0.25, 80.3, 0x557b72);
          part(0.65, 0.18, 0.2, 0.26, 60, 12, 0x394e47);
          part(0.15, 0.73, 0.7, 0.15, 12, 12, metal);
          for (let i = 0; i < 5; i++) top(0.18 + i * 0.13, 0.74, 0.045, 0.12, 24.2, 0x56665f);
          top(0.74, 0.24, 0.05, 0.07, 72.2, 0xd4a954);
          break;
        case "crate":
          part(0, 0, 1, 1, 0, 45, wood);
          for (const p of [0.12, 0.82]) { part(p, 0, 0.06, 1, 45, 2, 0x765d3c); part(p, 0.96, 0.06, 0.04, 0, 45, 0x765d3c); }
          top(0.32, 0.3, 0.34, 0.35, 47.2, cream);
          break;
        case "departure_board":
          legs(28, metal); part(0, 0, 1, 0.5, 28, 36, 0x344d49);
          for (let i = 0; i < 3; i++) top(0.08, 0.08 + i * 0.13, 0.68, 0.05, 64.2, 0xe2bd79);
          break;
        case "ticket_machine":
          part(0, 0, 1, 1, 0, 72, 0x779286); top(0.15, 0.2, 0.65, 0.44, 72.2, 0x345b54);
          part(0.16, 0.87, 0.6, 0.05, 45, 12, cream); part(0.3, 0.96, 0.36, 0.04, 16, 8, 0x42574f);
          break;
        case "turnstile":
          part(0.08, 0, 0.32, 1, 0, 38, metal); part(0.68, 0, 0.24, 1, 0, 38, metal);
          part(0.4, 0.45, 0.28, 0.07, 20, 16, 0x87b3a2); top(0.14, 0.14, 0.2, 0.18, 38.2, 0x487766);
          break;
        case "treadmill":
          part(0, 0, 1, 1, 0, 8, 0x6c8279); top(0.14, 0.3, 0.72, 0.63, 8.2, 0x354940);
          for (const p of [0.05, 0.88]) part(p, 0.06, 0.06, 0.42, 8, 44, metal);
          part(0.1, 0.04, 0.8, 0.18, 48, 5, 0x637a72); top(0.28, 0.07, 0.42, 0.11, 53.2, 0xaac7b4);
          break;
        case "weight_rack":
          legs(24, metal); part(0, 0, 1, 1, 24, 5, metal);
          for (let i = 0; i < 5; i++) {
            part(0.05 + i * 0.19, 0.28, 0.09, 0.42, 29, 10, 0x3d4b45);
            part(0.10 + i * 0.19, 0.46, 0.06, 0.07, 29, 6, metal);
          }
          break;
        case "exercise_mat":
          part(0, 0, 1, 1, 0, 2, 0x769f91); top(0.06, 0.06, 0.88, 0.88, 2.2, 0xaac4a6);
          break;
        case "fountain":
          part(0, 0, 1, 1, 0, 12, metal); top(0.08, 0.08, 0.84, 0.84, 12.2, 0x7cbbb2); part(0.4, 0.4, 0.2, 0.2, 12, 28, cream);
          break;
        default:
          part(0, 0, 1, 1, 0, 36, wood);
      }
    }

    drawIsoAgent(a, ux, uy, col, sel, lying, off, pose = "stand", seat = null) {
      const g = this.gAgents, s = off.scale, u = 1.5 * s;
      const floor = iso(ux, uy), foot = { x: Math.round(off.sx + floor.sx), y: Math.round(off.sy + floor.sy) };
      const id = Math.abs(Number(a.agent_id) || 0);
      const outline = 0x363e33, hair = [0x493d32, 0x6c4b32, 0x343b34, 0x8c7054][id % 4];
      const skin = [0xe1b487, 0xf0cda0, 0xbb8962, 0xd6a071][id % 4];
      const skinShade = this.darken(skin, 0.85), shirtShade = this.darken(col, 0.73), shirtLight = this.lighten(col, 1.18);
      g.fillStyle(0x414732, 0.20); g.fillEllipse(foot.x, foot.y, 28 * s, 9 * s);
      if (sel) { g.lineStyle(Math.max(1, 2 * s), 0xf9eac0); g.strokeEllipse(foot.x, foot.y, 36 * s, 14 * s); }
      const seated = pose === "sit", seatPoint = seated && seat ? iso(seat.x, seat.y) : null;
      const bodyX = seatPoint ? off.sx + seatPoint.sx : foot.x;
      const bodyY = seatPoint ? off.sy + seatPoint.sy - seat.height * s - 30 * u : foot.y - 48 * u;
      // The seated waist follows the seat surface; calves extend to the floor.
      const pixel = (x, y, w, h, color) => {
        if (lying) {
          const p = (xx, yy) => { const v = iso(ux + (xx - 12) * u, uy + (yy - 24) * u); return { x: off.sx + v.sx, y: off.sy + v.sy - 25 * s }; };
          const points = [p(x,y), p(x+w,y), p(x+w,y+h), p(x,y+h)];
          g.fillStyle(color); g.beginPath(); g.moveTo(points[0].x, points[0].y);
          points.slice(1).forEach(pt => g.lineTo(pt.x, pt.y)); g.closePath(); g.fillPath();
        } else {
          px(g, Math.round(bodyX + (x - 12) * u), Math.round(bodyY + y * u),
            Math.max(1, Math.ceil(w * u)), Math.max(1, Math.ceil(h * u)), color);
        }
      };
      const legTop = 30, legEnd = seated ? (foot.y - bodyY) / u - 3 : 44;
      for (const x of [6, 13]) {
        if (seated) {
          pixel(x - 2, legTop, 8, 4, outline); pixel(x - 1, legTop, 6, 3, 0x52665d);
        }
        const calfTop = seated ? 33 : legTop, calfX = seated ? x - 2 : x;
        pixel(calfX, calfTop, 6, legEnd - calfTop, outline);
        pixel(calfX + 1, calfTop, 4, legEnd - calfTop - 1, 0x52665d);
        pixel(calfX - 1, legEnd, 7, 3, outline); pixel(calfX, legEnd, 5, 1, 0xd6d2ba);
      }
      pixel(5, 17, 15, 15, outline); pixel(6, 18, 13, 12, col); pixel(7, 18, 3, 12, shirtLight);
      pixel(17, 20, 2, 10, shirtShade); pixel(6, 30, 13, 2, 0x4b5849);
      pixel(10, 15, 5, 5, skin); pixel(10, 18, 5, 1, skinShade);
      // Arms, cuffs and hands.
      for (const x of [2, 19]) {
        pixel(x, 19, 4, 12, outline); pixel(x + 1, 20, 2, 7, col); pixel(x + 1, 27, 2, 4, skin);
      }
      pixel(5, 4, 15, 12, outline); pixel(6, 5, 13, 11, skin);
      pixel(6, 13, 2, 2, skinShade); pixel(17, 8, 2, 7, skinShade);
      // Hair silhouette and staggered fringe.
      pixel(6, 2, 12, 3, outline); pixel(5, 4, 15, 4, hair);
      pixel(4, 7, 3, 5, hair); pixel(18, 7, 3, 5, hair);
      pixel(7, 3, 5, 2, this.lighten(hair, 1.28)); pixel(7, 7, 3, 2, hair); pixel(13, 7, 3, 1, hair);
      if (id % 3 === 0) { pixel(4, 10, 3, 9, hair); pixel(18, 10, 3, 9, hair); }
      pixel(9, 10, 2, 2, outline); pixel(15, 10, 2, 2, outline);
      if (!lying) { pixel(9, 10, 1, 1, 0xfff5df); pixel(15, 10, 1, 1, 0xfff5df); }
      pixel(12, 12, 1, 2, skinShade); pixel(11, 15, 4, 1, 0x9d6448);
      if (id % 4 === 0) { pixel(8, 9, 4, 1, outline); pixel(14, 9, 4, 1, outline); pixel(12, 10, 2, 1, outline); }
      pixel(11, 22, 1, 1, shirtLight); pixel(11, 26, 1, 1, shirtLight);
      // At overview scale, show the artwork rather than overlapping tiny labels.
      if (s < 0.20 && !sel) return;
      // Keep labels small; they follow the visible head rather than a detached anchor.
      const text = `${Array.from(a.name || initials(a.name, a.agent_id)).slice(0, 9).join("")} · ${actEmoji(a.activity || a.scheduled_activity || a.action)}`;
      const labelY = lying ? foot.y - 44 * s : bodyY - 8;
      const label = this.add.text(bodyX, labelY, text, { fontFamily: "VT323, PingFang SC, monospace", fontSize: "11px",
        color: "#344639", backgroundColor: "#fff8e3", padding: { x: 4, y: 2 } }).setOrigin(0.5, 1).setDepth(50);
      this.labels.push(label);
    }

    wanderStep(a, tx, ty, minX, minY, maxX, maxY) {
      tx = Phaser.Math.Clamp(tx, minX, maxX); ty = Phaser.Math.Clamp(ty, minY, maxY);
      let current = this.wander[a.agent_id];
      if (!current) { current = { x: tx, y: ty, walking: false }; this.wander[a.agent_id] = current; }
      // Trace frames are observations: a paused activity must not invent a walk.
      current.x = tx; current.y = ty; current.walking = false;
      return current;
    }
    // Color helpers
    darken(hex, k) {
      const r = Math.max(0, Math.min(255, Math.round(((hex >> 16) & 0xff) * k)));
      const g = Math.max(0, Math.min(255, Math.round(((hex >> 8) & 0xff) * k)));
      const b = Math.max(0, Math.min(255, Math.round((hex & 0xff) * k)));
      return (r << 16) | (g << 8) | b;
    }
    lighten(hex, k) { return this.darken(hex, k); }
  }

  // ---- shared indoor pixel helpers (used for backdrop grass + iso tile patterns) ----
  function px(g, x, y, w, h, c, a) { g.fillStyle(c, a == null ? 1 : a); g.fillRect(x, y, w, h); }
  function grass(g, x, y, w, h) {
    let s = 991; const rnd = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
    for (let i = 0; i < (w * h) / 5000; i++) {
      const gx = x + rnd() * w, gy = y + rnd() * h, r = rnd();
      if (r < 0.7) { px(g, gx, gy, 4, 2, 0x5a964b, 0.5); px(g, gx + 1, gy - 2, 2, 2, 0x5a964b, 0.5); }
      else if (r < 0.85) px(g, gx, gy, 3, 3, 0xe86b6b);
      else px(g, gx, gy, 3, 3, 0xe8c84e);
    }
  }
  // Correct isometric surface polygons for every plank, tile and woven rug.
  function isoSurface(g, x, y, w, h, off, color, alpha = 1) {
    const points = [iso(x,y), iso(x+w,y), iso(x+w,y+h), iso(x,y+h)];
    g.fillStyle(color, alpha); g.beginPath();
    g.moveTo(Math.round(off.sx + points[0].sx), Math.round(off.sy + points[0].sy));
    points.slice(1).forEach(p => g.lineTo(Math.round(off.sx + p.sx), Math.round(off.sy + p.sy)));
    g.closePath(); g.fillPath();
  }
  function isoPlank(g, x, y, w, h, off) {
    const step = 26 * off.scale, length = 110 * off.scale, seam = Math.max(0.5, off.scale);
    for (let row = 0; row * step < h; row++) {
      const yy = y + row * step, hh = Math.min(step, y+h-yy);
      for (let col = -1; col * length < w; col++) {
        const xx = Math.max(x, x + col * length + (row % 2) * length / 2);
        const right = Math.min(x + w, x + (col + 1) * length + (row % 2) * length / 2);
        if (right <= xx) continue;
        const ww = right - xx;
        isoSurface(g, xx, yy, ww, hh, off, 0xa57649, (row + col + 3) % 3 === 0 ? 0.10 : 0.035);
        isoSurface(g, xx, yy, ww, Math.min(seam, hh), off, 0x997348, 0.38);
        isoSurface(g, xx, yy, Math.min(seam, ww), hh, off, 0x997348, 0.38);
        if (ww > length * 0.4) isoSurface(g, xx + ww * 0.20, yy + hh * 0.44, ww * 0.45, seam, off, 0x866641, 0.12);
      }
    }
  }
  function isoTile(g, x, y, w, h, off) {
    const step = 32 * off.scale, grout = Math.max(0.5, off.scale);
    for (let row = 0; row * step < h; row++) for (let col = 0; col * step < w; col++) {
      const xx = x + col * step, yy = y + row * step, ww = Math.min(step,w-col*step), hh = Math.min(step,h-row*step);
      isoSurface(g, xx, yy, ww, hh, off, (row+col)%2 ? 0x789487 : 0xffffff, 0.07);
      isoSurface(g, xx, yy, ww, Math.min(grout,hh), off, 0x718878, 0.24);
      isoSurface(g, xx, yy, Math.min(grout,ww), hh, off, 0x718878, 0.24);
    }
  }
  function isoRug(g, x, y, w, h, off, color) {
    isoSurface(g, x, y, w, h, off, color);
    const inset = Math.min(w,h) * 0.08;
    isoSurface(g, x+inset, y+inset, w-inset*2, h-inset*2, off, 0xe8d7b0);
    isoSurface(g, x+inset*1.5, y+inset*1.5, w-inset*3, h-inset*3, off, color);
    for (let i = 1; i < 9; i++) {
      isoSurface(g, x+w*i/10, y+inset*1.5, Math.max(0.5,off.scale), h-inset*3, off, 0xf2e4c5, 0.4);
    }
  }

  // ---- enter/exit ----
  function enterIndoor(nodeId) {
    state.view = "indoor"; state.indoorLoc = nodeId;
    App.game.scene.sleep("village"); App.game.scene.run("indoor", { nodeId });
    setBtns();
  }
  function exitIndoor() {
    state.view = "village"; state.indoorLoc = null;
    App.game.scene.stop("indoor"); App.game.scene.wake("village");
    setBtns();
  }
  function setBtns() {
    const wrap = $("mapCanvasWrap");
    if (wrap) wrap.parentElement.classList.toggle("is-indoor", state.view === "indoor");
    const v = $("viewVillageBtn"), i = $("viewIndoorBtn");
    if (v && i) { v.classList.toggle("active", state.view === "village"); i.classList.toggle("active", state.view === "indoor"); }
  }

  // ---- data + controls ----
  async function loadTrace() {
    try {
      const res = await fetch(state.dataPath, { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      state.trace = data; state.frames = data.frames || []; state.agents = data.agents || [];
      state.frameIdx = Math.min(state.frameIdx, Math.max(0, state.frames.length - 1));
      const sl = $("timelineSlider"); if (sl) { sl.max = Math.max(0, state.frames.length - 1); sl.value = state.frameIdx; }
      if ($("statusBadge")) $("statusBadge").textContent = state.frames.length ? "已载入" : "无帧";
      if (App.village) App.village.rebuild();
      updateFrameUI();
    } catch (e) {
      if ($("statusBadge")) $("statusBadge").textContent = "加载失败";
      console.warn("loadTrace:", e.message);
    }
  }
  function updateFrameUI() {
    const f = state.frames[state.frameIdx];
    if ($("frameBadge")) $("frameBadge").textContent = "Frame " + state.frameIdx;
    if (f && $("frameTitle")) $("frameTitle").textContent = `Day ${f.day ?? "—"} · ${f.time || ""} ${f.weekday || ""}`;
    if (f && $("timelineLabel")) $("timelineLabel").textContent = `${f.date || ""} ${f.time || ""}`;
  }
  function setFrame(i) {
    state.frameIdx = Math.max(0, Math.min(state.frames.length - 1, i));
    const sl = $("timelineSlider"); if (sl) sl.value = state.frameIdx;
    updateFrameUI();
  }
  function play() { state.playing = true; if ($("playBtn")) $("playBtn").textContent = "暂停"; }
  function pause() { state.playing = false; if ($("playBtn")) $("playBtn").textContent = "播放"; }

  function wire() {
    const zoomBy = (factor, reset = false) => {
      const scene = state.view === "indoor" ? App.indoor : App.village;
      if (!scene) return;
      if (state.view === "indoor") scene.setZoom(reset ? 1 : scene.zoom * factor);
      else {
        if (reset) scene.fit();
        else scene.cameras.main.setZoom(Phaser.Math.Clamp(scene.cameras.main.zoom * factor, 0.1, 4));
      }
    };
    if ($("zoomInBtn")) $("zoomInBtn").addEventListener("click", () => zoomBy(1.25));
    if ($("zoomOutBtn")) $("zoomOutBtn").addEventListener("click", () => zoomBy(0.8));
    if ($("zoomResetBtn")) $("zoomResetBtn").addEventListener("click", () => zoomBy(1, true));
    const dp = $("dataPathInput"); if (dp) { dp.value = state.dataPath; }
    $("reloadBtn") && $("reloadBtn").addEventListener("click", () => { state.dataPath = (dp && dp.value) || state.dataPath; loadTrace(); });
    $("playBtn") && $("playBtn").addEventListener("click", () => (state.playing ? pause() : play()));
    $("timelineSlider") && $("timelineSlider").addEventListener("input", (e) => { pause(); setFrame(+e.target.value); });
    $("speedSelect") && $("speedSelect").addEventListener("change", (e) => { state.speed = +e.target.value || 1; });
    $("viewVillageBtn") && $("viewVillageBtn").addEventListener("click", () => { if (state.view === "indoor") exitIndoor(); });
    $("viewIndoorBtn") && $("viewIndoorBtn").addEventListener("click", () => {
      if (state.view === "village") {
        // enter the location of the selected agent, else first hub
        const f = state.frames[state.frameIdx]; let loc = null;
        if (f && state.selectedId != null) { const a = f.agents.find((x) => x.agent_id === state.selectedId); if (a) loc = a.resolved_location || a.location; }
        if (!loc && state.trace.map) { const hub = state.trace.map.nodes.find((n) => n.kind === "hub"); loc = hub && hub.id; }
        if (loc) enterIndoor(loc);
      }
    });
    $("liveToggle") && $("liveToggle").addEventListener("change", (e) => { state.live = e.target.checked; setupPolling(); });
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && state.view === "indoor") exitIndoor();
      else if (e.code === "Space") { e.preventDefault(); state.playing ? pause() : play(); }
    });
    // playback driver
    let last = 0;
    function loop(ts) {
      if (state.playing && state.frames.length) {
        if (!last) last = ts;
        const interval = 900 / state.speed;
        if (ts - last >= interval) { last = ts; let n = state.frameIdx + 1; if (n >= state.frames.length) n = 0; setFrame(n); }
      } else last = 0;
      requestAnimationFrame(loop);
    }
    requestAnimationFrame(loop);
  }
  function setupPolling() {
    if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
    if (state.live) state.pollTimer = setInterval(() => { if (!state.playing) loadTrace(); }, 4000);
  }

  // ---- boot ----
  // Embedded consumers own the frame and building. They never start village
  // playback, polling or global keyboard handlers.
  function createIndoorRenderer(host, opts = {}) {
    const viewState = { trace: null, frames: [], frameIdx: 0, selectedId: null };
    const scene = new IndoorScene({ state: viewState, embedded: true, onZoom: opts.onZoom });
    const game = new Phaser.Game({
      type: Phaser.AUTO, parent: host, backgroundColor: "#30463d",
      // Console tabs and city/indoor modes hide their parent with display:none.
      // RESIZE would allocate a 0x0 WebGL framebuffer, breaking later renders.
      // The host's ResizeObserver supplies only visible, positive sizes instead.
      scale: { mode: Phaser.Scale.NONE, width: Math.max(1, host.clientWidth || 0),
        height: Math.max(1, host.clientHeight || 0) },
      render: { pixelArt: true, antialias: false }, scene: [scene],
    });
    let sourceTrace = null;
    return {
      render(trace, frame, node, selectedId) {
        const id = node ? node.id : null;
        if (sourceTrace !== trace || scene.nodeId !== id) {
          scene.tree = null; scene.node = null; scene.wander = {};
          if (scene.nodeId !== id) { scene.zoom = 1; scene.pan = { x: 0, y: 0 }; }
        }
        sourceTrace = trace;
        const nodes = (trace && trace.map && trace.map.nodes) || [];
        viewState.trace = node && !nodes.some(n => n.id === id)
          ? { ...trace, map: { ...trace && trace.map, nodes: [...nodes, node] } } : trace;
        viewState.frames = frame ? [frame] : []; viewState.selectedId = selectedId;
        scene.nodeId = id;
        if (scene.g) scene.draw();
        if (opts.onZoom) opts.onZoom(scene.zoom || 1);
      },
      setZoom(value) { if (scene.g) scene.setZoom(value); },
      resize() {
        const width = host.clientWidth, height = host.clientHeight;
        if (!game.isBooted || !(width > 0 && height > 0)) return;
        game.scale.resize(width, height);
        if (scene.g) scene.draw();
      },
      destroy() { game.destroy(true); },
    };
  }
  window.createIndoorRenderer = createIndoorRenderer;

  function boot() {
    const params = new URLSearchParams(location.search);
    state.dataPath = params.get("data") || DEFAULT_DATA_PATH;
    wire();
    App.game = new Phaser.Game({
      type: Phaser.AUTO, parent: "mapCanvasWrap", backgroundColor: "#6fb84e",
      scale: { mode: Phaser.Scale.RESIZE, width: "100%", height: "100%" },
      render: { pixelArt: true, antialias: false },
      scene: [VillageScene, IndoorScene],
    });
    App.game.scene.start("village");
    loadTrace().then(() => setupPolling());
  }

  if (!indoorOnly) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
    else boot();
  }

  window.__SIMVIZ__ = { state, App, activitySlot, VillageScene, IndoorScene, loadTrace, enterIndoor, exitIndoor };
})();
