/* GAWorld Agent Studio — display + edit UI wired to the dashboard API.
 * Fields map to GAWorld's real seed model: identity + 9 normalized [0,1]
 * state variables (CSV), narrative profile (Markdown), memory / skills /
 * finance (read-only, populated by the simulator). */

"use strict";

/* `en` is the machine name, rendered under the label as a fixed identifier —
   it is the state variable's name in the CSV, not a translation, so it stays a
   literal in both locales. Everything else comes from the locale at call time;
   as literals they froze whatever language was current when this file was
   evaluated. */
const STATE_VARS = [
  { key: "emotion",             en: "emotion" },
  { key: "stress",              en: "stress" },
  { key: "econ_security",       en: "econ security" },
  { key: "city_identity",       en: "city identity" },
  { key: "policy_sensitivity",  en: "policy sensitivity" },
  { key: "platform_dependence", en: "platform dependence" },
  { key: "risk_preference",     en: "risk preference" },
  { key: "voice_propensity",    en: "voice propensity" },
  { key: "mobility_intent",     en: "mobility intent" },
];

const varLabel = (v) => __(`st.name.${v.key}`);
/* The radar is 200 units wide and holds nine labels around its rim, which is
   not enough room for a phrase: "经济安全感" already overflowed the viewBox by
   22 units and "Economic security" by 52. Axis labels are abbreviated by
   convention, so the chart gets its own one-word set. */
const varAxisLabel = (v) => __(`st.axis.${v.key}`);
const machineName = (v) => (getLocale() === "en" ? "" : ` <span class="en">${v.en}</span>`);
const poleLo = (v) => __(`st.lo.${v.key}`);
const poleHi = (v) => __(`st.hi.${v.key}`);
const BEHAVIOR_KEYS = ["mobility_intent", "voice_propensity", "risk_preference", "platform_dependence", "policy_sensitivity"];

const store = {
  agents: [],
  currentId: null,
  detail: null,
  creating: false,
  step: 1,
  draft: null, // { identity:{...}, state:{...}, profile_text, narrative:{personality, job} }
  goalsDraft: null, // working copy of the three-tier goals, edited inline in step 6
  goalSeq: 0, // counter for client-side ids of newly added goals
  stateDirty: false, // step 2 sliders moved but not yet confirmed
  profileEditing: false, // step 1 profile shows rendered Markdown until this flips
  profileEdit: "", // buffer for the profile textarea, discarded on cancel
  socialDraft: null, // working copy of the relationship edges, edited inline in step 5
  socialRemoved: [], // ids deleted from socialDraft, sent with the next save
  familyPreview: null, // server-side family preview for the current agent (step 5)
  familyDraft: null, // working copy of this agent's family override
  familyLoading: false, // guards the lazy preview fetch against retry loops
  financeDraft: null, // working copy of the editable finance state (step 7)
  memGraph: null, // { svg, nodes } for the inline memory graph
  memGraphBig: null, // { svg, nodes } for the zoomed modal graph
  memPick: null, // index into memGraph.nodes of the node whose body is shown
  big5: null, // { values, authored, paragraph, consistency, ... } from /api/agents/<id>/big5
  big5Draft: null, // working copy of the five z scores, edited by the step-2 sliders
  big5Dirty: false, // sliders moved but not yet written to the seed CSV
  big5Loading: false, // guards the lazy fetch against retry loops
};

const $ = (sel) => document.querySelector(sel);

async function api(path, options = {}) {
  const res = await fetch(path, { cache: "no-store", headers: { "Content-Type": "application/json" }, ...options });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok || payload.error) throw new Error(payload.error || `HTTP ${res.status}`);
  return payload;
}

function foot(msg, tone = "") {
  const box = $("#footMsg");
  box.textContent = msg || "";
  box.className = "foot-msg " + tone;
}

function esc(text) {
  return String(text == null ? "" : text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function clamp01(v) { return Math.max(0, Math.min(1, Number(v) || 0)); }

/* Minimal Markdown → HTML, same subset the homepage profile panel renders. */
function renderMarkdown(md) {
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

/* ---------- avatar ---------- */
function placeholderAvatar(name) {
  const ch = esc((name || "?").trim().slice(0, 1) || "?");
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 120'><rect width='120' height='120' fill='#e3ede4'/><text x='60' y='78' font-family='Georgia,serif' font-size='58' fill='#13795b' text-anchor='middle'>${ch}</text></svg>`;
  return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
}
function setAvatar(id, name) {
  const img = $("#subjectAvatar");
  const ph = placeholderAvatar(name);
  if (id == null) { img.src = ph; return; }
  img.onerror = () => { img.onerror = null; img.src = ph; };
  img.src = `/api/agents/${Number(id)}/avatar`;
}

/* ---------- radar ---------- */
function radarSVG(stateObj, withLabels) {
  const cx = 100, cy = 100, R = withLabels ? 66 : 74, n = STATE_VARS.length;
  const ang = (i) => (-90 + (i * 360) / n) * (Math.PI / 180);
  const pt = (i, r) => [cx + Math.cos(ang(i)) * r, cy + Math.sin(ang(i)) * r];
  let rings = "";
  [0.25, 0.5, 0.75, 1].forEach((f) => {
    const p = STATE_VARS.map((_, i) => pt(i, R * f).map((v) => v.toFixed(1)).join(",")).join(" ");
    rings += `<polygon points="${p}" fill="none" stroke="#cbd7cd" stroke-width="1"/>`;
  });
  let spokes = "", labels = "";
  STATE_VARS.forEach((v, i) => {
    const [x, y] = pt(i, R);
    spokes += `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="#e0e8e0" stroke-width="1"/>`;
    if (withLabels) {
      const [lx, ly] = pt(i, R + 15);
      const anchor = Math.abs(lx - cx) < 6 ? "middle" : (lx > cx ? "start" : "end");
      labels += `<text x="${lx.toFixed(1)}" y="${(ly + 3).toFixed(1)}" font-size="8.5" fill="#5c6860" text-anchor="${anchor}">${esc(varAxisLabel(v))}</text>`;
    }
  });
  const poly = STATE_VARS.map((v, i) => pt(i, R * clamp01(stateObj[v.key])).map((c) => c.toFixed(1)).join(",")).join(" ");
  const dots = STATE_VARS.map((v, i) => { const [x, y] = pt(i, R * clamp01(stateObj[v.key])); return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.2" fill="#13795b"/>`; }).join("");
  const box = withLabels ? "-26 0 252 200" : "0 0 200 200";
  return `<svg viewBox="${box}">${rings}${spokes}<polygon points="${poly}" fill="rgba(19,121,91,0.18)" stroke="#13795b" stroke-width="1.6"/>${dots}${labels}</svg>`;
}

/* ---------- data ---------- */
async function loadAgents() {
  const payload = await api("/api/agents");
  store.agents = payload.agents || [];
  const sel = $("#agentSelect");
  sel.innerHTML = store.agents.map((a) => `<option value="${a.id}">${esc(a.id)} · ${esc(a.name)}</option>`).join("");
  if (store.agents.length && store.currentId == null) {
    store.currentId = store.agents[0].id;
  }
  sel.value = String(store.currentId);
}

function draftFromDetail(d) {
  return {
    identity: { ...d.identity },
    state: { ...d.state },
    profile_text: d.profile_text || "",
    narrative: { personality: "", job: "" },
  };
}

function blankDraft() {
  const state = {};
  STATE_VARS.forEach((v) => (state[v.key] = v.key === "emotion" ? 0.55 : 0.5));
  /* i18n-exempt-start: seed values written into the state CSV, not UI text */
  return {
    identity: { id: null, name: "", gender: "女", age: 30, hukou: "本地", residence: "杭州" },
    /* i18n-exempt-end */
    state,
    profile_text: "",
    narrative: { personality: "", job: "" },
  };
}

async function selectAgent(id) {
  store.creating = false;
  store.currentId = Number(id);
  $("#saveHint").textContent = __("sd.loading");
  const d = await api(`/api/agents/${id}/detail`);
  store.detail = d;
  store.draft = draftFromDetail(d);
  store.goalsDraft = cloneGoals(d.goals);
  store.socialDraft = cloneRelations(d.social);
  store.socialRemoved = [];
  store.financeDraft = cloneFinance(d.finance_state);
  store.stateDirty = false;
  store.profileEditing = false;
  store.memPick = null;
  store.familyPreview = null;
  store.familyDraft = null;
  $("#saveHint").textContent = __("sd.loaded");
  renderSubject();
  renderStep();
  // The family preview is a second request; render once without it so the
  // step is never blank, then again when it lands.
  loadFamilyPreview().then(() => { if (store.step === 5) renderStep(); });
  // Same pattern for the Big Five card: render step 2 without it rather than
  // blocking the whole step on a second request, then again when it lands.
  store.big5 = null;
  store.big5Draft = null;
  store.big5Dirty = false;
  loadBig5().then(() => { if (store.step === 2) renderStep(); });
}

function startCreate() {
  store.creating = true;
  store.currentId = null;
  store.detail = null;
  store.draft = blankDraft();
  store.goalsDraft = null;
  store.socialDraft = null;
  store.socialRemoved = [];
  store.financeDraft = null;
  store.stateDirty = false;
  store.profileEditing = false;
  store.memPick = null;
  store.familyPreview = null;
  store.familyDraft = null;
  store.step = 1;
  setActiveStepButton();
  $("#saveHint").textContent = __("sd.new_unsaved");
  renderSubject();
  renderStep();
  foot(__("sd.new_mode_hint"), "");
}

/* ---------- subject rail ---------- */
function renderSubject() {
  const dr = store.draft;
  if (!dr) return;
  const idt = dr.identity;
  setAvatar(store.creating ? null : store.currentId, idt.name);
  $("#subjectName").textContent = idt.name || (store.creating ? __("sd.new_resident") : "—");
  const bits = [store.creating ? __("sd.no_id") : `ID ${store.currentId}`, idt.gender, idt.age ? __f("sd.age_years", { n: idt.age }) : "", idt.residence].filter(Boolean);
  $("#subjectMeta").textContent = bits.join(" · ");
  $("#miniRadar").outerHTML = `<svg id="miniRadar" viewBox="0 0 200 200">${radarSVG(dr.state, false).replace(/^<svg[^>]*>|<\/svg>$/g, "")}</svg>`;
}

/* ---------- steps ---------- */
function setActiveStepButton() {
  document.querySelectorAll(".step").forEach((b) => {
    const n = Number(b.dataset.step);
    b.classList.toggle("is-active", n === store.step);
    b.classList.toggle("is-done", n < store.step);
  });
}

function field(label, inputHTML) {
  return `<label class="field"><span>${esc(label)}</span>${inputHTML}</label>`;
}

function renderStep() {
  if (!store.draft) { $("#stepBody").innerHTML = `<p class="section-note">${esc(__("sd.pick_resident"))}</p>`; return; }
  setActiveStepButton();
  const fn = [null, stepIdentity, stepState, stepSkills, stepMemory, stepSocial, stepBehavior, stepReview][store.step];
  $("#stepBody").innerHTML = fn();
  bindStep();
}

function stepIdentity() {
  const i = store.draft.identity;
  const extra = store.creating
    ? `<div class="card"><h3>${esc(__("sd.seed_title"))}</h3>
        ${field(__("sd.seed_job"), `<input data-nar="job" value="${esc(store.draft.narrative.job)}" placeholder="${esc(__("sd.seed_job_ph"))}">`)}
        ${field(__("sd.seed_personality"), `<textarea data-nar="personality" placeholder="${esc(__("sd.seed_personality_ph"))}">${esc(store.draft.narrative.personality)}</textarea>`)}
      </div>`
    : profileCard();
  return `
    <h2 class="section-title">${esc(__("sd.identity"))}</h2>
    <p class="section-note">${esc(__("sd.identity_note"))}</p>
    <div class="cols side">
      <div>
        <div class="card">
          <h3>${esc(__("sd.basics"))}</h3>
          ${field(__("sd.name"), `<input data-idt="name" value="${esc(i.name)}">`)}
          <div class="grid2">
            ${field(__("sd.gender"), `<input data-idt="gender" value="${esc(i.gender)}">`)}
            ${field(__("sd.age"), `<input data-idt="age" type="number" min="16" max="90" value="${esc(i.age)}">`)}
          </div>
          <div class="grid2">
            ${field(__("sd.hukou"), `<input data-idt="hukou" value="${esc(i.hukou)}">`)}
            ${field(__("sd.residence"), `<input data-idt="residence" value="${esc(i.residence)}">`)}
          </div>
        </div>
        ${extra}
      </div>
      <div class="card">
        <h3>${esc(__("sd.state_glance"))}</h3>
        <div class="viz-wrap">${radarSVG(store.draft.state, true)}</div>
      </div>
    </div>`;
}

/* Profile reads as rendered Markdown; “编辑” swaps in the raw source, and the
 * change only reaches the profile file once 确认修改 is pressed. */
function profileCard() {
  if (!store.profileEditing) {
    return `<div class="card">
      <h3>${esc(__("sd.profile"))}
        <button type="button" id="editProfileBtn" class="mini-btn">${esc(__("sd.edit"))}</button></h3>
      <div class="profile-md md-body" data-empty="${esc(__("sd.profile_empty"))}">${renderMarkdown(store.draft.profile_text)}</div>
    </div>`;
  }
  return `<div class="card">
    <h3>${esc(__("sd.profile_md"))}</h3>
    <label class="field"><span>${esc(__("sd.profile_write_back"))}</span>
      <textarea data-profile-edit style="min-height:220px">${esc(store.profileEdit)}</textarea></label>
    <div class="confirm-bar">
      <span class="confirm-hint">${esc(__("sd.profile_edit_hint"))}</span>
      <button type="button" id="cancelProfileBtn" class="button">${esc(__("sd.cancel"))}</button>
      <button type="button" id="confirmProfileBtn" class="button primary">${esc(__("sd.confirm"))}</button>
    </div>
  </div>`;
}

async function confirmProfile() {
  if (store.creating || store.currentId == null) return;
  try {
    foot(__("sd.saving_profile"));
    await api(`/api/agents/${store.currentId}/profile`, {
      method: "POST", body: JSON.stringify({ text: store.profileEdit }),
    });
    store.draft.profile_text = store.profileEdit;
    if (store.detail) store.detail.profile_text = store.profileEdit;
    store.profileEditing = false;
    foot(__("sd.profile_saved"), "ok");
    renderStep();
  } catch (err) {
    foot(__("sd.profile_save_failed") + err.message, "err");
  }
}

/* ---------------------------------------------------------------------------
 * Big Five (OCEAN) — a card of its own inside step 2.
 *
 * Deliberately NOT mixed into the nine state sliders above it, even though they
 * share a screen. Keeping OCEAN independent of those nine variables is the
 * whole point of how the scores were produced: the corpus was sampled first and
 * written from, with only two literature-backed correlations injected, because
 * scoring the prose instead just read the state variables back out (openness
 * correlated 0.90 with mobility_intent). A panel that presents them as one
 * family invites an operator to undo that by hand.
 *
 * These are z scores, not [0,1] — negative is the low pole, not "less of a good
 * thing" — so the sliders are centred on 0 and labelled with both poles.
 * ------------------------------------------------------------------------- */

const BIG5_DIMS = ["o", "c", "e", "a", "n"];

/* What each flag from the server means, in the operator's terms. The flags are
 * arithmetic on the scores against the authoring floor, not an analysis of the
 * paragraph text — so the copy says what to go and check, never "the paragraph
 * says X". */
const BIG5_FLAG_CLS = {
  rewrite: { flip: "bad", drift: "warn" },
  now_missing: "warn",
  now_moot: "warn",
  unknown: "",
};

function big5FlagInfo(flag) {
  if (!flag || flag.state === "ok") return null;
  const entry = BIG5_FLAG_CLS[flag.state];
  if (entry === undefined) return null;
  const variant = typeof entry === "string" ? null : (flag.severity in entry ? flag.severity : "drift");
  if (variant && !(variant in entry)) return null;
  const key = variant ? `${flag.state}.${variant}` : flag.state;
  return {
    cls: variant ? entry[variant] : entry,
    label: __(`sd.b5flag.${key}`),
    hint: __(`sd.b5hint.${key}`),
  };
}

async function loadBig5() {
  if (store.creating || store.currentId == null || store.big5Loading) return;
  store.big5Loading = true;
  try {
    store.big5 = await api(`/api/agents/${store.currentId}/big5`);
    store.big5Draft = { ...store.big5.values };
    store.big5Dirty = false;
  } catch (err) {
    store.big5 = { error: err.message };
    store.big5Draft = null;
  } finally {
    store.big5Loading = false;
  }
}

/* The trait names and pole descriptions travel in the payload in both
   languages (see BIG5_POLES_EN in dashboard_server.py) rather than as locale
   keys, because the same wording is shared with scripts/calibrate_big5.py —
   one table on the server keeps the panel and the calibrator describing the
   same poles. */
const big5Table = (data, field) =>
  (getLocale() === "en" ? data[`${field}_en`] : data[field]) || data[field] || {};

function big5Card() {
  if (store.creating) {
    return `<div class="card"><h3>${esc(__("sd.big5"))}</h3>
      <p class="section-note">${esc(__("sd.big5_unsaved"))}</p></div>`;
  }
  const data = store.big5;
  if (!data) return `<div class="card"><h3>${esc(__("sd.big5"))}</h3><p class="section-note">${esc(__("sd.reading"))}</p></div>`;
  if (data.error) {
    return `<div class="card"><h3>${esc(__("sd.big5"))}</h3>
      <p class="section-note">${esc(__("sd.read_failed"))}${esc(data.error)}</p></div>`;
  }
  const draft = store.big5Draft || data.values;
  const clip = Number(data.clip) || 2.5;
  const rows = BIG5_DIMS.map((dim) => {
    const z = Number(draft[dim] || 0);
    const poles = big5Table(data, "poles")[dim] || ["", ""];
    const flag = big5FlagInfo((data.consistency || {})[dim]);
    const mark = flag
      ? `<span class="b5-flag ${flag.cls}" title="${esc(flag.hint)}">${esc(flag.label)}</span>`
      : "";
    const distinct = Math.abs(z) >= Number(data.floor || 0.5);
    return `
    <div class="slider-row b5-row" data-b5row="${dim}">
      <div class="slabel">
        <span>${esc(big5Table(data, "names")[dim] || dim)} <span class="en">${dim.toUpperCase()}</span>${mark}</span>
        <span class="val${distinct ? " b5-distinct" : ""}">${z >= 0 ? "+" : ""}${z.toFixed(2)}</span>
      </div>
      <div class="b5-track"><input type="range" min="${-clip}" max="${clip}" step="0.05" value="${z}" data-b5="${dim}"></div>
      <div class="poles b5-poles"><span>${esc(poles[0])}</span><span class="b5-zero-label">0</span><span>${esc(poles[1])}</span></div>
    </div>`;
  }).join("");

  const flagged = BIG5_DIMS
    .map((dim) => [dim, big5FlagInfo((data.consistency || {})[dim])])
    .filter(([, f]) => f);
  const banner = flagged.length
    ? `<div class="b5-banner ${flagged.some(([, f]) => f.cls === "bad") ? "bad" : "warn"}">
         ${flagged.map(([dim, f]) =>
           `<div><b>${esc(big5Table(data, "names")[dim] || dim)}</b>${esc(__("sd.colon"))}${esc(f.hint)}</div>`).join("")}
       </div>`
    : "";

  const paragraph = data.paragraph
    ? `<div class="b5-para">${esc(data.paragraph)}</div>`
    : `<p class="section-note">${esc(__("sd.big5_no_para"))}</p>`;

  return `
    <div class="card b5-card">
      <h3>${esc(__("sd.big5"))} <span class="en">Big Five</span>
        <span class="b5-source">${esc(data.source || "—")}</span></h3>
      <p class="section-note">${__f("sd.big5_note", { floor: esc(data.floor), file: `<code>${esc(fileBase(data))}</code>` })}</p>
      ${rows}
      ${banner}
      <div class="confirm-bar">
        <span class="confirm-hint" id="big5Hint">${esc(store.big5Dirty ? __("sd.unconfirmed") : __("sd.matches_saved_scores"))}</span>
        <button type="button" id="confirmBig5Btn" class="button primary"${store.big5Dirty ? "" : " disabled"}>${esc(__("sd.confirm"))}</button>
      </div>
    </div>
    <div class="card b5-card">
      <h3>${esc(__("sd.b5_para_title"))}<span class="b5-note-inline">${esc(__("sd.b5_para_manual"))}</span></h3>
      <p class="section-note">${__("sd.b5_para_note")}</p>
      ${paragraph}
      <div class="confirm-bar">
        <span class="confirm-hint">${esc(__("sd.b5_para_where"))}</span>
        <button type="button" id="gotoProfileBtn" class="button">${esc(__("sd.b5_para_goto"))}</button>
      </div>
    </div>`;
}

function fileBase(data) {
  return "data/agents_big5.csv";
}

function markBig5Dirty() {
  store.big5Dirty = true;
  const hint = $("#big5Hint");
  if (hint) hint.textContent = __("sd.unconfirmed");
  const btn = $("#confirmBig5Btn");
  if (btn) btn.disabled = false;
}

async function confirmBig5() {
  if (store.currentId == null || !store.big5Draft) return;
  try {
    foot(__("sd.saving_big5"));
    store.big5 = await api(`/api/agents/${store.currentId}/big5`, {
      method: "POST", body: JSON.stringify({ values: store.big5Draft }),
    });
    store.big5Draft = { ...store.big5.values };
    store.big5Dirty = false;
    foot(__("sd.big5_saved"), "ok");
    renderStep();
  } catch (err) {
    foot(__("sd.big5_save_failed") + err.message, "err");
  }
}

function stepState() {
  const st = store.draft.state;
  const rows = STATE_VARS.map((v) => `
    <div class="slider-row" data-var="${v.key}">
      <div class="slabel"><span>${esc(varLabel(v))}${machineName(v)}</span><span class="val">${st[v.key].toFixed(2)}</span></div>
      <input type="range" min="0" max="1" step="0.01" value="${st[v.key]}" data-state="${v.key}">
      <div class="poles"><span>${poleLo(v)}</span><span>${poleHi(v)}</span></div>
    </div>`).join("");
  return `
    <h2 class="section-title">${esc(__("sd.state_title"))}</h2>
    <p class="section-note">${esc(__("sd.state_note"))}</p>
    <div class="cols side">
      <div class="card">${rows}
        <div class="confirm-bar">
          <span class="confirm-hint" id="stateHint">${esc(store.stateDirty ? __("sd.unconfirmed") : __("sd.matches_saved"))}</span>
          <button type="button" id="confirmStateBtn" class="button primary"${store.stateDirty ? "" : " disabled"}>${esc(__("sd.confirm"))}</button>
        </div>
      </div>
      <div class="card"><h3>${esc(__("sd.state_radar"))}</h3><div class="viz-wrap" id="bigRadar">${radarSVG(st, true)}</div></div>
    </div>
    <div class="b5-block">${big5Card()}</div>`;
}

function markStateDirty() {
  store.stateDirty = true;
  const hint = $("#stateHint");
  if (hint) hint.textContent = __("sd.unconfirmed");
  const btn = $("#confirmStateBtn");
  if (btn) btn.disabled = false;
}

async function confirmState() {
  if (!(await save())) return;
  store.stateDirty = false;
  const hint = $("#stateHint");
  if (hint) hint.textContent = __("sd.confirmed_written");
  const btn = $("#confirmStateBtn");
  if (btn) btn.disabled = true;
}

/* These four tables hold machine keys only; the text comes from the locale at
   call time. An unknown key is shown raw rather than replaced by a missing-key
   name — the simulator may emit a kind or phase this page has not met yet. */
const KINDS = ["hobby", "skill"];
const enumLabel = (known, prefix, key) =>
  known.indexOf(key) >= 0 ? __(prefix + key) : (key || "");
const COG_KEYS = [
  "skill_breadth", "deliverable_capacity", "growth_level",
  "memory_volume", "external_knowledge",
];

function chips(arr, cls = "") {
  return (arr && arr.length)
    ? `<div class="chips">${arr.map((s) => `<span class="chip ${cls}">${esc(s)}</span>`).join("")}</div>`
    : "";
}

function growthRows(growth) {
  const items = (growth && growth.items) || [];
  if (!items.length) return `<p class="section-note">${esc(__("sd.growth_empty"))}</p>`;
  return items.map((it) => {
    const practiced = it.total_minutes > 0
      ? __f("sd.practiced", { minutes: it.total_minutes, streak: it.streak_days, day: it.last_practiced_day })
      : __("sd.not_practiced");
    return `<div class="bar-row"><div class="bl">
        <b>${esc(it.name)} <span class="tag">${esc(enumLabel(KINDS, "std.kind.", it.kind))}</span></b>
        <small>${esc(it.motivation || it.category || "")}</small>
        <small class="growth-change">${esc(practiced)}</small></div>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.round(clamp01(it.level) * 100)}%"></div></div></div>`;
  }).join("");
}

function stepSkills() {
  const d = store.detail || {};
  const caps = d.capabilities;
  const priv = d.private_skills || [];
  const lib = d.skills || [];
  const cog = d.cognition;

  const capCard = `<div class="card"><h3>${esc(__("sd.caps"))} ${caps && caps.job_label ? `<span class="tag">${esc(caps.job_label)}</span>` : ""}</h3>
    ${caps
      ? `${chips(caps.skills)}${(caps.deliverables || []).length ? `<p class="section-note">${esc(__("sd.deliverables"))}</p>${chips(caps.deliverables)}` : ""}
         ${caps.notes ? `<p class="section-note">${esc(caps.notes)}</p>` : ""}`
      : `<p class="section-note">${esc(__("sd.caps_empty"))}</p>`}</div>`;
  const privCard = `<div class="card"><h3>${esc(__("sd.private_skills"))} <span class="tag">${esc(__f("sd.n_items", { n: priv.length }))}</span></h3>
    ${priv.length
      ? priv.map((s) => `<div class="bar-row"><div class="bl"><b>${esc(s.title)}</b><small>${esc(s.file)} · ${esc(__("sd.distilled"))}</small></div></div>`).join("")
      : `<p class="section-note">${esc(__("sd.private_skills_empty"))}</p>`}</div>`;
  const libCard = `<div class="card"><h3>${esc(__("sd.skill_library"))} <span class="tag">${esc(__f("sd.n_items", { n: lib.length }))}</span></h3>
    ${lib.length ? chips(lib.map((s) => s.title)) : `<p class="section-note">${esc(__("sd.skill_library_empty"))}</p>`}</div>`;
  const cogCard = `<div class="card"><h3>${esc(__("sd.cog_index"))}</h3>
    ${cog
      ? `<div class="cog-score">${cog.score}</div>
         ${COG_KEYS.map((key) => `
           <div class="bar-row"><div class="bl"><b>${esc(__("std.cog." + key))}</b></div>
           <div class="bar-track"><div class="bar-fill" style="width:${Math.round(clamp01(cog.components[key]) * 100)}%"></div></div></div>`).join("")}
         <p class="section-note">${esc(__("sd.cog_note"))}</p>`
      : `<p class="section-note">${esc(__("sd.shown_after_load"))}</p>`}</div>`;
  return `
    <h2 class="section-title">${esc(__("sd.skills_title"))}</h2>
    <p class="section-note">${esc(__("sd.skills_note"))}</p>
    <div class="cols two">
      <div>${capCard}<div class="card"><h3>${esc(__("sd.growth"))} <span class="tag">${esc(__f("sd.n_items", { n: ((d.growth || {}).items || []).length }))}</span></h3>${growthRows(d.growth)}</div></div>
      <div>${cogCard}${privCard}${libCard}</div>
    </div>`;
}

/* ---------- memory (step 4) ---------- */
const MEMORY_GROUPS = [
  { key: "long", color: "#385866" },
  { key: "rag", color: "#d6a81e" },
  { key: "habit", color: "#13795b" },
  { key: "intent", color: "#17211d" },
  { key: "sched", color: "#7a8b80" },
];
const memGroupLabel = (key) => __(`sd.mem.${key}`);
const INTENT_KEYS = [
  "priorities", "avoidances", "target_social", "target_recovery", "growth_focus",
];
const PHASES = ["morning", "afternoon", "evening", "night"];

/** Strip the [额外信息…] tag and the trailing bigram keyword tail. */
function memoryBody(text) {
  /* i18n-exempt-start: matches text the simulator writes, not interface copy */
  return String(text || "").replace(/^\[额外信息[^\]]*\]\s*/, "").split("关键词:")[0].trim();
  /* i18n-exempt-end */
}
function preview(text, n = 16) {
  const t = String(text || "").trim();
  return t.length > n ? t.slice(0, n) + "…" : t;
}

/** Turn the detail payload's memory bodies into graph groups + list rows. */
function memoryGroups() {
  const mem = (store.detail && store.detail.memory) || {};
  const long = [], rag = [];
  (mem.long_term || []).forEach((item) => {
    const body = memoryBody(item.text) || item.text;
    (item.rag ? rag : long).push({ title: preview(body), text: body });
  });
  const habit = (mem.habits || []).map((h) => ({
    title: preview(h.activity || h.key),
    text: `${enumLabel(PHASES, "std.phase.", h.phase)} · ${h.activity || h.key}\n`
      + `${__("sd.habit_action")}${h.preferred_action || "—"}\n`
      + `${__("sd.habit_strength")} ${clamp01(h.strength).toFixed(2)}`
      + `${h.last_updated_day == null ? "" : ` · ${__f("sd.updated_day", { day: h.last_updated_day })}`}`,
  }));
  const intent = [];
  Object.keys(mem.intentions || {}).forEach((key) => {
    const value = mem.intentions[key];
    (Array.isArray(value) ? value : [value]).filter(Boolean).forEach((v) => {
      intent.push({ title: preview(String(v)), text: `${enumLabel(INTENT_KEYS, "std.intent.", key)}: ${v}` });
    });
  });
  const sched = (mem.schedule || []).map((s) => ({
    title: `${s.time} ${preview(s.activity, 8)}`,
    text: `${s.time} · ${s.activity}`,
  }));
  const byKey = { long, rag, habit, intent, sched };
  return MEMORY_GROUPS.map((g) => Object.assign({}, g, { label: memGroupLabel(g.key), items: byKey[g.key] || [] }));
}

/** Radial graph: agent at the centre, one hub per memory kind, items as leaves. */
function memoryGraphSVG(groups, size, maxLeaves) {
  const cx = size / 2, cy = size / 2;
  const active = groups.filter((g) => g.items.length);
  const nodes = [];
  if (!active.length) {
    return { svg: `<svg viewBox="0 0 ${size} ${size}"><text x="${cx}" y="${cy}" font-size="${size / 20}" fill="#5c6860" text-anchor="middle">${esc(__("sd.mem_empty"))}</text></svg>`, nodes, hidden: 0 };
  }
  const hubR = size * 0.23, leafRa = size * 0.36, leafRb = size * 0.44;
  const leafSize = size > 400 ? 5.5 : 3.6;
  let edges = "", hubs = "", dots = "", labels = "";
  let hidden = 0;
  active.forEach((g, gi) => {
    const a0 = (-90 + (gi * 360) / active.length) * (Math.PI / 180);
    const hx = cx + Math.cos(a0) * hubR, hy = cy + Math.sin(a0) * hubR;
    edges += `<line x1="${cx}" y1="${cy}" x2="${hx.toFixed(1)}" y2="${hy.toFixed(1)}" stroke="#cbd7cd" stroke-width="1.2"/>`;
    const shown = g.items.slice(0, maxLeaves);
    hidden += g.items.length - shown.length;
    const span = ((Math.PI * 2) / active.length) * 0.8;
    shown.forEach((item, li) => {
      const t = shown.length === 1 ? 0.5 : li / (shown.length - 1);
      const a = a0 - span / 2 + span * t;
      const r = li % 2 ? leafRb : leafRa;
      const x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r;
      const idx = nodes.length;
      nodes.push({ title: item.title, text: item.text, group: g.label, color: g.color });
      edges += `<line x1="${hx.toFixed(1)}" y1="${hy.toFixed(1)}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="#e0e8e0" stroke-width="1"/>`;
      dots += `<circle class="mem-node" data-node="${idx}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${leafSize}" fill="${g.color}"><title>${esc(item.title)}</title></circle>`;
    });
    hubs += `<circle class="mem-hub" cx="${hx.toFixed(1)}" cy="${hy.toFixed(1)}" r="${leafSize * 1.7}" fill="#fff" stroke="${g.color}" stroke-width="2"/>`;
    // Label rides the clear band between the hub and its leaves, with a white
    // halo so it stays legible where it crosses a spoke.
    const lr = (hubR + leafRa) / 2;
    labels += `<text x="${(cx + Math.cos(a0) * lr).toFixed(1)}" y="${(cy + Math.sin(a0) * lr).toFixed(1)}" font-size="${size / 26}" fill="${g.color}" text-anchor="middle" stroke="#fff" stroke-width="3" paint-order="stroke">${g.label} ${g.items.length}</text>`;
  });
  const centre = `<circle cx="${cx}" cy="${cy}" r="${leafSize * 1.3}" fill="#17211d"/>`;
  return {
    svg: `<svg viewBox="0 0 ${size} ${size}" class="mem-graph">${edges}${dots}${hubs}${centre}${labels}</svg>`,
    nodes,
    hidden,
  };
}

function memoryNodeInfo(node) {
  if (!node) return `<p class="section-note">${esc(__("sd.mem_pick_node"))}</p>`;
  return `<span class="chip" style="border-color:${node.color};color:${node.color}">${esc(node.group)}</span>
    <p class="mem-node-text">${esc(node.text)}</p>`;
}

function memoryListCard(title, count, rowsHTML, emptyNote) {
  return `<div class="card"><h3>${title} <span class="tag">${count}</span></h3>
    ${count ? `<div class="mem-list">${rowsHTML}</div>` : `<p class="section-note">${emptyNote}</p>`}</div>`;
}

function stepMemory() {
  const d = store.detail || {};
  const c = d.memory_counts || { long_term: 0, habits: 0, intentions: 0, schedule: 0 };
  const mem = d.memory || {};
  const total = c.long_term + c.habits + c.intentions + c.schedule;
  const groups = memoryGroups();
  store.memGraph = memoryGraphSVG(groups, 260, 10);
  const pick = store.memPick == null ? null : store.memGraph.nodes[store.memPick];

  const longRows = (mem.long_term || []).slice().reverse().map((item) =>
    `<div class="mem-row${item.rag ? " is-rag" : ""}"><span class="mem-idx">#${item.index}</span>
      <span class="mem-text">${esc(memoryBody(item.text) || item.text)}</span></div>`).join("");
  const habitRows = (mem.habits || []).map((h) =>
    `<div class="bar-row"><div class="bl"><b>${esc(h.activity || h.key)} <span class="tag">${esc(enumLabel(PHASES, "std.phase.", h.phase))}</span></b>
      <small>${esc(h.preferred_action || "—")}${h.last_updated_day == null ? "" : ` · ${esc(__f("sd.updated_day", { day: h.last_updated_day }))}`}</small></div>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.round(clamp01(h.strength) * 100)}%"></div></div></div>`).join("");
  const intentRows = Object.keys(mem.intentions || {}).map((key) => {
    const value = mem.intentions[key];
    const list = (Array.isArray(value) ? value : [value]).filter(Boolean);
    if (!list.length) return "";
    return `<div class="mem-row"><span class="mem-idx">${esc(enumLabel(INTENT_KEYS, "std.intent.", key))}</span>
      <span class="mem-text">${list.map((v) => esc(String(v))).join(__("sd.list_sep"))}</span></div>`;
  }).join("");
  const schedRows = (mem.schedule || []).map((s) =>
    `<div class="mem-row"><span class="mem-idx">${esc(s.time)}</span><span class="mem-text">${esc(s.activity)}</span></div>`).join("");

  return `
    <h2 class="section-title">${esc(__("sd.mem_title"))}</h2>
    <p class="section-note">${esc(__("sd.mem_note"))}</p>
    <div class="cols side">
      <div class="card">
        <div class="stat-grid">
          <div class="stat"><div class="n">${c.long_term}</div><div class="l">${esc(memGroupLabel("long"))}</div></div>
          <div class="stat"><div class="n">${c.habits}</div><div class="l">${esc(memGroupLabel("habit"))}</div></div>
          <div class="stat"><div class="n">${Object.keys(mem.intentions || {}).length || c.intentions}</div><div class="l">${esc(memGroupLabel("intent"))}</div></div>
          <div class="stat"><div class="n">${c.schedule}</div><div class="l">${esc(memGroupLabel("sched"))}</div></div>
        </div>
        <p class="section-note" style="margin-top:14px">${esc(total ? __("sd.mem_has_traces") : __("sd.mem_none_yet"))}</p>
      </div>
      <div class="card"><h3>${esc(__("sd.mem_graph"))}
          <button type="button" id="memZoomBtn" class="mini-btn" title="${esc(__("sd.zoom_title"))}">⤢ ${esc(__("sd.zoom"))}</button></h3>
        <div class="viz-wrap" id="memGraphBox">${store.memGraph.svg}</div>
        ${store.memGraph.hidden ? `<p class="section-note">${esc(__f("sd.mem_hidden", { n: store.memGraph.hidden }))}</p>` : ""}
        <div class="mem-node-info" id="memNodeInfo">${memoryNodeInfo(pick)}</div>
      </div>
    </div>
    <div class="card">
      <h3>${esc(__("sd.mem_add_title"))}</h3>
      ${field(__("sd.kind"), `<select id="memKind"><option value="memory">${esc(memGroupLabel("long"))}</option><option value="rag">${esc(__("sd.rag_kind"))}</option></select>`)}
      <label class="field"><span>${esc(__("sd.content"))}</span>
        <textarea id="memText" placeholder="${esc(__("sd.mem_add_ph"))}"></textarea></label>
      <div class="confirm-bar">
        <span class="confirm-hint">${esc(__f("sd.mem_add_hint", { id: store.currentId == null ? "N" : store.currentId }))}</span>
        <button type="button" id="addMemBtn" class="button primary"${store.creating ? " disabled" : ""}>${esc(__("sd.mem_add_btn"))}</button>
      </div>
    </div>
    ${memoryListCard(esc(memGroupLabel("long")), (mem.long_term || []).length, longRows, esc(__("sd.mem_long_empty")))}
    ${memoryListCard(esc(memGroupLabel("habit")), (mem.habits || []).length, habitRows, esc(__("sd.mem_habit_empty")))}
    ${memoryListCard(esc(memGroupLabel("intent")), Object.keys(mem.intentions || {}).length, intentRows, esc(__("sd.mem_intent_empty")))}
    ${memoryListCard(esc(memGroupLabel("sched")), (mem.schedule || []).length, schedRows, esc(__("sd.mem_sched_empty")))}
    ${ragCard(d.rag)}`;
}

function openMemoryModal() {
  const built = memoryGraphSVG(memoryGroups(), 640, 30);
  store.memGraphBig = built;
  const box = document.createElement("div");
  box.className = "mem-modal";
  box.id = "memModal";
  box.innerHTML = `<div class="mem-modal-box">
      <div class="mem-modal-head"><h3>${esc(__("sd.mem_graph"))}</h3>
        <button type="button" class="mini-btn" id="memModalClose" aria-label="${esc(__("sd.close"))}">✕</button></div>
      <div class="mem-modal-body">
        <div class="mem-modal-graph">${built.svg}</div>
        <div class="mem-modal-info" id="memModalInfo">${memoryNodeInfo(null)}</div>
      </div></div>`;
  box.addEventListener("click", (ev) => {
    if (ev.target === box || ev.target.closest("#memModalClose")) { closeMemoryModal(); return; }
    const dot = ev.target.closest("[data-node]");
    if (dot) $("#memModalInfo").innerHTML = memoryNodeInfo(built.nodes[Number(dot.dataset.node)]);
  });
  document.body.appendChild(box);
  document.addEventListener("keydown", memoryModalKeys);
}

function memoryModalKeys(ev) {
  if (ev.key === "Escape") closeMemoryModal();
}

function closeMemoryModal() {
  const box = $("#memModal");
  if (box) box.remove();
  document.removeEventListener("keydown", memoryModalKeys);
}

async function addMemory() {
  if (store.creating || store.currentId == null) { foot(__("sd.save_first_memory"), "err"); return; }
  const kind = $("#memKind").value;
  const text = ($("#memText").value || "").trim();
  if (!text) { foot(__("sd.mem_text_required"), "err"); return; }
  try {
    foot(__("sd.saving_memory"));
    const res = await api(`/api/agents/${store.currentId}/memory`, {
      method: "POST", body: JSON.stringify({ kind, text }),
    });
    store.detail.memory = Object.assign({}, store.detail.memory, { long_term: res.long_term || [] });
    store.detail.rag = res.rag;
    store.detail.memory_counts = Object.assign({}, store.detail.memory_counts, { long_term: res.count });
    store.memPick = null;
    renderStep();
    foot(kind === "rag" ? __("sd.rag_written") : __("sd.mem_written"), "ok");
  } catch (err) {
    foot(__("sd.write_failed") + err.message, "err");
  }
}

function ragCard(rag) {
  const items = (rag && rag.items) || [];
  const body = items.length
    /* i18n-exempt-start: splits on a tag the simulator writes into the text */
    ? items.slice(0, 8).map((t) => `<p class="rag-item">${esc(t.split("关键词:")[0].trim())}</p>`).join("")
    /* i18n-exempt-end */
    : `<p class="section-note">${esc(__("sd.rag_empty"))}</p>`;
  return `<div class="card"><h3>${esc(__("sd.rag_kind"))} <span class="tag">${esc(__f("sd.n_entries", { n: (rag && rag.count) || 0 }))}</span></h3>${body}</div>`;
}

const TIERS = ["inner", "close", "acquaintance", "weak"];
const ROLES = [
  "mother", "father", "parent", "sibling", "grandparent", "relative",
  "spouse", "partner", "child", "best_friend", "close_friend", "friend",
  "classmate", "coworker", "boss", "subordinate", "mentor", "client",
  "neighbor", "online_friend", "acquaintance", "old_friend", "former_coworker", "ex",
];
const roleLabel = (r) =>
  ROLES.indexOf(r) >= 0 ? __(`std.role.${r}`) : (r || __("std.role_fallback"));

const TIER_RINGS = [
  { key: "inner", r: 34, cap: 5, c: "#13795b" },
  { key: "close", r: 58, cap: 15, c: "#385866" },
  { key: "acquaintance", r: 84, cap: 50, c: "#d6a81e" },
  { key: "weak", r: 110, cap: 150, c: "#cbd7cd" },
];

function cloneRelations(social) {
  return ((social && social.relations) || []).map((r) => ({
    id: r.id, name: r.name, role: r.role, kind: r.kind, tier: r.tier,
    closeness: clamp01(r.closeness), trust: clamp01(r.trust),
  }));
}

function relationRef(el) {
  const arr = store.socialDraft;
  return Array.isArray(arr) ? arr[Number(el.dataset.idx)] : null;
}

function dunbarSVG(relations) {
  const counts = { inner: 0, close: 0, acquaintance: 0, weak: 0 };
  relations.forEach((r) => { if (counts[r.tier] != null) counts[r.tier] += 1; });
  let rings = "", labels = "";
  TIER_RINGS.slice().reverse().forEach((t) => {
    rings += `<circle cx="130" cy="130" r="${t.r}" fill="none" stroke="${t.c}" stroke-width="1.4"/>`;
  });
  TIER_RINGS.forEach((t) => {
    labels += `<text x="130" y="${130 - t.r + 12}" font-size="9" fill="#5c6860" text-anchor="middle">${esc(__(`std.tier.${t.key}`))} · ${counts[t.key]}/${t.cap}</text>`;
  });
  let people = `<circle cx="130" cy="130" r="6" fill="#17211d"/>`;
  TIER_RINGS.forEach((t) => {
    const arr = relations.filter((r) => r.tier === t.key).slice(0, 24);
    arr.forEach((r, j) => {
      const a = (j / Math.max(1, arr.length)) * Math.PI * 2;
      people += `<circle cx="${(130 + Math.cos(a) * t.r).toFixed(1)}" cy="${(130 + Math.sin(a) * t.r).toFixed(1)}" r="2.8" fill="${t.c}"><title>${esc(r.name)} · ${esc(roleLabel(r.role))}</title></circle>`;
    });
  });
  return `<svg viewBox="0 0 260 260">${rings}${people}${labels}</svg>`;
}

function relationEditorRow(r, idx) {
  const attrs = `data-idx="${idx}"`;
  const roleOptions = ROLES.map((k) =>
    `<option value="${k}"${r.role === k ? " selected" : ""}>${esc(__(`std.role.${k}`))}</option>`).join("");
  const unknownRole = r.role && ROLES.indexOf(r.role) < 0
    ? `<option value="${esc(r.role)}" selected>${esc(r.role)}</option>` : "";
  const tierOptions = TIER_RINGS.map((t) =>
    `<option value="${t.key}"${r.tier === t.key ? " selected" : ""}>${esc(__(`std.tier.${t.key}`))}</option>`).join("");
  const bar = (field, label) => `<label class="goal-mini goal-prog"><span>${label} <b class="val">${r[field].toFixed(2)}</b></span>
    <input type="range" min="0" max="1" step="0.01" value="${r[field]}" data-rel-${field} ${attrs}></label>`;
  return `<div class="goal-edit">
    <div class="goal-edit-head">
      <input class="goal-title-input" data-rel-name ${attrs} value="${esc(r.name)}" placeholder="${esc(__("sd.name"))}">
      <button type="button" class="goal-remove" data-rel-remove ${attrs} title="${esc(__("sd.rel_remove_title"))}" aria-label="${esc(__("sd.remove"))}">✕</button>
    </div>
    <div class="goal-edit-controls">
      <label class="goal-mini"><span>${esc(__("sd.relation"))}</span><select data-rel-role ${attrs}>${unknownRole}${roleOptions}</select></label>
      <label class="goal-mini"><span>${esc(__("sd.tier"))}</span><select data-rel-tier ${attrs}>${tierOptions}</select></label>
      ${bar("closeness", esc(__("sd.closeness")))}
      ${bar("trust", esc(__("sd.trust")))}
    </div>
  </div>`;
}

/* ---------------------------------------------------------------------------
 * 家庭（step 5）
 *
 * Households are re-derived from (roster, config, seed) at the start of every
 * run, so an edit made here cannot be a mutation of the result — it would be
 * erased the next time the simulation started. What the panel writes is an
 * *override*: `data/family_overrides.json`, which the assigner consults while
 * assigning. That is why every save comes back with a fresh preview rather
 * than an "已保存" toast: the question worth answering is what this agent's
 * family will actually be next run, including the knock-on effects on whoever
 * they were pinned to.
 * ------------------------------------------------------------------------- */

/* Marital statuses, household types and elder roles reuse the keys the
   dashboard's family card already defines — same vocabulary, one translation. */
const MARITALS = ["never", "married", "divorced", "widowed"];
const HH_TYPES = [
  "single", "shared", "with_parents", "cohabit",
  "couple", "nuclear", "single_parent", "multigen",
];
const ELDER_ROLES = ["mother", "father", "parent", "grandparent"];

/* Gender is stored as the Chinese literal the roster CSV and the override file
   use, so the *value* stays put; only the option text comes from the locale. */
/* i18n-exempt-start: data values, not interface text */
const MALE = "男";
const FEMALE = "女";
/* i18n-exempt-end */
const GENDERS = [MALE, FEMALE];
const genderLabel = (g) => (g === MALE ? __("city.gender_male") : g === FEMALE ? __("city.gender_female") : g);

function blankFamilyDraft(override) {
  const src = override && typeof override === "object" ? override : {};
  const partner = src.partner;
  let partnerMode = "auto";
  if ("partner" in src) partnerMode = partner === null ? "none" : (partner.kind === "agent" ? "agent" : "ghost");
  return {
    marital_status: src.marital_status || "",
    partnerMode,
    partnerRole: (partner && partner.role) || "spouse",
    partnerAgentId: partner && partner.kind === "agent" ? Number(partner.agent_id) : null,
    partnerGhost: partner && partner.kind === "ghost"
      ? { name: partner.name || "", gender: partner.gender || FEMALE, age: Number(partner.age) || 30 }
      : { name: "", gender: FEMALE, age: 30 },
    children: Array.isArray(src.children) ? src.children.map(clonePerson) : null,
    elders: Array.isArray(src.elders) ? src.elders.map(clonePerson) : null,
    note: src.note || "",
  };
}

function clonePerson(p) {
  return {
    name: p.name || "", gender: p.gender || MALE,
    age: Number(p.age) || 0, coresident: p.coresident !== false,
    role: p.role || "",
  };
}

/* Draft -> the wire shape `normalize_override` validates. The tri-state on
 * children/elders is load-bearing: `null` means "sample it", `[]` means
 * "pinned to none" — an operator saying this couple has no children. */
function familyDraftToOverride(d) {
  const out = {};
  if (d.marital_status) out.marital_status = d.marital_status;
  if (d.partnerMode === "none") out.partner = null;
  else if (d.partnerMode === "agent" && d.partnerAgentId != null) {
    out.partner = { kind: "agent", agent_id: Number(d.partnerAgentId), role: d.partnerRole };
  } else if (d.partnerMode === "ghost") {
    out.partner = {
      kind: "ghost", role: d.partnerRole, name: d.partnerGhost.name,
      gender: d.partnerGhost.gender, age: Number(d.partnerGhost.age) || 0, coresident: true,
    };
  }
  if (d.children) out.children = d.children;
  if (d.elders) out.elders = d.elders;
  if (d.note) out.note = d.note;
  return out;
}

async function loadFamilyPreview() {
  if (store.creating || store.currentId == null) { store.familyPreview = null; return; }
  try {
    const payload = await api(`/api/family/preview?agent_id=${store.currentId}`);
    store.familyPreview = payload;
    store.familyDraft = blankFamilyDraft(payload.override);
  } catch (err) {
    store.familyPreview = { error: err.message };
    store.familyDraft = blankFamilyDraft(null);
  }
}

function personRow(person, idx, kind) {
  const attrs = `data-fam-kind="${kind}" data-idx="${idx}"`;
  const genderOpts = GENDERS.map((g) =>
    `<option value="${g}"${person.gender === g ? " selected" : ""}>${esc(genderLabel(g))}</option>`).join("");
  const roleSelect = kind === "elders"
    ? `<label class="goal-mini"><span>${esc(__("sd.person_role"))}</span><select data-fam-role ${attrs}>${
        ELDER_ROLES.map((r) =>
          `<option value="${r}"${person.role === r ? " selected" : ""}>${esc(__(`std.role.${r}`))}</option>`).join("")
      }</select></label>`
    : "";
  return `<div class="goal-edit">
    <div class="goal-edit-head">
      <input class="goal-title-input" data-fam-name ${attrs} value="${esc(person.name)}" placeholder="${esc(__("sd.name"))}">
      <button type="button" class="goal-remove" data-fam-remove ${attrs} title="${esc(__("sd.remove"))}" aria-label="${esc(__("sd.remove"))}">✕</button>
    </div>
    <div class="goal-edit-controls">
      <label class="goal-mini"><span>${esc(__("sd.gender"))}</span><select data-fam-gender ${attrs}>${genderOpts}</select></label>
      <label class="goal-mini"><span>${esc(__("sd.age"))}</span><input type="number" min="0" max="120" data-fam-age ${attrs} value="${Number(person.age) || 0}"></label>
      ${roleSelect}
      <label class="goal-mini goal-check"><span>${esc(__("sd.coresident"))}</span>
        <input type="checkbox" data-fam-coresident ${attrs}${person.coresident ? " checked" : ""}></label>
    </div>
  </div>`;
}

function personGroup(kind, title, hint) {
  const list = store.familyDraft[kind];
  const manual = Array.isArray(list);
  const body = manual
    ? `${list.map((p, i) => personRow(p, i, kind)).join("") || `<p class="section-note">${esc(__("sd.pinned_none"))}</p>`}
       <button type="button" class="goal-add" data-fam-add="${kind}">+ ${esc(__("sd.add"))}</button>`
    : `<p class="section-note">${esc(hint)}</p>`;
  return `<div class="fam-group">
    <label class="fam-toggle">
      <input type="checkbox" data-fam-manual="${kind}"${manual ? " checked" : ""}>
      <b>${esc(title)}</b><span class="section-note">${esc(manual ? __("sd.manual") : __("sd.automatic"))}</span>
    </label>
    ${body}
  </div>`;
}

function familyPartnerBlock(candidates) {
  const d = store.familyDraft;
  const modes = ["auto", "none", "agent", "ghost"].map((v) =>
    `<label class="fam-radio"><input type="radio" name="famPartnerMode" value="${v}"${
      d.partnerMode === v ? " checked" : ""}> ${esc(__(`sd.partner_mode.${v}`))}</label>`).join("");
  const roleSel = `<label class="goal-mini"><span>${esc(__("sd.relation"))}</span><select data-fam-partner-role>
      <option value="spouse"${d.partnerRole === "spouse" ? " selected" : ""}>${esc(__("family.role.spouse"))}</option>
      <option value="partner"${d.partnerRole === "partner" ? " selected" : ""}>${esc(__("sd.role_cohabit"))}</option>
    </select></label>`;
  let detail = "";
  if (d.partnerMode === "agent") {
    const opts = (candidates || []).map((c) =>
      `<option value="${c.agent_id}"${Number(d.partnerAgentId) === Number(c.agent_id) ? " selected" : ""}>${
        esc(c.name)} · ${esc(__f("sd.age_years", { n: c.age }))} · ${esc(genderLabel(c.gender))}${c.residence ? " · " + esc(c.residence) : ""}</option>`).join("");
    detail = `<div class="goal-edit-controls">
      <label class="goal-mini"><span>${esc(__("sd.pick_agent"))}</span><select data-fam-partner-agent>
        <option value="">— ${esc(__("sd.please_pick"))} —</option>${opts}</select></label>
      ${roleSel}
    </div>
    <p class="section-note">${esc(__("sd.partner_agent_note"))}</p>`;
  } else if (d.partnerMode === "ghost") {
    detail = `<div class="goal-edit-controls">
      <label class="goal-mini"><span>${esc(__("sd.name"))}</span><input data-fam-partner-name value="${esc(d.partnerGhost.name)}" placeholder="${esc(__("sd.ghost_name_ph"))}"></label>
      <label class="goal-mini"><span>${esc(__("sd.gender"))}</span><select data-fam-partner-gender>
        ${GENDERS.map((g) => `<option value="${g}"${d.partnerGhost.gender === g ? " selected" : ""}>${esc(genderLabel(g))}</option>`).join("")}
      </select></label>
      <label class="goal-mini"><span>${esc(__("sd.age"))}</span><input type="number" min="0" max="120" data-fam-partner-age value="${Number(d.partnerGhost.age) || 0}"></label>
      ${roleSel}
    </div>`;
  } else if (d.partnerMode === "none") {
    detail = `<p class="section-note">${esc(__("sd.partner_none_note"))}</p>`;
  } else {
    detail = `<p class="section-note">${esc(__("sd.partner_auto_note"))}</p>`;
  }
  return `<div class="fam-group"><b>${esc(__("sd.partner"))}</b>
    <div class="fam-radios">${modes}</div>${detail}</div>`;
}

function familyCard() {
  if (store.creating) {
    return `<div class="card"><h3>${esc(__("sd.family"))}</h3>
      <p class="section-note">${esc(__("sd.family_unsaved"))}</p></div>`;
  }
  const preview = store.familyPreview;
  if (!preview) {
    return `<div class="card"><h3>${esc(__("sd.family"))}</h3><p class="section-note">${esc(__("sd.loading"))}</p></div>`;
  }
  if (preview.error) {
    return `<div class="card"><h3>${esc(__("sd.family"))}</h3>
      <p class="section-note">${esc(__("sd.family_preview_failed"))}${esc(preview.error)}</p></div>`;
  }
  const sel = preview.selected || {};
  const d = store.familyDraft;
  const statusOpts = [["", __("sd.marital_auto")]].concat(
    MARITALS.map((k) => [k, __(`family.marital.${k}`)])
  ).map(([v, label]) =>
    `<option value="${v}"${d.marital_status === v ? " selected" : ""}>${esc(label)}</option>`).join("");

  const tags = `<span class="tag">${esc(MARITALS.indexOf(sel.marital_status) >= 0 ? __(`family.marital.${sel.marital_status}`) : "?")}</span>
    <span class="tag">${esc(HH_TYPES.indexOf(sel.household_type) >= 0 ? __(`family.type.${sel.household_type}`) : (sel.household_type || "?"))}</span>
    <span class="tag${sel.pinned ? " tag-pinned" : ""}">${esc(sel.pinned ? __("sd.pinned") : __("sd.automatic"))}</span>`;

  const duties = preview.duties || {};
  const dutyList = (arr, label) =>
    (arr && arr.length)
      ? `<li><b>${esc(label)}</b>${esc(__("sd.colon"))}${arr.map(esc).join(__("sd.semicolon"))}</li>`
      : `<li><b>${esc(label)}</b>${esc(__("sd.colon"))}${esc(__("sd.none"))}</li>`;

  const warnings = (preview.warnings || []).length
    ? `<p class="fam-warn">${preview.warnings.map(esc).join("<br>")}</p>` : "";

  return `<div class="card">
    <h3>${esc(__("sd.family"))} <span class="tag">${esc(sel.household_id || "")}</span></h3>
    <p class="section-note">${__f("sd.family_note", { file: "<code>data/family_overrides.json</code>" })}</p>
    ${warnings}
    <div class="fam-head">${tags}</div>
    <p class="fam-brief">${esc(sel.brief || __("sd.no_family"))}</p>
    <ul class="fam-duties">${dutyList(duties.weekday, __("sd.weekday"))}${dutyList(duties.weekend, __("sd.weekend"))}</ul>

    <div class="fam-group"><b>${esc(__("sd.marital_status"))}</b>
      <div class="goal-edit-controls">
        <label class="goal-mini"><span>${esc(__("sd.status"))}</span><select data-fam-status>${statusOpts}</select></label>
      </div>
    </div>
    ${familyPartnerBlock(preview.candidates)}
    ${personGroup("children", __("sd.children"), __("sd.children_hint"))}
    ${personGroup("elders", __("sd.elders"), __("sd.elders_hint"))}

    <div class="goals-save">
      <button type="button" id="resetFamilyBtn" class="button">${esc(__("sd.family_reset"))}</button>
      <button type="button" id="saveFamilyBtn" class="button primary">${esc(__("sd.family_save"))}</button>
    </div>
  </div>`;
}

async function saveFamilyOverride(clear) {
  if (store.creating || store.currentId == null) return;
  try {
    foot(clear ? __("sd.family_resetting") : __("sd.family_saving"));
    const body = clear
      ? { agent_id: store.currentId, clear: true }
      : { agent_id: store.currentId, override: familyDraftToOverride(store.familyDraft) };
    const payload = await api("/api/family/override", { method: "POST", body: JSON.stringify(body) });
    store.familyPreview = payload;
    store.familyDraft = blankFamilyDraft(payload.override);
    renderStep();
    foot(clear ? __("sd.family_reset_done") : __("sd.family_save_done"), "ok");
  } catch (err) {
    foot((clear ? __("sd.family_reset_failed") : __("sd.save_failed")) + err.message, "err");
  }
}

function bindFamilyCard() {
  const body = $("#stepBody");
  if (!body || !store.familyDraft) return;
  const d = store.familyDraft;

  const status = body.querySelector("[data-fam-status]");
  if (status) status.addEventListener("change", () => { d.marital_status = status.value; });

  body.querySelectorAll('input[name="famPartnerMode"]').forEach((el) => {
    el.addEventListener("change", () => { d.partnerMode = el.value; renderStep(); });
  });
  const partnerAgent = body.querySelector("[data-fam-partner-agent]");
  if (partnerAgent) partnerAgent.addEventListener("change", () => {
    d.partnerAgentId = partnerAgent.value ? Number(partnerAgent.value) : null;
  });
  const partnerRole = body.querySelector("[data-fam-partner-role]");
  if (partnerRole) partnerRole.addEventListener("change", () => { d.partnerRole = partnerRole.value; });
  const gName = body.querySelector("[data-fam-partner-name]");
  if (gName) gName.addEventListener("input", () => { d.partnerGhost.name = gName.value; });
  const gGender = body.querySelector("[data-fam-partner-gender]");
  if (gGender) gGender.addEventListener("change", () => { d.partnerGhost.gender = gGender.value; });
  const gAge = body.querySelector("[data-fam-partner-age]");
  if (gAge) gAge.addEventListener("input", () => { d.partnerGhost.age = Number(gAge.value) || 0; });

  body.querySelectorAll("[data-fam-manual]").forEach((el) => {
    el.addEventListener("change", () => {
      const kind = el.dataset.famManual;
      d[kind] = el.checked ? (d[kind] || []) : null;
      renderStep();
    });
  });
  body.querySelectorAll("[data-fam-add]").forEach((el) => {
    el.addEventListener("click", () => {
      const kind = el.dataset.famAdd;
      d[kind] = d[kind] || [];
      d[kind].push(kind === "children"
        ? { name: "", gender: MALE, age: 6, coresident: true, role: "child" }
        : { name: "", gender: FEMALE, age: 68, coresident: true, role: "mother" });
      renderStep();
    });
  });
  const personRef = (el) => {
    const list = d[el.dataset.famKind];
    return Array.isArray(list) ? list[Number(el.dataset.idx)] : null;
  };
  body.querySelectorAll("[data-fam-name]").forEach((el) => {
    el.addEventListener("input", () => { const p = personRef(el); if (p) p.name = el.value; });
  });
  body.querySelectorAll("[data-fam-gender]").forEach((el) => {
    el.addEventListener("change", () => { const p = personRef(el); if (p) p.gender = el.value; });
  });
  body.querySelectorAll("[data-fam-age]").forEach((el) => {
    el.addEventListener("input", () => { const p = personRef(el); if (p) p.age = Number(el.value) || 0; });
  });
  body.querySelectorAll("[data-fam-role]").forEach((el) => {
    el.addEventListener("change", () => { const p = personRef(el); if (p) p.role = el.value; });
  });
  body.querySelectorAll("[data-fam-coresident]").forEach((el) => {
    el.addEventListener("change", () => { const p = personRef(el); if (p) p.coresident = el.checked; });
  });
  body.querySelectorAll("[data-fam-remove]").forEach((el) => {
    el.addEventListener("click", () => {
      const list = d[el.dataset.famKind];
      if (Array.isArray(list)) list.splice(Number(el.dataset.idx), 1);
      renderStep();
    });
  });

  const save = $("#saveFamilyBtn");
  if (save) save.addEventListener("click", () => saveFamilyOverride(false));
  const reset = $("#resetFamilyBtn");
  if (reset) reset.addEventListener("click", () => saveFamilyOverride(true));
}

function stepSocial() {
  const social = store.detail && store.detail.social;
  const relations = store.socialDraft || [];
  const note = store.creating
    ? __("sd.social_new")
    : (social
      ? __f("sd.social_loaded", { n: social.count })
      : __f("sd.social_no_file", { id: store.currentId }));
  const editor = store.creating
    ? `<p class="section-note">${esc(__("sd.social_new_locked"))}</p>`
    : `${relations.map(relationEditorRow).join("")}
       <button type="button" class="goal-add" id="addRelBtn">+ ${esc(__("sd.rel_add"))}</button>
       <div class="goals-save"><button type="button" id="saveRelBtn" class="button primary">${esc(__("sd.rel_save"))}</button></div>`;
  return `
    <h2 class="section-title">${esc(__("sd.social_title"))}</h2>
    <p class="section-note">${esc(__("sd.social_note"))}${esc(note)}</p>
    <div class="cols side">
      <div class="card"><h3>${esc(__("sd.social_rings"))}</h3><div class="viz-wrap" id="dunbarViz">${dunbarSVG(relations)}</div></div>
      <div class="card"><h3>${esc(__("sd.social_influence"))}</h3>${["voice_propensity", "platform_dependence"].map((key) => {
        const v = STATE_VARS.find((x) => x.key === key), val = store.draft.state[key];
        return `<div class="bar-row"><div class="bl"><b>${esc(varLabel(v))}</b><small>${esc(poleLo(v))} → ${esc(poleHi(v))}</small></div><div class="bar-track"><div class="bar-fill" style="width:${Math.round(val * 100)}%"></div></div></div>`;
      }).join("")}<p class="section-note" style="margin-top:10px">${esc(__("sd.social_evolves"))}</p></div>
    </div>
    <div class="card"><h3>${esc(__("sd.social_edit"))} <span class="tag">${relations.length}</span></h3>${editor}</div>
    ${familyCard()}`;
}

async function saveRelations() {
  if (store.creating || store.currentId == null || !store.socialDraft) return;
  const blank = store.socialDraft.find((r) => !String(r.name || "").trim());
  if (blank) { foot(__("sd.rel_name_required"), "err"); return; }
  try {
    foot(__("sd.rel_saving"));
    const saved = await api(`/api/agents/${store.currentId}/relationships`, {
      method: "POST",
      body: JSON.stringify({ relations: store.socialDraft, removed: store.socialRemoved }),
    });
    store.detail.social = saved;
    store.socialDraft = cloneRelations(saved);
    store.socialRemoved = [];
    renderStep();
    foot(__("sd.rel_saved"), "ok");
  } catch (err) {
    foot(__("sd.rel_save_failed") + err.message, "err");
  }
}

const GOAL_STATUSES = ["active", "completed", "abandoned", "paused"];
const GOAL_DOMAINS = ["career", "family", "health", "wealth", "social", "self"];
// Active-goal caps per tier — mirror DEFAULT_GOALS_CONFIG in gaworld/goals.py
// (POST /goals normalizes with defaults, so these must match to avoid surprise truncation).
const GOAL_LIMITS = { life_goals: 2, long_term_goals: 3, short_term_goals: 4 };
const GOAL_ID_PREFIX = { life_goals: "lg", long_term_goals: "ltg", short_term_goals: "stg" };
const GOAL_TIERS = [
  { key: "life_goals", domain: true, progress: false },
  { key: "long_term_goals", domain: false, progress: true },
  { key: "short_term_goals", domain: false, progress: true },
];
const tierLabel = (t) => __(`std.tier.${t.key}`);

function cloneGoals(goals) {
  const src = goals && typeof goals === "object" ? goals : {};
  const out = JSON.parse(JSON.stringify(src));
  GOAL_TIERS.forEach(({ key }) => { if (!Array.isArray(out[key])) out[key] = []; });
  return out;
}

function goalRef(el) {
  const arr = store.goalsDraft && store.goalsDraft[el.dataset.tier];
  return Array.isArray(arr) ? arr[Number(el.dataset.idx)] : null;
}

function addGoal(tier) {
  if (!store.goalsDraft) return;
  const goal = { id: `${GOAL_ID_PREFIX[tier]}_${++store.goalSeq}`, title: "", status: "active" };
  if (tier === "life_goals") { goal.domain = "self"; goal.description = ""; }
  else { goal.parent = ""; goal.progress = 0; }
  (store.goalsDraft[tier] = store.goalsDraft[tier] || []).push(goal);
}

function goalRows(goals) {
  const tiers = ["life_goals", "long_term_goals", "short_term_goals"];
  const hasAny = goals && tiers.some((k) => (goals[k] || []).length);
  if (!hasAny) return `<p class="section-note">${esc(__("sd.goals_empty"))}</p>`;
  const life = (goals.life_goals || []).filter((g) => g.status === "active");
  const lifeHtml = life.length ? `<p class="section-note">${esc(__("std.tier.life_goals"))}</p>${chips(life.map((g) => g.title))}` : "";
  const tier = (items, label) => {
    if (!(items || []).length) return "";
    const rows = items.map((g) => {
      const pct = Math.round(clamp01(g.progress || 0) * 100);
      const status = g.status && g.status !== "active" ? ` <span class="tag">${esc(GOAL_STATUSES.indexOf(g.status) >= 0 ? __(`std.goal.${g.status}`) : g.status)}</span>` : "";
      const sub = [
        g.target_day != null ? __f("sd.goal_target_day", { day: g.target_day }) : (g.horizon_days != null ? __f("sd.goal_horizon", { n: g.horizon_days }) : ""),
        g.recent_note || "",
      ].filter(Boolean).join(" · ");
      return `<div class="bar-row"><div class="bl"><b>${esc(g.title)}${status}</b><small>${esc(sub)}</small></div>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div></div>`;
    }).join("");
    return `<p class="section-note">${esc(label)}</p>${rows}`;
  };
  const lastReview = (goals.review_log || []).slice(-1)[0] || null;
  const reviewHtml = lastReview
    ? `<p class="section-note growth-change">${esc(__f("sd.goal_review", { day: Number(lastReview.day) || 0 }))}${esc(lastReview.summary || "")}</p>`
    : "";
  return lifeHtml + tier(goals.long_term_goals, __("std.tier.long_term_goals")) + tier(goals.short_term_goals, __("std.tier.short_term_goals")) + reviewHtml;
}

function goalEditorRow(tier, idx, g, meta) {
  const attrs = `data-tier="${tier}" data-idx="${idx}"`;
  const statusSel = `<label class="goal-mini"><span>${esc(__("sd.status"))}</span>
    <select data-goal-status ${attrs}>${GOAL_STATUSES.map((k) =>
      `<option value="${k}"${(g.status || "active") === k ? " selected" : ""}>${esc(__(`std.goal.${k}`))}</option>`).join("")}</select></label>`;
  const domainSel = meta.domain
    ? `<label class="goal-mini"><span>${esc(__("sd.domain"))}</span>
        <select data-goal-domain ${attrs}>${GOAL_DOMAINS.map((k) =>
          `<option value="${k}"${(g.domain || "self") === k ? " selected" : ""}>${esc(__(`std.domain.${k}`))}</option>`).join("")}</select></label>`
    : "";
  const pct = Math.round(clamp01(g.progress || 0) * 100);
  const progress = meta.progress
    ? `<label class="goal-mini goal-prog"><span>${esc(__("sd.progress"))} <b class="val">${pct}%</b></span>
        <input type="range" min="0" max="100" step="1" value="${pct}" data-goal-progress ${attrs}></label>`
    : "";
  return `<div class="goal-edit">
    <div class="goal-edit-head">
      <input class="goal-title-input" data-goal-title ${attrs} value="${esc(g.title)}" placeholder="${esc(__("sd.goal_title_ph"))}">
      <button type="button" class="goal-remove" data-goal-remove ${attrs} title="${esc(__("sd.goal_remove_title"))}" aria-label="${esc(__("sd.remove"))}">✕</button>
    </div>
    <div class="goal-edit-controls">${domainSel}${progress}${statusSel}</div>
  </div>`;
}

function goalsEditorHtml(goals) {
  const tiers = GOAL_TIERS.map((meta) => {
    const items = goals[meta.key] || [];
    const rows = items.map((g, idx) => goalEditorRow(meta.key, idx, g, meta)).join("");
    const activeCount = items.filter((g) => (g.status || "active") === "active").length;
    const atLimit = activeCount >= GOAL_LIMITS[meta.key];
    const addBtn = `<button type="button" class="goal-add" data-goal-add data-tier="${meta.key}"${atLimit ? ` disabled title="${esc(__f("std.goal_limit", { tier: tierLabel(meta), n: GOAL_LIMITS[meta.key] }))}"` : ""}>${esc(__f("std.goal_add", { tier: tierLabel(meta) }))}</button>`;
    return `<div class="goal-tier"><p class="section-note">${esc(tierLabel(meta))}</p>${rows}${addBtn}</div>`;
  }).join("");
  const lastReview = (goals.review_log || []).slice(-1)[0] || null;
  const reviewHtml = lastReview
    ? `<p class="section-note growth-change">${esc(__f("sd.goal_review", { day: Number(lastReview.day) || 0 }))}${esc(lastReview.summary || "")}</p>`
    : "";
  return `${tiers}${reviewHtml}<div class="goals-save"><button type="button" id="saveGoalsBtn" class="button primary">${esc(__("sd.goals_save"))}</button></div>`;
}

function stepBehavior() {
  const st = store.draft.state;
  const rows = BEHAVIOR_KEYS.map((key) => {
    const v = STATE_VARS.find((x) => x.key === key);
    return `<div class="slider-row" data-var="${key}">
      <div class="slabel"><span>${esc(varLabel(v))}${machineName(v)}</span><span class="val">${st[key].toFixed(2)}</span></div>
      <input type="range" min="0" max="1" step="0.01" value="${st[key]}" data-state="${key}">
      <div class="poles"><span>${esc(poleLo(v))}</span><span>${esc(poleHi(v))}</span></div></div>`;
  }).join("");
  return `
    <h2 class="section-title">${esc(__("sd.behavior_title"))}</h2>
    <p class="section-note">${esc(__("sd.behavior_note"))}</p>
    <div class="cols side">
      <div class="card"><h3>${esc(__("sd.behavior_traits"))}</h3>${rows}</div>
      <div class="card"><h3>${esc(__("sd.goals_three_tier"))} <span class="tag">${esc(__("sd.goals_tier_tags"))}</span></h3>
        ${store.creating
          ? goalRows((store.detail || {}).goals)
          : goalsEditorHtml(store.goalsDraft || cloneGoals(null))}
        <p class="section-note">${esc(store.creating ? __("sd.goals_new_note") : __("sd.goals_edit_note"))}</p>
      </div>
    </div>`;
}

/* ---------- finance (step 7) ---------- */
const FINANCE_ACCOUNTS = ["checking", "savings", "investment", "housing_fund"].map((key) => ({ key }));
const FINANCE_AMOUNTS = ["gross_monthly_salary", "net_monthly_salary", "monthly_rent", "debt"].map((key) => ({ key }));
const FINANCE_RATES = ["engel_coefficient", "savings_rate"].map((key) => ({ key }));
const finLabel = (key) => __(`sd.fin.${key}`);
// Liquid accounts only — mirrors _total_balance in gaworld/economy/finance.py.
const FINANCE_LIQUID = ["checking", "savings", "investment"];

function cloneFinance(fin) {
  if (!fin) return null;
  const accounts = fin.accounts || {};
  const out = { accounts: {} };
  FINANCE_ACCOUNTS.forEach((a) => (out.accounts[a.key] = Number(accounts[a.key]) || 0));
  FINANCE_AMOUNTS.concat(FINANCE_RATES).forEach((f) => (out[f.key] = Number(fin[f.key]) || 0));
  return out;
}

function financeBalance(draft) {
  return FINANCE_LIQUID.reduce((sum, key) => sum + (Number(draft.accounts[key]) || 0), 0);
}

function financeCard() {
  const fin = store.detail && store.detail.finance_state;
  if (!fin) {
    return `<div class="card"><h3>${esc(__("sd.finance"))}</h3><p class="section-note">${esc(__("sd.finance_empty"))}</p></div>`;
  }
  if (!fin.editable || !store.financeDraft) {
    return `<div class="card"><h3>${esc(__("sd.finance_readonly"))}</h3><div class="review-list">
        <div><span class="k">${esc(__("sd.fin.balance"))}</span><span class="v">${fin.balance}</span></div>
        <div><span class="k">${esc(__("sd.fin.net_monthly_salary"))}</span><span class="v">${fin.net_monthly_salary}</span></div>
        <div><span class="k">${esc(__("sd.fin.engel_coefficient"))}</span><span class="v">${fin.engel_coefficient}</span></div>
        <div><span class="k">${esc(__("sd.fin.savings_rate"))}</span><span class="v">${fin.savings_rate}</span></div></div>
      <p class="section-note">${esc(__f("sd.finance_no_state", { id: store.currentId }))}</p></div>`;
  }
  const d = store.financeDraft;
  const money = (list) => list.map((f) => `<label class="field"><span>${esc(__f("sd.fin_with_currency", { label: finLabel(f.key), currency: fin.currency }))}</span>
    <input type="number" step="0.01" min="0" value="${(f.key in d ? d[f.key] : d.accounts[f.key])}" data-fin="${f.key}"></label>`).join("");
  const rates = FINANCE_RATES.map((f) => `<label class="field"><span>${esc(finLabel(f.key))} <b class="val">${d[f.key].toFixed(2)}</b></span>
    <input type="range" min="0" max="1" step="0.01" value="${d[f.key]}" data-fin-rate="${f.key}"></label>`).join("");
  return `<div class="card">
    <h3>${esc(__("sd.finance"))} <span class="tag">${esc(__("sd.editable"))}</span></h3>
    <p class="section-note">${esc(__f("sd.finance_note", { id: store.currentId }))}</p>
    <div class="grid2">${money(FINANCE_ACCOUNTS)}</div>
    <div class="grid2">${money(FINANCE_AMOUNTS)}</div>
    <div class="grid2">${rates}</div>
    <div class="confirm-bar">
      <span class="confirm-hint">${esc(__("sd.fin_total"))} <b id="finBalance">${financeBalance(d).toFixed(2)}</b> ${esc(fin.currency)}</span>
      <button type="button" id="saveFinBtn" class="button primary">${esc(__("sd.fin_save"))}</button>
    </div></div>`;
}

async function saveFinance() {
  if (store.creating || store.currentId == null || !store.financeDraft) return;
  try {
    foot(__("sd.fin_saving"));
    const saved = await api(`/api/agents/${store.currentId}/finance`, {
      method: "POST", body: JSON.stringify(store.financeDraft),
    });
    store.detail.finance_state = saved;
    store.financeDraft = cloneFinance(saved);
    renderStep();
    foot(__("sd.fin_saved"), "ok");
  } catch (err) {
    foot(__("sd.fin_save_failed") + err.message, "err");
  }
}

function stepReview() {
  const i = store.draft.identity, st = store.draft.state;
  const idRows = [["sd.name", i.name], ["sd.gender", i.gender], ["sd.age", i.age], ["sd.hukou", i.hukou], ["sd.residence", i.residence]]
    .map(([k, v]) => `<div><span class="k">${esc(__(k))}</span><span class="v">${esc(v)}</span></div>`).join("");
  const stRows = STATE_VARS.map((v) => `<div><span class="k">${esc(varLabel(v))}</span><span class="v">${st[v.key].toFixed(2)}</span></div>`).join("");
  const finCard = financeCard();
  return `
    <h2 class="section-title">${esc(__("sd.review_title"))}</h2>
    <p class="section-note">${esc(store.creating ? __("sd.review_create_note") : __("sd.review_save_note"))}</p>
    ${agentCardBlock(store.detail)}
    <div class="cols two">
      <div class="card"><h3>${esc(__("sd.identity"))}</h3><div class="review-list">${idRows}</div></div>
      <div class="card"><h3>${esc(__("sd.state_vars"))}</h3><div class="review-list">${stRows}</div></div>
    </div>
    ${finCard}
    <div class="card">
      <h3>${esc(__("sd.interview"))}</h3>
      <label class="field"><span>${esc(__("sd.interview_label"))}</span>
        <input id="interviewQ" placeholder="${esc(__("sd.interview_ph"))}"></label>
      <button id="interviewBtn" class="button" ${store.creating ? "disabled" : ""}>${esc(__("sd.interview_start"))}</button>
      <div class="interview-out" id="interviewOut" hidden></div>
    </div>
    <div class="deploy-actions">
      <button id="saveBtn2" class="button primary">${esc(store.creating ? __("sd.create_resident") : __("sd.save_changes"))}</button>
      <button id="runBtn2" class="button steel" ${store.creating ? "disabled" : ""}>${esc(__("sd.run_with_resident"))}</button>
    </div>`;
}

function agentCardBlock(detail) {
  if (!detail || !detail.agent_card) return "";
  const card = detail.agent_card;
  const oc = detail.openclaw || {};
  const cog = detail.cognition;
  const ocChip = oc.connected
    ? `<span class="chip ok">🦞 ${esc(__("sd.oc_connected"))}</span>`
    : `<span class="chip">🦞 ${esc(__("sd.oc_disconnected"))}</span>`;
  const ocLine = oc.connected
    ? `<small class="muted-line">${esc(oc.is_openclaw_agent ? __("sd.oc_external") : __("sd.oc_peer"))} · ${esc(__f("sd.oc_stats", { cluster: oc.cluster || "—", sent: oc.messages_sent, received: oc.messages_received }))}</small>`
    : `<small class="muted-line">${esc(__("sd.oc_none"))}</small>`;
  return `<div class="card"><h3>Agent Card <span class="tag">${esc(card.schema)}</span></h3>
    <div class="ac-head"><b>${esc(card.name)}</b> <span class="tag">#${esc(card.id)}</span>
      ${card.job_label ? `<span class="tag">${esc(card.job_label)}</span>` : ""}
      ${ocChip}${cog ? `<span class="chip">${esc(__("sd.cog_index"))} ${cog.score}</span>` : ""}</div>
    <small class="muted-line">${esc(card.description)}</small>
    ${card.skills.length ? `<p class="section-note">${esc(__("sd.skills"))}</p>${chips(card.skills)}` : ""}
    ${card.interests.length ? `<p class="section-note">${esc(__("sd.interests"))}</p>${chips(card.interests)}` : ""}
    ${card.deliverables.length ? `<p class="section-note">${esc(__("sd.deliverables"))}</p>${chips(card.deliverables)}` : ""}
    ${ocLine}
    <small class="muted-line">API${esc(__("sd.colon"))}${esc(card.endpoints.detail)}</small></div>`;
}

/* ---------- step event binding ---------- */
function bindStep() {
  $("#stepBody").querySelectorAll("[data-idt]").forEach((el) => {
    el.addEventListener("input", () => {
      const key = el.dataset.idt;
      store.draft.identity[key] = key === "age" ? Number(el.value) : el.value;
      renderSubject();
    });
  });
  const pEdit = $("#stepBody").querySelector("[data-profile-edit]");
  if (pEdit) pEdit.addEventListener("input", () => { store.profileEdit = pEdit.value; });
  const pBtn = $("#editProfileBtn");
  if (pBtn) pBtn.addEventListener("click", () => {
    store.profileEdit = store.draft.profile_text;
    store.profileEditing = true;
    renderStep();
  });
  const pCancel = $("#cancelProfileBtn");
  if (pCancel) pCancel.addEventListener("click", () => {
    store.profileEditing = false;
    renderStep();
  });
  const pOk = $("#confirmProfileBtn"); if (pOk) pOk.addEventListener("click", confirmProfile);
  $("#stepBody").querySelectorAll("[data-nar]").forEach((el) => {
    el.addEventListener("input", () => { store.draft.narrative[el.dataset.nar] = el.value; });
  });
  $("#stepBody").querySelectorAll("[data-b5]").forEach((el) => {
    el.addEventListener("input", () => {
      const dim = el.dataset.b5;
      const z = Math.max(-2.5, Math.min(2.5, Number(el.value) || 0));
      if (!store.big5Draft) store.big5Draft = {};
      store.big5Draft[dim] = z;
      const row = el.closest(".b5-row");
      if (row) {
        const val = row.querySelector(".val");
        val.textContent = (z >= 0 ? "+" : "") + z.toFixed(2);
        const floor = Number((store.big5 && store.big5.floor) || 0.5);
        val.classList.toggle("b5-distinct", Math.abs(z) >= floor);
      }
      markBig5Dirty();
    });
  });
  const b5Ok = $("#confirmBig5Btn");
  if (b5Ok) b5Ok.addEventListener("click", confirmBig5);
  const b5Goto = $("#gotoProfileBtn");
  if (b5Goto) b5Goto.addEventListener("click", () => {
    store.step = 1;
    store.profileEdit = store.draft.profile_text;
    store.profileEditing = true;
    renderStep();
  });
  $("#stepBody").querySelectorAll("[data-state]").forEach((el) => {
    el.addEventListener("input", () => {
      const key = el.dataset.state;
      store.draft.state[key] = clamp01(el.value);
      const row = el.closest(".slider-row");
      if (row) row.querySelector(".val").textContent = store.draft.state[key].toFixed(2);
      const big = $("#bigRadar"); if (big) big.innerHTML = radarSVG(store.draft.state, true);
      renderSubject();
      markStateDirty();
    });
  });
  const cs = $("#confirmStateBtn"); if (cs) cs.addEventListener("click", confirmState);
  $("#stepBody").querySelectorAll("[data-goal-title]").forEach((el) => {
    el.addEventListener("input", () => { const g = goalRef(el); if (g) g.title = el.value; });
  });
  $("#stepBody").querySelectorAll("[data-goal-progress]").forEach((el) => {
    el.addEventListener("input", () => {
      const g = goalRef(el); if (!g) return;
      g.progress = clamp01(Number(el.value) / 100);
      const box = el.closest(".goal-prog"), val = box && box.querySelector(".val");
      if (val) val.textContent = Math.round(g.progress * 100) + "%";
    });
  });
  $("#stepBody").querySelectorAll("[data-goal-domain]").forEach((el) => {
    el.addEventListener("change", () => { const g = goalRef(el); if (g) g.domain = el.value; });
  });
  $("#stepBody").querySelectorAll("[data-goal-status]").forEach((el) => {
    el.addEventListener("change", () => { const g = goalRef(el); if (g) { g.status = el.value; renderStep(); } });
  });
  $("#stepBody").querySelectorAll("[data-goal-remove]").forEach((el) => {
    el.addEventListener("click", () => {
      const arr = store.goalsDraft && store.goalsDraft[el.dataset.tier];
      if (Array.isArray(arr)) { arr.splice(Number(el.dataset.idx), 1); renderStep(); }
    });
  });
  $("#stepBody").querySelectorAll("[data-goal-add]").forEach((el) => {
    el.addEventListener("click", () => { addGoal(el.dataset.tier); renderStep(); });
  });
  const sg = $("#saveGoalsBtn"); if (sg) sg.addEventListener("click", saveGoals);
  bindMemoryStep();
  bindSocialStep();
  bindFinanceStep();
  const iBtn = $("#interviewBtn"); if (iBtn) iBtn.addEventListener("click", runInterview);
  const s2 = $("#saveBtn2"); if (s2) s2.addEventListener("click", save);
  const r2 = $("#runBtn2"); if (r2) r2.addEventListener("click", runSim);
}

function bindMemoryStep() {
  const zoom = $("#memZoomBtn"); if (zoom) zoom.addEventListener("click", openMemoryModal);
  const add = $("#addMemBtn"); if (add) add.addEventListener("click", addMemory);
  const box = $("#memGraphBox");
  if (box) box.addEventListener("click", (ev) => {
    const dot = ev.target.closest("[data-node]");
    if (!dot) return;
    store.memPick = Number(dot.dataset.node);
    $("#memNodeInfo").innerHTML = memoryNodeInfo(store.memGraph.nodes[store.memPick]);
  });
}

function bindSocialStep() {
  // Step 5 can be reached before the (async) preview has landed — or after a
  // failed one. Kick it off lazily, guarded so a failure cannot loop.
  if (!store.creating && store.currentId != null && !store.familyPreview && !store.familyLoading) {
    store.familyLoading = true;
    loadFamilyPreview().finally(() => {
      store.familyLoading = false;
      if (store.step === 5) renderStep();
    });
  }
  bindFamilyCard();
  const redrawRings = () => {
    const viz = $("#dunbarViz");
    if (viz) viz.innerHTML = dunbarSVG(store.socialDraft || []);
  };
  $("#stepBody").querySelectorAll("[data-rel-name]").forEach((el) => {
    el.addEventListener("input", () => { const r = relationRef(el); if (r) { r.name = el.value; redrawRings(); } });
  });
  $("#stepBody").querySelectorAll("[data-rel-role]").forEach((el) => {
    el.addEventListener("change", () => { const r = relationRef(el); if (r) { r.role = el.value; redrawRings(); } });
  });
  $("#stepBody").querySelectorAll("[data-rel-tier]").forEach((el) => {
    el.addEventListener("change", () => { const r = relationRef(el); if (r) { r.tier = el.value; redrawRings(); } });
  });
  ["closeness", "trust"].forEach((fieldName) => {
    $("#stepBody").querySelectorAll(`[data-rel-${fieldName}]`).forEach((el) => {
      el.addEventListener("input", () => {
        const r = relationRef(el); if (!r) return;
        r[fieldName] = clamp01(el.value);
        const val = el.closest(".goal-prog").querySelector(".val");
        if (val) val.textContent = r[fieldName].toFixed(2);
      });
    });
  });
  $("#stepBody").querySelectorAll("[data-rel-remove]").forEach((el) => {
    el.addEventListener("click", () => {
      const idx = Number(el.dataset.idx);
      const removed = (store.socialDraft || []).splice(idx, 1)[0];
      if (removed && removed.id) store.socialRemoved.push(removed.id);
      renderStep();
    });
  });
  const addRel = $("#addRelBtn");
  if (addRel) addRel.addEventListener("click", () => {
    (store.socialDraft = store.socialDraft || []).push({
      id: "", name: "", role: "friend", kind: "ghost", tier: "acquaintance", closeness: 0.3, trust: 0.3,
    });
    renderStep();
  });
  const saveRel = $("#saveRelBtn"); if (saveRel) saveRel.addEventListener("click", saveRelations);
}

function bindFinanceStep() {
  const refreshBalance = () => {
    const box = $("#finBalance");
    if (box) box.textContent = financeBalance(store.financeDraft).toFixed(2);
  };
  $("#stepBody").querySelectorAll("[data-fin]").forEach((el) => {
    el.addEventListener("input", () => {
      const key = el.dataset.fin;
      const value = Math.max(0, Number(el.value) || 0);
      if (key in store.financeDraft.accounts) store.financeDraft.accounts[key] = value;
      else store.financeDraft[key] = value;
      refreshBalance();
    });
  });
  $("#stepBody").querySelectorAll("[data-fin-rate]").forEach((el) => {
    el.addEventListener("input", () => {
      const key = el.dataset.finRate;
      store.financeDraft[key] = clamp01(el.value);
      const val = el.closest(".field").querySelector(".val");
      if (val) val.textContent = store.financeDraft[key].toFixed(2);
    });
  });
  const saveFin = $("#saveFinBtn"); if (saveFin) saveFin.addEventListener("click", saveFinance);
}

/* ---------- actions ---------- */
/** Persist identity + state (and profile text). Returns true when it stuck. */
async function save() {
  if (!store.draft) return false;
  const i = store.draft.identity;
  try {
    foot(__("sd.saving"));
    if (store.creating) {
      const body = { name: i.name, gender: i.gender, age: i.age, hukou: i.hukou, residence: i.residence,
        state: store.draft.state, job: store.draft.narrative.job, personality: store.draft.narrative.personality };
      const res = await api("/api/agents", { method: "POST", body: JSON.stringify(body) });
      foot(__f("sd.created", { id: res.id, name: res.name }), "ok");
      store.creating = false;
      await loadAgents();
      $("#agentSelect").value = String(res.id);
      await selectAgent(res.id);
      return true;
    }
    await api(`/api/agents/${store.currentId}/state`, { method: "POST", body: JSON.stringify({
      name: i.name, gender: i.gender, age: i.age, hukou: i.hukou, residence: i.residence, state: store.draft.state }) });
    if (store.detail && store.draft.profile_text && store.draft.profile_text !== store.detail.profile_text) {
      await api(`/api/agents/${store.currentId}/profile`, { method: "POST", body: JSON.stringify({ text: store.draft.profile_text }) });
    }
    $("#saveHint").textContent = __("sd.saved_tick");
    foot(__("sd.saved_csv_profile"), "ok");
    // refresh options label in case name changed
    await loadAgents();
    $("#agentSelect").value = String(store.currentId);
    return true;
  } catch (err) {
    foot(__("sd.save_failed") + err.message, "err");
    return false;
  }
}

async function saveGoals() {
  if (store.creating || store.currentId == null || !store.goalsDraft) return;
  try {
    foot(__("sd.goals_saving"));
    const saved = await api(`/api/agents/${store.currentId}/goals`, {
      method: "POST", body: JSON.stringify(store.goalsDraft),
    });
    store.detail = store.detail || {};
    store.detail.goals = saved || {};
    store.goalsDraft = cloneGoals(store.detail.goals);
    renderStep();
    foot(__("sd.goals_saved"), "ok");
  } catch (err) {
    foot(__("sd.goals_save_failed") + err.message, "err");
  }
}

async function runSim() {
  if (store.creating || store.currentId == null) { foot(__("sd.save_first_run"), "err"); return; }
  try {
    foot(__("sd.run_submitting"));
    await api("/api/run/start", { method: "POST", body: JSON.stringify({ config: { agent_ids: [store.currentId] } }) });
    foot(__f("sd.run_started", { id: store.currentId }), "ok");
  } catch (err) { foot(__("sd.run_failed") + err.message, "err"); }
}

async function runInterview() {
  const q = ($("#interviewQ") && $("#interviewQ").value || "").trim();
  const out = $("#interviewOut");
  if (!q) { foot(__("sd.interview_q_required"), "err"); return; }
  out.hidden = false; out.textContent = __("sd.interview_running");
  try {
    const res = await api("/api/interview", { method: "POST", body: JSON.stringify({ agent_id: store.currentId, questions: [q] }) });
    out.textContent = (res.stdout || res.stderr || __("sd.no_output")).trim();
  } catch (err) { out.textContent = __("sd.interview_failed") + err.message; }
}

/* ---------- wire up ---------- */
function init() {
  document.querySelectorAll(".step").forEach((b) => b.addEventListener("click", () => {
    store.step = Number(b.dataset.step); renderStep();
  }));
  $("#agentSelect").addEventListener("change", (e) => selectAgent(e.target.value).catch((err) => foot(err.message, "err")));
  $("#newAgentBtn").addEventListener("click", startCreate);
  $("#saveBtn").addEventListener("click", save);
  $("#runBtn").addEventListener("click", runSim);

  loadAgents()
    .then(() => store.currentId != null ? selectAgent(store.currentId) : renderStep())
    .catch((err) => foot(__("sd.load_failed") + err.message, "err"));
}

document.addEventListener("DOMContentLoaded", init);
