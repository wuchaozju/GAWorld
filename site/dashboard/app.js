const state = {
  config: null,
  agents: [],
  selectedAgentId: null,
  lifeEventTemplates: [],
  lifeEvents: [],
  trace: null,
  traceGeneratedAt: null,
  memoryPayload: null,
  profileText: "",
  rawSourceKey: "long_term",
  // Frames captured live from latest_frame.json between trace flushes
  // (the simulator only rewrites simulation_trace.json every N frames).
  liveFrames: new Map(),
  frameIndex: 0,
  follow: true,
  running: false,
  pollTimer: null,
  avatarCache: new Map(),
  // Run log accumulated across status polls: `offset` is the byte position the
  // server already sent us, so each poll only brings back what was appended.
  // Null offset asks for a full (re)load.
  runLog: { text: "", offset: null, size: 0, skipped: 0 },
  // Wall clock ("YYYY-MM-DD HH:MM:SS") of a pending 定时运行, or null. Owned by
  // the server — the timer lives there, so it survives closing this page.
  scheduledAt: null,
  // Last schedule failure already reported, so the poll does not re-toast it.
  scheduleError: null,
  // Household assignment for the current run, read from the recorder output.
  // Null until the first fetch; `{available:false}` once we know a run has
  // not produced any yet.
  family: null,
};

const els = {
  agentIdsInput: document.getElementById("agentIdsInput"),
  simDaysInput: document.getElementById("simDaysInput"),
  secondsPerDayInput: document.getElementById("secondsPerDayInput"),
  timeStepInput: document.getElementById("timeStepInput"),
  defaultProviderSelect: document.getElementById("defaultProviderSelect"),
  scheduleProviderSelect: document.getElementById("scheduleProviderSelect"),
  realtimeInput: document.getElementById("realtimeInput"),
  fastForwardInput: document.getElementById("fastForwardInput"),
  stepUnitSelect: document.getElementById("stepUnitSelect"),
  simSpanLabel: document.getElementById("simSpanLabel"),
  simSpanHelp: document.getElementById("simSpanHelp"),
  randomnessInput: document.getElementById("randomnessInput"),
  randomnessValue: document.getElementById("randomnessValue"),
  routineRandomnessInput: document.getElementById("routineRandomnessInput"),
  routineRandomnessValue: document.getElementById("routineRandomnessValue"),
  saveConfigBtn: document.getElementById("saveConfigBtn"),
  runBtn: document.getElementById("runBtn"),
  scheduleAtInput: document.getElementById("scheduleAtInput"),
  scheduleRunBtn: document.getElementById("scheduleRunBtn"),
  cancelScheduleBtn: document.getElementById("cancelScheduleBtn"),
  resetRunBtn: document.getElementById("resetRunBtn"),
  stopBtn: document.getElementById("stopBtn"),
  runStatusBadge: document.getElementById("runStatusBadge"),
  traceStatus: document.getElementById("traceStatus"),
  messageLine: document.getElementById("messageLine"),
  reloadTraceBtn: document.getElementById("reloadTraceBtn"),
  frameTitle: document.getElementById("frameTitle"),
  mapCanvas: document.getElementById("mapCanvas"),
  timelineSlider: document.getElementById("timelineSlider"),
  timelineLabel: document.getElementById("timelineLabel"),
  followLatestInput: document.getElementById("followLatestInput"),
  latestFrameBox: document.getElementById("latestFrameBox"),
  selectedAgentAvatar: document.getElementById("selectedAgentAvatar"),
  agentSelect: document.getElementById("agentSelect"),
  profileView: document.getElementById("profileView"),
  simRosterList: document.getElementById("simRosterList"),
  simRosterCount: document.getElementById("simRosterCount"),
  toggleSimBtn: document.getElementById("toggleSimBtn"),
  refreshAgentBtn: document.getElementById("refreshAgentBtn"),
  familyOverview: document.getElementById("familyOverview"),
  familyDetail: document.getElementById("familyDetail"),
  refreshFamilyBtn: document.getElementById("refreshFamilyBtn"),
  interviewContext: document.getElementById("interviewContext"),
  interviewQuestions: document.getElementById("interviewQuestions"),
  interviewBtn: document.getElementById("interviewBtn"),
  interviewOutput: document.getElementById("interviewOutput"),
  lifeEventTemplateSelect: document.getElementById("lifeEventTemplateSelect"),
  lifeEventAgentInput: document.getElementById("lifeEventAgentInput"),
  lifeEventModeSelect: document.getElementById("lifeEventModeSelect"),
  lifeEventDayInput: document.getElementById("lifeEventDayInput"),
  lifeEventTimeInput: document.getElementById("lifeEventTimeInput"),
  lifeEventSeverityInput: document.getElementById("lifeEventSeverityInput"),
  lifeEventTitleInput: document.getElementById("lifeEventTitleInput"),
  lifeEventDescriptionInput: document.getElementById("lifeEventDescriptionInput"),
  lifeEventNewJobField: document.getElementById("lifeEventNewJobField"),
  lifeEventNewJobInput: document.getElementById("lifeEventNewJobInput"),
  useSelectedAgentBtn: document.getElementById("useSelectedAgentBtn"),
  addLifeEventBtn: document.getElementById("addLifeEventBtn"),
  reloadLifeEventsBtn: document.getElementById("reloadLifeEventsBtn"),
  lifeEventListBox: document.getElementById("lifeEventListBox"),
  fosHintInput: document.getElementById("fosHintInput"),
  fosEnglishCheckbox: document.getElementById("fosEnglishCheckbox"),
  fosExportBtn: document.getElementById("fosExportBtn"),
  fosCopyBtn: document.getElementById("fosCopyBtn"),
  fosDownloadBtn: document.getElementById("fosDownloadBtn"),
  fosOutputBox: document.getElementById("fosOutputBox"),
  reloadMemoryBtn: document.getElementById("reloadMemoryBtn"),
  rawMemoryBtn: document.getElementById("rawMemoryBtn"),
  memoryView: document.getElementById("memoryView"),
  stateMemoryView: document.getElementById("stateMemoryView"),
  episodesView: document.getElementById("episodesView"),
  agentLogView: document.getElementById("agentLogView"),
  rawModal: document.getElementById("rawModal"),
  rawModalTabs: document.getElementById("rawModalTabs"),
  rawModalBody: document.getElementById("rawModalBody"),
  rawModalMeta: document.getElementById("rawModalMeta"),
  rawCopyBtn: document.getElementById("rawCopyBtn"),
  rawDownloadBtn: document.getElementById("rawDownloadBtn"),
  reloadStatusBtn: document.getElementById("reloadStatusBtn"),
  runLogBox: document.getElementById("runLogBox"),
  runLogMeta: document.getElementById("runLogMeta"),
  exportRunLogBtn: document.getElementById("exportRunLogBtn"),
};

// Terrain-map rendering (avatars, trails, landmarks, zoom/pan) is provided by
// the shared CityMapView module, used identically by the simviz replay tab.
const mapView = new CityMapView(els.mapCanvas, {
  getSelectedAgentId: () => state.selectedAgentId,
  emptyText: "等待轨迹数据…",
});

function traceAgentMap() {
  const agents = (state.trace && Array.isArray(state.trace.agents)) ? state.trace.agents : [];
  return new Map(agents.map((agent) => [Number(agent.id), agent]));
}

function resolveAssetPath(assetPath) {
  const text = String(assetPath || "").trim();
  if (!text) return "";
  if (/^(https?:)?\/\//.test(text) || text.startsWith("data:")) return text;
  // The trace stores paths relative to the visualization output dir
  // (e.g. "avatars/agent_33.svg"), not relative to this page.
  if (!text.startsWith("/")) return `/output/visualization/${text}`;
  return text;
}

function getAgentAvatarPath(agentId) {
  const meta = traceAgentMap().get(Number(agentId));
  const fallbackPath = `/output/visualization/avatars/agent_${Number(agentId || 0)}.svg`;
  return resolveAssetPath((meta && meta.avatar_path) || fallbackPath);
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
    renderTrace();
  };
  img.onerror = () => {
    state.avatarCache.delete(resolved);
  };
  img.src = resolved;
  return null;
}

function renderSelectedAgentAvatar() {
  if (!state.selectedAgentId) {
    els.selectedAgentAvatar.removeAttribute("src");
    els.selectedAgentAvatar.alt = "";
    return;
  }
  const selected = state.agents.find((agent) => Number(agent.id) === Number(state.selectedAgentId));
  const avatarPath = getAgentAvatarPath(state.selectedAgentId);
  els.selectedAgentAvatar.src = avatarPath;
  els.selectedAgentAvatar.alt = `${selected ? selected.name : `Agent ${state.selectedAgentId}`} avatar`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

let messageTimer = null;
function message(text, tone = "") {
  els.messageLine.textContent = text || "";
  els.messageLine.className = `toast${text ? " show" : ""}${tone ? ` ${tone}` : ""}`;
  if (messageTimer) window.clearTimeout(messageTimer);
  if (text) {
    messageTimer = window.setTimeout(() => {
      els.messageLine.className = "toast";
    }, tone === "error" ? 10000 : 4000);
  }
}

// Enable/disable controls according to whether a simulation is running:
// run buttons and run-config inputs lock while running, stop unlocks.
function syncRunButtons() {
  const running = Boolean(state.running);
  els.runBtn.disabled = running;
  els.resetRunBtn.disabled = running;
  els.stopBtn.disabled = !running;
  // A pending schedule swaps its button for 取消定时: re-arming would silently
  // replace the timer, so cancelling has to be the visible next step.
  const scheduled = Boolean(state.scheduledAt);
  els.scheduleRunBtn.hidden = scheduled;
  els.cancelScheduleBtn.hidden = !scheduled;
  els.scheduleAtInput.disabled = running || scheduled;
  els.scheduleRunBtn.disabled = running;
  [
    els.agentIdsInput,
    els.simDaysInput,
    els.secondsPerDayInput,
    els.timeStepInput,
    els.defaultProviderSelect,
    els.scheduleProviderSelect,
    els.realtimeInput,
    els.fastForwardInput,
    els.stepUnitSelect,
    els.randomnessInput,
    els.routineRandomnessInput,
  ].forEach((el) => { el.disabled = running; });
  if (els.toggleSimBtn) els.toggleSimBtn.disabled = running;
  document.body.classList.toggle("is-running", running);
}

// Wrap an async click handler: disable the button and show a spinner while
// it runs, and surface any error on the message line.
function withBusy(btn, fn) {
  return async () => {
    if (btn.disabled) return;
    btn.disabled = true;
    btn.classList.add("busy");
    try {
      await fn();
    } catch (error) {
      message(error.message, "error");
    } finally {
      btn.disabled = false;
      btn.classList.remove("busy");
      // Re-apply run-state locking in case this button is one of the
      // run controls (e.g. 停止 must stay disabled once nothing runs).
      syncRunButtons();
    }
  };
}

// Replace a log box's text, keeping it pinned to the bottom if the user
// hasn't scrolled up.
function setLogText(el, text) {
  if (el.textContent === text) return;
  const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
  el.textContent = text;
  if (nearBottom) el.scrollTop = el.scrollHeight;
}

// The run horizon is entered in whatever the step unit is: "30 天", "24 月",
// "10 年". Only the label and the number change here — the day count is
// derived server-side, where the calendar lives.
const SPAN_FIELD_KEYS = {
  day: ["sim.days", "sim.days_hint"],
  month: ["sim.months", "sim.months_hint"],
  year: ["sim.years", "sim.years_hint"],
};
const SPAN_APPROX_DAYS = { day: 1, month: 30, year: 365 };

function currentStepUnit() {
  const unit = els.stepUnitSelect ? els.stepUnitSelect.value : "day";
  return SPAN_FIELD_KEYS[unit] ? unit : "day";
}

function applyStepUnitLabels() {
  const [labelKey, helpKey] = SPAN_FIELD_KEYS[currentStepUnit()];
  els.simSpanLabel.setAttribute("data-i18n", labelKey);
  els.simSpanHelp.setAttribute("data-i18n-help", helpKey);
  // Re-run the i18n pass instead of writing the text ourselves: before the
  // locale file lands __() echoes the key back, and we would paint
  // "sim.years" into the toolbar.
  if (window.applyTranslations) window.applyTranslations();
  // Remember what the number currently means, so the next change can rescale
  // it. Kept on the element rather than in a closure: loadConfig() sets the
  // unit after the listeners are bound, and a closure would go stale.
  els.stepUnitSelect.dataset.spanUnit = currentStepUnit();
}

// Switching the unit rescales the number so the horizon stays roughly where
// it was (30 days -> 1 month). Approximate on purpose: it is a starting
// value the user then edits, and whatever they submit is converted exactly.
function onStepUnitChanged() {
  const previousUnit = els.stepUnitSelect.dataset.spanUnit || "day";
  const unit = currentStepUnit();
  const days = Number(els.simDaysInput.value || 1) * (SPAN_APPROX_DAYS[previousUnit] || 1);
  els.simDaysInput.value = Math.max(1, Math.round(days / SPAN_APPROX_DAYS[unit]));
  // Picking 月/年 is picking fast-forward — there is no per-month tick loop.
  // Tick the box so the toolbar shows what will actually run instead of
  // quietly falling back to a day-by-day run over a now-huge horizon.
  if (unit !== "day") els.fastForwardInput.checked = true;
  applyStepUnitLabels();
}

// ...and the reverse: turning fast-forward off leaves no runner that can take
// a month-long step, so the unit has to come back to 天.
function onFastForwardChanged() {
  if (els.fastForwardInput.checked || currentStepUnit() === "day") return;
  els.stepUnitSelect.value = "day";
  onStepUnitChanged();
}

function configPayloadFromForm() {
  const defaultProvider = els.defaultProviderSelect.value;
  const scheduleProvider = els.scheduleProviderSelect.value || defaultProvider;
  return {
    agent_ids: els.agentIdsInput.value,
    // The horizon field is expressed in the step unit; the server does the
    // calendar math (leap years, 28/31-day months) and derives sim_days.
    sim_span: { unit: currentStepUnit(), count: Number(els.simDaysInput.value || 1) },
    seconds_per_day: Number(els.secondsPerDayInput.value || 10),
    simulate_realtime: els.realtimeInput.checked,
    time_step_minutes: els.timeStepInput.value.trim(),
    long_run: {
      enabled: els.fastForwardInput.checked,
      unit: els.stepUnitSelect.value || "day",
      randomness: Number(els.randomnessInput.value),
    },
    routine_change: {
      randomness: Number(els.routineRandomnessInput.value),
    },
    llm: {
      routing: {
        default: defaultProvider,
        tasks: { schedule: scheduleProvider },
      },
    },
  };
}

async function loadConfig() {
  state.config = await api("/api/config");
  const cfg = state.config;
  els.agentIdsInput.value = (cfg.agent_ids || []).join(",");
  const span = cfg.sim_span || { unit: "day", count: cfg.sim_days || 1 };
  els.simDaysInput.value = span.count || 1;
  els.secondsPerDayInput.value = cfg.seconds_per_day || 10;
  els.timeStepInput.value = cfg.time_step_minutes == null ? "" : cfg.time_step_minutes;
  els.realtimeInput.checked = Boolean(cfg.simulate_realtime);
  els.fastForwardInput.checked = Boolean(cfg.long_run && cfg.long_run.enabled);
  els.stepUnitSelect.value = (cfg.long_run && cfg.long_run.unit) || "day";
  applyStepUnitLabels();
  const randomness = cfg.long_run && cfg.long_run.randomness != null ? cfg.long_run.randomness : 0.3;
  els.randomnessInput.value = randomness;
  els.randomnessValue.textContent = Number(randomness).toFixed(2);
  const routineRandomness =
    cfg.routine_change && cfg.routine_change.randomness != null ? cfg.routine_change.randomness : 0;
  els.routineRandomnessInput.value = routineRandomness;
  els.routineRandomnessValue.textContent = Number(routineRandomness).toFixed(2);
  const providers = (cfg.llm && cfg.llm.providers) || [];
  const routing = (cfg.llm && cfg.llm.routing) || {};
  fillProviderSelect(els.defaultProviderSelect, providers, routing.default);
  fillProviderSelect(els.scheduleProviderSelect, providers, (routing.tasks || {}).schedule || routing.default);
}

function fillProviderSelect(select, providers, selected) {
  select.innerHTML = "";
  providers.forEach((provider) => {
    const option = document.createElement("option");
    option.value = provider;
    option.textContent = provider;
    option.selected = provider === selected;
    select.appendChild(option);
  });
}

async function saveConfig() {
  await api("/api/config", { method: "POST", body: JSON.stringify(configPayloadFromForm()) });
  await loadConfig();
  message(__("config.saved"));
}

// The toolbar "Agent IDs" input is the single source of truth for which
// agents run in the simulation; the profile dropdown mirrors it live.
function configuredIdSet() {
  return new Set(
    els.agentIdsInput.value
      .split(",")
      .map((part) => Number(part.trim()))
      .filter((id) => Number.isFinite(id) && id > 0)
  );
}

function refreshAgentOptionLabels() {
  const configured = configuredIdSet();
  Array.from(els.agentSelect.options).forEach((option) => {
    const agent = state.agents.find((item) => Number(item.id) === Number(option.value));
    if (!agent) return;
    const inSim = configured.has(Number(agent.id));
    option.textContent = `${inSim ? "▶ " : ""}${String(agent.id).padStart(2, "0")} · ${agent.name}${inSim ? "（仿真中）" : ""}`;
  });
  updateToggleSimBtn();
  renderSimRoster();
}

// Avatar strip of the residents on the current run roster (the toolbar
// "Agent IDs" list). Clicking a face selects that resident.
function renderSimRoster() {
  if (!els.simRosterList) return;
  const ids = Array.from(configuredIdSet()).sort((a, b) => a - b);
  if (els.simRosterCount) els.simRosterCount.textContent = ids.length ? String(ids.length) : "";
  els.simRosterList.innerHTML = "";
  ids.forEach((id) => {
    const agent = state.agents.find((item) => Number(item.id) === id);
    const name = agent ? agent.name : `Agent ${id}`;
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "roster-chip";
    chip.dataset.agentId = String(id);
    chip.disabled = !agent;
    chip.title = `${String(id).padStart(2, "0")} · ${name}`;
    chip.classList.toggle("is-active", id === Number(state.selectedAgentId));

    const face = document.createElement("span");
    face.className = "roster-face";
    face.textContent = String(name).trim().slice(0, 1).toUpperCase();
    const img = document.createElement("img");
    img.alt = "";
    // No avatar file for this resident yet — fall back to the initial
    // rendered underneath.
    img.addEventListener("error", () => img.remove());
    img.src = getAgentAvatarPath(id);
    face.appendChild(img);

    const label = document.createElement("span");
    label.className = "roster-name";
    label.textContent = name;

    chip.append(face, label);
    els.simRosterList.appendChild(chip);
  });
}

// Switch the profile / memory / map focus to another resident.
async function selectAgent(agentId) {
  const id = Number(agentId);
  if (!id || id === Number(state.selectedAgentId)) return;
  state.selectedAgentId = id;
  els.agentSelect.value = String(id);
  renderSelectedAgentAvatar();
  updateToggleSimBtn();
  renderSimRoster();
  renderTrace();
  renderFamilyDetail();
  try {
    await loadProfile();
    await loadMemory();
  } catch (error) {
    message(error.message, "error");
  }
}

function updateToggleSimBtn() {
  if (!els.toggleSimBtn) return;
  const inSim = configuredIdSet().has(Number(state.selectedAgentId));
  els.toggleSimBtn.textContent = inSim ? "✓ 仿真中 · 点击移出" : "加入仿真";
  els.toggleSimBtn.classList.toggle("primary", inSim);
}

function toggleSelectedAgentInSim() {
  const id = Number(state.selectedAgentId);
  if (!id) return;
  const ids = configuredIdSet();
  if (ids.has(id)) ids.delete(id);
  else ids.add(id);
  els.agentIdsInput.value = Array.from(ids).sort((a, b) => a - b).join(",");
  refreshAgentOptionLabels();
  message(`Agent ${id} 已${ids.has(id) ? "加入" : "移出"}仿真名单，点击「保存配置」或「运行仿真」生效`);
}

async function loadAgents() {
  const payload = await api("/api/agents");
  state.agents = payload.agents || [];
  if (!state.selectedAgentId && state.agents.length) {
    const configured = state.agents.find((agent) => agent.configured);
    state.selectedAgentId = (configured || state.agents[0]).id;
  }
  els.agentSelect.innerHTML = "";
  state.agents.forEach((agent) => {
    const option = document.createElement("option");
    option.value = String(agent.id);
    option.textContent = `${String(agent.id).padStart(2, "0")} · ${agent.name}`;
    option.selected = agent.id === state.selectedAgentId;
    els.agentSelect.appendChild(option);
  });
  refreshAgentOptionLabels();
  renderSelectedAgentAvatar();
}

function selectedLifeEventTemplate() {
  const key = els.lifeEventTemplateSelect.value;
  return state.lifeEventTemplates.find((item) => item.key === key) || {};
}

function fillLifeEventTemplates() {
  els.lifeEventTemplateSelect.innerHTML = "";
  state.lifeEventTemplates.forEach((template) => {
    const option = document.createElement("option");
    option.value = template.key;
    option.textContent = template.title || template.key;
    els.lifeEventTemplateSelect.appendChild(option);
  });
  applyLifeEventTemplate();
}

function applyLifeEventTemplate() {
  const template = selectedLifeEventTemplate();
  if (!template.key) return;
  if (!els.lifeEventTitleInput.value.trim()) {
    els.lifeEventTitleInput.value = template.title || "";
  }
  if (!els.lifeEventDescriptionInput.value.trim()) {
    els.lifeEventDescriptionInput.value = template.description || "";
  }
  els.lifeEventSeverityInput.value = template.severity == null ? 0.7 : template.severity;
  // Only a 换工作 event has a destination job to name; 失业 always goes to 待业中.
  els.lifeEventNewJobField.hidden = template.key !== "job_change";
}

function renderLifeEvents() {
  const events = state.lifeEvents || [];
  if (!events.length) {
    els.lifeEventListBox.textContent = __("life_event.none");
    return;
  }
  els.lifeEventListBox.textContent = events.slice().reverse().map((event) => {
    const target = (event.agent_ids || []).length ? `#${event.agent_ids.join(",#")}` : __("agent.all");
    const when = event.schedule_mode === "immediate"
      ? __("life_event.immediate")
      : __f("life_event.scheduled_fmt", {day: event.day || "?", time: event.time || __("life_event.current_time")});
    const status = event.status === "consumed"
      ? __f("life_event.triggered_at", {day: event.triggered_day || "?", time: event.triggered_time || ""})
      : __("life_event.pending");
    return [
      `[${status}] ${event.title || __("life_event.event_prefix")}`,
      __f("life_event.detail", {target: target, when: when, severity: Number(event.severity || 0).toFixed(2)}),
      event.description || "",
    ].join("\n");
  }).join("\n\n");
}

async function loadLifeEvents() {
  const payload = await api("/api/life-events");
  state.lifeEventTemplates = payload.templates || [];
  state.lifeEvents = payload.events || [];
  if (!els.lifeEventTemplateSelect.options.length) fillLifeEventTemplates();
  renderLifeEvents();
}

function lifeEventPayloadFromForm() {
  return {
    template_key: els.lifeEventTemplateSelect.value,
    agent_ids: els.lifeEventAgentInput.value.trim(),
    schedule_mode: els.lifeEventModeSelect.value,
    day: els.lifeEventDayInput.value.trim(),
    time: els.lifeEventTimeInput.value.trim(),
    severity: Number(els.lifeEventSeverityInput.value || 0.7),
    title: els.lifeEventTitleInput.value.trim(),
    description: els.lifeEventDescriptionInput.value.trim(),
    new_job: els.lifeEventNewJobInput.value.trim(),
  };
}

async function addLifeEvent() {
  const payload = lifeEventPayloadFromForm();
  const result = await api("/api/life-events", { method: "POST", body: JSON.stringify(payload) });
  state.lifeEvents = result.events || [];
  renderLifeEvents();
  message(__("life_event.queued"));
}

function renderMarkdown(md) {
  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (t) => esc(t)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  const lines = String(md || "").replace(/\r\n?/g, "\n").split("\n");
  let html = "";
  let inList = false;
  const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
  for (const ln of lines) {
    const h = ln.match(/^(#{1,4})\s+(.*)$/);
    const li = ln.match(/^\s*[-*]\s+(.*)$/);
    if (h) {
      closeList();
      const lvl = Math.min(h[1].length + 1, 5);
      html += `<h${lvl}>${inline(h[2])}</h${lvl}>`;
    } else if (li) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inline(li[1])}</li>`;
    } else if (ln.trim() === "") {
      closeList();
    } else {
      closeList();
      html += `<p>${inline(ln)}</p>`;
    }
  }
  closeList();
  return html;
}

function renderProfileView() {
  if (!els.profileView) return;
  els.profileView.innerHTML = renderMarkdown(state.profileText);
}

// ---------------------------------------------------------------------------
// 家庭结构 card
//
// Reads `/api/family/overview`, which serves the recorder output of the last
// run rather than re-deriving households on request: the assignment the agents
// are actually living in is the one worth showing, and re-deriving it would
// silently disagree with the run whenever the config changed since it started.
// ---------------------------------------------------------------------------

const HOUSEHOLD_TYPE_ZH = {
  single: "独居",
  shared: "合租",
  with_parents: "与父母同住",
  cohabit: "未婚同居",
  couple: "夫妻二人",
  nuclear: "核心家庭",
  single_parent: "单亲家庭",
  multigen: "三代同堂",
};

const MARITAL_STATUS_ZH = {
  never: "未婚",
  married: "已婚",
  divorced: "离异",
  widowed: "丧偶",
};

const FAMILY_ROLE_ZH = {
  spouse: "配偶",
  partner: "伴侣",
  child: "子女",
  father: "父亲",
  mother: "母亲",
  parent: "父母",
  sibling: "兄弟姐妹",
  ex: "前任",
  roommate: "室友",
};

function familyTypeLabel(key) {
  return HOUSEHOLD_TYPE_ZH[key] || key || "?";
}

async function loadFamily() {
  try {
    state.family = await api("/api/family/overview");
  } catch (error) {
    // A run that never started has no records; that is not an error worth
    // shouting about in the message line.
    state.family = { available: false, error: error.message };
  }
  renderFamilyCard();
}

function renderFamilyCard() {
  renderFamilyOverview();
  renderFamilyDetail();
}

function renderFamilyOverview() {
  if (!els.familyOverview) return;
  const data = state.family;
  if (!data || !data.available) {
    els.familyOverview.innerHTML = "";
    return;
  }
  const summary = data.summary || {};
  const types = summary.household_types || {};
  const statuses = summary.marital_statuses || {};
  const people = Number(summary.agents || (data.agents || []).length) || 0;
  const single = Number(statuses.never || 0);

  const stat = (label, value, hint) =>
    `<div class="family-stat" title="${escapeHtml(hint || "")}">
       <span class="family-stat-value">${escapeHtml(value)}</span>
       <span class="family-stat-label">${escapeHtml(label)}</span>
     </div>`;

  const stats = [
    stat(tr("family.stat.households", "户"), summary.households || (data.households || []).length,
      "本次运行里一共有多少个住在一起的家庭单元"),
    stat(tr("family.stat.couples", "仿真内夫妻"), summary.in_sim_couples || 0,
      "配偶同样是本次运行里的居民，两人会真的在家里碰面、互相影响"),
    stat(tr("family.stat.with_children", "有子女"), summary.with_children || 0,
      "有孩子的居民人数。孩子会占用日程，也会花钱"),
    stat(tr("family.stat.single", "单身"), people ? `${single}/${people}` : single,
      "婚姻状态为未婚的居民占比"),
  ].join("");

  const total = Object.values(types).reduce((sum, n) => sum + Number(n || 0), 0);
  const order = Object.keys(types).sort((a, b) => Number(types[b]) - Number(types[a]));
  const bar = total
    ? order
        .map((key, index) => {
          const count = Number(types[key] || 0);
          const pct = ((count / total) * 100).toFixed(1);
          return `<span class="family-bar-seg" data-seg="${index % 6}" style="width:${pct}%"
                        title="${escapeHtml(familyTypeLabel(key))} ${count} 户（${pct}%）"></span>`;
        })
        .join("")
    : "";
  const legend = order
    .map(
      (key, index) =>
        `<span class="family-legend-item"><i data-seg="${index % 6}"></i>${escapeHtml(
          familyTypeLabel(key)
        )} <b>${Number(types[key] || 0)}</b></span>`
    )
    .join("");

  els.familyOverview.innerHTML =
    `<div class="family-stats">${stats}</div>` +
    (total
      ? `<div class="family-bar">${bar}</div><div class="family-legend">${legend}</div>`
      : "");
}

function familyMemberChip(member) {
  const role = FAMILY_ROLE_ZH[member.role] || member.role || "";
  const age = Number(member.age || 0);
  const where = member.coresident ? "同住" : "不同住";
  const inSim = member.kind === "agent";
  return `<li class="family-member${member.coresident ? " is-coresident" : ""}">
      <span class="family-member-role">${escapeHtml(role)}</span>
      <span class="family-member-name">${escapeHtml(member.name || "")}</span>
      <span class="family-member-meta">${age ? age + "岁 · " : ""}${escapeHtml(where)}${
        inSim ? " · 也在本次仿真中" : ""
      }</span>
    </li>`;
}

function renderFamilyDetail() {
  if (!els.familyDetail) return;
  const data = state.family;
  if (!data || !data.available) {
    els.familyDetail.innerHTML = "";
    return;
  }
  const agentId = Number(state.selectedAgentId);
  const row = (data.agents || []).find((item) => Number(item.agent_id) === agentId);
  if (!row) {
    els.familyDetail.innerHTML = `<p class="family-note">${escapeHtml(
      tr("family.not_in_run", "这位居民没有参与上一轮运行，因此没有家庭记录。")
    )}</p>`;
    return;
  }

  const members = Array.isArray(row.members) ? row.members : [];
  const coresident = members.filter((m) => m.coresident);
  const elsewhere = members.filter((m) => !m.coresident);
  const finance = (data.finance || {})[row.household_id];

  const tags =
    `<span class="family-tag">${escapeHtml(
      MARITAL_STATUS_ZH[row.marital_status] || row.marital_status || "?"
    )}</span>` +
    `<span class="family-tag">${escapeHtml(familyTypeLabel(row.household_type))}</span>` +
    (Number(row.care_load) > 0
      ? `<span class="family-tag subtle" title="照护负担：孩子和老人占掉的精力，0 到 1">照护负担 ${Number(
          row.care_load
        ).toFixed(2)}</span>`
      : "");

  const group = (title, list) =>
    list.length
      ? `<div class="family-group"><p class="family-group-title">${escapeHtml(title)}</p>
           <ul class="family-members">${list.map(familyMemberChip).join("")}</ul></div>`
      : "";

  const money =
    finance && (finance.dependant_cost || finance.partner_transfer)
      ? `<p class="family-note">本轮累计：养育与赡养支出 <b>¥${Number(
          finance.dependant_cost || 0
        ).toFixed(2)}</b>${
          finance.partner_transfer
            ? `，伴侣之间互相补贴 <b>¥${Number(finance.partner_transfer).toFixed(2)}</b>`
            : ""
        }（共 ${Number(finance.days || 0)} 天）。</p>`
      : "";

  els.familyDetail.innerHTML =
    `<div class="family-head-row"><strong>${escapeHtml(row.name || "")}</strong>${tags}</div>` +
    (row.brief ? `<p class="family-brief">${escapeHtml(row.brief)}</p>` : "") +
    group(tr("family.coresident", "住在一起"), coresident) +
    group(tr("family.elsewhere", "不同住的家人"), elsewhere) +
    money;
}

// The homepage shows profiles read-only; editing lives in Agent Studio.
async function loadProfile() {
  if (!state.selectedAgentId) return;
  const profile = await api(`/api/agents/${state.selectedAgentId}/profile`);
  state.profileText = profile.text || "";
  renderProfileView();
}

async function loadMemory() {
  if (!state.selectedAgentId) return;
  const payload = await api(`/api/agents/${state.selectedAgentId}/memory`);
  state.memoryPayload = payload;
  renderMemory();
}

// ------------------------------------------------------------ memory views
//
// The memory endpoint hands back raw simulator artefacts (JSON arrays, keyed
// habit tables, an episode JSONL tail and a plain-text log). The panel shows a
// human-readable rendering of each; the untouched originals stay reachable
// through the raw-data modal below.

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// Translate with an explicit fallback, since __() echoes unknown keys back.
function tr(key, fallback) {
  const text = __(key);
  return text === key ? fallback : text;
}

function textOf(value) {
  if (value == null) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function emptyHtml(text) {
  return `<p class="mem-empty">${escapeHtml(text)}</p>`;
}

function memBlock(title, bodyHtml) {
  if (!bodyHtml) return "";
  return `<section class="mem-block"><p class="mem-block-title">${escapeHtml(title)}</p>${bodyHtml}</section>`;
}

function memRow(label, valueHtml) {
  if (!valueHtml) return "";
  return `<div class="mem-row"><span class="mem-label">${escapeHtml(label)}</span><span class="mem-value">${valueHtml}</span></div>`;
}

function memChips(values, cls) {
  const list = (Array.isArray(values) ? values : [values]).map(textOf).filter(Boolean);
  if (!list.length) return "";
  const klass = cls ? ` ${cls}` : "";
  return list.map((v) => `<span class="mem-chip${klass}">${escapeHtml(v)}</span>`).join("");
}

function memBar(value) {
  const pct = Math.max(0, Math.min(1, Number(value) || 0)) * 100;
  return `<span class="mem-bar"><i style="width:${pct.toFixed(0)}%"></i></span>`
    + `<span class="mem-strength">${(Number(value) || 0).toFixed(2)}</span>`;
}

function renderMemory() {
  const payload = state.memoryPayload || {};
  renderLongTermMemory(payload.memory);
  renderStateMemory(payload);
  renderEpisodes(payload.episodes_tail);
  renderAgentLog(payload.log_tail);
}

function renderLongTermMemory(memory) {
  const items = Array.isArray(memory) ? memory : [];
  if (!items.length) {
    els.memoryView.innerHTML = emptyHtml(tr("memory.no_long_term", "暂无长期记忆。"));
    return;
  }
  els.memoryView.innerHTML = items.map((entry) => {
    const text = textOf(entry);
    // Entries are written as "[Day 2 12:00 MemoryReview] <text>".
    const match = text.match(/^\[([^\]]{1,80})\]\s*([\s\S]*)$/);
    const tag = match ? match[1] : "";
    const body = match ? match[2] : text;
    return `<div class="mem-item">${tag ? `<span class="mem-chip time">${escapeHtml(tag)}</span>` : ""}`
      + `<p>${escapeHtml(body)}</p></div>`;
  }).join("");
}

function scheduleEntries(schedule) {
  if (Array.isArray(schedule)) {
    return schedule.map((item) => (item && typeof item === "object")
      ? { time: textOf(item.time), activity: textOf(item.activity) }
      : { time: "", activity: textOf(item) });
  }
  if (schedule && typeof schedule === "object") {
    return Object.entries(schedule).map(([time, activity]) => ({ time, activity: textOf(activity) }));
  }
  return [];
}

const INTENTION_LABELS = {
  priorities: "优先事项",
  avoidances: "回避",
  growth_focus: "成长方向",
  target_social: "社交目标",
  target_recovery: "恢复目标",
};

const EMPLOYMENT_RECORD_LABELS = {
  job_change: "换工作", unemployment: "失业", rehired: "复职",
};

// The profile markdown carries the Day-1 job, which is exactly what stops
// being true once a 换工作/失业 event fires — so the live job comes from the
// economy state instead, together with the changes that produced it.
function employmentHtml(employment) {
  const info = (employment && typeof employment === "object") ? employment : {};
  const job = textOf(info.job);
  if (!job) return "";
  const unemployed = info.status === "unemployed";
  const statusChip = `<span class="mem-chip${unemployed ? " warn" : ""}">`
    + `${escapeHtml(unemployed ? tr("memory.employment_unemployed", "待业")
      : tr("memory.employment_employed", "在职"))}</span>`;

  let html = memRow(tr("memory.employment_job", "当前职业"), escapeHtml(job) + statusChip);
  const hourly = Number(info.hourly_income) || 0;
  if (hourly > 0) {
    html += memRow(tr("memory.employment_hourly", "时薪"), escapeHtml(hourly.toFixed(2)));
  }
  const recovery = Number(info.recovery_days) || 0;
  if (unemployed && recovery > 0) {
    const previous = textOf(info.previous_job);
    html += memRow(
      tr("memory.employment_recovery", "复职倒计时"),
      escapeHtml(__f("memory.employment_days", {days: recovery})
        + (previous ? ` · ${previous}` : "")));
  }

  const history = Array.isArray(info.history) ? info.history : [];
  html += history.slice().reverse().map((row) => {
    const fallback = EMPLOYMENT_RECORD_LABELS[row.type];
    const label = fallback ? tr(`memory.employment.${row.type}`, fallback) : textOf(row.type);
    const move = `${textOf(row.from_job) || "—"} → ${textOf(row.to_job)}`;
    const pay = (row.from_hourly == null || row.to_hourly == null) ? ""
      : `（${Number(row.from_hourly).toFixed(2)} → ${Number(row.to_hourly).toFixed(2)}）`;
    return `<div class="mem-item">`
      + (row.day == null ? "" : `<span class="mem-chip time">Day ${escapeHtml(row.day)}</span>`)
      + `<span class="mem-chip">${escapeHtml(label)}</span>`
      + `<p>${escapeHtml(move + pay)}</p></div>`;
  }).join("");
  return html;
}

function renderStateMemory(payload) {
  const slots = scheduleEntries(payload.schedule);
  const scheduleHtml = slots.length
    ? `<div class="mem-timeline">${slots.map((slot) => `<div class="mem-slot">`
      + `<span class="mem-slot-time">${escapeHtml(slot.time || "—")}</span>`
      + `<span class="mem-slot-activity">${escapeHtml(slot.activity)}</span></div>`).join("")}</div>`
    : "";

  const habits = (payload.habits && typeof payload.habits === "object") ? payload.habits : {};
  const habitRows = Object.entries(habits)
    .filter(([, v]) => v && typeof v === "object")
    .sort((a, b) => (Number(b[1].strength) || 0) - (Number(a[1].strength) || 0));
  const habitsHtml = habitRows.length
    ? habitRows.map(([key, habit]) => {
      const context = String(key).split("|").filter(Boolean);
      const day = habit.last_updated_day;
      return `<div class="mem-item">${memChips(context, "neutral")}`
        + `<p>${escapeHtml(textOf(habit.preferred_action))}</p>`
        + `<div class="mem-row"><span class="mem-label">${escapeHtml(tr("memory.habit_strength", "强度"))}</span>`
        + `<span class="mem-value">${memBar(habit.strength)}`
        + (day == null ? "" : `<span class="mem-strength">· ${escapeHtml(tr("memory.habit_updated", "更新于 Day"))} ${escapeHtml(day)}</span>`)
        + `</span></div></div>`;
    }).join("")
    : "";

  const intentions = (payload.intentions && typeof payload.intentions === "object") ? payload.intentions : {};
  const intentionRows = Object.entries(intentions).map(([key, value]) => {
    const label = INTENTION_LABELS[key] ? tr(`memory.intent.${key}`, INTENTION_LABELS[key]) : key;
    if (Array.isArray(value)) return memRow(label, memChips(value, key === "avoidances" ? "warn" : ""));
    const text = textOf(value);
    return text ? memRow(label, escapeHtml(text)) : "";
  }).join("");

  const html = memBlock(tr("memory.block_employment", "职业"), employmentHtml(payload.employment))
    + memBlock(tr("memory.block_schedule", "日程"), scheduleHtml)
    + memBlock(tr("memory.block_habits", "习惯"), habitsHtml)
    + memBlock(tr("memory.block_intentions", "意图"), intentionRows);
  els.stateMemoryView.innerHTML = html || emptyHtml(tr("memory.no_state", "暂无日程 / 习惯 / 意图。"));
}

// The episodes endpoint returns a byte tail of a JSONL file, so the first line
// is often truncated mid-object — unparseable lines are simply skipped.
function parseEpisodes(text) {
  const out = [];
  String(text || "").split("\n").forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed && typeof parsed === "object") out.push(parsed);
    } catch (_) { /* partial line from the tail cut */ }
  });
  return out;
}

const PLAN_LABELS = {
  goal: "目标", constraint: "顾虑", urge: "冲动", plan: "打算", expected_outcome: "预期",
};
const REFLECTION_LABELS = {
  result: "结果", feeling: "感受", lesson: "教训", next_bias: "后续倾向",
};

function structRows(struct, labels) {
  if (!struct || typeof struct !== "object") return "";
  return Object.entries(struct)
    .map(([key, value]) => memRow(labels[key] || key, escapeHtml(textOf(value))))
    .join("");
}

function travelHtml(travel) {
  if (!travel || typeof travel !== "object") return "";
  const bits = [];
  if (travel.mode) bits.push(textOf(travel.mode));
  if (Number(travel.distance_km)) bits.push(`${Number(travel.distance_km).toFixed(2)} km`);
  if (Number(travel.minutes)) bits.push(`${Number(travel.minutes)} min`);
  if (Number(travel.cost)) bits.push(`¥${Number(travel.cost).toFixed(2)}`);
  if (travel.status) bits.push(textOf(travel.status));
  return bits.length ? memChips(bits, "neutral") : "";
}

function deltaChips(delta) {
  if (!delta || typeof delta !== "object") return "";
  const entries = Object.entries(delta)
    .filter(([, v]) => typeof v === "number" && Math.abs(v) >= 0.005)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 8);
  return entries.map(([key, value]) => `<span class="mem-chip ${value >= 0 ? "up" : "down"}">`
    + `${escapeHtml(key)} ${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(2)}</span>`).join("");
}

function renderEpisodes(tailText) {
  const episodes = parseEpisodes(tailText);
  if (!episodes.length) {
    els.episodesView.innerHTML = emptyHtml(__("memory.no_episodes"));
    return;
  }
  // Newest first: the tail is chronological.
  els.episodesView.innerHTML = episodes.slice().reverse().map((ep) => {
    const when = `D${textOf(ep.day) || "?"} · ${textOf(ep.time) || "--:--"}`;
    const valence = typeof ep.valence === "number" ? ep.valence : null;
    const summary = `<summary><span class="mem-chip time">${escapeHtml(when)}</span>`
      + `<span class="ep-title">${escapeHtml(textOf(ep.final_activity) || textOf(ep.scheduled_activity))}</span>`
      + (ep.location ? `<span class="mem-chip neutral">${escapeHtml(textOf(ep.location))}</span>` : "")
      + (valence == null ? "" : `<span class="mem-chip ${valence >= 0 ? "up" : "down"}">${valence >= 0 ? "+" : "−"}${Math.abs(valence).toFixed(2)}</span>`)
      + `</summary>`;
    const body = memRow(tr("memory.ep.scheduled", "计划"), escapeHtml(textOf(ep.scheduled_activity)))
      + memRow(tr("memory.ep.action", "行动"), escapeHtml(textOf(ep.action)))
      + memRow(tr("memory.ep.travel", "移动"), travelHtml(ep.travel))
      + memRow(tr("memory.ep.env_events", "环境事件"), memChips(ep.env_events, "warn"))
      + memRow(tr("memory.ep.life_events", "人生事件"), memChips(ep.life_events, "warn"))
      + memRow(tr("memory.ep.partners", "社交对象"), memChips(ep.social_partners, "neutral"))
      + memRow(tr("memory.ep.perception", "感知"), escapeHtml(textOf(ep.perception)))
      + structRows(ep.plan_struct, PLAN_LABELS)
      + memRow(tr("memory.ep.outcome", "结果"), escapeHtml(textOf(ep.outcome)))
      + structRows(ep.reflection_struct, REFLECTION_LABELS)
      + memRow(tr("memory.ep.delta", "状态变化"), deltaChips(ep.delta))
      + memRow(tr("memory.ep.tags", "标签"), memChips(ep.tags, "neutral"));
    return `<details class="ep-card">${summary}<div class="ep-body">${body}</div></details>`;
  }).join("");
}

function renderAgentLog(logText) {
  const lines = String(logText || "").split("\n").filter((line) => line.trim());
  if (!lines.length) {
    els.agentLogView.innerHTML = emptyHtml(__("memory.no_agent_log"));
    return;
  }
  const nearBottom = els.agentLogView.scrollTop + els.agentLogView.clientHeight
    >= els.agentLogView.scrollHeight - 30;
  els.agentLogView.innerHTML = lines.map((line) => {
    // Simulator log lines are either "[Tag ...] body" or "Label: body".
    const bracket = line.match(/^\s*\[([^\]]{1,60})\]\s*([\s\S]*)$/);
    const labelled = bracket ? null : line.match(/^\s*([A-Za-z]{1,12}):\s*([\s\S]*)$/);
    const match = bracket || labelled;
    if (!match) return `<div class="log-line plain"><span class="log-text">${escapeHtml(line)}</span></div>`;
    return `<div class="log-line"><span class="log-tag">${escapeHtml(match[1])}</span>`
      + `<span class="log-text">${escapeHtml(match[2])}</span></div>`;
  }).join("");
  if (nearBottom) els.agentLogView.scrollTop = els.agentLogView.scrollHeight;
}

// ------------------------------------------------------------- raw data modal

function memoryRawSources() {
  const payload = state.memoryPayload || {};
  const id = state.selectedAgentId || 0;
  return [
    {
      key: "long_term",
      label: __("memory.long_term"),
      format: "JSON",
      filename: `agent_${id}.json`,
      mime: "application/json;charset=utf-8",
      text: JSON.stringify(payload.memory || [], null, 2),
    },
    {
      key: "state",
      label: __("memory.schedule"),
      format: "JSON",
      filename: `agent_${id}_state_memory.json`,
      mime: "application/json;charset=utf-8",
      text: JSON.stringify({
        schedule: payload.schedule || {},
        habits: payload.habits || {},
        intentions: payload.intentions || {},
      }, null, 2),
    },
    {
      key: "episodes",
      label: __("memory.recent_episodes"),
      format: "JSONL",
      filename: `agent_${id}_episodes.jsonl`,
      mime: "application/x-ndjson;charset=utf-8",
      text: payload.episodes_tail || "",
    },
    {
      key: "log",
      label: __("memory.agent_log"),
      format: "TEXT",
      filename: `agent_${id}.log`,
      mime: "text/plain;charset=utf-8",
      text: payload.log_tail || "",
    },
    {
      key: "all",
      label: tr("raw.all", "全部（含 goals）"),
      format: "JSON",
      filename: `agent_${id}_memory_payload.json`,
      mime: "application/json;charset=utf-8",
      text: JSON.stringify(payload, null, 2),
    },
  ];
}

function currentRawSource() {
  const sources = memoryRawSources();
  return sources.find((s) => s.key === state.rawSourceKey) || sources[0];
}

function renderRawModal() {
  const sources = memoryRawSources();
  els.rawModalTabs.innerHTML = sources.map((source) => `<button type="button" class="raw-modal-tab`
    + `${source.key === state.rawSourceKey ? " active" : ""}" data-raw-tab="${source.key}">`
    + `${escapeHtml(source.label)}</button>`).join("");
  const active = currentRawSource();
  els.rawModalBody.textContent = active.text || tr("raw.empty", "（无内容）");
  const chars = (active.text || "").length;
  els.rawModalMeta.textContent = `${active.filename} · ${active.format} · ${chars.toLocaleString()} chars`;
  els.rawDownloadBtn.disabled = !chars;
  els.rawCopyBtn.disabled = !chars;
}

function openRawModal(sourceKey) {
  if (!state.memoryPayload) {
    message(tr("raw.no_data", "请先选择居民并加载记忆。"), "error");
    return;
  }
  if (sourceKey) state.rawSourceKey = sourceKey;
  renderRawModal();
  els.rawModal.hidden = false;
}

function closeRawModal() {
  els.rawModal.hidden = true;
}

function downloadText(filename, text, mime) {
  const url = URL.createObjectURL(new Blob([text], { type: mime || "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function runSimulation(reset = false) {
  message(reset ? "正在重置并启动仿真..." : __("sim.starting"));
  const payload = { reset, config: configPayloadFromForm() };
  await api("/api/run/start", { method: "POST", body: JSON.stringify(payload) });
  // A new run truncates the log file, so the offset we hold no longer maps to
  // anything — drop it and let the next poll reload from the top.
  resetRunLog();
  state.follow = true;
  message("仿真已启动，地图将实时跟随最新帧");
  await refreshStatus();
}

// 定时运行: hand the server the wall clock and the current form config, and let
// its timer start the run — the page does not have to stay open.
async function scheduleSimulation() {
  const at = els.scheduleAtInput.value;
  if (!at) {
    message(tr("sim.schedule_pick_time", "请先选择开始运行的时间。"), "error");
    return;
  }
  const payload = { at, reset: false, config: configPayloadFromForm() };
  const status = await api("/api/run/schedule", { method: "POST", body: JSON.stringify(payload) });
  message(window.__f("sim.scheduled", { at: status.scheduled_at || at }));
  await refreshStatus();
}

async function cancelScheduledSimulation() {
  await api("/api/run/schedule/cancel", { method: "POST", body: "{}" });
  message(tr("sim.schedule_cancelled", "已取消定时运行"));
  await refreshStatus();
}

async function stopSimulation() {
  await api("/api/run/stop", { method: "POST", body: "{}" });
  message("已停止仿真");
  await refreshStatus();
}

function resetRunLog() {
  state.runLog = { text: "", offset: null, size: 0, skipped: 0 };
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// The status poll ships only the bytes appended since our offset, so the panel
// accumulates the full log instead of the trailing window it used to show.
function applyRunLog(status) {
  const text = status.log_tail || "";
  if (status.log_append) {
    if (text) state.runLog.text += text;
  } else {
    state.runLog.text = text;
    // Only a full reload can drop the head of the log, so the notice about it
    // survives the appends that follow.
    state.runLog.skipped = Number(status.log_skipped_bytes || 0);
  }
  state.runLog.offset = Number(status.log_offset || 0);
  state.runLog.size = Number(status.log_size || 0);
  setLogText(els.runLogBox, state.runLog.text || __("run_log.no_log"));
  renderRunLogMeta();
}

function renderRunLogMeta() {
  const { text, size, skipped } = state.runLog;
  if (!size) {
    els.runLogMeta.textContent = "";
    return;
  }
  const lines = text ? text.replace(/\n$/, "").split("\n").length : 0;
  const parts = [window.__f("run_log.meta", { lines, size: formatBytes(size) })];
  if (skipped) parts.push(window.__f("run_log.truncated", { size: formatBytes(skipped) }));
  els.runLogMeta.textContent = parts.join(" · ");
}

function exportRunLog() {
  if (!state.runLog.size) {
    message(__("run_log.no_log"), "error");
    return;
  }
  // The server streams the untruncated log as Markdown and names the file via
  // Content-Disposition, so nothing has to be buffered in the page.
  const link = document.createElement("a");
  link.href = "/api/run/log/export";
  document.body.appendChild(link);
  link.click();
  link.remove();
  message(__("run_log.exported"));
}

async function refreshStatus() {
  const offset = state.runLog.offset;
  const status = await api(`/api/run/status${offset == null ? "" : `?log_offset=${offset}`}`);
  state.running = Boolean(status.running);
  state.scheduledAt = status.scheduled_at || null;
  syncRunButtons();
  const badge = status.running
    ? __("sim.running")
    : status.returncode == null ? __("sim.not_run") : __("sim.finished") + " " + status.returncode;
  // A pending schedule is the most useful thing the badge can say while
  // nothing runs, so it takes over the idle text.
  els.runStatusBadge.textContent = !status.running && state.scheduledAt
    ? window.__f("sim.scheduled_badge", { at: state.scheduledAt })
    : badge;
  els.runStatusBadge.className = `status-badge ${status.running ? "running" : status.returncode === 0 ? "done" : status.returncode ? "error" : ""}`;
  // A timer that fired but could not start the run reports once, here.
  if (status.schedule_error && status.schedule_error !== state.scheduleError) {
    message(window.__f("sim.schedule_failed", { error: status.schedule_error }), "error");
  }
  state.scheduleError = status.schedule_error || null;
  applyRunLog(status);
  if (status.running) loadTrace(false).catch(() => {});
}

// The simulator only rewrites simulation_trace.json every N frames but
// updates latest_frame.json on every step, so a live view has to merge both.
function allFrames() {
  const traceFrames = state.trace && Array.isArray(state.trace.frames) ? state.trace.frames : [];
  if (!state.liveFrames.size) return traceFrames;
  const lastFlushed = traceFrames.length
    ? Number(traceFrames[traceFrames.length - 1].index ?? traceFrames.length - 1)
    : -1;
  const extra = Array.from(state.liveFrames.values())
    .filter((frame) => Number(frame.index) > lastFlushed)
    .sort((a, b) => Number(a.index) - Number(b.index));
  return traceFrames.concat(extra);
}

async function loadTrace(showErrors = true) {
  try {
    const response = await fetch(`/output/visualization/simulation_trace.json?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const trace = await response.json();
    const generatedAt = trace.meta && trace.meta.generated_at;
    if (generatedAt && generatedAt !== state.traceGeneratedAt) {
      // New run: drop frames captured from the previous run.
      state.traceGeneratedAt = generatedAt;
      state.liveFrames.clear();
      state.frameIndex = 0;
      state.follow = true;
      state.avatarCache.clear();
      state.trace = trace;
      // Avatar paths come from the trace, so refresh the roster faces once
      // per run rather than on every poll.
      renderSimRoster();
    }
    state.trace = trace;
  } catch (error) {
    if (showErrors) {
      els.traceStatus.textContent = __("trace.load_failed") + ": " + error.message;
      drawEmptyMap();
    }
    if (!state.trace) return;
  }
  try {
    const response = await fetch(`/output/visualization/latest_frame.json?t=${Date.now()}`, { cache: "no-store" });
    if (response.ok) {
      const latest = await response.json();
      const frame = latest && latest.frame;
      if (frame && frame.index != null && Array.isArray(frame.agents)) {
        state.liveFrames.set(Number(frame.index), frame);
      }
    }
  } catch (_error) {
    // latest_frame is best-effort; the flushed trace still renders.
  }
  const traceFrames = Array.isArray(state.trace.frames) ? state.trace.frames : [];
  const lastFlushed = traceFrames.length
    ? Number(traceFrames[traceFrames.length - 1].index ?? traceFrames.length - 1)
    : -1;
  Array.from(state.liveFrames.keys()).forEach((key) => {
    if (key <= lastFlushed) state.liveFrames.delete(key);
  });
  const frames = allFrames();
  if (!frames.length) state.frameIndex = 0;
  else if (state.follow) state.frameIndex = frames.length - 1;
  else state.frameIndex = Math.min(state.frameIndex, frames.length - 1);
  renderTrace();
}

function currentFrame() {
  return allFrames()[state.frameIndex] || null;
}

function renderTrace() {
  const frames = allFrames();
  const frame = frames[state.frameIndex] || null;
  if (!frame) {
    // No agent frames yet — but if the trace already carries the map, draw it
    // (terrain + nodes) instead of a blank placeholder, so the city map is
    // visible as soon as a run starts, before any frame is produced.
    const mapNodes = state.trace && state.trace.map && state.trace.map.nodes;
    if (Array.isArray(mapNodes) && mapNodes.length) {
      drawMap([]);
    } else {
      drawEmptyMap();
    }
    if (state.trace) els.traceStatus.textContent = "轨迹已初始化 · 0 帧";
    return;
  }
  renderSelectedAgentAvatar();
  els.frameTitle.textContent = `Day ${frame.day} · ${frame.time}`;
  const finished = state.trace.meta && state.trace.meta.finished;
  const liveCount = frames.length - (Array.isArray(state.trace.frames) ? state.trace.frames.length : 0);
  els.traceStatus.textContent = `${frames.length} 帧${liveCount > 0 ? `（含 ${liveCount} 实时帧）` : ""} · ${finished ? "已完成" : "写入中"}`;
  els.timelineSlider.max = String(Math.max(0, frames.length - 1));
  els.timelineSlider.value = String(state.frameIndex);
  els.timelineLabel.textContent = `${frame.date || ""} ${frame.weekday || ""} ${frame.time || ""}`.trim();
  if (els.followLatestInput) els.followLatestInput.checked = state.follow;
  els.latestFrameBox.textContent = JSON.stringify(frame, null, 2);
  drawMap(frames.slice(0, state.frameIndex + 1));
}

function drawEmptyMap() {
  mapView.renderEmpty(__("trace.waiting"));
  els.frameTitle.textContent = __("trace.not_loaded");
  els.timelineLabel.textContent = __("trace.no_frames");
  els.latestFrameBox.textContent = __("trace.no_current_frame");
}

// The terrain map (baked tiles, place markers, LOD landmark labels, agent
// trails, large avatars, zoom/pan) is rendered by the shared CityMapView
// module (site/shared/citymap-view.js) — the same renderer the simviz replay
// tab uses, so the two views stay identical.
function drawMap(framesUpTo) {
  mapView.setTrace(state.trace);
  mapView.render(framesUpTo);
}

function setupMapInteractions() {
  // Zoom (wheel / buttons) + pan (drag) are wired inside CityMapView.
}

async function fosExport() {
  const hint = els.fosHintInput.value.trim() || null;
  const english = els.fosEnglishCheckbox.checked;
  els.fosOutputBox.textContent = window.__("fos_export.generating");
  const payload = { hint, english };
  const result = await api("/api/fos-export", { method: "POST", body: JSON.stringify(payload) });
  if (result.error) {
    els.fosOutputBox.textContent = "Error: " + result.error;
    return;
  }
  let output = result.prompt;
  if (result.summary) {
    output = result.summary + "\n\n" + output;
  }
  els.fosOutputBox.textContent = output;
}

async function interview() {
  if (!state.selectedAgentId) return;
  els.interviewOutput.textContent = __("interview.running");
  const questions = els.interviewQuestions.value.split("\n").map((line) => line.trim()).filter(Boolean);
  if (!questions.length) {
    els.interviewOutput.textContent = "请先在上方输入至少一个问题（每行一个）。";
    return;
  }
  const payload = {
    agent_id: state.selectedAgentId,
    context: els.interviewContext.value.trim(),
    questions,
  };
  const startedAt = Date.now();
  els.interviewOutput.textContent = "采访运行中... 0s";
  const timer = window.setInterval(() => {
    const elapsed = Math.round((Date.now() - startedAt) / 1000);
    els.interviewOutput.textContent = `采访运行中... ${elapsed}s（LLM 生成通常需要 1-3 分钟）`;
  }, 1000);
  try {
    const result = await api("/api/interview", { method: "POST", body: JSON.stringify(payload) });
    els.interviewOutput.textContent = [result.stdout, result.stderr].filter(Boolean).join("\n") || __f("interview.no_result", {code: result.returncode});
  } finally {
    window.clearInterval(timer);
  }
}

function initCollapsibles() {
  document.querySelectorAll(".panel.collapsible").forEach((panel) => {
    const head = panel.querySelector(".section-head");
    if (!head || head.__collapseWired) return;
    head.__collapseWired = true;
    const chevron = document.createElement("button");
    chevron.type = "button";
    chevron.className = "collapse-toggle";
    chevron.setAttribute("aria-label", "折叠 / 展开");
    const host = head.querySelector(".head-actions") || head;
    host.appendChild(chevron);
    const sync = () => chevron.setAttribute("aria-expanded", String(!panel.classList.contains("is-collapsed")));
    sync();
    head.addEventListener("click", (e) => {
      const t = e.target;
      if (t !== chevron && t.closest && t.closest("button, a, select, input, textarea, .help-tip")) return;
      panel.classList.toggle("is-collapsed");
      sync();
    });
  });
}

function initFrameJson() {
  const box = document.querySelector(".frame-json");
  if (!box) return;
  const toggle = box.querySelector(".frame-json-toggle");
  if (!toggle || toggle.__wired) return;
  toggle.__wired = true;
  toggle.addEventListener("click", (e) => {
    if (e.target.closest(".help-tip")) return;
    box.classList.toggle("is-collapsed");
  });
}

function bindEvents() {
  initCollapsibles();
  initFrameJson();
  els.stepUnitSelect.addEventListener("change", onStepUnitChanged);
  els.fastForwardInput.addEventListener("change", onFastForwardChanged);
  els.saveConfigBtn.addEventListener("click", withBusy(els.saveConfigBtn, saveConfig));
  els.runBtn.addEventListener("click", withBusy(els.runBtn, () => runSimulation(false)));
  els.scheduleRunBtn.addEventListener("click", withBusy(els.scheduleRunBtn, scheduleSimulation));
  els.cancelScheduleBtn.addEventListener("click", withBusy(els.cancelScheduleBtn, cancelScheduledSimulation));
  els.resetRunBtn.addEventListener("click", withBusy(els.resetRunBtn, () => runSimulation(true)));
  els.stopBtn.addEventListener("click", withBusy(els.stopBtn, stopSimulation));
  els.reloadTraceBtn.addEventListener("click", withBusy(els.reloadTraceBtn, async () => {
    await loadTrace(true);
    message("轨迹已刷新");
  }));
  els.reloadStatusBtn.addEventListener("click", withBusy(els.reloadStatusBtn, async () => {
    // An explicit refresh reloads the whole log, so a panel that missed polls
    // (or a log rotated behind our back) recovers.
    resetRunLog();
    await refreshStatus();
    message("运行状态已刷新");
  }));
  els.exportRunLogBtn.addEventListener("click", exportRunLog);
  els.agentSelect.addEventListener("change", () => selectAgent(els.agentSelect.value));
  if (els.simRosterList) {
    els.simRosterList.addEventListener("click", (event) => {
      const chip = event.target.closest(".roster-chip");
      if (chip) selectAgent(chip.dataset.agentId);
    });
  }
  els.agentIdsInput.addEventListener("input", refreshAgentOptionLabels);
  els.randomnessInput.addEventListener("input", () => {
    els.randomnessValue.textContent = Number(els.randomnessInput.value).toFixed(2);
  });
  els.routineRandomnessInput.addEventListener("input", () => {
    els.routineRandomnessValue.textContent = Number(els.routineRandomnessInput.value).toFixed(2);
  });
  if (els.toggleSimBtn) els.toggleSimBtn.addEventListener("click", toggleSelectedAgentInSim);
  els.refreshAgentBtn.addEventListener("click", withBusy(els.refreshAgentBtn, async () => {
    await loadProfile();
    message("Profile 已刷新");
  }));
  if (els.refreshFamilyBtn) {
    els.refreshFamilyBtn.addEventListener("click", withBusy(els.refreshFamilyBtn, async () => {
      await loadFamily();
      message("家庭结构已刷新");
    }));
  }
  els.reloadMemoryBtn.addEventListener("click", withBusy(els.reloadMemoryBtn, async () => {
    await loadMemory();
    if (!els.rawModal.hidden) renderRawModal();
    message("记忆已刷新");
  }));
  els.rawMemoryBtn.addEventListener("click", () => openRawModal(state.rawSourceKey));
  document.querySelectorAll("[data-raw-open]").forEach((btn) => {
    btn.addEventListener("click", () => openRawModal(btn.getAttribute("data-raw-open")));
  });
  els.rawModal.addEventListener("click", (event) => {
    if (event.target.closest("[data-raw-close]")) { closeRawModal(); return; }
    const tab = event.target.closest("[data-raw-tab]");
    if (tab) {
      state.rawSourceKey = tab.getAttribute("data-raw-tab");
      renderRawModal();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !els.rawModal.hidden) closeRawModal();
  });
  els.rawCopyBtn.addEventListener("click", () => {
    const source = currentRawSource();
    if (!source.text) return;
    navigator.clipboard.writeText(source.text)
      .then(() => message(tr("raw.copied", "已复制原始内容")))
      .catch(() => message(tr("raw.copy_failed", "复制失败"), "error"));
  });
  els.rawDownloadBtn.addEventListener("click", () => {
    const source = currentRawSource();
    if (!source.text) return;
    downloadText(source.filename, source.text, source.mime);
    message(`${source.filename} ${tr("raw.downloaded", "已下载")}`);
  });
  els.interviewBtn.addEventListener("click", withBusy(els.interviewBtn, () => interview().catch((error) => {
    els.interviewOutput.textContent = `采访失败：${error.message}`;
  })));
  els.lifeEventTemplateSelect.addEventListener("change", () => {
    els.lifeEventTitleInput.value = "";
    els.lifeEventDescriptionInput.value = "";
    applyLifeEventTemplate();
  });
  els.useSelectedAgentBtn.addEventListener("click", () => {
    if (state.selectedAgentId) {
      els.lifeEventAgentInput.value = String(state.selectedAgentId);
      message(`人生事件目标已设为 Agent ${state.selectedAgentId}`);
    }
  });
  els.addLifeEventBtn.addEventListener("click", withBusy(els.addLifeEventBtn, addLifeEvent));
  els.reloadLifeEventsBtn.addEventListener("click", withBusy(els.reloadLifeEventsBtn, async () => {
    await loadLifeEvents();
    message("人生事件已刷新");
  }));
  els.fosExportBtn.addEventListener("click", () => fosExport().catch((error) => message(error.message, "error")));
  els.fosCopyBtn.addEventListener("click", () => {
    const text = els.fosOutputBox.textContent;
    if (text && text !== window.__("fos_export.no_output")) {
      navigator.clipboard.writeText(text).then(() => message("Copied!")).catch(() => message("Copy failed"));
    }
  });
  els.fosDownloadBtn.addEventListener("click", () => {
    const text = els.fosOutputBox.textContent;
    if (!text || text === window.__("fos_export.no_output")) return;
    const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    const stamp = new Date().toISOString().slice(0, 19).replace(/-/g, "").replace("T", "-").replace(/:/g, "");
    link.download = `fos-prompt-${stamp}.md`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    message(window.__("fos_export.downloaded"));
  });
  els.timelineSlider.addEventListener("input", () => {
    state.frameIndex = Number(els.timelineSlider.value || 0);
    // Scrubbing away from the newest frame pauses follow; dragging back to
    // the end resumes it.
    state.follow = state.frameIndex >= allFrames().length - 1;
    renderTrace();
  });
  if (els.followLatestInput) {
    els.followLatestInput.addEventListener("change", () => {
      state.follow = els.followLatestInput.checked;
      if (state.follow) {
        const frames = allFrames();
        state.frameIndex = frames.length ? frames.length - 1 : 0;
      }
      renderTrace();
    });
  }
  els.selectedAgentAvatar.addEventListener("error", () => {
    els.selectedAgentAvatar.style.visibility = "hidden";
  });
  els.selectedAgentAvatar.addEventListener("load", () => {
    els.selectedAgentAvatar.style.visibility = "visible";
  });
}

async function init() {
  bindEvents();
  setupMapInteractions();
  drawEmptyMap();
  const steps = [
    ["配置", loadConfig],
    ["人物列表", loadAgents],
    ["人生事件", loadLifeEvents],
    ["Profile", loadProfile],
    ["家庭", loadFamily],
    ["记忆", loadMemory],
    ["运行状态", refreshStatus],
  ];
  for (const [label, step] of steps) {
    try {
      await step();
    } catch (error) {
      message(`${label}加载失败: ${error.message}`, "error");
    }
  }
  await loadTrace(false);
  state.pollTimer = window.setInterval(() => {
    refreshStatus().catch(() => {});
    loadTrace(false).catch(() => {});
    loadLifeEvents().catch(() => {});
  }, 2500);
}

// i18n.js fires locale-changed on `document` with bubbles:false, so re-render
// the memory views (whose labels are baked in at render time) from the cached
// payload — no refetch needed.
document.addEventListener("locale-changed", function () {
  if (!state.memoryPayload) return;
  renderMemory();
  if (!els.rawModal.hidden) renderRawModal();
});

// Re-render dynamic UI when language changes
window.addEventListener("locale-changed", function () {
  refreshStatus().catch(() => {});
  loadTrace(false).catch(() => {});
  loadLifeEvents().catch(() => {});
  loadMemory().then(() => { if (!els.rawModal.hidden) renderRawModal(); }).catch(() => {});
  renderTrace();
});

init().catch((error) => message(error.message, "error"));
