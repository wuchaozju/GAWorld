(function () {
  "use strict";

  var RULES = {equal_split: "等额分配", need_first: "困难优先", lottery: "资格达标后抽签", skill_first: "技能匹配优先"};
  var TYPES = {create: "创建组织", add_member: "加入成员", remove_member: "退出成员", handover: "交接负责人",
    fund: "补充资金", apply_aid: "提交资助申请", publish_job: "发布岗位", apply_job: "提交应聘", set_rule: "更新决策规则", update_profile: "修改名称与目标", close: "关闭组织",
    set_governance:"设置组织治理", propose_rule:"代成员提交规则提案", cast_vote:"代成员投票", leader_decide:"代负责人决策"};
  var MODES = {off:"关闭治理", leader:"负责人决策", member_vote:"成员表决"};
  var THRESHOLDS = {quorum_majority:"至少半数参与，赞成多于反对", electorate_majority:"全体有资格成员过半赞成", simple_majority:"投票者多数，无参与门槛"};
  var PROPOSAL_STATUSES = {open:"表决中", approved:"通过待执行", rejected:"未通过", expired:"截止未成决议", invalidated:"提案失效", executed:"已执行", execution_failed:"执行失败"};
  var GOVERNANCE_REASONS = {threshold_met:"达到通过门槛",threshold_not_met:"未达到通过门槛",participation_insufficient:"参与人数不足",
    leader_decision:"负责人已作出决定",leader_did_not_decide:"负责人未在截止前决定",leader_changed:"负责人发生交接",
    rule_version_changed:"规则已被更新",governance_version_changed:"治理政策已更新",organization_closed:"组织已关闭",
    governance_disabled:"治理功能已关闭",execution_command_collision:"执行命令编号冲突"};
  var STATUSES = {pending: "排队等待", applied: "已应用", rejected: "已拒绝", open: "运行中", active: "有效", closed: "已关闭",
    inactive: "本次不活跃", paid: "已支付", hired: "已录用", approved: "已通过"};

  function esc(value) { return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; }); }
  function money(cents) { return cents == null ? "—" : "¥" + (Number(cents) / 100).toLocaleString("zh-CN", {minimumFractionDigits: 2, maximumFractionDigits: 2}); }
  function cents(raw) {
    var value = String(raw == null ? "" : raw).trim();
    if (!/^\d+(\.\d{1,2})?$/.test(value)) throw new Error("金额须为非负数，最多两位小数");
    var parts = value.split(".");
    var result = Number(parts[0]) * 100 + Number(((parts[1] || "") + "00").slice(0, 2));
    if (!Number.isSafeInteger(result)) throw new Error("金额超出可用范围");
    return result;
  }
  function integer(raw, label, minimum) {
    var text = String(raw == null ? "" : raw).trim();
    var result = Number(text);
    if (!/^-?\d+$/.test(text) || !Number.isSafeInteger(result) || (minimum != null && result < minimum)) throw new Error(label + "须为有效整数");
    return result;
  }
  function sourceLabel(source) { return {government: "政府部门池", firms: "企业部门池"}[source] || source || "—"; }
  function buildCommand(type, fields, organizationId) {
    var payload = {type: type, organization_id: type === "create" ? String(fields.organization_id || "").trim() : organizationId};
    if (!payload.organization_id) throw new Error("请选择或填写组织 ID");
    if (type === "create") {
      Object.assign(payload, {name: String(fields.name || "").trim(), kind: fields.kind, goal: fields.goal || "",
        leader_id: integer(fields.leader_id, "负责人 ID", 1), member_ids: String(fields.member_ids || "").split(/[,，\s]+/).filter(Boolean).map(function (n) { return integer(n, "成员 ID", 1); }),
        initial_balance_cents: cents(fields.initial_balance), funding_source: fields.funding_source || (fields.kind === "company" ? "firms" : "government"),
        rule: fields.rule, rule_params: fields.kind === "community" ? {max_award_cents: cents(fields.cap)} : {},
        decision_interval: integer(fields.decision_interval, "决策间隔", 1), seed: integer(fields.seed, "随机种子")});
    } else if (type === "set_governance") {
      payload.governance = {mode:fields.mode, threshold:fields.threshold, voting_days:integer(fields.voting_days, "表决天数", 1)};
      if (!Object.hasOwn(MODES, fields.mode) || !Object.hasOwn(THRESHOLDS, fields.threshold) || payload.governance.voting_days > 365) throw new Error("治理政策无效");
    } else if (type === "propose_rule") {
      Object.assign(payload, {agent_id:integer(fields.agent_id,"居民 ID",1), rule:fields.rule,
        rule_params:fields.cap ? {max_award_cents:cents(fields.cap)} : {}, title:fields.title || "", reason:fields.reason || ""});
    } else if (type === "cast_vote" || type === "leader_decide") {
      var choices = type === "cast_vote" ? ["yes","no","abstain"] : ["yes","no"];
      if (choices.indexOf(fields.choice) < 0 || !fields.proposal_id) throw new Error("请选择有效提案和表决选项");
      Object.assign(payload, {agent_id:integer(fields.agent_id,"居民 ID",1), proposal_id:fields.proposal_id,choice:fields.choice,reason:fields.reason || ""});
    } else if (type === "fund") Object.assign(payload, {amount_cents: cents(fields.amount), source: fields.source});
    else if (type === "update_profile") {
      payload.name = String(fields.name || "").trim();
      if (!payload.name) throw new Error("组织名称不能为空");
      payload.goal = fields.goal || "";
    }
    else if (type === "handover") payload.leader_id = integer(fields.leader_id, "负责人 ID", 1);
    else if (type === "publish_job") {
      var skill = Number(fields.min_income_skill);
      if (!Number.isFinite(skill) || skill < 0 || skill > 1) throw new Error("最低技能须在 0 到 1 之间");
      Object.assign(payload, {occupation: fields.occupation, vacancies: integer(fields.vacancies, "岗位人数", 1),
        monthly_salary_cents: cents(fields.monthly_salary), min_income_skill: skill, location: fields.location || ""});
      if (fields.job_id) payload.job_id = fields.job_id;
    } else if (type === "set_rule") {
      payload.rule = fields.rule;
      payload.rule_params = fields.cap ? {max_award_cents: cents(fields.cap)} : {};
    } else if (type === "close") payload.reason = fields.reason || "";
    else {
      payload.agent_id = integer(fields.agent_id, "居民 ID", 1);
      payload.reason = fields.reason || "";
      if (type === "add_member") payload.role = fields.role || "member";
      if (type === "apply_aid") payload.amount_cents = cents(fields.amount);
      if (type === "apply_job") payload.job_id = fields.job_id;
    }
    return payload;
  }
  function empty(message) { return '<div class="org-empty">' + esc(message) + '</div>'; }
  function table(headers, rows) {
    if (!rows.length) return empty("暂无记录");
    return '<div class="org-table-wrap"><table class="org-table"><thead><tr>' + headers.map(function (h) { return "<th>" + esc(h) + "</th>"; }).join("") + "</tr></thead><tbody>" + rows.map(function (row) { return "<tr>" + row.map(function (cell) { return "<td>" + esc(cell) + "</td>"; }).join("") + "</tr>"; }).join("") + "</tbody></table></div>";
  }
  function renderCommand(command) {
    var status = command.status || "pending";
    return '<article class="org-command is-' + esc(status) + '"><div class="org-command-head"><strong>' + esc(TYPES[command.type] || command.type) + " · " + esc(command.organization_id) + '</strong><span class="org-tag">' + esc(STATUSES[status] || status) + '</span></div><small>' + esc(command.command_id) + " · " + esc(command.created_at || "") + "</small>" + (command.result == null ? "" : "<pre>" + esc(JSON.stringify(command.result, null, 2)) + "</pre>") + "</article>";
  }
  function renderDetail(org) {
    var members = org.members || [], jobs = org.jobs || [], applications = org.applications || [];
    var result = '<div class="org-identity"><div><h2>' + esc(org.name) + "</h2><code>" + esc(org.organization_id) + '</code></div><span class="org-tag">' + (org.kind === "company" ? "企业" : "社区组织") + " · " + esc(STATUSES[org.status] || org.status) + "</span></div>";
    result += '<p class="org-note">' + esc(org.goal || "尚未填写组织目标") + '</p><dl class="org-ledger"><div><dt>可用余额</dt><dd>' + money(org.balance_cents) + '</dd></div><div><dt>承诺未付</dt><dd>' + money(org.committed_cents) + '</dd></div><div class="org-arrears"><dt>工资欠付</dt><dd>' + money(org.arrears_cents) + "</dd></div></dl>";
    result += '<div class="org-facts"><span>负责人 <strong>#' + esc(org.leader_id) + '</strong></span><span>拨款来源 <strong>' + esc(sourceLabel(org.funding_source)) + '</strong></span><span>规则 <strong>' + esc(RULES[org.rule] || org.rule) + " · v" + esc(org.rule_version) + '</strong></span><span>累计收入 / 支出 <strong>' + money(org.income_cents) + " / " + money(org.expense_cents) + '</strong></span><span>决策间隔 <strong>' + esc(org.decision_interval) + ' 天</strong></span><span>运行世代 <strong>' + esc(org.generation_id || "—") + "</strong></span></div>";
    result += "<h3>成员</h3>" + table(["居民", "角色", "状态", "岗位"], members.map(function (m) { return ["#" + m.agent_id, m.role === "leader" ? "负责人" : m.role, STATUSES[m.status] || m.status || (m.active === false ? "本次不活跃" : "有效"), m.job_id || "—"]; }));
    result += "<h3>岗位与工资</h3>" + table(["岗位", "职业", "名额", "月薪", "最低技能", "地点"], jobs.map(function (j) { return [j.job_id, j.occupation, j.vacancies, money(j.monthly_salary_cents), j.min_income_skill, j.location || "—"]; }));
    result += "<h3>申请与结果</h3>" + table(["居民", "申请", "状态", "金额 / 岗位", "理由 / 结果"], applications.map(function (a) { return ["#" + a.agent_id, a.kind || a.type || "—", STATUSES[a.status] || a.status, a.job_id || money(a.amount_cents), a.rejection_reason || a.reason || "—"]; }));
    if (org.governance || (org.proposals || []).length) {
      var policy = org.governance || {};
      var policyText = policy.mode === "leader" ? "由固定负责人作出赞成或反对决策；交接会使旧提案失效" : policy.mode === "member_vote" ? (THRESHOLDS[policy.threshold] || policy.threshold || "—") + "；弃权计入参与，首次投票不可改" : "当前不接收治理提案";
      result += '<h3>组织治理：提案—表决—执行</h3><p class="org-note">' + esc(MODES[policy.mode] || policy.mode || "—") + " · " + esc(policyText) + " · 表决 " + esc(policy.voting_days) + " 天 · 治理 v" + esc(org.governance_version) + "。提案开启时固定资格。通过后下一日边界执行。</p>";
      result += (org.proposals || []).length ? org.proposals.slice().reverse().map(function (p) {
        var t = p.tally, before = p.before || {}, after = p.after || {};
        var ruleText = function (r) { return (RULES[r.rule] || r.rule || "—") + (r.rule_params && r.rule_params.max_award_cents != null ? "，单人上限 " + money(r.rule_params.max_award_cents) : ""); };
        var authority = (p.policy || policy).mode === "leader" ? "固定决策者：#" + p.leader_id : "固定成员：" + (p.electorate || []).map(function (n) { return "#" + n; }).join("、");
        var html = '<article class="org-command"><div class="org-command-head"><strong>' + esc(p.title || p.proposal_id) + '</strong><span class="org-tag">' + esc(PROPOSAL_STATUSES[p.status] || p.status) + '</span></div><p>' + esc(ruleText(before)) + " → " + esc(ruleText(after)) + '</p><p class="org-note">提案者 #' + esc(p.proposer_id) + " · 原规则 v" + esc(p.base_rule_version) + " · Day " + esc(p.opened_day) + " 开启 · 截止 Day " + esc(p.closing_day) + " 日边界</p><p>理由：" + esc(p.reason || "未提供") + '</p><p class="org-note">' + esc(authority) + "</p>";
        if (t) html += '<p>赞成 ' + esc(t.yes) + " / 反对 " + esc(t.no) + " / 弃权 " + esc(t.abstain) + " · 参与 " + esc(t.participation) + " / " + esc(t.eligible) + " · 决议 Day " + esc(p.resolved_day) + "（" + esc(GOVERNANCE_REASONS[p.resolution_reason] || p.resolution_reason || "—") + "）</p>";
        if (p.execute_not_before_day != null) html += '<p class="org-note">最早执行 Day ' + esc(p.execute_not_before_day) + " · 执行命令 <code>" + esc(p.execution_command_id) + "</code></p>";
        if (p.execution_day != null || p.execution_reason) html += "<p>执行" + (p.execution_day != null ? " Day " + esc(p.execution_day) : "") + (p.execution_rule_version != null ? " · 规则 v" + esc(p.execution_rule_version) : " · " + esc(GOVERNANCE_REASONS[p.execution_reason] || p.execution_reason || "失败")) + "</p>";
        html += table(["居民", "选择", "理由", "来源"], (org.ballots || []).filter(function (b) { return b.proposal_id === p.proposal_id; }).map(function (b) { return ["#" + b.agent_id,{yes:"赞成",no:"反对",abstain:"弃权"}[b.choice] || b.choice,b.reason || "未提供", b.actor && b.actor.source || "研究者代理 / CLI"]; }));
        return html + "</article>";
      }).join("") : empty("尚无治理提案");
    }
    result += '<details><summary>查看完整记录与规则版本</summary><pre>' + esc(JSON.stringify(org, null, 2)) + "</pre></details>";
    return result;
  }

  function operationsFor(org, enabled) {
    var operations = ["fund", "add_member", "remove_member", "handover", "update_profile", "set_rule", "close"].concat(org.kind === "company" ? ["publish_job", "apply_job"] : ["apply_aid"]);
    if (enabled) {
      operations.push("set_governance");
      var mode = (org.governance || {}).mode;
      var open = (org.proposals || []).some(function (p) { return p.status === "open"; });
      var unfinished = (org.proposals || []).some(function (p) { return p.status === "open" || p.status === "approved"; });
      if (mode && mode !== "off" && !unfinished) operations.push("propose_rule");
      if (open && mode === "member_vote") operations.push("cast_vote");
      if (open && mode === "leader") operations.push("leader_decide");
    }
    return operations;
  }
  if (typeof module !== "undefined" && module.exports) module.exports = {buildCommand: buildCommand, renderCommand: renderCommand, renderDetail: renderDetail, operationsFor:operationsFor};
  if (typeof document === "undefined") return;

  var selected = null, selectedOrg = null, canWrite = false, timer = null, loading = false, refreshRequested = false;
  var exportMeta = null, exporting = false;
  var governanceEnabled = false, operationKey = "";
  var el = function (id) { return document.getElementById(id); };
  function status(message, error) { el("orgStatus").textContent = message; el("orgStatus").classList.toggle("is-error", !!error); }
  async function api(url, payload) {
    var response = await fetch(url, payload ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)} : {});
    var body = await response.json();
    if (!response.ok) throw new Error(body.error || "读取失败（" + response.status + "）");
    return body;
  }
  function updateDownload() {
    el("orgDownload").disabled = exporting || !exportMeta;
    el("orgDownload").textContent = exporting ? "正在读取指标……" : exportMeta ? "下载 Day " + exportMeta.day + " 指标 JSON" : "下载完成日指标 JSON";
  }
  async function downloadMetrics() {
    if (exporting || !exportMeta) return;
    var requested = exportMeta;
    exporting = true;
    updateDownload();
    try {
      var data = await api("/api/organizations/exports/metrics?generation_id=" + encodeURIComponent(requested.generation_id) + "&day=" + requested.day);
      if (data.generation_id !== requested.generation_id || data.day !== requested.day || typeof data.content !== "string" || typeof data.filename !== "string") throw new Error("指标文件与请求的世代或完成日不一致");
      var url = URL.createObjectURL(new Blob([data.content], {type: "application/json"}));
      var link = document.createElement("a");
      try {
        link.href = url;
        link.download = data.filename;
        document.body.appendChild(link);
        link.click();
      } finally {
        link.remove();
        URL.revokeObjectURL(url);
      }
      status("已下载 Day " + data.day + " 的本世代累计指标。可与另一个世界同一完成日的文件进行离线规则对照。");
    } catch (error) { status(error.message, true); }
    finally { exporting = false; updateDownload(); }
  }
  function ruleOptions(kind) {
    return (kind === "company" ? ["lottery", "skill_first"] : ["equal_split", "need_first"]).map(function (r) { return '<option value="' + r + '">' + RULES[r] + "</option>"; }).join("");
  }
  function updateTemplate() {
    var kind = el("orgKind").value;
    el("orgCreateRule").innerHTML = ruleOptions(kind);
    el("orgFunding").value = kind === "company" ? "firms" : "government";
    el("orgCapField").hidden = kind === "company";
  }
  function field(name, label, extra) { return '<label class="field"><span>' + label + '</span><input name="' + name + '" ' + (extra || "") + ' /></label>'; }
  function commandInputs() {
    var type = el("orgCommandType").value, html = "";
    var resident = field("agent_id", "居民 ID", 'type="number" min="1" step="1" required');
    var reason = field("reason", "原因", 'type="text"');
    if (type === "set_governance") {
      var policy = selectedOrg.governance || {mode:"member_vote",threshold:"quorum_majority",voting_days:1};
      html = '<label class="field"><span>治理方式</span><select name="mode">' + Object.keys(MODES).map(function (m) { return '<option value="' + m + '"' + (m === policy.mode ? ' selected' : '') + '>' + MODES[m] + '</option>'; }).join("") + '</select></label><label class="field"><span>成员表决门槛</span><select name="threshold">' + Object.keys(THRESHOLDS).map(function (t) { return '<option value="' + t + '"' + (t === policy.threshold ? ' selected' : '') + '>' + THRESHOLDS[t] + '</option>'; }).join("") + '</select></label>' + field("voting_days","表决天数",'type="number" min="1" max="365" value="' + esc(policy.voting_days) + '" required');
    } else if (type === "propose_rule") html = resident + field("title","提案标题") + '<label class="field"><span>拟议规则</span><select name="rule">' + ruleOptions(selectedOrg.kind) + '</select></label>' + (selectedOrg.kind === "community" ? field("cap","拟议单人上限（元，留空保持当前值）",'inputmode="decimal"') : "") + reason + '<p class="org-note">由研究者代指定成员提交。提案开启时才固定成员名单和规则版本。</p>';
    else if (type === "cast_vote" || type === "leader_decide") html = resident + '<label class="field"><span>开放提案</span><select name="proposal_id">' + (selectedOrg.proposals || []).filter(function (p) { return p.status === "open"; }).map(function (p) { return '<option value="' + esc(p.proposal_id) + '">' + esc(p.title || p.proposal_id) + '</option>'; }).join("") + '</select></label><label class="field"><span>选择</span><select name="choice"><option value="yes">赞成</option><option value="no">反对</option>' + (type === "cast_vote" ? '<option value="abstain">弃权</option>' : "") + '</select></label>' + reason + '<p class="org-note">由研究者代理提交；运行时检查固定资格。首次有效选择不可改。</p>';
    else if (type === "fund") html = field("amount", "拨款金额（元）", 'inputmode="decimal" required') + '<label class="field"><span>资金来源</span><select name="source"><option value="government">政府部门池</option><option value="firms">企业部门池</option></select></label>';
    else if (type === "handover") html = field("leader_id", "新负责人居民 ID（有效成员）", 'type="number" min="1" step="1" required');
    else if (type === "update_profile") html = field("name", "组织名称", 'required value="' + esc(selectedOrg.name) + '"') + '<label class="field"><span>组织目标</span><textarea name="goal" rows="2">' + esc(selectedOrg.goal || "") + '</textarea></label>';
    else if (type === "publish_job") html = field("occupation", "职业", "required") + field("job_id", "岗位 ID（可留空）") + field("vacancies", "岗位人数", 'type="number" min="1" value="1" required') + field("monthly_salary", "月薪（元）", 'inputmode="decimal" required') + field("min_income_skill", "最低 income_skill", 'type="number" min="0" step="0.01" value="0" required') + field("location", "工作地点");
    else if (type === "set_rule") html = '<label class="field"><span>新决策规则</span><select name="rule">' + ruleOptions(selectedOrg.kind) + "</select></label>" + (selectedOrg.kind === "community" ? field("cap", "单人资助上限（元）", 'inputmode="decimal" value="100" required') : "");
    else if (type === "close") html = reason;
    else html = resident + (type === "apply_aid" ? field("amount", "申请金额（元）", 'inputmode="decimal" required') : "") + (type === "apply_job" ? field("job_id", "岗位 ID", "required") : "") + reason;
    el("orgCommandInputs").innerHTML = html;
  }
  async function loadDetail() {
    if (!selected) return;
    var requested = selected;
    var base = "/api/organizations/" + encodeURIComponent(requested);
    var results = await Promise.all([api(base), api(base + "/history")]);
    if (requested !== selected) return;
    var operations = operationsFor(results[0], governanceEnabled);
    var openProposalIds = (results[0].proposals || []).filter(function (p) { return p.status === "open"; }).map(function (p) { return p.proposal_id; });
    var nextOperationKey = requested + ":" + operations.join(",") + ":" + openProposalIds.join(",") + ":" + (results[0].governance_version || "");
    var rebuildForm = operationKey !== nextOperationKey;
    operationKey = nextOperationKey;
    selectedOrg = results[0];
    el("orgDetail").innerHTML = renderDetail(selectedOrg);
    el("orgHistoryPanel").hidden = false;
    el("orgHistory").innerHTML = results[1].history.length ? results[1].history.map(function (row) { return "<details><summary>" + esc(row.kind || row.type || row.event || "记录") + " · " + esc(row.day == null ? row.created_at || "" : "Day " + row.day) + "</summary><pre>" + esc(JSON.stringify(row, null, 2)) + "</pre></details>"; }).join("") : empty("尚无已执行的决策或交易");
    el("orgOperations").hidden = false;
    el("orgCommandFields").disabled = !canWrite;
    if (rebuildForm) {
      var current = el("orgCommandType").value;
      el("orgCommandType").innerHTML = operations.map(function (type) { return '<option value="' + type + '">' + TYPES[type] + "</option>"; }).join("");
      if (operations.indexOf(current) >= 0) el("orgCommandType").value = current;
      commandInputs();
    }
  }
  async function refresh() {
    if (loading) { refreshRequested = true; return; }
    loading = true;
    try {
      var results = await Promise.all([api("/api/organizations"), api("/api/organizations/commands")]);
      var overview = results[0], commands = results[1].commands;
      governanceEnabled = !!overview.governance_enabled;
      var meta = overview.meta || {};
      exportMeta = typeof meta.generation_id === "string" && Number.isSafeInteger(meta.last_processed_day) && meta.last_processed_day > 0 ? {generation_id:meta.generation_id, day:meta.last_processed_day} : null;
      updateDownload();
      canWrite = overview.can_write;
      el("orgCreateFields").disabled = !canWrite;
      el("orgCommandFields").disabled = !canWrite || !selectedOrg || selectedOrg.organization_id !== selected;
      el("orgCount").textContent = overview.organizations.length + " 个";
      el("orgList").innerHTML = overview.organizations.length ? overview.organizations.map(function (org) { return '<button type="button" data-org-id="' + esc(org.organization_id) + '" class="' + (org.organization_id === selected ? "is-active" : "") + '"><strong>' + esc(org.name) + '</strong><small>' + (org.kind === "company" ? "企业" : "社区") + " · " + esc(STATUSES[org.status] || org.status) + " · " + money(org.balance_cents) + "</small></button>"; }).join("") : empty("还没有组织。可从下方选择一个模板。");
      el("orgCommands").innerHTML = commands.length ? commands.slice().reverse().map(renderCommand).join("") : empty("没有排队或完成的管理命令");
      status((overview.enabled ? "组织已启用：命令在仿真日边界执行。" : "组织尚未启用：命令等待下一次启用组织的运行。") + (canWrite ? "" : " 当前世界只读，需世界拥有者或管理员提交命令。"));
      if (overview.meta && overview.meta.recovery_required) status("组织状态需要核对恢复：新的组织支付已停止。请查看运行错误与持久记录。", true);
      if (selected) await loadDetail();
      clearTimeout(timer);
      if (commands.some(function (c) { return c.status === "pending"; })) timer = setTimeout(refresh, 5000);
    } catch (error) { exportMeta = null; updateDownload(); status(error.message, true); }
    finally {
      loading = false;
      if (refreshRequested) { refreshRequested = false; refresh(); }
    }
  }
  function values(form) { var result = {}; new FormData(form).forEach(function (value, key) { result[key] = value; }); return result; }
  async function submit(event, create) {
    event.preventDefault();
    if (!canWrite || (!create && (!selectedOrg || selectedOrg.organization_id !== selected))) return;
    var button = event.target.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      var fields = values(event.target);
      var command = await api("/api/organizations/commands", buildCommand(create ? "create" : fields.type, fields, selected));
      await refresh();
      status("命令 " + command.command_id + " 已排队；当前状态：" + (STATUSES[command.status] || command.status) + "。请等待下一次日边界并查看执行结果。");
    } catch (error) { status(error.message, true); }
    finally { button.disabled = !canWrite; }
  }
  el("orgList").addEventListener("click", function (event) {
    var button = event.target.closest("[data-org-id]");
    if (!button) return;
    selected = button.dataset.orgId;
    el("orgCommandFields").disabled = true;
    refresh();
  });
  el("orgRefresh").addEventListener("click", refresh);
  el("orgDownload").addEventListener("click", downloadMetrics);
  el("orgKind").addEventListener("change", updateTemplate);
  el("orgCommandType").addEventListener("change", commandInputs);
  el("orgCreateForm").addEventListener("submit", function (event) { submit(event, true); });
  el("orgCommandForm").addEventListener("submit", function (event) { submit(event, false); });
  updateTemplate();
  updateDownload();
  refresh();
}());
