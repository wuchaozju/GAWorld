/* City panel.
 *
 * Create a whole simulation world from a place name, then put agents in it.
 * The left column creates and lists; the right column acts on whichever city
 * is selected. One piece of shared state (`state.selected`) links the two.
 *
 * Everything here is a thin shell over /api/city/* — the map, environment and
 * population generation all happen server-side in gaworld.city, so this file
 * stays a form-and-list renderer with no simulation logic of its own.
 */
(function () {
  "use strict";

  var state = {
    overview: null,
    selected: "",
    detail: null,
    busy: false,
    mapView: null,
    mapToken: 0,
    knowledge: null,
  };

  function el(id) { return document.getElementById(id); }

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  async function api(path, options) {
    var settings = Object.assign({}, options || {});
    settings.headers = Object.assign(
      { "Content-Type": "application/json" }, settings.headers || {}
    );
    var response = await fetch(path, settings);
    var payload = {};
    try { payload = await response.json(); } catch (_) { payload = {}; }
    if (!response.ok) throw new Error(payload.error || (__("city.request_failed") + response.status));
    return payload;
  }

  function post(path, body) {
    return api(path, { method: "POST", body: JSON.stringify(body || {}) });
  }

  function status(node, message, kind) {
    if (!node) return;
    node.className = "city-status" + (kind ? " is-" + kind : "");
    node.textContent = message || "";
  }

  /* Long operations disable every submit button rather than only the one that
     was pressed: creating a city and populating it at the same time would race
     on the same manifest file. */
  function setBusy(busy) {
    state.busy = busy;
    var buttons = document.querySelectorAll(".city-form button");
    for (var i = 0; i < buttons.length; i += 1) buttons[i].disabled = busy;
  }

  function fillOptions(select, values, placeholderText, preferred) {
    if (!select) return;
    var current = select.value;
    select.innerHTML = "";
    if (placeholderText != null) {
      var blank = document.createElement("option");
      blank.value = "";
      blank.textContent = placeholderText;
      select.appendChild(blank);
    }
    values.forEach(function (value) {
      var option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    });
    // The server sorts presets alphabetically, which would otherwise leave
    // "aging_community" selected by default rather than the general-purpose one.
    var chosen = null;
    if (current && values.indexOf(current) !== -1) chosen = current;
    else if (preferred && values.indexOf(preferred) !== -1) chosen = preferred;
    if (chosen == null) return;
    select.value = chosen;
    // Set the `selected` ATTRIBUTE too, not just the property: form.reset()
    // (which the create form runs on success) restores each select to the
    // option carrying that attribute, and with none set it silently falls back
    // to the first option — i.e. the next city would quietly be generated with
    // "aging_community" instead of the preset the operator last chose.
    for (var i = 0; i < select.options.length; i += 1) {
      if (select.options[i].value === chosen) select.options[i].setAttribute("selected", "selected");
      else select.options[i].removeAttribute("selected");
    }
  }

  // ------------------------------------------------------------- rendering

  function renderTopMeta() {
    var node = el("cityTopMeta");
    if (!node || !state.overview) return;
    var total = state.overview.cities.length;
    var selected = state.overview.selected;
    node.innerHTML =
      '<div class="city-meta-item"><span>' + esc(__("city.meta_cities")) + "</span><b>" +
        total + "</b></div>" +
      '<div class="city-meta-item"><span>' + esc(__("city.meta_in_use")) + "</span><b>" +
        esc(selected || __("city.default_world")) + "</b></div>";
  }

  function renderList() {
    var node = el("cityList");
    if (!node || !state.overview) return;
    var cities = state.overview.cities;
    if (!cities.length) {
      node.innerHTML = '<p class="city-hint">' + esc(__("city.empty")) + "</p>";
      return;
    }
    node.innerHTML = cities.map(function (city) {
      var active = city.slug === state.selected ? " is-active" : "";
      var inUse = city.slug === state.overview.selected
        ? '<span class="city-badge is-use">' + esc(__("city.badge_running")) + "</span>" : "";
      var mode = city.map_mode === "real"
        ? '<span class="city-badge is-real">' + esc(__("city.badge_real")) + "</span>"
        : '<span class="city-badge">' + esc(__("city.badge_procedural")) + "</span>";
      return (
        '<button type="button" class="city-item' + active + '" data-slug="' + esc(city.slug) + '">' +
          '<div class="city-item-head"><b>' + esc(city.name) + "</b>" + mode + inUse + "</div>" +
          '<div class="city-item-sub">' + esc(city.display_name) + "</div>" +
          '<div class="city-item-stats">' +
            "<span>" + esc(city.scale || "—") + "</span>" +
            "<span>" + esc(__f("city.agent_count", { count: city.population })) + "</span>" +
          "</div>" +
        "</button>"
      );
    }).join("");
  }

  function renderDetail() {
    var card = el("cityDetailCard");
    var hint = el("cityEmptyHint");
    var node = el("cityDetail");
    if (!card || !node) return;
    if (!state.detail) {
      card.hidden = true;
      if (hint) hint.hidden = false;
      return;
    }
    card.hidden = false;
    if (hint) hint.hidden = true;

    var detail = state.detail;
    var place = detail.place || {};
    var inUse = state.overview && state.overview.selected === detail.slug;
    var rows = [
      [__("city.kv_place"), detail.display_name],
      [__("city.kv_scale"), detail.scale],
      [__("city.kv_map"), __(detail.map_mode === "real" ? "city.map_real" : "city.map_procedural")],
      [__("city.kv_coords"), place.lat != null ? place.lat.toFixed(4) + ", " + place.lng.toFixed(4) : "—"],
      [__("city.kv_source"), __(place.source === "nominatim" ? "city.source_online" : "city.source_offline")],
      [__("city.kv_agents"), detail.population],
      [__("city.kv_districts"), (detail.districts || []).slice(0, 6).join("、")],
    ];
    node.innerHTML =
      '<dl class="city-kv">' +
        rows.map(function (row) {
          return "<dt>" + esc(row[0]) + "</dt><dd>" + esc(row[1] == null ? "—" : row[1]) + "</dd>";
        }).join("") +
      "</dl>" +
      '<div class="city-detail-actions">' +
        '<button type="button" class="btn' + (inUse ? " ghost" : " primary") + '" id="cityUseBtn">' +
          esc(__(inUse ? "city.stop_using" : "city.use_for_run")) +
        "</button>" +
        '<button type="button" class="btn danger" id="cityDeleteBtn">' +
          esc(__("city.delete")) + "</button>" +
      "</div>";

    el("cityUseBtn").addEventListener("click", function () {
      onSelectForRun(inUse ? { clear: true } : { city: detail.slug });
    });
    el("cityDeleteBtn").addEventListener("click", onDelete);

    fillOptions(
      el("migrateFrom"),
      state.overview.cities
        .map(function (c) { return c.slug; })
        .filter(function (slug) { return slug !== detail.slug; }),
      __("city.default_dataset")
    );
  }

  // ------------------------------------------------------------------- map

  /* The preview reuses CityMapView — the renderer the console map panel and
     the simviz replay already use — so a city looks here exactly as it will
     when it runs. It expects a "trace"; a map with no agents and no frames is
     a legitimate one, so we hand it `{map}` and render zero frames. */
  function ensureMapView() {
    if (state.mapView) return state.mapView;
    var canvas = el("cityMapCanvas");
    if (!canvas || typeof window.CityMapView !== "function") return null;
    state.mapView = new window.CityMapView(canvas, {
      getSelectedAgentId: function () { return null; },
      emptyText: function () { return __("city.map_empty"); },
    });
    return state.mapView;
  }

  function setMapOverlay(message) {
    var overlay = el("cityMapOverlay");
    if (!overlay) return;
    overlay.hidden = !message;
    overlay.textContent = message || "";
  }

  async function loadMap(slug) {
    var view = ensureMapView();
    if (!view) return;
    // Selecting cities faster than they load would let an earlier response
    // paint over a later one; only the newest token is allowed to render.
    var token = (state.mapToken += 1);

    var card = el("cityMapCard");
    if (!slug) {
      if (card) card.hidden = true;
      view.setTrace(null);
      view.render([]);
      setMapOverlay("");
      status(el("cityMapMeta"), "");
      return;
    }
    if (card) card.hidden = false;
    var nameNode = el("cityMapName");
    if (nameNode) nameNode.textContent = state.detail ? state.detail.name : "";

    setMapOverlay(__("city.map_loading"));
    try {
      var payload = await api("/api/city/map?city=" + encodeURIComponent(slug));
      if (token !== state.mapToken) return;
      view.setTrace({ map: payload.map, agents: [], meta: {} });
      view.render([]);
      setMapOverlay("");
      var meta = payload.meta || {};
      var bits = [
        __(meta.mode === "real" ? "city.map_real" : "city.map_procedural"),
        meta.nodes + " " + __("city.map_nodes"),
        meta.edges + " " + __("city.map_edges"),
      ];
      if (meta.river) bits.push(meta.river);
      if ((meta.metro_lines || []).length) {
        bits.push(__("city.map_metro") + " " + meta.metro_lines.join("/"));
      }
      status(el("cityMapMeta"), bits.join(" · "));
    } catch (err) {
      if (token !== state.mapToken) return;
      view.setTrace(null);
      view.render([]);
      setMapOverlay(err.message);
      status(el("cityMapMeta"), "");
    }
  }

  // ------------------------------------------------------- knowledge base

  function renderKnowledge(payload) {
    var card = el("cityKnowledgeCard");
    var node = el("cityKnowledge");
    if (!card || !node) return;
    card.hidden = false;
    state.knowledge = payload;

    var profile = (payload && payload.profile) || {};
    el("cityKnowledgeSource").textContent = payload && payload.empty
      ? __("city.knowledge_none")
      : __("city.knowledge_source_" + (profile.source || "stub"));

    if (!payload || payload.empty) {
      node.innerHTML = '<p class="city-hint">' + esc(__("city.knowledge_empty")) + "</p>";
      return;
    }

    var arrows = { growing: "↑", declining: "↓", stable: "·" };
    var rows = (profile.industries || []).map(function (industry) {
      return (
        '<li><span class="city-ind-trend is-' + esc(industry.trend) + '">' +
          esc(arrows[industry.trend] || "·") + "</span>" +
        "<b>" + esc(industry.name) + "</b>" +
        '<span class="city-ind-weight">' + Math.round((industry.weight || 0) * 100) + "%</span>" +
        '<span class="city-ind-note">' + esc(industry.note || "") + "</span></li>"
      );
    }).join("");

    var channels = (payload && payload.channels) || {};
    var economy = Object.keys(channels.economy || {}).sort().map(function (key) {
      return key + " " + channels.economy[key];
    }).join("  ");

    var meta = [];
    if (profile.summary) meta.push("<p>" + esc(profile.summary) + "</p>");
    if ((profile.priorities || []).length) {
      meta.push("<p><em>" + esc(__("city.knowledge_priorities")) + "</em>" +
                esc(profile.priorities.join("、")) + "</p>");
    }
    if ((profile.labor_demand || []).length) {
      meta.push("<p><em>" + esc(__("city.knowledge_demand")) + "</em>" +
                esc(profile.labor_demand.join("、")) + "</p>");
    }
    if (economy) {
      meta.push("<p><em>" + esc(__("city.knowledge_income")) + "</em>" + esc(economy) + "</p>");
    }
    var sources = (profile.sources || []).slice(0, 4).map(function (s) {
      return '<a href="' + esc(s.url) + '" target="_blank" rel="noopener">' +
             esc(s.title || s.url) + "</a>";
    }).join(" · ");
    if (sources) meta.push('<p class="city-knowledge-sources">' + sources + "</p>");

    node.innerHTML = (rows ? '<ul class="city-industries">' + rows + "</ul>" : "") + meta.join("");
  }

  async function loadKnowledge(slug) {
    var card = el("cityKnowledgeCard");
    if (!slug) {
      if (card) card.hidden = true;
      return;
    }
    try {
      renderKnowledge(await api("/api/city/knowledge?city=" + encodeURIComponent(slug)));
    } catch (err) {
      if (card) card.hidden = false;
      el("cityKnowledge").innerHTML = '<p class="city-hint">' + esc(err.message) + "</p>";
    }
  }

  function knowledgeAction(path, body, busyKey) {
    return async function () {
      if (state.busy || !state.detail) return;
      var node = el("cityKnowledgeStatus");
      setBusy(true);
      status(node, __(busyKey), "busy");
      try {
        var result = await post(path, Object.assign({ city: state.detail.slug }, body || {}));
        if (result.profile) renderKnowledge(result);
        else await loadKnowledge(state.detail.slug);
        status(node, __("city.knowledge_done"), "ok");
      } catch (err) {
        status(node, err.message, "error");
      } finally {
        setBusy(false);
      }
    };
  }

  function render() {
    renderTopMeta();
    renderList();
    renderDetail();
  }

  // --------------------------------------------------------------- actions

  async function loadOverview() {
    state.overview = await api("/api/city");
    fillOptions(el("cityScale"), state.overview.scales, __("city.scale_auto"));
    fillOptions(el("cityPreset"), state.overview.presets, null, "cn_county_town");
    fillOptions(el("popPreset"), state.overview.presets, null, "cn_county_town");
    render();
  }

  async function loadDetail(slug) {
    state.selected = slug;
    state.detail = slug ? await api("/api/city/detail?city=" + encodeURIComponent(slug)) : null;
    render();
    // Not awaited: the detail card and its forms are usable immediately, and
    // building a real map server-side takes a moment.
    loadMap(slug);
    loadKnowledge(slug);
  }

  function numberOrNull(id) {
    var raw = el(id).value.trim();
    if (!raw) return null;
    var parsed = Number(raw);
    return isFinite(parsed) ? parsed : null;
  }

  async function onCreate(event) {
    event.preventDefault();
    if (state.busy) return;
    var node = el("cityCreateStatus");
    var name = el("cityName").value.trim();
    if (!name) { status(node, __("city.need_name"), "error"); return; }

    setBusy(true);
    status(node, __(el("cityOffline").checked ? "city.generating" : "city.geocoding"), "busy");
    try {
      var result = await post("/api/city/create", {
        name: name,
        scale: el("cityScale").value || null,
        offline: el("cityOffline").checked,
        size: Number(el("citySize").value) || 0,
        preset: el("cityPreset").value,
        seed: numberOrNull("citySeed"),
      });
      var city = result.city;
      var mode = __(city.map_mode === "real" ? "city.mode_real" : "city.mode_procedural");
      status(node, result.population
        ? __f("city.created_with_pop", {
            name: city.name, mode: mode, count: result.population.total,
          })
        : __f("city.created", { name: city.name, mode: mode }), "ok");
      el("cityCreateForm").reset();
      // reset() snaps every select back to its first option, so re-apply the
      // preferred defaults rather than leaving "aging_community" selected.
      await loadOverview();
      await loadDetail(city.slug);
    } catch (error) {
      status(node, error.message, "error");
    } finally {
      setBusy(false);
    }
  }

  /* The three "add agents" forms share one submit path: they differ only in
     endpoint and payload, and every one of them ends by refreshing the same
     two views. */
  function agentAction(endpoint, buildPayload, describe) {
    return async function (event) {
      event.preventDefault();
      if (state.busy || !state.detail) return;
      var node = el("cityActionStatus");
      setBusy(true);
      status(node, __("city.working"), "busy");
      try {
        var result = await post(endpoint, Object.assign(
          { city: state.detail.slug }, buildPayload()
        ));
        status(node, "✓ " + describe(result), "ok");
        await loadOverview();
        await loadDetail(state.detail.slug);
      } catch (error) {
        status(node, error.message, "error");
      } finally {
        setBusy(false);
      }
    };
  }

  async function onSelectForRun(payload) {
    var node = el("cityActionStatus");
    setBusy(true);
    try {
      var result = await post("/api/city/select", payload);
      status(node, result.selected
        ? __f("city.will_use", { name: result.selected })
        : __("city.restored_default"), "ok");
      await loadOverview();
      await loadDetail(state.selected);
    } catch (error) {
      status(node, error.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete() {
    if (!state.detail) return;
    if (!window.confirm(__f("city.confirm_delete", { name: state.detail.name }))) {
      return;
    }
    var node = el("cityActionStatus");
    setBusy(true);
    try {
      await post("/api/city/delete", { city: state.detail.slug });
      state.detail = null;
      state.selected = "";
      status(node, __("city.deleted"), "ok");
      await loadOverview();
    } catch (error) {
      status(node, error.message, "error");
    } finally {
      setBusy(false);
    }
  }

  // ------------------------------------------------------------------ init

  function bind() {
    el("cityCreateForm").addEventListener("submit", onCreate);
    el("cityKnowledgeRebuild").addEventListener(
      "click", knowledgeAction("/api/city/knowledge", {}, "city.knowledge_building"));
    el("cityKnowledgeOffline").addEventListener(
      "click", knowledgeAction("/api/city/knowledge", { offline: true }, "city.knowledge_building"));
    el("cityNewsRefresh").addEventListener(
      "click", knowledgeAction("/api/city/news", { force: true }, "city.news_fetching"));

    el("cityList").addEventListener("click", function (event) {
      var item = event.target.closest(".city-item");
      if (item) loadDetail(item.dataset.slug);
    });

    el("cityPopForm").addEventListener("submit", agentAction(
      "/api/city/population",
      function () {
        return {
          size: Number(el("popSize").value) || 0,
          preset: el("popPreset").value,
          replace: el("popReplace").checked,
        };
      },
      function (result) {
        var pop = result.population;
        var note = pop.added !== pop.requested
          ? __f("city.pop_clamped", { requested: pop.requested }) : "";
        return __f("city.pop_added", { added: pop.added, total: pop.total, note: note });
      }
    ));

    el("cityAgentForm").addEventListener("submit", agentAction(
      "/api/city/agent",
      function () {
        return {
          name: el("agentName").value.trim(),
          age: Number(el("agentAge").value),
          gender: el("agentGender").value,
          job: el("agentJob").value.trim() || undefined,
        };
      },
      function (result) {
        return __f("city.agent_joined", {
          name: result.agent.name, residence: result.agent.residence,
        });
      }
    ));

    el("cityMigrateForm").addEventListener("submit", agentAction(
      "/api/city/migrate",
      function () {
        return {
          agent_id: Number(el("migrateId").value),
          from_city: el("migrateFrom").value || undefined,
          rehome: el("migrateRehome").checked,
        };
      },
      function (result) {
        return __f("city.agent_migrated", {
          source: result.agent.source_id, id: result.agent.id,
        });
      }
    ));
  }

  async function init() {
    bind();
    try {
      await loadOverview();
    } catch (error) {
      status(el("cityCreateStatus"), error.message, "error");
    }
  }

  /* Every label here is drawn from JS, so the language switch has to redraw.
     The two <select> placeholders are rebuilt through loadOverview() because
     fillOptions() bakes the placeholder text in at build time. Transient status
     messages are left alone: re-translating "✓ 已删除" after the fact would be
     rewriting a record of something that already happened. */
  document.addEventListener("locale-changed", function () {
    if (!state.overview) return;
    fillOptions(el("cityScale"), state.overview.scales, __("city.scale_auto"));
    render();
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
