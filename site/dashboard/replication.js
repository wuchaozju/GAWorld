
var gwURL = globalThis.GAWorldURL ? globalThis.GAWorldURL.url : function (value) { return value; };
var gwHTML = globalThis.GAWorldURL ? globalThis.GAWorldURL.html : function (value) { return value; };
/* 研究工作台 · 社会调查/实验拟合度 — 上传文献 → 抽取研究设计与真人结果 → 核对 → 居民重做 → 代码比较。
 *
 * POST /api/research/replication/extract 和 /run 各开一个后台任务，轮询 /api/research/replication/jobs/<id>；
 * 抽取结果（spec）只在页面里，核对后随 /run 发回；跑完的记录在 /api/research/replication/<id>，
 * 当前打开的记录记在 ?rep= 里。Tab 切换由 serious-game.js 统一管理。
 */
(function () {
  "use strict";

  var JOB_POLL_MS = 1500;
  var SAMPLES = [10, 20, 30, 50, 100, 200, 300, 500];
  var VERDICT_CLASS = {
    replicated: "rw-verdict-supported",
    same_direction: "rw-verdict-inconclusive",
    not_replicated: "rw-verdict-contradicted",
    reversed: "rw-verdict-contradicted",
    no_human_effect: "rw-verdict-unmeasured",
  };
  var VERDICT_TEXT = {
    replicated: "方向一致且显著（不代表效应等价）",
    same_direction: "方向一致，但不显著",
    not_replicated: "未复现：方向不一致，也不显著",
    reversed: "方向相反且显著",
    no_human_effect: "文献中无差异",
  };

  function t(key, fallback) {
    if (typeof window.__ !== "function") return fallback;
    var value = window.__("research." + key);
    return value && value !== "research." + key ? value : fallback;
  }

  function tf(key, fallback, params) {
    var text = t(key, fallback);
    Object.keys(params || {}).forEach(function (name) {
      text = text.split("{" + name + "}").join(String(params[name]));
    });
    return text;
  }

  function $(id) {
    return document.getElementById(id);
  }

  function esc(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function api(method, path, body) {
    return fetch(path, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    })
      .then(function (res) {
        return res
          .json()
          .catch(function () {
            throw new Error("HTTP " + res.status);
          })
          .then(function (data) {
            if (!res.ok) throw new Error((data && data.error) || "HTTP " + res.status);
            return data;
          });
      })
      .catch(function (err) {
        if (err instanceof TypeError) {
          throw new Error(tf("no_backend", "连不上后端：{error}", { error: err.message }));
        }
        throw err;
      });
  }

  var state = { providers: [], cities: [], runs: [], spec: null, run: null, maxSample: 500, running:false, educationSchema:{}, eligible:null, generation:null, extraction:null };
  var eligibilityTimer = null, eligibilitySequence = 0;

  /* ----------------------------------------------------------------- 模型参数
     温度与 max tokens 是实验协议的一部分。这里读出界面上填的三个阶段的参数，
     并在越界时说清楚，而不是把它悄悄改掉——一个没到模型的温度比一个被拒绝的
     温度更糟。 */

  var GEN_FIELDS = {
    extract: { temp: "rpGenExtractTemp", max: "rpGenExtractMax" },
    answer: { temp: "rpGenAnswerTemp", max: "rpGenAnswerMax" },
    interpret: { temp: "rpGenInterpretTemp", max: "rpGenInterpretMax" },
  };

  function fillGeneration(defaults) {
    if (!defaults) return;
    state.generation = defaults;
    Object.keys(GEN_FIELDS).forEach(function (stage) {
      var values = defaults[stage] || {};
      var fields = GEN_FIELDS[stage];
      if (values.temperature != null && $(fields.temp)) $(fields.temp).value = values.temperature;
      if (values.max_tokens != null && $(fields.max)) $(fields.max).value = values.max_tokens;
    });
  }

  function generationPayload() {
    var out = {};
    var problem = "";
    Object.keys(GEN_FIELDS).forEach(function (stage) {
      var fields = GEN_FIELDS[stage];
      var temp = Number($(fields.temp) && $(fields.temp).value);
      var max = Number($(fields.max) && $(fields.max).value);
      if (!isFinite(temp) || temp < 0 || temp > 2) {
        problem = tf("rp_gen_bad_temp", "{stage}的温度要在 0–2 之间", { stage: stage });
      } else if (!isFinite(max) || max < 32 || max > 32000) {
        problem = tf("rp_gen_bad_tokens", "{stage}的 max tokens 要在 32–32000 之间", { stage: stage });
      } else {
        out[stage] = { temperature: temp, max_tokens: Math.round(max) };
      }
    });
    var box = $("rpGenError");
    if (box) {
      box.textContent = problem;
      box.classList.toggle("is-error", !!problem);
    }
    return problem ? null : out;
  }

  function renderModelInfo() {
    var host = $("rpModelInfo");
    if (!host) return;
    var name = ($("rpProvider") || {}).value || "";
    var found = state.providers.filter(function (p) { return p.name === name; })[0];
    if (!name) {
      host.textContent = t("rp_model_route", "按配置路由：会用默认模型，具体是哪一个在运行记录里写明。");
      return;
    }
    host.textContent = found && found.model
      ? tf("rp_model_known", "当前模型：{model}{type}", {
          model: found.model,
          type: found.type ? " · " + found.type : "",
        })
      : tf("rp_model_unknown", "当前模型：{name}（配置里没有写明版本）", { name: name });
  }

  function refreshEligibility() {
    clearTimeout(eligibilityTimer);
    var sequence = ++eligibilitySequence;
    if (!state.spec) return;
    state.eligible = null;
    eligibilityTimer = setTimeout(function () {
      api("POST", "/api/research/replication/check", {spec:state.spec, city:$("rpCity").value}).then(function (data) {
        if (sequence !== eligibilitySequence) return;
        state.eligible = data.eligible;
        $("rpEligible").textContent = GAWorldResidentFilters.count(data.eligible, data.total) + (data.eligible < Number($("rpSample").value) ? " · " + t("rp_sample_short", "样本不足，将使用全部符合条件者；可在智能体工作台补充学生样本。") : "");
        syncCost();
      }).catch(function (err) {
        if (sequence === eligibilitySequence) $("rpEligible").textContent = err.message;
      });
    }, 250);
  }

  function setUrl(runId) {
    var query = new URLSearchParams(window.location.search);
    if (runId) query.set("rep", runId);
    else query.delete("rep");
    var text = query.toString();
    window.history.replaceState(null, "", gwURL(window.location.pathname + (text ? "?" + text : "")));
  }

  function setProgress(id, text, mode) {
    var el = $(id);
    el.textContent = text || "";
    el.classList.toggle("is-error", mode === "error");
    el.classList.toggle("is-live", mode === "live");
  }

  function num(value, digits) {
    if (value == null || value === "") return "—";
    var n = Number(value);
    return isFinite(n) ? String(Math.round(n * Math.pow(10, digits)) / Math.pow(10, digits)) : "—";
  }

  function pval(value) {
    return value != null && value < 0.001 ? "p<0.001" : "p=" + num(value, 3);
  }

  function language() {
    return typeof window.getLocale === "function" ? window.getLocale() : "zh-CN";
  }

  function pct(value) {
    return value == null ? "—" : Math.round(Number(value) * 100) + "%";
  }

  function pollJob(jobId, onProgress, onDone, onFail) {
    api("GET", "/api/research/replication/jobs/" + encodeURIComponent(jobId))
      .then(function (job) {
        if (job.status === "running") {
          onProgress(Math.round((job.progress || 0) * 100) + "% · " + (job.message || ""));
          setTimeout(function () {
            pollJob(jobId, onProgress, onDone, onFail);
          }, JOB_POLL_MS);
          return;
        }
        if (job.status !== "done") onFail(job.error || t("rp_failed", "任务失败"));
        else onDone(job.result);
      })
      .catch(function (err) {
        onFail(err.message);
      });
  }

  /* ---------------------------------------------------------------- setup */

  function fillProviders() {
    var select = $("rpProvider");
    var previous = select.value;
    select.innerHTML =
      gwHTML('<option value="">' + esc(t("route_by_config", "按配置路由（默认模型）")) + "</option>" +
      state.providers.map(function (p) {
        return (
          '<option value="' + esc(p.name) + '">' +
          esc(p.name + (p.model ? " · " + p.model : "") + (p.is_default ? " ★" : "")) +
          "</option>"
        );
      }).join(""));
    select.value = previous;
    renderModelInfo();
  }

  function fillCities(selected) {
    var options = ['<option value="">' + esc(t("sg_default_world", "默认世界")) + "</option>"];
    state.cities.forEach(function (c) {
      options.push(
        '<option value="' + esc(c.slug) + '"' + (c.slug === selected ? " selected" : "") + ">" +
        esc(c.display_name || c.name || c.slug) + "</option>"
      );
    });
    $("rpCity").innerHTML = gwHTML(options.join(""));
  }

  function fillSamples() {
    var sizes = SAMPLES.filter(function (n) {
      return n <= state.maxSample;
    });
    $("rpSample").innerHTML = gwHTML(sizes.map(function (n) {
      return '<option value="' + n + '"' + (n === 50 ? " selected" : "") + ">" + n + "</option>";
    }).join(""));
  }

  function cityName(slug) {
    var found = state.cities.filter(function (c) {
      return c.slug === slug;
    })[0];
    return found ? found.display_name || found.name || found.slug : "";
  }

  function refreshRuns() {
    return api("GET", "/api/research/replication").then(function (data) {
      state.runs = data.runs || [];
      state.maxSample = data.max_sample || state.maxSample;
      fillGeneration(data.generation || null);
      renderRuns();
    });
  }

  /* --------------------------------------------------------------- upload */

  function readFile(file) {
    var hint = $("rpFileHint");
    hint.textContent = tf("reading_file", "正在读取 {name}…", { name: file.name });
    var shown = function (text, pages) {
      $("rpText").value = text;
      if (!$("rpTitle").value) $("rpTitle").value = file.name.replace(/\.(pdf|txt|md|markdown)$/i, "");
      hint.textContent = tf("extracted", "已读取 {name}：{pages} 页，{n} 字", { name: file.name, pages: pages, n: text.length });
    };
    var reader = new FileReader();
    reader.onerror = function () {
      hint.textContent = t("read_failed", "读不了这个文件。");
    };
    if (/\.pdf$/i.test(file.name)) {
      reader.onload = function () {
        api("POST", "/api/research/extract", { name: file.name, data: reader.result })
          .then(function (data) {
            shown(data.text || "", data.pages);
          })
          .catch(function (err) {
            hint.textContent = t("extract_failed", "读取失败：") + err.message;
          });
      };
      reader.readAsDataURL(file);
      return;
    }
    reader.onload = function () {
      shown(String(reader.result || ""), 1);
    };
    reader.readAsText(file);
  }

  /* -------------------------------------------------------------- extract */

  function extract() {
    var text = $("rpText").value.trim();
    if (!text) {
      setProgress("rpExtractProgress", t("rp_need_text", "先上传或粘贴一篇文献"), "error");
      return;
    }
    $("rpExtract").disabled = true;
    setProgress("rpExtractProgress", t("rp_extracting", "正在阅读文献…"), "live");
    var generation = generationPayload();
    if (!generation) {
      $("rpExtract").disabled = false;
      setProgress("rpExtractProgress", t("rp_gen_bad", "生成参数不合法，请改正后再抽取。"), "error");
      return;
    }
    api("POST", "/api/research/replication/extract", {
      text: text,
      title: $("rpTitle").value.trim(),
      provider: $("rpProvider").value,
      generation: generation,
    })
      .then(function (data) {
        pollJob(
          data.job_id,
          function (msg) {
            setProgress("rpExtractProgress", msg, "live");
          },
          function (result) {
            $("rpExtract").disabled = false;
            setProgress("rpExtractProgress", t("rp_extracted", "已抽取，请在下方核对。"), "");
            // Which model read the paper travels with the run: it may differ
            // from the one that later plays the residents.
            state.extraction = { generation: result.generation || null, model: result.model || {} };
            setSpec(result.spec);
            $("rpSpecCard").scrollIntoView({ behavior: "smooth" });
          },
          function (error) {
            $("rpExtract").disabled = false;
            setProgress("rpExtractProgress", error, "error");
          }
        );
      })
      .catch(function (err) {
        $("rpExtract").disabled = false;
        setProgress("rpExtractProgress", err.message, "error");
      });
  }

  /* ----------------------------------------------------------- spec editor */

  function setSpec(spec) {
    state.spec = spec;
    if (spec) {
      spec.bias_checks = spec.bias_checks || {order:false, wording:false};
      spec.human_design = spec.human_design || "unknown";
      spec.sampling_probe = spec.sampling_probe || {enabled:false,repeats:3};
      spec.interaction_probe = spec.interaction_probe || {enabled:false,rounds:1,group_size:4};
      spec.identity_probe = spec.identity_probe || {enabled:false,template:"",a:"",b:""};
    }
    $("rpSpecCard").hidden = !spec;
    $("rpRunCard").hidden = !spec;
    renderSpec();
    syncJson();
    syncCost();
    refreshEligibility();
  }

  function syncJson() {
    if (!state.spec) return;
    var copy = JSON.parse(JSON.stringify(state.spec));
    delete copy.warnings;
    delete copy.truncated;
    $("rpJson").value = JSON.stringify(copy, null, 2);
  }

  function itemKeys(item) {
    if (item.kind === "choice") return item.options.slice();
    if (item.kind === "scale") {
      var keys = [];
      for (var v = item.min; v <= item.max; v += 1) keys.push(String(v));
      return keys;
    }
    return [];
  }

  function findResult(itemId, conditionId, groupId) {
    return (state.spec.results || []).filter(function (r) {
      return r.item === itemId && r.condition === conditionId && (r.group || "") === (groupId || "");
    })[0];
  }

  function groupLabel(groupId) {
    var spec = (state.run && state.run.spec) || state.spec;
    var found = ((spec && spec.groups) || []).filter(function (g) {
      return g.id === groupId;
    })[0];
    return found ? found.label : groupId;
  }

  /* 女 · 30–49 岁 · 外地户籍 — how a group filters residents (same wording as the backend). */
  function groupText(g) {
    var parts = g.gender ? [g.gender] : [];
    if (g.age_min != null && g.age_max != null) parts.push(g.age_min + "–" + g.age_max + " " + t("rp_age_unit", "岁"));
    else if (g.age_min != null) parts.push(g.age_min + " " + t("rp_age_up", "岁以上"));
    else if (g.age_max != null) parts.push(g.age_max + " " + t("rp_age_down", "岁以下"));
    if (g.hukou) parts.push(g.hukou + t("rp_hukou_suffix", "户籍"));
    ["education", "student_status", "job"].forEach(function (key) { if (g[key]) parts.push(GAWorldResidentFilters.label(key) + ": " + GAWorldResidentFilters.valueLabel(g[key])); });
    return parts.join(" · ");
  }

  function select(label, path, value, options) {
    return (
      '<label class="rw-field"><span>' + esc(label) + '</span><select data-path="' + path + '">' +
      options.map(function (o) {
        return '<option value="' + esc(o[0]) + '"' + ((value || "") === o[0] ? " selected" : "") + ">" + esc(o[1]) + "</option>";
      }).join("") + "</select></label>"
    );
  }

  function kindLabel(item) {
    if (item.kind === "scale") return tf("rp_kind_scale", "量表 {min}–{max}", { min: item.min, max: item.max });
    if (item.kind === "choice") return tf("rp_kind_choice", "单选 · {n} 项", { n: item.options.length });
    return t("rp_kind_number", "数值") + (item.unit ? " · " + item.unit : "");
  }

  function field(label, path, value, attrs) {
    return (
      '<label class="rw-field"><span>' + esc(label) + "</span><input " + (attrs || 'type="text"') +
      ' data-path="' + path + '" value="' + esc(value == null ? "" : value) + '" /></label>'
    );
  }

  function area(label, path, value, rows) {
    return (
      '<label class="rw-field"><span>' + esc(label) + '</span><textarea class="rp-short" rows="' + (rows || 3) +
      '" data-path="' + path + '">' + esc(value || "") + "</textarea></label>"
    );
  }

  function resultInputs(item, condition, group) {
    var r = findResult(item.id, condition.id, group ? group.id : "") || {};
    var cell = item.id + "|" + condition.id + "|" + (group ? group.id : "");
    var input = function (fieldName, value, placeholder) {
      return (
        '<input type="number" step="any" class="rp-num" data-cell="' + esc(cell) + '" data-field="' + fieldName +
        '" value="' + esc(value == null ? "" : value) + '" placeholder="' + esc(placeholder) + '" />'
      );
    };
    var parts = [];
    if (item.kind === "choice") {
      itemKeys(item).forEach(function (key) {
        var share = r.distribution ? r.distribution[key] : null;
        parts.push(
          '<span class="rp-share"><small>' + esc(key) + "</small>" +
          input("dist:" + key, share == null ? "" : Math.round(share * 1000) / 10, "%") + "</span>"
        );
      });
    } else {
      parts.push(input("mean", r.mean, t("rp_mean", "均值")));
      parts.push(input("sd", r.sd, "SD"));
      if (r.mean == null && r.distribution) parts.push('<small class="rw-hint">' + esc(t("rp_from_dist", "由分布算均值")) + "</small>");
    }
    parts.push(input("n", r.n, "n"));
    parts.push(
      '<input type="text" class="rp-src" data-cell="' + esc(cell) + '" data-field="source" value="' + esc(r.source || "") +
      '" placeholder="' + esc(t("rp_source", "出处")) + '" />'
    );
    return '<div class="rp-cell">' + parts.join("") + "</div>";
  }

  function renderSpec() {
    var spec = state.spec;
    var host = $("rpSpec");
    if (!spec) {
      host.innerHTML = gwHTML("");
      return;
    }
    var html = "";
    if ((spec.warnings || []).length || spec.truncated) {
      var warnings = (spec.warnings || []).slice();
      if (spec.truncated) warnings.push(t("rp_truncated", "文献太长，只读了前一部分；结果在后面的话请只粘贴方法与结果。"));
      html += '<ul class="rw-list rw-warn">' + warnings.map(function (w) {
        return "<li>" + esc(w) + "</li>";
      }).join("") + "</ul>";
    }
    html +=
      '<div class="rp-grid">' +
      field(t("rp_f_title", "研究标题"), "title", spec.title) +
      field(t("rp_f_citation", "文献"), "citation", spec.citation) +
      "</div>" +
      field(t("rp_f_population", "真人受访者"), "population", spec.population) +
      '<div class="rw-row">' +
      field(t("rp_f_human_n", "真人总样本"), "human_n", spec.human_n, 'type="number" min="0"') +
      "</div>" +
      GAWorldResidentFilters.controls(state.educationSchema, spec, "replication", {query:false}) +
      '<p class="rw-hint">' + esc(t("rp_education_note", "入选条件取交集。已获学历与在读阶段不同；未知信息不匹配指定条件。大学生包含大专与本科在读。")) + '</p>' +
      area(t("rp_f_intro", "所有受访者看到的说明"), "intro", spec.intro, 3);

    html += "<h4>" + esc(tf("rp_conditions", "实验条件（{n} 个，第一个是对照组）", { n: spec.conditions.length })) + "</h4>";
    spec.conditions.forEach(function (c, i) {
      html +=
        '<div class="rp-block"><div class="rp-block-head"><b>' + esc(c.id) + "</b>" +
        field(t("rp_f_label", "名称"), "conditions." + i + ".label", c.label) +
        field(t("rp_f_cond_n", "真人 n"), "conditions." + i + ".human_n", c.human_n, 'type="number" min="0"') +
        "</div>" + area(t("rp_f_stimulus", "这一组看到的材料"), "conditions." + i + ".stimulus", c.stimulus, 3) + "</div>";
    });

    var groups = spec.groups || [];
    html += "<h4>" + esc(tf("rp_groups", "人群分组（{n} 个）", { n: groups.length })) + "</h4>" +
      '<p class="rw-hint">' + esc(t("rp_groups_hint", "文献按人群分别报告了结果时在这里定义分组。居民只有性别、年龄和户籍，所以分组只能按这三项划分（可以组合）；按学历、收入等划分的结果无法对应。同一维度的分组里，第一个是参照组。")) + "</p>";
    var anyOption = [["", t("rp_any", "不限")]];
    groups.forEach(function (g, i) {
      var base = "groups." + i + ".";
      html +=
        '<div class="rp-block"><div class="rp-block-head"><b>' + esc(g.id) + "</b>" +
        field(t("rp_f_label", "名称"), base + "label", g.label) +
        select(t("rp_f_gender", "性别"), base + "gender", g.gender, anyOption.concat([["女", t("rp_female", "女")], ["男", t("rp_male", "男")]])) +
        field(t("rp_f_g_age_min", "年龄 ≥"), base + "age_min", g.age_min, 'type="number" min="0"') +
        field(t("rp_f_g_age_max", "年龄 ≤"), base + "age_max", g.age_max, 'type="number" min="0"') +
        select(t("rp_f_hukou", "户籍"), base + "hukou", g.hukou, anyOption.concat([["本地", t("rp_local", "本地")], ["外地", t("rp_nonlocal", "外地")]])) +
        select(GAWorldResidentFilters.label("education"), base + "education", g.education, anyOption.concat(["未知"].concat(state.educationSchema.education_levels || []).map(function(v) { return [v, GAWorldResidentFilters.valueLabel(v)]; }))) +
        select(GAWorldResidentFilters.label("student_status"), base + "student_status", g.student_status, anyOption.concat((state.educationSchema.student_statuses || []).map(function(v) { return [v, GAWorldResidentFilters.valueLabel(v)]; }))) +
        field(GAWorldResidentFilters.label("job"), base + "job", g.job) +
        '<button type="button" class="btn ghost tiny danger" data-del-group="' + i + '">' + esc(t("delete", "删除")) + "</button>" +
        "</div></div>";
    });
    html += '<button type="button" class="btn ghost tiny" data-add-group="1">' + esc(t("rp_add_group", "＋ 添加分组")) + "</button>";

    html += '<div class="rp-block"><h4>' + esc(t("check_settings", "结果检查设置（在运行前确认）")) + '</h4>' +
      '<label>' + esc(t("check_human_design", "文献中真人的条件分配")) + '<select data-path="human_design">' +
      [['unknown',t("check_unknown","未报告 / 未确认")],['between',t("check_between","独立组")],['paired',t("check_paired","同一人重复作答")]].map(function(o){
        return '<option value="' + o[0] + '"' + (spec.human_design === o[0] ? ' selected' : '') + '>' + esc(o[1]) + '</option>';
      }).join('') + '</select></label>' +
      '<label class="ps-check"><input type="checkbox" data-bias-check="order"' + (spec.bias_checks.order ? ' checked' : '') + '>' +
      esc(t("check_order_opt", "复验单选题的选项顺序（额外一组调用）")) + '</label>' +
      '<label class="ps-check"><input type="checkbox" data-bias-check="wording"' + (spec.bias_checks.wording ? ' checked' : '') + '>' +
      esc(t("check_wording_opt", "用下方填写的等义问法复验（额外一组调用）")) + '</label>' +
      '<p class="rw-hint">' + esc(t("check_margin_note", "容许误差使用题目原始单位，须按实际意义在运行前填写；留空不判断等价。请自行确认改写保持原意。")) + '</p></div>';
    html += '<div class="rp-block"><label class="ps-check"><input type="checkbox" data-sampling-enabled' +
      (spec.sampling_probe.enabled ? ' checked' : '') + '>' + esc(t("check_sampling_opt", "重复回答，检查随机波动")) + '</label>' +
      '<div id="rpSamplingFields"><p class="rw-hint">' + esc(t("check_sampling_note", "对原题与已启用的顺序、问法、身份版本各增加独立重复回答，按种子打乱顺序。只用额外重复回答计算每位居民的均值，再比较版本差异；多次回答不算多个居民。不重复互动轮次。")) + '</p>' +
      field(t("check_sampling_repeats", "每版额外重复次数（2–5）"), "sampling_probe.repeats", spec.sampling_probe.repeats, 'type="number" min="2" max="5" step="1"') +
      '<p id="rpSamplingError" class="rw-hint" role="alert"></p></div></div>';
    html += '<div class="rp-block"><label class="ps-check"><input type="checkbox" data-interaction-enabled' +
      (spec.interaction_probe.enabled ? ' checked' : '') + '>' + esc(t("check_interaction_opt", "检查同伴反馈与短期记忆（每轮额外四组调用）")) + '</label>' +
      '<div id="rpInteractionFields"><p class="rw-hint">' + esc(t("check_interaction_note", "同一批居民分别在无历史、只看自己、只看同伴、两者都看四种条件下重新回答，每轮同步更新。按独立小组统计，不写入居民长期记忆；更一致不等于更正确。每个条件至少两人，无法分成每组至少两人的情况会在调用前报错。")) + '</p>' +
      field(t("check_interaction_rounds", "互动轮数（1–3）"), "interaction_probe.rounds", spec.interaction_probe.rounds, 'type="number" min="1" max="3" step="1"') +
      field(t("check_interaction_size", "每组人数上限（2–8）"), "interaction_probe.group_size", spec.interaction_probe.group_size, 'type="number" min="2" max="8" step="1"') +
      '<p id="rpInteractionError" class="rw-hint" role="alert"></p></div></div>';
    html += '<div class="rp-block"><label class="ps-check"><input type="checkbox" data-identity-enabled' +
      (spec.identity_probe.enabled ? ' checked' : '') + '>' + esc(t("check_identity_opt", "检查材料中的身份线索（额外两组调用）")) + '</label>' +
      '<div id="rpIdentityFields"><p class="rw-hint">' + esc(t("check_identity_note", "同一居民分别回答 A、B 两份材料，只替换其中的身份线索，居民自身档案不变。请确认原题和条件材料没有矛盾身份，两个版本仍适合回答同一题。差异不自动等于不公正。")) + '</p>' +
      area(tf("check_identity_template", "共同材料（在替换处写 {token}，只写一次）", {token:"{{identity}}"}), "identity_probe.template", spec.identity_probe.template, 3) +
      field(t("check_identity_a", "A 的身份线索"), "identity_probe.a", spec.identity_probe.a) +
      field(t("check_identity_b", "B 的身份线索"), "identity_probe.b", spec.identity_probe.b) +
      '<p id="rpIdentityError" class="rw-warn" role="status"></p>' +
      '<div class="rp-identity-preview"><b>' + esc(t("check_identity_preview_a", "A 版补充材料")) + '</b><pre id="rpIdentityPreviewA"></pre>' +
      '<b>' + esc(t("check_identity_preview_b", "B 版补充材料")) + '</b><pre id="rpIdentityPreviewB"></pre></div></div></div>';
    html += "<h4>" + esc(tf("rp_items", "题目与真人结果（{n} 题）", { n: spec.items.length })) + "</h4>";
    spec.items.forEach(function (item, i) {
      var rows = spec.conditions.map(function (c) {
        var whole = "<tr><td>" + esc(c.label) + "</td><td>" + resultInputs(item, c, null) + "</td></tr>";
        return whole + groups.map(function (g) {
          return '<tr class="rp-group-row"><td>' + esc(c.label) + " · " + esc(g.label || g.id) + "</td><td>" + resultInputs(item, c, g) + "</td></tr>";
        }).join("");
      }).join("");
      var options = item.kind === "choice"
        ? '<p class="rw-hint">' + esc(item.options.map(function (o, k) { return k + 1 + ". " + o; }).join("　")) + "</p>"
        : item.kind === "scale" && (item.labels || []).length
          ? '<p class="rw-hint">' + esc(item.labels.join(" … ")) + "</p>"
          : "";
      html +=
        '<div class="rp-block"><div class="rp-block-head"><b>' + esc(item.id) + '</b><span class="rw-badge">' +
        esc(kindLabel(item)) + "</span></div>" +
        field(t("rp_f_question", "题目"), "items." + i + ".text", item.text) + options +
        field(t("check_wording_input", "用于复验的等义问法（可选）"), "items." + i + ".audit_wording", item.audit_wording || "") +
        (item.kind === "choice" ? "" : field(t("check_margin_input", "等价性容许误差（原始单位，可选）"), "items." + i + ".equivalence_margin", item.equivalence_margin, 'type="number" min="0" step="any"')) +
        (item.kind === "choice" ? "" : '<div class="rp-sampling-margin">' + field(t("check_sampling_margin", "重复均值对照容许误差（原始单位，可选）"), "items." + i + ".sampling_margin", item.sampling_margin, 'type="number" min="0" step="any"') + '</div>') +
        (item.kind === "choice" ? "" : '<div class="rp-interaction-margin">' + field(t("check_interaction_margin", "互动对照容许误差（原始单位，可选）"), "items." + i + ".interaction_margin", item.interaction_margin, 'type="number" min="0" step="any"') + '</div>') +
        (item.kind === "choice" ? "" : '<div class="rp-identity-margin">' + field(t("check_identity_margin", "身份对照容许误差（原始单位，可选）"), "items." + i + ".identity_margin", item.identity_margin, 'type="number" min="0" step="any"') + '</div>') +
        '<table class="rw-table rp-results"><thead><tr><th>' + esc(t("rp_col_condition", "条件")) + "</th><th>" +
        esc(item.kind === "choice" ? t("rp_human_dist", "真人各选项比例（%）") : t("rp_human_mean", "真人均值 / SD")) +
        " · n · " + esc(t("rp_source", "出处")) + "</th></tr></thead><tbody>" + rows + "</tbody></table></div>";
    });
    host.innerHTML = gwHTML(html);
    syncIdentity();
  }

  function syncIdentity() {
    var view = window.GAWorldIdentityChecks.inspect(state.spec && state.spec.identity_probe);
    if ($("rpIdentityFields")) {
      $("rpIdentityFields").hidden = !view.enabled;
      $("rpIdentityPreviewA").textContent = view.a;
      $("rpIdentityPreviewB").textContent = view.b;
      var errors = {template:tf("check_identity_error_template", "共同材料必须包含且仅包含一个 {token}。", {token:"{{identity}}"}),
        values:t("check_identity_error_values", "请填写两个不同且非空的身份线索，线索内不要再写占位符。"),
        length:t("check_identity_error_length", "共同材料最多 2000 字符，身份线索最多 100 字符，均须为文字。")};
      $("rpIdentityError").textContent = view.error ? errors[view.error] : '';
      document.querySelectorAll('.rp-identity-margin').forEach(function(el){el.hidden = !view.enabled;});
    }
    $("rpRun").disabled = state.running || state.eligible === 0 || !!view.error || !!syncInteraction().error || !!syncSampling().error;
    return view;
  }

  function syncSampling() {
    var settings = (state.spec || {}).sampling_probe || {};
    var enabled = settings.enabled === true;
    var valid = Number.isInteger(settings.repeats) && settings.repeats >= 2 && settings.repeats <= 5;
    var view = {enabled:enabled,error:enabled && !valid, multiplier:enabled && valid ? 1 + settings.repeats : 1};
    if ($("rpSamplingFields")) {
      $("rpSamplingFields").hidden = !enabled;
      $("rpSamplingError").textContent = view.error ? t("check_sampling_error", "额外重复次数须为 2–5 的整数。") : '';
      document.querySelectorAll('.rp-sampling-margin').forEach(function(el){el.hidden = !enabled;});
    }
    return view;
  }

  function syncInteraction() {
    var view = window.GAWorldInteractionChecks.inspect(state.spec && state.spec.interaction_probe);
    if ($("rpInteractionFields")) {
      $("rpInteractionFields").hidden = !view.enabled;
      $("rpInteractionError").textContent = view.error ? t("check_interaction_error", "轮数须为 1–3 的整数，每组人数上限须为 2–8 的整数。") : '';
      document.querySelectorAll('.rp-interaction-margin').forEach(function(el){el.hidden = !view.enabled;});
    }
    return view;
  }

  function setPath(path, raw, isNumber) {
    var keys = path.split(".");
    var target = state.spec;
    for (var i = 0; i < keys.length - 1; i += 1) target = target[keys[i]];
    var value = raw;
    if (isNumber || raw === "") value = raw === "" ? null : Number(raw);
    target[keys[keys.length - 1]] = value;
  }

  function setCell(cell, fieldName, raw) {
    var ids = cell.split("|");
    var result = findResult(ids[0], ids[1], ids[2]);
    if (!result) {
      result = { item: ids[0], condition: ids[1], group: ids[2] || "", mean: null, sd: null, n: null, distribution: null, source: "" };
      state.spec.results.push(result);
    }
    if (fieldName === "source") {
      result.source = raw;
      return;
    }
    var value = raw === "" ? null : Number(raw);
    if (fieldName.indexOf("dist:") === 0) {
      var key = fieldName.slice(5);
      result.distribution = result.distribution || {};
      if (value == null) delete result.distribution[key];
      else result.distribution[key] = value / 100;
      if (!Object.keys(result.distribution).length) result.distribution = null;
      return;
    }
    result[fieldName] = value;
  }

  function onSpecInput(event) {
    var el = event.target;
    if (el.hasAttribute("data-rf")) state.spec[el.dataset.rf] = el.value === "" ? null : el.dataset.rf.indexOf("age_") === 0 ? Number(el.value) : el.value;
    else if (el.hasAttribute("data-sampling-enabled")) state.spec.sampling_probe.enabled = el.checked;
    else if (el.hasAttribute("data-interaction-enabled")) state.spec.interaction_probe.enabled = el.checked;
    else if (el.hasAttribute("data-identity-enabled")) state.spec.identity_probe.enabled = el.checked;
    else if (el.hasAttribute("data-bias-check")) state.spec.bias_checks[el.getAttribute("data-bias-check")] = el.checked;
    else if (el.hasAttribute("data-path")) setPath(el.getAttribute("data-path"), el.value, el.type === "number");
    else if (el.hasAttribute("data-cell")) setCell(el.getAttribute("data-cell"), el.getAttribute("data-field"), el.value);
    else return;
    syncJson();
    syncCost();
    refreshEligibility();
  }

  /* Adding or deleting a group changes the results grid, so the editor is redrawn. */
  function onSpecClick(event) {
    var add = event.target.closest("[data-add-group]");
    var del = event.target.closest("[data-del-group]");
    if (!add && !del) return;
    var groups = (state.spec.groups = state.spec.groups || []);
    if (add) {
      var n = groups.length + 1;
      var used = groups.map(function (g) { return g.id; });
      while (used.indexOf("G" + n) >= 0) n += 1;
      groups.push({ id: "G" + n, label: "", gender: null, age_min: null, age_max: null, hukou: null });
    } else {
      var gone = groups.splice(Number(del.getAttribute("data-del-group")), 1)[0];
      state.spec.results = state.spec.results.filter(function (r) {
        return r.group !== gone.id;
      });
    }
    renderSpec();
    syncJson();
  }

  function applyJson() {
    var parsed;
    try {
      parsed = JSON.parse($("rpJson").value);
    } catch (err) {
      setProgress("rpProgress", t("rp_bad_json", "JSON 格式有误：") + err.message, "error");
      return;
    }
    api("POST", "/api/research/replication/check", { spec: parsed })
      .then(function (data) {
        setSpec(data.spec);
        setProgress("rpProgress", t("rp_json_applied", "已应用，并按规则校验过。"), "");
      })
      .catch(function (err) {
        setProgress("rpProgress", err.message, "error");
      });
  }

  function syncCost() {
    if (!state.spec) return;
    var n = Number($("rpSample").value) || 50;
    var paired = (document.querySelector("input[name=rpDesign]:checked") || {}).value === "paired";
    var calls = paired ? n * state.spec.conditions.length : n;
    var checks = state.spec.bias_checks || {};
    var variants = (checks.order && state.spec.items.some(function(i){return i.kind === "choice";}) ? 1 : 0) +
      (checks.wording && state.spec.items.some(function(i){return !!i.audit_wording;}) ? 1 : 0) + syncIdentity().extraCalls;
    calls = calls * ((1 + variants) * syncSampling().multiplier + syncInteraction().extraCalls) + ($("rpInterpret").checked ? 1 : 0);
    $("rpCost").textContent = tf("rp_cost", "预计 {calls} 次模型调用（按所选样本量估算，实际人数受符合条件的居民数限制）", { calls: calls });
  }

  /* ------------------------------------------------------------------ run */

  function start() {
    if (!state.spec || state.running || syncIdentity().error || syncInteraction().error || syncSampling().error) return;
    var city = $("rpCity").value;
    var seed = $("rpSeed").value.trim();
    var generation = generationPayload();
    if (!generation) {
      setProgress("rpProgress", t("rp_gen_bad", "生成参数不合法，请改正后再运行。"), "error");
      return;
    }
    state.running = true;
    $("rpRun").disabled = true;
    setProgress("rpProgress", t("rp_running", "居民正在作答…"), "live");
    api("POST", "/api/research/replication/run", {
      spec: state.spec,
      city: city,
      city_name: cityName(city),
      sample_size: Number($("rpSample").value) || 50,
      seed: seed ? Number(seed) : null,
      design: (document.querySelector("input[name=rpDesign]:checked") || {}).value || "between",
      provider: $("rpProvider").value,
      interpret: $("rpInterpret").checked,
      language: language(),
      generation: generation,
      extraction_model: (state.extraction || {}).model || {},
    })
      .then(function (data) {
        pollJob(
          data.job_id,
          function (msg) {
            setProgress("rpProgress", msg, "live");
          },
          function (result) {
            state.running = false;
            syncCost();
            setProgress("rpProgress", t("rp_done", "完成。"), "");
            openRun(result.run_id);
            refreshRuns();
          },
          function (error) {
            state.running = false;
            syncCost();
            setProgress("rpProgress", error, "error");
          }
        );
      })
      .catch(function (err) {
        state.running = false;
        syncCost();
        setProgress("rpProgress", err.message, "error");
      });
  }

  function openRun(runId) {
    return api("GET", "/api/research/replication/" + encodeURIComponent(runId))
      .then(function (run) {
        state.run = run;
        setUrl(run.id);
        render();
        renderRuns();
        $("rpResult").scrollIntoView({ behavior: "smooth" });
      })
      .catch(function (err) {
        setProgress("rpProgress", err.message, "error");
      });
  }

  /* --------------------------------------------------------------- render */

  function tile(label, value, note) {
    return (
      '<div class="rp-tile"><span>' + esc(label) + "</span><b>" + esc(value) + "</b>" +
      (note ? "<small>" + esc(note) + "</small>" : "") + "</div>"
    );
  }

  function scoreNote(s) {
    if (!s || (s.score_version || 1) < 2) {
      return t(
        "rp_score_note_old",
        "拟合度分 = 100 ×（有处理效应时：50% 水平准确度 + 50% 效应方向一致率；只有调查时：水平准确度）。" +
          "本记录按旧公式计分，没有计入离散度——居民是不是比真人更一致，这个分数看不出来。"
      );
    }
    var weights = s.score_weights || {};
    var labels = { level: "rp_level", spread: "rp_spread", direction: "rp_direction" };
    var fallbacks = { level: "水平准确度", spread: "离散度准确度", direction: "效应方向一致率" };
    var parts = [];
    ["level", "spread", "direction"].forEach(function (key) {
      if (weights[key] == null) return;
      parts.push(Math.round(weights[key] * 100) + "% " + t(labels[key], fallbacks[key]));
    });
    var note =
      t(
        "rp_score_note",
        "拟合度分 = 100 ×（水平准确度、离散度准确度、效应方向一致率按权重相加）；" +
          "算不出的分量（文献未报离散度、或没有处理效应）不计入，剩下的权重按比例重新分配。" +
          "水平准确度 = 1 − 平均误差；离散度准确度 = 1 − 平均离散度误差。"
      ) + (parts.length ? " " + tf("rp_score_weights", "本次权重：{parts}", { parts: parts.join(" + ") }) : "");
    if ((s.score_version || 1) >= 3 && s.degenerate_ci_cells) {
      note +=
        " " +
        tf(
          "rp_score_collapse_note",
          "其中 {n} 个单元格的居民 95% 区间退化成一个点（全员同答）且未覆盖真人均值；文献未报离散度时，这一项已计入水平准确度。",
          { n: s.degenerate_ci_cells }
        );
    }
    return note;
  }

  /* What this run's seed covered. A seed fixes which residents answer and how
     their answers are grouped — always reproducible. Whether the model's own
     sampling repeats is the provider's business, so the note says which of
     the two the seed can speak for rather than implying the score repeats. */
  function seedScopeNote(run) {
    var scope = run.seed_scope;
    if (!scope) return "";
    if (scope.provider_supports_seed) {
      return (
        '<p class="rw-hint">' +
        esc(
          t(
            "rp_seed_scope_seeded",
            "种子固定了抽哪些居民、怎么分组，并给每次模型调用派了一个格子种子；本次模型的接口接受 seed，已据此请求同一次抽样——但托管端点不承诺逐字复现，同一种子重复运行的拟合度分仍可能有小幅差异。"
          )
        ) +
        "</p>"
      );
    }
    return (
      '<p class="rw-hint">' +
      esc(
        t(
          "rp_seed_scope_unseeded",
          "种子固定了抽哪些居民、怎么分组，并给每次模型调用派了一个格子种子；但本次模型的接口不接受 seed，作答本身无法复现——同一种子重复运行的拟合度分可能不同。"
        )
      ) +
      "</p>"
    );
  }

  /* Why the "human value inside the 95% interval" rate is what it is. A rate of
     0% caused by collapsed intervals (every resident answered the same thing)
     says something about the crowd, not about the humans — a bare 0% would not. */
  function withinNote(s) {
    var collapsed = s.collapsed_ci_cells || 0;
    if (!collapsed) return "";
    var missed = s.degenerate_ci_cells || 0;
    return tf("rp_ci_collapsed_note", "{n} 个单元格的区间退化（居民全员同答），其中 {m} 个未覆盖真人均值", {
      n: collapsed,
      m: missed,
    });
  }

  function dist(distribution) {
    if (!distribution) return "—";
    return Object.keys(distribution).map(function (k) {
      return esc(k) + " " + pct(distribution[k]);
    }).join("<br>");
  }

  /* Human mean as a tick, the agents' 95% interval as a band, on the item's range. */
  function rangeBar(item, cell) {
    if (item.min == null || item.max == null || cell.human_mean == null || !cell.agent.ci) return "";
    var span = item.max - item.min;
    var at = function (v) {
      return Math.max(0, Math.min(100, ((v - item.min) / span) * 100));
    };
    var low = at(cell.agent.ci[0]);
    var high = at(cell.agent.ci[1]);
    return (
      '<div class="rp-bar" title="' + esc(item.min + "–" + item.max) + '"><span class="rp-bar-ci" style="left:' + low +
      "%;width:" + Math.max(1, high - low) + '%"></span><span class="rp-bar-agent" style="left:' + at(cell.agent.mean) +
      '%"></span><span class="rp-bar-human" style="left:' + at(cell.human_mean) + '%"></span></div>'
    );
  }

  function cellsTable(run) {
    var items = {};
    run.spec.items.forEach(function (i) {
      items[i.id] = i;
    });
    var labels = {};
    run.spec.conditions.forEach(function (c) {
      labels[c.id] = c.label;
    });
    var rows = run.comparison.cells.map(function (cell) {
      var item = items[cell.item];
      var human = cell.human;
      var humanText, agentText;
      if (item.kind === "choice") {
        humanText = human ? dist(human.distribution) : "";
        agentText = dist(cell.agent.distribution);
      } else {
        humanText = human ? num(cell.human_mean, 2) + (human.sd ? " <small>(SD " + num(human.sd, 2) + ")</small>" : "") : "";
        agentText = cell.agent.mean == null ? "—" : num(cell.agent.mean, 2) + " <small>(SD " + num(cell.agent.sd, 2) + ")</small>";
      }
      var inside = cell.within_ci == null ? "" : cell.within_ci
        ? '<span class="ps-good">' + esc(t("rp_yes", "是")) + "</span>"
        : '<span class="rw-warn">' + esc(t("rp_no", "否")) + "</span>";
      // A collapsed interval means every resident answered the same thing, so
      // the human mean could not land inside it. That is a defect of the crowd,
      // not a statement about the humans, and the cell has to say which it is.
      if (cell.ci_degenerate) {
        inside += ' <small class="rw-warn">' + esc(t("rp_ci_collapsed", "区间退化（全员同答）")) + "</small>";
      }
      var spread = cell.spread_error == null
        ? (cell.sd_ratio == null ? "—" : " <small>SD ×" + num(cell.sd_ratio, 2) + "</small>")
        : num(cell.spread_error, 3) + (cell.sd_ratio == null ? "" : " <small>SD ×" + num(cell.sd_ratio, 2) + "</small>");
      // A leaked cell means the residents were handed this question's answer, so
      // whatever they said back says nothing about them: the cell stays visible,
      // but it is marked as outside the score.
      var leak = cell.leak
        ? ' <small class="rw-warn">' + esc(t("rp_cell_leak", "（材料含真人结果，不计入评分）")) + "</small>"
        : "";
      return (
        "<tr><td><b>" + esc(item.id) + "</b> " + esc(item.text) + "</td><td>" + esc(labels[cell.condition]) + "</td><td>" +
        (human ? humanText : '<span class="rw-hint">' + esc(t("rp_unreported", "未报告")) + "</span>") + "</td><td>" + agentText +
        " <small>n=" + cell.agent.n + "</small>" + rangeBar(item, cell) + "</td><td>" +
        (cell.diff == null ? "—" : num(cell.diff, 2)) + "</td><td>" + (cell.error == null ? "—" : num(cell.error, 3)) + leak +
        (cell.tvd != null && item.kind !== "choice" ? " <small>TVD " + num(cell.tvd, 3) + "</small>" : "") + "</td><td>" + spread +
        "</td><td>" + inside + "</td></tr>"
      );
    });
    return (
      '<div class="rw-table-scroll"><table class="rw-table rw-rep-cells"><thead><tr><th>' + esc(t("rp_col_item", "题目")) + "</th><th>" +
      esc(t("rp_col_condition", "条件")) + "</th><th>" + esc(t("rp_col_human", "真人")) + "</th><th>" +
      esc(t("rp_col_agent", "智能体")) + "</th><th>" + esc(t("rp_col_diff", "差值")) + "</th><th>" +
      esc(t("rp_col_error", "误差 0–1")) + "</th><th>" + esc(t("rp_col_spread", "离散度误差")) +
      "</th><th>" + esc(t("rp_col_inside", "真人值在 95% 区间内")) +
      "</th></tr></thead><tbody>" + rows.join("") + "</tbody></table></div>" +
      '<p class="rw-hint">' + esc(t("rp_bar_note", "条形：浅色带 = 居民均值的 95% 区间，深色 = 居民均值，红线 = 真人均值。")) + "</p>" +
      '<p class="rw-hint">' + esc(t("rp_spread_note", "离散度误差按两个标准差之比算：0 = 居民和真人一样分散，1 = 完全对不上；SD × 是居民 SD ÷ 真人 SD。")) + "</p>"
    );
  }

  function effectsTable(run) {
    var labels = {};
    run.spec.conditions.forEach(function (c) {
      labels[c.id] = c.label;
    });
    var rows = run.comparison.effects.map(function (e) {
      return (
        "<tr><td><b>" + esc(e.item) + "</b>" + (e.option ? " <small>" + esc(tf("rp_option_share", "「{option}」占比", { option: e.option })) + "</small>" : "") +
        "</td><td>" + esc(labels[e.condition]) + " vs " + esc(labels[e.base]) + "</td><td>" + num(e.human_effect, 3) +
        (e.human_p != null ? " <small>" + pval(e.human_p) + "</small>" : "") + "</td><td>" + num(e.agent_effect, 3) +
        (e.agent_p != null ? " <small>" + pval(e.agent_p) + "</small>" : "") + "</td><td>" +
        (e.ratio == null ? "—" : num(e.ratio, 2)) + '</td><td><span class="rw-verdict ' + (VERDICT_CLASS[e.verdict] || "") + '">' +
        esc(t("rp_v_" + e.verdict, VERDICT_TEXT[e.verdict] || e.verdict)) + "</span></td></tr>"
      );
    });
    return (
      '<div class="rw-table-scroll"><table class="rw-table"><thead><tr><th>' + esc(t("rp_col_item", "题目")) + "</th><th>" +
      esc(t("rp_col_contrast", "对比")) + "</th><th>" + esc(t("rp_col_h_effect", "真人效应")) + "</th><th>" +
      esc(t("rp_col_a_effect", "智能体效应")) + "</th><th>" + esc(t("rp_col_ratio", "效应比")) + "</th><th>" +
      esc(t("rp_col_verdict", "判定")) + "</th></tr></thead><tbody>" + rows.join("") + "</tbody></table></div>" +
      '<p class="rw-hint">' + esc(t("rp_effect_note", "效应 = 处理组 − 对照组，按题目量程归一（单选题为真人变化最大的那个选项的占比变化）；p 值为正态近似。")) + "</p>"
    );
  }

  function answersBlock(run) {
    var names = {};
    run.residents.forEach(function (r) {
      names[r.agent_id] = r;
    });
    var labels = {};
    run.spec.conditions.forEach(function (c) {
      labels[c.id] = c.label;
    });
    var items = run.spec.items;
    var rows = run.responses.map(function (r) {
      var who = names[r.agent_id] || {};
      var cells = !r.ok ? '<td class="rw-warn" colspan="' + items.length + '">' + esc(r.error || t("ps_no_answer", "无有效回答")) + "</td>" : items.map(function (item) {
        var v = r.answers[item.id];
        if (v == null) return '<td class="rw-warn">—</td>';
        return "<td>" + esc(item.kind === "choice" ? item.options[v] : num(v, 2)) + "</td>";
      }).join("");
      return (
        "<tr><td>" + esc(who.name || "#" + r.agent_id) + "<br><small>" + esc([who.age, who.gender, who.job].filter(Boolean).join(" · ")) +
        "</small></td><td>" + esc(labels[r.condition]) + "</td>" + cells + "</tr>"
      );
    }).join("");
    return (
      '<details class="rw-material"><summary>' + esc(tf("rp_answers", "每位居民的回答（{n} 份）", { n: run.responses.length })) +
      '</summary><div class="rw-table-scroll"><table class="rw-table"><thead><tr><th>' + esc(t("ps_col_resident", "居民")) + "</th><th>" +
      esc(t("rp_col_condition", "条件")) + "</th>" + items.map(function (i) {
        return "<th>" + esc(i.id) + "</th>";
      }).join("") + "</tr></thead><tbody>" + rows + "</tbody></table></div></details>"
    );
  }

  function scopeNote(s) {
    var scope = s.score_scope;
    if (!scope) return "/ 100";
    var cover = s.coverage || {};
    var partial = cover.cells_with_human != null && cover.cells_with_human < cover.cells_possible;
    if (!partial && !s.leaked_cells) return "/ 100";
    return "/ 100 · " + tf("rp_scope_note", "仅覆盖 {scope}", { scope: scope });
  }

  function coverageBanner(s) {
    var cover = s.coverage || {};
    var warnings = cover.warnings || [];
    var leaks = s.leak_findings || [];
    if (!warnings.length && !leaks.length) return "";
    var lines = warnings.slice();
    leaks.forEach(function (leak) {
      lines.push(
        tf(
          "rp_leak_line",
          "材料泄漏：{item}/{condition} 的真人{kind} {value} 出现在{where}里（{excerpt}）——居民拿到了答案，这一格不计入评分",
          {
            item: leak.item,
            condition: leak.condition,
            kind: leak.kind,
            value: leak.value,
            where: leak.where,
            excerpt: leak.excerpt,
          }
        )
      );
    });
    var head = cover.cells_possible
      ? tf("rp_scope_head", "这个分数只覆盖 {compared}/{possible} 个单元格（题目×条件）", {
          compared: s.cells_compared || 0,
          possible: cover.cells_possible,
        })
      : "";
    return (
      '<p class="rw-hint rw-warn">' + esc(head) + "</p>" +
      '<ul class="rw-list rw-warn">' + lines.map(function (line) { return "<li>" + esc(line) + "</li>"; }).join("") + "</ul>"
    );
  }

  /* What answered, and with which parameters. A model name is a label, not a
     version: the endpoint and config fingerprints are what say whether this
     run can be compared with another one, so they are shown next to it. */
  function modelBlock(run) {
    var model = run.model || ((run.check_protocol || {}).model) || {};
    var generation = run.generation || {};
    var stages = [
      { key: "extract", label: t("rp_gen_extract", "读取文献") },
      { key: "answer", label: t("rp_gen_answer", "居民作答") },
      { key: "interpret", label: t("rp_gen_interpret", "解读偏差") },
    ];
    var rows = stages.map(function (stage) {
      var values = generation[stage.key];
      if (!values) return "";
      return (
        '<div class="rp-model-row"><span>' + esc(stage.label) + "</span><b>" +
        esc(tf("rp_gen_values", "温度 {temp} · max tokens {max}", {
          temp: values.temperature, max: values.max_tokens,
        })) + "</b></div>"
      );
    }).join("");
    var version = model.model || t("rp_model_unknown_name", "未记录模型名");
    var provider = model.provider || "";
    var line = provider ? provider + " · " + version : version;
    // The model that read the paper may differ from the one that played the
    // residents; the record keeps both, so the page shows both.
    var reader = run.extraction_model || {};
    var readerLine = "";
    if (reader.model || reader.provider) {
      readerLine =
        '<div class="rp-model-row"><span>' + esc(t("rp_run_reader", "读文献的模型")) + "</span><b>" +
        esc((reader.provider || "") + (reader.provider && reader.model ? " · " : "") + (reader.model || "")) +
        "</b></div>";
    }
    return (
      '<div class="rp-model"><h4>' + esc(t("rp_run_model_title", "本次运行的模型与参数")) + "</h4>" +
      '<div class="rp-model-row"><span>' + esc(t("rp_run_model", "模型")) + "</span><b>" + esc(line) + "</b></div>" +
      readerLine +
      (model.backend_type
        ? '<div class="rp-model-row"><span>' + esc(t("rp_run_backend", "后端")) + "</span><b>" + esc(model.backend_type) + "</b></div>"
        : "") +
      (model.endpoint_hash
        ? '<div class="rp-model-row"><span>' + esc(t("rp_run_endpoint", "端点指纹")) + "</span><b>" + esc(model.endpoint_hash) + "</b></div>"
        : "") +
      (model.config_hash
        ? '<div class="rp-model-row"><span>' + esc(t("rp_run_config", "配置指纹")) + "</span><b>" + esc(model.config_hash) + "</b></div>"
        : "") +
      rows +
      '<p class="rw-hint">' + esc(t("rp_run_model_hint", "模型名只是标识；端点与配置指纹用来核对两次运行是否用了同一个模型版本。参数随数据包一起导出。")) + "</p>" +
      "</div>"
    );
  }

  function render() {
    var host = $("rpResult");
    var run = state.run;
    if (!run) {
      host.hidden = true;
      return;
    }
    host.hidden = false;
    var s = run.comparison.summary;
    var design = run.design === "paired" ? t("rp_design_paired_short", "配对") : t("rp_design_between_short", "组间");
    var html =
      '<div class="rw-result-head"><div><h3>' + esc(run.title) + '</h3><div class="rw-badges">' +
      '<span class="rw-badge">' + esc(run.city_name || run.city || t("sg_default_world", "默认世界")) + "</span>" +
      '<span class="rw-badge">' + esc(tf("rp_sample_meta", "{n} 位居民 · {design} · 种子 {seed}", { n: run.residents.length, design: design, seed: run.seed })) + "</span>" +
      (run.failed ? '<span class="rw-badge feas-low">' + esc(tf("rp_failed_n", "{n} 份无效回答", { n: run.failed })) + "</span>" : "") +
      '</div></div><div class="rw-actions">' +
      '<button class="btn ghost tiny" id="rpReuse">' + esc(t("rp_reuse", "用这份设计再跑")) + "</button>" +
      '<button class="btn ghost tiny" id="rpExport">' + esc(t("download", "下载 Markdown")) + "</button>" +
      '<button class="btn ghost tiny" id="rpBundle">' + esc(t("rp_export_bundle", "下载完整数据包（ZIP）")) + "</button>" +
      '<button class="btn ghost tiny" id="rpEvidence">' + esc(t("check_download", "下载完整检查记录")) + "</button>" +
      '<button class="btn ghost tiny danger" id="rpDelete">' + esc(t("delete", "删除")) + "</button></div></div>";
    if (run.residents.length < run.requested_sample) {
      html += '<p class="rw-hint rw-warn">' + esc(tf("rp_capped", "请求 {asked} 位，城市里符合年龄范围的居民只有 {eligible} 位，已全部使用。", {
        asked: run.requested_sample, eligible: run.eligible,
      })) + "</p>";
    }
    html += seedScopeNote(run);
    html += modelBlock(run);
    if (run.spec.citation || run.spec.population) {
      html += '<p class="rw-hint">' + esc(run.spec.citation) + (run.spec.population ? " · " + esc(t("rp_f_population", "真人受访者")) + "：" + esc(run.spec.population) : "") + "</p>";
    }
    html += window.GAWorldResultChecks.render(run.comparison.result_checks);
    html += coverageBanner(s);
    html +=
      '<div class="rp-tiles">'  +
      tile(t("rp_score", "拟合度分"), s.score == null ? "—" : num(s.score, 1), scopeNote(s)) +
      tile(t("rp_level", "水平准确度"), num(s.level_accuracy, 3), tf("rp_cells_n", "{n} 个单元格", { n: s.cells_compared })) +
      tile(t("rp_spread", "离散度准确度"), num(s.spread_accuracy, 3), tf("rp_spread_n", "{n} 个可比单元格", { n: s.spread_cells_compared || 0 })) +
      tile(t("rp_within", "真人值落在 95% 区间"), pct(s.within_ci_rate), withinNote(s)) +
      tile(t("rp_level_r", "单元格相关 r"), num(s.level_r, 2), "") +
      (s.effects_judged
        ? tile(t("rp_direction", "效应方向一致"), pct(s.direction_rate), tf("rp_effects_n", "{n} 个效应", { n: s.effects_judged })) +
          tile(t("rp_replication", "方向一致且显著"), pct(s.replication_rate), "") +
          tile(t("rp_effect_r", "效应相关 r"), num(s.effect_r, 2), "")
        : "") +
      "</div>" +
      '<p class="rw-hint">' + esc(scoreNote(s)) + "</p>";
    html += '<p class="rw-hint">' + esc(t("check_legacy_note", "拟合度、方向一致和真人均值落入 AI 区间均不证明效应等价；请查看逐项真人参照检查。")) + '</p>';
    if (run.comparison.effects.length) html += "<h4>" + esc(t("rp_effects", "处理效应：智能体复现了文献的发现吗")) + "</h4>" + effectsTable(run);
    html += "<h4>" + esc(t("rp_cells", "逐题对照")) + "</h4>" + cellsTable(run);
    html += '<h4>' + esc(t("check_rows", "逐项结果检查")) + '</h4>';
    ["cells", "effects", "group_cells", "group_gaps"].forEach(function(key){
      (run.comparison[key] || []).forEach(function(row){html += window.GAWorldResultChecks.render(row.result_checks);});
    });
    html += answersBlock(run);
    html += '<p class="rw-hint">' + esc(t("rp_disclaimer", "居民回答由大模型按每位居民的档案扮演生成。拟合度衡量这批居民与文献中真人的接近程度——文献人群和城市居民不同（国家、年龄、职业），差异一部分来自人群本身。")) + "</p>";
    host.innerHTML = gwHTML(html);

    $("rpReuse").addEventListener("click", function () {
      setSpec(JSON.parse(JSON.stringify(run.spec)));
      if (run.city != null) $("rpCity").value = run.city;
      $("rpSpecCard").scrollIntoView({ behavior: "smooth" });
    });
    $("rpExport").addEventListener("click", exportRun);
    $("rpBundle").addEventListener("click", exportBundle);
    $("rpEvidence").addEventListener("click", function () {
      var url = URL.createObjectURL(new Blob([JSON.stringify(run, null, 2)], {type:"application/json;charset=utf-8"}));
      var link = document.createElement("a");
      link.href = url;
      link.download = run.id + "-checks.json";
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    });
    $("rpDelete").addEventListener("click", deleteRun);
  }

  function exportRun() {
    api("GET", "/api/research/replication/" + encodeURIComponent(state.run.id) + "/export")
      .then(function (data) {
        var blob = new Blob([data.markdown], { type: "text/markdown;charset=utf-8" });
        var link = document.createElement("a");
        link.href = gwURL(URL.createObjectURL(blob));
        link.download = data.filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () {
          URL.revokeObjectURL(link.href);
        }, 1000);
      })
      .catch(function (err) {
        window.alert(err.message);
      });
  }

  /* The whole run as a ZIP: the report, the per-resident answers, the personas,
     the model-call log and the distribution charts. */
  function exportBundle() {
    api("GET", "/api/research/replication/" + encodeURIComponent(state.run.id) + "/bundle")
      .then(function (data) {
        var binary = atob(data.bytes_base64 || "");
        var bytes = new Uint8Array(binary.length);
        for (var index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
        var blob = new Blob([bytes], { type: "application/zip" });
        var link = document.createElement("a");
        link.href = gwURL(URL.createObjectURL(blob));
        link.download = data.filename || "replication-data.zip";
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () {
          URL.revokeObjectURL(link.href);
        }, 1000);
      })
      .catch(function (err) {
        window.alert(err.message);
      });
  }

  function deleteRun() {
    if (!window.confirm(t("rp_confirm_delete", "删除这条拟合记录？"))) return;
    api("POST", "/api/research/replication/" + encodeURIComponent(state.run.id) + "/delete", {})
      .then(function () {
        state.run = null;
        setUrl("");
        render();
        refreshRuns();
      })
      .catch(function (err) {
        window.alert(err.message);
      });
  }

  function renderRuns() {
    var host = $("rpRuns");
    host.innerHTML = gwHTML(state.runs.length
      ? state.runs.map(function (r) {
          var active = state.run && state.run.id === r.id ? " is-active" : "";
          var meta = (r.city_name || t("sg_default_world", "默认世界")) + " · " +
            tf("rp_run_meta", "{n} 人 · 拟合度 {score}", { n: r.residents, score: r.score == null ? "—" : r.score });
          return (
            '<button type="button" class="rw-history-item' + active + '" data-run="' + esc(r.id) + '"><span class="rw-hist-title">' +
            esc(r.title) + '</span><span class="rw-hist-meta">' + esc(meta) + "</span></button>"
          );
        }).join("")
      : '<p class="rw-hint">' + esc(t("rp_no_runs", "还没有拟合记录")) + "</p>");
  }

  /* ----------------------------------------------------------------- init */

  function init() {
    if (!$("rwPaneReplication")) return;
    var query = new URLSearchParams(window.location.search);
    if (query.get("seat")) return; // serious-game player view: nothing else on the page
    fillSamples();
    $("rpFile").addEventListener("change", function (event) {
      var file = event.target.files && event.target.files[0];
      if (file) readFile(file);
      event.target.value = "";
    });
    $("rpExtract").addEventListener("click", extract);
    $("rpSpec").addEventListener("input", onSpecInput);
    $("rpSpec").addEventListener("change", onSpecInput);
    $("rpSpec").addEventListener("click", onSpecClick);
    $("rpJsonApply").addEventListener("click", applyJson);
    $("rpSample").addEventListener("change", function () { syncCost(); refreshEligibility(); });
    $("rpCity").addEventListener("change", refreshEligibility);
    $("rpInterpret").addEventListener("change", syncCost);
    document.querySelectorAll("input[name=rpDesign]").forEach(function (radio) {
      radio.addEventListener("change", syncCost);
    });
    $("rpRun").addEventListener("click", start);
    $("rpProvider").addEventListener("change", renderModelInfo);
    $("rpRuns").addEventListener("click", function (event) {
      var item = event.target.closest("[data-run]");
      if (item) openRun(item.getAttribute("data-run"));
    });
    document.addEventListener("locale-changed", function () {
      renderRuns();
      renderSpec();
      syncCost();
      render();
    });
    fillCities("");
    api("GET", "/api/population/schema").then(function (schema) { state.educationSchema = schema; renderSpec(); }).catch(function () {});
    api("GET", "/api/research/context")
      .then(function (context) {
        state.providers = context.providers || [];
        fillProviders();
      })
      .catch(function () {
        fillProviders();
      });
    api("GET", "/api/city/catalogue")
      .then(function (data) {
        state.cities = data.cities || [];
        fillCities(data.selected || "");
      })
      .catch(function () {});
    refreshRuns()
      .then(function () {
        fillSamples();
        var runId = query.get("rep");
        if (runId) openRun(runId);
      })
      .catch(function (err) {
        setProgress("rpProgress", err.message, "error");
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
