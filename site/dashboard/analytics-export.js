// Export builders for the analytics view.
//
// Everything here is pure: it takes the payloads already loaded by
// analytics.js plus the current picker selection, and returns strings (or
// bytes, for the zip) ready to be handed to a Blob. Keeping it separate from
// the renderers means the formats can be tested headlessly in node — see
// analytics-export.test.js.
(function (root, factory) {
  "use strict";

  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.GAWorldAnalyticsExport = api;
  }
}(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  function num(value, digits) {
    if (value == null || isNaN(value)) return "";
    return Number(value).toFixed(digits == null ? 4 : digits);
  }

  function label(map, key) {
    return (map && map[key]) || key;
  }

  /* The exported documents follow the interface language: the metric names in
     them already do (they come from `labels`), and leaving the surrounding
     headings in one language would produce a mixed-language report — worse
     than either consistent choice. The translator arrives through `labels`
     rather than off a global, so this file stays pure and testable in node. */
  function t(labels, key) {
    return labels && typeof labels.t === "function" ? labels.t(key) : key;
  }

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  /* --------------------------------------------------------------- scope */

  // What the user currently has selected, resolved against the payloads. The
  // economy fallback mirrors renderEconomy(): when no selected agent has a
  // ledger we show (and therefore export) every ledger rather than nothing.
  function selection(state) {
    var history = state.history && state.history.available ? state.history : null;
    var economy = state.economy && state.economy.available ? state.economy : null;
    var metrics = history
      ? (state.metrics || []).filter(function (key) { return history.metrics.indexOf(key) >= 0; })
      : [];
    var agents = history
      ? history.agents.filter(function (agent) {
          return (state.agents || []).indexOf(String(agent.id)) >= 0;
        })
      : [];
    var ledgers = [];
    if (economy) {
      ledgers = economy.ledger.filter(function (item) {
        return !(state.agents || []).length || state.agents.indexOf(String(item.id)) >= 0;
      });
      if (!ledgers.length) ledgers = economy.ledger;
    }
    return {
      metrics: metrics,
      agents: agents,
      econSeries: economy
        ? (state.econSeries || []).filter(function (key) { return economy.series_keys.indexOf(key) >= 0; })
        : [],
      ledgers: ledgers,
    };
  }

  // Which run the export came from. The picker sits in the page chrome the
  // report strips out, so the name has to be carried into the file itself.
  function runTitle(state, labels) {
    var run = state.runInfo;
    if (!run || run.kind === "live") return t(labels, "an.current_run");
    return run.label || run.id;
  }

  function scopeSummary(state, labels) {
    var pick = selection(state);
    return {
      run: runTitle(state, labels),
      metrics: pick.metrics.map(function (key) { return label(labels.metric, key); }),
      agents: pick.agents.map(function (agent) { return agent.name; }),
      econ_series: pick.econSeries.map(function (key) { return label(labels.econ, key); }),
    };
  }

  /* ---------------------------------------------------------------- json */

  // Raw payloads, trimmed to the current selection so the file matches what is
  // on screen. Sections without a picker (social / behavior / events) are kept
  // whole.
  function buildJson(state, labels, stamp) {
    var pick = selection(state);
    var history = null;
    if (state.history && state.history.available) {
      history = {
        available: true,
        steps: state.history.steps,
        sampled: state.history.sampled,
        metrics: pick.metrics,
        agents: pick.agents,
        series: {},
        deltas: {},
      };
      pick.metrics.forEach(function (metric) {
        history.series[metric] = {};
        history.deltas[metric] = {};
        pick.agents.forEach(function (agent) {
          var id = String(agent.id);
          history.series[metric][id] = (state.history.series[metric] || {})[id] || [];
          history.deltas[metric][id] = (state.history.deltas[metric] || {})[id] || {};
        });
      });
    }

    var economy = null;
    if (state.economy && state.economy.available) {
      economy = {
        available: true,
        series_keys: pick.econSeries,
        ledger: pick.ledgers.map(function (item) {
          var row = { id: item.id, name: item.name, days: item.days };
          pick.econSeries.forEach(function (key) { row[key] = item[key] || []; });
          return row;
        }),
        wealth: state.economy.wealth,
        conservation: state.economy.conservation,
        macro: state.economy.macro,
        macro_timeline: state.economy.macro_timeline,
        sectors: state.economy.sectors,
      };
    }

    return {
      exported_at: stamp,
      run: state.runInfo || null,
      scope: scopeSummary(state, labels),
      overview: state.overview,
      state_history: history,
      economy: economy,
      social: state.social,
      behavior: state.behavior,
      events: state.events,
    };
  }

  /* ----------------------------------------------------------------- csv */

  function csvCell(value) {
    var text = value == null ? "" : String(value);
    return /[",\n\r]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  }

  function csv(header, rows) {
    return [header].concat(rows).map(function (row) {
      return row.map(csvCell).join(",");
    }).join("\r\n") + "\r\n";
  }

  // One file per figure on the page. Long format (one observation per row)
  // wherever a series is involved, so the output loads straight into
  // pandas/R without reshaping.
  function buildCsvFiles(state, labels) {
    var pick = selection(state);
    var files = [];
    var rows;

    if (state.overview) {
      var data = state.overview;
      var meta = data.sim_meta || {};
      rows = [
        [t(labels, "an.kpi_agents"), data.agent_count],
        [t(labels, "ax.metric_count"), data.metric_count],
        [t(labels, "an.kpi_steps"), data.step_count],
        [t(labels, "an.kpi_frames"), data.frame_count],
        [t(labels, "an.kpi_events"), data.event_total],
        [t(labels, "an.kpi_diary"), data.diary_count],
        [t(labels, "an.kpi_relations"), data.relationship_total],
        [t(labels, "ax.day_first"), data.day_span ? data.day_span.first : ""],
        [t(labels, "ax.day_last"), data.day_span ? data.day_span.last : ""],
        [t(labels, "ax.finished_flag"), data.finished ? "true" : "false"],
        [t(labels, "an.meta_sim_days"), meta.sim_days],
        [t(labels, "an.meta_seconds"), meta.seconds_per_day],
        [t(labels, "an.meta_time_step"), meta.time_step_minutes],
        [t(labels, "an.meta_map"), meta.map_path],
        [t(labels, "an.meta_generated"), data.generated_at],
        [t(labels, "an.meta_updated"), data.last_updated],
      ];
      (data.top_movers || []).forEach(function (item) {
        rows.push([t(labels, "ax.top_mover_prefix") + label(labels.metric, item.metric), item.mean_delta]);
      });
      files.push({ name: "overview.csv", text: csv(["item", "value"], rows) });
    }

    if (pick.metrics.length && pick.agents.length) {
      rows = [];
      var deltaRows = [];
      pick.metrics.forEach(function (metric) {
        pick.agents.forEach(function (agent) {
          var id = String(agent.id);
          ((state.history.series[metric] || {})[id] || []).forEach(function (value, index) {
            rows.push([metric, label(labels.metric, metric), agent.id, agent.name, index, num(value, 6)]);
          });
          var stats = (state.history.deltas[metric] || {})[id] || {};
          deltaRows.push([
            metric, label(labels.metric, metric), agent.id, agent.name,
            num(stats.first, 6), num(stats.last, 6), num(stats.delta, 6),
            num(stats.min, 6), num(stats.max, 6), num(stats.mean, 6),
          ]);
        });
      });
      files.push({
        name: "state_history.csv",
        text: csv(["metric", "metric_label", "agent_id", "agent_name", "step_index", "value"], rows),
      });
      files.push({
        name: "state_deltas.csv",
        text: csv(
          ["metric", "metric_label", "agent_id", "agent_name", "first", "last", "delta", "min", "max", "mean"],
          deltaRows),
      });
    }

    if (pick.ledgers.length && pick.econSeries.length) {
      rows = [];
      pick.ledgers.forEach(function (item) {
        (item.days || []).forEach(function (day, index) {
          rows.push([item.id, item.name, day].concat(pick.econSeries.map(function (key) {
            return num((item[key] || [])[index], 4);
          })));
        });
      });
      files.push({
        name: "economy_ledger.csv",
        text: csv(["agent_id", "agent_name", "day"].concat(pick.econSeries), rows),
      });
    }

    if (state.economy && (state.economy.wealth || []).length) {
      var wealthKeys = Object.keys(state.economy.wealth[0]).filter(function (key) {
        return key !== "id" && key !== "name";
      });
      files.push({
        name: "economy_wealth.csv",
        text: csv(["agent_id", "agent_name"].concat(wealthKeys), state.economy.wealth.map(function (item) {
          return [item.id, item.name].concat(wealthKeys.map(function (key) {
            return typeof item[key] === "number" ? num(item[key], 4) : item[key];
          }));
        })),
      });
    }

    if (state.social && state.social.available) {
      var byId = {};
      state.social.nodes.forEach(function (node) { byId[node.id] = node.label; });
      files.push({
        name: "social_links.csv",
        text: csv(
          ["source", "source_label", "target", "target_label", "role", "closeness", "trust", "obligation", "last_contact_day"],
          state.social.links.map(function (link) {
            return [
              link.source, byId[link.source] || "", link.target, byId[link.target] || "",
              link.role, num(link.closeness, 4), num(link.trust, 4), num(link.obligation, 4),
              link.last_contact_day,
            ];
          })),
      });
    }

    if (state.behavior && state.behavior.available) {
      var behavior = state.behavior;
      files.push({
        name: "behavior_places.csv",
        text: csv(["place", "visits"], behavior.places.map(function (item) {
          return [item.name, item.visits];
        })),
      });
      files.push({
        name: "behavior_modes.csv",
        text: csv(["mode", "trips"], behavior.modes.map(function (item) {
          return [item.mode, item.trips];
        })),
      });
      files.push({
        name: "behavior_habits.csv",
        text: csv(
          ["agent_id", "agent_name", "period", "period_label", "context", "activity", "strength", "action", "last_updated_day"],
          behavior.habits.map(function (habit) {
            return [
              habit.agent_id, habit.name, habit.period, label(labels.period, habit.period),
              habit.context, habit.activity, num(habit.strength, 4), habit.action, habit.last_updated_day,
            ];
          })),
      });
      files.push({
        name: "behavior_heatmap.csv",
        text: csv(["period", "period_label", "context", "strength"],
          (behavior.heatmap.cells || []).map(function (cell) {
            return [cell.period, label(labels.period, cell.period), cell.context, num(cell.value, 4)];
          })),
      });
      files.push({
        name: "schedule_hours.csv",
        text: csv(["hour", "count"], (behavior.schedule_hours || []).map(function (item) {
          return [item.hour, item.count];
        })),
      });
    }

    if (state.events && state.events.available) {
      rows = [];
      state.events.timeline.forEach(function (frame) {
        frame.events.forEach(function (event) {
          rows.push([
            frame.day, frame.date, frame.weekday, frame.day_type, event.type, event.topic,
            event.name, event.scope, num(event.severity, 3),
            (event.impact_tags || []).join("|"), event.description,
          ]);
        });
      });
      files.push({
        name: "events.csv",
        text: csv(
          ["day", "date", "weekday", "day_type", "type", "topic", "name", "scope", "severity", "impact_tags", "description"],
          rows),
      });
    }

    return files;
  }

  /* ------------------------------------------------------------ markdown */

  function mdTable(header, rows, labels) {
    if (!rows.length) return t(labels, "ax.no_data") + "\n";
    return "| " + header.join(" | ") + " |\n"
      + "| " + header.map(function () { return "---"; }).join(" | ") + " |\n"
      + rows.map(function (row) {
        return "| " + row.map(function (cell) {
          return String(cell == null ? "" : cell).replace(/\|/g, "\\|");
        }).join(" | ") + " |";
      }).join("\n") + "\n";
  }

  function buildMarkdown(state, labels, stamp) {
    var pick = selection(state);
    var none = t(labels, "ax.none");
    var out = [
      "# " + t(labels, "ax.report_title"), "",
      t(labels, "ax.run") + "：" + runTitle(state, labels), "",
      t(labels, "ax.exported_at") + "：" + stamp, "",
    ];

    out.push("**" + t(labels, "ax.scope") + "**：" + [
      t(labels, "ax.scope_metrics") + " " + (pick.metrics.length ? pick.metrics.map(function (k) { return label(labels.metric, k); }).join("、") : none),
      t(labels, "ax.scope_agents") + " " + (pick.agents.length ? pick.agents.map(function (a) { return a.name; }).join("、") : none),
      t(labels, "ax.scope_econ") + " " + (pick.econSeries.length ? pick.econSeries.map(function (k) { return label(labels.econ, k); }).join("、") : none),
    ].join("；"), "");

    var data = state.overview;
    if (data) {
      var meta = data.sim_meta || {};
      out.push("## " + t(labels, "ax.h_overview"), "");
      out.push(mdTable([t(labels, "ax.col_item"), t(labels, "ax.col_value")], [
        [t(labels, "an.kpi_agents"), data.agent_count],
        [t(labels, "ax.metric_count"), data.metric_count],
        [t(labels, "an.kpi_steps"), data.step_count],
        [t(labels, "an.kpi_frames"), data.frame_count],
        [t(labels, "an.kpi_events"), data.event_total],
        [t(labels, "an.kpi_diary"), data.diary_count],
        [t(labels, "an.kpi_relations"), data.relationship_total],
        [t(labels, "ax.day_range"), data.day_span ? "Day " + data.day_span.first + " – " + data.day_span.last : "—"],
        [t(labels, "ax.run_state"), t(labels, data.finished ? "an.runs_done" : "an.runs_partial")],
        [t(labels, "an.meta_sim_days"), meta.sim_days == null ? "—" : meta.sim_days],
        [t(labels, "an.meta_map"), meta.map_path || "—"],
        [t(labels, "an.meta_updated"), data.last_updated || "—"],
      ], labels));
      out.push("", "### " + t(labels, "ax.h_top_movers"), "");
      out.push(mdTable([t(labels, "ax.col_metric"), t(labels, "ax.col_mean_delta")], (data.top_movers || []).map(function (item) {
        return [label(labels.metric, item.metric), (item.mean_delta > 0 ? "+" : "") + num(item.mean_delta, 3)];
      }), labels));
    }

    if (pick.metrics.length && pick.agents.length) {
      out.push("", "## " + t(labels, "ax.h_state_delta"), "");
      var rows = [];
      pick.metrics.forEach(function (metric) {
        pick.agents.forEach(function (agent) {
          var stats = (state.history.deltas[metric] || {})[String(agent.id)] || {};
          rows.push([
            label(labels.metric, metric), agent.name,
            num(stats.first, 3), num(stats.last, 3),
            (stats.delta > 0 ? "+" : "") + num(stats.delta, 3),
            num(stats.mean, 3),
          ]);
        });
      });
      out.push(mdTable([
        t(labels, "ax.col_metric"), t(labels, "ax.col_resident"),
        t(labels, "ax.col_first"), t(labels, "ax.col_last"), "Δ", t(labels, "ax.col_mean"),
      ], rows, labels));
    }

    if (state.economy && state.economy.available) {
      var macro = state.economy.macro || {};
      out.push("", "## " + t(labels, "ax.h_economy"), "", "### " + t(labels, "ax.h_macro"), "");
      out.push(mdTable([t(labels, "ax.col_item"), t(labels, "ax.col_value")], [
        [t(labels, "an.macro_phase"), macro.phase || "—"],
        [t(labels, "an.macro_inflation"), macro.inflation_rate == null ? "—" : (macro.inflation_rate * 100).toFixed(2) + "%"],
        [t(labels, "an.macro_unemployment"), macro.unemployment_rate == null ? "—" : (macro.unemployment_rate * 100).toFixed(2) + "%"],
        [t(labels, "an.macro_cum_inflation"), num(macro.cumulative_inflation, 4) || "—"],
        [t(labels, "an.money_drift"), state.economy.conservation ? num(state.economy.conservation.drift, 6) : "—"],
      ], labels));
      out.push("", "### " + t(labels, "ax.h_wealth"), "");
      out.push(mdTable([t(labels, "ax.col_resident"), t(labels, "ax.col_assets")], state.economy.wealth.slice(0, 10).map(function (item) {
        return [item.name, num(item.balance, 2)];
      }), labels));
    }

    if (state.social && state.social.available) {
      out.push("", "## " + t(labels, "ax.h_social"), "");
      out.push(mdTable([t(labels, "ax.col_tier"), t(labels, "ax.col_count")], Object.keys(state.social.tier_counts).map(function (tier) {
        return [tier, state.social.tier_counts[tier]];
      }), labels));
      out.push("", "### " + t(labels, "ax.h_roles"), "");
      out.push(mdTable([t(labels, "ax.col_role"), t(labels, "ax.col_count")], Object.keys(state.social.role_counts).map(function (role) {
        return [role, state.social.role_counts[role]];
      }), labels));
    }

    if (state.behavior && state.behavior.available) {
      out.push("", "## " + t(labels, "ax.h_behavior"), "", "### " + t(labels, "ax.h_places"), "");
      out.push(mdTable([t(labels, "ax.col_place"), t(labels, "ax.col_visits")], state.behavior.places.slice(0, 10).map(function (item) {
        return [item.name, item.visits];
      }), labels));
      out.push("", "### " + t(labels, "ax.h_modes"), "");
      out.push(mdTable([t(labels, "ax.col_mode"), t(labels, "ax.col_trips")], state.behavior.modes.map(function (item) {
        return [item.mode, item.trips];
      }), labels));
      out.push("", "### " + t(labels, "ax.h_habits"), "");
      out.push(mdTable([
        t(labels, "ax.col_resident"), t(labels, "ax.col_period"), t(labels, "ax.col_context"),
        t(labels, "ax.col_activity"), t(labels, "ax.col_strength"),
      ],
        state.behavior.habits.slice(0, 10).map(function (habit) {
          return [
            habit.name || habit.agent_id, label(labels.period, habit.period),
            habit.context, habit.activity, num(habit.strength, 3),
          ];
        }), labels));
    }

    if (state.events && state.events.available) {
      out.push("", "## " + t(labels, "ax.h_events"), "");
      out.push(mdTable([t(labels, "ax.col_event_type"), t(labels, "ax.col_times")], Object.keys(state.events.type_counts).map(function (type) {
        return [type, state.events.type_counts[type]];
      }), labels));
      out.push("", "### " + t(labels, "ax.h_impacts"), "");
      out.push(mdTable([t(labels, "ax.col_tag"), t(labels, "ax.col_times")], Object.keys(state.events.impact_counts).map(function (tag) {
        return [tag, state.events.impact_counts[tag]];
      }), labels));
      var recent = [];
      state.events.timeline.slice(-30).reverse().forEach(function (frame) {
        frame.events.forEach(function (event) {
          recent.push(["Day " + frame.day, event.type, event.name, event.scope, num(event.severity, 2)]);
        });
      });
      out.push("", "### " + t(labels, "ax.h_recent"), "");
      out.push(mdTable([
        t(labels, "ax.col_day"), t(labels, "ax.col_type"), t(labels, "ax.col_event"),
        t(labels, "ax.col_scope"), t(labels, "ax.col_strength"),
      ], recent, labels));
    }

    return out.join("\n").replace(/\n{3,}/g, "\n\n") + "\n";
  }

  /* ---------------------------------------------------------------- html */

  function escapeHtml(text) {
    return String(text == null ? "" : text).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  // The page already renders every figure as inline SVG, so a snapshot of the
  // live markup plus the inlined stylesheets is a complete offline report —
  // no chart library, no network, printable straight to PDF.
  function buildHtmlReport(state, labels, stamp, bodyHtml, css) {
    var scope = scopeSummary(state, labels);
    var none = t(labels, "ax.none");
    var lines = [
      [t(labels, "ax.run"), scope.run],
      [t(labels, "ax.exported_at"), stamp],
      [t(labels, "ax.state_metrics"), scope.metrics.join("、") || none],
      [t(labels, "ax.col_resident"), scope.agents.join("、") || none],
      [t(labels, "ax.econ_metrics"), scope.econ_series.join("、") || none],
    ];
    return "<!doctype html>\n<html lang=\"" + (labels && labels.lang ? labels.lang : "zh-CN") + "\">\n<head>\n"
      + '<meta charset="utf-8" />\n'
      + '<meta name="viewport" content="width=device-width, initial-scale=1" />\n'
      + "<title>" + escapeHtml(t(labels, "ax.report_title")) + " · " + escapeHtml(stamp) + "</title>\n"
      + "<style>\n" + css + "\n"
      + ".an-report-scope{display:grid;gap:6px;padding:14px 16px;margin-bottom:4px;"
      + "border:1px solid var(--line);border-radius:var(--radius-sm);background:var(--card);font-size:12px}\n"
      + ".an-report-scope b{color:var(--muted);font-weight:600;margin-right:8px}\n"
      + ".an-table-wrap,.an-event-list{max-height:none;overflow:visible}\n"
      // The hero's decorative overlay is the one asset the stylesheets pull
      // from the server; dropping it keeps the file from touching the network.
      + ".hero::before{display:none}\n"
      + "@media print{body{background:#fff}.panel,.an-card{break-inside:avoid}}\n"
      + "</style>\n</head>\n<body>\n<main class=\"shell\">\n"
      + '<div class="an-report-scope">'
      + lines.map(function (pair) {
        return "<div><b>" + escapeHtml(pair[0]) + "</b>" + escapeHtml(pair[1]) + "</div>";
      }).join("")
      + "</div>\n" + bodyHtml + "\n</main>\n</body>\n</html>\n";
  }

  /* ----------------------------------------------------------------- zip */

  var CRC_TABLE = (function () {
    var table = new Int32Array(256), i, k, c;
    for (i = 0; i < 256; i++) {
      c = i;
      for (k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      table[i] = c;
    }
    return table;
  }());

  function crc32(bytes) {
    var c = -1;
    for (var i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
    return (c ^ -1) >>> 0;
  }

  // Store-only (method 0) zip writer. The payload is a handful of small CSVs,
  // so skipping deflate costs nothing and keeps this dependency-free.
  function zipStore(files, date) {
    var encoder = new TextEncoder();
    var when = date || new Date();
    var dosTime = (when.getHours() << 11) | (when.getMinutes() << 5) | (when.getSeconds() >> 1);
    var dosDate = ((when.getFullYear() - 1980) << 9) | ((when.getMonth() + 1) << 5) | when.getDate();

    var entries = files.map(function (file) {
      var name = encoder.encode(file.name);
      // A BOM keeps Excel from mangling the Chinese column values.
      var data = encoder.encode("﻿" + file.text);
      return { name: name, data: data, crc: crc32(data) };
    });

    var localSize = entries.reduce(function (sum, e) { return sum + 30 + e.name.length + e.data.length; }, 0);
    var centralSize = entries.reduce(function (sum, e) { return sum + 46 + e.name.length; }, 0);
    var out = new Uint8Array(localSize + centralSize + 22);
    var view = new DataView(out.buffer);
    var offset = 0;

    entries.forEach(function (entry) {
      entry.offset = offset;
      view.setUint32(offset, 0x04034b50, true);
      view.setUint16(offset + 4, 20, true);
      view.setUint16(offset + 6, 0x0800, true); // UTF-8 filenames
      view.setUint16(offset + 8, 0, true);      // stored
      view.setUint16(offset + 10, dosTime, true);
      view.setUint16(offset + 12, dosDate, true);
      view.setUint32(offset + 14, entry.crc, true);
      view.setUint32(offset + 18, entry.data.length, true);
      view.setUint32(offset + 22, entry.data.length, true);
      view.setUint16(offset + 26, entry.name.length, true);
      view.setUint16(offset + 28, 0, true);
      out.set(entry.name, offset + 30);
      out.set(entry.data, offset + 30 + entry.name.length);
      offset += 30 + entry.name.length + entry.data.length;
    });

    var centralStart = offset;
    entries.forEach(function (entry) {
      view.setUint32(offset, 0x02014b50, true);
      view.setUint16(offset + 4, 20, true);
      view.setUint16(offset + 6, 20, true);
      view.setUint16(offset + 8, 0x0800, true);
      view.setUint16(offset + 10, 0, true);
      view.setUint16(offset + 12, dosTime, true);
      view.setUint16(offset + 14, dosDate, true);
      view.setUint32(offset + 16, entry.crc, true);
      view.setUint32(offset + 20, entry.data.length, true);
      view.setUint32(offset + 24, entry.data.length, true);
      view.setUint16(offset + 28, entry.name.length, true);
      view.setUint16(offset + 30, 0, true);
      view.setUint16(offset + 32, 0, true);
      view.setUint16(offset + 34, 0, true);
      view.setUint16(offset + 36, 0, true);
      view.setUint32(offset + 38, 0, true);
      view.setUint32(offset + 42, entry.offset, true);
      out.set(entry.name, offset + 46);
      offset += 46 + entry.name.length;
    });

    view.setUint32(offset, 0x06054b50, true);
    view.setUint16(offset + 8, entries.length, true);
    view.setUint16(offset + 10, entries.length, true);
    view.setUint32(offset + 12, offset - centralStart, true);
    view.setUint32(offset + 16, centralStart, true);
    return out;
  }

  function timestamp(date) {
    var when = date || new Date();
    return when.getFullYear() + "-" + pad(when.getMonth() + 1) + "-" + pad(when.getDate())
      + " " + pad(when.getHours()) + ":" + pad(when.getMinutes()) + ":" + pad(when.getSeconds());
  }

  function fileStamp(date) {
    var when = date || new Date();
    return String(when.getFullYear()) + pad(when.getMonth() + 1) + pad(when.getDate())
      + "-" + pad(when.getHours()) + pad(when.getMinutes());
  }

  return {
    selection: selection,
    scopeSummary: scopeSummary,
    buildJson: buildJson,
    buildCsvFiles: buildCsvFiles,
    buildMarkdown: buildMarkdown,
    buildHtmlReport: buildHtmlReport,
    zipStore: zipStore,
    timestamp: timestamp,
    fileStamp: fileStamp,
  };
}));
