
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
    replicated: "复现：方向一致且显著",
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

  var state = { providers: [], cities: [], runs: [], spec: null, run: null, maxSample: 500 };

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
    api("POST", "/api/research/replication/extract", {
      text: text,
      title: $("rpTitle").value.trim(),
      provider: $("rpProvider").value,
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
    $("rpSpecCard").hidden = !spec;
    $("rpRunCard").hidden = !spec;
    renderSpec();
    syncJson();
    syncCost();
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
      field(t("rp_f_age_min", "最小年龄（居民按此筛选）"), "age_min", spec.age_min, 'type="number" min="0"') +
      field(t("rp_f_age_max", "最大年龄"), "age_max", spec.age_max, 'type="number" min="0"') +
      "</div>" +
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
        '<button type="button" class="btn ghost tiny danger" data-del-group="' + i + '">' + esc(t("delete", "删除")) + "</button>" +
        "</div></div>";
    });
    html += '<button type="button" class="btn ghost tiny" data-add-group="1">' + esc(t("rp_add_group", "＋ 添加分组")) + "</button>";

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
        '<table class="rw-table rp-results"><thead><tr><th>' + esc(t("rp_col_condition", "条件")) + "</th><th>" +
        esc(item.kind === "choice" ? t("rp_human_dist", "真人各选项比例（%）") : t("rp_human_mean", "真人均值 / SD")) +
        " · n · " + esc(t("rp_source", "出处")) + "</th></tr></thead><tbody>" + rows + "</tbody></table></div>";
    });
    host.innerHTML = gwHTML(html);
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
    if (el.hasAttribute("data-path")) setPath(el.getAttribute("data-path"), el.value, el.type === "number");
    else if (el.hasAttribute("data-cell")) setCell(el.getAttribute("data-cell"), el.getAttribute("data-field"), el.value);
    else return;
    syncJson();
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
    $("rpCost").textContent = tf("rp_cost", "约 {calls} 次模型调用（不超过城市里符合年龄的居民数）", { calls: calls });
  }

  /* ------------------------------------------------------------------ run */

  function start() {
    if (!state.spec) return;
    var city = $("rpCity").value;
    var seed = $("rpSeed").value.trim();
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
    })
      .then(function (data) {
        pollJob(
          data.job_id,
          function (msg) {
            setProgress("rpProgress", msg, "live");
          },
          function (result) {
            $("rpRun").disabled = false;
            setProgress("rpProgress", t("rp_done", "完成。"), "");
            openRun(result.run_id);
            refreshRuns();
          },
          function (error) {
            $("rpRun").disabled = false;
            setProgress("rpProgress", error, "error");
          }
        );
      })
      .catch(function (err) {
        $("rpRun").disabled = false;
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
      return (
        "<tr><td><b>" + esc(item.id) + "</b> " + esc(item.text) + "</td><td>" + esc(labels[cell.condition]) + "</td><td>" +
        (human ? humanText : '<span class="rw-hint">' + esc(t("rp_unreported", "未报告")) + "</span>") + "</td><td>" + agentText +
        " <small>n=" + cell.agent.n + "</small>" + rangeBar(item, cell) + "</td><td>" +
        (cell.diff == null ? "—" : num(cell.diff, 2)) + "</td><td>" + (cell.error == null ? "—" : num(cell.error, 3)) +
        (cell.tvd != null && item.kind !== "choice" ? " <small>TVD " + num(cell.tvd, 3) + "</small>" : "") + "</td><td>" + inside + "</td></tr>"
      );
    });
    return (
      '<div class="rw-table-scroll"><table class="rw-table"><thead><tr><th>' + esc(t("rp_col_item", "题目")) + "</th><th>" +
      esc(t("rp_col_condition", "条件")) + "</th><th>" + esc(t("rp_col_human", "真人")) + "</th><th>" +
      esc(t("rp_col_agent", "智能体")) + "</th><th>" + esc(t("rp_col_diff", "差值")) + "</th><th>" +
      esc(t("rp_col_error", "误差 0–1")) + "</th><th>" + esc(t("rp_col_inside", "真人值在 95% 区间内")) +
      "</th></tr></thead><tbody>" + rows.join("") + "</tbody></table></div>" +
      '<p class="rw-hint">' + esc(t("rp_bar_note", "条形：浅色带 = 居民均值的 95% 区间，深色 = 居民均值，红线 = 真人均值。")) + "</p>"
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
      '<button class="btn ghost tiny danger" id="rpDelete">' + esc(t("delete", "删除")) + "</button></div></div>";
    if (run.residents.length < run.requested_sample) {
      html += '<p class="rw-hint rw-warn">' + esc(tf("rp_capped", "请求 {asked} 位，城市里符合年龄范围的居民只有 {eligible} 位，已全部使用。", {
        asked: run.requested_sample, eligible: run.eligible,
      })) + "</p>";
    }
    if (run.spec.citation || run.spec.population) {
      html += '<p class="rw-hint">' + esc(run.spec.citation) + (run.spec.population ? " · " + esc(t("rp_f_population", "真人受访者")) + "：" + esc(run.spec.population) : "") + "</p>";
    }
    html +=
      '<div class="rp-tiles">' +
      tile(t("rp_score", "拟合度分"), s.score == null ? "—" : num(s.score, 1), "/ 100") +
      tile(t("rp_level", "水平准确度"), num(s.level_accuracy, 3), tf("rp_cells_n", "{n} 个单元格", { n: s.cells_compared })) +
      tile(t("rp_within", "真人值落在 95% 区间"), pct(s.within_ci_rate), "") +
      tile(t("rp_level_r", "单元格相关 r"), num(s.level_r, 2), "") +
      (s.effects_judged
        ? tile(t("rp_direction", "效应方向一致"), pct(s.direction_rate), tf("rp_effects_n", "{n} 个效应", { n: s.effects_judged })) +
          tile(t("rp_replication", "显著复现"), pct(s.replication_rate), "") +
          tile(t("rp_effect_r", "效应相关 r"), num(s.effect_r, 2), "")
        : "") +
      "</div>" +
      '<p class="rw-hint">' + esc(t("rp_score_note", "拟合度分 = 100 ×（有处理效应时：50% 水平准确度 + 50% 效应方向一致率；只有调查时：水平准确度）。水平准确度 = 1 − 平均误差。")) + "</p>";
    if (run.comparison.effects.length) html += "<h4>" + esc(t("rp_effects", "处理效应：智能体复现了文献的发现吗")) + "</h4>" + effectsTable(run);
    html += "<h4>" + esc(t("rp_cells", "逐题对照")) + "</h4>" + cellsTable(run);
    html += answersBlock(run);
    html += '<p class="rw-hint">' + esc(t("rp_disclaimer", "居民回答由大模型按每位居民的档案扮演生成。拟合度衡量这批居民与文献中真人的接近程度——文献人群和城市居民不同（国家、年龄、职业），差异一部分来自人群本身。")) + "</p>";
    host.innerHTML = gwHTML(html);

    $("rpReuse").addEventListener("click", function () {
      setSpec(JSON.parse(JSON.stringify(run.spec)));
      if (run.city != null) $("rpCity").value = run.city;
      $("rpSpecCard").scrollIntoView({ behavior: "smooth" });
    });
    $("rpExport").addEventListener("click", exportRun);
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
    $("rpSpec").addEventListener("click", onSpecClick);
    $("rpJsonApply").addEventListener("click", applyJson);
    $("rpSample").addEventListener("change", syncCost);
    document.querySelectorAll("input[name=rpDesign]").forEach(function (radio) {
      radio.addEventListener("change", syncCost);
    });
    $("rpRun").addEventListener("click", start);
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
