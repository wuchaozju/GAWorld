// Unified console shell: hosts the GAWorld apps as tabs.
// Each app is an independent same-origin page loaded in its own iframe. Frames
// are created on first visit and kept alive (hidden, not destroyed) so each app
// preserves its state when you switch away and back.
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
    { id: "collaboration", src: "/site/dashboard/collaboration.html" },
    { id: "external", src: "/site/dashboard/external.html" },
    { id: "settings", src: "/site/dashboard/settings.html" },
    { id: "docs", src: "/site/dashboard/docs.html" },
  ];

  var framesEl = document.getElementById("frames");
  var openNewEl = document.getElementById("openNew");
  var tabButtons = Array.prototype.slice.call(document.querySelectorAll(".tab"));
  var frames = {}; // id -> iframe element (lazily created)

  function tabById(id) {
    for (var i = 0; i < TABS.length; i++) {
      if (TABS[i].id === id) return TABS[i];
    }
    return null;
  }

  function ensureFrame(tab) {
    if (frames[tab.id]) return frames[tab.id];
    var iframe = document.createElement("iframe");
    iframe.src = tab.src;
    iframe.title = tab.id;
    iframe.hidden = true;
    framesEl.appendChild(iframe);
    frames[tab.id] = iframe;
    return iframe;
  }

  // Language switch. Each page reads the saved language from localStorage on
  // load (same origin, so the value is shared); the broadcast below is what
  // updates the frames that are already open.
  function initLangSwitch() {
    var buttons = [
      { el: document.getElementById("lang-zh-btn"), locale: "zh-CN" },
      { el: document.getElementById("lang-en-btn"), locale: "en" },
    ];
    buttons.forEach(function (item) {
      if (!item.el) return;
      item.el.addEventListener("click", function () {
        if (typeof window.setLocale === "function") window.setLocale(item.locale);
      });
    });
  }

  function activate(id) {
    var tab = tabById(id) || TABS[0];
    ensureFrame(tab);
    Object.keys(frames).forEach(function (key) {
      frames[key].hidden = key !== tab.id;
    });
    tabButtons.forEach(function (btn) {
      btn.classList.toggle("is-active", btn.dataset.tab === tab.id);
      btn.setAttribute("aria-selected", btn.dataset.tab === tab.id ? "true" : "false");
    });
    openNewEl.setAttribute("href", tab.src);
    document.title = "GAWorld Console · " + tab.id;
  }

  function currentTabId() {
    var id = (location.hash || "").replace(/^#/, "");
    return tabById(id) ? id : TABS[0].id;
  }

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

  window.addEventListener("hashchange", function () {
    activate(currentTabId());
  });

  initLangSwitch();
  activate(currentTabId());
})();
