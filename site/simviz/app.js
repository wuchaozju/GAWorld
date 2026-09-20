// GAWorld Town Village visualizer.
// Renders a Smallville-style top-down pixel village with character sprites,
// speech bubbles ("NAME: emoji") and floating activity scene cards.
//
// Assets:
//   ./assets/tuxmon.png  — tilemap (768x960, 32px tiles, CC-BY-SA 3.0 Tuxemon team)
//   ./assets/misa.png    — character sprite atlas
//   ./assets/misa.json   — TexturePacker frame data for misa

const DEFAULT_DATA_PATH = "../../output/visualization/simulation_trace.json";

// Palette used for tinting characters and labelling agents.
const AGENT_COLORS = [
  "#dc7d2d", "#0d8a73", "#9a4d38", "#5a67a8", "#c84c61",
  "#7b8f27", "#0083a8", "#a35b9c", "#b67d2a", "#3f7ba6",
];

// Activity → emoji table. Tries exact match first, then substring fallback.
// Keys cover both schedule_activity (e.g. "睡前") and action (e.g. "睡觉").
const ACTIVITY_EMOJI = [
  // sleep / rest
  [/睡|休息|床|nap|sleep/i, "🛌"],
  [/睡前|睡觉/i, "💤"],
  // food
  [/早饭|早餐|breakfast/i, "🍳"],
  [/午饭|午餐|lunch/i, "🍱"],
  [/晚饭|晚餐|dinner/i, "🍲"],
  [/吃|饭|餐|eat|meal/i, "🍽️"],
  [/咖啡|coffee|cafe/i, "☕"],
  [/茶|tea/i, "🍵"],
  // work / school
  [/上班|工作|办公|work|office|job/i, "💻"],
  [/上学|学校|school|课/i, "📚"],
  [/读书|阅读|看书|read|book/i, "📖"],
  [/会议|开会|meeting/i, "📋"],
  // shopping
  [/买菜|购物|shop|超市|grocer/i, "🛒"],
  [/钱|银行|bank|atm/i, "💰"],
  // social / communication
  [/聊天|社交|talk|chat/i, "💬"],
  [/电话|打电话|call|phone/i, "📞"],
  [/消息|微信|message|text/i, "📱"],
  // movement / exercise
  [/晨练|跑步|run|jog/i, "🏃"],
  [/散步|walk|stroll/i, "🚶"],
  [/锻炼|健身|gym|exercise/i, "💪"],
  [/瑜伽|yoga/i, "🧘"],
  // leisure
  [/玩|娱乐|游戏|play|game/i, "🎮"],
  [/音乐|music|听歌/i, "🎵"],
  [/看电视|tv|看剧/i, "📺"],
  [/电影|movie/i, "🎬"],
  [/拖延|刷手机|刷会儿/i, "📱"],
  // personal / routine
  [/洗澡|淋浴|bath|shower/i, "🚿"],
  [/卫生|刷牙|brush/i, "🪥"],
  [/打扫|清洁|clean/i, "🧹"],
  [/做饭|烹饪|cook/i, "🍳"],
  // time slots
  [/午休/i, "🛋️"],
  [/个人时间/i, "✨"],
  [/按.*继续|按.*处理|按清单/i, "✅"],
  [/确认|联系/i, "📞"],
  [/推进|往前推/i, "🛠️"],
  [/逛/i, "👀"],
];

function activityToEmoji(text) {
  const s = String(text || "").trim();
  if (!s) return "💭";
  for (const [pattern, emoji] of ACTIVITY_EMOJI) {
    if (pattern.test(s)) return emoji;
  }
  return "💭";
}

// Hand-picked source rects from tuxmon.png (sx, sy, sw, sh in source pixels).
// The tileset is 768x960 with 32px tiles. These were chosen by visual inspection.
const TILESET = {
  src: "./assets/tuxmon.png",
  grass: [32, 32, 32, 32],
  sand: [288, 32, 32, 32],
  water: [352, 256, 32, 32],
  flower_red: [192, 0, 32, 32],
  flower_blue: [192, 64, 32, 32],
  flower_yellow: [192, 128, 32, 32],
  tree: [32, 192, 32, 64],   // 2-tile tall tree (trunk + canopy)
  bush: [288, 288, 32, 32],
  fountain: [256, 320, 96, 64],
  fence_h: [0, 256, 96, 32],
  // Buildings — multi-tile rects. Roof + visible interior cut-away.
  building_school: [0, 416, 192, 128],      // 6x4 tiles, tall white glass facade
  building_cafe: [448, 416, 128, 96],       // 4x3 tiles, red-roofed cafe
  building_medical: [576, 448, 96, 96],     // 3x3 tiles, red cross / clinic
  building_house_wood: [288, 544, 96, 96],  // 3x3 tiles, brown wooden house
  building_shop: [288, 416, 128, 96],       // 4x3 brown sign building
  building_house_red: [384, 736, 96, 96],   // 3x3 red roof house
  building_house_tan: [0, 736, 96, 96],     // tan brick house
};

// Resolve a category to a building source rect.
const CATEGORY_BUILDING = {
  residential: "building_house_wood",
  commerce: "building_shop",
  education: "building_school",
  medical: "building_medical",
  leisure: "building_cafe",
  government: "building_house_tan",
  mixed: "building_house_red",
  industry: "building_shop",
  transit: "building_house_tan",
};

// Misa atlas — 4-direction walking. Loaded from misa.json at startup.
let misaFrames = null;
const misaImg = new Image();
const tilesetImg = new Image();
const imgReady = { tileset: false, misa: false };

const state = {
  trace: null,
  frameIndex: 0,
  selectedAgentId: null,
  playing: false,
  playbackTimer: null,
  pollTimer: null,
  speed: 1,
  dataPath: DEFAULT_DATA_PATH,
  renderMetrics: null,
  avatarCache: new Map(),
  showCards: true,
  bldgLayout: null,        // map of nodeId → {x,y,w,h} once computed
  decorations: null,       // cached prop placements (trees/flowers)
  agentTints: new Map(),   // agent_id → tinted character canvas cache
  viewMode: "village",     // "village" | "indoor"
  indoorLocation: null,    // node id when in indoor mode
  viewModeManual: false,   // user explicitly toggled (don't auto-switch)
  animTimer: null,         // requestAnimationFrame id for animation loop
  zoom: 1,                 // village-mode zoom factor (1..4)
  panX: 0, panY: 0,        // pan offset (applied AFTER zoom)
  dragging: null,          // { startX, startY, startPanX, startPanY } during drag
  continuous: false,       // continuous timeline (fractional frame index)
  frameFloat: 0,           // fractional frame index when continuous=true
  indoorAgents: new Map(), // agent_id → { x, y, targetX, targetY, holdUntil, dir }
};

const els = {
  statusBadge: document.getElementById("statusBadge"),
  frameBadge: document.getElementById("frameBadge"),
  dataPathInput: document.getElementById("dataPathInput"),
  reloadBtn: document.getElementById("reloadBtn"),
  playBtn: document.getElementById("playBtn"),
  liveToggle: document.getElementById("liveToggle"),
  cardsToggle: document.getElementById("cardsToggle"),
  speedSelect: document.getElementById("speedSelect"),
  frameTitle: document.getElementById("frameTitle"),
  frameMeta: document.getElementById("frameMeta"),
  mapCanvas: document.getElementById("mapCanvas"),
  sceneCardsLayer: document.getElementById("sceneCardsLayer"),
  timelineSlider: document.getElementById("timelineSlider"),
  timelineLabel: document.getElementById("timelineLabel"),
  timelineHint: document.getElementById("timelineHint"),
  agentName: document.getElementById("agentName"),
  agentAvatar: document.getElementById("agentAvatar"),
  agentMeta: document.getElementById("agentMeta"),
  agentLocation: document.getElementById("agentLocation"),
  agentTarget: document.getElementById("agentTarget"),
  agentActivity: document.getElementById("agentActivity"),
  agentAction: document.getElementById("agentAction"),
  agentTravelMode: document.getElementById("agentTravelMode"),
  agentTravelStats: document.getElementById("agentTravelStats"),
  agentCoords: document.getElementById("agentCoords"),
  agentChanged: document.getElementById("agentChanged"),
  agentPerception: document.getElementById("agentPerception"),
  agentPlan: document.getElementById("agentPlan"),
  agentReflection: document.getElementById("agentReflection"),
  envContext: document.getElementById("envContext"),
  eventChips: document.getElementById("eventChips"),
  rosterList: document.getElementById("rosterList"),
  viewVillageBtn: document.getElementById("viewVillageBtn"),
  viewIndoorBtn: document.getElementById("viewIndoorBtn"),
  continuousToggle: document.getElementById("continuousToggle"),
  zoomInBtn: document.getElementById("zoomInBtn"),
  zoomOutBtn: document.getElementById("zoomOutBtn"),
  zoomResetBtn: document.getElementById("zoomResetBtn"),
  zoomLevel: document.getElementById("zoomLevel"),
  zoomControls: document.getElementById("zoomControls"),
};

const ctx = els.mapCanvas.getContext("2d");
ctx.imageSmoothingEnabled = false;

// ───────── boot ─────────
async function init() {
  const params = new URLSearchParams(window.location.search);
  state.dataPath = params.get("data") || DEFAULT_DATA_PATH;
  els.dataPathInput.value = state.dataPath;
  els.liveToggle.checked = params.get("live") !== "0";
  bindEvents();
  await loadAssets();
  loadTrace(true);
  startPolling();
}

function bindEvents() {
  els.reloadBtn.addEventListener("click", () => loadTrace(true));
  els.playBtn.addEventListener("click", togglePlayback);
  els.speedSelect.addEventListener("change", () => {
    state.speed = Number(els.speedSelect.value || 1);
    if (state.playing) { stopPlayback(); startPlayback(); }
  });
  els.liveToggle.addEventListener("change", startPolling);
  els.cardsToggle.addEventListener("change", () => {
    state.showCards = els.cardsToggle.checked;
    render();
  });
  els.dataPathInput.addEventListener("change", () => {
    state.dataPath = els.dataPathInput.value.trim() || DEFAULT_DATA_PATH;
    const url = new URL(window.location.href);
    url.searchParams.set("data", state.dataPath);
    window.history.replaceState({}, "", url);
    state.bldgLayout = null; state.decorations = null;
    loadTrace(true);
  });
  els.timelineSlider.addEventListener("input", (e) => {
    stopPlayback();
    state.frameIndex = Number(e.target.value || 0);
    render();
  });
  els.mapCanvas.addEventListener("click", onCanvasClick);
  els.mapCanvas.addEventListener("mousemove", onCanvasMouseMove);
  els.mapCanvas.addEventListener("wheel", onCanvasWheel, { passive: false });
  els.mapCanvas.addEventListener("mousedown", onCanvasMouseDown);
  window.addEventListener("mousemove", onCanvasDragMove);
  window.addEventListener("mouseup", onCanvasMouseUp);
  els.viewVillageBtn.addEventListener("click", () => setViewMode("village", true));
  els.viewIndoorBtn.addEventListener("click", () => setViewMode("indoor", true));
  els.continuousToggle.addEventListener("change", () => {
    state.continuous = els.continuousToggle.checked;
    state.frameFloat = state.frameIndex;
    if (state.continuous && !state.playing) startPlayback();
  });
  els.zoomInBtn.addEventListener("click", () => zoomBy(1.25));
  els.zoomOutBtn.addEventListener("click", () => zoomBy(1 / 1.25));
  els.zoomResetBtn.addEventListener("click", resetZoom);
}

function zoomBy(factor, focusX, focusY) {
  const cx = focusX != null ? focusX : els.mapCanvas.width / 2;
  const cy = focusY != null ? focusY : els.mapCanvas.height / 2;
  const newZoom = clamp(state.zoom * factor, 1, 6);
  if (newZoom === state.zoom) return;
  // Keep the focal point stationary in screen space.
  state.panX = cx - (cx - state.panX) * (newZoom / state.zoom);
  state.panY = cy - (cy - state.panY) * (newZoom / state.zoom);
  state.zoom = newZoom;
  clampPan();
  updateZoomLabel();
  render();
}

function resetZoom() {
  state.zoom = 1; state.panX = 0; state.panY = 0;
  updateZoomLabel();
  render();
}

function clampPan() {
  // Don't let the user pan past the canvas edges (leave a small margin).
  const limit = (state.zoom - 1) * els.mapCanvas.width / 2;
  const limitY = (state.zoom - 1) * els.mapCanvas.height / 2;
  state.panX = clamp(state.panX, -limit, limit);
  state.panY = clamp(state.panY, -limitY, limitY);
}

function updateZoomLabel() {
  if (els.zoomLevel) els.zoomLevel.textContent = `${Math.round(state.zoom * 100)}%`;
}

function onCanvasWheel(event) {
  if (state.viewMode !== "village") return;
  event.preventDefault();
  const rect = els.mapCanvas.getBoundingClientRect();
  const x = (event.clientX - rect.left) * (els.mapCanvas.width / rect.width);
  const y = (event.clientY - rect.top) * (els.mapCanvas.height / rect.height);
  zoomBy(event.deltaY < 0 ? 1.15 : 1 / 1.15, x, y);
}

function onCanvasMouseDown(event) {
  if (state.viewMode !== "village" || state.zoom <= 1.001) return;
  state.dragging = {
    startX: event.clientX, startY: event.clientY,
    startPanX: state.panX, startPanY: state.panY,
    moved: false,
  };
  els.mapCanvas.style.cursor = "grabbing";
}

function onCanvasDragMove(event) {
  if (!state.dragging) return;
  const dx = event.clientX - state.dragging.startX;
  const dy = event.clientY - state.dragging.startY;
  if (Math.abs(dx) + Math.abs(dy) > 4) state.dragging.moved = true;
  const rect = els.mapCanvas.getBoundingClientRect();
  const ratio = els.mapCanvas.width / rect.width;
  state.panX = state.dragging.startPanX + dx * ratio;
  state.panY = state.dragging.startPanY + dy * ratio;
  clampPan();
  render();
}

function onCanvasMouseUp(event) {
  if (!state.dragging) return;
  const moved = state.dragging.moved;
  state.dragging = null;
  els.mapCanvas.style.cursor = "default";
  // If the user actually dragged (not a click), swallow the next click.
  if (moved) {
    state._suppressNextClick = true;
    setTimeout(() => { state._suppressNextClick = false; }, 0);
  }
}

// `location` explicitly overrides — pass it when entering indoor via a click
// on a specific building or agent so it isn't clobbered by the selected agent.
function setViewMode(mode, manual = false, location = null) {
  state.viewMode = mode;
  state.viewModeManual = manual;
  els.viewVillageBtn.classList.toggle("active", mode === "village");
  els.viewIndoorBtn.classList.toggle("active", mode === "indoor");
  if (mode === "indoor") {
    if (location) state.indoorLocation = location;
    else if (!state.indoorLocation) {
      const sel = getSelectedAgentFrame();
      if (sel) state.indoorLocation = sel.target_location || sel.location;
      else {
        // Fall back: pick the first building that has any agents inside.
        const frame = getCurrentFrame();
        if (frame) {
          const hit = frame.agents.find((a) => a.target_location || a.location);
          if (hit) state.indoorLocation = hit.target_location || hit.location;
        }
        // Last resort: first node in the map.
        if (!state.indoorLocation && state.trace && state.trace.map && state.trace.map.nodes && state.trace.map.nodes.length) {
          state.indoorLocation = state.trace.map.nodes[0].id;
        }
      }
    }
  }
  render();
}

// View follows the selected agent. Auto switching has two layers:
//   * If user hasn't manually locked the mode → switch village/indoor by travel state.
//   * Even with viewModeManual=true, while in indoor we still FOLLOW the agent
//     when they move to a new location (so the room updates with them).
//     `viewModeManual` only blocks the village ⇄ indoor *mode* flip.
function autoUpdateViewMode() {
  const a = getSelectedAgentFrame();
  if (!a) return;
  const traveling = a.travel && ["departed", "in_transit"].includes(a.travel.status);
  if (!state.viewModeManual) {
    if (traveling) {
      if (state.viewMode !== "village") {
        state.viewMode = "village";
        els.viewVillageBtn.classList.add("active");
        els.viewIndoorBtn.classList.remove("active");
      }
    } else if (a.target_location) {
      if (state.viewMode !== "indoor") {
        state.viewMode = "indoor";
        els.viewVillageBtn.classList.remove("active");
        els.viewIndoorBtn.classList.add("active");
      }
      state.indoorLocation = a.target_location;
    }
  } else if (state.viewMode === "indoor" && !traveling && a.target_location) {
    // Manual mode but still indoors: follow selected agent across rooms.
    state.indoorLocation = a.target_location;
  }
}

function loadAssets() {
  const tilesetP = new Promise((resolve) => {
    tilesetImg.onload = () => { imgReady.tileset = true; resolve(); };
    tilesetImg.onerror = () => resolve();
    tilesetImg.src = TILESET.src;
  });
  const misaP = new Promise((resolve) => {
    misaImg.onload = () => { imgReady.misa = true; resolve(); };
    misaImg.onerror = () => resolve();
    misaImg.src = "./assets/misa.png";
  });
  const jsonP = fetch("./assets/misa.json").then((r) => r.json()).then((d) => {
    misaFrames = d.frames;
  }).catch(() => { misaFrames = null; });
  return Promise.all([tilesetP, misaP, jsonP]);
}

// ───────── data loading ─────────
async function loadTrace(forceFrameClamp = false) {
  const target = `${state.dataPath}${state.dataPath.includes("?") ? "&" : "?"}t=${Date.now()}`;
  try {
    const response = await fetch(target, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const frameCount = Array.isArray(payload.frames) ? payload.frames.length : 0;
    state.trace = payload;
    state.bldgLayout = null; state.decorations = null;  // recompute on new data
    if (frameCount === 0) state.frameIndex = 0;
    else if (forceFrameClamp || state.frameIndex >= frameCount) state.frameIndex = frameCount - 1;
    ensureSelectedAgent();
    render();
  } catch (error) {
    showError(error);
  }
}

function startPolling() {
  clearInterval(state.pollTimer);
  if (!els.liveToggle.checked) return;
  state.pollTimer = setInterval(() => loadTrace(false), 2500);
}

function togglePlayback() { state.playing ? stopPlayback() : startPlayback(); }

// Frame dwell time. Each frame represents minutes of sim time, so we hold it
// for ~3s real-time at 1x speed (was 0.9s, which made agents look teleporty).
// The animation loop interpolates positions between dwell starts so movement
// looks continuous.
const FRAME_DWELL_MS = 3000;

function startPlayback() {
  if (!state.trace || !Array.isArray(state.trace.frames) || state.trace.frames.length === 0) return;
  state.playing = true;
  els.playBtn.textContent = "暂停";
  state.frameEnteredAt = performance.now();
  state.frameFloat = state.frameIndex;
  state._lastTick = performance.now();
  if (state.continuous) {
    // Continuous: advance frameFloat smoothly each rAF tick. Sub-frame interp
    // happens inside agentPixelPosition via state.frameFloat.
    const tick = () => {
      if (!state.playing) return;
      const now = performance.now();
      const dt = now - state._lastTick; state._lastTick = now;
      const total = state.trace.frames.length;
      const framesPerMs = state.speed / FRAME_DWELL_MS;
      state.frameFloat = (state.frameFloat + dt * framesPerMs) % total;
      const newIndex = Math.floor(state.frameFloat);
      if (newIndex !== state.frameIndex) {
        state.frameIndex = newIndex;
        state.frameEnteredAt = now;
      }
      render();
      state.playbackTimer = requestAnimationFrame(tick);
    };
    state.playbackTimer = requestAnimationFrame(tick);
  } else {
    // Discrete: dwell on each frame.
    const tick = () => {
      if (!state.playing) return;
      const total = state.trace.frames.length;
      state.frameIndex = state.frameIndex >= total - 1 ? 0 : state.frameIndex + 1;
      state.frameFloat = state.frameIndex;
      state.frameEnteredAt = performance.now();
      render();
      state.playbackTimer = window.setTimeout(tick, Math.max(400, FRAME_DWELL_MS / state.speed));
    };
    tick();
  }
}

function stopPlayback() {
  state.playing = false;
  els.playBtn.textContent = "播放";
  window.clearTimeout(state.playbackTimer);
  cancelAnimationFrame(state.playbackTimer);
}

function ensureSelectedAgent() {
  const frame = getCurrentFrame();
  if (!frame || !Array.isArray(frame.agents) || frame.agents.length === 0) {
    state.selectedAgentId = null;
    return;
  }
  if (!frame.agents.some((a) => a.agent_id === state.selectedAgentId)) {
    state.selectedAgentId = frame.agents[0].agent_id;
  }
}

function getCurrentFrame() {
  return state.trace && Array.isArray(state.trace.frames) && state.trace.frames.length > 0
    ? state.trace.frames[state.frameIndex] : null;
}

function getSelectedAgentFrame() {
  const frame = getCurrentFrame();
  if (!frame) return null;
  return frame.agents.find((a) => a.agent_id === state.selectedAgentId) || frame.agents[0] || null;
}

function traceAgentsMap() {
  return new Map((((state.trace || {}).agents) || []).map((a) => [a.id, a]));
}

function getAgentMeta(agentId) { return traceAgentsMap().get(Number(agentId)) || null; }

function resolveAssetPath(assetPath) {
  const text = String(assetPath || "").trim();
  if (!text) return "";
  if (/^(https?:)?\/\//.test(text) || text.startsWith("data:")) return text;
  try {
    return new URL(text, new URL(state.dataPath, window.location.href)).href;
  } catch (_) { return text; }
}

function getAgentAvatarPath(agent) {
  if (!agent) return "";
  const meta = getAgentMeta(agent.agent_id || agent.id);
  const fallback = `avatars/agent_${Number(agent.agent_id || agent.id || 0)}.svg`;
  return resolveAssetPath(agent.avatar_path || (meta && meta.avatar_path) || fallback);
}

function loadAvatar(path) {
  const resolved = resolveAssetPath(path);
  if (!resolved) return null;
  if (state.avatarCache.has(resolved)) {
    const cached = state.avatarCache.get(resolved);
    return cached.loaded ? cached.img : null;
  }
  const img = new Image();
  img.decoding = "async";
  state.avatarCache.set(resolved, { img, loaded: false });
  img.onload = () => {
    const item = state.avatarCache.get(resolved);
    if (item) item.loaded = true;
    render();
  };
  img.onerror = () => state.avatarCache.delete(resolved);
  img.src = resolved;
  return null;
}

function mapNodes() {
  return new Map((((state.trace || {}).map || {}).nodes || []).map((n) => [n.id, n]));
}

// ───────── render ─────────
function render() {
  const trace = state.trace;
  const frame = getCurrentFrame();
  const frames = trace && Array.isArray(trace.frames) ? trace.frames : [];
  const selected = getSelectedAgentFrame();
  if (!trace || frames.length === 0) { renderEmptyState(); return; }

  els.frameBadge.textContent = `Frame ${frame.index + 1} / ${frames.length}`;
  els.statusBadge.textContent = trace.meta && trace.meta.finished ? "回放数据已完成" : "实时数据更新中";
  els.statusBadge.className = `badge ${trace.meta && trace.meta.finished ? "badge-done" : "badge-live"}`;
  els.frameTitle.textContent = `Day ${frame.day} · ${frame.time}`;
  els.frameMeta.textContent = [frame.date, frame.weekday, frame.day_type].filter(Boolean).join(" · ");
  els.timelineSlider.max = String(Math.max(0, frames.length - 1));
  els.timelineSlider.value = String(state.frameIndex);
  els.timelineLabel.textContent = `${frame.date || ""} ${frame.weekday || ""} ${frame.time}`.trim();
  els.timelineHint.textContent = `${frame.agents.length} 个 agent · ${uniqueLocations(frame.agents).length} 个活跃地点`;

  autoUpdateViewMode();
  // Snapshot the previous frame's resolved positions so the next render can
  // tween from them. We do this BEFORE rendering the new positions.
  if (state.frameIndex !== state._lastSnapshotIndex) {
    state.prevAgentPositions = {};
    frame.agents.forEach((a) => {
      if (a._spriteX != null) state.prevAgentPositions[a.agent_id] = { x: a._spriteX, y: a._spriteY };
    });
    state._lastSnapshotIndex = state.frameIndex;
    state.frameEnteredAt = performance.now();
  }
  renderAgentSummary(selected);
  renderContext(frame);
  renderRoster(frame.agents);
  if (state.viewMode === "indoor" && state.indoorLocation) {
    renderIndoor(trace.map, frame, selected);
  } else {
    renderVillage(trace.map, frame, selected);
  }
  renderSceneCards(frame);
  if (!state.animTimer) startAnimationLoop();
}

// rAF loop: only re-renders when agents are walking OR when in indoor mode
// (so idle bobbing + action animations are visible). Cheap when nothing moves.
function startAnimationLoop() {
  const tick = () => {
    state.animTimer = requestAnimationFrame(tick);
    const frame = getCurrentFrame();
    if (!frame) return;
    const moving = frame.agents.some((a) => a.travel && ["departed", "in_transit"].includes(a.travel.status));
    // Also keep redrawing during the first second of any new frame so the
    // cross-frame position tween is visible.
    const tweening = state.frameEnteredAt && (performance.now() - state.frameEnteredAt) < 1000;
    if (moving || state.viewMode === "indoor" || tweening) {
      // Throttle to ~10 fps for the cheap canvas redraw.
      const now = performance.now();
      if (!state._lastFrame || now - state._lastFrame > 100) {
        state._lastFrame = now;
        if (state.viewMode === "indoor" && state.indoorLocation) {
          renderIndoor(state.trace.map, frame, getSelectedAgentFrame());
        } else {
          renderVillage(state.trace.map, frame, getSelectedAgentFrame());
        }
      }
    }
  };
  state.animTimer = requestAnimationFrame(tick);
}

function renderEmptyState() {
  els.frameBadge.textContent = "Frame 0";
  els.frameTitle.textContent = "等待可视化数据";
  els.frameMeta.textContent = "先运行模拟，或确认数据路径是否正确。";
  els.timelineSlider.max = "0";
  els.timelineSlider.value = "0";
  els.timelineLabel.textContent = "暂无帧";
  els.timelineHint.textContent = "默认读取 ../../output/visualization/simulation_trace.json";
  els.statusBadge.textContent = "未加载到数据";
  els.statusBadge.className = "badge badge-error";
  ctx.clearRect(0, 0, els.mapCanvas.width, els.mapCanvas.height);
  ctx.fillStyle = "#9bc56d";
  ctx.fillRect(0, 0, els.mapCanvas.width, els.mapCanvas.height);
  ctx.fillStyle = "#3d5a2a";
  ctx.font = "32px Manrope";
  ctx.fillText("等待村落数据…", 60, 80);
  renderAgentSummary(null);
  els.envContext.textContent = "-";
  els.eventChips.innerHTML = "";
  els.rosterList.innerHTML = "";
  els.sceneCardsLayer.innerHTML = "";
  state.renderMetrics = null;
}

function renderAgentSummary(agent) {
  const nodes = mapNodes();
  if (!agent) {
    ["agentLocation", "agentTarget", "agentActivity", "agentAction", "agentTravelMode", "agentTravelStats", "agentCoords", "agentChanged"].forEach((id) => {
      els[id].textContent = "-";
    });
    els.agentName.textContent = "未选择";
    els.agentAvatar.removeAttribute("src");
    els.agentMeta.textContent = "";
    els.agentPerception.textContent = "-";
    els.agentPlan.textContent = "-";
    els.agentReflection.textContent = "-";
    return;
  }
  const resolvedNode = nodes.get(agent.resolved_location) || nodes.get(agent.target_location);
  els.agentName.textContent = agent.name;
  const avatarPath = getAgentAvatarPath(agent);
  if (avatarPath) { els.agentAvatar.src = avatarPath; els.agentAvatar.alt = `${agent.name} avatar`; }
  else { els.agentAvatar.removeAttribute("src"); els.agentAvatar.alt = ""; }
  els.agentMeta.textContent = `ID ${agent.agent_id} · ${agent.home || "未知住处"} → ${agent.workplace || "未知工作地"}`;
  els.agentLocation.textContent = agent.location || "-";
  els.agentTarget.textContent = agent.target_location || "-";
  els.agentActivity.textContent = `${activityToEmoji(agent.activity || agent.scheduled_activity)} ${agent.activity || agent.scheduled_activity || "-"}`;
  els.agentAction.textContent = `${activityToEmoji(agent.action)} ${agent.action || "-"}`;
  els.agentTravelMode.textContent = agent.travel && agent.travel.mode ? agent.travel.mode : "停留";
  els.agentTravelStats.textContent = agent.travel && agent.travel.minutes
    ? `${fmt(agent.travel.distance_km)} km / ${agent.travel.minutes} min` : "0 km / 0 min";
  els.agentCoords.textContent = resolvedNode ? `${resolvedNode.lat}, ${resolvedNode.lng}` : "-";
  els.agentChanged.textContent = agent.changed ? `是 · ${agent.change_reason || "临时调整"}` : "否";
  els.agentPerception.textContent = agent.perception || "-";
  els.agentPlan.textContent = agent.plan || "-";
  els.agentReflection.textContent = agent.reflection || "-";
}

function renderContext(frame) {
  els.envContext.textContent = frame.env_context || "无额外环境上下文";
  els.eventChips.innerHTML = "";
  const chips = [];
  if (frame.policy && frame.policy.name) chips.push(`政策: ${frame.policy.name}`);
  if (Array.isArray(frame.env_events)) {
    frame.env_events.forEach((event) => {
      if (event && typeof event === "object") chips.push(event.description || event.name || event.type || "event");
    });
  }
  if (chips.length === 0) chips.push("无显著环境事件");
  chips.forEach((text) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = text;
    els.eventChips.appendChild(chip);
  });
}

function renderRoster(agentFrames) {
  els.rosterList.innerHTML = "";
  const sorted = [...agentFrames].sort((a, b) =>
    (a.target_location || "").localeCompare(b.target_location || "", "zh-Hans-CN") ||
    a.name.localeCompare(b.name, "zh-Hans-CN"));
  sorted.forEach((agent) => {
    const button = document.createElement("button");
    button.className = `roster-item ${agent.agent_id === state.selectedAgentId ? "active" : ""}`;
    button.type = "button";
    button.addEventListener("click", () => { state.selectedAgentId = agent.agent_id; render(); });
    const travelText = agent.travel && agent.travel.mode ? `${agent.travel.mode} · ${agent.travel.status || ""}` : "停留";
    const emoji = activityToEmoji(agent.activity || agent.scheduled_activity);
    const avatarPath = getAgentAvatarPath(agent);
    button.innerHTML = `<div class="roster-head"><div class="roster-agent"><img class="roster-avatar" src="${escapeHtml(avatarPath)}" alt="${escapeHtml(agent.name)} avatar" /><span class="roster-name">${escapeHtml(agent.name)}</span><span class="roster-emoji">${emoji}</span></div><span class="badge">${escapeHtml(agent.target_location || agent.location || "未定位")}</span></div><div class="roster-meta"><div>${escapeHtml(agent.activity || agent.scheduled_activity || "无活动")}</div><div>${escapeHtml(travelText)}</div></div>`;
    els.rosterList.appendChild(button);
  });
}

// ───────── village rendering ─────────
// Hoisted: used by both computeLayout (to pre-color districts) and drawLandUse.
const LAND_USE_COLOR = {
  residential: "#ead9bd",
  commerce:    "#f0e0b0",
  education:   "#dde7e8",
  medical:     "#f3dadc",
  leisure:     "#cfe1bb",
  government:  "#e2dcc8",
  industry:    "#dad4c4",
  mixed:       "#e8dec5",
  transit:     "#d8d4d8",
};

function computeLayout(mapData) {
  const tileMap = (mapData || {}).tile_map || {};
  const worldW = Number(tileMap.width || 160);
  const worldH = Number(tileMap.height || 112);
  const scale = Math.min(els.mapCanvas.width / worldW, els.mapCanvas.height / worldH);
  const drawWidth = worldW * scale;
  const drawHeight = worldH * scale;
  const offsetX = Math.floor((els.mapCanvas.width - drawWidth) / 2);
  const offsetY = Math.floor((els.mapCanvas.height - drawHeight) / 2);

  // ── Buildings placed at raw tile_x/tile_y from the city_map generator. ──
  // The generator now lays places in a block-grid around their hub, so the
  // raw positions ARE the real intended layout. We just draw rectangles.
  const buildings = new Map();
  const PLACE_W = Math.max(14, Math.round(scale * 1.6));   // about 1.6 tiles
  const PLACE_H = Math.max(12, Math.round(scale * 1.4));
  const HUB_W = Math.max(28, Math.round(scale * 3.0));
  const HUB_H = Math.max(24, Math.round(scale * 2.6));

  (mapData.nodes || []).forEach((node) => {
    const isHub = node.kind === "hub";
    const w = isHub ? HUB_W : PLACE_W;
    const h = isHub ? HUB_H : PLACE_H;
    const cx = offsetX + node.tile_x * scale + scale / 2;
    const cy = offsetY + node.tile_y * scale + scale / 2;
    const x = Math.round(cx - w / 2);
    const y = Math.round(cy - h / 2);
    const key = CATEGORY_BUILDING[node.category] || "building_house_wood";
    buildings.set(node.id, {
      node, sprite: key, srcRect: TILESET[key], isHub,
      x, y, w, h, cx, cy,
    });
  });

  // ── District metadata for land-use polygons + labels ──
  const districtAgg = new Map();
  (mapData.nodes || []).forEach((node) => {
    const d = node.district || "未知";
    if (!districtAgg.has(d)) districtAgg.set(d, { name: d, members: [], cx: 0, cy: 0 });
    const b = buildings.get(node.id); if (!b) return;
    const agg = districtAgg.get(d);
    agg.members.push(node);
    agg.cx += b.cx; agg.cy += b.cy;
  });
  const districtList = [...districtAgg.values()].map((d) => {
    d.cx /= Math.max(1, d.members.length);
    d.cy /= Math.max(1, d.members.length);
    // Visual polygon radius = max distance from centroid to a member, padded.
    let maxR = 0;
    d.members.forEach((n) => {
      const b = buildings.get(n.id); if (!b) return;
      const dx = b.cx - d.cx, dy = b.cy - d.cy;
      maxR = Math.max(maxR, Math.hypot(dx, dy));
    });
    d.r = maxR + 24;
    d.n = d.members.length;
    const cat = {};
    d.members.forEach((n) => { cat[n.category] = (cat[n.category] || 0) + 1; });
    d.dominantCategory = Object.entries(cat).sort((a, b) => b[1] - a[1])[0][0];
    d.color = (LAND_USE_COLOR[d.dominantCategory] || LAND_USE_COLOR.residential) + "cc";
    return d;
  });

  const list = [...buildings.values()];

  // ── Bridges (still derived from raw bridge_tiles — they sit on the river) ──
  const rawBridges = Array.isArray(tileMap.bridge_tiles) ? tileMap.bridge_tiles : [];
  const bridgeSpans = clusterBridgeTiles(rawBridges, scale, offsetX, offsetY);

  // No tree decorations: the OSM look reads cleaner without scattered pixel sprites.
  const decorations = [];

  state.renderMetrics = { scale, offsetX, offsetY, worldW, worldH, drawWidth, drawHeight };

  // Road network: trunk = MST connecting district hubs; locals = each
  // place to its district hub. No snapping needed since district layout
  // already puts everything in clean cells.
  const roadNetwork = buildRoadNetwork(list);

  // Snap bridge spans onto the nearest trunk segment crossing the river.
  const trunkAlignedBridges = alignBridgesToTrunk(bridgeSpans, roadNetwork.trunk);

  return {
    buildings,
    decorations,
    districts: districtList,
    bridgeSpans: trunkAlignedBridges,
    roadNetwork,
  };
}

function nearestHub(b, hubMap) {
  let best = null, bestD = Infinity;
  hubMap.forEach((h) => {
    const d = Math.hypot(h.cx - b.cx, h.cy - b.cy);
    if (d < bestD) { bestD = d; best = h; }
  });
  return best;
}

// Build a tree-shaped road network. Trunk = MST over hubs; locals = each
// non-hub connected to its nearest hub. Avoids the spiderweb that drawing
// every edge in mapData.edges produces.
function buildRoadNetwork(buildings) {
  const hubs = buildings.filter((b) => b.isHub);
  const places = buildings.filter((b) => !b.isHub);
  const trunk = primMST(hubs);
  // Prefer the hub in the same district; fall back to nearest if district
  // has no hub. Keeps locals from crossing district boundaries.
  const hubByDistrict = new Map();
  hubs.forEach((h) => { hubByDistrict.set(h.node.district || "未知", h); });
  const locals = places.map((p) => {
    const sameDistrict = hubByDistrict.get(p.node.district || "未知");
    if (sameDistrict) return { a: p, b: sameDistrict };
    let best = null, bestD = Infinity;
    hubs.forEach((h) => {
      const d = Math.hypot(h.cx - p.cx, h.cy - p.cy);
      if (d < bestD) { bestD = d; best = h; }
    });
    return best ? { a: p, b: best } : null;
  }).filter(Boolean);
  return { trunk, locals, hubs };
}

function primMST(nodes) {
  if (nodes.length < 2) return [];
  const edges = [];
  const visited = new Set([0]);
  while (visited.size < nodes.length) {
    let best = null;
    for (let i = 0; i < nodes.length; i += 1) {
      if (!visited.has(i)) continue;
      for (let j = 0; j < nodes.length; j += 1) {
        if (visited.has(j)) continue;
        const d = Math.hypot(nodes[i].cx - nodes[j].cx, nodes[i].cy - nodes[j].cy);
        if (!best || d < best.d) best = { i, j, d };
      }
    }
    if (!best) break;
    edges.push({ a: nodes[best.i], b: nodes[best.j] });
    visited.add(best.j);
  }
  return edges;
}

// For each bridge span, snap its centerline onto the closest trunk segment
// crossing the river area. Drops bridge spans that aren't near any trunk.
function alignBridgesToTrunk(spans, trunk) {
  if (!trunk || !trunk.length) return spans;
  return spans.map((b) => {
    let best = null, bestD = Infinity;
    trunk.forEach((t) => {
      const d = pointToSegDist(b.cx, b.cy, t.a.cx, t.a.cy, t.b.cx, t.b.cy);
      if (d < bestD) { bestD = d; best = t; }
    });
    if (best && bestD < 120) {
      // Project the bridge centroid onto the trunk line so the bridge sits
      // ON the road instead of off to the side.
      const proj = projectOnSeg(b.cx, b.cy, best.a.cx, best.a.cy, best.b.cx, best.b.cy);
      const dx = best.b.cx - best.a.cx, dy = best.b.cy - best.a.cy;
      return { ...b, cx: proj.x, cy: proj.y, horizontal: Math.abs(dx) >= Math.abs(dy) };
    }
    return null;
  }).filter(Boolean);
}

function pointToSegDist(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1;
  const len2 = dx * dx + dy * dy;
  if (len2 < 1) return Math.hypot(px - x1, py - y1);
  let t = ((px - x1) * dx + (py - y1) * dy) / len2;
  t = clamp(t, 0, 1);
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}
function projectOnSeg(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1;
  const len2 = dx * dx + dy * dy;
  if (len2 < 1) return { x: x1, y: y1 };
  let t = ((px - x1) * dx + (py - y1) * dy) / len2;
  t = clamp(t, 0, 1);
  return { x: x1 + t * dx, y: y1 + t * dy };
}

// Group bridge_tiles into spans by clustering. We expect ~1-3 actual bridges
// crossing the river even if the raw data has many tile-sized strip rectangles.
function clusterBridgeTiles(tiles, scale, offsetX, offsetY) {
  if (!tiles.length) return [];
  // Project to world px, then cluster by proximity.
  const pts = tiles.map((t) => ({
    x: offsetX + t.x * scale + scale / 2,
    y: offsetY + t.y * scale + scale / 2,
  }));
  const visited = new Array(pts.length).fill(false);
  const clusters = [];
  const thr = scale * 6;
  for (let i = 0; i < pts.length; i += 1) {
    if (visited[i]) continue;
    const q = [i]; visited[i] = true;
    const members = [];
    while (q.length) {
      const idx = q.shift(); members.push(pts[idx]);
      for (let j = 0; j < pts.length; j += 1) {
        if (visited[j]) continue;
        if (Math.hypot(pts[j].x - pts[idx].x, pts[j].y - pts[idx].y) < thr) {
          visited[j] = true; q.push(j);
        }
      }
    }
    // Centroid + axis-aligned span based on bbox
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    members.forEach((p) => {
      minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
      minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
    });
    clusters.push({
      cx: (minX + maxX) / 2, cy: (minY + maxY) / 2,
      w: Math.max(scale * 4, maxX - minX + scale * 2),
      h: Math.max(scale * 2.5, maxY - minY + scale * 1.5),
      horizontal: (maxX - minX) >= (maxY - minY),
    });
  }
  return clusters;
}

function renderVillage(mapData, frame, selectedAgent) {
  if (!state.bldgLayout) {
    const layout = computeLayout(mapData);
    state.bldgLayout = layout.buildings;
    state.decorations = layout.decorations;
    state.districts = layout.districts;
    state.bridgeSpans = layout.bridgeSpans;
    state.roadNetwork = layout.roadNetwork;
  }

  ctx.save();
  // Off-map gutter color
  ctx.fillStyle = "#d8d0bc";
  ctx.fillRect(0, 0, els.mapCanvas.width, els.mapCanvas.height);
  ctx.translate(state.panX, state.panY);
  ctx.scale(state.zoom, state.zoom);

  const { offsetX, offsetY, drawWidth, drawHeight } = state.renderMetrics;

  // ── OSM-style base: cream land ──
  ctx.fillStyle = "#f2ead6";
  ctx.fillRect(offsetX, offsetY, drawWidth, drawHeight);
  // Land use polygons per district (very subtle tint, like OSM)
  drawLandUse();

  // ── River + banks ──
  drawRiverOSM(mapData.tile_map);

  // ── Road network (locals → trunk → junctions) ──
  drawRoadsOSM();

  // ── Bridges where trunk crosses river ──
  drawBridgeSpansOSM();

  // ── Park decorations (trees) only inside park/leisure polygons ──
  drawDecorations();

  // ── Buildings on top of roads ──
  drawBuildings();

  // ── District labels ──
  drawDistrictLabels();

  // ── Selected route + agents + bubbles ──
  drawRouteHint(selectedAgent, mapNodes());
  drawAgents(frame);
  drawSpeechBubbles(frame);
  drawDayNight(frame);

  ctx.restore();
}

function drawDistrictTints() {
  if (!state.districts) return;
  state.districts.forEach((d) => {
    // Filled circle with thin dashed border — reads as a "neighborhood lot".
    ctx.fillStyle = d.color;
    ctx.beginPath(); ctx.arc(d.cx, d.cy, d.r, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = "rgba(28,38,48,0.20)";
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 4]);
    ctx.beginPath(); ctx.arc(d.cx, d.cy, d.r, 0, Math.PI * 2); ctx.stroke();
    ctx.setLineDash([]);
  });
}

function drawDistrictLabels() {
  if (!state.districts) return;
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  state.districts.forEach((d) => {
    if (d.n < 2) return;
    // Pill behind the label so it's legible over any background.
    ctx.font = "bold 13px 'Space Grotesk', sans-serif";
    const label = d.name.length > 16 ? d.name.slice(0, 15) + "…" : d.name;
    const tw = ctx.measureText(label).width;
    const ly = d.cy - d.r - 8;
    ctx.fillStyle = "rgba(28,38,48,0.78)";
    roundedRect(d.cx - tw / 2 - 10, ly - 10, tw + 20, 22, 11); ctx.fill();
    ctx.fillStyle = "#f4ede0";
    ctx.fillText(label, d.cx, ly + 1);
  });
  ctx.textAlign = "start"; ctx.textBaseline = "alphabetic";
}

function drawBridgeSpans() {
  if (!state.bridgeSpans) return;
  state.bridgeSpans.forEach((b) => {
    const w = b.horizontal ? b.w : b.h;
    const h = b.horizontal ? b.h : b.w;
    ctx.save();
    ctx.translate(b.cx, b.cy);
    if (!b.horizontal) ctx.rotate(Math.PI / 2);
    ctx.fillStyle = "#c0a274"; ctx.fillRect(-w / 2, -h / 2, w, h);
    ctx.fillStyle = "rgba(0,0,0,0.18)"; ctx.fillRect(-w / 2, h / 2 - 4, w, 4);
    // Plank stripes
    ctx.strokeStyle = "rgba(80,55,30,0.6)"; ctx.lineWidth = 1;
    for (let i = 1; i < 6; i += 1) {
      ctx.beginPath();
      ctx.moveTo(-w / 2 + (w / 6) * i, -h / 2);
      ctx.lineTo(-w / 2 + (w / 6) * i, h / 2);
      ctx.stroke();
    }
    // Railings
    ctx.strokeStyle = "#7c5a3a"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(-w / 2, -h / 2); ctx.lineTo(w / 2, -h / 2); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(-w / 2, h / 2); ctx.lineTo(w / 2, h / 2); ctx.stroke();
    ctx.restore();
  });
}

// Cleaner road network: only draw hub↔hub mains (asphalt road with center
// dashes) and local connectors as faint dotted hints. Avoids the spaghetti
// look of 186 edges drawn at full weight.
function drawRoads(mapData) {
  const nodes = mapNodes();
  const edges = (mapData || {}).edges || [];
  const { scale, offsetX, offsetY } = state.renderMetrics;
  const projX = (n) => offsetX + n.tile_x * scale + scale / 2;
  const projY = (n) => offsetY + n.tile_y * scale + scale / 2;
  const between = (e) => {
    const a = nodes.get(e.source || e.from); const b = nodes.get(e.target || e.to);
    return a && b ? { a, b } : null;
  };

  // Deduplicate parallel edges & ensure both endpoints exist.
  const seen = new Set();
  const segs = edges.map(between).filter(Boolean).filter((s) => {
    const key = [s.a.id, s.b.id].sort().join("→");
    if (seen.has(key)) return false; seen.add(key); return true;
  });
  const mains = segs.filter((s) => s.a.kind === "hub" || s.b.kind === "hub");
  const minors = segs.filter((s) => s.a.kind !== "hub" && s.b.kind !== "hub");

  ctx.lineCap = "round"; ctx.lineJoin = "round";

  // Minor connectors: faint dotted line (just a hint that places are linked).
  ctx.strokeStyle = "rgba(60, 70, 80, 0.18)";
  ctx.lineWidth = 1.5;
  ctx.setLineDash([2, 6]);
  minors.forEach((s) => {
    ctx.beginPath();
    ctx.moveTo(projX(s.a), projY(s.a));
    ctx.lineTo(projX(s.b), projY(s.b));
    ctx.stroke();
  });
  ctx.setLineDash([]);

  // Main asphalt outline → inner stripe → center yellow dashes
  mains.forEach((s) => {
    ctx.strokeStyle = "#2a2e36"; ctx.lineWidth = 22;
    ctx.beginPath(); ctx.moveTo(projX(s.a), projY(s.a)); ctx.lineTo(projX(s.b), projY(s.b)); ctx.stroke();
  });
  mains.forEach((s) => {
    ctx.strokeStyle = "#4a4f57"; ctx.lineWidth = 18;
    ctx.beginPath(); ctx.moveTo(projX(s.a), projY(s.a)); ctx.lineTo(projX(s.b), projY(s.b)); ctx.stroke();
  });
  mains.forEach((s) => {
    ctx.strokeStyle = "#f5e07c"; ctx.lineWidth = 2;
    ctx.setLineDash([14, 12]);
    ctx.beginPath(); ctx.moveTo(projX(s.a), projY(s.a)); ctx.lineTo(projX(s.b), projY(s.b)); ctx.stroke();
    ctx.setLineDash([]);
  });

  // Crosswalks at hub intersections.
  nodes.forEach((n) => {
    if (n.kind !== "hub") return;
    const x = projX(n), y = projY(n);
    // Junction pavement square
    ctx.fillStyle = "#4a4f57"; ctx.fillRect(x - 18, y - 18, 36, 36);
    ctx.strokeStyle = "#2a2e36"; ctx.lineWidth = 1.5;
    ctx.strokeRect(x - 18, y - 18, 36, 36);
    // Zebra stripes on each side
    ctx.fillStyle = "#f4ede0";
    for (let i = 0; i < 4; i += 1) {
      ctx.fillRect(x - 16 + i * 8, y - 22, 5, 4);   // top
      ctx.fillRect(x - 16 + i * 8, y + 18, 5, 4);   // bottom
      ctx.fillRect(x - 22, y - 16 + i * 8, 4, 5);   // left
      ctx.fillRect(x + 18, y - 16 + i * 8, 4, 5);   // right
    }
  });
}

// Map screen-space px → world-space px (inverse of the transform applied
// in renderVillage). Used by click/hover hit-tests when zoom != 1.
function screenToWorld(sx, sy) {
  return {
    x: (sx - state.panX) / state.zoom,
    y: (sy - state.panY) / state.zoom,
  };
}
// And the inverse for "world position" of a drawn sprite that we want to
// hit-test in screen space.
function worldToScreen(wx, wy) {
  return { x: wx * state.zoom + state.panX, y: wy * state.zoom + state.panY };
}

function drawGrassTexture(ox, oy, w, h) {
  if (!imgReady.tileset) return;
  // Sparse 14px grass-tile sprinkles to give texture without overpainting.
  const step = 56;
  for (let y = oy; y < oy + h; y += step) {
    for (let x = ox; x < ox + w; x += step) {
      const seed = ((x * 73856093) ^ (y * 19349663)) >>> 0;
      const r = (seed % 100) / 100;
      if (r < 0.15) drawSprite("flower_yellow", x, y, 12);
      else if (r < 0.25) drawSprite("flower_red", x, y, 12);
    }
  }
}

function drawRiver(tileMap) {
  const points = Array.isArray(tileMap.river_path) ? tileMap.river_path : [];
  if (points.length < 2) return;
  const { scale, offsetX, offsetY } = state.renderMetrics;
  ctx.strokeStyle = "#5c8faf";
  ctx.lineWidth = Math.max(8, scale * 2.2);
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = offsetX + p[0] * scale + scale / 2;
    const y = offsetY + p[1] * scale + scale / 2;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.strokeStyle = "#7fb1cf";
  ctx.lineWidth = Math.max(4, scale * 1.1);
  ctx.stroke();
}

// `drawBridges` and `drawPaths` are superseded by `drawBridgeSpans` and
// `drawRoads`. They remain as no-ops in case anything else calls them.
function drawBridges() { /* superseded by drawBridgeSpans */ }
function drawPaths() { /* superseded by drawRoads */ }

// ── OSM-style cartographic renderers ────────────────────────────────────

// Land use polygons per district. Color comes from the dominant building
// category in that district. Subtle tint, no hard borders.
function drawLandUse() {
  if (!state.districts || !state.bldgLayout) return;
  // Each district gets one color: weighted majority of its members' category.
  // We approximate the polygon as a soft circle around the district centroid.
  state.districts.forEach((d) => {
    const members = [...state.bldgLayout.values()].filter((b) => (b.node.district || "未知") === d.name);
    if (!members.length) return;
    const counts = {};
    members.forEach((b) => { counts[b.node.category] = (counts[b.node.category] || 0) + 1; });
    const top = Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
    ctx.fillStyle = LAND_USE_COLOR[top] || LAND_USE_COLOR.residential;
    ctx.beginPath(); ctx.arc(d.cx, d.cy, d.r + 6, 0, Math.PI * 2); ctx.fill();
  });
}

// Cleaner river: wide blue body + subtle lighter inner stripe, no flicker.
function drawRiverOSM(tileMap) {
  const points = Array.isArray(tileMap.river_path) ? tileMap.river_path : [];
  if (points.length < 2) return;
  const { scale, offsetX, offsetY } = state.renderMetrics;
  // Outer (bank / shoreline tint) for soft edge
  ctx.strokeStyle = "#a8c4d8";
  ctx.lineWidth = Math.max(14, scale * 3.0);
  ctx.lineJoin = "round"; ctx.lineCap = "round";
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = offsetX + p[0] * scale + scale / 2;
    const y = offsetY + p[1] * scale + scale / 2;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  // Inner river body
  ctx.strokeStyle = "#7fa9c5";
  ctx.lineWidth = Math.max(10, scale * 2.2);
  ctx.stroke();
  // Highlight
  ctx.strokeStyle = "rgba(255,255,255,0.18)";
  ctx.lineWidth = 1.5;
  ctx.stroke();
}

// OSM-style road rendering: drawn FROM the MST road network instead of from
// Render the road network from mapData.edges, styled by road_type. This
// reflects the real city_map topology (arterials, collectors, locals).
function drawRoadsOSM() {
  const trace = state.trace; if (!trace || !trace.map) return;
  const edges = trace.map.edges || [];
  if (!state.bldgLayout) return;
  ctx.lineCap = "round"; ctx.lineJoin = "round";

  // Bucket edges by road_type for ordered drawing (local under, arterial top).
  const buckets = { local: [], collector: [], arterial: [], bridge: [] };
  edges.forEach((e) => {
    const a = state.bldgLayout.get(e.source);
    const b = state.bldgLayout.get(e.target);
    if (!a || !b) return;
    const t = e.bridge ? "bridge" : (e.road_type || "local");
    if (!buckets[t]) buckets[t] = [];
    buckets[t].push({ a, b });
  });

  // Local — thin tan pedestrian path
  ctx.strokeStyle = "#c4a87e"; ctx.lineWidth = 3;
  buckets.local.forEach((s) => {
    ctx.beginPath(); ctx.moveTo(s.a.cx, s.a.cy); ctx.lineTo(s.b.cx, s.b.cy); ctx.stroke();
  });

  // Collector — medium sand-paved street
  ctx.strokeStyle = "#5a5a5a"; ctx.lineWidth = 7;
  buckets.collector.forEach((s) => {
    ctx.beginPath(); ctx.moveTo(s.a.cx, s.a.cy); ctx.lineTo(s.b.cx, s.b.cy); ctx.stroke();
  });
  ctx.strokeStyle = "#9a9486"; ctx.lineWidth = 5;
  buckets.collector.forEach((s) => {
    ctx.beginPath(); ctx.moveTo(s.a.cx, s.a.cy); ctx.lineTo(s.b.cx, s.b.cy); ctx.stroke();
  });

  // Arterial — wide asphalt with center yellow dashes
  ctx.strokeStyle = "#3a3a3a"; ctx.lineWidth = 14;
  buckets.arterial.forEach((s) => {
    ctx.beginPath(); ctx.moveTo(s.a.cx, s.a.cy); ctx.lineTo(s.b.cx, s.b.cy); ctx.stroke();
  });
  ctx.strokeStyle = "#7a7a7a"; ctx.lineWidth = 11;
  buckets.arterial.forEach((s) => {
    ctx.beginPath(); ctx.moveTo(s.a.cx, s.a.cy); ctx.lineTo(s.b.cx, s.b.cy); ctx.stroke();
  });
  ctx.strokeStyle = "#f5e07c"; ctx.lineWidth = 1.5;
  ctx.setLineDash([12, 10]);
  buckets.arterial.forEach((s) => {
    ctx.beginPath(); ctx.moveTo(s.a.cx, s.a.cy); ctx.lineTo(s.b.cx, s.b.cy); ctx.stroke();
  });
  ctx.setLineDash([]);

  // Bridge — render with bridge styling
  buckets.bridge.forEach((s) => {
    ctx.strokeStyle = "#8e8474"; ctx.lineWidth = 14;
    ctx.beginPath(); ctx.moveTo(s.a.cx, s.a.cy); ctx.lineTo(s.b.cx, s.b.cy); ctx.stroke();
    ctx.strokeStyle = "#3a3a3a"; ctx.lineWidth = 1.5;
    ctx.setLineDash([]);
  });

  // Hub junctions: subtle dot at hub center
  state.bldgLayout.forEach((b) => {
    if (!b.isHub) return;
    ctx.fillStyle = "rgba(58,58,58,0.85)";
    ctx.beginPath(); ctx.arc(b.cx, b.cy, 5, 0, Math.PI * 2); ctx.fill();
  });
}

function drawBridgeSpansOSM() {
  if (!state.bridgeSpans) return;
  state.bridgeSpans.forEach((b) => {
    const w = b.horizontal ? Math.max(60, b.w) : Math.max(28, b.h);
    const h = b.horizontal ? Math.max(28, b.h) : Math.max(60, b.w);
    ctx.save();
    ctx.translate(b.cx, b.cy);
    if (!b.horizontal) ctx.rotate(Math.PI / 2);
    // Bridge deck (lighter than asphalt, with railings)
    ctx.fillStyle = "#8e8474"; ctx.fillRect(-w / 2, -h / 2, w, h);
    ctx.strokeStyle = "#3a3a3a"; ctx.lineWidth = 1.5;
    ctx.strokeRect(-w / 2, -h / 2, w, h);
    // Railings (dark strips top + bottom)
    ctx.fillStyle = "#3a3a3a";
    ctx.fillRect(-w / 2, -h / 2, w, 3);
    ctx.fillRect(-w / 2, h / 2 - 3, w, 3);
    // Center yellow dash continues across the bridge
    ctx.strokeStyle = "#f5e07c"; ctx.lineWidth = 2;
    ctx.setLineDash([10, 8]);
    ctx.beginPath(); ctx.moveTo(-w / 2, 0); ctx.lineTo(w / 2, 0); ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  });
}

function drawDecorations() {
  if (!imgReady.tileset || !state.decorations) return;
  // Only draw tree decorations on the village now — flowers add clutter without
  // improving readability. Trees come from the tileset grove sprites.
  state.decorations.forEach((d) => {
    if (d.kind !== "tree" && d.kind !== "bush") return;
    const size = d.kind === "tree" ? 32 : 16;
    drawSprite(d.kind, d.x, d.y, size);
  });
}

// Hubs use the full Tuxemon sprite (= landmark). Places use a simple
// procedural "cottage" icon — keeps the village clean and readable.
function drawBuildings() {
  if (!state.bldgLayout) return;
  const sel = getSelectedAgentFrame();
  const targetLoc = sel && (sel.target_location || sel.location);
  const sorted = [...state.bldgLayout.values()].sort((a, b) => a.y - b.y);
  sorted.forEach((b) => {
    // Drop shadow ellipse
    ctx.fillStyle = "rgba(0,0,0,0.20)";
    ctx.beginPath();
    ctx.ellipse(b.x + b.w / 2, b.y + b.h - 2, b.w * 0.45, 5, 0, 0, Math.PI * 2);
    ctx.fill();
    if (b.isHub && imgReady.tileset) {
      // Hub: real building sprite from tileset
      ctx.drawImage(tilesetImg, b.srcRect[0], b.srcRect[1], b.srcRect[2], b.srcRect[3], b.x, b.y, b.w, b.h);
    } else {
      drawCottageIcon(b);
    }
    // Only label the currently-active building (the selected agent's loc).
    // District labels handle naming for the rest of the map.
    if (b.node.id === targetLoc) {
      const label = shortLabel(b.node.label);
      ctx.font = "bold 12px 'Space Grotesk', sans-serif";
      const tw = ctx.measureText(label).width;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      const pad = 6;
      roundedRect(b.x + b.w / 2 - tw / 2 - pad, b.y - 22, tw + pad * 2, 18, 4);
      ctx.fillStyle = "rgba(220, 125, 45, 0.96)"; ctx.fill();
      ctx.fillStyle = "#fff7e1";
      ctx.fillText(label, b.x + b.w / 2, b.y - 13);
      ctx.textAlign = "start"; ctx.textBaseline = "alphabetic";
    }
  });
}

// OSM-style building footprint: filled rectangle, thin dark outline, color by
// category. Drops the fantasy "pitched roof + door + window" look in favor of
// the way real maps render buildings at zoom 17–18.
const CATEGORY_FILL = {
  residential: "#d9c194",
  commerce:    "#e8c184",
  education:   "#a8c2cf",
  medical:     "#e0a8ad",
  leisure:     "#a8c896",
  government:  "#b6ad8e",
  industry:    "#a8a094",
  mixed:       "#cbb47d",
  transit:     "#a6b2c8",
};

function drawCottageIcon(b) {
  const x = b.x, y = b.y, w = b.w, h = b.h;
  const fill = CATEGORY_FILL[b.node.category] || CATEGORY_FILL.residential;
  // Solid footprint
  ctx.fillStyle = fill;
  ctx.fillRect(x, y, w, h);
  // Thin dark outline — OSM convention
  ctx.strokeStyle = "rgba(40, 40, 40, 0.85)";
  ctx.lineWidth = 1.5;
  ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
  // Subtle highlight on top edge for slight 3D feel
  ctx.fillStyle = "rgba(255,255,255,0.18)";
  ctx.fillRect(x + 1, y + 1, w - 2, 2);
}

function drawRouteHint(selectedAgent, nodes) {
  if (!selectedAgent || !selectedAgent.travel || !Array.isArray(selectedAgent.travel.route)) return;
  if (selectedAgent.travel.route.length < 2) return;
  const { scale } = state.renderMetrics;
  ctx.strokeStyle = "rgba(220, 125, 45, 0.85)";
  ctx.lineWidth = Math.max(3, scale * 0.4);
  ctx.setLineDash([8, 8]);
  ctx.beginPath();
  let started = false;
  selectedAgent.travel.route.forEach((nodeId) => {
    const p = nodeDisplayCenter(nodeId, nodes); if (!p) return;
    if (!started) { ctx.moveTo(p.x, p.y); started = true; }
    else ctx.lineTo(p.x, p.y);
  });
  ctx.stroke();
  ctx.setLineDash([]);
}

function drawAgents(frame) {
  const nodes = mapNodes();
  // Cluster agents at same location so they don't perfectly overlap.
  const locCount = new Map();
  frame.agents.forEach((a) => {
    const pos = agentPixelPosition(a, nodes); if (!pos) return;
    const key = `${Math.round(pos.x / 10)},${Math.round(pos.y / 10)}`;
    locCount.set(key, (locCount.get(key) || 0) + 1);
    a._renderPos = pos; a._cluster = locCount.get(key) - 1;
  });

  frame.agents.forEach((a) => {
    const pos = a._renderPos; if (!pos) return;
    const cluster = a._cluster || 0;
    const dx = (cluster % 3) * 14 - 14;
    const dy = Math.floor(cluster / 3) * 10;
    const px = pos.x + dx;
    const py = pos.y + dy;
    const traveling = a.travel && ["departed", "in_transit"].includes(a.travel.status);
    const mode = traveling ? String((a.travel && a.travel.mode) || "walk").toLowerCase() : "walk";
    // Vehicle is drawn underneath the character so the person sits "on" it.
    if (traveling && mode !== "walk") drawVehicle(mode, px, py, agentColor(a.agent_id));
    drawCharacter(a, px, py);
    a._spriteX = px; a._spriteY = py;
  });
}

// Simple side-on vehicle sprites for the village view. Drawn beneath the
// character. Direction is implied by character facing; sprites are symmetric.
function drawVehicle(mode, px, py, tint) {
  const t = Date.now();
  // Wheel "spin" bob: subtle vertical jitter for moving vehicles.
  const bob = Math.sin(t / 80) * 0.6;
  switch (mode) {
    case "bike":
    case "e-bike":
    case "bicycle": {
      ctx.save(); ctx.translate(px, py + 14 + bob);
      ctx.strokeStyle = "#222"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(-7, 0, 5, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath(); ctx.arc(7, 0, 5, 0, Math.PI * 2); ctx.stroke();
      ctx.strokeStyle = tint; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(-7, 0); ctx.lineTo(0, -6); ctx.lineTo(7, 0); ctx.stroke();
      ctx.restore(); return;
    }
    case "car":
    case "taxi": {
      ctx.save(); ctx.translate(px, py + 14 + bob);
      ctx.fillStyle = tint; roundedRect(-16, -10, 32, 14, 4); ctx.fill();
      ctx.fillStyle = "#a8d4ee"; ctx.fillRect(-10, -8, 20, 6);
      ctx.fillStyle = "#222";
      ctx.beginPath(); ctx.arc(-10, 5, 3, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.arc(10, 5, 3, 0, Math.PI * 2); ctx.fill();
      ctx.restore(); return;
    }
    case "bus": {
      ctx.save(); ctx.translate(px, py + 14 + bob);
      ctx.fillStyle = "#dc7d2d"; roundedRect(-22, -12, 44, 18, 3); ctx.fill();
      ctx.fillStyle = "#a8d4ee";
      for (let i = 0; i < 4; i += 1) ctx.fillRect(-18 + i * 10, -9, 7, 7);
      ctx.fillStyle = "#222";
      ctx.beginPath(); ctx.arc(-14, 8, 3, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.arc(14, 8, 3, 0, Math.PI * 2); ctx.fill();
      ctx.restore(); return;
    }
    case "metro":
    case "subway":
    case "train": {
      ctx.save(); ctx.translate(px, py + 14 + bob);
      ctx.fillStyle = "#8f5bd8"; roundedRect(-24, -10, 48, 16, 4); ctx.fill();
      ctx.fillStyle = "#fff7e1"; ctx.font = "bold 11px sans-serif";
      ctx.textAlign = "center"; ctx.fillText("M", 0, 2); ctx.textAlign = "start";
      ctx.fillStyle = "#a8d4ee";
      for (let i = 0; i < 3; i += 1) ctx.fillRect(-20 + i * 14, -7, 6, 5);
      ctx.restore(); return;
    }
    default:
      return; // walk → no vehicle
  }
}

function characterDirection(agent) {
  const travel = agent.travel || {};
  if (!["departed", "in_transit"].includes(travel.status)) return "front";
  const nodes = mapNodes();
  const start = nodes.get(agent.resolved_location);
  const end = nodes.get(agent.target_location);
  if (!start || !end) return "front";
  const dx = end.tile_x - start.tile_x;
  const dy = end.tile_y - start.tile_y;
  if (Math.abs(dx) > Math.abs(dy)) return dx > 0 ? "right" : "left";
  return dy > 0 ? "front" : "back";
}

function drawCharacter(agent, px, py) {
  const tint = agentColor(agent.agent_id);
  const isSelected = agent.agent_id === state.selectedAgentId;
  const dir = characterDirection(agent);
  const walking = ["departed", "in_transit"].includes((agent.travel || {}).status);
  const frameKey = walking
    ? `misa-${dir}-walk.00${Math.floor(Date.now() / 220) % 4}`
    : `misa-${dir}`;
  const charH = 38;
  const charW = 30;
  // Shadow
  ctx.fillStyle = "rgba(0,0,0,0.28)";
  ctx.beginPath();
  ctx.ellipse(px, py + charH / 2 - 1, charW / 2.2, 5, 0, 0, Math.PI * 2);
  ctx.fill();

  // Selected ring
  if (isSelected) {
    ctx.strokeStyle = "rgba(255, 220, 120, 0.95)";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.ellipse(px, py + charH / 2 - 1, charW / 1.7, 8, 0, 0, Math.PI * 2);
    ctx.stroke();
  }

  if (imgReady.misa && misaFrames && misaFrames[frameKey]) {
    const tinted = getTintedCharacter(agent.agent_id, tint, frameKey);
    if (tinted) {
      ctx.drawImage(tinted, px - charW / 2, py - charH / 2, charW, charH);
      return;
    }
  }
  // Fallback: simple humanoid blob.
  ctx.fillStyle = tint;
  ctx.beginPath();
  ctx.arc(px, py - 6, 8, 0, Math.PI * 2); ctx.fill();
  ctx.fillRect(px - 8, py, 16, 14);
}

// Tint a misa sprite frame by composing the source onto a tinted canvas.
function getTintedCharacter(agentId, tint, frameKey) {
  const cacheKey = `${agentId}:${frameKey}:${tint}`;
  if (state.agentTints.has(cacheKey)) return state.agentTints.get(cacheKey);
  if (!misaFrames || !misaFrames[frameKey]) return null;
  const f = misaFrames[frameKey].frame;
  const c = document.createElement("canvas");
  c.width = f.w; c.height = f.h;
  const cx = c.getContext("2d");
  cx.imageSmoothingEnabled = false;
  cx.drawImage(misaImg, f.x, f.y, f.w, f.h, 0, 0, f.w, f.h);
  // Multiply with tint over a copy: hue-style tint by drawing tint with source-atop.
  cx.globalCompositeOperation = "source-atop";
  cx.fillStyle = tint + "55";
  cx.fillRect(0, 0, f.w, f.h);
  cx.globalCompositeOperation = "source-over";
  state.agentTints.set(cacheKey, c);
  return c;
}

function drawSpeechBubbles(frame) {
  ctx.font = "14px 'Manrope', sans-serif";
  frame.agents.forEach((a) => {
    if (!a._spriteX) return;
    const initials = nameInitials(a.name);
    const emoji = activityToEmoji(a.activity || a.scheduled_activity || a.action);
    const text = `${initials}: ${emoji}`;
    const tw = ctx.measureText(text).width + 16;
    const th = 22;
    const bx = a._spriteX - tw / 2;
    const by = a._spriteY - 42;
    // bubble
    ctx.fillStyle = "rgba(255,255,255,0.96)";
    ctx.strokeStyle = "rgba(40, 60, 60, 0.85)";
    ctx.lineWidth = 1.5;
    roundedRect(bx, by, tw, th, 5);
    ctx.fill(); ctx.stroke();
    // tail
    ctx.beginPath();
    ctx.moveTo(a._spriteX - 4, by + th);
    ctx.lineTo(a._spriteX, by + th + 6);
    ctx.lineTo(a._spriteX + 4, by + th);
    ctx.closePath();
    ctx.fillStyle = "rgba(255,255,255,0.96)"; ctx.fill();
    ctx.strokeStyle = "rgba(40, 60, 60, 0.85)"; ctx.stroke();
    // text
    ctx.fillStyle = "#1e2c2c";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, bx + tw / 2, by + th / 2 + 1);
    ctx.textAlign = "start"; ctx.textBaseline = "alphabetic";
  });

  // Selected agent gets a fuller dialog quote underneath the bubble.
  const sel = getSelectedAgentFrame();
  if (!sel || !sel._spriteX) return;
  const quote = (sel.perception || sel.reflection || sel.plan || "").split("；")[0].slice(0, 56);
  if (!quote) return;
  ctx.font = "12px 'Manrope', sans-serif";
  const tw = Math.min(ctx.measureText(quote).width + 20, 280);
  const tx = clamp(sel._spriteX - tw / 2, 8, els.mapCanvas.width - tw - 8);
  const ty = sel._spriteY + 32;
  ctx.fillStyle = "rgba(33, 42, 50, 0.92)";
  roundedRect(tx, ty, tw, 28, 6); ctx.fill();
  ctx.fillStyle = "#fff7e1";
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(quote, tx + tw / 2, ty + 14);
  ctx.textAlign = "start"; ctx.textBaseline = "alphabetic";
}

function drawDayNight(frame) {
  const { offsetX, offsetY, drawWidth, drawHeight } = state.renderMetrics;
  const hour = Number((frame.time || "12:00").split(":")[0] || 12);
  if (hour >= 6 && hour < 18) return;
  const alpha = hour >= 18 && hour < 22 ? 0.18 : 0.32;
  ctx.fillStyle = `rgba(22, 31, 54, ${alpha})`;
  ctx.fillRect(offsetX, offsetY, drawWidth, drawHeight);
}

function drawSprite(key, cx, cy, size) {
  const r = TILESET[key];
  if (!r || !imgReady.tileset) return;
  ctx.drawImage(tilesetImg, r[0], r[1], r[2], r[3], cx - size / 2, cy - size, size, size * (r[3] / r[2]));
}

// ───────── indoor rendering ─────────
// Per-category furniture layout. Coordinates are in normalized 0..1 across the
// indoor room. `kind` is a stylized shape; `slot` marks where an agent can be
// placed for that activity.
const INTERIOR_LAYOUTS = {
  residential: {
    floor: "#f0d9a8", wall: "#c19a6b", accent: "#8b5a2b", wallpaper: "stripe",
    furniture: [
      // bedroom zone (left)
      { kind: "area_rug", x: 0.06, y: 0.30, w: 0.34, h: 0.32 },
      { kind: "bed", x: 0.08, y: 0.32, w: 0.22, h: 0.30, slot: "sleep" },
      { kind: "nightstand", x: 0.31, y: 0.38, w: 0.06, h: 0.10 },
      { kind: "lamp", x: 0.31, y: 0.28, w: 0.06, h: 0.10 },
      { kind: "picture_frame", x: 0.14, y: 0.00, w: 0.10, h: 0.08 },
      // dining/kitchen zone (right back)
      { kind: "kitchen_unit", x: 0.55, y: 0.18, w: 0.40, h: 0.16 },
      { kind: "fridge", x: 0.92, y: 0.20, w: 0.06, h: 0.18 },
      { kind: "table", x: 0.62, y: 0.42, w: 0.18, h: 0.16, slot: "eat" },
      { kind: "chair", x: 0.58, y: 0.58, w: 0.06, h: 0.08, slot: "sit" },
      { kind: "chair", x: 0.78, y: 0.58, w: 0.06, h: 0.08, slot: "sit" },
      // living zone (front)
      { kind: "area_rug", x: 0.40, y: 0.70, w: 0.42, h: 0.20 },
      { kind: "sofa", x: 0.42, y: 0.74, w: 0.30, h: 0.12, slot: "watch" },
      { kind: "coffee_table", x: 0.50, y: 0.86, w: 0.14, h: 0.06, slot: "coffee" },
      { kind: "tv", x: 0.85, y: 0.74, w: 0.10, h: 0.08 },
      { kind: "plant_pot", x: 0.78, y: 0.86, w: 0.06, h: 0.10 },
      { kind: "bookshelf", x: 0.04, y: 0.74, w: 0.22, h: 0.08, slot: "read" },
    ],
  },
  leisure: {
    floor: "#e6d3a8", wall: "#a06a45", accent: "#7d4427", wallpaper: "brick",
    furniture: [
      // bar area along back wall
      { kind: "counter", x: 0.06, y: 0.18, w: 0.55, h: 0.10, slot: "order" },
      { kind: "coffee_machine", x: 0.10, y: 0.06, w: 0.10, h: 0.12 },
      { kind: "coffee_machine", x: 0.24, y: 0.06, w: 0.10, h: 0.12 },
      { kind: "picture_frame", x: 0.70, y: 0.04, w: 0.12, h: 0.10 },
      // dining floor
      { kind: "area_rug", x: 0.18, y: 0.42, w: 0.30, h: 0.32 },
      { kind: "coffee_table", x: 0.25, y: 0.50, w: 0.14, h: 0.10, slot: "coffee" },
      { kind: "chair", x: 0.22, y: 0.62, w: 0.07, h: 0.08, slot: "sit" },
      { kind: "chair", x: 0.36, y: 0.62, w: 0.07, h: 0.08, slot: "sit" },
      { kind: "coffee_table", x: 0.60, y: 0.50, w: 0.14, h: 0.10, slot: "coffee" },
      { kind: "chair", x: 0.57, y: 0.62, w: 0.07, h: 0.08, slot: "sit" },
      { kind: "chair", x: 0.71, y: 0.62, w: 0.07, h: 0.08, slot: "sit" },
      { kind: "coffee_table", x: 0.40, y: 0.78, w: 0.14, h: 0.10, slot: "coffee" },
      { kind: "chair", x: 0.37, y: 0.90, w: 0.07, h: 0.08, slot: "sit" },
      { kind: "chair", x: 0.51, y: 0.90, w: 0.07, h: 0.08, slot: "sit" },
      { kind: "plant_pot", x: 0.86, y: 0.40, w: 0.08, h: 0.16 },
      { kind: "plant_pot", x: 0.86, y: 0.72, w: 0.08, h: 0.16 },
    ],
  },
  education: {
    floor: "#d8c89a", wall: "#728f6a", accent: "#3f5f3a", wallpaper: "stripe",
    furniture: [
      { kind: "chalkboard", x: 0.20, y: 0.04, w: 0.60, h: 0.10 },
      { kind: "podium", x: 0.46, y: 0.18, w: 0.08, h: 0.10 },
      { kind: "picture_frame", x: 0.05, y: 0.02, w: 0.10, h: 0.08 },
      { kind: "picture_frame", x: 0.85, y: 0.02, w: 0.10, h: 0.08 },
      // 3×3 student desk grid
      { kind: "desk", x: 0.15, y: 0.38, w: 0.12, h: 0.10, slot: "study" },
      { kind: "desk", x: 0.34, y: 0.38, w: 0.12, h: 0.10, slot: "study" },
      { kind: "desk", x: 0.53, y: 0.38, w: 0.12, h: 0.10, slot: "study" },
      { kind: "desk", x: 0.72, y: 0.38, w: 0.12, h: 0.10, slot: "study" },
      { kind: "desk", x: 0.15, y: 0.58, w: 0.12, h: 0.10, slot: "study" },
      { kind: "desk", x: 0.34, y: 0.58, w: 0.12, h: 0.10, slot: "study" },
      { kind: "desk", x: 0.53, y: 0.58, w: 0.12, h: 0.10, slot: "study" },
      { kind: "desk", x: 0.72, y: 0.58, w: 0.12, h: 0.10, slot: "study" },
      { kind: "chair", x: 0.18, y: 0.50, w: 0.06, h: 0.07, slot: "sit" },
      { kind: "chair", x: 0.37, y: 0.50, w: 0.06, h: 0.07, slot: "sit" },
      { kind: "chair", x: 0.56, y: 0.50, w: 0.06, h: 0.07, slot: "sit" },
      { kind: "chair", x: 0.75, y: 0.50, w: 0.06, h: 0.07, slot: "sit" },
      { kind: "bookshelf", x: 0.05, y: 0.85, w: 0.45, h: 0.08, slot: "read" },
      { kind: "plant_pot", x: 0.88, y: 0.85, w: 0.08, h: 0.12 },
    ],
  },
  commerce: {
    floor: "#e8d8b8", wall: "#a87042", accent: "#6a4220", wallpaper: "tile",
    furniture: [
      // product shelves
      { kind: "shelf", x: 0.08, y: 0.20, w: 0.08, h: 0.50 },
      { kind: "shelf", x: 0.22, y: 0.20, w: 0.08, h: 0.50 },
      { kind: "shelf", x: 0.36, y: 0.20, w: 0.08, h: 0.50 },
      { kind: "shelf", x: 0.50, y: 0.20, w: 0.08, h: 0.50 },
      { kind: "shelf", x: 0.64, y: 0.20, w: 0.08, h: 0.50 },
      // checkout area
      { kind: "checkout", x: 0.78, y: 0.55, w: 0.18, h: 0.10, slot: "shop" },
      { kind: "fridge", x: 0.86, y: 0.20, w: 0.10, h: 0.30 },
      { kind: "area_rug", x: 0.10, y: 0.80, w: 0.60, h: 0.12 },
      { kind: "plant_pot", x: 0.78, y: 0.78, w: 0.08, h: 0.14 },
    ],
  },
  medical: {
    floor: "#e8eef0", wall: "#a8bcc4", accent: "#6f8d96", wallpaper: "tile",
    furniture: [
      { kind: "picture_frame", x: 0.10, y: 0.02, w: 0.10, h: 0.08 },
      { kind: "picture_frame", x: 0.80, y: 0.02, w: 0.10, h: 0.08 },
      // patient beds with bedside curtains
      { kind: "bed", x: 0.08, y: 0.22, w: 0.22, h: 0.16, slot: "rest" },
      { kind: "nightstand", x: 0.31, y: 0.26, w: 0.06, h: 0.08 },
      { kind: "lamp", x: 0.31, y: 0.18, w: 0.06, h: 0.08 },
      { kind: "bed", x: 0.08, y: 0.48, w: 0.22, h: 0.16, slot: "rest" },
      { kind: "nightstand", x: 0.31, y: 0.52, w: 0.06, h: 0.08 },
      { kind: "lamp", x: 0.31, y: 0.44, w: 0.06, h: 0.08 },
      { kind: "bed", x: 0.08, y: 0.74, w: 0.22, h: 0.16, slot: "rest" },
      // consult zone
      { kind: "desk", x: 0.62, y: 0.36, w: 0.20, h: 0.12, slot: "consult" },
      { kind: "chair", x: 0.60, y: 0.52, w: 0.08, h: 0.10, slot: "sit" },
      { kind: "chair", x: 0.74, y: 0.52, w: 0.08, h: 0.10, slot: "sit" },
      { kind: "shelf", x: 0.86, y: 0.36, w: 0.10, h: 0.40 },
      { kind: "plant_pot", x: 0.65, y: 0.78, w: 0.08, h: 0.14 },
    ],
  },
  government: {
    floor: "#dfd6c2", wall: "#7e7558", accent: "#56503a", wallpaper: "stripe",
    furniture: [
      { kind: "podium", x: 0.46, y: 0.08, w: 0.08, h: 0.10 },
      { kind: "picture_frame", x: 0.10, y: 0.02, w: 0.10, h: 0.08 },
      { kind: "picture_frame", x: 0.80, y: 0.02, w: 0.10, h: 0.08 },
      { kind: "desk", x: 0.18, y: 0.30, w: 0.18, h: 0.12, slot: "work" },
      { kind: "desk", x: 0.42, y: 0.30, w: 0.18, h: 0.12, slot: "work" },
      { kind: "desk", x: 0.66, y: 0.30, w: 0.18, h: 0.12, slot: "work" },
      { kind: "chair", x: 0.21, y: 0.46, w: 0.08, h: 0.10, slot: "sit" },
      { kind: "chair", x: 0.45, y: 0.46, w: 0.08, h: 0.10, slot: "sit" },
      { kind: "chair", x: 0.69, y: 0.46, w: 0.08, h: 0.10, slot: "sit" },
      { kind: "area_rug", x: 0.30, y: 0.68, w: 0.40, h: 0.18 },
      { kind: "bookshelf", x: 0.05, y: 0.80, w: 0.22, h: 0.08, slot: "read" },
      { kind: "plant_pot", x: 0.86, y: 0.78, w: 0.08, h: 0.14 },
    ],
  },
  mixed: {
    floor: "#e6d6b0", wall: "#9c7548", accent: "#5e4225", wallpaper: "stripe",
    furniture: [
      { kind: "picture_frame", x: 0.10, y: 0.02, w: 0.10, h: 0.08 },
      { kind: "sofa", x: 0.20, y: 0.35, w: 0.30, h: 0.14, slot: "sit" },
      { kind: "coffee_table", x: 0.26, y: 0.52, w: 0.18, h: 0.08, slot: "coffee" },
      { kind: "area_rug", x: 0.18, y: 0.45, w: 0.34, h: 0.20 },
      { kind: "bookshelf", x: 0.62, y: 0.20, w: 0.34, h: 0.08, slot: "read" },
      { kind: "desk", x: 0.62, y: 0.42, w: 0.18, h: 0.12, slot: "work" },
      { kind: "chair", x: 0.66, y: 0.58, w: 0.08, h: 0.10, slot: "sit" },
      { kind: "plant_pot", x: 0.85, y: 0.78, w: 0.08, h: 0.14 },
      { kind: "lamp", x: 0.50, y: 0.18, w: 0.08, h: 0.12 },
    ],
  },
};
INTERIOR_LAYOUTS.industry = INTERIOR_LAYOUTS.commerce;
INTERIOR_LAYOUTS.transit = INTERIOR_LAYOUTS.government;

// Outdoor / specialized location layouts, selected by name keyword instead of
// category. These override the category default when the node label matches.
INTERIOR_LAYOUTS.park = {
  floor: "#7da35d", wall: "#a8d4ee", accent: "#3f7ba6", outdoor: true,
  furniture: [
    { kind: "tree_big", x: 0.10, y: 0.30, w: 0.12, h: 0.20 },
    { kind: "tree_big", x: 0.78, y: 0.30, w: 0.12, h: 0.20 },
    { kind: "fountain", x: 0.42, y: 0.40, w: 0.16, h: 0.16 },
    { kind: "bench", x: 0.25, y: 0.65, w: 0.14, h: 0.05, slot: "rest" },
    { kind: "bench", x: 0.60, y: 0.65, w: 0.14, h: 0.05, slot: "rest" },
    { kind: "flowerbed", x: 0.40, y: 0.78, w: 0.20, h: 0.06 },
  ],
};
INTERIOR_LAYOUTS.library = {
  floor: "#e6d3a8", wall: "#7d5a3a", accent: "#4a3a25", wallpaper: "stripe",
  furniture: [
    { kind: "bookshelf", x: 0.05, y: 0.18, w: 0.90, h: 0.10, slot: "read" },
    { kind: "bookshelf", x: 0.05, y: 0.42, w: 0.40, h: 0.10, slot: "read" },
    { kind: "bookshelf", x: 0.55, y: 0.42, w: 0.40, h: 0.10, slot: "read" },
    { kind: "area_rug", x: 0.15, y: 0.60, w: 0.70, h: 0.24 },
    { kind: "desk", x: 0.20, y: 0.62, w: 0.14, h: 0.10, slot: "study" },
    { kind: "desk", x: 0.43, y: 0.62, w: 0.14, h: 0.10, slot: "study" },
    { kind: "desk", x: 0.66, y: 0.62, w: 0.14, h: 0.10, slot: "study" },
    { kind: "lamp", x: 0.24, y: 0.55, w: 0.06, h: 0.08 },
    { kind: "lamp", x: 0.47, y: 0.55, w: 0.06, h: 0.08 },
    { kind: "lamp", x: 0.70, y: 0.55, w: 0.06, h: 0.08 },
    { kind: "chair", x: 0.23, y: 0.76, w: 0.08, h: 0.10, slot: "sit" },
    { kind: "chair", x: 0.46, y: 0.76, w: 0.08, h: 0.10, slot: "sit" },
    { kind: "chair", x: 0.69, y: 0.76, w: 0.08, h: 0.10, slot: "sit" },
    { kind: "plant_pot", x: 0.88, y: 0.84, w: 0.08, h: 0.12 },
  ],
};
INTERIOR_LAYOUTS.gym = {
  floor: "#b8b8b8", wall: "#5a5a5a", accent: "#dc7d2d", wallpaper: "tile",
  furniture: [
    { kind: "picture_frame", x: 0.10, y: 0.02, w: 0.10, h: 0.08 },
    { kind: "picture_frame", x: 0.80, y: 0.02, w: 0.10, h: 0.08 },
    // cardio row
    { kind: "treadmill", x: 0.10, y: 0.25, w: 0.10, h: 0.22, slot: "exercise" },
    { kind: "treadmill", x: 0.24, y: 0.25, w: 0.10, h: 0.22, slot: "exercise" },
    { kind: "treadmill", x: 0.38, y: 0.25, w: 0.10, h: 0.22, slot: "exercise" },
    { kind: "treadmill", x: 0.52, y: 0.25, w: 0.10, h: 0.22, slot: "exercise" },
    // free-weights area
    { kind: "weightrack", x: 0.70, y: 0.20, w: 0.22, h: 0.10 },
    { kind: "weightrack", x: 0.70, y: 0.38, w: 0.22, h: 0.10 },
    // yoga zone
    { kind: "area_rug", x: 0.12, y: 0.60, w: 0.40, h: 0.30 },
    { kind: "mat", x: 0.18, y: 0.66, w: 0.16, h: 0.10, slot: "yoga" },
    { kind: "mat", x: 0.36, y: 0.66, w: 0.16, h: 0.10, slot: "yoga" },
    { kind: "mat", x: 0.18, y: 0.80, w: 0.16, h: 0.10, slot: "yoga" },
    { kind: "mat", x: 0.36, y: 0.80, w: 0.16, h: 0.10, slot: "yoga" },
    { kind: "plant_pot", x: 0.86, y: 0.78, w: 0.08, h: 0.14 },
  ],
};
INTERIOR_LAYOUTS.restaurant = {
  floor: "#e6d3a8", wall: "#a06a45", accent: "#7d4427", wallpaper: "brick",
  furniture: [
    // back-of-house line
    { kind: "kitchen_unit", x: 0.06, y: 0.16, w: 0.34, h: 0.14 },
    { kind: "fridge", x: 0.42, y: 0.16, w: 0.08, h: 0.18 },
    { kind: "counter", x: 0.52, y: 0.20, w: 0.42, h: 0.10 },
    { kind: "coffee_machine", x: 0.56, y: 0.10, w: 0.08, h: 0.10 },
    { kind: "picture_frame", x: 0.74, y: 0.04, w: 0.12, h: 0.08 },
    // dining tables
    { kind: "area_rug", x: 0.08, y: 0.42, w: 0.84, h: 0.42 },
    { kind: "table", x: 0.18, y: 0.46, w: 0.14, h: 0.14, slot: "eat" },
    { kind: "chair", x: 0.15, y: 0.62, w: 0.07, h: 0.08, slot: "sit" },
    { kind: "chair", x: 0.29, y: 0.62, w: 0.07, h: 0.08, slot: "sit" },
    { kind: "table", x: 0.44, y: 0.46, w: 0.14, h: 0.14, slot: "eat" },
    { kind: "chair", x: 0.41, y: 0.62, w: 0.07, h: 0.08, slot: "sit" },
    { kind: "chair", x: 0.55, y: 0.62, w: 0.07, h: 0.08, slot: "sit" },
    { kind: "table", x: 0.70, y: 0.46, w: 0.14, h: 0.14, slot: "eat" },
    { kind: "chair", x: 0.67, y: 0.62, w: 0.07, h: 0.08, slot: "sit" },
    { kind: "chair", x: 0.81, y: 0.62, w: 0.07, h: 0.08, slot: "sit" },
    { kind: "table", x: 0.31, y: 0.74, w: 0.14, h: 0.12, slot: "eat" },
    { kind: "chair", x: 0.28, y: 0.86, w: 0.07, h: 0.08, slot: "sit" },
    { kind: "chair", x: 0.42, y: 0.86, w: 0.07, h: 0.08, slot: "sit" },
    { kind: "table", x: 0.57, y: 0.74, w: 0.14, h: 0.12, slot: "eat" },
    { kind: "chair", x: 0.54, y: 0.86, w: 0.07, h: 0.08, slot: "sit" },
    { kind: "chair", x: 0.68, y: 0.86, w: 0.07, h: 0.08, slot: "sit" },
    { kind: "plant_pot", x: 0.04, y: 0.78, w: 0.08, h: 0.16 },
  ],
};
INTERIOR_LAYOUTS.office = {
  floor: "#dfd6c2", wall: "#7e7558", accent: "#56503a", wallpaper: "tile",
  furniture: [
    { kind: "picture_frame", x: 0.10, y: 0.02, w: 0.10, h: 0.08 },
    { kind: "picture_frame", x: 0.80, y: 0.02, w: 0.10, h: 0.08 },
    // workstation row
    { kind: "desk", x: 0.06, y: 0.22, w: 0.18, h: 0.12, slot: "work" },
    { kind: "desk", x: 0.28, y: 0.22, w: 0.18, h: 0.12, slot: "work" },
    { kind: "desk", x: 0.52, y: 0.22, w: 0.18, h: 0.12, slot: "work" },
    { kind: "desk", x: 0.76, y: 0.22, w: 0.18, h: 0.12, slot: "work" },
    { kind: "chair", x: 0.10, y: 0.38, w: 0.08, h: 0.10, slot: "sit" },
    { kind: "chair", x: 0.32, y: 0.38, w: 0.08, h: 0.10, slot: "sit" },
    { kind: "chair", x: 0.56, y: 0.38, w: 0.08, h: 0.10, slot: "sit" },
    { kind: "chair", x: 0.80, y: 0.38, w: 0.08, h: 0.10, slot: "sit" },
    { kind: "lamp", x: 0.22, y: 0.16, w: 0.06, h: 0.08 },
    { kind: "lamp", x: 0.70, y: 0.16, w: 0.06, h: 0.08 },
    // meeting zone
    { kind: "area_rug", x: 0.22, y: 0.58, w: 0.56, h: 0.30 },
    { kind: "sofa", x: 0.26, y: 0.62, w: 0.30, h: 0.12, slot: "sit" },
    { kind: "coffee_table", x: 0.34, y: 0.78, w: 0.18, h: 0.08, slot: "coffee" },
    { kind: "plant_pot", x: 0.62, y: 0.60, w: 0.08, h: 0.14 },
    { kind: "plant_pot", x: 0.86, y: 0.78, w: 0.08, h: 0.14 },
  ],
};

// Resolve node → layout key. Name keywords win over category so a
// "Riverside Park" (category leisure) gets the park layout instead of a cafe.
function resolveLayoutKey(node) {
  if (!node) return "residential";
  const name = String(node.label || node.id || "").toLowerCase();
  const NAME_RULES = [
    [/park|公园|绿地|广场|square/, "park"],
    [/library|图书馆|阅览/, "library"],
    [/gym|健身|fitness/, "gym"],
    [/school|学校|college|大学|university|课堂/, "education"],
    [/hospital|clinic|诊所|医院|医疗/, "medical"],
    [/cafe|coffee|咖啡|茶馆|teahouse/, "leisure"],
    [/restaurant|餐厅|食堂|饭店|noodle/, "restaurant"],
    [/office|办公|company|公司/, "office"],
    [/market|store|shop|商店|超市|mall/, "commerce"],
    [/home|house|住宅|公寓|building [a-z]-/, "residential"],
  ];
  for (const [pat, key] of NAME_RULES) {
    if (pat.test(name) && INTERIOR_LAYOUTS[key]) return key;
  }
  return INTERIOR_LAYOUTS[node.category] ? node.category : "residential";
}

// Match an activity verb to a slot label so the agent appears at the right
// piece of furniture.
function activityToSlot(text) {
  const s = String(text || "");
  if (/睡|休息|床|sleep/i.test(s)) return "sleep";
  if (/咖啡|coffee|喝/i.test(s)) return "coffee";
  if (/吃|饭|餐|eat/i.test(s)) return "eat";
  if (/读|看书|book|read/i.test(s)) return "read";
  if (/看电视|tv/i.test(s)) return "watch";
  if (/上学|学|课|study/i.test(s)) return "study";
  if (/买|shop|购物/i.test(s)) return "shop";
  if (/工作|办公|work/i.test(s)) return "work";
  if (/诊|医|看病|consult/i.test(s)) return "consult";
  if (/锻炼|健身|跑步|gym|exercise|run|jog/i.test(s)) return "exercise";
  if (/瑜伽|冥想|yoga|meditat/i.test(s)) return "yoga";
  if (/散步|休憩|歇会|坐|rest|sit/i.test(s)) return "rest";
  return null;
}

// Architectural floor-plan style: white background, thick black walls, doors
// as gaps with arc, furniture as labelled minimal rectangles. Designed to read
// like an IKEA / real-estate floor plan rather than a fake pixel-art interior.
function renderIndoor(mapData, frame, selectedAgent) {
  const locId = state.indoorLocation;
  const nodes = mapNodes();
  const node = nodes.get(locId);
  const layoutKey = resolveLayoutKey(node);
  const category = (node && node.category) || "residential";
  const layout = INTERIOR_LAYOUTS[layoutKey] || INTERIOR_LAYOUTS.residential;

  const W = els.mapCanvas.width;
  const H = els.mapCanvas.height;

  // ── Outside the room: grass surround (Smallville look) ──
  if (layout.outdoor) {
    ctx.fillStyle = "#8ec07c"; ctx.fillRect(0, 0, W, H);
  } else {
    ctx.fillStyle = "#7cc36a"; ctx.fillRect(0, 0, W, H);
    drawIndoorGrassTexture(W, H);
  }

  // Room rect.
  const bannerH = 56;
  const padX = 84, padTop = bannerH + 30, padBot = 64;
  const roomX = padX, roomY = padTop;
  const roomW = W - padX * 2;
  const roomH = H - padTop - padBot;
  const wallThick = 14;
  const doorW = 64;
  const doorX = roomX + roomW / 2 - doorW / 2;

  // ── Floor (pixel planks or tiles) ──
  if (layout.outdoor) {
    ctx.fillStyle = layout.floor || "#7da35d";
    ctx.fillRect(roomX, roomY, roomW, roomH);
    drawIndoorGrassTexture(roomW, roomH, roomX, roomY);
  } else {
    drawPixelFloor(layout, roomX, roomY, roomW, roomH);
  }

  // ── Walls: chunky gray pixel band with a door gap in the bottom wall ──
  if (!layout.outdoor) {
    drawPixelWall(roomX - wallThick, roomY - wallThick, roomW + wallThick * 2, wallThick); // top
    drawPixelWall(roomX - wallThick, roomY, wallThick, roomH);                             // left
    drawPixelWall(roomX + roomW, roomY, wallThick, roomH);                                 // right
    // bottom wall split around the door
    drawPixelWall(roomX - wallThick, roomY + roomH, doorX - roomX + wallThick, wallThick);
    drawPixelWall(doorX + doorW, roomY + roomH, roomX + roomW + wallThick - (doorX + doorW), wallThick);
    // doormat in the gap
    ctx.fillStyle = "#7a5a3a"; ctx.fillRect(doorX, roomY + roomH - 2, doorW, wallThick + 2);
    ctx.fillStyle = "#8b6a44"; ctx.fillRect(doorX + 4, roomY + roomH, doorW - 8, wallThick - 4);

    // Windows: light-blue glass insets in the top wall.
    const winCount = Math.max(2, Math.floor(roomW / 300));
    const winW = 78;
    for (let i = 0; i < winCount; i += 1) {
      const wx = roomX + (roomW / (winCount + 1)) * (i + 1) - winW / 2;
      const wy = roomY - wallThick;
      ctx.fillStyle = "#bfe1f2"; ctx.fillRect(wx, wy + 2, winW, wallThick - 4);
      ctx.fillStyle = "#8fc4e0"; ctx.fillRect(wx, wy + 2, winW, 2);
      ctx.strokeStyle = "#6f757d"; ctx.lineWidth = 1;
      ctx.strokeRect(wx, wy + 2, winW, wallThick - 4);
      ctx.beginPath(); ctx.moveTo(wx + winW / 2, wy + 2); ctx.lineTo(wx + winW / 2, wy + wallThick - 2); ctx.stroke();
    }
  }

  // ── Furniture: pixel sprites ──
  const furnRects = [];
  layout.furniture.forEach((f) => {
    const fx = roomX + f.x * roomW;
    const fy = roomY + f.y * roomH;
    const fw = f.w * roomW;
    const fh = f.h * roomH;
    drawFurniture(f.kind, fx, fy, fw, fh, layout);
    furnRects.push({ ...f, px: fx, py: fy, pw: fw, ph: fh });
  });

  // ── Agents inside ──
  const here = frame.agents.filter((a) =>
    (a.target_location === locId || a.location === locId) &&
    (!a.travel || !["departed", "in_transit"].includes(a.travel.status))
  );
  const slotsUsed = new Set();
  here.forEach((a) => {
    const slot = activityToSlot(a.activity || a.scheduled_activity || a.action);
    const cands = furnRects.filter((r) => r.slot === slot && !slotsUsed.has(r.px + ":" + r.py));
    const open = cands[0] || furnRects.filter((r) => r.slot && !slotsUsed.has(r.px + ":" + r.py))[0];
    if (open) {
      slotsUsed.add(open.px + ":" + open.py);
      a._slotSpot = { x: open.px + open.pw / 2, y: open.py + open.ph / 2, slot: open.slot, kind: open.kind };
    } else {
      a._slotSpot = { x: roomX + roomW * (0.3 + (a.agent_id % 5) * 0.1), y: roomY + roomH * 0.78, slot: null, kind: null };
    }
  });

  const now = performance.now();
  const drawList = here.map((a) => ({
    agent: a,
    wander: updateIndoorWander(a, now, roomX, roomY - 0, roomW, roomH, 0),
  })).sort((a, b) => a.wander.y - b.wander.y);

  drawList.forEach(({ agent, wander }) => {
    // Lie down when the agent is sleeping/resting at a bed slot.
    const slot = agent._slotSpot && agent._slotSpot.slot;
    const lying = (slot === "sleep" || slot === "rest") && !wander.walking;
    drawIndoorCharacter(agent, wander.x, wander.y, lying, wander.dir || "front", wander.walking);
    agent._spriteX = wander.x; agent._spriteY = wander.y;
  });

  // ── Banner (pixel-styled rounded plate) ──
  const label = (node && node.label) || locId;
  ctx.fillStyle = "rgba(28,38,48,0.92)";
  roundedRect(W / 2 - 320, 12, 640, bannerH, 10); ctx.fill();
  ctx.fillStyle = "#f4ede0";
  ctx.font = "bold 22px 'Space Grotesk', sans-serif";
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  const lblIcon = layout.outdoor ? "🌳" : "🏠";
  ctx.fillText(`${lblIcon}  ${label}`, W / 2, 12 + bannerH / 2 - 7);
  ctx.font = "12px 'Manrope', sans-serif";
  ctx.fillStyle = "rgba(244, 237, 224, 0.72)";
  ctx.fillText(`${layoutKey} · ${category} · ${here.length} 人在场  ·  点「村落」返回`,
               W / 2, 12 + bannerH / 2 + 13);
  ctx.textAlign = "start"; ctx.textBaseline = "alphabetic";

  drawSpeechBubblesIndoor(here);
}

// Lightly scatter darker grass tufts + flowers over a green surface, matching
// the village grass treatment so indoor mode shares the pixel look.
function drawIndoorGrassTexture(w, h, ox = 0, oy = 0) {
  let seed = 1337;
  const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
  ctx.save();
  ctx.beginPath(); ctx.rect(ox, oy, w, h); ctx.clip();
  for (let i = 0; i < (w * h) / 5200; i++) {
    const x = ox + rnd() * w, y = oy + rnd() * h;
    const r = rnd();
    if (r < 0.7) { ctx.fillStyle = "rgba(90,150,75,0.5)"; ctx.fillRect(x, y, 4, 2); ctx.fillRect(x + 1, y - 2, 2, 2); }
    else if (r < 0.85) { ctx.fillStyle = "#e86b6b"; ctx.fillRect(x, y, 3, 3); }
    else { ctx.fillStyle = "#e8c84e"; ctx.fillRect(x, y, 3, 3); }
  }
  ctx.restore();
}

// Floor-plan furniture: thin black rectangle outline, light grey fill, simple
// symbol inside, label below. Every kind is drawn the same way for consistency
// — only the symbol and label change.
// Per-agent wandering inside the current room. Picks a random target near the
// activity slot, walks there, dwells, then picks another. Returns the current
// {x, y, dir, walking, atSlot, slot} for rendering.
function updateIndoorWander(agent, now, roomX, roomY, roomW, roomH, wallTop) {
  let s = state.indoorAgents.get(agent.agent_id);
  const spot = agent._slotSpot;
  const minX = roomX + 24, maxX = roomX + roomW - 24;
  const minY = roomY + wallTop + 24, maxY = roomY + roomH - 24;
  if (!s || s.loc !== state.indoorLocation) {
    // Fresh — start exactly at the slot (avoids initial wide gallop).
    s = {
      loc: state.indoorLocation,
      x: spot.x, y: spot.y,
      targetX: spot.x, targetY: spot.y,
      dir: "front", walking: false, atSlot: true,
      slot: spot.slot, holdUntil: now + 2000 + Math.random() * 3000,
    };
    state.indoorAgents.set(agent.agent_id, s);
    return s;
  }
  // If we have a slot target distinct from current, walk there first.
  const dxSlot = spot.x - s.targetX;
  const dySlot = spot.y - s.targetY;
  if (Math.abs(dxSlot) + Math.abs(dySlot) > 4 && !s.walking) {
    s.targetX = spot.x; s.targetY = spot.y;
    s.atSlot = false;
    s.slot = spot.slot;
  }
  // When holding at the slot, occasionally pick a brief wander target near it.
  if (!s.walking && now > s.holdUntil) {
    const wanderRadius = 80;
    s.targetX = clamp(spot.x + (Math.random() - 0.5) * wanderRadius, minX, maxX);
    s.targetY = clamp(spot.y + (Math.random() - 0.5) * wanderRadius * 0.6, minY, maxY);
    s.atSlot = false;
    s.walking = true;
  }
  // Walk toward target.
  const dx = s.targetX - s.x;
  const dy = s.targetY - s.y;
  const dist = Math.hypot(dx, dy);
  if (dist < 2) {
    s.x = s.targetX; s.y = s.targetY;
    s.walking = false;
    // Mark as "at slot" only when target equals slot center (within tol).
    s.atSlot = Math.hypot(spot.x - s.x, spot.y - s.y) < 6;
    if (s.atSlot) {
      s.holdUntil = now + 3000 + Math.random() * 5000;  // sit at slot longer
    } else {
      s.holdUntil = now + 800 + Math.random() * 1200;   // brief pause then return to slot
    }
  } else {
    s.walking = true;
    // Step size scales with frame delta — assume ~16ms; speed ~80 px/s.
    const stepBase = 80 / 60;
    const step = Math.min(dist, stepBase);
    s.x += (dx / dist) * step;
    s.y += (dy / dist) * step;
    if (Math.abs(dx) > Math.abs(dy)) s.dir = dx > 0 ? "right" : "left";
    else s.dir = dy > 0 ? "front" : "back";
  }
  return s;
}

// Pixel plank / tile floor fill, Smallville-style. Warm wood planks for
// living spaces, light tiles for clinical / tiled rooms.
function drawPixelFloor(layout, roomX, roomY, roomW, roomH) {
  const tiled = layout.wallpaper === "tile" || /e8eef0|b8b8b8/.test(layout.floor || "");
  const base = layout.floor || "#e8d8b8";
  ctx.fillStyle = base;
  ctx.fillRect(roomX, roomY, roomW, roomH);
  ctx.save();
  ctx.beginPath(); ctx.rect(roomX, roomY, roomW, roomH); ctx.clip();
  if (tiled) {
    // checker tiles
    const t = 26;
    for (let yy = roomY, ry = 0; yy < roomY + roomH; yy += t, ry++) {
      for (let xx = roomX, rx = 0; xx < roomX + roomW; xx += t, rx++) {
        if ((rx + ry) % 2 === 0) { ctx.fillStyle = "rgba(255,255,255,0.05)"; ctx.fillRect(xx, yy, t, t); }
      }
    }
    ctx.strokeStyle = "rgba(40,55,70,0.07)"; ctx.lineWidth = 1;
    for (let xx = roomX; xx <= roomX + roomW; xx += t) { ctx.beginPath(); ctx.moveTo(xx, roomY); ctx.lineTo(xx, roomY + roomH); ctx.stroke(); }
    for (let yy = roomY; yy <= roomY + roomH; yy += t) { ctx.beginPath(); ctx.moveTo(roomX, yy); ctx.lineTo(roomX + roomW, yy); ctx.stroke(); }
  } else {
    // horizontal wood planks with staggered seams
    const ph = 22;
    for (let yy = roomY, row = 0; yy < roomY + roomH; yy += ph, row++) {
      // alternate plank shade
      ctx.fillStyle = row % 2 === 0 ? "rgba(0,0,0,0.0)" : "rgba(120,80,40,0.06)";
      ctx.fillRect(roomX, yy, roomW, ph);
      // plank seam
      ctx.strokeStyle = "rgba(80,50,20,0.18)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(roomX, yy); ctx.lineTo(roomX + roomW, yy); ctx.stroke();
      // vertical board breaks, staggered per row
      const off = (row % 2) * 70;
      ctx.strokeStyle = "rgba(80,50,20,0.10)";
      for (let xx = roomX + off; xx < roomX + roomW; xx += 140) {
        ctx.beginPath(); ctx.moveTo(xx, yy); ctx.lineTo(xx, yy + ph); ctx.stroke();
      }
    }
  }
  ctx.restore();
}

// Thick gray pixel wall band (top-down cutaway) with a chunky inner highlight.
function drawPixelWall(x, y, w, h) {
  ctx.fillStyle = "#9aa0a8"; ctx.fillRect(x, y, w, h);          // wall body
  ctx.fillStyle = "#c4c9cf"; ctx.fillRect(x, y, w, Math.min(3, h)); // top highlight
  ctx.fillStyle = "#6f757d"; ctx.fillRect(x, y + h - Math.min(3, h), w, Math.min(3, h)); // bottom shade
}

function drawWallpaper(layout, roomX, roomY, roomW, wallTop) {
  if (!layout.wallpaper || layout.outdoor) return;
  ctx.save();
  ctx.beginPath();
  ctx.rect(roomX, roomY, roomW, wallTop - 6);
  ctx.clip();
  switch (layout.wallpaper) {
    case "stripe":
      ctx.strokeStyle = "rgba(255,255,255,0.10)"; ctx.lineWidth = 6;
      for (let x = roomX; x < roomX + roomW; x += 18) {
        ctx.beginPath(); ctx.moveTo(x, roomY); ctx.lineTo(x, roomY + wallTop); ctx.stroke();
      }
      break;
    case "brick":
      ctx.strokeStyle = "rgba(0,0,0,0.16)"; ctx.lineWidth = 1;
      const bh = 14, bw = 36;
      for (let row = 0, y = roomY; y < roomY + wallTop; row += 1, y += bh) {
        const off = row % 2 === 0 ? 0 : bw / 2;
        ctx.beginPath(); ctx.moveTo(roomX, y); ctx.lineTo(roomX + roomW, y); ctx.stroke();
        for (let x = roomX + off; x < roomX + roomW; x += bw) {
          ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x, y + bh); ctx.stroke();
        }
      }
      break;
    case "tile":
      ctx.strokeStyle = "rgba(255,255,255,0.14)"; ctx.lineWidth = 1;
      for (let x = roomX; x < roomX + roomW; x += 24) {
        ctx.beginPath(); ctx.moveTo(x, roomY); ctx.lineTo(x, roomY + wallTop); ctx.stroke();
      }
      for (let y = roomY; y < roomY + wallTop; y += 24) {
        ctx.beginPath(); ctx.moveTo(roomX, y); ctx.lineTo(roomX + roomW, y); ctx.stroke();
      }
      break;
  }
  ctx.restore();
}

function drawFurniture(kind, x, y, w, h, layout) {
  ctx.fillStyle = layout.accent;
  switch (kind) {
    case "bed": {
      ctx.fillStyle = "#8b5a2b"; ctx.fillRect(x, y, w, h);                 // frame
      ctx.fillStyle = "#fff5d6"; ctx.fillRect(x + 4, y + 4, w - 8, h - 8); // mattress
      ctx.fillStyle = "#d96b4e"; ctx.fillRect(x + 6, y + 6, w - 12, h * 0.30); // blanket
      ctx.fillStyle = "#fff8e0"; ctx.fillRect(x + 8, y + h - 28, w - 16, 16); // pillow
      ctx.strokeStyle = "rgba(0,0,0,0.18)"; ctx.lineWidth = 1; ctx.strokeRect(x, y, w, h);
      return;
    }
    case "table": {
      ctx.fillStyle = "#9c6a3d"; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#bd8654"; ctx.fillRect(x + 3, y + 3, w - 6, h - 6);
      ctx.strokeStyle = "rgba(0,0,0,0.2)"; ctx.strokeRect(x, y, w, h);
      return;
    }
    case "chair": {
      ctx.fillStyle = "#7d5331"; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#a47148"; ctx.fillRect(x + 2, y + 2, w - 4, h * 0.55);
      return;
    }
    case "bookshelf": {
      ctx.fillStyle = "#5e3a1c"; ctx.fillRect(x, y - 10, w, h + 10);
      for (let i = 0; i < Math.floor(w / 8); i += 1) {
        ctx.fillStyle = ["#c84c61", "#5a67a8", "#0d8a73", "#dc7d2d", "#9a4d38"][i % 5];
        ctx.fillRect(x + 2 + i * 8, y - 8, 6, h + 6);
      }
      return;
    }
    case "tv": {
      ctx.fillStyle = "#1c1c1c"; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#4ea2d4"; ctx.fillRect(x + 3, y + 3, w - 6, h - 8);
      ctx.fillStyle = "#444"; ctx.fillRect(x + w / 2 - 6, y + h - 4, 12, 4);
      return;
    }
    case "rug": {
      ctx.fillStyle = "#c84c61"; ctx.fillRect(x, y, w, h);
      ctx.strokeStyle = "#7d2a3a"; ctx.lineWidth = 4; ctx.strokeRect(x + 4, y + 4, w - 8, h - 8);
      return;
    }
    case "counter": {
      ctx.fillStyle = "#6e4a2d"; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#a07853"; ctx.fillRect(x, y, w, 6);
      return;
    }
    case "coffee_machine": {
      ctx.fillStyle = "#3a3a3a"; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#dc7d2d"; ctx.fillRect(x + w * 0.2, y + h * 0.3, w * 0.6, h * 0.4);
      ctx.fillStyle = "#fff"; ctx.fillRect(x + w * 0.35, y + h * 0.65, w * 0.30, h * 0.20);
      return;
    }
    case "chalkboard": {
      ctx.fillStyle = "#3a4d3a"; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#fff"; ctx.font = `${Math.floor(h * 0.45)}px 'VT323', monospace`;
      ctx.fillText("E = mc²", x + 12, y + h * 0.7);
      return;
    }
    case "desk": {
      ctx.fillStyle = "#8b5a2b"; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#c1965f"; ctx.fillRect(x + 2, y + 2, w - 4, h * 0.4);
      // book/paper on desk
      ctx.fillStyle = "#fff8e0"; ctx.fillRect(x + 4, y + 6, w * 0.3, h * 0.3);
      return;
    }
    case "shelf": {
      ctx.fillStyle = "#6e4a2d"; ctx.fillRect(x, y, w, h);
      for (let row = 0; row < 4; row += 1) {
        ctx.fillStyle = ["#c84c61", "#5a67a8", "#dc7d2d", "#0d8a73"][row];
        ctx.fillRect(x + 4, y + 8 + row * (h / 4), w - 8, h / 4 - 4);
      }
      return;
    }
    case "tree_big": {
      ctx.fillStyle = "#5a3a1c"; ctx.fillRect(x + w / 2 - 4, y + h * 0.6, 8, h * 0.4);
      ctx.fillStyle = "#3f7a3a"; ctx.beginPath(); ctx.arc(x + w / 2, y + h * 0.4, w * 0.6, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#6aa86d"; ctx.beginPath(); ctx.arc(x + w / 2 - 6, y + h * 0.35, w * 0.45, 0, Math.PI * 2); ctx.fill();
      return;
    }
    case "fountain": {
      ctx.fillStyle = "#9aa6b0"; ctx.beginPath(); ctx.ellipse(x + w / 2, y + h / 2, w / 2, h / 2, 0, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#7fb1cf"; ctx.beginPath(); ctx.ellipse(x + w / 2, y + h / 2, w / 2.8, h / 2.8, 0, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#a8d4ee"; ctx.beginPath(); ctx.arc(x + w / 2, y + h / 2, w / 8, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.fillRect(x + w / 2 - 1, y + h * 0.1, 2, h * 0.4);
      return;
    }
    case "bench": {
      ctx.fillStyle = "#7d5331"; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#a47148"; ctx.fillRect(x, y - h * 1.2, w, h * 1.2);
      return;
    }
    case "flowerbed": {
      ctx.fillStyle = "#6a4220"; ctx.fillRect(x, y, w, h);
      for (let i = 0; i < Math.floor(w / 10); i += 1) {
        ctx.fillStyle = ["#c84c61", "#dc7d2d", "#9b8d69", "#fff"][i % 4];
        ctx.beginPath(); ctx.arc(x + 6 + i * 10, y + h / 2, 3, 0, Math.PI * 2); ctx.fill();
      }
      return;
    }
    case "treadmill": {
      ctx.fillStyle = "#3a3a3a"; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#888"; ctx.fillRect(x + 2, y + 4, w - 4, h * 0.55);
      ctx.fillStyle = "#222"; ctx.fillRect(x + 4, y + 6, w - 8, h * 0.45);
      ctx.fillStyle = "#dc7d2d"; ctx.fillRect(x, y + h - 8, w, 4);
      return;
    }
    case "weightrack": {
      ctx.fillStyle = "#444"; ctx.fillRect(x, y, w, h);
      for (let i = 0; i < 4; i += 1) {
        ctx.fillStyle = "#222"; ctx.fillRect(x + 4 + i * (w / 4 - 2), y + 4, 14, h - 8);
        ctx.fillStyle = "#dc7d2d"; ctx.fillRect(x + 4 + i * (w / 4 - 2), y + 4, 14, 4);
      }
      return;
    }
    case "mat": {
      ctx.fillStyle = "#5a67a8"; ctx.fillRect(x, y, w, h);
      ctx.strokeStyle = "#3a4878"; ctx.lineWidth = 2; ctx.strokeRect(x + 2, y + 2, w - 4, h - 4);
      return;
    }
    case "nightstand": {
      ctx.fillStyle = "#7d5331"; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#a47148"; ctx.fillRect(x + 2, y + 2, w - 4, h - 4);
      // drawer pull
      ctx.fillStyle = "#4a3017"; ctx.fillRect(x + w / 2 - 3, y + h / 2 - 1, 6, 2);
      return;
    }
    case "lamp": {
      // small lamp on top of furniture (base + shade)
      ctx.fillStyle = "#7d5331"; ctx.fillRect(x + w / 2 - 2, y + h - 8, 4, 8);
      ctx.fillStyle = "#f1c97a"; // shade
      ctx.beginPath();
      ctx.moveTo(x + w / 2 - w * 0.35, y + h - 8);
      ctx.lineTo(x + w / 2 + w * 0.35, y + h - 8);
      ctx.lineTo(x + w / 2 + w * 0.25, y + 2);
      ctx.lineTo(x + w / 2 - w * 0.25, y + 2);
      ctx.closePath(); ctx.fill();
      // glow
      ctx.fillStyle = "rgba(255, 220, 120, 0.25)";
      ctx.beginPath(); ctx.arc(x + w / 2, y + h + 4, w * 0.9, 0, Math.PI * 2); ctx.fill();
      return;
    }
    case "plant_pot": {
      ctx.fillStyle = "#a05a3a"; // pot
      ctx.beginPath();
      ctx.moveTo(x + 2, y + h * 0.55);
      ctx.lineTo(x + w - 2, y + h * 0.55);
      ctx.lineTo(x + w - 5, y + h);
      ctx.lineTo(x + 5, y + h);
      ctx.closePath(); ctx.fill();
      ctx.fillStyle = "#3f7a3a"; // leaves
      ctx.beginPath(); ctx.arc(x + w / 2, y + h * 0.35, w * 0.45, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#6aa86d";
      ctx.beginPath(); ctx.arc(x + w * 0.35, y + h * 0.30, w * 0.30, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.arc(x + w * 0.70, y + h * 0.35, w * 0.28, 0, Math.PI * 2); ctx.fill();
      return;
    }
    case "picture_frame": {
      // wall-mounted picture (drawn on top wall)
      ctx.fillStyle = "#5e3a1c"; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#fff8e0"; ctx.fillRect(x + 2, y + 2, w - 4, h - 4);
      // tiny scene inside
      ctx.fillStyle = "#a8d4ee"; ctx.fillRect(x + 4, y + 4, w - 8, (h - 8) * 0.55);
      ctx.fillStyle = "#9bc56d"; ctx.fillRect(x + 4, y + 4 + (h - 8) * 0.55, w - 8, (h - 8) * 0.45);
      return;
    }
    case "area_rug": {
      // bigger, more decorative rug with pattern
      ctx.fillStyle = "#a04a4a"; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#7d2a3a"; ctx.fillRect(x + 4, y + 4, w - 8, h - 8);
      ctx.strokeStyle = "#f1c97a"; ctx.lineWidth = 2;
      ctx.strokeRect(x + 8, y + 8, w - 16, h - 16);
      // diamond center
      ctx.fillStyle = "#f1c97a";
      ctx.beginPath();
      ctx.moveTo(x + w / 2, y + h / 2 - 6);
      ctx.lineTo(x + w / 2 + 6, y + h / 2);
      ctx.lineTo(x + w / 2, y + h / 2 + 6);
      ctx.lineTo(x + w / 2 - 6, y + h / 2);
      ctx.closePath(); ctx.fill();
      return;
    }
    case "kitchen_unit": {
      // countertop + sink + cabinets
      ctx.fillStyle = "#7d5331"; ctx.fillRect(x, y + h * 0.25, w, h * 0.75);
      ctx.fillStyle = "#d4b97e"; ctx.fillRect(x, y + h * 0.20, w, 5); // counter
      ctx.fillStyle = "#9aa6b0"; ctx.fillRect(x + w * 0.55, y + h * 0.05, w * 0.40, h * 0.20); // sink
      ctx.fillStyle = "#3a3a3a"; ctx.fillRect(x + w * 0.05, y + h * 0.05, w * 0.18, h * 0.20); // stove
      ctx.fillStyle = "#5e3a1c";
      for (let i = 0; i < 3; i += 1) ctx.fillRect(x + 4 + i * (w / 3), y + h * 0.55, w / 3 - 8, h * 0.40);
      return;
    }
    case "fridge": {
      ctx.fillStyle = "#e6e6e0"; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#b8b8b0"; ctx.fillRect(x + w - 6, y + 4, 4, h - 8); // handle bar
      ctx.fillStyle = "#888"; ctx.fillRect(x + 2, y + h * 0.45, w - 4, 2); // divider
      return;
    }
    case "sofa": {
      ctx.fillStyle = "#5a67a8"; ctx.fillRect(x, y + h * 0.30, w, h * 0.70);
      ctx.fillStyle = "#7488c4";
      ctx.fillRect(x + 4, y + h * 0.05, w * 0.28, h * 0.40); // left cushion back
      ctx.fillRect(x + w * 0.36, y + h * 0.05, w * 0.28, h * 0.40);
      ctx.fillRect(x + w * 0.68, y + h * 0.05, w * 0.28, h * 0.40);
      // armrests
      ctx.fillStyle = "#3a4878"; ctx.fillRect(x, y + h * 0.30, 6, h * 0.55);
      ctx.fillRect(x + w - 6, y + h * 0.30, 6, h * 0.55);
      return;
    }
    case "coffee_table": {
      ctx.fillStyle = "#5e3a1c"; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#8b5a2b"; ctx.fillRect(x + 2, y + 2, w - 4, h - 4);
      // cup on table
      ctx.fillStyle = "#fff"; ctx.fillRect(x + w / 2 - 4, y + h / 2 - 3, 8, 6);
      ctx.fillStyle = "#3a2818"; ctx.fillRect(x + w / 2 - 3, y + h / 2 - 2, 6, 3);
      return;
    }
    case "podium": {
      ctx.fillStyle = "#8b5a2b"; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#a87042"; ctx.fillRect(x + 2, y + 2, w - 4, h * 0.60);
      ctx.fillStyle = "#fff8e0"; ctx.fillRect(x + 6, y + h * 0.25, w - 12, h * 0.15);
      return;
    }
    case "checkout": {
      // commerce checkout counter with register
      ctx.fillStyle = "#7d5331"; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#a07853"; ctx.fillRect(x, y, w, 6);
      ctx.fillStyle = "#3a3a3a"; ctx.fillRect(x + w * 0.10, y + 6, w * 0.30, h * 0.55);
      ctx.fillStyle = "#888"; ctx.fillRect(x + w * 0.13, y + 9, w * 0.24, h * 0.20);
      return;
    }
    default:
      ctx.fillStyle = layout.accent;
      ctx.fillRect(x, y, w, h);
  }
}

function drawIndoorCharacter(agent, px, py, lying, dir = "front", walking = false) {
  const tint = agentColor(agent.agent_id);
  const charW = 32, charH = 42;
  ctx.fillStyle = "rgba(0,0,0,0.25)";
  ctx.beginPath();
  ctx.ellipse(px, py + charH / 2, charW / 2.2, 5, 0, 0, Math.PI * 2);
  ctx.fill();
  const selected = agent.agent_id === state.selectedAgentId;
  if (selected) {
    ctx.strokeStyle = "rgba(255, 220, 120, 0.95)";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.ellipse(px, py + charH / 2, charW / 1.7, 8, 0, 0, Math.PI * 2);
    ctx.stroke();
  }
  if (lying) {
    ctx.save();
    ctx.translate(px, py);
    ctx.rotate(-Math.PI / 2);
    drawCharacterSprite(agent, 0, 0, charW, charH, "front", false, tint);
    ctx.restore();
  } else {
    drawCharacterSprite(agent, px, py, charW, charH, dir, walking, tint);
  }
}

function drawCharacterSprite(agent, px, py, w, h, dir, walking, tint) {
  const frameKey = walking
    ? `misa-${dir}-walk.00${Math.floor(Date.now() / 220) % 4}`
    : `misa-${dir}`;
  if (imgReady.misa && misaFrames && misaFrames[frameKey]) {
    const tinted = getTintedCharacter(agent.agent_id, tint, frameKey);
    if (tinted) {
      ctx.drawImage(tinted, px - w / 2, py - h / 2, w, h);
      return;
    }
  }
  // Fallback humanoid
  ctx.fillStyle = tint;
  ctx.beginPath(); ctx.arc(px, py - 6, 8, 0, Math.PI * 2); ctx.fill();
  ctx.fillRect(px - 8, py, 16, 14);
}

// Activity-specific animated prop drawn next to the character. Each kind
// gets its own motion (bounce, rise-fade, jitter) so different activities
// read distinctly even when the underlying sprite is the same humanoid.
function drawActivityProp(agent, px, py) {
  const act = String(agent.action || agent.activity || agent.scheduled_activity || "");
  const t = Date.now();
  const phase = (t / 1000 + agent.agent_id * 0.4) % 1; // 0..1 cycle each second
  ctx.save();
  ctx.font = "20px sans-serif";

  if (/睡|sleep/i.test(act)) {
    // "Zzz" rising from head, fading
    ctx.globalAlpha = 1 - phase;
    ctx.fillText("💤", px - 6, py - 22 - phase * 10);
  } else if (/咖啡|coffee/i.test(act)) {
    // Coffee cup in hand, steam wisp drifting up
    ctx.fillText("☕", px + 14, py + 4);
    ctx.globalAlpha = 0.6 - phase * 0.6;
    ctx.font = "14px sans-serif";
    ctx.fillText("·", px + 20, py - 4 - phase * 8);
    ctx.fillText("·", px + 22, py - 10 - phase * 6);
  } else if (/吃|饭|餐|eat/i.test(act)) {
    // Chopsticks/fork move up/down like chewing
    const dy = Math.sin(t / 200) * 4;
    ctx.fillText("🍽️", px + 14, py + 6 + dy);
  } else if (/读|看书|book|read/i.test(act)) {
    // Book flips: alternate emoji between two states
    ctx.fillText((t / 800) % 2 < 1 ? "📖" : "📗", px + 14, py + 6);
  } else if (/学|课|study/i.test(act)) {
    ctx.fillText("📚", px + 14, py + 6);
    // Pencil bobbing
    ctx.globalAlpha = 0.85;
    ctx.font = "12px sans-serif";
    ctx.fillText("✏️", px + 12, py + 18 + Math.sin(t / 180) * 2);
  } else if (/工作|办公|work|电脑/i.test(act)) {
    // Keyboard "typing" — laptop emoji + tiny key jitter
    const dx = Math.sin(t / 100) * 1;
    ctx.fillText("💻", px + 14 + dx, py + 6);
    ctx.globalAlpha = 0.7;
    ctx.font = "10px sans-serif";
    ctx.fillText("·", px + 20, py - 4 - (phase * 6));
  } else if (/手机|刷/i.test(act)) {
    const dy = Math.sin(t / 220) * 1.5;
    ctx.fillText("📱", px + 14, py + 6 + dy);
  } else if (/看电视|tv/i.test(act)) {
    ctx.fillText("📺", px + 14, py + 6);
  } else if (/购物|买|shop/i.test(act)) {
    const dy = Math.abs(Math.sin(t / 300)) * 3;
    ctx.fillText("🛍️", px + 14, py + 6 - dy);
  } else if (/锻炼|健身|跑步|gym|exercise|run|jog/i.test(act)) {
    ctx.fillText("💪", px + 14, py + 6 + Math.sin(t / 150) * 3);
  } else if (/瑜伽|冥想|yoga|meditat/i.test(act)) {
    ctx.fillText("🧘", px + 14, py + 6);
    ctx.globalAlpha = 0.7 - phase * 0.7;
    ctx.font = "12px sans-serif";
    ctx.fillText("✨", px + 22, py - 4 - phase * 8);
  } else if (/聊天|交谈|talk|chat/i.test(act)) {
    ctx.fillText((t / 400) % 2 < 1 ? "💬" : "💭", px + 14, py - 6);
  } else if (/散步|walk|stroll/i.test(act)) {
    // Walking footprint emoji bobbing
    ctx.fillText("👣", px + 14, py + 12 + Math.sin(t / 250) * 2);
  } else if (/拖延|刷会儿/i.test(act)) {
    const dy = Math.sin(t / 220) * 1.5;
    ctx.fillText("📱", px + 14, py + 6 + dy);
  }
  ctx.restore();
}

function drawSpeechBubblesIndoor(agents) {
  ctx.font = "13px 'Manrope', sans-serif";
  agents.forEach((a) => {
    const initials = nameInitials(a.name);
    const emoji = activityToEmoji(a.activity || a.scheduled_activity || a.action);
    const text = `${initials}: ${emoji}`;
    const tw = ctx.measureText(text).width + 16;
    const th = 22;
    const bx = a._spriteX - tw / 2;
    const by = a._spriteY - 40;
    ctx.fillStyle = "rgba(255,255,255,0.96)";
    ctx.strokeStyle = "rgba(40, 60, 60, 0.85)";
    ctx.lineWidth = 1.5;
    roundedRect(bx, by, tw, th, 5); ctx.fill(); ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(a._spriteX - 4, by + th);
    ctx.lineTo(a._spriteX, by + th + 6);
    ctx.lineTo(a._spriteX + 4, by + th);
    ctx.closePath();
    ctx.fillStyle = "rgba(255,255,255,0.96)"; ctx.fill();
    ctx.strokeStyle = "rgba(40, 60, 60, 0.85)"; ctx.stroke();
    ctx.fillStyle = "#1e2c2c";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(text, bx + tw / 2, by + th / 2 + 1);
    ctx.textAlign = "start"; ctx.textBaseline = "alphabetic";
  });
}

// ───────── scene cards ─────────
function renderSceneCards(frame) {
  els.sceneCardsLayer.innerHTML = "";
  if (!state.showCards) return;
  // Pick up to 4 "scenes" — distinct locations with the most agents or most
  // narratively interesting activity (perception non-empty).
  const byLoc = new Map();
  frame.agents.forEach((a) => {
    const loc = a.target_location || a.location || "?";
    if (!byLoc.has(loc)) byLoc.set(loc, []);
    byLoc.get(loc).push(a);
  });
  const scenes = [...byLoc.entries()]
    .map(([loc, agents]) => ({
      loc, agents,
      score: agents.length * 2 + agents.reduce((s, a) => s + ((a.perception || "").length > 0 ? 1 : 0), 0),
    }))
    .sort((a, b) => b.score - a.score)
    .slice(0, 4);

  scenes.forEach((s, i) => {
    const a = s.agents[0];
    const title = sceneTitle(a);
    const dialog = (a.perception || a.plan || a.reflection || "").slice(0, 80);
    const div = document.createElement("div");
    div.className = `scene-card scene-pos-${i}`;
    div.innerHTML = `
      <div class="scene-card-head">
        <span class="scene-card-title">${escapeHtml(title)}</span>
      </div>
      <div class="scene-card-body">
        <div class="scene-card-agents">${s.agents.slice(0, 3).map((ag) => `<span class="scene-agent" style="background:${agentColor(ag.agent_id)}">${escapeHtml(nameInitials(ag.name))}</span>`).join("")}</div>
        <div class="scene-card-loc">${escapeHtml(s.loc)}</div>
      </div>
      ${dialog ? `<div class="scene-card-dialog">[${escapeHtml(a.name)}] ${escapeHtml(dialog)}</div>` : ""}
    `;
    els.sceneCardsLayer.appendChild(div);
  });
}

function sceneTitle(agent) {
  const act = agent.activity || agent.scheduled_activity || agent.action || "活动";
  const loc = agent.target_location || agent.location || "";
  const emoji = activityToEmoji(act);
  if (loc) return `${emoji} 在${loc}${act}`;
  return `${emoji} ${act}`;
}

// ───────── helpers ─────────
// Resolve a node id → its drawn building's center. We use the visual building
// position from the layout (district-cell coords), not the raw tile_x/tile_y,
// since the new layout completely reprojects nodes.
function nodeDisplayCenter(nodeId, nodes) {
  if (!nodeId) return null;
  if (state.bldgLayout && state.bldgLayout.has(nodeId)) {
    const b = state.bldgLayout.get(nodeId);
    return { x: b.cx, y: b.cy };
  }
  // Fallback: raw tile position (used for indoor + before layout ready).
  const n = nodes && nodes.get && nodes.get(nodeId);
  if (!n) return null;
  const m = state.renderMetrics; if (!m) return null;
  return {
    x: m.offsetX + n.tile_x * m.scale + m.scale / 2,
    y: m.offsetY + n.tile_y * m.scale + m.scale / 2,
  };
}

function agentPosAtFrame(agentId, frameIdx) {
  const f = state.trace && state.trace.frames && state.trace.frames[frameIdx];
  if (!f) return null;
  const a = f.agents.find((x) => x.agent_id === agentId);
  if (!a) return null;
  const nodes = mapNodes();
  const start = nodeDisplayCenter(a.resolved_location, nodes) || nodeDisplayCenter(a.target_location, nodes);
  if (!start) return null;
  let end = nodeDisplayCenter(a.target_location, nodes) || start;
  let progress = 1;
  if (a.travel && ["departed", "in_transit"].includes(a.travel.status)) {
    progress = Number(a.travel.progress || 0);
  } else {
    end = start;
  }
  return { x: start.x + (end.x - start.x) * progress, y: start.y + (end.y - start.y) * progress };
}

function agentPixelPosition(agent, nodes) {
  const m = state.renderMetrics; if (!m) return null;
  if (state.continuous && state.trace && state.trace.frames) {
    const total = state.trace.frames.length;
    const cur = agentPosAtFrame(agent.agent_id, state.frameIndex);
    const nextIdx = Math.min(state.frameIndex + 1, total - 1);
    const next = agentPosAtFrame(agent.agent_id, nextIdx) || cur;
    if (cur) {
      const frac = state.frameFloat - state.frameIndex;
      return { x: cur.x + (next.x - cur.x) * frac, y: cur.y + (next.y - cur.y) * frac };
    }
  }

  const start = nodeDisplayCenter(agent.resolved_location, nodes) || nodeDisplayCenter(agent.target_location, nodes);
  if (!start) return null;
  let end = nodeDisplayCenter(agent.target_location, nodes) || start;
  let progress = 1;
  if (agent.travel && ["departed", "in_transit"].includes(agent.travel.status)) {
    progress = Number(agent.travel.progress || 0);
    if (state.playing && state.frameEnteredAt) {
      const elapsed = (performance.now() - state.frameEnteredAt) / (FRAME_DWELL_MS / Math.max(0.5, state.speed));
      progress = clamp(progress + elapsed * 0.05, 0, 1);
    }
  } else {
    end = start;
  }
  let x = start.x + (end.x - start.x) * progress;
  let y = start.y + (end.y - start.y) * progress;

  if (state.playing && state.frameEnteredAt) {
    const prevPos = (state.prevAgentPositions || {})[agent.agent_id];
    if (prevPos) {
      const t = clamp((performance.now() - state.frameEnteredAt) / 700, 0, 1);
      const ease = t * t * (3 - 2 * t);
      x = prevPos.x + (x - prevPos.x) * ease;
      y = prevPos.y + (y - prevPos.y) * ease;
    }
  }
  return { x, y };
}

function onCanvasClick(event) {
  if (state._suppressNextClick) return;
  const frame = getCurrentFrame(); if (!frame) return;
  const rect = els.mapCanvas.getBoundingClientRect();
  const sx = (event.clientX - rect.left) * (els.mapCanvas.width / rect.width);
  const sy = (event.clientY - rect.top) * (els.mapCanvas.height / rect.height);
  // In village mode `_spriteX/Y` and building rects are in world space, so
  // translate the click before hit-testing.
  const { x, y } = state.viewMode === "village" ? screenToWorld(sx, sy) : { x: sx, y: sy };
  // 1. Agent hit-test.
  const hitRadius = state.viewMode === "village" ? 32 / state.zoom : 32;
  let best = null;
  frame.agents.forEach((a) => {
    if (!a._spriteX) return;
    const d = Math.hypot(x - a._spriteX, y - a._spriteY);
    if (!best || d < best.dist) best = { id: a.agent_id, dist: d };
  });
  if (best && best.dist < hitRadius) {
    state.selectedAgentId = best.id;
    state.viewModeManual = false;
    render(); return;
  }
  // 2. Village mode: clicking a building enters indoor mode for that location.
  if (state.viewMode === "village" && state.bldgLayout) {
    for (const b of state.bldgLayout.values()) {
      if (x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h) {
        setViewMode("indoor", true, b.node.id);
        return;
      }
    }
  }
}

function onCanvasMouseMove(event) {
  if (state.dragging) return;
  const frame = getCurrentFrame(); if (!frame) { els.mapCanvas.style.cursor = "default"; return; }
  const rect = els.mapCanvas.getBoundingClientRect();
  const sx = (event.clientX - rect.left) * (els.mapCanvas.width / rect.width);
  const sy = (event.clientY - rect.top) * (els.mapCanvas.height / rect.height);
  const { x, y } = state.viewMode === "village" ? screenToWorld(sx, sy) : { x: sx, y: sy };
  const hitRadius = state.viewMode === "village" ? 32 / state.zoom : 32;
  const hitAgent = frame.agents.some((a) => a._spriteX && Math.hypot(x - a._spriteX, y - a._spriteY) < hitRadius);
  let hitBldg = false;
  if (!hitAgent && state.viewMode === "village" && state.bldgLayout) {
    for (const b of state.bldgLayout.values()) {
      if (x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h) { hitBldg = true; break; }
    }
  }
  if (hitAgent || hitBldg) els.mapCanvas.style.cursor = "pointer";
  else if (state.viewMode === "village" && state.zoom > 1.001) els.mapCanvas.style.cursor = "grab";
  else els.mapCanvas.style.cursor = "default";
}

function showError(error) {
  stopPlayback();
  state.trace = null;
  renderEmptyState();
  els.statusBadge.textContent = `加载失败: ${error.message}`;
  els.statusBadge.className = "badge badge-error";
}

function uniqueLocations(agentFrames) {
  return [...new Set(agentFrames.map((a) => a.target_location || a.location).filter(Boolean))];
}
function agentColor(agentId) { return AGENT_COLORS[Math.abs(Number(agentId || 0)) % AGENT_COLORS.length]; }
function shortLabel(text) {
  const s = String(text || "");
  return s.length > 12 ? `${s.slice(0, 11)}…` : s;
}
function nameInitials(name) {
  const s = String(name || "").trim();
  if (!s) return "?";
  // For Chinese names, take last 2 chars; for ascii, first 2 letters.
  if (/[一-龥]/.test(s)) return s.slice(-2);
  const parts = s.split(/\s+/);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return s.slice(0, 2).toUpperCase();
}
function fmt(v) { return Number(v || 0).toFixed(1); }
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
function escapeHtml(v) {
  return String(v || "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}
function roundedRect(x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y); ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r); ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h); ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}
function mulberry32(a) {
  return function () {
    let t = (a += 0x6D2B79F5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

init();
