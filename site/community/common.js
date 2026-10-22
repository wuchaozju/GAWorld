(function () {
  "use strict";
  var C = window.Community = {};
  C.user = null;
  C.world = null;
  C.esc = function (value) { return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };
  C.date = function (value) { if (!value) return ""; var d = new Date(typeof value === "number" ? value * 1000 : value); return isNaN(d.getTime()) ? "" : d.toLocaleDateString("zh-CN"); };
  C.api = async function (method, path, data) {
    var headers = { "Content-Type": "application/json" };
    if (method !== "GET" && C.world !== null) headers["X-GAWorld-World"] = C.world;
    var response = await fetch(path, { method: method, headers: headers, body: data === undefined ? undefined : JSON.stringify(data) });
    var result = await response.json();
    if (!response.ok) throw new Error(result.error || "请求失败");
    return result;
  };
  C.toast = function (message) { var node = document.getElementById("notice"); node.textContent = message; node.hidden = false; clearTimeout(C.toastTimer); C.toastTimer = setTimeout(function () { node.hidden = true; }, 5500); };
  C.error = function (error) { C.toast(error.message || String(error)); };
  C.empty = function (title, description) { return '<div class="empty"><h3>' + C.esc(title) + '</h3><p>' + C.esc(description || "") + '</p></div>'; };
  C.status = { plan: "研究方案", completed: "已完成", partial: "部分结果", failed: "运行失败" };
  C.kind = { plan: "研究方案", study: "研究报告", simulation: "仿真案例" };
  C.author = function (author) { return '<a href="/people/' + encodeURIComponent(author.public_id || "") + '">' + C.esc(author.display_name || "研究者") + '</a>'; };
  C.card = function (p) { return '<article class="card"><div><span class="status">' + C.esc(C.status[p.result_status] || "方案") + '</span><span class="muted hint">' + C.esc(C.kind[p.kind]) + ' · v' + Number(p.version) + '</span></div><h3><a href="/publications/' + encodeURIComponent(p.id) + '">' + C.esc(p.title) + '</a></h3><p class="summary">' + C.esc(p.summary || p.body.slice(0, 200)) + '</p><div class="tags">' + (p.tags || []).map(function (t) { return '<a class="tag" href="/explore?tag=' + encodeURIComponent(t) + '">' + C.esc(t) + '</a>'; }).join("") + '</div><div class="card-footer">' + C.author(p.author || {}) + '<span>' + C.date(p.published_at) + '</span></div></article>'; };
  C.loginRequired = function () { if (C.user) return true; location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search); return false; };
  C.ready = C.api("GET", "/api/auth/me").then(function (me) {
    C.user = me.user || null;
    var nav = document.getElementById("accountNav");
    if (C.user) {
      nav.innerHTML = '<a href="/workspace?view=notifications">消息</a><a href="/workspace?view=account">' + C.esc(C.user.display_name || C.user.nickname) + '</a>';
    } else {
      nav.innerHTML = '<a href="/login">登录</a><a class="button compact" href="/register">注册</a>';
    }
    return me;
  }).catch(function (error) { C.error(error); return {}; });
})();
