/* Content editors preserve every scientific field unless the user changes it. */
(function (root) {
  "use strict";
  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function lines(value) { return String(value || "").split("\n").map(function (v) { return v.trim(); }).filter(Boolean); }
  function hasResults(study) {
    var runtime = study.runtime || {};
    return !!((study.runs || []).length || runtime.started_at_epoch || runtime.actual_provider || runtime.input_snapshots || Object.keys(study.evaluation || {}).length);
  }
  function merge(kind, original, fields) {
    var result = clone(original);
    result.title = fields.title;
    if (kind === "plan") {
      result.summary = fields.summary;
      result.research_questions = lines(fields.questions);
      result.hypotheses = lines(fields.hypotheses);
      var design = JSON.parse(fields.design);
      if (Array.isArray(design)) {
        result.designs = design;
        result.design = design[result.recommended_design || 0] || {};
      } else {
        result.design = design;
        result.designs = [];
        result.recommended_design = 0;
      }
      result.steps = JSON.parse(fields.steps);
    } else {
      result.notes = fields.notes;
      result.conditions = JSON.parse(fields.conditions);
      result.hypotheses = JSON.parse(fields.hypotheses);
      result.measures = JSON.parse(fields.measures);
      result.survey = JSON.parse(fields.survey);
    }
    return result;
  }
  function open(host, kind, original, save) {
    host.replaceChildren();
    host.hidden = false;
    var form = document.createElement("form");
    form.className = "rw-content-editor";
    var heading = document.createElement("h4");
    heading.textContent = kind === "plan" ? "编辑实施方案" : "编辑运行方案";
    form.appendChild(heading);
    var inputs = {};
    function field(key, label, value, json) {
      var wrap = document.createElement("label");
      wrap.className = "rw-field";
      var caption = document.createElement("span");
      caption.textContent = label;
      wrap.appendChild(caption);
      var input = document.createElement(key === "title" ? "input" : "textarea");
      input.value = json ? JSON.stringify(value, null, 2) : String(value || "");
      input.rows = json ? 9 : 3;
      input.dataset.field = key;
      if (json) input.className = "rw-structured-editor";
      wrap.appendChild(input);
      inputs[key] = input;
      form.appendChild(wrap);
    }
    field("title", "标题", original.title);
    if (kind === "plan") {
      field("summary", "研究概要", original.summary);
      field("questions", "研究问题（每行一条）", (original.research_questions || []).join("\n"));
      field("hypotheses", "研究假设（每行一条）", (original.hypotheses || []).join("\n"));
      field("design", "实验设计（JSON，可修改条件、变量与流程）", original.designs && original.designs.length ? original.designs : original.design || {}, true);
      field("steps", "实施步骤（JSON）", original.steps || [], true);
    } else {
      field("notes", "研究备注与限制", original.notes);
      field("conditions", "实验条件与事件（JSON）", original.conditions || [], true);
      field("hypotheses", "运行假设（JSON：比较条件、方向、最小效应）", original.hypotheses || [], true);
      field("measures", "观测指标（JSON：可改指标；来源与证据等级由系统核对）", original.measures || [], true);
      field("survey", "后置问卷（JSON）", original.survey || {}, true);
    }
    var hint = document.createElement("p");
    hint.className = "rw-hint";
    hint.textContent = kind === "plan" ? "保存后保留上一版本。已编译研究保留当时的实施方案。" : "保存后重新检查并撤销批准。天数、居民、种子、模型和并发数可在运行参数区调整。";
    form.appendChild(hint);
    var error = document.createElement("p");
    error.className = "rw-warn";
    error.setAttribute("role", "alert");
    form.appendChild(error);
    var actions = document.createElement("div");
    actions.className = "rw-row";
    var submit = document.createElement("button");
    submit.className = "btn tiny";
    submit.type = "submit";
    submit.textContent = "保存并检查";
    var cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "btn tiny ghost";
    cancel.textContent = "取消编辑";
    cancel.addEventListener("click", function () { host.hidden = true; host.replaceChildren(); });
    actions.append(submit, cancel);
    form.appendChild(actions);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var values = {};
      Object.keys(inputs).forEach(function (key) { values[key] = inputs[key].value; });
      error.textContent = "";
      var edited;
      try { edited = merge(kind, original, values); }
      catch (err) { error.textContent = "内容格式不正确：" + err.message; return; }
      submit.disabled = true;
      cancel.disabled = true;
      Promise.resolve().then(function () { return save(edited); }).then(function () {
        host.hidden = true;
        host.replaceChildren();
      }).catch(function (err) {
        error.textContent = err.message;
        submit.disabled = false;
        cancel.disabled = false;
      });
    });
    host.appendChild(form);
    heading.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  var api = { merge: merge, open: open, hasResults: hasResults };
  root.ResearchEditors = api;
  if (typeof module !== "undefined") module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
