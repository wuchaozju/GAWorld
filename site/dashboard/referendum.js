// 公投局 (Referendum) — front-end controller.
//
//   POST /api/games/referendum/run   → {job_id}; residents × 2 model calls,
//        so it is a background job like disaster mode and the rumor game.
//   GET  /api/games/referendum/jobs/<id> → progress, then the whole vote.
//   GET  /api/games/referendum/runs  → finished votes (sidebar history).
//
// The board is built around one comparison: the private tally against the
// public one. Everything else on the page — the flip list, the cards, the
// digest — is there to explain that single pair of bars.

(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
  // Same contract as city-agents.js: an unresolved key means i18n has not
  // loaded yet (the catalogue fetch can win that race), so fall back to the
  // inline text rather than rendering "vote.custom_option" at the user.
  const t = (key, fallback) => {
    const value = typeof __ === "function" ? __(key) : "";
    return !value || value === key ? fallback : value;
  };

  const CUSTOM = "__custom__";
  const STANCES = ["支持", "反对", "弃权"];

  const state = {
    city: null,
    agents: [],
    picked: new Set(),
    motions: [],
    run: null,
    jobId: null,
    jobTimer: null,
    maxAgents: 14,
  };

  const exporter = GAWorldGameExport.attach(() => state.run && {
    game: "referendum",
    label: (state.run.motion || {}).title,
    markdown: GAWorldGameExport.referendum(state.run),
  });

  async function init() {
    $("#vRunBtn").addEventListener("click", startRun);
    $("#vPickRandom").addEventListener("click", pickRandom);
    $("#vPickNone").addEventListener("click", () => { state.picked.clear(); renderAgents(); });
    $("#vCity").addEventListener("change", () => {
      state.city = $("#vCity").value;
      state.picked.clear();
      loadAgents();
    });
    $("#vMotion").addEventListener("change", renderMotionText);
    await Promise.all([loadCities().then(loadAgents), loadCatalogue()]);
    loadHistory();
  }

  // -- pickers ------------------------------------------------------------
  async function loadCities() {
    const sel = $("#vCity");
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
    const sel = $("#vMotion");
    try {
      const resp = await fetch("/api/games/referendum/catalogue");
      const data = await resp.json();
      state.motions = data.motions || [];
      state.maxAgents = data.max_agents || 14;
      sel.innerHTML = state.motions
        .map((m) => `<option value="${esc(m.id)}">${esc(m.emoji + " " + m.title)}</option>`)
        .join("") + `<option value="${CUSTOM}">✍️ ${esc(t("vote.custom_option", "自己写一个议案…"))}</option>`;
      renderMotionText();
    } catch (err) {
      sel.innerHTML = `<option value="">${esc(String(err))}</option>`;
    }
  }

  function renderMotionText() {
    const id = $("#vMotion").value;
    const custom = id === CUSTOM;
    $("#vCustomBlock").hidden = !custom;
    const found = state.motions.find((m) => m.id === id);
    $("#vMotionText").textContent = custom
      ? t("vote.custom_hint", "写清楚投什么、谁得利、谁吃亏。")
      : (found ? found.text : "");
  }

  async function loadAgents() {
    const list = $("#vAgents");
    if (state.city === null) return;
    list.innerHTML = `<li class="disaster-empty">${esc(t("vote.loading", "加载中…"))}</li>`;
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
    const list = $("#vAgents");
    if (!state.agents.length) {
      list.innerHTML = `<li class="disaster-empty">${esc(t("vote.no_agents", "这座城市暂无居民"))}</li>`;
      $("#vPicked").textContent = "0";
      return;
    }
    list.innerHTML = state.agents
      .map((a) => {
        const meta = [a.age ? a.age + "岁" : "", a.job || "", a.residence || ""].filter(Boolean).join(" · ");
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
        if (state.picked.size > state.maxAgents) {
          state.picked.delete(id);
          box.checked = false;
          setStatus(t("vote.too_many", "最多 14 人"), true);
        }
        $("#vPicked").textContent = String(state.picked.size);
      });
    });
    $("#vPicked").textContent = String(state.picked.size);
  }

  function pickRandom() {
    const pool = state.agents.slice();
    for (let i = pool.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [pool[i], pool[j]] = [pool[j], pool[i]];
    }
    state.picked = new Set(pool.slice(0, 8).map((a) => a.id));
    renderAgents();
  }

  // -- the run ------------------------------------------------------------
  async function startRun() {
    if (state.picked.size < 2) return setStatus(t("vote.need_two", "至少选两个人才叫表决"), true);
    const id = $("#vMotion").value;
    const body = {
      city: state.city,
      agent_ids: Array.from(state.picked),
      motion_id: id === CUSTOM ? "" : id,
      campaign: $("#vCampaign").value.trim(),
    };
    if (id === CUSTOM) {
      body.custom = { title: $("#vCustomTitle").value.trim(), text: $("#vCustomText").value };
    }

    $("#vRunBtn").disabled = true;
    setProgress(0);
    setStatus(t("vote.running", "表决中…"));
    try {
      const resp = await fetch("/api/games/referendum/run", {
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
      $("#vRunBtn").disabled = false;
    }
  }

  function pollJob() {
    if (!state.jobId) return;
    clearInterval(state.jobTimer);
    state.jobTimer = setInterval(async () => {
      try {
        const resp = await fetch("/api/games/referendum/jobs/" + encodeURIComponent(state.jobId));
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const rec = await resp.json();
        setProgress(Math.round((rec.progress || 0) * 100));
        if (rec.status === "running") {
          setStatus(rec.message || t("vote.running", "表决中…"));
          return;
        }
        stopPolling();
        if (rec.status === "done") {
          state.run = rec.result;
          render();
          setStatus(t("vote.done", "表决结束"));
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
    $("#vRunBtn").disabled = false;
  }

  // -- rendering ----------------------------------------------------------
  function render() {
    const run = state.run;
    $("#vIdle").hidden = !!run;
    $("#vResult").hidden = !run;
    exporter.sync();
    if (!run) return;

    const motion = run.motion || {};
    const stats = run.stats || {};
    const pub = stats.public || {};
    $("#vTitle").textContent = `${motion.emoji || ""} ${motion.title || ""} · ${stats.total} ${t("vote.voters", "人")}`;

    const passed = stats.result === "通过";
    const verdict = $("#vVerdict");
    verdict.className = "vote-verdict " + (passed ? "is-pass" : stats.result === "否决" ? "is-fail" : "is-tie");
    verdict.innerHTML = `
      <b class="headline">${esc(stats.result)}</b>
      <span class="tally">${esc(t("vote.for", "支持"))} ${pub["支持"] || 0} ·
        ${esc(t("vote.against", "反对"))} ${pub["反对"] || 0} ·
        ${esc(t("vote.abstain", "弃权"))} ${pub["弃权"] || 0}</span>
      <span class="swing">${esc(t("vote.swing", "较私下表态"))} ${stats.swing > 0 ? "+" : ""}${stats.swing} ·
        ${stats.flips} ${esc(t("vote.flipped", "人改票"))}</span>
      ${run.campaign ? `<span class="campaign">${esc(t("vote.campaign_used", "宣传口径"))}：「${esc(run.campaign)}」</span>` : ""}
    `;

    $("#vBars").innerHTML = [
      stanceBar(t("vote.private", "私下"), stats.private || {}, stats.total),
      stanceBar(t("vote.public", "正式"), pub, stats.total),
    ].join("");

    const flips = run.flips || [];
    $("#vFlipsBox").hidden = !flips.length;
    $("#vFlips").innerHTML = flips
      .map((f) => `<li>
        <span class="who">${esc(f.name)}</span>
        <span class="move">${esc(f.from)} → <b>${esc(f.to)}</b></span>
        <span class="why">${esc(f.say)}</span>
      </li>`)
      .join("");

    $("#vSummaryBox").hidden = !run.summary;
    $("#vSummary").textContent = run.summary || "";

    $("#vCards").innerHTML = (run.voters || [])
      .map((v) => {
        const pubV = v.public || {};
        const priv = v.private || {};
        return `<article class="disaster-card${v.flipped ? " is-flipped" : ""}">
          <header>
            <span class="name">#${v.agent_id} ${esc(v.name)}</span>
            <span class="tag is-${stanceClass(pubV.stance)}">${esc(pubV.stance || "—")}</span>
          </header>
          <p class="detail">${esc(v.job || "")}${v.residence ? " · " + esc(v.residence) : ""}</p>
          ${pubV.say ? `<p class="say">「${esc(pubV.say)}」</p>` : ""}
          <footer>
            <span class="belief">${esc(t("vote.private", "私下"))} ${esc(priv.stance || "—")} → ${esc(pubV.stance || "—")}</span>
            <span class="help">${esc(t("vote.strength", "坚定度"))} ${pubV.strength == null ? "—" : pubV.strength}</span>
          </footer>
        </article>`;
      })
      .join("");
  }

  function stanceClass(stance) {
    if (stance === "支持") return "for";
    if (stance === "反对") return "against";
    if (stance === "弃权") return "abstain";
    return "other";
  }

  function stanceBar(label, counts, total) {
    const parts = STANCES.map((stance) => {
      const n = counts[stance] || 0;
      const pct = total ? Math.round((n / total) * 100) : 0;
      return n
        ? `<i class="is-${stanceClass(stance)}" style="width:${pct}%" title="${esc(stance)} ${n}">${n}</i>`
        : "";
    }).join("");
    return `<div class="vote-bar">
      <span class="label">${esc(label)}</span>
      <span class="track">${parts}</span>
      <span class="n">${esc(t("vote.avg_strength", "坚定度"))} ${counts.avg_strength == null ? "—" : counts.avg_strength}</span>
    </div>`;
  }

  function setStatus(message, isError) {
    const el = $("#vStatus");
    el.className = "disaster-status" + (isError ? " is-error" : "");
    el.textContent = message;
  }

  function setProgress(pct) {
    $("#vBar").style.width = pct + "%";
    $("#vPct").textContent = pct + "%";
  }

  async function loadHistory() {
    const ul = $("#vHistory");
    try {
      const resp = await fetch("/api/games/referendum/runs");
      const data = await resp.json();
      const runs = data.runs || [];
      if (!runs.length) {
        ul.innerHTML = `<li class="disaster-empty">${esc(t("vote.no_history", "还没有记录"))}</li>`;
        return;
      }
      ul.innerHTML = runs
        .map((r) => `<li>
          <button type="button" data-job="${esc(r.job_id)}">
            <span class="who">${esc((r.emoji || "") + " " + (r.motion || ""))}</span>
            <span class="meta">${esc(r.result || "")} · ${r.voters} ${esc(t("vote.voters", "人"))} · ${r.flips} ${esc(t("vote.flipped", "人改票"))}</span>
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
      const resp = await fetch("/api/games/referendum/jobs/" + encodeURIComponent(jobId));
      const rec = await resp.json();
      if (!resp.ok) throw new Error(rec.error || "HTTP " + resp.status);
      state.run = rec.result;
      render();
      setStatus(t("vote.viewing", "回看已完成的表决"));
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
