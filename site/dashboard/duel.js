// 双队竞赛 (Team Duel) — front-end controller.
//
// One server call carries the game:
//
//   POST /api/games/duel/run → {job_id}; poll /jobs/<id> for progress, then
//        draw the scored comparison.
//
// Two things the page does on its own:
//
// * **The roster is a tri-state.** Every resident row carries a 甲 / 乙 pair
//   of buttons rather than a checkbox, because "in the run" and "which side"
//   are one decision, and a checkbox plus a dropdown would take two clicks to
//   say what one click says here.
// * **Editing a built-in task's methods turns it into a custom task.** The
//   backend takes the methods from the bank entry, so a player who rewrites
//   them in the form has to be sent through the custom path or their edit is
//   silently ignored — which is the sort of thing you only notice three runs
//   later, wondering why both plans look the same.

(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
  const t = (key, fallback) => (typeof __ === "function" ? __(key) : fallback);

  const CUSTOM = "__custom__";

  const state = {
    city: null,
    agents: [],
    sides: new Map(),   // agent_id -> "A" | "B"
    tasks: [],
    criteria: [],
    maxPerTeam: 5,
    maxMembers: 10,
    maxScore: 40,
    run: null,
    jobId: null,
    jobTimer: null,
  };

  const exporter = GAWorldGameExport.attach(() => state.run && {
    game: "duel",
    label: (state.run.task || {}).title,
    markdown: GAWorldGameExport.duel(state.run),
  });

  async function init() {
    $("#dRunBtn").addEventListener("click", startRun);
    $("#dPickRandom").addEventListener("click", pickRandom);
    $("#dPickNone").addEventListener("click", () => { state.sides.clear(); afterPick(); });
    $("#dCity").addEventListener("change", () => {
      state.city = $("#dCity").value;
      state.sides.clear();
      loadAgents();
    });
    $("#dTask").addEventListener("change", renderTask);
    $("#dRounds").addEventListener("input", renderCost);
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
    const sel = $("#dTask");
    try {
      const resp = await fetch("/api/games/duel/catalogue");
      const data = await resp.json();
      state.tasks = data.tasks || [];
      state.criteria = data.criteria || [];
      state.maxPerTeam = data.max_per_team || 5;
      state.maxMembers = data.max_members || 10;
      state.maxScore = data.max_score || 40;
      sel.innerHTML = state.tasks
        .map((task) => `<option value="${esc(task.id)}">${esc(task.emoji + " " + task.title)}</option>`)
        .join("") + `<option value="${CUSTOM}">✍️ ${esc(t("duel.custom_option", "自己出一个…"))}</option>`;
      $("#dRounds").max = data.max_rounds || 3;
      $("#dRounds").value = data.default_rounds || 2;
      renderTask();
    } catch (err) {
      sel.innerHTML = `<option value="">${esc(String(err))}</option>`;
    }
  }

  function currentTask() {
    return state.tasks.find((task) => task.id === $("#dTask").value) || null;
  }

  function renderTask() {
    const custom = $("#dTask").value === CUSTOM;
    $("#dCustomBlock").hidden = !custom;
    const task = currentTask();
    $("#dTaskText").textContent = custom
      ? t("duel.custom_hint", "自己写一个任务，再给两个队各写一条路子。")
      : (task ? task.text + "（" + task.goal + "）" : "");
    // Prefill the method boxes so a built-in task is playable without typing,
    // and an edit starts from something concrete rather than a blank page.
    $("#dMethodATitle").value = custom ? "" : (task ? task.method_a.title : "");
    $("#dMethodAText").value = custom ? "" : (task ? task.method_a.text : "");
    $("#dMethodBTitle").value = custom ? "" : (task ? task.method_b.title : "");
    $("#dMethodBText").value = custom ? "" : (task ? task.method_b.text : "");
    renderCost();
  }

  function renderCost() {
    const rounds = Math.max(1, parseInt($("#dRounds").value, 10) || 1);
    const members = state.sides.size;
    const calls = rounds * (members + 2) + 1;
    $("#dCost").textContent = t("duel.cost_prefix", "开销：轮数 ×（人数 + 2）+ 1 次模型调用 = ") + calls;
  }

  async function loadAgents() {
    const list = $("#dAgents");
    if (state.city === null) return;
    list.innerHTML = `<li class="disaster-empty">${esc(t("duel.loading", "加载中…"))}</li>`;
    try {
      const resp = await fetch("/api/games/agents?city=" + encodeURIComponent(state.city));
      const data = await resp.json();
      state.agents = data.agents || [];
      renderAgents();
      afterPick();
    } catch (err) {
      list.innerHTML = `<li class="disaster-empty is-error">${esc(String(err))}</li>`;
    }
  }

  function renderAgents() {
    const list = $("#dAgents");
    if (!state.agents.length) {
      list.innerHTML = `<li class="disaster-empty">${esc(t("duel.no_agents", "这座城市暂无居民"))}</li>`;
      return;
    }
    list.innerHTML = state.agents.map((a) => {
      const side = state.sides.get(a.id) || "";
      const meta = [a.age ? a.age + "岁" : "", a.job || ""].filter(Boolean).join(" · ");
      return `<li class="${side ? "is-picked" : ""}">
        <span class="who">#${a.id} ${esc(a.name)}<span class="meta"> ${esc(meta)}</span></span>
        <span class="duel-side">
          <button type="button" class="duel-pick is-a ${side === "A" ? "is-on" : ""}" data-agent="${a.id}" data-side="A">甲</button>
          <button type="button" class="duel-pick is-b ${side === "B" ? "is-on" : ""}" data-agent="${a.id}" data-side="B">乙</button>
        </span>
      </li>`;
    }).join("");
    $$("button[data-agent]", list).forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = parseInt(btn.getAttribute("data-agent"), 10);
        const side = btn.getAttribute("data-side");
        if (state.sides.get(id) === side) state.sides.delete(id);
        else if (countSide(side) >= state.maxPerTeam) {
          setStatus(t("duel.team_full", "一个队最多 ") + state.maxPerTeam + t("duel.team_full_tail", " 人"), true);
          return;
        } else state.sides.set(id, side);
        renderAgents();
        afterPick();
      });
    });
  }

  function countSide(side) {
    let n = 0;
    state.sides.forEach((value) => { if (value === side) n += 1; });
    return n;
  }

  function afterPick() {
    $("#dCountA").textContent = countSide("A");
    $("#dCountB").textContent = countSide("B");
    renderCost();
  }

  function pickRandom() {
    const pool = state.agents.slice();
    for (let i = pool.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [pool[i], pool[j]] = [pool[j], pool[i]];
    }
    const perTeam = Math.min(3, state.maxPerTeam, Math.floor(pool.length / 2));
    state.sides.clear();
    pool.slice(0, perTeam).forEach((a) => state.sides.set(a.id, "A"));
    pool.slice(perTeam, perTeam * 2).forEach((a) => state.sides.set(a.id, "B"));
    renderAgents();
    afterPick();
  }

  // -- run ----------------------------------------------------------------
  function teamIds(side) {
    const ids = [];
    state.sides.forEach((value, id) => { if (value === side) ids.push(id); });
    return ids;
  }

  function methodsEdited(task) {
    if (!task) return true;
    return $("#dMethodATitle").value.trim() !== task.method_a.title
      || $("#dMethodAText").value.trim() !== task.method_a.text
      || $("#dMethodBTitle").value.trim() !== task.method_b.title
      || $("#dMethodBText").value.trim() !== task.method_b.text;
  }

  async function startRun() {
    const teamA = teamIds("A");
    const teamB = teamIds("B");
    if (!teamA.length || !teamB.length) {
      return setStatus(t("duel.need_two_teams", "两个队各至少要一个人。"), true);
    }
    const isCustom = $("#dTask").value === CUSTOM;
    const task = currentTask();
    const methods = {
      method_a: { title: $("#dMethodATitle").value.trim(), text: $("#dMethodAText").value.trim() },
      method_b: { title: $("#dMethodBTitle").value.trim(), text: $("#dMethodBText").value.trim() },
    };
    if (!methods.method_a.text || !methods.method_b.text) {
      return setStatus(t("duel.need_methods", "两个队各要一个办法，不然没得比。"), true);
    }

    const body = {
      city: state.city,
      team_a: teamA,
      team_b: teamB,
      rounds: Math.max(1, parseInt($("#dRounds").value, 10) || 2),
      task_id: isCustom ? "" : $("#dTask").value,
    };
    // A rewritten method only reaches the model through the custom path.
    if (isCustom || methodsEdited(task)) {
      body.task_id = "";
      body.custom = Object.assign({
        title: isCustom ? $("#dCustomTitle").value.trim() : task.title,
        text: isCustom ? $("#dCustomText").value.trim() : task.text,
        goal: isCustom ? $("#dCustomGoal").value.trim() : task.goal,
      }, methods);
    }

    $("#dRunBtn").disabled = true;
    setProgress(0);
    setStatus(t("duel.running", "开赛…"));
    try {
      const resp = await fetch("/api/games/duel/run", {
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
        const resp = await fetch("/api/games/duel/jobs/" + encodeURIComponent(state.jobId));
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const rec = await resp.json();
        setProgress(Math.round((rec.progress || 0) * 100));
        if (rec.status === "running") {
          setStatus(rec.message || t("duel.running", "开赛…"));
          return;
        }
        stopPolling();
        if (rec.status === "done") {
          state.run = rec.result;
          render();
          setStatus(t("duel.done", "比完了"));
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
    exporter.sync();
    if (!run) return;
    const task = run.task || {};
    $("#dTitle").textContent = (task.emoji || "") + " " + (task.title || "");
    renderVerdict(run);
    renderSheet(run);
    renderBoards(run);
  }

  function teamByKey(run, key) {
    return (run.teams || []).find((team) => team.key === key) || { members: [], plans: [], method: {} };
  }

  function renderVerdict(run) {
    const verdict = run.verdict || {};
    const scores = verdict.scores || {};
    const teamA = teamByKey(run, "A");
    const teamB = teamByKey(run, "B");
    const winner = verdict.winner;
    const label = winner === "tie"
      ? t("duel.tie", "打平")
      : (winner === "A" ? teamA.name : teamB.name) + t("duel.wins", " 赢");
    const disagreed = (run.stats || {}).judge_disagreed;
    const said = verdict.judge_said;
    const saidLabel = said === "tie"
      ? t("duel.tie", "打平")
      : (said === "A" ? teamA.name : said === "B" ? teamB.name : "");

    $("#dVerdict").className = "duel-verdict is-" + (winner === "tie" ? "tie" : winner.toLowerCase());
    $("#dVerdict").innerHTML = `
      <div class="duel-score">
        <span class="side is-a">
          <b>${esc(teamA.name)}</b><span class="method">${esc((teamA.method || {}).title || "")}</span>
          <i>${(scores.A || {}).total || 0}</i>
        </span>
        <span class="vs">vs</span>
        <span class="side is-b">
          <b>${esc(teamB.name)}</b><span class="method">${esc((teamB.method || {}).title || "")}</span>
          <i>${(scores.B || {}).total || 0}</i>
        </span>
      </div>
      <h4>${esc(label)}</h4>
      <p>${esc(verdict.reason || "")}</p>
      <p class="duel-blind">${esc(t("duel.blind", "评审看到的是「方案一 / 方案二」，不知道谁是谁。这一场的顺序："))}
        ${esc((verdict.order || []).map((k) => (k === "A" ? teamA.name : teamB.name)).join(" → "))}
        ${disagreed ? `<b class="duel-flag">${esc(t("duel.disagreed", "评审自己说的赢家是 ") + saidLabel + t("duel.disagreed_tail", "，和分数对不上——两份方案很接近。"))}</b>` : ""}
      </p>`;
  }

  function renderSheet(run) {
    const verdict = run.verdict || {};
    const scores = verdict.scores || {};
    const criteria = verdict.criteria || state.criteria;
    const rows = criteria.map((c) => {
      const a = (scores.A || {})[c.key] || 0;
      const b = (scores.B || {})[c.key] || 0;
      const max = 10;
      return `<div class="duel-row">
        <span class="n is-a">${a}</span>
        <span class="track"><i class="is-a" style="width:${(a / max) * 100}%"></i></span>
        <span class="label">${esc(c.label)}</span>
        <span class="track"><i class="is-b" style="width:${(b / max) * 100}%"></i></span>
        <span class="n is-b">${b}</span>
      </div>`;
    }).join("");
    $("#dSheet").innerHTML = `<h4>${esc(t("duel.scoresheet", "评分表"))}</h4>${rows}`;
  }

  function renderBoards(run) {
    $("#dBoards").innerHTML = ["A", "B"].map((key) => {
      const team = teamByKey(run, key);
      const plans = team.plans || [];
      const last = plans[plans.length - 1] || {};
      const earlier = plans.slice(0, -1);
      const steps = (last.steps || []).map((s) => `<li>${esc(s)}</li>`).join("");
      const members = (team.members || []).map((m) => {
        const move = (m.moves || [])[m.moves.length - 1] || {};
        return `<div class="duel-member">
          <header><span class="name">${esc(m.name)}</span><span class="job">${esc(m.job || "")}</span></header>
          <p class="move">${esc(move.move || "—")}</p>
          <p class="why">${esc(move.why || "")}</p>
          <footer><span class="conf">${esc(t("duel.confidence", "把握"))} ${move.confidence || 0}</span></footer>
        </div>`;
      }).join("");
      const history = earlier.length
        ? `<details class="duel-history-plans">
             <summary>${esc(t("duel.earlier_rounds", "更早几轮的方案"))}（${earlier.length}）</summary>
             ${earlier.map((p) => `<p><b>${t("duel.round", "第")}${p.round + 1}${t("duel.round_tail", "轮")}：</b>${esc(p.headline)}</p>`).join("")}
           </details>`
        : "";
      return `<section class="duel-board is-${key.toLowerCase()}">
        <header class="duel-board-head">
          <h4>${esc(team.name)}</h4>
          <span class="method">${esc((team.method || {}).title || "")}</span>
        </header>
        <p class="duel-method-text">${esc((team.method || {}).text || "")}</p>
        <p class="duel-headline">${esc(last.headline || "—")}</p>
        <ol class="duel-steps">${steps}</ol>
        ${last.risk ? `<p class="duel-risk">${esc(t("duel.risk", "最可能栽在："))}${esc(last.risk)}</p>` : ""}
        ${history}
        <div class="duel-members">${members}</div>
      </section>`;
    }).join("");
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
    const list = $("#dHistory");
    try {
      const resp = await fetch("/api/games/duel/runs");
      const data = await resp.json();
      const runs = data.runs || [];
      if (!runs.length) {
        list.innerHTML = `<li class="persuade-empty">${esc(t("duel.no_history", "还没有比过"))}</li>`;
        return;
      }
      list.innerHTML = runs.map((r) => {
        const mark = r.winner === "tie"
          ? t("duel.tie", "打平")
          : (r.winner === "A" ? t("duel.team_a", "甲队") : t("duel.team_b", "乙队")) + t("duel.wins", " 赢");
        return `<li>
          <button type="button" data-job="${esc(r.job_id)}">
            <span class="who">${esc((r.emoji || "") + " " + (r.task || ""))}</span>
            <span class="meta">${esc(mark)} · ${r.score_a || 0} : ${r.score_b || 0}</span>
          </button>
        </li>`;
      }).join("");
      $$("button[data-job]", list).forEach((btn) => {
        btn.addEventListener("click", () => openRun(btn.getAttribute("data-job")));
      });
    } catch (err) {
      list.innerHTML = `<li class="persuade-empty is-error">${esc(String(err))}</li>`;
    }
  }

  async function openRun(jobId) {
    try {
      const resp = await fetch("/api/games/duel/jobs/" + encodeURIComponent(jobId));
      const rec = await resp.json();
      if (!resp.ok) throw new Error(rec.error || "HTTP " + resp.status);
      state.run = rec.result;
      render();
      setStatus(t("duel.viewing", "回看已结束的一场"));
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
