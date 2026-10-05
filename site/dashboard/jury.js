// 陪审团 (Jury Deliberation) — front-end controller.
//
// One server call carries the trial:
//
//   POST /api/games/jury/run → {job_id}; poll /jobs/<id> for progress, then
//        draw the verdict card, the per-round transcript, and the anonymous ballots.
//
// Two things the page does on its own:
//
// * **The roster is a checkbox, not a tri-state.** A jury is one group, not
//   two teams — duplicating the duel/rumor picker here would invite the
//   "甲 / 乙" mistake and force a side pick that the game does not use.
// * **Editing a built-in case's facts turns it into a custom case.** The
//   backend takes the case from the bank entry verbatim, so a player who
//   rewrites the textarea has to be sent through the custom path or their
//   edit is silently ignored.

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
    jurors: new Set(),     // agent_id
    cases: [],
    questions: [],
    minJurors: 3,
    maxJurors: 5,
    defaultRounds: 3,
    maxRounds: 5,
    run: null,
    jobId: null,
    jobTimer: null,
  };

  const exporter = GAWorldGameExport.attach(() => state.run && {
    game: "jury",
    label: (state.run.case || {}).title,
    markdown: GAWorldGameExport.jury(state.run),
  });

  async function init() {
    $("#jRunBtn").addEventListener("click", startRun);
    $("#jPickRandom").addEventListener("click", pickRandom);
    $("#jPickNone").addEventListener("click", () => { state.jurors.clear(); renderAgents(); renderCost(); });
    $("#jCity").addEventListener("change", () => {
      state.city = $("#jCity").value;
      state.jurors.clear();
      loadAgents();
    });
    $("#jCase").addEventListener("change", renderCase);
    $("#jRounds").addEventListener("input", renderCost);
    $("#jQuestion").addEventListener("change", renderQuestion);
    await Promise.all([loadCities().then(loadAgents), loadCatalogue()]);
    loadHistory();
  }

  // -- catalogue ----------------------------------------------------------
  async function loadCities() {
    const sel = $("#jCity");
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
    const caseSel = $("#jCase");
    const questionSel = $("#jQuestion");
    try {
      const resp = await fetch("/api/games/jury/catalogue");
      const data = await resp.json();
      state.cases = data.cases || [];
      state.questions = data.questions || [];
      state.minJurors = data.min_jurors || 3;
      state.maxJurors = data.max_jurors || 5;
      state.defaultRounds = data.default_rounds || 3;
      state.maxRounds = data.max_rounds || 5;
      caseSel.innerHTML = state.cases
        .map((c) => `<option value="${esc(c.id)}">${esc((c.emoji || "") + " " + c.title)}</option>`)
        .join("") + `<option value="${CUSTOM}">✍️ ${esc(t("jury.custom_option", "自己写一个…"))}</option>`;
      questionSel.innerHTML = state.questions
        .map((q) => `<option value="${esc(q.key)}">${esc(q.label)}</option>`)
        .join("");
      $("#jRounds").max = state.maxRounds;
      $("#jRounds").value = state.defaultRounds;
      renderCase();
      renderQuestion();
    } catch (err) {
      caseSel.innerHTML = `<option value="">${esc(String(err))}</option>`;
    }
  }

  function currentCase() {
    return state.cases.find((c) => c.id === $("#jCase").value) || null;
  }

  function currentQuestion() {
    return state.questions.find((q) => q.key === $("#jQuestion").value) || null;
  }

  function renderCase() {
    const custom = $("#jCase").value === CUSTOM;
    $("#jCustomBlock").hidden = !custom;
    const c = currentCase();
    if (custom) {
      $("#jCaseText").textContent = t("jury.custom_hint", "自己写一个:把案情写清楚,被告怎么说的、原告怎么说的都写上。");
      $("#jCustomDefendants").value = $("#jCustomDefendants").value || "";
      $("#jCustomFacts").value = $("#jCustomFacts").value || "";
    } else {
      $("#jCaseText").textContent = c ? (c.defendants + " — " + c.facts) : "";
      $("#jCustomDefendants").value = "";
      $("#jCustomFacts").value = "";
    }
    renderCost();
  }

  function renderQuestion() {
    const q = currentQuestion();
    $("#jQuestionText").textContent = q ? q.text : "";
  }

  function renderCost() {
    const rounds = Math.max(1, parseInt($("#jRounds").value, 10) || 1);
    const jurors = state.jurors.size;
    const calls = rounds * jurors + 1;
    $("#jCost").textContent = t("jury.cost_prefix", "开销:轮数 × 陪审人数 + 1 次模型调用 = ") + calls;
  }

  // -- roster -------------------------------------------------------------
  async function loadAgents() {
    const list = $("#jAgents");
    if (state.city === null) return;
    list.innerHTML = `<li class="jury-empty">${esc(t("jury.loading", "加载中…"))}</li>`;
    try {
      const resp = await fetch("/api/games/agents?city=" + encodeURIComponent(state.city));
      const data = await resp.json();
      state.agents = data.agents || [];
      renderAgents();
      renderCost();
    } catch (err) {
      list.innerHTML = `<li class="jury-empty is-error">${esc(String(err))}</li>`;
    }
  }

  function renderAgents() {
    const list = $("#jAgents");
    if (!state.agents.length) {
      list.innerHTML = `<li class="jury-empty">${esc(t("jury.no_agents", "这座城市暂无居民"))}</li>`;
      return;
    }
    list.innerHTML = state.agents.map((a) => {
      const picked = state.jurors.has(a.id);
      const meta = [a.age ? a.age + "岁" : "", a.job || ""].filter(Boolean).join(" · ");
      return `<li class="${picked ? "is-picked" : ""}">
        <label>
          <input type="checkbox" data-agent="${a.id}" ${picked ? "checked" : ""} />
          <span class="who">#${a.id} ${esc(a.name)}<span class="meta"> ${esc(meta)}</span></span>
        </label>
      </li>`;
    }).join("");
    $$("input[data-agent]", list).forEach((cb) => {
      cb.addEventListener("change", () => {
        const id = parseInt(cb.getAttribute("data-agent"), 10);
        if (cb.checked) {
          if (state.jurors.size >= state.maxJurors) {
            cb.checked = false;
            setStatus(t("jury.jury_full", "陪审团最多 ") + state.maxJurors + t("jury.jury_full_tail", " 人"), true);
            return;
          }
          state.jurors.add(id);
        } else {
          state.jurors.delete(id);
        }
        renderAgents();
        renderCost();
      });
    });
    $("#jCount").textContent = state.jurors.size;
  }

  function pickRandom() {
    const pool = state.agents.slice();
    for (let i = pool.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [pool[i], pool[j]] = [pool[j], pool[i]];
    }
    const take = Math.min(state.minJurors + 2, state.maxJurors, pool.length);
    state.jurors.clear();
    pool.slice(0, take).forEach((a) => state.jurors.add(a.id));
    renderAgents();
    renderCost();
  }

  // -- run ----------------------------------------------------------------
  function factsEdited(c) {
    if (!c) return true;
    return $("#jCustomFacts").value.trim() !== c.facts
      || $("#jCustomDefendants").value.trim() !== c.defendants
      || $("#jCustomTitle").value.trim() !== c.title;
  }

  async function startRun() {
    const jurorIds = Array.from(state.jurors);
    if (jurorIds.length < state.minJurors) {
      return setStatus(t("jury.need_jurors", "陪审员至少 ") + state.minJurors + t("jury.need_jurors_tail", " 人"), true);
    }
    if (jurorIds.length > state.maxJurors) {
      return setStatus(t("jury.too_many", "陪审员最多 ") + state.maxJurors + t("jury.need_jurors_tail", " 人"), true);
    }

    const isCustom = $("#jCase").value === CUSTOM;
    const c = currentCase();
    const body = {
      city: state.city,
      agent_ids: jurorIds,
      rounds: Math.max(1, parseInt($("#jRounds").value, 10) || state.defaultRounds),
      question_key: $("#jQuestion").value || (state.questions[0] && state.questions[0].key) || "",
      case_id: isCustom ? "" : $("#jCase").value,
    };
    if (isCustom || factsEdited(c)) {
      body.case_id = "";
      const facts = isCustom
        ? $("#jCustomFacts").value.trim()
        : (c ? c.facts : "");
      const defendants = isCustom
        ? $("#jCustomDefendants").value.trim()
        : (c ? c.defendants : "");
      const title = isCustom
        ? $("#jCustomTitle").value.trim()
        : (c ? c.title : "");
      if (!facts) return setStatus(t("jury.need_facts", "把案情写清楚再开庭。"), true);
      body.custom = { title, defendants, facts };
    }

    $("#jRunBtn").disabled = true;
    setProgress(0);
    setStatus(t("jury.running", "开庭…"));
    try {
      const resp = await fetch("/api/games/jury/run", {
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
      $("#jRunBtn").disabled = false;
    }
  }

  function pollJob() {
    if (!state.jobId) return;
    clearInterval(state.jobTimer);
    state.jobTimer = setInterval(async () => {
      try {
        const resp = await fetch("/api/games/jury/jobs/" + encodeURIComponent(state.jobId));
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const rec = await resp.json();
        setProgress(Math.round((rec.progress || 0) * 100));
        if (rec.status === "running") {
          setStatus(rec.message || t("jury.running", "开庭…"));
          return;
        }
        stopPolling();
        if (rec.status === "done") {
          state.run = rec.result;
          render();
          setStatus(t("jury.done", "已宣判"));
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
    $("#jRunBtn").disabled = false;
  }

  // -- rendering ----------------------------------------------------------
  function render() {
    const run = state.run;
    $("#jIdle").hidden = !!run;
    $("#jResult").hidden = !run;
    exporter.sync();
    if (!run) return;
    const c = run.case || {};
    $("#jTitle").textContent = (c.emoji || "⚖️") + " " + (c.title || "");
    renderVerdict(run);
    renderStats(run);
    renderRounds(run);
    renderBallots(run);
  }

  function renderVerdict(run) {
    const tally = run.tally || {};
    const stats = run.stats || {};
    const jurors = run.jurors || [];
    const verdict = tally.verdict || "无罪";
    const guilty = tally.guilty || 0;
    const notGuilty = tally.not_guilty || 0;

    const verdictClass = verdict === "有罪" ? "is-guilty" : "is-not";
    $("#jVerdict").className = "jury-verdict " + verdictClass;
    $("#jVerdict").innerHTML = `
      <div class="jury-tally">
        <span class="side is-not">
          <b>${esc(t("jury.not_guilty", "无罪"))}</b><i>${notGuilty}</i>
        </span>
        <span class="vs">vs</span>
        <span class="side is-guilty">
          <b>${esc(t("jury.guilty", "有罪"))}</b><i>${guilty}</i>
        </span>
      </div>
      <h4>${esc(verdict)}${esc(t("jury.verdict_tail", "  " + jurors.length + " 人陪审"))}</h4>
      <p>${esc(t("jury.spread", "意见分歧度:"))} <b>${stats.spread || 0}</b> / 100
         · ${esc(t("jury.median_conf", "中位信心:"))} <b>${stats.median_confidence || 0}</b></p>
    `;
  }

  function renderStats(run) {
    const stats = run.stats || {};
    const question = run.question || {};
    const cells = [
      [t("jury.stat_jurors", "陪审人数"), stats.jurors || 0],
      [t("jury.stat_guilty", "有罪票"), stats.guilty || 0],
      [t("jury.stat_not", "无罪票"), stats.not_guilty || 0],
      [t("jury.stat_conf_guilty", "坚决有罪"), stats.confident_guilty || 0],
      [t("jury.stat_conf_not", "坚决无罪"), stats.confident_not_guilty || 0],
      [t("jury.stat_spread", "分歧度"), (stats.spread || 0) + " / 100"],
    ];
    $("#jStats").innerHTML = `
      <div class="jury-stats-head">
        <h4>${esc(t("jury.stat_question", "第二个问题:"))} ${esc((question.label || ""))}</h4>
        <p class="jury-hint">${esc(question.text || "")}</p>
      </div>
      <div class="jury-metrics">
        ${cells.map(([label, value]) => `
          <div class="jury-metric">
            <span class="label">${esc(label)}</span>
            <b>${esc(value)}</b>
          </div>
        `).join("")}
      </div>
    `;
  }

  function renderRounds(run) {
    const logs = run.rounds_log || [];
    if (!logs.length) {
      $("#jRounds").innerHTML = "";
      return;
    }
    $("#jRounds").innerHTML = `
      <h4>${esc(t("jury.rounds_title", "庭审记录"))}</h4>
      ${logs.map((log) => `
        <section class="jury-round">
          <header>
            <b>${esc(t("jury.round_n", "第 N 轮").replace("N", String((log.round || 0) + 1)))}</b>
          </header>
          <div class="jury-round-body">
            ${(log.speeches || []).map((sp) => `
                <div class="jury-speech">
                  <span class="who">#${esc(sp.agent_id)} ${esc(sp.name)}</span>
                  <p>${esc(sp.text || "")}</p>
                </div>
              `).join("")}
            </div>
          </section>
      `).join("")}
    `;
  }

  function renderBallots(run) {
    const tally = run.tally || {};
    const jurors = run.jurors || [];
    const supporting = tally.supporting || [];
    const dissenting = tally.dissenting || [];
    const verdict = tally.verdict || "无罪";
    $("#jBallots").innerHTML = `
      <h4>${esc(t("jury.ballots_title", "匿名投票"))}</h4>
      <p class="jury-hint">${esc(t("jury.ballots_hint", "下面是每个陪审员的最终选票。陪审员 ID 故意不暴露,只看立场。" ))}</p>
      <div class="jury-ballots-grid">
        ${jurors.map((j, i) => {
          const vote = (j.verdict || "无罪") === "有罪" ? "is-guilty" : "is-not";
          const confidence = j.confidence || 0;
          const qClass = (confidence >= 70)
            ? "rep-conf"
            : (confidence >= 40 ? "rep-sure" : "rep-weak");
          const dim = confidence;
          return `
            <article class="jury-ballot ${vote}">
              <header>
                <span class="ballot-id">${esc(t("jury.ballot_n", "陪审员 #N").replace("N", String(i + 1)))}</span>
                <span class="ballot-vote">${esc(j.verdict || "无罪")}</span>
              </header>
              <p class="ballot-meta">${esc(j.name || "")} · ${esc(j.job || "")}</p>
              <div class="ballot-meter ${qClass}"><i style="width:${dim}%"></i></div>
              <p class="ballot-confidence">${dim} / 100</p>
              <blockquote>${esc(j.quote || "（没有写理由）")}</blockquote>
              ${j.secondary_value
                ? `<p class="ballot-secondary"><b>${esc(t("jury.secondary", "量刑"))}</b>: ${esc(j.secondary_value)}</p>`
                : ""}
            </article>
          `;
        }).join("")}
      </div>
      <div class="jury-tally-rows">
        <div class="jury-row is-support">
          <span class="label">${esc(t("jury.supporting", verdict)}</span>
          <ul>${supporting.map((s) => `<li><b>${esc(s.name)}</b>: ${esc(s.quote || "")}</li>`).join("")}</ul>
        </div>
        ${dissenting.length ? `
          <div class="jury-row is-dissent">
            <span class="label">${esc(t("jury.dissenting", "反对方"))}</span>
            <ul>${dissenting.map((s) => `<li><b>${esc(s.name)}</b>: ${esc(s.quote || "")}</li>`).join("")}</ul>
          </div>
        ` : ""}
      </div>
    `;
  }

  function setProgress(p) {
    $("#jBar").style.width = p + "%";
    $("#jPct").textContent = p + "%";
  }

  function setStatus(text, isError) {
    const el = $("#jStatus");
    el.textContent = text;
    el.className = "jury-status" + (isError ? " is-error" : "");
  }

  // -- history ------------------------------------------------------------
  async function loadHistory() {
    const ul = $("#jHistory");
    if (!ul) return;
    try {
      const resp = await fetch("/api/games/jury/runs");
      const data = await resp.json();
      const runs = data.runs || [];
      if (!runs.length) {
        ul.innerHTML = `<li class="jury-empty">${esc(t("jury.no_history", "尚无记录"))}</li>`;
        return;
      }
      ul.innerHTML = runs.slice(0, 5).map((row) => {
        const title = `${row.emoji || ""} ${esc(row.case_title || "未命名")}`;
        const meta = `${row.guilty || 0} 有罪 / ${row.not_guilty || 0} 无罪 · 分歧 ${row.spread || 0}`;
        return `<li><button type="button" data-job="${esc(row.job_id)}">
          <span class="who">${title}</span>
          <span class="meta">${esc(row.verdict || "—")} · ${esc(meta)}</span>
        </button></li>`;
      }).join("");
      $$("button[data-job]", ul).forEach((btn) => {
        btn.addEventListener("click", async () => {
          const jobId = btn.getAttribute("data-job");
          try {
            const resp = await fetch("/api/games/jury/jobs/" + encodeURIComponent(jobId));
            const rec = await resp.json();
            if (rec && rec.status === "done" && rec.result) {
              state.run = rec.result;
              render();
              setStatus(t("jury.loaded", "已加载庭审记录"));
            }
          } catch (err) { /* ignore */ }
        });
      });
    } catch (err) { /* ignore */ }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();