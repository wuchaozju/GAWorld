// Unified console shell: hosts the GAWorld apps as views in a grouped sidebar.
// Each app is an independent same-origin page loaded in its own iframe. Frames
// are created on first visit and kept alive (hidden, not destroyed) so each app
// preserves its state when you switch away and back.
//
// The sidebar markup (index.html) owns the grouping and order; TABS here only
// maps a view id to the page it loads, and TABS[0] is the default view.
(function () {
  "use strict";

  var TABS = [
    { id: "dashboard", src: "/dashboard" },
    { id: "simviz", src: "/site/simviz/index.html" },
    { id: "city", src: "/site/dashboard/city.html" },
    { id: "analytics", src: "/site/dashboard/analytics.html" },
    { id: "studio", src: "/site/dashboard/studio.html" },
    { id: "organizations", src: "/site/dashboard/organizations.html" },
    { id: "population", src: "/site/dashboard/population.html" },
    { id: "play", src: "/site/dashboard/play.html" },
    { id: "survey", src: "/site/dashboard/survey.html" },
    { id: "research", src: "/site/dashboard/research.html" },
    { id: "collaboration", src: "/site/dashboard/collaboration.html" },
    { id: "games", src: "/site/dashboard/games.html" },
    { id: "external", src: "/site/dashboard/external.html" },
    { id: "admin", src: "/site/dashboard/admin.html" },
    { id: "settings", src: "/site/dashboard/settings.html" },
    { id: "docs", src: "/site/dashboard/docs.html" },
  ];

  // Views that moved inside another page: the old hash still opens them.
  // Parallel Worlds is now the 平行世界 tab of the research workbench.
  var ALIASES = {
    worlds: { id: "research", src: "/site/dashboard/research.html?tab=worlds" },
  };

  var COLLAPSE_KEY = "gaworld-nav-collapsed";

  var framesEl = document.getElementById("frames");
  var loadingEl = document.getElementById("frameLoading");
  var openNewEl = document.getElementById("openNew");
  var crumbGroupEl = document.getElementById("crumbGroup");
  var crumbViewEl = document.getElementById("crumbView");
  var navToggleEl = document.getElementById("navToggle");
  var backdropEl = document.getElementById("navBackdrop");
  var tabsEl = document.getElementById("tabs");
  var tabButtons = Array.prototype.slice.call(document.querySelectorAll(".tab"));
  var phone = window.matchMedia("(max-width: 860px)");

  var frames = {}; // id -> iframe element (lazily created)
  var loaded = {}; // id -> true once the iframe fired load
  var activeId = null;

  function tabById(id) {
    for (var i = 0; i < TABS.length; i++) {
      if (TABS[i].id === id) return TABS[i];
    }
    return null;
  }

  function buttonById(id) {
    for (var i = 0; i < tabButtons.length; i++) {
      if (tabButtons[i].dataset.tab === id) return tabButtons[i];
    }
    return null;
  }

  function text(key) {
    return typeof window.__ === "function" ? window.__(key) : key;
  }

  function labelOf(btn) {
    var el = btn.querySelector("[data-i18n]");
    return el ? el.textContent.trim() : btn.dataset.tab;
  }

  function groupLabelOf(btn) {
    var group = btn.closest(".nav-group");
    var el = group && group.querySelector(".nav-group-label [data-i18n]");
    return el ? el.textContent.trim() : "";
  }

  function readCollapsed() {
    try { return localStorage.getItem(COLLAPSE_KEY) === "1"; } catch (_) { return false; }
  }

  function writeCollapsed(on) {
    try { localStorage.setItem(COLLAPSE_KEY, on ? "1" : "0"); } catch (_) { /* private mode */ }
  }

  /* ---------------------------------------------------------------- frames */

  function ensureFrame(tab) {
    if (frames[tab.id]) return frames[tab.id];
    var iframe = document.createElement("iframe");
    iframe.src = tab.src;
    iframe.title = tab.id;
    iframe.hidden = true;
    iframe.addEventListener("load", function () {
      loaded[tab.id] = true;
      syncLoading();
    });
    framesEl.appendChild(iframe);
    frames[tab.id] = iframe;
    return iframe;
  }

  function syncLoading() {
    loadingEl.hidden = !activeId || !!loaded[activeId];
  }

  /* ---------------------------------------------------------------- chrome */

  function isCollapsed() {
    return !phone.matches && document.body.classList.contains("nav-collapsed");
  }

  // Breadcrumb, window title, and the tooltips that stand in for the labels
  // while the rail is collapsed. Re-run on every locale change, because all
  // of it is derived from the translated label text.
  function syncChrome() {
    var btn = buttonById(activeId);
    if (btn) {
      var view = labelOf(btn);
      crumbGroupEl.textContent = groupLabelOf(btn);
      crumbViewEl.textContent = view;
      document.title = "GAWorld Console · " + view;
    }
    var collapsed = isCollapsed();
    tabButtons.forEach(function (b) {
      if (collapsed) b.title = labelOf(b);
      else b.removeAttribute("title");
    });
    var toggleKey = phone.matches
      ? "console.menu"
      : (collapsed ? "console.expand_nav" : "console.collapse_nav");
    // Keep data-i18n-title in step so the next applyTranslations() agrees;
    // until the locale file has loaded, __() echoes the key, so leave the
    // markup's own title in place rather than showing "console.menu".
    navToggleEl.setAttribute("data-i18n-title", toggleKey);
    var toggleText = text(toggleKey);
    if (toggleText !== toggleKey) navToggleEl.title = toggleText;
    var expanded = phone.matches
      ? document.body.classList.contains("nav-open")
      : !collapsed;
    navToggleEl.setAttribute("aria-expanded", expanded ? "true" : "false");
  }

  function setCollapsed(on) {
    document.body.classList.toggle("nav-collapsed", on);
    writeCollapsed(on);
    syncChrome();
  }

  function openDrawer() {
    document.body.classList.add("nav-open");
    backdropEl.hidden = false;
    syncChrome();
  }

  function closeDrawer() {
    document.body.classList.remove("nav-open");
    backdropEl.hidden = true;
    syncChrome();
  }

  /* -------------------------------------------------------------- activate */

  function activate(id) {
    var tab = tabById(id) || TABS[0];
    activeId = tab.id;
    ensureFrame(tab);
    Object.keys(frames).forEach(function (key) {
      frames[key].hidden = key !== tab.id;
    });
    tabButtons.forEach(function (btn) {
      var on = btn.dataset.tab === tab.id;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
      btn.tabIndex = on ? 0 : -1; // roving tabindex: one tab stop for the list
    });
    openNewEl.setAttribute("href", tab.src);
    syncLoading();
    if (phone.matches) closeDrawer(); else syncChrome();
  }

  function currentTabId() {
    var id = (location.hash || "").replace(/^#/, "");
    var alias = ALIASES[id];
    if (alias) {
      // Point the target view at the right sub-tab before it activates: a
      // fresh frame loads the aliased src, an open one is navigated to it.
      if (frames[alias.id]) frames[alias.id].src = alias.src;
      else ensureFrame({ id: alias.id, src: alias.src });
      history.replaceState(null, "", "#" + alias.id);
      return alias.id;
    }
    return tabById(id) ? id : TABS[0].id;
  }

  /* ---------------------------------------------------------------- wiring */

  tabButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var id = btn.dataset.tab;
      if (("#" + id) === location.hash) {
        activate(id); // same hash: no hashchange event, activate directly
      } else {
        location.hash = id;
      }
    });
  });

  // Arrow keys walk the list (it is a vertical tablist); Enter/Space activate,
  // which a <button> already does on its own.
  tabsEl.addEventListener("keydown", function (event) {
    var index = tabButtons.indexOf(document.activeElement);
    if (index < 0) return;
    var n = tabButtons.length;
    var next = null;
    if (event.key === "ArrowDown" || event.key === "ArrowRight") next = (index + 1) % n;
    else if (event.key === "ArrowUp" || event.key === "ArrowLeft") next = (index - 1 + n) % n;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = n - 1;
    if (next === null) return;
    event.preventDefault();
    tabButtons[next].focus();
  });

  navToggleEl.addEventListener("click", function () {
    if (phone.matches) {
      if (document.body.classList.contains("nav-open")) closeDrawer(); else openDrawer();
    } else {
      setCollapsed(!document.body.classList.contains("nav-collapsed"));
    }
  });

  backdropEl.addEventListener("click", closeDrawer);

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && document.body.classList.contains("nav-open")) closeDrawer();
  });

  // Crossing the phone breakpoint: the drawer never stays open, and the
  // collapsed rail only means something on a desktop.
  var onPhoneChange = function () { closeDrawer(); };
  if (typeof phone.addEventListener === "function") phone.addEventListener("change", onPhoneChange);
  else if (typeof phone.addListener === "function") phone.addListener(onPhoneChange);

  // Language switch. Each page reads the saved language from localStorage on
  // load (same origin, so the value is shared); the broadcast in i18n.js is
  // what updates the frames that are already open.
  [
    { el: document.getElementById("lang-zh-btn"), locale: "zh-CN" },
    { el: document.getElementById("lang-en-btn"), locale: "en" },
  ].forEach(function (item) {
    if (!item.el) return;
    item.el.addEventListener("click", function () {
      if (typeof window.setLocale === "function") window.setLocale(item.locale);
    });
  });

  document.addEventListener("locale-changed", syncChrome);

  window.addEventListener("hashchange", function () {
    activate(currentTabId());
  });

  if (readCollapsed()) document.body.classList.add("nav-collapsed");
  activate(currentTabId());

  // Accounts mode only: who is signed in, and a way out. In single-user mode
  // /api/auth/me answers {mode: "single"} and the chip stays hidden.
  fetch("/api/auth/me")
    .then(function (resp) { return resp.ok ? resp.json() : null; })
    .then(function (me) {
      if (!me || me.mode !== "accounts" || !me.user) return;
      document.getElementById("userName").textContent = me.user.nickname;
      // The teacher console is for admins; the server checks the role again.
      var adminTab = document.querySelector('[data-tab="admin"]');
      if (adminTab) adminTab.hidden = me.user.role !== "admin";
      document.getElementById("userChip").hidden = false;
      document.getElementById("logoutBtn").hidden = !me.user.id;  // the token admin has no session
      document.getElementById("logoutBtn").addEventListener("click", function () {
        fetch("/api/auth/logout", { method: "POST" }).then(function () { location.href = "/login"; });
      });
    })
    .catch(function () {});

  // Worlds (accounts mode only): which world every panel of this browser is
  // looking at. The choice is a server-side cookie, so switching reloads the
  // page and every iframe follows; the server re-checks access each request.
  var worldState = null;

  function postJson(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }).then(function (resp) {
      return resp.json().then(function (data) {
        if (!resp.ok) throw new Error(data.error || resp.status);
        return data;
      });
    });
  }

  function worldLabel(w) {
    return w.mine ? w.name : w.name + " · " + w.owner;
  }

  function renderWorlds() {
    if (!worldState) return;
    var select = document.getElementById("worldSelect");
    select.innerHTML = "";
    var shared = document.createElement("option");
    shared.value = "";
    shared.textContent = text("world.shared");
    select.appendChild(shared);
    worldState.worlds.forEach(function (w) {
      var option = document.createElement("option");
      option.value = w.id;
      option.textContent = worldLabel(w);
      select.appendChild(option);
    });
    var current = worldState.current;
    select.value = current ? current.id : "";
    var note = document.getElementById("worldCurrentNote");
    if (!current) {
      note.textContent = text(worldState.default_writable ? "world.shared_admin" : "world.shared_note");
    } else if (current.can_write) {
      note.textContent = current.name;
    } else {
      note.textContent = window.__f ? window.__f("world.readonly", { owner: current.owner }) : current.owner;
    }
    document.getElementById("worldOwnerControls").hidden = !(current && current.can_write);
    if (current) document.getElementById("worldVisibility").value = current.visibility;
    document.getElementById("worldChip").hidden = false;
  }

  function loadWorlds() {
    return fetch("/api/worlds")
      .then(function (resp) { return resp.ok ? resp.json() : null; })
      .then(function (data) {
        if (!data || data.mode !== "accounts") return;
        worldState = data;
        renderWorlds();
      });
  }

  function loadCities() {
    return fetch("/api/config")
      .then(function (resp) { return resp.ok ? resp.json() : { cities: [] }; })
      .then(function (cfg) {
        var select = document.getElementById("worldCity");
        select.innerHTML = "";
        var base = document.createElement("option");
        base.value = "";
        base.textContent = text("world.default_city");
        select.appendChild(base);
        (cfg.cities || []).filter(function (c) { return c.population > 0; }).forEach(function (c) {
          var option = document.createElement("option");
          option.value = c.slug;
          option.textContent = c.display_name + " · " + c.population;
          select.appendChild(option);
        });
      });
  }

  function worldError(err) {
    document.getElementById("worldError").textContent = err ? String(err.message || err) : "";
  }

  document.getElementById("worldSelect").addEventListener("change", function (event) {
    postJson("/api/worlds/select", { id: event.target.value }).then(function () { location.reload(); }, worldError);
  });
  // Distributed nodes (gaworld.cluster): other machines that run part of this
  // world's residents. The status refreshes while the dialog is open.
  var clusterTimer = null;

  function fmt(key, params) {
    return window.__f ? window.__f(key, params) : text(key);
  }

  function nodeLine(node) {
    var li = document.createElement("li");
    li.className = node.online ? "online" : "";
    var info = document.createElement("div");
    var title = document.createElement("strong");
    title.textContent = node.name;
    info.appendChild(title);
    var detail = document.createElement("small");
    var parts = [fmt("world.node_residents", { ids: node.agent_ids.join(", ") })];
    parts.push(node.online ? text("world.node_state_" + node.state) : text("world.node_offline"));
    if (node.sim_time) parts.push(fmt("world.node_at", { day: node.sim_day, time: node.sim_time }));
    if (node.error) parts.push(node.error);
    detail.textContent = parts.join(" · ");
    info.appendChild(detail);
    li.appendChild(info);
    var remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = text("world.node_remove");
    remove.addEventListener("click", function () {
      if (!window.confirm(fmt("world.node_remove_confirm", { name: node.name }))) return;
      postJson("/api/cluster/nodes/" + node.id + "/delete", {}).then(loadCluster, worldError);
    });
    li.appendChild(remove);
    return li;
  }

  function loadCluster() {
    var current = worldState && worldState.current;
    if (!current || !current.can_write) return Promise.resolve();
    document.getElementById("worldShareLink").value = location.origin + "/play/" + current.id;
    return fetch("/api/cluster")
      .then(function (resp) { return resp.ok ? resp.json() : null; })
      .then(function (data) {
        if (!data) return;
        var timeout = document.getElementById("worldSyncTimeout");
        if (document.activeElement !== timeout) timeout.value = data.sync_timeout_seconds;
        document.getElementById("worldHubLine").textContent = data.nodes.length
          ? fmt("world.hub_line", { ids: data.hub.agent_ids.join(", ") || "—" })
          : "";
        var list = document.getElementById("worldNodes");
        list.innerHTML = "";
        data.nodes.forEach(function (node) { list.appendChild(nodeLine(node)); });
      });
  }

  document.getElementById("worldManageBtn").addEventListener("click", function () {
    worldError(null);
    loadCities();
    if (worldState && worldState.current && worldState.current.can_write) {
      fetch("/api/config").then(function (resp) { return resp.json(); }).then(function (cfg) {
        document.getElementById("worldWait").value = (cfg.multiplayer || {}).wait_for_players_seconds || 0;
      });
      document.getElementById("worldNodeCommand").hidden = true;
      loadCluster();
      clearInterval(clusterTimer);
      clusterTimer = setInterval(loadCluster, 5000);
    }
    document.getElementById("worldDialog").showModal();
  });
  document.getElementById("worldDialog").addEventListener("close", function () {
    clearInterval(clusterTimer);
    clusterTimer = null;
  });
  document.getElementById("worldCloseBtn").addEventListener("click", function () {
    document.getElementById("worldDialog").close();
  });
  document.getElementById("worldShareLink").addEventListener("focus", function (event) {
    event.target.select();
  });
  document.getElementById("worldSyncTimeout").addEventListener("change", function (event) {
    postJson("/api/config", { cluster: { sync_timeout_seconds: Number(event.target.value) || 0 } })
      .then(function () { worldError(null); }, worldError);
  });
  document.getElementById("worldNodeAdd").addEventListener("click", function () {
    var button = document.getElementById("worldNodeAdd");
    button.disabled = true;
    postJson("/api/cluster/nodes", {
      name: document.getElementById("worldNodeName").value.trim(),
      agent_ids: document.getElementById("worldNodeAgents").value,
    }).then(function (data) {
      button.disabled = false;
      worldError(null);
      document.getElementById("worldNodeName").value = "";
      document.getElementById("worldNodeAgents").value = "";
      document.getElementById("worldNodeCommandText").textContent =
        "python -m gaworld.cluster join " + location.origin + " --token " + data.token;
      document.getElementById("worldNodeCommand").hidden = false;
      return loadCluster();
    }, function (err) {
      button.disabled = false;
      worldError(err);
    });
  });
  document.getElementById("worldCreateForm").addEventListener("submit", function (event) {
    event.preventDefault();
    var button = document.getElementById("worldCreateBtn");
    button.disabled = true;
    postJson("/api/worlds/create", {
      name: document.getElementById("worldName").value.trim(),
      city: document.getElementById("worldCity").value,
    }).then(function () { location.reload(); }, function (err) {
      button.disabled = false;
      worldError(err);
    });
  });
  document.getElementById("worldVisibility").addEventListener("change", function (event) {
    var current = worldState && worldState.current;
    if (!current) return;
    postJson("/api/worlds/" + current.id + "/visibility", { visibility: event.target.value })
      .then(loadWorlds, worldError);
  });
  document.getElementById("worldWait").addEventListener("change", function (event) {
    postJson("/api/config", { multiplayer: { wait_for_players_seconds: Number(event.target.value) || 0 } })
      .then(function () { worldError(null); }, worldError);
  });
  document.getElementById("worldDeleteBtn").addEventListener("click", function () {
    var current = worldState && worldState.current;
    if (!current || !window.confirm(text("world.delete_confirm"))) return;
    postJson("/api/worlds/" + current.id + "/delete", {}).then(function () { location.reload(); }, worldError);
  });
  document.addEventListener("locale-changed", renderWorlds);
  loadWorlds().catch(function () {});
})();
