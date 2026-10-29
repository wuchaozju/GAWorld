
var gwHTML = globalThis.GAWorldURL ? globalThis.GAWorldURL.html : function (value) { return value; };
// 穿越历史 (Timeslip) — front-end controller.
//
// One server call drives the game:
//
//   POST /api/games/timeslip/run -> {job_id}; poll /jobs/<id> for progress,
//        then draw the chronicle.
//
// What this page adds on top of the standard front-end:
//
// * The roster toggle is the same tri-state pattern duel uses: each resident
//   has one "选" button that doubles as un-pick, so the user never has to
//   look at two controls for one decision.
// * Custom dynasty is a small inline form — the catalogue already covers
//   most cases, but the user might want to try a specific year or a non-Chinese
//   era, and the back end takes the block straight.

(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
  // Falls back to the second arg when the locale is missing the key, so the
  // page reads as intended Chinese even before every i18n string has shipped.
  const t = (key, fallback) => {
    const value = typeof __ === "function" ? __(key) : "";
    return !value || value === key ? (fallback || "") : value;
  };
  const tf = (key, params, fallback) => (typeof __f === "function" ? __f(key, params) : (fallback || ""));

  const CUSTOM = "__custom__";

  const state = {
    city: null,
    agents: [],
    picked: new Set(),
    dynasties: [],
    dynasty: null,
    maxAgents: 8,
    minAgents: 2,
    minStages: 2,
    maxStages: 6,
    defaultStages: 4,
    run: null,
    jobId: null,
    // Release function returned by setButtonBusy() while the run
    // button is busy. pollJob/stopPolling read this to re-enable
    // the button when the job ends; null when at rest.
    runRelease: null,
    jobTimer: null,
  };

  const exporter = GAWorldGameExport.attach(() => state.run && {
    game: "timeslip",
    label: (state.run.dynasty || {}).dynasty || "穿越历史",
    markdown: GAWorldGameExport.timeslip(state.run),
  });

  async function init() {
    $("#tRunBtn").addEventListener("click", startRun);
    $("#tPickRandom").addEventListener("click", pickRandom);
    $("#tPickNone").addEventListener("click", () => { state.picked.clear(); afterPick(); });
    $("#tCity").addEventListener("change", () => {
      state.city = $("#tCity").value;
      state.picked.clear();
      loadAgents();
    });
    $("#tDynasty").addEventListener("change", renderDynasty);
    $("#tStages").addEventListener("input", renderCost);
    $("#tCustomName").addEventListener("input", afterPick);
    $("#tCustomFrame").addEventListener("input", afterPick);
    $("#tCustomStages").addEventListener("input", afterPick);
    await Promise.all([loadCities().then(loadAgents), loadCatalogue()]);
    loadHistory();
  }

  // ----------------------------------------------------------------------
  // Catalogue
  // ----------------------------------------------------------------------
  async function loadCatalogue() {
    try {
      const resp = await fetch("/api/games/timeslip/catalogue");
      const data = await resp.json();
      state.dynasties = data.dynasties || [];
      state.maxAgents = data.max_agents || 8;
      state.minAgents = data.min_agents || 2;
      state.minStages = data.min_stages || 2;
      state.maxStages = data.max_stages || 6;
      state.defaultStages = data.default_stages || 4;

      const sel = $("#tDynasty");
      sel.innerHTML = gwHTML(state.dynasties
        .map((d) => `<option value="${esc(d.id)}">${esc((d.emoji || "") + " " + d.dynasty)}</option>`)
        .concat([`<option value="${CUSTOM}">${esc(t("timeslip.custom_option", "自己写一个朝代…"))}</option>`])
        .join(""));
      sel.value = state.dynasties[0] ? state.dynasties[0].id : CUSTOM;
      state.dynasty = state.dynasties[0] || null;
      $("#tStages").value = state.defaultStages;
      $("#tStages").min = state.minStages;
      $("#tStages").max = state.maxStages;
      renderDynasty();
    } catch (e) {
      $("#tDynasty").innerHTML = gwHTML(`<option>${esc(t("timeslip.catalogue_failed", "加载朝代失败"))}</option>`);
    }
  }

  function renderDynasty() {
    const sel = $("#tDynasty");
    const isCustom = sel.value === CUSTOM;
    $("#tCustomBlock").hidden = !isCustom;
    state.dynasty = isCustom ? null : state.dynasties.find((d) => d.id === sel.value) || null;
    const hint = $("#tDynastyText");
    if (isCustom) {
      hint.textContent = t("timeslip.custom_hint", "自己写一个朝代：交代时代、写出几幕场景。后端会用最近的几幕。");
    } else if (state.dynasty) {
      const stages = Array.isArray(state.dynasty.stages) ? state.dynasty.stages : [];
      hint.innerHTML = gwHTML(`${esc(state.dynasty.frame)}<br/><span class="muted">${esc(tf("timeslip.stages_hint", {n: stages.length}, `内置 ${stages.length} 幕`))}</span>`);
    } else {
      hint.textContent = "";
    }
    afterPick();
  }

  // ----------------------------------------------------------------------
  // Cities / agents
  // ----------------------------------------------------------------------
  async function loadCities() {
    const sel = $("#tCity");
    try {
      const resp = await fetch("/api/city/catalogue");
      const data = await resp.json();
      const cities = data.cities || [];
      sel.innerHTML = gwHTML(cities
        .map((c) => `<option value="${esc(c.slug)}">${esc(c.display_name || c.name || c.slug)}</option>`)
        .join(""));
      const preferred = data.selected != null ? data.selected : (cities[0] && cities[0].slug);
      if (preferred != null) sel.value = preferred;
      state.city = sel.value;
    } catch (e) {
      sel.innerHTML = gwHTML(`<option value="">默认世界</option>`);
      state.city = "";
    }
  }

  async function loadAgents() {
    const list = $("#tAgents");
    list.innerHTML = gwHTML(`<li class="disaster-empty">${esc(t("timeslip.loading", "加载中…"))}</li>`);
    try {
      const resp = await fetch(`/api/games/timeslip/agents?city=${encodeURIComponent(state.city || "")}`);
      const data = await resp.json();
      state.agents = data.agents || [];
    } catch (e) {
      state.agents = [];
    }
    renderAgents();
  }

  function renderAgents() {
    const list = $("#tAgents");
    if (!state.agents.length) {
      list.innerHTML = gwHTML(`<li class="disaster-empty">${esc(t("timeslip.agents_empty", "这座城里没有可挑选的居民"))}</li>`);
      return;
    }
    const byId = new Map(state.agents.map((a) => [a.id, a]));
    list.innerHTML = gwHTML(state.agents
      .map((person) => {
        const selected = state.picked.has(person.id);
        return `
          <li class="disaster-row${selected ? " is-picked" : ""}" data-id="${esc(person.id)}">
            <span class="disaster-name">
              <b>#${esc(person.id)} ${esc(person.name)}</b>
              <span class="muted">${esc(person.age || "")} ${esc(person.gender || "")} · ${esc(person.job || "—")}</span>
            </span>
            <button class="button small t-pick" data-id="${esc(person.id)}" type="button">
              ${selected ? esc(t("timeslip.unpick", "取消")) : esc(t("timeslip.pick", "选"))}
            </button>
          </li>`;
      })
      .join(""));
    list.querySelectorAll(".t-pick").forEach((btn) => {
      btn.addEventListener("click", () => togglePick(parseInt(btn.dataset.id, 10)));
    });
    afterPick();
  }

  function togglePick(agentId) {
    if (state.picked.has(agentId)) state.picked.delete(agentId);
    else if (state.picked.size < state.maxAgents) state.picked.add(agentId);
    renderAgents();
  }

  function pickRandom() {
    const pool = state.agents.filter((a) => !state.picked.has(a.id));
    const want = Math.max(state.minAgents, Math.min(6, state.maxAgents));
    const shuffled = pool.slice().sort(() => Math.random() - 0.5);
    state.picked.clear();
    for (const person of shuffled.slice(0, want)) state.picked.add(person.id);
    renderAgents();
  }

  function afterPick() {
    $("#tCount").textContent = String(state.picked.size);
    renderCost();
    const btn = $("#tRunBtn");
    btn.disabled = state.picked.size < state.minAgents;
  }

  function renderCost() {
    const stages = Math.max(state.minStages, Math.min(state.maxStages, parseInt($("#tStages").value || "4", 10)));
    const ppl = state.picked.size;
    const calls = (stages + 1) * Math.max(1, ppl) + 1;
    const dynLabel = state.dynasty ? state.dynasty.dynasty : t("timeslip.custom_running", "（自定义朝代）");
    $("#tCost").textContent = `${esc(dynLabel)} · ${ppl} 位 · ${stages} 幕 · 约 ${calls} 次模型调用`;
  }

  // ----------------------------------------------------------------------
  // Run / poll
  // ----------------------------------------------------------------------
  async function startRun() {
    if (state.jobTimer) { clearInterval(state.jobTimer); state.jobTimer = null; }
    const btn = $("#tRunBtn");
    btn.disabled = true;
    state.runRelease = setButtonBusy(btn, "timeslip.running", "穿越中…");
    state.run = null;
    state.jobId = null;
    $("#tResult").hidden = true;
    $("#tIdle").hidden = false;
    $("#tStatus").textContent = t("timeslip.starting", "启动穿越…");
    $("#tBar").style.width = "0%";
    $("#tPct").textContent = "0%";
    // Reset the right-side title so a previous run's dynasty name doesn't
    // stick on the board while we're starting a new one.
    $("#tTitle").textContent = t("timeslip.section_board", "穿越实况");

    const stages = Math.max(state.minStages, Math.min(state.maxStages, parseInt($("#tStages").value || "4", 10)));
    const payload = {
      city: state.city || "",
      agent_ids: Array.from(state.picked),
      stages,
    };
    const isCustom = $("#tDynasty").value === CUSTOM;
    if (isCustom) {
      payload.dynasty_id = "";
      payload.custom = {
        name: $("#tCustomName").value.trim(),
        frame: $("#tCustomFrame").value.trim(),
        stages: $("#tCustomStages").value.split("\n").map((s) => s.trim()).filter(Boolean),
      };
      if (!payload.custom.name || !payload.custom.frame) {
        $("#tStatus").textContent = t("timeslip.custom_required", "自定义朝代要写名字和时代背景。");
        if (state.runRelease) { state.runRelease(); state.runRelease = null; }
        return;
      }
      if (payload.custom.stages.length < state.minStages) {
        $("#tStatus").textContent = t("timeslip.custom_stages_required", "至少要写两幕场景。");
        if (state.runRelease) { state.runRelease(); state.runRelease = null; }
        return;
      }
    } else {
      payload.dynasty_id = state.dynasty ? state.dynasty.id : "";
    }

    try {
      const resp = await fetch("/api/games/timeslip/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
      state.jobId = data.job_id;
      pollJob();
    } catch (e) {
      $("#tStatus").textContent = (e && e.message) || String(e);
      if (state.runRelease) { state.runRelease(); state.runRelease = null; }
    }
  }

  function pollJob() {
    const btn = $("#tRunBtn");
    state.jobTimer = setInterval(async () => {
      try {
        const resp = await fetch(`/api/games/timeslip/jobs/${encodeURIComponent(state.jobId)}`);
        const data = await resp.json();
        const pct = Math.round((data.progress || 0) * 100);
        $("#tBar").style.width = `${pct}%`;
        $("#tPct").textContent = `${pct}%`;
        if (data.status === "running") {
          $("#tStatus").textContent = data.message || "";
        } else if (data.status === "done") {
          clearInterval(state.jobTimer);
          state.jobTimer = null;
          state.run = data.result || {};
          $("#tBar").style.width = "100%";
          $("#tPct").textContent = "100%";
          $("#tStatus").textContent = t("timeslip.completed", "已完成");
          renderResult();
          if (state.runRelease) { state.runRelease(); state.runRelease = null; }
          loadHistory();
        } else if (data.status === "failed") {
          clearInterval(state.jobTimer);
          state.jobTimer = null;
          $("#tStatus").textContent = `${t("timeslip.failed", "穿越失败：")}${data.error || ""}`;
          if (state.runRelease) { state.runRelease(); state.runRelease = null; }
        } else {
          $("#tStatus").textContent = data.message || data.status || "";
        }
      } catch (e) {
        // transient — keep polling
      }
    }, 1500);
  }

  function renderResult() {
    const run = state.run;
    if (!run || !run.dynasty) return;
    const dyn = run.dynasty;
    $("#tTitle").textContent = dyn.dynasty || (dyn.id || "穿越历史");
    $("#tIdle").hidden = true;
    $("#tResult").hidden = false;
    renderScoreboard(run);
    renderStages(run);
    renderRoster(run);
    renderEssay(run);
  }

  function renderScoreboard(run) {
    const stats = run.stats || {};
    const box = $("#tScoreboard");
    const dyn = run.dynasty || {};
    const most = stats.most_in_period || {};
    const least = stats.least_in_period || {};
    const torn = stats.most_torn || {};
    box.innerHTML = gwHTML(`
      <header class="timeslip-head">
        <span class="timeslip-emoji">${esc(dyn.emoji || "🏺")}</span>
        <div>
          <h3>${esc(dyn.dynasty || "穿越历史")}</h3>
          <p class="muted">${esc(dyn.frame || "")}</p>
        </div>
      </header>
      <div class="timeslip-cards">
        <div class="timeslip-card">
          <div class="timeslip-card-tag">${esc(t("timeslip.tag_most_fit", "最像古人"))}</div>
          <div class="timeslip-card-name">#${esc(most.agent_id || "?")} ${esc(most.name || "—")}</div>
          <p class="muted">${esc(t("timeslip.tag_most_fit_hint", "古人口吻挂得上礼数的人"))}</p>
        </div>
        <div class="timeslip-card">
          <div class="timeslip-card-tag">${esc(t("timeslip.tag_least_fit", "最格格不入"))}</div>
          <div class="timeslip-card-name">#${esc(least.agent_id || "?")} ${esc(least.name || "—")}</div>
          <p class="muted">${esc(t("timeslip.tag_least_fit_hint", "稳定度也低的那一位"))}</p>
        </div>
        <div class="timeslip-card">
          <div class="timeslip-card-tag">${esc(t("timeslip.tag_torn", "撕裂最重"))}</div>
          <div class="timeslip-card-name">#${esc(torn.agent_id || "?")} ${esc(torn.name || "—")}</div>
          <p class="muted">${esc(t("timeslip.tag_torn_hint", "嘴上说的和心里想的差最远"))}</p>
        </div>
      </div>
      <p class="timeslip-moods muted">${esc(stats.moods || "")}</p>
    `);
  }

  function renderStages(run) {
    const stages = run.stages || [];
    const dynasty = run.dynasty || {};
    const container = $("#tStagesBlock");
    const nameLookup = new Map();
    for (const person of run.cards || []) nameLookup.set(person.agent_id, person);
    for (const person of (run.stats && run.stats.residents) || []) nameLookup.set(person.agent_id, person);

    container.innerHTML = gwHTML(`
      <h3>${esc(t("timeslip.stages_title", "一幕一幕"))}</h3>
      ${stages.map((stage) => {
        const lines = (stage.reactions || []).map((r) => {
          const persona = nameLookup.get(r.agent_id) || {};
          return `
            <article class="timeslip-reaction">
              <header>
                <b>#${esc(r.agent_id)} ${esc(r.name || persona.name || "")}</b>
                <span class="muted">${esc(persona.job || "")}</span>
              </header>
              <p class="timeslip-line">「${esc(r.line || "")}」</p>
              <p class="timeslip-inner muted">内心独白:${esc(r.inner || "")}</p>
              <ul class="timeslip-scores">
                <li><span>${esc(t("timeslip.score_era", "时代契合度"))}</span><b>${esc(r.scores ? r.scores.era_fit : "?")}</b></li>
                <li><span>${esc(t("timeslip.score_stab", "稳定度"))}</span><b>${esc(r.scores ? r.scores.stability : "?")}</b></li>
                <li><span>${esc(t("timeslip.score_conflict", "内在冲突"))}</span><b>${esc(r.scores ? r.scores.inner_conflict : "?")}</b></li>
              </ul>
            </article>`;
        }).join("");
        return `
          <section class="timeslip-stage">
            <header>
              <h4>${esc(tf("timeslip.stage_heading", {n: stage.index + 1}, `第 ${stage.index + 1} 幕`))}</h4>
              <p class="muted">${esc(stage.stage_mood || "")}</p>
            </header>
            <p class="timeslip-stage-text">${esc(stage.text || "")}</p>
            <div class="timeslip-grid">${lines}</div>
          </section>`;
      }).join("")}
    `);
  }

  function renderRoster(run) {
    const residents = (run.stats && run.stats.residents) || [];
    const container = $("#tRoster");
    if (!residents.length) {
      container.innerHTML = gwHTML("");
      return;
    }
    container.innerHTML = gwHTML(`
      <h3>${esc(t("timeslip.roster_card_title", "穿越者速写"))}</h3>
      <table class="timeslip-table">
        <thead>
          <tr>
            <th>#</th>
            <th>${esc(t("timeslip.col_name", "居民"))}</th>
            <th>${esc(t("timeslip.col_era_fit", "时代契合"))}</th>
            <th>${esc(t("timeslip.col_stability", "稳定度"))}</th>
            <th>${esc(t("timeslip.col_conflict", "内在冲突"))}</th>
            <th>${esc(t("timeslip.col_best_line", "名句"))}</th>
          </tr>
        </thead>
        <tbody>
          ${residents.map((p) => `
            <tr>
              <td>#${esc(p.agent_id)}</td>
              <td><b>${esc(p.name || "")}</b><br/><span class="muted">${esc(p.job || "")}</span></td>
              <td>${esc(p.scores ? p.scores.era_fit : "?")}</td>
              <td>${esc(p.scores ? p.scores.stability : "?")}</td>
              <td>${esc(p.scores ? p.scores.inner_conflict : "?")}</td>
              <td>${esc(p.best_line || "—")}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
      <p class="muted timeslip-note">${esc(run.scoring_note || "")}</p>
    `);
  }

  function renderEssay(run) {
    const container = $("#tEssay");
    const text = (run.essay || "").trim();
    if (!text) {
      container.innerHTML = gwHTML("");
      return;
    }
    container.innerHTML = gwHTML(`
      <h3>${esc(t("timeslip.essay_title", "穿越纪实"))}</h3>
      <p>${esc(text).replace(/\n+/g, "<br/>")}</p>
    `);
  }

  // ----------------------------------------------------------------------
  // History
  // ----------------------------------------------------------------------
  async function loadHistory() {
    const list = $("#tHistory");
    list.innerHTML = gwHTML(`<li class="disaster-empty">${esc(t("timeslip.loading_short", "加载…"))}</li>`);
    try {
      const resp = await fetch("/api/games/timeslip/runs");
      const data = await resp.json();
      const rows = data.runs || [];
      if (!rows.length) {
        list.innerHTML = gwHTML(`<li class="disaster-empty">${esc(t("timeslip.no_history", "还没有穿越记录"))}</li>`);
        return;
      }
      list.innerHTML = gwHTML(rows.slice(0, 8).map((row) => {
        const dyn = row.dynasty || row.dynasty_id || "穿越历史";
        const emo = row.emoji || "";
        return `
          <li>
            <button class="button small" data-id="${esc(row.job_id)}" type="button">
              ${esc(emo + " " + dyn)} · ${esc(row.agents || "?")}人 · ${esc(row.stages || "?")}幕
            </button>
          </li>`;
      }).join(""));
      list.querySelectorAll("button[data-id]").forEach((btn) => {
        btn.addEventListener("click", () => loadOneRun(btn.dataset.id));
      });
    } catch (e) {
      list.innerHTML = gwHTML(`<li class="disaster-empty">${esc(t("timeslip.history_failed", "加载历史失败"))}</li>`);
    }
  }

  async function loadOneRun(jobId) {
    try {
      const resp = await fetch(`/api/games/timeslip/jobs/${encodeURIComponent(jobId)}`);
      const data = await resp.json();
      if (!resp.ok || !data.result) return;
      state.run = data.result;
      renderResult();
    } catch (e) {
      // ignore
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
