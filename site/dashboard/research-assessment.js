/* Render server-normalized evidence; no scientific or execution rules here. */
(function (root) {
  "use strict";
  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }
  function english(options) { return !!options && options.language === "en"; }
  var fields = {
    participants: ["研究对象", "Participants"], sample: ["样本与招募", "Sample and recruitment"],
    assignment: ["组别与分配", "Conditions and assignment"], interventions: ["刺激与干预", "Stimuli and interventions"],
    measures: ["测量与量表", "Measures and scales"], timepoints: ["测量时间点", "Measurement timepoints"],
    analysis: ["分析方法", "Analysis"], results: ["原文报告结果", "Reported results"]
  };
  function render(value, options) {
    value = value || {};
    var en = english(options), pending = en ? "Pending confirmation" : "待确认";
    if (value.status === "legacy") {
      return '<p class="rw-hint rw-warn">' + esc((en ? "Legacy model rating; no shared rubric: " : "旧版模型总评，无统一量表：") + value.score + "/100") +
        '<br>' + esc(en ? "Not comparable with rubric v1." : "不能与新版建议分直接比较。") + '</p>';
    }
    var score = value.score == null ? pending : String(value.score) + "/100";
    var html = '<section class="rw-section rw-assessment"><h4>' + esc(en ? "Method advice · rubric v1" : "方法建议 · 量表 v1") + ' · ' + esc(score) + '</h4>' +
      '<p class="rw-hint">' + esc(en ? "Model advice, not success probability. Execution checks await compilation." : "模型方法建议，不是成功率；平台执行检查待编译后由代码确认。") + '</p>';
    html += '<div class="rw-table-scroll"><table class="rw-table"><thead><tr>' +
      [en ? "Dimension" : "维度", en ? "Band / weight" : "档位 / 权重", en ? "Evidence and gaps" : "依据与缺口"].map(function (text) { return '<th>' + esc(text) + '</th>'; }).join("") + '</tr></thead><tbody>';
    (value.dimensions || []).forEach(function (item) {
      html += '<tr><td>' + esc(en ? item.label_en : item.label) + '</td><td>' + esc(item.band == null ? pending : item.band + "/4") + ' · ' + esc(item.weight) + '%</td><td>' +
        esc(item.evidence || pending) + (item.gap ? '<br>' + esc((en ? "Gap: " : "缺口：") + item.gap) : '') + '</td></tr>';
    });
    return html + '</tbody></table></div></section>';
  }
  function renderSource(source, options) {
    if (!source || !source.sha256) return "";
    var en = english(options);
    return '<details class="rw-source-plan"><summary>' + esc(source.truncated ? (en ? "Partial material" : "材料覆盖不完整") : (en ? "Provided text coverage" : "提供文本的覆盖范围")) +
      ' · ' + esc(source.used_chars + " / " + source.input_chars) + '</summary><p class="rw-hint">' +
      esc(en ? "Coverage describes supplied text, not proof that the entire publication was read." : "覆盖范围只描述提供的文本，不代表已读完整出版物。") +
      '</p><pre>SHA256: ' + esc(source.sha256) + '</pre></details>';
  }
  function renderOriginalDesign(original, options) {
    if (!original || !Object.keys(original).length) return "";
    var en = english(options);
    var html = '<section class="rw-section"><h4>' + esc(en ? "Original design and sources" : "原研究设计与来源") + '</h4><p class="rw-hint">' +
      esc(en ? "Quote location checks cannot establish that the interpretation is correct." : "片段定位只能核对原文是否存在，不能证明提炼结论正确。") + '</p><dl class="rw-dl">';
    Object.keys(fields).forEach(function (key) {
      var item = original[key] || {}, source = item.source || {};
      html += '<dt>' + esc(fields[key][en ? 1 : 0]) + '</dt><dd>' + esc(item.status === "unknown" ? (en ? "Not reported" : "未说明") : (item.value || (en ? "Not reported" : "未说明")));
      if (source.locator || source.quote) {
        html += '<p class="rw-hint">' + esc(source.locator) + ' · ' + esc(source.verified ? (en ? "Quote located" : "片段已定位") : (en ? "Source unverified" : "来源未验证")) + '<br>' + esc(source.quote) + '</p>';
      }
      if (item.manual_edited) html += '<small>' + esc(en ? "Manually edited" : "研究者已修订") + '</small>';
      html += '</dd>';
    });
    return html + '</dl></section>';
  }
  function renderPreservation(rows, options) {
    if (!rows || !rows.length) return "";
    var en = english(options), statuses = {
      preserved: ["保留", "Preserved"], approximated: ["近似替代", "Approximation"],
      missing: ["缺失", "Missing"], pending: ["待确认", "Pending confirmation"]
    };
    var html = '<section class="rw-section"><h4>' + esc(en ? "Design preservation" : "原设计保留情况") + '</h4><ul>';
    rows.forEach(function (item) {
      html += '<li><b>' + esc((fields[item.field] || [item.field, item.field])[en ? 1 : 0]) + ' · ' + esc((statuses[item.status] || statuses.pending)[en ? 1 : 0]) + '</b><br>' +
        esc(item.original) + ' → ' + esc(item.proposed) + (item.consequence ? '<br>' + esc(item.consequence) : '') + '</li>';
    });
    return html + '</ul></section>';
  }
  var api = {render:render, renderSource:renderSource, renderOriginalDesign:renderOriginalDesign, renderPreservation:renderPreservation};
  root.GAWorldResearchAssessment = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
