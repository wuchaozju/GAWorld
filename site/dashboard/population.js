/* Population Studio — 造一座小镇，然后按群体模拟它。
 *
 * 五步：群体定义 → 人口结构 → 状态分布 → 群体模拟 → 验证与复核。
 *
 * 三个刻意的设计：
 *
 * - 旋钮定义来自 `GET /api/population/schema`，不在这里再抄一份。九维状态变量在本仓库
 *   已经被声明了两次（dashboard_server.py 与 studio.js）且靠手工同步，人口旋钮不该变成第三份。
 * - 图表全部手写 SVG。site/dashboard 没有构建步骤也没有 vendored 图表库，为几个坐标轴引入
 *   CDN 依赖会让 dashboard 失去离线可用性。
 * - 每个主操作都有**面板内的按钮**，不依赖页脚按钮改 label。靠 label 变化承载主操作
 *   是很差的可发现性——用户找不到就会以为功能坏了。
 */
(function () {
  "use strict";

  var state = {
    step: 1,
    schema: null,
    spec: null,
    preview: null,
    population: null,
    groupRun: null,
    verdict: null,
    written: [],
    roster: { query: "", limit: 20, open: null },
    run: {
      days: 7,
      budget: 20,
      audit: 0.03,
      coupling: 0.7,
      useLlm: false,
      provider: "",
      seed: 1,
    },
    busy: false,
  };

  function $(id) {
    return document.getElementById(id);
  }

  function esc(text) {
    return String(text == null ? "" : text).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function pct(v) {
    return Math.round(Number(v) * 100) + "%";
  }

  function money(v) {
    return Number(v).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  }

  /* ------------------------------------------------------------------- api */

  /** Every failure ends up visible and always clears `busy`.
   *
   *  The previous version had no `.catch`: one failed request left `busy`
   *  stuck true and every later click became a silent no-op — which looks
   *  exactly like "the button does nothing". */
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
            return { error: __f("pop.not_json", { status: res.status }) };
          })
          .then(function (payload) {
            if (!res.ok && !payload.error) payload.error = "HTTP " + res.status;
            return payload;
          });
      })
      .catch(function (err) {
        return { error: __f("pop.no_backend", { error: (err && err.message) ? err.message : err }) };
      });
  }

  function fail(message) {
    state.busy = false;
    setProgress("❌ " + message, 0, true);
    render();
  }

  /* ------------------------------------------------------------------ spec */

  function deepGet(obj, path) {
    var parts = path.split(".");
    var cur = obj;
    for (var i = 0; i < parts.length; i++) {
      if (cur == null) return undefined;
      cur = cur[parts[i]];
    }
    return cur;
  }

  function deepSet(obj, path, value) {
    var parts = path.split(".");
    var cur = obj;
    for (var i = 0; i < parts.length - 1; i++) {
      if (typeof cur[parts[i]] !== "object" || cur[parts[i]] === null) cur[parts[i]] = {};
      cur = cur[parts[i]];
    }
    cur[parts[parts.length - 1]] = value;
  }

  /* ---------------------------------------------------------------- charts */

  function svg(width, height, inner) {
    return (
      '<svg viewBox="0 0 ' + width + " " + height + '" preserveAspectRatio="xMidYMid meet">' +
      inner + "</svg>"
    );
  }

  function agePyramid(bins) {
    if (!bins || !bins.length) return "<p class='pop-hint'>" + esc(__("pop.no_data")) + "</p>";
    var W = 320, H = 200, mid = W / 2, rowH = Math.max(4, (H - 20) / bins.length);
    var max = 1;
    bins.forEach(function (b) { max = Math.max(max, b.male, b.female); });
    var parts = [];
    bins.forEach(function (b, i) {
      var y = 10 + i * rowH;
      var lw = (b.male / max) * (mid - 26);
      var rw = (b.female / max) * (mid - 26);
      parts.push('<rect x="' + (mid - lw) + '" y="' + y + '" width="' + lw + '" height="' + (rowH - 1) + '" fill="#2563eb" opacity="0.75"><title>' + esc(__f("pop.pyramid_male", { age: b.age_from + "-" + b.age_to, count: b.male })) + "</title></rect>");
      parts.push('<rect x="' + mid + '" y="' + y + '" width="' + rw + '" height="' + (rowH - 1) + '" fill="#db2777" opacity="0.7"><title>' + esc(__f("pop.pyramid_female", { age: b.age_from + "-" + b.age_to, count: b.female })) + "</title></rect>");
      if (i % 3 === 0) {
        parts.push('<text x="' + mid + '" y="' + (y + rowH - 2) + '" font-size="8" text-anchor="middle" fill="#6b7280">' + b.age_from + "</text>");
      }
    });
    parts.push('<text x="6" y="9" font-size="9" fill="#2563eb">' + esc(__("pop.axis_male")) + "</text>");
    parts.push('<text x="' + (W - 26) + '" y="9" font-size="9" fill="#db2777">' + esc(__("pop.axis_female")) + "</text>");
    return svg(W, H, parts.join(""));
  }

  function lorenz(points) {
    if (!points || !points.length) return "<p class='pop-hint'>" + esc(__("pop.no_data")) + "</p>";
    var W = 300, H = 200, pad = 24;
    var path = points.map(function (p, i) {
      var x = pad + p.population_share * (W - pad * 2);
      var y = H - pad - p.income_share * (H - pad * 2);
      return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
    }).join(" ");
    return svg(W, H,
      '<line x1="' + pad + '" y1="' + (H - pad) + '" x2="' + (W - pad) + '" y2="' + pad + '" stroke="#9ca3af" stroke-dasharray="3 3"><title>' + esc(__("pop.lorenz_equal")) + '</title></line>' +
      '<path d="' + path + '" fill="none" stroke="#2563eb" stroke-width="2"><title>' + esc(__("pop.lorenz_actual")) + '</title></path>' +
      '<line x1="' + pad + '" y1="' + (H - pad) + '" x2="' + (W - pad) + '" y2="' + (H - pad) + '" stroke="#d1d5db"/>' +
      '<line x1="' + pad + '" y1="' + pad + '" x2="' + pad + '" y2="' + (H - pad) + '" stroke="#d1d5db"/>' +
      '<text x="' + (W / 2) + '" y="' + (H - 6) + '" font-size="8" text-anchor="middle" fill="#6b7280">' + esc(__("pop.lorenz_axis")) + "</text>");
  }

  function barChart(rows, opts) {
    opts = opts || {};
    if (!rows || !rows.length) return "<p class='pop-hint'>" + esc(__("pop.no_data")) + "</p>";
    var W = 300, H = 180, pad = 26;
    var max = 1;
    rows.forEach(function (r) { max = Math.max(max, r.value); });
    var bw = (W - pad * 2) / rows.length;
    var parts = [];
    rows.forEach(function (r, i) {
      var h = (r.value / max) * (H - pad * 2);
      var x = pad + i * bw;
      parts.push('<rect x="' + (x + 1) + '" y="' + (H - pad - h) + '" width="' + (bw - 2) + '" height="' + h + '" fill="' + (opts.color || "#2563eb") + '" opacity="0.8"><title>' + esc(opts.unit
        ? r.label + opts.unit + "：" + __f("pop.unit_people", { count: r.value })
        : r.label + "：" + r.value) + "</title></rect>");
      if (rows.length <= 26 || i % 2 === 0) {
        parts.push('<text x="' + (x + bw / 2) + '" y="' + (H - pad + 10) + '" font-size="8" text-anchor="middle" fill="#6b7280">' + esc(r.label) + "</text>");
      }
    });
    parts.push('<line x1="' + pad + '" y1="' + (H - pad) + '" x2="' + (W - pad) + '" y2="' + (H - pad) + '" stroke="#d1d5db"/>');
    return svg(W, H, parts.join(""));
  }

  function stateRadar(stats, keys) {
    var W = 300, H = 260, cx = W / 2, cy = H / 2 + 6, R = 84;
    var n = keys.length;
    function point(i, value) {
      var a = (Math.PI * 2 * i) / n - Math.PI / 2;
      return [cx + Math.cos(a) * R * value, cy + Math.sin(a) * R * value];
    }
    function poly(getter, fill, stroke, op) {
      var pts = keys.map(function (k, i) {
        return point(i, Math.max(0, Math.min(1, getter(k)))).map(function (v) { return v.toFixed(1); }).join(",");
      });
      return '<polygon points="' + pts.join(" ") + '" fill="' + fill + '" fill-opacity="' + op + '" stroke="' + stroke + '" stroke-width="1.5"/>';
    }
    var rings = [0.25, 0.5, 0.75, 1].map(function (r) {
      return '<circle cx="' + cx + '" cy="' + cy + '" r="' + R * r + '" fill="none" stroke="#e5e7eb"/>';
    }).join("");
    var labels = keys.map(function (k, i) {
      var p = point(i, 1.2);
      var s = stats[k] || {};
      return '<text x="' + p[0].toFixed(1) + '" y="' + p[1].toFixed(1) + '" font-size="8" text-anchor="middle" fill="#6b7280">' + esc(label(k, "zh")) + "<title>" + esc(__f("pop.stat_summary", {
        label: label(k, "zh"),
        mean: (s.mean || 0).toFixed(2),
        p25: (s.p25 || 0).toFixed(2),
        p75: (s.p75 || 0).toFixed(2),
      })) + "</title></text>";
    }).join("");
    var band = poly(function (k) { return (stats[k] || {}).p75 || 0; }, "#2563eb", "#93c5fd", 0.15) +
      poly(function (k) { return (stats[k] || {}).p25 || 0; }, "#ffffff", "#93c5fd", 0.9);
    var mean = poly(function (k) { return (stats[k] || {}).mean || 0; }, "none", "#2563eb", 1);
    return svg(W, H, rings + band + mean + labels);
  }

  /* -------------------------------------------------------------- 文案定义 */

  /** 「中文 English」双语标注。标签来自后端 schema 的 `labels`，
   *  不在这里再抄一份——面板之前就是因为一半中文一半英文标识符才显得混乱。
   *  `zhOnly` 用于图表这类空间紧张的地方，英文放在悬停里。 */
  function label(key, mode) {
    var l = (state.schema && state.schema.labels && state.schema.labels[key]) || null;
    if (!l) return key;
    if (mode === "zh") return l.zh;
    if (mode === "en") return l.en;
    return l.zh + " " + l.en;
  }

  function labelHtml(key) {
    var l = (state.schema && state.schema.labels && state.schema.labels[key]) || null;
    if (!l) return esc(key);
    return esc(l.zh) + ' <em class="pop-key">' + esc(l.en) + "</em>";
  }

  /* The help texts live in the locale files; these map a state variable or a
     dotted config path to its key suffix. They used to hold the Chinese prose
     directly, which froze whatever language was current when this file was
     evaluated — and the locale JSON has not arrived by then. */
  var STATE_HELP_KEYS = [
    "emotion", "stress", "econ_security", "city_identity", "policy_sensitivity",
    "platform_dependence", "risk_preference", "voice_propensity", "mobility_intent",
  ];

  var KNOB_HELP_KEYS = {
    "size": "size",
    "seed": "seed",
    "name": "name",
    "demography.median_age": "median_age",
    "demography.share_under_18": "share_under_18",
    "demography.share_over_65": "share_over_65",
    "demography.migrant_share": "migrant_share",
    "household.mean_size": "mean_size",
    "household.share_single_person": "share_single_person",
    "household.share_multigen": "share_multigen",
    "education_work.tertiary_rate": "tertiary_rate",
    "education_work.employment_rate": "employment_rate",
    "income.median_monthly": "median_monthly",
    "income.gini": "gini",
    "psychology.state_sd": "state_sd",
  };

  var RUN_HELP_KEYS = ["days", "budget", "audit", "coupling", "useLlm", "provider"];

  function stateHelp(key) {
    return STATE_HELP_KEYS.indexOf(key) >= 0 ? __("pop.state." + key) : "";
  }

  function knobHelp(path) {
    var suffix = KNOB_HELP_KEYS[path];
    return suffix ? __("pop.knob." + suffix) : "";
  }

  function runHelp(key) {
    return RUN_HELP_KEYS.indexOf(key) >= 0 ? __("pop.run." + key) : "";
  }



  function help(text) {
    return text ? ' <span class="pop-q" title="' + esc(text.replace(/\*\*/g, "")) + '">?</span>' : "";
  }

  /* ------------------------------------------------------------- field 构件 */

  function fieldSlider(path, label, min, max, step, fmt) {
    var value = deepGet(state.spec, path);
    return (
      '<div class="pop-field"><label><span>' + esc(label) + help(knobHelp(path)) +
      '</span><span class="pop-value" data-out="' + path + '">' + esc(fmt ? fmt(value) : value) + "</span></label>" +
      '<input type="range" data-path="' + path + '" data-fmt="' + (fmt === pct ? "pct" : fmt === money ? "money" : "raw") +
      '" min="' + min + '" max="' + max + '" step="' + step + '" value="' + value + '" title="' + esc(knobHelp(path).replace(/\*\*/g, "")) + '" /></div>'
    );
  }

  function fieldNumber(path, label, min, max, step) {
    var value = deepGet(state.spec, path);
    return (
      '<div class="pop-field"><label><span>' + esc(label) + help(knobHelp(path)) + "</span></label>" +
      '<input type="number" data-path="' + path + '" min="' + min + '" max="' + max + '" step="' + step +
      '" value="' + value + '" title="' + esc(knobHelp(path).replace(/\*\*/g, "")) + '" /></div>'
    );
  }

  function actionBar(html) {
    return '<div class="pop-actionbar">' + html + "</div>";
  }

  /* --------------------------------------------------------------- step 1 */

  function renderStep1() {
    var desc = (state.schema.preset_descriptions || {})[state.spec.preset];
    var presets = (state.schema.presets || []).map(function (p) {
      var d = (state.schema.preset_descriptions || {})[p] || {};
      return '<option value="' + esc(p) + '"' + (state.spec.preset === p ? " selected" : "") + ">" +
        esc(d.title ? d.title + "（" + p + "）" : p) + "</option>";
    }).join("");

    var descBox = desc
      ? '<div class="pop-presetcard"><h4>' + esc(desc.title) + "</h4><p>" + esc(desc.summary) +
        '</p><p class="pop-usewhen"><b>' + esc(__("pop.presetcard_usewhen")) + "</b>" +
        esc(desc.use_when) + "</p></div>"
      : "";

    return (
      '<div class="pop-card">' +
      "<h2>" + esc(__("pop.step1_title")) + "</h2>" +
      '<p class="pop-lede">' + esc(__("pop.step1_lede")) + "</p>" +
      '<div class="pop-grid">' +
      '<div class="pop-field"><label><span>' + esc(__("pop.field_preset")) + "</span>" +
        help(__("pop.field_preset_help")) + "</label>" +
      '<select data-path="preset">' + presets + "</select></div>" +
      fieldNumber("size", __("pop.field_size"), 20, 5000, 10) +
      fieldNumber("seed", __("pop.field_seed"), 0, 2147483647, 1) +
      '<div class="pop-field"><label><span>' + esc(__("pop.field_name")) + "</span>" +
        help(knobHelp("name")) + "</label>" +
      '<input type="text" data-path="name" value="' + esc(state.spec.name) + '" /></div>' +
      "</div>" + descBox +
      '<div class="pop-seedbox"><b>' + esc(__("pop.seedbox_title")) + "</b>" +
      esc(__("pop.seedbox_body")) + "</div>" +
      actionBar('<button class="btn" data-go="2">' + esc(__("pop.next_structure")) + "</button>") +
      "</div>"
    );
  }

  /* --------------------------------------------------------------- step 2 */

  function renderStep2() {
    var busy = state.busy;
    return (
      '<div class="pop-card">' +
      "<h2>" + esc(__("pop.step2_title")) + "</h2>" +
      '<p class="pop-lede">' + esc(__("pop.step2_lede")) + "</p>" +
      '<div class="pop-grid">' +
      fieldSlider("demography.median_age", __("pop.slider_median_age"), 18, 65, 1) +
      fieldSlider("demography.share_under_18", __("pop.slider_under_18"), 0, 0.4, 0.01, pct) +
      fieldSlider("demography.share_over_65", __("pop.slider_over_65"), 0, 0.5, 0.01, pct) +
      fieldSlider("demography.migrant_share", __("pop.slider_migrant"), 0, 0.9, 0.01, pct) +
      fieldSlider("household.mean_size", __("pop.slider_mean_size"), 1, 6, 0.1) +
      fieldSlider("household.share_single_person", __("pop.slider_single"), 0, 0.8, 0.01, pct) +
      fieldSlider("household.share_multigen", __("pop.slider_multigen"), 0, 0.6, 0.01, pct) +
      fieldSlider("education_work.tertiary_rate", __("pop.slider_tertiary"), 0, 1, 0.01, pct) +
      fieldSlider("education_work.employment_rate", __("pop.slider_employment"), 0, 1, 0.01, pct) +
      fieldSlider("income.median_monthly", __("pop.slider_income"), 1000, 40000, 100, money) +
      fieldSlider("income.gini", __("pop.slider_gini"), 0.15, 0.65, 0.01) +
      "</div>" +
      actionBar(
        '<button class="btn primary" id="popGenerate"' + (busy ? " disabled" : "") + ">" +
        esc(busy ? __("pop.generating")
          : state.population ? __("pop.regenerate")
          : __f("pop.generate_n", { count: state.spec.size })) +
        "</button>" +
        (state.population
          ? '<button class="btn ghost" data-go="3">' + esc(__("pop.next_states")) + "</button>" : "") +
        '<span class="pop-actionhint">' +
        esc(__(state.population ? "pop.generated_hint" : "pop.generate_hint")) +
        "</span>"
      ) +
      "</div>" + (state.population ? achievedCard() + rosterCard() : "")
    );
  }

  function achievedCard() {
    var rep = state.population.report;
    var rows = Object.keys(rep.achieved).map(function (k) {
      var e = rep.achieved[k];
      var rel = Math.abs(e.target) > 1e-9 ? Math.abs(e.delta) / Math.abs(e.target) : 0;
      var color = rel > 0.1 ? "#dc2626" : rel > 0.05 ? "#d97706" : "#16a34a";
      var note = __(rel > 0.1 ? "pop.gap_far" : rel > 0.05 ? "pop.gap_some" : "pop.gap_ok");
      return "<tr><td>" + labelHtml(k) + '</td><td class="num">' + e.target +
        '</td><td class="num">' + e.achieved + '</td><td class="num" style="color:' + color + '" title="' +
        esc(note) + '">' + (rel * 100).toFixed(1) + "%</td></tr>";
    }).join("");

    var gaps = (rep.achieved && state.population.worst_gaps) || [];
    var gapNote = gaps.length && gaps[0].relative_error > 0.05
      ? '<p class="pop-warn">' + esc(__("pop.gap_note")) + "</p>"
      : "";

    return (
      '<div class="pop-card"><h2>' + esc(__("pop.achieved_title")) + "</h2>" +
      '<p class="pop-lede">' + esc(__("pop.achieved_lede")) + "</p>" + gapNote +
      '<table class="pop-table"><thead><tr><th>' + esc(__("pop.col_metric")) + "</th>" +
      '<th class="num">' + esc(__("pop.col_target")) + "</th>" +
      '<th class="num">' + esc(__("pop.col_achieved")) + "</th>" +
      '<th class="num">' + esc(__("pop.col_error")) + "</th></tr></thead><tbody>" + rows + "</tbody></table>" +
      '<div class="pop-charts">' +
      '<div class="pop-chart"><h4>' + esc(__("pop.chart_pyramid")) + "</h4>" + agePyramid(rep.charts.age_pyramid) +
      '<p class="pop-chart-note">' + esc(__("pop.chart_pyramid_note")) + "</p></div>" +
      '<div class="pop-chart"><h4>' + esc(__("pop.chart_lorenz")) + "</h4>" + lorenz(rep.charts.lorenz) +
      '<p class="pop-chart-note">' + esc(__("pop.chart_lorenz_note")) + "</p></div>" +
      '<div class="pop-chart"><h4>' + esc(__("pop.chart_household")) + "</h4>" +
      barChart((rep.charts.household_sizes || []).map(function (r) { return { label: r.size, value: r.count }; }),
        { unit: __("pop.unit_household") }) +
      '<p class="pop-chart-note">' + esc(__("pop.chart_household_note")) + "</p></div>" +
      '<div class="pop-chart"><h4>' + esc(__("pop.chart_social")) + "</h4>" +
      barChart((rep.network.degree_histogram || []).slice(0, 24).map(function (r) { return { label: r.degree, value: r.count }; }),
        { color: "#0891b2", unit: __("pop.unit_friends") }) +
      '<p class="pop-chart-note">' + esc(__f("pop.chart_social_note", {
        clustering: rep.network.clustering.toFixed(2),
        random: rep.network.random_clustering.toFixed(2),
        path: rep.network.mean_path_length.toFixed(1),
      })) + "</p></div>" +
      "</div></div>"
    );
  }

  /* ------------------------------------------------- step 2 · 居民名册 */

  /** The generated agents themselves, previewable and downloadable right here.
   *
   *  Aggregate charts answer "did the generator hit my targets"; they do not
   *  answer "who are these people". Making the user run a simulation (or hunt
   *  for a written file in step 5) before they can look at a single resident
   *  is why the population felt like a black box.
   *
   *  The table body is rendered by :func:`renderRoster` rather than inlined
   *  here: filtering must not re-render the whole panel, or the search box
   *  loses focus on every keystroke. */
  function rosterCard() {
    var total = (state.population.people || []).length;
    return (
      '<div class="pop-card"><h2>' + esc(__f("pop.roster_title", { count: total })) + "</h2>" +
      '<p class="pop-lede">' + esc(__("pop.roster_lede")) + "</p>" +
      '<div class="pop-rostertools">' +
      '<input type="search" id="popRosterQ" placeholder="' + esc(__("pop.roster_filter")) + '" value="' +
      esc(state.roster.query) + '" />' +
      '<span class="pop-hint" id="popRosterCount"></span></div>' +
      '<table class="pop-table pop-roster"><thead><tr>' +
      "<th>" + esc(__("pop.col_id")) + "</th><th>" + esc(__("pop.col_name")) + "</th>" +
      "<th>" + esc(__("pop.col_gender")) + '</th><th class="num">' + esc(__("pop.col_age")) + "</th>" +
      "<th>" + esc(__("pop.col_hukou")) + "</th><th>" + esc(__("pop.col_home")) + "</th>" +
      "<th>" + esc(__("pop.col_job")) + '</th><th class="num">' + esc(__("pop.col_income")) + "</th>" +
      "<th>" + esc(__("pop.col_household")) + "</th>" +
      '</tr></thead><tbody id="popRosterBody"></tbody></table>' +
      '<div id="popRosterMore" class="pop-roster-more"></div>' +
      actionBar(
        '<button class="btn" data-export="csv">' + esc(__("pop.export_csv")) + "</button>" +
        '<button class="btn" data-export="md">' + esc(__("pop.export_md")) + "</button>" +
        '<button class="btn ghost" data-export="json">' + esc(__("pop.export_json")) + "</button>" +
        '<span class="pop-actionhint">' + __("pop.export_hint") + "</span>"
      ) +
      "</div>"
    );
  }

  function householdLabel(type) {
    var labels = (state.schema && state.schema.household_type_labels) || {};
    return labels[type] || type || "—";
  }

  function stateBars(personState) {
    var keys = (state.schema && state.schema.state_var_keys) || [];
    return '<div class="pop-statebars">' + keys.map(function (k) {
      var v = Number((personState || {})[k] || 0);
      return '<div class="pop-statebar" title="' + esc(stateHelp(k)) + '">' +
        "<span>" + esc(label(k, "zh")) + "</span>" +
        '<i><b style="width:' + Math.round(v * 100) + '%"></b></i>' +
        "<em>" + v.toFixed(2) + "</em></div>";
    }).join("") + "</div>";
  }

  function rosterRow(p) {
    var open = state.roster.open === p.id;
    var row =
      '<tr class="pop-roster-row' + (open ? " is-open" : "") + '" data-person="' + p.id + '">' +
      '<td class="num">' + p.id + "</td><td>" + esc(p.name) + "</td><td>" + esc(p.gender) + "</td>" +
      '<td class="num">' + p.age + "</td><td>" + esc(p.hukou) + "</td><td>" + esc(p.residence) + "</td>" +
      "<td>" + esc(p.job) + "</td>" +
      '<td class="num">' + (p.income_monthly > 0 ? money(p.income_monthly) : "—") + "</td>" +
      "<td>" + esc(householdLabel(p.household_type)) + "</td></tr>";
    if (!open) return row;
    return row + '<tr class="pop-roster-detail"><td colspan="9">' + stateBars(p.state) + "</td></tr>";
  }

  var ROSTER_PAGE = 20;

  function renderRoster() {
    var body = $("popRosterBody");
    if (!body || !state.population) return;
    var all = state.population.people || [];
    var q = state.roster.query.trim().toLowerCase();
    var matched = !q ? all : all.filter(function (p) {
      return [p.id, p.name, p.job, p.residence, p.hukou, p.gender]
        .join(" ").toLowerCase().indexOf(q) >= 0;
    });
    var shown = matched.slice(0, state.roster.limit);

    body.innerHTML = shown.length
      ? shown.map(rosterRow).join("")
      : '<tr><td colspan="9" class="pop-hint">' + esc(__("pop.roster_empty")) + "</td></tr>";

    var count = $("popRosterCount");
    if (count) {
      count.textContent = q
        ? __f("pop.roster_matched", { matched: matched.length, shown: shown.length })
        : __f("pop.roster_total", { total: all.length, shown: shown.length });
    }

    var more = $("popRosterMore");
    if (more) {
      more.innerHTML = matched.length > shown.length
        ? '<button class="btn small ghost" id="popRosterMoreBtn">' +
          esc(__f("pop.roster_more", { page: ROSTER_PAGE, rest: matched.length - shown.length })) +
          "</button>"
        : "";
      bind("popRosterMoreBtn", function () {
        state.roster.limit += ROSTER_PAGE;
        renderRoster();
      });
    }

    Array.prototype.forEach.call(body.querySelectorAll(".pop-roster-row"), function (tr) {
      tr.addEventListener("click", function () {
        var id = Number(tr.dataset.person);
        state.roster.open = state.roster.open === id ? null : id;
        renderRoster();
      });
    });
  }

  /** Downloads are rendered by the backend (`/api/population/export`) so the
   *  CSV column order and the profile template stay declared once, in
   *  `gaworld/population/writer.py`. */
  function downloadExport(fmt) {
    setProgress(__("pop.download_preparing"), 0.5);
    api("GET", "/api/population/export?format=" + encodeURIComponent(fmt)).then(function (res) {
      if (res.error) return fail(res.error);
      saveFile(res.filename, res.content, res.content_type, res.bom);
      setProgress(__f("pop.download_done", { filename: res.filename }), 1);
    });
  }

  function saveFile(filename, text, contentType, bom) {
    // The BOM is not decoration: the simulator reads the state CSV with a
    // BOM-aware codec, and Excel needs it to show Chinese names correctly.
    var blob = new Blob(bom ? ["\ufeff", text] : [text], { type: contentType });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(function () { URL.revokeObjectURL(url); }, 0);
  }

  /* --------------------------------------------------------------- step 3 */

  function renderStep3() {
    var keys = state.schema.state_var_keys || [];
    var sliders = keys.map(function (k) {
      var path = "psychology.state_means." + k;
      var value = deepGet(state.spec, path);
      return '<div class="pop-field"><label><span>' + esc(label(k, "zh")) +
        ' <em class="pop-key">' + esc(k) + "</em>" + help(stateHelp(k)) +
        '</span><span class="pop-value" data-out="' + path + '">' + value + "</span></label>" +
        '<input type="range" data-path="' + path + '" data-fmt="raw" min="0" max="1" step="0.01" value="' + value +
        '" title="' + esc(stateHelp(k)) + '" /></div>';
    }).join("");

    var radar = state.population
      ? '<div class="pop-chart" style="max-width:340px"><h4>' + esc(__("pop.radar_title")) + "</h4>" +
        stateRadar(state.population.report.charts.state_distribution, keys) +
        '<p class="pop-chart-note">' + esc(__("pop.radar_note")) + "</p></div>"
      : '<p class="pop-hint">' + esc(__("pop.radar_pending")) + "</p>";

    return (
      '<div class="pop-card"><h2>' + esc(__("pop.step3_title")) + "</h2>" +
      '<p class="pop-lede">' + esc(__("pop.step3_lede")) + "</p>" +
      '<div class="pop-grid">' + sliders + "</div>" +
      '<div class="pop-grid" style="margin-top:14px">' +
      fieldSlider("psychology.state_sd", __("pop.slider_state_sd"), 0.02, 0.3, 0.01) +
      "</div>" + radar +
      actionBar(
        '<button class="btn" id="popRegen">' + esc(__("pop.regen_states")) + "</button>" +
        '<button class="btn ghost" data-go="4">' + esc(__("pop.next_run")) + "</button>" +
        '<span class="pop-actionhint">' + esc(__("pop.regen_hint")) + "</span>"
      ) +
      "</div>"
    );
  }

  /* --------------------------------------------------------------- step 4 */

  function renderStep4() {
    var r = state.run;
    var providers = state.schema.providers || [];
    var providerOptions = ['<option value="">' + esc(__("pop.provider_default")) + "</option>"].concat(
      providers.map(function (p) {
        return '<option value="' + esc(p.name) + '"' + (r.provider === p.name ? " selected" : "") + ">" +
          esc(p.name + "　—　" + p.model + "（" + p.type +
            (p.is_default ? __("pop.provider_is_default") : "") + "）") + "</option>";
      })
    ).join("");

    var warn = r.coupling === 0
      ? '<p class="pop-warn">' + __("pop.coupling_off_warn") + "</p>"
      : "";

    var costHint = r.useLlm
      ? '<p class="pop-warn">' + esc(__f("pop.cost_warn", {
          briefs: Math.round(state.spec.size / 13) * r.days,
          extra: r.budget ? __f("pop.cost_extra", { days: r.budget * r.days }) : "",
        })) + "</p>"
      : "";

    return (
      '<div class="pop-card"><h2>' + esc(__("pop.step4_title")) + "</h2>" +
      '<p class="pop-lede">' + esc(__("pop.step4_lede")) + "</p>" +
      warn + costHint +
      '<div class="pop-grid">' +
      runSlider("days", __("pop.slider_days"), 1, 60, 1, r.days) +
      runSlider("budget", __("pop.slider_budget"), 0, 200, 1, r.budget) +
      runSlider("audit", __("pop.slider_audit"), 0, 0.2, 0.01, r.audit, pct) +
      runSlider("coupling", __("pop.slider_coupling"), 0, 1.5, 0.05, r.coupling, function (v) { return Number(v).toFixed(2); }) +
      '<div class="pop-field"><label><span>' + esc(__("pop.field_use_llm")) + "</span>" +
        help(runHelp("useLlm")) + "</label>" +
      '<select data-run="useLlm"><option value="0"' + (r.useLlm ? "" : " selected") + ">" +
        esc(__("pop.use_llm_no")) + "</option>" +
      '<option value="1"' + (r.useLlm ? " selected" : "") + ">" +
        esc(__("pop.use_llm_yes")) + "</option></select></div>" +
      '<div class="pop-field"><label><span>' + esc(__("pop.field_provider")) + "</span>" +
        help(runHelp("provider")) + "</label>" +
      '<select data-run="provider"' + (r.useLlm ? "" : " disabled") + ">" + providerOptions + "</select>" +
      '<span class="pop-note">' + esc(__(r.useLlm ? "pop.provider_note_on" : "pop.provider_note_off")) +
        "</span></div>" +
      "</div>" +
      actionBar(
        '<button class="btn primary" id="popRunGroup"' + (state.busy ? " disabled" : "") + ">" +
        esc(state.busy ? __("pop.simulating") : __f("pop.run_n_days", { days: r.days })) + "</button>" +
        (state.groupRun
          ? '<button class="btn ghost" data-go="5">' + esc(__("pop.next_check")) + "</button>" : "") +
        '<span class="pop-actionhint">' +
        (state.population ? "" : esc(__("pop.no_population_warn"))) + "</span>"
      ) +
      "</div>" + (state.groupRun ? groupResultCard() : "")
    );
  }

  function runSlider(key, label, min, max, step, value, fmt) {
    return '<div class="pop-field"><label><span>' + esc(label) + help(runHelp(key)) +
      '</span><span class="pop-value">' + esc(fmt ? fmt(value) : value) + "</span></label>" +
      '<input type="range" data-run="' + key + '" min="' + min + '" max="' + max + '" step="' + step +
      '" value="' + value + '" title="' + esc(runHelp(key)) + '" /></div>';
  }

  function groupResultCard() {
    var g = state.groupRun;
    var c = g.cost;
    var rows = g.cohorts.slice(0, 40).map(function (co) {
      return "<tr><td>" + esc(co.label) + '</td><td class="num">' + co.size +
        '</td><td class="num">' + (co.centroid.stress || 0).toFixed(2) +
        '</td><td class="num">' + (co.dispersion.stress || 0).toFixed(2) + "</td></tr>";
    }).join("");
    var saving = c.savings_factor
      ? __f("pop.saving_factor", { factor: c.savings_factor.toFixed(0) })
      : __("pop.saving_none");
    return (
      '<div class="pop-card"><h2>' + esc(__("pop.run_done")) + "</h2>" +
      '<div class="pop-statgrid">' +
      stat(label("population"), c.population, __("pop.tip_population")) +
      stat(label("cohorts"), c.cohorts, __("pop.tip_cohorts")) +
      stat(label("group_llm_calls"), c.group_llm_calls, __("pop.tip_calls")) +
      stat(label("individual_agent_days"), c.individual_agent_days, __("pop.tip_agent_days")) +
      stat(label("savings_factor"), saving,
        __f("pop.tip_savings", { calls: c.full_individual_llm_calls_estimate })) +
      stat(label("max_residual_l1"), g.max_residual_l1.toFixed(4), __("pop.tip_residual")) +
      "</div>" +
      '<h4 class="pop-subhead">' + esc(__("pop.cohorts_head")) + "</h4>" +
      '<p class="pop-chart-note">' + esc(__("pop.cohorts_note")) + "</p>" +
      '<table class="pop-table"><thead><tr><th>' + esc(__("pop.col_cohort")) + "</th>" +
      '<th class="num">' + esc(__("pop.col_size")) + "</th>" +
      '<th class="num">' + esc(__("pop.col_stress_mean")) + "</th>" +
      '<th class="num">' + esc(__("pop.col_stress_sd")) + "</th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table>" +
      '<h4 class="pop-subhead">' + esc(__("pop.daily_head")) + "</h4>" +
      '<div class="pop-log">' + esc(g.day_blocks.join("\n\n")) + "</div>" +
      "</div>"
    );
  }

  function stat(label, value, tip) {
    return (
      '<div class="pop-stat" title="' + esc(tip) + '">' +
      '<span class="pop-stat-k">' + esc(label) + "</span>" +
      '<span class="pop-stat-v">' + esc(value) + "</span>" +
      "</div>"
    );
  }

  /** Files the user can actually open, not just a path to go hunting for.
   *  The dashboard already serves the repo statically, so a repo-relative URL
   *  is directly clickable. */
  function writtenCard() {
    var files = state.written || [];
    if (!files.length) return "";
    var cards = files.map(function (f) {
      var size = f.bytes > 1024 * 1024
        ? (f.bytes / 1024 / 1024).toFixed(1) + " MB"
        : Math.max(1, Math.round(f.bytes / 1024)) + " KB";
      var open = f.url
        ? '<a class="btn small" href="' + esc(f.url) + '" target="_blank" rel="noopener">' +
            esc(__("pop.file_open")) + "</a>" +
          '<a class="btn small ghost" href="' + esc(f.url) + '" download>' +
            esc(__("pop.file_download")) + "</a>"
        : '<span class="pop-hint">' + esc(__("pop.file_outside")) + "</span>";
      return (
        '<div class="pop-file">' +
        '<div class="pop-file-head"><b>' + esc(f.label) + "</b><span>" + esc(size) + "</span></div>" +
        '<p class="pop-file-hint">' + esc(f.hint) + "</p>" +
        '<code class="pop-file-path">' + esc(f.path) + "</code>" +
        '<div class="pop-file-acts">' + open + "</div>" +
        "<details><summary>" + esc(__("pop.file_preview")) +
          '</summary><pre class="pop-pre">' + esc(f.preview) + "</pre></details>" +
        "</div>"
      );
    }).join("");
    return (
      '<div class="pop-card"><h2>' + esc(__("pop.written_title")) + "</h2>" +
      '<p class="pop-lede">' + __("pop.written_lede") + "</p>" +
      '<div class="pop-files">' + cards + "</div></div>"
    );
  }

  /* --------------------------------------------------------------- step 5 */

  function renderStep5() {
    var intro =
      '<div class="pop-explain">' +
      "<h4>" + esc(__("pop.v_intro_head")) + "</h4>" +
      "<p>" + __("pop.v_intro_p1") + "</p>" +
      "<p>" + __("pop.v_intro_p2") + "</p>" +
      '<p class="pop-hint">' + esc(__("pop.v_intro_time")) + "</p>" +
      "</div>";

    var layerGuide =
      '<div class="pop-explain"><h4>' + esc(__("pop.v_guide_head")) + "</h4>" +
      '<ul class="pop-guide">' +
      ["pop.v_l1_guide", "pop.v_l2_guide", "pop.v_l3_guide", "pop.v_l4_guide"]
        .map(function (key) { return "<li>" + __(key) + "</li>"; }).join("") +
      '</ul><p class="pop-hint">' + __("pop.v_watershed") + "</p></div>";

    var body = "";
    if (state.verdict) {
      var v = state.verdict.verdict;
      var MARK = {
        pass: { icon: "✅", word: __("pop.v_pass"), meaning: __("pop.v_pass_meaning") },
        fail: { icon: "❌", word: __("pop.v_fail"), meaning: __("pop.v_fail_meaning") },
        inconclusive: {
          icon: "⚠️", word: __("pop.v_inconclusive"), meaning: __("pop.v_inconclusive_meaning"),
        },
      };
      var byLayer = {};
      v.layers.forEach(function (l) { byLayer[l.layer] = l; });

      // 一句话结论 + 能做/不能做清单。用户真正想知道的是「那我现在能拿它干什么」，
      // 而不是四个字母代号各自的 z 值。
      var can = [], cannot = [];
      function verdictOf(id) { return byLayer[id] && byLayer[id].status; }
      (verdictOf("L1") === "pass" ? can : cannot).push(__("pop.v_can_l1"));
      (verdictOf("L3") === "pass" ? can : cannot).push(__("pop.v_can_l3"));
      (verdictOf("L4") === "pass" ? can : cannot).push(__("pop.v_can_l4"));
      (verdictOf("L2") === "pass" ? can : cannot).push(__("pop.v_can_l2"));

      var checklist =
        '<div class="pop-usecase">' +
        '<div class="pop-usecase-col ok"><h5>' + esc(__("pop.v_can_head")) + "</h5>" +
        (can.length ? "<ul>" + can.map(function (t) { return "<li>" + esc(t) + "</li>"; }).join("") + "</ul>"
                    : '<p class="pop-hint">' + esc(__("pop.v_can_none")) + "</p>") + "</div>" +
        '<div class="pop-usecase-col no"><h5>' + esc(__("pop.v_cannot_head")) + "</h5>" +
        (cannot.length ? "<ul>" + cannot.map(function (t) { return "<li>" + esc(t) + "</li>"; }).join("") + "</ul>"
                       : '<p class="pop-hint">' + esc(__("pop.v_cannot_none")) + "</p>") + "</div></div>";

      var headline = v.gate_passed
        ? '<div class="pop-verdict-box pass">' + __("pop.v_headline_pass") + "</div>"
        : '<div class="pop-verdict-box fail">' + __f("pop.v_headline_fail", {
            advice: __(verdictOf("L2") !== "pass" ? "pop.v_advice_l2" : "pop.v_advice_other"),
          }) + "</div>";

      var layers = v.layers.map(function (l) {
        var m = MARK[l.status];
        return '<div class="pop-layer ' + l.status + '">' +
          '<div class="pop-layer-head">' + m.icon + " " + esc(label(l.layer, "zh")) +
          ' <em>' + esc(label(l.layer, "en")) + "</em> — " + esc(m.word) + "</div>" +
          '<div class="pop-layer-note">' + esc(layerQuestion(l.layer)) + "</div>" +
          '<div class="pop-layer-note">' + esc(m.meaning) + "</div>" +
          layerDetail(l) + "</div>";
      }).join("");

      body = headline + checklist +
        '<h4 class="pop-subhead">' + esc(__("pop.v_per_item")) + "</h4>" +
        '<div class="pop-verdict">' + layers + "</div>" +
        '<details class="pop-details"><summary>' + esc(__("pop.v_technical")) + "</summary>" +
        '<div class="pop-log">' + esc(state.verdict.text) + "</div></details>";
    }

    return (
      '<div class="pop-card"><h2>' + esc(__("pop.step5_title")) + "</h2>" +
      intro + layerGuide + body +
      actionBar(
        '<button class="btn primary" id="popValidate"' + (state.busy ? " disabled" : "") + ">" +
        esc(state.busy ? __("pop.checking")
          : state.verdict ? __("pop.v_recheck") : __("pop.v_check")) + "</button>" +
        '<button class="btn ghost" id="popWrite"' + (state.busy ? " disabled" : "") + ">" +
        esc(__("pop.v_write")) + "</button>" +
        '<span class="pop-actionhint">' + esc(__("pop.v_write_hint")) + "</span>"
      ) +
      "</div>" + writtenCard()
    );
  }

  /** The one-sentence question each layer answers. */
  var LAYER_IDS = ["L1", "L2", "L3", "L4"];

  function layerQuestion(id) {
    return LAYER_IDS.indexOf(id) >= 0 ? __("pop.q_" + id.toLowerCase()) : "";
  }

  /** 差在哪一边——「传不动」和「传得太猛」是两种完全不同的毛病，
   *  但都只表现为一个 z 值，所以这里从每个指标的实测 Moran's I 反推方向。 */
  function moranDirection(d) {
    var keys = (d.failures && d.failures.length ? d.failures : d.discriminating_keys) || [];
    if (!keys.length || !d.by_key) return "";
    var k = keys[0], e = d.by_key[k];
    if (!e) return "";
    var weaker = Math.abs(e.group_morans_i) < Math.abs(e.reference_morans_i);
    return __f("pop.moran_example", {
      metric: esc(label(k, "zh")),
      reference: e.reference_morans_i.toFixed(3),
      group: e.group_morans_i.toFixed(3),
      verdict: __(weaker ? "pop.moran_weak" : "pop.moran_strong"),
    });
  }

  function layerDetail(l) {
    var d = l.detail || {};
    if (l.layer === "L1" && d.gaps) {
      var worst = null;
      Object.keys(d.gaps).forEach(function (k) {
        if (!worst || d.gaps[k].wasserstein1 > d.gaps[worst].wasserstein1) worst = k;
      });
      if (!worst) return "";
      var gap = d.gaps[worst].wasserstein1, allow = d.budget[worst];
      return '<div class="pop-layer-fact">' + __f("pop.l1_detail", {
        metric: esc(label(worst, "zh")),
        gap: gap.toFixed(3),
        pct: (gap * 100).toFixed(1),
        allow: allow.toFixed(3),
        verdict: __(gap <= allow ? "pop.l1_within" : "pop.l1_over"),
      }) + "</div>";
    }
    if (l.layer === "L4" && d.reference_ate !== undefined) {
      var relErr = (d.magnitude_relative_error * 100).toFixed(0);
      return '<div class="pop-layer-fact">' + __f("pop.l4_detail", {
        reference: d.reference_ate.toFixed(3),
        group: d.group_ate.toFixed(3),
        sign: d.same_sign
          ? __f("pop.l4_same_sign", { direction: __(d.reference_ate < 0 ? "pop.l4_down" : "pop.l4_up") })
          : __("pop.l4_opposite"),
        err: relErr,
        retained: (d.heterogeneity_retained_ratio * 100).toFixed(0),
      }) + "</div>";
    }
    if (l.layer === "L2" && d.worst_z !== undefined) {
      return '<div class="pop-layer-fact">' + __f("pop.l2_detail", {
        z: d.worst_z.toFixed(2),
        tolerance: d.tolerance_z.toFixed(1),
      }) + moranDirection(d) + "</div>";
    }
    if (l.layer === "L3" && d.by_key) {
      var k0 = Object.keys(d.by_key).filter(function (k) { return d.by_key[k] && d.by_key[k].spread_ratio; })[0];
      if (k0) {
        var ratio = d.by_key[k0].spread_ratio;
        return '<div class="pop-layer-fact">' + __f("pop.l3_detail", {
          metric: esc(label(k0, "zh")),
          ratio: (ratio * 100).toFixed(0),
        }) + "</div>";
      }
    }
    if (d.failures && d.failures.length) {
      return '<div class="pop-layer-fact">' +
        esc(__f("pop.failures", { items: d.failures.join("、") })) + "</div>";
    }
    return "";
  }

  /* ------------------------------------------------------------- 侧栏 / 壳 */

  function renderIssues() {
    var el = $("popIssues");
    if (!el) return;
    if (!state.preview) {
      el.innerHTML = '<p class="pop-hint">' + esc(__("pop.checking")) + "</p>";
      return;
    }
    var issues = state.preview.issues || [];
    var html = issues.length
      ? issues.map(function (i) {
          return '<div class="pop-issue ' + esc(i.level) + '"><b>' +
            esc(__(i.level === "error" ? "pop.infeasible" : "pop.maybe_infeasible")) +
            "</b>" + esc(i.message) +
            (i.suggestion ? '<div class="pop-suggest">👉 ' + esc(i.suggestion) + "</div>" : "") + "</div>";
        }).join("")
      : '<div class="pop-issue ok">' + __("pop.no_conflict") + "</div>";

    var b = state.preview.bounds;
    html += '<div class="pop-issue info">' + __("pop.reachable_title") +
      esc(__f("pop.reachable_body", {
        size: b.household_mean_size.min.toFixed(1) + "–" + b.household_mean_size.max.toFixed(1),
        age: b.median_age.min.toFixed(0) + "–" + b.median_age.max.toFixed(0),
      })) +
      '<div class="pop-suggest">' + esc(__("pop.reachable_note")) + "</div></div>";
    el.innerHTML = html;
  }

  function renderSummary() {
    var el = $("popSummary");
    if (!el) return;
    if (!state.population) {
      el.innerHTML = '<p class="pop-hint">' + __("pop.not_generated") + "</p>";
      return;
    }
    var a = state.population.report.achieved;
    el.innerHTML = "<dl>" +
      "<dt>" + esc(__("pop.dt_count")) + "</dt><dd>" + state.population.report.size + "</dd>" +
      "<dt>" + esc(__("pop.dt_median_age")) + "</dt><dd>" + a.median_age.achieved + "</dd>" +
      "<dt>" + esc(__("pop.dt_employment")) + "</dt><dd>" + pct(a.employment_rate.achieved) + "</dd>" +
      "<dt>" + esc(__("pop.dt_income")) + "</dt><dd>" + money(a.income_median.achieved) + "</dd>" +
      "<dt>" + esc(__("pop.dt_gini")) + "</dt><dd>" + a.income_gini.achieved.toFixed(2) + "</dd>" +
      "<dt>" + esc(__("pop.dt_household")) + "</dt><dd>" + a.household_mean_size.achieved.toFixed(1) + "</dd>" +
      "<dt>" + esc(__("pop.dt_ties")) + "</dt><dd>" + a.mean_degree.achieved.toFixed(0) + "</dd>" +
      "</dl>";
  }

  function render() {
    var renderers = { 1: renderStep1, 2: renderStep2, 3: renderStep3, 4: renderStep4, 5: renderStep5 };
    $("popPanel").innerHTML = (renderers[state.step] || renderStep1)();
    Array.prototype.forEach.call(document.querySelectorAll("#popSteps .step"), function (btn) {
      btn.classList.toggle("is-active", Number(btn.dataset.step) === state.step);
    });
    var prev = $("popPrev"), next = $("popNext");
    if (prev) prev.disabled = state.step === 1;
    if (next) next.disabled = state.step === 5;
    renderIssues();
    renderSummary();
    bindPanel();
    renderRoster();
  }

  function setProgress(text, fraction, isError) {
    var el = $("popProgress");
    if (!el) return;
    el.innerHTML = text
      ? '<span class="' + (isError ? "pop-progress-err" : "") + '">' + esc(text) + "</span>" +
        (isError ? "" : '<div class="pop-bar"><i style="width:' + Math.round((fraction || 0) * 100) + '%"></i></div>')
      : "";
  }

  /* --------------------------------------------------------------- events */

  var previewTimer = null;
  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(function () {
      api("POST", "/api/population/preview", { spec: state.spec }).then(function (res) {
        if (res.error) {
          var el = $("popIssues");
          if (el) el.innerHTML = '<div class="pop-issue error">' + __("pop.precheck_failed") +
            esc(res.error) + "</div>";
          return;
        }
        state.preview = res;
        state.spec = res.spec;
        renderIssues();
      });
    }, 180);
  }

  function bindPanel() {
    var panel = $("popPanel");

    Array.prototype.forEach.call(panel.querySelectorAll("[data-path]"), function (input) {
      input.addEventListener("input", function () {
        var path = input.dataset.path;
        var value = input.type === "range" || input.type === "number" ? Number(input.value) : input.value;
        deepSet(state.spec, path, value);
        var out = panel.querySelector('[data-out="' + path + '"]');
        if (out) {
          var f = input.dataset.fmt;
          out.textContent = f === "pct" ? pct(value) : f === "money" ? money(value) : value;
        }
        if (path === "preset") {
          api("POST", "/api/population/preview", { preset: value }).then(function (res) {
            if (res.error) return fail(res.error);
            state.spec = res.spec;
            state.preview = res;
            render();
          });
          return;
        }
        schedulePreview();
      });
    });

    Array.prototype.forEach.call(panel.querySelectorAll("[data-run]"), function (input) {
      input.addEventListener("input", function () {
        var key = input.dataset.run;
        if (key === "useLlm") {
          state.run.useLlm = input.value === "1";
          render();
          return;
        }
        if (key === "provider") {
          state.run.provider = input.value;
          return;
        }
        state.run[key] = Number(input.value);
        var out = input.parentNode.querySelector(".pop-value");
        if (out) {
          out.textContent = key === "audit" ? pct(state.run[key])
            : key === "coupling" ? state.run[key].toFixed(2) : state.run[key];
        }
        if (key === "coupling" || key === "days" || key === "budget") render();
      });
    });

    Array.prototype.forEach.call(panel.querySelectorAll("[data-go]"), function (btn) {
      btn.addEventListener("click", function () {
        state.step = Number(btn.dataset.go);
        render();
      });
    });

    Array.prototype.forEach.call(panel.querySelectorAll("[data-export]"), function (btn) {
      btn.addEventListener("click", function () {
        downloadExport(btn.dataset.export);
      });
    });

    // Filtering redraws only the table body: a full render() would rebuild the
    // input and drop the caret on every keystroke.
    var search = $("popRosterQ");
    if (search) {
      search.addEventListener("input", function () {
        state.roster.query = search.value;
        state.roster.limit = ROSTER_PAGE;
        renderRoster();
      });
    }

    bind("popGenerate", generate);
    bind("popRegen", generate);
    bind("popRunGroup", runGroup);
    bind("popValidate", runValidation);
    bind("popWrite", writePopulation);
  }

  function bind(id, fn) {
    var el = $(id);
    if (el) el.addEventListener("click", fn);
  }

  function poll(jobId, onDone) {
    function tick() {
      api("GET", "/api/population/jobs/" + jobId).then(function (job) {
        if (job.error || !job.status) {
          return fail(job.error || __("pop.task_lost"));
        }
        setProgress(job.message, job.progress);
        if (job.status === "running") {
          setTimeout(tick, 600);
          return;
        }
        state.busy = false;
        if (job.status === "error") {
          return fail(job.message);
        }
        setProgress("", 0);
        onDone(job.result);
      });
    }
    tick();
  }

  function generate(after) {
    if (state.busy) return;
    state.busy = true;
    render();
    setProgress(__f("pop.generating_n", { count: state.spec.size }), 0.1);
    api("POST", "/api/population/generate", { spec: state.spec }).then(function (res) {
      if (res.error) return fail(res.error);
      poll(res.job_id, function (result) {
        state.population = result;
        state.groupRun = null;
        state.verdict = null;
        state.roster = { query: "", limit: ROSTER_PAGE, open: null };
        render();
        if (typeof after === "function") after();
      });
    });
  }

  function runGroup() {
    if (state.busy) return;
    if (!state.population) {
      // 自动补上缺的一步，而不是让用户对着一个不动的按钮发呆
      generate(runGroup);
      return;
    }
    state.busy = true;
    render();
    setProgress(__f("pop.simulating_n", { days: state.run.days }), 0.1);
    api("POST", "/api/population/group-run", {
      source: "last",
      days: state.run.days,
      materialization_budget: state.run.budget,
      audit_fraction: state.run.audit,
      network_coupling: state.run.coupling,
      use_llm: state.run.useLlm,
      provider: state.run.provider,
      seed: state.run.seed,
    }).then(function (res) {
      if (res.error) return fail(res.error);
      poll(res.job_id, function (result) {
        state.groupRun = result;
        render();
      });
    });
  }

  function runValidation() {
    if (state.busy) return;
    state.busy = true;
    render();
    setProgress(__("pop.running_control"), 0.1);
    api("POST", "/api/population/validate", {
      days: 14,
      materialization_budget: state.run.budget,
      network_coupling: state.run.coupling,
      seed: state.run.seed,
    }).then(function (res) {
      if (res.error) return fail(res.error);
      poll(res.job_id, function (result) {
        state.verdict = result;
        render();
      });
    });
  }

  function writePopulation() {
    if (state.busy) return;
    state.busy = true;
    render();
    setProgress(__("pop.writing_files"), 0.1);
    api("POST", "/api/population/generate", { spec: state.spec, write: true }).then(function (res) {
      if (res.error) return fail(res.error);
      poll(res.job_id, function (result) {
        state.population = result;
        state.written = result.written || [];
        render();
        setProgress(
          state.written.length
            ? __f("pop.saved_n", { count: state.written.length })
            : __("pop.done"),
          1
        );
      });
    });
  }

  /* ----------------------------------------------------------------- boot */

  function boot() {
    api("GET", "/api/population/schema").then(function (schema) {
      if (schema.error) {
        $("popPanel").innerHTML = '<div class="pop-card"><h2>' + esc(__("pop.load_failed_title")) +
          '</h2><p class="pop-warn">' + esc(schema.error) + "</p><p>" +
          esc(__("pop.load_failed_hint")) + "</p></div>";
        return;
      }
      state.schema = schema;
      state.spec = schema.defaults;
      var meta = $("popTopMeta");
      if (meta) {
        meta.innerHTML =
          esc(__f("pop.models_available", { count: (schema.providers || []).length })) +
          "<br/>" + esc(__("pop.cohort_axes")) +
          esc((schema.cohort_axes || []).map(function (a) {
            return (schema.cohort_axis_labels || {})[a] || a;
          }).join("、"));
      }
      render();
      schedulePreview();
    });

    bind("popPrev", function () {
      state.step = Math.max(1, state.step - 1);
      render();
    });
    bind("popNext", function () {
      state.step = Math.min(5, state.step + 1);
      render();
    });
    Array.prototype.forEach.call(document.querySelectorAll("#popSteps .step"), function (btn) {
      btn.addEventListener("click", function () {
        state.step = Number(btn.dataset.step);
        render();
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  /* The whole wizard is drawn from JS, so a language switch just re-runs the
     renderers over the state already in hand. The top-bar meta is rebuilt from
     the schema, which is language-independent and already loaded. No refetch. */
  if (typeof document !== "undefined") {
    document.addEventListener("locale-changed", function () {
      if (!state.schema) return;
      var meta = $("popTopMeta");
      if (meta) {
        meta.innerHTML =
          esc(__f("pop.models_available", { count: (state.schema.providers || []).length })) +
          "<br/>" + esc(__("pop.cohort_axes")) +
          esc((state.schema.cohort_axes || []).map(function (a) {
            return (state.schema.cohort_axis_labels || {})[a] || a;
          }).join("、"));
      }
      render();
      renderIssues();
      renderSummary();
    });
  }

  /* Test hook. The step-5 copy reads a dozen nested fields off the validator's
     output; a renamed field there would blank the card while every Python test
     stays green. This lets a node test push a real verdict payload in. */
  if (typeof global !== "undefined") {
    global.__POP_TEST__ = {
      setVerdict: function (v) { state.verdict = v; },
      setPopulation: function (p) { state.population = p; },
      setWritten: function (w) { state.written = w; },
      setStep: function (n) { state.step = n; },
      render: render,
      state: state,
    };
  }
})();
