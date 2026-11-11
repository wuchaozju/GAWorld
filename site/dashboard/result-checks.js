/* Shared, read-only evidence cards. No inferred pass state for historical results. */
(function (root) {
  "use strict";
  function esc(value) {
    return String(value == null ? "" : value).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function text(key, fallback) {
    var value = root && typeof root.__ === "function" && root.__("research.check_" + key);
    return value && value !== "research.check_" + key ? value : fallback;
  }
  var states = {untested:"未检验", insufficient:"证据不足", detected:"检出方向性差异",
    stable:"在预设容许范围内稳定", not_applicable:"不适用", observed:"描述性记录"};
  var dimensions = {sampling:"重复回答与随机波动",order:"选项顺序", wording:"问法", identity:"身份与情境", interaction:"互动与记忆",
    model:"模型与评分", human:"真人参照", quality:"缺失与失败", mechanism:"机制与参数"};
  function render(card) {
    var historical = !card;
    card = card || {ref:"", scope:text("historical", "历史记录没有保存检查证据；尚未检验。"),
      checks:Object.keys(dimensions).map(function (id) { return {id:id,label:dimensions[id],status:"untested",detail:""}; })};
    var rows = card.checks || [];
    var html = '<details class="result-checks"><summary>' + esc(text("title", "偏向性与适用范围")) +
      (card.ref ? ' · ' + esc(card.ref) : '') + '</summary><p class="rw-hint">' + esc(card.scope || "") + '</p>';
    html += '<div class="rw-table-scroll"><table class="rw-table"><thead><tr><th>' + esc(text("dimension", "检查")) +
      '</th><th>' + esc(text("status", "状态")) + '</th><th>' + esc(text("evidence", "依据")) + '</th></tr></thead><tbody>';
    rows.forEach(function (row) {
      var e = row.evidence || {}, detail = row.detail || "", values = [];
      [["contrast","比较方向"],["a","A 线索"],["b","B 线索"],
        ["difference","差值"],["ci","校正后区间"],["margin","容许误差"],["pairs","配对居民数"],
        ["missing","缺失"],["switch_rate","选项改变比例"],["complete_groups","完整小组"],["missing_groups","缺失小组"]].forEach(function (pair) {
        if (e[pair[0]] != null) values.push(text(pair[0],pair[1]) + ': ' + JSON.stringify(e[pair[0]], function(key,value) {
          return typeof value === "number" && Number.isFinite(value) ? Number(value.toPrecision(4)) : value;
        }));
      });
      Object.keys(e.noise || {}).forEach(function(name) {
        var n = e.noise[name];
        values.push(text("noise_variant_" + name, name) + ' · ' + text('pairs','配对居民数') + ': ' + n.complete_residents +
          ' · ' + text('missing','缺失') + ': ' + n.missing + ' · ' +
          text(n.mean_disagreement != null ? 'draw_disagreement' : 'draw_sd', n.mean_disagreement != null ? '重复回答分歧率' : '居民内标准差均值') + ': ' +
          (n.mean_disagreement != null ? n.mean_disagreement.toPrecision(4) : n.mean_within_resident_sd != null ? n.mean_within_resident_sd.toPrecision(4) : '—'));
      });
      var contrasts = '';
      Object.keys(e.contrasts || {}).forEach(function(key) {
        var c = e.contrasts[key], ce = c.evidence || {};
        var name = text("contrast_" + key, c.label);
        var rounded = function(value) { return JSON.stringify(value, function(k,v) {
          return typeof v === 'number' && Number.isFinite(v) ? Number(v.toPrecision(4)) : v;
        }); };
        contrasts += '<p><b>' + esc(name) + '</b> · ' + esc(text(c.status,states[c.status])) +
          ' · ' + esc(text('difference','差值')) + ': ' + esc(rounded(ce.difference == null ? ce.option_shifts : ce.difference)) +
          (ce.ci ? ' · ' + esc(text('ci','校正后区间')) + ': ' + esc(rounded(ce.ci)) : '') +
          (ce.margin != null ? ' · ' + esc(text('margin','容许误差')) + ': ' + esc(rounded(ce.margin)) : '') + '</p>';
      });
      html += '<tr><td>' + esc(text(row.id, row.label || dimensions[row.id])) + '</td><td><strong>' +
        esc(text(row.status,states[row.status] || states.untested)) + '</strong></td><td>' + esc(detail) +
        (values.length ? '<p>' + esc(values.join(' · ')) + '</p>' : '') + contrasts +
        (Object.keys(e).length ? '<details><summary>' + esc(text("details", "查看记录")) + '</summary><pre>' +
          esc(JSON.stringify(e,null,2)) + '</pre></details>' : '') + '</td></tr>';
    });
    return html + '</tbody></table></div>' + (historical ? '' : '<p class="rw-hint">' +
      esc(text("scope", "这些检查不提供总体无偏保证，也不自动证明现实有效性。")) + '</p>') + '</details>';
  }
  var api = {render:render};
  if (typeof module !== "undefined") module.exports = api;
  if (root) root.GAWorldResultChecks = api;
})(typeof window !== "undefined" ? window : globalThis);
