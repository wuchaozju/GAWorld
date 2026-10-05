// 同居模式 (Roommate Mode) — front-end controller (v2: pixel canvas + auto-play).
//
// Long-lived game. Server keeps the session in memory; front-end polls and
// renders. Key behaviours:
//
//   POST /api/games/roommate/start      → { ...session } (zero model calls)
//   POST /api/games/roommate/tick       → advance N ticks (cost = interactions)
//   POST /api/games/roommate/end        → mark finished
//
// Render model (v2):
//   - The apartment is a 640x400 pixel-art canvas (16px grid). The first
//     draw paints the floor plan + furniture sprites once; subsequent
//     draws just animate residents and bubble positions.
//   - Speech bubbles are HTML overlays anchored to resident sprite pixels
//     by reading the canvas bounding rect, so they survive any zoom.
//   - The clock ticks every 250 ms when the player presses play — much
//     faster than the 1.5 s of v1, so a 6-hour session feels alive.

(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));


  // All resident coordinates are foot points in this 640 × 400 dollhouse.
  const CANVAS_W = 640;
  const CANVAS_H = 400;
  const TILE = 8;
  const ROOMS = [
    { id: "kitchen", label: "厨房", x: 12, y: 12, w: 168, h: 172 },
    { id: "living", label: "客厅", x: 188, y: 12, w: 208, h: 172 },
    { id: "master", label: "主卧", x: 404, y: 12, w: 108, h: 172 },
    { id: "second", label: "次卧", x: 520, y: 12, w: 108, h: 172 },
    { id: "study", label: "书房", x: 12, y: 248, w: 180, h: 140 },
    { id: "bath", label: "卫生间", x: 200, y: 248, w: 128, h: 140 },
    { id: "balcony", label: "阳台", x: 336, y: 248, w: 160, h: 140 },
    { id: "hallway", label: "走廊", x: 12, y: 192, w: 616, h: 48 },
  ];
  const ROOM_DOORS = {
    kitchen: { x: 108, y: 184, side: "bottom" },
    living: { x: 310, y: 184, side: "bottom" },
    master: { x: 458, y: 184, side: "bottom" },
    second: { x: 574, y: 184, side: "bottom" },
    study: { x: 154, y: 248, side: "top" },
    bath: { x: 282, y: 248, side: "top" },
    balcony: { x: 424, y: 248, side: "top" },
  };
  const ROOM_SPOTS = Object.fromEntries(ROOMS.map(r => [r.id,
    [0.18,0.4,0.62,0.84].flatMap(t => [20,Math.min(52,r.h-16)].map(offset =>
      ({x: Math.round(r.x + r.w * t), y: r.y + r.h - offset})))]));
  const HALLWAY_PATH = [{x: 24, y: 216}, {x: 616, y: 216}];

  const SOLID_FURNITURE = new Set(["counter", "stove", "fridge", "sofa", "sofa_table",
    "tv", "tv_stand", "bed", "desk", "shelf", "tub", "toilet", "plant"]);

  // Search each room's floor on a four-pixel grid, with furniture as obstacles.
  // The final short step onto a bed or chair is intentional activity placement.
  function roomWalkPath(roomId, from, to) {
    const room = ROOMS.find(r => r.id === roomId);
    if (!room || roomId === "hallway") return [to];
    const step=4, cols=Math.floor((room.w-12)/step)+1, rows=Math.floor((room.h-16)/step)+1;
    const point=i => ({x:room.x+6+(i%cols)*step, y:room.y+8+Math.floor(i/cols)*step});
    const solids=(SPRITES[roomId] || []).filter(it => SOLID_FURNITURE.has(it.kind));
    const available=[];
    for(let i=0;i<cols*rows;i++) {
      const p=point(i);
      available[i]=!solids.some(it => p.x>=it.x-3 && p.x<=it.x+it.w+3 &&
        p.y>=it.y-2 && p.y<=it.y+it.h+3);
    }
    function nearest(p) {
      let best=-1, distance=Infinity;
      for(let i=0;i<available.length;i++) if(available[i]) {
        const q=point(i), d=(p.x-q.x)**2+(p.y-q.y)**2;
        if(d<distance) {best=i;distance=d;}
      }
      return best;
    }
    const first=nearest(from), last=nearest(to);
    if(first<0 || last<0) return [to];
    const queue=[first], previous=new Map([[first,-1]]);
    for(let cursor=0;cursor<queue.length && !previous.has(last);cursor++) {
      const i=queue[cursor], x=i%cols;
      const next=[i-cols,i+cols];
      if(x>0) next.push(i-1);
      if(x<cols-1) next.push(i+1);
      for(const n of next) if(n>=0 && n<available.length && available[n] && !previous.has(n)) {
        previous.set(n,i);queue.push(n);
      }
    }
    if(!previous.has(last)) return [to];
    const reverse=[];
    for(let i=last;i!==-1;i=previous.get(i)) reverse.push(point(i));
    const points=reverse.reverse(), turns=[];
    for(let i=0;i<points.length;i++) {
      const a=points[i-1],b=points[i],c=points[i+1];
      if(!a || !c || (b.x-a.x !== c.x-b.x) || (b.y-a.y !== c.y-b.y)) turns.push(b);
    }
    turns.push(to);
    return turns;
  }

  function computePath(fromRoom, fromSpot, toRoom, toSpot) {
    fromSpot = fromSpot || ROOM_SPOTS[fromRoom]?.[0] || ROOM_SPOTS.hallway[0];
    toSpot = toSpot || ROOM_SPOTS[toRoom]?.[0] || ROOM_SPOTS.hallway[0];
    if (fromRoom === toRoom) return roomWalkPath(toRoom,fromSpot,toSpot);
    const fromDoor = ROOM_DOORS[fromRoom] || {x: fromSpot.x, y: 216};
    const toDoor = ROOM_DOORS[toRoom] || {x: toSpot.x, y: 216};
    const points = [
      ...roomWalkPath(fromRoom,fromSpot,fromDoor),
      {x: fromDoor.x, y: 216}, {x: toDoor.x, y: 216}, toDoor,
      ...roomWalkPath(toRoom,toDoor,toSpot),
    ];
    return points.filter((p, i) => !i || p.x !== points[i-1].x || p.y !== points[i-1].y);
  }

  const floorSpotCache = new Map();
  function floorSpots(roomId) {
    if (floorSpotCache.has(roomId)) return floorSpotCache.get(roomId);
    const room = ROOMS.find(r => r.id === roomId) || ROOMS.find(r => r.id === "hallway");
    const solids=(SPRITES[room.id] || []).filter(it => SOLID_FURNITURE.has(it.kind));
    const valid=p => p.x>=room.x+12 && p.x<=room.x+room.w-12 &&
      p.y>=room.y+Math.min(36,room.h/2) && p.y<=room.y+room.h-12 &&
      !solids.some(it => p.x>=it.x-6 && p.x<=it.x+it.w+6 && p.y>=it.y-2 && p.y<=it.y+it.h+6);
    const selected=[];
    const distance=p => selected.length ? Math.min(...selected.map(q => (p.x-q.x)**2+(p.y-q.y)**2)) : 1e6;
    for (const p of ROOM_SPOTS[room.id]) if(valid(p) && distance(p)>=24**2) selected.push(p);
    const candidates=[];
    for(let y=room.y+room.h-12;y>=room.y+Math.min(36,room.h/2);y-=8) {
      for(let x=room.x+12;x<=room.x+room.w-12;x+=8) if(valid({x,y})) candidates.push({x,y});
    }
    while(selected.length<6) {
      let best=null, score=0;
      for(const p of candidates) if(distance(p)>score) {best=p;score=distance(p);}
      if(!best) break;
      selected.push(best);
    }
    floorSpotCache.set(roomId,selected);
    return selected;
  }

  function pickRoomSpot(roomId, agentId, activity = "") {
    const items = SPRITES[roomId] || [];
    const pose = pickPose({activity}, false, false);
    let kind = {cooking: "stove", sleeping: "bed", reading: "chair",
      phone: "sofa", eating: "sofa_table"}[pose];
    if (/洗澡|泡澡/.test(activity)) kind = "tub";
    if (/洗衣|洗碗/.test(activity)) kind = "sink";
    const peers = (state.session?.residents || []).filter(r => r.room === roomId &&
      pickPose(r, false, false) === pose).sort((a,b) => a.agent_id-b.agent_id);
    const peerIndex = peers.findIndex(r => r.agent_id === agentId);
    const order = peerIndex < 0 ? Math.abs(Number(agentId)||0) : peerIndex;
    const matches = items.filter(it => it.kind === kind);
    const item = matches.length ? matches[order % matches.length] : null;
    if (item) {
      const index = peerIndex < 0 ? 0 : Math.floor(order / matches.length);
      const slots = Math.max(1, Math.floor(item.w / 22));
      const x = Math.round(item.x + item.w * ((index % slots) + 1) / (slots + 1));
      if (pose === "sleeping") return {x: item.x + 22 + (index % 2) * (item.w-44), y: item.y + 38};
      const room = ROOMS.find(r => r.id === roomId);
      const y = item.y + item.h + (pose === "phone" ? -3 : pose === "reading" ? 4 : 22) +
        Math.floor(index/slots)*24;
      return {x,y:Math.min(room.y+room.h-12,y)};
    }
    const spots=floorSpots(roomId);
    // Share the allocation across poses: a chatter and an exerciser cannot
    // each claim the first spare patch of floor.
    const roomPeers=(state.session?.residents || []).filter(r => r.room===roomId)
      .sort((a,b) => a.agent_id-b.agent_id);
    const roomIndex=roomPeers.findIndex(r => r.agent_id===agentId);
    return spots[(roomIndex<0 ? order : roomIndex) % spots.length];
  }

  // Mood -1..+1 -> color (red < 0, green > 0). Used by both the
  // pixel sprite shirt and the dashboard bar.
  function moodColor(score) {
    if (score >= 0) {
      const intensity = Math.min(1, score) * 0.6 + 0.4;
      return "hsl(120, 35%, " + Math.round(85 - intensity * 20) + "%)";
    } else {
      const intensity = Math.min(1, -score) * 0.6 + 0.4;
      return "hsl(8, 40%, " + Math.round(85 - intensity * 20) + "%)";
    }
  }

  // Lookup room label by id from the session ROOMS array.
  function roomLabelById(s, id) {
    const found = (s.rooms || []).find((r) => r.id === id);
    return found ? found.label : (id || "");
  }

  const state = {
    city: null,
    agents: [],
    picked: new Set(),
    filter: "",
    catalogue: null,
    session: null,
    pollTimer: null,
    playing: false,
    spritesPainted: false,
    // Per-resident on-screen position + animation state. Lives outside
    // the session so it persists between ticks — the canvas smooths the
    // jump from one server-reported room to the next.
    sprites: {}, // agent_id -> {x, y, tx, ty, fromX, fromY, tStart, ms, walkFrame, isMoving, lastActivity, lastRoom}
    rafId: null,
    frameStamp: 0,
    // Auto-tick speed multiplier — drives both the poll interval and
    // the per-tick ``steps`` (see ``SPEED_TABLE``). Default 1×; the
    // player can change it on the toolbar.
    speed: 1,
    // Bubble playback cursor — for the most recent ``interact`` /
    // ``direct`` event with multiple ``turns``, we cycle through them
    // at 2 s/turn so the player sees both sides of the conversation
    // without scrolling the side panel. ``-1`` means no turn shown
    // (single bubble or no turns).
    bubbleTurnIdx: -1,
    bubbleTurnEventId: null,
    // Cache so ``renderBubbles`` only rebuilds the speech-bubble DOM
    // when the highlighted event or turn cursor changes — not every
    // frame. See ``renderBubbles`` for the payload-key format.
    bubbleBuiltKey: null,
    bubbleBuiltSeq: 0,
    bubbleSlots: [],
    bubbleTurnTimer: 0,
    // Modal dialog state for "you clicked a piece of furniture; who
    // should use it?". A flat object the bubble layer paints in a
    // fixed overlay: { furniture: {kind, roomId, label, activity},
    // residents: [{agent_id, name, emoji}], x, y }.
    furnitureDialog: null,
    furnitureDialogTimer: 0,
    lastClickEventAt: 0,
  };

  async function init() {
    $("#rStartBtn").addEventListener("click", startSession);
    $("#rPickRandom").addEventListener("click", pickRandom);
    $("#rPickNone").addEventListener("click", () => { state.picked.clear(); renderAgents(); });
    $("#rCity").addEventListener("change", () => {
      state.city = $("#rCity").value;
      state.picked.clear();
      loadAgents();
    });
    $("#rFilter").addEventListener("input", () => {
      state.filter = $("#rFilter").value.trim().toLowerCase();
      renderAgents();
    });
    $("#rTick1Btn").addEventListener("click", () => requestTick(1));
    $("#rTick6Btn").addEventListener("click", () => requestTick(6));
    $("#rPauseBtn").addEventListener("click", pause);
    $("#rResumeCtrl").addEventListener("click", resume);
    // Speed selector: 4 buttons in a pill group, each calls setSpeed().
    document.querySelectorAll(".speed-btn").forEach((b) => {
      b.addEventListener("click", () => {
        const v = parseFloat(b.getAttribute("data-speed"));
        if (!Number.isNaN(v)) setSpeed(v);
      });
    });
    $("#rEndBtn").addEventListener("click", endSession);
    $("#rResumeBtn").addEventListener("click", resumeLastSession);
    $("#rExportLink").addEventListener("click", exportMarkdown);

    // Player-driven furniture click → "let X use this". The canvas
    // captures the click first; the bubble layer (siblings) only see
    // synthetic events we dispatch when we open one.
    const canvas = $("#rCanvas");
    if (canvas) {
      canvas.addEventListener("click", onCanvasClick);
    }

    await Promise.all([loadCities().then(loadAgents), loadCatalogue()]);
    checkResume();
    if (typeof ResizeObserver !== "undefined" && canvas) {
      new ResizeObserver(() => { _geo.valid = false; }).observe(canvas);
    }
  }

  // -- pickers ------------------------------------------------------------
  async function loadCities() {
    const sel = $("#rCity");
    try {
      const resp = await fetch("/api/city/catalogue");
      const data = await resp.json();
      const cities = data.cities || [];
      sel.innerHTML = cities
        .map((c) => '<option value="' + esc(c.slug) + '">' + esc(c.display_name || c.name || c.slug) + '</option>')
        .join("");
      const preferred = data.selected != null ? data.selected : (cities[0] && cities[0].slug);
      if (preferred != null) sel.value = preferred;
      state.city = sel.value;
    } catch (err) {
      sel.innerHTML = '<option value="">' + esc(String(err)) + '</option>';
      state.city = "";
    }
  }

  async function loadCatalogue() {
    try {
      const resp = await fetch("/api/games/roommate/catalogue");
      state.catalogue = await resp.json();
    } catch (err) {
      state.catalogue = null;
    }
  }

  async function loadAgents() {
    const list = $("#rAgents");
    if (state.city === null) return;
    list.innerHTML = '<li class="roommate-empty">加载中...</li>';
    try {
      const resp = await fetch("/api/games/agents?city=" + encodeURIComponent(state.city));
      const data = await resp.json();
      state.agents = data.agents || [];
      renderAgents();
    } catch (err) {
      list.innerHTML = '<li class="roommate-empty is-error">' + esc(String(err)) + '</li>';
    }
  }

  function renderAgents() {
    const list = $("#rAgents");
    const max = (state.catalogue && state.catalogue.max_agents) || 6;
    const filter = state.filter;
    const filtered = state.agents.filter((a) => {
      if (!filter) return true;
      const hay = ((a.name || "") + " " + (a.job || "") + " #" + a.id).toLowerCase();
      return hay.indexOf(filter) >= 0;
    });
    if (!filtered.length) {
      list.innerHTML = '<li class="roommate-empty">' + esc(filter ? "没有匹配的居民" : "这座城市暂无居民") + '</li>';
      $("#rPicked").textContent = String(state.picked.size);
      return;
    }
    list.innerHTML = filtered
      .map((a) => {
        const meta = [a.age ? a.age + "岁" : "", a.gender || "", a.job || ""].filter(Boolean).join(" · ");
        const picked = state.picked.has(a.id);
        const on = picked ? " checked" : "";
        const cls = picked ? " is-picked" : "";
        return '<li><label class="' + (picked ? "is-picked" : "").trim() + '">'
          + '<input type="checkbox" value="' + a.id + '"' + on + ' />'
          + '<span class="who">#' + a.id + ' ' + esc(a.name) + '</span>'
          + '<span class="meta">' + esc(meta) + '</span>'
          + '</label></li>';
      })
      .join("");
    Array.from(list.querySelectorAll("li > label")).forEach((label) => {
      const box = label.querySelector("input[type=checkbox]");
      label.addEventListener("click", (ev) => {
        // The label click already toggles the checkbox; just reflect state
        // on the surrounding chip. Guard against the synthetic click the
        // browser fires when the inner checkbox is the actual target.
        if (ev.target === box) return;
      });
      box.addEventListener("change", () => {
        const id = parseInt(box.value, 10);
        if (box.checked) state.picked.add(id);
        else state.picked.delete(id);
        if (state.picked.size > max) {
          state.picked.delete(id);
          box.checked = false;
          alert("最多 " + max + " 人");
        }
        label.classList.toggle("is-picked", box.checked);
        $("#rPicked").textContent = String(state.picked.size);
      });
    });
    $("#rPicked").textContent = String(state.picked.size);
  }

  function pickRandom() {
    const pool = state.agents.slice();
    for (let i = pool.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [pool[i], pool[j]] = [pool[j], pool[i]];
    }
    state.picked = new Set(pool.slice(0, Math.min(4, pool.length)).map((a) => a.id));
    renderAgents();
  }

  // -- start / resume -----------------------------------------------------
  async function startSession() {
    const ids = Array.from(state.picked);
    if (ids.length < 2) return alert("至少选 2 位居民");
    const tick = parseInt($("#rTick").value, 10) || 5;
    const hours = parseInt($("#rHours").value, 10) || 24;
    const body = {
      city: state.city,
      agent_ids: ids,
      vibe: $("#rVibe").value.trim(),
      tick_minutes: tick,
      max_hours: hours,
    };
    $("#rStartBtn").disabled = true;
    try {
      const resp = await fetch("/api/games/roommate/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.error || "HTTP " + resp.status);
      enterSession(data);
    } catch (err) {
      alert(String(err.message || err));
    } finally {
      $("#rStartBtn").disabled = false;
    }
  }

  async function checkResume() {
    try {
      const resp = await fetch("/api/games/roommate/sessions");
      const data = await resp.json();
      const sessions = (data.sessions || []).filter((s) => !s.finished);
      if (sessions.length) {
        $("#rResumeBtn").hidden = false;
        $("#rResumeBtn").dataset.id = sessions[0].id;
      }
    } catch (err) {
      // silent
    }
  }

  async function resumeLastSession() {
    const id = $("#rResumeBtn").dataset.id;
    if (!id) return;
    try {
      const resp = await fetch("/api/games/roommate/sessions/" + encodeURIComponent(id));
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "HTTP " + resp.status);
      enterSession(data);
    } catch (err) {
      alert(String(err.message || err));
    }
  }

  function enterSession(session) {
    state.session = session;
    state.spritesPainted = false;
    state.bubbleBuiltKey = null;
    state.bubbleBuiltSeq = 0;
    state.bubbleSlots = [];
    state.furnitureDialog = null;
    _geo.valid = false;
    // Seed every resident's sprite position inside their starting room.
    state.sprites = {};
    const now = performance.now();
    (session.residents || []).forEach((r) => {
      const pos = pickRoomSpot(r.room || "living", r.agent_id, r.activity);
      state.sprites[r.agent_id] = {
        x: pos.x, y: pos.y,
        tx: pos.x, ty: pos.y,
        fromX: pos.x, fromY: pos.y,
        tStart: now, ms: 0,
        walkFrame: 0, isMoving: false,
        lastActivity: r.activity || "", lastRoom: r.room || "living",
        lastSpot: pos,
      };
    });
    $("#rSetup").hidden = true;
    $("#rLive").hidden = false;
    paintApartmentOnce();
    renderAll();
    $("#rAptVibe").textContent = session.vibe ? "「" + session.vibe + "」" : "";
    $("#rAptTitle").textContent = "🏠 公寓 · " + session.residents.length + " 位居民";
    // Auto-start: no waiting for the player to press play.
    // Defer play() and startFrameLoop() one tick so the click handler
    // that opened the session returns first. Without this defer, on a
    // slow first paint the user perceives the click as having "frozen"
    // the page — the click handler is still on the stack when the
    // 60 fps RAF loop starts up.
    setTimeout(() => {
      play();
      startFrameLoop();
    }, 80);
  }

  // -- tick / play loop ---------------------------------------------------
  async function requestTick(steps) {
    if (!state.session) return;
    // Drop overlapping requests — never queue more than one tick. A
    // 250 ms poll timer that fires while the previous tick is still
    // in flight would otherwise pile up against a slow model call.
    if (state.tickInFlight) {
      // If we already have one in flight, remember this request and
      // fire it after the current one returns — keeps the player's
      // pace (they clicked +6, they get +6) without piling up.
      state.pendingTick = { steps: steps };
      return;
    }
    // Use a counter (not a promise) so the flag is reliable across
    // microtask boundaries.
    state.tickInFlight = { steps: steps };
    try {
      const ctrl = new AbortController();
      // Hard 8-second timeout per tick. A hung LLM should not freeze the
      // browser tab forever — the watchdog on the server side will emit a
      // fallback event, and we move on.
      const timer = setTimeout(() => ctrl.abort(), 8000);
      const resp = await fetch("/api/games/roommate/tick", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: state.session.id, steps: steps }),
        signal: ctrl.signal,
      });
      clearTimeout(timer);
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "HTTP " + resp.status);
      state.session = data;
      renderAll();
      if (state.session.finished) {
        pause();
        $("#rStatus").textContent = "已结束";
        $("#rStatus").classList.add("is-done");
      }
    } catch (err) {
      // AbortError from the timeout above: keep playing, the server
      // emitted whatever it could.
      if (err && err.name === "AbortError") {
        $("#rStatus").textContent = "模型响应慢,跳过本轮";
        $("#rStatus").classList.add("is-error");
        return;
      }
      pause();
      $("#rStatus").textContent = String(err.message || err);
      $("#rStatus").classList.add("is-error");
    } finally {
      state.tickInFlight = null;
    }
    // If another tick was requested while this one was in flight, fire
    // it now so the player still sees progress at their pace. The
    // setInterval timer will pick up the next round on its own.
    if (state.pendingTick) {
      const pending = state.pendingTick;
      state.pendingTick = null;
      // Schedule on next microtask so we don't recursively fill the
      // stack when many clicks queued while the model was hanging.
      Promise.resolve().then(() => requestTick(pending.steps));
    }
  }

  //: Speed knobs for the auto-tick loop. The interval halves (and the
//: per-tick ``steps`` doubles) for every notch above 1×. The poll
//: interval is clamped so even at 4× we never tick more often than every
//: 1.5 s — that gives the model a chance to reply before the next
//: request lands.
const SPEED_TABLE = {
  0.5: { intervalMs: 12000, steps: 1 },
  1:   { intervalMs: 6000,  steps: 1 },
  2:   { intervalMs: 3000,  steps: 1 },
  4:   { intervalMs: 1500,  steps: 2 },
};

function play() {
    state.playing = true;
    $("#rPauseBtn").hidden = false;
    $("#rResumeCtrl").hidden = true;
    $("#rStatus").textContent = "运行中";
    $("#rStatus").classList.remove("is-error", "is-done");
    if (state.pollTimer) clearInterval(state.pollTimer);
    const { intervalMs, steps } = SPEED_TABLE[state.speed] || SPEED_TABLE[1];
    // Pace the auto-tick aggressively low when the LLM is unresponsive
    // — even at 4× we still wait 1.5 s between ticks so a 30 s model
    // hang backs up at most 20 requests, which fetch can keep up with.
    state.pollTimer = setInterval(() => {
      // Don't queue a timer tick on top of an in-flight manual click —
      // the manual click's pendingTick will fire on return.
      if (!state.tickInFlight && !state.pendingTick) requestTick(steps);
    }, intervalMs);
    // Repaint so the status label / dashboard reflect the new state
    // immediately. Without this, the button toggles but ``renderClock``
    // would not run again until the next tick lands, leaving the
    // "已暂停" → "运行中" label stale.
    renderAll();
    // Restart the per-frame redraw — ``pause`` stopped it; the resident
    // sprites are still walking between ticks.
    startFrameLoop();
  }

  // Change the auto-tick cadence while the simulation is running. Reuses
  // ``play()`` so the timer, status label, and frame loop all stay in
  // sync with the new speed. Safe to call when paused — it only takes
  // effect on the next ``play()``.
  function setSpeed(mult) {
    if (!(mult in SPEED_TABLE)) return;
    state.speed = mult;
    // Update the pill group so the active speed is highlighted.
    document.querySelectorAll(".speed-btn").forEach((b) => {
      b.classList.toggle("speed-btn-active", String(mult) === b.getAttribute("data-speed"));
    });
    if (state.playing) play();
  }

  function pause() {
    state.playing = false;
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = null;
    $("#rPauseBtn").hidden = true;
    $("#rResumeCtrl").hidden = false;
    // Pause the per-frame redraw — without ticking the simulation,
    // the apartment is a still image. Re-paint once so the label
    // shows "已暂停" and the button swap is visible.
    stopFrameLoop();
    renderAll();
  }

  function resume() {
    if (state.session && state.session.running && !state.session.finished) {
      play();
    } else {
      requestTick(1);
    }
  }

  async function endSession() {
    if (!state.session) return;
    pause();
    try {
      const resp = await fetch("/api/games/roommate/end", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: state.session.id }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "HTTP " + resp.status);
      state.session = data;
      renderAll();
      $("#rStatus").textContent = "已结束";
      $("#rStatus").classList.add("is-done");
    } catch (err) {
      alert(String(err.message || err));
    }
  }

  // -- rendering: canvas + bubbles + events + dashboard -------------------
  function renderAll() {
    if (!state.session) return;
    renderClock();
    renderConversation();
    renderEvents();
    renderDashboard();
    renderActivityLine();
    renderFurnitureDialog();
    // The frame loop already paints the canvas + bubbles every frame,
    // so we only need to refresh the side panels here.
  }

  // ---- player-driven furniture click ----------------------------------
  // Convert a mouse event's pixel coordinates into the canvas's logical
  // 640×400 grid, then walk the furniture hitboxes (drawn last so they
  // sit on top of rugs and curtains) and return the first match. The
  // hit-test mirrors what is painted: ``SPRITES[roomId]`` lists items
  // in draw order, so iterating in reverse lets windows / plants win
  // over the rug underneath.
  function hitTestFurniture(canvasX, canvasY) {
    if (!state.session) return null;
    const items = [];
    for (const r of ROOMS) {
      const list = SPRITES[r.id] || [];
      // Reverse so visually-on-top pieces (plants, books, etc.) win.
      for (let i = list.length - 1; i >= 0; i--) {
        const it = list[i];
        items.push({ room: r, item: it });
      }
    }
    for (const { room, item } of items) {
      if (NON_INTERACTIVE_KINDS.has(item.kind)) continue;
      if (!FURNITURE_ACTION[item.kind]) continue;
      const x0 = item.x, y0 = item.y;
      const x1 = item.x + item.w;
      const y1 = item.y + item.h;
      if (canvasX >= x0 && canvasX < x1 && canvasY >= y0 && canvasY < y1) {
        return { room, item };
      }
    }
    return null;
  }

  function onCanvasClick(ev) {
    if (!state.session || !state.session.running) return;
    // Throttle — two clicks within 200 ms is a double-click on the same
    // furniture, treat the second as a re-open.
    const now = performance.now();
    if (now - (state.lastClickEventAt || 0) < 200) return;
    state.lastClickEventAt = now;
    const canvas = ev.currentTarget;
    _refreshGeometry();
    const rect = _geo.rect;
    const cx = (ev.clientX - rect.left) / _geo.scaleX;
    const cy = (ev.clientY - rect.top) / _geo.scaleY;
    if (cx < 0 || cy < 0 || cx >= CANVAS_W || cy >= CANVAS_H) return;
    const hit = hitTestFurniture(cx, cy);
    if (!hit) {
      // Click outside any furniture — close any open dialog.
      state.furnitureDialog = null;
      renderFurnitureDialog();
      return;
    }
    openFurnitureDialog(hit, ev);
  }

  function openFurnitureDialog(hit, ev) {
    const action = FURNITURE_ACTION[hit.item.kind];
    const roomId = hit.room.id;
    // The natural room for the chosen activity — the table knows, not
    // the click. Falls back to the room the furniture lives in.
    const activities = action.activities;
    // Default activity: first in the list (most likely what the player
    // wants). For multi-purpose pieces (books / sofa_table / fridge)
    // we still default to the first.
    const activity = activities[0];
    // Compute the dialog overlay position from the click coords.
    _refreshGeometry();
    const fx = _geo.offsetX + (hit.item.x + hit.item.w / 2) * _geo.scaleX;
    const fy = _geo.offsetY + (hit.item.y + hit.item.h) * _geo.scaleY;
    state.furnitureDialog = {
      kind: hit.item.kind,
      roomId,
      label: action.label,
      activity,
      activities,
      // If the table specifies an explicit room (sofa_table → "kitchen")
      // honour it, otherwise keep the activity's natural room.
      room: roomId,
      anchor: { x: fx, y: fy },
      // List of residents to pick from. Filter out anyone settled already.
      residents: (state.session.residents || []).filter((r) => r.name),
    };
    renderFurnitureDialog();
  }

  function renderFurnitureDialog() {
    const layer = $("#rBubbles");
    if (!layer) return;
    // Drop any dialog whose session went away or is paused/finished.
    if (!state.session || !state.session.running) {
      state.furnitureDialog = null;
    }
    // Find a previous dialog DOM node so we can replace it in place.
    let node = document.getElementById("rFurnitureDialog");
    if (!state.furnitureDialog) {
      if (node) node.remove();
      return;
    }
    const d = state.furnitureDialog;
    if (!node) {
      node = document.createElement("div");
      node.id = "rFurnitureDialog";
      node.className = "furniture-dialog";
      layer.appendChild(node);
    }
    _maybeRefreshGeometry();
    const key = JSON.stringify([d.kind,d.roomId,d.activity,d.anchor.x,d.anchor.y,_geo.stage?.width,_geo.stage?.height,
      d.residents.map(r => [r.agent_id,r.name,r.emoji])]);
    if (node.dataset.renderKey === key) return;
    node.dataset.renderKey = key;
    const residentsHtml = d.residents.map((r) =>
      '<button type="button" class="furniture-pick" data-agent-id="' + r.agent_id + '">'
      + '<span class="furniture-pick-emoji">' + esc(r.emoji || "🙂") + '</span>'
      + '<span class="furniture-pick-name">' + esc(r.name) + '</span>'
      + '</button>'
    ).join("");
    const actsHtml = d.activities.map((a) =>
      '<button type="button" class="furniture-act' + (a === d.activity ? " furniture-act-active" : "") + '" data-activity="' + esc(a) + '">' + esc(a) + '</button>'
    ).join("");

    node.innerHTML =
      '<header>' + esc(d.label) + '<button type="button" class="furniture-close" aria-label="关闭">×</button></header>'
      + '<p class="furniture-room">在 <b>' + esc(roomLabelById(state.session, d.roomId) || d.roomId) + '</b> 房间里</p>'
      + '<div class="furniture-acts">' + actsHtml + '</div>'
      + '<p class="furniture-pick-label">让谁过去?</p>'
      + '<div class="furniture-picks">' + residentsHtml + '</div>';
    // Clamp the entire menu inside the dollhouse at every screen size.
    _maybeRefreshGeometry();
    const w=node.offsetWidth, h=node.offsetHeight;
    const width=_geo.stage?.width || layer.clientWidth;
    const height=_geo.stage?.height || layer.clientHeight;
    node.style.left=Math.max(w/2+8,Math.min(width-w/2-8,d.anchor.x))+"px";
    node.style.top=Math.max(0,Math.min(height-h-16,d.anchor.y))+"px";
    // Wire up the buttons. Use a fresh listener each time the dialog
    // re-renders so we don't pile up handlers.
    Array.from(node.querySelectorAll(".furniture-close")).forEach((b) => {
      b.addEventListener("click", () => {
        state.furnitureDialog = null;
        renderFurnitureDialog();
      });
    });
    Array.from(node.querySelectorAll(".furniture-act")).forEach((b) => {
      b.addEventListener("click", () => {
        if (!state.furnitureDialog) return;
        state.furnitureDialog.activity = b.getAttribute("data-activity") || state.furnitureDialog.activity;
        // Re-paint so the active pill moves.
        renderFurnitureDialog();
      });
    });
    Array.from(node.querySelectorAll(".furniture-pick")).forEach((b) => {
      b.addEventListener("click", () => {
        const agentId = parseInt(b.getAttribute("data-agent-id"), 10);
        const dlg = state.furnitureDialog;
        if (!dlg) return;
        submitDirect(agentId, dlg);
      });
    });
  }

  async function submitDirect(agentId, dlg) {
    if (!state.session || !state.session.id) return;
    const sid = state.session.id;
    const payload = {
      agent_id: agentId,
        activity: dlg.activity,
        note: "玩家让 " + (state.session.residents.find((r) => r.agent_id === agentId) || {}).name + " "
          + dlg.label,
      };
    if (dlg.room) payload.room = dlg.room;
    // Hide the dialog immediately so the user sees their click "took".
    state.furnitureDialog = null;
    renderFurnitureDialog();
    try {
      const resp = await fetch("/api/games/roommate/sessions/" + encodeURIComponent(sid) + "/direct", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        const errBody = await resp.json().catch(() => ({}));
        showTransientNotice("指令被拒:" + (errBody.error || resp.status));
        return;
      }
      state.session = await resp.json();
      renderAll();
    } catch (err) {
      showTransientNotice("网络错误:" + String(err));
    }
  }

  function showTransientNotice(text) {
    let bar = document.getElementById("rTransientNotice");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "rTransientNotice";
      bar.className = "transient-notice";
      const layer = $("#rBubbles");
      if (layer && layer.parentElement) layer.parentElement.appendChild(bar);
    }
    bar.textContent = text;
    bar.classList.add("transient-notice-show");
    clearTimeout(showTransientNotice._t);
    showTransientNotice._t = setTimeout(() => bar.classList.remove("transient-notice-show"), 2200);
  }

  function renderClock() {
    const s = state.session;
    $("#rClock").textContent = s.virtual_clock;
    if (state.playing === false && s.running && !s.finished) {
      $("#rStatus").textContent = "已暂停";
    } else if (s.finished) {
      $("#rStatus").textContent = "已结束";
      $("#rStatus").classList.add("is-done");
    } else {
      $("#rStatus").textContent = "运行中";
      $("#rStatus").classList.remove("is-error", "is-done");
    }
  }

  // ----- pixel art -----
  function getCtx() {
    const canvas = $("#rCanvas");
    if (!canvas) return null;
    if (canvas.width !== CANVAS_W) canvas.width = CANVAS_W;
    if (canvas.height !== CANVAS_H) canvas.height = CANVAS_H;
    return canvas.getContext("2d");
  }

  // When the server reports a new ``resident.room``, snap the sprite to
  // a slot in the new room and animate a walk from its current position
  // along a fixed path (room spot → door → hallway → door → target spot).
  // Called from :func:`renderAll`.
  function retargetSprites() {
    if (!state.session) return;
    const now = performance.now();
    (state.session.residents || []).forEach((r) => {
      const sp = state.sprites[r.agent_id];
      if (!sp) return;
      const movedRoom = r.room !== sp.lastRoom;
      const dest = pickRoomSpot(r.room, r.agent_id, r.activity);
      const changedSpot = !sp.lastSpot || dest.x !== sp.lastSpot.x || dest.y !== sp.lastSpot.y;
      if (movedRoom || changedSpot) {
        const curSpot = {x: sp.x, y: sp.y};
        const physicalRoom = ROOMS.find(room => sp.x>=room.x && sp.x<=room.x+room.w &&
          sp.y>=room.y && sp.y<=room.y+room.h);
        const path = computePath(physicalRoom?.id || "hallway", curSpot, r.room, dest);
        sp.path = path;
        sp.pathIdx = 0;
        sp.fromX = sp.x;
        sp.fromY = sp.y;
        sp.tx = path[0].x;
        sp.ty = path[0].y;
        sp.tStart = now;
        // Time per waypoint scales with distance so fast walks look brisk.
        const segLen = Math.hypot(sp.tx - sp.fromX, sp.ty - sp.fromY);
        sp.ms = Math.max(450, Math.min(1400, segLen * 6));
        sp.isMoving = true;
        sp.lastRoom = r.room;
        sp.lastSpot = dest;
      }
      sp.lastActivity = r.activity || sp.lastActivity;
    });
  }

  // Dimming helper: shift a hex colour towards a target by `amt` (0..1).
  function shade(hex, amt, target) {
    const h = parseInt(hex.slice(1), 16);
    let r = (h >> 16) & 0xff;
    let g = (h >> 8) & 0xff;
    let b = h & 0xff;
    const t = parseInt(target.slice(1), 16);
    const tr = (t >> 16) & 0xff;
    const tg = (t >> 8) & 0xff;
    const tb = t & 0xff;
    r = Math.round(r + (tr - r) * amt);
    g = Math.round(g + (tg - g) * amt);
    b = Math.round(b + (tb - b) * amt);
    return "#" + ((r << 16) | (g << 8) | b).toString(16).padStart(6, "0");
  }

  // Offscreen cache for the static parts of the apartment (floor, walls,
// furniture, room labels, waypoint dots). Built once per session so the
// per-frame repaint only draws residents, bubbles and the night overlay.
  let _bgCache = null;
  function getBgCache() {
    if (_bgCache) return _bgCache;
    const off = document.createElement("canvas");
    off.width = CANVAS_W;
    off.height = CANVAS_H;
    const c = off.getContext("2d");
    c.imageSmoothingEnabled = false;
    paintApartment(c);
    _bgCache = off;
    return off;
  }

  function paintApartment(ctx) {
    ctx.fillStyle = "#443d3c";
    ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
    for (const r of ROOMS) {
      ctx.save();
      ctx.beginPath(); ctx.rect(r.x, r.y, r.w, r.h); ctx.clip();
      paintFloor(ctx, r);
      paintFloorDetails(ctx, r);
      // Rugs always belong below furniture.
      for (const it of SPRITES[r.id] || []) if (it.kind === "rug") SPRITE_DRAW.rug(ctx, it);
      paintAtmosphere(ctx, r);
      ctx.restore();
      paintWalls(ctx, r);
      if (r.id !== "hallway") paintWallDecor(ctx, r);
      for (const it of SPRITES[r.id] || []) if (it.kind !== "rug") SPRITE_DRAW[it.kind]?.(ctx, it);
      paintRoomLabel(ctx, r);
    }
    // Entry alcove belongs to the corridor, with shoes, a bench and coats.
    const entry = {id: "entry", label: "玄关", x: 504, y: 248, w: 124, h: 140};
    paintFloor(ctx, entry); paintWalls(ctx, entry);
    SPRITE_DRAW.shelf(ctx, {x: 516, y: 302, w: 98, h: 32});
    SPRITE_DRAW.plant(ctx, {x: 596, y: 348, w: 16, h: 22});
    ctx.fillStyle = "#796b68"; ctx.fillRect(528, 346, 54, 24);
    ctx.fillStyle = "#baa58e"; ctx.fillRect(531, 349, 48, 18);
    for (let i=0; i<3; i++) {
      ctx.fillStyle = ["#ae6e57", "#657b83", "#818a69"][i];
      ctx.fillRect(526+i*24, 274, 14, 20);
      ctx.fillStyle = "#e7d9bc"; ctx.fillRect(531+i*24, 271, 4, 3);
    }
    paintRoomLabel(ctx, entry);
    paintWaypointOverlay(ctx);
  }

  function paintApartmentOnce() {
    const ctx = getCtx();
    if (!ctx) return;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(getBgCache(), 0, 0);
    state.spritesPainted = true;
  }

  // Room-specific floor decorations: kitchen tiles, bath tile pattern,
  // living-room rug, bedroom wood plank grain. Drawn over the base floor.
  // Wall-mounted decorations: framed paintings, wall clock, hanging
  // calendar, etc. Drawn after the furniture so they sit on top of the
  // back wall. Each room gets 1–3 props selected deterministically.
  function paintWallDecor(ctx, r) {
    if (r.id === "kitchen") {
      // Hanging spice rack on the back wall.
      const x = r.x + 6, y = r.y + 12;
      ctx.fillStyle = "#5d4a30";
      ctx.fillRect(x, y, 28, 2);
      const colors = ["#b45c3c", "#6ea05c", "#6fb1c4", "#e9d8a6", "#8b6f47"];
      for (let i = 0; i < 5; i++) {
        ctx.fillStyle = colors[i];
        ctx.fillRect(x + 2 + i * 5, y + 2, 4, 6);
        ctx.fillStyle = "#1a120a";
        ctx.fillRect(x + 2 + i * 5, y + 8, 4, 1);
      }
    } else if (r.id === "living") {
      // A wall clock above the sofa.
      const x = r.x + 60, y = r.y + 12;
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(x - 1, y - 1, 14, 14);
      ctx.fillStyle = "#fffbe9";
      ctx.fillRect(x, y, 12, 12);
      ctx.fillStyle = "#1a120a";
      // Tick marks.
      for (let i = 0; i < 12; i++) {
        const a = (i / 12) * Math.PI * 2;
        const tx = x + 6 + Math.cos(a) * 5;
        const ty = y + 6 + Math.sin(a) * 5;
        ctx.fillRect(Math.round(tx), Math.round(ty), 1, 1);
      }
      // Hands — current time.
      const d = new Date();
      const sec = d.getSeconds() / 60;
      const min = (d.getMinutes() + sec) / 60;
      const hr = (d.getHours() + min) / 12;
      ctx.fillStyle = "#1a120a";
      ctx.fillRect(x + 5, y + 2, 1, 4); // hour hand (up = 12)
      ctx.fillRect(x + 6, y + 4, 4, 1); // minute hand (right = 3)
      ctx.fillStyle = "#b45c3c";
      ctx.fillRect(x + 6, y + 6, 1, 1); // centre
      // Big framed painting right of the clock.
      const px = r.x + 100, py = r.y + 12;
      ctx.fillStyle = "#1a120a";
      ctx.fillRect(px - 1, py - 1, 28, 24);
      ctx.fillStyle = "#6fb1c4";
      ctx.fillRect(px, py, 26, 22);
      // Mountain + sun.
      ctx.fillStyle = "#e9d8a6";
      ctx.fillRect(px + 18, py + 4, 4, 4);
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(px + 4, py + 14, 10, 8);
      ctx.fillRect(px + 12, py + 10, 8, 12);
      ctx.fillStyle = "#fffbe9";
      ctx.fillRect(px + 6, py + 18, 2, 1);
      ctx.fillRect(px + 14, py + 14, 2, 1);
    } else if (r.id === "master") {
      // A tall window with curtains.
      const x = r.x + 6, y = r.y + 10;
      ctx.fillStyle = "#1a120a";
      ctx.fillRect(x - 1, y - 1, 28, 36);
      ctx.fillStyle = "#b4d8e6";
      ctx.fillRect(x, y, 26, 34);
      // Mullion
      ctx.fillStyle = "#5d4a30";
      ctx.fillRect(x + 12, y, 2, 34);
      ctx.fillRect(x, y + 16, 26, 1);
      // Curtain sides
      ctx.fillStyle = "#5a4b8b";
      ctx.fillRect(x - 3, y - 1, 3, 36);
      ctx.fillRect(x + 26, y - 1, 3, 36);
      // Frame highlight
      ctx.fillStyle = "#a37a4b";
      ctx.fillRect(x - 1, y - 1, 28, 1);
      // A small framed photo beside the bed
      const fx = r.x + r.w - 22, fy = r.y + 12;
      ctx.fillStyle = "#1a120a";
      ctx.fillRect(fx - 1, fy - 1, 16, 16);
      ctx.fillStyle = "#fffbe9";
      ctx.fillRect(fx, fy, 14, 14);
      ctx.fillStyle = "#e9d8a6";
      ctx.fillRect(fx + 2, fy + 2, 10, 10);
      ctx.fillStyle = "#b45c3c";
      ctx.fillRect(fx + 6, fy + 6, 2, 4);
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(fx + 5, fy + 4, 4, 2);
    } else if (r.id === "second") {
      // A poster on the wall + a window
      const x = r.x + 6, y = r.y + 10;
      ctx.fillStyle = "#1a120a";
      ctx.fillRect(x - 1, y - 1, 22, 28);
      ctx.fillStyle = "#b4d8e6";
      ctx.fillRect(x, y, 20, 26);
      ctx.fillStyle = "#5d4a30";
      ctx.fillRect(x + 9, y, 2, 26);
      // Mountains outside
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(x + 2, y + 18, 6, 8);
      ctx.fillRect(x + 13, y + 14, 5, 12);
      // Sun
      ctx.fillStyle = "#e9d8a6";
      ctx.fillRect(x + 4, y + 4, 3, 3);
    } else if (r.id === "study") {
      // A whiteboard / calendar on the wall.
      const x = r.x + 4, y = r.y + 12;
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(x, y, 24, 18);
      ctx.fillStyle = "#fffbe9";
      ctx.fillRect(x + 1, y + 1, 22, 16);
      ctx.fillStyle = "#b45c3c";
      // Header band
      ctx.fillRect(x + 1, y + 1, 22, 3);
      // To-do lines
      ctx.fillStyle = "#1a120a";
      ctx.fillRect(x + 2, y + 6, 1, 1);
      ctx.fillRect(x + 4, y + 6, 14, 1);
      ctx.fillRect(x + 2, y + 9, 1, 1);
      ctx.fillRect(x + 4, y + 9, 12, 1);
      ctx.fillRect(x + 2, y + 12, 1, 1);
      ctx.fillRect(x + 4, y + 12, 16, 1);
      ctx.fillRect(x + 2, y + 15, 1, 1);
      ctx.fillRect(x + 4, y + 15, 10, 1);
    } else if (r.id === "bath") {
      // Mirror on the wall.
      const x = r.x + 4, y = r.y + 10;
      ctx.fillStyle = "#5d6b62";
      ctx.fillRect(x - 1, y - 1, 22, 14);
      ctx.fillStyle = "#a4d2e0";
      ctx.fillRect(x, y, 20, 12);
      // Reflective highlight
      ctx.fillStyle = "#f3e7c3";
      ctx.fillRect(x + 2, y + 2, 3, 1);
      ctx.fillRect(x + 5, y + 2, 1, 1);
    } else if (r.id === "balcony") {
      // Hanging laundry on a line.
      const x = r.x + 6, y = r.y + 6;
      // Line
      ctx.fillStyle = "#5d4a30";
      ctx.fillRect(x, y, r.w - 12, 1);
      // Clothes
      const palette = ["#b45c3c", "#6fb1c4", "#e9d8a6", "#6fb1c4", "#b45c3c"];
      for (let i = 0; i < 5; i++) {
        ctx.fillStyle = palette[i];
        const cx = x + 4 + i * 12;
        ctx.fillRect(cx, y + 1, 10, 6);
        ctx.fillStyle = "#1a120a";
        ctx.fillRect(cx, y + 7, 10, 1);
      }
    } else if (r.id === "hallway") {
      // A row of hooks on the wall with hanging coats.
      const x = r.x + 8, y = r.y + 12;
      ctx.fillStyle = "#5d4a30";
      ctx.fillRect(x, y, r.w - 16, 2);
      const colors = ["#b45c3c", "#5a4b8b", "#6ea05c", "#3a2716", "#cba46b"];
      for (let i = 0; i < colors.length; i++) {
        ctx.fillStyle = colors[i];
        ctx.fillRect(x + 6 + i * 22, y + 2, 8, 16);
        ctx.fillStyle = "#1a120a";
        ctx.fillRect(x + 7 + i * 22, y + 8, 1, 4);
      }
    }
  }

  function paintFloorDetails(ctx, r) {
    if (r.id === "kitchen") {
      // Checkerboard floor over the wooden base.
      for (let yy = 0; yy < r.h; yy += 16) {
        for (let xx = 0; xx < r.w; xx += 16) {
          const dark = ((xx / 16) + (yy / 16)) % 2 === 0;
          ctx.fillStyle = dark ? "rgba(255, 230, 180, 0.18)" : "rgba(60, 30, 20, 0.18)";
          ctx.fillRect(r.x + xx, r.y + yy, 16, 16);
        }
      }
    } else if (r.id === "bath") {
      // Bathroom: white tiles with light blue grout.
      ctx.fillStyle = "rgba(180, 215, 225, 0.4)";
      ctx.fillRect(r.x, r.y, r.w, r.h);
      ctx.fillStyle = "rgba(120, 165, 180, 0.6)";
      for (let yy = 0; yy < r.h; yy += 12) {
        ctx.fillRect(r.x, r.y + yy, r.w, 1);
      }
      for (let xx = 0; xx < r.w; xx += 12) {
        ctx.fillRect(r.x + xx, r.y + r.h - 12, 1, 12);
      }
    } else if (r.id === "hallway") {
      // Long horizontal planks.
      ctx.fillStyle = "rgba(120, 80, 40, 0.4)";
      for (let yy = 4; yy < r.h; yy += 12) {
        ctx.fillRect(r.x, r.y + yy, r.w, 1);
      }
      // A centre runner rug in the hallway.
      ctx.fillStyle = "rgba(180, 60, 60, 0.4)";
      ctx.fillRect(r.x + 8, r.y + 24, r.w - 16, 12);
      ctx.fillStyle = "rgba(220, 200, 120, 0.5)";
      ctx.fillRect(r.x + 8, r.y + 28, r.w - 16, 1);
    } else if (r.id === "balcony") {
      // Outdoor deck with horizontal boards and a low outer railing.
      ctx.fillStyle = "rgba(170, 170, 170, 0.4)";
      ctx.fillRect(r.x, r.y, r.w, r.h);
      ctx.fillStyle = "rgba(120, 120, 120, 0.6)";
      for (let yy = 0; yy < r.h; yy += 8) {
        ctx.fillRect(r.x, r.y + yy, r.w, 1);
      }
      for (let xx = 0; xx < r.w; xx += 8) {
        ctx.fillRect(r.x + xx, r.y + r.h - 12, 1, 12);
      }
      // Railing at the outside edge.
      ctx.fillStyle = "#5d6b62";
      ctx.fillRect(r.x, r.y+r.h-12, r.w, 2);
      ctx.fillStyle = "#a8b8b0";
      for (let xx = 2; xx < r.w; xx += 6) {
        ctx.fillRect(r.x + xx, r.y + r.h - 12, 1, 12);
      }
    } else if (r.id === "living") {
      // Big patterned rug in the centre.
      const rx = r.x + 16, ry = r.y + 70, rw = r.w - 32, rh = r.h - 90;
      if (rw > 30 && rh > 30) {
        ctx.fillStyle = "rgba(160, 90, 50, 0.55)";
        ctx.fillRect(rx, ry, rw, rh);
        ctx.fillStyle = "rgba(220, 180, 90, 0.5)";
        // Diamond pattern
        for (let yy = 0; yy < rh; yy += 6) {
          ctx.fillRect(rx + 2, ry + yy, rw - 4, 1);
        }
        for (let xx = 0; xx < rw; xx += 10) {
          ctx.fillRect(rx + xx, ry + 2, 1, rh - 4);
        }
        // Outer fringe.
        ctx.fillStyle = "rgba(120, 60, 30, 0.7)";
        ctx.fillRect(rx - 2, ry - 2, rw + 4, 2);
        ctx.fillRect(rx - 2, ry + rh, rw + 4, 2);
        ctx.fillRect(rx - 2, ry, 2, rh);
        ctx.fillRect(rx + rw, ry, 2, rh);
      }
    }
  }

  // Tiny indicator dots over the waypoints we use — only when debug is on,
  // but the call is harmless when off. Kept for visual reference of the
  // path system.
  function paintWaypointOverlay(ctx) {
    if (!window.__RM_DEBUG_PATH__) return;
    const doors = ROOM_DOORS;
    Object.keys(doors).forEach((rid) => {
      const d = doors[rid];
      ctx.fillStyle = "rgba(255, 200, 80, 0.55)";
      ctx.fillRect(d.x - 1, d.y - 1, 3, 3);
    });
    (ROOM_SPOTS.hallway || []).forEach((s) => {
      ctx.fillStyle = "rgba(120, 200, 255, 0.45)";
      ctx.fillRect(s.x - 1, s.y - 1, 3, 3);
    });
  }

  // Floor: 8x8 tile pattern with three brightness steps to fake plank
  // grain and grout. Each room gets its own seed offset so the pattern
  // doesn't repeat across the whole apartment.
  function paintFloor(ctx, r) {
    const tileColors = ["#d9b783", "#d3ad76", "#cba46b", "#b88f55"];
    const grout = "#7d5e3a";
    ctx.fillStyle = tileColors[0];
    ctx.fillRect(r.x, r.y, r.w, r.h);
    // Plank rows: every 3rd tile is a slightly darker row.
    for (let yy = 0; yy < r.h; yy += TILE * 2) {
      ctx.fillStyle = tileColors[1];
      ctx.fillRect(r.x, r.y + yy, r.w, TILE);
    }
    // Plank seams: short dark line every ~24 px so it reads as wood.
    const seed = r.id.charCodeAt(0);
    for (let xx = 0; xx < r.w; xx += TILE) {
      const seamY = r.y + TILE - 1 + ((seed + xx) % 12);
      if (seamY < r.y + r.h - 2) {
        ctx.fillStyle = grout;
        ctx.fillRect(r.x + xx, seamY, TILE - 2, 1);
      }
    }
    // Vertical seams every 32 px.
    for (let yy = 0; yy < r.h; yy += 16) {
      const seamX = r.x + ((seed * 7 + yy) % 24);
      if (seamX < r.x + r.w - 2) {
        ctx.fillStyle = grout;
        ctx.fillRect(seamX, r.y + yy, 1, 8);
      }
    }
  }

  // Walls: top + left half-height interior partition. The top wall carries
  // the warm wood trim; the partition wall is half-height so the player can
  // still see into the next room.
  function paintWalls(ctx, r) {
    const trimLight = "#a37a4b";
    const trim = "#6b4a2b";
    const trimDark = "#3a2716";
    // Top wall: 4 px tall wood trim.
    ctx.fillStyle = trim;
    ctx.fillRect(r.x, r.y, r.w, 4);
    ctx.fillStyle = trimLight;
    ctx.fillRect(r.x, r.y, r.w, 1);
    ctx.fillStyle = trimDark;
    ctx.fillRect(r.x, r.y + 3, r.w, 1);
    // Left wall: 4 px wood trim.
    ctx.fillStyle = trim;
    ctx.fillRect(r.x, r.y, 4, r.h);
    ctx.fillStyle = trimLight;
    ctx.fillRect(r.x, r.y, 1, r.h);
    ctx.fillStyle = trimDark;
    ctx.fillRect(r.x + 3, r.y, 1, r.h);
    // Right + bottom only the dark trim (1 px) — like a picture frame.
    ctx.fillStyle = trimDark;
    ctx.fillRect(r.x + r.w - 1, r.y, 1, r.h);
    ctx.fillRect(r.x, r.y + r.h - 1, r.w, 1);
    const door = ROOM_DOORS[r.id];
    if (door) {
      ctx.fillStyle = "#d3ad76";
      ctx.fillRect(door.x - 14, door.y - (door.side === "top" ? 8 : 4), 28, 12);
      ctx.fillStyle = "#b18b61";
      ctx.fillRect(door.x - 14, door.y, 28, 1);
      ctx.fillStyle = "#f0d8ad";
      ctx.fillRect(door.x - 16, door.y - 4, 2, 8);
      ctx.fillRect(door.x + 14, door.y - 4, 2, 8);
    }
    if (r.id === "hallway") {
      // The corridor has open thresholds along both long edges.
      for (const d of Object.values(ROOM_DOORS)) {
        const edgeY = d.side === "bottom" ? r.y : r.y+r.h-4;
        ctx.fillStyle = "#d3ad76"; ctx.fillRect(d.x-14, edgeY, 28, 4);
      }
    }
  }

  function paintRoomLabel(ctx, r) {
    // A small chip in the top-left of each room — readable but unobtrusive.
    ctx.fillStyle = "rgba(26, 18, 10, 0.7)";
    ctx.fillRect(r.x + 8, r.y + r.h - 15, r.label.length * 9 + 8, 11);
    ctx.fillStyle = "#f3e7c3";
    ctx.font = "9px monospace";
    ctx.fillText(r.label, r.x + 11, r.y + r.h - 7);
  }

  function paintSprites(ctx, roomId) {
    const items = SPRITES[roomId] || [];
    for (const it of items) {
      const fn = SPRITE_DRAW[it.kind];
      if (fn) fn(ctx, it);
    }
  }

  // Each sprite draws itself with three tones (base / shade / highlight)
  // so even small furniture reads as 3D. Sprites are positioned by
  // absolute (x, y) in canvas pixels, not by tile.
  const SPRITE_DRAW = {
    counter: (ctx, it) => {
      // Counter top: warm marble counter with shadow under.
      const x = it.x, y = it.y, w = it.w, h = it.h;
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(x, y + h - 2, w, 2);
      ctx.fillStyle = "#e9d8a6";
      ctx.fillRect(x, y, w, h - 2);
      ctx.fillStyle = "#f3e7c3";
      ctx.fillRect(x, y, w, 1);
      ctx.fillStyle = "#cba46b";
      ctx.fillRect(x, y + h - 3, w, 1);
    },
    stove: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      // Body
      ctx.fillStyle = "#5d6b62";
      ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#1a120a";
      ctx.fillRect(x + 1, y + h - 2, w - 2, 1);
      // Two burners, each with a pan
      ctx.fillStyle = "#1a120a";
      ctx.fillRect(x + 4, y + 2, 6, 4);
      ctx.fillStyle = "#b45c3c";
      ctx.fillRect(x + 4, y + 1, 6, 1);
      ctx.fillRect(x + 14, y + 2, 6, 4);
      ctx.fillStyle = "#f3e7c3";
      ctx.fillRect(x + 14, y + 1, 6, 1);
      // Knobs
      ctx.fillStyle = "#cba46b";
      ctx.fillRect(x + 2, y + h - 5, 2, 2);
      ctx.fillRect(x + w - 4, y + h - 5, 2, 2);
    },
    fridge: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      ctx.fillStyle = "#1a120a";
      ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#dfe7e0";
      ctx.fillRect(x + 1, y + 1, w - 2, h - 2);
      ctx.fillStyle = "#f3e7c3";
      ctx.fillRect(x + 1, y + 1, w - 2, 1);
      // Door split
      ctx.fillStyle = "#a8b8b0";
      ctx.fillRect(x + Math.floor(w / 2), y + 2, 1, h - 4);
      // Handle
      ctx.fillStyle = "#5d6b62";
      ctx.fillRect(x + Math.floor(w / 2) + 2, y + 4, 1, 5);
    },
    sink: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(x, y + h - 2, w, 2);
      ctx.fillStyle = "#a8b8b0";
      ctx.fillRect(x, y, w, h - 2);
      // Basin
      ctx.fillStyle = "#6fb1c4";
      ctx.fillRect(x + 2, y + 3, w - 4, h - 6);
      ctx.fillStyle = "#a4d2e0";
      ctx.fillRect(x + 3, y + 3, w - 6, 1);
      // Faucet
      ctx.fillStyle = "#5d6b62";
      ctx.fillRect(x + Math.floor(w / 2) - 1, y - 4, 2, 6);
      ctx.fillRect(x + Math.floor(w / 2) - 3, y - 4, 6, 1);
    },
    sofa: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      // Backrest
      ctx.fillStyle = shade("#b45c3c", 0.4, "#1a120a");
      ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#b45c3c";
      ctx.fillRect(x + 1, y + 1, w - 2, h - 1);
      ctx.fillStyle = shade("#b45c3c", 0.4, "#f3e7c3");
      ctx.fillRect(x + 1, y + 1, w - 2, 1);
      // Cushions: 3 segments
      const cw = Math.floor(w / 3);
      for (let i = 0; i < 3; i++) {
        const cx = x + 2 + i * cw;
        ctx.fillStyle = "#d9b783";
        ctx.fillRect(cx, y + 4, cw - 2, h - 5);
        ctx.fillStyle = "#f3e7c3";
        ctx.fillRect(cx, y + 4, cw - 2, 1);
      }
    },
    sofa_table: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(x, y + h - 2, w, 2);
      ctx.fillStyle = "#a37a4b";
      ctx.fillRect(x, y, w, h - 2);
      ctx.fillStyle = "#cba46b";
      ctx.fillRect(x, y, w, 1);
      // A coffee mug on the table
      ctx.fillStyle = "#f3e7c3";
      ctx.fillRect(x + 6, y + 2, 4, 5);
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(x + 7, y + 3, 2, 1);
    },
    tv_stand: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#a37a4b";
      ctx.fillRect(x + 1, y + h - 6, w - 2, 4);
    },
    tv: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      // Frame
      ctx.fillStyle = "#1a120a";
      ctx.fillRect(x - 2, y - 2, w + 4, h + 4);
      // Screen
      ctx.fillStyle = "#6fb1c4";
      ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#a4d2e0";
      ctx.fillRect(x + 1, y + 1, w - 2, 2);
      // Reflection
      ctx.fillStyle = "#f3e7c3";
      ctx.fillRect(x + 1, y + 1, 4, 1);
    },
    rug: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      ctx.fillStyle = "#c8a878";
      ctx.fillRect(x, y, w, h);
      // Pattern: 3 horizontal bands
      ctx.fillStyle = "#a37a4b";
      ctx.fillRect(x, y + 3, w, 1);
      ctx.fillRect(x, y + h - 4, w, 1);
      ctx.fillStyle = "#8b6f47";
      for (let xx = 0; xx < w; xx += 6) {
        ctx.fillRect(x + xx, y + h / 2 - 1, 3, 1);
      }
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(x, y, w, 1);
      ctx.fillRect(x, y + h - 1, w, 1);
    },
    bed: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      // Frame
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(x, y + h - 3, w, 3);
      // Mattress
      ctx.fillStyle = "#f3e7c3";
      ctx.fillRect(x + 1, y + 1, w - 2, h - 4);
      ctx.fillStyle = shade("#f3e7c3", 0.2, "#a37a4b");
      ctx.fillRect(x + 1, y + h - 4, w - 2, 1);
      // Blanket (lower half)
      ctx.fillStyle = it.blanket || "#b45c3c";
      ctx.fillRect(x + 1, y + Math.floor(h * 0.5), w - 2, h - Math.floor(h * 0.5) - 3);
      ctx.fillStyle = shade(it.blanket || "#b45c3c", 0.3, "#1a120a");
      ctx.fillRect(x + 1, y + Math.floor(h * 0.5), w - 2, 1);
      // Pillow
      ctx.fillStyle = "#fffbe9";
      ctx.fillRect(x + 4, y + 3, 8, 6);
      ctx.fillStyle = "#cba46b";
      ctx.fillRect(x + 4, y + 8, 8, 1);
      // Second pillow for double beds
      if (w > 32) {
        ctx.fillStyle = "#fffbe9";
        ctx.fillRect(x + 14, y + 3, 8, 6);
        ctx.fillStyle = "#cba46b";
        ctx.fillRect(x + 14, y + 8, 8, 1);
      }
    },
    lamp: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(x + 2, y + h - 4, 2, 4);
      ctx.fillStyle = "#f3e7c3";
      ctx.fillRect(x, y, w, 4);
      ctx.fillStyle = "#fffbe9";
      ctx.fillRect(x + 1, y + 1, w - 2, 2);
    },
    desk: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(x, y + h - 2, w, 2);
      ctx.fillStyle = "#a37a4b";
      ctx.fillRect(x, y, w, h - 2);
      ctx.fillStyle = "#cba46b";
      ctx.fillRect(x, y, w, 1);
      // A laptop
      ctx.fillStyle = "#1a120a";
      ctx.fillRect(x + 4, y + 2, 10, 6);
      ctx.fillStyle = "#6fb1c4";
      ctx.fillRect(x + 5, y + 3, 8, 4);
    },
    chair: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(x, y + h - 3, w, 3);
      ctx.fillStyle = "#5d6b62";
      ctx.fillRect(x, y, w, h - 3);
      ctx.fillStyle = "#a37a4b";
      ctx.fillRect(x + 1, y + 1, w - 2, 1);
    },
    shelf: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      ctx.fillStyle = "#5d4a30";
      ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(x, y, w, 1);
      ctx.fillRect(x, y + h - 1, w, 1);
      // Books on shelves
      const colors = ["#b45c3c", "#6fb1c4", "#6ea05c", "#e9d8a6", "#8b6f47", "#5d6b62"];
      const rows = Math.floor((h - 2) / 7);
      for (let row = 0; row < rows; row++) {
        const ry = y + 2 + row * 7;
        let cx = x + 1;
        while (cx < x + w - 1) {
          const bookW = 2 + ((row * 11 + cx * 7) % 3);
          const colorIdx = (row + cx) % colors.length;
          ctx.fillStyle = colors[colorIdx];
          ctx.fillRect(cx, ry, bookW, 5);
          ctx.fillStyle = shade(colors[colorIdx], 0.3, "#1a120a");
          ctx.fillRect(cx, ry + 4, bookW, 1);
          cx += bookW + 1;
        }
        ctx.fillStyle = "#3a2716";
        ctx.fillRect(x, ry + 6, w, 1);
      }
    },
    plant: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      // Pot
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(x, y + h - 5, w, 5);
      ctx.fillStyle = "#8b6f47";
      ctx.fillRect(x + 1, y + h - 5, w - 2, 4);
      ctx.fillStyle = "#a37a4b";
      ctx.fillRect(x + 1, y + h - 5, w - 2, 1);
      // Leaves: cluster of triangles in two greens
      const greens = ["#6ea05c", "#8bbf72", "#547d44"];
      for (let i = 0; i < 6; i++) {
        const lx = x + 1 + (i % 3) * 3;
        const ly = y + h - 6 - Math.floor(i / 3) * 3;
        ctx.fillStyle = greens[i % greens.length];
        ctx.fillRect(lx, ly, 3, 4 - Math.floor(i / 3));
      }
    },
    tub: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      ctx.fillStyle = "#5d6b62";
      ctx.fillRect(x, y + h - 2, w, 2);
      ctx.fillStyle = "#f3e7c3";
      ctx.fillRect(x, y, w, h - 2);
      ctx.fillStyle = "#6fb1c4";
      ctx.fillRect(x + 2, y + 2, w - 4, h - 4);
      ctx.fillStyle = "#a4d2e0";
      ctx.fillRect(x + 3, y + 2, w - 6, 1);
      // Faucet
      ctx.fillStyle = "#5d6b62";
      ctx.fillRect(x + Math.floor(w / 2), y - 3, 1, 4);
    },
    toilet: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      ctx.fillStyle = "#f3e7c3";
      ctx.fillRect(x, y + h - 3, w, 3);
      ctx.fillStyle = "#fffbe9";
      ctx.fillRect(x, y, w, h - 3);
      ctx.fillStyle = "#cba46b";
      ctx.fillRect(x, y, w, 1);
    },
    window: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      // Frame, then glazing and a tiny outdoor skyline.
      ctx.fillStyle = "#675349";
      ctx.fillRect(x - 2, y - 2, w + 4, h + 4);
      ctx.fillStyle = "#b4d8e6";
      ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#8fbfd0";
      ctx.fillRect(x, y + h - 6, w, 6);
      ctx.fillStyle = "#789d90";
      for (let i=0; i<w; i+=9) ctx.fillRect(x+i,y+h-8-(i%5),6,8+(i%5));
      ctx.fillStyle = "#edf1dc";
      ctx.fillRect(x+3,y+3,5,1); ctx.fillRect(x+4,y+4,2,4);
      ctx.fillStyle = "#a37a4b";
      ctx.fillRect(x - 2, y - 2, w + 4, 1);
      // Mullion
      ctx.fillStyle = "#a37a4b";
      ctx.fillRect(x + Math.floor(w / 2) - 1, y, 2, h);
      // Sill
      ctx.fillStyle = "#8b6f47";
      ctx.fillRect(x - 2, y + h + 1, w + 4, 2);
      // Light beam coming in (warm interior reflection)
      ctx.fillStyle = "rgba(255, 215, 130, 0.15)";
      ctx.fillRect(x + 2, y + h, Math.floor(w * 0.6), 16);
    },
    curtain: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      ctx.fillStyle = "#b45c3c";
      ctx.fillRect(x, y, w, h);
      // Vertical folds
      ctx.fillStyle = shade("#b45c3c", 0.3, "#1a120a");
      for (let xx = 2; xx < w; xx += 4) {
        ctx.fillRect(x + xx, y, 1, h);
      }
      ctx.fillStyle = shade("#b45c3c", 0.4, "#f3e7c3");
      for (let xx = 4; xx < w; xx += 4) {
        ctx.fillRect(x + xx, y, 1, h);
      }
      // Rod
      ctx.fillStyle = "#a37a4b";
      ctx.fillRect(x - 1, y - 1, w + 2, 2);
    },
    picture: (ctx, it) => {
      const x = it.x, y = it.y, w = it.w, h = it.h;
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(x - 1, y - 1, w + 2, h + 2);
      ctx.fillStyle = "#f3e7c3";
      ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#6fb1c4";
      ctx.fillRect(x + 1, y + 1, w - 2, Math.floor(h * 0.6));
      ctx.fillStyle = "#6ea05c";
      ctx.fillRect(x + 1, y + Math.floor(h * 0.6), w - 2, Math.floor(h * 0.4) - 1);
    },
    books: (ctx, it) => {
      // Stack on a desk
      const x = it.x, y = it.y, w = it.w, h = it.h;
      const colors = ["#b45c3c", "#6fb1c4", "#6ea05c", "#e9d8a6"];
      ctx.fillStyle = colors[0];
      ctx.fillRect(x, y + h - 4, w, 4);
      ctx.fillStyle = shade(colors[0], 0.3, "#1a120a");
      ctx.fillRect(x, y + h - 4, w, 1);
      ctx.fillStyle = colors[1];
      ctx.fillRect(x + 1, y + h - 8, w - 2, 4);
      ctx.fillStyle = shade(colors[1], 0.3, "#1a120a");
      ctx.fillRect(x + 1, y + h - 8, w - 2, 1);
      ctx.fillStyle = colors[2];
      ctx.fillRect(x + 2, y + h - 12, w - 4, 4);
      ctx.fillStyle = shade(colors[2], 0.3, "#1a120a");
      ctx.fillRect(x + 2, y + h - 12, w - 4, 1);
    },
  };

  // Additional single-pixel details give the larger furniture visible depth.
  for (const kind of ["counter", "sofa", "sofa_table", "bed", "desk", "chair", "plant", "tub", "toilet"]) {
    const draw = SPRITE_DRAW[kind];
    SPRITE_DRAW[kind] = (ctx, it) => {
      const {x,y,w,h} = it;
      ctx.fillStyle = "rgba(37,30,34,0.18)"; ctx.fillRect(x+3,y+h,w,3);
      draw(ctx,it);
      if (kind === "counter") {
        ctx.fillStyle = "#b19b7a"; ctx.fillRect(x,y+h-8,w,6);
        for (let i=4; i<w; i+=24) {
          ctx.fillStyle = "#816e59"; ctx.fillRect(x+i,y+h-8,1,6);
          ctx.fillStyle = "#e8dbc2"; ctx.fillRect(x+i+8,y+h-6,6,1);
        }
      } else if (kind === "sofa") {
        ctx.fillStyle = "#a7af9a"; ctx.fillRect(x+5,y+3,w-10,7);
        ctx.fillStyle = "#717d71"; ctx.fillRect(x+5,y+9,w-10,1);
        ctx.fillStyle = "#819281"; ctx.fillRect(x+1,y+2,6,h-4); ctx.fillRect(x+w-7,y+2,6,h-4);
        ctx.fillStyle = "#e1bd89"; ctx.fillRect(x+12,y+12,13,11);
        ctx.fillStyle = "#bb8069"; ctx.fillRect(x+w-30,y+12,14,11);
        ctx.fillStyle = "#f0d5a5"; ctx.fillRect(x+13,y+13,11,1);
        ctx.fillStyle = "#6f796d"; ctx.fillRect(x+5,y+h-3,w-10,3);
      } else if (kind === "bed") {
        const blanket = it.blanket || "#7888a0";
        ctx.fillStyle = "#806b58"; ctx.fillRect(x,y-3,w,5);
        ctx.fillStyle = "#f4ebd9";
        ctx.fillRect(x+10,y+7,24,12); ctx.fillRect(x+w-34,y+7,24,12);
        ctx.fillStyle = "#cfc7b7"; ctx.fillRect(x+10,y+18,24,1); ctx.fillRect(x+w-34,y+18,24,1);
        ctx.fillStyle = blanket; ctx.fillRect(x+2,y+24,w-4,h-28);
        ctx.fillStyle = shade(blanket,0.23,"#f9e9ce");
        ctx.fillRect(x+2,y+24,w-4,3);
        for(let i=8;i<w-4;i+=12) ctx.fillRect(x+i,y+29,1,h-35);
        ctx.fillStyle = shade(blanket,0.2,"#33323b"); ctx.fillRect(x+2,y+h-5,w-4,2);
      } else if (kind === "desk") {
        ctx.fillStyle = "#574b45"; ctx.fillRect(x+18,y+3,24,12);
        ctx.fillStyle = "#9dbdc4"; ctx.fillRect(x+20,y+5,20,8);
        ctx.fillStyle = "#d8d9cc"; ctx.fillRect(x+18,y+15,24,3);
        ctx.fillStyle = "#52656e"; ctx.fillRect(x+23,y+16,14,1);
        ctx.fillStyle = "#f4ead3"; ctx.fillRect(x+w-23,y+5,16,10);
        ctx.fillStyle = "#acb4a0"; ctx.fillRect(x+w-20,y+7,10,1); ctx.fillRect(x+w-20,y+10,8,1);
      } else if (kind === "sofa_table") {
        ctx.fillStyle = "#785f4e"; ctx.fillRect(x+2,y+h-7,w-4,4);
        ctx.fillStyle = "#dac099"; ctx.fillRect(x+2,y+1,w-4,1);
        if(w>40) {
          ctx.fillStyle = "#738f86"; ctx.fillRect(x+w-23,y+4,14,8);
          ctx.fillStyle = "#e8dec5"; ctx.fillRect(x+w-21,y+5,10,1);
          ctx.fillStyle = "#b87553"; ctx.fillRect(x+18,y+4,8,5);
        }
      } else if (kind === "chair") {
        ctx.fillStyle = "#a3ac96"; ctx.fillRect(x+2,y+2,w-4,3);
        ctx.fillStyle = "#7a8979"; ctx.fillRect(x+2,y+6,w-4,h-10);
        ctx.fillStyle = "#443d3a"; ctx.fillRect(x+1,y+h-2,2,3); ctx.fillRect(x+w-3,y+h-2,2,3);
      } else if (kind === "plant") {
        ctx.fillStyle = "#567652"; ctx.fillRect(x+w/2-1,y+6,2,h-10);
        for(let i=0;i<4;i++) {
          ctx.fillStyle = i%2 ? "#88a66c" : "#6e915f";
          ctx.fillRect(x+(i%2 ? w/2 : 2),y+3+i*4,w/2-2,5);
          ctx.fillStyle = "#b6c38d"; ctx.fillRect(x+(i%2 ? w/2+1 : 3),y+4+i*4,3,1);
        }
      } else if (kind === "tub") {
        ctx.fillStyle = "#e5e6d6"; ctx.fillRect(x+1,y+h-6,w-2,4);
        ctx.fillStyle = "#d2ebdf"; ctx.fillRect(x+8,y+8,9,1); ctx.fillRect(x+w-18,y+14,10,1);
        ctx.fillStyle = "#f8f2db"; ctx.fillRect(x+w-12,y+3,7,3);
      } else if (kind === "toilet") {
        ctx.fillStyle = "#abb9b4"; ctx.fillRect(x+3,y+3,w-6,5);
        ctx.fillStyle = "#d4ddd0"; ctx.fillRect(x+4,y+12,w-8,h-18);
        ctx.fillStyle = "#adc6c3"; ctx.fillRect(x+6,y+15,w-12,h-24);
      }
    };
  }

  // When the player clicks a piece of furniture in the canvas we offer a
  // short menu of activities that piece supports. The menu is built from
  // this table: ``activities`` is shown to the player; the first one is
  // the default. ``room`` lets us override the activity's natural room
  // (e.g. clicking a tub still maps to ``bath``). The ``label`` is the
  // action verb the prompt and dialog use ("打开电视", "看书", ...).
  const FURNITURE_ACTION = {
    tv:        { label: "看电视/追剧",   activities: ["看电视", "追剧"],      room: "living" },
    sofa:      { label: "坐下刷手机",    activities: ["刷短视频"],            room: "living" },
    sofa_table:{ label: "喝一杯",        activities: ["泡茶"],                room: "kitchen" },
    tv_stand:  { label: "路过电视柜",    activities: ["看电视", "追剧"],      room: "living" },
    stove:     { label: "做顿饭",        activities: ["做早餐", "做午餐", "做晚餐"], room: "kitchen" },
    sink:      { label: "洗东西",        activities: ["洗衣服"],              room: "bath" },
    fridge:    { label: "拿点吃的",      activities: ["吃早餐", "吃午餐", "吃晚餐"], room: "kitchen" },
    counter:   { label: "做饭",          activities: ["做早餐", "做午餐", "做晚餐"], room: "kitchen" },
    bed:       { label: "休息",          activities: ["午睡", "睡前阅读"],     room: null /* wherever the bed is */ },
    tub:       { label: "洗澡",          activities: ["洗澡"],                room: "bath" },
    toilet:    { label: "上厕所",        activities: ["发呆"],                room: "bath" },
    desk:      { label: "坐下工作/学习", activities: ["看书", "写日记", "处理工作邮件", "画一会儿画", "练琴"], room: null },
    chair:     { label: "坐下来",        activities: ["看书", "发呆"],        room: null },
    books:     { label: "翻书",          activities: ["看书"],                room: null },
    shelf:     { label: "拿本书",        activities: ["看书"],                room: "study" },
    plant:     { label: "浇花/看窗外",   activities: ["看窗外"],              room: null },
    picture:   { label: "看画",          activities: ["发呆"],                room: null },
    window:    { label: "看窗外",        activities: ["看窗外"],              room: null },
  };
  // Sprites drawn over furniture (rugs, windows, etc.) — not clickable
  // on their own; clicking them falls through to the furniture below.
  const NON_INTERACTIVE_KINDS = new Set([
    "rug", "curtain", "picture_frame", "railing"
  ]);

  // Sprites use absolute pixel coordinates (no tile math). Replaces the
  // older per-tile recipe with per-pixel layouts that read as proper
  // pixel art rather than coloured rectangles.
  const SPRITES = {
    kitchen: [
      {kind:"window",x:66,y:20,w:44,h:26},
      {kind:"counter",x:24,y:54,w:140,h:24},
      {kind:"stove",x:46,y:54,w:30,h:24},
      {kind:"sink",x:112,y:54,w:32,h:24},
      {kind:"fridge",x:24,y:90,w:28,h:48},
      {kind:"sofa_table",x:86,y:114,w:64,h:22},
      {kind:"chair",x:86,y:146,w:16,h:14},
      {kind:"chair",x:130,y:146,w:16,h:14},
      {kind:"plant",x:150,y:88,w:14,h:20},
      {kind:"rug",x:60,y:84,w:86,h:16},
    ],
    living: [
      {kind:"window",x:202,y:20,w:40,h:26},
      {kind:"curtain",x:200,y:20,w:12,h:26},
      {kind:"rug",x:212,y:80,w:142,h:66},
      {kind:"sofa",x:208,y:58,w:110,h:34},
      {kind:"sofa_table",x:230,y:114,w:72,h:20},
      {kind:"tv_stand",x:336,y:88,w:44,h:14},
      {kind:"tv",x:338,y:58,w:40,h:30},
      {kind:"plant",x:366,y:136,w:16,h:24},
    ],
    master: [
      {kind:"bed",x:416,y:68,w:84,h:56,blanket:"#7888a0"},
      {kind:"lamp",x:416,y:128,w:12,h:18},
      {kind:"shelf",x:474,y:136,w:26,h:28},
      {kind:"rug",x:430,y:130,w:40,h:30},
    ],
    second: [
      {kind:"bed",x:532,y:58,w:84,h:52,blanket:"#9a887f"},
      {kind:"desk",x:532,y:128,w:68,h:18},
      {kind:"chair",x:542,y:150,w:16,h:16},
      {kind:"books",x:576,y:130,w:14,h:12},
      {kind:"lamp",x:600,y:132,w:10,h:14},
      {kind:"rug",x:534,y:116,w:74,h:12},
    ],
    study: [
      {kind:"window",x:58,y:258,w:42,h:24},
      {kind:"desk",x:32,y:296,w:94,h:22},
      {kind:"chair",x:48,y:324,w:20,h:18},
      {kind:"chair",x:90,y:324,w:20,h:18},
      {kind:"books",x:102,y:298,w:16,h:14},
      {kind:"lamp",x:36,y:288,w:12,h:16},
      {kind:"shelf",x:136,y:284,w:40,h:64},
      {kind:"plant",x:26,y:348,w:16,h:24},
      {kind:"rug",x:50,y:320,w:66,h:42},
    ],
    bath: [
      {kind:"tub",x:212,y:284,w:68,h:40},
      {kind:"toilet",x:296,y:282,w:20,h:30},
      {kind:"sink",x:212,y:344,w:32,h:20},
      {kind:"rug",x:250,y:334,w:54,h:30},
      {kind:"plant",x:300,y:352,w:14,h:20},
    ],
    balcony: [
      {kind:"plant",x:350,y:284,w:20,h:30},
      {kind:"plant",x:384,y:298,w:16,h:24},
      {kind:"plant",x:466,y:280,w:18,h:28},
      {kind:"chair",x:440,y:326,w:24,h:20},
      {kind:"sofa_table",x:396,y:330,w:30,h:18},
      {kind:"plant",x:352,y:348,w:18,h:26},
    ],
    hallway: [],
  };

  function paintAtmosphere(ctx, room) {
    const win = (SPRITES[room.id] || []).find(it => it.kind === "window");
    if (!win) return;
    for (let i=0; i<6; i++) {
      ctx.fillStyle = `rgba(255, 242, 186, ${0.12-i*0.016})`;
      ctx.fillRect(win.x+i*3, win.y+win.h+i*8, win.w+8, 8);
    }
  }

  // ----- animation system -----
  // requestAnimationFrame loop drives the canvas. The server keeps
  // providing discrete "tick" updates; the canvas smooths them by lerping
  // every sprite from its old to its new position over ~1.2 s, with a
  // 2-frame walk cycle while moving and a breathing idle frame while
  // standing still.
  function startFrameLoop() {
    if (state.rafId) cancelAnimationFrame(state.rafId);
    const tick = (now) => {
      state.frameStamp = now;
      try {
        paintFrame(now);
      } catch (err) {
        // Defensive — a single broken frame must not stop the loop.
        const sig = (err && (err.stack || err.message)) || String(err);
        if (window.__RM_FRAME_ERR !== sig) {
          window.__RM_FRAME_ERR = sig;
          console.error("paintFrame error:", sig);
        }
      }
      state.rafId = requestAnimationFrame(tick);
    };
    state.rafId = requestAnimationFrame(tick);
  }

  function stopFrameLoop() {
    if (state.rafId) cancelAnimationFrame(state.rafId);
    state.rafId = null;
  }

  function paintFrame(now) {
    const ctx = getCtx();
    if (!ctx || !state.session) return;
    try {
      retargetSprites();
      // Static apartment is cached on an offscreen canvas — paint it as
      // a single image blit, then layer the moving pieces on top.
      const cache = getBgCache();
      ctx.imageSmoothingEnabled = false;
      ctx.fillStyle = "#1a120a";
      ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
      ctx.drawImage(cache, 0, 0);
      paintAmbient(now);
      paintResidentsOnce(now);
      paintNightOverlay();
      // Repaint speech bubbles too — they depend on which residents are
      // chatting, and the anchor can shift as the sprite moves.
      renderBubbles();
    } catch (err) {
      // A single broken frame must not stop the loop — log once per
      // error class so we can spot a runaway bug without spamming.
      const sig = (err && (err.stack || err.message)) || String(err);
      if (window.__RM_LAST_ERR !== sig) {
        window.__RM_LAST_ERR = sig;
        console.error("paintFrame error:", sig);
      }
    }
  }

  // Animated ambient details drawn on top of the cached apartment each
  // frame: stove flame flicker, TV screen flicker, dust drifting. These
  // are cheap (a few pixels each) but they sell the "the apartment is
  // alive even when nobody's moving" feeling.
  function paintAmbient(now) {
    const ctx = getCtx();
    if (!ctx) return;
    const t = now / 380;
    const stove = SPRITES.kitchen.find(it => it.kind === "stove");
    if ((state.session.residents || []).some(r => r.room === "kitchen" && pickPose(r,false,false) === "cooking")) {
      ctx.fillStyle = Math.floor(t)%2 ? "#ff6e2a" : "#f3b04a";
      ctx.fillRect(stove.x+4, stove.y+3, stove.w-8, 1);
    }
    const tv = SPRITES.living.find(it => it.kind === "tv");
    ctx.fillStyle = `rgba(110, 200, 230, ${0.12+0.08*Math.sin(t)})`;
    ctx.fillRect(tv.x+3, tv.y+3, tv.w-6, tv.h-8);
    ctx.fillStyle = "rgba(255,255,255,0.12)";
    ctx.fillRect(tv.x+3, tv.y+3+((now/90)%(tv.h-8)|0), tv.w-6, 1);
  }

  // Resident positions: each frame, ease the sprite toward its current
  // target, advance to the next waypoint when arrived, then draw.
  function paintResidentsOnce(now) {
    const ctx = getCtx();
    if (!ctx) return;
    const residents = [...(state.session.residents || [])].sort((a,b) =>
      (state.sprites[a.agent_id]?.y || 0) - (state.sprites[b.agent_id]?.y || 0));
    for (const r of residents) {
      const sp = state.sprites[r.agent_id];
      if (!sp) continue;
      // Clamp the sprite to the apartment bounds — defensive against any
      // path that briefly steps outside (e.g. mid-corridor between two
      // doors). Without this, a path that lands off-screen leaves the
      // sprite walking into the void.
      sp.x = Math.max(12, Math.min(CANVAS_W - 12, sp.x));
      sp.y = Math.max(36, Math.min(CANVAS_H - 10, sp.y));
      // Advance toward the current waypoint.
      if (sp.isMoving) {
        const elapsed = (now - sp.tStart) / sp.ms;
        const t = Math.min(1, Math.max(0, elapsed));
        const ease = t * t * (3 - 2 * t); // smoothstep
        sp.x = sp.fromX + (sp.tx - sp.fromX) * ease;
        sp.y = sp.fromY + (sp.ty - sp.fromY) * ease;
        sp.walkFrame = Math.floor((now / 220) % 2);
        if (t >= 1) {
          // Waypoint reached — advance to the next leg or finish.
          sp.pathIdx = (sp.pathIdx || 0) + 1;
          sp.x = sp.tx;
          sp.y = sp.ty;
          // Defensive cap: a path that's longer than 32 hops is almost
          // certainly broken. Bail out so we don't paint forever.
          if (sp.path && sp.pathIdx < sp.path.length && sp.pathIdx < 32) {
            const next = sp.path[sp.pathIdx];
            const samePoint = (next.x === sp.x && next.y === sp.y);
            if (samePoint && sp.pathIdx + 1 < sp.path.length) {
              sp.pathIdx += 1;
            }
            const nxt = sp.path[sp.pathIdx];
            sp.fromX = sp.x;
            sp.fromY = sp.y;
            sp.tx = nxt.x;
            sp.ty = nxt.y;
            sp.tStart = now;
            const segLen = Math.hypot(sp.tx - sp.fromX, sp.ty - sp.fromY);
            sp.ms = Math.max(300, Math.min(1200, segLen * 6));
          } else {
            sp.isMoving = false;
            sp.path = null;
          }
        }
      } else {
        // Idle bob: ±1 px vertical.
        sp.bob = Math.sin(now / 600) * 1.0;
      }
      const isNight = !!state.session.is_night;
      const pose = pickPose(r, sp.isMoving, isNight);
      drawResident(ctx, sp.x, sp.y + (sp.isMoving ? 0 : (sp.bob || 0)), r, pose, sp.walkFrame, isNight);
    }
  }

  // Pick the sprite pose from the resident's current activity.
  // ``moving`` overrides the static pose with a walk-cycle frame.
  function pickPose(r, moving, isNight) {
    if (moving) return "walking";
    const a = r.activity || "";
    if (/睡觉|午睡|休息睡眠/.test(a)) return "sleeping";
    if (/做饭|做早餐|做午餐|做晚餐|烹饪|准备.*餐/.test(a)) return "cooking";
    if (/吃|用餐|享用/.test(a)) return "eating";
    if (/健身|锻炼|瑜伽/.test(a)) return "exercise";
    if (/看书|阅读|日记|邮件|工作|学习/.test(a)) return "reading";
    if (/电视|刷|追剧|电话/.test(a)) return "phone";
    return "standing";
  }

  function residentAppearance(r) {
    const id = Math.abs(Number(r.agent_id) || 0);
    const shirts = ["#6f9190", "#bd785b", "#7786b0", "#87966b", "#b58ba0", "#c3a365"];
    const skins = ["#edc5a5", "#d8aa86", "#f0cfb3", "#c99673"];
    return {skin: skins[id%skins.length], hair: Number(r.age)>=60 ? "#aaa8a1" :
      ["#342d2c", "#6a4938", "#493e3b"][id%3], shirt: shirts[id%shirts.length],
      pants: ["#405061", "#594d53", "#536158"][id%3], shoe: "#34353d"};
  }

  // 24x40 character sprite with several poses. The standing / sleeping /
  // reading / cooking frames share a head + torso template and swap in
  // different arms, props (book / pan / phone), or rotation. ``walkFrame``
  // is 0 or 1 and flips the legs.
  function drawResident(ctx, x, y, r, pose, walkFrame, isNight) {
    const look = residentAppearance(r);
    const skin = look.skin;
    const skinShade = shade(skin, 0.24, "#754d3b");
    const hair = look.hair;
    const hairShade = shade(hair, 0.16, "#211c28");
    const shirt = look.shirt;
    const shirtShade = shade(shirt, 0.24, "#282936");
    const shirtLight = shade(shirt, 0.35, "#fff0d0");
    const pants = look.pants;
    const pantsLight = shade(pants, 0.2, "#f3e7c3");
    const shoe = look.shoe;
    // Foot-point coordinates keep walking, furniture and bubbles aligned.
    x = Math.round(x)-10;
    y = Math.round(y)-(pose === "sleeping" ? 16 : 30);

    if (pose === "sleeping") {
      // Head lies on the pillow; the matching bed blanket covers the body.
      const bx=x+4, by=y-12;
      ctx.fillStyle = "#f5ead6"; ctx.fillRect(bx-2,by-1,16,10);
      ctx.fillStyle = skinShade; ctx.fillRect(bx+2,by,8,9);
      ctx.fillStyle = skin; ctx.fillRect(bx+3,by+2,6,6);
      ctx.fillStyle = hair; ctx.fillRect(bx+2,by,8,3);
      ctx.fillStyle = "#4e4544"; ctx.fillRect(bx+4,by+5,2,1); ctx.fillRect(bx+7,by+5,2,1);
      ctx.fillStyle = shade(shirt,0.25,"#e8dbc8"); ctx.fillRect(bx-1,by+10,14,16);
      ctx.fillStyle = shirtLight; ctx.fillRect(bx-1,by+10,14,2);
      ctx.fillStyle = shirtShade; ctx.fillRect(bx+2,by+14,1,9); ctx.fillRect(bx+9,by+14,1,9);
      paintResidentName(ctx,x+10,by-6,r);
      return;
    }

    // Shadow (round ellipse on the floor)
    ctx.fillStyle = "rgba(0, 0, 0, 0.32)";
    ctx.beginPath();
    ctx.ellipse(x + 10, y + 32, 9, 2, 0, 0, Math.PI * 2);
    ctx.fill();

    // Legs (pose-dependent)
    ctx.fillStyle = pants;
    if (pose === "walking") {
      if (walkFrame === 0) {
        ctx.fillRect(x + 6, y + 22, 3, 6);
        ctx.fillRect(x + 11, y + 24, 3, 6);
      } else {
        ctx.fillRect(x + 6, y + 24, 3, 6);
        ctx.fillRect(x + 11, y + 22, 3, 6);
      }
    } else if (pose === "reading" || pose === "phone") {
      // Seated: cross-legged stub
      ctx.fillRect(x + 6, y + 26, 3, 3);
      ctx.fillRect(x + 11, y + 26, 3, 3);
      ctx.fillRect(x + 6, y + 22, 3, 5);
      ctx.fillRect(x + 11, y + 22, 3, 5);
    } else if (pose === "cooking") {
      // Standing, slight stagger
      ctx.fillRect(x + 6, y + 24, 3, 5);
      ctx.fillRect(x + 11, y + 24, 3, 5);
    } else {
      ctx.fillRect(x + 6, y + 24, 3, 5);
      ctx.fillRect(x + 11, y + 24, 3, 5);
    }
    // Shoes / pants highlight
    ctx.fillStyle = shoe;
    ctx.fillRect(x + 5, y + 28, 5, 2);
    ctx.fillRect(x + 10, y + 28, 5, 2);
    ctx.fillStyle = pantsLight;
    ctx.fillRect(x + 6, y + 22, 1, walkFrame === 1 ? 6 : (pose === "walking" ? 4 : 5));

    // Torso (10 wide, 12 tall, with collar V-neck)
    ctx.fillStyle = shirtShade;
    ctx.fillRect(x + 4, y + 12, 12, 12);
    ctx.fillStyle = shirt;
    ctx.fillRect(x + 5, y + 12, 10, 12);
    ctx.fillStyle = shirtLight;
    ctx.fillRect(x + 5, y + 12, 10, 1);
    // Collar V
    ctx.fillStyle = "#1a120a";
    ctx.fillRect(x + 8, y + 12, 1, 1);
    ctx.fillRect(x + 11, y + 12, 1, 1);

    // Arms by pose
    if (pose === "walking") {
      // Arms swing opposite to legs.
      if (walkFrame === 0) {
        ctx.fillStyle = shirtShade;
        ctx.fillRect(x + 3, y + 14, 2, 5);
        ctx.fillRect(x + 15, y + 16, 2, 5);
        ctx.fillStyle = skin;
        ctx.fillRect(x + 3, y + 19, 2, 2);
        ctx.fillRect(x + 15, y + 21, 2, 2);
      } else {
        ctx.fillStyle = shirtShade;
        ctx.fillRect(x + 3, y + 16, 2, 5);
        ctx.fillRect(x + 15, y + 14, 2, 5);
        ctx.fillStyle = skin;
        ctx.fillRect(x + 3, y + 21, 2, 2);
        ctx.fillRect(x + 15, y + 19, 2, 2);
      }
    } else if (pose === "reading") {
      // Both arms forward, holding a small book.
      ctx.fillStyle = shirtShade;
      ctx.fillRect(x + 4, y + 18, 3, 4);
      ctx.fillRect(x + 13, y + 18, 3, 4);
      ctx.fillStyle = skin;
      ctx.fillRect(x + 6, y + 20, 2, 2);
      ctx.fillRect(x + 12, y + 20, 2, 2);
      // Book
      ctx.fillStyle = "#e9d8a6";
      ctx.fillRect(x + 5, y + 18, 10, 4);
      ctx.fillStyle = "#b45c3c";
      ctx.fillRect(x + 5, y + 18, 10, 1);
      ctx.fillStyle = "#1a120a";
      ctx.fillRect(x + 6, y + 20, 1, 1);
      ctx.fillRect(x + 9, y + 20, 1, 1);
      ctx.fillRect(x + 12, y + 20, 1, 1);
      ctx.fillRect(x + 7, y + 21, 1, 1);
      ctx.fillRect(x + 11, y + 21, 1, 1);
    } else if (pose === "phone") {
      // Right arm up holding phone.
      ctx.fillStyle = shirtShade;
      ctx.fillRect(x + 3, y + 14, 2, 4);
      ctx.fillRect(x + 14, y + 12, 2, 4);
      ctx.fillStyle = skin;
      ctx.fillRect(x + 3, y + 18, 2, 2);
      ctx.fillRect(x + 14, y + 10, 2, 3);
      // Phone in right hand
      ctx.fillStyle = "#1a120a";
      ctx.fillRect(x + 13, y + 9, 4, 3);
      ctx.fillStyle = "#6fb1c4";
      ctx.fillRect(x + 14, y + 10, 2, 1);
    } else if (pose === "cooking") {
      // Left arm forward holding a pan, right arm to side.
      ctx.fillStyle = shirtShade;
      ctx.fillRect(x + 3, y + 14, 2, 4);
      ctx.fillRect(x + 12, y + 16, 3, 4);
      ctx.fillStyle = skin;
      ctx.fillRect(x + 3, y + 18, 2, 2);
      ctx.fillRect(x + 15, y + 20, 2, 2);
      // Pan
      ctx.fillStyle = "#1a120a";
      ctx.fillRect(x + 4, y + 17, 6, 3);
      ctx.fillStyle = "#3a2716";
      ctx.fillRect(x + 3, y + 19, 1, 2);
      // Steam
      ctx.fillStyle = "rgba(255, 255, 255, 0.5)";
      ctx.fillRect(x + 6, y + 14, 1, 2);
      ctx.fillRect(x + 8, y + 13, 1, 2);
    } else if (pose === "eating") {
      ctx.fillStyle = skin; ctx.fillRect(x+4,y+18,3,4); ctx.fillRect(x+13,y+18,3,4);
      ctx.fillStyle = "#f7ead7"; ctx.fillRect(x+6,y+19,8,4);
      ctx.fillStyle = "#738d80"; ctx.fillRect(x+7,y+22,6,1);
      ctx.fillStyle = "#dcaa60"; ctx.fillRect(x+8,y+19,4,1);
      ctx.fillStyle = "#604637"; ctx.fillRect(x+14,y+15,1,5);
    } else if (pose === "exercise") {
      ctx.fillStyle = shirtShade; ctx.fillRect(x+2,y+13,3,3); ctx.fillRect(x+15,y+13,3,3);
      ctx.fillStyle = skin; ctx.fillRect(x+1,y+8,2,7); ctx.fillRect(x+17,y+8,2,7);
      ctx.fillStyle = "#647181"; ctx.fillRect(x-1,y+6,6,3); ctx.fillRect(x+15,y+6,6,3);
    } else {
      // Default standing: arms at sides.
      ctx.fillStyle = shirtShade;
      ctx.fillRect(x + 3, y + 13, 2, 6);
      ctx.fillRect(x + 15, y + 13, 2, 6);
      ctx.fillStyle = skin;
      ctx.fillRect(x + 3, y + 19, 2, 2);
      ctx.fillRect(x + 15, y + 19, 2, 2);
    }

    // Shirt buttons, hem, stitched jeans and light sneaker soles.
    ctx.fillStyle = shirtLight; ctx.fillRect(x+9,y+15,1,1); ctx.fillRect(x+9,y+18,1,1);
    ctx.fillStyle = shirtShade; ctx.fillRect(x+5,y+23,10,1);
    ctx.fillStyle = pantsLight; ctx.fillRect(x+12,y+24,1,3);
    ctx.fillStyle = "#d9d0be"; ctx.fillRect(x+5,y+30,5,1); ctx.fillRect(x+10,y+30,5,1);
    // Head (10 wide, 12 tall)
    ctx.fillStyle = skinShade;
    ctx.fillRect(x + 5, y + 1, 10, 12);
    ctx.fillStyle = skin;
    ctx.fillRect(x + 6, y + 1, 8, 12);
    // Hair
    ctx.fillStyle = hairShade;
    if (r.gender === "女") {
      // Long hair: covers top, falls down both sides to shoulder.
      ctx.fillRect(x + 5, y + 1, 10, 3);
      ctx.fillRect(x + 4, y + 1, 1, 9);
      ctx.fillRect(x + 15, y + 1, 1, 9);
      // Highlight
      ctx.fillStyle = shade(hair, 0.4, "#f3e7c3");
      ctx.fillRect(x + 7, y + 2, 3, 1);
    } else {
      // Short: top + a fringe tuft.
      ctx.fillRect(x + 5, y + 1, 10, 3);
      ctx.fillRect(x + 7, y + 4, 5, 1);
      ctx.fillStyle = shade(hair, 0.3, "#f3e7c3");
      ctx.fillRect(x + 8, y + 2, 2, 1);
    }
    if (Math.abs(Number(r.agent_id)||0)%3 === 0) {
      ctx.fillStyle = hair; ctx.fillRect(x+13,y+3,3,6);
      ctx.fillStyle = shirtLight; ctx.fillRect(x+15,y+5,1,2);
    }
    if (Number(r.age)>=45) {
      ctx.strokeStyle = "#544d53"; ctx.lineWidth = 1;
      ctx.strokeRect(x+7,y+6,3,3); ctx.strokeRect(x+11,y+6,3,3);
    }
    // Eyes (open by default; closed when sleeping — handled in sleeping pose)
    ctx.fillStyle = "#1a120a";
    if (pose === "reading" || pose === "phone") {
      // Looking down — eyes shifted.
      ctx.fillRect(x + 8, y + 7, 1, 1);
      ctx.fillRect(x + 11, y + 7, 1, 1);
    } else {
      ctx.fillRect(x + 8, y + 6, 1, 1);
      ctx.fillRect(x + 11, y + 6, 1, 1);
    }
    // Eyebrows
    ctx.fillStyle = hair;
    ctx.fillRect(x + 8, y + 5, 1, 1);
    ctx.fillRect(x + 11, y + 5, 1, 1);
    // Mouth — smile / flat / frown
    ctx.fillStyle = "#1a120a";
    if (r.mood > 0.2) {
      ctx.fillRect(x + 9, y + 9, 2, 1);
    } else if (r.mood < -0.2) {
      ctx.fillRect(x + 9, y + 10, 2, 1);
      ctx.fillStyle = skin;
      ctx.fillRect(x + 9, y + 9, 2, 1);
    } else {
      ctx.fillRect(x + 9, y + 10, 1, 1);
    }
    // Cheek blush
    ctx.fillStyle = "rgba(180, 90, 80, 0.25)";
    ctx.fillRect(x + 6, y + 8, 2, 1);
    ctx.fillRect(x + 12, y + 8, 2, 1);

    paintResidentName(ctx, x+10, y-11, r);
    // Mood bar above head (10 wide, 3 tall)
    drawMoodBar(ctx, x + 5, y - 4, r.mood, moodColor(r.mood), "#f3e7c3");
  }

  function paintResidentName(ctx, x, y, r) {
    const name = String(r.name || "").slice(0,6);
    ctx.font = "8px sans-serif";
    const w = Math.ceil(ctx.measureText(name).width)+6;
    ctx.fillStyle = "rgba(46,42,42,0.78)"; ctx.fillRect(Math.round(x-w/2),Math.round(y)-7,w,10);
    ctx.fillStyle = "#fff3d9"; ctx.textAlign = "center";
    ctx.fillText(name,Math.round(x),Math.round(y)); ctx.textAlign = "start";
  }

  function drawMoodBar(ctx, x, y, mood, color, light) {
    ctx.fillStyle = "#1a120a";
    ctx.fillRect(x, y, 10, 3);
    const fill = Math.max(0, Math.min(10, Math.round((mood + 1) * 5)));
    ctx.fillStyle = color;
    ctx.fillRect(x, y, fill, 3);
    ctx.fillStyle = light;
    ctx.fillRect(x, y, fill, 1);
  }

  // Night overlay: a single dark blue alpha rectangle over the whole
  // canvas. ``alpha`` comes from the session's ``night_progress`` value
  // the server computes from the virtual clock.
  function paintNightOverlay() {
    const ctx = getCtx();
    if (!ctx || !state.session) return;
    const p = state.session.night_progress || 0;
    if (p <= 0) return;
    ctx.fillStyle = "rgba(15, 22, 50, " + (0.55 * p).toFixed(3) + ")";
    ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
  }

  // Cached canvas-to-stage geometry. Reading ``getBoundingClientRect``
  // every frame forces a synchronous layout / reflow — at 30 fps with
  // N bubbles, that is 60N layouts per second, which is what froze the
  // page when a session went live. The cache invalidates on resize.
  const _geo = { rect: null, stage: null, scaleX: 1, scaleY: 1, offsetX: 0, offsetY: 0, valid: false };
  function _refreshGeometry() {
    const canvas = $("#rCanvas");
    if (!canvas) return false;
    const rect = canvas.getBoundingClientRect();
    const stage = canvas.parentElement ? canvas.parentElement.getBoundingClientRect() : null;
    _geo.rect = rect;
    _geo.stage = stage;
    _geo.scaleX = rect.width / CANVAS_W;
    _geo.scaleY = rect.height / CANVAS_H;
    _geo.offsetX = (stage ? rect.left - stage.left : 0);
    _geo.offsetY = (stage ? rect.top - stage.top : 0);
    _geo.valid = true;
    return true;
  }
  window.addEventListener("resize", () => { _geo.valid = false; });
  window.addEventListener("scroll", () => { _geo.valid = false; }, true);
  // Two-axis scroll can move the canvas too; cheap to refresh on each
  // frame the bubbles fire (we still avoid the per-bubble read).
  function _maybeRefreshGeometry() {
    if (!_geo.valid) _refreshGeometry();
  }

  function bubbleAnchor(agentId) {
    const sp = state.sprites[agentId];
    if (!sp) return null;
    _maybeRefreshGeometry();
    if (!_geo.valid) return null;
    // Anchor above the head: head is at sprite y, draw is 28 px tall.
    const x = sp.x;
    const y = Math.max(12, sp.y - 38);
    return {
      x: _geo.offsetX + x * _geo.scaleX,
      y: _geo.offsetY + y * _geo.scaleY,
    };
  }

  const bubbleSizes = new WeakMap();
  function positionBubble(node, anchor) {
    const width=_geo.stage?.width || _geo.rect.width;
    let size=bubbleSizes.get(node);
    if (!size || size.stageWidth!==width) {
      size={w:node.offsetWidth,h:node.offsetHeight,stageWidth:width};
      bubbleSizes.set(node,size);
    }
    node.style.left=Math.max(size.w/2+8,Math.min(width-size.w/2-8,anchor.x))+"px";
    node.style.top=Math.max(size.h+8,anchor.y)+"px";
  }

  function renderBubbles() {
    const layer = $("#rBubbles");
    if (!layer || !state.session) return;
    // Pick the most recent conversation-shaped event (interact / direct).
    const events = state.session.events || [];
    const last = events.slice().reverse().find((e) => e && (e.kind === "interact" || e.kind === "direct"));
    if (!last) {
      // No conversation yet — drop any stale bubbles once.
      if (state.bubbleBuiltSeq !== 0) {
        layer.querySelectorAll(".speech-bubble").forEach(node => node.remove());
        state.bubbleBuiltSeq = 0;
      }
      return;
    }
    const turns = Array.isArray(last.turns) ? last.turns : [];
    const turnCount = turns.length;
    // Reset the playback cursor whenever the highlighted event changes.
    if (state.bubbleTurnEventId !== last.seq) {
      state.bubbleTurnEventId = last.seq;
      state.bubbleTurnIdx = turnCount > 1 ? 0 : -1;
      state.bubbleTurnTimer = state.frameStamp;
    }
    // When there are several turns, advance the cursor every 2 s so the
    // viewer sees both sides of the conversation.
    let activeTurn = null;
    if (turnCount > 1 && state.bubbleTurnIdx >= 0) {
      const elapsed = state.frameStamp - state.bubbleTurnTimer;
      if (elapsed > 2000) {
        state.bubbleTurnIdx = (state.bubbleTurnIdx + 1) % turnCount;
        state.bubbleTurnTimer = state.frameStamp;
      }
      activeTurn = turns[state.bubbleTurnIdx] || null;
    } else if (turnCount === 1) {
      activeTurn = turns[0];
    }

    // Build a fresh payload whenever the event identity, turn cursor, or
    // per-turn active state changes. Otherwise the frame just nudges the
    // bubble positions, which is cheap. The old version rebuilt innerHTML
    // every frame — at 30 fps that was ~30 full DOM rebuilds per second
    // and is what froze the page once a few multi-turn events queued up.
    const cursorKey = turnCount > 1 ? state.bubbleTurnIdx : -1;
    const payloadKey = last.seq + ":" + cursorKey;
    if (state.bubbleBuiltKey !== payloadKey) {
      state.bubbleBuiltKey = payloadKey;
      state.bubbleBuiltSeq = last.seq;
      layer.querySelectorAll(".speech-bubble").forEach(node => node.remove());
      const actors = last.actor_ids || [];
      const thought = String(last.thought || "");
      const tparts = thought.split("|").map((s) => String(s || "").trim()).filter(Boolean);
      // Map each speaker to their bubble slot; we keep them in DOM order
      // so position churn later just updates left/top, not innerHTML.
      state.bubbleSlots = [];
      if (turnCount > 1) {
        const seenAnchors = new Set();
        for (const t of turns) {
          const whoName = String(t && t.who || "");
          const resident = (state.session.residents || []).find((r) => r.name === whoName);
          const aid = resident ? resident.agent_id : (actors[0] || null);
          const anchor = bubbleAnchor(aid);
          if (!anchor || seenAnchors.has(whoName)) continue;
          seenAnchors.add(whoName);
          const myThought = tparts.find((p) => p.indexOf(whoName + ":") === 0) || "";
          const thoughtText = String(myThought || "").split(":").slice(1).join(":").trim();
          const isActive = activeTurn && activeTurn.who === whoName;
          const node = document.createElement("div");
          node.className = "speech-bubble" + (isActive ? "" : " speech-bubble-queued");
          node.dataset.who = whoName;
          node.innerHTML =
            '<header><b>' + esc(whoName) + '</b>'
            + (turnCount > 1 ? ' <span class="bubble-turn-idx">' + (state.bubbleTurnIdx + 1) + '/' + turnCount + '</span>' : '')
            + '</header>'
            + (t.text ? '<p class="bubble-say">「' + esc(t.text) + '」</p>' : "")
            + (thoughtText ? '<p class="bubble-think">💭 ' + esc(thoughtText) + '</p>' : "");
          layer.appendChild(node);
          positionBubble(node, anchor);
          state.bubbleSlots.push({ node, who: whoName, baseY: anchor.y });
        }
      } else {
        actors.forEach((aid) => {
          const anchor = bubbleAnchor(aid);
          if (!anchor) return;
          const head = state.session.residents.find((r) => r.agent_id === aid);
          const name = head ? head.name : "#" + aid;
          const myThought = tparts.find((p) => p.indexOf(name + ":") === 0) || "";
          const thoughtText = String(myThought || "").split(":").slice(1).join(":").trim();
          const text = (activeTurn && activeTurn.who === name) ? activeTurn.text
                      : (activeTurn ? activeTurn.text : "");
          const node = document.createElement("div");
          node.className = "speech-bubble";
          node.dataset.who = name;
          node.innerHTML =
            '<header><b>' + esc(name) + '</b></header>'
            + (text ? '<p class="bubble-say">「' + esc(text) + '」</p>' : "")
            + (thoughtText ? '<p class="bubble-think">💭 ' + esc(thoughtText) + '</p>' : "");
          layer.appendChild(node);
          positionBubble(node, anchor);
          state.bubbleSlots.push({ node, who: name, baseY: anchor.y });
        });
      }
      return; // bump fully on content change — positions already anchored
    }
    // Same event / same cursor: just keep the bubbles glued to their
    // sprites as the residents walk around.
    if (state.bubbleSlots && state.bubbleSlots.length) {
      for (const slot of state.bubbleSlots) {
        const resident = (state.session.residents || []).find((r) => r.name === slot.who);
        if (!resident) continue;
        const anchor = bubbleAnchor(resident.agent_id);
        if (!anchor) continue;
        positionBubble(slot.node, anchor);
      }
    }
  }

  function bubbleHtml(name, dialogue, thought, x, y, stateName, totalTurns) {
    const cls = "speech-bubble" + (stateName === "queued" ? " speech-bubble-queued" : "");
    return '<div class="' + cls + '" style="left:' + x + 'px; top:' + y + 'px;">'
      + '<header><b>' + esc(name) + '</b>'
      + (totalTurns > 1 ? ' <span class="bubble-turn-idx">' + (state.bubbleTurnIdx + 1) + '/' + totalTurns + '</span>' : '')
      + '</header>'
      + (dialogue ? '<p class="bubble-say">「' + esc(dialogue) + '」</p>' : "")
      + (thought ? '<p class="bubble-think">💭 ' + esc(thought) + '</p>' : "")
      + '</div>';
  }

  // Side-panel conversation feed: one row per model-written turn so the
  // player can read the whole exchange at a glance without squinting at
  // floating speech bubbles. Most recent exchange is at the top.
  function renderConversation() {
    const box = $("#rConversation");
    if (!box) return;
    if (!state.session) {
      box.innerHTML = '<p class="conv-empty">还没开始同居 — 选两位居民开始。</p>';
      return;
    }
    const events = (state.session.events || []).filter(
      (e) => e && (e.kind === "interact" || e.kind === "direct")
    );
    if (!events.length) {
      box.innerHTML = '<p class="conv-empty">还没人开口 — 时间走起来,他们碰到一起就会开聊。</p>';
      return;
    }
    // Take the latest exchange's turns in reverse-order (newest first).
    const last = events[events.length - 1];
    const turns = Array.isArray(last.turns) ? last.turns.slice().reverse() : [];
    if (!turns.length) {
      box.innerHTML = '<p class="conv-empty">这段对话没有内容。</p>';
      return;
    }
    const roomLabel = roomLabelById(state.session, last.room) || "";
    const head = '<div class="conv-room">🕒 ' + esc(state.session.virtual_clock || "")
      + ' · ' + esc(roomLabel) + '</div>';
    const rows = turns.map((t) => {
      const name = String(t.who || "");
      const resident = (state.session.residents || []).find((r) => r.name === name);
      const emoji = resident ? resident.emoji : "💬";
      return '<div class="conv-row">'
        + '<span class="conv-emoji">' + esc(emoji) + '</span>'
        + '<span class="conv-name">' + esc(name) + '</span>'
        + '<span class="conv-text">' + esc(t.text || "") + '</span>'
        + '</div>';
    }).join("");
    box.innerHTML = head + rows;
    // Pin scroll to top so newest turn is visible.
    box.scrollTop = 0;
  }

  function renderEvents() {
    const ul = $("#rEvents");
    if (!state.session) return;
    const events = (state.session.events || []).slice().reverse();
    if (!events.length) {
      ul.innerHTML = '<li class="event-empty">还没有事件 — 时间走起来就会有。</li>';
      return;
    }
    ul.innerHTML = events.map(eventItemHtml).join("");
  }

  function eventItemHtml(e) {
    const residentNames = (e.actor_ids || [])
      .map((aid) => {
        const r = (state.session.residents || []).find((x) => x.agent_id === aid);
        return r ? r.name : "#" + aid;
      });
    const who = residentNames.join(" & ");
    const roomLabel = roomLabelById(state.session, e.room);
    if (e.kind === "move") {
      return '<li class="event-move">'
        + '<header><b>' + esc(who) + '</b> → ' + esc(roomLabel) + ' · <span class="muted">第' + e.tick + '刻</span></header>'
        + '<p>' + esc(e.note) + '</p>'
        + '</li>';
    }
    if (e.kind === "interact") {
      const delta = e.mood_delta || 0;
      const rel = Object.values(e.relationship_delta || {})[0] || 0;
      return '<li class="event-interact">'
        + '<header>'
        + '<b>' + esc(who) + '</b> 在' + esc(roomLabel) + '聊上了 · <span class="muted">第' + e.tick + '刻</span>'
        + '<span class="event-deltas">'
        + '<span class="delta-mood ' + (delta >= 0 ? "pos" : "neg") + '">' + (delta >= 0 ? "↑" : "↓") + '心情 ' + (Math.abs(delta) * 100).toFixed(0) + '</span>'
        + '<span class="delta-rel ' + (rel >= 0 ? "pos" : "neg") + '">' + (rel >= 0 ? "↑" : "↓") + '关系 ' + Math.abs(rel).toFixed(1) + '</span>'
        + '</span>'
        + '</header>'
        + '<pre class="event-dialogue">' + esc(e.dialogue || "") + '</pre>'
        + (e.thought ? '<p class="event-thought">💭 ' + esc(e.thought) + '</p>' : "")
        + '</li>';
    }
    return '<li class="event-' + esc(e.kind) + '"><pre>' + esc(JSON.stringify(e, null, 2)) + '</pre></li>';
  }

  function renderDashboard() {
    const mood = $("#rMood");
    if (!mood || !state.session) return;
    mood.innerHTML = state.session.residents.map((r) => {
      const pct = Math.round((r.mood + 1) * 50);
      return '<li>'
        + '<span class="mood-name">' + esc(r.name) + '</span>'
        + '<span class="mood-bar"><i style="width:' + pct + '%; background:' + moodColor(r.mood) + '"></i></span>'
        + '<span class="mood-label">' + esc(r.mood_label) + '</span>'
        + '</li>';
    }).join("");

    const rel = $("#rRelations");
    const residents = state.session.residents;
    if (residents.length < 2) {
      rel.innerHTML = '<p class="muted">至少 2 位居民才能看关系。</p>';
    } else {
      let html = '<table class="relation-table"><thead><tr><th></th>';
      residents.forEach((r) => {
        html += '<th>' + esc(r.name) + '</th>';
      });
      html += '</tr></thead><tbody>';
      residents.forEach((row) => {
        html += '<tr><th>' + esc(row.name) + '</th>';
        residents.forEach((col) => {
          if (row.agent_id === col.agent_id) {
            html += '<td class="rel-self">—</td>';
          } else {
            const v = (((state.session.relationships || {})[row.agent_id] || {})[col.agent_id] || 0);
            const cls = v > 10 ? "pos" : v < -10 ? "neg" : "";
            html += '<td class="' + cls + '">' + v.toFixed(0) + '</td>';
          }
        });
        html += '</tr>';
      });
      html += '</tbody></table>';
      rel.innerHTML = html;
    }

    const events = state.session.events || [];
    const interactions = events.filter((e) => e.kind === "interact").length;
    const moves = events.filter((e) => e.kind === "move").length;
    const total = events.length;
    const truncated = state.session.events_truncated;
    $("#rTally").textContent = "互动 " + interactions + " 次 · 移动 " + moves + " 次 · 共 " + total + " 事件" + (truncated ? " (已截断)" : "");
  }

  function renderActivityLine() {
    const line = $("#rActivityLine");
    if (!state.session) return;
    const items = state.session.residents.map((r) => r.name + " " + r.activity);
    line.textContent = "各自在:" + items.join(" · ");
  }

  // -- export -------------------------------------------------------------
  function exportMarkdown(ev) {
    if (!state.session) {
      ev.preventDefault();
      return;
    }
    const md = renderMarkdown(state.session);
    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = ev.currentTarget;
    a.href = url;
    a.download = "同居模式-" + state.session.id + ".md";
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  function renderMarkdown(s) {
    const head = [
      "# 同居模式 · " + s.id,
      "",
      "- 城市:" + (s.city || "默认世界"),
      "- 氛围:" + (s.vibe || "(无)"),
      "- 节奏:1 刻 = " + s.tick_minutes + " 分钟",
      "- 时长:" + s.max_hours + " 小时",
      "- 结束时间(虚拟):" + s.virtual_clock,
      "",
      "## 居民",
    ];
    const residentLines = s.residents.map((r) =>
      "- " + r.name + " · " + r.age + "岁 · " + (r.job || "") + " · 当前:" + r.activity + " · 心情:" + r.mood_label + " (" + r.mood.toFixed(2) + ")"
    );
    const residents = s.residents;
    const relTable = [
      "| |" + residents.map((r) => " " + r.name + " ").join("|") + "|",
      "|---" + residents.map(() => "---").join("|") + "|",
    ];
    residents.forEach((row) => {
      const cells = residents.map((col) => {
        if (row.agent_id === col.agent_id) return "—";
        const v = (((s.relationships || {})[row.agent_id] || {})[col.agent_id] || 0);
        return v.toFixed(0);
      });
      relTable.push("| " + row.name + " |" + cells.map((c) => " " + c + " ").join("|") + "|");
    });
    const events = (s.events || []).map((e) => {
      const head = "**第" + e.tick + "刻 · " + roomLabelById(s, e.room) + " · " + (e.actor_ids || []).map((aid) => {
        const r = residents.find((x) => x.agent_id === aid);
        return r ? r.name : "#" + aid;
      }).join(" & ") + "**";
      if (e.kind === "move") {
        return "- 🚶 " + head + "\n  " + e.note;
      }
      if (e.kind === "interact") {
        const d = (e.dialogue || "").split("\n").map((l) => "  > " + l).join("\n");
        const t = e.thought ? "\n  💭 " + e.thought : "";
        return "- 💬 " + head + "\n" + d + t;
      }
      return "- " + e.kind + ": " + JSON.stringify(e);
    });
    return [
      ...head,
      ...residentLines,
      "",
      "## 关系",
      ...relTable,
      "",
      "## 事件流 (新→旧)",
      ...events,
    ].join("\n");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
