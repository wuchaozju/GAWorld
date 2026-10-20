(function () {
  "use strict";
  var base = "/api/research/organization-intelligence";
  var state = { record: null, studies: [], timer: null, offset: 0, log: "", busy: false, loading: false };
  var labels = { draft: "协议已冻结", running: "正在运行", stopping: "正在停止", stopped: "已停止", completed: "已完成", failed: "失败 · 证据已保留", interrupted: "已中断" };
  function $(id) { return document.getElementById(id); }
  function esc(value) { return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) { return {"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c]; }); }
  function seconds(value) { return value == null ? "待估计" : Math.round(value) + " 秒"; }
  async function api(path, body) {
    var response = await fetch(base + path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    var data = await response.json();
    if (!response.ok) throw new Error(data.error || "HTTP " + response.status);
    return data;
  }
  function fail(error) { $("oiError").textContent = error.message || String(error); }
  function budget() { $("oiBudget").textContent = "当前城市：" + ($("oiForm").dataset.city || "加载中") + "。预计 " + (Number($("oiRepeats").value) * 109) + " 次请求；每次最多 2048 输出 token，无自动重试或模型回退。实际费用取决于模型服务。"; }
  function download(name, text, type) {
    var url = URL.createObjectURL(new Blob([text], { type: type || "text/plain;charset=utf-8" }));
    var a = document.createElement("a"); a.href = url; a.download = name; a.click();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }
  function results(record) {
    var analysis = record.analysis;
    if (!analysis || !analysis.complete) { $("oiResults").textContent = "待全部条件完成后生成比较。已有部分结果不用于判断组织收益。"; return; }
    var html = '<p class="oi-note">' + esc(analysis.inference) + '</p><table><thead><tr><th>预注册比较</th><th>平均效用差</th></tr></thead><tbody>';
    analysis.contrasts.forEach(function (c) { html += "<tr><td>" + esc(c.label) + "</td><td>" + (c.mean > 0 ? "+" : "") + Number(c.mean).toFixed(3) + "</td></tr>"; });
    $("oiResults").innerHTML = html + "</tbody></table>";
  }
  function render(record) {
    state.record = record;
    state.studies = state.studies.map(function (r) { return r.id === record.id ? record : r; });
    renderList();
    var p = record.protocol, t = record.telemetry || {}, live = ["running", "stopping"].includes(record.status);
    $("oiStudy").hidden = false;
    $("oiStatus").textContent = labels[record.status] || record.status;
    $("oiIdentity").textContent = record.id + " · " + p.model.name + " / " + p.model.model + " · " + p.repeats + " 组 · " + (p.city || "当前世界");
    $("oiProgress").value = record.progress || 0;
    var current = record.current;
    $("oiMetrics").textContent = "响应记录 " + record.calls_completed + " / " + p.budget.requests + " · 已开始请求 " + (record.calls_started || 0) +
      "\nHTTP 提交 " + (t.http_attempts || 0) + " · HTTP 失败 " + (t.http_failures || 0) + " · 模型回退 " + (t.requests_fell_back || 0) +
      "\n活动 " + seconds(record.elapsed_seconds || 0) + " · 日历 " + seconds(record.wall_seconds || 0) + " · 暂停 " + seconds(record.paused_seconds || 0) + " · 预计剩余 " + (live ? seconds(record.remaining_seconds) : "—") +
      "\n输入 " + (record.input_chars || 0) + " 字符 · 输出 " + (record.output_chars || 0) + " 字符（非 token 用量）" +
      (current ? "\n当前：第 " + (current.block + 1) + " 组 · " + (p.arms[current.arm] || (current.arm === "organized" ? "组织协作" : current.arm)) + " · " + ({train: "训练", test: "测试", archive: "归纳档案"}[current.phase] || current.phase) : "") +
      (record.error ? "\n" + record.error : "");
    $("oiRun").hidden = record.status !== "draft";
    $("oiRun").disabled = state.busy;
    $("oiStop").hidden = !live;
    $("oiStop").disabled = state.busy || record.status === "stopping";
    $("oiProtocol").textContent = JSON.stringify(p, null, 2);
    results(record);
    clearTimeout(state.timer);
    if (live) state.timer = setTimeout(function () { open(record.id, false).catch(fail); }, 2000);
  }
  async function logs() {
    if (!state.record || !$("oiLogDetails").open) return;
    var identifier = state.record.id;
    var data = await api("/" + identifier + "/logs?offset=" + state.offset);
    if (!state.record || identifier !== state.record.id) return;
    state.offset = data.next_offset || state.offset;
    state.log = (state.log + (data.text || "")).slice(-60000);
    $("oiLogs").textContent = state.log || "尚未发起请求。";
  }
  async function open(identifier, updateUrl) {
    if (state.loading) return;
    state.loading = true;
    try {
      var record = await api("/" + identifier);
      if (!state.record || state.record.id !== identifier) { state.offset = 0; state.log = ""; $("oiLogs").textContent = ""; }
      render(record);
      if (updateUrl) { var url = new URL(location.href); url.searchParams.set("oi", identifier); url.searchParams.set("tab", "organization-intelligence"); history.replaceState(null, "", url); }
      await logs();
    } finally { state.loading = false; }
  }
  async function refresh() {
    var data = await api("");
    var old = $("oiProvider").value;
    $("oiProvider").innerHTML = data.providers.map(function (p) { return '<option value="' + esc(p.name) + '">' + esc(p.name + " · " + p.model) + '</option>'; }).join("");
    $("oiProvider").value = old || data.default_provider;
    $("oiForm").dataset.city = data.city;
    budget();
    state.studies = data.studies;
    renderList();
  }
  function renderList() {
    $("oiStudies").innerHTML = state.studies.length ? state.studies.map(function (r) { return '<button type="button" class="oi-record" data-oi="' + esc(r.id) + '" aria-current="' + Boolean(state.record && state.record.id === r.id) + '">' + esc(labels[r.status] || r.status) + " · " + (r.calls_completed || 0) + " 次响应<br>" + esc(r.id) + '</button>'; }).join("") : '<p class="oi-note">尚无研究，先生成一份实验协议。</p>';
  }
  async function action(fn) {
    if (state.busy) return;
    state.busy = true; $("oiError").textContent = ""; $("oiCreate").disabled = true;
    if (state.record) render(state.record);
    try { await fn(); await refresh(); } catch (error) { fail(error); }
    finally { state.busy = false; $("oiCreate").disabled = false; if (state.record) render(state.record); }
  }
  function init() {
    if (!$("oiForm")) return;
    $("oiRepeats").addEventListener("input", budget);
    $("oiForm").addEventListener("submit", function (event) { event.preventDefault(); action(async function () {
      var record = await api("", { provider: $("oiProvider").value, repeats: Number($("oiRepeats").value), seed: Number($("oiSeed").value) });
      await open(record.id, true);
    }); });
    $("oiRun").addEventListener("click", function () { action(async function () { await api("/" + state.record.id + "/run", {}); await open(state.record.id, false); }); });
    $("oiStop").addEventListener("click", function () { action(async function () { var id = state.record.id; await api("/" + id + "/stop", {}); await open(id, false); }); });
    $("oiExport").addEventListener("click", function () { action(async function () { var data = await api("/" + state.record.id + "/export"); download(data.filename, data.markdown); }); });
    $("oiProtocolDownload").addEventListener("click", function () { if (state.record) download(state.record.id + "-protocol.json", JSON.stringify(state.record.protocol, null, 2), "application/json"); });
    $("oiAuditDownload").addEventListener("click", function () { action(async function () {
      var identifier = state.record.id, offset = 0, size = null, chunks = [];
      do {
        var chunk = await api("/" + identifier + "/logs?offset=" + offset);
        if (size === null) size = chunk.size || 0;
        chunks.push(chunk.text || "");
        if (chunk.next_offset <= offset) break;
        offset = chunk.next_offset;
      } while (offset < size);
      download(identifier + "-events.jsonl", chunks.join(""), "application/x-ndjson");
    }); });
    $("oiStudies").addEventListener("click", function (event) { var button = event.target.closest("[data-oi]"); if (button) open(button.dataset.oi, true).catch(fail); });
    $("oiLogDetails").addEventListener("toggle", function () { logs().catch(fail); });
    refresh().then(function () { var identifier = new URLSearchParams(location.search).get("oi"); if (identifier) return open(identifier, false); }).catch(fail);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
}());
