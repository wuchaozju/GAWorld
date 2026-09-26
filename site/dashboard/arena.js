// GAWorld Agent Arena — front-end controller.
//
// Six panels:
//
//   1. city picker (top-left)
//   2. contestant list (left, multi-select)
//   3. task list (left, multi-select; "random" button → /api/arena/generate)
//   4. live progress bar (right header)
//   6. apply-top-k + survivor tags (right middle)
//   7. refill toolbar (right bottom; from another city or via bulk import)
//
// State is intentionally local — the arena does not write to the simulator
// state CSV. ``/api/arena/retain`` only flips in-process flags keyed by
// ``(city_slug, agent_id)``; restarting the dashboard clears them, which
// matches user expectation for an evaluation sandbox.

(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
  const t = (key, fallback) => (typeof __ === "function" ? __(key) : fallback);

  // -- module state ----------------------------------------------------------
  const state = {
    city: "",
    agents: [],
    eliminated: new Set(),
    tasks: [],
    customTasks: [],
    selectedAgents: new Set(),
    selectedTasks: new Set(),
    jobId: null,
    jobTimer: null,
    leaderboard: [],
  };

  async function init() {
    bindCityPicker();
    bindContestantToolbar();
    bindTaskToolbar();
    bindRunButton();
    bindRetain();
    bindRefill();
    $("#arenaRefreshBtn").addEventListener("click", refreshAll);
    await refreshAll();
  }

  // -- city picker --------------------------------------------------------
  function bindCityPicker() {
    const sel = $("#arenaCitySelect");
    sel.addEventListener("change", () => {
      state.city = sel.value;
      loadAgents();
      loadTasks();
      loadEliminated();
    });
  }

  async function refreshAll() {
    await loadCityPicker();
    if (state.city) {
      await Promise.all([loadAgents(), loadTasks(), loadEliminated()]);
    }
  }

  async function loadCityPicker() {
    const sel = $("#arenaCitySelect");
    try {
      const resp = await fetch("/api/city/catalogue");
      const data = await resp.json();
      const cities = data.cities || [];
      sel.innerHTML = cities
        .map((c) => `<option value="${esc(c.slug)}">${esc(c.display_name || c.name || c.slug)}</option>`)
        .join("");
      // Default to dashboard-config selected, fall back to first city.
      const preferred = data.selected || (cities[0] && cities[0].slug);
      if (preferred) {
        sel.value = preferred;
        state.city = preferred;
      }
    } catch (err) {
      sel.innerHTML = `<option value="">${esc(String(err))}</option>`;
    }
  }

  async function loadAgents() {
    if (!state.city) return;
    try {
      const resp = await fetch("/api/arena/agents?city=" + encodeURIComponent(state.city));
      const data = await resp.json();
      state.agents = data.agents || [];
      state.selectedAgents = new Set(state.selectedAgents); // keep selections
      renderContestants();
    } catch (err) {
      $("#arenaContestants").innerHTML = `<li class="arena-list-empty">${esc(String(err))}</li>`;
    }
  }

  async function loadEliminated() {
    if (!state.city) return;
    try {
      const resp = await fetch("/api/arena/state", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ city: state.city }),
      });
      const data = await resp.json();
      state.eliminated = new Set(data.eliminated || []);
      renderContestants();
      renderEliminatedTags();
    } catch (err) {
      // ignore — best-effort.
    }
  }

  // -- contestant list --------------------------------------------------
  function bindContestantToolbar() {
    $("#arenaPickAll").addEventListener("click", () => {
      state.agents.forEach((a) => {
        if (!state.eliminated.has(a.id)) state.selectedAgents.add(a.id);
      });
      renderContestants();
    });
    $("#arenaPickNone").addEventListener("click", () => {
      state.selectedAgents.clear();
      renderContestants();
    });
  }

  function renderContestants() {
    const ul = $("#arenaContestants");
    if (!state.agents.length) {
      ul.innerHTML = `<li class="arena-list-empty">${esc(t("arena.no_agents", "这座城市暂无居民"))}</li>`;
      return;
    }
    ul.innerHTML = state.agents.map((a) => {
      const checked = state.selectedAgents.has(a.id);
      const eliminated = state.eliminated.has(a.id);
      const cls = eliminated ? "is-eliminated" : "";
      return `<li class="${cls}">
        <label>
          <input type="checkbox" data-agent="${a.id}" ${checked ? "checked" : ""} ${eliminated ? "disabled" : ""} />
          <span class="name">#${a.id} ${esc(a.name || "")}</span>
          <span class="meta">${esc(a.industry || "")} ${a.age ? "· " + a.age + "岁" : ""}</span>
          ${eliminated ? `<span class="arena-tag">${esc(t("arena.eliminated_tag", "已淘汰"))}</span>` : ""}
        </label>
      </li>`;
    }).join("");
    $$("input[data-agent]", ul).forEach((cb) => {
      cb.addEventListener("change", () => {
        const id = parseInt(cb.getAttribute("data-agent"), 10);
        if (cb.checked) state.selectedAgents.add(id);
        else state.selectedAgents.delete(id);
      });
    });
  }

  // -- task list --------------------------------------------------------
  function bindTaskToolbar() {
    $("#arenaPickTasksAll").addEventListener("click", () => {
      state.tasks.forEach((task) => state.selectedTasks.add(task.id));
      state.customTasks.forEach((task) => state.selectedTasks.add(task.id));
      renderTasks();
    });
    $("#arenaPickTasksNone").addEventListener("click", () => {
      state.selectedTasks.clear();
      renderTasks();
    });
    $("#arenaGenerateBtn").addEventListener("click", generateTasks);
  }

  async function loadTasks() {
    if (!state.city) return;
    try {
      const resp = await fetch("/api/arena/tasks");
      const data = await resp.json();
      state.tasks = data.tasks || [];
      renderTasks();
    } catch (err) {
      $("#arenaTasks").innerHTML = `<li class="arena-list-empty">${esc(String(err))}</li>`;
    }
  }

  function renderTasks() {
    const ul = $("#arenaTasks");
    ul.innerHTML = state.tasks.map((task) => {
      const checked = state.selectedTasks.has(task.id);
      return `<li>
        <label>
          <input type="checkbox" data-task="${esc(task.id)}" ${checked ? "checked" : ""} />
          <span class="name">${esc(task.title)}</span>
          <span class="meta">${esc(task.category)}</span>
        </label>
      </li>`;
    }).join("");
    $$("input[data-task]", ul).forEach((cb) => {
      cb.addEventListener("change", () => {
        const id = cb.getAttribute("data-task");
        if (cb.checked) state.selectedTasks.add(id);
        else state.selectedTasks.delete(id);
      });
    });

    const custom = $("#arenaCustomTasks");
    if (!state.customTasks.length) {
      custom.innerHTML = "";
      return;
    }
    custom.innerHTML = `
      <h5>${esc(t("arena.custom_tasks", "LLM 生成的题"))}</h5>
      <ul class="arena-task-list">
        ${state.customTasks.map((task) => `
          <li>
            <label>
              <input type="checkbox" data-task="${esc(task.id)}" ${state.selectedTasks.has(task.id) ? "checked" : ""} />
              <span class="name">${esc(task.title || task.category)}</span>
              <span class="meta">${esc(task.category)}</span>
            </label>
          </li>
        `).join("")}
      </ul>
    `;
    $$("input[data-task]", custom).forEach((cb) => {
      cb.addEventListener("change", () => {
        const id = cb.getAttribute("data-task");
        if (cb.checked) state.selectedTasks.add(id);
        else state.selectedTasks.delete(id);
      });
    });
  }

  async function generateTasks() {
    const btn = $("#arenaGenerateBtn");
    btn.disabled = true;
    btn.textContent = t("arena.generating", "🎲 生成中…");
    try {
      const resp = await fetch("/api/arena/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ n: 5, categories: ["math", "qa", "logic"], difficulty: "medium" }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.error || ("HTTP " + resp.status));
      }
      const data = await resp.json();
      state.customTasks = state.customTasks.concat(data.tasks || []);
      state.customTasks.forEach((task) => state.selectedTasks.add(task.id));
      renderTasks();
    } catch (err) {
      alert(t("arena.generate_failed", "出题失败") + ": " + (err.message || err));
    } finally {
      btn.disabled = false;
      btn.textContent = t("arena.generate", "🎲 随机出题");
    }
  }

  // -- run --------------------------------------------------------------
  function bindRunButton() {
    $("#arenaRunBtn").addEventListener("click", runRound);
  }

  async function runRound() {
    if (!state.city) {
      alert(t("arena.need_city", "请先选择城市"));
      return;
    }
    const agentIds = Array.from(state.selectedAgents);
    if (!agentIds.length) {
      alert(t("arena.need_agents", "至少勾一个选手"));
      return;
    }
    const taskIds = Array.from(state.selectedTasks);
    if (!taskIds.length) {
      alert(t("arena.need_tasks", "至少勾一道题"));
      return;
    }
    // Split into built-in vs custom so the backend picks the right source.
    const builtinIds = new Set(state.tasks.map((t) => t.id));
    const chosenBuiltin = taskIds.filter((id) => builtinIds.has(id));
    const customTasks = state.customTasks.filter((t) => state.selectedTasks.has(t.id));

    const status = $("#arenaStatus");
    status.className = "hint";
    status.textContent = t("arena.starting", "启动中…");
    $("#arenaRunBtn").disabled = true;
    setProgress(0);

    try {
      const resp = await fetch("/api/arena/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          city: state.city,
          agent_ids: agentIds,
          task_ids: chosenBuiltin,
          custom_tasks: customTasks,
        }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.error || ("HTTP " + resp.status));
      }
      const data = await resp.json();
      state.jobId = data.job_id;
      pollJob();
    } catch (err) {
      status.className = "imp-status is-error";
      status.textContent = String(err.message || err);
      $("#arenaRunBtn").disabled = false;
    }
  }

  function pollJob() {
    if (!state.jobId) return;
    clearInterval(state.jobTimer);
    state.jobTimer = setInterval(async () => {
      try {
        const resp = await fetch("/api/arena/jobs/" + encodeURIComponent(state.jobId));
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const rec = await resp.json();
        const pct = Math.round((rec.progress || 0) * 100);
        setProgress(pct);
        const status = $("#arenaStatus");
        if (status) status.textContent = rec.message || (rec.status === "running" ? "…" : "");
        if (rec.status === "done") {
          clearInterval(state.jobTimer);
          state.jobTimer = null;
          state.leaderboard = (rec.result && rec.result.leaderboard) || [];
          renderLeaderboard();
          renderSurvivors();
          $("#arenaRunBtn").disabled = false;
          status.className = "imp-status is-success";
          status.textContent = t("arena.done", "本场完成");
        } else if (rec.status === "failed") {
          clearInterval(state.jobTimer);
          state.jobTimer = null;
          $("#arenaRunBtn").disabled = false;
          status.className = "imp-status is-error";
          status.textContent = (rec.error || "failed") + "";
        }
      } catch (err) {
        clearInterval(state.jobTimer);
        state.jobTimer = null;
        $("#arenaRunBtn").disabled = false;
        const status = $("#arenaStatus");
        if (status) {
          status.className = "imp-status is-error";
          status.textContent = String(err);
        }
      }
    }, 700);
  }

  function setProgress(pct) {
    $("#arenaBar").style.width = pct + "%";
    $("#arenaPct").textContent = pct + "%";
  }

  // -- leaderboard + retain ---------------------------------------------
  function renderLeaderboard() {
    const wrap = $("#arenaLeaderboard");
    if (!state.leaderboard.length) {
      wrap.innerHTML = `<div class="arena-leaderboard-empty">${esc(t("arena.no_runs", "尚未运行"))}</div>`;
      return;
    }
    wrap.innerHTML = state.leaderboard.map((row, idx) => {
      const eliminated = state.eliminated.has(row.agent_id);
      const accPct = (row.accuracy * 100).toFixed(0) + "%";
      const lat = row.median_latency_s.toFixed(2) + "s";
      const cls = eliminated ? "arena-leaderboard-row is-eliminated" : "arena-leaderboard-row";
      const action = eliminated
        ? `<span class="arena-tag">${esc(t("arena.eliminated_tag", "已淘汰"))}</span>`
        : `<button class="button small" data-eliminate="${row.agent_id}">${esc(t("arena.eliminate_one", "淘汰"))}</button>`;
      return `<div class="${cls}">
        <span class="rank">${idx + 1}</span>
        <span class="name">#${row.agent_id} ${esc(row.name)}</span>
        <span class="acc"><b>${accPct}</b><span class="meta">(${row.correct}/${row.attempted})</span></span>
        <span class="latency">${lat}</span>
        <span class="row-actions">${action}</span>
      </div>`;
    }).join("");
    $$("button[data-eliminate]", wrap).forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = parseInt(btn.getAttribute("data-eliminate"), 10);
        applyElimination([id]);
      });
    });
  }

  function bindRetain() {
    $("#arenaApplyTopKBtn").addEventListener("click", async () => {
      if (!state.leaderboard.length) {
        alert(t("arena.need_run", "先跑一场"));
        return;
      }
      const k = Math.max(1, parseInt($("#arenaTopK").value, 10) || 1);
      try {
        const resp = await fetch("/api/arena/retain", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ city: state.city, leaderboard: state.leaderboard, k }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || ("HTTP " + resp.status));
        state.eliminated = new Set(data.all_eliminated || []);
        renderContestants();
        renderLeaderboard();
        renderEliminatedTags();
      } catch (err) {
        alert(String(err.message || err));
      }
    });
  }

  function applyElimination(agentIds) {
    state.eliminated = new Set([...state.eliminated, ...agentIds]);
    renderContestants();
    renderLeaderboard();
    renderEliminatedTags();
  }

  function renderSurvivors() {
    const wrap = $("#arenaSurvivors");
    if (!state.leaderboard.length) {
      wrap.innerHTML = `<span class="is-empty">${esc(t("arena.no_survivors", "尚未产生"))}</span>`;
      return;
    }
    const topK = Math.max(1, parseInt($("#arenaTopK").value, 10) || 1);
    const survivors = state.leaderboard.slice(0, topK).filter((r) => !state.eliminated.has(r.agent_id));
    if (!survivors.length) {
      wrap.innerHTML = `<span class="is-empty">${esc(t("arena.all_eliminated", "已全部淘汰"))}</span>`;
      return;
    }
    wrap.innerHTML = survivors
      .map((row) => `<span class="arena-tag is-success">#${row.agent_id} ${esc(row.name)}</span>`)
      .join("");
  }

  function renderEliminatedTags() {
    renderSurvivors();
  }

  // -- refill ----------------------------------------------------------
  function bindRefill() {
    $("#arenaRefillBtn").addEventListener("click", async () => {
      const fromCity = $("#arenaFromCity").value.trim();
      const n = parseInt($("#arenaRefillN").value, 10) || 1;
      const msg = $("#arenaRefillMsg");
      msg.className = "arena-status";
      if (!state.city) {
        msg.className = "imp-status is-error";
        msg.textContent = t("arena.need_city", "请先选择目标城市");
        return;
      }
      if (!fromCity) {
        msg.className = "imp-status is-error";
        msg.textContent = t("arena.need_source", "请填写来源城市");
        return;
      }
      try {
        const resp = await fetch("/api/arena/refill", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ city: state.city, from_city: fromCity, n }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || ("HTTP " + resp.status));
        msg.className = "imp-status is-success";
        msg.textContent = (data.added_names || []).join("、") + " 已加入";
        await loadAgents();
      } catch (err) {
        msg.className = "imp-status is-error";
        msg.textContent = String(err.message || err);
      }
    });
  }

  // -- go ---------------------------------------------------------------
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();