/* Render server-owned admission checks; never duplicate scientific/budget rules. */
(function (root) {
  "use strict";
  function esc(value) { return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
  }); }
  function words(options) {
    return options && options.language === "en" ? {
      mode:"Mode compatibility (checked by code)",tick:"Full intraday",lean_tick:"Lean intraday",daily_brief:"Daily brief · exploratory",
      yes:"Supported",no:"Unsupported",estimated:"Estimated calls",hard:"Actual HTTP attempt cap (includes retries)",
      max:"Allowed planning maximum",candidates:"Revisions within budget · review before approving",review:"Review this revision",
      stage:"Stage",provider:"Provider",model:"Model",attempts:"Attempts",code:"Reason",next:"Next step",task_id:"Task",
      study_id:"Study",attempt:"Run attempt",last_activity:"Last activity"
    } : {
      mode:"运行方式兼容性（代码检查）",tick:"完整日内",lean_tick:"精简日内",daily_brief:"按天简报 · 近似探索",
      yes:"支持",no:"不支持",estimated:"估算调用量",hard:"实际 HTTP 请求硬上限（包含重试）",max:"可申请的规划预算上限",
      candidates:"预算内候选修订 · 审阅后重新批准",review:"审阅这份修订",stage:"阶段",provider:"模型接口",model:"模型",
      attempts:"尝试次数",code:"原因码",next:"下一步",task_id:"任务",study_id:"研究",attempt:"运行尝试",last_activity:"最后活动"
    };
  }
  var faults = {
    budget_exhausted:["The actual HTTP request budget is exhausted.","Review the budget and start a new approved attempt; existing outputs are retained."],
    request_timeout:["The model wait timed out.","Check the task status and provider logs before starting another request."],
    rate_limited:["The provider is rate limiting requests.","Follow the provider retry delay and check the retry counter."],
    quota_exhausted:["The provider quota is exhausted.","Check the account quota or plan before retrying."],
    authentication_failed:["The provider rejected authentication.","Review the configured credentials and test this model."],
    connection_failed:["The provider connection failed.","Check the configured endpoint and connection, then reconnect to the task."],
    dns_failed:["The provider hostname could not be resolved.","Check the hostname and DNS connection."],
    model_not_found:["The selected model is unavailable.","Check the exact model name and model availability."],
    configuration_missing:["The model configuration is incomplete or incompatible.","Review model configuration and run a generation test."],
    output_format:["The model output could not be parsed.","Review format diagnostics and the configured output token budget."],
    service_restarted:["The task was interrupted by a service restart.","Inspect retained results and start a new attempt."],
    user_stopped:["The task was stopped by the user.","Retained outputs remain available; use a new attempt to rerun."],
    process_exit:["A simulation subprocess exited unsuccessfully.","Review the world log and exit code; do not infer its cause from the code alone."],
    process_signal:["A simulation subprocess ended after a signal.","Review the process and system logs; the signal alone does not establish an out-of-memory failure."],
    task_failed:["The task failed.","Use the task identifier and stage to locate the retained diagnostic logs."]
  };
  function renderChecks(preflight, options) {
    var w = words(options), html = "", budget = preflight.budget || {}, modes = preflight.modes || {};
    if (budget.http_budget != null) html += '<p class="rw-hint">' + esc(w.hard) + ': ' + esc(budget.http_budget) + ' · ' + esc(w.max) + ': ' + esc(budget.maximum) + '</p>';
    if (Object.keys(modes).length) {
      html += '<h4>' + esc(w.mode) + '</h4><div class="rw-table-scroll"><table class="rw-table"><tbody>';
      Object.keys(modes).forEach(function (mode) {
        var check = modes[mode];
        html += '<tr><th>' + esc(w[mode] || mode) + '</th><td>' + esc(check.compatible ? w.yes : w.no) + '</td><td>' +
          esc(w.estimated) + ': ' + esc(check.estimated_calls) + (check.errors || []).map(function (error) {
            return '<div class="rw-warn">' + esc(error) + '</div>';
          }).join('') + '</td></tr>';
      });
      html += '</tbody></table></div>';
    }
    if (options && options.editable && (preflight.candidates || []).length) {
      html += '<h4>' + esc(w.candidates) + '</h4>';
      preflight.candidates.forEach(function (candidate, index) {
        html += '<p class="rw-hint">' + esc(candidate.note) + ' · ' + esc(w.estimated) + ': ' + esc(candidate.estimated_calls) +
          ' <button type="button" class="btn tiny ghost" data-budget-candidate="' + index + '">' + esc(w.review) + '</button></p>';
      });
    }
    return html;
  }
  function renderDiagnostic(value, options) {
    if (!value || !value.code) return "";
    var w = words(options), english = options && options.language === 'en';
    var translated = faults[value.code] || faults.task_failed;
    var html = '<div class="rw-gap rw-gap-warn" role="status"><b>' + esc(english ? translated[0] : value.message) + '</b>';
    ['code','stage','provider','model','attempts','task_id','study_id','attempt','last_activity'].forEach(function (key) {
      if (value[key] != null && value[key] !== '') html += '<p class="rw-hint">' + esc(w[key] || key) + ': ' + esc(value[key]) + '</p>';
    });
    return html + '<p>' + esc(w.next) + ': ' + esc(english ? translated[1] : value.next_action) + '</p></div>';
  }
  var api = {renderChecks:renderChecks, renderDiagnostic:renderDiagnostic};
  root.ResearchAdmission = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
