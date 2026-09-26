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
    agentH: 64,     // character body height on screen
    furnH: 56,      // standard furniture height
    furnShrinkY: 0.5, // floor-plane uses 0.5 squash (matches the projection)
  };

  function iso(ux, uy) {
    return { sx: ux - uy, sy: (ux + uy) * 0.5 };
  }
  function isoRect(g, x, y, w, h, fill) {
    // diamond: top → right → bottom → left
    const a = iso(x, y), b = iso(x + w, y), c = iso(x + w, y + h), d = iso(x, y + h);
    g.fillStyle(fill, 1); g.beginPath(); g.moveTo(a.sx, a.sy); g.lineTo(b.sx, b.sy); g.lineTo(c.sx, c.sy); g.lineTo(d.sx, d.sy); g.closePath(); g.fillPath();
  }
  function isoStroke(g, x, y, w, h, color, lw = 1, alpha = 1) {
    const a = iso(x, y), b = iso(x + w, y), c = iso(x + w, y + h), d = iso(x, y + h);
    g.lineStyle(lw, color, alpha); g.beginPath(); g.moveTo(a.sx, a.sy); g.lineTo(b.sx, b.sy); g.lineTo(c.sx, c.sy); g.lineTo(d.sx, d.sy); g.lineTo(a.sx, a.sy); g.strokePath();
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
  };

  class IndoorScene extends Phaser.Scene {
    constructor() { super("indoor"); }
    init(d) { this.nodeId = d.nodeId; this.wander = {}; this.tree = null; this.node = null; }
    create() {
      App.indoor = this;
      this.g = this.add.graphics();
      this.gWalls = this.add.graphics();
      this.gObjs = this.add.graphics();
      this.gAgents = this.add.graphics();
      this.gUI = this.add.graphics();
      this.labels = [];
      this.cameras.main.setBackgroundColor("#7cc36a");
      this.scale.on("resize", () => this.draw());
      this.draw();
    }
    update(t) { if (!this._l || t - this._l > 70) { this._l = t; this.draw(); } }
    mapNodes() { const m = new Map(); const md = state.trace && state.trace.map; if (md) (md.nodes || []).forEach((n) => m.set(n.id, n)); return m; }
    ensureTree() {
      if (this.tree) return this.tree;
      const GS = (typeof window !== "undefined" && window.GAWorldSpatial) || null;
      const node = this.mapNodes().get(this.nodeId); if (!node || !GS) return null;
      this.node = node; this.tree = GS.buildBuildingTree(node);
      if (window.__SIMVIZ__) window.__SIMVIZ__.indoorTree = this.tree;
      return this.tree;
    }
    draw() {
      const W = this.scale.width, H = this.scale.height;
      const gBg = this.g, gW = this.gWalls, gO = this.gObjs, gA = this.gAgents, gU = this.gUI;
      [gBg, gW, gO, gA, gU].forEach((gg) => gg.clear());
      this.labels.forEach((t) => t.destroy()); this.labels = [];
      // backdrop
      gBg.fillStyle(0x7cc36a, 1); gBg.fillRect(0, 0, W, H);
      const bannerH = 52, padTop = bannerH + 28, padBot = 46;
      const rw = Math.min(W * 0.9, 1100), rh = Math.min((H - padTop - padBot) * 2, 760); // rh is doubled for iso squashing
      const tree = this.ensureTree();
      if (!tree) {
        this.labels.push(this.add.text(W / 2, H / 2, "加载中…", { fontFamily: "VT323, monospace", fontSize: "22px", color: "#1e2c2c" }).setOrigin(0.5));
        return;
      }
      const node = this.node, sector = tree.sector, outdoor = !!tree.outdoor;
      if (!outdoor) grass(gBg, 0, 0, W, H);

      // ---- collect world-space rooms ----
      const arenas = tree.arenaNames(sector);
      const arenaMeta = arenas.map((name) => {
        const m = tree.arena(sector, name).meta;
        return { name, x: m.x * rw, y: m.y * rh, w: m.w * rw, h: m.h * rh, meta: m };
      });
      const arenaByName = Object.fromEntries(arenaMeta.map((a) => [a.name, a]));

      // isometric origin so the whole building is centered
      const aabb = arenas.reduce((b, a) => ({
        x0: Math.min(b.x0, a.x), y0: Math.min(b.y0, a.y),
        x1: Math.max(b.x1, a.x + a.w), y1: Math.max(b.y1, a.y + a.h),
      }), { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity });
      if (!isFinite(aabb.x0)) return;
      const wCx = (aabb.x0 + aabb.x1) / 2, wCy = (aabb.y0 + aabb.y1) / 2;
      const offset = { sx: W / 2 - iso(wCx, wCy).sx, sy: padTop + 80 - iso(wCx, wCy).sy };

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
        if (style.tiled) isoTile(gBg, a.x, a.y, a.w, a.h, offset, 0xffffff, 0.05);
        else isoPlank(gBg, a.x, a.y, a.w, a.h, offset);
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
        shellEdges.forEach((e) => drawables.push({ kind: "wall", e, height: ISO.wallH, depth: e.x + e.y + e.w + e.h }));
        // interior partitions
        arenaMeta.forEach((a) => {
          const door = a.meta.door;
          this.partitionEdgesOf(a, arenaMeta).forEach((e) => {
            drawables.push({ kind: "wall", e, height: 56, depth: e.x + e.y + e.w + e.h, doorSide: door });
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
        if (rec.slot) objSpots.push({ rec, cx: fx + fw / 2, cy: fy + fh / 2, depth });
      });

      // ---- 3) agents ----
      let here = [];
      if (state.frames.length) {
        const frame = state.frames[state.frameIdx];
        here = (frame.agents || []).filter((a) => {
          const loc = a.resolved_location || a.location || a.target_location;
          return loc === this.nodeId && (!a.travel || !/transit|departed/.test(a.travel.status || ""));
        });
      }
      const usedObj = new Set();
      here.forEach((a, i) => {
        const slot = activitySlot(a.activity || a.scheduled_activity || a.action);
        let spot = objSpots.find((o) => o.rec.slot === slot && !usedObj.has(o.rec.address));
        if (!spot && slot) {
          const arena = tree.arenaForActivity(sector, slot);
          const r = arena && arenaByName[arena];
          if (r) spot = { rec: null, cx: r.x + r.w / 2, cy: r.y + r.h / 2, depth: isoDepth(r.x, r.y, r.w, r.h) };
        }
        if (spot && spot.rec) usedObj.add(spot.rec.address);
        // If a furniture spot is taken, displace agent slightly in world-x so
        // we don't sit two agents on one chair.
        const tx = spot ? spot.cx + ((usedObj.size % 3) - 1) * 12 : (aabb.x0 + aabb.x1) / 2 + (i % 5) * 16;
        const ty = spot ? spot.cy + ((usedObj.size % 3) - 1) * 8 : (aabb.y0 + aabb.y1) / 2 + 40;
        const w = this.wanderStep(a, tx, ty, aabb.x0 + 18, aabb.y0 + 18, aabb.x1 - 18, aabb.y1 - 18);
        const lying = (slot === "sleep" || slot === "rest") && !w.walking;
        drawables.push({ kind: "agent", agent: a, ux: w.x, uy: w.y, col: agentColor(a.agent_id), sel: state.selectedId === a.agent_id, lying, depth: w.x + w.y + 6 });
      });

      // ---- 4) paint sorted ----
      drawables.sort((a, b) => a.depth - b.depth);
      drawables.forEach((d) => {
        if (d.kind === "floorEdge") this.drawFloorEdge(d.a, offset);
        else if (d.kind === "wall") this.drawIsoWall(d.e, d.height, offset, d.doorSide);
        else if (d.kind === "furn") this.drawIsoFurn(d.rec, d.fx, d.fy, d.fw, d.fh, offset);
        else if (d.kind === "agent") this.drawIsoAgent(d.agent, d.ux, d.uy, d.col, d.sel, d.lying, offset);
      });

      // ---- 5) UI / banner ----
      const bannerW = 640;
      gU.fillStyle(0x1c2630, 0.92);
      gU.fillRoundedRect(W / 2 - bannerW / 2, 12, bannerW, bannerH, 10);
      this.labels.push(this.add.text(W / 2, 12 + bannerH / 2 - 7, `${outdoor ? "🌳" : "🏠"}  ${(node && (node.label || node.id)) || this.nodeId}`, { fontFamily: "VT323, monospace", fontSize: "24px", color: "#f4ede0" }).setOrigin(0.5).setDepth(20));
      this.labels.push(this.add.text(W / 2, 12 + bannerH / 2 + 13, `${(node && node.category) || ""} · ${arenas.length} 房间 · ${here.length} 人在场 · 点「村落」返回`, { fontFamily: "VT323, monospace", fontSize: "14px", color: "#f4ede0bb" }).setOrigin(0.5).setDepth(20));
      // small room tags
      arenaMeta.forEach((a) => {
        const p = offset.sx + iso(a.x, a.y).sx;
        const py = offset.sy + iso(a.x, a.y).sy;
        this.labels.push(this.add.text(p + 4, py - 6, a.name, { fontFamily: "VT323, monospace", fontSize: "11px", color: outdoor ? "#2c4a2c" : "#7a6a55" }).setOrigin(0, 1).setDepth(3));
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
      const eps = 1.5;
      const t = 4; // thin partition thickness
      const onB = {
        N: all.some((o) => Math.abs(o.y + o.h - a.y) < eps && o.x < a.x + a.w - eps && o.x + o.w > a.x + eps),
        S: all.some((o) => Math.abs(o.y - (a.y + a.h)) < eps && o.x < a.x + a.w - eps && o.x + o.w > a.x + eps),
        W: all.some((o) => Math.abs(o.x + o.w - a.x) < eps && o.y < a.y + a.h - eps && o.y + o.h > a.y + eps),
        E: all.some((o) => Math.abs(o.x - (a.x + a.w)) < eps && o.y < a.y + a.h - eps && o.y + o.h > a.y + eps),
      };
      const out = [];
      if (!onB.N) out.push({ x: a.x, y: a.y - t / 2, w: a.w, h: t, side: "N" });
      if (!onB.S) out.push({ x: a.x, y: a.y + a.h - t / 2, w: a.w, h: t, side: "S" });
      if (!onB.W) out.push({ x: a.x - t / 2, y: a.y, w: t, h: a.h, side: "W" });
      if (!onB.E) out.push({ x: a.x + a.w - t / 2, y: a.y, w: t, h: a.h, side: "E" });
      return out;
    }
    drawIsoWall(e, height, off, doorSide) {
      // Render an axis-aligned wall in world space as an extruded slab.
      // e is {x, y, w, h, side} in world units. height is vertical lift (screen px).
      const g = this.gWalls;
      const isHoriz = e.h === 0;
      const horiz = !isHoriz; // we always render the wall facing the camera
      // doorway: when doorSide matches e.side, punch a centered gap
      const gapFrac = 0.35;
      const segments = (doorSide === e.side)
        ? (isHoriz
            ? [{ o0: 0, o1: (1 - gapFrac) / 2 }, { o0: (1 + gapFrac) / 2, o1: 1 }]
            : [{ o0: 0, o1: (1 - gapFrac) / 2 }, { o0: (1 + gapFrac) / 2, o1: 1 }])
        : [{ o0: 0, o1: 1 }];
      segments.forEach((seg) => {
        if (seg.o1 - seg.o0 < 0.01) return;
        const sx = e.x + (isHoriz ? seg.o0 * e.w : 0);
        const sy = e.y + (isHoriz ? 0 : seg.o0 * e.h);
        const sw = (isHoriz ? (seg.o1 - seg.o0) * e.w : e.w);
        const sh = (isHoriz ? e.h : (seg.o1 - seg.o0) * e.h);
        // 4 corners on the floor (world space) + 4 on the ceiling (lift by -height on screen)
        const p = (px, py, top) => ({ sx: off.sx + iso(px, py).sx, sy: off.sy + iso(px, py).sy - (top ? height : 0) });
        const bl = p(sx, sy, false), br = p(sx + sw, sy + sh, false);
        const tl = p(sx, sy, true), tr = p(sx + sw, sy + sh, true);
        // Visible faces of a slab depend on side. We pick the two faces whose
        // outward normal points away from the room interior:
        //   side=N (top, e.h=0): visible = top quad + back-left quad (W of slab? actually E face when w>0)
        // Simpler heuristic: always draw the front (toward camera = toward higher ux+uy) face and the top quad.
        // For an N-edge (y=const, h=0) we draw the "south" face (toward higher y).
        let frontFace, topFace;
        if (e.side === "N") {        // y = const; front = south face (toward y+)
          frontFace = [p(sx, sy, false), p(sx + sw, sy + sh, false), p(sx + sw, sy + sh, true), p(sx, sy, true)];
          topFace   = [p(sx, sy, true), p(sx + sw, sy + sh, true), p(sx + sw, sy + sh, false), p(sx, sy, false)];
        } else if (e.side === "S") { // south edge; front = north face
          frontFace = [p(sx, sy, true), p(sx + sw, sy + sh, true), p(sx + sw, sy + sh, false), p(sx, sy, false)];
          topFace   = [p(sx, sy, true), p(sx + sw, sy + sh, true), p(sx + sw, sy + sh, false), p(sx, sy, false)];
        } else if (e.side === "W") { // left edge; front = east face
          frontFace = [p(sx + sw, sy, false), p(sx + sw, sy + sh, false), p(sx + sw, sy + sh, true), p(sx, sy, true)];
          topFace   = [p(sx, sy, true), p(sx + sw, sy + sh, true), p(sx + sw, sy + sh, false), p(sx, sy, false)];
        } else {                      // E
          frontFace = [p(sx, sy, false), p(sx, sy + sh, false), p(sx, sy + sh, true), p(sx, sy, true)];
          topFace   = [p(sx, sy, true), p(sx, sy + sh, true), p(sx, sy + sh, false), p(sx, sy, false)];
        }
        const quad = (pts, fill, alpha = 1) => { g.fillStyle(fill, alpha); g.beginPath(); g.moveTo(pts[0].sx, pts[0].sy); pts.slice(1).forEach((pt) => g.lineTo(pt.sx, pt.sy)); g.closePath(); g.fillPath(); };
        // Front face: warm gray with subtle vertical gradient (lit from north-west)
        quad(frontFace, 0x9aa0a8, 1);
        quad(frontFace, 0xffffff, 0.05);
        // Top face: lighter, slight blue tint (sky light)
        quad(topFace, 0xc4c9cf, 1);
        // subtle outline on top edge for definition
        g.lineStyle(1, 0x6f757d, 0.6); g.beginPath(); g.moveTo(topFace[0].sx, topFace[0].sy); topFace.slice(1).forEach((pt) => g.lineTo(pt.sx, pt.sy)); g.closePath(); g.strokePath();
      });
    }
    drawIsoFurn(rec, x, y, w, h, off) {
      const g = this.gObjs;
      const kind = rec.kind || "default";
      const hp = (px, py, top) => ({ sx: off.sx + iso(px, py).sx, sy: off.sy + iso(px, py).sy - (top ? this.furnHeight(kind) : 0) });
      // box faces: front (south & east) + top + side
      const baseColor = this.furnColor(kind);
      const dark = this.darken(baseColor, 0.78);
      const lite = this.lighten(baseColor, 1.18);
      const sw = w, sh = h;
      const H = this.furnHeight(kind);
      // For non-rectangular kinds we fall back to a colored box. Custom
      // silhouettes are layered on top.
      // South face (y+ constant)
      const south = [hp(x, y + sh, false), hp(x + sw, y + sh, false), hp(x + sw, y + sh, true), hp(x, y + sh, true)];
      const east  = [hp(x + sw, y, false), hp(x + sw, y + sh, false), hp(x + sw, y + sh, true), hp(x + sw, y, true)];
      const top   = [hp(x, y, true), hp(x + sw, y, true), hp(x + sw, y + sh, true), hp(x, y + sh, true)];
      const quad = (pts, fill, alpha = 1) => { g.fillStyle(fill, alpha); g.beginPath(); g.moveTo(pts[0].sx, pts[0].sy); pts.slice(1).forEach((pt) => g.lineTo(pt.sx, pt.sy)); g.closePath(); g.fillPath(); };
      // Soft contact shadow under the box
      const shadowPts = [
        { sx: off.sx + iso(x + 4, y + sh + 4).sx, sy: off.sy + iso(x + 4, y + sh + 4).sy },
        { sx: off.sx + iso(x + sw - 4, y + sh + 4).sx, sy: off.sy + iso(x + sw - 4, y + sh + 4).sy },
        { sx: off.sx + iso(x + sw, y + sh).sx, sy: off.sy + iso(x + sw, y + sh).sy },
        { sx: off.sx + iso(x, y + sh).sx, sy: off.sy + iso(x, y + sh).sy },
      ];
      g.fillStyle(0x000000, 0.18);
      g.beginPath(); g.moveTo(shadowPts[0].sx, shadowPts[0].sy); shadowPts.slice(1).forEach((pt) => g.lineTo(pt.sx, pt.sy)); g.closePath(); g.fillPath();

      quad(south, dark);
      quad(east, this.darken(baseColor, 0.62));
      quad(top, lite);

      // Highlight along front-top edge
      g.lineStyle(1, 0xffffff, 0.18); g.beginPath();
      g.moveTo(south[2].sx, south[2].sy); g.lineTo(south[3].sx, south[3].sy); g.strokePath();

      // ---- custom silhouettes on top of the box ----
      this.drawFurnDetail(rec, x, y, w, h, off, H, baseColor);
    }
    furnHeight(kind) {
      // Override by kind for variety. Everything else gets a sensible default.
      const map = { bed: 40, sofa: 50, wardrobe: 110, fridge: 110, piano: 90, bookshelf: 130, shelf: 95, chalkboard: 120,
        stove: 80, kitchen: 90, plant: 60, tree: 180, fountain: 30, bench: 36, toilet: 50, sink: 80, bathtub: 50,
        counter: 95, checkout: 90, desk: 80, coffee_machine: 80, podium: 90, tv: 90, table: 70, coffee_table: 40, chair: 90, nightstand: 60 };
      return map[kind] || ISO.furnH;
    }
    furnColor(kind) {
      const map = {
        bed: 0x8b5a2b, nightstand: 0xa87042, kitchen: 0xcfc3a0, fridge: 0xe8e8e0,
        table: 0xb07a45, coffee_table: 0x7a5331, chair: 0xc84c4c, desk: 0xcaa06a,
        sofa: 0x5a67a8, tv: 0x1c2630, bookshelf: 0x8b5a2b, shelf: 0x8b5a2b,
        counter: 0x7d5331, coffee_machine: 0xbfb6a3, chalkboard: 0x3a4d3a, podium: 0x8b5a2b,
        checkout: 0x7d5331, plant: 0x5cc2a8, tree: 0x4e8c3a, fountain: 0x9aa0a8,
        bench: 0xbfa074, toilet: 0xeaeef0, sink: 0xdfe6ea, bathtub: 0xccd8dd,
        wardrobe: 0x9a6b3f, stove: 0x6b6f74, piano: 0x26262c,
      };
      return map[kind] || 0xbfb6a3;
    }
    drawFurnDetail(rec, x, y, w, h, off, H, base) {
      const g = this.gObjs;
      const hp = (px, py, top) => ({ sx: off.sx + iso(px, py).sx, sy: off.sy + iso(px, py).sy - (top ? H : 0) });
      const kind = rec.kind;
      const cx = x + w / 2, cz = y + h / 2;
      // pixels drawn at world-space size, projected
      switch (kind) {
        case "bed": {
          // pillow stripe near head (smaller y)
          const py = y + Math.min(8, h * 0.2);
          const rect = (xa, ya, wa, ha, col, a = 1) => {
            const p = [hp(xa, ya, true), hp(xa + wa, ya, true), hp(xa + wa, ya + ha, true), hp(xa, ya + ha, true)];
            g.fillStyle(col, a); g.beginPath(); g.moveTo(p[0].sx, p[0].sy); p.slice(1).forEach((pt) => g.lineTo(pt.sx, pt.sy)); g.closePath(); g.fillPath();
          };
          rect(x + 4, py, w - 8, h * 0.18, 0xfff5d6);
          // blanket (rest of bed)
          rect(x + 4, py + h * 0.2, w - 8, h - h * 0.2 - 4, 0xd96b4e);
          break;
        }
        case "sofa": {
          // backrest along north edge (smaller y)
          g.fillStyle(0x4a5690, 1);
          const p = [hp(x, y, true), hp(x + w, y, true), hp(x + w, y, false), hp(x, y, false)];
          g.beginPath(); g.moveTo(p[0].sx, p[0].sy); p.slice(1).forEach((pt) => g.lineTo(pt.sx, pt.sy)); g.closePath(); g.fillPath();
          // seat cushions (2 stripes)
          const c1 = [hp(x + w * 0.05, y + 6, true), hp(x + w * 0.5, y + 6, true), hp(x + w * 0.5, y + h * 0.6, true), hp(x + w * 0.05, y + h * 0.6, true)];
          g.fillStyle(0x6e7cc0, 1); g.beginPath(); g.moveTo(c1[0].sx, c1[0].sy); c1.slice(1).forEach((pt) => g.lineTo(pt.sx, pt.sy)); g.closePath(); g.fillPath();
          const c2 = [hp(x + w * 0.55, y + 6, true), hp(x + w * 0.95, y + 6, true), hp(x + w * 0.95, y + h * 0.6, true), hp(x + w * 0.55, y + h * 0.6, true)];
          g.fillStyle(0x6e7cc0, 1); g.beginPath(); g.moveTo(c2[0].sx, c2[0].sy); c2.slice(1).forEach((pt) => g.lineTo(pt.sx, pt.sy)); g.closePath(); g.fillPath();
          break;
        }
        case "tv": {
          // screen face on south edge
          const p = [hp(x + 4, y + h - 4, true), hp(x + w - 4, y + h - 4, true), hp(x + w - 4, y + h - 4, true), hp(x + 4, y + h - 4, true)];
          g.fillStyle(0x2e4a6a, 1); g.fillRect(p[0].sx - 1, p[0].sy - 24, (p[1].sx - p[0].sx) + 2, 22);
          break;
        }
        case "table": case "desk": {
          // small object on top (book for desk, plate for table)
          if (kind === "desk") {
            const bx = x + w * 0.6, bz = y + h * 0.3, bw = w * 0.28, bh = h * 0.4;
            const p = [hp(bx, bz, true), hp(bx + bw, bz, true), hp(bx + bw, bz + bh, true), hp(bx, bz + bh, true)];
            g.fillStyle(0x3a4658, 1); g.beginPath(); g.moveTo(p[0].sx, p[0].sy); p.slice(1).forEach((pt) => g.lineTo(pt.sx, pt.sy)); g.closePath(); g.fillPath();
          } else {
            const plate = hp(cx, cz, true);
            g.fillStyle(0xffffff, 1); g.fillCircle(plate.sx, plate.sy - 2, Math.min(w, h) * 0.18);
          }
          break;
        }
        case "bookshelf": case "shelf": {
          // shelf lines: horizontal stripes on south face
          const cs = [0xc84c61, 0x5a9bd4, 0x7b8f27, 0xe0a458, 0x5cc2a8];
          const stripes = 4;
          for (let i = 0; i < stripes; i++) {
            const ty = y + (h * (i + 0.5) / stripes);
            const p = [hp(x + 1, ty, true), hp(x + w - 1, ty, true)];
            g.lineStyle(Math.max(2, h * 0.18), cs[i % cs.length], 1);
            g.beginPath(); g.moveTo(p[0].sx, p[0].sy); g.lineTo(p[1].sx, p[1].sy); g.strokePath();
          }
          break;
        }
        case "stove": {
          // 4 burners on top
          for (let i = 0; i < 2; i++) for (let j = 0; j < 2; j++) {
            const bx = x + w * (0.3 + i * 0.4), bz = y + h * (0.32 + j * 0.36);
            const p = hp(bx, bz, true);
            g.fillStyle(0x121417, 1); g.fillCircle(p.sx, p.sy, Math.min(w, h) * 0.13);
          }
          break;
        }
        case "fridge": {
          // horizontal split line
          const p = [hp(x + 1, y + h * 0.45, true), hp(x + w - 1, y + h * 0.45, true)];
          g.lineStyle(2, 0xb8b8b0, 1); g.beginPath(); g.moveTo(p[0].sx, p[0].sy); g.lineTo(p[1].sx, p[1].sy); g.strokePath();
          break;
        }
        case "piano": {
          // keyboard on south side
          const kh = Math.min(10, H * 0.35);
          const ky = y + h - 2;
          // base of keyboard on top face front edge
          const base = [hp(x + 2, ky, true), hp(x + w - 2, ky, true), hp(x + w - 2, ky, true), hp(x + 2, ky, true)];
          g.fillStyle(0xfbfbf6, 1); g.beginPath();
          g.moveTo(base[0].sx, base[0].sy - kh);
          g.lineTo(base[1].sx, base[1].sy - kh);
          g.lineTo(base[1].sx, base[1].sy);
          g.lineTo(base[0].sx, base[0].sy);
          g.closePath(); g.fillPath();
          break;
        }
        case "plant": {
          // canopy of leaves
          const cxw = cx, czy = cz;
          const cs = [
            { sx: off.sx + iso(cxw, czy).sx, sy: off.sy + iso(cxw, czy).sy - H * 0.5 },
          ];
          g.fillStyle(0x5cc2a8, 1); g.fillCircle(cs[0].sx, cs[0].sy, Math.min(w, h) * 0.55);
          g.fillStyle(0x4a9c80, 1); g.fillCircle(cs[0].sx - 3, cs[0].sy + 2, Math.min(w, h) * 0.4);
          // pot ring on top of trunk box (south face top edge)
          const top = hp(cx, cz, true);
          g.fillStyle(0x6f4a28, 1); g.fillRect(top.sx - 3, top.sy - 2, 6, 4);
          break;
        }
        case "tree": {
          const cs = [{ sx: off.sx + iso(cx, cz).sx, sy: off.sy + iso(cx, cz).sy - H * 0.55 }];
          g.fillStyle(0x4e8c3a, 1); g.fillCircle(cs[0].sx, cs[0].sy, Math.min(w, h) * 0.7);
          g.fillStyle(0x3a6e2c, 1); g.fillCircle(cs[0].sx - 4, cs[0].sy + 3, Math.min(w, h) * 0.55);
          break;
        }
        case "fountain": {
          const cxw = cx, czy = cz;
          const p = { sx: off.sx + iso(cxw, czy).sx, sy: off.sy + iso(cxw, czy).sy - H * 0.4 };
          g.fillStyle(0x5aa6d8, 1); g.fillCircle(p.sx, p.sy, Math.min(w, h) * 0.4);
          g.fillStyle(0xbfe1f2, 1); g.fillCircle(p.sx, p.sy, Math.min(w, h) * 0.22);
          break;
        }
        case "toilet": {
          // bowl (oval) on top
          const p = hp(cx, cz, true);
          g.fillStyle(0xf6f9fa, 1); g.fillEllipse(p.sx, p.sy, w * 0.6, h * 0.5);
          g.fillStyle(0xc4d0d6, 1); g.fillEllipse(p.sx, p.sy, w * 0.4, h * 0.3);
          break;
        }
        case "sink": {
          const p = hp(cx, y + h * 0.3, true);
          g.fillStyle(0xc2ccd2, 1); g.fillEllipse(p.sx, p.sy, w * 0.74, h * 0.42);
          g.fillStyle(0xeef3f5, 1); g.fillEllipse(p.sx, p.sy, w * 0.5, h * 0.28);
          break;
        }
        case "bathtub": {
          const p = hp(cx, cz, true);
          g.fillStyle(0xffffff, 1); g.fillEllipse(p.sx, p.sy, w * 0.85, h * 0.7);
          g.fillStyle(0xbfe1f2, 1); g.fillEllipse(p.sx, p.sy, w * 0.65, h * 0.5);
          break;
        }
        case "coffee_table": {
          // mug on top
          const p = hp(cx + w * 0.15, cz, true);
          g.fillStyle(0xffffff, 1); g.fillCircle(p.sx, p.sy - 2, 4);
          break;
        }
        case "chair": {
          // backrest line on north edge
          g.fillStyle(0xa83a3a, 1);
          const p = [hp(x + 1, y, true), hp(x + w - 1, y, true), hp(x + w - 1, y, false), hp(x + 1, y, false)];
          g.beginPath(); g.moveTo(p[0].sx, p[0].sy); p.slice(1).forEach((pt) => g.lineTo(pt.sx, pt.sy)); g.closePath(); g.fillPath();
          break;
        }
        case "wardrobe": {
          // vertical split line
          const p = [hp(x + w / 2, y + 2, true), hp(x + w / 2, y + h - 2, true)];
          g.lineStyle(1, 0x6f4a28, 1); g.beginPath(); g.moveTo(p[0].sx, p[0].sy); g.lineTo(p[1].sx, p[1].sy); g.strokePath();
          // handles
          const pa = hp(x + w / 2 - 3, y + h * 0.45, true);
          const pb = hp(x + w / 2 + 2, y + h * 0.45, true);
          g.fillStyle(0x3a2a1a, 1); g.fillRect(pa.sx, pa.sy, 1.5, 5); g.fillRect(pb.sx, pb.sy, 1.5, 5);
          break;
        }
        case "chalkboard": {
          // dark front face
          const p = [hp(x + 4, y + 4, true), hp(x + w - 4, y + 4, true), hp(x + w - 4, y + h - 4, true), hp(x + 4, y + h - 4, true)];
          g.fillStyle(0x2e3e2e, 1); g.beginPath(); g.moveTo(p[0].sx, p[0].sy); p.slice(1).forEach((pt) => g.lineTo(pt.sx, pt.sy)); g.closePath(); g.fillPath();
          break;
        }
        default: break;
      }
    }
    drawIsoAgent(a, ux, uy, col, sel, lying, off) {
      const g = this.gAgents;
      const H = ISO.agentH;
      const hp = (px, py, top) => ({ sx: off.sx + iso(px, py).sx, sy: off.sy + iso(px, py).sy - (top ? H : 0) });
      const p = hp(ux, uy, true);
      const foot = hp(ux, uy, false);
      // contact shadow on floor (isometric ellipse)
      g.fillStyle(0x000000, 0.22);
      g.beginPath();
      g.ellipse(foot.sx, foot.sy, 18, 6, 0, 0, Math.PI * 2);
      g.fillPath();
      if (lying) {
        // sideways blob
        g.fillStyle(col, 1); g.fillRect(p.sx - 6, p.sy + 4, H * 0.7, 12);
        g.fillStyle(0xf0c79a, 1); g.fillCircle(p.sx + H * 0.32, p.sy + 10, 7);
        g.fillStyle(0x3a2a1a, 1); g.fillRect(p.sx + H * 0.34, p.sy + 7, 8, 3);
      } else {
        // standing — head on top of a tapered body
        // body (rectangle, slightly forward-leaning)
        const bw = 14, bh = 28;
        g.fillStyle(col, 1); g.fillRect(p.sx - bw / 2, p.sy - bh + 8, bw, bh - 8);
        // belt shadow
        g.fillStyle(0x000000, 0.25); g.fillRect(p.sx - bw / 2, p.sy - bh + 8, bw, 3);
        // head
        g.fillStyle(0xf0c79a, 1); g.fillCircle(p.sx, p.sy - bh + 4, 7);
        // hair cap
        g.fillStyle(0x3a2a1a, 1); g.fillRect(p.sx - 7, p.sy - bh - 1, 14, 5);
        g.fillCircle(p.sx, p.sy - bh + 0, 7);
        // shoes (tiny darker pixels at the foot)
        g.fillStyle(0x3a2a1a, 1); g.fillRect(foot.sx - 7, foot.sy - 3, 5, 3);
        g.fillRect(foot.sx + 2, foot.sy - 3, 5, 3);
      }
      // selection ring
      if (sel) { g.lineStyle(2, 0xffffff, 1); g.strokeEllipse(foot.sx, foot.sy, 26, 10); }
      // name + emoji bubble (always above head)
      const text = `${initials(a.name, a.agent_id)}: ${actEmoji(a.activity || a.scheduled_activity || a.action)}`;
      const headY = p.sy - H + 0 - 24;
      this.labels.push(this.add.text(p.sx, headY, text, { fontFamily: "VT323, monospace", fontSize: "16px", color: "#1e2c2c", backgroundColor: "#ffffff", padding: { x: 7, y: 4 } }).setOrigin(0.5).setDepth(50));
    }
    wanderStep(a, tx, ty, minX, minY, maxX, maxY) {
      let s = this.wander[a.agent_id]; const now = performance.now();
      if (!s) { s = { x: tx, y: ty, tx, ty, walking: false, hold: now + 2000 + Math.random() * 3000 }; this.wander[a.agent_id] = s; return s; }
      if (Math.abs(tx - s.tx) + Math.abs(ty - s.ty) > 6) { s.tx = tx; s.ty = ty; s.walking = true; }
      if (!s.walking && now > s.hold) { s.tx = Phaser.Math.Clamp(tx + (Math.random() - 0.5) * 90, minX, maxX); s.ty = Phaser.Math.Clamp(ty + (Math.random() - 0.5) * 50, minY, maxY); s.walking = true; }
      const dx = s.tx - s.x, dy = s.ty - s.y, d = Math.hypot(dx, dy);
      if (d < 2) { s.x = s.tx; s.y = s.ty; if (s.walking) { s.walking = false; s.hold = now + 2500 + Math.random() * 4000; } }
      else { const st = Math.min(d, 1.6); s.x += dx / d * st; s.y += dy / d * st; }
      return s;
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
  // Plank stripes drawn in world space: rows of slightly darker fills separated by lines.
  function isoPlank(g, x, y, w, h, off) {
    const stripe = 20;
    for (let row = 0; row * stripe < h; row++) {
      const yy = y + row * stripe;
      const sh = Math.min(stripe, h - row * stripe);
      if (row % 2 === 1) {
        g.fillStyle(0x785028, 0.06);
        const a = { sx: off.sx + iso(x, yy).sx, sy: off.sy + iso(x, yy).sy };
        const b = { sx: off.sx + iso(x + w, yy).sx, sy: off.sy + iso(x + w, yy).sy };
        g.beginPath(); g.moveTo(a.sx, a.sy); g.lineTo(b.sx, b.sy);
        g.lineTo(b.sx, b.sy + sh * 0.5); g.lineTo(a.sx, a.sy + sh * 0.5);
        g.closePath(); g.fillPath();
      }
    }
  }
  function isoTile(g, x, y, w, h, off, col, alpha) {
    const t = 26;
    for (let row = 0; row * t < h; row++) for (let col2 = 0; col2 * t < w; col2++) {
      if ((row + col2) % 2 === 0) {
        const xx = x + col2 * t, yy = y + row * t;
        const tw = Math.min(t, w - col2 * t), th = Math.min(t, h - row * t);
        const a = { sx: off.sx + iso(xx, yy).sx, sy: off.sy + iso(xx, yy).sy };
        const b = { sx: off.sx + iso(xx + tw, yy).sx, sy: off.sy + iso(xx + tw, yy).sy };
        const c = { sx: off.sx + iso(xx + tw, yy + th).sx, sy: off.sy + iso(xx + tw, yy + th).sy };
        const d = { sx: off.sx + iso(xx, yy + th).sx, sy: off.sy + iso(xx, yy + th).sy };
        g.fillStyle(col, alpha); g.beginPath(); g.moveTo(a.sx, a.sy); g.lineTo(b.sx, b.sy); g.lineTo(c.sx, c.sy); g.lineTo(d.sx, d.sy); g.closePath(); g.fillPath();
      }
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

  if (typeof Phaser === "undefined") {
    if ($("statusBadge")) $("statusBadge").textContent = "Phaser 未加载";
  } else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  window.__SIMVIZ__ = { state, App, activitySlot, VillageScene, IndoorScene, loadTrace, enterIndoor, exitIndoor };
})();
