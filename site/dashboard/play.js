/*
 * 多人共玩 (Play Together): claim a resident of the open world this browser is
 * in, send what it does next / says to someone, watch everybody's moves live.
 *
 * Server: /api/play (gaworld/apps/play_api.py). The claim is a two-minute
 * lease; this page renews it every 30 s and lets go when it is closed. The
 * live feed is the world's record stream (/api/events/stream). In a
 * distributed world (gaworld.cluster) a resident may run on another machine;
 * its records reach the same stream, so nothing here changes.
 */
(function () {
  "use strict";

  var HEARTBEAT_MS = 30000;
  var REFRESH_MS = 5000;
  var TABLES = "multiplayer.act,multiplayer.say,multiplayer.presence,agent.step";

  var $ = function (id) { return document.getElementById(id); };
  var t = function (key, fallback) {
    var value = typeof window.__ === "function" ? window.__(key) : key;
    return value === key ? fallback : value;
  };
  var tf = function (key, fallback, params) {
    var text = t(key, fallback);
    Object.keys(params || {}).forEach(function (name) {
      text = text.split("{" + name + "}").join(params[name]);
    });
    return text;
  };

  var residents = [];
  var play = null;
  var feedEmpty = true;
  var lastStep = null;

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

  function status(text, isError) {
    var el = $("pStatus");
    el.textContent = text;
    el.style.color = isError ? "#b3261e" : "";
  }

  function nameOf(id) {
    var found = residents.find(function (r) { return Number(r.id) === Number(id); });
    return found ? found.name : "#" + id;
  }

  function render() {
    if (!play) return;
    var taken = {};
    play.claims.forEach(function (c) { taken[c.agent_id] = c; });
    var query = $("pSearch").value.trim();
    var list = $("pResidents");
    list.innerHTML = "";
    residents
      .filter(function (r) { return !query || String(r.name).indexOf(query) >= 0 || String(r.id) === query; })
      .forEach(function (r) {
        var claim = taken[r.id];
        var row = document.createElement("div");
        row.className = "play-row" + (claim ? (claim.mine ? " mine" : " taken") : "");
        var label = document.createElement("span");
        label.textContent = r.name + " ";
        var note = document.createElement("small");
        note.textContent = "#" + r.id + " · " + (claim
          ? (claim.mine ? t("play.you", "你在扮演") : tf("play.played_by", "由 {player} 扮演", { player: claim.player }))
          : t("play.free", "空闲"));
        label.appendChild(note);
        row.appendChild(label);
        if (!claim) {
          var button = document.createElement("button");
          button.className = "button small";
          button.type = "button";
          button.textContent = t("play.claim", "认领");
          button.addEventListener("click", function () { claimResident(r.id); });
          row.appendChild(button);
        }
        list.appendChild(row);
      });

    var mine = play.mine;
    $("pControls").hidden = mine == null;
    if (mine == null || (lastStep && Number(lastStep.agent_id) !== Number(mine))) {
      lastStep = null;
      $("pNow").hidden = true;
    }
    $("pMine").textContent = mine == null ? t("play.none", "还没有认领居民：在居民列表里挑一位。") : nameOf(mine) + " · #" + mine;
    var select = $("pSayTo");
    var keep = select.value;
    select.innerHTML = "";
    residents.forEach(function (r) {
      if (Number(r.id) === Number(mine)) return;
      var option = document.createElement("option");
      option.value = r.id;
      option.textContent = r.name + " · #" + r.id;
      select.appendChild(option);
    });
    if (keep) select.value = keep;
    status(tf("play.world", "世界：{name}", { name: play.world.name }) + " · " +
      (play.running ? t("play.status_running", "仿真运行中，行动在下一个 tick 生效")
                    : t("play.status_stopped", "仿真没有在运行：可以先认领，行动要等仿真运行后才生效")));
  }

  function refresh() {
    return api("GET", "/api/play").then(function (data) {
      play = data;
      $("pBoard").hidden = false;
      $("pFeedPanel").hidden = false;
      render();
    }, function (err) {
      play = null;
      $("pBoard").hidden = true;
      $("pFeedPanel").hidden = true;
      status(String(err.message || err), true);
    });
  }

  function claimResident(id) {
    api("POST", "/api/play/claim", { agent_id: id }).then(refresh, function (err) { status(err.message, true); });
  }

  function heartbeat() {
    if (play && play.mine != null) {
      api("POST", "/api/play/claim", { agent_id: play.mine }).catch(function (err) { status(err.message, true); });
    }
  }

  // What my resident is doing right now: its latest step in the record stream.
  function showStep(row) {
    if (!play || play.mine == null || Number(row.agent_id) !== Number(play.mine)) return;
    lastStep = row;
    var box = $("pNow");
    box.innerHTML = "";
    var when = document.createElement("time");
    when.textContent = "D" + row._day + " " + (row._time || "");
    box.appendChild(when);
    box.appendChild(document.createTextNode(tf("play.now", "在{location}：{activity}", {
      location: row.location || "—",
      activity: row.action && row.action !== row.activity ? row.activity + "（" + row.action + "）" : row.activity || "",
    })));
    box.hidden = false;
  }

  function addFeed(row, table) {
    if (table === "agent.step") return showStep(row);
    var text;
    if (table === "multiplayer.act") {
      text = tf("play.ev_act", "{player}（{name}）：{text}", { player: row.player, name: row.agent_name, text: row.text });
    } else if (table === "multiplayer.say") {
      text = tf("play.ev_say", "{player}（{name}）对 {target} 说：{text}",
        { player: row.player, name: row.agent_name, target: row.target_name, text: row.text });
    } else {
      var key = { claim: "play.ev_claim", release: "play.ev_release", lapse: "play.ev_lapse" }[row.event];
      if (!key) return;
      var fallback = { claim: "{player} 开始扮演 {name}", release: "{player} 把 {name} 交还给了模型",
        lapse: "{player} 离开了，{name} 交还给模型" }[row.event];
      text = tf(key, fallback, { player: row.player, name: nameOf(row.agent_id) });
      refresh();
    }
    var feed = $("pFeed");
    if (feedEmpty) { feed.innerHTML = ""; feedEmpty = false; }
    var line = document.createElement("p");
    var when = document.createElement("time");
    when.textContent = row._day != null ? "D" + row._day + " " + (row._time || "") : new Date().toLocaleTimeString();
    line.appendChild(when);
    line.appendChild(document.createTextNode(text));
    feed.insertBefore(line, feed.firstChild);
  }

  function listen() {
    var source = new EventSource("/api/events/stream?tables=" + encodeURIComponent(TABLES));
    TABLES.split(",").forEach(function (table) {
      source.addEventListener(table, function (event) {
        try { addFeed(JSON.parse(event.data), table); } catch (e) { /* a malformed row is skipped */ }
      });
    });
  }

  $("pSearch").addEventListener("input", render);
  $("pActForm").addEventListener("submit", function (event) {
    event.preventDefault();
    api("POST", "/api/play/act", { text: $("pAct").value }).then(function () {
      $("pAct").value = "";
      status(t("play.sent", "已送出，下一个 tick 生效"));
    }, function (err) { status(err.message, true); });
  });
  $("pSayForm").addEventListener("submit", function (event) {
    event.preventDefault();
    api("POST", "/api/play/say", { target_id: Number($("pSayTo").value), text: $("pSay").value }).then(function () {
      $("pSay").value = "";
      status(t("play.sent", "已送出，下一个 tick 生效"));
    }, function (err) { status(err.message, true); });
  });
  $("pRelease").addEventListener("click", function () {
    api("POST", "/api/play/release", {}).then(refresh, function (err) { status(err.message, true); });
  });
  // Closing the tab lets go at once instead of after the lease runs out.
  window.addEventListener("pagehide", function () {
    if (play && play.mine != null && navigator.sendBeacon) {
      navigator.sendBeacon("/api/play/release", new Blob(["{}"], { type: "application/json" }));
    }
  });
  // A phone pauses timers while the browser is in the background: renew the
  // lease (and catch up) as soon as the page is visible again.
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      heartbeat();
      refresh();
    }
  });
  document.addEventListener("locale-changed", render);

  api("GET", "/api/agents").then(function (data) {
    residents = (Array.isArray(data) ? data : data.agents || []).map(function (r) { return { id: r.id, name: r.name }; });
  }).catch(function () { residents = []; }).then(function () {
    return refresh();
  }).then(function () {
    if (play) listen();
    setInterval(heartbeat, HEARTBEAT_MS);
    setInterval(refresh, REFRESH_MS);
  });
})();
