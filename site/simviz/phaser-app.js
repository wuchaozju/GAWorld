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

  // ===== INDOOR SCENE (multi-room floor plan from the spatial tree) =====
  // room.type → floor tint / pattern (drawn with the existing floor() helper)
  const ROOM_FLOOR = {
    bedroom: { floor: 0xf0d9a8 }, living: { floor: 0xf0d9a8 },
    bathroom: { floor: 0xdfeaee, tiled: true }, kitchen: { floor: 0xe8dcc0, tiled: true },
    study: { floor: 0xdfd6c2 }, office: { floor: 0xdfd6c2 }, reception: { floor: 0xe4ddcb },
    meeting: { floor: 0xdfd6c2 }, ward: { floor: 0xe8eef0, tiled: true },
    consult: { floor: 0xe8eef0, tiled: true }, pharmacy: { floor: 0xe8eef0, tiled: true },
    classroom: { floor: 0xd8c89a }, library: { floor: 0xe6dcb4 },
    shop: { floor: 0xe8d8b8, tiled: true }, storeroom: { floor: 0xded0b0, tiled: true },
    checkout: { floor: 0xe8d8b8, tiled: true }, seating: { floor: 0xe6d3a8 },
    counter: { floor: 0xe6d3a8 }, park: { floor: 0x7da35d, outdoor: true },
  };

  class IndoorScene extends Phaser.Scene {
    constructor() { super("indoor"); }
    init(d) { this.nodeId = d.nodeId; this.wander = {}; this.tree = null; this.node = null; }
    create() { App.indoor = this; this.g = this.add.graphics(); this.labels = []; this.cameras.main.setBackgroundColor("#7cc36a"); this.scale.on("resize", () => this.draw()); this.draw(); }
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
      const g = this.g; g.clear(); this.labels.forEach((t) => t.destroy()); this.labels = [];
      const W = this.scale.width, H = this.scale.height;
      g.fillStyle(0x7cc36a, 1); g.fillRect(0, 0, W, H);
      const bannerH = 52, padX = Math.max(40, W * 0.06), padTop = bannerH + 28, padBot = 46;
      const rx = padX, ry = padTop, rw = W - padX * 2, rh = H - padTop - padBot;
      const tree = this.ensureTree();
      if (!tree) { this.labels.push(this.add.text(W / 2, H / 2, "加载中…", { fontFamily: "VT323, monospace", fontSize: "22px", color: "#1e2c2c" }).setOrigin(0.5)); return; }
      const node = this.node, sector = tree.sector, outdoor = !!tree.outdoor;
      if (!outdoor) grass(g, 0, 0, W, H);

      // ---- rooms: geometry + objects walked straight off the tree ----
      const arenaRects = {}, objSpots = [];
      const arenas = tree.arenaNames(sector);
      arenas.forEach((name) => {
        const m = tree.arena(sector, name).meta;
        const r = { x: rx + m.x * rw, y: ry + m.y * rh, w: m.w * rw, h: m.h * rh };
        arenaRects[name] = r;
        const style = ROOM_FLOOR[m.type] || { floor: 0xe6dcc4 };
        floor(g, { floor: style.floor, tiled: !!style.tiled, outdoor }, r.x, r.y, r.w, r.h);
      });
      if (!outdoor) {
        this.drawShell(g, rx, ry, rw, rh);
        arenas.forEach((name) => { const r = arenaRects[name]; this.drawPartitions(g, r.x, r.y, r.w, r.h, tree.arena(sector, name).meta.door, rx, ry, rw, rh); });
      }
      tree.objects(sector).forEach((rec) => {
        const r = arenaRects[rec.arena]; if (!r) return;
        const fx = r.x + rec.geom.x * r.w, fy = r.y + rec.geom.y * r.h, fw = rec.geom.w * r.w, fh = rec.geom.h * r.h;
        furn(g, rec.kind, fx, fy, fw, fh);
        if (rec.slot) objSpots.push({ rec, cx: fx + fw / 2, cy: fy + fh / 2 });
      });
      // small room tags — the spatial index made visible
      arenas.forEach((name) => { const r = arenaRects[name]; this.labels.push(this.add.text(r.x + 5, r.y + 3, name, { fontFamily: "VT323, monospace", fontSize: "12px", color: outdoor ? "#2c4a2c" : "#7a6a55" }).setOrigin(0, 0).setDepth(3)); });

      // ---- agents dropped into the room their activity belongs to ----
      let here = [];
      if (state.frames.length) { const frame = state.frames[state.frameIdx]; here = (frame.agents || []).filter((a) => { const loc = a.resolved_location || a.location || a.target_location; return loc === this.nodeId && (!a.travel || !/transit|departed/.test(a.travel.status || "")); }); }
      const usedObj = new Set();
      here.forEach((a, i) => {
        const slot = activitySlot(a.activity || a.scheduled_activity || a.action);
        let spot = objSpots.find((o) => o.rec.slot === slot && !usedObj.has(o.rec.address));
        if (!spot && slot) { const arena = tree.arenaForActivity(sector, slot), r = arena && arenaRects[arena]; if (r) spot = { rec: null, cx: r.x + r.w / 2, cy: r.y + r.h / 2 }; }
        if (spot && spot.rec) usedObj.add(spot.rec.address);
        const tx = spot ? spot.cx : rx + rw * (0.2 + (i % 5) * 0.15), ty = spot ? spot.cy : ry + rh * 0.85;
        const w = this.wanderStep(a, tx, ty, rx + 18, ry + 18, rx + rw - 18, ry + rh - 18);
        const lying = (slot === "sleep" || slot === "rest") && !w.walking;
        this.drawAgent(g, a, w.x, w.y, agentColor(a.agent_id), state.selectedId === a.agent_id, lying);
      });

      // ---- banner ----
      g.fillStyle(0x1c2630, 0.92); g.fillRoundedRect(W / 2 - 320, 12, 640, bannerH, 10);
      this.labels.push(this.add.text(W / 2, 12 + bannerH / 2 - 7, `${outdoor ? "🌳" : "🏠"}  ${(node && (node.label || node.id)) || this.nodeId}`, { fontFamily: "VT323, monospace", fontSize: "24px", color: "#f4ede0" }).setOrigin(0.5));
      this.labels.push(this.add.text(W / 2, 12 + bannerH / 2 + 13, `${(node && node.category) || ""} · ${arenas.length} 房间 · ${here.length} 人在场 · 点「村落」返回`, { fontFamily: "VT323, monospace", fontSize: "14px", color: "#f4ede0bb" }).setOrigin(0.5));
    }
    drawShell(g, rx, ry, rw, rh) {
      const wt = 14, doorW = 64, doorX = rx + rw / 2 - doorW / 2;
      wall(g, rx - wt, ry - wt, rw + wt * 2, wt); wall(g, rx - wt, ry, wt, rh); wall(g, rx + rw, ry, wt, rh);
      wall(g, rx - wt, ry + rh, doorX - rx + wt, wt); wall(g, doorX + doorW, ry + rh, rx + rw + wt - (doorX + doorW), wt);
      g.fillStyle(0x7a5a3a, 1); g.fillRect(doorX, ry + rh - 2, doorW, wt + 2); g.fillStyle(0x8b6a44, 1); g.fillRect(doorX + 4, ry + rh, doorW - 8, wt - 4);
      const wc = Math.max(2, Math.floor(rw / 320)), ww = 78;
      for (let i = 0; i < wc; i++) { const wx = rx + (rw / (wc + 1)) * (i + 1) - ww / 2, wy = ry - wt; g.fillStyle(0xbfe1f2, 1); g.fillRect(wx, wy + 2, ww, wt - 4); g.fillStyle(0x8fc4e0, 1); g.fillRect(wx, wy + 2, ww, 2); g.lineStyle(1, 0x6f757d, 1); g.strokeRect(wx, wy + 2, ww, wt - 4); }
    }
    // thin interior partitions; the room's `door` side gets a centered gap (a doorway)
    drawPartitions(g, x, y, w, h, door, rx, ry, rw, rh) {
      const t = 6, eps = 1.5;
      const onB = { N: y <= ry + eps, S: y + h >= ry + rh - eps, W: x <= rx + eps, E: x + w >= rx + rw - eps };
      const gap = Math.min(34, Math.min(w, h) * 0.5);
      const seg = (sx, sy, sw, sh, horiz, isDoor) => {
        if (!isDoor) { wall(g, sx, sy, sw, sh); return; }
        if (horiz) { const g1 = (sw - gap) / 2; wall(g, sx, sy, g1, sh); wall(g, sx + sw - g1, sy, g1, sh); }
        else { const g1 = (sh - gap) / 2; wall(g, sx, sy, sw, g1); wall(g, sx, sy + sh - g1, sw, g1); }
      };
      if (!onB.N) seg(x, y - t / 2, w, t, true, door === "N");
      if (!onB.S) seg(x, y + h - t / 2, w, t, true, door === "S");
      if (!onB.W) seg(x - t / 2, y, t, h, false, door === "W");
      if (!onB.E) seg(x + w - t / 2, y, t, h, false, door === "E");
    }
    drawAgent(g, a, x, y, col, sel, lying) {
      g.fillStyle(0x000000, 0.18); g.fillEllipse(x, y + 18, 24, 8);
      const w = 18, h = 26;
      if (lying) { g.fillStyle(col, 1); g.fillRect(x - h / 2, y - w / 2, h - 8, w); g.fillStyle(0xf0c79a, 1); g.fillCircle(x + h / 2 - 6, y, 7); }
      else { g.fillStyle(col, 1); g.fillRect(x - w / 2, y - h / 2 + 8, w, h - 8); g.fillStyle(0x000000, 0.18); g.fillRect(x - w / 2, y - h / 2 + 8, w, 4); g.fillStyle(0xf0c79a, 1); g.fillCircle(x, y - h / 2 + 4, 7); g.fillStyle(0x3a2a1a, 1); g.fillRect(x - 6, y - h / 2, 12, 4); }
      if (sel) { g.lineStyle(2, 0xffffff, 1); g.strokeEllipse(x, y + 18, 30, 12); }
      const text = `${initials(a.name, a.agent_id)}: ${actEmoji(a.activity || a.scheduled_activity || a.action)}`;
      this.labels.push(this.add.text(x, y - h / 2 - 20, text, { fontFamily: "VT323, monospace", fontSize: "16px", color: "#1e2c2c", backgroundColor: "#ffffff", padding: { x: 7, y: 4 } }).setOrigin(0.5).setDepth(5));
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
  }

  // ---- indoor pixel helpers ----
  function px(g, x, y, w, h, c, a) { g.fillStyle(c, a == null ? 1 : a); g.fillRect(x, y, w, h); }
  function grass(g, x, y, w, h) { let s = 991; const rnd = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; }; for (let i = 0; i < (w * h) / 5000; i++) { const gx = x + rnd() * w, gy = y + rnd() * h, r = rnd(); if (r < 0.7) { px(g, gx, gy, 4, 2, 0x5a964b, 0.5); px(g, gx + 1, gy - 2, 2, 2, 0x5a964b, 0.5); } else if (r < 0.85) px(g, gx, gy, 3, 3, 0xe86b6b); else px(g, gx, gy, 3, 3, 0xe8c84e); } }
  function floor(g, layout, x, y, w, h) {
    px(g, x, y, w, h, layout.floor); if (layout.outdoor) { grass(g, x, y, w, h); return; }
    if (layout.tiled) { const t = 26; for (let yy = y, ry = 0; yy < y + h; yy += t, ry++) for (let xx = x, rx = 0; xx < x + w; xx += t, rx++) if ((rx + ry) % 2 === 0) px(g, xx, yy, Math.min(t, x + w - xx), Math.min(t, y + h - yy), 0xffffff, 0.05); }
    else { const ph = 20; for (let yy = y, row = 0; yy < y + h; yy += ph, row++) { if (row % 2) px(g, x, yy, w, Math.min(ph, y + h - yy), 0x785028, 0.06); g.lineStyle(1, 0x50321e, 0.18); g.lineBetween(x, yy, x + w, yy); } }
  }
  function wall(g, x, y, w, h) { px(g, x, y, w, h, 0x9aa0a8); px(g, x, y, w, Math.min(3, h), 0xc4c9cf); px(g, x, y + h - Math.min(3, h), w, Math.min(3, h), 0x6f757d); }
  function furn(g, k, x, y, w, h) {
    switch (k) {
      case "bed": px(g, x, y, w, h, 0x8b5a2b); px(g, x + 4, y + 4, w - 8, h - 8, 0xfff5d6); px(g, x + 6, y + 6, w - 12, h * 0.3, 0xd96b4e); px(g, x + 8, y + h - Math.min(20, h * 0.3), w - 16, 12, 0xfff8e0); break;
      case "nightstand": px(g, x, y, w, h, 0xa87042); px(g, x + 2, y + 2, w - 4, h - 4, 0xc89060); break;
      case "kitchen": px(g, x, y, w, h, 0xcfc3a0); px(g, x, y, w, 4, 0xe8dcc0); for (let i = 0; i < 3; i++) px(g, x + 6 + i * (w / 3), y + h * 0.4, w / 6, h * 0.4, 0x9a8a64); break;
      case "fridge": px(g, x, y, w, h, 0xe8e8e0); px(g, x, y + h * 0.45, w, 2, 0xb8b8b0); break;
      case "table": px(g, x, y, w, h, 0xb07a45); px(g, x + 3, y + 3, w - 6, h - 6, 0xc89058); break;
      case "coffee_table": px(g, x, y, w, h, 0x7a5331); px(g, x + 2, y + 2, w - 4, h - 4, 0x8b5a2b); px(g, x + w / 2 - 4, y + h / 2 - 3, 8, 6, 0xffffff); break;
      case "chair": px(g, x, y, w, h, 0xc84c4c); px(g, x + 2, y, w - 4, 3, 0xa83a3a); break;
      case "desk": px(g, x, y, w, h, 0xcaa06a); px(g, x + 3, y + 3, w - 6, h - 6, 0xd9b483); px(g, x + w * 0.6, y + h * 0.3, w * 0.28, h * 0.4, 0x3a4658); break;
      case "sofa": px(g, x, y, w, h, 0x5a67a8); px(g, x + 3, y + 3, w - 6, h - 6, 0x6e7cc0); px(g, x, y, 6, h, 0x4a5690); px(g, x + w - 6, y, 6, h, 0x4a5690); break;
      case "tv": px(g, x, y, w, h, 0x1c2630); px(g, x + 2, y + 2, w - 4, h - 4, 0x2e4a6a); break;
      case "bookshelf": case "shelf": { px(g, x, y, w, h, 0x8b5a2b); const cs = [0xc84c61, 0x5a9bd4, 0x7b8f27, 0xe0a458, 0x5cc2a8]; for (let i = 0, bx = x + 2; bx < x + w - 3; i++, bx += 5) px(g, bx, y + 2, 4, h - 4, cs[i % cs.length]); break; }
      case "counter": px(g, x, y, w, h, 0x7d5331); px(g, x, y, w, 5, 0xa07853); break;
      case "coffee_machine": px(g, x, y, w, h, 0xbfb6a3); px(g, x + 2, y + 2, w - 4, h * 0.5, 0x7a7064); break;
      case "chalkboard": px(g, x, y, w, h, 0x3a4d3a); px(g, x + 3, y + 3, w - 6, h - 6, 0x2e3e2e); break;
      case "podium": px(g, x, y, w, h, 0x8b5a2b); px(g, x + 2, y + 2, w - 4, h * 0.6, 0xa87042); break;
      case "checkout": px(g, x, y, w, h, 0x7d5331); px(g, x, y, w, 6, 0xa07853); px(g, x + w * 0.1, y + 6, w * 0.3, h * 0.5, 0x3a3a3a); break;
      case "plant": px(g, x + w * 0.2, y + h * 0.5, w * 0.6, h * 0.5, 0x8b5a2b); g.fillStyle(0x5cc2a8, 1); g.fillCircle(x + w / 2, y + h * 0.4, w * 0.45); break;
      case "tree": px(g, x + w * 0.4, y + h * 0.6, w * 0.2, h * 0.4, 0x7a5331); g.fillStyle(0x4e8c3a, 1); g.fillCircle(x + w / 2, y + h * 0.4, w * 0.5); break;
      case "fountain": g.fillStyle(0x9aa0a8, 1); g.fillCircle(x + w / 2, y + h / 2, Math.min(w, h) / 2); g.fillStyle(0x5aa6d8, 1); g.fillCircle(x + w / 2, y + h / 2, Math.min(w, h) / 2 - 4); break;
      case "bench": px(g, x, y, w, h, 0xbfa074); px(g, x, y, w, 2, 0xa8895c); break;
      case "toilet": px(g, x + w * 0.22, y, w * 0.56, h * 0.34, 0xeaeef0); g.fillStyle(0xf6f9fa, 1); g.fillEllipse(x + w * 0.5, y + h * 0.62, w * 0.62, h * 0.5); g.fillStyle(0xc4d0d6, 1); g.fillEllipse(x + w * 0.5, y + h * 0.62, w * 0.4, h * 0.32); break;
      case "sink": px(g, x, y, w, h * 0.5, 0xdfe6ea); g.fillStyle(0xc2ccd2, 1); g.fillEllipse(x + w * 0.5, y + h * 0.3, w * 0.74, h * 0.42); g.fillStyle(0xeef3f5, 1); g.fillEllipse(x + w * 0.5, y + h * 0.3, w * 0.5, h * 0.28); px(g, x + w * 0.46, y - h * 0.05, w * 0.08, h * 0.22, 0x9aa7ad); break;
      case "bathtub": px(g, x, y, w, h, 0xccd8dd); px(g, x + 3, y + 3, w - 6, h - 6, 0xffffff); px(g, x + 6, y + 6, w - 12, h - 12, 0xbfe1f2); g.fillStyle(0x9aa7ad, 1); g.fillCircle(x + w - 9, y + 9, 2); break;
      case "wardrobe": px(g, x, y, w, h, 0x9a6b3f); px(g, x + 2, y + 2, w - 4, h - 4, 0xb07f4e); g.lineStyle(1, 0x6f4a28, 1); g.lineBetween(x + w / 2, y + 2, x + w / 2, y + h - 2); g.fillStyle(0x3a2a1a, 1); g.fillRect(x + w / 2 - 3, y + h * 0.45, 2, h * 0.12); px(g, x + w / 2 + 2, y + h * 0.45, 2, h * 0.12, 0x3a2a1a); break;
      case "stove": px(g, x, y, w, h, 0x6b6f74); px(g, x + 2, y + 2, w - 4, h - 4, 0x3a3e42); for (let i = 0; i < 2; i++) for (let j = 0; j < 2; j++) { g.fillStyle(0x121417, 1); g.fillCircle(x + w * (0.3 + i * 0.4), y + h * (0.32 + j * 0.36), Math.min(w, h) * 0.13); } break;
      case "piano": px(g, x, y, w, h, 0x26262c); px(g, x + 2, y + 2, w - 4, h * 0.52, 0x1a1a20); { const kh = Math.min(10, h * 0.3); px(g, x + 3, y + h - kh, w - 6, kh, 0xfbfbf6); g.lineStyle(1, 0x2a2a2a, 1); for (let kx = x + 6; kx < x + w - 4; kx += 4) g.lineBetween(kx, y + h - kh, kx, y + h - 2); } break;
      default: px(g, x, y, w, h, 0xbfb6a3);
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
