/*
 * 教师控制台 (Teacher Console): limits, invite codes, roster and usage, every
 * world, class-wide events, audit. Admins only -- the console shows the tab to
 * admins, and every endpoint used here checks the role again on the server.
 */
(function () {
  "use strict";

  var ONLINE_SECONDS = 120;
  var REFRESH_MS = 15000;

  var $ = function (id) { return document.getElementById(id); };
  var t = function (key, fallback) {
    var value = typeof window.__ === "function" ? window.__(key) : key;
    return value === key ? fallback : value;
  };

  function api(method, url, body) {
    return fetch(url, {
      method: method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (resp) {
      return resp.json().then(function (data) {
        if (!resp.ok) throw new Error(data.error || resp.status);
        return data;
      });
    });
  }

  function say(text, isError) {
    var el = $("aMsg");
    el.textContent = text || "";
    el.className = "admin-msg" + (isError ? " error" : "");
  }
  var fail = function (err) { say(String(err.message || err), true); };

  function cell(row, content) {
    var td = document.createElement("td");
    if (content instanceof Node) td.appendChild(content);
    else td.textContent = content == null ? "" : String(content);
    row.appendChild(td);
    return td;
  }

  function button(label, onClick) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "button small";
    b.textContent = label;
    b.addEventListener("click", onClick);
    return b;
  }

  function day(ts) {
    return ts ? new Date(ts * 1000).toLocaleString() : "";
  }

  function download(name, text) {
    var link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  // -- limits ---------------------------------------------------------------

  function loadLimits() {
    return api("GET", "/api/worlds/settings").then(function (data) {
      $("aMaxRuns").value = data.limits.max_concurrent_runs;
      $("aMaxPerUser").value = data.limits.max_runs_per_user;
      $("aQuota").value = data.limits.daily_llm_calls_per_user;
    });
  }

  $("aLimitsSave").addEventListener("click", function () {
    api("POST", "/api/worlds/settings", {
      max_concurrent_runs: Number($("aMaxRuns").value),
      max_runs_per_user: Number($("aMaxPerUser").value),
      daily_llm_calls_per_user: Number($("aQuota").value),
    }).then(function () { say(t("admin.saved", "已保存")); }, fail);
  });

  // -- invites --------------------------------------------------------------

  function loadInvites() {
    return api("GET", "/api/auth/invites").then(function (data) {
      var body = $("aInviteRows");
      body.innerHTML = "";
      data.invites.forEach(function (inv) {
        var row = document.createElement("tr");
        cell(row, inv.label || "—");
        cell(row, inv.used_by ? t("admin.used_by", "已被使用：") + inv.used_by
          : inv.expires_at < Date.now() / 1000 ? t("admin.expired", "已过期") : t("admin.unused", "未使用"));
        cell(row, day(inv.expires_at));
        cell(row, inv.used_by ? "" : button(t("admin.revoke", "作废"), function () {
          api("POST", "/api/auth/invites/" + inv.id + "/revoke", {}).then(loadInvites, fail);
        }));
        body.appendChild(row);
      });
    });
  }

  $("aInvite").addEventListener("click", function () {
    api("POST", "/api/auth/invites", {
      count: Number($("aCount").value),
      label: $("aLabel").value.trim(),
      expires_days: Number($("aExpires").value),
      can_create_city: $("aCanCity").checked,
    }).then(function (data) {
      var base = location.origin + "/join?code=";
      $("aCodes").textContent = data.codes.map(function (code) { return base + code; }).join("\n");
      $("aCodes").hidden = false;
      return loadInvites();
    }, fail);
  });

  // -- roster ---------------------------------------------------------------

  function loadUsers() {
    return api("GET", "/api/auth/usage").then(function (data) {
      var body = $("aUsers");
      body.innerHTML = "";
      var now = Date.now() / 1000;
      data.users.forEach(function (u) {
        var row = document.createElement("tr");
        var name = document.createElement("span");
        var dot = document.createElement("span");
        dot.className = "dot" + (u.last_seen && now - u.last_seen < ONLINE_SECONDS ? " on" : "");
        name.appendChild(dot);
        name.appendChild(document.createTextNode(u.nickname + (u.role === "admin" ? " ★" : "")));
        cell(row, name);
        cell(row, u.label || "—");
        cell(row, u.today + " / " + u.total);
        var box = document.createElement("input");
        box.type = "checkbox";
        box.checked = !!u.can_create_city;
        box.disabled = u.role === "admin";
        box.addEventListener("change", function () {
          api("POST", "/api/auth/users/" + u.id + "/city", { allow: box.checked }).catch(fail);
        });
        cell(row, box);
        cell(row, button(t("admin.reset", "重置密码"), function () {
          api("POST", "/api/auth/users/" + u.id + "/reset", {}).then(function (res) {
            $("aCodes").textContent = u.nickname + " · " + location.origin + "/reset?code=" + res.code;
            $("aCodes").hidden = false;
            say(t("admin.reset_note", "重置链接 24 小时内有效，只显示这一次。"));
          }, fail);
        }));
        body.appendChild(row);
      });
    });
  }

  // -- worlds and broadcast -------------------------------------------------

  var worldList = [];

  function loadWorlds() {
    return api("GET", "/api/worlds").then(function (data) {
      worldList = data.worlds || [];
      var body = $("aWorlds");
      body.innerHTML = "";
      worldList.forEach(function (w) {
        var row = document.createElement("tr");
        cell(row, w.name);
        cell(row, w.owner);
        cell(row, w.city || t("admin.default_pop", "默认人口"));
        cell(row, t("world.vis_" + w.visibility, w.visibility).split(/[：:]/)[0]);
        cell(row, w.running ? t("admin.running", "运行中")
          : w.queued ? t("admin.queued", "排队第 ") + w.queued : "—");
        cell(row, w.calls_today);
        var actions = document.createElement("span");
        if (w.running || w.queued) {
          actions.appendChild(button(t("admin.stop", "停止"), function () {
            api("POST", "/api/worlds/" + w.id + "/stop", {}).then(loadWorlds, fail);
          }));
        }
        actions.appendChild(button(t("admin.export", "导出共玩记录"), function () {
          api("GET", "/api/worlds/" + w.id + "/trail").then(function (res) { download(res.filename, res.markdown); }, fail);
        }));
        cell(row, actions);
        body.appendChild(row);
      });
      renderTargets();
    });
  }

  function renderTargets() {
    var box = $("aTargets");
    var checked = {};
    box.querySelectorAll("input:checked").forEach(function (el) { checked[el.value] = true; });
    box.innerHTML = "";
    [{ id: "", name: t("world.shared", "共享世界（默认）") }].concat(worldList).forEach(function (w) {
      var label = document.createElement("label");
      var input = document.createElement("input");
      input.type = "checkbox";
      input.value = w.id;
      input.checked = !!checked[w.id];
      label.appendChild(input);
      label.appendChild(document.createTextNode(" " + w.name + (w.owner ? " · " + w.owner : "")));
      box.appendChild(label);
    });
  }

  $("aBroadcast").addEventListener("click", function () {
    var ids = [];
    $("aTargets").querySelectorAll("input:checked").forEach(function (el) { ids.push(el.value); });
    if (!ids.length) { say(t("admin.pick_worlds", "先勾选至少一个世界"), true); return; }
    api("POST", "/api/worlds/broadcast", {
      world_ids: ids,
      title: $("aTitle").value.trim(),
      description: $("aDesc").value.trim(),
      severity: Number($("aSeverity").value),
    }).then(function (data) {
      var ok = data.results.filter(function (r) { return r.ok; });
      var live = ok.filter(function (r) { return r.running; });
      say(t("admin.broadcast_done", "已广播到 ") + ok.length + t("admin.worlds_unit", " 个世界") +
        "（" + t("admin.live_now", "其中运行中 ") + live.length + "）");
      return loadAudit();
    }, fail);
  });

  // -- audit ----------------------------------------------------------------

  function loadAudit() {
    return api("GET", "/api/auth/audit").then(function (data) {
      var body = $("aAudit");
      body.innerHTML = "";
      data.audit.slice(0, 50).forEach(function (a) {
        var row = document.createElement("tr");
        cell(row, day(a.at));
        cell(row, a.nickname || "—");
        cell(row, a.action);
        cell(row, a.detail);
        body.appendChild(row);
      });
    });
  }

  function refresh() {
    return Promise.all([loadUsers(), loadWorlds()]).catch(fail);
  }

  Promise.all([loadLimits(), loadInvites(), refresh(), loadAudit()]).catch(fail);
  setInterval(refresh, REFRESH_MS);
  document.addEventListener("locale-changed", function () { refresh(); loadInvites(); });
})();
