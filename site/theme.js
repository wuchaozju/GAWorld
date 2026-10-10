/* Shared appearance: apply before CSS paints, then mount accessible controls. */
(function () {
  "use strict";
  const key = "gaworld-theme";
  const root = document.documentElement;
  const origin = window.location.origin;
  const valid = (value) => value === "light" || value === "dark";
  let theme = "light";
  try {
    const saved = localStorage.getItem(key);
    if (valid(saved)) theme = saved;
  } catch (_) { /* Private browsing may disable storage. */ }

  function labels() {
    const english = root.lang === "en" || (window.getLocale && window.getLocale() === "en");
    document.querySelectorAll(".theme-switch").forEach((group) => {
      group.setAttribute("aria-label", english ? "Appearance" : "外观模式");
      group.querySelectorAll("[data-theme-choice]").forEach((button) => {
        const mode = button.dataset.themeChoice;
        button.setAttribute("aria-pressed", String(mode === theme));
        button.querySelector("span").textContent = english
          ? (mode === "light" ? "Light" : "Dark") : (mode === "light" ? "浅色" : "深色");
      });
    });
  }
  function apply() {
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
    labels();
  }
  function broadcast() {
    const message = { type: key, theme };
    document.querySelectorAll("iframe").forEach((frame) => {
      if (frame.contentWindow) frame.contentWindow.postMessage(message, origin);
    });
    if (window.parent !== window) window.parent.postMessage(message, origin);
  }
  function set(value, persist = true) {
    if (!valid(value)) return;
    if (persist) {
      try { localStorage.setItem(key, value); } catch (_) { /* Switching still works. */ }
    }
    if (theme === value) return;
    theme = value;
    apply();
    broadcast();
    document.dispatchEvent(new CustomEvent("theme-changed", { detail: { theme } }));
  }
  window.GAWorldTheme = { set, get: () => theme };
  apply();
  window.addEventListener("storage", (event) => {
    if (event.key === key || event.key === null) set(valid(event.newValue) ? event.newValue : "light", false);
  });
  window.addEventListener("message", (event) => {
    if (event.origin !== origin || !event.data) return;
    if (event.data.type === key) set(event.data.theme, false);
    if (event.data.type === "gaworld-theme-request" && event.source) {
      event.source.postMessage({ type: key, theme }, origin);
    }
  });
  document.addEventListener("locale-changed", labels);
  function mount() {
    if (window.top !== window) {
      window.parent.postMessage({ type: "gaworld-theme-request" }, origin);
      return;
    }
    const group = document.createElement("div");
    group.className = "theme-switch";
    group.setAttribute("role", "group");
    for (const mode of ["light", "dark"]) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.themeChoice = mode;
      const icon = mode === "light"
        ? '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>'
        : '<path d="M20 14a8 8 0 0 1-10-10 8 8 0 1 0 10 10Z"/>';
      button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' + icon + '</svg><span></span>';
      button.addEventListener("click", () => set(mode));
      group.appendChild(button);
    }
    const host = [".bar-right", ".topbar-inner", ".studio-top", ".hero-status", ".masthead", ".topbar"]
      .map((selector) => document.querySelector(selector)).find(Boolean);
    if (host) host.appendChild(group);
    else {
      group.classList.add("theme-switch-floating");
      document.body.appendChild(group);
    }
    labels();
    broadcast();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
