/* 外部系统观测台 —— 看住世界本身：货币系统 / 外部环境 / 对外服务。
 *
 * 三个刻意的设计：
 *
 * - **配置表单是从配置本身长出来的**，不是手写的。economy 一棵子树就有上百个叶子，
 *   手写表单既写不完也会在加旋钮的当天过期。这里按 JSON 形状渲染控件，后端再按
 *   现有配置的类型把补丁强制成形（见 external_systems_api._coerce_like）。
 * - **"改运行时状态"走干预队列，不是直接改 macro_state.json**。那个文件是 run 的
 *   *产物*：仿真在 on_simulation_start 从配置重建宏观状态，从不回读它。直接改它会
 *   看起来生效、实际什么都没发生。
 * - 图表手写 SVG，与 population.js 同因：本目录没有构建步骤，引 CDN 图表库会让
 *   dashboard 失去离线可用性。
 */
(function () {
  "use strict";

  var TABS = ["currency", "environment", "services"];

  var state = {
    tab: "currency",
    data: null,
    health: null,
    dirty: {},    // "economy.macro.initial_inflation_rate" -> value
    invalid: {},  // same key -> true when the textarea holds unparseable JSON
    busy: false,
  };

  /* ----------------------------------------------------------------- utils */

  function $(id) {
    return document.getElementById(id);
  }

  function esc(text) {
    return String(text == null ? "" : text).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function money(v) {
    var n = Number(v);
    if (!isFinite(n)) return "—";
    return n.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  }

  function pct(v, digits) {
    var n = Number(v);
    if (!isFinite(n)) return "—";
    return (n * 100).toFixed(digits == null ? 2 : digits) + "%";
  }

  function fixed(v, digits) {
    var n = Number(v);
    return isFinite(n) ? n.toFixed(digits == null ? 3 : digits) : "—";
  }

  /* Enum display names come from the locale at call time. The machine key is
     the identity; an unknown one is shown raw rather than replaced by a
     missing-key name, since the simulator may emit a phase or event type this
     page has not been taught yet. */
  var PHASES = ["expansion", "peak", "contraction", "trough"];
  var EVENT_TYPES = ["natural", "economic", "political", "technology"];
  var HEALTH_STATES = ["ok", "down", "error", "disabled"];

  function enumLabel(known, prefix, key) {
    return known.indexOf(key) >= 0 ? __(prefix + key) : (key || "");
  }

  function phaseLabel(key) { return enumLabel(PHASES, "ext.label.", key); }
  function phaseShort(key) { return enumLabel(PHASES, "ext.phase.", key); }
  function typeLabel(key) { return enumLabel(EVENT_TYPES, "ext.evt.", key); }
  function healthLabel(key) { return enumLabel(HEALTH_STATES, "ext.health.", key); }

  /* Field labels come from the server (`overview().labels`), which resolves them
     through gaworld.settings.config_docs — the same bilingual table the 配置
     panel uses. This file used to carry its own 195-entry copy, 182 of them
     byte-identical to that table: a second source of truth that would also
     silently miss any knob added after it was written.
     These few keys mean something narrower here than they do in 配置
     ("routing" is payment routing, not task routing), so they still override. */
  var LABEL_OVERRIDES = [
    "expansion", "peak", "contraction", "trough", "routing", "mode",
    "description", "policy_events", "news", "local_agent_ids",
    "peer_agent_ids", "llm", "default",
  ];

  function label(key) {
    if (LABEL_OVERRIDES.indexOf(key) >= 0) return __("ext.label." + key);
    var entry = (state.data && state.data.labels && state.data.labels[key]) || null;
    if (!entry) return key;
    var english = typeof getLocale === "function" && getLocale() === "en";
    return (english && entry.en) || entry.zh || key;
  }

  /* ------------------------------------------------------------------- help */

  /* 说明文字的写法约定：说**改了会怎样**，不要复述标题。
   * "通胀率：通货膨胀的比率" 等于没说；"物价每年涨多少，只作用在支出侧、工资不跟涨"
   * 才是用户真正需要知道的那句。
   *
   * 查表先试完整路径、再退回末段键名：`unemployment_rate` 在社保里是缴费比例、
   * 在宏观里是失业率，`routing` 在 economy 里是支付路由、在 llm 里是模型路由——
   * 只按末段查会把两件事说成一件。 */
  /* Help texts live in the locale files; this is the set of keys that have one.
     The table used to hold the Chinese prose directly — 160 entries evaluated
     at load time, which froze whatever language was current then, before the
     locale JSON had even arrived.

     Lookup is full-path-first, then last segment: `unemployment_rate` is a
     contribution rate under social insurance and the unemployment level under
     macro; `routing` is payment routing under economy and model routing under
     llm. Resolving only by last segment would tell two different stories as
     one. */
  var HELP_KEYS = [
    "aggressive", "annual_interest_rate", "asset_returns", "auto_save_enabled", "base_cap",
    "base_floor", "base_url", "block.conservation", "block.ledger", "block.queue",
    "block.sectors", "block.wealth", "bootstrap", "brackets", "budget_template",
    "cfg.card", "checking_buffer_months", "conservative", "contraction", "credit",
    "credit_limit_months", "currency", "cycle_phase_duration_days", "daily_chance",
    "daily_market_volatility", "daily_policy_chance", "daily_tech_chance",
    "daily_utilities_cost", "daily_variance", "daily_weather_chance", "default",
    "default_special_deduction", "description", "distributed", "economic", "economy",
    "economy.macro.enabled", "economy.routing",
    "economy.social_insurance.unemployment_rate", "enabled", "engel_curve",
    "env.day_count", "env.latest_day", "env.sev_bar", "env.severity", "env.tags",
    "env.ticks", "env.type", "environment", "environment_server", "expansion",
    "expense_mult", "expense_ranges", "external_environment",
    "external_environment_service", "external_rag", "extreme_chance", "extreme_events",
    "fallback_to_empty", "friend_loans", "generator", "hardship_liquidity_months",
    "history_days", "host", "housing_fund_employer_rate", "housing_fund_rate",
    "income_elasticity", "income_mult", "income_volatility", "industry_conditions",
    "info_seek", "inheritance_base_probability", "inheritance_enabled",
    "inheritance_hukou_bonus", "initial_bank_balance", "initial_firms_balance",
    "initial_government_balance", "initial_inflation_rate", "initial_unemployment_rate",
    "intraday", "investment", "iv.day", "iv.form", "iv.inflation", "iv.note", "iv.phase",
    "iv.sector", "iv.unemployment", "landlord_keywords", "landlord_share",
    "layoff_base_prob", "layoff_risk", "lender_buffer_months", "llm", "llm.routing",
    "macro", "macro_event_chance", "macro_events", "market_correlation",
    "market_news_threshold_pct", "max_events_per_tick", "max_outstanding_months",
    "max_reads_per_day", "medical_cost_range", "medical_emergency_prob", "medical_rate",
    "merchant_labor_share", "min_hourly_income", "min_spend_factor", "mode", "moderate",
    "monthly_exemption", "natural", "news", "output_dir", "peak", "pension_rate",
    "phase_effects", "phases", "policy_events", "political", "port", "portfolio_profiles",
    "raise_base_prob", "raise_chance", "relay", "runtime_absorb", "sectors", "seed",
    "send_probability", "server", "shocks", "social_insurance", "spending", "svc.llm",
    "svc.news", "svc.probe", "svc.status", "tab.currency", "tab.environment",
    "tab.services", "tasks", "tax", "technology", "tile.drift", "tile.gini",
    "tile.indebted", "tile.inflation", "tile.money_total", "tile.phase",
    "tile.price_index", "tile.unemployment", "timeout", "top_k",
    "traffic.congested_ticks", "traffic.peak", "traffic.peak_flow", "trough",
    "use_cache_first", "weather_states", "willingness_factor", "year_end_bonus_enabled",
    "year_end_bonus_months",
  ];

  function helpText(key) {
    return key && HELP_KEYS.indexOf(key) >= 0 ? __("ext.help." + key) : "";
  }

  /** The "?" dot for a hover explanation. Nothing is added when there is none. */
  function tip(key, fallbackKey) {
    var text = helpText(key) || helpText(fallbackKey);
    return text ? ' <span class="help-tip" data-help="' + esc(text) + '"></span>' : "";
  }

  /* -------------------------------------------------------------------- api */

  /** 任何失败都要看得见，并且一定把 busy 清掉：卡住的 busy 看起来就是"按钮没反应"。 */
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
            return { error: __f("ext.not_json", { status: res.status }) };
          })
          .then(function (payload) {
            if (!res.ok && !payload.error) payload.error = "HTTP " + res.status;
            return payload;
          });
      })
      .catch(function (err) {
        return { error: String((err && err.message) || err) };
      });
  }

  function status(text, kind) {
    var el = $("extStatus");
    if (!el) return;
    el.textContent = text || "";
    el.className = "ext-status" + (kind ? " " + kind : "");
  }

  /* ----------------------------------------------------------------- charts */

  /** 多序列折线图，共用 y 轴。points 为等间距数值数组。 */
  function lineChart(series, opts) {
    opts = opts || {};
    var width = opts.width || 640;
    var height = opts.height || 132;
    var pad = 26;
    var lengths = series.map(function (s) { return s.points.length; });
    var count = Math.max.apply(null, lengths.concat([0]));
    if (count < 2) return '<p class="ext-hint">' + esc(__("ext.too_few_points")) + "</p>";

    var all = [];
    series.forEach(function (s) { all = all.concat(s.points.filter(isFinite)); });
    var lo = Math.min.apply(null, all);
    var hi = Math.max.apply(null, all);
    if (lo === hi) { lo -= 1; hi += 1; }

    function x(i) { return pad + (i * (width - pad * 2)) / (count - 1); }
    function y(v) { return height - pad - ((v - lo) / (hi - lo)) * (height - pad * 2); }

    var paths = series.map(function (s) {
      var d = s.points.map(function (v, i) {
        return (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1);
      }).join(" ");
      return '<path d="' + d + '" fill="none" stroke="' + s.color + '" stroke-width="1.8" />';
    }).join("");

    var legend = series.map(function (s) {
      return '<span><i style="background:' + s.color + '"></i>' + esc(s.label) + "</span>";
    }).join("");

    return (
      '<svg class="ext-chart" viewBox="0 0 ' + width + " " + height + '" preserveAspectRatio="none" role="img">' +
      '<line x1="' + pad + '" y1="' + (height - pad) + '" x2="' + (width - pad) + '" y2="' + (height - pad) +
      '" stroke="#dde6de" />' +
      paths +
      '<text x="' + pad + '" y="14" font-size="10" fill="#66746c">' + esc(opts.hiLabel || String(Math.round(hi))) + "</text>" +
      '<text x="' + pad + '" y="' + (height - 6) + '" font-size="10" fill="#66746c">' +
      esc(opts.loLabel || String(Math.round(lo))) + "</text>" +
      "</svg>" +
      '<div class="ext-chart-legend">' + legend + "</div>"
    );
  }

  function tiles(items) {
    return '<div class="ext-tiles">' + items.map(function (t) {
      return '<div class="ext-tile' + (t.warn ? " is-warn" : "") + '"><b>' + esc(t.value) +
        "</b><span>" + esc(t.label) + (t.help ? tip(t.help) : "") + "</span></div>";
    }).join("") + "</div>";
  }

  /* --------------------------------------------------------- config editor */

  function pathKey(prefix, key) {
    return prefix ? prefix + "." + key : String(key);
  }

  function currentValue(path, fallback) {
    return Object.prototype.hasOwnProperty.call(state.dirty, path) ? state.dirty[path] : fallback;
  }

  function fieldClass(path) {
    return "ext-field" +
      (Object.prototype.hasOwnProperty.call(state.dirty, path) ? " is-dirty" : "") +
      (state.invalid[path] ? " is-bad" : "");
  }

  /** 按 JSON 形状渲染控件。数组和无法判型的值退化为 JSON 文本框。
   *  每个节点带一个 hover 说明（`HELP` 里查得到的话），说的是"改了会怎样"。 */
  function renderNode(key, value, path, depth) {
    var hint = tip(path, key);

    if (value && typeof value === "object" && !Array.isArray(value)) {
      var body = Object.keys(value).map(function (childKey) {
        return renderNode(childKey, value[childKey], pathKey(path, childKey), depth + 1);
      }).join("");
      return '<details class="ext-group"' + (depth === 0 ? " open" : "") + ">" +
        "<summary>" + esc(label(key)) + hint + "</summary>" +
        '<div class="ext-group-body">' + body + "</div></details>";
    }

    if (typeof value === "boolean") {
      var on = currentValue(path, value);
      return '<label class="' + fieldClass(path) + ' inline">' +
        '<input type="checkbox" data-path="' + esc(path) + '" data-kind="bool"' + (on ? " checked" : "") + " />" +
        "<span>" + esc(label(key)) + hint + "</span></label>";
    }

    if (typeof value === "number") {
      return '<label class="' + fieldClass(path) + '"><span>' + esc(label(key)) + hint + "</span>" +
        '<input type="number" step="any" data-path="' + esc(path) + '" data-kind="number" value="' +
        esc(currentValue(path, value)) + '" /></label>';
    }

    if (typeof value === "string") {
      return '<label class="' + fieldClass(path) + '"><span>' + esc(label(key)) + hint + "</span>" +
        '<input type="text" data-path="' + esc(path) + '" data-kind="text" value="' +
        esc(currentValue(path, value)) + '" /></label>';
    }

    // 数组 / null：JSON 文本框。结构化控件在这里得不偿失，而 JSON 是可校验的。
    var raw = currentValue(path, value);
    var text = typeof raw === "string" && state.invalid[path] ? raw : JSON.stringify(raw);
    return '<label class="' + fieldClass(path) + '"><span>' + esc(label(key)) + hint +
      (state.invalid[path] ? ' <b class="ext-warn">' + esc(__("ext.json_invalid")) + "</b>" : "") + "</span>" +
      '<textarea data-path="' + esc(path) + '" data-kind="json">' + esc(text) + "</textarea></label>";
  }

  function renderConfigEditor(config) {
    var keys = Object.keys(config || {});
    if (!keys.length) return '<p class="ext-hint">' + esc(__("ext.no_editable")) + "</p>";
    return keys.map(function (key) {
      return renderNode(key, config[key], key, 0);
    }).join("");
  }

  function dirtyCount() {
    return Object.keys(state.dirty).length;
  }

  /** 把扁平的 dirty 路径还原成嵌套补丁。 */
  function buildPatch() {
    var patch = {};
    Object.keys(state.dirty).forEach(function (path) {
      var parts = path.split(".");
      var node = patch;
      for (var i = 0; i < parts.length - 1; i++) {
        if (typeof node[parts[i]] !== "object" || node[parts[i]] === null) node[parts[i]] = {};
        node = node[parts[i]];
      }
      node[parts[parts.length - 1]] = state.dirty[path];
    });
    return patch;
  }

  /* -------------------------------------------------------- observe: money */

  function renderCurrencyObserve(data) {
    var rt = data.runtime;
    var macro = rt.macro || {};
    var cons = rt.conservation || {};
    var latest = cons.latest;
    var wealth = rt.wealth || {};
    var sectors = rt.sectors || {};

    var head = tiles([
      { label: __("ext.tile_phase"), value: phaseShort(macro.phase) || "—", help: "tile.phase" },
      { label: __("ext.tile_inflation"), value: pct(macro.inflation_rate), help: "tile.inflation" },
      { label: __("ext.tile_unemployment"), value: pct(macro.unemployment_rate), help: "tile.unemployment" },
      { label: __("ext.tile_price_index"), value: fixed(macro.cumulative_inflation, 4), help: "tile.price_index" },
      {
        label: __("ext.tile_money_total"),
        value: money(latest ? latest.system_total : rt.money_stock.final_system_total),
        help: "tile.money_total",
      },
      {
        label: __("ext.tile_drift"),
        value: cons.max_abs_drift == null ? "—" : money(cons.max_abs_drift),
        warn: cons.ok === false,
        help: "tile.drift",
      },
      { label: __("ext.tile_gini"), value: wealth.gini == null ? "—" : fixed(wealth.gini, 4), help: "tile.gini" },
      {
        label: __("ext.tile_indebted"),
        value: (wealth.indebted_agents || 0) + " / " + (wealth.agents || 0),
        help: "tile.indebted",
      },
    ]);

    var sectorRows = ["firms", "government", "bank"].map(function (name) {
      var cn = __("ext.pool_" + name);
      return "<tr><td>" + cn + " <code>" + name + "</code></td><td class=\"num\">" +
        money(sectors[name]) + "</td></tr>";
    }).join("");

    var injected = Number(rt.money_stock.intervention_injected_total || 0);
    var conservationNote = cons.ok === false
      ? '<p class="ext-hint ext-warn">' + esc(__("ext.cons_drift")) + "</p>"
      : cons.ok === true
        ? '<p class="ext-hint ext-ok">' + esc(__("ext.cons_ok")) + "</p>"
        : '<p class="ext-hint">' + esc(__("ext.cons_none")) + "</p>";

    var ledger = rt.ledger || [];
    var ledgerChart = lineChart(
      [
        { label: __("ext.series_income"), color: "#0e7a58", points: ledger.map(function (d) { return d.income; }) },
        { label: __("ext.series_expense"), color: "#c04545", points: ledger.map(function (d) { return d.expense; }) },
      ],
      { hiLabel: __("ext.axis_high"), loLabel: __("ext.axis_low") }
    );

    var totalChart = lineChart(
      [{ label: __("ext.tile_money_total"), color: "#3c5a68", points: (cons.rows || []).map(function (r) { return r.system_total; }) }],
      { hiLabel: __("ext.axis_high"), loLabel: __("ext.axis_low") }
    );

    var iv = rt.interventions || { pending: [], applied: [] };
    var pendingList = iv.pending.length
      ? '<ul class="ext-queue">' + iv.pending.map(function (item) {
        return "<li><b>" + esc(item.id) + "</b> · " +
          (item.day == null ? esc(__("ext.iv_next_day")) : esc(__f("ext.iv_on_day", { day: item.day }))) +
          (item.note ? " · " + esc(item.note) : "") +
          "<br/><code>" + esc(JSON.stringify({ macro: item.macro, sector_delta: item.sector_delta })) + "</code></li>";
      }).join("") + "</ul>"
      : '<p class="ext-hint">' + esc(__("ext.iv_none_pending")) + "</p>";

    var appliedList = (iv.applied || []).length
      ? '<ul class="ext-queue">' + iv.applied.slice().reverse().map(function (item) {
        return "<li><b>" + esc(__f("ext.iv_applied_day", { day: item.applied_day })) + "</b> · " + esc(item.id) +
          (item.note ? " · " + esc(item.note) : "") +
          "<br/><code>" + esc(JSON.stringify({
            macro: item.applied_macro, sector_delta: item.applied_sector_delta,
          })) + "</code></li>";
      }).join("") + "</ul>"
      : '<p class="ext-hint">' + esc(__("ext.iv_none_applied")) + "</p>";

    return (
      '<div class="ext-card"><h2>' + esc(__("ext.currency_title")) + "</h2>" +
      '<p class="ext-lede">' + __f("ext.currency_lede", { path: esc(rt.output_dir) }) + "</p>" +
      head +
      "<h3>" + esc(__("ext.sector_balances")) + tip("block.sectors") + "</h3>" +
      '<table class="ext-table"><thead><tr><th>' + esc(__("ext.col_sector")) +
        '</th><th class="num">' + esc(__("ext.col_balance")) + "</th></tr></thead><tbody>" +
      sectorRows +
      (injected ? "<tr><td>" + esc(__("ext.injected_total")) + tip("iv.sector") +
        '</td><td class="num">' + money(injected) + "</td></tr>" : "") +
      "</tbody></table>" +
      "<h3>" + esc(__("ext.conservation")) + tip("block.conservation") + "</h3>" + conservationNote + totalChart +
      "<h3>" + esc(__("ext.daily_ledger")) + tip("block.ledger") + "</h3>" + ledgerChart +
      "</div>" +

      '<div class="ext-card"><h2>' + esc(__("ext.wealth_title")) + tip("block.wealth") + "</h2>" +
      '<p class="ext-lede">' + esc(__("ext.wealth_lede")) + "</p>" +
      '<table class="ext-table"><tbody>' +
      [[__("ext.w_residents"), wealth.agents || 0],
       [__("ext.w_total"), money(wealth.total_balance)],
       [__("ext.w_mean"), money(wealth.mean_balance)],
       [__("ext.w_median"), money(wealth.median_balance), __("ext.w_median_help")],
       [__("ext.w_minmax"), money(wealth.min_balance) + " / " + money(wealth.max_balance)],
       [__("ext.w_fund"), money(wealth.total_housing_fund), __("ext.w_fund_help")],
       [__("ext.w_debt"), money(wealth.total_debt)],
       [__("ext.w_gini"), wealth.gini == null ? __("ext.w_gini_na") : fixed(wealth.gini, 4), helpText("tile.gini")]]
        .map(function (row) {
          var hint = row[2] ? ' <span class="help-tip" data-help="' + esc(row[2]) + '"></span>' : "";
          return "<tr><td>" + esc(row[0]) + hint + '</td><td class="num">' + esc(row[1]) + "</td></tr>";
        }).join("") +
      "</tbody></table></div>" +

      '<div class="ext-card"><h2>' + esc(__("ext.queue_title")) + tip("block.queue") + "</h2>" +
      '<p class="ext-lede">' + __f("ext.queue_lede", { path: esc(iv.path) }) + "</p>" +
      "<h3>" + esc(__("ext.queue_pending")) + "</h3>" + pendingList +
      "<h3>" + esc(__("ext.queue_applied")) + "</h3>" + appliedList +
      "</div>"
    );
  }

  function renderCurrencyEdit(data) {
    var macro = (data.runtime && data.runtime.macro) || {};
    var phases = ["", "expansion", "peak", "contraction", "trough"];
    var options = phases.map(function (p) {
      return '<option value="' + esc(p) + '">' + (p ? esc(phaseLabel(p)) : esc(__("ext.no_change"))) + "</option>";
    }).join("");

    return (
      '<div class="ext-edit-card"><h3>' + esc(__("ext.iv_form_title")) + tip("iv.form") + "</h3>" +
      '<p class="ext-note">' + __("ext.iv_form_lede") + "</p>" +
      '<label class="ext-field"><span>' +
      esc(__f("ext.iv_phase_current", { phase: phaseLabel(macro.phase) || "—" })) +
      tip("iv.phase") + "</span>" +
      '<select id="ivPhase">' + options + "</select></label>" +
      '<div class="ext-row">' +
      '<label class="ext-field"><span>' +
      esc(__f("ext.iv_inflation_current", { value: pct(macro.inflation_rate) })) +
      tip("iv.inflation") + "</span>" +
      '<input type="number" step="any" id="ivInflation" placeholder="0.08" /></label>' +
      '<label class="ext-field"><span>' +
      esc(__f("ext.iv_unemployment_current", { value: pct(macro.unemployment_rate) })) +
      tip("iv.unemployment") + "</span>" +
      '<input type="number" step="any" id="ivUnemployment" placeholder="0.09" /></label>' +
      "</div>" +
      '<div class="ext-row">' +
      '<label class="ext-field"><span>' + esc(__("ext.iv_firms")) + tip("iv.sector") +
        '</span><input type="number" step="any" id="ivFirms" /></label>' +
      '<label class="ext-field"><span>' + esc(__("ext.iv_government")) + tip("iv.sector") +
        '</span><input type="number" step="any" id="ivGovernment" /></label>' +
      '<label class="ext-field"><span>' + esc(__("ext.iv_bank")) + tip("iv.sector") +
        '</span><input type="number" step="any" id="ivBank" /></label>' +
      "</div>" +
      '<div class="ext-row">' +
      '<label class="ext-field"><span>' + esc(__("ext.iv_day")) + tip("iv.day") +
        '</span><input type="number" step="1" id="ivDay" /></label>' +
      '<label class="ext-field"><span>' + esc(__("ext.iv_note")) + tip("iv.note") +
        '</span><input type="text" id="ivNote" placeholder="' + esc(__("ext.iv_note_ph")) + '" /></label>' +
      "</div>" +
      '<div class="ext-edit-actions">' +
      '<button class="button" id="ivSubmit">' + esc(__("ext.iv_submit")) + "</button>" +
      '<button class="button subtle" id="ivClear">' + esc(__("ext.iv_clear")) + "</button>" +
      "</div></div>" +
      renderConfigCard("currency", data.config, __("ext.cfg_currency_hint"))
    );
  }

  /* --------------------------------------------------- observe: environment */

  function renderTrafficCard(traffic) {
    if (!traffic || !traffic.available) {
      return '<div class="ext-card"><h2>' + esc(__("ext.traffic_title")) + "</h2>" +
        '<p class="ext-hint">' + __("ext.traffic_off") + "</p></div>";
    }
    // "Never congested" is the reading that matters on a small population:
    // it means every trip ran at free flow, not that the model is quiet.
    var quiet = !traffic.ever_congested;
    var rows = (traffic.ticks || []).slice().reverse().slice(0, 12).map(function (tick) {
      var busiest = (tick.busiest || []).map(function (item) {
        return '<span class="ext-badge">' + esc(String(item.edge).replace("||", " ↔ ")) +
          " ×" + esc(fixed(item.factor, 2)) + "</span>";
      }).join("");
      return '<div class="ext-event"><div class="ext-event-head">' +
        "<b>" + esc(__f("ext.env_day", { day: tick._day })) + " " + esc(tick._time || "") + "</b>" +
        '<span class="ext-badge">' + esc(__f("ext.traffic_edges", {
          congested: tick.edges_congested, loaded: tick.edges_loaded,
        })) + "</span>" +
        '<span class="ext-badge">' + esc(__f("ext.traffic_flow", { pcu: tick.flow_pcu })) + "</span>" +
        busiest + "</div></div>";
    }).join("");

    return (
      '<div class="ext-card"><h2>' + esc(__("ext.traffic_title")) + "</h2>" +
      '<p class="ext-lede">' + __f("ext.traffic_lede", { path: esc(traffic.records_path) }) + "。</p>" +
      tiles([
        { label: __("ext.traffic_peak"), value: fixed(traffic.peak_congestion, 2) + "×",
          help: "traffic.peak", warn: quiet },
        { label: __("ext.traffic_congested_ticks"),
          value: traffic.congested_ticks + " / " + traffic.tick_count,
          help: "traffic.congested_ticks", warn: quiet },
        { label: __("ext.traffic_peak_flow"), value: fixed(traffic.peak_flow_pcu, 1),
          help: "traffic.peak_flow" },
      ]) +
      (quiet ? '<p class="ext-hint">' + __("ext.traffic_never") + "</p>" : rows) +
      "</div>"
    );
  }

  function renderEnvironmentObserve(data) {
    var rt = data.runtime;
    if (!rt.available) {
      return '<div class="ext-card"><h2>' + esc(__("ext.env_title")) + "</h2>" +
        '<p class="ext-hint">' + __("ext.env_empty") + "</p></div>" +
        renderTrafficCard(data.traffic);
    }

    var counts = rt.event_type_counts || {};
    var countTiles = Object.keys(counts).map(function (key) {
      return { label: __f("ext.evt_count_label", { type: typeLabel(key) }), value: counts[key], help: "env.type" };
    });

    var days = (rt.days || []).slice().reverse().map(function (day) {
      var events = (day.events || []).map(function (ev) {
        var sev = Number(ev.severity) || 0;
        return '<div class="ext-event"><div class="ext-event-head">' +
          '<span class="ext-badge t-' + esc(ev.type) + '" data-help="' + esc(helpText("env.type")) + '">' +
          esc(typeLabel(ev.type)) + "</span>" +
          "<b>" + esc(ev.name) + "</b>" +
          '<span class="ext-sev' + (sev >= 0.6 ? " high" : "") +
          '" data-help="' + esc(__f("ext.severity_prefix", { value: sev }) + helpText("env.sev_bar")) +
          '"><i style="width:' + Math.round(Math.min(1, sev) * 100) + '%"></i></span>' +
          (ev.impact_tags || []).map(function (tag) {
            return '<span class="ext-badge" data-help="' + esc(helpText("env.tags")) + '">' + esc(tag) + "</span>";
          }).join("") +
          "</div><p>" + esc(ev.description) + "</p></div>";
      }).join("");
      return '<div class="ext-day"><div class="ext-day-head"><b>' +
        esc(__f("ext.env_day", { day: day.day })) + "</b>" +
        "<span>" + esc(day.date || "") + "</span></div>" +
        '<p class="ext-day-summary">' + esc(day.summary || "") + "</p>" + events + "</div>";
    }).join("");

    return (
      '<div class="ext-card"><h2>' + esc(__("ext.env_overview_title")) + "</h2>" +
      '<p class="ext-lede">' + __f("ext.env_overview_lede", { path: esc(rt.timeline_path) }) + "。</p>" +
      tiles([
        {
          label: __("ext.env_latest_day"),
          value: rt.latest_day == null ? "—" : __f("ext.env_day", { day: rt.latest_day }),
          help: "env.latest_day",
        },
        { label: __("ext.env_day_count"), value: rt.day_count, help: "env.day_count" },
        { label: __("ext.env_ticks"), value: rt.tick_records, help: "env.ticks" },
        {
          label: __("ext.env_severity"),
          value: rt.mean_severity == null ? "—" : fixed(rt.mean_severity, 3),
          help: "env.severity",
        },
      ].concat(countTiles)) +
      "</div>" +
      '<div class="ext-card"><h2>' +
      esc(__f("ext.env_recent_title", { days: (rt.days || []).length })) + "</h2>" +
      (days || '<p class="ext-hint">' + esc(__("ext.env_no_events")) + "</p>") + "</div>" +
      renderTrafficCard(data.traffic)
    );
  }

  function renderEnvironmentEdit(data) {
    return renderConfigCard("environment", data.config, __("ext.cfg_env_hint"));
  }

  /* ------------------------------------------------------ observe: services */

  function renderServicesObserve(data) {
    var rt = data.runtime;
    var probed = {};
    ((state.health && state.health.targets) || []).forEach(function (t) { probed[t.id] = t; });

    var rows = (rt.targets || []).map(function (target) {
      var result = probed[target.id];
      var cls = result ? result.status : (target.enabled ? "" : "disabled");
      var text;
      if (!result) {
        text = __(target.enabled ? "ext.svc_unprobed" : "ext.svc_disabled");
      } else {
        // `latency_ms` is absent for a target that was never dialled, so it is
        // appended only when a probe actually happened.
        text = healthLabel(result.status) +
          "（" + (result.detail || "") +
          (result.latency_ms == null ? "" : "，" + result.latency_ms + "ms") + "）";
      }
      return "<tr><td>" + esc(target.label) + "</td>" +
        "<td><code>" + esc(target.url || "—") + "</code></td>" +
        '<td data-help="' + esc(helpText("svc.status")) + '"><span class="ext-dot ' + esc(cls) + '"></span>' +
        esc(text) + "</td></tr>";
    }).join("");

    var tasks = (rt.llm_routing && rt.llm_routing.tasks) || {};
    var taskRows = Object.keys(tasks).map(function (key) {
      return "<tr><td>" + esc(key) + "</td><td>" + esc(tasks[key]) + "</td></tr>";
    }).join("") || '<tr><td colspan="2">' + esc(__("ext.svc_all_default")) + "</td></tr>";

    return (
      '<div class="ext-card"><h2>' + esc(__("ext.svc_title")) + tip("svc.probe") + "</h2>" +
      '<p class="ext-lede">' + esc(__("ext.svc_lede")) + "</p>" +
      '<table class="ext-table"><thead><tr><th>' + esc(__("ext.svc_col_service")) +
        "</th><th>" + esc(__("ext.svc_col_url")) + "</th><th>" + esc(__("ext.svc_col_status")) +
        tip("svc.status") + "</th></tr></thead><tbody>" +
      (rows || '<tr><td colspan="3">' + esc(__("ext.svc_none")) + "</td></tr>") + "</tbody></table>" +
      '<div class="ext-edit-actions"><button class="button subtle" id="svcProbe">' +
        esc(__("ext.svc_probe_btn")) + "</button>" +
      '<span class="ext-note">' + esc(state.health
        ? __("ext.svc_last_probe") + state.health.checked_at
        : __("ext.svc_never")) + "</span></div>" +
      "</div>" +

      '<div class="ext-card"><h2>' + esc(__("ext.llm_title")) + tip("svc.llm") + "</h2>" +
      '<p class="ext-lede">' + esc(__("ext.llm_lede")) + "</p>" +
      tiles([
        { label: __("ext.llm_available"), value: (rt.llm_providers || []).length },
        { label: __("ext.llm_default"), value: (rt.llm_routing && rt.llm_routing["default"]) || "—", help: "default" },
      ]) +
      "<h3>" + esc(__("ext.llm_list")) + '</h3><p class="ext-hint">' +
        esc((rt.llm_providers || []).join(" · ") || __("ext.llm_none")) + "</p>" +
      "<h3>" + esc(__("ext.llm_per_task")) + "</h3>" +
      '<table class="ext-table"><thead><tr><th>' + esc(__("ext.llm_col_task")) +
        "</th><th>" + esc(__("ext.llm_col_model")) + "</th></tr></thead><tbody>" +
        taskRows + "</tbody></table>" +
      "</div>" +

      '<div class="ext-card"><h2>' + esc(__("ext.src_title")) + tip("svc.news") + "</h2>" +
      tiles([
        { label: __("ext.src_cached"), value: (rt.news_cache && rt.news_cache.entries) || 0, help: "svc.news" },
        {
          label: __("ext.src_cache_file"),
          value: __((rt.news_cache && rt.news_cache.exists) ? "ext.exists" : "ext.missing"),
        },
      ]) +
      '<p class="ext-hint">' + esc(__("ext.src_cache_path")) + "<code>" +
        esc((rt.news_cache && rt.news_cache.path) || "—") + "</code></p></div>"
    );
  }

  function renderServicesEdit(data) {
    return renderConfigCard("services", data.config, __("ext.cfg_svc_hint"));
  }

  /* -------------------------------------------------------------- rendering */

  function renderConfigCard(tab, config, note) {
    var count = dirtyCount();
    return (
      '<div class="ext-edit-card"><h3>' + esc(__("ext.cfg_title")) + tip("cfg.card") + "</h3>" +
      '<p class="ext-note">' + esc(note) + "</p>" +
      '<div id="extConfigTree">' + renderConfigEditor(config) + "</div>" +
      '<div class="ext-edit-actions">' +
      '<button class="button" id="cfgSave"' + (count ? "" : " disabled") + ">" +
        esc(count ? __f("ext.save_n", { count: count }) : __("ext.save")) + "</button>" +
      '<button class="button subtle" id="cfgReset"' + (count ? "" : " disabled") + ">" +
        esc(__("ext.discard")) + "</button>" +
      "</div></div>"
    );
  }

  var RENDERERS = {
    currency: { observe: renderCurrencyObserve, edit: renderCurrencyEdit },
    environment: { observe: renderEnvironmentObserve, edit: renderEnvironmentEdit },
    services: { observe: renderServicesObserve, edit: renderServicesEdit },
  };

  function render() {
    var data = state.data && state.data[state.tab];
    if (!data) {
      $("extObserve").innerHTML =
        '<div class="ext-card"><p class="ext-hint">' + esc(__("ext.loading")) + "</p></div>";
      $("extEdit").innerHTML = "";
      return;
    }
    var renderer = RENDERERS[state.tab];
    $("extObserve").innerHTML = renderer.observe(data);
    $("extEdit").innerHTML = renderer.edit(data);

    Array.prototype.forEach.call(document.querySelectorAll("#extTabs .step"), function (btn) {
      btn.classList.toggle("is-active", btn.dataset.tab === state.tab);
    });

    var meta = $("extTopMeta");
    if (meta) {
      meta.innerHTML = esc(__f("ext.observed_at", { at: state.data.generated_at })) +
        (dirtyCount() ? "<br/>" + __f("ext.unsaved_n", { count: dirtyCount() }) : "");
    }

    // 每次渲染都重建了 innerHTML，之前绑好的「?」全没了，要重新扫一遍。
    if (window.HelpTips) window.HelpTips.scan();
  }

  function load() {
    return api("GET", "/api/external-systems/overview").then(function (payload) {
      if (payload.error) {
        $("extObserve").innerHTML = '<div class="ext-card"><h2>' + esc(__("ext.load_failed")) +
          '</h2><p class="ext-warn">' + esc(payload.error) + "</p></div>";
        status(payload.error, "err");
        return;
      }
      state.data = payload;
      render();
    });
  }

  /* ---------------------------------------------------------------- actions */

  function onConfigInput(event) {
    var el = event.target;
    var path = el.dataset && el.dataset.path;
    if (!path) return;
    var kind = el.dataset.kind;

    if (kind === "bool") {
      state.dirty[path] = el.checked;
    } else if (kind === "number") {
      if (el.value === "") { delete state.dirty[path]; } else { state.dirty[path] = Number(el.value); }
    } else if (kind === "json") {
      try {
        state.dirty[path] = JSON.parse(el.value);
        delete state.invalid[path];
      } catch (err) {
        state.dirty[path] = el.value;
        state.invalid[path] = true;
      }
    } else {
      state.dirty[path] = el.value;
    }
    el.parentNode.classList.add("is-dirty");
    el.parentNode.classList.toggle("is-bad", !!state.invalid[path]);
    syncSaveButton();
  }

  function syncSaveButton() {
    var count = dirtyCount();
    var save = $("cfgSave");
    var reset = $("cfgReset");
    if (save) {
      save.disabled = !count;
      save.textContent = count ? __f("ext.save_n", { count: count }) : __("ext.save");
    }
    if (reset) reset.disabled = !count;
    var meta = $("extTopMeta");
    if (meta && state.data) {
      meta.innerHTML = esc(__f("ext.observed_at", { at: state.data.generated_at })) +
        (count ? "<br/>" + __f("ext.unsaved_n", { count: count }) : "");
    }
  }

  function saveConfig() {
    var bad = Object.keys(state.invalid);
    if (bad.length) {
      status(__f("ext.json_errors", { count: bad.length, paths: bad.join("、") }), "err");
      return;
    }
    if (!dirtyCount()) return;
    status(__("ext.saving"));
    api("POST", "/api/external-systems/config", { config: buildPatch() }).then(function (res) {
      if (res.error) { status(res.error, "err"); return; }
      state.dirty = {};
      state.invalid = {};
      var dropped = res.dropped || [];
      status(
        __f("ext.saved_n", { count: (res.applied || []).join("、") }) +
        (dropped.length ? __f("ext.dropped_keys", { keys: dropped.join("、") }) : ""),
        dropped.length ? "err" : "ok"
      );
      load();
    });
  }

  function submitIntervention() {
    var macro = {};
    var phase = $("ivPhase").value;
    if (phase) macro.phase = phase;
    if ($("ivInflation").value !== "") macro.inflation_rate = Number($("ivInflation").value);
    if ($("ivUnemployment").value !== "") macro.unemployment_rate = Number($("ivUnemployment").value);

    var sector = {};
    ["Firms:firms", "Government:government", "Bank:bank"].forEach(function (pair) {
      var parts = pair.split(":");
      var value = $("iv" + parts[0]).value;
      if (value !== "") sector[parts[1]] = Number(value);
    });

    status(__("ext.submitting_iv"));
    api("POST", "/api/external-systems/interventions", {
      macro: macro,
      sector_delta: sector,
      day: $("ivDay").value,
      note: $("ivNote").value,
    }).then(function (res) {
      if (res.error) { status(res.error, "err"); return; }
      status(__f("ext.iv_queued", { id: res.queued.id }), "ok");
      load();
    });
  }

  function clearInterventions() {
    api("POST", "/api/external-systems/interventions/cancel", { all: true }).then(function (res) {
      if (res.error) { status(res.error, "err"); return; }
      status(__f("ext.iv_cleared_n", { count: res.removed }), "ok");
      load();
    });
  }

  function probeServices() {
    status(__("ext.probing"));
    api("GET", "/api/external-systems/health").then(function (res) {
      if (res.error) { status(res.error, "err"); return; }
      state.health = res;
      status(__("ext.probe_done"), "ok");
      render();
    });
  }

  /* ------------------------------------------------------------------- boot */

  function switchTab(tab) {
    if (TABS.indexOf(tab) < 0 || tab === state.tab) return;
    if (dirtyCount() && !window.confirm(__("ext.confirm_switch"))) return;
    state.dirty = {};
    state.invalid = {};
    state.tab = tab;
    status("");
    render();
  }

  function boot() {
    $("extTabs").addEventListener("click", function (event) {
      var btn = event.target.closest(".step");
      if (btn) switchTab(btn.dataset.tab);
    });

    $("extEdit").addEventListener("change", onConfigInput);
    $("extEdit").addEventListener("click", function (event) {
      var id = event.target.id;
      if (id === "cfgSave") saveConfig();
      else if (id === "cfgReset") { state.dirty = {}; state.invalid = {}; status(""); render(); }
      else if (id === "ivSubmit") submitIntervention();
      else if (id === "ivClear") clearInterventions();
    });

    $("extObserve").addEventListener("click", function (event) {
      if (event.target.id === "svcProbe") probeServices();
    });

    $("extRefresh").addEventListener("click", function () {
      status(__("ext.refreshing"));
      load().then(function () { status(__("ext.refreshed"), "ok"); });
    });

    load();
  }

  /* Every label, tile and note here is drawn from JS, and the field labels come
     from the payload already in `state.data` in both languages — so a language
     switch just re-runs render() over what is loaded. No refetch. Transient
     status messages are left as written: they are a record of something that
     already happened. */
  document.addEventListener("locale-changed", function () {
    if (!state.data) return;
    render();
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
