// 灾害模式 (Disaster Mode) — front-end controller.
//
// One run is one background job on the server (`/api/games/disaster/*`):
//
//   POST run          → {job_id}; the round is agents × stages LLM calls, far
//                       too long for a request/response, so it polls.
//   GET  jobs/<id>    → progress while running, the whole run once done.
//   GET  runs         → finished runs still in memory (sidebar history).
//
// The board is rendered from the finished run only: a stage is meaningless
// until every resident in it has answered, and a half-filled histogram would
// read as a result rather than as a work in progress. The progress bar is
// what moves during the round.

(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
  const t = (key, fallback) => (typeof __ === "function" ? __(key) : fallback);

  const CUSTOM = "__custom__";

  // `city` is null until the picker loads: "" is a real city (the default
  // world), so it cannot double as "nothing selected".
  const state = {
    city: null,
    agents: [],
    picked: new Set(),
    disasters: [],
    run: null,
    jobId: null,
    jobTimer: null,
  };

  async function init() {
    $("#dRunBtn").addEventListener("click", startRun);
    $("#dPickRandom").addEventListener("click", pickRandom);
    $("#dPickNone").addEventListener("click", () => { state.picked.clear(); renderAgents(); });
    $("#dCity").addEventListener("change", () => {
      state.city = $("#dCity").value;
      state.picked.clear();
      loadAgents();
    });
    $("#dDisaster").addEventListener("change", renderDisasterHint);
    await Promise.all([loadCities().then(loadAgents), loadCatalogue()]);
    loadHistory();
  }

  // -- pickers ------------------------------------------------------------
  async function loadCities() {
    const sel = $("#dCity");
    try {
      const resp = await fetch("/api/city/catalogue");
      const data = await resp.json();
      const cities = data.cities || [];
      sel.innerHTML = cities
        .map((c) => `<option value="${esc(c.slug)}">${esc(c.display_name || c.name || c.slug)}</option>`)
        .join("");
      const preferred = data.selected != null ? data.selected : (cities[0] && cities[0].slug);
      if (preferred != null) sel.value = preferred;
      state.city = sel.value;
    } catch (err) {
      sel.innerHTML = `<option value="">${esc(String(err))}</option>`;
      state.city = "";
    }
  }

  async function loadCatalogue() {
    const sel = $("#dDisaster");
    try {
      const resp = await fetch("/api/games/disaster/catalogue");
      const data = await resp.json();
      state.disasters = data.disasters || [];
      state.maxAgents = data.max_agents || 12;
      sel.innerHTML = state.disasters
        .map((d) => `<option value="${esc(d.id)}">${esc(d.emoji + " " + d.name)}</option>`)
        .join("") + `<option value="${CUSTOM}">✍️ ${esc(t("disaster.custom_option", "自定义灾难…"))}</option>`;
      $("#dStageCount").max = data.max_stages || 3;
      $("#dStageCount").value = data.default_stages || 2;
      renderDisasterHint();
    } catch (err) {
      sel.innerHTML = `<option value="">${esc(String(err))}</option>`;
    }
  }

  function renderDisasterHint() {
    const id = $("#dDisaster").value;
    const custom = id === CUSTOM;
    $("#dCustomBlock").hidden = !custom;
    const found = state.disasters.find((d) => d.id === id);
    $("#dDisasterHint").textContent = custom
      ? t("disaster.custom_hint", "自己写：一行一幕，最多 3 幕。")
      : (found ? found.stages.map((s, i) => `第${i + 1}幕 · ${s.slice(0, 26)}…`).join("\n") : "");
  }

  async function loadAgents() {
    const list = $("#dAgents");
    if (state.city === null) return;
    list.innerHTML = `<li class="disaster-empty">${esc(t("disaster.loading", "加载中…"))}</li>`;
    try {
      const resp = await fetch("/api/games/agents?city=" + encodeURIComponent(state.city));
      const data = await resp.json();
      state.agents = data.agents || [];
      renderAgents();
    } catch (err) {
      list.innerHTML = `<li class="disaster-empty is-error">${esc(String(err))}</li>`;
    }
  }

  function renderAgents() {
    const list = $("#dAgents");
    if (!state.agents.length) {
      list.innerHTML = `<li class="disaster-empty">${esc(t("disaster.no_agents", "这座城市暂无居民"))}</li>`;
      $("#dPicked").textContent = "0";
      return;
    }
    list.innerHTML = state.agents
      .map((a) => {
        const meta = [a.age ? a.age + "岁" : "", a.gender || "", a.job || ""].filter(Boolean).join(" · ");
        const on = state.picked.has(a.id) ? " checked" : "";
        return `<li><label>
          <input type="checkbox" value="${a.id}"${on} />
          <span class="who">#${a.id} ${esc(a.name)}</span>
          <span class="meta">${esc(meta)}</span>
        </label></li>`;
      })
      .join("");
    Array.from(list.querySelectorAll("input[type=checkbox]")).forEach((box) => {
      box.addEventListener("change", () => {
        const id = parseInt(box.value, 10);
        if (box.checked) state.picked.add(id);
        else state.picked.delete(id);
        if (state.picked.size > (state.maxAgents || 12)) {
          state.picked.delete(id);
          box.checked = false;
          setStatus(t("disaster.too_many", "最多 12 人"), true);
        }
        $("#dPicked").textContent = String(state.picked.size);
      });
    });
    $("#dPicked").textContent = String(state.picked.size);
  }

  function pickRandom() {
    const pool = state.agents.slice();
    for (let i = pool.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [pool[i], pool[j]] = [pool[j], pool[i]];
    }
    state.picked = new Set(pool.slice(0, 6).map((a) => a.id));
    renderAgents();
  }

  // -- the run ------------------------------------------------------------
  async function startRun() {
    if (!state.picked.size) return setStatus(t("disaster.need_agents", "先选几个居民"), true);
    const id = $("#dDisaster").value;
    const body = {
      city: state.city,
      agent_ids: Array.from(state.picked),
      disaster_id: id === CUSTOM ? "" : id,
      stages: Math.max(1, parseInt($("#dStageCount").value, 10) || 2),
    };
    if (id === CUSTOM) {
      body.custom = {
        name: $("#dCustomName").value.trim(),
        stages: $("#dCustomStages").value,
      };
    }

    $("#dRunBtn").disabled = true;
    setProgress(0);
    setStatus(t("disaster.running", "推演中…"));
    try {
      const resp = await fetch("/api/games/disaster/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.error || "HTTP " + resp.status);
      state.jobId = data.job_id;
      pollJob();
    } catch (err) {
      setStatus(String(err.message || err), true);
      $("#dRunBtn").disabled = false;
    }
  }

  function pollJob() {
    if (!state.jobId) return;
    clearInterval(state.jobTimer);
    state.jobTimer = setInterval(async () => {
      try {
        const resp = await fetch("/api/games/disaster/jobs/" + encodeURIComponent(state.jobId));
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const rec = await resp.json();
        setProgress(Math.round((rec.progress || 0) * 100));
        if (rec.status === "running") {
          setStatus(rec.message || t("disaster.running", "推演中…"));
          return;
        }
        stopPolling();
        if (rec.status === "done") {
          state.run = rec.result;
          render();
          setStatus(t("disaster.done", "推演完成"));
          loadHistory();
        } else {
          setStatus(rec.error || "failed", true);
        }
      } catch (err) {
        stopPolling();
        setStatus(String(err.message || err), true);
      }
    }, 900);
  }

  function stopPolling() {
    clearInterval(state.jobTimer);
    state.jobTimer = null;
    $("#dRunBtn").disabled = false;
  }

  // -- rendering ----------------------------------------------------------
  function render() {
    const run = state.run;
    $("#dIdle").hidden = !!run;
    $("#dResult").hidden = !run;
    if (!run) return;

    const d = run.disaster || {};
    $("#dTitle").textContent = `${d.emoji || ""} ${d.name || ""} · ${(run.agents || []).length} 人 · ${(run.stages || []).length} 幕`;

    $("#dSummaryBox").hidden = !run.summary;
    $("#dSummary").textContent = run.summary || "";

    const overall = (run.stats || {}).overall || {};
    $("#dOverall").innerHTML = [
      metric(t("disaster.m_panic", "平均恐慌"), overall.avg_panic, "/ 5"),
      metric(t("disaster.m_help", "互助率"), Math.round((overall.help_rate || 0) * 100) + "%", ""),
      metric(t("disaster.m_reactions", "反应数"), overall.n, ""),
      metric(t("disaster.m_top", "最多的选择"), topAction(overall.actions), ""),
    ].join("");

    const stages = (run.stats || {}).per_stage || [];
    $("#dTimeline").innerHTML = stages.map((stage, index) => stageBlock(run, stage, index)).join("");
  }

  function metric(label, value, suffix) {
    return `<div class="disaster-metric">
      <span class="label">${esc(label)}</span>
      <b>${esc(value == null ? "—" : value)}</b><span class="suffix">${esc(suffix)}</span>
    </div>`;
  }

  function topAction(actions) {
    const ranked = Object.entries(actions || {}).sort((a, b) => b[1] - a[1]);
    return ranked.length ? `${ranked[0][0]} ×${ranked[0][1]}` : "—";
  }

  function stageBlock(run, stage, index) {
    const total = stage.n || 1;
    const bars = Object.entries(stage.actions || {})
      .sort((a, b) => b[1] - a[1])
      .map(([action, n]) => `<div class="disaster-bar">
        <span class="bar-label">${esc(action)}</span>
        <span class="bar-track"><i style="width:${Math.round((n / total) * 100)}%"></i></span>
        <span class="bar-n">${n}</span>
      </div>`)
      .join("");

    const cards = (run.agents || [])
      .map((person) => {
        const r = (person.reactions || [])[index];
        if (!r) return "";
        return `<article class="disaster-card">
          <header>
            <span class="name">#${person.agent_id} ${esc(person.name)}</span>
            <span class="tag">${esc(r.action)}</span>
          </header>
          <p class="detail">${esc(r.detail)}</p>
          ${r.say ? `<p class="say">「${esc(r.say)}」</p>` : ""}
          <footer>
            <span class="panic" title="${esc(t("disaster.panic", "恐慌值"))}">${"●".repeat(r.panic)}${"○".repeat(5 - r.panic)}</span>
            ${r.help ? `<span class="help">${esc(t("disaster.helping", "🤝 顾得上别人"))}</span>` : ""}
          </footer>
        </article>`;
      })
      .join("");

    return `<section class="disaster-stage">
      <header class="stage-head">
        <h4>${esc(t("disaster.stage", "第"))}${index + 1}${esc(t("disaster.stage_suffix", "幕"))}</h4>
        <span class="stage-meta">${esc(t("disaster.m_panic", "平均恐慌"))} ${stage.avg_panic} · ${esc(t("disaster.m_help", "互助率"))} ${Math.round((stage.help_rate || 0) * 100)}%</span>
      </header>
      <p class="stage-text">${esc(stage.text || (run.stages || [])[index] || "")}</p>
      <div class="disaster-bars">${bars}</div>
      <div class="disaster-cards">${cards}</div>
    </section>`;
  }

  function setStatus(message, isError) {
    const el = $("#dStatus");
    el.className = "disaster-status" + (isError ? " is-error" : "");
    el.textContent = message;
  }

  function setProgress(pct) {
    $("#dBar").style.width = pct + "%";
    $("#dPct").textContent = pct + "%";
  }

  async function loadHistory() {
    const ul = $("#dHistory");
    try {
      const resp = await fetch("/api/games/disaster/runs");
      const data = await resp.json();
      const runs = data.runs || [];
      if (!runs.length) {
        ul.innerHTML = `<li class="disaster-empty">${esc(t("disaster.no_history", "还没有推演"))}</li>`;
        return;
      }
      ul.innerHTML = runs
        .map((r) => `<li>
          <button type="button" data-job="${esc(r.job_id)}">
            <span class="who">${esc((r.emoji || "") + " " + (r.disaster || ""))}</span>
            <span class="meta">${r.agents} ${esc(t("disaster.people", "人"))} · ${r.stages} ${esc(t("disaster.stage_suffix", "幕"))} · ${esc(t("disaster.m_panic", "平均恐慌"))} ${r.avg_panic}</span>
          </button>
        </li>`)
        .join("");
      Array.from(ul.querySelectorAll("button[data-job]")).forEach((btn) => {
        btn.addEventListener("click", () => openRun(btn.getAttribute("data-job")));
      });
    } catch (err) {
      ul.innerHTML = `<li class="disaster-empty is-error">${esc(String(err))}</li>`;
    }
  }

  async function openRun(jobId) {
    try {
      const resp = await fetch("/api/games/disaster/jobs/" + encodeURIComponent(jobId));
      const rec = await resp.json();
      if (!resp.ok) throw new Error(rec.error || "HTTP " + resp.status);
      state.run = rec.result;
      render();
      setStatus(t("disaster.viewing", "回看已完成的推演"));
    } catch (err) {
      setStatus(String(err.message || err), true);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
