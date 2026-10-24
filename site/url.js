/* The script's own served URL identifies the mount; never trust URL query parameters. */
(function (root) {
  "use strict";
  if (root.GAWorldURL) return;
  var script = document.currentScript;
  var scriptPath = script ? new URL(script.src, location.href).pathname : "/site/url.js";
  var suffix = "/site/url.js";
  var prefix = scriptPath.endsWith(suffix) ? scriptPath.slice(0, -suffix.length) : "";
  if (prefix && !/^(\/[A-Za-z0-9_-]+)+$/.test(prefix)) throw new Error("Invalid GAWorld mount");

  function path(value) {
    if (!prefix || typeof value !== 'string') return value;
    var pathname = value.split(/[?#]/, 1)[0];
    if (pathname !== prefix && !pathname.startsWith(prefix + '/')) return value;
    var rest = value.slice(prefix.length);
    return rest.startsWith('/') ? rest : '/' + rest;
  }

  function url(value) {
    if (!prefix || value == null || (typeof value !== 'string' && !(value instanceof URL))) return value;
    var text = String(value);
    if (!text || text.startsWith('#') || text.startsWith('?')) return value;
    var parsed;
    try { parsed = new URL(text, location.href); } catch (_) { return value; }
    if (parsed.origin !== location.origin || !/^https?:$/.test(parsed.protocol)) return value;
    if (path(parsed.pathname) !== parsed.pathname) return value;
    parsed.pathname = prefix + parsed.pathname;
    return /^https?:\/\//i.test(text) || text.startsWith('//') ? parsed.href : parsed.pathname + parsed.search + parsed.hash;
  }

  function html(value) {
    if (!prefix || !value) return value;
    var template = document.createElement("template");
    template.innerHTML = value;
    var attributes = ["href", "src", "action", "formaction", "poster", "data", "xlink:href"];
    template.content.querySelectorAll("*").forEach(function (element) {
      attributes.forEach(function (name) {
        if (element.hasAttribute(name)) element.setAttribute(name, url(element.getAttribute(name)));
      });
    });
    return template.innerHTML;
  }

  root.GAWorldURL = { prefix: prefix, url: url, html: html, path: path };
  if (prefix && typeof root.fetch === "function") {
    var original = root.fetch.bind(root);
    root.fetch = function (input, init) {
      var request = typeof Request !== "undefined" && input instanceof Request;
      var before = request ? input.url : input;
      var after = url(before);
      if (request && after !== before) input = new Request(after, input);
      else if (!request) input = after;
      return original(input, init);
    };
  }
})(globalThis);
