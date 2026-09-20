/**
 * GAWorld i18n — lightweight vanilla-JS internationalization.
 *
 * Supports English (en) and Chinese (zh-CN) via JSON locale files.
 * No dependencies, no build step.
 *
 * The console shell (/site/console/) owns the language switcher and broadcasts
 * changes to every hosted iframe via postMessage. Because all pages are
 * same-origin they also share localStorage, so a page loaded later picks up the
 * saved language on its own without waiting for a broadcast.
 *
 * Markup hooks:
 *   data-i18n            -> textContent
 *   data-i18n-placeholder-> placeholder
 *   data-i18n-title      -> title
 *   data-i18n-content    -> content attribute (meta tags)
 *   data-i18n-help       -> data-help attribute (help-tip tooltips)
 *   data-i18n-aria       -> aria-label
 *   data-i18n-empty      -> data-empty attribute (CSS-rendered placeholder text)
 *
 * Note: data-i18n replaces the element's entire textContent, so an element that
 * also holds children (a help-tip, a badge) must keep its text in its own
 * <span data-i18n="...">.
 */
(function () {
  "use strict";

  const STORAGE_KEY = "gaworld-lang";
  const MESSAGE_TYPE = "gaworld-locale";
  const DEFAULT_LOCALE = "zh-CN";
  const LOCALE_MAP = { en: "en", zh: "zh-CN", "zh-CN": "zh-CN" };

  let currentLocale = null;
  let translations = {};

  function normalize(locale) {
    return LOCALE_MAP[locale] || DEFAULT_LOCALE;
  }

  function storageAvailable() {
    try {
      const k = "__test__";
      localStorage.setItem(k, "1");
      localStorage.removeItem(k);
      return true;
    } catch (_) {
      return false;
    }
  }

  function savedLocale() {
    return storageAvailable() ? localStorage.getItem(STORAGE_KEY) : null;
  }

  async function loadLocale(locale) {
    const url = "/site/dashboard/locales/" + locale + ".json";
    const resp = await fetch(url);
    if (!resp.ok) throw new Error("Failed to load locale: " + url);
    return resp.json();
  }

  window.__ = function (key) {
    if (translations[key] !== undefined) return translations[key];
    return key;
  };

  window.__f = function (key, params) {
    var t = window.__(key);
    if (params) {
      for (var k in params) {
        if (params.hasOwnProperty(k)) {
          t = t.split("{" + k + "}").join(String(params[k]));
        }
      }
    }
    return t;
  };

  /**
   * Switch language. `broadcast` is false when the change arrived from the
   * console shell, so an iframe never echoes it back into a loop.
   */
  window.setLocale = async function (locale, broadcast) {
    var code = normalize(locale);
    if (code === currentLocale) return;
    try {
      var data = await loadLocale(code);
      translations = data;
      currentLocale = code;
      if (storageAvailable()) {
        localStorage.setItem(STORAGE_KEY, code);
      }
      applyTranslations();
      if (broadcast !== false) broadcastLocale(code);
      document.dispatchEvent(new CustomEvent("locale-changed", { detail: { locale: code } }));
    } catch (err) {
      console.error("i18n: Failed to set locale", err);
    }
  };

  window.getLocale = function () {
    return currentLocale;
  };

  /** Push the locale to hosted iframes (shell) and to the parent (page). */
  function broadcastLocale(code) {
    var msg = { type: MESSAGE_TYPE, locale: code };
    try {
      document.querySelectorAll("iframe").forEach(function (frame) {
        if (frame.contentWindow) frame.contentWindow.postMessage(msg, location.origin);
      });
    } catch (_) { /* no frames */ }
    if (window.parent && window.parent !== window) {
      try {
        window.parent.postMessage(msg, location.origin);
      } catch (_) { /* cross-origin parent */ }
    }
  }
  window.broadcastLocale = broadcastLocale;

  function applyAttr(selector, apply) {
    document.querySelectorAll("[" + selector + "]").forEach(function (el) {
      var key = el.getAttribute(selector);
      if (!key) return;
      var t = window.__(key);
      if (t !== key) apply(el, t);
    });
  }

  window.applyTranslations = function () {
    if (currentLocale) {
      document.documentElement.setAttribute("lang", currentLocale);
    }
    applyAttr("data-i18n", function (el, t) { el.textContent = t; });
    applyAttr("data-i18n-placeholder", function (el, t) { el.placeholder = t; });
    applyAttr("data-i18n-title", function (el, t) { el.title = t; });
    applyAttr("data-i18n-content", function (el, t) { el.setAttribute("content", t); });
    applyAttr("data-i18n-help", function (el, t) { el.setAttribute("data-help", t); });
    applyAttr("data-i18n-aria", function (el, t) { el.setAttribute("aria-label", t); });
    // data-empty is rendered by CSS (content: attr(data-empty)) as placeholder text.
    applyAttr("data-i18n-empty", function (el, t) { el.setAttribute("data-empty", t); });

    var enBtn = document.getElementById("lang-en-btn");
    var zhBtn = document.getElementById("lang-zh-btn");
    if (enBtn && zhBtn) {
      enBtn.classList.toggle("is-active", currentLocale === "en");
      zhBtn.classList.toggle("is-active", currentLocale === "zh-CN");
      enBtn.setAttribute("aria-pressed", currentLocale === "en" ? "true" : "false");
      zhBtn.setAttribute("aria-pressed", currentLocale === "zh-CN" ? "true" : "false");
    }
  };

  window.addEventListener("message", function (event) {
    if (event.origin !== location.origin) return;
    var data = event.data;
    if (!data || data.type !== MESSAGE_TYPE || !data.locale) return;
    window.setLocale(data.locale, false);
  });

  async function init() {
    var initial = normalize(savedLocale() || DEFAULT_LOCALE);
    try {
      var data = await loadLocale(initial);
      translations = data;
      currentLocale = initial;
    } catch (_) {
      currentLocale = DEFAULT_LOCALE;
      translations = {};
    }
    applyTranslations();
    document.dispatchEvent(new CustomEvent("locale-changed", { detail: { locale: currentLocale } }));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
