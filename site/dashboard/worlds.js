/* Parallel Worlds panel.
 *
 * Two halves that talk to each other through one piece of state: the left
 * column *designs* an experiment (worlds, and the events inside them) and the
 * right column *reads* one back (branch diagram, trajectories, divergence,
 * per-agent movers). Editing an event on the left and pressing run is the
 * whole interaction the panel exists for — everything on the right is a view
 * onto `state.report`.
 *
 * Charts are hand-written SVG. Same reason population.js and external.js give:
 * this directory has no build step, and a CDN chart library would cost the
 * dashboard its offline usability.
 */
(function () {
  "use strict";

  /* Eight worlds is the server-side cap, so eight colours is the whole set.
     Picked to stay distinguishable in the panel's green-on-paper palette. */
  var COLORS = [
    "#0e7a58", "#c04545", "#3a6ea5", "#d6a81e",
    "#7a4fa3", "#0f8f8f", "#b3622b", "#5c6b73",
  ];

  var state = {
    overview: null,
    spec: null,
    report: null,
    job: null,
    metric: "",
    relative: false,
    hidden: {},
    moverWorld: "",
    experiment: "",
    poll: null,
    error: "",
  };

  var seq = 0;

  // ---------------------------------------------------------------- utils

  function el(id) { return document.getElementById(id); }

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function fmt(value, digits) {
    var number = Number(value);
    if (!isFinite(number)) return "—";
    return number.toFixed(digits == null ? 4 : digits);
  }

  function signed(value, digits) {
    var number = Number(value) || 0;
    return (number > 0 ? "+" : "") + fmt(number, digits);
  }

  async function api(path, options) {
    var settings = Object.assign({}, options || {});
    settings.headers = Object.assign(
      { "Content-Type": "application/json" }, settings.headers || {}
    );
    var response = await fetch(path, settings);
    var payload = {};
    try { payload = await response.json(); } catch (_) { payload = {}; }
    if (!response.ok) throw new Error(payload.error || (__("pw.request_failed") + response.status));
    return payload;
  }

  function colorFor(index) { return COLORS[index % COLORS.length]; }

  function worldColors() {
    var map = {};
    var list = (state.report && state.report.worlds) || [];
    list.forEach(function (world, index) { map[world.id] = colorFor(index); });
    return map;
  }

  function visibleWorlds() {
    var list = (state.report && state.report.worlds) || [];
    return list.filter(function (world) { return !state.hidden[world.id]; });
  }

  // ------------------------------------------------------------ spec model

  function newWorld(label, events) {
    seq += 1;
    return { key: "w" + seq, label: label, events: (events || []).map(cloneEvent) };
  }

  function cloneEvent(event) {
    return {
      day: event.day == null ? 2 : event.day,
      time: event.time || "10:00",
      name: event.name || "",
      description: event.description || "",
    };
  }

  function defaultSpec(defaults) {
    var spec = {
      name: __("pw.experiment_name"),
      sim_days: defaults.sim_days || 3,
      seed: defaults.seed || 42,
      agent_ids: (defaults.agent_ids || []).join(","),
      llm_provider: defaults.llm_provider || "",
      fast: false,
      max_parallel: defaults.max_parallel || 2,
      worlds: [newWorld(__("pw.world_baseline"), []), newWorld(__("pw.world_event"), [{
        day: 2, time: "09:00", name: "", description: "",
      }])],
    };
    spec.baseline = spec.worlds[0].key;
    return spec;
  }

  function applyPreset(preset) {
    state.spec.name = preset.name;
    state.spec.worlds = preset.worlds.map(function (world) {
      return newWorld(world.label, world.events);
    });
    state.spec.baseline = state.spec.worlds[0].key;
    renderDesign();
  }

  function specPayload() {
    var agents = String(state.spec.agent_ids || "")
      .split(/[,，\s]+/).filter(Boolean).map(Number).filter(function (n) { return n > 0; });
    return {
      name: state.spec.name,
      sim_days: Number(state.spec.sim_days) || null,
      seed: Number(state.spec.seed) || 42,
      agent_ids: agents,
      llm_provider: state.spec.llm_provider || null,
      fast: !!state.spec.fast,
      max_parallel: Number(state.spec.max_parallel) || 2,
      baseline_id: state.spec.baseline,
      worlds: state.spec.worlds.map(function (world) {
        return {
          id: world.key,
          label: world.label,
          events: world.events
            .filter(function (event) { return String(event.name || "").trim(); })
            .map(function (event) {
              return {
                day: Number(event.day) || 1,
                time: event.time || "10:00",
                name: event.name,
                description: event.description,
              };
            }),
        };
      }),
    };
  }

  // -------------------------------------------------------- design column

  function renderShared() {
    var providers = (state.overview && state.overview.providers) || [];
    var spec = state.spec;
    el("pwShared").innerHTML = [
      field("pw-wide", __("pw.field_name"), "<input type=\"text\" data-spec=\"name\" value=\"" + esc(spec.name) + "\" />"),
      field("", __("pw.field_sim_days"), "<input type=\"number\" min=\"1\" data-spec=\"sim_days\" value=\"" + esc(spec.sim_days) + "\" />"),
      field("", __("pw.field_seed"), "<input type=\"number\" data-spec=\"seed\" value=\"" + esc(spec.seed) + "\" />"),
      field("", __("pw.field_parallel"), "<input type=\"number\" min=\"1\" max=\"4\" data-spec=\"max_parallel\" value=\"" + esc(spec.max_parallel) + "\" />"),
      field("pw-wide", __("pw.field_agents"),
        "<input type=\"text\" data-spec=\"agent_ids\" placeholder=\"1,2,3\" value=\"" + esc(spec.agent_ids) + "\" />"),
      field("pw-wide", __("pw.field_provider"),
        "<select data-spec=\"llm_provider\"><option value=\"\">" + esc(__("pw.provider_default")) + "</option>" +
        providers.map(function (name) {
          return "<option value=\"" + esc(name) + "\"" +
            (name === spec.llm_provider ? " selected" : "") + ">" + esc(name) + "</option>";
        }).join("") + "</select>"),
      "<label class=\"pw-check pw-wide\"><input type=\"checkbox\" data-spec=\"fast\"" +
      (spec.fast ? " checked" : "") + " /> " + esc(__("pw.fast_mode")) + "</label>",
    ].join("");
  }

  function field(extra, label, control) {
    return "<label class=\"" + extra + "\"><span>" + esc(label) + "</span>" + control + "</label>";
  }

  function renderPresets() {
    var presets = (state.overview && state.overview.presets) || [];
    el("pwPresets").innerHTML = presets.map(function (preset) {
      return "<button type=\"button\" class=\"pw-preset\" data-preset=\"" + esc(preset.id) +
        "\" title=\"" + esc(preset.note || "") + "\">" + esc(preset.name) + "</button>";
    }).join("");
  }

  function renderWorlds() {
    var spec = state.spec;
    el("pwWorldList").innerHTML = spec.worlds.map(function (world, index) {
      var isBaseline = world.key === spec.baseline;
      var events = world.events.length
        ? world.events.map(function (event, eventIndex) {
            return eventCard(world.key, event, eventIndex, spec.sim_days);
          }).join("")
        : "<p class=\"pw-empty\">" + esc(__("pw.no_events")) + "</p>";
      return [
        "<div class=\"pw-world" + (isBaseline ? " is-baseline" : "") + "\" style=\"--w-color:" + colorFor(index) + "\">",
        "  <div class=\"pw-world-top\">",
        "    <input type=\"text\" data-world=\"" + world.key + "\" data-field=\"label\" value=\"" + esc(world.label) + "\" />",
        "    <div class=\"pw-world-tools\">",
        "      <button type=\"button\" class=\"pw-icon\" data-copy=\"" + world.key + "\" title=\"" + esc(__("pw.copy_world")) + "\">⧉</button>",
        "      <button type=\"button\" class=\"pw-icon is-danger\" data-remove=\"" + world.key + "\"" +
                 (spec.worlds.length <= 2 ? " disabled" : "") + " title=\"" + esc(__("pw.delete_world")) + "\">✕</button>",
        "    </div>",
        "  </div>",
        "  <label class=\"pw-baseline-pick\"><input type=\"radio\" name=\"pwBaseline\" data-baseline=\"" +
             world.key + "\"" + (isBaseline ? " checked" : "") + " /> " + esc(__("pw.as_baseline")) + "</label>",
        "  <div class=\"pw-events\">" + events + "</div>",
        "  <button type=\"button\" class=\"pw-addevent\" data-addevent=\"" + world.key + "\">" + esc(__("pw.add_event")) + "</button>",
        "</div>",
      ].join("");
    }).join("");
  }

  function eventCard(worldKey, event, index, simDays) {
    var attrs = "data-world=\"" + worldKey + "\" data-event=\"" + index + "\" data-field=";
    return [
      "<div class=\"pw-event\">",
      "  <div class=\"pw-event-row\">",
      "    <label><span>" + esc(__("pw.event_day")) + "</span><input type=\"number\" min=\"1\" max=\"" + esc(simDays || 30) +
           "\" " + attrs + "\"day\" value=\"" + esc(event.day) + "\" /></label>",
      "    <label><span>" + esc(__("pw.event_time")) + "</span><input type=\"text\" " + attrs + "\"time\" value=\"" + esc(event.time) + "\" /></label>",
      "    <label><span>" + esc(__("pw.event_name")) + "</span><input type=\"text\" " + attrs + "\"name\" placeholder=\"" + esc(__("pw.event_name_ph")) + "\" value=\"" + esc(event.name) + "\" /></label>",
      "    <button type=\"button\" class=\"pw-icon is-danger\" data-delevent=\"" + worldKey + ":" + index + "\" title=\"" + esc(__("pw.delete_event")) + "\">✕</button>",
      "  </div>",
      "  <textarea " + attrs + "\"description\" placeholder=\"" + esc(__("pw.event_desc_ph")) + "\">" + esc(event.description) + "</textarea>",
      "</div>",
    ].join("");
  }

  function renderDesign() {
    renderShared();
    renderPresets();
    renderWorlds();
  }

  // ---------------------------------------------------------- chart plumbing

  var PLOT = { left: 44, right: 14, top: 14, bottom: 26 };

  function scaler(width, height, xMax, yMin, yMax) {
    var span = (yMax - yMin) || 1;
    return {
      x: function (value) {
        return PLOT.left + (value / (xMax || 1)) * (width - PLOT.left - PLOT.right);
      },
      y: function (value) {
        return height - PLOT.bottom -
          ((value - yMin) / span) * (height - PLOT.top - PLOT.bottom);
      },
    };
  }

  /* Series carry nulls where no agent reported at a step; a null must break the
     path rather than being drawn through, otherwise a gap reads as a real dip. */
  function linePath(series, scale) {
    var parts = [];
    var pen = "M";
    series.forEach(function (value, index) {
      if (value == null) { pen = "M"; return; }
      parts.push(pen + scale.x(index).toFixed(1) + " " + scale.y(value).toFixed(1));
      pen = "L";
    });
    return parts.join(" ");
  }

  function axes(width, height, xMax, yMin, yMax, scale, stepsPerDay, simDays) {
    var out = [];
    var ticks = 4;
    for (var i = 0; i <= ticks; i++) {
      var value = yMin + ((yMax - yMin) * i) / ticks;
      var y = scale.y(value);
      out.push("<line class=\"pw-grid\" x1=\"" + PLOT.left + "\" y1=\"" + y.toFixed(1) +
        "\" x2=\"" + (width - PLOT.right) + "\" y2=\"" + y.toFixed(1) + "\" opacity=\".55\" />");
      out.push("<text class=\"pw-axis\" x=\"" + (PLOT.left - 6) + "\" y=\"" + (y + 3).toFixed(1) +
        "\" text-anchor=\"end\">" + fmt(value, Math.abs(yMax - yMin) < 0.2 ? 3 : 2) + "</text>");
    }
    if (stepsPerDay && simDays) {
      for (var day = 1; day <= simDays; day++) {
        var x = scale.x(Math.min(xMax, day * stepsPerDay));
        out.push("<text class=\"pw-axis\" x=\"" + x.toFixed(1) + "\" y=\"" + (height - 8) +
          "\" text-anchor=\"middle\">D" + day + "</text>");
      }
    } else {
      out.push("<text class=\"pw-axis\" x=\"" + PLOT.left + "\" y=\"" + (height - 8) + "\">0</text>");
      out.push("<text class=\"pw-axis\" x=\"" + (width - PLOT.right) + "\" y=\"" + (height - 8) +
        "\" text-anchor=\"end\">" + esc(__f("pw.axis_steps", { count: xMax })) + "</text>");
    }
    return out.join("");
  }

  function eventStep(event, report) {
    var perDay = report.steps_per_day;
    if (!perDay) return null;
    var day = Number(event.day) || 0;
    if (!day) return null;
    var minutes = 0;
    var parts = String(event.time || "").split(":");
    if (parts.length === 2) minutes = (Number(parts[0]) || 0) * 60 + (Number(parts[1]) || 0);
    return Math.min(report.steps - 1, Math.max(0, (day - 1) * perDay + (minutes / 1440) * perDay));
  }

  function eventMarkers(report, scale, height) {
    var colors = worldColors();
    var out = [];
    visibleWorlds().forEach(function (world) {
      (world.events || []).forEach(function (event) {
        var step = eventStep(event, report);
        if (step == null) return;
        var x = scale.x(step).toFixed(1);
        out.push("<line class=\"pw-eventline\" x1=\"" + x + "\" y1=\"" + PLOT.top +
          "\" x2=\"" + x + "\" y2=\"" + (height - PLOT.bottom) +
          "\" stroke=\"" + colors[world.id] + "\"><title>" +
          esc(world.label + " · Day " + event.day + " " + event.time + " " + event.name) +
          "</title></line>");
      });
    });
    return out.join("");
  }

  function emptyChart(target, message) {
    el(target).innerHTML = "<p class=\"pw-hint\">" + esc(message) + "</p>";
  }

  // ------------------------------------------------------- branch diagram

  /* Lanes alternate above and below the trunk purely to keep worlds apart; the
     distance from the trunk is the divergence, which is the part that means
     something. Said so in the panel's help text too. */
  function renderBranch() {
    var report = state.report;
    if (!report || !report.steps) { return emptyChart("pwBranch", __("pw.empty_branch")); }
    var width = 760, height = 250;
    var trunkY = height / 2;
    var worlds = visibleWorlds();
    var peak = 0;
    worlds.forEach(function (world) {
      peak = Math.max(peak, world.divergence_peak || 0);
    });
    peak = peak || 0.05;
    var lane = (height / 2 - PLOT.top - 14) / 1;
    var scale = scaler(width, height, Math.max(1, report.steps - 1), 0, 1);
    var colors = worldColors();

    var parts = [];
    // Day grid.
    if (report.steps_per_day && report.sim_days) {
      for (var day = 1; day < report.sim_days; day++) {
        var x = scale.x(day * report.steps_per_day);
        parts.push("<line class=\"pw-grid\" x1=\"" + x.toFixed(1) + "\" y1=\"" + PLOT.top +
          "\" x2=\"" + x.toFixed(1) + "\" y2=\"" + (height - PLOT.bottom) + "\" opacity=\".5\" />");
        parts.push("<text class=\"pw-axis\" x=\"" + x.toFixed(1) + "\" y=\"" + (height - 8) +
          "\" text-anchor=\"middle\">D" + (day + 1) + "</text>");
      }
    }

    var side = 1;
    worlds.forEach(function (world) {
      var curve = (report.divergence && report.divergence[world.id]) || [];
      var direction = world.is_baseline ? 0 : side;
      if (!world.is_baseline) side = side > 0 ? -1 : 1;
      var points = [];
      for (var step = 0; step < report.steps; step++) {
        var value = curve[step];
        var offset = value == null ? 0 : (value / peak) * lane * 0.86 * direction;
        points.push([scale.x(step), trunkY - offset]);
      }
      var d = points.map(function (point, index) {
        return (index ? "L" : "M") + point[0].toFixed(1) + " " + point[1].toFixed(1);
      }).join(" ");
      parts.push("<path class=\"pw-series" + (world.is_baseline ? " is-baseline" : "") +
        "\" d=\"" + d + "\" stroke=\"" + colors[world.id] + "\"><title>" +
        esc(__f("pw.tip_final_divergence", { world: world.label, value: fmt(world.divergence_final) })) + "</title></path>");

      // Split marker: where this history actually parted from the baseline.
      if (world.split_step != null) {
        var sx = scale.x(world.split_step);
        var sy = points[world.split_step] ? points[world.split_step][1] : trunkY;
        parts.push("<circle class=\"pw-node\" cx=\"" + sx.toFixed(1) + "\" cy=\"" + sy.toFixed(1) +
          "\" r=\"4.5\" fill=\"#fff\" stroke=\"" + colors[world.id] + "\" stroke-width=\"2\"><title>" +
          esc(__f("pw.tip_split_at", { world: world.label, step: world.split_step })) + "</title></circle>");
      }
      // The baseline label goes on the left of the trunk; branch labels ride
      // the right end of their own lane. Otherwise every world whose final
      // divergence is small piles its name onto the same few pixels.
      if (world.is_baseline) {
        parts.push("<text class=\"pw-node-label\" x=\"" + (PLOT.left + 4) + "\" y=\"" +
          (trunkY - 8) + "\" fill=\"" + colors[world.id] + "\">" +
          esc(__f("pw.label_baseline", { world: world.label })) + "</text>");
      } else {
        var last = points[points.length - 1] || [width - PLOT.right, trunkY];
        parts.push("<text class=\"pw-node-label\" x=\"" + (last[0] - 6).toFixed(1) + "\" y=\"" +
          (last[1] + (direction > 0 ? -9 : 16)).toFixed(1) + "\" text-anchor=\"end\" fill=\"" +
          colors[world.id] + "\">" + esc(world.label) + "</text>");
      }

      // Event pins on the world's own lane.
      (world.events || []).forEach(function (event) {
        var step = eventStep(event, report);
        if (step == null) return;
        var index = Math.round(step);
        var point = points[Math.min(points.length - 1, index)] || [scale.x(step), trunkY];
        parts.push("<circle cx=\"" + point[0].toFixed(1) + "\" cy=\"" + point[1].toFixed(1) +
          "\" r=\"3\" fill=\"" + colors[world.id] + "\"><title>" +
          esc("Day " + event.day + " " + event.time + " · " + event.name) + "</title></circle>");
        parts.push("<text class=\"pw-axis\" x=\"" + point[0].toFixed(1) + "\" y=\"" +
          (point[1] - 8).toFixed(1) + "\" text-anchor=\"middle\">" + esc(event.name) + "</text>");
      });
    });

    parts.unshift("<line class=\"pw-grid\" x1=\"" + PLOT.left + "\" y1=\"" + trunkY +
      "\" x2=\"" + (width - PLOT.right) + "\" y2=\"" + trunkY + "\" stroke-dasharray=\"2 4\" />");

    el("pwBranch").innerHTML =
      "<svg viewBox=\"0 0 " + width + " " + height + "\" role=\"img\" aria-label=\"" + esc(__("pw.chart_branch")) + "\">" +
      parts.join("") + "</svg>" + replayLinks();
  }

  /* Every world is a complete simulation, so its trace is replayable by the
     existing 仿真回放 page — the run id it wants is the visualization dir. */
  function replayLinks() {
    var links = (state.report.worlds || []).filter(function (world) {
      return world.trace;
    }).map(function (world) {
      var run = world.trace.replace(/\/simulation_trace\.json$/, "");
      return "<a class=\"pw-replay\" target=\"_blank\" rel=\"noopener\" href=\"/site/simviz/index.html?run=" +
        encodeURIComponent(run) + "\">▶ " + esc(world.label) + "</a>";
    });
    return links.length
      ? "<div class=\"pw-replays\"><span>" + esc(__("pw.replay_label")) + "</span>" + links.join("") + "</div>"
      : "";
  }

  // --------------------------------------------------------- trajectories

  function trajectorySeries(metric) {
    var report = state.report;
    var table = (report.trajectories && report.trajectories[metric]) || {};
    var baseline = table[report.baseline_id] || [];
    return visibleWorlds().map(function (world) {
      var raw = table[world.id] || [];
      var values = state.relative
        ? raw.map(function (value, index) {
            var base = baseline[index];
            return value == null || base == null ? null : value - base;
          })
        : raw;
      return { world: world, values: values };
    }).filter(function (item) { return item.values.length; });
  }

  function renderTrajectory() {
    var report = state.report;
    if (!report || !report.metrics || !report.metrics.length) {
      return emptyChart("pwTrajectory", __("pw.empty_trajectory"));
    }
    var metric = state.metric || report.metrics[0];
    var series = trajectorySeries(metric);
    if (!series.length) return emptyChart("pwTrajectory", __("pw.all_hidden"));

    var width = 760, height = 250;
    var values = [];
    series.forEach(function (item) {
      item.values.forEach(function (value) { if (value != null) values.push(value); });
    });
    var min = Math.min.apply(null, values);
    var max = Math.max.apply(null, values);
    if (min === max) { min -= 0.05; max += 0.05; }
    var pad = (max - min) * 0.12;
    var scale = scaler(width, height, Math.max(1, report.steps - 1), min - pad, max + pad);
    var colors = worldColors();

    var parts = [axes(width, height, report.steps - 1, min - pad, max + pad, scale,
      report.steps_per_day, report.sim_days)];
    parts.push(eventMarkers(report, scale, height));
    series.forEach(function (item) {
      parts.push("<path class=\"pw-series" + (item.world.is_baseline ? " is-baseline" : "") +
        "\" d=\"" + linePath(item.values, scale) + "\" stroke=\"" + colors[item.world.id] + "\" />");
    });
    parts.push("<line id=\"pwCursor\" class=\"pw-grid\" x1=\"0\" y1=\"" + PLOT.top +
      "\" x2=\"0\" y2=\"" + (height - PLOT.bottom) + "\" stroke=\"" + "#1a2420" +
      "\" opacity=\"0\" />");
    parts.push("<rect class=\"pw-hit\" x=\"" + PLOT.left + "\" y=\"" + PLOT.top +
      "\" width=\"" + (width - PLOT.left - PLOT.right) + "\" height=\"" +
      (height - PLOT.top - PLOT.bottom) + "\" />");

    el("pwTrajectory").innerHTML =
      "<svg viewBox=\"0 0 " + width + " " + height + "\" role=\"img\" aria-label=\"" + esc(__("pw.chart_trajectory")) + "\">" +
      parts.join("") + "</svg>";
    bindHover(el("pwTrajectory"), width, scale, series, metric);
  }

  function bindHover(wrap, width, scale, series, metric) {
    var svg = wrap.querySelector("svg");
    var cursor = wrap.querySelector("#pwCursor");
    var report = state.report;
    if (!svg) return;
    svg.addEventListener("mousemove", function (event) {
      var rect = svg.getBoundingClientRect();
      if (!rect.width) return;
      var x = ((event.clientX - rect.left) / rect.width) * width;
      var span = width - PLOT.left - PLOT.right;
      var step = Math.round(((x - PLOT.left) / span) * Math.max(1, report.steps - 1));
      step = Math.max(0, Math.min(report.steps - 1, step));
      if (cursor) {
        var cx = scale.x(step).toFixed(1);
        cursor.setAttribute("x1", cx);
        cursor.setAttribute("x2", cx);
        cursor.setAttribute("opacity", "0.35");
      }
      var label = report.metric_labels[metric] || metric;
      var day = report.steps_per_day
        ? __f("pw.readout_day", { day: Math.floor(step / report.steps_per_day) + 1 })
        : "";
      var bits = series.map(function (item) {
        var value = item.values[step];
        return "<b style=\"color:" + worldColors()[item.world.id] + "\">" + esc(item.world.label) +
          "</b> " + (value == null ? "—" : fmt(value, 3));
      });
      el("pwReadout").innerHTML =
        esc(__f("pw.readout", {
          step: step,
          day: day,
          metric: label,
          relative: state.relative ? __("pw.relative_suffix") : "",
        })) + bits.join("｜");
    });
    svg.addEventListener("mouseleave", function () {
      if (cursor) cursor.setAttribute("opacity", "0");
      el("pwReadout").textContent = __("pw.readout_hint");
    });
  }

  // ---------------------------------------------------------- divergence

  function renderDivergence() {
    var report = state.report;
    if (!report || !report.steps) return emptyChart("pwDivergence", __("pw.empty_divergence"));
    var worlds = visibleWorlds().filter(function (world) { return !world.is_baseline; });
    if (!worlds.length) return emptyChart("pwDivergence", __("pw.only_baseline"));

    var width = 760, height = 170;
    var max = report.split_threshold * 2;
    worlds.forEach(function (world) {
      ((report.divergence && report.divergence[world.id]) || []).forEach(function (value) {
        if (value != null && value > max) max = value;
      });
    });
    var scale = scaler(width, height, Math.max(1, report.steps - 1), 0, max * 1.12);
    var colors = worldColors();
    var parts = [axes(width, height, report.steps - 1, 0, max * 1.12, scale,
      report.steps_per_day, report.sim_days)];

    var thresholdY = scale.y(report.split_threshold).toFixed(1);
    parts.push("<line x1=\"" + PLOT.left + "\" y1=\"" + thresholdY + "\" x2=\"" +
      (width - PLOT.right) + "\" y2=\"" + thresholdY +
      "\" stroke=\"#c04545\" stroke-width=\"1\" stroke-dasharray=\"4 3\" opacity=\".8\" />");
    parts.push("<text class=\"pw-axis\" x=\"" + (width - PLOT.right) + "\" y=\"" +
      (Number(thresholdY) - 4) + "\" text-anchor=\"end\" fill=\"#c04545\">" +
      esc(__f("pw.split_threshold", { value: fmt(report.split_threshold, 2) })) + "</text>");

    worlds.forEach(function (world) {
      var curve = (report.divergence && report.divergence[world.id]) || [];
      parts.push("<path class=\"pw-series\" d=\"" + linePath(curve, scale) +
        "\" stroke=\"" + colors[world.id] + "\" />");
      if (world.split_step != null && curve[world.split_step] != null) {
        parts.push("<circle cx=\"" + scale.x(world.split_step).toFixed(1) + "\" cy=\"" +
          scale.y(curve[world.split_step]).toFixed(1) + "\" r=\"4\" fill=\"#fff\" stroke=\"" +
          colors[world.id] + "\" stroke-width=\"2\"><title>" +
          esc(__f("pw.tip_split_short", { world: world.label, step: world.split_step })) + "</title></circle>");
      }
    });
    el("pwDivergence").innerHTML =
      "<svg viewBox=\"0 0 " + width + " " + height + "\" role=\"img\" aria-label=\"" + esc(__("pw.chart_divergence")) + "\">" +
      parts.join("") + "</svg>";
  }

  // -------------------------------------------------------------- tables

  function renderLegend() {
    var report = state.report;
    if (!report) { el("pwLegend").innerHTML = ""; return; }
    var colors = worldColors();
    el("pwLegend").innerHTML = report.worlds.map(function (world) {
      return "<button type=\"button\" class=\"pw-legend-item" +
        (state.hidden[world.id] ? " is-off" : "") + "\" data-toggle=\"" + esc(world.id) + "\">" +
        "<span class=\"pw-legend-dot\" style=\"background:" + colors[world.id] + "\"></span>" +
        esc(world.label) + (world.is_baseline ? esc(__("pw.legend_baseline")) : "") +
        (world.status && world.status !== "done" ? " (" + esc(world.status) + ")" : "") +
        "</button>";
    }).join("");
  }

  function renderDeltas() {
    var report = state.report;
    var rows = (report && report.deltas) || [];
    if (!rows.length) { el("pwDeltas").innerHTML = "<p class=\"pw-hint\">" + esc(__("pw.empty_deltas")) + "</p>"; return; }
    var labels = {};
    var colors = worldColors();
    report.worlds.forEach(function (world) { labels[world.id] = world.label; });
    var visible = {};
    visibleWorlds().forEach(function (world) { visible[world.id] = true; });

    var body = rows.filter(function (row) { return visible[row.world_id]; })
      .slice(0, 60).map(function (row) {
        var cls = row.delta_final > 0 ? "pw-up" : "pw-down";
        return "<tr><td><span class=\"pw-chip\"><span class=\"pw-legend-dot\" style=\"background:" +
          colors[row.world_id] + "\"></span>" + esc(labels[row.world_id] || row.world_id) +
          "</span></td><td>" + esc(row.label) + "</td><td>" + fmt(row.baseline_final, 3) +
          "</td><td>" + fmt(row.final, 3) + "</td><td class=\"" + cls + "\">" +
          signed(row.delta_final, 3) + "</td><td class=\"" + cls + "\">" +
          signed(row.delta_mean, 3) + "</td></tr>";
      }).join("");
    el("pwDeltas").innerHTML =
      "<table><thead><tr>" +
      [ "pw.th_world", "pw.th_metric", "pw.th_baseline_final",
        "pw.th_this_world", "pw.th_delta_final", "pw.th_delta_mean",
      ].map(function (key) { return "<th>" + esc(__(key)) + "</th>"; }).join("") +
      "</tr></thead><tbody>" + body + "</tbody></table>";
  }

  function renderMovers() {
    var report = state.report;
    var movers = (report && report.movers) || {};
    var options = Object.keys(movers);
    var select = el("pwMoverWorld");
    if (!options.length) {
      select.innerHTML = "";
      el("pwMovers").innerHTML = "<p class=\"pw-hint\">" + esc(__("pw.empty_movers")) + "</p>";
      return;
    }
    if (options.indexOf(state.moverWorld) < 0) state.moverWorld = options[0];
    var labels = {};
    report.worlds.forEach(function (world) { labels[world.id] = world.label; });
    select.innerHTML = options.map(function (id) {
      return "<option value=\"" + esc(id) + "\"" + (id === state.moverWorld ? " selected" : "") +
        ">" + esc(labels[id] || id) + "</option>";
    }).join("");

    var rows = movers[state.moverWorld] || [];
    var peak = rows.reduce(function (acc, row) { return Math.max(acc, row.distance); }, 0) || 1;
    var color = worldColors()[state.moverWorld];
    var names = {};
    ((state.overview && state.overview.agents) || []).forEach(function (agent) {
      names[String(agent.id)] = agent.name;
    });
    el("pwMovers").innerHTML =
      "<table><thead><tr>" +
      [ "pw.th_resident", "pw.th_distance", "pw.th_top_metric",
      ].map(function (key) { return "<th>" + esc(__(key)) + "</th>"; }).join("") +
      "</tr></thead><tbody>" +
      rows.map(function (row) {
        var name = names[String(row.agent_id)] || ("Agent " + row.agent_id);
        var pct = ((row.distance / peak) * 100).toFixed(0);
        return "<tr><td>" + esc(name) + "</td><td><div class=\"pw-bar\"><span style=\"width:" +
          pct + "%;background:" + color + "\"></span></div><small>" + fmt(row.distance, 3) +
          "</small></td><td>" + esc(row.top_label) + " <span class=\"" +
          (row.top_delta > 0 ? "pw-up" : "pw-down") + "\">" + signed(row.top_delta, 3) +
          "</span></td></tr>";
      }).join("") + "</tbody></table>";
  }

  function renderMetricSelect() {
    var report = state.report;
    var select = el("pwMetricSelect");
    if (!report || !report.metrics.length) { select.innerHTML = ""; return; }
    if (report.metrics.indexOf(state.metric) < 0) state.metric = report.metrics[0];
    select.innerHTML = report.metrics.map(function (metric) {
      return "<option value=\"" + esc(metric) + "\"" + (metric === state.metric ? " selected" : "") +
        ">" + esc(report.metric_labels[metric] || metric) + "</option>";
    }).join("");
  }

  function renderTopMeta() {
    var report = state.report;
    if (!report) { el("pwTopMeta").innerHTML = esc(__("pw.no_experiment")); return; }
    var lines = (report.summary || []).map(esc);
    el("pwTopMeta").innerHTML =
      "<div><b>" + esc(report.name || report.experiment_id || "") + "</b>" +
      (report.legacy ? esc(__("pw.legacy_suffix")) : "") + "</div>" +
      "<div>" + esc(report.created_at || "") + "</div>" +
      (lines.length ? "<div style=\"margin-top:4px\">" + lines.join("<br/>") + "</div>" : "");
  }

  function renderObserve() {
    renderLegend();
    renderMetricSelect();
    renderBranch();
    renderTrajectory();
    renderDivergence();
    renderDeltas();
    renderMovers();
    renderTopMeta();
  }

  // ------------------------------------------------------------- run bar

  var STATUS_KEYS = {
    pending: "pw.status_pending", running: "pw.status_running", done: "pw.status_done",
    error: "pw.status_error", stopped: "pw.status_stopped",
  };

  /* Resolved per call rather than baked into a lookup at load time: the table
     used to hold the Chinese text itself, which froze whatever language was
     current when this file was evaluated. */
  function statusText(status) {
    var key = STATUS_KEYS[status];
    return key ? __(key) : status;
  }

  function renderRunBar() {
    var job = state.job;
    var run = el("pwRun");
    var stop = el("pwStop");
    var running = !!(job && job.status === "running");
    run.disabled = running;
    run.textContent = __(running ? "pw.run_busy" : "pw.run");
    stop.hidden = !running;

    if (!job) {
      el("pwRunState").textContent = __("pw.not_running");
      el("pwProgress").innerHTML = state.error
        ? "<div class=\"pw-error\">" + esc(state.error) + "</div>" : "";
      return;
    }
    el("pwRunState").textContent =
      statusText(job.status) + " · " + Math.round((job.progress || 0) * 100) + "%";

    var worlds = (job.snapshot && job.snapshot.worlds) || [];
    var simDays = (job.snapshot && job.snapshot.sim_days) || 1;
    var rows = worlds.map(function (world, index) {
      var ratio = world.status === "done" ? 1 : Math.min(1, (world.day || 0) / simDays);
      return "<div class=\"pw-prow\"><span class=\"pw-plabel\">" + esc(world.label) +
        "</span><span class=\"pw-bar\"><span style=\"width:" + (ratio * 100).toFixed(0) +
        "%;background:" + colorFor(index) + "\"></span></span><span class=\"pw-pstate\">" +
        esc(statusText(world.status)) +
        (world.status === "running" ? " D" + (world.day || 0) : "") + "</span></div>";
    }).join("");
    var message = job.message ? "<div class=\"pw-prow\"><span class=\"pw-plabel\">" + esc(__("pw.progress")) + "</span>" +
      "<span class=\"pw-pstate\" style=\"text-align:left;grid-column:2/4\">" + esc(job.message) +
      "</span></div>" : "";
    var error = job.error ? "<div class=\"pw-error\">" + esc(job.error) + "</div>" : "";
    el("pwProgress").innerHTML = rows + message + error +
      (state.error ? "<div class=\"pw-error\">" + esc(state.error) + "</div>" : "");
  }

  function renderHistory() {
    var items = (state.overview && state.overview.experiments) || [];
    el("pwHistory").innerHTML =
      "<option value=\"\">" + esc(__("pw.load_history")) + "</option>" +
      items.map(function (item) {
        return "<option value=\"" + esc(item.root) + "\"" +
          (item.root === state.experiment ? " selected" : "") + ">" +
          esc(item.name || item.id) + esc(__f("pw.world_count", { count: item.worlds })) +
          (item.legacy ? esc(__("pw.legacy_tag")) : "") +
          (item.has_data ? "" : esc(__("pw.no_data_tag"))) + "</option>";
      }).join("");
  }

  // ------------------------------------------------------------- actions

  async function loadOverview() {
    state.overview = await api("/api/parallel-worlds/overview");
    if (!state.spec) state.spec = defaultSpec(state.overview.defaults || {});
    state.job = state.overview.job || state.job;
    renderDesign();
    renderHistory();
    renderRunBar();
    if (!state.report) {
      // Newest experiment that actually produced state data: `output/` keeps
      // the shells of runs that died before writing any, and opening on one of
      // those shows an empty page for no reason.
      var usable = (state.overview.experiments || []).filter(function (item) {
        return item.has_data;
      })[0];
      if (usable) await loadExperiment(usable.root);
    }
    if (!state.report) renderObserve();  // draw the empty states, not blank cards
  }

  async function loadExperiment(root) {
    if (!root) return;
    state.experiment = root;
    state.report = await api("/api/parallel-worlds/experiment?root=" + encodeURIComponent(root));
    state.hidden = {};
    renderObserve();
    renderHistory();
  }

  async function runExperiment() {
    state.error = "";
    try {
      var result = await api("/api/parallel-worlds/start", {
        method: "POST",
        body: JSON.stringify(specPayload()),
      });
      state.job = result.job;
      state.experiment = result.experiment;
      renderRunBar();
      startPolling();
    } catch (error) {
      state.error = error.message;
      renderRunBar();
    }
  }

  function startPolling() {
    stopPolling();
    state.poll = setInterval(async function () {
      try {
        var payload = await api("/api/parallel-worlds/job");
        state.job = payload.job;
        renderRunBar();
        if (!state.job || state.job.status !== "running") {
          stopPolling();
          state.overview = await api("/api/parallel-worlds/overview");
          renderHistory();
          if (state.experiment) await loadExperiment(state.experiment);
        }
      } catch (error) {
        state.error = error.message;
        stopPolling();
        renderRunBar();
      }
    }, 2500);
  }

  function stopPolling() {
    if (state.poll) { clearInterval(state.poll); state.poll = null; }
  }

  // -------------------------------------------------------------- events

  function findWorld(key) {
    return state.spec.worlds.filter(function (world) { return world.key === key; })[0];
  }

  function onDesignInput(event) {
    var target = event.target;
    var specKey = target.getAttribute("data-spec");
    if (specKey) {
      state.spec[specKey] = target.type === "checkbox" ? target.checked : target.value;
      return;
    }
    var worldKey = target.getAttribute("data-world");
    if (!worldKey) return;
    var world = findWorld(worldKey);
    if (!world) return;
    var fieldName = target.getAttribute("data-field");
    var eventIndex = target.getAttribute("data-event");
    if (eventIndex == null) {
      if (fieldName === "label") world.label = target.value;
      return;
    }
    var item = world.events[Number(eventIndex)];
    if (item) item[fieldName] = target.value;
  }

  function onDesignClick(event) {
    var target = event.target.closest("[data-preset],[data-copy],[data-remove],[data-addevent],[data-delevent]");
    if (!target) return;
    var presetId = target.getAttribute("data-preset");
    if (presetId) {
      var preset = (state.overview.presets || []).filter(function (item) {
        return item.id === presetId;
      })[0];
      if (preset) applyPreset(preset);
      return;
    }
    var copyKey = target.getAttribute("data-copy");
    if (copyKey) {
      var source = findWorld(copyKey);
      if (source && state.spec.worlds.length < 8) {
        state.spec.worlds.push(newWorld(source.label + __("pw.copy_suffix"), source.events));
        renderWorlds();
      }
      return;
    }
    var removeKey = target.getAttribute("data-remove");
    if (removeKey) {
      if (state.spec.worlds.length <= 2) return;
      state.spec.worlds = state.spec.worlds.filter(function (world) {
        return world.key !== removeKey;
      });
      if (state.spec.baseline === removeKey) state.spec.baseline = state.spec.worlds[0].key;
      renderWorlds();
      return;
    }
    var addKey = target.getAttribute("data-addevent");
    if (addKey) {
      var world = findWorld(addKey);
      if (world) {
        world.events.push({
          day: Math.min(Number(state.spec.sim_days) || 3, 2),
          time: "09:00", name: "", description: "",
        });
        renderWorlds();
      }
      return;
    }
    var delKey = target.getAttribute("data-delevent");
    if (delKey) {
      var parts = delKey.split(":");
      var owner = findWorld(parts[0]);
      if (owner) { owner.events.splice(Number(parts[1]), 1); renderWorlds(); }
    }
  }

  function onDesignChange(event) {
    var baselineKey = event.target.getAttribute("data-baseline");
    if (baselineKey) { state.spec.baseline = baselineKey; renderWorlds(); return; }
    onDesignInput(event);
  }

  function bind() {
    var design = el("pwDesign");
    design.addEventListener("input", onDesignInput);
    design.addEventListener("change", onDesignChange);
    design.addEventListener("click", onDesignClick);

    el("pwAddWorld").addEventListener("click", function () {
      if (state.spec.worlds.length >= 8) return;
      state.spec.worlds.push(newWorld(__f("pw.world_n", { n: state.spec.worlds.length + 1 }), [{
        day: 2, time: "09:00", name: "", description: "",
      }]));
      renderWorlds();
    });

    el("pwLegend").addEventListener("click", function (event) {
      var button = event.target.closest("[data-toggle]");
      if (!button) return;
      var id = button.getAttribute("data-toggle");
      state.hidden[id] = !state.hidden[id];
      renderObserve();
    });

    el("pwMetricSelect").addEventListener("change", function (event) {
      state.metric = event.target.value;
      renderTrajectory();
    });
    el("pwRelative").addEventListener("change", function (event) {
      state.relative = event.target.checked;
      renderTrajectory();
    });
    el("pwMoverWorld").addEventListener("change", function (event) {
      state.moverWorld = event.target.value;
      renderMovers();
    });
    el("pwHistory").addEventListener("change", function (event) {
      if (event.target.value) loadExperiment(event.target.value).catch(function (error) {
        state.error = error.message;
        renderRunBar();
      });
    });
    el("pwRefresh").addEventListener("click", function () {
      loadOverview().catch(function (error) { state.error = error.message; renderRunBar(); });
    });
    el("pwRun").addEventListener("click", runExperiment);
    el("pwStop").addEventListener("click", async function () {
      try {
        var payload = await api("/api/parallel-worlds/stop", { method: "POST" });
        state.job = payload.job;
        renderRunBar();
      } catch (error) { state.error = error.message; renderRunBar(); }
    });
  }

  function boot() {
    bind();
    loadOverview().catch(function (error) {
      state.error = error.message;
      renderRunBar();
    });
    if (state.job && state.job.status === "running") startPolling();
  }

  /* Everything on this page is drawn from JS, so the language switch has to
     redraw it — and the first paint can land before the locale JSON does, in
     which case __() has been echoing keys back and the same redraw fixes it.
     The spec holds two world labels that were themselves translated at
     creation, so those are re-translated only while they are untouched
     defaults; a name the user typed is theirs to keep. */
  function onLocaleChanged(previous) {
    if (state.spec) {
      var defaults = {};
      defaults[previous.baseline] = "pw.world_baseline";
      defaults[previous.event] = "pw.world_event";
      defaults[previous.name] = "pw.experiment_name";
      if (defaults[state.spec.name]) state.spec.name = __(defaults[state.spec.name]);
      state.spec.worlds.forEach(function (world) {
        if (defaults[world.label]) world.label = __(defaults[world.label]);
      });
    }
    renderDesign();
    renderHistory();
    renderRunBar();
    renderObserve();
  }

  if (typeof document !== "undefined") {
    var lastLabels = {
      baseline: typeof __ === "function" ? __("pw.world_baseline") : "",
      event: typeof __ === "function" ? __("pw.world_event") : "",
      name: typeof __ === "function" ? __("pw.experiment_name") : "",
    };
    document.addEventListener("locale-changed", function () {
      var previous = lastLabels;
      lastLabels = {
        baseline: __("pw.world_baseline"),
        event: __("pw.world_event"),
        name: __("pw.experiment_name"),
      };
      onLocaleChanged(previous);
    });
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { boot: boot, __state: state };
  }
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", boot);
    } else {
      boot();
    }
  }
})();
