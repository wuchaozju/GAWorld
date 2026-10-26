
var gwHTML = globalThis.GAWorldURL ? globalThis.GAWorldURL.html : function (value) { return value; };
// 《这是我的战争》 (Warzone) — front-end controller.
//
// One run is one background job on the server (`/api/games/warzone/*`):
//
//   POST /run        → {job_id}; days × agents × 2 + 1 LLM calls, polled.
//   GET  /jobs/<id>  → progress while running, the whole run once done.
//   GET  /runs       → finished runs still in memory (sidebar history).
//
// The board is rendered only after `status === "done"`: a day is meaningless
// until everyone in it has proposed, voted, and the warehouse settled. The
// progress bar is what moves during the round; the stock bar shrinks day by day.

(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
  const t = (key, fallback) => {
    const value = typeof __ === "function" ? __(key) : "";
    return !value || value === key ? fallback : value;
  };

  const CUSTOM = "__custom__";

  const state = {
    city: null,
    agents: [],
    picked: new Set(),
    scenarios: [],
    run: null,
    jobId: null,
    // Release function returned by setButtonBusy() while the run
    // button is busy. pollJob/stopPolling read this to re-enable
    // the button when the job ends; null when at rest.
    runRelease: null,
    jobTimer: null,
  };

  const exporter = GAWorldGameExport.attach(() => state.run && {
    game: "warzone",
    label: (state.run.scenario || {}).name,
    markdown: GAWorldGameExport.warzone(state.run),
  });

  async function init() {
    $("#wRunBtn").addEventListener("click", startRun);
    $("#wPickRandom").addEventListener("click", pickRandom);
    $("#wPickNone").addEventListener("click", () => { state.picked.clear(); renderAgents(); });
    $("#wCity").addEventListener("change", () => {
      state.city = $("#wCity").value;
      state.picked.clear();
      loadAgents();
    });
    $("#wScenario").addEventListener("change", renderScenarioHint);
    await Promise.all([loadCities().then(loadAgents), loadCatalogue()]);
    loadHistory();
  }

  // -- pickers ------------------------------------------------------------
  async function loadCities() {
    const sel = $("#wCity");
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
    } catch (err) {
      sel.innerHTML = gwHTML(`<option value="">${esc(String(err))}</option>`);
      state.city = "";
    }
  }

  async function loadCatalogue() {
    const sel = $("#wScenario");
    try {
      const resp = await fetch("/api/games/warzone/catalogue");
      const data = await resp.json();
      state.scenarios = data.scenarios || [];
      state.maxAgents = data.max_agents || 8;
      state.resources = data.resources || ["食物", "药品", "燃料", "守卫时间"];
      sel.innerHTML = gwHTML(state.scenarios
        .map((s) => `<option value="${esc(s.id)}">${esc(s.emoji + " " + s.name)}</option>`)
        .join("") + `<option value="${CUSTOM}">✍️ ${esc(t("warzone.custom_option", "自定义剧本…"))}</option>`);
      $("#wDays").max = data.default_days || 7;
      $("#wDays").value = data.default_days || 7;
      renderScenarioHint();
    } catch (err) {
      sel.innerHTML = gwHTML(`<option value="">${esc(String(err))}</option>`);
    }
  }

  function renderScenarioHint() {
    const id = $("#wScenario").value;
    const custom = id === CUSTOM;
    $("#wCustomBlock").hidden = !custom;
    const found = state.scenarios.find((s) => s.id === id);
    $("#wScenarioHint").textContent = custom
      ? t("warzone.custom_hint", "自己写：每行一天，每段开头写「第 N 天：」会更自然。")
      : (found ? found.days.map((d, i) => `第${i + 1}天 · ${d.slice(0, 24)}…`).join("\n") : "");
  }

  async function loadAgents() {
    const list = $("#wAgents");
    if (state.city === null) return;
    list.innerHTML = gwHTML(`<li class="warzone-empty">${esc(t("warzone.loading", "加载中…"))}</li>`);
    try {
      const resp = await fetch("/api/games/agents?city=" + encodeURIComponent(state.city));
      const data = await resp.json();
      state.agents = data.agents || [];
      renderAgents();
    } catch (err) {
      list.innerHTML = gwHTML(`<li class="warzone-empty is-error">${esc(String(err))}</li>`);
    }
  }

  function renderAgents() {
    const list = $("#wAgents");
    if (!state.agents.length) {
      list.innerHTML = gwHTML(`<li class="warzone-empty">${esc(t("warzone.no_agents", "这座城市暂无居民"))}</li>`);
      $("#wPicked").textContent = "0";
      return;
    }
    list.innerHTML = gwHTML(state.agents
      .map((a) => {
        const meta = [a.age ? a.age + "岁" : "", a.gender || "", a.job || ""].filter(Boolean).join(" · ");
        const on = state.picked.has(a.id) ? " checked" : "";
        return `<li><label>
          <input type="checkbox" value="${a.id}"${on} />
          <span class="who">#${a.id} ${esc(a.name)}</span>
          <span class="meta">${esc(meta)}</span>
        </label></li>`;
      })
      .join(""));
    Array.from(list.querySelectorAll("input[type=checkbox]")).forEach((box) => {
      box.addEventListener("change", () => {
        const id = parseInt(box.value, 10);
        if (box.checked) state.picked.add(id);
        else state.picked.delete(id);
        if (state.picked.size > (state.maxAgents || 8)) {
          state.picked.delete(id);
          box.checked = false;
          setStatus(t("warzone.too_many", "最多 8 人"), true);
        }
        $("#wPicked").textContent = String(state.picked.size);
      });
    });
    $("#wPicked").textContent = String(state.picked.size);
  }

  function pickRandom() {
    const pool = state.agents.slice();
    for (let i = pool.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [pool[i], pool[j]] = [pool[j], pool[i]];
    }
    state.picked = new Set(pool.slice(0, 5).map((a) => a.id));
    renderAgents();
  }

  // -- the run ------------------------------------------------------------
  async function startRun() {
    if (!state.picked.size) return setStatus(t("warzone.need_agents", "先选几个居民"), true);
    const id = $("#wScenario").value;
    const body = {
      city: state.city,
      agent_ids: Array.from(state.picked),
      scenario_id: id === CUSTOM ? "" : id,
      days: Math.max(1, parseInt($("#wDays").value, 10) || 7),
    };
    if (id === CUSTOM) {
      body.custom = {
        name: $("#wCustomName").value.trim(),
        days: $("#wCustomDays").value,
        stock: {
          食物: parseInt($("#wCustomStockFood").value, 10) || 0,
          药品: parseInt($("#wCustomStockMedicine").value, 10) || 0,
          燃料: parseInt($("#wCustomStockFuel").value, 10) || 0,
          守卫时间: parseInt($("#wCustomStockGuard").value, 10) || 0,
        },
      };
    }

    $("#wRunBtn").disabled = true;
    state.runRelease = setButtonBusy($("#wRunBtn"), "warzone.running", "围困中…");
    setProgress(0);
    setStatus(t("warzone.running", "围困中…"));
    try {
      const resp = await fetch("/api/games/warzone/run", {
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
      if (state.runRelease) { state.runRelease(); state.runRelease = null; }
    }
  }

  function pollJob() {
    if (!state.jobId) return;
    clearInterval(state.jobTimer);
    state.jobTimer = setInterval(async () => {
      try {
        const resp = await fetch("/api/games/warzone/jobs/" + encodeURIComponent(state.jobId));
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const rec = await resp.json();
        setProgress(Math.round((rec.progress || 0) * 100));
        if (rec.status === "running") {
          setStatus(rec.message || t("warzone.running", "围困中…"));
          return;
        }
        stopPolling();
        if (rec.status === "done") {
          state.run = rec.result;
          render();
          setStatus(t("warzone.done", "围困完成"));
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
    if (state.runRelease) { state.runRelease(); state.runRelease = null; }
  }

  // -- rendering ----------------------------------------------------------
  function render() {
    const run = state.run;
    $("#wIdle").hidden = !!run;
    $("#wResult").hidden = !run;
    exporter.sync();
    if (!run) return;

    const sc = run.scenario || {};
    $("#wTitle").textContent = `${sc.emoji || ""} ${sc.name || ""} · ${(run.residents || []).length} 人 · ${(run.days || []).length} 天`;

    $("#wEssayBox").hidden = !run.essay;
    $("#wEssay").textContent = run.essay || "";

    const stats = run.stats || {};
    $("#wOverall").innerHTML = gwHTML([
      metric(t("warzone.m_mortality", "死亡率"), pct(stats.mortality), ""),
      metric(t("warzone.m_dissent", "投票分歧"), pct(stats.dissent_rate), ""),
      metric(t("warzone.m_gini", "食物基尼"), stats.food_gini == null ? "—" : stats.food_gini, ""),
      metric(t("warzone.m_distress", "平均道德焦虑"), stats.avg_moral_distress == null ? "—" : stats.avg_moral_distress, "/ 5"),
      metric(t("warzone.m_depleted", "最先耗尽"), stats.depleted_first || t("warzone.depleted_none", "（未耗尽）"), ""),
      metric(t("warzone.m_strongest", "最坚定建议者"), personRef(stats.strongest_id, run.residents), ""),
      metric(t("warzone.m_excluded", "最被排斥居民"), personRef(stats.most_excluded_id, run.residents), ""),
    ].join(""));

    $("#wStock").innerHTML = gwHTML(stockTrail(run));
    $("#wLog").innerHTML = gwHTML((run.log || []).map(dayBlock).join(""));
  }

  function pct(x) {
    return Math.round((Number(x) || 0) * 100) + "%";
  }

  function personRef(id, residents) {
    if (!id) return "—";
    const found = (residents || []).find((p) => p.agent_id === id);
    return found ? `#${id} ${esc(found.name)}` : `#${id}`;
  }

  function metric(label, value, suffix) {
    return `<div class="warzone-metric">
      <span class="label">${esc(label)}</span>
      <b>${esc(value == null ? "—" : value)}</b><span class="suffix">${esc(suffix)}</span>
    </div>`;
  }

  // Stock trail: one pill per day, per resource. The first pill shows the
  // initial stockpile (before any distribution ran); subsequent pills show
  // each day's post-settlement stock so the curve is monotone decreasing.
  function stockTrail(run) {
    const initial = (run.scenario || {}).stock_initial || {};
    const days = run.log || [];
    const resources = Object.keys(initial);
    if (!resources.length) return "";
    const maxStock = Math.max(...Object.values(initial), 1);
    const head = `<h4>${esc(t("warzone.stock_title", "仓库每日结余"))}</h4>`;
    const rows = resources.map((resource) => {
      const series = [initial[resource] || 0].concat(
        days.map((d) => d.stock_after ? (d.stock_after[resource] || 0) : 0)
      );
      const bars = series.map((value, i) => {
        const width = Math.max(2, Math.round((value / maxStock) * 100));
        const label = i === 0 ? t("warzone.stock_initial", "初") : `${t("warzone.day_short", "天")}${i}`;
        return `<span class="warzone-stock-pill" style="--w:${width}%"><b>${esc(label)}</b><i>${value}</i></span>`;
      }).join("");
      return `<div class="warzone-stock-row"><span class="warzone-stock-label">${esc(resource)}</span><span class="warzone-stock-cells">${bars}</span></div>`;
    }).join("");
    return head + rows;
  }

  function dayBlock(day, index) {
    const stock = day.stock_after || {};
    const initial = day.stock_before || {};
    const stockLine = Object.keys(stock)
      .map((k) => {
        const before = initial[k] != null ? initial[k] : "?";
        const after = stock[k];
        if (before === after) return `${k} ${after}`;
        return `${k} ${before}→${after}`;
      })
      .join(" · ");
    const deathsLine = (day.deaths && day.deaths.length)
      ? `<p class="warzone-day-deaths">☠ ${esc(day.deaths.join("、"))}</p>` : "";
    const proposals = (day.proposals || [])
      .map((p, i) => planCard(p, i, personById))
      .join("");
    const votes = (day.votes || []).map((v) => voteCard(v, day.proposals, personById)).join("");
    const winner = day.winning_proposal || {};
    const winnerAuthor = winner.author_id
      ? personLabel(winner.author_id, winner.author_name)
      : "（无）";
    const tally = day.tally || {};
    const tallyLine = Object.keys(tally).length
      ? Object.entries(tally).map(([idx, n]) => {
          const proposal = (day.proposals || [])[parseInt(idx, 10)];
          return `${proposal ? personLabel(proposal.author_id, proposal.author_name) : `方案${parseInt(idx, 10) + 1}`}:${n}`;
        }).join(" · ")
      : "（无）";
    return `<section class="warzone-day">
      <header class="warzone-day-head">
        <h4>${esc(t("warzone.day", "第"))}${index + 1}${esc(t("warzone.day_suffix", "天"))}</h4>
        <span class="warzone-day-meta">${esc(stockLine)}</span>
      </header>
      <p class="warzone-day-text">${esc(day.text || "")}</p>
      <p class="warzone-day-winner">
        <b>${esc(t("warzone.winner_label", "胜出方案"))}:</b>
        ${esc(winnerAuthor)} · ${esc(winner.rationale || "")}
      </p>
      <p class="warzone-day-tally">${esc(t("warzone.tally_label", "票数"))}: ${esc(tallyLine)}</p>
      <div class="warzone-proposals">${proposals}</div>
      <div class="warzone-votes">${votes}</div>
      ${deathsLine}
    </section>`;
  }

  function personById(id) {
    return (state.run && state.run.residents || []).find((p) => p.agent_id === id) || null;
  }

  function planCard(plan, index, resolveName) {
    const authorLabel = resolveName(plan.author_id)
      ? personLabel(plan.author_id, plan.author_name)
      : `#${plan.author_id}`;
    const rows = (plan.plan || []).map((row) => {
      const recipientLabel = recipientLabelFor(row.recipient_id, resolveName);
      return `<li><b>${esc(row.resource)}</b> → <span>${esc(recipientLabel)}</span> ×${row.amount}</li>`;
    }).join("");
    return `<article class="warzone-plan">
      <header>
        <span class="plan-label">${esc(authorLabel)}</span>
        <span class="plan-author">${esc(plan.rationale || "")}</span>
      </header>
      <ul class="plan-rows">${rows}</ul>
    </article>`;
  }

  function voteCard(vote, proposals, resolveName) {
    const choice = vote.choice || "abstain";
    const targetProposal = vote.for && proposals ? proposals[vote.for - 1] : null;
    const target = targetProposal
      ? personLabel(targetProposal.author_id, targetProposal.author_name)
      : "";
    const cls = choice === "yes" ? "is-yes" : choice === "no" ? "is-no" : "is-abstain";
    const voter = resolveName(vote.voter_id);
    const voterLabel = voter ? personLabel(voter.agent_id, voter.name) : `#${vote.voter_id}`;
    return `<div class="warzone-vote ${cls}">
      <span class="who">${esc(voterLabel)}</span>
      <span class="choice">${esc(choice)}</span>
      ${target ? `<span class="for">→ ${esc(target)}</span>` : ""}
      ${(vote.reason || "").trim() ? `<span class="reason" title="${esc(vote.reason)}">${esc(vote.reason)}</span>` : ""}
    </div>`;
  }

  function personLabel(id, fallbackName) {
    return `#${id} ${esc(fallbackName || "")}`.trim();
  }

  function recipientLabelFor(token, resolveName) {
    const text = String(token || "").trim();
    if (text === "shared") return "公共";
    if (text === "household") return "全家庭";
    const m = text.match(/^#?(\d+)$/);
    if (m) {
      const person = resolveName(parseInt(m[1], 10));
      return person ? personLabel(person.agent_id, person.name) : text;
    }
    return text;
  }

  function setStatus(message, isError) {
    const el = $("#wStatus");
    el.className = "warzone-status" + (isError ? " is-error" : "");
    el.textContent = message;
  }

  function setProgress(pct) {
    $("#wBar").style.width = pct + "%";
    $("#wPct").textContent = pct + "%";
  }

  async function loadHistory() {
    const ul = $("#wHistory");
    try {
      const resp = await fetch("/api/games/warzone/runs");
      const data = await resp.json();
      const runs = data.runs || [];
      if (!runs.length) {
        ul.innerHTML = gwHTML(`<li class="warzone-empty">${esc(t("warzone.no_history", "还没有围困记录"))}</li>`);
        return;
      }
      ul.innerHTML = gwHTML(runs.map((r) => `<li>
        <button type="button" data-job="${esc(r.job_id)}">
          <span class="who">${esc((r.emoji || "") + " " + (r.scenario || ""))}</span>
          <span class="meta">${r.agents} ${esc(t("warzone.people", "人"))} · ${r.days} ${esc(t("warzone.day_suffix", "天"))} · 死亡率 ${pct(r.mortality)}</span>
        </button>
      </li>`).join(""));
      Array.from(ul.querySelectorAll("button[data-job]")).forEach((btn) => {
        btn.addEventListener("click", () => openRun(btn.getAttribute("data-job")));
      });
    } catch (err) {
      ul.innerHTML = gwHTML(`<li class="warzone-empty is-error">${esc(String(err))}</li>`);
    }
  }

  async function openRun(jobId) {
    try {
      const resp = await fetch("/api/games/warzone/jobs/" + encodeURIComponent(jobId));
      const rec = await resp.json();
      if (!resp.ok) throw new Error(rec.error || "HTTP " + resp.status);
      state.run = rec.result;
      render();
      setStatus(t("warzone.viewing", "回看已完成的围困"));
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
