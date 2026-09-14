// Analytics view: renders the artifacts of a finished (or running) simulation
// as SVG. No chart library — every figure below is a string of SVG built from
// the /api/analytics/* payloads, so the page works fully offline.
//
// Any past run can be analysed, not just the current one: /api/analytics/runs
// lists the live run, the archives the visualizer keeps under
// <visualization>/runs/ and the scenario (compare-event) runs, each tagged with
// the sections its artifacts can fill. The selection rides in ?run= so a run is
// linkable.
(function () {
  "use strict";

  var PALETTE = [
    "#0e7a58", "#3c5a68", "#d6a81e", "#c04545", "#7b5ea7",
    "#17936c", "#b3703a", "#4a7fb5", "#8a9a3f", "#a4478b",
  ];

  /* The seeded state variables, finance rows and time bands get a translated
     label; anything else the simulator emits falls back to its raw key.
     These are the machine keys, not the text — the text comes from the locale
     at call time, because a module-level literal would freeze whatever language
     was current when this file was evaluated. */
  var METRIC_KEYS = [
    "emotion", "stress", "econ_security", "city_identity", "policy_sensitivity",
    "platform_dependence", "risk_preference", "voice_propensity", "mobility_intent",
    "energy", "fatigue_debt", "hunger", "social_need", "self_control",
    "time_pressure", "stance_score", "toxicity_score", "misinformation_risk",
    "cross_viewpoint_exposure", "intervention_reward", "metric",
  ];
  var ECON_KEYS = [
    "balance", "income", "expense", "checking", "savings", "investment",
    "debt", "econ_security", "engel_coefficient",
  ];
  var PERIOD_KEYS = ["morning", "noon", "afternoon", "evening", "night"];

  /* `key` doubles as an identifier elsewhere, so an unknown one is shown raw
     rather than replaced by a missing-key name. */
  function lookup(known, prefix, key) {
    return known.indexOf(key) >= 0 ? __(prefix + String(key).replace(/-/g, "_")) : key;
  }
  function econLabel(key) { return lookup(ECON_KEYS, "an.econ_", key); }
  function periodLabel(key) { return lookup(PERIOD_KEYS, "an.period_", key); }
  function sectionLabel(key) { return lookup(SECTION_KEYS, "an.section_", key); }

  /* The exporter takes plain maps, so build them from the current locale each
     time rather than handing it a table frozen at load. */
  function labelTables() {
    function table(keys, prefix) {
      var out = {};
      keys.forEach(function (key) { out[key] = __(prefix + key.replace(/-/g, "_")); });
      return out;
    }
    return {
      metric: table(METRIC_KEYS, "an.metric_"),
      econ: table(ECON_KEYS, "an.econ_"),
      period: table(PERIOD_KEYS, "an.period_"),
      // The exporter is pure and reaches for no globals, so the translator and
      // the language tag for the HTML report travel with the labels.
      t: __,
      lang: typeof getLocale === "function" ? getLocale() : "zh-CN",
    };
  }

  var EVENT_COLORS = {
    natural: "#3c5a68", technology: "#7b5ea7", policy: "#0e7a58",
    economy: "#d6a81e", social: "#c04545", health: "#b3703a",
  };

  var state = {
    overview: null, history: null, economy: null,
    social: null, behavior: null, events: null,
    metrics: [],        // selected state metrics
    agents: [],         // selected agent ids (strings)
    econSeries: ["balance", "income", "expense"],
    runs: [],           // every analysable run, newest first
    runId: "",          // "" = the current run
    runInfo: null,      // the selected entry of state.runs
  };

  var SECTION_KEYS = ["state-history", "economy", "social", "behavior", "events"];
  var exporter = window.GAWorldAnalyticsExport;

  function $(id) { return document.getElementById(id); }

  function esc(text) {
    return String(text == null ? "" : text).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function metricLabel(key) { return lookup(METRIC_KEYS, "an.metric_", key); }
  function color(index) { return PALETTE[index % PALETTE.length]; }
  function num(value, digits) {
    if (value == null || isNaN(value)) return "—";
    return Number(value).toFixed(digits == null ? 2 : digits);
  }
  function compact(value) {
    if (value == null || isNaN(value)) return "—";
    var abs = Math.abs(value);
    if (abs >= 1e8) return (value / 1e8).toFixed(2) + __("an.unit_yi");
    if (abs >= 1e4) return (value / 1e4).toFixed(2) + __("an.unit_wan");
    return Number(value).toFixed(abs >= 100 ? 0 : 2);
  }

  async function api(path, params) {
    var query = params ? "?" + new URLSearchParams(params).toString() : "";
    var res = await fetch(path + query, { headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error(path + " → HTTP " + res.status);
    return res.json();
  }

  // Every section of one page load reads the same run.
  function section(name) {
    return api("/api/analytics/" + name, state.runId ? { run: state.runId } : null);
  }

  function note(message) {
    return '<p class="an-empty">' + esc(message) + "</p>";
  }

  /* ------------------------------------------------------------ primitives */

  // Multi-series line chart. Each series is {label, color, points:[y|null]};
  // x is the point index normalized across the longest series.
  function lineChart(series, opts) {
    opts = opts || {};
    var W = 320, H = 150, padL = 34, padR = 8, padT = 10, padB = 20;
    var live = series.filter(function (s) { return s.points && s.points.length; });
    if (!live.length) return note(__("an.no_data"));

    var values = [];
    live.forEach(function (s) {
      s.points.forEach(function (v) { if (v != null && !isNaN(v)) values.push(v); });
    });
    if (!values.length) return note(__("an.no_data"));
    var lo = opts.yMin != null ? opts.yMin : Math.min.apply(null, values);
    var hi = opts.yMax != null ? opts.yMax : Math.max.apply(null, values);
    if (hi - lo < 1e-9) { hi = lo + Math.max(1e-6, Math.abs(lo) * 0.1 || 1); }

    var maxLen = Math.max.apply(null, live.map(function (s) { return s.points.length; }));
    var x = function (i, len) {
      var t = len > 1 ? i / (len - 1) : 0;
      return padL + t * (W - padL - padR);
    };
    var y = function (v) {
      return padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB);
    };

    var grid = "", i;
    for (i = 0; i <= 4; i++) {
      var value = lo + ((hi - lo) * i) / 4;
      var gy = y(value).toFixed(1);
      grid += '<line x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy +
        '" stroke="#e4ece5" stroke-width="1"/>' +
        '<text x="' + (padL - 4) + '" y="' + (Number(gy) + 3).toFixed(1) +
        '" font-size="8" fill="#8a968f" text-anchor="end">' + esc(compact(value)) + "</text>";
    }
    // Zero baseline stands out when a series crosses it (deltas, net income).
    if (lo < 0 && hi > 0) {
      grid += '<line x1="' + padL + '" y1="' + y(0).toFixed(1) + '" x2="' + (W - padR) +
        '" y2="' + y(0).toFixed(1) + '" stroke="#b9c6bc" stroke-width="1" stroke-dasharray="3 3"/>';
    }

    var paths = live.map(function (s, index) {
      var segments = [], open = false;
      s.points.forEach(function (v, idx) {
        if (v == null || isNaN(v)) { open = false; return; }
        segments.push((open ? "L" : "M") + x(idx, s.points.length).toFixed(1) + " " + y(v).toFixed(1));
        open = true;
      });
      if (!segments.length) return "";
      return '<path d="' + segments.join(" ") + '" fill="none" stroke="' +
        (s.color || color(index)) + '" stroke-width="1.7" stroke-linejoin="round"/>';
    }).join("");

    var xAxis = "";
    if (opts.xLabels && opts.xLabels.length) {
      var ticks = [0, Math.floor(opts.xLabels.length / 2), opts.xLabels.length - 1];
      ticks.forEach(function (idx, position) {
        if (idx < 0 || idx >= opts.xLabels.length) return;
        var anchor = position === 0 ? "start" : position === 2 ? "end" : "middle";
        xAxis += '<text x="' + x(idx, opts.xLabels.length).toFixed(1) + '" y="' + (H - 5) +
          '" font-size="8" fill="#8a968f" text-anchor="' + anchor + '">' +
          esc(opts.xLabels[idx]) + "</text>";
      });
    } else {
      xAxis = '<text x="' + (W - padR) + '" y="' + (H - 5) +
        '" font-size="8" fill="#8a968f" text-anchor="end">' +
        esc(__f("an.axis_steps", { count: maxLen })) + "</text>";
    }

    return '<svg class="an-chart" viewBox="0 0 ' + W + " " + H + '" role="img">' +
      grid + paths + xAxis + "</svg>";
  }

  // Horizontal bars. Values may be negative (diverging around a zero axis).
  function barChart(items, opts) {
    opts = opts || {};
    if (!items.length) return note(__("an.no_data"));
    var rowH = 20, W = 320, padL = opts.labelWidth || 96;
    // Reserve room for the longest value label, otherwise long strings such as
    // "0.62 → 1.00" run past the viewBox and get clipped by the card.
    var widest = items.reduce(function (max, item) {
      return Math.max(max, String(item.display || num(item.value, 3)).length);
    }, 0);
    var padR = Math.max(30, widest * 5 + 6);
    var H = items.length * rowH + 6;
    var values = items.map(function (item) { return Number(item.value) || 0; });
    var hi = Math.max.apply(null, values.concat([0]));
    var lo = Math.min.apply(null, values.concat([0]));
    var span = Math.max(hi - lo, 1e-9);
    var plot = W - padL - padR;
    var zero = padL + ((0 - lo) / span) * plot;

    var rows = items.map(function (item, index) {
      var value = Number(item.value) || 0;
      var width = (Math.abs(value) / span) * plot;
      var bx = value >= 0 ? zero : zero - width;
      var cy = index * rowH + 4;
      var fill = item.color || (opts.diverging ? (value >= 0 ? "#0e7a58" : "#c04545") : color(index));
      return '<text x="' + (padL - 6) + '" y="' + (cy + 11) +
        '" font-size="9" fill="#3f4d45" text-anchor="end">' + esc(item.label) + "</text>" +
        '<rect x="' + bx.toFixed(1) + '" y="' + cy + '" width="' + Math.max(width, 1).toFixed(1) +
        '" height="12" rx="2" fill="' + fill + '" opacity="0.85"><title>' +
        esc(item.label + "：" + (item.display || num(value, 3))) + "</title></rect>" +
        '<text x="' + (W - 4) + '" y="' + (cy + 11) +
        '" font-size="8.5" fill="#66746c" text-anchor="end">' +
        esc(item.display || num(value, 3)) + "</text>";
    }).join("");

    var axis = opts.diverging
      ? '<line x1="' + zero.toFixed(1) + '" y1="0" x2="' + zero.toFixed(1) + '" y2="' + H +
        '" stroke="#c4d1c6" stroke-width="1"/>'
      : "";
    return '<svg class="an-chart" viewBox="0 0 ' + W + " " + H + '" role="img">' + axis + rows + "</svg>";
  }

  function radarChart(axes, entries) {
    if (!axes.length || !entries.length) return note(__("an.no_data"));
    var cx = 110, cy = 110, R = 74, n = axes.length;
    var angle = function (i) { return (-90 + (i * 360) / n) * (Math.PI / 180); };
    var point = function (i, r) { return [cx + Math.cos(angle(i)) * r, cy + Math.sin(angle(i)) * r]; };

    var rings = [0.25, 0.5, 0.75, 1].map(function (f) {
      var pts = axes.map(function (_, i) {
        return point(i, R * f).map(function (v) { return v.toFixed(1); }).join(",");
      }).join(" ");
      return '<polygon points="' + pts + '" fill="none" stroke="#d8e3da" stroke-width="1"/>';
    }).join("");

    var labels = axes.map(function (key, i) {
      var p = point(i, R + 16);
      var anchor = Math.abs(p[0] - cx) < 6 ? "middle" : p[0] > cx ? "start" : "end";
      return '<text x="' + p[0].toFixed(1) + '" y="' + (p[1] + 3).toFixed(1) +
        '" font-size="8" fill="#66746c" text-anchor="' + anchor + '">' +
        esc(metricLabel(key)) + "</text>";
    }).join("");

    var shapes = entries.map(function (entry, index) {
      var stroke = entry.color || color(index);
      var pts = axes.map(function (key, i) {
        var v = Math.max(0, Math.min(1, Number(entry.values[key]) || 0));
        return point(i, R * v).map(function (c) { return c.toFixed(1); }).join(",");
      }).join(" ");
      return '<polygon points="' + pts + '" fill="' + stroke + '" fill-opacity="0.13" stroke="' +
        stroke + '" stroke-width="1.6"/>';
    }).join("");

    return '<svg class="an-chart is-compact" viewBox="0 0 220 220" role="img">' +
      rings + shapes + labels + "</svg>";
  }

  function heatmap(rows, cols, lookup, labelFor) {
    if (!rows.length || !cols.length) return note(__("an.no_data"));
    var cellW = 54, cellH = 26, padL = 62, padT = 34;
    var W = padL + cols.length * cellW + 8;
    var H = padT + rows.length * cellH + 6;
    var max = 0;
    rows.forEach(function (r) {
      cols.forEach(function (c) { max = Math.max(max, lookup(r, c) || 0); });
    });
    if (max <= 0) max = 1;

    var header = cols.map(function (c, i) {
      return '<text x="' + (padL + i * cellW + cellW / 2) + '" y="' + (padT - 8) +
        '" font-size="8.5" fill="#66746c" text-anchor="middle">' + esc(c) + "</text>";
    }).join("");

    var body = rows.map(function (r, ri) {
      var label = '<text x="' + (padL - 8) + '" y="' + (padT + ri * cellH + cellH / 2 + 3) +
        '" font-size="9" fill="#3f4d45" text-anchor="end">' + esc(labelFor ? labelFor(r) : r) + "</text>";
      var cells = cols.map(function (c, ci) {
        var value = lookup(r, c) || 0;
        var alpha = value <= 0 ? 0.04 : 0.12 + 0.78 * (value / max);
        return '<rect x="' + (padL + ci * cellW) + '" y="' + (padT + ri * cellH) +
          '" width="' + (cellW - 3) + '" height="' + (cellH - 3) +
          '" rx="3" fill="#0e7a58" fill-opacity="' + alpha.toFixed(3) + '"><title>' +
          esc(String(r) + " · " + String(c) + "：" + num(value, 3)) + "</title></rect>";
      }).join("");
      return label + cells;
    }).join("");

    return '<svg class="an-chart is-compact" viewBox="0 0 ' + W + " " + H + '" role="img">' +
      header + body + "</svg>";
  }

  /* -------------------------------------------------------------- sections */

  function renderOverview() {
    var data = state.overview;
    if (!data) return;
    var span = data.day_span ? "Day " + data.day_span.first + " – " + data.day_span.last : "—";
    var cards = [
      { label: __("an.kpi_agents"), value: data.agent_count,
        hint: __f("an.kpi_metrics_hint", { count: data.metric_count }) },
      { label: __("an.kpi_steps"), value: data.step_count, hint: span },
      { label: __("an.kpi_frames"), value: data.frame_count,
        hint: __(data.finished ? "an.kpi_finished" : "an.kpi_running") },
      { label: __("an.kpi_events"), value: data.event_total, hint: __("an.kpi_events_hint") },
      { label: __("an.kpi_diary"), value: data.diary_count, hint: __("an.kpi_diary_hint") },
      { label: __("an.kpi_relations"), value: data.relationship_total, hint: __("an.kpi_relations_hint") },
    ];
    $("anOverview").innerHTML = cards.map(function (card) {
      return '<article class="an-kpi"><span class="an-kpi-label">' + esc(card.label) +
        '</span><strong class="an-kpi-value">' + esc(card.value == null ? "—" : card.value) +
        '</strong><span class="an-kpi-hint">' + esc(card.hint) + "</span></article>";
    }).join("");

    var movers = (data.top_movers || []).map(function (item) {
      return { label: metricLabel(item.metric), value: item.mean_delta, display: (item.mean_delta > 0 ? "+" : "") + num(item.mean_delta, 3) };
    });
    $("anMovers").innerHTML = movers.length
      ? barChart(movers, { diverging: true })
      : note(__("an.no_movers"));

    var meta = data.sim_meta || {};
    $("anRunMeta").innerHTML = [
      [__("an.meta_sim_days"), meta.sim_days],
      [__("an.meta_seconds"), meta.seconds_per_day],
      [__("an.meta_time_step"), meta.time_step_minutes == null ? __("an.meta_default") : meta.time_step_minutes],
      [__("an.meta_map"), meta.map_path],
      [__("an.meta_generated"), data.generated_at],
      [__("an.meta_updated"), data.last_updated],
    ].map(function (pair) {
      return '<div><dt>' + esc(pair[0]) + "</dt><dd>" + esc(pair[1] == null || pair[1] === "" ? "—" : pair[1]) + "</dd></div>";
    }).join("");
  }

  function agentColor(agentId) {
    var index = (state.history ? state.history.agents : []).findIndex(function (a) {
      return String(a.id) === String(agentId);
    });
    return color(index < 0 ? 0 : index);
  }

  function renderStateControls() {
    var data = state.history;
    if (!data || !data.available) {
      // Switching to a run without state artifacts must not leave the previous
      // run's chips behind.
      $("anMetricPicker").innerHTML = "";
      $("anAgentPicker").innerHTML = "";
      return;
    }
    $("anMetricPicker").innerHTML = data.metrics.map(function (key) {
      var on = state.metrics.indexOf(key) >= 0;
      return '<button type="button" class="an-chip' + (on ? " is-on" : "") +
        '" data-metric="' + esc(key) + '">' + esc(metricLabel(key)) + "</button>";
    }).join("");
    $("anAgentPicker").innerHTML = data.agents.map(function (agent) {
      var on = state.agents.indexOf(String(agent.id)) >= 0;
      return '<button type="button" class="an-chip' + (on ? " is-on" : "") +
        '" data-agent="' + esc(agent.id) + '" style="--chip:' + agentColor(agent.id) + '">' +
        '<i class="an-swatch"></i>' + esc(agent.name) + "</button>";
    }).join("");
  }

  function renderStateCharts() {
    var data = state.history;
    if (!data || !data.available) {
      $("anStateGrid").innerHTML = note(__("an.empty_history"));
      $("anStateDelta").innerHTML = "";
      $("anStateRadar").innerHTML = "";
      return;
    }
    if (!state.metrics.length || !state.agents.length) {
      $("anStateGrid").innerHTML = note(__("an.pick_metric_agent"));
      $("anStateDelta").innerHTML = "";
      $("anStateRadar").innerHTML = "";
      return;
    }

    $("anStateGrid").innerHTML = state.metrics.map(function (metric) {
      var perAgent = data.series[metric] || {};
      var series = state.agents.map(function (agentId) {
        return { label: agentId, color: agentColor(agentId), points: perAgent[agentId] || [] };
      });
      var deltas = data.deltas[metric] || {};
      var mean = state.agents.reduce(function (sum, agentId) {
        var stats = deltas[agentId];
        return sum + (stats && stats.delta != null ? stats.delta : 0);
      }, 0) / state.agents.length;
      var badge = (mean > 0 ? "+" : "") + num(mean, 3);
      return '<article class="an-card"><header class="an-card-head"><h4>' + esc(metricLabel(metric)) +
        '</h4><span class="an-badge ' + (mean >= 0 ? "is-up" : "is-down") + '">Δ ' + esc(badge) +
        "</span></header>" + lineChart(series, { yMin: 0, yMax: 1 }) + "</article>";
    }).join("");

    // Start → end movement, one bar per metric per selected agent.
    var bars = [];
    state.metrics.forEach(function (metric) {
      state.agents.forEach(function (agentId) {
        var stats = (data.deltas[metric] || {})[agentId];
        if (!stats || stats.delta == null) return;
        var name = (data.agents.find(function (a) { return String(a.id) === agentId; }) || {}).name || agentId;
        bars.push({
          label: metricLabel(metric) + (state.agents.length > 1 ? " · " + name : ""),
          value: stats.delta,
          display: num(stats.first, 2) + " → " + num(stats.last, 2),
        });
      });
    });
    $("anStateDelta").innerHTML = bars.length
      ? barChart(bars, { diverging: true, labelWidth: 118 })
      : note(__("an.no_change_data"));

    var axes = state.metrics.slice(0, 9);
    var entries = state.agents.map(function (agentId) {
      var values = {};
      axes.forEach(function (metric) {
        var stats = (data.deltas[metric] || {})[agentId];
        values[metric] = stats ? stats.last : 0;
      });
      return { label: agentId, color: agentColor(agentId), values: values };
    });
    $("anStateRadar").innerHTML = radarChart(axes, entries);
  }

  function renderEconomy() {
    var data = state.economy;
    if (!data || !data.available) {
      $("anEconGrid").innerHTML = note(__("an.empty_economy"));
      $("anEconSeriesPicker").innerHTML = "";
      $("anEconWealth").innerHTML = "";
      $("anEconMacro").innerHTML = "";
      return;
    }

    var ledgers = data.ledger.filter(function (item) {
      return !state.agents.length || state.agents.indexOf(String(item.id)) >= 0;
    });
    if (!ledgers.length) ledgers = data.ledger;

    $("anEconSeriesPicker").innerHTML = data.series_keys.map(function (key) {
      var on = state.econSeries.indexOf(key) >= 0;
      return '<button type="button" class="an-chip' + (on ? " is-on" : "") +
        '" data-econ="' + esc(key) + '">' + esc(econLabel(key)) + "</button>";
    }).join("");

    $("anEconGrid").innerHTML = state.econSeries.map(function (key) {
      var series = ledgers.map(function (item) {
        return { label: item.name, color: agentColor(item.id), points: item[key] || [] };
      });
      var labels = (ledgers[0] && ledgers[0].days || []).map(function (day) { return "D" + day; });
      var bounded = key === "engel_coefficient" || key === "econ_security";
      return '<article class="an-card"><header class="an-card-head"><h4>' +
        esc(econLabel(key)) + "</h4></header>" +
        lineChart(series, bounded ? { yMin: 0, yMax: 1, xLabels: labels } : { xLabels: labels }) +
        "</article>";
    }).join("");

    var wealth = data.wealth.slice(0, 12).map(function (item) {
      return { label: item.name, value: item.balance, display: compact(item.balance) };
    });
    $("anEconWealth").innerHTML = barChart(wealth, { labelWidth: 84 });

    var macro = data.macro || {};
    var chips = [
      [__("an.macro_phase"), macro.phase || "—"],
      [__("an.macro_progress"), macro.phase_day_counter == null ? "—" : macro.phase_day_counter + " / " + macro.phase_duration],
      [__("an.macro_inflation"), macro.inflation_rate == null ? "—" : (macro.inflation_rate * 100).toFixed(2) + "%"],
      [__("an.macro_unemployment"), macro.unemployment_rate == null ? "—" : (macro.unemployment_rate * 100).toFixed(2) + "%"],
      [__("an.macro_cum_inflation"), macro.cumulative_inflation == null ? "—" : macro.cumulative_inflation.toFixed(4)],
    ];
    if (data.conservation) {
      chips.push([__("an.money_drift"), num(data.conservation.drift, 4)]);
      chips.push([__("an.money_total"), compact(data.conservation.system_total)]);
    }
    $("anEconMacro").innerHTML = chips.map(function (pair) {
      return '<div><dt>' + esc(pair[0]) + "</dt><dd>" + esc(pair[1]) + "</dd></div>";
    }).join("");
  }

  // Deterministic spring layout: agents seeded on a circle, ghost ties pushed
  // outward from their owner, then relaxed. No RNG, so the graph is stable
  // across reloads.
  function layoutGraph(nodes, links, width, height) {
    var positions = {}, agents = nodes.filter(function (n) { return n.kind === "agent"; });
    var cx = width / 2, cy = height / 2;
    nodes.forEach(function (node, index) {
      var ring = node.kind === "agent" ? Math.min(width, height) * 0.18 : Math.min(width, height) * 0.38;
      var total = node.kind === "agent" ? Math.max(agents.length, 1) : nodes.length;
      var theta = (index * 2 * Math.PI) / total;
      positions[node.id] = { x: cx + Math.cos(theta) * ring, y: cy + Math.sin(theta) * ring };
    });

    var index = {};
    nodes.forEach(function (node) { index[node.id] = node; });
    for (var step = 0; step < 220; step++) {
      var force = {};
      nodes.forEach(function (node) { force[node.id] = { x: 0, y: 0 }; });
      // Repulsion between every pair — node counts here are in the hundreds
      // at most, so O(n^2) is cheap enough.
      for (var i = 0; i < nodes.length; i++) {
        for (var j = i + 1; j < nodes.length; j++) {
          var a = positions[nodes[i].id], b = positions[nodes[j].id];
          var dx = a.x - b.x, dy = a.y - b.y;
          var dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
          var push = 900 / (dist * dist);
          force[nodes[i].id].x += (dx / dist) * push;
          force[nodes[i].id].y += (dy / dist) * push;
          force[nodes[j].id].x -= (dx / dist) * push;
          force[nodes[j].id].y -= (dy / dist) * push;
        }
      }
      links.forEach(function (link) {
        var a = positions[link.source], b = positions[link.target];
        if (!a || !b) return;
        var dx = b.x - a.x, dy = b.y - a.y;
        var dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
        // Closer ties sit nearer: rest length shrinks with closeness.
        var rest = 130 - 70 * (link.closeness || 0);
        var pull = (dist - rest) * 0.02;
        a.x += (dx / dist) * pull; a.y += (dy / dist) * pull;
        b.x -= (dx / dist) * pull; b.y -= (dy / dist) * pull;
      });
      nodes.forEach(function (node) {
        var p = positions[node.id];
        p.x += Math.max(-6, Math.min(6, force[node.id].x));
        p.y += Math.max(-6, Math.min(6, force[node.id].y));
        // Gentle pull to center keeps disconnected components on canvas.
        p.x += (cx - p.x) * 0.004;
        p.y += (cy - p.y) * 0.004;
        p.x = Math.max(24, Math.min(width - 24, p.x));
        p.y = Math.max(20, Math.min(height - 20, p.y));
      });
    }
    return positions;
  }

  function renderSocial() {
    var data = state.social;
    if (!data || !data.available) {
      $("anSocialGraph").innerHTML = note(__("an.empty_social"));
      $("anSocialTiers").innerHTML = "";
      $("anSocialRoles").innerHTML = "";
      return;
    }
    var W = 640, H = 420;
    var positions = layoutGraph(data.nodes, data.links, W, H);

    var edges = data.links.map(function (link) {
      var a = positions[link.source], b = positions[link.target];
      if (!a || !b) return "";
      var trust = link.trust || 0;
      return '<line x1="' + a.x.toFixed(1) + '" y1="' + a.y.toFixed(1) + '" x2="' + b.x.toFixed(1) +
        '" y2="' + b.y.toFixed(1) + '" stroke="' + (trust >= 0.6 ? "#0e7a58" : trust >= 0.35 ? "#8aa79a" : "#c9b7a0") +
        '" stroke-width="' + (0.6 + 3 * (link.closeness || 0)).toFixed(2) +
        '" stroke-opacity="0.6"><title>' +
        esc(__f("an.edge_tooltip", {
          role: link.role, closeness: num(link.closeness, 2), trust: num(trust, 2),
        })) +
        "</title></line>";
    }).join("");

    var dots = data.nodes.map(function (node) {
      var p = positions[node.id];
      if (!p) return "";
      var isAgent = node.kind === "agent";
      var r = isAgent ? 9 : 5;
      return '<circle cx="' + p.x.toFixed(1) + '" cy="' + p.y.toFixed(1) + '" r="' + r +
        '" fill="' + (isAgent ? agentColor(node.agent_id) : "#c8d6cb") +
        '" stroke="#ffffff" stroke-width="1.5"><title>' +
        esc(node.label + (node.role ? " · " + node.role : "")) + "</title></circle>" +
        (isAgent
          ? '<text x="' + p.x.toFixed(1) + '" y="' + (p.y - 13).toFixed(1) +
            '" font-size="9.5" fill="#243029" text-anchor="middle">' + esc(node.label) + "</text>"
          : '<text x="' + p.x.toFixed(1) + '" y="' + (p.y + 13).toFixed(1) +
            '" font-size="7.5" fill="#7e8b84" text-anchor="middle">' + esc(node.label) + "</text>");
    }).join("");

    $("anSocialGraph").innerHTML =
      '<svg class="an-graph" viewBox="0 0 ' + W + " " + H + '" role="img">' + edges + dots + "</svg>";

    var TIERS = ["inner", "close", "acquaintance", "weak", "unknown"];
    $("anSocialTiers").innerHTML = barChart(
      Object.keys(data.tier_counts).map(function (tier) {
        return { label: lookup(TIERS, "an.tier_", tier), value: data.tier_counts[tier], display: String(data.tier_counts[tier]) };
      }), { labelWidth: 70 });
    $("anSocialRoles").innerHTML = barChart(
      Object.keys(data.role_counts).map(function (role) {
        return { label: role, value: data.role_counts[role], display: String(data.role_counts[role]) };
      }), { labelWidth: 110 });
  }

  function renderBehavior() {
    var data = state.behavior;
    if (!data || !data.available) {
      $("anPlaces").innerHTML = note(__("an.empty_behavior"));
      $("anModes").innerHTML = "";
      $("anHeatmap").innerHTML = "";
      $("anHours").innerHTML = "";
      $("anHabits").innerHTML = "";
      return;
    }

    $("anPlaces").innerHTML = barChart(
      data.places.slice(0, 14).map(function (item) {
        return { label: item.name, value: item.visits, display: String(item.visits) };
      }), { labelWidth: 140 });

    $("anModes").innerHTML = barChart(
      data.modes.map(function (item) {
        return { label: item.mode, value: item.trips, display: String(item.trips) };
      }), { labelWidth: 64 });

    var cells = {};
    (data.heatmap.cells || []).forEach(function (cell) {
      cells[cell.period + "||" + cell.context] = cell.value;
    });
    $("anHeatmap").innerHTML = heatmap(
      data.heatmap.periods, data.heatmap.contexts,
      function (period, context) { return cells[period + "||" + context]; },
      periodLabel);

    var hours = data.schedule_hours || [];
    $("anHours").innerHTML = hours.some(function (h) { return h.count > 0; })
      ? lineChart([{ label: __("an.series_schedule"), color: "#0e7a58", points: hours.map(function (h) { return h.count; }) }],
          { yMin: 0, xLabels: hours.map(function (h) { return __f("an.hour_suffix", { hour: h.hour }); }) })
      : note(__("an.no_schedule"));

    $("anHabits").innerHTML = data.habits.length
      ? '<table class="an-table"><thead><tr>' +
        ["an.th_resident", "an.th_period", "an.th_context", "an.th_activity", "an.th_strength"]
          .map(function (key) { return "<th>" + esc(__(key)) + "</th>"; }).join("") +
        "</tr></thead><tbody>" +
        data.habits.map(function (habit) {
          return "<tr><td>" + esc(habit.name || habit.agent_id) + "</td><td>" +
            esc(periodLabel(habit.period)) + "</td><td>" + esc(habit.context) +
            '</td><td class="an-cell-wide">' + esc(habit.activity) + "</td><td>" +
            num(habit.strength, 3) + "</td></tr>";
        }).join("") + "</tbody></table>"
      : note(__("an.no_habits"));
  }

  function renderEvents() {
    var data = state.events;
    if (!data || !data.available) {
      $("anEventTimeline").innerHTML = note(__("an.empty_events"));
      $("anEventTypes").innerHTML = "";
      $("anEventImpacts").innerHTML = "";
      return;
    }

    var days = data.timeline.map(function (item) { return item.day; }).filter(function (d) { return d != null; });
    var minDay = days.length ? Math.min.apply(null, days) : 0;
    var maxDay = days.length ? Math.max.apply(null, days) : 1;
    // Lane labels are event type names ("technology", "economic", …), so the
    // left gutter has to clear the widest of them.
    var W = 640, H = 150, padR = 16, padT = 24, padB = 26;
    var padL = Math.max(40, Object.keys(data.type_counts).reduce(function (max, type) {
      return Math.max(max, type.length);
    }, 0) * 4.6 + 20);
    // Inset the first dot past the lane label — a Day-1 event drawn exactly on
    // padL would otherwise overlap the longest type name.
    var x0 = padL + 9;
    var xFor = function (day) {
      var t = maxDay > minDay ? (day - minDay) / (maxDay - minDay) : 0.5;
      return x0 + t * (W - x0 - padR);
    };

    var types = Object.keys(data.type_counts);
    var laneY = {};
    types.forEach(function (type, index) {
      laneY[type] = padT + (index * (H - padT - padB)) / Math.max(types.length - 1, 1);
    });

    var lanes = types.map(function (type) {
      return '<line x1="' + padL + '" y1="' + laneY[type].toFixed(1) + '" x2="' + (W - padR) +
        '" y2="' + laneY[type].toFixed(1) + '" stroke="#e8efe9" stroke-width="1"/>' +
        '<text x="' + (padL - 4) + '" y="' + (laneY[type] + 3).toFixed(1) +
        '" font-size="8" fill="#8a968f" text-anchor="end">' + esc(type) + "</text>";
    }).join("");

    var dots = data.timeline.map(function (frame) {
      return frame.events.map(function (event) {
        var y = laneY[event.type];
        if (y == null || frame.day == null) return "";
        return '<circle cx="' + xFor(frame.day).toFixed(1) + '" cy="' + y.toFixed(1) +
          '" r="' + (2.5 + 5 * (event.severity || 0)).toFixed(1) + '" fill="' +
          (EVENT_COLORS[event.type] || "#66746c") + '" fill-opacity="0.65"><title>' +
          esc("Day " + frame.day + " · " + event.name + __f("an.severity_paren", { value: num(event.severity, 2) })) +
          "</title></circle>";
      }).join("");
    }).join("");

    var axis = '<text x="' + padL + '" y="' + (H - 6) + '" font-size="8" fill="#8a968f">Day ' + minDay +
      '</text><text x="' + (W - padR) + '" y="' + (H - 6) +
      '" font-size="8" fill="#8a968f" text-anchor="end">Day ' + maxDay + "</text>";

    $("anEventTimeline").innerHTML =
      '<svg class="an-chart is-wide" viewBox="0 0 ' + W + " " + H + '" role="img">' +
      lanes + dots + axis + "</svg>" +
      '<div class="an-event-list">' + data.timeline.slice(-30).reverse().map(function (frame) {
        return frame.events.map(function (event) {
          return '<div class="an-event"><span class="an-event-day">Day ' + esc(frame.day) +
            '</span><span class="an-event-dot" style="background:' +
            (EVENT_COLORS[event.type] || "#66746c") + '"></span><span class="an-event-name">' +
            esc(event.name) + '</span><span class="an-event-meta">' + esc(event.scope) +
            esc(__f("an.severity_suffix", { value: num(event.severity, 2) })) + "</span></div>";
        }).join("");
      }).join("") + "</div>";

    $("anEventTypes").innerHTML = barChart(types.map(function (type) {
      return { label: type, value: data.type_counts[type], display: String(data.type_counts[type]), color: EVENT_COLORS[type] };
    }), { labelWidth: 80 });

    $("anEventImpacts").innerHTML = barChart(Object.keys(data.impact_counts).map(function (tag) {
      return { label: tag, value: data.impact_counts[tag], display: String(data.impact_counts[tag]) };
    }), { labelWidth: 120 });
  }

  /* ----------------------------------------------------------------- export */

  function showRunStatus() {
    var status = $("anStatus");
    if (!state.overview) return;
    status.textContent = __(state.overview.finished ? "an.runs_done" : "an.runs_partial");
    status.className = "an-status" + (state.overview.finished ? " is-ok" : " is-busy");
  }

  function download(filename, blob) {
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
  }

  // Snapshot of the rendered page with the interactive chrome removed. Every
  // figure is already inline SVG, so this alone is the whole report body.
  function reportBody() {
    var clone = document.querySelector("main.shell").cloneNode(true);
    Array.prototype.forEach.call(
      clone.querySelectorAll(".hero-status, .an-pickers, .help-tip, .an-export"),
      function (node) { node.remove(); });
    return clone.innerHTML;
  }

  // Inline the page's own stylesheets so the report renders identically with
  // no server behind it.
  async function reportCss() {
    var hrefs = Array.prototype.map.call(
      document.querySelectorAll('link[rel="stylesheet"]'),
      function (link) { return link.getAttribute("href"); });
    var sheets = await Promise.all(hrefs.map(function (href) {
      return fetch(href).then(function (res) { return res.ok ? res.text() : ""; })
        .catch(function () { return ""; });
    }));
    return sheets.join("\n");
  }

  async function runExport(kind) {
    var now = new Date();
    var base = "gaworld-analytics-" + exporter.fileStamp(now);
    var stamp = exporter.timestamp(now);
    if (kind === "json") {
      download(base + ".json", new Blob(
        [JSON.stringify(exporter.buildJson(state, labelTables(), stamp), null, 2)],
        { type: "application/json" }));
    } else if (kind === "md") {
      download(base + ".md", new Blob(
        [exporter.buildMarkdown(state, labelTables(), stamp)],
        { type: "text/markdown;charset=utf-8" }));
    } else if (kind === "csv") {
      var files = exporter.buildCsvFiles(state, labelTables());
      if (!files.length) throw new Error(__("an.nothing_to_export"));
      download(base + "-csv.zip", new Blob(
        [exporter.zipStore(files, now)], { type: "application/zip" }));
    } else {
      var css = await reportCss();
      download(base + ".html", new Blob(
        [exporter.buildHtmlReport(state, labelTables(), stamp, reportBody(), css)],
        { type: "text/html;charset=utf-8" }));
    }
  }

  function bindExport() {
    var menu = $("anExport");
    var panel = menu.querySelector(".an-export-menu");

    // The dropdown escapes the hero's overflow clipping by being fixed, which
    // means its position has to be pinned to the summary on every open.
    menu.addEventListener("toggle", function () {
      if (!menu.open) return;
      var rect = menu.querySelector("summary").getBoundingClientRect();
      panel.style.top = rect.bottom + 6 + "px";
      panel.style.left = Math.max(8, rect.right - panel.offsetWidth) + "px";
    });
    window.addEventListener("scroll", function () { menu.open = false; }, true);

    menu.addEventListener("click", async function (event) {
      var button = event.target.closest("[data-export]");
      if (!button) return;
      menu.open = false;
      var status = $("anStatus");
      try {
        await runExport(button.dataset.export);
        status.textContent = __("an.export_done");
        status.className = "an-status is-ok";
        // The chip belongs to the run, so hand it back after the notice.
        setTimeout(showRunStatus, 2500);
      } catch (error) {
        status.textContent = __f("an.export_failed", { error: error.message });
        status.className = "an-status is-error";
      }
    });
    // Clicking anywhere else closes the dropdown, matching native menu feel.
    document.addEventListener("click", function (event) {
      if (menu.open && !menu.contains(event.target)) menu.open = false;
    });
  }

  /* -------------------------------------------------------------- run list */

  function formatStamp(iso) {
    var date = new Date(iso);
    if (isNaN(date.getTime())) return iso || "";
    var pad = function (n) { return String(n).padStart(2, "0"); };
    return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate()) +
      " " + pad(date.getHours()) + ":" + pad(date.getMinutes());
  }

  function runLabel(run) {
    var parts = [run.kind === "live" ? __("an.current_run") : (run.label || run.id)];
    if (run.agent_count) parts.push(__f("an.people_count", { count: run.agent_count }));
    if (run.sim_days) parts.push(__f("an.days_count", { count: run.sim_days }));
    if (run.last_updated) parts.push(formatStamp(run.last_updated));
    return parts.join(" · ");
  }

  function renderRunOptions() {
    var select = $("anRunSelect");
    select.innerHTML = "";
    [["live", __("an.current_run")], ["archive", __("an.runs_history")], ["scenario", __("an.runs_scenario")]]
      .forEach(function (pair) {
        var runs = state.runs.filter(function (run) { return run.kind === pair[0]; });
        if (!runs.length) return;
        var group = document.createElement("optgroup");
        group.label = pair[1];
        runs.forEach(function (run) {
          var option = document.createElement("option");
          option.value = run.id;
          option.textContent = runLabel(run);
          group.appendChild(option);
        });
        select.appendChild(group);
      });
    select.value = state.runId;
  }

  // Recorded runs keep different artifact sets: an archived run holds only its
  // trace, and a scenario run may have skipped the economy. Say so up front
  // rather than leaving six "暂无数据" panels to be read as a broken page.
  function renderRunNote() {
    var note = $("anRunNote");
    var run = state.runInfo;
    var missing = run && run.sections
      ? SECTION_KEYS.filter(function (key) { return !run.sections[key]; })
      : [];
    if (!run || run.kind === "live" || !missing.length) {
      note.hidden = true;
      note.textContent = "";
      return;
    }
    note.hidden = false;
    note.textContent = __f("an.missing_sections", { sections: missing.map(sectionLabel).join("、") });
  }

  function selectRun(runId) {
    var match = state.runs.filter(function (run) { return run.id === runId; })[0];
    state.runInfo = match || null;
    state.runId = match ? match.id : "";
    // Metric / agent picks belong to the run they were made in.
    state.metrics = [];
    state.agents = [];
    var url = new URL(window.location.href);
    if (state.runId) url.searchParams.set("run", state.runId);
    else url.searchParams.delete("run");
    window.history.replaceState(null, "", url);
  }

  async function loadRuns() {
    var payload = await api("/api/analytics/runs");
    state.runs = Array.isArray(payload.runs) ? payload.runs : [];
    var wanted = state.runId || new URLSearchParams(window.location.search).get("run") || "";
    var match = state.runs.filter(function (run) { return run.id === wanted; })[0];
    // A run that vanished from disk (or an unknown ?run=) falls back to the
    // live one rather than failing every section with a 404.
    state.runInfo = match || state.runs[0] || null;
    state.runId = state.runInfo ? state.runInfo.id : "";
    renderRunOptions();
    renderRunNote();
  }

  /* ----------------------------------------------------------------- wiring */

  function pickDefaults() {
    var data = state.history;
    if (!data || !data.available) return;
    if (!state.agents.length) {
      state.agents = data.agents.slice(0, 4).map(function (agent) { return String(agent.id); });
    }
    if (!state.metrics.length) {
      // Rank by how much each metric moved so the first screenful shows the
      // signal, but still fill up to six charts when few metrics changed.
      state.metrics = data.metrics.slice().sort(function (a, b) {
        return Math.abs(meanDelta(b)) - Math.abs(meanDelta(a));
      }).slice(0, 6);
    }
  }

  function meanDelta(metric) {
    var deltas = (state.history.deltas || {})[metric] || {};
    var values = Object.keys(deltas).map(function (key) { return deltas[key].delta || 0; });
    if (!values.length) return 0;
    return values.reduce(function (a, b) { return a + b; }, 0) / values.length;
  }

  function toggle(list, value) {
    var index = list.indexOf(value);
    if (index >= 0) list.splice(index, 1);
    else list.push(value);
    return list;
  }

  function bindPickers() {
    $("anMetricPicker").addEventListener("click", function (event) {
      var button = event.target.closest("[data-metric]");
      if (!button) return;
      toggle(state.metrics, button.dataset.metric);
      renderStateControls();
      renderStateCharts();
    });
    $("anAgentPicker").addEventListener("click", function (event) {
      var button = event.target.closest("[data-agent]");
      if (!button) return;
      toggle(state.agents, button.dataset.agent);
      renderStateControls();
      renderStateCharts();
      renderEconomy();
    });
    $("anEconSeriesPicker").addEventListener("click", function (event) {
      var button = event.target.closest("[data-econ]");
      if (!button) return;
      toggle(state.econSeries, button.dataset.econ);
      renderEconomy();
    });
    $("anRefreshBtn").addEventListener("click", function () { load(); });
    $("anRunSelect").addEventListener("change", function (event) {
      selectRun(event.target.value);
      load();
    });
  }

  async function load() {
    var status = $("anStatus");
    status.textContent = __("an.loading");
    status.className = "an-status is-busy";
    try {
      await loadRuns();
      var results = await Promise.all([
        section("overview"),
        section("state-history"),
        section("economy"),
        section("social"),
        section("behavior"),
        section("events"),
      ]);
      state.overview = results[0];
      state.history = results[1];
      state.economy = results[2];
      state.social = results[3];
      state.behavior = results[4];
      state.events = results[5];
      // Drop selections that no longer exist in the new payload.
      state.metrics = state.metrics.filter(function (m) { return state.history.metrics.indexOf(m) >= 0; });
      var ids = state.history.agents.map(function (a) { return String(a.id); });
      state.agents = state.agents.filter(function (a) { return ids.indexOf(a) >= 0; });
      pickDefaults();

      renderOverview();
      renderStateControls();
      renderStateCharts();
      renderEconomy();
      renderSocial();
      renderBehavior();
      renderEvents();

      showRunStatus();
    } catch (error) {
      status.textContent = __f("an.load_failed", { error: error.message });
      status.className = "an-status is-error";
    }
  }

  /* Every label, KPI, table header and empty state here is drawn from JS, and
     the metric dictionaries resolve per call — so a language switch just needs
     the renderers run again over the payloads already in `state`. No refetch:
     the data is language-independent. */
  document.addEventListener("locale-changed", function () {
    if (!state.overview) return;
    renderRunOptions();
    renderOverview();
    renderStateControls();
    renderStateCharts();
    renderEconomy();
    renderSocial();
    renderBehavior();
    renderEvents();
    showRunStatus();
    renderRunNote();
  });

  bindPickers();
  bindExport();
  load();
})();
