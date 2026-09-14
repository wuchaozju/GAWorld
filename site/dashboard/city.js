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
    if (current && values.indexOf(current) !== -1) select.value = current;
    else if (preferred && values.indexOf(preferred) !== -1) select.value = preferred;
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
