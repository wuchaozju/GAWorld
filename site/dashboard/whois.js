// 谁是真人 (Who's Human) — front-end controller.
//
//   GET  /api/games/whois/catalogue              topics + seat limits
//   POST /api/games/whois/rooms                  open a room (host)
//   GET  /api/games/whois/rooms                  rooms this host opened
//   GET  /api/games/whois/rooms/<id>[?seat=tok]  host view, or one seat's view
//   POST /api/games/whois/rooms/<id>/say|vote    a person's message / ballot
//   POST /api/games/whois/rooms/<id>/next|reveal host stops waiting
//
// One page, two modes. Without ?seat= it is the host's panel: who is who,
// who has written, the seat links to hand out. With ?seat= it is a player's
// seat, which by design shows nothing about the others but their messages —
// not who has written, not who has voted, not how many people are present.

(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
  const t = (key, fallback) => {
    const value = typeof __ === "function" ? __(key) : "";
    return !value || value === key ? fallback : value;
  };
  const API = "/api/games/whois";
  const CUSTOM = "__custom__";

  const params = new URLSearchParams(location.search);
  const state = {
    roomId: params.get("room") || "",
    seat: params.get("seat") || "",
    view: null,
    topics: [],
    timer: null,
  };

  async function call(method, path, body) {
    const resp = await fetch(API + path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || resp.statusText);
    return data;
  }

  function showError(err) {
    const box = $("#wError");
    box.hidden = !err;
    box.textContent = err ? String(err.message || err) : "";
  }

  // -- host setup ----------------------------------------------------------
  async function loadCities() {
    const sel = $("#wCity");
    try {
      const data = await (await fetch("/api/city/catalogue")).json();
      const cities = data.cities || [];
      sel.innerHTML = cities
        .map((c) => `<option value="${esc(c.slug)}">${esc(c.display_name || c.name || c.slug)}</option>`)
        .join("");
      const preferred = data.selected != null ? data.selected : (cities[0] && cities[0].slug);
      if (preferred != null) sel.value = preferred;
    } catch (err) {
      sel.innerHTML = `<option value="">${esc(String(err))}</option>`;
    }
  }

  async function loadCatalogue() {
    const data = await call("GET", "/catalogue");
    state.topics = data.topics || [];
    $("#wTopic").innerHTML = state.topics
      .map((topic) => `<option value="${esc(topic.id)}">${esc(topic.emoji + " " + topic.title)}</option>`)
      .join("") + `<option value="${CUSTOM}">✍️ ${esc(t("whois.custom_option", "自己写一个…"))}</option>`;
  }

  async function loadRooms() {
    const list = $("#wRooms");
    try {
      const data = await call("GET", "/rooms");
      list.innerHTML = (data.rooms || []).map((room) => `
        <li><button type="button" data-room="${esc(room.id)}">
          <span class="who">${esc(room.topic)}</span>
          <span class="meta">${esc(statusText(room.status))} · ${esc(room.seats)} ${esc(t("whois.seats_suffix", "个座位"))}</span>
        </button></li>`).join("") || `<li class="disaster-empty">${esc(t("whois.no_rooms", "还没开过"))}</li>`;
    } catch (err) {
      list.innerHTML = `<li class="disaster-empty is-error">${esc(String(err.message || err))}</li>`;
    }
  }

  async function createRoom() {
    showError(null);
    const topic = $("#wTopic").value;
    const payload = {
      city: $("#wCity").value,
      agents: Number($("#wAgents").value),
      humans: Number($("#wHumans").value),
      rounds: Number($("#wRounds").value),
    };
    if (topic === CUSTOM) payload.custom = { text: $("#wCustom").value };
    else payload.topic_id = topic;
    try {
      const view = await call("POST", "/rooms", payload);
      state.roomId = view.id;
      history.replaceState(null, "", "?room=" + encodeURIComponent(view.id));
      render(view);
      poll();
      loadRooms();
    } catch (err) {
      showError(err);
    }
  }

  // -- rendering -----------------------------------------------------------
  function statusText(status) {
    return {
      chatting: t("whois.status_chatting", "聊天中"),
      guessing: t("whois.status_guessing", "猜真人中"),
      revealed: t("whois.status_revealed", "已揭晓"),
    }[status] || status;
  }

  function seatLink(token) {
    return `${location.origin}${location.pathname}?room=${encodeURIComponent(state.roomId)}&seat=${encodeURIComponent(token)}`;
  }

  function who(card) {
    if (!card.kind) return "";
    if (card.kind === "human") return t("whois.is_human", "真人");
    const a = card.agent || {};
    return `${t("whois.is_resident", "居民")} · ${a.name || ""}${a.job ? "（" + a.job + "）" : ""}`;
  }

  function render(view) {
    state.view = view;
    $("#wIdle").hidden = true;
    $("#wTitle").textContent = `${(view.topic || {}).emoji || ""} ${(view.topic || {}).text || ""}`;
    const roundText = view.status === "chatting"
      ? " · " + t("whois.round_of", "第 {n}/{total} 轮").replace("{n}", view.round).replace("{total}", view.rounds_total)
      : "";
    $("#wStatus").textContent = statusText(view.status) + roundText;

    const host = !!view.host;
    $("#wHostActions").hidden = !host || view.status === "revealed";
    $("#wNext").hidden = view.status !== "chatting";
    $("#wReveal").hidden = view.status !== "guessing";
    renderSeats(view, host);
    renderChat(view);
    renderCompose(view);
    renderBallot(view);
    renderResults(view);
  }

  function renderSeats(view, host) {
    const box = $("#wLinks");
    box.hidden = !host;
    if (!host) return;
    $("#wSeats").innerHTML = view.seats.map((card) => {
      const flags = view.status === "chatting"
        ? (card.posted ? "✓ " + t("whois.posted", "已发") : "…")
        : view.status === "guessing" && card.kind === "human"
          ? (card.voted ? "✓ " + t("whois.voted", "已猜") : "…")
          : "";
      const link = card.token
        ? `<input class="whois-link" readonly value="${esc(seatLink(card.token))}" />
           <button type="button" class="button" data-copy="${esc(seatLink(card.token))}">${esc(t("whois.copy", "复制链接"))}</button>`
        : "";
      return `<li><b>${esc(card.alias)}</b> <span class="muted">${esc(who(card))}</span>
        <span class="whois-flag">${esc(flags)}</span>${link}</li>`;
    }).join("");
  }

  function renderChat(view) {
    const box = $("#wChat");
    const mine = view.me && view.me.alias;
    box.hidden = false;
    const rounds = (view.transcript || []).map((record) => `
      <div class="whois-round">
        <p class="whois-round-head">${esc(t("whois.round_n", "第 {n} 轮").replace("{n}", record.round + 1))}</p>
        ${record.messages.map((m) => `
          <div class="whois-msg${m.alias === mine ? " is-me" : ""}">
            <span class="whois-alias">${esc(m.alias)}</span><span class="whois-text">${esc(m.text)}</span>
          </div>`).join("")}
      </div>`).join("");
    box.innerHTML = rounds || `<p class="disaster-hint">${esc(t("whois.no_messages", "还没有人说话。这一轮大家同时写，写完一起出现。"))}</p>`;
  }

  function renderCompose(view) {
    const me = view.me;
    const box = $("#wCompose");
    box.hidden = !(me && view.status === "chatting");
    if (box.hidden) return;
    const posted = me.posted;
    $("#wText").hidden = posted;
    $("#wSay").hidden = posted;
    let note = $("#wComposeNote");
    if (!note) {
      note = document.createElement("p");
      note.id = "wComposeNote";
      note.className = "disaster-hint";
      box.appendChild(note);
    }
    note.textContent = posted
      ? `${t("whois.waiting", "已发出，等这一轮其他人写完：")}「${me.my_message || ""}」`
      : `${t("whois.you_are", "你是")} ${me.alias}`;
  }

  function renderBallot(view) {
    const me = view.me;
    const box = $("#wBallot");
    box.hidden = !(me && view.status === "guessing");
    if (box.hidden) return;
    if (me.voted) {
      $("#wBallotRows").innerHTML = `<li class="disaster-hint">${esc(t("whois.voted_wait", "已提交，等揭晓。"))}</li>`;
      $("#wReason").hidden = true;
      $("#wVote").hidden = true;
      return;
    }
    if ($("#wBallotRows").dataset.room === view.id) return; // keep the half-filled ballot
    $("#wBallotRows").dataset.room = view.id;
    $("#wBallotRows").innerHTML = view.seats.filter((card) => card.alias !== me.alias).map((card) => `
      <li><b>${esc(card.alias)}</b>
        <label><input type="radio" name="v-${esc(card.alias)}" value="human" /> ${esc(t("whois.is_human", "真人"))}</label>
        <label><input type="radio" name="v-${esc(card.alias)}" value="resident" /> ${esc(t("whois.is_resident", "居民"))}</label>
      </li>`).join("");
  }

  function renderResults(view) {
    const box = $("#wResults");
    box.hidden = view.status !== "revealed";
    if (box.hidden) return;
    const res = view.results || {};
    const bySeat = Object.fromEntries((res.seats || []).map((s) => [s.alias, s]));
    const mine = view.me && (res.judges || []).find((j) => j.alias === view.me.alias);
    const rows = view.seats.map((card) => {
      const s = bySeat[card.alias] || {};
      return `<li class="${card.kind === "human" ? "is-human" : "is-resident"}">
        <b>${esc(card.alias)}</b> ${esc(who(card))}
        <span class="muted">${esc(t("whois.judged_human", "被判为真人"))} ${s.judged_human || 0}/${s.judgments || 0}</span></li>`;
    }).join("");
    const accuracy = res.accuracy == null ? "—" : Math.round(res.accuracy * 100) + "%";
    box.innerHTML = `
      <h4>${esc(t("whois.reveal_title", "揭晓"))}</h4>
      ${mine ? `<p class="whois-mine">${esc(t("whois.your_score", "你猜对了"))} ${mine.correct}/${mine.total}</p>` : ""}
      <ul class="whois-reveal">${rows}</ul>
      <p class="disaster-hint">${esc(t("whois.overall", "全场判断准确率"))} ${accuracy} ·
        ${esc(t("whois.resident_rate", "居民被当成真人"))} ${res.resident_judged_human || 0}/${res.resident_judgments || 0} ·
        ${esc(t("whois.human_rate", "真人被认出"))} ${res.human_judged_human || 0}/${res.human_judgments || 0}</p>`;
  }

  // -- actions -------------------------------------------------------------
  async function refresh() {
    if (!state.roomId) return;
    try {
      const query = state.seat ? "?seat=" + encodeURIComponent(state.seat) : "";
      render(await call("GET", "/rooms/" + encodeURIComponent(state.roomId) + query));
      showError(null);
    } catch (err) {
      showError(err);
    }
  }

  function poll() {
    clearInterval(state.timer);
    state.timer = setInterval(() => {
      if (state.view && state.view.status === "revealed") clearInterval(state.timer);
      else refresh();
    }, 2000);
  }

  async function post(action, body) {
    showError(null);
    try {
      render(await call("POST", `/rooms/${encodeURIComponent(state.roomId)}/${action}`, body));
    } catch (err) {
      showError(err);
    }
  }

  function say() {
    const text = $("#wText").value.trim();
    if (!text) return;
    post("say", { seat: state.seat, text }).then(() => { $("#wText").value = ""; });
  }

  function vote() {
    const verdicts = {};
    for (const card of state.view.seats) {
      const picked = document.querySelector(`input[name="v-${CSS.escape(card.alias)}"]:checked`);
      if (picked) verdicts[card.alias] = picked.value;
    }
    post("vote", { seat: state.seat, verdicts, reason: $("#wReason").value });
  }

  async function init() {
    $("#wSay").addEventListener("click", say);
    $("#wVote").addEventListener("click", vote);
    $("#wNext").addEventListener("click", () => post("next"));
    $("#wReveal").addEventListener("click", () => post("reveal"));
    $("#wSeats").addEventListener("click", (event) => {
      const button = event.target.closest("[data-copy]");
      if (button && navigator.clipboard) navigator.clipboard.writeText(button.dataset.copy);
    });
    if (state.seat) {
      // A player's seat: no setup, no host controls.
      $("#wSetup").hidden = true;
      document.querySelector(".disaster-grid").classList.add("is-single");
    } else {
      $("#wCreate").addEventListener("click", createRoom);
      $("#wTopic").addEventListener("change", () => { $("#wCustomBlock").hidden = $("#wTopic").value !== CUSTOM; });
      $("#wRooms").addEventListener("click", (event) => {
        const button = event.target.closest("[data-room]");
        if (!button) return;
        state.roomId = button.dataset.room;
        history.replaceState(null, "", "?room=" + encodeURIComponent(state.roomId));
        refresh().then(poll);
      });
      await Promise.all([loadCities(), loadCatalogue().catch(showError)]);
      loadRooms();
    }
    if (state.roomId) {
      await refresh();
      poll();
    }
  }

  if (typeof window !== "undefined" && document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
