/* A page keeps its initial world; a cookie change in another tab must not retarget its writes. */
(function () {
  'use strict';
  if (window.__gaworldContextGuard) return;
  window.__gaworldContextGuard = true;
  var original = window.fetch.bind(window), world = null;
  var ready = original('/api/worlds').then(function (r) { if (!r.ok) throw new Error('世界上下文读取失败，请刷新页面'); return r.json(); }).then(function (data) { if (!data || !['single','accounts'].includes(data.mode)) throw new Error('世界上下文无效，请刷新页面'); if (data.mode === 'accounts') world = (data.current || {}).id || ''; });
  ready.catch(function () {});
  window.fetch = async function (input, init) {
    var url = new URL(input instanceof URL || typeof input === 'string' ? input : input.url, location.href), opts = init || {};
    if (window.GAWorldURL) url.pathname = window.GAWorldURL.path(url.pathname);
    var method = String(opts.method || (typeof input === 'object' && input.method) || 'GET').toUpperCase();
    if (method !== 'GET' && method !== 'HEAD' && url.origin === location.origin && url.pathname.startsWith('/api/') && !url.pathname.startsWith('/api/auth/')) {
      await ready;
      if (world !== null && !url.pathname.startsWith('/api/auth/')) {
        var headers = new Headers(opts.headers || (typeof input === 'object' && input.headers) || {});
        if (!headers.has('X-GAWorld-World')) headers.set('X-GAWorld-World', world);
        opts = Object.assign({}, opts, { headers: headers });
      }
    }
    return original(input, opts);
  };
})();
