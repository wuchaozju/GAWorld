/* Shared URL mapping: old share links and personal pages reuse the console shell. */
(function (root) {
  'use strict';
  var views = {overview:'workspace', research:'myresearch', worlds:'myworlds', publish:'publish', publications:'publications', bookmarks:'bookmarks', notifications:'notifications', account:'account', moderation:'moderation'};
  var tabs = Object.keys(views).map(function (view) {
    return {id:views[view], src:'/workspace' + (view === 'overview' ? '' : '?view=' + view), personal:true};
  }).concat([{id:'explore',src:'/explore'}, {id:'plaza',src:'/plaza'}]);
  function query(params) { var q = params.toString(); return q ? '?' + q : ''; }
  function consoleUrl(path) {
    if (!/^\/(?![\/\\])/.test(path) || /[\u0000-\u0020\\]/.test(path)) return null;
    var url = new URL(path, 'http://console.local'), params = url.searchParams, id, detail = '';
    params.delete('embedded');
    if (url.pathname === '/console') return url.pathname + url.search + url.hash;
    if (url.pathname === '/workspace' || url.pathname === '/site/community/workspace.html') { id = views[params.get('view')] || 'workspace'; params.delete('view'); }
    else if (url.pathname === '/explore' || url.pathname === '/plaza') id = url.pathname.slice(1);
    else if (/^\/(publications|people|posts)\/[A-Za-z0-9_-]+$/.test(url.pathname)) {
      id = url.pathname.startsWith('/posts/') ? 'plaza' : 'explore'; detail = url.pathname;
    } else if (url.pathname === '/site/dashboard/research.html') id = 'research';
    else if (url.pathname === '/site/dashboard/analytics.html' || url.pathname === '/site/simviz/index.html') id = 'analytics';
    else return null;
    if (url.hash) params.set('anchor', url.hash.slice(1));
    return '/console#' + id + detail + query(params);
  }
  function resolve(hash, allTabs) {
    var split = String(hash || '').replace(/^#/, '').split('?'), route = split.shift(), params = new URLSearchParams(split.join('?'));
    if (route === 'worlds') { route = 'research'; params.set('tab', 'worlds'); }
    if (route === 'simviz') route = 'analytics';
    var parts = route.split('/'), id = parts.shift(), tab = allTabs.find(function (t) { return t.id === id; });
    if (!tab || (parts.length && !((id === 'explore' && /^(publications|people)\/[A-Za-z0-9_-]+$/.test(parts.join('/'))) || (id === 'plaza' && /^posts\/[A-Za-z0-9_-]+$/.test(parts.join('/')))))) return allTabs[0];
    var src = new URL(parts.length ? '/' + parts.join('/') : tab.src, 'http://console.local');
    var anchor = params.get('anchor'); params.delete('anchor');
    // Personal tab identity owns its view, never an arbitrary query parameter.
    params.delete('embedded');
    if (tab.personal) params.delete('view');
    params.forEach(function (v,k) { src.searchParams.set(k,v); });
    return {id:id, src:src.pathname + src.search + (anchor ? '#' + encodeURIComponent(anchor) : ''), personal:tab.personal};
  }
  var api = {tabs:tabs, consoleUrl:consoleUrl, resolve:resolve};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.GAWorldNavigation = api;
})(typeof window !== 'undefined' ? window : globalThis);
