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
    { id: "worlds", src: "/site/dashboard/worlds.html" },
    { id: "analytics", src: "/site/dashboard/analytics.html" },
    { id: "studio", src: "/site/dashboard/studio.html" },
    { id: "population", src: "/site/dashboard/population.html" },
    { id: "survey", src: "/site/dashboard/survey.html" },
    { id: "research", src: "/site/dashboard/research.html" },
    { id: "collaboration", src: "/site/dashboard/collaboration.html" },
    { id: "games", src: "/site/dashboard/games.html" },
    { id: "external", src: "/site/dashboard/external.html" },
    { id: "settings", src: "/site/dashboard/settings.html" },
    { id: "docs", src: "/site/dashboard/docs.html" },
  ];

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
})();
