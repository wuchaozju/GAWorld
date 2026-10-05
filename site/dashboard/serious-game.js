/* 研究工作台 · 严肃游戏 — 一段描述 → 一个可以开玩的回合制情景推演。
 *
 * 也管页面顶部的三个 Tab（实施方案 / 严肃游戏 / 政策仿真与优化），当前 Tab 记在 ?tab= 里。
 *
 * 三种视图：
 *   - 设计：描述 → POST /api/research/games/design（后台任务）→ 游戏设计 + 座位配置；
 *   - 主持（?session=<id>）：研究者自己的面板，看得到所有角色的私密信息和居民的心里话，
 *     发真人座位链接，可以「不等了，结算本轮」；
 *   - 玩家（?session=<id>&seat=<token>）：真人在自己的浏览器里只看到自己的角色，
 *     设计面板和侧栏都藏起来。
 * 对局没结束就每 2 秒轮询一次，居民行动、主持裁定都在服务器后台进行。
 */
(function () {
  "use strict";

  var POLL_MS = 2000;
  var JOB_POLL_MS = 1500;

  function t(key, fallback) {
    if (typeof window.__ !== "function") return fallback;
    var value = window.__("research." + key);
    return value && value !== "research." + key ? value : fallback;
  }

  function tf(key, fallback, params) {
    var text = t(key, fallback);
    Object.keys(params || {}).forEach(function (name) {
      text = text.split("{" + name + "}").join(String(params[name]));
    });
    return text;
  }

  function $(id) {
    return document.getElementById(id);
  }

  function esc(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function api(method, path, body) {
    return fetch(path, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    })
      .then(function (res) {
        return res
          .json()
          .catch(function () {
            throw new Error("HTTP " + res.status);
          })
          .then(function (data) {
            if (!res.ok) throw new Error((data && data.error) || "HTTP " + res.status);
            return data;
          });
      })
      .catch(function (err) {
        if (err instanceof TypeError) {
          throw new Error(tf("no_backend", "连不上后端：{error}", { error: err.message }));
        }
        throw err;
      });
  }

  var state = {
    providers: [],
    cities: [],
    residents: {},
    games: [],
    sessions: [],
    game: null,
    session: null,
    seat: "",
    pollTimer: null,
    busy: false,
  };

  /* ------------------------------------------------------------------ tabs */

  function params() {
    return new URLSearchParams(window.location.search);
  }

  function setUrl(updates) {
    var query = params();
    Object.keys(updates).forEach(function (key) {
      if (updates[key]) query.set(key, updates[key]);
      else query.delete(key);
    });
    var text = query.toString();
    window.history.replaceState(null, "", window.location.pathname + (text ? "?" + text : ""));
  }

  /* Each tab names its pane through aria-controls, so a new tab needs no
     change here. */
  function showTab(name) {
    document.querySelectorAll(".rw-tab").forEach(function (tab) {
      var on = tab.getAttribute("data-tab") === name;
      tab.classList.toggle("is-active", on);
      tab.setAttribute("aria-selected", on ? "true" : "false");
      var pane = $(tab.getAttribute("aria-controls"));
      if (pane) pane.hidden = !on;
    });
    setUrl({ tab: name === "plan" ? "" : name, run: name === "policy" ? params().get("run") : "" });
  }

  /* ----------------------------------------------------------------- setup */

  function fillSelect(select, values, autoLabel) {
    select.innerHTML =
      '<option value="0">' + esc(autoLabel) + "</option>" +
      values.map(function (n) {
        return '<option value="' + n + '">' + n + "</option>";
      }).join("");
  }

  function fillProviders() {
    var select = $("sgProvider");
    var previous = select.value;
    select.innerHTML =
      '<option value="">' + esc(t("route_by_config", "按配置路由（默认模型）")) + "</option>" +
      state.providers.map(function (p) {
        return (
          '<option value="' + esc(p.name) + '">' +
          esc(p.name + (p.model ? " · " + p.model : "") + (p.is_default ? " ★" : "")) +
          "</option>"
        );
      }).join("");
    select.value = previous;
  }

  function setProgress(text, mode) {
    var el = $("sgProgress");
    el.textContent = text || "";
    el.classList.toggle("is-error", mode === "error");
    el.classList.toggle("is-live", mode === "live");
  }

  function loadCities() {
    return api("GET", "/api/city/catalogue")
      .then(function (data) {
        state.cities = data.cities || [];
        state.defaultCity = data.selected != null ? data.selected : "";
      })
      .catch(function () {
        state.cities = [];
      });
  }

  function loadResidents(city) {
    if (state.residents[city]) return Promise.resolve(state.residents[city]);
    return api("GET", "/api/city/agents?limit=2000&city=" + encodeURIComponent(city || ""))
      .then(function (data) {
        state.residents[city] = data.agents || [];
        return state.residents[city];
      })
      .catch(function () {
        return [];
      });
  }

  function refreshLists() {
    return api("GET", "/api/research/games").then(function (data) {
      state.games = data.games || [];
      state.sessions = data.sessions || [];
      renderLists();
    });
  }

  /* ---------------------------------------------------------------- design */

  function design() {
    var description = $("sgDesc").value.trim();
    if (!description) {
      setProgress(t("sg_need_desc", "先写一段游戏描述"), "error");
      return;
    }
    state.busy = true;
    $("sgDesign").disabled = true;
    setProgress(t("sg_designing", "正在设计游戏…（一次模型调用，本地模型可能要一两分钟）"), "live");
    api("POST", "/api/research/games/design", {
      description: description,
      rounds: Number($("sgRounds").value) || 0,
      roles: Number($("sgRoles").value) || 0,
      provider: $("sgProvider").value,
    })
      .then(function (data) {
        pollJob(data.job_id);
      })
      .catch(function (err) {
        doneDesign(err.message, "error");
      });
  }

  function doneDesign(text, mode) {
    state.busy = false;
    $("sgDesign").disabled = false;
    setProgress(text, mode);
  }

  function pollJob(jobId) {
    api("GET", "/api/research/games/jobs/" + encodeURIComponent(jobId))
      .then(function (job) {
        if (job.status === "running") {
          setTimeout(function () {
            pollJob(jobId);
          }, JOB_POLL_MS);
          return;
        }
        if (job.status !== "done") {
          doneDesign(job.error || t("sg_failed", "设计失败"), "error");
          return;
        }
        doneDesign(t("sg_designed", "游戏设计好了，看一下再开局。"), "");
        openGame(job.result.game_id);
        refreshLists();
      })
      .catch(function (err) {
        doneDesign(err.message, "error");
      });
  }

  function openGame(gameId) {
    stopPolling();
    state.session = null;
    $("sgSession").hidden = true;
    setUrl({ session: "", seat: "" });
    return api("GET", "/api/research/games/" + encodeURIComponent(gameId))
      .then(function (game) {
        state.game = game;
        renderGame();
        renderLists();
      })
      .catch(function (err) {
        setProgress(err.message, "error");
      });
  }

  function list(items) {
    if (!items || !items.length) return "";
    return '<ul class="rw-list">' + items.map(function (i) {
      return "<li>" + esc(i) + "</li>";
    }).join("") + "</ul>";
  }

  function cityOptions(selected) {
    var options = ['<option value="">' + esc(t("sg_default_world", "默认世界")) + "</option>"];
    state.cities.forEach(function (c) {
      options.push(
        '<option value="' + esc(c.slug) + '"' + (c.slug === selected ? " selected" : "") + ">" +
        esc(c.display_name || c.name || c.slug) + "</option>"
      );
    });
    return options.join("");
  }

  function renderGame() {
    var host = $("sgGame");
    var game = state.game;
    if (!game) {
      host.hidden = true;
      return;
    }
    var spec = game.spec;
    var roleRows = spec.roles.map(function (r) {
      return (
        "<tr><td><b>" + esc(r.name) + "</b></td><td>" + esc(r.public) + "</td><td>" + esc(r.goal) +
        '</td><td class="sg-private">' + esc(r.private) + "</td></tr>"
      );
    }).join("");
    var indicators = spec.indicators.map(function (i) {
      return "<li><b>" + esc(i.name) + "</b> · " + i.initial + "（" + i.min + "–" + i.max + "）" + esc(i.description) + "</li>";
    }).join("");
    var rounds = spec.rounds.map(function (r) {
      return (
        '<li class="rw-step"><div class="rw-step-title">' + esc(r.title) + '</div><p class="rw-step-detail">' +
        esc(r.event) + "<br><i>" + esc(r.prompt) + "</i>" +
        (r.options.length ? "<br>" + r.options.map(function (o) {
          return '<span class="rw-badge">' + esc(o) + "</span>";
        }).join(" ") : "") + "</p></li>"
      );
    }).join("");
    var seats = spec.roles.map(function (r) {
      return (
        '<div class="sg-seat" data-role="' + esc(r.id) + '">' +
        '<div class="sg-seat-role"><b>' + esc(r.name) + "</b>" +
        (r.suggested_player ? '<span class="rw-hint">' + esc(tf("sg_suggest", "适合：{who}", { who: r.suggested_player })) + "</span>" : "") +
        "</div>" +
        '<div class="sg-seat-kind">' +
        '<label><input type="radio" name="sgKind-' + esc(r.id) + '" value="agent" checked /> ' + esc(t("sg_kind_agent", "居民智能体")) + "</label>" +
        '<label><input type="radio" name="sgKind-' + esc(r.id) + '" value="human" /> ' + esc(t("sg_kind_human", "真人")) + "</label>" +
        "</div>" +
        '<select class="sg-seat-agent"><option value="">' + esc(t("sg_random_resident", "随机居民")) + "</option></select>" +
        '<input class="sg-seat-name" type="text" hidden placeholder="' + esc(t("sg_player_name", "玩家称呼（可选）")) + '" />' +
        "</div>"
      );
    }).join("");

    host.innerHTML =
      '<div class="rw-result-head"><div><h3>' + esc(spec.title) + "</h3>" +
      '<div class="rw-badges"><span class="rw-badge">' + esc(tf("sg_n_roles", "{n} 个角色", { n: spec.roles.length })) +
      '</span><span class="rw-badge">' + esc(tf("sg_n_rounds", "{n} 轮", { n: spec.rounds.length })) + "</span></div></div>" +
      '<div class="rw-actions"><button class="btn ghost tiny" id="sgDeleteGame">' + esc(t("delete", "删除")) + "</button></div></div>" +
      '<p class="rw-summary">' + esc(spec.summary) + "</p>" +
      "<h4>" + esc(t("sg_setting", "背景")) + '</h4><p class="rw-rationale">' + esc(spec.setting) + "</p>" +
      (spec.learning_objectives.length ? "<h4>" + esc(t("sg_objectives", "学习目标")) + "</h4>" + list(spec.learning_objectives) : "") +
      "<h4>" + esc(t("sg_roles", "角色")) + '</h4><table class="rw-table"><thead><tr><th>' + esc(t("sg_role", "角色")) +
      "</th><th>" + esc(t("sg_public", "公开身份")) + "</th><th>" + esc(t("sg_goal", "目标")) + "</th><th>" +
      esc(t("sg_private", "私密信息")) + "</th></tr></thead><tbody>" + roleRows + "</tbody></table>" +
      (indicators ? "<h4>" + esc(t("sg_indicators", "公共指标")) + '</h4><ul class="rw-list">' + indicators + "</ul>" : "") +
      "<h4>" + esc(t("sg_rounds", "回合")) + '</h4><ol class="rw-steps">' + rounds + "</ol>" +
      "<h4>" + esc(t("sg_scoring", "评分维度")) + "</h4>" + list(spec.scoring.map(function (c) {
        return c.criterion + (c.description ? "：" + c.description : "");
      })) +
      (spec.debrief_questions.length ? "<h4>" + esc(t("sg_debrief_q", "复盘问题")) + "</h4>" + list(spec.debrief_questions) : "") +
      '<div class="sg-setup"><h4>' + esc(t("sg_setup", "2 · 安排座位，开一局")) + "</h4>" +
      '<p class="rw-hint">' + esc(t("sg_setup_hint", "每个角色选由谁来玩：居民智能体按自己的档案演这个角色；真人座位会生成一个链接，发给参与者在自己的浏览器里打开。")) + "</p>" +
      '<div class="rw-row"><label class="rw-field rw-field-model"><span>' + esc(t("sg_city", "居民来自")) +
      '</span><select id="sgCity">' + cityOptions(state.defaultCity || "") + "</select></label></div>" +
      '<div class="sg-seats">' + seats + "</div>" +
      '<div class="rw-row"><button class="btn" id="sgStart">' + esc(t("sg_start", "开始对局")) + "</button></div>" +
      '<p class="rw-progress" id="sgStartProgress"></p></div>';
    host.hidden = false;

    $("sgDeleteGame").addEventListener("click", deleteGame);
    $("sgStart").addEventListener("click", startSession);
    $("sgCity").addEventListener("change", fillResidentPickers);
    host.querySelectorAll(".sg-seat").forEach(function (row) {
      row.querySelectorAll("input[type=radio]").forEach(function (radio) {
        radio.addEventListener("change", function () {
          var human = row.querySelector("input[type=radio]:checked").value === "human";
          row.querySelector(".sg-seat-agent").hidden = human;
          row.querySelector(".sg-seat-name").hidden = !human;
        });
      });
    });
    fillResidentPickers();
  }

  function fillResidentPickers() {
    var city = $("sgCity").value;
    loadResidents(city).then(function (people) {
      var options = '<option value="">' + esc(t("sg_random_resident", "随机居民")) + "</option>" +
        people.map(function (p) {
          return '<option value="' + p.id + '">#' + p.id + " " + esc(p.name) + " · " + esc(p.age) + " · " + esc(p.job || "") + "</option>";
        }).join("");
      document.querySelectorAll(".sg-seat-agent").forEach(function (select) {
        select.innerHTML = options;
      });
    });
  }

  function deleteGame() {
    if (!state.game || !window.confirm(t("sg_confirm_delete_game", "删除这个游戏设计？已经开过的对局会保留。"))) return;
    api("POST", "/api/research/games/" + encodeURIComponent(state.game.id) + "/delete", {})
      .then(function () {
        state.game = null;
        renderGame();
        refreshLists();
      })
      .catch(function (err) {
        setProgress(err.message, "error");
      });
  }

  function startSession() {
    var seats = [];
    document.querySelectorAll(".sg-seat").forEach(function (row) {
      var kind = row.querySelector("input[type=radio]:checked").value;
      seats.push({
        role_id: row.getAttribute("data-role"),
        kind: kind,
        agent_id: kind === "agent" ? row.querySelector(".sg-seat-agent").value : "",
        player_name: kind === "human" ? row.querySelector(".sg-seat-name").value : "",
      });
    });
    var button = $("sgStart");
    button.disabled = true;
    $("sgStartProgress").textContent = t("sg_starting", "正在入座…");
    api("POST", "/api/research/games/sessions", {
      game_id: state.game.id,
      seats: seats,
      city: $("sgCity").value,
      provider: $("sgProvider").value,
    })
      .then(function (session) {
        button.disabled = false;
        $("sgStartProgress").textContent = "";
        refreshLists();
        openSession(session.id, "");
      })
      .catch(function (err) {
        button.disabled = false;
        $("sgStartProgress").textContent = err.message;
      });
  }

  /* --------------------------------------------------------------- session */

  function stopPolling() {
    if (state.pollTimer) clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }

  function openSession(sessionId, seat) {
    stopPolling();
    state.seat = seat || "";
    setUrl({ tab: "game", session: sessionId, seat: state.seat });
    if (!seat) {
      state.game = null;
      $("sgGame").hidden = true;
    }
    return fetchSession(sessionId);
  }

  function fetchSession(sessionId) {
    var path = "/api/research/games/sessions/" + encodeURIComponent(sessionId) +
      (state.seat ? "?seat=" + encodeURIComponent(state.seat) : "");
    return api("GET", path)
      .then(function (session) {
        var changed = !state.session || state.session.updated_at !== session.updated_at ||
          state.session.status !== session.status || state.session.id !== session.id;
        state.session = session;
        if (changed) renderSession();
        renderLists();
        if (session.status !== "finished" && session.status !== "failed") {
          state.pollTimer = setTimeout(function () {
            fetchSession(sessionId);
          }, POLL_MS);
        }
      })
      .catch(function (err) {
        var host = $("sgSession");
        host.hidden = false;
        host.innerHTML = '<p class="rw-progress is-error">' + esc(err.message) + "</p>";
      });
  }

  function statusLabel(session) {
    var waiting = session.seats.filter(function (s) {
      return !s.acted;
    });
    switch (session.status) {
      case "acting":
        if (waiting.some(function (s) { return s.kind === "agent"; })) return t("sg_st_agents", "居民正在思考…");
        return tf("sg_st_humans", "等待真人行动（还差 {n} 位）", { n: waiting.length });
      case "resolving":
        return t("sg_st_resolving", "主持人正在裁定本轮结果…");
      case "debriefing":
        return t("sg_st_debriefing", "正在复盘…");
      case "finished":
        return t("sg_st_finished", "对局结束");
      case "failed":
        return tf("sg_st_failed", "出错了：{error}", { error: session.error || "" });
      default:
        return session.status;
    }
  }

  function roleName(session, roleId) {
    var role = session.roles.filter(function (r) {
      return r.id === roleId;
    })[0];
    return role ? role.name : roleId;
  }

  function seatLink(token) {
    var url = new URL(window.location.href);
    url.search = "";
    url.searchParams.set("tab", "game");
    url.searchParams.set("session", state.session.id);
    url.searchParams.set("seat", token);
    return url.toString();
  }

  function indicatorBars(session) {
    if (!session.indicator_defs.length) return "";
    return '<div class="sg-indicators">' + session.indicator_defs.map(function (d) {
      var value = session.indicators[d.id];
      var pct = d.max > d.min ? Math.round(((value - d.min) / (d.max - d.min)) * 100) : 0;
      return (
        '<div class="sg-ind" title="' + esc(d.description) + '"><div class="sg-ind-head"><span>' + esc(d.name) +
        "</span><b>" + esc(value) + '</b></div><div class="sg-ind-bar"><i style="width:' + pct + '%"></i></div></div>'
      );
    }).join("") + "</div>";
  }

  function seatsBlock(session) {
    var rows = session.seats.map(function (s) {
      var who = s.kind === "human"
        ? '<span class="rw-badge sg-human">' + esc(t("sg_kind_human", "真人")) + "</span> " + esc(s.player_name)
        : '<span class="rw-badge">' + esc(t("sg_kind_agent", "居民智能体")) + "</span> " +
          esc(s.agent ? "#" + s.agent.agent_id + " " + s.agent.name + " · " + s.agent.age + " · " + (s.agent.job || "") : s.player_name);
      var mark = session.status === "acting" ? (s.acted ? "✓" : "…") : "";
      var link = session.host && s.kind === "human" && s.token
        ? ' <button class="btn ghost tiny sg-copy" data-link="' + esc(seatLink(s.token)) + '">' + esc(t("sg_copy_link", "复制座位链接")) +
          '</button> <a class="btn ghost tiny" target="_blank" rel="noopener" href="' + esc(seatLink(s.token)) + '">' + esc(t("sg_open_seat", "以该角色进入")) + "</a>"
        : "";
      return "<tr><td><b>" + esc(roleName(session, s.role_id)) + "</b></td><td>" + who + link + '</td><td class="sg-mark">' + mark + "</td></tr>";
    }).join("");
    return '<table class="rw-table sg-seat-table"><tbody>' + rows + "</tbody></table>";
  }

  function actionLine(session, roleId, move, showThought) {
    return (
      "<li><b>" + esc(roleName(session, roleId)) + "</b>：" +
      (move.choice ? '<span class="rw-badge">' + esc(move.choice) + "</span> " : "") + esc(move.action) +
      (showThought && move.thought ? '<div class="sg-thought">💭 ' + esc(move.thought) + "</div>" : "") + "</li>"
    );
  }

  function historyBlock(session) {
    var names = {};
    session.indicator_defs.forEach(function (d) {
      names[d.id] = d.name;
    });
    return session.rounds.slice().reverse().map(function (r) {
      var moved = Object.keys(r.indicator_changes || {}).filter(function (k) {
        return r.indicator_changes[k];
      }).map(function (k) {
        var v = r.indicator_changes[k];
        return '<span class="rw-badge ' + (v > 0 ? "sg-up" : "sg-down") + '">' + esc(names[k] || k) + " " + (v > 0 ? "+" : "") + v + "</span>";
      }).join(" ");
      var outcomes = Object.keys(r.role_outcomes || {}).filter(function (k) {
        return r.role_outcomes[k];
      }).map(function (k) {
        return "<li><b>" + esc(roleName(session, k)) + "</b>：" + esc(r.role_outcomes[k]) + "</li>";
      }).join("");
      return (
        '<div class="sg-round"><div class="rw-step-title">' + esc(r.title) + "</div>" +
        '<p class="rw-hint">' + esc(r.event) + "</p>" +
        '<ul class="rw-list">' + Object.keys(r.actions).map(function (k) {
          return actionLine(session, k, r.actions[k], session.host);
        }).join("") + "</ul>" +
        '<p class="sg-narration">' + esc(r.narration) + "</p>" + (moved ? "<p>" + moved + "</p>" : "") +
        (outcomes ? '<details><summary class="rw-hint">' + esc(t("sg_outcomes", "各方得失")) + '</summary><ul class="rw-list">' + outcomes + "</ul></details>" : "") +
        "</div>"
      );
    }).join("");
  }

  function currentBlock(session) {
    var round = session.current_round;
    if (!round) return "";
    var html =
      '<div class="sg-current"><div class="rw-step-title">' +
      esc(tf("sg_round_of", "第 {i} / {n} 轮 · {title}", { i: session.round_index + 1, n: session.round_count, title: round.title })) +
      '</div><p class="rw-step-detail">' + esc(round.event) + "</p><p><i>" + esc(round.prompt) + "</i></p>";
    var me = session.me;
    if (me && me.kind === "human") {
      if (me.acted) {
        html += '<p class="rw-hint">' + esc(t("sg_you_acted", "你这一轮已经行动了，等其他人。")) + "</p>" +
          (me.my_action ? '<ul class="rw-list">' + actionLine(session, me.role_id, me.my_action, false) + "</ul>" : "");
      } else {
        html +=
          (round.options.length ? '<div class="sg-options">' + round.options.map(function (o) {
            return '<label class="rw-kind-opt"><input type="radio" name="sgChoice" value="' + esc(o) + '" /><span>' + esc(o) + "</span></label>";
          }).join("") + "</div>" : "") +
          '<label class="rw-field"><span>' + esc(t("sg_your_action", "你的行动或发言")) + '</span><textarea id="sgAction" rows="4" placeholder="' +
          esc(t("sg_action_ph", "用第一人称写：你做了什么、说了什么。")) + '"></textarea></label>' +
          '<button class="btn" id="sgSubmit">' + esc(t("sg_submit", "提交本轮行动")) + '</button> <span class="rw-progress" id="sgActProgress"></span>';
      }
    }
    if (session.host && session.status === "acting") {
      var waitingHumans = session.seats.some(function (s) { return s.kind === "human" && !s.acted; });
      var agentsBusy = session.seats.some(function (s) { return s.kind === "agent" && !s.acted; });
      if (waitingHumans && !agentsBusy) {
        html += '<p><button class="btn ghost" id="sgForce">' + esc(t("sg_force", "不等了，结算本轮")) + "</button></p>";
      }
      var open = session.open_actions || {};
      if (Object.keys(open).length) {
        html += '<details><summary class="rw-hint">' + esc(t("sg_open_actions", "本轮已提交的行动（仅主持可见）")) + '</summary><ul class="rw-list">' +
          Object.keys(open).map(function (k) {
            return actionLine(session, k, open[k], true);
          }).join("") + "</ul></details>";
      }
    }
    return html + "</div>";
  }

  function debriefBlock(session) {
    var d = session.debrief;
    if (!d) return "";
    var criteria = session.scoring.map(function (c) {
      return c.criterion;
    });
    var scoreRows = d.scores.map(function (row) {
      return "<tr><td><b>" + esc(roleName(session, row.role_id)) + "</b></td>" + criteria.map(function (c) {
        return "<td>" + esc(row.scores[c]) + "</td>";
      }).join("") + "<td><b>" + row.total + "</b></td><td>" + esc(row.comment) + "</td></tr>";
    }).join("");
    var mark = { yes: "✅", partly: "◐", no: "✗" };
    return (
      '<div class="sg-debrief"><h4>' + esc(t("sg_debrief", "复盘")) + '</h4><p class="rw-summary">' + esc(d.summary) + "</p>" +
      (scoreRows ? '<table class="rw-table"><thead><tr><th>' + esc(t("sg_role", "角色")) + "</th>" + criteria.map(function (c) {
        return "<th>" + esc(c) + "</th>";
      }).join("") + "<th>" + esc(t("sg_total", "总分")) + "</th><th>" + esc(t("sg_basis", "依据")) + "</th></tr></thead><tbody>" + scoreRows + "</tbody></table>" : "") +
      (d.objectives.length ? "<h4>" + esc(t("sg_objectives", "学习目标")) + '</h4><ul class="rw-list">' + d.objectives.map(function (o) {
        return "<li>" + mark[o.met] + " <b>" + esc(o.objective) + "</b>：" + esc(o.evidence) + "</li>";
      }).join("") + "</ul>" : "") +
      d.answers.map(function (a) {
        return "<h4>" + esc(a.question) + '</h4><p class="rw-rationale">' + esc(a.answer) + "</p>";
      }).join("") +
      (d.insights.length ? "<h4>" + esc(t("sg_insights", "洞见")) + "</h4>" + list(d.insights) : "") +
      "</div>"
    );
  }

  function renderSession() {
    var session = state.session;
    var host = $("sgSession");
    if (!session) {
      host.hidden = true;
      return;
    }
    // Keep a half-typed action across re-renders triggered by polling.
    var draft = $("sgAction") ? $("sgAction").value : "";
    var me = session.me;
    var myRole = me ? session.roles.filter(function (r) { return r.id === me.role_id; })[0] : null;
    var live = session.status !== "finished" && session.status !== "failed";

    host.innerHTML =
      '<div class="rw-result-head"><div><h3>' + esc(session.title) + "</h3>" +
      '<div class="rw-badges"><span class="rw-badge ' + (live ? "is-live" : "") + '">' + esc(statusLabel(session)) + "</span></div></div>" +
      '<div class="rw-actions">' + (session.host
        ? '<button class="btn ghost tiny" id="sgExport">' + esc(t("download", "下载 Markdown")) + '</button><button class="btn ghost tiny danger" id="sgDeleteSession">' + esc(t("delete", "删除")) + "</button>"
        : "") + "</div></div>" +
      '<p class="rw-rationale">' + esc(session.setting) + "</p>" +
      (myRole
        ? '<div class="sg-brief"><div class="rw-step-title">' + esc(tf("sg_you_are", "你扮演：{name}", { name: myRole.name })) + '</div><dl class="rw-dl">' +
          "<dt>" + esc(t("sg_public", "公开身份")) + "</dt><dd>" + esc(myRole.public) + "</dd>" +
          "<dt>" + esc(t("sg_goal", "目标")) + "</dt><dd>" + esc(myRole.goal) + "</dd>" +
          "<dt>" + esc(t("sg_private", "私密信息")) + "</dt><dd>" + esc(myRole.private || "—") + "</dd></dl></div>"
        : "") +
      indicatorBars(session) +
      seatsBlock(session) +
      currentBlock(session) +
      debriefBlock(session) +
      (session.rounds.length ? "<h4>" + esc(t("sg_history", "回合记录")) + "</h4>" + historyBlock(session) : "");
    host.hidden = false;

    if ($("sgAction")) $("sgAction").value = draft;
    if ($("sgSubmit")) $("sgSubmit").addEventListener("click", submitAction);
    if ($("sgForce")) $("sgForce").addEventListener("click", forceResolve);
    if ($("sgExport")) $("sgExport").addEventListener("click", exportSession);
    if ($("sgDeleteSession")) $("sgDeleteSession").addEventListener("click", deleteSession);
    host.querySelectorAll(".sg-copy").forEach(function (button) {
      button.addEventListener("click", function () {
        var link = button.getAttribute("data-link");
        (navigator.clipboard ? navigator.clipboard.writeText(link) : Promise.reject())
          .then(function () {
            button.textContent = t("sg_copied", "已复制");
          })
          .catch(function () {
            window.prompt(t("sg_copy_link", "复制座位链接"), link);
          });
      });
    });
  }

  function submitAction() {
    var session = state.session;
    var checked = document.querySelector("input[name=sgChoice]:checked");
    var action = $("sgAction").value.trim();
    if (!action && !checked) {
      $("sgActProgress").textContent = t("sg_need_action", "写下你的行动，或选一个做法");
      return;
    }
    $("sgSubmit").disabled = true;
    api("POST", "/api/research/games/sessions/" + encodeURIComponent(session.id) + "/act", {
      seat: state.seat,
      action: action,
      choice: checked ? checked.value : "",
    })
      .then(function (data) {
        $("sgAction").value = "";
        state.session = data;
        renderSession();
      })
      .catch(function (err) {
        $("sgSubmit").disabled = false;
        $("sgActProgress").textContent = err.message;
      });
  }

  function forceResolve() {
    api("POST", "/api/research/games/sessions/" + encodeURIComponent(state.session.id) + "/resolve", {})
      .then(function (data) {
        state.session = data;
        renderSession();
      })
      .catch(function (err) {
        window.alert(err.message);
      });
  }

  function exportSession() {
    api("GET", "/api/research/games/sessions/" + encodeURIComponent(state.session.id) + "/export")
      .then(function (data) {
        var blob = new Blob([data.markdown], { type: "text/markdown;charset=utf-8" });
        var link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = data.filename;
        document.body.appendChild(link);
        link.click();
        setTimeout(function () {
          URL.revokeObjectURL(link.href);
          link.remove();
        }, 0);
      })
      .catch(function (err) {
        window.alert(err.message);
      });
  }

  function deleteSession() {
    if (!window.confirm(t("sg_confirm_delete_session", "删除这局对局记录？"))) return;
    api("POST", "/api/research/games/sessions/" + encodeURIComponent(state.session.id) + "/delete", {})
      .then(function () {
        stopPolling();
        state.session = null;
        renderSession();
        setUrl({ session: "", seat: "" });
        refreshLists();
      })
      .catch(function (err) {
        window.alert(err.message);
      });
  }

  /* ------------------------------------------------------------------ side */

  function renderLists() {
    var games = $("sgGames");
    games.innerHTML = state.games.length
      ? state.games.map(function (g) {
          var active = state.game && state.game.id === g.id ? " is-active" : "";
          return (
            '<button type="button" class="rw-history-item' + active + '" data-game="' + esc(g.id) + '"><span class="rw-hist-title">' +
            esc(g.title) + '</span><span class="rw-hist-meta">' + esc(tf("sg_game_meta", "{roles} 个角色 · {rounds} 轮", g)) + "</span></button>"
          );
        }).join("")
      : '<p class="rw-hint">' + esc(t("sg_no_games", "还没有游戏")) + "</p>";
    var sessions = $("sgSessions");
    sessions.innerHTML = state.sessions.length
      ? state.sessions.map(function (s) {
          var active = state.session && state.session.id === s.id ? " is-active" : "";
          var progress = s.status === "finished" ? t("sg_st_finished", "对局结束") : tf("sg_progress", "第 {i}/{n} 轮", { i: Math.min(s.round_index + 1, s.round_count), n: s.round_count });
          return (
            '<button type="button" class="rw-history-item' + active + '" data-session="' + esc(s.id) + '"><span class="rw-hist-title">' +
            esc(s.title) + '</span><span class="rw-hist-meta">' + esc(progress) + " · " +
            esc(tf("sg_seat_meta", "{agents} 居民 / {humans} 真人", s)) + "</span></button>"
          );
        }).join("")
      : '<p class="rw-hint">' + esc(t("sg_no_sessions", "还没有对局")) + "</p>";
  }

  /* ------------------------------------------------------------------ init */

  function init() {
    if (!$("rwPaneGame")) return;
    document.querySelectorAll(".rw-tab").forEach(function (tab) {
      tab.addEventListener("click", function () {
        showTab(tab.getAttribute("data-tab"));
      });
    });
    var range = [];
    for (var n = 2; n <= 8; n += 1) range.push(n);
    fillSelect($("sgRounds"), range, t("sg_auto", "自动"));
    fillSelect($("sgRoles"), range, t("sg_auto", "自动"));
    $("sgDesign").addEventListener("click", design);
    $("sgGames").addEventListener("click", function (event) {
      var item = event.target.closest("[data-game]");
      if (item) openGame(item.getAttribute("data-game"));
    });
    $("sgSessions").addEventListener("click", function (event) {
      var item = event.target.closest("[data-session]");
      if (item) openSession(item.getAttribute("data-session"), "");
    });
    document.addEventListener("locale-changed", function () {
      renderLists();
      renderGame();
      renderSession();
    });

    var query = params();
    var seat = query.get("seat") || "";
    var sessionId = query.get("session") || "";
    if (query.get("tab") === "game" || sessionId) showTab("game");
    else if (query.get("tab") === "policy" || query.get("tab") === "worlds") showTab(query.get("tab"));

    if (sessionId && seat) {
      // Player view: one role, nothing else on the page.
      document.body.classList.add("sg-player");
      openSession(sessionId, seat);
      return;
    }
    api("GET", "/api/research/context")
      .then(function (context) {
        state.providers = context.providers || [];
        fillProviders();
      })
      .catch(function () {
        fillProviders();
      });
    Promise.all([loadCities(), refreshLists()]).then(function () {
      if (sessionId) openSession(sessionId, "");
    }).catch(function (err) {
      setProgress(err.message, "error");
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
