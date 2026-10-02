/* 研究工作台 · 政策仿真与优化 — 选城市 + 写政策（可选候选政策）→ 居民逐个反应 → 评估 + 修改建议。
 *
 * POST /api/research/policy/run 开一个后台任务，轮询 /api/research/policy/jobs/<id>；
 * 跑完的记录在 /api/research/policy/<id>，当前打开的记录记在 ?run= 里。
 * Tab 切换由 serious-game.js 统一管理。
 */
(function () {
  "use strict";

  var JOB_POLL_MS = 1500;
  var SAMPLES = [6, 9, 12, 15, 20, 24, 30];

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

  var state = { providers: [], cities: [], runs: [], run: null, busy: false };

  function setUrl(runId) {
    var query = new URLSearchParams(window.location.search);
    if (runId) query.set("run", runId);
    else query.delete("run");
    var text = query.toString();
    window.history.replaceState(null, "", window.location.pathname + (text ? "?" + text : ""));
  }

  function setProgress(text, mode) {
    var el = $("psProgress");
    el.textContent = text || "";
    el.classList.toggle("is-error", mode === "error");
    el.classList.toggle("is-live", mode === "live");
  }

  function versionLabel(key) {
    if (key === "A") return t("ps_ver_a", "原政策");
    if (key === "B") return t("ps_ver_b", "候选政策");
    if (key === "R") return t("ps_ver_r", "推荐修订版");
    return key;
  }

  function pct(value) {
    return Math.round((Number(value) || 0) * 100) + "%";
  }

  /* ----------------------------------------------------------------- setup */

  function fillProviders() {
    var select = $("psProvider");
    var previous = select.value;
    select.innerHTML =
      '<option value="">' + esc(t("route_by_config", "按配置路由（默认模型）")) + "</option>" +
      state.providers.map(function (p) {
        return (
          '<option value="' + esc(p.name) + '">' +
          esc(p.name + (p.model ? " · " + p.model : "") + (p.is_default ? " ★" : "")) +
          "</option>"
        );
      }).join("");
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
    $("psCity").innerHTML = options.join("");
  }

  function cityName(slug) {
    var found = state.cities.filter(function (c) {
      return c.slug === slug;
    })[0];
    return found ? found.display_name || found.name || found.slug : "";
  }

  function refreshRuns() {
    return api("GET", "/api/research/policy").then(function (data) {
      state.runs = data.runs || [];
      renderRuns();
    });
  }

  /* ------------------------------------------------------------------- run */

  function start() {
    var policy = $("psPolicy").value.trim();
    if (!policy) {
      setProgress(t("ps_need_policy", "先写一段政策描述"), "error");
      return;
    }
    var city = $("psCity").value;
    state.busy = true;
    $("psRun").disabled = true;
    setProgress(t("ps_running", "正在仿真…（每位居民每个版本一次模型调用）"), "live");
    api("POST", "/api/research/policy/run", {
      policy: policy,
      candidate: $("psCandidate").value.trim(),
      city: city,
      city_name: cityName(city),
      sample_size: Number($("psSample").value) || 12,
      verify: $("psVerify").checked,
      provider: $("psProvider").value,
    })
      .then(function (data) {
        pollJob(data.job_id);
      })
      .catch(function (err) {
        done(err.message, "error");
      });
  }

  function done(text, mode) {
    state.busy = false;
    $("psRun").disabled = false;
    setProgress(text, mode);
  }

  function pollJob(jobId) {
    api("GET", "/api/research/policy/jobs/" + encodeURIComponent(jobId))
      .then(function (job) {
        if (job.status === "running") {
          setProgress(Math.round((job.progress || 0) * 100) + "% · " + (job.message || ""), "live");
          setTimeout(function () {
            pollJob(jobId);
          }, JOB_POLL_MS);
          return;
        }
        if (job.status !== "done") {
          done(job.error || t("ps_failed", "仿真失败"), "error");
          return;
        }
        done(t("ps_done", "仿真完成。"), "");
        openRun(job.result.run_id);
        refreshRuns();
      })
      .catch(function (err) {
        done(err.message, "error");
      });
  }

  function openRun(runId) {
    return api("GET", "/api/research/policy/" + encodeURIComponent(runId))
      .then(function (run) {
        state.run = run;
        setUrl(run.id);
        render();
        renderRuns();
      })
      .catch(function (err) {
        setProgress(err.message, "error");
      });
  }

  /* ---------------------------------------------------------------- render */

  function list(items) {
    if (!items || !items.length) return "";
    return '<ul class="rw-list">' + items.map(function (i) {
      return "<li>" + esc(i) + "</li>";
    }).join("") + "</ul>";
  }

  function metricsTable(run) {
    var head = [
      t("ps_col_version", "版本"), t("ps_col_n", "有效样本"), t("ps_col_support", "支持"),
      t("ps_col_oppose", "反对"), t("ps_col_hurt", "日子变差"), t("ps_col_msupport", "支持度 −2~2"),
      t("ps_col_wellbeing", "生活 −5~5"), t("ps_col_finance", "钱包 −5~5"),
      t("ps_col_compliance", "遵从 0~100"), t("ps_col_score", "综合分"),
    ];
    var rows = run.policies.map(function (p) {
      var m = run.metrics[p.key] || {};
      var best = run.best === p.key;
      var name = esc(versionLabel(p.key)) + (best ? ' <span class="rw-badge ps-best">' + esc(t("ps_best", "推荐")) + "</span>" : "");
      if (!m.n) {
        return "<tr><td>" + name + '</td><td colspan="9">' + esc(t("ps_no_answers", "没有有效回答")) + "</td></tr>";
      }
      return (
        "<tr" + (best ? ' class="ps-best-row"' : "") + "><td>" + name + "</td><td>" + m.n +
        (m.failed ? ' <span class="rw-warn">(' + esc(tf("ps_failed_n", "{n} 无效", { n: m.failed })) + ")</span>" : "") +
        "</td><td>" + pct(m.support_rate) + "</td><td>" + pct(m.oppose_rate) + "</td><td>" + pct(m.hurt_rate) +
        "</td><td>" + m.mean_support + "</td><td>" + m.mean_wellbeing + "</td><td>" + m.mean_finance +
        "</td><td>" + m.mean_compliance + '</td><td><div class="ps-score"><span class="ps-score-bar" style="width:' +
        Math.max(0, Math.min(100, m.score)) + '%"></span><b>' + m.score + "</b></div></td></tr>"
      );
    });
    return (
      '<table class="rw-table"><thead><tr>' + head.map(function (h) {
        return "<th>" + esc(h) + "</th>";
      }).join("") + "</tr></thead><tbody>" + rows.join("") + "</tbody></table>"
    );
  }

  var AXES = [
    ["age_band", "ps_axis_age", "年龄段"],
    ["gender", "ps_axis_gender", "性别"],
    ["hukou", "ps_axis_hukou", "户籍"],
  ];

  function groupsTable(run) {
    var head = "<th>" + esc(t("ps_col_group", "分组")) + "</th>" + run.policies.map(function (p) {
      return "<th>" + esc(versionLabel(p.key)) + "<br><small>" + esc(t("ps_group_cell", "支持度 / 生活")) + "</small></th>";
    }).join("");
    var rows = [];
    AXES.forEach(function (axis) {
      var names = {};
      run.policies.forEach(function (p) {
        Object.keys(((run.groups[p.key] || {})[axis[0]]) || {}).forEach(function (n) {
          names[n] = true;
        });
      });
      Object.keys(names).sort().forEach(function (name) {
        var cells = run.policies.map(function (p) {
          var row = (((run.groups[p.key] || {})[axis[0]]) || {})[name];
          if (!row) return "<td>—</td>";
          var cls = row.mean_wellbeing < 0 ? ' class="rw-warn"' : "";
          return "<td" + cls + ">" + row.mean_support + " / " + row.mean_wellbeing + " <small>(" + row.n + ")</small></td>";
        }).join("");
        rows.push("<tr><td>" + esc(t(axis[1], axis[2])) + " · " + esc(name) + "</td>" + cells + "</tr>");
      });
    });
    var gaps = run.policies.map(function (p) {
      var g = (run.groups[p.key] || {}).widest_gap || {};
      if (!g.gap) return "";
      return "<li>" + esc(tf("ps_gap_line", "{version}：{axis}之间生活感受差距最大（{low} 比 {high} 低 {gap}）", {
        version: versionLabel(p.key),
        axis: t((AXES.filter(function (a) { return a[0] === g.axis; })[0] || [])[1] || "", g.axis),
        low: g.low,
        high: g.high,
        gap: g.gap,
      })) + "</li>";
    }).join("");
    return (
      '<table class="rw-table"><thead><tr>' + head + "</tr></thead><tbody>" + rows.join("") + "</tbody></table>" +
      (gaps ? '<ul class="rw-list ps-gaps">' + gaps + "</ul>" : "")
    );
  }

  function reactionsBlock(run) {
    var names = {};
    run.residents.forEach(function (r) {
      names[r.agent_id] = r;
    });
    return run.policies.map(function (p) {
      var rows = (run.reactions[p.key] || []).map(function (r) {
        var who = names[r.agent_id] || {};
        var label = esc(who.name || "#" + r.agent_id) + "<br><small>" + esc([who.age, who.gender, who.job].filter(Boolean).join(" · ")) + "</small>";
        if (!r.ok) return "<tr><td>" + label + '</td><td colspan="7" class="rw-warn">' + esc(t("ps_no_answer", "无有效回答")) + "</td></tr>";
        return (
          "<tr><td>" + label + "</td><td>" + r.support + "</td><td>" + r.wellbeing + "</td><td>" + r.finance +
          "</td><td>" + r.compliance + "</td><td>" + esc(r.behavior) + "</td><td>" + esc(r.concern) +
          "</td><td>" + esc(r.suggestion) + "</td></tr>"
        );
      }).join("");
      return (
        '<details class="rw-material"><summary>' + esc(tf("ps_reactions_of", "{version} · 每位居民的反应", { version: versionLabel(p.key) })) +
        '</summary><table class="rw-table"><thead><tr><th>' + esc(t("ps_col_resident", "居民")) + "</th><th>" +
        esc(t("ps_col_s", "支持")) + "</th><th>" + esc(t("ps_col_w", "生活")) + "</th><th>" + esc(t("ps_col_f", "钱包")) +
        "</th><th>" + esc(t("ps_col_c", "遵从")) + "</th><th>" + esc(t("ps_col_behavior", "会怎么做")) + "</th><th>" +
        esc(t("ps_col_concern", "担心")) + "</th><th>" + esc(t("ps_col_suggestion", "建议")) + "</th></tr></thead><tbody>" +
        rows + "</tbody></table></details>"
      );
    }).join("");
  }

  function verdictLine(run) {
    var a = (run.metrics.A || {}).score;
    var r = run.metrics.R;
    if (!r || !r.n) return "";
    var delta = Math.round((r.score - a) * 10) / 10;
    var key = delta > 0 ? "ps_verdict_better" : "ps_verdict_worse";
    var fallback = delta > 0
      ? "修订版在同一批居民上的综合分比原政策高 {delta} 分。"
      : "修订版没有跑赢原政策（综合分差 {delta}）——建议只作参考，或调整后再试。";
    return '<p class="rw-summary ' + (delta > 0 ? "ps-good" : "rw-warn") + '">' + esc(tf(key, fallback, { delta: delta })) + "</p>";
  }

  function render() {
    var host = $("psResult");
    var run = state.run;
    if (!run) {
      host.hidden = true;
      return;
    }
    host.hidden = false;
    var rec = run.recommendation || {};
    var policies = run.policies.map(function (p) {
      return "<dt>" + esc(versionLabel(p.key)) + '</dt><dd class="ps-policy-text">' + esc(p.text) + "</dd>";
    }).join("");
    var mods = (rec.modifications || []).map(function (m) {
      return (
        '<li class="rw-step"><div class="rw-step-title">' + esc(m.change) + "</div>" +
        (m.reason ? '<p class="rw-step-detail">' + esc(t("ps_reason", "理由")) + "：" + esc(m.reason) + "</p>" : "") +
        (m.addresses ? '<p class="rw-step-detail">' + esc(t("ps_addresses", "回应")) + "：" + esc(m.addresses) + "</p>" : "") +
        "</li>"
      );
    }).join("");

    var html =
      '<div class="rw-result-head"><div><h3>' + esc(run.title) + '</h3><div class="rw-badges">' +
      '<span class="rw-badge">' + esc(run.city_name || run.city || t("sg_default_world", "默认世界")) + "</span>" +
      '<span class="rw-badge">' + esc(tf("ps_sample_meta", "{n} 位居民 · 种子 {seed}", { n: run.residents.length, seed: run.seed })) + "</span>" +
      (run.best ? '<span class="rw-badge feas-high">' + esc(tf("ps_best_meta", "推荐：{version}", { version: versionLabel(run.best) })) + "</span>" : "") +
      '</div></div><div class="rw-actions">' +
      (rec.revised_policy ? '<button class="btn ghost tiny" id="psIterate">' + esc(t("ps_iterate", "以修订版为原政策再优化")) + "</button>" : "") +
      '<button class="btn ghost tiny" id="psExport">' + esc(t("download", "下载 Markdown")) + "</button>" +
      '<button class="btn ghost tiny danger" id="psDelete">' + esc(t("delete", "删除")) + "</button></div></div>" +
      "<h4>" + esc(t("ps_policies", "政策版本")) + '</h4><dl class="rw-dl">' + policies + "</dl>" +
      "<h4>" + esc(t("ps_results", "仿真结果")) + "</h4>" + metricsTable(run) + verdictLine(run) +
      '<p class="rw-hint">' + esc(t("ps_score_note", "综合分 0–100 = 支持度 35% + 生活 30% + 钱包 15% + 遵从 20%（各自归一到 0–1）。")) + "</p>";

    if (rec.assessment || (rec.effects || []).length) {
      html += "<h4>" + esc(t("ps_assessment", "效果评估")) + '</h4><p class="rw-summary">' + esc(rec.assessment) + "</p>";
      if ((rec.effects || []).length) html += "<h4>" + esc(t("ps_effects", "主要效果")) + "</h4>" + list(rec.effects);
      if ((rec.risks || []).length) html += "<h4>" + esc(t("ps_risks", "风险与被忽视的人群")) + "</h4>" + list(rec.risks);
      if (rec.comparison) html += "<h4>" + esc(t("ps_comparison", "原政策与候选政策对比")) + '</h4><p class="rw-summary">' + esc(rec.comparison) + "</p>";
    }
    if (mods) html += "<h4>" + esc(t("ps_modifications", "推荐的修改")) + '</h4><ol class="rw-steps">' + mods + "</ol>";
    if (rec.revised_policy) {
      html += "<h4>" + esc(t("ps_revised", "修订后的政策")) + '</h4><p class="rw-summary ps-policy-text">' + esc(rec.revised_policy) + "</p>";
    }
    if (rec.expected) html += "<h4>" + esc(t("ps_expected", "预期")) + '</h4><p class="rw-rationale">' + esc(rec.expected) + "</p>";
    html += "<h4>" + esc(t("ps_groups", "分组对比")) + "</h4>" + groupsTable(run);
    html += "<h4>" + esc(t("ps_reactions", "居民反应")) + "</h4>" + reactionsBlock(run);
    html += '<p class="rw-hint">' + esc(t("ps_disclaimer", "居民反应由大模型按每位居民的档案扮演生成，是对政策反应的情景推演，不是民意调查。")) + "</p>";
    host.innerHTML = html;

    var iterate = $("psIterate");
    if (iterate) {
      iterate.addEventListener("click", function () {
        $("psPolicy").value = rec.revised_policy;
        $("psCandidate").value = "";
        if (run.city != null) $("psCity").value = run.city;
        $("psForm").scrollIntoView({ behavior: "smooth" });
        setProgress(t("ps_iterate_hint", "修订版已填入「政策描述」，可以再改一改，然后开始下一轮仿真。"), "");
      });
    }
    $("psExport").addEventListener("click", exportRun);
    $("psDelete").addEventListener("click", deleteRun);
  }

  function exportRun() {
    api("GET", "/api/research/policy/" + encodeURIComponent(state.run.id) + "/export")
      .then(function (data) {
        var blob = new Blob([data.markdown], { type: "text/markdown;charset=utf-8" });
        var link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
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
    if (!window.confirm(t("ps_confirm_delete", "删除这条仿真记录？"))) return;
    api("POST", "/api/research/policy/" + encodeURIComponent(state.run.id) + "/delete", {})
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
    var host = $("psRuns");
    host.innerHTML = state.runs.length
      ? state.runs.map(function (r) {
          var active = state.run && state.run.id === r.id ? " is-active" : "";
          var meta = (r.city_name || t("sg_default_world", "默认世界")) + " · " +
            tf("ps_run_meta", "{n} 人 · {versions} 个版本", { n: r.residents, versions: r.versions.length }) +
            (r.best ? " · " + versionLabel(r.best) + " " + (r.best_score != null ? r.best_score : "") : "");
          return (
            '<button type="button" class="rw-history-item' + active + '" data-run="' + esc(r.id) + '"><span class="rw-hist-title">' +
            esc(r.title) + '</span><span class="rw-hist-meta">' + esc(meta) + "</span></button>"
          );
        }).join("")
      : '<p class="rw-hint">' + esc(t("ps_no_runs", "还没有仿真记录")) + "</p>";
  }

  /* ------------------------------------------------------------------ init */

  function init() {
    if (!$("rwPanePolicy")) return;
    var query = new URLSearchParams(window.location.search);
    if (query.get("seat")) return; // serious-game player view: nothing else on the page
    $("psSample").innerHTML = SAMPLES.map(function (n) {
      return '<option value="' + n + '"' + (n === 12 ? " selected" : "") + ">" + n + "</option>";
    }).join("");
    $("psRun").addEventListener("click", start);
    $("psRuns").addEventListener("click", function (event) {
      var item = event.target.closest("[data-run]");
      if (item) openRun(item.getAttribute("data-run"));
    });
    document.addEventListener("locale-changed", function () {
      renderRuns();
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
        var runId = query.get("run");
        if (runId) openRun(runId);
      })
      .catch(function (err) {
        setProgress(err.message, "error");
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
