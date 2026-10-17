/* Research batches: model × city × independent run, using ordinary studies. */
(function (root) {
  "use strict";
  function esc(value) {
    return String(value == null ? "" : value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function t(key, fallback) {
    if (!root || typeof root.__ !== "function") return fallback;
    var found = root.__("research.batch_" + key);
    return found && found !== "research.batch_" + key ? found : fallback;
  }
  function counts(models, cities, repeats, conditions) { return { runs: models * cities * repeats, worlds: models * cities * repeats * conditions }; }
  function selection(previous, checked, current) {
    var old = new Set(previous);
    return Array.from(current).filter(function (id) { return !old.has(id) || checked.has(id); });
  }
  function num(value) { return value == null ? "—" : Number(value).toLocaleString(undefined, { maximumFractionDigits: 4 }); }
  function table(headers, rows) {
    return '<div class="rw-table-scroll"><table class="rw-table"><thead><tr>' + headers.map(function (h) { return "<th>" + esc(h) + "</th>"; }).join("") +
      "</tr></thead><tbody>" + rows.map(function (row) { return "<tr>" + row.map(function (v) { return "<td>" + esc(v) + "</td>"; }).join("") + "</tr>"; }).join("") + "</tbody></table></div>";
  }
  function comparisonHTML(data) {
    var c = data.counts || {};
    var html = '<div class="rb-summary">' + [
      [t("planned", "计划运行"), c.planned], [t("selected", "已选"), c.selected], [t("done", "已完成"), c.done],
      [t("failed", "失败 / 中断"), c.failed], [t("pending", "待完成"), c.pending],
    ].map(function (item) { return '<div><span>' + esc(item[0]) + "</span><strong>" + esc(item[1] == null ? 0 : item[1]) + "</strong></div>"; }).join("") + "</div>";
    html += table([t("model", "模型"), t("city", "城市"), t("hypothesis", "假设"), t("version", "模式 / 版本"),
      t("valid", "有效运行"), t("effect", "平均效应"), t("sd", "标准差"), "95% CI", t("direction", "方向一致率")],
    (data.groups || []).map(function (g) { return [g.provider + " / " + g.model, g.city || t("current", "当前世界"), g.hypothesis,
      (g.mode || "") + " / " + num(g.epoch), g.n + " · " + g.unique_seeds + " " + t("seeds", "种子"), num(g.mean), num(g.sd),
      g.ci95 ? g.ci95.map(num).join(" ~ ") : "—", Math.round(100 * g.direction_rate) + "%"]; }));
    if (!(data.groups || []).length) html += '<p class="rw-hint">' + esc(t("no_results", "尚无可纳入统计的完整运行。")) + "</p>";
    if ((data.contrasts || []).length) html += "<h4>" + esc(t("contrasts", "模型 / 城市差异（右侧减左侧）")) + "</h4>" + table(
      [t("dimension", "维度"), t("left", "左侧"), t("right", "右侧"), t("context", "比较范围"), t("hypothesis", "假设"), t("difference", "效应之差"), "95% CI"],
      data.contrasts.map(function (c) { return [c.kind, c.left, c.right, c.city || c.provider || "", c.hypothesis, num(c.difference), c.ci95 ? c.ci95.map(num).join(" ~ ") : "—"]; }));
    if ((data.runtime_metrics || []).length) html += "<h4>" + esc(t("reliability", "运行可靠性与实测请求")) + "</h4>" + table(
      [t("model", "模型"), t("city", "城市"), t("planned", "计划运行"), t("task_failure", "任务失败率"), t("requests", "实测请求"), t("request_failure", "请求失败率")],
      data.runtime_metrics.map(function (m) { return [m.provider, m.city || t("current", "当前世界"), m.planned,
        Math.round(100 * m.task_failure_rate) + "%", num(m.requests), m.request_failure_rate == null ? "—" : Math.round(100 * m.request_failure_rate) + "%"]; }));
    html += '<p class="rw-hint rb-note">' + esc(data.note || "") + "</p>";
    if ((data.issues || []).length) html += "<details><summary>" + esc(t("issues", "排除与缺失")) + " (" + data.issues.length + ")</summary><ul>" +
      data.issues.map(function (i) { return "<li>" + esc(i.cell_id + ": " + i.reason) + "</li>"; }).join("") + "</ul></details>";
    return html;
  }
  var exports = { counts: counts, selection: selection, comparisonHTML: comparisonHTML };
  if (typeof module !== "undefined") module.exports = exports;
  if (!root || !root.document) return;
  var document = root.document, prefix = "/api/research/batches";
  var source = null, context = null, current = null, selected = new Set(), known = [], request = 0, busy = false;
  function $(id) { return document.getElementById(id); }
  function api(method, path, body) {
    return fetch(path, { method: method, credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: method === "POST" ? JSON.stringify(body || {}) : undefined }).then(function (response) {
      return response.json().then(function (data) { if (!response.ok) throw new Error(data.error || response.statusText); return data; });
    });
  }
  function error(err) { $("rwBatchError").textContent = err ? err.message : ""; }
  function checked(name) { return Array.from(document.querySelectorAll('input[name="' + name + '"]:checked')).map(function (el) { return el.value; }); }
  function button(id, text, disabled, ghost) { return '<button type="button" class="btn tiny' + (ghost ? " ghost" : "") + '" id="' + id + '"' + (disabled || busy ? " disabled" : "") + ">" + esc(text) + "</button>"; }
  function preview() {
    if (!source || !$("rbRepeats")) return;
    var c = counts(checked("rbModel").length, checked("rbCity").length, Number($("rbRepeats").value), (source.protocol.conditions || []).length);
    $("rbPreview").textContent = c.runs + " " + t("runs", "次完整实验") + " · " + c.worlds + " " + t("worlds", "个条件世界");
  }
  function renderForm() {
    var host = $("rwBatchForm");
    if (!context || !source) { host.innerHTML = '<p class="rw-hint">' + esc(t("choose_study", "先打开一份研究协议，即可创建多模型、多城市和重复运行批次。")) + "</p>"; return; }
    var providers = (context.providers || []).filter(function (p) { return p.name; });
    host.innerHTML = '<p class="rw-hint">' + esc(t("source", "来源研究") + ": " + source.title) + '</p><div class="rb-grid"><fieldset><legend>' + esc(t("models", "居民仿真模型（可多选）")) + '</legend><div class="rb-choices">' +
      providers.map(function (p, i) { return '<label><input type="checkbox" name="rbModel" value="' + esc(p.name) + '"' + ((source.protocol.sim_provider ? source.protocol.sim_provider === p.name : i === 0) ? " checked" : "") + ' /> <span>' + esc(p.label || p.name) + "</span></label>"; }).join("") +
      '</div></fieldset><fieldset><legend>' + esc(t("cities", "城市（可多选）")) + '</legend><div class="rb-choices"><label><input type="checkbox" name="rbCity" value="" checked /> <span>' + esc(t("current", "当前世界")) + "</span></label>" +
      (context.cities || []).map(function (c) { return '<label><input type="checkbox" name="rbCity" value="' + esc(c.slug) + '" /> <span>' + esc(c.display_name || c.name || c.slug) + "</span></label>"; }).join("") + '</div></fieldset></div><div class="rb-knobs">' +
      '<label class="rw-field"><span>' + esc(t("repeat", "每个组合运行次数")) + '</span><input id="rbRepeats" type="number" min="1" max="100" value="3" /></label>' +
      '<label class="rw-field"><span>' + esc(t("seed", "起始种子")) + '</span><input id="rbSeed" type="number" min="0" value="42" /></label>' +
      '<label class="rw-field"><span>' + esc(t("strategy", "种子策略")) + '</span><select id="rbStrategy"><option value="vary">' + esc(t("vary", "不同种子 · 稳健性")) + '</option><option value="fixed">' + esc(t("fixed", "固定种子 · 输出波动")) + '</option></select></label>' +
      '<label class="rw-field"><span>' + esc(t("sample", "每城居民数（0 = 全体）")) + '</span><input id="rbSample" type="number" min="0" value="' + esc((source.protocol.sample.agent_ids || []).length) + '" /></label></div>' +
      '<div class="rw-row"><strong id="rbPreview"></strong>' + button("rbCreate", t("create", "生成批次与预算"), !providers.length, false) + '</div><p class="rw-hint">' + esc(t("create_hint", "生成批次会冻结城市与人口，不调用模型；每次运行包含协议中的全部对照与处理条件。")) + "</p>";
    host.querySelectorAll("input,select").forEach(function (el) { el.addEventListener("change", preview); });
    $("rbCreate").addEventListener("click", function () {
      if (busy) return;
      busy = true; this.disabled = true; error(null);
      api("POST", prefix, { study_id: source.id, providers: checked("rbModel"), cities: checked("rbCity"),
        repeats: Number($("rbRepeats").value), seed: Number($("rbSeed").value), seed_strategy: $("rbStrategy").value,
        sample_size: Number($("rbSample").value) }).then(function (batch) { known = []; selected.clear(); current = batch; return openBatch(batch.id); })
        .then(history).catch(error).finally(function () { busy = false; if ($("rbCreate")) $("rbCreate").disabled = false; renderViewer(); });
    });
    preview();
  }
  function saveFile(filename, data, mime) {
    var url = URL.createObjectURL(new Blob([data], { type: mime })), link = document.createElement("a");
    link.href = url; link.download = filename; document.body.appendChild(link); link.click(); link.remove(); setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }
  function download(kind) {
    if (!current) return;
    if (kind === "json") { saveFile(current.id + ".json", JSON.stringify(current, null, 2), "application/json"); return; }
    api("GET", prefix + "/" + current.id + "/" + kind).then(function (data) {
      if (kind === "export") { var raw = atob(data.data), bytes = new Uint8Array(raw.length); for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i); saveFile(data.filename, bytes, data.mime); }
      else saveFile(data.filename, data.markdown, "text/markdown;charset=utf-8");
    }).catch(error);
  }
  function action(name, payload) {
    if (busy || !current) return;
    busy = true; error(null); renderViewer();
    api("POST", prefix + "/" + current.id + "/" + name, payload || {}).then(function () { return openBatch(current.id); })
      .then(history).catch(error).finally(function () { busy = false; renderViewer(); });
  }
  function renderViewer() {
    var host = $("rwBatchViewer");
    if (!current) { host.innerHTML = ""; return; }
    var live = ["running", "paused", "stopping"].includes(current.status), c = current.preflight || {}, timing = current.timing || {};
    var pending = current.cells.some(function (c) { return ["pending", "cancelled", "queued"].includes(c.status); });
    var failed = current.cells.some(function (c) { return ["failed", "interrupted", "stopped"].includes(c.status); });
    var active = document.activeElement, focused = host.contains(active) ? (active.id || active.getAttribute("data-cell")) : null;
    var oldScroll = host.querySelector(".rb-tasks"), scrollLeft = oldScroll ? oldScroll.scrollLeft : 0;
    host.innerHTML = '<div class="rb-batch-head"><div><span class="rw-badge">' + esc(current.status) + '</span><h4>' + esc(current.title) + '</h4><p class="rw-hint">' + esc(current.id) + '</p></div><div class="rw-actions">' +
      (live ? button("rbPause", current.status === "paused" ? t("resume", "继续") : t("pause", "暂停"), current.status === "stopping", true) + button("rbStop", t("stop", "停止"), current.status === "stopping", true) :
        button("rbRun", current.status === "draft" ? t("approve", "批准并运行批次") : t("continue", "继续剩余任务"), !c.ok || !pending, false) + (failed ? button("rbRetry", t("retry", "重试失败任务"), !c.ok, true) : "")) +
      button("rbPython", t("python", "下载 Python 实验包"), false, true) + button("rbReport", t("report", "下载报告"), false, true) + button("rbJSON", "JSON", false, true) + '</div></div>' +
      '<p class="rw-hint">' + esc(t("budget", "预计调用") + ": " + num(c.estimated_calls) + " / " + num(c.limit) + " · " + t("worlds", "条件世界") + ": " + num(c.worlds)) + '</p>' +
      (c.errors || []).map(function (e) { return '<p class="rw-warn">' + esc(e) + "</p>"; }).join("") +
      (c.warnings || []).map(function (e) { return '<p class="rw-hint rw-warn">' + esc(e) + "</p>"; }).join("") +
      ((current.protocol.execution_mode === "daily_brief" || current.protocol.purpose === "exploratory") ? '<p class="rw-hint rw-warn">' + esc(t("exploratory", "近似探索：重复一致性不等于正式假设验证或现实效力。")) + "</p>" : "") +
      '<progress class="rb-progress" max="1" value="' + Number(current.progress || 0) + '"></progress><p class="rw-hint">' +
      esc(t("progress", "进度") + ": " + Math.round(100 * (current.progress || 0)) + "% · " + t("active_time", "运行秒数") + ": " + num(timing.elapsed_seconds) + " · " + t("eta", "预计剩余秒数") + ": " + num(timing.remaining_seconds)) + '</p>' +
      '<div class="rb-tasks rw-table-scroll"><table class="rw-table"><thead><tr><th><input id="rbSelectAll" type="checkbox" aria-label="' + esc(t("select_all", "选择全部运行")) + '"' + (selected.size === current.cells.length ? " checked" : "") + ' /></th>' +
      [t("model", "模型"), t("city", "城市"), t("repeat", "重复"), t("seed", "种子"), t("status", "状态 / 实测调用"), t("record", "运行记录")].map(function (h) { return "<th>" + esc(h) + "</th>"; }).join("") + "</tr></thead><tbody>" +
      current.cells.map(function (cell) { var stats = (cell.result || {}).telemetry || (cell.run_status || {}).telemetry || {}; return '<tr><td><input type="checkbox" data-cell="' + esc(cell.id) + '" aria-label="' + esc(cell.id) + '"' + (selected.has(cell.id) ? " checked" : "") + ' /></td><td>' + esc(cell.provider) + '</td><td>' + esc(cell.city || t("current", "当前世界")) + '</td><td>' + cell.repeat + '</td><td>' + cell.seed + '</td><td title="' + esc(cell.error || "") + '">' + esc(cell.status) + " · " + num(stats.requests) + '</td><td>' +
        (cell.study_id ? '<button class="btn tiny ghost" data-study="' + esc(cell.study_id) + '">' + esc(t("logs", "查看结果与日志")) + "</button>" : "—") + "</td></tr>"; }).join("") + '</tbody></table></div><h4>' + esc(t("comparison", "所选运行的比较")) + '</h4><div id="rbComparison">' + comparisonHTML(current.comparison || {}) + "</div>";
    var bind = function (id, fn) { if ($(id)) $(id).addEventListener("click", fn); };
    bind("rbRun", function () { action("run"); }); bind("rbRetry", function () { action("run", { retry_failed: true }); });
    bind("rbPause", function () { action(current.status === "paused" ? "resume" : "pause"); }); bind("rbStop", function () { action("stop"); });
    bind("rbPython", function () { download("export"); }); bind("rbReport", function () { download("report"); }); bind("rbJSON", function () { download("json"); });
    host.querySelectorAll("[data-study]").forEach(function (el) { el.addEventListener("click", function () { document.dispatchEvent(new CustomEvent("research-open-study", { detail: el.getAttribute("data-study") })); }); });
    host.querySelectorAll("[data-cell]").forEach(function (el) { el.addEventListener("change", function () { if (el.checked) selected.add(el.getAttribute("data-cell")); else selected.delete(el.getAttribute("data-cell")); updateComparison(); }); });
    $("rbSelectAll").addEventListener("change", function () { selected = new Set(this.checked ? current.cells.map(function (c) { return c.id; }) : []); renderViewer(); updateComparison(); });
    host.querySelector(".rb-tasks").scrollLeft = scrollLeft;
    if (focused) { var target = $(focused) || host.querySelector('[data-cell="' + focused + '"]'); if (target) target.focus({ preventScroll: true }); }
  }
  function updateComparison() {
    if (!current) return Promise.resolve();
    if ($("rbSelectAll")) {
      $("rbSelectAll").checked = selected.size === current.cells.length;
      $("rbSelectAll").indeterminate = selected.size > 0 && selected.size < current.cells.length;
    }
    var id = current.id, ids = Array.from(selected), signature = ids.join(",");
    return api("POST", prefix + "/" + id + "/compare", { cells: ids }).then(function (data) {
      if (current && current.id === id && Array.from(selected).join(",") === signature) { current.comparison = data; $("rbComparison").innerHTML = comparisonHTML(data); }
    }).catch(error);
  }
  function openBatch(id) {
    var token = ++request;
    return api("GET", prefix + "/" + id).then(function (data) {
      if (token !== request) return;
      if (!current || current.id !== id) { known = []; selected.clear(); }
      var ids = data.cells.map(function (c) { return c.id; });
      selected = new Set(selection(known, selected, new Set(ids))); known = ids; current = data;
      renderViewer(); return updateComparison();
    });
  }
  function history() {
    return api("GET", prefix).then(function (data) {
      var host = $("rwBatches");
      host.innerHTML = (data.batches || []).map(function (b) { return '<button class="rb-history" data-batch="' + esc(b.id) + '"><strong>' + esc(b.title) + '</strong><span>' + esc(b.status + " · " + b.matrix.providers.length + " × " + b.matrix.cities.length + " × " + b.matrix.repeats) + "</span></button>"; }).join("") || '<p class="rw-hint">' + esc(t("empty", "还没有实验批次。")) + "</p>";
      host.querySelectorAll("[data-batch]").forEach(function (el) { el.addEventListener("click", function () { openBatch(el.getAttribute("data-batch")).then(function () { $("rwBatchViewer").scrollIntoView({ behavior: "smooth", block: "start" }); }).catch(error); }); });
    });
  }
  function init() {
    if (!$("rwBatchPanel")) return;
    document.addEventListener("research-study-selected", function (event) { var changed = !source || !event.detail || source.id !== event.detail.id; source = event.detail; if (changed) renderForm(); });
    document.addEventListener("research-batch-open", function () { $("rwBatchPanel").scrollIntoView({ behavior: "smooth", block: "start" }); });
    document.addEventListener("locale-changed", function () { renderForm(); renderViewer(); history().catch(error); });
    api("GET", prefix + "/context").then(function (data) { context = data; renderForm(); return history(); }).catch(error);
    setInterval(function () { if (document.hidden || busy) return; if (current && ["running", "paused", "stopping"].includes(current.status)) openBatch(current.id).catch(error); }, 2000);
    setInterval(function () { if (!document.hidden && !busy) history().catch(error); }, 15000);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})(typeof window === "undefined" ? null : window);
