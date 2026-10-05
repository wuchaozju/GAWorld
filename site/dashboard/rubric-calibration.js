// Track R human anchor calibration — annotation page.
//
//   GET  /api/bench/calibration                     → the sets
//   GET  /api/bench/calibration/<set>?annotator=名   → tasks + this annotator's labels only
//   POST /api/bench/calibration/<set>/label          → one label (0 / 1 / 2 / null)
//   POST /api/bench/calibration/<set>/analyze        → α, ρ, QWK, gate
//   POST /api/bench/calibration/build                → a new set from the active world's run
//
// Two things the page holds to on purpose:
//
// * **Blind.** Tasks come without the key (which samples were corrupted, what
//   the rule scored) and without anyone else's labels; the result view only
//   opens once this annotator has labelled every task.
// * **One click saves.** Picking a score posts it and moves to the next
//   unlabelled task, so a half-finished session loses nothing.

(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
  const t = (key, fallback) => {
    if (typeof __ !== "function") return fallback;
    const value = __(key);
    return value && value !== key ? value : fallback;
  };
  const tf = (key, fallback, params) => {
    let text = t(key, fallback);
    Object.keys(params || {}).forEach((name) => { text = text.split("{" + name + "}").join(String(params[name])); });
    return text;
  };
  const NAME_KEY = "gaworld.calibration.annotator";

  const state = { sets: [], set: null, labels: {}, index: 0, setId: "", annotator: "" };

  async function api(path, options) {
    const settings = Object.assign({ headers: { "Content-Type": "application/json" } }, options || {});
    const response = await fetch(path, settings);
    let payload = {};
    try { payload = await response.json(); } catch (_) { payload = {}; }
    if (!response.ok) throw new Error(payload.error || ("HTTP " + response.status));
    return payload;
  }

  function showError(message) {
    const box = $("cError");
    box.hidden = !message;
    box.textContent = message || "";
  }

  function tasks() { return (state.set && state.set.tasks) || []; }
  function labelled(task) { return Object.prototype.hasOwnProperty.call(state.labels, task.task_id); }
  function doneCount() { return tasks().filter(labelled).length; }

  // ---------------------------------------------------------------- sets

  function renderSets() {
    const select = $("cSet");
    if (!state.sets.length) {
      select.innerHTML = "<option value=\"\">" + esc(t("calib.no_sets", "（还没有校准集）")) + "</option>";
      return;
    }
    select.innerHTML = state.sets.map((row) => {
      const gate = row.gate && row.gate.status ? " · " + row.gate.status : "";
      return "<option value=\"" + esc(row.set_id) + "\"" + (row.set_id === state.setId ? " selected" : "") + ">" +
        esc(row.set_id + " · " + row.n_tasks + t("calib.tasks_unit", " 题") + gate) + "</option>";
    }).join("");
  }

  function renderSetInfo() {
    const row = state.sets.find((item) => item.set_id === state.setId);
    if (!row) { $("cSetInfo").textContent = ""; return; }
    const dims = Object.keys(row.dims || {}).map((d) => d + "×" + row.dims[d]).join("，");
    const people = Object.keys(row.annotators || {}).map((n) => n + " " + row.annotators[n]).join("，") || "—";
    let text = tf("calib.set_info", "rubric {version}，按维度 {dims}；已标：{people}；judge：{judged}", {
      version: row.rubric_version, dims: dims, people: people,
      judged: row.judged ? t("calib.yes", "已打分") : t("calib.no", "未打分"),
    });
    if ((row.dims_without_data || []).length) {
      text += " " + tf("calib.missing_dims", "（这次运行没有 {dims} 的数据）", { dims: row.dims_without_data.join("、") });
    }
    $("cSetInfo").textContent = text;
  }

  async function loadSets() {
    const data = await api("/api/bench/calibration");
    state.sets = data.sets || [];
    if (!state.setId || !state.sets.some((row) => row.set_id === state.setId)) {
      state.setId = state.sets.length ? state.sets[0].set_id : "";
    }
    renderSets();
    renderSetInfo();
  }

  async function loadSet() {
    showError("");
    if (!state.setId) { state.set = null; render(); return; }
    const query = state.annotator ? "?annotator=" + encodeURIComponent(state.annotator) : "";
    const data = await api("/api/bench/calibration/" + encodeURIComponent(state.setId) + query);
    state.set = data.set;
    state.labels = data.labels || {};
    const open = tasks().findIndex((task) => !labelled(task));
    state.index = open >= 0 ? open : 0;
    $("cResult").hidden = true;
    render();
  }

  // ---------------------------------------------------------------- task

  function renderProgress() {
    const total = tasks().length;
    const done = doneCount();
    $("cProgress").textContent = done + " / " + total;
    $("cBar").style.width = (total ? Math.round(100 * done / total) : 0) + "%";
    $("cJump").innerHTML = tasks().map((task, i) =>
      "<button type=\"button\" data-jump=\"" + i + "\" class=\"" + (labelled(task) ? "is-done" : "") +
      (i === state.index ? " is-current" : "") + "\">" + (i + 1) + "</button>").join("");
    $("cAnalyze").disabled = !(total && done === total && state.annotator);
  }

  function render() {
    const list = tasks();
    const ready = list.length && state.annotator;
    $("cEmpty").hidden = !!ready;
    $("cTask").hidden = !ready;
    renderProgress();
    if (!ready) return;
    const task = list[state.index];
    const mine = state.labels[task.task_id];
    $("cTaskTitle").textContent = tf("calib.task_title", "{id} · {item}（{n} / {total}）",
      { id: task.task_id, item: task.item_id, n: state.index + 1, total: list.length });
    $("cProp").textContent = task.proposition;
    $("cScores").innerHTML = ["0", "1", "2"].map((score) =>
      "<button type=\"button\" data-score=\"" + score + "\" class=\"" +
      (mine && String(mine.score) === score ? "is-picked" : "") + "\"><b>" + score + "</b>" +
      esc((task.anchors || {})[score] || "") + "</button>").join("");
    $("cAbstain").classList.toggle("is-picked", !!mine && mine.score === null);
    $("cFailure").textContent = (task.failure_modes || []).length
      ? t("calib.failure_modes", "典型失败（命中应压低分数）：") + task.failure_modes.join("；") : "";
    $("cNote").value = (mine && mine.note) || "";
    const facts = task.facts && Object.keys(task.facts).length ? JSON.stringify(task.facts, null, 2) : "";
    $("cFactsBox").hidden = !facts;
    $("cFacts").textContent = facts;
    $("cSample").textContent = task.sample || "";
    $("cPrev").disabled = state.index === 0;
    $("cNext").disabled = state.index >= list.length - 1;
  }

  async function saveLabel(score) {
    const task = tasks()[state.index];
    if (!task) return;
    showError("");
    try {
      await api("/api/bench/calibration/" + encodeURIComponent(state.setId) + "/label", {
        method: "POST",
        body: JSON.stringify({ annotator: state.annotator, task_id: task.task_id, score: score, note: $("cNote").value }),
      });
      state.labels[task.task_id] = { score: score, note: $("cNote").value };
      const next = tasks().findIndex((item, i) => i > state.index && !labelled(item));
      const anyOpen = tasks().findIndex((item) => !labelled(item));
      state.index = next >= 0 ? next : (anyOpen >= 0 ? anyOpen : state.index);
      render();
    } catch (error) {
      showError(error.message);
    }
  }

  // ---------------------------------------------------------------- result

  function num(value) { return value == null ? "—" : Number(value).toFixed(2); }

  function renderResult(a) {
    const gate = a.gate || {};
    const summary = a.agreement_summary || {};
    const judge = summary.judge || {};
    const rule = summary.rule || {};
    const th = a.thresholds || {};
    const check = a.ablation_check || {};
    const rows = Object.keys(a.items || {}).map((iid) => {
      const it = a.items[iid];
      return "<tr><td>" + esc(iid) + "</td><td>" + esc(it.checker) + "</td><td class=\"num\">" + it.n_tasks +
        "</td><td class=\"num\">" + it.n_disagree + "/" + it.n_double + "</td><td class=\"num\">" + num(it.human_mean) +
        "</td><td class=\"num\">" + num(it.machine_mean) + "</td></tr>";
    }).join("");
    const queue = (a.rewrite_queue || []).map((row) =>
      "<li><b>" + esc(row.item_id) + "</b> " + esc(row.reasons.join("；")) + "</li>").join("");
    $("cResult").innerHTML = [
      "<p class=\"calib-result-gate " + (gate.status === "ok" ? "is-ok" : "is-bad") + "\">" +
        esc(t("calib.result_gate", "结论") + "：" + gate.status) + "</p>",
      (gate.reasons || []).length ? "<p class=\"calib-hint\">" + esc(gate.reasons.join("；")) + "</p>" : "",
      "<table class=\"calib-table\"><thead><tr><th>" + esc(t("calib.metric", "指标")) + "</th><th>" +
        esc(t("calib.value", "值")) + "</th><th>" + esc(t("calib.threshold", "门槛")) + "</th></tr></thead><tbody>",
      "<tr><td>" + esc(t("calib.human_alpha", "人-人 α（序数）")) + "</td><td class=\"num\">" + num(a.human_alpha) +
        "</td><td>≥ " + th.human_alpha_min + "</td></tr>",
      "<tr><td>" + esc(t("calib.judge_rho", "人-judge Spearman ρ")) + "</td><td class=\"num\">" + num(judge.spearman) +
        "</td><td>≥ " + th.human_judge_min + "</td></tr>",
      "<tr><td>" + esc(t("calib.judge_qwk", "人-judge QWK")) + "</td><td class=\"num\">" + num(judge.qwk) +
        "</td><td>≥ " + th.human_judge_min + "</td></tr>",
      "<tr><td>" + esc(t("calib.rule_agree", "人-规则 ρ / QWK（只报告）")) + "</td><td class=\"num\">" + num(rule.spearman) +
        " / " + num(rule.qwk) + "</td><td>—</td></tr>",
      "</tbody></table>",
      "<p class=\"calib-hint\">" + esc(tf("calib.ablation_check",
        "真实样本人均 {real}，被破坏样本 {ablated}：差距很小说明连人也看不出破坏，是破坏算子的问题。",
        { real: num(check.human_mean_real), ablated: num(check.human_mean_ablated) })) + "</p>",
      "<table class=\"calib-table\"><thead><tr><th>item</th><th>checker</th><th>" + esc(t("calib.tasks", "任务")) +
        "</th><th>" + esc(t("calib.disagree", "两人分歧")) + "</th><th>" + esc(t("calib.human_mean", "人均")) +
        "</th><th>" + esc(t("calib.machine_mean", "机器均")) + "</th></tr></thead><tbody>" + rows + "</tbody></table>",
      queue ? "<h4>" + esc(t("calib.rewrite", "重写队列")) + "</h4><ul>" + queue + "</ul>" : "",
    ].join("");
    $("cResult").hidden = false;
    $("cTask").hidden = true;
  }

  async function analyze() {
    showError("");
    try {
      renderResult(await api("/api/bench/calibration/" + encodeURIComponent(state.setId) + "/analyze", { method: "POST" }));
      await loadSets();
    } catch (error) { showError(error.message); }
  }

  async function build() {
    showError("");
    $("cBuild").disabled = true;
    try {
      const made = await api("/api/bench/calibration/build", { method: "POST", body: JSON.stringify({}) });
      state.setId = made.set_id;
      await loadSets();
      await loadSet();
    } catch (error) {
      showError(error.message);
    } finally {
      $("cBuild").disabled = false;
    }
  }

  // ---------------------------------------------------------------- wiring

  function bind() {
    $("cSet").addEventListener("change", (event) => {
      state.setId = event.target.value;
      renderSetInfo();
      loadSet().catch((error) => showError(error.message));
    });
    $("cAnnotator").addEventListener("change", (event) => {
      state.annotator = event.target.value.trim();
      try { localStorage.setItem(NAME_KEY, state.annotator); } catch (_) { /* private mode */ }
      loadSet().catch((error) => showError(error.message));
    });
    $("cScores").addEventListener("click", (event) => {
      const button = event.target.closest("[data-score]");
      if (button) saveLabel(Number(button.getAttribute("data-score")));
    });
    $("cAbstain").addEventListener("click", () => saveLabel(null));
    $("cJump").addEventListener("click", (event) => {
      const button = event.target.closest("[data-jump]");
      if (!button) return;
      state.index = Number(button.getAttribute("data-jump"));
      $("cResult").hidden = true;
      render();
    });
    $("cPrev").addEventListener("click", () => { state.index = Math.max(0, state.index - 1); render(); });
    $("cNext").addEventListener("click", () => { state.index = Math.min(tasks().length - 1, state.index + 1); render(); });
    $("cNextOpen").addEventListener("click", () => {
      const open = tasks().findIndex((task) => !labelled(task));
      if (open >= 0) { state.index = open; render(); }
    });
    $("cAnalyze").addEventListener("click", analyze);
    $("cBuild").addEventListener("click", build);
  }

  async function boot() {
    bind();
    try { state.annotator = (localStorage.getItem(NAME_KEY) || "").trim(); } catch (_) { state.annotator = ""; }
    $("cAnnotator").value = state.annotator;
    try {
      await loadSets();
      await loadSet();
    } catch (error) {
      showError(error.message);
    }
  }

  document.addEventListener("locale-changed", () => { renderSets(); renderSetInfo(); render(); });

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { boot: boot, __state: state, renderResult: renderResult };
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
