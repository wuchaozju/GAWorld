(function () {
  "use strict";
  var key = "gaworld.theme";
  var media = window.matchMedia("(prefers-color-scheme: dark)");
  var mode = "system";
  function normalize(value) {
    return value === "dark" || value === "light" ? value : "system";
  }
  function read() {
    try { return normalize(localStorage.getItem(key)); }
    catch (_) { return "system"; }
  }
  function apply(value) {
    mode = normalize(value);
    var theme = mode === "system" ? (media.matches ? "dark" : "light") : mode;
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    var control = document.getElementById("themeMode");
    if (control) control.value = mode;
  }
  function set(value) {
    var next = normalize(value);
    try { localStorage.setItem(key, next); } catch (_) { /* Storage may be disabled. */ }
    apply(next);
  }
  apply(read());
  window.GAWorldTheme = { get: function () { return mode; }, set: set };
  media.addEventListener("change", function () { if (mode === "system") apply(mode); });
  window.addEventListener("storage", function (event) {
    if (event.key === key || event.key === null) apply(read());
  });
  document.addEventListener("DOMContentLoaded", function () {
    apply(mode);
    var control = document.getElementById("themeMode");
    if (control) control.addEventListener("change", function () { set(control.value); });
  });
})();
